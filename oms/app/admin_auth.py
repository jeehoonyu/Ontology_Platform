"""
Management & Enablement — authentication providers, API tokens / service accounts,
and third-party OAuth clients (deep-fidelity pass 12). Based on
/docs/foundry/authentication/*: identity-provider integrations (SAML/OIDC) with
attribute mapping, and tokens that are invalid while the owning user account is
inactive. Additive; deterministic; local (not real cryptography/OAuth).
"""
import time
import uuid
from typing import Optional, List, Any, Dict

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import String, Integer, Boolean, JSON
from sqlalchemy.orm import Mapped, mapped_column, Session
from pydantic import BaseModel, Field

from .database import Base, get_db
from . import models_action, admin_directory as _dir

router = APIRouter(tags=["admin_auth"])


def _now() -> int:
    return int(time.time())


class AuthProvider(Base):
    __tablename__ = "admin_auth_providers"
    id: Mapped[str] = mapped_column(String, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String)
    protocol: Mapped[str] = mapped_column(String)              # saml | oidc
    config: Mapped[dict] = mapped_column(JSON, default=dict)   # no secrets stored in clear
    attribute_mapping: Mapped[dict] = mapped_column(JSON, default=dict)  # idp_attr -> foundry_attr
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[int] = mapped_column(Integer)


class ServiceAccount(Base):
    __tablename__ = "admin_service_accounts"
    id: Mapped[str] = mapped_column(String, primary_key=True, index=True)
    display_name: Mapped[str] = mapped_column(String)
    organization_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    created_at: Mapped[int] = mapped_column(Integer)


class ApiToken(Base):
    __tablename__ = "admin_api_tokens"
    id: Mapped[str] = mapped_column(String, primary_key=True, index=True)
    token: Mapped[str] = mapped_column(String, index=True)
    principal_type: Mapped[str] = mapped_column(String, default="user")  # user | service_account
    principal_id: Mapped[str] = mapped_column(String, index=True)
    scopes: Mapped[list] = mapped_column(JSON, default=list)
    expires_at: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    revoked: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[int] = mapped_column(Integer)


class OAuthClient(Base):
    __tablename__ = "admin_oauth_clients"
    id: Mapped[str] = mapped_column(String, primary_key=True, index=True)
    display_name: Mapped[str] = mapped_column(String)
    client_id: Mapped[str] = mapped_column(String, index=True)
    scopes: Mapped[list] = mapped_column(JSON, default=list)
    redirect_uris: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[int] = mapped_column(Integer)


# ---------------------------------------------------------------------------
class ProviderCreate(BaseModel):
    id: Optional[str] = None
    name: str
    protocol: str = "saml"
    config: Dict[str, Any] = Field(default_factory=dict)
    attribute_mapping: Dict[str, str] = Field(default_factory=dict)


class MapAssertionRequest(BaseModel):
    assertion: Dict[str, Any]


class ServiceAccountCreate(BaseModel):
    id: Optional[str] = None
    display_name: str
    organization_id: Optional[str] = None


class TokenCreate(BaseModel):
    principal_type: str = "user"
    principal_id: str
    scopes: List[str] = Field(default_factory=list)
    ttl_seconds: Optional[int] = None


class TokenValidateRequest(BaseModel):
    token: str
    required_scope: Optional[str] = None


class OAuthClientCreate(BaseModel):
    id: Optional[str] = None
    display_name: str
    scopes: List[str] = Field(default_factory=list)
    redirect_uris: List[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Auth providers
# ---------------------------------------------------------------------------
@router.post("/admin/auth-providers", status_code=201)
def create_provider(body: ProviderCreate, db: Session = Depends(get_db)):
    if body.protocol not in ("saml", "oidc"):
        raise HTTPException(status_code=422, detail="protocol must be saml or oidc")
    pid = body.id or uuid.uuid4().hex
    db.add(AuthProvider(id=pid, name=body.name, protocol=body.protocol, config=body.config,
                        attribute_mapping=body.attribute_mapping, enabled=True, created_at=_now()))
    db.commit()
    return {"id": pid, "name": body.name, "protocol": body.protocol, "enabled": True}


@router.get("/admin/auth-providers")
def list_providers(db: Session = Depends(get_db)):
    return [{"id": p.id, "name": p.name, "protocol": p.protocol, "enabled": p.enabled} for p in db.query(AuthProvider).all()]


@router.post("/admin/auth-providers/{provider_id}/enable")
def enable_provider(provider_id: str, db: Session = Depends(get_db)):
    p = db.get(AuthProvider, provider_id)
    if not p:
        raise HTTPException(status_code=404, detail="provider not found")
    p.enabled = True
    db.add(models_action.AuditLog(id=uuid.uuid4().hex, actor="admin", event_type="admin.auth_provider.enabled",
                                  subject_type="auth_provider", subject_id=provider_id, payload={"enabled": True}))
    db.commit()
    return {"id": provider_id, "enabled": True}


@router.post("/admin/auth-providers/{provider_id}/disable")
def disable_provider(provider_id: str, db: Session = Depends(get_db)):
    p = db.get(AuthProvider, provider_id)
    if not p:
        raise HTTPException(status_code=404, detail="provider not found")
    p.enabled = False
    db.add(models_action.AuditLog(id=uuid.uuid4().hex, actor="admin", event_type="admin.auth_provider.disabled",
                                  subject_type="auth_provider", subject_id=provider_id, payload={"enabled": False}))
    db.commit()
    return {"id": provider_id, "enabled": False}


@router.post("/admin/auth-providers/{provider_id}/map-assertion")
def map_assertion(provider_id: str, body: MapAssertionRequest, db: Session = Depends(get_db)):
    """Apply the provider's attribute mapping to an IdP assertion -> Foundry user attributes."""
    p = db.get(AuthProvider, provider_id)
    if not p:
        raise HTTPException(status_code=404, detail="provider not found")
    if not p.enabled:
        raise HTTPException(status_code=403, detail="provider disabled")
    mapped: Dict[str, Any] = {}
    for idp_attr, foundry_attr in (p.attribute_mapping or {}).items():
        if idp_attr in body.assertion:
            mapped[foundry_attr] = body.assertion[idp_attr]
    return {"provider_id": provider_id, "protocol": p.protocol, "mapped_attributes": mapped}


# ---------------------------------------------------------------------------
# Service accounts + tokens
# ---------------------------------------------------------------------------
@router.post("/admin/service-accounts", status_code=201)
def create_service_account(body: ServiceAccountCreate, db: Session = Depends(get_db)):
    sid = body.id or uuid.uuid4().hex
    db.add(ServiceAccount(id=sid, display_name=body.display_name, organization_id=body.organization_id, created_at=_now()))
    db.commit()
    return {"id": sid, "display_name": body.display_name}


@router.get("/admin/service-accounts")
def list_service_accounts(organization_id: Optional[str] = None, db: Session = Depends(get_db)):
    q = db.query(ServiceAccount)
    if organization_id:
        q = q.filter(ServiceAccount.organization_id == organization_id)
    return [{"id": s.id, "display_name": s.display_name, "organization_id": s.organization_id} for s in q.all()]


@router.post("/admin/tokens", status_code=201)
def issue_token(body: TokenCreate, db: Session = Depends(get_db)):
    if body.principal_type == "user" and not db.get(_dir.AdminUser, body.principal_id):
        raise HTTPException(status_code=404, detail="user not found")
    if body.principal_type == "service_account" and not db.get(ServiceAccount, body.principal_id):
        raise HTTPException(status_code=404, detail="service account not found")
    tid = uuid.uuid4().hex
    secret = "tok_" + uuid.uuid4().hex
    expires = (_now() + body.ttl_seconds) if body.ttl_seconds else None
    db.add(ApiToken(id=tid, token=secret, principal_type=body.principal_type, principal_id=body.principal_id,
                    scopes=body.scopes, expires_at=expires, revoked=False, created_at=_now()))
    db.add(models_action.AuditLog(id=uuid.uuid4().hex, actor="admin", event_type="admin.token.issued",
                                  subject_type=body.principal_type, subject_id=body.principal_id, payload={"scopes": body.scopes}))
    db.commit()
    return {"id": tid, "token": secret, "principal_id": body.principal_id, "scopes": body.scopes, "expires_at": expires}


@router.post("/admin/tokens/validate")
def validate_token(body: TokenValidateRequest, db: Session = Depends(get_db)):
    tok = db.query(ApiToken).filter(ApiToken.token == body.token).first()
    if not tok:
        return {"valid": False, "reason": "unknown token"}
    if tok.revoked:
        return {"valid": False, "reason": "revoked"}
    if tok.expires_at is not None and tok.expires_at < _now():
        return {"valid": False, "reason": "expired"}
    # tokens are invalid while the owning user account is inactive
    if tok.principal_type == "user":
        user = db.get(_dir.AdminUser, tok.principal_id)
        if not user or user.status != "active":
            return {"valid": False, "reason": "principal inactive"}
    if body.required_scope and body.required_scope not in (tok.scopes or []):
        return {"valid": False, "reason": "missing scope", "required_scope": body.required_scope}
    return {"valid": True, "principal_type": tok.principal_type, "principal_id": tok.principal_id, "scopes": tok.scopes}


@router.post("/admin/tokens/{token_id}/revoke")
def revoke_token(token_id: str, db: Session = Depends(get_db)):
    tok = db.get(ApiToken, token_id)
    if not tok:
        raise HTTPException(status_code=404, detail="token not found")
    tok.revoked = True
    db.commit()
    return {"id": token_id, "revoked": True}


@router.get("/admin/tokens")
def list_tokens(principal_id: Optional[str] = None, db: Session = Depends(get_db)):
    q = db.query(ApiToken)
    if principal_id:
        q = q.filter(ApiToken.principal_id == principal_id)
    return [{"id": t.id, "principal_id": t.principal_id, "scopes": t.scopes,
             "revoked": t.revoked, "expires_at": t.expires_at} for t in q.all()]


@router.post("/admin/oauth-clients", status_code=201)
def create_oauth_client(body: OAuthClientCreate, db: Session = Depends(get_db)):
    cid = body.id or uuid.uuid4().hex
    client_id = "client_" + uuid.uuid4().hex[:12]
    secret = "secret_" + uuid.uuid4().hex
    db.add(OAuthClient(id=cid, display_name=body.display_name, client_id=client_id,
                       scopes=body.scopes, redirect_uris=body.redirect_uris, created_at=_now()))
    db.commit()
    return {"id": cid, "client_id": client_id, "client_secret": secret,  # secret shown once
            "scopes": body.scopes, "redirect_uris": body.redirect_uris}


@router.get("/admin/oauth-clients")
def list_oauth_clients(db: Session = Depends(get_db)):
    return [{"id": c.id, "display_name": c.display_name, "client_id": c.client_id,
             "scopes": c.scopes, "redirect_uris": c.redirect_uris} for c in db.query(OAuthClient).all()]


@router.get("/admin/oauth-clients/{client_id}")
def get_oauth_client(client_id: str, db: Session = Depends(get_db)):
    c = db.get(OAuthClient, client_id)
    if not c:
        raise HTTPException(status_code=404, detail="oauth client not found")
    return {"id": c.id, "display_name": c.display_name, "client_id": c.client_id,
            "scopes": c.scopes, "redirect_uris": c.redirect_uris}


@router.delete("/admin/oauth-clients/{client_id}")
def delete_oauth_client(client_id: str, db: Session = Depends(get_db)):
    c = db.get(OAuthClient, client_id)
    if not c:
        raise HTTPException(status_code=404, detail="oauth client not found")
    db.delete(c)
    db.add(models_action.AuditLog(id=uuid.uuid4().hex, actor="admin", event_type="admin.oauth_client.deleted",
                                  subject_type="oauth_client", subject_id=client_id, payload={}))
    db.commit()
    return {"id": client_id, "deleted": True}

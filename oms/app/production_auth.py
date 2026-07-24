"""Production authentication and authorization boundary.

Local development remains deterministic, while production uses an OIDC
authorization-code flow with PKCE and server-side sessions.  The browser only
receives an opaque session identifier; provider tokens are not stored in the
cookie.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import time
import urllib.parse
import urllib.request
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel
from sqlalchemy import Integer, JSON, String
from sqlalchemy.orm import Mapped, Session, mapped_column
from starlette.middleware.base import BaseHTTPMiddleware

from . import admin_auth, models_action
from .database import Base, SessionLocal, get_db

router = APIRouter(tags=["authentication"])

SESSION_COOKIE = "ontology_session"
FLOW_COOKIE = "ontology_oidc_flow"
ROLE_PERMISSIONS: Dict[str, set[str]] = {
    "viewer": {"view"},
    "editor": {"view", "edit"},
    "operator": {"view", "edit", "execute"},
    "approver": {"view", "approve"},
    "publisher": {"view", "edit", "publish", "deploy", "export"},
    "owner": {"view", "edit", "publish", "deploy", "execute", "approve", "export", "restore", "manage"},
    "administrator": {"*"},
    "admin": {"*"},
}


def _now() -> int:
    return int(time.time())


def auth_mode() -> str:
    return os.getenv("AUTH_MODE", "local").strip().lower()


def is_production() -> bool:
    return os.getenv("APP_ENV", "development").strip().lower() in {"production", "prod"}


def validate_auth_configuration() -> None:
    if is_production() and auth_mode() != "oidc":
        raise RuntimeError("Production requires AUTH_MODE=oidc; the local authentication bypass is disabled")
    if auth_mode() == "oidc":
        missing = [name for name in ("OIDC_ISSUER", "OIDC_CLIENT_ID") if not os.getenv(name)]
        if missing:
            raise RuntimeError(f"OIDC authentication is missing required settings: {', '.join(missing)}")


class AuthSession(Base):
    __tablename__ = "auth_sessions"

    id: Mapped[str] = mapped_column(String, primary_key=True, index=True)
    principal_id: Mapped[str] = mapped_column(String, index=True)
    email: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    display_name: Mapped[str] = mapped_column(String)
    roles: Mapped[list] = mapped_column(JSON, default=list)
    claims: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[int] = mapped_column(Integer)
    expires_at: Mapped[int] = mapped_column(Integer, index=True)
    last_seen_at: Mapped[int] = mapped_column(Integer)


class OidcFlow(Base):
    __tablename__ = "auth_oidc_flows"

    id: Mapped[str] = mapped_column(String, primary_key=True, index=True)
    state: Mapped[str] = mapped_column(String, unique=True, index=True)
    nonce: Mapped[str] = mapped_column(String)
    code_verifier: Mapped[str] = mapped_column(String)
    next_path: Mapped[str] = mapped_column(String, default="/workspace/command-center")
    created_at: Mapped[int] = mapped_column(Integer)
    expires_at: Mapped[int] = mapped_column(Integer, index=True)


@dataclass
class Principal:
    id: str
    display_name: str
    email: Optional[str]
    roles: List[str]
    permissions: List[str]
    authenticated: bool = True
    organization_id: Optional[str] = None
    project_ids: List[str] = field(default_factory=list)

    def allows(self, permission: str) -> bool:
        return "*" in self.permissions or permission in self.permissions

    def as_dict(self) -> Dict[str, Any]:
        return {
            "authenticated": self.authenticated,
            "principal_id": self.id,
            "display_name": self.display_name,
            "email": self.email,
            "roles": self.roles,
            "permissions": self.permissions,
            "organization_id": self.organization_id,
            "project_ids": self.project_ids,
            "auth_mode": auth_mode(),
        }


class LogoutRequest(BaseModel):
    all_sessions: bool = False


def _permissions(roles: List[str], scopes: Optional[List[str]] = None) -> List[str]:
    result = set(scopes or [])
    for role in roles:
        result.update(ROLE_PERMISSIONS.get(str(role).lower(), set()))
    return sorted(result)


def _local_principal() -> Principal:
    return Principal(
        id=os.getenv("LOCAL_AUTH_USER", "local-admin"),
        display_name="Local Administrator",
        email=None,
        roles=["administrator"],
        permissions=["*"],
        project_ids=["*"],
    )


def _claim_projects(claims: Dict[str, Any]) -> List[str]:
    value = claims.get("project_ids", claims.get("projects", []))
    if isinstance(value, str):
        value = [item.strip() for item in value.replace(",", " ").split() if item.strip()]
    return sorted({str(item) for item in value}) if isinstance(value, list) else []


def _session_principal(db: Session, session_id: Optional[str]) -> Optional[Principal]:
    if not session_id:
        return None
    row = db.get(AuthSession, session_id)
    if not row or row.expires_at <= _now():
        return None
    row.last_seen_at = _now()
    roles = [str(item) for item in (row.roles or [])]
    claims = row.claims or {}
    return Principal(
        row.principal_id,
        row.display_name,
        row.email,
        roles,
        _permissions(roles),
        organization_id=str(claims.get("organization_id") or claims.get("org_id")) if (claims.get("organization_id") or claims.get("org_id")) else None,
        project_ids=_claim_projects(claims),
    )


def _bearer_principal(db: Session, authorization: Optional[str]) -> Optional[Principal]:
    if not authorization or not authorization.lower().startswith("bearer "):
        return None
    secret = authorization.split(" ", 1)[1].strip()
    token = db.query(admin_auth.ApiToken).filter(admin_auth.ApiToken.token == secret).first()
    if not token or token.revoked or (token.expires_at is not None and token.expires_at <= _now()):
        return None
    scopes = [str(item) for item in (token.scopes or [])]
    project_ids = sorted({scope.split(":", 2)[1] for scope in scopes if scope.startswith("project:") and len(scope.split(":", 2)) == 3})
    permissions = [scope.split(":", 2)[2] if scope.startswith("project:") and len(scope.split(":", 2)) == 3 else scope for scope in scopes]
    organization_id = None
    if token.principal_type == "service_account":
        account = db.get(admin_auth.ServiceAccount, token.principal_id)
        organization_id = account.organization_id if account else None
    return Principal(token.principal_id, token.principal_id, None, [token.principal_type], _permissions([], permissions), organization_id=organization_id, project_ids=project_ids)


def resolve_principal(request: Request, db: Session) -> Optional[Principal]:
    if auth_mode() == "local":
        return _local_principal()
    return _bearer_principal(db, request.headers.get("authorization")) or _session_principal(
        db, request.cookies.get(SESSION_COOKIE)
    )


def current_principal(request: Request, db: Session = Depends(get_db)) -> Principal:
    principal = resolve_principal(request, db)
    if not principal:
        raise HTTPException(status_code=401, detail="Authentication required")
    return principal


def require_permission(permission: str):
    def dependency(principal: Principal = Depends(current_principal)) -> Principal:
        if not principal.allows(permission):
            raise HTTPException(status_code=403, detail=f"Permission '{permission}' is required")
        return principal

    return dependency


def _discovery() -> Dict[str, Any]:
    issuer = os.environ["OIDC_ISSUER"].rstrip("/")
    url = f"{issuer}/.well-known/openid-configuration"
    with urllib.request.urlopen(url, timeout=10) as response:  # nosec - administrator-configured OIDC endpoint
        return json.loads(response.read().decode("utf-8"))


def _post_form(url: str, payload: Dict[str, str]) -> Dict[str, Any]:
    request = urllib.request.Request(
        url,
        data=urllib.parse.urlencode(payload).encode("utf-8"),
        headers={"content-type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=15) as response:  # nosec - discovered OIDC endpoint
        return json.loads(response.read().decode("utf-8"))


def _validate_id_token(id_token: str, discovery: Dict[str, Any], nonce: str) -> Dict[str, Any]:
    try:
        from authlib.jose import JsonWebToken
    except ImportError as exc:  # pragma: no cover - configuration guard
        raise HTTPException(status_code=503, detail="OIDC dependencies are not installed") from exc
    with urllib.request.urlopen(discovery["jwks_uri"], timeout=10) as response:  # nosec - discovered OIDC endpoint
        jwks = json.loads(response.read().decode("utf-8"))
    jwt = JsonWebToken(["RS256", "RS384", "RS512", "ES256", "ES384"])
    claims = jwt.decode(
        id_token,
        jwks,
        claims_options={
            "iss": {"essential": True, "value": os.environ["OIDC_ISSUER"].rstrip("/")},
            "aud": {"essential": True, "value": os.environ["OIDC_CLIENT_ID"]},
            "exp": {"essential": True},
        },
    )
    claims.validate()
    result = dict(claims)
    if result.get("nonce") != nonce:
        raise HTTPException(status_code=400, detail="OIDC nonce validation failed")
    return result


def _claim_roles(claims: Dict[str, Any]) -> List[str]:
    configured = os.getenv("OIDC_ROLES_CLAIM", "roles")
    value: Any = claims
    for segment in configured.split("."):
        value = value.get(segment) if isinstance(value, dict) else None
    roles = value if isinstance(value, list) else ([value] if isinstance(value, str) else [])
    if not roles and isinstance(claims.get("realm_access"), dict):
        roles = claims["realm_access"].get("roles", [])
    return sorted({str(role).lower() for role in roles}) or [os.getenv("OIDC_DEFAULT_ROLE", "viewer")]


@router.get("/auth/login")
def login(request: Request, next: str = "/workspace/command-center", db: Session = Depends(get_db)):
    if auth_mode() == "local":
        return RedirectResponse(next if next.startswith("/") else "/workspace/command-center")
    discovery = _discovery()
    state = secrets.token_urlsafe(32)
    nonce = secrets.token_urlsafe(32)
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    flow = OidcFlow(
        id=uuid.uuid4().hex,
        state=state,
        nonce=nonce,
        code_verifier=verifier,
        next_path=next if next.startswith("/") else "/workspace/command-center",
        created_at=_now(),
        expires_at=_now() + 600,
    )
    db.add(flow)
    db.commit()
    redirect_uri = os.getenv("OIDC_REDIRECT_URI") or str(request.url_for("oidc_callback"))
    query = urllib.parse.urlencode({
        "response_type": "code",
        "client_id": os.environ["OIDC_CLIENT_ID"],
        "redirect_uri": redirect_uri,
        "scope": os.getenv("OIDC_SCOPES", "openid profile email"),
        "state": state,
        "nonce": nonce,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    })
    response = RedirectResponse(f"{discovery['authorization_endpoint']}?{query}")
    response.set_cookie(FLOW_COOKIE, flow.id, httponly=True, secure=is_production(), samesite="lax", max_age=600)
    return response


@router.get("/auth/callback", name="oidc_callback")
def oidc_callback(request: Request, code: str, state: str, db: Session = Depends(get_db)):
    if auth_mode() != "oidc":
        raise HTTPException(status_code=404, detail="OIDC is not enabled")
    flow = db.get(OidcFlow, request.cookies.get(FLOW_COOKIE, ""))
    if not flow or flow.state != state or flow.expires_at <= _now():
        raise HTTPException(status_code=400, detail="OIDC state is invalid or expired")
    discovery = _discovery()
    redirect_uri = os.getenv("OIDC_REDIRECT_URI") or str(request.url_for("oidc_callback"))
    payload = {
        "grant_type": "authorization_code",
        "client_id": os.environ["OIDC_CLIENT_ID"],
        "code": code,
        "redirect_uri": redirect_uri,
        "code_verifier": flow.code_verifier,
    }
    if os.getenv("OIDC_CLIENT_SECRET"):
        payload["client_secret"] = os.environ["OIDC_CLIENT_SECRET"]
    token = _post_form(discovery["token_endpoint"], payload)
    if not token.get("id_token"):
        raise HTTPException(status_code=400, detail="OIDC provider did not return an ID token")
    claims = _validate_id_token(token["id_token"], discovery, flow.nonce)
    roles = _claim_roles(claims)
    session = AuthSession(
        id=secrets.token_urlsafe(40),
        principal_id=str(claims.get("sub")),
        email=claims.get("email"),
        display_name=str(claims.get("name") or claims.get("preferred_username") or claims.get("sub")),
        roles=roles,
        claims={key: claims.get(key) for key in ("sub", "email", "name", "preferred_username", "organization_id", "org_id", "project_ids", "projects") if claims.get(key) is not None},
        created_at=_now(),
        expires_at=min(int(claims.get("exp", _now() + 28800)), _now() + int(os.getenv("SESSION_TTL_SECONDS", "28800"))),
        last_seen_at=_now(),
    )
    db.add(session)
    db.delete(flow)
    db.add(models_action.AuditLog(
        id=uuid.uuid4().hex,
        actor=session.principal_id,
        event_type="auth.session.created",
        subject_type="auth_session",
        subject_id=session.id,
        payload={"roles": roles},
    ))
    db.commit()
    response = RedirectResponse(flow.next_path)
    response.delete_cookie(FLOW_COOKIE)
    response.set_cookie(
        SESSION_COOKIE,
        session.id,
        httponly=True,
        secure=is_production(),
        samesite="lax",
        max_age=max(0, session.expires_at - _now()),
    )
    return response


@router.get("/auth/session")
def session_info(principal: Principal = Depends(current_principal)):
    return principal.as_dict()


@router.post("/auth/logout")
def logout(body: LogoutRequest, request: Request, db: Session = Depends(get_db)):
    session_id = request.cookies.get(SESSION_COOKIE)
    row = db.get(AuthSession, session_id) if session_id else None
    principal_id = row.principal_id if row else "anonymous"
    if body.all_sessions and row:
        db.query(AuthSession).filter(AuthSession.principal_id == row.principal_id).delete()
    elif row:
        db.delete(row)
    db.add(models_action.AuditLog(
        id=uuid.uuid4().hex,
        actor=principal_id,
        event_type="auth.session.ended",
        subject_type="auth_session",
        subject_id=session_id or "none",
        payload={"all_sessions": body.all_sessions},
    ))
    db.commit()
    response = JSONResponse({"authenticated": False})
    response.delete_cookie(SESSION_COOKIE)
    return response


def _permission_for_request(method: str, path: str) -> str:
    if method.upper() in {"GET", "HEAD", "OPTIONS"}:
        return "view"
    lowered = path.lower()
    if "/approve" in lowered or "/reject" in lowered or "/decisions" in lowered:
        return "approve"
    if "/deploy" in lowered:
        return "deploy"
    if "/publish" in lowered:
        return "publish"
    if "/execute" in lowered or "/run" in lowered or "/triage" in lowered:
        return "execute"
    if "/export" in lowered or "/report" in lowered:
        return "export"
    if "/restore" in lowered:
        return "restore"
    if lowered.startswith("/admin"):
        return "administer"
    return "edit"


class ProductionAuthorizationMiddleware(BaseHTTPMiddleware):
    """Require authenticated, authorized requests when AUTH_MODE=oidc."""

    async def dispatch(self, request: Request, call_next):
        if auth_mode() != "oidc":
            return await call_next(request)
        path = request.url.path
        public_prefixes = ("/auth/", "/health/", "/workspace", "/react/", "/ui/", "/docs", "/redoc", "/openapi.json")
        if path == "/" or path.startswith(public_prefixes):
            return await call_next(request)
        db = SessionLocal()
        try:
            principal = resolve_principal(request, db)
            if not principal:
                return JSONResponse({"detail": "Authentication required", "login_url": "/auth/login"}, status_code=401)
            permission = _permission_for_request(request.method, path)
            if not principal.allows(permission):
                return JSONResponse({"detail": f"Permission '{permission}' is required"}, status_code=403)
            request.state.principal = principal
            db.commit()
        finally:
            db.close()
        return await call_next(request)

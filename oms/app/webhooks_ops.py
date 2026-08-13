"""
Foundry WEBHOOKS (outbound writeback / side-effect) + inbound LISTENERS.

Docs (data-connection/{webhooks-overview,webhooks-setup,webhooks-reference,
listeners-overview,listeners-event-processing}, action-types/{webhooks,set-up-webhook},
administration/configure-outbound-applications).

Deterministic transport
------------------------
We do NOT make real HTTP calls. A webhook stores a `request_config` and a
`mock_response` (the deterministic stand-in for the external system). "Invoking"
builds the request (parameter substitution) and then returns the mock_response
unless `mock_response.fail` is true. This faithfully models the documented
writeback vs side-effect semantics deterministically.

Tables (all prefixed Wh / wh_ to avoid collisions on the shared Base):
    wh_webhooks         - outbound webhook configs (writeback | side_effect)
    wh_executions       - invocation log (success | failed), idempotency, outputs
    wh_credentials      - per-source api_key/oauth2 credentials
    wh_outbound_apps    - registered OAuth2 outbound applications
    wh_listeners        - inbound listeners (hmac | bearer | api_key | none)
    wh_listener_events  - inbound event log (persisted | validation_error | auth_error)
"""

from .database import Base, get_db
from . import models, models_action, production_auth, semantic_scope
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import String, Integer, JSON, Boolean, Float, ForeignKey, inspect
from sqlalchemy.orm import Mapped, mapped_column, Session
from pydantic import BaseModel, ConfigDict, Field
from typing import Optional, List, Any, Dict
import time, uuid, hashlib, json

router = APIRouter(tags=["webhooks"])


# ---------------------------------------------------------------------------
# SQLAlchemy models
# ---------------------------------------------------------------------------

WEBHOOK_MODES = {"writeback", "side_effect"}
CREDENTIAL_TYPES = {"api_key", "oauth2"}
LISTENER_AUTH_TYPES = {"hmac", "bearer", "api_key", "none"}


class WhWebhook(Base):
    __tablename__ = "wh_webhooks"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    project_id: Mapped[str] = mapped_column(String, default="default", server_default="default", index=True)
    source_id: Mapped[Optional[str]] = mapped_column(String, nullable=True, index=True)
    display_name: Mapped[str] = mapped_column(String)
    mode: Mapped[str] = mapped_column(String)  # writeback | side_effect
    # {method, path, headers, query, body_template}
    request_config: Mapped[dict] = mapped_column(JSON, default=dict)
    # list of {name, required} (or dict name->{required})
    input_parameters: Mapped[list] = mapped_column(JSON, default=list)
    # list of keys to extract from mock_response.body
    output_parameters: Mapped[list] = mapped_column(JSON, default=list)
    # {status, body, fail?}
    mock_response: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[int] = mapped_column(Integer)
    updated_at: Mapped[int] = mapped_column(Integer)


class WhExecution(Base):
    __tablename__ = "wh_executions"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    project_id: Mapped[str] = mapped_column(String, default="default", server_default="default", index=True)
    webhook_id: Mapped[str] = mapped_column(String, ForeignKey("wh_webhooks.id"), index=True)
    request_payload: Mapped[dict] = mapped_column(JSON, default=dict)
    response_payload: Mapped[dict] = mapped_column(JSON, default=dict)
    response_status: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String)  # success | failed
    extracted_outputs: Mapped[dict] = mapped_column(JSON, default=dict)
    idempotency_key: Mapped[Optional[str]] = mapped_column(String, nullable=True, index=True)
    actor: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    created_at: Mapped[int] = mapped_column(Integer)


class WhCredential(Base):
    __tablename__ = "wh_credentials"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    project_id: Mapped[str] = mapped_column(String, default="default", server_default="default", index=True)
    source_id: Mapped[str] = mapped_column(String, index=True)
    credential_type: Mapped[str] = mapped_column(String)  # api_key | oauth2
    token: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    expires_at: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    created_at: Mapped[int] = mapped_column(Integer)


class WhOutboundApp(Base):
    __tablename__ = "wh_outbound_apps"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    project_id: Mapped[str] = mapped_column(String, default="default", server_default="default", index=True)
    display_name: Mapped[str] = mapped_column(String)
    client_id: Mapped[str] = mapped_column(String)
    client_secret: Mapped[str] = mapped_column(String)
    token_endpoint: Mapped[str] = mapped_column(String)
    scopes: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[int] = mapped_column(Integer)


class WhListener(Base):
    __tablename__ = "wh_listeners"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    project_id: Mapped[str] = mapped_column(String, default="default", server_default="default", index=True)
    display_name: Mapped[str] = mapped_column(String)
    auth_type: Mapped[str] = mapped_column(String)  # hmac | bearer | api_key | none
    auth_secret: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    target_asset_id: Mapped[Optional[str]] = mapped_column(String, nullable=True, index=True)
    # list of required keys (or dict key->spec)
    event_schema: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[int] = mapped_column(Integer)

    @property
    def credential_configured(self) -> bool:
        return bool(self.auth_secret) if self.auth_type != "none" else True


class WhListenerEvent(Base):
    __tablename__ = "wh_listener_events"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    project_id: Mapped[str] = mapped_column(String, default="default", server_default="default", index=True)
    listener_id: Mapped[str] = mapped_column(String, ForeignKey("wh_listeners.id"), index=True)
    raw_payload: Mapped[dict] = mapped_column(JSON, default=dict)
    auth_valid: Mapped[bool] = mapped_column(Boolean, default=False)
    # persisted | validation_error | auth_error
    processing_status: Mapped[str] = mapped_column(String)
    error_message: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    created_at: Mapped[int] = mapped_column(Integer)


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------

class WebhookCreate(BaseModel):
    id: Optional[str] = None
    project_id: str = "default"
    source_id: Optional[str] = None
    display_name: str
    mode: str = "writeback"
    request_config: Dict[str, Any] = Field(default_factory=dict)
    input_parameters: List[Dict[str, Any]] = Field(default_factory=list)
    output_parameters: List[str] = Field(default_factory=list)
    mock_response: Dict[str, Any] = Field(default_factory=dict)


class WebhookRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    project_id: str
    source_id: Optional[str] = None
    display_name: str
    mode: str
    request_config: Dict[str, Any]
    input_parameters: List[Any]
    output_parameters: List[Any]
    mock_response: Dict[str, Any]
    created_at: int
    updated_at: int


class WebhookInvoke(BaseModel):
    parameters: Dict[str, Any] = Field(default_factory=dict)
    idempotency_key: Optional[str] = None
    actor: Optional[str] = "system"


class WebhookSideEffectInvoke(BaseModel):
    # batch list of parameter sets -> one WhExecution each
    parameter_sets: List[Dict[str, Any]] = Field(default_factory=list)
    actor: Optional[str] = "system"


class ExecutionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    project_id: str
    webhook_id: str
    request_payload: Dict[str, Any]
    response_payload: Dict[str, Any]
    response_status: Optional[int] = None
    status: str
    extracted_outputs: Dict[str, Any]
    idempotency_key: Optional[str] = None
    actor: Optional[str] = None
    created_at: int


class CredentialCreate(BaseModel):
    id: Optional[str] = None
    project_id: str = "default"
    credential_type: str = "api_key"
    token: Optional[str] = None
    expires_at: Optional[int] = None


class AuthorizeRequest(BaseModel):
    outbound_app_id: str
    code: str
    source_id: Optional[str] = None
    ttl_seconds: Optional[int] = 3600


class OutboundAppCreate(BaseModel):
    id: Optional[str] = None
    project_id: str = "default"
    display_name: str
    client_id: str
    client_secret: str
    token_endpoint: str
    scopes: List[str] = Field(default_factory=list)


class OutboundAppRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    project_id: str
    display_name: str
    client_id: str
    token_endpoint: str
    scopes: List[str]
    created_at: int


class ListenerCreate(BaseModel):
    id: Optional[str] = None
    project_id: str = "default"
    display_name: str
    auth_type: str = "none"
    auth_secret: Optional[str] = None
    target_asset_id: Optional[str] = None
    # accepts either a list of required keys or a dict key->spec
    event_schema: Any = Field(default_factory=dict)


class ListenerRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    project_id: str
    display_name: str
    auth_type: str
    credential_configured: bool = False
    target_asset_id: Optional[str] = None
    event_schema: Any
    created_at: int


class ListenerEventRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    project_id: str
    listener_id: str
    raw_payload: Dict[str, Any]
    auth_valid: bool
    processing_status: str
    error_message: Optional[str] = None
    created_at: int


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now() -> int:
    return int(time.time())


def _required_param_names(input_parameters: Any) -> List[str]:
    """Return names of input parameters marked required.

    Accepts either a list of {name, required} dicts or a dict name->{required}.
    """
    names: List[str] = []
    if isinstance(input_parameters, dict):
        for name, spec in input_parameters.items():
            if isinstance(spec, dict) and spec.get("required"):
                names.append(name)
    elif isinstance(input_parameters, list):
        for item in input_parameters:
            if isinstance(item, dict) and item.get("required"):
                names.append(item.get("name"))
    return [n for n in names if n]


def _substitute_value(value: Any, parameters: Dict[str, Any]) -> Any:
    """Substitute {name} tokens.

    If the value is EXACTLY a single `{name}` token, return the raw parameter
    value (preserving numeric / non-string types). Otherwise do a string-format
    replacement of every `{name}` token found in the string.
    """
    if not isinstance(value, str):
        return value
    stripped = value.strip()
    if stripped.startswith("{") and stripped.endswith("}") and stripped.count("{") == 1:
        key = stripped[1:-1]
        if key in parameters:
            return parameters[key]
        return value
    out = value
    for key, pval in parameters.items():
        token = "{" + key + "}"
        if token in out:
            out = out.replace(token, str(pval))
    return out


def _substitute_deep(obj: Any, parameters: Dict[str, Any]) -> Any:
    if isinstance(obj, dict):
        return {k: _substitute_deep(v, parameters) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_substitute_deep(v, parameters) for v in obj]
    return _substitute_value(obj, parameters)


def _build_request(webhook: WhWebhook, parameters: Dict[str, Any]) -> Dict[str, Any]:
    """Build the outbound request from request_config with parameter substitution."""
    cfg = webhook.request_config or {}
    return {
        "method": _substitute_value(cfg.get("method", "POST"), parameters),
        "path": _substitute_value(cfg.get("path", ""), parameters),
        "headers": _substitute_deep(cfg.get("headers", {}) or {}, parameters),
        "query": _substitute_deep(cfg.get("query", {}) or {}, parameters),
        "body": _substitute_deep(cfg.get("body_template", {}) or {}, parameters),
    }


def _extract_outputs(webhook: WhWebhook, response_body: Any) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    keys = webhook.output_parameters or []
    if isinstance(response_body, dict):
        for key in keys:
            if key in response_body:
                out[key] = response_body[key]
    return out


def _credential_status_for_source(db: Session, source_id: Optional[str], project_id: str = "default") -> Dict[str, Any]:
    """Return {needs_refresh, expired} for the latest credential of a source."""
    if not source_id:
        return {"has_credential": False, "needs_refresh": False, "expired": False}
    cred = (
        db.query(WhCredential)
        .filter(WhCredential.project_id == project_id, WhCredential.source_id == source_id)
        .order_by(WhCredential.created_at.desc())
        .first()
    )
    if not cred:
        return {"has_credential": False, "needs_refresh": False, "expired": False}
    expired = cred.expires_at is not None and cred.expires_at <= _now()
    return {"has_credential": True, "needs_refresh": expired, "expired": expired}


def _validate_required_params(webhook: WhWebhook, parameters: Dict[str, Any]) -> None:
    required = _required_param_names(webhook.input_parameters)
    missing = [name for name in required if name not in parameters]
    if missing:
        raise HTTPException(
            status_code=422,
            detail=f"Missing required parameters: {missing}",
        )


def _get_webhook(db: Session, webhook_id: str, principal: Optional[production_auth.Principal] = None, permission: str = "view") -> WhWebhook:
    if principal is None:
        wh = db.query(WhWebhook).filter(WhWebhook.id == webhook_id).first()
        if not wh:
            raise HTTPException(status_code=404, detail=f"Webhook '{webhook_id}' not found")
        return wh
    return semantic_scope.owned_row(db, principal, WhWebhook, webhook_id, permission, "Webhook")


def _validate_source_project(db: Session, source_id: Optional[str], project_id: str) -> None:
    if not source_id:
        return
    from . import connectivity
    if connectivity.ConnectionSource.__tablename__ not in inspect(db.get_bind()).get_table_names():
        return
    source = db.get(connectivity.ConnectionSource, source_id)
    if source and source.project_id != project_id:
        raise HTTPException(status_code=422, detail="Connection source must belong to the same project")


def _required_event_keys(event_schema: Any) -> List[str]:
    if isinstance(event_schema, list):
        return [k for k in event_schema if isinstance(k, str)]
    if isinstance(event_schema, dict):
        # support {key: {required: bool}} or {"required": [...]} or {key: type}
        if "required" in event_schema and isinstance(event_schema["required"], list):
            return [k for k in event_schema["required"] if isinstance(k, str)]
        out = []
        for key, spec in event_schema.items():
            if isinstance(spec, dict):
                if spec.get("required", True):
                    out.append(key)
            else:
                out.append(key)
        return out
    return []


def hmac_signature(secret: str, body_bytes: bytes) -> str:
    """Deterministic signature used by hmac listeners: sha256(secret + body) hex.

    (The brief defines the listener signature as sha256(secret+body) rather than a
    true HMAC; we honor that exact definition for deterministic verification.)
    """
    h = hashlib.sha256()
    h.update((secret or "").encode("utf-8"))
    h.update(body_bytes)
    return h.hexdigest()


def _audit(db: Session, event_type: str, subject_type: str, subject_id: str, payload: dict):
    db.add(models_action.AuditLog(
        id=uuid.uuid4().hex,
        actor="system",
        event_type=event_type,
        subject_type=subject_type,
        subject_id=subject_id,
        payload=payload,
    ))


# ---------------------------------------------------------------------------
# Webhook CRUD
# ---------------------------------------------------------------------------

@router.post("/connections/webhooks", response_model=WebhookRead)
def create_webhook(body: WebhookCreate, db: Session = Depends(get_db), principal: production_auth.Principal = Depends(production_auth.require_permission("edit"))):
    semantic_scope.assert_project(db, principal, body.project_id, "edit")
    _validate_source_project(db, body.source_id, body.project_id)
    if body.mode not in WEBHOOK_MODES:
        raise HTTPException(status_code=422, detail=f"mode must be one of {sorted(WEBHOOK_MODES)}")
    wh_id = body.id or uuid.uuid4().hex
    if db.query(WhWebhook).filter(WhWebhook.id == wh_id).first():
        raise HTTPException(status_code=400, detail="Webhook already exists")
    now = _now()
    row = WhWebhook(
        id=wh_id,
        project_id=body.project_id,
        source_id=body.source_id,
        display_name=body.display_name,
        mode=body.mode,
        request_config=body.request_config,
        input_parameters=body.input_parameters,
        output_parameters=body.output_parameters,
        mock_response=body.mock_response,
        created_at=now,
        updated_at=now,
    )
    db.add(row)
    _audit(db, "webhooks.webhook.created", "webhook", wh_id,
           {"display_name": body.display_name, "mode": body.mode})
    db.commit()
    db.refresh(row)
    return row


@router.get("/connections/webhooks", response_model=List[WebhookRead])
def list_webhooks(db: Session = Depends(get_db), principal: production_auth.Principal = Depends(production_auth.require_permission("view"))):
    return semantic_scope.accessible_query(db, principal, WhWebhook).order_by(WhWebhook.created_at).all()


@router.get("/connections/webhooks/{webhook_id}", response_model=WebhookRead)
def get_webhook(webhook_id: str, db: Session = Depends(get_db), principal: production_auth.Principal = Depends(production_auth.require_permission("view"))):
    return _get_webhook(db, webhook_id, principal)


# ---------------------------------------------------------------------------
# Invoke (writeback)
# ---------------------------------------------------------------------------

@router.post("/connections/webhooks/{webhook_id}/invoke")
def invoke_webhook(webhook_id: str, body: WebhookInvoke, db: Session = Depends(get_db), principal: production_auth.Principal = Depends(production_auth.require_permission("execute"))):
    """Writeback invoke: failures are BLOCKING (return 422 so the caller rolls back)."""
    wh = _get_webhook(db, webhook_id, principal, "execute")
    _validate_required_params(wh, body.parameters)

    # Idempotency: if this key already succeeded, return the cached execution.
    if body.idempotency_key:
        cached = (
            db.query(WhExecution)
            .filter(
                WhExecution.webhook_id == webhook_id,
                WhExecution.idempotency_key == body.idempotency_key,
                WhExecution.status == "success",
            )
            .first()
        )
        if cached:
            return {
                "status": "success",
                "cached": True,
                "execution_id": cached.id,
                "response_status": cached.response_status,
                "extracted_outputs": cached.extracted_outputs,
            }

    request_payload = _build_request(wh, body.parameters)
    cred_status = _credential_status_for_source(db, wh.source_id, wh.project_id)
    mock = wh.mock_response or {}
    resp_status = mock.get("status", 200)
    resp_body = mock.get("body", {})
    failed = bool(mock.get("fail"))

    exec_id = uuid.uuid4().hex
    now = _now()

    if failed:
        execution = WhExecution(
            id=exec_id,
            project_id=wh.project_id,
            webhook_id=webhook_id,
            request_payload=request_payload,
            response_payload=mock,
            response_status=resp_status if isinstance(resp_status, int) else 500,
            status="failed",
            extracted_outputs={},
            idempotency_key=body.idempotency_key,
            actor=body.actor,
            created_at=now,
        )
        db.add(execution)
        _audit(db, "webhooks.webhook.invoked", "webhook", webhook_id,
               {"status": "failed", "mode": "writeback"})
        db.commit()
        raise HTTPException(
            status_code=422,
            detail={
                "status": "failed",
                "execution_id": exec_id,
                "response_status": execution.response_status,
                "message": "Webhook reported failure; rollback ontology writeback.",
                "needs_refresh": cred_status["needs_refresh"],
            },
        )

    extracted = _extract_outputs(wh, resp_body)
    execution = WhExecution(
        id=exec_id,
        project_id=wh.project_id,
        webhook_id=webhook_id,
        request_payload=request_payload,
        response_payload=mock,
        response_status=resp_status if isinstance(resp_status, int) else 200,
        status="success",
        extracted_outputs=extracted,
        idempotency_key=body.idempotency_key,
        actor=body.actor,
        created_at=now,
    )
    db.add(execution)
    _audit(db, "webhooks.webhook.invoked", "webhook", webhook_id,
           {"status": "success", "mode": "writeback"})
    db.commit()
    return {
        "status": "success",
        "cached": False,
        "execution_id": exec_id,
        "response_status": execution.response_status,
        "extracted_outputs": extracted,
        "needs_refresh": cred_status["needs_refresh"],
    }


# ---------------------------------------------------------------------------
# Side-effect invoke (non-blocking, batch)
# ---------------------------------------------------------------------------

@router.post("/connections/webhooks/{webhook_id}/invoke-side-effect")
def invoke_side_effect(webhook_id: str, body: WebhookSideEffectInvoke, db: Session = Depends(get_db), principal: production_auth.Principal = Depends(production_auth.require_permission("execute"))):
    """Side-effect invoke: failures are NON-BLOCKING; always return 200.

    Supports a batch list of parameter sets -> one WhExecution each.
    """
    wh = _get_webhook(db, webhook_id, principal, "execute")
    cred_status = _credential_status_for_source(db, wh.source_id, wh.project_id)
    param_sets = body.parameter_sets if body.parameter_sets else [{}]
    results: List[Dict[str, Any]] = []
    now = _now()

    for params in param_sets:
        # Validate required params; a missing param logs a failed execution (non-blocking).
        required = _required_param_names(wh.input_parameters)
        missing = [name for name in required if name not in params]
        request_payload = _build_request(wh, params)
        exec_id = uuid.uuid4().hex
        mock = wh.mock_response or {}
        resp_status = mock.get("status", 200)
        resp_body = mock.get("body", {})

        if missing:
            execution = WhExecution(
                id=exec_id, project_id=wh.project_id, webhook_id=webhook_id, request_payload=request_payload,
                response_payload={"error": f"missing required parameters: {missing}"},
                response_status=422, status="failed", extracted_outputs={},
                idempotency_key=None, actor=body.actor, created_at=now,
            )
            db.add(execution)
            results.append({"execution_id": exec_id, "status": "failed",
                            "error": f"missing required parameters: {missing}"})
            continue

        failed = bool(mock.get("fail"))
        if failed:
            execution = WhExecution(
                id=exec_id, project_id=wh.project_id, webhook_id=webhook_id, request_payload=request_payload,
                response_payload=mock,
                response_status=resp_status if isinstance(resp_status, int) else 500,
                status="failed", extracted_outputs={}, idempotency_key=None,
                actor=body.actor, created_at=now,
            )
            db.add(execution)
            results.append({"execution_id": exec_id, "status": "failed"})
        else:
            extracted = _extract_outputs(wh, resp_body)
            execution = WhExecution(
                id=exec_id, project_id=wh.project_id, webhook_id=webhook_id, request_payload=request_payload,
                response_payload=mock,
                response_status=resp_status if isinstance(resp_status, int) else 200,
                status="success", extracted_outputs=extracted, idempotency_key=None,
                actor=body.actor, created_at=now,
            )
            db.add(execution)
            results.append({"execution_id": exec_id, "status": "success",
                            "extracted_outputs": extracted})

    _audit(db, "webhooks.webhook.invoked", "webhook", webhook_id,
           {"mode": "side_effect", "count": len(results)})
    db.commit()
    return {
        "mode": "side_effect",
        "count": len(results),
        "succeeded": sum(1 for r in results if r["status"] == "success"),
        "failed": sum(1 for r in results if r["status"] == "failed"),
        "results": results,
        "needs_refresh": cred_status["needs_refresh"],
    }


# ---------------------------------------------------------------------------
# Test / dry-run (stores nothing)
# ---------------------------------------------------------------------------

@router.post("/connections/webhooks/{webhook_id}/test")
def test_webhook(webhook_id: str, body: WebhookInvoke, db: Session = Depends(get_db), principal: production_auth.Principal = Depends(production_auth.require_permission("execute"))):
    """Dry-run: build + return request preview + mock response + extracted outputs.

    Does NOT store a WhExecution.
    """
    wh = _get_webhook(db, webhook_id, principal, "execute")
    _validate_required_params(wh, body.parameters)
    request_payload = _build_request(wh, body.parameters)
    mock = wh.mock_response or {}
    resp_body = mock.get("body", {})
    failed = bool(mock.get("fail"))
    extracted = {} if failed else _extract_outputs(wh, resp_body)
    return {
        "dry_run": True,
        "request_preview": request_payload,
        "mock_response": mock,
        "would_fail": failed,
        "extracted_outputs": extracted,
    }


# ---------------------------------------------------------------------------
# Executions log
# ---------------------------------------------------------------------------

@router.get("/connections/webhooks/{webhook_id}/executions", response_model=List[ExecutionRead])
def list_executions(webhook_id: str, db: Session = Depends(get_db), principal: production_auth.Principal = Depends(production_auth.require_permission("view"))):
    wh = _get_webhook(db, webhook_id, principal)
    return (
        db.query(WhExecution)
        .filter(WhExecution.project_id == wh.project_id, WhExecution.webhook_id == webhook_id)
        .order_by(WhExecution.created_at)
        .all()
    )


# ---------------------------------------------------------------------------
# Outbound applications
# ---------------------------------------------------------------------------

@router.post("/outbound-applications", response_model=OutboundAppRead)
def create_outbound_app(body: OutboundAppCreate, db: Session = Depends(get_db), principal: production_auth.Principal = Depends(production_auth.require_permission("administer"))):
    semantic_scope.assert_project(db, principal, body.project_id, "administer")
    app_id = body.id or uuid.uuid4().hex
    if db.query(WhOutboundApp).filter(WhOutboundApp.id == app_id).first():
        raise HTTPException(status_code=400, detail="OutboundApp already exists")
    row = WhOutboundApp(
        id=app_id,
        project_id=body.project_id,
        display_name=body.display_name,
        client_id=body.client_id,
        client_secret=body.client_secret,
        token_endpoint=body.token_endpoint,
        scopes=body.scopes,
        created_at=_now(),
    )
    db.add(row)
    _audit(db, "webhooks.outbound_app.created", "outbound_app", app_id,
           {"display_name": body.display_name})
    db.commit()
    db.refresh(row)
    return row


@router.get("/outbound-applications", response_model=List[OutboundAppRead])
def list_outbound_apps(db: Session = Depends(get_db), principal: production_auth.Principal = Depends(production_auth.require_permission("administer"))):
    return semantic_scope.accessible_query(db, principal, WhOutboundApp, "administer").order_by(WhOutboundApp.created_at).all()


# ---------------------------------------------------------------------------
# Credentials / OAuth
# ---------------------------------------------------------------------------

@router.post("/connections/sources/{source_id}/credentials")
def create_credential(source_id: str, body: CredentialCreate, db: Session = Depends(get_db), principal: production_auth.Principal = Depends(production_auth.require_permission("administer"))):
    semantic_scope.assert_project(db, principal, body.project_id, "administer")
    _validate_source_project(db, source_id, body.project_id)
    if body.credential_type not in CREDENTIAL_TYPES:
        raise HTTPException(status_code=422,
                            detail=f"credential_type must be one of {sorted(CREDENTIAL_TYPES)}")
    cred_id = body.id or uuid.uuid4().hex
    if db.query(WhCredential).filter(WhCredential.id == cred_id).first():
        raise HTTPException(status_code=400, detail="Credential already exists")
    row = WhCredential(
        id=cred_id,
        project_id=body.project_id,
        source_id=source_id,
        credential_type=body.credential_type,
        token=body.token,
        expires_at=body.expires_at,
        created_at=_now(),
    )
    db.add(row)
    _audit(db, "webhooks.credential.created", "credential", cred_id,
           {"source_id": source_id, "credential_type": body.credential_type})
    db.commit()
    db.refresh(row)
    expired = row.expires_at is not None and row.expires_at <= _now()
    return {
        "id": cred_id,
        "project_id": row.project_id,
        "source_id": source_id,
        "credential_type": row.credential_type,
        "expires_at": row.expires_at,
        "expired": expired,
        "needs_refresh": expired,
    }


@router.post("/connections/webhooks/{webhook_id}/authorize")
def authorize_webhook(webhook_id: str, body: AuthorizeRequest, db: Session = Depends(get_db), principal: production_auth.Principal = Depends(production_auth.require_permission("administer"))):
    """Simulate an OAuth2 code -> token exchange against a WhOutboundApp.

    Deterministic: token = sha256(client_secret + code). Stores a WhCredential
    (oauth2) for the webhook's source (or the supplied source_id).
    """
    wh = _get_webhook(db, webhook_id, principal, "administer")
    app = db.query(WhOutboundApp).filter(WhOutboundApp.id == body.outbound_app_id, WhOutboundApp.project_id == wh.project_id).first()
    if not app:
        raise HTTPException(status_code=404,
                            detail=f"OutboundApp '{body.outbound_app_id}' not found")
    source_id = body.source_id or wh.source_id
    if not source_id:
        raise HTTPException(status_code=422,
                            detail="No source_id available to bind the credential to")
    _validate_source_project(db, source_id, wh.project_id)

    token = hashlib.sha256((app.client_secret + body.code).encode("utf-8")).hexdigest()
    now = _now()
    ttl = body.ttl_seconds if body.ttl_seconds is not None else 3600
    expires_at = now + ttl
    cred_id = uuid.uuid4().hex
    row = WhCredential(
        id=cred_id,
        project_id=wh.project_id,
        source_id=source_id,
        credential_type="oauth2",
        token=token,
        expires_at=expires_at,
        created_at=now,
    )
    db.add(row)
    _audit(db, "webhooks.webhook.authorized", "webhook", webhook_id,
           {"outbound_app_id": app.id, "source_id": source_id})
    db.commit()
    return {
        "credential_id": cred_id,
        "source_id": source_id,
        "token": token,
        "expires_at": expires_at,
        "expired": False,
        "needs_refresh": False,
    }


# ---------------------------------------------------------------------------
# Inbound listeners
# ---------------------------------------------------------------------------

@router.post("/listeners", response_model=ListenerRead)
def create_listener(body: ListenerCreate, db: Session = Depends(get_db), principal: production_auth.Principal = Depends(production_auth.require_permission("edit"))):
    semantic_scope.assert_project(db, principal, body.project_id, "edit")
    if body.auth_type not in LISTENER_AUTH_TYPES:
        raise HTTPException(status_code=422,
                            detail=f"auth_type must be one of {sorted(LISTENER_AUTH_TYPES)}")
    if body.auth_type != "none" and not body.auth_secret:
        raise HTTPException(status_code=422,
                            detail=f"auth_secret is required for auth_type '{body.auth_type}'")
    if body.target_asset_id:
        asset = semantic_scope.asset_for(db, principal, body.target_asset_id, "edit")
        if asset.project_id != body.project_id:
            raise HTTPException(status_code=422, detail="Listener target asset must belong to the same project")
    listener_id = body.id or uuid.uuid4().hex
    if db.query(WhListener).filter(WhListener.id == listener_id).first():
        raise HTTPException(status_code=400, detail="Listener already exists")
    row = WhListener(
        id=listener_id,
        project_id=body.project_id,
        display_name=body.display_name,
        auth_type=body.auth_type,
        auth_secret=body.auth_secret,
        target_asset_id=body.target_asset_id,
        event_schema=body.event_schema,
        created_at=_now(),
    )
    db.add(row)
    _audit(db, "webhooks.listener.created", "listener", listener_id,
           {"display_name": body.display_name, "auth_type": body.auth_type})
    db.commit()
    db.refresh(row)
    return row


@router.get("/listeners", response_model=List[ListenerRead])
def list_listeners(db: Session = Depends(get_db), principal: production_auth.Principal = Depends(production_auth.require_permission("view"))):
    return semantic_scope.accessible_query(db, principal, WhListener).order_by(WhListener.created_at).all()


@router.get("/listeners/{listener_id}", response_model=ListenerRead)
def get_listener(listener_id: str, db: Session = Depends(get_db), principal: production_auth.Principal = Depends(production_auth.require_permission("view"))):
    return semantic_scope.owned_row(db, principal, WhListener, listener_id, "view", "Listener")


def _check_listener_auth(listener: WhListener, headers: Dict[str, str], body_bytes: bytes) -> bool:
    auth_type = listener.auth_type
    secret = listener.auth_secret or ""
    # normalize header keys to lower-case
    lh = {k.lower(): v for k, v in headers.items()}
    if auth_type == "none":
        return True
    if auth_type == "hmac":
        provided = lh.get("x-signature", "")
        expected = hmac_signature(secret, body_bytes)
        return provided == expected
    if auth_type == "bearer":
        provided = lh.get("authorization", "")
        # accept either "Bearer <secret>" or the raw secret
        if provided.lower().startswith("bearer "):
            provided = provided[7:]
        return provided == secret
    if auth_type == "api_key":
        provided = lh.get("x-api-key", "")
        return provided == secret
    return False


@router.post("/listeners/{listener_id}/events")
async def receive_listener_event(listener_id: str, request: Request, db: Session = Depends(get_db)):
    """Inbound endpoint.

    - auth fail   -> 401 + WhListenerEvent(auth_error)
    - schema fail -> 202 + WhListenerEvent(validation_error)  [accept-for-retry, no mutation]
    - success     -> 200 + append payload to target DataAsset.records + event(persisted)
    """
    listener = db.query(WhListener).filter(WhListener.id == listener_id).first()
    if not listener:
        raise HTTPException(status_code=404, detail=f"Listener '{listener_id}' not found")

    body_bytes = await request.body()
    try:
        payload = json.loads(body_bytes.decode("utf-8")) if body_bytes else {}
    except json.JSONDecodeError:
        payload = {}
    if not isinstance(payload, dict):
        payload = {"_raw": payload}

    headers = {k: v for k, v in request.headers.items()}
    now = _now()
    event_id = uuid.uuid4().hex

    # 1. Auth validation
    auth_valid = _check_listener_auth(listener, headers, body_bytes)
    if not auth_valid:
        event = WhListenerEvent(
            id=event_id, project_id=listener.project_id, listener_id=listener_id, raw_payload=payload,
            auth_valid=False, processing_status="auth_error",
            error_message="authentication failed", created_at=now,
        )
        db.add(event)
        db.commit()
        raise HTTPException(status_code=401, detail={
            "processing_status": "auth_error", "event_id": event_id,
            "message": "authentication failed",
        })

    # 2. Schema validation
    required_keys = _required_event_keys(listener.event_schema)
    missing = [k for k in required_keys if k not in payload]
    if missing:
        event = WhListenerEvent(
            id=event_id, project_id=listener.project_id, listener_id=listener_id, raw_payload=payload,
            auth_valid=True, processing_status="validation_error",
            error_message=f"missing required keys: {missing}", created_at=now,
        )
        db.add(event)
        db.commit()
        # 202 Accepted-for-retry; do NOT modify the asset.
        from fastapi.responses import JSONResponse
        return JSONResponse(status_code=202, content={
            "processing_status": "validation_error", "event_id": event_id,
            "missing_keys": missing,
        })

    # 3. Success -> append to target DataAsset.records
    appended = False
    if listener.target_asset_id:
        asset = db.query(models.DataAsset).filter(
            models.DataAsset.id == listener.target_asset_id,
            models.DataAsset.project_id == listener.project_id,
        ).first()
        if asset:
            records = list(asset.records or [])
            records.append(payload)
            asset.records = records
            asset.updated_at = now
            appended = True

    event = WhListenerEvent(
        id=event_id, project_id=listener.project_id, listener_id=listener_id, raw_payload=payload,
        auth_valid=True, processing_status="persisted",
        error_message=None, created_at=now,
    )
    db.add(event)
    _audit(db, "webhooks.listener.event_persisted", "listener", listener_id,
           {"event_id": event_id, "appended": appended})
    db.commit()
    return {
        "processing_status": "persisted",
        "event_id": event_id,
        "appended": appended,
        "target_asset_id": listener.target_asset_id,
    }


@router.get("/listeners/{listener_id}/events", response_model=List[ListenerEventRead])
def list_listener_events(listener_id: str, db: Session = Depends(get_db), principal: production_auth.Principal = Depends(production_auth.require_permission("view"))):
    listener = semantic_scope.owned_row(db, principal, WhListener, listener_id, "view", "Listener")
    return (
        db.query(WhListenerEvent)
        .filter(WhListenerEvent.project_id == listener.project_id, WhListenerEvent.listener_id == listener_id)
        .order_by(WhListenerEvent.created_at)
        .all()
    )

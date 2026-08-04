"""Provider-neutral, governed model inference gateway.

External calls are disabled unless a provider explicitly enables them and references
an environment-backed secret. Deterministic inference remains the default for local
deployments, tests, and recovery rehearsals.
"""

from __future__ import annotations

import hashlib
import fnmatch
import ipaddress
import json
import os
import socket
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from typing import Any, Dict, List, Optional, Protocol

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import Integer, JSON, String, UniqueConstraint
from sqlalchemy.orm import Mapped, Session, mapped_column

from . import models, semantic_scope, tenancy
from .database import Base, get_db
from .production_auth import Principal, require_permission
from .runtime import create_audit_log


router = APIRouter(tags=["model-gateway"])


class ModelGatewayProvider(Base):
    __tablename__ = "model_gateway_providers"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    project_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    display_name: Mapped[str] = mapped_column(String, nullable=False)
    provider_type: Mapped[str] = mapped_column(String, nullable=False, index=True)
    base_url: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    secret_ref: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    allowed_models: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    policy: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    configuration: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String, nullable=False, index=True)
    created_at: Mapped[int] = mapped_column(Integer, nullable=False)
    updated_at: Mapped[int] = mapped_column(Integer, nullable=False)


class ModelGatewayRun(Base):
    __tablename__ = "model_gateway_runs"
    __table_args__ = (
        UniqueConstraint("project_id", "provider_id", "created_by", "idempotency_key", name="uq_model_gateway_run_idempotency"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True)
    project_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    provider_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    model_name: Mapped[str] = mapped_column(String, nullable=False, index=True)
    status: Mapped[str] = mapped_column(String, nullable=False, index=True)
    request_hash: Mapped[str] = mapped_column(String, nullable=False, index=True)
    idempotency_key: Mapped[Optional[str]] = mapped_column(String, nullable=True, index=True)
    input_summary: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    output: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    usage: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    policy_decision: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    trace: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    evidence: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    error: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    created_by: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[int] = mapped_column(Integer, nullable=False)
    completed_at: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)


class ProviderCreate(BaseModel):
    id: Optional[str] = None
    project_id: str = "default"
    display_name: str = Field(min_length=1, max_length=200)
    provider_type: str = Field(default="deterministic", pattern="^(deterministic|openai_compatible|local_http)$")
    base_url: Optional[str] = None
    secret_ref: Optional[str] = None
    allowed_models: List[str] = Field(default_factory=list)
    policy: Dict[str, Any] = Field(default_factory=dict)
    configuration: Dict[str, Any] = Field(default_factory=dict)


class GatewayMessage(BaseModel):
    role: str = Field(pattern="^(system|user|assistant|tool)$")
    content: str = Field(max_length=200_000)


class OntologyObjectReference(BaseModel):
    object_type_id: str
    object_id: str
    fields: List[str] = Field(default_factory=list)


class GatewayInferenceRequest(BaseModel):
    project_id: str = "default"
    provider_id: str
    model_name: str
    messages: List[GatewayMessage] = Field(min_length=1, max_length=100)
    ontology_objects: List[OntologyObjectReference] = Field(default_factory=list, max_length=100)
    response_schema: Dict[str, Any] = Field(default_factory=dict)
    parameters: Dict[str, Any] = Field(default_factory=dict)
    proposed_action_type_id: Optional[str] = None
    idempotency_key: Optional[str] = Field(default=None, min_length=1, max_length=200)


class ModelAdapter(Protocol):
    def infer(self, provider: ModelGatewayProvider, request: GatewayInferenceRequest, context: List[Dict[str, Any]]) -> Dict[str, Any]: ...


class DeterministicAdapter:
    def infer(self, provider: ModelGatewayProvider, request: GatewayInferenceRequest, context: List[Dict[str, Any]]) -> Dict[str, Any]:
        user_text = "\n".join(message.content for message in request.messages if message.role == "user")
        digest = hashlib.sha256(json.dumps({
            "model": request.model_name,
            "messages": [message.model_dump() for message in request.messages],
            "context": context,
            "parameters": request.parameters,
        }, sort_keys=True, default=str).encode("utf-8")).hexdigest()
        object_count = len(context)
        content = f"Deterministic analysis {digest[:12]}: reviewed {object_count} governed ontology object(s)."
        if user_text:
            content += f" Request focus: {user_text[:240]}"
        structured = {"summary": content, "confidence": round(0.55 + int(digest[:2], 16) / 2550, 3), "evidence_count": object_count}
        if request.response_schema:
            structured["response_schema_applied"] = True
        return {
            "content": content,
            "structured_output": structured,
            "usage": {"input_units": sum(len(message.content) for message in request.messages), "output_units": len(content), "estimated_cost_usd": 0.0},
            "provider_trace": {"adapter": "deterministic", "digest": digest},
        }


def _allowed_model_host(hostname: str) -> bool:
    allowlist = [value.strip().lower() for value in os.getenv("MODEL_GATEWAY_ALLOWED_HOSTS", "").split(",") if value.strip()]
    if os.getenv("APP_ENV", "development").lower() == "production" and not allowlist:
        return False
    return not allowlist or any(fnmatch.fnmatch(hostname.lower(), pattern) for pattern in allowlist)


def _validate_model_url(url: str, *, resolve: bool = True) -> None:
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise RuntimeError("Model provider URL must use http or https")
    if parsed.username or parsed.password:
        raise RuntimeError("Credentials must not be embedded in model provider URLs")
    if not _allowed_model_host(parsed.hostname):
        raise RuntimeError("Model provider host is not in MODEL_GATEWAY_ALLOWED_HOSTS")
    if not resolve:
        return
    allow_private = os.getenv("MODEL_GATEWAY_ALLOW_PRIVATE_NETWORKS", "false").lower() in {"1", "true", "yes"}
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    try:
        addresses = {item[4][0] for item in socket.getaddrinfo(parsed.hostname, port, type=socket.SOCK_STREAM)}
    except socket.gaierror as exc:
        raise RuntimeError("Model provider host could not be resolved") from exc
    for address in addresses:
        ip = ipaddress.ip_address(address)
        unsafe = ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_reserved or ip.is_unspecified
        if unsafe and not allow_private:
            raise RuntimeError("Private or local model provider addresses are disabled")


class _SafeModelRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        _validate_model_url(newurl)
        source = urllib.parse.urlsplit(req.full_url)
        target = urllib.parse.urlsplit(newurl)
        if source.hostname != target.hostname or (source.scheme == "https" and target.scheme != "https"):
            raise RuntimeError("Cross-host and HTTPS-downgrade model provider redirects are disabled")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class OpenAICompatibleAdapter:
    def infer(self, provider: ModelGatewayProvider, request: GatewayInferenceRequest, context: List[Dict[str, Any]]) -> Dict[str, Any]:
        if not bool((provider.configuration or {}).get("external_calls_enabled")):
            raise RuntimeError("External model calls are disabled for this provider")
        if not provider.base_url:
            raise RuntimeError("Provider base_url is required")
        secret_name = provider.secret_ref or ""
        token = os.getenv(secret_name) if secret_name else None
        if not token:
            raise RuntimeError("Configured provider secret reference is unavailable")
        context_message = {
            "role": "system",
            "content": "Governed ontology context:\n" + json.dumps(context, sort_keys=True, default=str),
        }
        payload = {
            "model": request.model_name,
            "messages": [context_message, *[message.model_dump() for message in request.messages]],
            **{key: value for key, value in request.parameters.items() if key in {"temperature", "max_tokens", "top_p", "seed"}},
        }
        if request.response_schema:
            payload["response_format"] = {"type": "json_schema", "json_schema": request.response_schema}
        body = json.dumps(payload).encode("utf-8")
        endpoint = provider.base_url.rstrip("/")
        if not endpoint.endswith("/chat/completions"):
            endpoint += "/chat/completions"
        _validate_model_url(endpoint)
        http_request = urllib.request.Request(
            endpoint,
            data=body,
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            method="POST",
        )
        timeout = max(1, min(int((provider.configuration or {}).get("timeout_seconds", 60)), 300))
        try:
            with urllib.request.build_opener(_SafeModelRedirectHandler()).open(http_request, timeout=timeout) as response:
                result = json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"Provider request failed: {exc}") from exc
        choices = result.get("choices") or []
        content = (((choices[0] if choices else {}).get("message") or {}).get("content") or "")
        return {
            "content": content,
            "structured_output": {},
            "usage": result.get("usage") or {},
            "provider_trace": {"adapter": provider.provider_type, "request_id": result.get("id"), "finish_reason": (choices[0] if choices else {}).get("finish_reason")},
        }


def _provider_dict(row: ModelGatewayProvider) -> Dict[str, Any]:
    return {
        "id": row.id, "project_id": row.project_id, "display_name": row.display_name,
        "provider_type": row.provider_type, "base_url": row.base_url,
        "secret_ref": row.secret_ref, "secret_configured": bool(row.secret_ref and os.getenv(row.secret_ref)),
        "allowed_models": row.allowed_models or [], "policy": row.policy or {},
        "configuration": {key: value for key, value in (row.configuration or {}).items() if "secret" not in key.lower() and "token" not in key.lower()},
        "status": row.status, "created_at": row.created_at, "updated_at": row.updated_at,
    }


def _run_dict(row: ModelGatewayRun) -> Dict[str, Any]:
    return {
        "id": row.id, "project_id": row.project_id, "provider_id": row.provider_id,
        "model_name": row.model_name, "status": row.status, "request_hash": row.request_hash,
        "idempotency_key": row.idempotency_key,
        "input_summary": row.input_summary or {}, "output": row.output or {}, "usage": row.usage or {},
        "policy_decision": row.policy_decision or {}, "trace": row.trace or [], "evidence": row.evidence or [],
        "error": row.error, "created_by": row.created_by, "created_at": row.created_at, "completed_at": row.completed_at,
    }


def _provider_for(db: Session, principal: Principal, provider_id: str, permission: str) -> ModelGatewayProvider:
    row = db.get(ModelGatewayProvider, provider_id)
    if not row:
        raise HTTPException(status_code=404, detail="Model gateway provider not found")
    tenancy.assert_project_permission(db, principal, row.project_id, permission)
    return row


def _policy(provider: ModelGatewayProvider, request: GatewayInferenceRequest) -> Dict[str, Any]:
    policy = provider.policy or {}
    reasons = []
    input_chars = sum(len(message.content) for message in request.messages)
    max_input_chars = int(policy.get("max_input_chars", 200_000))
    if input_chars > max_input_chars:
        reasons.append(f"Input contains {input_chars} characters; provider limit is {max_input_chars}")
    allowed_models = set(provider.allowed_models or [])
    if allowed_models and request.model_name not in allowed_models:
        reasons.append("Requested model is not in the provider allowlist")
    if provider.status != "ACTIVE":
        reasons.append("Provider is not active")
    return {
        "status": "DENY" if reasons else "ALLOW",
        "reasons": reasons,
        "input_chars": input_chars,
        "max_input_chars": max_input_chars,
        "external_call": provider.provider_type != "deterministic",
        "action_mode": "PROPOSE_ONLY" if request.proposed_action_type_id else "NONE",
    }


def _ontology_context(db: Session, principal: Principal, project_id: str, refs: List[OntologyObjectReference]) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    context = []
    evidence = []
    for ref in refs:
        obj = semantic_scope.object_for(db, principal, ref.object_id, "view")
        if obj.project_id != project_id or obj.object_type_id != ref.object_type_id:
            raise HTTPException(status_code=409, detail=f"Ontology context object '{ref.object_id}' has incompatible scope")
        properties = dict(obj.properties or {})
        if ref.fields:
            properties = {field: properties.get(field) for field in ref.fields}
        context.append({"object_type_id": obj.object_type_id, "object_id": obj.id, "properties": properties})
        evidence.append({"type": "ontology_object", "id": obj.id, "object_type_id": obj.object_type_id, "updated_at": obj.updated_at})
    return context, evidence


def _request_hash(request: GatewayInferenceRequest, actor: str) -> str:
    payload = request.model_dump(exclude={"idempotency_key"})
    payload["actor"] = actor
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode("utf-8")).hexdigest()


def _adapter(provider: ModelGatewayProvider) -> ModelAdapter:
    if provider.provider_type == "deterministic":
        return DeterministicAdapter()
    return OpenAICompatibleAdapter()


@router.get("/models/gateway/catalog")
@router.get("/api/v1/models/gateway/catalog")
def gateway_catalog():
    return {
        "provider_types": ["deterministic", "openai_compatible", "local_http"],
        "default_provider_type": "deterministic",
        "secret_contract": "Environment variable reference only; secret values are never persisted or returned",
        "action_contract": "Model output may propose ontology actions but cannot directly execute mutations",
    }


@router.post("/models/gateway/providers", status_code=201)
@router.post("/api/v1/models/gateway/providers", status_code=201)
def create_provider(body: ProviderCreate, principal: Principal = Depends(require_permission("administer")), db: Session = Depends(get_db)):
    tenancy.assert_project_permission(db, principal, body.project_id, "administer")
    provider_id = body.id or f"model_provider_{uuid.uuid4().hex}"
    if db.get(ModelGatewayProvider, provider_id):
        raise HTTPException(status_code=409, detail="Model gateway provider already exists")
    if body.provider_type != "deterministic" and not body.base_url:
        raise HTTPException(status_code=422, detail="External and local HTTP providers require base_url")
    if body.provider_type != "deterministic" and not body.secret_ref:
        raise HTTPException(status_code=422, detail="External and local HTTP providers require an environment secret reference")
    if body.base_url:
        try:
            _validate_model_url(body.base_url, resolve=False)
        except RuntimeError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
    now = int(time.time())
    row = ModelGatewayProvider(
        id=provider_id, project_id=body.project_id, display_name=body.display_name,
        provider_type=body.provider_type, base_url=body.base_url, secret_ref=body.secret_ref,
        allowed_models=body.allowed_models, policy=body.policy,
        configuration=body.configuration, status="ACTIVE", created_at=now, updated_at=now,
    )
    db.add(row)
    create_audit_log(
        db, actor=principal.id, event_type="model_gateway.provider.created", subject_type="model_gateway_provider", subject_id=row.id,
        payload={"project_id": row.project_id, "provider_type": row.provider_type, "allowed_models": row.allowed_models},
    )
    db.commit()
    return _provider_dict(row)


@router.get("/models/gateway/providers")
@router.get("/api/v1/models/gateway/providers")
def list_providers(project_id: Optional[str] = None, principal: Principal = Depends(require_permission("view")), db: Session = Depends(get_db)):
    query = semantic_scope.accessible_query(db, principal, ModelGatewayProvider)
    if project_id:
        tenancy.assert_project_permission(db, principal, project_id, "view")
        query = query.filter(ModelGatewayProvider.project_id == project_id)
    rows = query.order_by(ModelGatewayProvider.display_name).all()
    return {"providers": [_provider_dict(row) for row in rows]}


@router.post("/models/gateway/infer")
@router.post("/api/v1/models/gateway/infer")
def infer(body: GatewayInferenceRequest, principal: Principal = Depends(require_permission("execute")), db: Session = Depends(get_db)):
    provider = _provider_for(db, principal, body.provider_id, "execute")
    if provider.project_id != body.project_id:
        raise HTTPException(status_code=409, detail="Provider belongs to another project")
    if body.proposed_action_type_id:
        action = db.get(models.ActionType, body.proposed_action_type_id)
        if not action or action.project_id != body.project_id:
            raise HTTPException(status_code=404, detail="Proposed ontology action type not found")
    request_hash = _request_hash(body, principal.id)
    if body.idempotency_key:
        previous = db.query(ModelGatewayRun).filter(
            ModelGatewayRun.project_id == body.project_id,
            ModelGatewayRun.provider_id == provider.id,
            ModelGatewayRun.created_by == principal.id,
            ModelGatewayRun.idempotency_key == body.idempotency_key,
        ).first()
        if previous:
            if previous.request_hash != request_hash:
                raise HTTPException(status_code=409, detail="Idempotency key was already used with a different inference request")
            if previous.status == "SUCCEEDED":
                return {**_run_dict(previous), "cached": True}
            raise HTTPException(status_code=409, detail={"message": "Idempotent inference already has a terminal or active run", "run_id": previous.id, "status": previous.status})
    context, evidence = _ontology_context(db, principal, body.project_id, body.ontology_objects)
    decision = _policy(provider, body)
    now = int(time.time())
    run = ModelGatewayRun(
        id=f"model_run_{uuid.uuid4().hex}", project_id=body.project_id, provider_id=provider.id,
        model_name=body.model_name, status="RUNNING", request_hash=request_hash,
        idempotency_key=body.idempotency_key,
        input_summary={"message_count": len(body.messages), "input_chars": decision["input_chars"], "ontology_object_count": len(context)},
        output={}, usage={}, policy_decision=decision,
        trace=[{"step": "policy", "status": decision["status"], "at": now}, {"step": "ontology_context", "objects": len(context), "at": now}],
        evidence=evidence, error=None, created_by=principal.id, created_at=now, completed_at=None,
    )
    db.add(run)
    if decision["status"] != "ALLOW":
        run.status = "DENIED"
        run.error = "; ".join(decision["reasons"])
        run.completed_at = int(time.time())
        create_audit_log(db, actor=principal.id, event_type="model_gateway.inference.denied", subject_type="model_gateway_run", subject_id=run.id, payload={"project_id": body.project_id, "policy_decision": decision})
        db.commit()
        raise HTTPException(status_code=403, detail={"message": "Model gateway policy denied inference", "run_id": run.id, "policy_decision": decision})
    try:
        result = _adapter(provider).infer(provider, body, context)
        action_proposal = None
        if body.proposed_action_type_id:
            action_proposal = {"action_type_id": body.proposed_action_type_id, "status": "PROPOSED", "execution_allowed": False, "next_step": "Submit through governed action approval workflow"}
        run.output = {"content": result.get("content", ""), "structured_output": result.get("structured_output") or {}, "action_proposal": action_proposal}
        run.usage = result.get("usage") or {}
        run.trace = [*(run.trace or []), {"step": "provider", "status": "SUCCEEDED", **(result.get("provider_trace") or {}), "at": int(time.time())}]
        run.status = "SUCCEEDED"
        run.completed_at = int(time.time())
        create_audit_log(db, actor=principal.id, event_type="model_gateway.inference.succeeded", subject_type="model_gateway_run", subject_id=run.id, payload={"project_id": body.project_id, "provider_id": provider.id, "model_name": body.model_name, "usage": run.usage, "evidence_count": len(evidence)})
        db.commit()
        return {**_run_dict(run), "cached": False}
    except Exception as exc:
        run.status = "FAILED"
        run.error = str(exc)
        run.completed_at = int(time.time())
        run.trace = [*(run.trace or []), {"step": "provider", "status": "FAILED", "error_type": type(exc).__name__, "at": int(time.time())}]
        create_audit_log(db, actor=principal.id, event_type="model_gateway.inference.failed", subject_type="model_gateway_run", subject_id=run.id, payload={"project_id": body.project_id, "provider_id": provider.id, "error_type": type(exc).__name__})
        db.commit()
        raise HTTPException(status_code=502, detail={"message": "Model provider inference failed", "run_id": run.id, "error": str(exc)}) from exc


@router.get("/models/gateway/runs")
@router.get("/api/v1/models/gateway/runs")
def list_runs(project_id: Optional[str] = None, provider_id: Optional[str] = None, limit: int = 100, principal: Principal = Depends(require_permission("view")), db: Session = Depends(get_db)):
    query = semantic_scope.accessible_query(db, principal, ModelGatewayRun)
    if project_id:
        tenancy.assert_project_permission(db, principal, project_id, "view")
        query = query.filter(ModelGatewayRun.project_id == project_id)
    if provider_id:
        provider = _provider_for(db, principal, provider_id, "view")
        query = query.filter(ModelGatewayRun.provider_id == provider.id, ModelGatewayRun.project_id == provider.project_id)
    rows = query.order_by(ModelGatewayRun.created_at.desc()).limit(max(1, min(limit, 1000))).all()
    return {"runs": [_run_dict(row) for row in rows]}

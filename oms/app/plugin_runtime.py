"""Signed, versioned, project-scoped plugin registry and sandbox execution."""
from __future__ import annotations

import base64
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time
from typing import Any, Dict, List, Optional
import uuid
import zipfile

from .plugin_oci import PLUGIN_SDK_API_VERSION, build_oci_command
from .plugin_egress import normalized_policy, validated_ca_bundle

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Mapped, Session, mapped_column

from . import models_action, tenancy
from .database import Base, get_db
from .production_auth import Principal, require_permission


router = APIRouter(prefix="/api/v1", tags=["plugins"])
PLUGIN_JSON = JSON().with_variant(JSONB(), "postgresql")
PLUGIN_KINDS = {"connector", "transform", "widget", "ontology_package", "model_provider"}
PLUGIN_ID = re.compile(r"^[a-z][a-z0-9_.-]{2,127}$")
PLUGIN_VERSION = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:-[0-9A-Za-z.-]+)?$")
CAPABILITIES = {"network", "scratch_write", "secrets", "ontology_read", "ontology_write", "dataset_read", "dataset_write"}


def _now() -> int:
    return int(time.time())


def _id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:20]}"


class PluginTrustKey(Base):
    __tablename__ = "plugin_trust_keys"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    organization_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    display_name: Mapped[str] = mapped_column(String, nullable=False)
    algorithm: Mapped[str] = mapped_column(String, nullable=False, default="ed25519")
    public_key: Mapped[str] = mapped_column(Text, nullable=False)
    fingerprint: Mapped[str] = mapped_column(String, nullable=False, unique=True, index=True)
    status: Mapped[str] = mapped_column(String, nullable=False, default="ACTIVE", index=True)
    created_by: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[int] = mapped_column(Integer, nullable=False)
    revoked_at: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)


class PluginVersion(Base):
    __tablename__ = "plugin_versions"
    __table_args__ = (
        UniqueConstraint("project_id", "plugin_id", "version", name="uq_plugin_project_version"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True)
    project_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    plugin_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    version: Mapped[str] = mapped_column(String, nullable=False)
    kind: Mapped[str] = mapped_column(String, nullable=False, index=True)
    runtime: Mapped[str] = mapped_column(String, nullable=False)
    entrypoint: Mapped[str] = mapped_column(String, nullable=False)
    manifest: Mapped[dict] = mapped_column(PLUGIN_JSON, nullable=False)
    manifest_sha256: Mapped[str] = mapped_column(String, nullable=False, index=True)
    bundle_sha256: Mapped[str] = mapped_column(String, nullable=False, index=True)
    bundle_path: Mapped[str] = mapped_column(Text, nullable=False)
    signature: Mapped[str] = mapped_column(Text, nullable=False)
    signer_key_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    capabilities: Mapped[list] = mapped_column(PLUGIN_JSON, nullable=False, default=list)
    operations: Mapped[dict] = mapped_column(PLUGIN_JSON, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String, nullable=False, default="VERIFIED", index=True)
    created_by: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[int] = mapped_column(Integer, nullable=False)
    activated_at: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    revoked_at: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)


class PluginExecution(Base):
    __tablename__ = "plugin_executions"
    __table_args__ = (
        UniqueConstraint("project_id", "plugin_version_id", "actor", "idempotency_key", name="uq_plugin_execution_idempotency"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True)
    job_id: Mapped[Optional[str]] = mapped_column(String, nullable=True, unique=True, index=True)
    project_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    plugin_version_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    plugin_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    operation: Mapped[str] = mapped_column(String, nullable=False, index=True)
    status: Mapped[str] = mapped_column(String, nullable=False, index=True)
    request_hash: Mapped[str] = mapped_column(String, nullable=False, index=True)
    idempotency_key: Mapped[Optional[str]] = mapped_column(String, nullable=True, index=True)
    input_summary: Mapped[dict] = mapped_column(PLUGIN_JSON, nullable=False, default=dict)
    output: Mapped[dict] = mapped_column(PLUGIN_JSON, nullable=False, default=dict)
    evidence: Mapped[dict] = mapped_column(PLUGIN_JSON, nullable=False, default=dict)
    sandbox: Mapped[dict] = mapped_column(PLUGIN_JSON, nullable=False, default=dict)
    exit_code: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    duration_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    actor: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[int] = mapped_column(Integer, nullable=False)
    completed_at: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)


class TrustKeyCreate(BaseModel):
    id: Optional[str] = None
    organization_id: str = Field(min_length=1, max_length=200)
    display_name: str = Field(min_length=1, max_length=200)
    public_key: str = Field(min_length=40, max_length=500)


class PluginRegister(BaseModel):
    project_id: str = Field(default="default", min_length=1, max_length=200)
    manifest: Dict[str, Any]
    bundle_base64: str = Field(min_length=1, max_length=14_000_000)
    signer_key_id: str = Field(min_length=1, max_length=200)
    signature: str = Field(min_length=40, max_length=500)


class PluginInvoke(BaseModel):
    operation: str = Field(min_length=1, max_length=120)
    input: Dict[str, Any] = Field(default_factory=dict)
    idempotency_key: Optional[str] = Field(default=None, min_length=1, max_length=200)


class PluginAsyncInvoke(PluginInvoke):
    priority: int = Field(default=50, ge=0, le=100)
    max_attempts: int = Field(default=3, ge=1, le=10)


class PluginWorkerRequest(BaseModel):
    job_id: str = Field(min_length=1, max_length=200)
    lease_token: str = Field(min_length=1, max_length=200)


class PluginWorkerComplete(PluginWorkerRequest):
    output: Dict[str, Any]
    sandbox: Dict[str, Any]
    exit_code: int = Field(default=0, ge=0, le=255)
    duration_ms: int = Field(default=0, ge=0, le=86_400_000)


class PluginWorkerFail(PluginWorkerRequest):
    error: str = Field(min_length=1, max_length=4000)
    retriable: bool = True
    retry_delay_seconds: int = Field(default=5, ge=0, le=86400)
    sandbox: Dict[str, Any] = Field(default_factory=dict)
    duration_ms: int = Field(default=0, ge=0, le=86_400_000)


def canonical_manifest(manifest: Dict[str, Any]) -> bytes:
    return json.dumps(manifest, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")


def _decode_public_key(value: str) -> bytes:
    try:
        raw = base64.b64decode(value, validate=True)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="public_key must be base64-encoded Ed25519 bytes") from exc
    if len(raw) != 32:
        raise HTTPException(status_code=422, detail="Ed25519 public keys must contain 32 bytes")
    return raw


def _decode_signature(value: str) -> bytes:
    try:
        raw = base64.b64decode(value, validate=True)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="signature must be base64 encoded") from exc
    if len(raw) != 64:
        raise HTTPException(status_code=422, detail="Ed25519 signatures must contain 64 bytes")
    return raw


def _bundle_root() -> Path:
    root = Path(os.getenv("PLUGIN_BUNDLE_ROOT", Path(__file__).resolve().parents[2] / "plugin-bundles")).resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root


def _safe_name(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_.-]", "_", value)


def _validate_manifest(manifest: Dict[str, Any], bundle_digest: str) -> Dict[str, Any]:
    errors: List[str] = []
    if manifest.get("schema_version") != 1:
        errors.append("schema_version must be 1")
    if manifest.get("sdk_api_version", PLUGIN_SDK_API_VERSION) != PLUGIN_SDK_API_VERSION:
        errors.append(f"sdk_api_version must be {PLUGIN_SDK_API_VERSION}")
    plugin_id = str(manifest.get("plugin_id") or "")
    version = str(manifest.get("version") or "")
    kind = str(manifest.get("kind") or "")
    runtime = str(manifest.get("runtime") or "")
    entrypoint = str(manifest.get("entrypoint") or "")
    if not PLUGIN_ID.fullmatch(plugin_id):
        errors.append("plugin_id must be a lowercase API name")
    if not PLUGIN_VERSION.fullmatch(version):
        errors.append("version must be semantic major.minor.patch")
    if kind not in PLUGIN_KINDS:
        errors.append(f"kind must be one of {sorted(PLUGIN_KINDS)}")
    if runtime != "python3":
        errors.append("runtime must be python3")
    path = Path(entrypoint)
    if not entrypoint or path.is_absolute() or ".." in path.parts or path.suffix != ".py":
        errors.append("entrypoint must be a relative Python file")
    if str(manifest.get("bundle_sha256") or "").lower() != bundle_digest:
        errors.append("bundle_sha256 does not match uploaded bytes")
    capabilities = [str(value) for value in manifest.get("capabilities") or []]
    unknown = sorted(set(capabilities) - CAPABILITIES)
    if unknown:
        errors.append(f"unknown capabilities: {', '.join(unknown)}")
    if "network" in capabilities:
        try:
            normalized_policy(manifest)
            validated_ca_bundle(manifest)
        except (TypeError, ValueError) as exc:
            errors.append(str(exc))
    elif manifest.get("network_policy"):
        errors.append("network_policy requires the network capability")
    operations = manifest.get("operations") or {}
    if not isinstance(operations, dict) or not operations:
        errors.append("operations must define at least one named operation")
    elif any(not re.fullmatch(r"[a-z][a-z0-9_.-]{0,119}", str(name)) for name in operations):
        errors.append("operation names must be lowercase API names")
    else:
        for operation, contract in operations.items():
            if not isinstance(contract, dict):
                errors.append(f"operations.{operation} must be an object")
                continue
            for schema_name in ("input_schema", "output_schema"):
                schema = contract.get(schema_name, {"type": "object"})
                if not isinstance(schema, dict) or schema.get("type", "object") not in {"object", "array", "string", "integer", "number", "boolean", "null"}:
                    errors.append(f"operations.{operation}.{schema_name} is not a supported schema")
                elif isinstance(schema, dict):
                    errors.extend(_schema_definition_errors(schema, f"operations.{operation}.{schema_name}"))
    limits = manifest.get("limits") or {}
    for name, default, minimum, maximum in (
        ("timeout_seconds", 30, 1, 300), ("memory_mb", 256, 32, 2048),
        ("max_input_bytes", 1_000_000, 1024, 10_000_000), ("max_output_bytes", 1_000_000, 1024, 10_000_000),
    ):
        value = limits.get(name, default)
        if not isinstance(value, int) or not minimum <= value <= maximum:
            errors.append(f"limits.{name} must be between {minimum} and {maximum}")
    if errors:
        raise HTTPException(status_code=422, detail={"message": "Plugin manifest is invalid", "errors": errors})
    return {"plugin_id": plugin_id, "version": version, "kind": kind, "runtime": runtime, "entrypoint": entrypoint, "capabilities": sorted(set(capabilities)), "operations": operations}


def _schema_definition_errors(schema: Dict[str, Any], path: str, depth: int = 0) -> List[str]:
    if depth > 8:
        return [f"{path} exceeds maximum schema depth"]
    errors: List[str] = []
    declared = schema.get("type", "object")
    if "enum" in schema and (not isinstance(schema["enum"], list) or len(schema["enum"]) > 1000):
        errors.append(f"{path}.enum must be an array of at most 1000 values")
    if "pattern" in schema:
        errors.append(f"{path}.pattern is not supported in sandbox contracts")
    if declared == "object":
        properties = schema.get("properties", {})
        required = schema.get("required", [])
        if not isinstance(properties, dict) or len(properties) > 1000:
            errors.append(f"{path}.properties must be an object with at most 1000 fields")
            properties = {}
        if not isinstance(required, list) or any(not isinstance(value, str) for value in required):
            errors.append(f"{path}.required must be an array of field names")
            required = []
        elif any(value not in properties for value in required):
            errors.append(f"{path}.required references an undefined property")
        if "additionalProperties" in schema and not isinstance(schema["additionalProperties"], bool):
            errors.append(f"{path}.additionalProperties must be boolean")
        for name, nested in properties.items():
            if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.-]{0,127}", str(name)) or not isinstance(nested, dict):
                errors.append(f"{path}.properties contains an invalid field")
            else:
                errors.extend(_schema_definition_errors(nested, f"{path}.properties.{name}", depth + 1))
    elif declared == "array" and "items" in schema:
        if not isinstance(schema["items"], dict):
            errors.append(f"{path}.items must be an object")
        else:
            errors.extend(_schema_definition_errors(schema["items"], f"{path}.items", depth + 1))
    for bound in ("minLength", "maxLength"):
        if bound in schema and (not isinstance(schema[bound], int) or not 0 <= schema[bound] <= 10_000_000):
            errors.append(f"{path}.{bound} must be a bounded non-negative integer")
    for bound in ("minimum", "maximum"):
        if bound in schema and (not isinstance(schema[bound], (int, float)) or isinstance(schema[bound], bool)):
            errors.append(f"{path}.{bound} must be numeric")
    return errors


def _validate_value(value: Any, schema: Dict[str, Any], path: str = "$") -> List[str]:
    errors: List[str] = []
    declared = schema.get("type", "object")
    matches = {
        "object": isinstance(value, dict),
        "array": isinstance(value, list),
        "string": isinstance(value, str),
        "integer": isinstance(value, int) and not isinstance(value, bool),
        "number": isinstance(value, (int, float)) and not isinstance(value, bool),
        "boolean": isinstance(value, bool),
        "null": value is None,
    }.get(declared, False)
    if not matches:
        return [f"{path} must be {declared}"]
    if "enum" in schema and value not in schema["enum"]:
        errors.append(f"{path} is not an allowed value")
    if declared == "object":
        properties = schema.get("properties") or {}
        required = schema.get("required") or []
        for name in required:
            if name not in value:
                errors.append(f"{path}.{name} is required")
        if schema.get("additionalProperties") is False:
            for name in value:
                if name not in properties:
                    errors.append(f"{path}.{name} is not allowed")
        for name, nested in properties.items():
            if name in value and isinstance(nested, dict):
                errors.extend(_validate_value(value[name], nested, f"{path}.{name}"))
    elif declared == "array" and isinstance(schema.get("items"), dict):
        for index, item in enumerate(value):
            errors.extend(_validate_value(item, schema["items"], f"{path}[{index}]"))
    elif declared == "string":
        if "minLength" in schema and len(value) < int(schema["minLength"]):
            errors.append(f"{path} is shorter than minLength")
        if "maxLength" in schema and len(value) > int(schema["maxLength"]):
            errors.append(f"{path} exceeds maxLength")
        if schema.get("pattern") and not re.fullmatch(str(schema["pattern"]), value):
            errors.append(f"{path} does not match pattern")
    elif declared in {"integer", "number"}:
        if "minimum" in schema and value < schema["minimum"]:
            errors.append(f"{path} is below minimum")
        if "maximum" in schema and value > schema["maximum"]:
            errors.append(f"{path} exceeds maximum")
    return errors


def _validate_zip(raw: bytes, entrypoint: str) -> None:
    maximum = int(os.getenv("PLUGIN_BUNDLE_MAX_BYTES", "10485760"))
    if len(raw) > maximum:
        raise HTTPException(status_code=413, detail="Plugin bundle exceeds configured size limit")
    try:
        with zipfile.ZipFile(__import__("io").BytesIO(raw)) as archive:
            members = archive.infolist()
            if len(members) > 1000:
                raise HTTPException(status_code=422, detail="Plugin bundle contains too many files")
            total = 0
            names = set()
            for member in members:
                path = Path(member.filename)
                if path.is_absolute() or ".." in path.parts or any(":" in part for part in path.parts) or member.filename.startswith(("/", "\\")):
                    raise HTTPException(status_code=422, detail="Plugin bundle contains an unsafe path")
                if path.as_posix() in names:
                    raise HTTPException(status_code=422, detail="Plugin bundle contains a duplicate path")
                if (member.external_attr >> 16) & 0o170000 == 0o120000:
                    raise HTTPException(status_code=422, detail="Plugin bundle symbolic links are not allowed")
                total += member.file_size
                names.add(path.as_posix())
            if total > maximum * 4:
                raise HTTPException(status_code=413, detail="Expanded plugin bundle exceeds configured size limit")
            if Path(entrypoint).as_posix() not in names:
                raise HTTPException(status_code=422, detail="Plugin entrypoint is absent from the bundle")
    except zipfile.BadZipFile as exc:
        raise HTTPException(status_code=422, detail="Plugin bundle is not a valid ZIP archive") from exc


def _audit(db: Session, principal: Principal, event_type: str, subject_id: str, payload: Dict[str, Any]) -> None:
    db.add(models_action.AuditLog(id=str(uuid.uuid4()), actor=principal.id, event_type=event_type, subject_type="plugin", subject_id=subject_id, payload=payload, created_at=_now()))


def _trust_key(db: Session, key_id: str) -> PluginTrustKey:
    row = db.get(PluginTrustKey, key_id)
    if not row:
        raise HTTPException(status_code=404, detail="Plugin trust key not found")
    return row


def _plugin(db: Session, version_id: str, principal: Principal, permission: str) -> PluginVersion:
    row = db.get(PluginVersion, version_id)
    if not row:
        raise HTTPException(status_code=404, detail="Plugin version not found")
    tenancy.assert_project_permission(db, principal, row.project_id, permission)
    return row


def _plugin_dict(row: PluginVersion) -> Dict[str, Any]:
    return {"id": row.id, "project_id": row.project_id, "plugin_id": row.plugin_id, "version": row.version, "kind": row.kind, "runtime": row.runtime, "entrypoint": row.entrypoint, "manifest_sha256": row.manifest_sha256, "bundle_sha256": row.bundle_sha256, "signer_key_id": row.signer_key_id, "capabilities": row.capabilities or [], "operations": row.operations or {}, "status": row.status, "created_by": row.created_by, "created_at": row.created_at, "activated_at": row.activated_at, "revoked_at": row.revoked_at}


def _execution_dict(row: PluginExecution) -> Dict[str, Any]:
    return {"id": row.id, "job_id": row.job_id, "project_id": row.project_id, "plugin_version_id": row.plugin_version_id, "plugin_id": row.plugin_id, "operation": row.operation, "status": row.status, "request_hash": row.request_hash, "idempotency_key": row.idempotency_key, "input_summary": row.input_summary or {}, "output": row.output or {}, "evidence": row.evidence or {}, "sandbox": row.sandbox or {}, "exit_code": row.exit_code, "duration_ms": row.duration_ms, "error": row.error, "actor": row.actor, "created_at": row.created_at, "completed_at": row.completed_at}


@router.post("/plugins/trust-keys", status_code=201)
def create_trust_key(body: TrustKeyCreate, principal: Principal = Depends(require_permission("administer")), db: Session = Depends(get_db)):
    if principal.organization_id and principal.organization_id != body.organization_id:
        raise HTTPException(status_code=403, detail="Plugin trust keys must belong to the authenticated organization")
    raw = _decode_public_key(body.public_key)
    key_id = body.id or _id("plugin_key")
    if db.get(PluginTrustKey, key_id):
        raise HTTPException(status_code=409, detail="Plugin trust key already exists")
    fingerprint = hashlib.sha256(raw).hexdigest()
    if db.query(PluginTrustKey).filter(PluginTrustKey.fingerprint == fingerprint).first():
        raise HTTPException(status_code=409, detail="Plugin trust key fingerprint already exists")
    row = PluginTrustKey(id=key_id, organization_id=body.organization_id, display_name=body.display_name, algorithm="ed25519", public_key=body.public_key, fingerprint=fingerprint, status="ACTIVE", created_by=principal.id, created_at=_now(), revoked_at=None)
    db.add(row)
    _audit(db, principal, "plugin.trust_key.created", row.id, {"organization_id": row.organization_id, "fingerprint": fingerprint})
    db.commit()
    return {"id": row.id, "organization_id": row.organization_id, "display_name": row.display_name, "algorithm": row.algorithm, "fingerprint": row.fingerprint, "status": row.status, "created_at": row.created_at}


@router.post("/plugins/trust-keys/{key_id}/revoke")
def revoke_trust_key(key_id: str, principal: Principal = Depends(require_permission("administer")), db: Session = Depends(get_db)):
    row = _trust_key(db, key_id)
    if principal.organization_id and principal.organization_id != row.organization_id:
        raise HTTPException(status_code=403, detail="Plugin trust key belongs to another organization")
    row.status = "REVOKED"
    row.revoked_at = _now()
    affected = db.query(PluginVersion).filter(PluginVersion.signer_key_id == key_id, PluginVersion.status != "REVOKED").all()
    for plugin in affected:
        plugin.status = "REVOKED"
        plugin.revoked_at = row.revoked_at
    _audit(db, principal, "plugin.trust_key.revoked", row.id, {"revoked_plugin_versions": [item.id for item in affected]})
    db.commit()
    return {"id": row.id, "status": row.status, "revoked_plugin_versions": len(affected)}


@router.post("/plugins/register", status_code=201)
def register_plugin(body: PluginRegister, principal: Principal = Depends(require_permission("administer")), db: Session = Depends(get_db)):
    tenancy.assert_project_permission(db, principal, body.project_id, "administer")
    key = _trust_key(db, body.signer_key_id)
    if key.status != "ACTIVE":
        raise HTTPException(status_code=409, detail="Plugin trust key is not active")
    project = db.get(tenancy.PlatformProject, body.project_id)
    if project and project.organization_id != key.organization_id:
        raise HTTPException(status_code=403, detail="Plugin trust key belongs to another organization")
    if len(canonical_manifest(body.manifest)) > 1_000_000:
        raise HTTPException(status_code=413, detail="Plugin manifest exceeds one megabyte")
    try:
        raw = base64.b64decode(body.bundle_base64, validate=True)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="bundle_base64 is invalid") from exc
    bundle_digest = hashlib.sha256(raw).hexdigest()
    parsed = _validate_manifest(body.manifest, bundle_digest)
    _validate_zip(raw, parsed["entrypoint"])
    manifest_bytes = canonical_manifest(body.manifest)
    try:
        Ed25519PublicKey.from_public_bytes(_decode_public_key(key.public_key)).verify(_decode_signature(body.signature), manifest_bytes)
    except InvalidSignature as exc:
        raise HTTPException(status_code=422, detail="Plugin manifest signature is invalid") from exc
    existing = db.query(PluginVersion).filter(PluginVersion.project_id == body.project_id, PluginVersion.plugin_id == parsed["plugin_id"], PluginVersion.version == parsed["version"]).first()
    if existing:
        raise HTTPException(status_code=409, detail="Plugin version is immutable and already registered")
    target_dir = _bundle_root() / _safe_name(body.project_id) / parsed["plugin_id"] / parsed["version"]
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / f"{bundle_digest}.zip"
    temporary = target.with_suffix(".tmp")
    temporary.write_bytes(raw)
    os.replace(temporary, target)
    now = _now()
    row = PluginVersion(id=_id("plugin_version"), project_id=body.project_id, plugin_id=parsed["plugin_id"], version=parsed["version"], kind=parsed["kind"], runtime=parsed["runtime"], entrypoint=parsed["entrypoint"], manifest=body.manifest, manifest_sha256=hashlib.sha256(manifest_bytes).hexdigest(), bundle_sha256=bundle_digest, bundle_path=str(target), signature=body.signature, signer_key_id=key.id, capabilities=parsed["capabilities"], operations=parsed["operations"], status="VERIFIED", created_by=principal.id, created_at=now, activated_at=None, revoked_at=None)
    db.add(row)
    _audit(db, principal, "plugin.version.registered", row.id, {"project_id": row.project_id, "plugin_id": row.plugin_id, "version": row.version, "kind": row.kind, "manifest_sha256": row.manifest_sha256, "bundle_sha256": row.bundle_sha256, "signer_fingerprint": key.fingerprint})
    db.commit()
    return _plugin_dict(row)


@router.post("/plugins/{version_id}/activate")
def activate_plugin(version_id: str, principal: Principal = Depends(require_permission("administer")), db: Session = Depends(get_db)):
    row = _plugin(db, version_id, principal, "administer")
    key = _trust_key(db, row.signer_key_id)
    if key.status != "ACTIVE" or row.status == "REVOKED":
        raise HTTPException(status_code=409, detail="Plugin or signing key is revoked")
    for current in db.query(PluginVersion).filter(PluginVersion.project_id == row.project_id, PluginVersion.plugin_id == row.plugin_id, PluginVersion.status == "ACTIVE").all():
        current.status = "SUPERSEDED"
    row.status = "ACTIVE"
    row.activated_at = _now()
    _audit(db, principal, "plugin.version.activated", row.id, {"project_id": row.project_id, "plugin_id": row.plugin_id, "version": row.version})
    db.commit()
    return _plugin_dict(row)


@router.get("/plugins/catalog")
def plugin_catalog(project_id: str = Query(default="default"), kind: Optional[str] = Query(default=None), principal: Principal = Depends(require_permission("view")), db: Session = Depends(get_db)):
    tenancy.assert_project_permission(db, principal, project_id, "view")
    query = db.query(PluginVersion).filter(PluginVersion.project_id == project_id, PluginVersion.status == "ACTIVE")
    if kind:
        if kind not in PLUGIN_KINDS:
            raise HTTPException(status_code=422, detail="Unknown plugin kind")
        query = query.filter(PluginVersion.kind == kind)
    rows = query.order_by(PluginVersion.kind, PluginVersion.plugin_id, PluginVersion.version).all()
    return {
        "project_id": project_id,
        "plugins": [_plugin_dict(row) for row in rows],
        "kinds": sorted(PLUGIN_KINDS),
        "runtime": "signed_sandbox_v1",
        "sdk_api_version": PLUGIN_SDK_API_VERSION,
    }


def _bundle_bytes(row: PluginVersion) -> bytes:
    source = Path(row.bundle_path).resolve()
    root = _bundle_root()
    if root not in source.parents or not source.is_file():
        raise RuntimeError("Registered plugin bundle is unavailable")
    raw = source.read_bytes()
    if hashlib.sha256(raw).hexdigest() != row.bundle_sha256:
        raise RuntimeError("Registered plugin bundle failed integrity verification")
    _validate_zip(raw, row.entrypoint)
    return raw


def _extract_bundle(row: PluginVersion, target: Path) -> None:
    raw = _bundle_bytes(row)
    with zipfile.ZipFile(__import__("io").BytesIO(raw)) as archive:
        archive.extractall(target)


def _sandbox_mode() -> str:
    configured = os.getenv("PLUGIN_SANDBOX_MODE", "").strip().lower()
    if configured:
        if configured not in {"process", "oci"}:
            raise RuntimeError("PLUGIN_SANDBOX_MODE must be process or oci")
        return configured
    return "oci" if os.getenv("APP_ENV", "development").lower() == "production" else "process"


def _process_command(bundle: Path, scratch: Path, row: PluginVersion, envelope: Dict[str, Any]) -> tuple[list[str], Dict[str, str], Dict[str, Any]]:
    runner = Path(__file__).with_name("plugin_sandbox_runner.py").resolve()
    command = [sys.executable, "-I", str(runner)]
    environment = {key: value for key, value in os.environ.items() if key.upper() in {"PATH", "SYSTEMROOT", "WINDIR", "COMSPEC", "TMP", "TEMP"}}
    sandbox = {"mode": "process", "network": "audit-denied" if "network" not in (row.capabilities or []) else "allowed", "filesystem": "bundle-readonly/scratch-write", "production_allowed": False}
    return command, environment, sandbox


def _oci_command(bundle: Path, scratch: Path, row: PluginVersion, envelope: Dict[str, Any]) -> tuple[list[str], Dict[str, str], Dict[str, Any]]:
    return build_oci_command(
        manifest=row.manifest,
        capabilities=row.capabilities or [],
        production=os.getenv("APP_ENV", "development").lower() == "production",
    )


def _run(row: PluginVersion, operation: str, input_value: Dict[str, Any]) -> tuple[Dict[str, Any], Dict[str, Any], int]:
    limits = row.manifest.get("limits") or {}
    timeout = int(limits.get("timeout_seconds", 30))
    max_output = int(limits.get("max_output_bytes", 1_000_000))
    mode = _sandbox_mode()
    if mode == "process" and os.getenv("APP_ENV", "development").lower() == "production":
        raise RuntimeError("Process plugin sandbox is disabled in production")
    with tempfile.TemporaryDirectory(prefix="ontologyos-plugin-") as directory:
        root = Path(directory)
        bundle = root / "bundle"
        scratch = root / "scratch"
        bundle.mkdir()
        scratch.mkdir()
        _extract_bundle(row, bundle)
        ca_bundle, _ = validated_ca_bundle(row.manifest)
        envelope = {"bundle_root": str(bundle), "scratch_root": str(scratch), "entrypoint": row.entrypoint, "capabilities": row.capabilities or [], "operation": operation, "input": input_value, "sdk_api_version": PLUGIN_SDK_API_VERSION}
        if ca_bundle:
            envelope["tls_ca_bundle_pem"] = ca_bundle
        if mode == "process":
            command, environment, sandbox = _process_command(bundle, scratch, row, envelope)
            stdin = json.dumps(envelope, separators=(",", ":"))
        else:
            command, environment, sandbox = _oci_command(bundle, scratch, row, envelope)
            bundle_bytes = Path(row.bundle_path).read_bytes()
            stdin = json.dumps({**envelope, "bundle_root": "/scratch/bundle", "scratch_root": "/scratch", "bundle_base64": base64.b64encode(bundle_bytes).decode("ascii"), "bundle_sha256": row.bundle_sha256}, separators=(",", ":"))
        try:
            completed = subprocess.run(command, input=stdin, text=True, capture_output=True, timeout=timeout, env=environment, cwd=str(scratch), check=False)
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(f"Plugin exceeded {timeout}-second execution limit") from exc
        stdout = completed.stdout.encode("utf-8", errors="replace")
        stderr = completed.stderr.encode("utf-8", errors="replace")
        if len(stdout) > max_output or len(stderr) > max_output:
            raise RuntimeError("Plugin exceeded output size limit")
        try:
            result = json.loads(completed.stdout or "{}")
        except json.JSONDecodeError as exc:
            raise RuntimeError("Plugin returned invalid JSON") from exc
        if completed.returncode != 0 or not result.get("ok", completed.returncode == 0):
            message = str(result.get("error") or completed.stderr or f"exit code {completed.returncode}")[:2000]
            raise RuntimeError(f"Plugin execution failed: {message}")
        output = result.get("output", result)
        if not isinstance(output, dict):
            raise RuntimeError("Plugin output must be an object")
        return output, sandbox, completed.returncode


def _validate_invocation(row: PluginVersion, body: PluginInvoke, db: Session) -> tuple[Dict[str, Any], bytes, str]:
    if row.status != "ACTIVE":
        raise HTTPException(status_code=409, detail="Plugin version is not active")
    key = _trust_key(db, row.signer_key_id)
    if key.status != "ACTIVE":
        raise HTTPException(status_code=409, detail="Plugin signing key is revoked")
    if body.operation not in (row.operations or {}):
        raise HTTPException(status_code=422, detail="Plugin operation is not declared by the manifest")
    operation_contract = (row.operations or {}).get(body.operation) or {}
    input_errors = _validate_value(body.input, operation_contract.get("input_schema") or {"type": "object"})
    if input_errors:
        raise HTTPException(status_code=422, detail={"message": "Plugin input violates its signed contract", "errors": input_errors})
    raw_input = json.dumps(body.input, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    limit = int((row.manifest.get("limits") or {}).get("max_input_bytes", 1_000_000))
    if len(raw_input) > limit:
        raise HTTPException(status_code=413, detail="Plugin input exceeds manifest limit")
    request_hash = hashlib.sha256(canonical_manifest({"operation": body.operation, "input": body.input})).hexdigest()
    return operation_contract, raw_input, request_hash


def _idempotent_execution(db: Session, row: PluginVersion, principal: Principal, body: PluginInvoke, request_hash: str) -> Optional[PluginExecution]:
    if not body.idempotency_key:
        return None
    existing = db.query(PluginExecution).filter(
        PluginExecution.project_id == row.project_id,
        PluginExecution.plugin_version_id == row.id,
        PluginExecution.actor == principal.id,
        PluginExecution.idempotency_key == body.idempotency_key,
    ).first()
    if existing and existing.request_hash != request_hash:
        raise HTTPException(status_code=409, detail="Idempotency key was used with different plugin input")
    return existing


def _queue_plugin_execution(row: PluginVersion, body: PluginAsyncInvoke, principal: Principal, db: Session) -> PluginExecution:
    _, raw_input, request_hash = _validate_invocation(row, body, db)
    existing = _idempotent_execution(db, row, principal, body, request_hash)
    if existing:
        return existing

    from . import platform_runtime, runtime_observability

    limits = row.manifest.get("limits") or {}
    timeout = int(limits.get("timeout_seconds", 30)) + 30
    estimates = {"compute_seconds": float(timeout), "estimated_cost_usd": 0.0, "token_units": 0.0, "record_units": 0.0}
    admission = runtime_observability.check_job_admission(db, row.project_id, estimates)
    now = _now()
    execution = PluginExecution(
        id=_id("plugin_run"), job_id=None, project_id=row.project_id, plugin_version_id=row.id,
        plugin_id=row.plugin_id, operation=body.operation, status="QUEUED", request_hash=request_hash,
        idempotency_key=body.idempotency_key, input_summary={"bytes": len(raw_input), "keys": sorted(body.input)},
        output={}, evidence={"manifest_sha256": row.manifest_sha256, "bundle_sha256": row.bundle_sha256, "signer_key_id": row.signer_key_id},
        sandbox={}, exit_code=None, duration_ms=0, error=None, actor=principal.id, created_at=now, completed_at=None,
    )
    db.add(execution)
    db.flush()
    job = platform_runtime.PlatformJob(
        id=_id("job"), project_id=row.project_id, job_type="plugin.execute", status="QUEUED",
        actor=principal.id, subject_type="plugin_execution", subject_id=execution.id,
        payload={
            "execution_id": execution.id,
            "plugin_version_id": row.id,
            "operation": body.operation,
            "input": body.input,
            "__execution": {
                "priority": body.priority,
                "max_attempts": body.max_attempts,
                "timeout_seconds": timeout,
                "available_at": now,
                "idempotency_key": body.idempotency_key,
            },
        },
        result={}, attempt=1, progress=0, created_at=now, updated_at=now,
        started_at=None, completed_at=None,
    )
    db.add(job)
    db.flush()
    execution.job_id = job.id
    execution.evidence = {**execution.evidence, "job_id": job.id, "execution_mode": "worker"}
    runtime_observability.record_job_queued(db, job, estimates, admission)
    platform_runtime._job_event(db, job, "job.queued", {"priority": body.priority, "available_at": now})
    platform_runtime._audit(db, principal.id, "job.queued", "platform_job", job.id, {"job_type": job.job_type, "priority": body.priority})
    _audit(db, principal, "plugin.execution.queued", execution.id, {
        "project_id": row.project_id, "plugin_version_id": row.id, "plugin_id": row.plugin_id,
        "operation": body.operation, "request_hash": request_hash, "job_id": job.id,
    })
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        replay = _idempotent_execution(db, row, principal, body, request_hash)
        if replay:
            return replay
        raise
    db.refresh(execution)
    return execution


def sync_execution_from_job(db: Session, job: Any) -> None:
    """Keep plugin evidence aligned when generic job recovery changes state."""
    if getattr(job, "job_type", None) != "plugin.execute":
        return
    execution = db.query(PluginExecution).filter(PluginExecution.job_id == job.id).first()
    if not execution:
        return
    if job.status == "QUEUED":
        execution.status = "QUEUED"
        execution.error = job.error
        execution.completed_at = None
    elif job.status in {"FAILED", "CANCELLED"}:
        execution.status = job.status
        execution.error = job.error or ("Cancelled by user" if job.status == "CANCELLED" else "Worker execution failed")
        execution.completed_at = job.completed_at or _now()


def _worker_context(db: Session, principal: Principal, body: PluginWorkerRequest):
    from . import platform_runtime
    job = platform_runtime._authorized_job(db, principal, body.job_id, "execute")
    if job.job_type != "plugin.execute" or job.subject_type != "plugin_execution":
        raise HTTPException(status_code=409, detail="Job is not a plugin execution")
    if job.status != "RUNNING":
        raise HTTPException(status_code=409, detail="Plugin job is not running")
    lease = platform_runtime._require_job_lease(db, job, body.lease_token)
    execution = db.get(PluginExecution, job.subject_id)
    if not execution or execution.job_id != job.id:
        raise HTTPException(status_code=409, detail="Plugin job references missing execution evidence")
    row = db.get(PluginVersion, execution.plugin_version_id)
    if not row:
        raise HTTPException(status_code=409, detail="Plugin version is unavailable")
    return job, lease, execution, row


@router.post("/plugins/{version_id}/invoke-async", status_code=202)
def invoke_plugin_async(version_id: str, body: PluginAsyncInvoke, principal: Principal = Depends(require_permission("execute")), db: Session = Depends(get_db)):
    row = _plugin(db, version_id, principal, "execute")
    return _execution_dict(_queue_plugin_execution(row, body, principal, db))


@router.get("/plugins/executions/{execution_id}")
def get_plugin_execution(execution_id: str, principal: Principal = Depends(require_permission("view")), db: Session = Depends(get_db)):
    execution = db.get(PluginExecution, execution_id)
    if not execution:
        raise HTTPException(status_code=404, detail="Plugin execution not found")
    tenancy.assert_project_permission(db, principal, execution.project_id, "view")
    return _execution_dict(execution)


@router.post("/plugins/workers/work")
def plugin_worker_work(body: PluginWorkerRequest, principal: Principal = Depends(require_permission("execute")), db: Session = Depends(get_db)):
    job, lease, execution, row = _worker_context(db, principal, body)
    if row.status != "ACTIVE" or _trust_key(db, row.signer_key_id).status != "ACTIVE":
        raise HTTPException(status_code=409, detail="Plugin or signing key was revoked after queueing")
    raw = _bundle_bytes(row)
    execution.status = "RUNNING"
    execution.error = None
    execution.evidence = {**(execution.evidence or {}), "worker_id": lease.worker_id, "attempt": job.attempt}
    db.commit()
    return {
        "execution_id": execution.id,
        "job_id": job.id,
        "plugin_version_id": row.id,
        "operation": execution.operation,
        "input": (job.payload or {}).get("input") or {},
        "manifest": row.manifest,
        "entrypoint": row.entrypoint,
        "capabilities": row.capabilities or [],
        "bundle_base64": base64.b64encode(raw).decode("ascii"),
        "bundle_sha256": row.bundle_sha256,
        "sdk_api_version": PLUGIN_SDK_API_VERSION,
    }


@router.post("/plugins/workers/complete")
def plugin_worker_complete(body: PluginWorkerComplete, principal: Principal = Depends(require_permission("execute")), db: Session = Depends(get_db)):
    from . import platform_runtime, runtime_observability
    existing_job = platform_runtime._authorized_job(db, principal, body.job_id, "execute")
    existing_execution = db.query(PluginExecution).filter(PluginExecution.job_id == existing_job.id).first()
    if existing_job.status == "SUCCEEDED" and existing_execution and existing_execution.status == "SUCCEEDED":
        completion_hash = hashlib.sha256(canonical_manifest(body.output)).hexdigest()
        if (existing_execution.evidence or {}).get("completion_hash") != completion_hash:
            raise HTTPException(status_code=409, detail="Plugin job already completed with different output")
        return _execution_dict(existing_execution)
    job, lease, execution, row = _worker_context(db, principal, body)
    contract = (row.operations or {}).get(execution.operation) or {}
    output_errors = _validate_value(body.output, contract.get("output_schema") or {"type": "object"})
    if output_errors:
        raise HTTPException(status_code=422, detail={"message": "Plugin output violates its signed contract", "errors": output_errors})
    maximum = int((row.manifest.get("limits") or {}).get("max_output_bytes", 1_000_000))
    if len(canonical_manifest(body.output)) > maximum:
        raise HTTPException(status_code=413, detail="Plugin output exceeds manifest limit")
    now = _now()
    completion_hash = hashlib.sha256(canonical_manifest(body.output)).hexdigest()
    execution.status = "SUCCEEDED"
    execution.output = body.output
    execution.sandbox = body.sandbox
    execution.exit_code = body.exit_code
    execution.duration_ms = body.duration_ms
    execution.error = None
    execution.completed_at = now
    execution.evidence = {**(execution.evidence or {}), "completion_hash": completion_hash, "worker_id": lease.worker_id}
    job.status = "SUCCEEDED"
    job.progress = 100
    job.result = {"execution_id": execution.id, "completion_hash": completion_hash}
    job.error = None
    job.updated_at = job.completed_at = now
    platform_runtime._job_event(db, job, "job.succeeded", {"worker_id": lease.worker_id, "duration_seconds": max(0, now - (job.started_at or now))})
    runtime_observability.record_job_terminal(db, job, "SUCCEEDED", job.result)
    platform_runtime._release_job_lease(db, job.id)
    platform_runtime._audit(db, principal.id, "job.succeeded", "platform_job", job.id, {"job_type": job.job_type, "attempt": job.attempt})
    _audit(db, principal, "plugin.execution.succeeded", execution.id, {
        "project_id": row.project_id, "plugin_version_id": row.id, "plugin_id": row.plugin_id,
        "operation": execution.operation, "job_id": job.id, "sandbox": body.sandbox,
        "duration_ms": body.duration_ms, "completion_hash": completion_hash,
    })
    db.commit()
    return _execution_dict(execution)


@router.post("/plugins/workers/fail")
def plugin_worker_fail(body: PluginWorkerFail, principal: Principal = Depends(require_permission("execute")), db: Session = Depends(get_db)):
    from . import platform_runtime, runtime_observability
    existing_job = platform_runtime._authorized_job(db, principal, body.job_id, "execute")
    existing_execution = db.query(PluginExecution).filter(PluginExecution.job_id == existing_job.id).first()
    if existing_execution and existing_execution.error == body.error and existing_job.status in {"QUEUED", "FAILED"}:
        return _execution_dict(existing_execution)
    job, lease, execution, row = _worker_context(db, principal, body)
    now = _now()
    max_attempts = int(platform_runtime._execution(job).get("max_attempts", 3))
    platform_runtime._release_job_lease(db, job.id)
    execution.error = body.error
    execution.sandbox = body.sandbox
    execution.duration_ms = body.duration_ms
    job.error = body.error
    job.updated_at = now
    if body.retriable and job.attempt < max_attempts:
        job.status = execution.status = "QUEUED"
        job.attempt += 1
        job.progress = 0
        job.started_at = None
        execution.completed_at = None
        platform_runtime._set_execution(job, available_at=now + body.retry_delay_seconds)
        platform_runtime._job_event(db, job, "job.retry_scheduled", {"worker_id": lease.worker_id, "attempt": job.attempt, "available_at": now + body.retry_delay_seconds, "error": body.error})
    else:
        job.status = execution.status = "FAILED"
        job.completed_at = execution.completed_at = now
        platform_runtime._job_event(db, job, "job.failed", {"worker_id": lease.worker_id, "attempt": job.attempt, "error": body.error})
    runtime_observability.record_job_terminal(db, job, job.status, {"execution_id": execution.id}, body.error)
    platform_runtime._audit(db, principal.id, "job.failed" if job.status == "FAILED" else "job.retry_scheduled", "platform_job", job.id, {"job_type": job.job_type, "attempt": job.attempt})
    _audit(db, principal, f"plugin.execution.{execution.status.lower()}", execution.id, {"job_id": job.id, "attempt": job.attempt, "error": body.error, "retriable": body.retriable})
    db.commit()
    return _execution_dict(execution)


@router.post("/plugins/{version_id}/invoke")
def invoke_plugin(version_id: str, body: PluginInvoke, principal: Principal = Depends(require_permission("execute")), db: Session = Depends(get_db)):
    row = _plugin(db, version_id, principal, "execute")
    if os.getenv("PLUGIN_EXECUTION_MODE", "direct").strip().lower() == "worker":
        queued = PluginAsyncInvoke(operation=body.operation, input=body.input, idempotency_key=body.idempotency_key)
        return _execution_dict(_queue_plugin_execution(row, queued, principal, db))
    operation_contract, raw_input, request_hash = _validate_invocation(row, body, db)
    existing = _idempotent_execution(db, row, principal, body, request_hash)
    if existing:
        return _execution_dict(existing)
    execution = PluginExecution(id=_id("plugin_run"), job_id=None, project_id=row.project_id, plugin_version_id=row.id, plugin_id=row.plugin_id, operation=body.operation, status="RUNNING", request_hash=request_hash, idempotency_key=body.idempotency_key, input_summary={"bytes": len(raw_input), "keys": sorted(body.input)}, output={}, evidence={"manifest_sha256": row.manifest_sha256, "bundle_sha256": row.bundle_sha256, "signer_key_id": row.signer_key_id, "execution_mode": "direct"}, sandbox={}, exit_code=None, duration_ms=0, error=None, actor=principal.id, created_at=_now(), completed_at=None)
    db.add(execution)
    db.flush()
    started = time.perf_counter()
    try:
        output, sandbox, exit_code = _run(row, body.operation, body.input)
        output_errors = _validate_value(output, operation_contract.get("output_schema") or {"type": "object"})
        if output_errors:
            raise RuntimeError(f"Plugin output violates its signed contract: {'; '.join(output_errors)}")
        execution.status = "SUCCEEDED"
        execution.output = output
        execution.sandbox = sandbox
        execution.exit_code = exit_code
    except Exception as exc:
        execution.status = "FAILED"
        execution.error = f"{type(exc).__name__}: {exc}"[:4000]
        execution.sandbox = {"mode": _sandbox_mode()}
    execution.duration_ms = max(0, int((time.perf_counter() - started) * 1000))
    execution.completed_at = _now()
    _audit(db, principal, f"plugin.execution.{execution.status.lower()}", execution.id, {"project_id": row.project_id, "plugin_version_id": row.id, "plugin_id": row.plugin_id, "operation": body.operation, "status": execution.status, "request_hash": request_hash, "sandbox": execution.sandbox, "duration_ms": execution.duration_ms})
    db.commit()
    db.refresh(execution)
    if execution.status == "FAILED":
        raise HTTPException(status_code=502, detail={"message": "Plugin execution failed", "execution_id": execution.id, "error": execution.error})
    return _execution_dict(execution)


@router.get("/plugins/{version_id}/executions")
def list_plugin_executions(version_id: str, limit: int = Query(default=50, ge=1, le=500), principal: Principal = Depends(require_permission("view")), db: Session = Depends(get_db)):
    row = _plugin(db, version_id, principal, "view")
    executions = db.query(PluginExecution).filter(PluginExecution.plugin_version_id == row.id, PluginExecution.project_id == row.project_id).order_by(PluginExecution.created_at.desc(), PluginExecution.id.desc()).limit(limit).all()
    return {"plugin_version_id": row.id, "executions": [_execution_dict(item) for item in executions]}

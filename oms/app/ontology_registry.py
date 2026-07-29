"""Immutable ontology schema registry and typed client generation."""
from __future__ import annotations

import hashlib
import json
import keyword
import re
import time
import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import JSON, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, Session, mapped_column

from . import models_action, ontology_versioning, tenancy
from .database import Base, get_db
from .production_auth import Principal, require_permission

router = APIRouter(tags=["ontology-registry"])
SEMVER = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:-[0-9A-Za-z.-]+)?$")
IDENTIFIER = re.compile(r"^[A-Za-z_$][A-Za-z0-9_$]*$")


class OntologyRegistryEntry(Base):
    __tablename__ = "ontology_registry_entries"
    __table_args__ = (
        UniqueConstraint("project_id", "channel", "version", name="uq_ontology_registry_project_channel_version"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, index=True)
    project_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    channel: Mapped[str] = mapped_column(String, nullable=False, index=True)
    version: Mapped[str] = mapped_column(String, nullable=False, index=True)
    revision_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    revision_number: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, default="PUBLISHED", index=True)
    manifest: Mapped[dict] = mapped_column(JSON, nullable=False)
    contract_schema: Mapped[dict] = mapped_column(JSON, nullable=False)
    compatibility: Mapped[dict] = mapped_column(JSON, nullable=False)
    checksum: Mapped[str] = mapped_column(String, nullable=False, index=True)
    published_by: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[int] = mapped_column(Integer, nullable=False, index=True)


class RegistryPublishRequest(BaseModel):
    project_id: str = "default"
    revision_id: str
    version: str = Field(pattern=SEMVER.pattern)
    channel: str = Field(default="production", pattern=r"^[A-Za-z][A-Za-z0-9_.-]*$")
    allow_breaking: bool = False


class RegistryCompatibilityRequest(BaseModel):
    project_id: str = "default"
    revision_id: str
    channel: str = Field(default="production", pattern=r"^[A-Za-z][A-Za-z0-9_.-]*$")


def _now() -> int:
    return int(time.time())


def _copy(value: Any) -> Any:
    return json.loads(json.dumps(value))


def _hash(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _pascal(value: str) -> str:
    parts = re.findall(r"[A-Za-z0-9]+", value)
    result = "".join(part[:1].upper() + part[1:] for part in parts) or "OntologyObject"
    return f"Object{result}" if result[0].isdigit() else result


def _python_name(value: str) -> str:
    result = re.sub(r"\W", "_", value)
    if not result or result[0].isdigit():
        result = f"field_{result}"
    return f"{result}_" if keyword.iskeyword(result) else result


def _spec_type(spec: Any) -> str:
    if not isinstance(spec, dict):
        return str(spec or "string").lower()
    return str(spec.get("base_type") or spec.get("type") or "string").lower()


def _enum_values(spec: Any) -> List[Any]:
    if not isinstance(spec, dict):
        return []
    values = spec.get("allowed_values") or spec.get("values") or spec.get("enum") or []
    return list(values) if isinstance(values, list) else []


def _json_property(spec: Any) -> Dict[str, Any]:
    base_type = _spec_type(spec)
    result: Dict[str, Any]
    if base_type in {"integer", "long", "short", "byte"}:
        result = {"type": "integer"}
    elif base_type in {"number", "double", "float", "decimal"}:
        result = {"type": "number"}
    elif base_type == "boolean":
        result = {"type": "boolean"}
    elif base_type in {"array", "vector"}:
        result = {"type": "array", "items": {}}
    elif base_type in {"json", "object", "struct"}:
        result = {"type": "object"}
    elif base_type in {"geometry", "geoshape", "geo", "geopoint", "geojson"}:
        result = {"type": "object", "x-ontology-type": base_type}
    else:
        result = {"type": "string"}
        if base_type in {"date", "timestamp"}:
            result["format"] = "date" if base_type == "date" else "date-time"
    values = _enum_values(spec)
    if values:
        result["enum"] = values
    if isinstance(spec, dict):
        for source, target in (("description", "description"), ("minimum", "minimum"), ("maximum", "maximum"), ("unit", "x-unit")):
            if spec.get(source) is not None:
                result[target] = spec[source]
    return result


def _json_schema(manifest: Dict[str, Any], version: str, channel: str) -> Dict[str, Any]:
    definitions: Dict[str, Any] = {}
    for object_type in manifest.get("object_types") or []:
        properties = object_type.get("properties") or {}
        required = [name for name, spec in properties.items() if bool((spec or {}).get("required"))]
        primary_key = object_type.get("primary_key")
        if primary_key and primary_key not in required:
            required.append(primary_key)
        definitions[str(object_type["id"])] = {
            "type": "object",
            "title": object_type.get("display_name") or object_type["id"],
            "description": object_type.get("description") or "",
            "properties": {name: _json_property(spec) for name, spec in properties.items()},
            "required": sorted(required),
            "additionalProperties": False,
            "x-object-type-id": object_type["id"],
            "x-primary-key": primary_key,
            "x-title-key": object_type.get("title_key"),
        }
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": f"urn:ontology:{manifest.get('project_id', 'default')}:{channel}:{version}",
        "title": f"Ontology contract {manifest.get('project_id', 'default')} {version}",
        "type": "object",
        "$defs": definitions,
        "x-link-types": _copy(manifest.get("link_types") or []),
        "x-action-types": _copy(manifest.get("action_types") or []),
    }


def _ts_type(spec: Any) -> str:
    values = _enum_values(spec)
    if values:
        return " | ".join(json.dumps(value) for value in values)
    return {
        "integer": "number", "long": "number", "short": "number", "byte": "number",
        "number": "number", "double": "number", "float": "number", "decimal": "number",
        "boolean": "boolean", "array": "unknown[]", "vector": "number[]",
        "json": "Record<string, unknown>", "object": "Record<string, unknown>",
        "struct": "Record<string, unknown>", "geometry": "GeoJSONGeometry",
        "geoshape": "GeoJSONGeometry", "geo": "GeoJSONGeometry", "geopoint": "GeoJSONGeometry",
    }.get(_spec_type(spec), "string")


def _py_type(spec: Any) -> str:
    values = _enum_values(spec)
    if values:
        return "Literal[" + ", ".join(repr(value) for value in values) + "]"
    return {
        "integer": "int", "long": "int", "short": "int", "byte": "int",
        "number": "float", "double": "float", "float": "float", "decimal": "float",
        "boolean": "bool", "array": "list[Any]", "vector": "list[float]",
        "json": "dict[str, Any]", "object": "dict[str, Any]", "struct": "dict[str, Any]",
        "geometry": "dict[str, Any]", "geoshape": "dict[str, Any]", "geo": "dict[str, Any]",
        "geopoint": "dict[str, Any]",
    }.get(_spec_type(spec), "str")


def _typescript_sdk(entry: OntologyRegistryEntry) -> Dict[str, str]:
    manifest = entry.manifest or {}
    lines = [
        f"// Generated from ontology registry {entry.id}; checksum {entry.checksum}",
        "export type GeoJSONGeometry = { type: string; coordinates?: unknown };",
        "export type ObjectSet<T> = { data: T[]; count: number };",
        "",
    ]
    for object_type in manifest.get("object_types") or []:
        name = _pascal(str(object_type["id"]))
        lines.append(f"export interface {name} {{")
        for property_name, spec in (object_type.get("properties") or {}).items():
            key = property_name if IDENTIFIER.match(property_name) else json.dumps(property_name)
            optional = "" if bool((spec or {}).get("required")) or property_name == object_type.get("primary_key") else "?"
            lines.append(f"  {key}{optional}: {_ts_type(spec)};")
        lines.extend(["}", ""])
    lines.extend([
        "export class OntologyClient {",
        "  constructor(private baseUrl: string, private headers: Record<string, string> = {}) {}",
        "  private async request<T>(path: string, init?: RequestInit): Promise<T> {",
        "    const response = await fetch(`${this.baseUrl}${path}`, { ...init, headers: { 'Content-Type': 'application/json', ...this.headers, ...(init?.headers || {}) } });",
        "    if (!response.ok) throw new Error(`Ontology request failed: ${response.status}`);",
        "    return response.json() as Promise<T>;",
        "  }",
    ])
    for object_type in manifest.get("object_types") or []:
        object_id = str(object_type["id"])
        name = _pascal(object_id)
        method = name[:1].lower() + name[1:]
        lines.append(f"  get{ name }(id: string): Promise<{name}> {{ return this.request('/objects/{object_id}/' + encodeURIComponent(id)); }}")
        lines.append(f"  search{ name }(filters: Partial<{name}> = {{}}): Promise<ObjectSet<{name}>> {{ return this.request('/object-sets/search', {{ method: 'POST', body: JSON.stringify({{ object_type_id: '{object_id}', filters }}) }}); }}")
        lines.append(f"  {method} = {{ get: this.get{name}.bind(this), search: this.search{name}.bind(this) }};")
    for action in manifest.get("action_types") or []:
        action_id = str(action["id"])
        action_name = _pascal(action_id)
        lines.append(f"  execute{action_name}(parameters: Record<string, unknown>): Promise<unknown> {{ return this.request('/actions/execute', {{ method: 'POST', body: JSON.stringify({{ action_type_id: '{action_id}', parameters }}) }}); }}")
    lines.append("}")
    return {"ontology.ts": "\n".join(lines) + "\n"}


def _python_sdk(entry: OntologyRegistryEntry) -> Dict[str, str]:
    manifest = entry.manifest or {}
    lines = [
        f'"""Generated from ontology registry {entry.id}; checksum {entry.checksum}."""',
        "from dataclasses import dataclass",
        "from typing import Any, Literal, Optional",
        "from urllib import request",
        "import json",
        "",
    ]
    for object_type in manifest.get("object_types") or []:
        name = _pascal(str(object_type["id"]))
        properties = object_type.get("properties") or {}
        required = [(field, spec) for field, spec in properties.items() if bool((spec or {}).get("required")) or field == object_type.get("primary_key")]
        optional = [(field, spec) for field, spec in properties.items() if (field, spec) not in required]
        lines.extend(["@dataclass", f"class {name}:"])
        if not properties:
            lines.append("    pass")
        for field, spec in required:
            lines.append(f"    {_python_name(field)}: {_py_type(spec)}")
        for field, spec in optional:
            lines.append(f"    {_python_name(field)}: Optional[{_py_type(spec)}] = None")
        lines.append("")
    lines.extend([
        "class OntologyClient:",
        "    def __init__(self, base_url: str, token: str | None = None):",
        "        self.base_url = base_url.rstrip('/')",
        "        self.headers = {'Content-Type': 'application/json'}",
        "        if token: self.headers['Authorization'] = f'Bearer {token}'",
        "",
        "    def _request(self, path: str, payload: dict[str, Any] | None = None) -> Any:",
        "        body = json.dumps(payload).encode() if payload is not None else None",
        "        req = request.Request(self.base_url + path, data=body, headers=self.headers, method='POST' if body else 'GET')",
        "        with request.urlopen(req) as response:",
        "            return json.loads(response.read().decode())",
        "",
    ])
    for object_type in manifest.get("object_types") or []:
        object_id = str(object_type["id"])
        method = re.sub(r"\W", "_", object_id).lower()
        lines.append(f"    def get_{method}(self, object_id: str) -> dict[str, Any]:")
        lines.append(f"        return self._request('/objects/{object_id}/' + object_id)")
        lines.append(f"    def search_{method}(self, filters: dict[str, Any] | None = None) -> dict[str, Any]:")
        lines.append(f"        return self._request('/object-sets/search', {{'object_type_id': '{object_id}', 'filters': filters or {{}}}})")
    return {"ontology_client.py": "\n".join(lines) + "\n"}


def _entry_dict(row: OntologyRegistryEntry, include_contract: bool = False) -> Dict[str, Any]:
    result = {
        "id": row.id, "project_id": row.project_id, "channel": row.channel, "version": row.version,
        "revision_id": row.revision_id, "revision_number": row.revision_number, "status": row.status,
        "compatibility": row.compatibility or {}, "checksum": row.checksum,
        "published_by": row.published_by, "created_at": row.created_at,
    }
    if include_contract:
        result["manifest"] = row.manifest or {}
        result["contract_schema"] = row.contract_schema or {}
    return result


def _revision(db: Session, principal: Principal, project_id: str, revision_id: str):
    tenancy.assert_project_permission(db, principal, project_id, "view")
    row = db.get(ontology_versioning.OntologyRevision, revision_id)
    if not row or row.project_id != project_id:
        raise HTTPException(status_code=404, detail="Ontology revision not found")
    if row.status not in {"PUBLISHED", "SUPERSEDED"}:
        raise HTTPException(status_code=409, detail="Only published ontology revisions can enter the schema registry")
    return row


def _latest(db: Session, project_id: str, channel: str) -> Optional[OntologyRegistryEntry]:
    return db.query(OntologyRegistryEntry).filter(
        OntologyRegistryEntry.project_id == project_id,
        OntologyRegistryEntry.channel == channel,
    ).order_by(OntologyRegistryEntry.created_at.desc(), OntologyRegistryEntry.version.desc()).first()


def _compatibility(db: Session, project_id: str, channel: str, manifest: Dict[str, Any]) -> Dict[str, Any]:
    current = _latest(db, project_id, channel)
    empty = {"schema_version": 1, "project_id": project_id, "object_types": [], "link_types": [], "action_types": []}
    diff = ontology_versioning._ontology_diff(current.manifest if current else empty, manifest)
    return {"against_registry_id": current.id if current else None, **diff}


@router.get("/ontology/registry")
def list_registry_entries(project_id: str = "default", channel: Optional[str] = None, principal: Principal = Depends(require_permission("view")), db: Session = Depends(get_db)):
    tenancy.assert_project_permission(db, principal, project_id, "view")
    query = db.query(OntologyRegistryEntry).filter(OntologyRegistryEntry.project_id == project_id)
    if channel:
        query = query.filter(OntologyRegistryEntry.channel == channel)
    rows = query.order_by(OntologyRegistryEntry.created_at.desc(), OntologyRegistryEntry.version.desc()).all()
    return {"project_id": project_id, "count": len(rows), "entries": [_entry_dict(row) for row in rows]}


@router.get("/ontology/registry/current")
def current_registry_entry(project_id: str = "default", channel: str = "production", principal: Principal = Depends(require_permission("view")), db: Session = Depends(get_db)):
    tenancy.assert_project_permission(db, principal, project_id, "view")
    row = _latest(db, project_id, channel)
    if not row:
        raise HTTPException(status_code=404, detail="No ontology registry entry is published for this channel")
    return _entry_dict(row, True)


@router.post("/ontology/registry/compatibility")
def check_registry_compatibility(body: RegistryCompatibilityRequest, principal: Principal = Depends(require_permission("view")), db: Session = Depends(get_db)):
    row = _revision(db, principal, body.project_id, body.revision_id)
    return {"project_id": body.project_id, "channel": body.channel, "revision_id": row.id, **_compatibility(db, body.project_id, body.channel, row.manifest or {})}


@router.post("/ontology/registry/publish", status_code=201)
def publish_registry_entry(body: RegistryPublishRequest, principal: Principal = Depends(require_permission("publish")), db: Session = Depends(get_db)):
    tenancy.assert_project_permission(db, principal, body.project_id, "publish")
    row = _revision(db, principal, body.project_id, body.revision_id)
    duplicate = db.query(OntologyRegistryEntry).filter(
        OntologyRegistryEntry.project_id == body.project_id,
        OntologyRegistryEntry.channel == body.channel,
        OntologyRegistryEntry.version == body.version,
    ).first()
    if duplicate:
        raise HTTPException(status_code=409, detail="Registry version already exists in this channel")
    compatibility = _compatibility(db, body.project_id, body.channel, row.manifest or {})
    if compatibility["classification"] == "BREAKING" and not body.allow_breaking:
        raise HTTPException(status_code=409, detail={"message": "Breaking registry publication requires explicit acknowledgement", "compatibility": compatibility})
    contract = _json_schema(row.manifest or {}, body.version, body.channel)
    now = _now()
    previous = db.query(OntologyRegistryEntry).filter(OntologyRegistryEntry.project_id == body.project_id).order_by(OntologyRegistryEntry.created_at.desc()).first()
    if previous and now <= previous.created_at:
        now = previous.created_at + 1
    entry = OntologyRegistryEntry(
        id=f"ontology_registry_{uuid.uuid4().hex}", project_id=body.project_id,
        channel=body.channel, version=body.version, revision_id=row.id, revision_number=row.revision,
        status="PUBLISHED", manifest=_copy(row.manifest or {}), contract_schema=contract,
        compatibility=compatibility, checksum=_hash({"manifest": row.manifest, "contract": contract}),
        published_by=principal.id, created_at=now,
    )
    db.add(entry)
    db.add(models_action.AuditLog(
        id=f"audit_{uuid.uuid4().hex}", actor=principal.id, event_type="ontology.registry.published",
        subject_type="ontology_registry_entry", subject_id=entry.id,
        payload={"project_id": body.project_id, "channel": body.channel, "version": body.version, "revision_id": row.id, "classification": compatibility["classification"], "checksum": entry.checksum},
    ))
    try:
        from . import ops_control
        ops_control.record_ops_event(
            db, source="ontology", event_type="ontology.registry.published", severity="info",
            title=f"Ontology registry {body.channel} {body.version} published",
            subject_type="ontology_registry_entry", subject_id=entry.id,
            payload={"project_id": body.project_id, "revision_id": row.id, "checksum": entry.checksum},
        )
    except Exception:
        pass
    db.commit()
    return _entry_dict(entry, True)


@router.get("/ontology/registry/{entry_id}")
def get_registry_entry(entry_id: str, principal: Principal = Depends(require_permission("view")), db: Session = Depends(get_db)):
    row = db.get(OntologyRegistryEntry, entry_id)
    if not row:
        raise HTTPException(status_code=404, detail="Ontology registry entry not found")
    tenancy.assert_project_permission(db, principal, row.project_id, "view")
    return _entry_dict(row, True)


@router.get("/ontology/registry/{entry_id}/schema")
def get_registry_schema(entry_id: str, principal: Principal = Depends(require_permission("export")), db: Session = Depends(get_db)):
    row = db.get(OntologyRegistryEntry, entry_id)
    if not row:
        raise HTTPException(status_code=404, detail="Ontology registry entry not found")
    tenancy.assert_project_permission(db, principal, row.project_id, "export")
    return {"registry_id": row.id, "version": row.version, "channel": row.channel, "checksum": row.checksum, "schema": row.contract_schema}


@router.get("/ontology/registry/{entry_id}/sdk/{language}")
def generate_registry_sdk(entry_id: str, language: str, principal: Principal = Depends(require_permission("export")), db: Session = Depends(get_db)):
    row = db.get(OntologyRegistryEntry, entry_id)
    if not row:
        raise HTTPException(status_code=404, detail="Ontology registry entry not found")
    tenancy.assert_project_permission(db, principal, row.project_id, "export")
    language = language.lower()
    if language not in {"typescript", "python"}:
        raise HTTPException(status_code=422, detail="language must be typescript or python")
    files = _typescript_sdk(row) if language == "typescript" else _python_sdk(row)
    return {"registry_id": row.id, "language": language, "version": row.version, "checksum": row.checksum, "files": files}


@router.get("/ui-state/ontology/registry")
def ontology_registry_ui_state(project_id: str = "default", channel: str = "production", principal: Principal = Depends(require_permission("view")), db: Session = Depends(get_db)):
    tenancy.assert_project_permission(db, principal, project_id, "view")
    rows = db.query(OntologyRegistryEntry).filter(OntologyRegistryEntry.project_id == project_id).order_by(OntologyRegistryEntry.created_at.desc()).all()
    current = next((row for row in rows if row.channel == channel), None)
    return {
        "summary": {"status": "PUBLISHED" if current else "NOT_PUBLISHED", "entries": len(rows), "channel": channel, "current_version": current.version if current else None},
        "primary_actions": [{"id": "publish", "label": "Publish registry version", "method": "POST", "path": "/ontology/registry/publish"}],
        "sections": {"current": _entry_dict(current) if current else None, "entries": [_entry_dict(row) for row in rows]},
        "evidence_links": ([{"label": f"Schema {current.version}", "href": f"/ontology/registry/{current.id}/schema", "kind": "schema_registry"}] if current else []),
        "warnings": [] if current else [{"code": "REGISTRY_EMPTY", "message": "Publish an approved ontology revision before generating client contracts."}],
        "permissions": sorted(tenancy.project_permissions(db, principal, project_id)),
        "last_updated": current.created_at if current else 0,
    }

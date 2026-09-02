"""
Faithful, documented Ontology-core semantics (pass 1 of the deep "implement as
written" work). This module adds the documented behaviors that the base platform
did not yet enforce:

  * the Foundry property **base-type catalog** (object-link-types/base-types),
  * **API-name rules** (PascalCase for object types, camelCase for properties),
  * **object-type profiles** — primary key, title key, per-property status and
    base type, and display metadata (action-types & object-types docs), and
  * a faithful **Action engine** — typed parameter validation, **submission
    criteria**, the full **mutation set** (create / modify / delete object,
    add / remove link), and **side effects** (notifications, webhooks).

It is additive: it augments the existing `object_types` / `action_types` tables
via a 1:1 profile table and new endpoints, leaving the working endpoints and
their tests untouched. Link cardinality is already enforced by the core
`/links` endpoint, so it is not duplicated here. Everything is deterministic and
local.
"""
import json
import re
import time
import uuid
from typing import Optional, List, Any, Dict

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import String, Integer, JSON, inspect
from sqlalchemy.orm.attributes import flag_modified
from sqlalchemy.orm import Mapped, mapped_column, Session
from pydantic import BaseModel, ConfigDict, Field

from .database import Base, get_db
from . import models, models_action, object_writes
from . import production_auth, runtime, semantic_scope, tenancy

router = APIRouter(tags=["ontology_core"])


def _now() -> int:
    return int(time.time())


def _audit(db: Session, actor: str, event_type: str, subject_type: str, subject_id: str, payload: dict):
    db.add(models_action.AuditLog(
        id=uuid.uuid4().hex, actor=actor or "system", event_type=event_type,
        subject_type=subject_type, subject_id=subject_id, payload=payload,
    ))


def _sync_semantic_contract(db: Session, obj_type: models.ObjectType, actor: str) -> None:
    from . import ontology_runtime_v1
    bind = db.get_bind()
    if bind is None or not inspect(bind).has_table(ontology_runtime_v1.OntologyPropertyDefinition.__tablename__):
        return
    ontology_runtime_v1.materialize_semantic_definitions(
        db,
        project_id=obj_type.project_id,
        actor=actor,
        object_type_ids=[obj_type.id],
    )


# ---------------------------------------------------------------------------
# Documented Foundry base-type catalog (object-link-types/base-types)
# ---------------------------------------------------------------------------
FOUNDRY_BASE_TYPES: Dict[str, Dict[str, Any]] = {
    "boolean":         {"category": "primitive", "json": "boolean"},
    "byte":            {"category": "numeric",   "json": "integer"},
    "short":           {"category": "numeric",   "json": "integer"},
    "integer":         {"category": "numeric",   "json": "integer"},
    "long":            {"category": "numeric",   "json": "integer"},
    "float":           {"category": "numeric",   "json": "number"},
    "double":          {"category": "numeric",   "json": "number"},
    "decimal":         {"category": "numeric",   "json": "number/string"},
    "string":          {"category": "text",      "json": "string"},
    "date":            {"category": "temporal",  "json": "string (ISO date)"},
    "timestamp":       {"category": "temporal",  "json": "string (ISO datetime)"},
    "geopoint":        {"category": "spatial",   "json": "GeoJSON Point / geohash"},
    "geoshape":        {"category": "spatial",   "json": "GeoJSON geometry"},
    "array":           {"category": "collection","json": "array"},
    "struct":          {"category": "collection","json": "object"},
    "attachment":      {"category": "reference", "json": "attachment ref"},
    "mediaReference":  {"category": "reference", "json": "media reference"},
    "timeSeries":      {"category": "reference", "json": "time series ref"},
    "marking":         {"category": "security",  "json": "marking id"},
    "vector":          {"category": "ml",        "json": "float array"},
    "cipherText":      {"category": "security",  "json": "encrypted string"},
}

# Documented guidance: primary keys must be stable & high-cardinality.
PK_ALLOWED = {"string", "integer", "long", "short", "byte", "decimal", "date", "timestamp", "boolean"}
PROPERTY_STATUSES = {"active", "experimental", "deprecated"}
LOCAL_SCHEMA_TYPES = {"any", "string", "integer", "number", "boolean", "array", "object", "json", "geometry", "geojson"}

PASCAL_RE = re.compile(r"^[A-Z][A-Za-z0-9]{0,99}$")   # object type API names
CAMEL_RE = re.compile(r"^[a-z][A-Za-z0-9]{0,99}$")    # property API names


def validate_api_name(name: str, style: str) -> List[str]:
    errors: List[str] = []
    if not name or not (1 <= len(name) <= 100):
        errors.append(f"API name '{name}' must be 1-100 characters")
        return errors
    if style == "pascal" and not PASCAL_RE.match(name):
        errors.append(f"Object-type API name '{name}' must be PascalCase, alphanumeric, 1-100 chars")
    if style == "camel" and not CAMEL_RE.match(name):
        errors.append(f"Property API name '{name}' must be camelCase, alphanumeric, 1-100 chars")
    return errors


# ---------------------------------------------------------------------------
# ORM model — object-type profile (augments object_types 1:1)
# ---------------------------------------------------------------------------
class ObjectTypeProfile(Base):
    __tablename__ = "object_type_profiles"
    object_type_id: Mapped[str] = mapped_column(String, primary_key=True)
    api_name: Mapped[str] = mapped_column(String)
    primary_key: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    title_key: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    icon: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    color: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    plural_name: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    groups: Mapped[list] = mapped_column(JSON, default=list)
    # name -> {base_type, status, required, shared_property_type_id, render_hint, description}
    properties: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[int] = mapped_column(Integer)
    updated_at: Mapped[int] = mapped_column(Integer)


# ---------------------------------------------------------------------------
# ORM model — queryable action log (Act/act_ prefix) for undo + auditing
# ---------------------------------------------------------------------------
class ActionLog(Base):
    """
    Append-only, queryable record of one action-type execution. Captures who ran
    it, with which parameters, which objects were mutated, and — for property
    modifications — the BEFORE values so the execution can be reversed (undo).
    """
    __tablename__ = "act_action_log"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    project_id: Mapped[str] = mapped_column(String, default="default", server_default="default", index=True)
    action_type_id: Mapped[str] = mapped_column(String, index=True)
    actor: Mapped[str] = mapped_column(String, default="system", index=True)
    parameters: Mapped[dict] = mapped_column(JSON, default=dict)
    mutated_object_ids: Mapped[list] = mapped_column(JSON, default=list)
    # per-object before/after snapshots: [{object_id, before, after, op}]
    reversal: Mapped[list] = mapped_column(JSON, default=list)
    function_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    undone: Mapped[bool] = mapped_column(Integer, default=0)  # 0/1 flag (sqlite-friendly)
    created_at: Mapped[int] = mapped_column(Integer, index=True)


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------
class PropertySpec(BaseModel):
    base_type: str
    status: str = "active"
    required: bool = False
    display_name: Optional[str] = None
    indexed: bool = False
    sensitive: bool = False
    shared_property_type_id: Optional[str] = None
    render_hint: Optional[str] = None
    description: Optional[str] = None
    minimum: Optional[float] = None
    maximum: Optional[float] = None
    min_length: Optional[int] = Field(default=None, ge=0)
    max_length: Optional[int] = Field(default=None, ge=0)
    pattern: Optional[str] = None
    enum: List[Any] = Field(default_factory=list)
    unit: Optional[str] = None
    geometry_type: Optional[str] = None


class ProfileUpsert(BaseModel):
    api_name: str
    primary_key: Optional[str] = None
    title_key: Optional[str] = None
    icon: Optional[str] = None
    color: Optional[str] = None
    plural_name: Optional[str] = None
    groups: List[str] = Field(default_factory=list)
    properties: Dict[str, PropertySpec] = Field(default_factory=dict)


class ProfileRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    object_type_id: str
    api_name: str
    primary_key: Optional[str] = None
    title_key: Optional[str] = None
    icon: Optional[str] = None
    color: Optional[str] = None
    plural_name: Optional[str] = None
    groups: List[str]
    properties: Dict[str, Any]
    created_at: int
    updated_at: int


class ApiNameRequest(BaseModel):
    name: str
    style: str = "pascal"  # pascal | camel


class ActionExecuteRequest(BaseModel):
    parameters: Dict[str, Any] = Field(default_factory=dict)
    actor: str = "system"
    dry_run: bool = False


class ObjectTypeUpdate(BaseModel):
    display_name: Optional[str] = None
    description: Optional[str] = None
    properties: Optional[Dict[str, Any]] = None


class ObjectTypeManagerMetadataRequest(BaseModel):
    display_name: Optional[str] = None
    description: Optional[str] = None
    plural_name: Optional[str] = None
    aliases: Optional[List[str]] = None
    point_of_contact: Optional[str] = None
    contributors: Optional[List[str]] = None
    status: Optional[str] = None
    visibility: Optional[str] = None
    edits_enabled: Optional[bool] = None
    groups: Optional[List[str]] = None


class ObjectTypeIndexRequest(BaseModel):
    actor: str = "ontology_manager"


class ObjectTypeOpenFromPipelineRequest(BaseModel):
    graph_id: str
    node_id: Optional[str] = None
    actor: str = "ontology_manager"


class ObjectTypePropertyCreate(BaseModel):
    name: str
    base_type: str = "string"
    status: str = "active"
    required: bool = False
    display_name: Optional[str] = None
    indexed: bool = False
    sensitive: bool = False
    description: Optional[str] = None
    render_hint: Optional[str] = None
    shared_property_type_id: Optional[str] = None
    minimum: Optional[float] = None
    maximum: Optional[float] = None
    min_length: Optional[int] = Field(default=None, ge=0)
    max_length: Optional[int] = Field(default=None, ge=0)
    pattern: Optional[str] = None
    enum: List[Any] = Field(default_factory=list)
    unit: Optional[str] = None
    geometry_type: Optional[str] = None
    actor: str = "ontology_manager"


class ObjectTypePropertyPatch(BaseModel):
    name: Optional[str] = None
    base_type: Optional[str] = None
    status: Optional[str] = None
    required: Optional[bool] = None
    display_name: Optional[str] = None
    indexed: Optional[bool] = None
    sensitive: Optional[bool] = None
    description: Optional[str] = None
    render_hint: Optional[str] = None
    shared_property_type_id: Optional[str] = None
    minimum: Optional[float] = None
    maximum: Optional[float] = None
    min_length: Optional[int] = Field(default=None, ge=0)
    max_length: Optional[int] = Field(default=None, ge=0)
    pattern: Optional[str] = None
    enum: Optional[List[Any]] = None
    unit: Optional[str] = None
    geometry_type: Optional[str] = None
    actor: str = "ontology_manager"


class ObjectTypePropertyOrderRequest(BaseModel):
    order: List[str] = Field(default_factory=list)
    actor: str = "ontology_manager"


class OntologyFieldMapping(BaseModel):
    source_field: str
    target_property: str


class OntologyMappingPreviewRequest(BaseModel):
    asset_id: str
    object_type_id: str
    mappings: List[OntologyFieldMapping] = Field(default_factory=list)
    limit: int = Field(default=20, ge=1, le=200)


class OntologyDatasourceMappingRequest(BaseModel):
    asset_id: str
    mappings: List[OntologyFieldMapping] = Field(default_factory=list)
    actor: str = "ontology_manager"


class ActionLogRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    project_id: str
    action_type_id: str
    actor: str
    parameters: Dict[str, Any]
    mutated_object_ids: List[str]
    reversal: List[Any]
    function_id: Optional[str] = None
    undone: bool
    created_at: int


class ValidatePrimaryKeyRequest(BaseModel):
    properties: Dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Base-type catalog + API name endpoints
# ---------------------------------------------------------------------------
@router.get("/ontology/base-types")
def list_base_types():
    return {
        "base_types": [{"name": k, **v} for k, v in FOUNDRY_BASE_TYPES.items()],
        "primary_key_allowed": sorted(PK_ALLOWED),
        "property_statuses": sorted(PROPERTY_STATUSES),
        "api_name_rules": {"object_type": "PascalCase 1-100 alnum", "property": "camelCase 1-100 alnum"},
    }


@router.post("/ontology/validate-api-name")
def validate_api_name_endpoint(body: ApiNameRequest):
    style = "camel" if body.style == "camel" else "pascal"
    errors = validate_api_name(body.name, style)
    return {"name": body.name, "style": style, "valid": not errors, "errors": errors}


# ---------------------------------------------------------------------------
# Object-type profiles
# ---------------------------------------------------------------------------
@router.put("/ontology/object-types/{object_type_id}/profile", response_model=ProfileRead)
def upsert_profile(object_type_id: str, body: ProfileUpsert, db: Session = Depends(get_db),
                   principal: production_auth.Principal = Depends(production_auth.require_permission("edit"))):
    obj_type = semantic_scope.object_type_for(db, principal, object_type_id, "edit")

    errors: List[str] = []
    # API names
    errors += validate_api_name(body.api_name, "pascal")
    for pname, spec in body.properties.items():
        errors += validate_api_name(pname, "camel")
        if spec.base_type not in FOUNDRY_BASE_TYPES:
            errors.append(f"Property '{pname}' has unknown base type '{spec.base_type}'")
        if spec.status not in PROPERTY_STATUSES:
            errors.append(f"Property '{pname}' has invalid status '{spec.status}'")
        if spec.minimum is not None and spec.maximum is not None and spec.minimum > spec.maximum:
            errors.append(f"Property '{pname}' minimum cannot exceed maximum")
        if spec.min_length is not None and spec.max_length is not None and spec.min_length > spec.max_length:
            errors.append(f"Property '{pname}' min_length cannot exceed max_length")
        if spec.enum and len({json.dumps(value, sort_keys=True, default=str) for value in spec.enum}) != len(spec.enum):
            errors.append(f"Property '{pname}' enum values must be unique")
    # Primary key
    if body.primary_key is not None:
        if body.primary_key not in body.properties:
            errors.append(f"primary_key '{body.primary_key}' is not a declared property")
        else:
            pk_type = body.properties[body.primary_key].base_type
            if pk_type not in PK_ALLOWED:
                errors.append(f"primary_key '{body.primary_key}' base type '{pk_type}' is not allowed for keys")
    # Title key
    if body.title_key is not None and body.title_key not in body.properties:
        errors.append(f"title_key '{body.title_key}' is not a declared property")

    if errors:
        raise HTTPException(status_code=422, detail=errors)

    now = _now()
    profile = db.get(ObjectTypeProfile, object_type_id)
    props = {k: v.model_dump() for k, v in body.properties.items()}
    if profile:
        profile.api_name = body.api_name
        profile.primary_key = body.primary_key
        profile.title_key = body.title_key
        profile.icon = body.icon
        profile.color = body.color
        profile.plural_name = body.plural_name
        profile.groups = body.groups
        profile.properties = props
        profile.updated_at = now
    else:
        profile = ObjectTypeProfile(
            object_type_id=object_type_id, api_name=body.api_name, primary_key=body.primary_key,
            title_key=body.title_key, icon=body.icon, color=body.color, plural_name=body.plural_name,
            groups=body.groups, properties=props, created_at=now, updated_at=now,
        )
        db.add(profile)
    _audit(db, semantic_scope.principal_id(principal), "ontology.object_type.profile_set", "object_type", object_type_id,
           {"api_name": body.api_name, "primary_key": body.primary_key})
    _sync_semantic_contract(db, obj_type, semantic_scope.principal_id(principal))
    db.commit(); db.refresh(profile)
    return profile


@router.get("/ontology/object-types/{object_type_id}/profile", response_model=ProfileRead)
def get_profile(object_type_id: str, db: Session = Depends(get_db),
                principal: production_auth.Principal = Depends(production_auth.require_permission("view"))):
    semantic_scope.object_type_for(db, principal, object_type_id, "view")
    profile = db.get(ObjectTypeProfile, object_type_id)
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not set for this object type")
    return profile


@router.get("/ontology/object-types/{object_type_id}/full")
def get_full_object_type(object_type_id: str, db: Session = Depends(get_db),
                         principal: production_auth.Principal = Depends(production_auth.require_permission("view"))):
    obj_type = semantic_scope.object_type_for(db, principal, object_type_id, "view")
    profile = db.get(ObjectTypeProfile, object_type_id)
    return {
        "id": obj_type.id,
        "display_name": obj_type.display_name,
        "description": obj_type.description,
        "base_properties": obj_type.properties,
        "profile": ProfileRead.model_validate(profile).model_dump() if profile else None,
    }


def _manager_metadata(obj_type: models.ObjectType, profile: Optional[ObjectTypeProfile]) -> Dict[str, Any]:
    base_properties = obj_type.properties if isinstance(obj_type.properties, dict) else {}
    manager = base_properties.get("__manager") if isinstance(base_properties.get("__manager"), dict) else {}
    return {
        "id": obj_type.id,
        "rid": manager.get("rid") or f"ri.local.ontology.object-type.{obj_type.id}",
        "display_name": obj_type.display_name,
        "description": obj_type.description,
        "plural_name": (profile.plural_name if profile else None) or manager.get("plural_name") or f"{obj_type.display_name}s",
        "api_name": (profile.api_name if profile else None) or manager.get("api_name") or obj_type.id,
        "aliases": manager.get("aliases", []),
        "point_of_contact": manager.get("point_of_contact", "local-owner"),
        "contributors": manager.get("contributors", []),
        "ontology": manager.get("ontology", "local"),
        "status": manager.get("status", "Example"),
        "visibility": manager.get("visibility", "Normal"),
        "index_status": manager.get("index_status", "not_indexed"),
        "edits": "Enabled" if manager.get("edits_enabled", True) else "Disabled",
        "groups": (profile.groups if profile else None) or manager.get("groups", []),
        "created_at": obj_type.created_at,
        "updated_at": obj_type.updated_at,
    }


def _property_rows(obj_type: models.ObjectType, profile: Optional[ObjectTypeProfile]) -> List[Dict[str, Any]]:
    if profile and isinstance(profile.properties, dict):
        return [
            {
                "order": index,
                "name": name,
                "api_name": name,
                "base_type": spec.get("base_type", "string") if isinstance(spec, dict) else "string",
                "status": spec.get("status", "active") if isinstance(spec, dict) else "active",
                "required": bool(spec.get("required")) if isinstance(spec, dict) else False,
                "display_name": spec.get("display_name", name) if isinstance(spec, dict) else name,
                "indexed": bool(spec.get("indexed")) if isinstance(spec, dict) else False,
                "sensitive": bool(spec.get("sensitive")) if isinstance(spec, dict) else False,
                "description": spec.get("description") if isinstance(spec, dict) else None,
                "minimum": spec.get("minimum") if isinstance(spec, dict) else None,
                "maximum": spec.get("maximum") if isinstance(spec, dict) else None,
                "min_length": spec.get("min_length") if isinstance(spec, dict) else None,
                "max_length": spec.get("max_length") if isinstance(spec, dict) else None,
                "pattern": spec.get("pattern") if isinstance(spec, dict) else None,
                "enum": spec.get("enum", []) if isinstance(spec, dict) else [],
                "unit": spec.get("unit") if isinstance(spec, dict) else None,
                "geometry_type": spec.get("geometry_type") if isinstance(spec, dict) else None,
                "source": "profile",
                "can_edit": True,
                "can_delete": name != profile.primary_key,
            }
            for index, (name, spec) in enumerate(profile.properties.items(), start=1)
        ]
    properties = obj_type.properties if isinstance(obj_type.properties, dict) else {}
    return [
        {
            "order": index,
            "name": name,
            "api_name": name,
            "base_type": ((spec or {}).get("base_type") or (spec or {}).get("type") or "string") if isinstance(spec, dict) else "string",
            "status": (spec or {}).get("status", "active") if isinstance(spec, dict) else "active",
            "required": bool((spec or {}).get("required")) if isinstance(spec, dict) else False,
            "display_name": (spec or {}).get("display_name", name) if isinstance(spec, dict) else name,
            "indexed": bool((spec or {}).get("indexed")) if isinstance(spec, dict) else False,
            "sensitive": bool((spec or {}).get("sensitive")) if isinstance(spec, dict) else False,
            "description": (spec or {}).get("description") if isinstance(spec, dict) else None,
            "minimum": (spec or {}).get("minimum") if isinstance(spec, dict) else None,
            "maximum": (spec or {}).get("maximum") if isinstance(spec, dict) else None,
            "min_length": (spec or {}).get("min_length") if isinstance(spec, dict) else None,
            "max_length": (spec or {}).get("max_length") if isinstance(spec, dict) else None,
            "pattern": (spec or {}).get("pattern") if isinstance(spec, dict) else None,
            "enum": (spec or {}).get("enum", []) if isinstance(spec, dict) else [],
            "unit": (spec or {}).get("unit") if isinstance(spec, dict) else None,
            "geometry_type": (spec or {}).get("geometry_type") if isinstance(spec, dict) else None,
            "source": "object_type",
            "can_edit": True,
            "can_delete": True,
        }
        for index, (name, spec) in enumerate(properties.items(), start=1)
        if not str(name).startswith("__")
    ]


def _allowed_property_types() -> set:
    return set(FOUNDRY_BASE_TYPES) | LOCAL_SCHEMA_TYPES


def _runtime_schema_type(base_type: str) -> str:
    if base_type in {"byte", "short", "integer", "long"}:
        return "integer"
    if base_type in {"float", "double", "decimal"}:
        return "number"
    if base_type == "boolean":
        return "boolean"
    if base_type == "array":
        return "array"
    if base_type in {"geopoint", "geoshape", "geometry", "geojson"}:
        return "geojson"
    if base_type in {"struct", "object", "json"}:
        return "object" if base_type == "struct" else base_type
    if base_type in LOCAL_SCHEMA_TYPES:
        return base_type
    return "string"


def _validate_property_name(name: str) -> List[str]:
    if not name or not str(name).strip():
        return ["Property name is required"]
    if str(name).startswith("__"):
        return ["Property names starting with '__' are reserved for manager metadata"]
    return validate_api_name(str(name), "camel")


def _stored_property_spec(
    *,
    base_type: str,
    status: str,
    required: bool,
    display_name: Optional[str],
    indexed: bool,
    sensitive: bool,
    description: Optional[str],
    render_hint: Optional[str],
    shared_property_type_id: Optional[str],
    constraints: Optional[Dict[str, Any]],
    profile_backed: bool,
) -> Dict[str, Any]:
    spec: Dict[str, Any] = {
        "base_type": base_type,
        "status": status,
        "required": bool(required),
        "indexed": bool(indexed),
        "sensitive": bool(sensitive),
    }
    if not profile_backed:
        spec["type"] = _runtime_schema_type(base_type)
    if description is not None:
        spec["description"] = description
    if display_name is not None:
        spec["display_name"] = display_name
    if render_hint is not None:
        spec["render_hint"] = render_hint
    if shared_property_type_id is not None:
        spec["shared_property_type_id"] = shared_property_type_id
    for key, value in (constraints or {}).items():
        if value not in (None, [], ""):
            spec[key] = value
    return spec


def _property_store(obj_type: models.ObjectType, profile: Optional[ObjectTypeProfile]) -> tuple[Dict[str, Any], bool]:
    if profile and isinstance(profile.properties, dict):
        return dict(profile.properties or {}), True
    return {
        key: value
        for key, value in dict(obj_type.properties or {}).items()
        if not str(key).startswith("__")
    }, False


def _write_property_store(
    obj_type: models.ObjectType,
    profile: Optional[ObjectTypeProfile],
    next_properties: Dict[str, Any],
    *,
    profile_backed: bool,
) -> None:
    now = _now()
    if profile_backed and profile:
        profile.properties = next_properties
        flag_modified(profile, "properties")
        profile.updated_at = now
    else:
        existing = dict(obj_type.properties or {})
        manager = existing.get("__manager") if isinstance(existing.get("__manager"), dict) else None
        visible = dict(next_properties)
        if manager:
            visible["__manager"] = manager
        obj_type.properties = visible
        flag_modified(obj_type, "properties")
    obj_type.updated_at = now


def _property_primary_key(obj_type: models.ObjectType, profile: Optional[ObjectTypeProfile]) -> Optional[str]:
    if profile and profile.primary_key:
        return profile.primary_key
    manager = (obj_type.properties or {}).get("__manager", {}) if isinstance(obj_type.properties, dict) else {}
    if isinstance(manager, dict):
        primary_key = manager.get("primary_key") or manager.get("source_primary_key")
        return str(primary_key) if primary_key else None
    return None


def _validate_property_spec(name: str, base_type: str, status: str, existing_names: set, *, original_name: Optional[str] = None) -> None:
    errors = [] if original_name == name else _validate_property_name(name)
    if name in existing_names and name != original_name:
        errors.append(f"Property '{name}' already exists")
    if base_type not in _allowed_property_types():
        errors.append(f"Property '{name}' has unsupported base type '{base_type}'")
    if status not in PROPERTY_STATUSES:
        errors.append(f"Property '{name}' has invalid status '{status}'")
    if errors:
        raise HTTPException(status_code=422, detail=errors)


def _validate_property_constraints(name: str, spec: Dict[str, Any]) -> None:
    errors: List[str] = []
    if spec.get("minimum") is not None and spec.get("maximum") is not None and spec["minimum"] > spec["maximum"]:
        errors.append(f"Property '{name}' minimum cannot exceed maximum")
    if spec.get("min_length") is not None and spec.get("max_length") is not None and spec["min_length"] > spec["max_length"]:
        errors.append(f"Property '{name}' min_length cannot exceed max_length")
    enum_values = spec.get("enum") or []
    if len({json.dumps(value, sort_keys=True, default=str) for value in enum_values}) != len(enum_values):
        errors.append(f"Property '{name}' enum values must be unique")
    if errors:
        raise HTTPException(status_code=422, detail=errors)


def _references_object_type(payload: Any, object_type_id: str) -> bool:
    if isinstance(payload, dict):
        return any(_references_object_type(value, object_type_id) for value in payload.values())
    if isinstance(payload, list):
        return any(_references_object_type(value, object_type_id) for value in payload)
    return str(payload) == object_type_id


def _mapping_type(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "double"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "geopoint" if value.get("type") == "Point" else "struct"
    text = str(value)
    if re.match(r"^\d{4}-\d{2}-\d{2}T", text):
        return "timestamp"
    if re.match(r"^\d{4}-\d{2}-\d{2}$", text):
        return "date"
    return "string"


def _mapping_compatible(source_type: str, target_type: str) -> bool:
    if source_type == "null":
        return True
    numeric = {"byte", "short", "integer", "long", "float", "double", "decimal", "number"}
    if source_type in numeric and target_type in numeric:
        return True
    return source_type == target_type or target_type == "string" or {source_type, target_type} <= {"struct", "json", "object"}


def _mapping_preview(db: Session, body: OntologyMappingPreviewRequest) -> Dict[str, Any]:
    asset = db.get(models.DataAsset, body.asset_id)
    obj_type = db.get(models.ObjectType, body.object_type_id)
    if not asset:
        raise HTTPException(status_code=404, detail=f"DataAsset '{body.asset_id}' not found")
    if not obj_type:
        raise HTTPException(status_code=404, detail=f"ObjectType '{body.object_type_id}' not found")
    if asset.project_id != obj_type.project_id:
        raise HTTPException(status_code=409, detail="Dataset and object type belong to different projects")
    profile = db.get(ObjectTypeProfile, body.object_type_id)
    properties, _profile_backed = _property_store(obj_type, profile)
    rows = list(asset.records or [])
    source_fields = sorted({str(key) for row in rows for key in (row or {}).keys()})
    normalized_sources = {re.sub(r"[^a-z0-9]", "", field.lower()): field for field in source_fields}
    mappings = list(body.mappings)
    if not mappings:
        for target in properties:
            normalized = re.sub(r"[^a-z0-9]", "", target.lower())
            source = normalized_sources.get(normalized)
            if source:
                mappings.append(OntologyFieldMapping(source_field=source, target_property=target))
    mapping_by_target = {item.target_property: item.source_field for item in mappings}
    compatibility = []
    errors = []
    warnings = []
    for item in mappings:
        if item.source_field not in source_fields:
            errors.append({"code": "SOURCE_NOT_FOUND", "source_field": item.source_field, "target_property": item.target_property, "message": "Source field does not exist"})
            continue
        if item.target_property not in properties:
            errors.append({"code": "PROPERTY_NOT_FOUND", "source_field": item.source_field, "target_property": item.target_property, "message": "Target property does not exist"})
            continue
        source_value = next(((row or {}).get(item.source_field) for row in rows if (row or {}).get(item.source_field) is not None), None)
        source_type = _mapping_type(source_value)
        spec = properties[item.target_property] if isinstance(properties[item.target_property], dict) else {}
        target_type = str(spec.get("base_type") or spec.get("type") or "string")
        compatible = _mapping_compatible(source_type, target_type)
        compatibility.append({"source_field": item.source_field, "target_property": item.target_property, "source_type": source_type, "target_type": target_type, "compatible": compatible})
        if not compatible:
            errors.append({"code": "TYPE_MISMATCH", "source_field": item.source_field, "target_property": item.target_property, "message": f"{source_type} is not compatible with {target_type}"})
    for name, spec in properties.items():
        if isinstance(spec, dict) and spec.get("required") and name not in mapping_by_target:
            errors.append({"code": "REQUIRED_UNMAPPED", "target_property": name, "message": f"Required property '{name}' is not mapped"})
    mapped_sources = {item.source_field for item in mappings}
    for field in source_fields:
        if field not in mapped_sources:
            warnings.append({"code": "UNMAPPED_SOURCE", "source_field": field, "message": f"Source field '{field}' will not be hydrated"})
    hydrated = []
    primary_key = _property_primary_key(obj_type, profile)
    for index, row in enumerate(rows[:body.limit]):
        props = {item.target_property: (row or {}).get(item.source_field) for item in mappings if item.source_field in (row or {}) and item.target_property in properties}
        hydrated.append({"object_id": str(props.get(primary_key) if primary_key else f"preview_{index + 1}"), "object_type_id": obj_type.id, **props})
    return {
        "asset": {"id": asset.id, "display_name": asset.display_name, "row_count": len(rows)},
        "object_type": {"id": obj_type.id, "display_name": obj_type.display_name, "primary_key": primary_key},
        "source_fields": [{"name": field, "inferred_type": _mapping_type(next(((row or {}).get(field) for row in rows if (row or {}).get(field) is not None), None)), "mapped": field in mapped_sources} for field in source_fields],
        "target_properties": [{"name": name, **(spec if isinstance(spec, dict) else {"base_type": str(spec)}), "mapped_from": mapping_by_target.get(name)} for name, spec in properties.items()],
        "mappings": [item.model_dump() for item in mappings],
        "compatibility": compatibility,
        "hydrated_preview": hydrated,
        "status": "FAIL" if errors else ("WARN" if warnings else "PASS"),
        "errors": errors,
        "warnings": warnings,
    }


def _object_type_manager_state(db: Session, object_type_id: str) -> Dict[str, Any]:
    obj_type = db.get(models.ObjectType, object_type_id)
    if not obj_type:
        raise HTTPException(status_code=404, detail=f"ObjectType '{object_type_id}' not found")
    profile = db.get(ObjectTypeProfile, object_type_id)
    metadata = _manager_metadata(obj_type, profile)
    properties = _property_rows(obj_type, profile)
    action_types = [
        {
            "id": action.id,
            "display_name": action.display_name,
            "description": action.description,
            "parameter_count": len(action.parameters or {}),
        }
        for action in db.query(models.ActionType).filter(models.ActionType.project_id == obj_type.project_id).all()
        if _references_object_type(action.rules or {}, object_type_id) or object_type_id in str(action.id)
    ]
    link_types = [
        {
            "id": link.id,
            "display_name": link.display_name,
            "source_object_type_id": link.source_object_type_id,
            "target_object_type_id": link.target_object_type_id,
            "cardinality": link.cardinality,
        }
        for link in db.query(models.LinkType).filter(
            models.LinkType.project_id == obj_type.project_id,
            (models.LinkType.source_object_type_id == object_type_id) | (models.LinkType.target_object_type_id == object_type_id)
        ).all()
    ]
    object_count = db.query(models.ObjectInstance).filter(
        models.ObjectInstance.object_type_id == object_type_id,
        models.ObjectInstance.project_id == obj_type.project_id,
    ).count()
    source_asset_ids = sorted({
        row.source_asset_id
        for row in db.query(models.ObjectInstance).filter(
            models.ObjectInstance.object_type_id == object_type_id,
            models.ObjectInstance.project_id == obj_type.project_id,
        ).all()
        if row.source_asset_id
    })
    manager_config = (obj_type.properties or {}).get("__manager", {}) if isinstance(obj_type.properties, dict) else {}
    saved_mappings = list(manager_config.get("datasource_mappings") or []) if isinstance(manager_config, dict) else []
    pipeline_dependents: List[Dict[str, Any]] = []
    try:
        from . import pipeline_builder_ops
        for graph in db.query(pipeline_builder_ops.PipelineBuilderGraph).filter(
            pipeline_builder_ops.PipelineBuilderGraph.project_id == obj_type.project_id,
        ).all():
            for node in graph.nodes or []:
                config = node.get("config") or {}
                if config.get("object_type_id") == object_type_id:
                    pipeline_dependents.append({"type": "pipeline_graph", "id": graph.id, "display_name": graph.display_name, "node_id": node.get("id")})
    except Exception:
        pipeline_dependents = []
    from . import ontology_runtime_v1
    downstream_health = ontology_runtime_v1.contract_binding_health(
        db, project_id=obj_type.project_id, object_type_id=object_type_id,
    )
    contract_rows = [
        {
            "id": binding["id"],
            "consumer_kind": (binding.get("definition") or {}).get("consumer_kind"),
            "consumer_id": (binding.get("definition") or {}).get("consumer_id"),
            "consumer_version": (binding.get("definition") or {}).get("consumer_version"),
            "properties": (binding.get("definition") or {}).get("properties") or [],
            "status": (binding.get("health") or {}).get("status"),
            "compatible": (binding.get("health") or {}).get("compatible"),
            "reason": (binding.get("health") or {}).get("reason"),
            "bound_revision_id": binding.get("ontology_revision_id"),
            "active_revision_id": (binding.get("health") or {}).get("active_revision_id"),
        }
        for binding in downstream_health["bindings"]
    ]
    return {
        "object_type": metadata,
        "navigation": [
            "overview",
            "properties",
            "security",
            "datasources",
            "observability",
            "capabilities",
            "object_views",
            "interfaces",
            "materializations",
            "automations",
            "usage",
            "contracts",
            "history",
        ],
        "cards": {
            "properties": {"count": len(properties), "rows": properties},
            "action_types": {"count": len(action_types), "rows": action_types},
            "link_types": {"count": len(link_types), "rows": link_types},
            "datasources": {"count": len(set(source_asset_ids) | {str(item.get('asset_id')) for item in saved_mappings}), "rows": [{"asset_id": asset_id, "status": "materialized"} for asset_id in source_asset_ids] + [{**item, "status": "mapped"} for item in saved_mappings if item.get("asset_id") not in source_asset_ids]},
            "observability": {"object_count": object_count, "index_status": metadata["index_status"], "data_health": "configured" if object_count else "not_configured"},
            "dependents": {"count": len(pipeline_dependents), "rows": pipeline_dependents},
            "contract_health": {
                "count": downstream_health["binding_count"],
                "status": downstream_health["status"],
                "counts": downstream_health["counts"],
                "active_revision_id": downstream_health["active_revision_id"],
                "rows": contract_rows,
            },
        },
        "primary_actions": [
            {"id": "update_metadata", "label": "Update metadata", "method": "PATCH", "path": f"/ontology/object-types/{object_type_id}/metadata"},
            {"id": "add_property", "label": "Add property", "method": "POST", "path": f"/ontology/object-types/{object_type_id}/properties"},
            {"id": "update_property", "label": "Update property", "method": "PATCH", "path": f"/ontology/object-types/{object_type_id}/properties/{{property_name}}"},
            {"id": "archive_property", "label": "Archive property", "method": "DELETE", "path": f"/ontology/object-types/{object_type_id}/properties/{{property_name}}"},
            {"id": "reorder_properties", "label": "Reorder properties", "method": "PATCH", "path": f"/ontology/object-types/{object_type_id}/properties/order"},
            {"id": "index", "label": "Index", "method": "POST", "path": f"/ontology/object-types/{object_type_id}/index"},
            {"id": "open_from_pipeline", "label": "Open from pipeline", "method": "POST", "path": f"/ontology/object-types/{object_type_id}/open-from-pipeline"},
        ],
        "last_updated": obj_type.updated_at,
    }


def _object_type_walkthrough(db: Session, object_type_id: str) -> Dict[str, Any]:
    state = _object_type_manager_state(db, object_type_id)
    manager = (db.get(models.ObjectType, object_type_id).properties or {}).get("__manager", {})
    current_resource = manager.get("last_opened_pipeline_graph_id") or object_type_id
    steps = [
        {"id": "pipeline_inputs", "title": "Inspect input datasets", "resource": current_resource, "status": "complete"},
        {"id": "pipeline_join", "title": "Review geospatial or semantic join", "resource": current_resource, "status": "complete" if state["cards"]["dependents"]["count"] else "available"},
        {"id": "post_join_filters", "title": "Review transforms and filters", "resource": current_resource, "status": "available"},
        {"id": "object_type_overview", "title": "Verify object type overview", "resource": object_type_id, "status": "active"},
        {"id": "properties", "title": "Confirm properties and keys", "resource": object_type_id, "status": "available"},
        {"id": "publish", "title": "Index and publish for downstream apps", "resource": object_type_id, "status": "available"},
    ]
    return {
        "object_type_id": object_type_id,
        "title": f"Build {state['object_type']['display_name']} workflow",
        "current_step_id": "object_type_overview",
        "current_resource_id": current_resource,
        "steps": steps,
        "links": [
            {"label": "Pipeline Builder", "path": "/workspace/pipeline"},
            {"label": "Ontology Manager", "path": f"/workspace/ontology?object_type_id={object_type_id}"},
            {"label": "Validation", "path": "/workspace/validation"},
        ],
    }


def _object_type_interface_state(db: Session, object_type_id: str) -> Dict[str, Any]:
    """Build the manager-facing view of explicitly implemented interfaces."""
    from . import ontology_interfaces, ontology_interfaces_ops

    implementations = (
        db.query(ontology_interfaces_ops.IfaceImplementation)
        .filter(ontology_interfaces_ops.IfaceImplementation.object_type_id == object_type_id)
        .order_by(ontology_interfaces_ops.IfaceImplementation.created_at, ontology_interfaces_ops.IfaceImplementation.id)
        .all()
    )
    rows: List[Dict[str, Any]] = []
    property_count = 0
    link_constraint_count = 0
    action_count = 0
    for implementation in implementations:
        interface = db.get(ontology_interfaces.OntologyInterface, implementation.interface_id)
        if interface is None:
            continue
        resolved_properties, inherited_from = ontology_interfaces_ops._resolve_properties(db, interface.id)
        resolved_links = ontology_interfaces_ops._resolve_link_constraints(db, interface.id)
        interface_actions = (
            db.query(ontology_interfaces_ops.IfaceAction)
            .filter(ontology_interfaces_ops.IfaceAction.interface_id == interface.id)
            .count()
        )
        property_count += len(resolved_properties)
        link_constraint_count += len(resolved_links)
        action_count += interface_actions
        rows.append({
            "id": implementation.id,
            "interface_id": interface.id,
            "display_name": interface.display_name,
            "description": interface.description,
            "extends": list(interface.extends or []),
            "property_count": len(resolved_properties),
            "inherited_property_count": sum(1 for owner in inherited_from.values() if owner != interface.id),
            "link_constraint_count": len(resolved_links),
            "action_count": interface_actions,
            "property_mappings": dict(implementation.property_mappings or {}),
            "link_mappings": dict(implementation.link_mappings or {}),
            "created_at": implementation.created_at,
        })
    return {
        "summary": {
            "configured": bool(rows),
            "implementation_count": len(rows),
            "resolved_property_count": property_count,
            "link_constraint_count": link_constraint_count,
            "action_count": action_count,
        },
        "rows": rows,
    }


def _object_type_section_state(db: Session, object_type_id: str, section_id: str) -> Dict[str, Any]:
    state = _object_type_manager_state(db, object_type_id)
    section = section_id.strip().lower().replace("-", "_")
    object_type = state["object_type"]
    cards = state["cards"]
    if section == "overview":
        return {
            "object_type_id": object_type_id,
            "section_id": section,
            "title": "Overview",
            "summary": object_type,
            "rows": [
                {"field": "Plural name", "value": object_type["plural_name"]},
                {"field": "Description", "value": object_type.get("description")},
                {"field": "API name", "value": object_type["api_name"]},
                {"field": "RID", "value": object_type["rid"]},
            ],
        }
    if section == "status":
        return {
            "object_type_id": object_type_id,
            "section_id": section,
            "title": "Status",
            "summary": {
                "status": object_type["status"],
                "visibility": object_type["visibility"],
                "index_status": object_type["index_status"],
                "edits": object_type["edits"],
            },
            "rows": [],
        }
    card_map = {
        "properties": "properties",
        "action_types": "action_types",
        "actions": "action_types",
        "link_types": "link_types",
        "links": "link_types",
        "datasources": "datasources",
        "observability": "observability",
        "dependents": "dependents",
        "contracts": "contract_health",
    }
    if section in card_map:
        card = cards[card_map[section]]
        if isinstance(card, dict) and "rows" in card:
            rows = card.get("rows", [])
            summary = {key: value for key, value in card.items() if key != "rows"}
        else:
            rows = []
            summary = card
        return {
            "object_type_id": object_type_id,
            "section_id": section,
            "title": section.replace("_", " ").title(),
            "summary": summary,
            "rows": rows,
        }
    supplemental = {
        "security": {"summary": {"visibility": object_type["visibility"], "groups": object_type.get("groups", [])}, "rows": []},
        "capabilities": {"summary": {"action_types": cards["action_types"]["count"], "link_types": cards["link_types"]["count"]}, "rows": []},
        "object_views": {"summary": {"configured": False}, "rows": []},
        "interfaces": _object_type_interface_state(db, object_type_id),
        "materializations": {"summary": {"datasource_count": cards["datasources"]["count"]}, "rows": cards["datasources"].get("rows", [])},
        "automations": {"summary": {"configured": False}, "rows": []},
        "usage": {"summary": {"object_count": cards["observability"].get("object_count", 0)}, "rows": cards["dependents"].get("rows", [])},
        "history": {"summary": {"updated_at": object_type["updated_at"], "created_at": object_type["created_at"]}, "rows": []},
    }
    if section not in supplemental:
        raise HTTPException(status_code=404, detail=f"Ontology section '{section_id}' not found")
    payload = supplemental[section]
    return {
        "object_type_id": object_type_id,
        "section_id": section,
        "title": section.replace("_", " ").title(),
        "summary": payload["summary"],
        "rows": payload["rows"],
    }


@router.get("/ui-state/ontology")
def ontology_ui_state(db: Session = Depends(get_db),
                      principal: production_auth.Principal = Depends(production_auth.require_permission("view"))):
    object_types = semantic_scope.accessible_query(db, principal, models.ObjectType).order_by(models.ObjectType.updated_at.desc()).all()
    selected = object_types[0] if object_types else None
    return {
        "summary": {
            "object_type_count": len(object_types),
            "selected_object_type_id": selected.id if selected else None,
            "draft_count": 0,
        },
        "primary_actions": [
            {"id": "create_draft", "label": "Generate ontology draft", "method": "POST", "path": "/ontology-generator/drafts"},
            {"id": "index", "label": "Index object type", "method": "POST", "path": "/ontology/object-types/{object_type_id}/index"},
            {"id": "version_draft", "label": "Open visual designer", "method": "POST", "path": "/artifacts/adopt"},
        ],
        "object_types": [
            {
                "id": obj.id,
                "display_name": obj.display_name,
                "description": obj.description,
                "updated_at": obj.updated_at,
                "property_count": len([key for key in (obj.properties or {}).keys() if not str(key).startswith("__")]),
            }
            for obj in object_types
        ],
        "selected_object_type": _object_type_manager_state(db, selected.id) if selected else None,
        "empty_state": None if selected else {"title": "No object types yet", "action": "Generate an ontology draft from an imported dataset."},
        "last_updated": max([obj.updated_at for obj in object_types], default=_now()),
    }


@router.get("/ui-state/ontology/object-types/{object_type_id}")
def ontology_object_type_ui_state(object_type_id: str, db: Session = Depends(get_db),
                                  principal: production_auth.Principal = Depends(production_auth.require_permission("view"))):
    semantic_scope.object_type_for(db, principal, object_type_id, "view")
    return _object_type_manager_state(db, object_type_id)


@router.get("/ui-state/ontology/object-types/{object_type_id}/walkthrough")
def ontology_object_type_walkthrough(object_type_id: str, db: Session = Depends(get_db),
                                     principal: production_auth.Principal = Depends(production_auth.require_permission("view"))):
    semantic_scope.object_type_for(db, principal, object_type_id, "view")
    return _object_type_walkthrough(db, object_type_id)


@router.get("/ui-state/ontology/object-types/{object_type_id}/sections/{section_id}")
def ontology_object_type_section(object_type_id: str, section_id: str, db: Session = Depends(get_db),
                                 principal: production_auth.Principal = Depends(production_auth.require_permission("view"))):
    semantic_scope.object_type_for(db, principal, object_type_id, "view")
    return _object_type_section_state(db, object_type_id, section_id)


@router.post("/ontology/mappings/preview")
def preview_ontology_mapping(body: OntologyMappingPreviewRequest, db: Session = Depends(get_db),
                             principal: production_auth.Principal = Depends(production_auth.require_permission("view"))):
    semantic_scope.asset_for(db, principal, body.asset_id, "view")
    semantic_scope.object_type_for(db, principal, body.object_type_id, "view")
    return _mapping_preview(db, body)


@router.post("/ontology/object-types/{object_type_id}/datasource-mappings")
def save_ontology_datasource_mapping(object_type_id: str, body: OntologyDatasourceMappingRequest, db: Session = Depends(get_db),
                                     principal: production_auth.Principal = Depends(production_auth.require_permission("edit"))):
    obj_type = semantic_scope.object_type_for(db, principal, object_type_id, "edit")
    asset = semantic_scope.asset_for(db, principal, body.asset_id, "view")
    if asset.project_id != obj_type.project_id:
        raise HTTPException(status_code=409, detail="Dataset and object type belong to different projects")
    preview_body = OntologyMappingPreviewRequest(
        asset_id=body.asset_id, object_type_id=object_type_id, mappings=body.mappings, limit=20,
    )
    preview = _mapping_preview(db, preview_body)
    if preview["errors"]:
        raise HTTPException(status_code=422, detail={"message": "Datasource mapping is invalid", "preview": preview})
    properties = dict(obj_type.properties or {})
    manager = dict(properties.get("__manager") or {})
    existing = [item for item in list(manager.get("datasource_mappings") or []) if item.get("asset_id") != body.asset_id]
    record = {
        "asset_id": body.asset_id,
        "mappings": [item.model_dump() for item in body.mappings],
        "mapped_property_count": len(body.mappings),
        "updated_at": _now(),
    }
    manager["datasource_mappings"] = existing + [record]
    properties["__manager"] = manager
    obj_type.properties = properties
    flag_modified(obj_type, "properties")
    obj_type.updated_at = _now()
    _audit(db, body.actor, "ontology.datasource_mapping.saved", "object_type", object_type_id, record)
    db.commit()
    return {"mapping": record, "preview": preview, "manager": _object_type_manager_state(db, object_type_id)}


@router.patch("/ontology/object-types/{object_type_id}/metadata")
def update_object_type_metadata(object_type_id: str, body: ObjectTypeManagerMetadataRequest, db: Session = Depends(get_db),
                                principal: production_auth.Principal = Depends(production_auth.require_permission("edit"))):
    obj_type = semantic_scope.object_type_for(db, principal, object_type_id, "edit")
    if body.display_name is not None:
        obj_type.display_name = body.display_name
    if body.description is not None:
        obj_type.description = body.description
    properties = dict(obj_type.properties or {})
    manager = dict(properties.get("__manager") or {})
    patch = body.model_dump(exclude_unset=True)
    for key in ("aliases", "point_of_contact", "contributors", "status", "visibility", "edits_enabled"):
        if key in patch:
            manager[key] = patch[key]
    if body.plural_name is not None:
        manager["plural_name"] = body.plural_name
    properties["__manager"] = manager
    obj_type.properties = properties
    obj_type.updated_at = _now()
    profile = db.get(ObjectTypeProfile, object_type_id)
    if profile:
        if body.plural_name is not None:
            profile.plural_name = body.plural_name
        if body.groups is not None:
            profile.groups = body.groups
        profile.updated_at = _now()
    _audit(db, "ontology_manager", "ontology.object_type.metadata_updated", "object_type", object_type_id, patch)
    db.commit()
    return _object_type_manager_state(db, object_type_id)


@router.post("/ontology/object-types/{object_type_id}/index")
def index_object_type(object_type_id: str, body: ObjectTypeIndexRequest = ObjectTypeIndexRequest(), db: Session = Depends(get_db),
                      principal: production_auth.Principal = Depends(production_auth.require_permission("edit"))):
    obj_type = semantic_scope.object_type_for(db, principal, object_type_id, "edit")
    properties = dict(obj_type.properties or {})
    manager = dict(properties.get("__manager") or {})
    manager["index_status"] = "indexed"
    manager["indexed_at"] = _now()
    properties["__manager"] = manager
    obj_type.properties = properties
    obj_type.updated_at = _now()
    _audit(db, body.actor, "ontology.object_type.indexed", "object_type", object_type_id, {"index_status": "indexed"})
    db.commit()
    return _object_type_manager_state(db, object_type_id)


@router.post("/ontology/object-types/{object_type_id}/open-from-pipeline")
def open_object_type_from_pipeline(object_type_id: str, body: ObjectTypeOpenFromPipelineRequest, db: Session = Depends(get_db),
                                   principal: production_auth.Principal = Depends(production_auth.require_permission("edit"))):
    obj_type = semantic_scope.object_type_for(db, principal, object_type_id, "edit")
    from . import pipeline_builder_ops
    graph = pipeline_builder_ops._get_graph(db, body.graph_id)
    if graph.project_id != obj_type.project_id:
        raise HTTPException(status_code=409, detail="Pipeline graph belongs to another project")
    properties = dict(obj_type.properties or {})
    manager = dict(properties.get("__manager") or {})
    manager["last_opened_pipeline_graph_id"] = body.graph_id
    if body.node_id:
        manager["last_opened_pipeline_node_id"] = body.node_id
    properties["__manager"] = manager
    obj_type.properties = properties
    obj_type.updated_at = _now()
    _audit(db, body.actor, "ontology.object_type.opened_from_pipeline", "object_type", object_type_id, {"graph_id": body.graph_id, "node_id": body.node_id})
    db.commit()
    return _object_type_manager_state(db, object_type_id)


@router.post("/ontology/object-types/{object_type_id}/properties")
def add_object_type_property(object_type_id: str, body: ObjectTypePropertyCreate, db: Session = Depends(get_db),
                             principal: production_auth.Principal = Depends(production_auth.require_permission("edit"))):
    obj_type = semantic_scope.object_type_for(db, principal, object_type_id, "edit")
    profile = db.get(ObjectTypeProfile, object_type_id)
    properties, profile_backed = _property_store(obj_type, profile)
    name = str(body.name).strip()
    _validate_property_spec(name, body.base_type, body.status, set(properties.keys()))
    _validate_property_constraints(name, body.model_dump())
    properties[name] = _stored_property_spec(
        base_type=body.base_type,
        status=body.status,
        required=body.required,
        display_name=body.display_name,
        indexed=body.indexed,
        sensitive=body.sensitive,
        description=body.description,
        render_hint=body.render_hint,
        shared_property_type_id=body.shared_property_type_id,
        constraints={
            "minimum": body.minimum, "maximum": body.maximum, "min_length": body.min_length,
            "max_length": body.max_length, "pattern": body.pattern, "enum": body.enum,
            "unit": body.unit, "geometry_type": body.geometry_type,
        },
        profile_backed=profile_backed,
    )
    _write_property_store(obj_type, profile, properties, profile_backed=profile_backed)
    _audit(db, body.actor, "ontology.object_type.property_created", "object_type", object_type_id, {
        "property_name": name,
        "base_type": body.base_type,
        "profile_backed": profile_backed,
    })
    _sync_semantic_contract(db, obj_type, body.actor)
    db.commit()
    return _object_type_manager_state(db, object_type_id)


@router.patch("/ontology/object-types/{object_type_id}/properties/order")
def reorder_object_type_properties(object_type_id: str, body: ObjectTypePropertyOrderRequest, db: Session = Depends(get_db),
                                   principal: production_auth.Principal = Depends(production_auth.require_permission("edit"))):
    obj_type = semantic_scope.object_type_for(db, principal, object_type_id, "edit")
    profile = db.get(ObjectTypeProfile, object_type_id)
    properties, profile_backed = _property_store(obj_type, profile)
    requested = [str(name).strip() for name in body.order if str(name).strip()]
    unknown = [name for name in requested if name not in properties]
    if unknown:
        raise HTTPException(status_code=422, detail=[f"Unknown property in order: {name}" for name in unknown])
    ordered_names = requested + [name for name in properties.keys() if name not in requested]
    next_properties = {name: properties[name] for name in ordered_names}
    _write_property_store(obj_type, profile, next_properties, profile_backed=profile_backed)
    _audit(db, body.actor, "ontology.object_type.properties_reordered", "object_type", object_type_id, {
        "order": ordered_names,
        "profile_backed": profile_backed,
    })
    _sync_semantic_contract(db, obj_type, body.actor)
    db.commit()
    return _object_type_manager_state(db, object_type_id)


@router.patch("/ontology/object-types/{object_type_id}/properties/{property_name}")
def update_object_type_property(object_type_id: str, property_name: str, body: ObjectTypePropertyPatch, db: Session = Depends(get_db),
                                principal: production_auth.Principal = Depends(production_auth.require_permission("edit"))):
    obj_type = semantic_scope.object_type_for(db, principal, object_type_id, "edit")
    profile = db.get(ObjectTypeProfile, object_type_id)
    properties, profile_backed = _property_store(obj_type, profile)
    if property_name not in properties:
        raise HTTPException(status_code=404, detail=f"Property '{property_name}' not found")
    primary_key = _property_primary_key(obj_type, profile)
    patch = body.model_dump(exclude_unset=True)
    next_name = str(patch.get("name") or property_name).strip()
    if primary_key == property_name and next_name != property_name:
        raise HTTPException(status_code=422, detail=[f"Primary key property '{property_name}' cannot be renamed"])
    existing = properties[property_name] if isinstance(properties[property_name], dict) else {}
    base_type = str(patch.get("base_type") or existing.get("base_type") or existing.get("type") or "string")
    status = str(patch.get("status") or existing.get("status") or "active")
    _validate_property_spec(next_name, base_type, status, set(properties.keys()), original_name=property_name)
    _validate_property_constraints(next_name, {**existing, **patch})
    required = bool(patch["required"]) if "required" in patch else bool(existing.get("required"))
    display_name = patch["display_name"] if "display_name" in patch else existing.get("display_name")
    indexed = bool(patch["indexed"]) if "indexed" in patch else bool(existing.get("indexed"))
    sensitive = bool(patch["sensitive"]) if "sensitive" in patch else bool(existing.get("sensitive"))
    description = patch["description"] if "description" in patch else existing.get("description")
    render_hint = patch["render_hint"] if "render_hint" in patch else existing.get("render_hint")
    shared_property_type_id = patch["shared_property_type_id"] if "shared_property_type_id" in patch else existing.get("shared_property_type_id")
    next_spec = _stored_property_spec(
        base_type=base_type,
        status=status,
        required=required,
        display_name=display_name,
        indexed=indexed,
        sensitive=sensitive,
        description=description,
        render_hint=render_hint,
        shared_property_type_id=shared_property_type_id,
        constraints={
            key: patch[key] if key in patch else existing.get(key)
            for key in ("minimum", "maximum", "min_length", "max_length", "pattern", "enum", "unit", "geometry_type")
        },
        profile_backed=profile_backed,
    )
    next_properties: Dict[str, Any] = {}
    for name, spec in properties.items():
        if name == property_name:
            next_properties[next_name] = next_spec
        else:
            next_properties[name] = spec
    if profile and profile.title_key == property_name:
        profile.title_key = next_name
    _write_property_store(obj_type, profile, next_properties, profile_backed=profile_backed)
    _audit(db, body.actor, "ontology.object_type.property_updated", "object_type", object_type_id, {
        "property_name": property_name,
        "next_property_name": next_name,
        "profile_backed": profile_backed,
    })
    _sync_semantic_contract(db, obj_type, body.actor)
    db.commit()
    return _object_type_manager_state(db, object_type_id)


@router.delete("/ontology/object-types/{object_type_id}/properties/{property_name}")
def archive_object_type_property(object_type_id: str, property_name: str, db: Session = Depends(get_db),
                                 principal: production_auth.Principal = Depends(production_auth.require_permission("edit"))):
    obj_type = semantic_scope.object_type_for(db, principal, object_type_id, "edit")
    profile = db.get(ObjectTypeProfile, object_type_id)
    properties, profile_backed = _property_store(obj_type, profile)
    if property_name not in properties:
        raise HTTPException(status_code=404, detail=f"Property '{property_name}' not found")
    primary_key = _property_primary_key(obj_type, profile)
    if primary_key == property_name:
        raise HTTPException(status_code=422, detail=[f"Primary key property '{property_name}' cannot be archived"])
    archived_spec = properties[property_name]
    next_properties = {name: spec for name, spec in properties.items() if name != property_name}
    _write_property_store(obj_type, profile, next_properties, profile_backed=profile_backed)
    object_properties = dict(obj_type.properties or {})
    manager = dict(object_properties.get("__manager") or {})
    archived = dict(manager.get("archived_properties") or {})
    archived[property_name] = {
        "archived_at": _now(),
        "profile_backed": profile_backed,
        "spec": archived_spec,
    }
    manager["archived_properties"] = archived
    object_properties["__manager"] = manager
    obj_type.properties = object_properties
    obj_type.updated_at = _now()
    _audit(db, "ontology_manager", "ontology.object_type.property_archived", "object_type", object_type_id, {
        "property_name": property_name,
        "profile_backed": profile_backed,
        "values_preserved": True,
    })
    _sync_semantic_contract(db, obj_type, "ontology_manager")
    db.commit()
    return _object_type_manager_state(db, object_type_id)


# ---------------------------------------------------------------------------
# Faithful Action engine: params + submission criteria + mutations + effects
# ---------------------------------------------------------------------------
def _resolve(expr: Any, parameters: Dict[str, Any]) -> Any:
    """Resolve a mutation expression against action parameters."""
    if isinstance(expr, str) and expr.startswith("$"):
        return parameters.get(expr[1:])
    if isinstance(expr, dict):
        if "from" in expr:
            return parameters.get(expr["from"])
        if "value" in expr:
            return expr["value"]
        if "template" in expr:
            try:
                return str(expr["template"]).format(**parameters)
            except Exception:
                return expr["template"]
    return expr


def _param_type_ok(value: Any, declared: Optional[str]) -> bool:
    if declared in (None, "any", "objectReference", "string"):
        return value is None or isinstance(value, str) if declared == "string" else True
    if declared in ("integer", "long", "short", "byte"):
        return isinstance(value, int) and not isinstance(value, bool)
    if declared in ("double", "float", "decimal"):
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if declared == "boolean":
        return isinstance(value, bool)
    if declared == "array":
        return isinstance(value, list)
    if declared in ("struct", "object"):
        return isinstance(value, dict)
    return True


def _cmp(op: str, left: Any, right: Any) -> bool:
    try:
        if op in ("eq", "=="):
            return left == right
        if op in ("ne", "!="):
            return left != right
        if op == "gt":
            return left > right
        if op == "gte":
            return left >= right
        if op == "lt":
            return left < right
        if op == "lte":
            return left <= right
        if op == "in":
            return left in (right or [])
        if op == "not_null":
            return left is not None
        if op == "truthy":
            return bool(left)
    except TypeError:
        return False
    return False


def _validate_params(action: models.ActionType, parameters: Dict[str, Any], db: Session) -> List[str]:
    errors: List[str] = []
    schema = action.parameters or {}
    for pname, definition in schema.items():
        decl = definition if isinstance(definition, dict) else {"type": definition}
        required = decl.get("required", not isinstance(definition, dict))
        if pname not in parameters or parameters.get(pname) is None:
            if required:
                errors.append(f"Missing required parameter '{pname}'")
            continue
        value = parameters[pname]
        dtype = decl.get("type")
        if not _param_type_ok(value, dtype):
            errors.append(f"Parameter '{pname}' expected {dtype}, got {type(value).__name__}")
        if "allowed_values" in decl and value not in decl["allowed_values"]:
            errors.append(f"Parameter '{pname}' value '{value}' not in allowed_values")
        if "min" in decl and isinstance(value, (int, float)) and value < decl["min"]:
            errors.append(f"Parameter '{pname}' below min {decl['min']}")
        if "max" in decl and isinstance(value, (int, float)) and value > decl["max"]:
            errors.append(f"Parameter '{pname}' above max {decl['max']}")
        # object reference existence
        if dtype == "objectReference" and isinstance(value, str):
            if not db.get(models.ObjectInstance, value):
                errors.append(f"Parameter '{pname}' references missing object '{value}'")
    return errors


def _evaluate_submission_criteria(criteria: List[dict], parameters: Dict[str, Any], db: Session) -> List[str]:
    failures: List[str] = []
    for crit in criteria or []:
        op = crit.get("op", "truthy")
        if "parameter" in crit:
            left = parameters.get(crit["parameter"])
        elif "object_param" in crit:
            obj_id = parameters.get(crit["object_param"])
            obj = db.get(models.ObjectInstance, obj_id) if obj_id else None
            left = (obj.properties or {}).get(crit.get("property")) if obj else None
        else:
            left = None
        if not _cmp(op, left, crit.get("value")):
            failures.append(crit.get("message", f"Submission criterion failed: {crit}"))
    return failures


def _normalize_function_edit(edit: Any, params: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Coerce a function-returned edit (or a proposed_action from a LogicFunction
    block) into a mutation dict understood by the mutation set below. Supported
    shapes:
      * {"op": "modify-object"|"create-object"|"delete-object"|"add-link"|
         "remove-link", ...}  (already-normalized mutation)
      * {"action_type_id": ..., "parameters": {...}}  (a proposed action — the
        referenced ActionType's own mutations are expanded by the caller)
    """
    if not isinstance(edit, dict):
        return None
    if edit.get("op"):
        return edit
    return None


def _run_function_backed(action: models.ActionType, function_id: str,
                         params: Dict[str, Any], db: Session) -> List[Dict[str, Any]]:
    """
    Delegate execution to the referenced ontology function (LogicFunction). The
    function runs via runtime.execute_logic_blocks; its proposed_actions (and any
    explicit 'edits' it sets as an output) are collected and expanded into the
    mutation set so the action applies the function's returned edits.
    """
    fn = db.get(models.LogicFunction, function_id)
    if not fn:
        raise HTTPException(status_code=404,
                            detail=f"function_id '{function_id}' references missing LogicFunction")
    try:
        run = runtime.execute_logic_blocks(db, logic_function=fn, inputs=params)
    except Exception as exc:  # surface logic errors as 422
        raise HTTPException(status_code=422, detail={"function_error": str(exc)})

    collected: List[Dict[str, Any]] = []
    # (a) explicit edits emitted as an output named 'edits'
    edits_out = (run.get("outputs") or {}).get("edits")
    if isinstance(edits_out, list):
        for e in edits_out:
            norm = _normalize_function_edit(e, params)
            if norm:
                collected.append(norm)
    # (b) proposed_actions -> expand each referenced action's own mutations
    for proposal in run.get("proposed_actions") or []:
        ref_id = proposal.get("action_type_id")
        ref = db.get(models.ActionType, ref_id) if ref_id else None
        if not ref:
            continue
        ref_params = proposal.get("parameters") or {}
        ref_rules = ref.rules or {}
        for mut in (ref_rules.get("mutations") or ref_rules.get("object_mutations") or []):
            # resolve the referenced action's mutation against the proposal params
            collected.append({k: (_resolve(v, ref_params) if k in
                              ("object_id", "source_object_id", "target_object_id") else v)
                              for k, v in mut.items()})
    return collected


def _apply_mutation_set(mutations: List[Dict[str, Any]], params: Dict[str, Any],
                        action_type_id: str, project_id: str, now: int, db: Session,
                        mutated_objects: List[str], links_changed: List[str],
                        reversal: List[Dict[str, Any]], actor: str = "system") -> None:
    """Apply the documented mutation set, capturing before-values for undo."""
    for m in mutations:
        op = m.get("op", "modify-object")
        if op in ("create-object", "modify-object"):
            otype = m.get("object_type_id")
            oid = _resolve(m.get("object_id"), params) or (m.get("object_id_param") and params.get(m["object_id_param"]))
            existing = db.get(models.ObjectInstance, str(oid)) if oid else None
            sets = {k: _resolve(v, params) for k, v in (m.get("set") or {}).items()}
            if existing is None:
                if op == "modify-object" and not m.get("create_if_missing"):
                    raise HTTPException(status_code=404, detail=f"Object '{oid}' not found for modify")
                if not otype:
                    raise HTTPException(status_code=422, detail="create-object requires object_type_id")
                new_id = str(oid) if oid else uuid.uuid4().hex
                object_writes.create_object(
                    db, object_id=new_id, object_type_id=otype, project_id=project_id,
                    properties=sets, actor=actor,
                    event_type="ontology.object.created", source_type="action",
                    source_id=action_type_id,
                    lineage={"created_by_action": action_type_id}, now=now,
                    evidence={"action_type_id": action_type_id},
                )
                mutated_objects.append(new_id)
                reversal.append({"op": "create-object", "object_id": new_id})
            else:
                if existing.project_id != project_id:
                    raise HTTPException(status_code=409, detail="Object mutation crosses a project boundary")
                _updated, before = object_writes.update_object(
                    db, existing, properties=sets, actor=actor,
                    event_type="ontology.object.updated", source_type="action",
                    source_id=action_type_id,
                    lineage={"last_action_id": action_type_id}, now=now,
                    evidence={"action_type_id": action_type_id},
                )
                mutated_objects.append(existing.id)
                # store the prior values for exactly the keys we changed
                reversal.append({"op": "modify-object", "object_id": existing.id,
                                 "before": {k: before.get(k) for k in sets},
                                 "before_present": {k: (k in before) for k in sets}})
        elif op == "delete-object":
            oid = _resolve(m.get("object_id"), params)
            inst = db.get(models.ObjectInstance, str(oid)) if oid else None
            if inst is None:
                raise HTTPException(status_code=404, detail=f"Object '{oid}' not found for delete")
            if inst.project_id != project_id:
                raise HTTPException(status_code=409, detail="Object mutation crosses a project boundary")
            reversal.append({"op": "delete-object", "object_id": str(oid),
                             "object_type_id": inst.object_type_id,
                             "before": dict(inst.properties or {})})
            db.delete(inst)
            mutated_objects.append(str(oid))
        elif op in ("add-link", "remove-link"):
            ltype = m.get("link_type_id")
            src = _resolve(m.get("source_object_id"), params)
            tgt = _resolve(m.get("target_object_id"), params)
            link_id = f"{ltype}:{src}:{tgt}"
            if op == "add-link":
                link_type = db.get(models.LinkType, ltype)
                source = db.get(models.ObjectInstance, str(src))
                target = db.get(models.ObjectInstance, str(tgt))
                if not link_type or not source or not target:
                    raise HTTPException(status_code=422, detail="Link mutation references missing resources")
                if any(row.project_id != project_id for row in (link_type, source, target)):
                    raise HTTPException(status_code=409, detail="Link mutation crosses a project boundary")
                if not db.get(models.LinkInstance, link_id):
                    db.add(models.LinkInstance(
                        id=link_id, project_id=project_id, link_type_id=ltype, source_object_id=str(src),
                        target_object_id=str(tgt), properties={}, created_at=now))
                    reversal.append({"op": "add-link", "link_id": link_id})
                links_changed.append(link_id)
            else:
                link = db.get(models.LinkInstance, link_id)
                if link:
                    if link.project_id != project_id:
                        raise HTTPException(status_code=409, detail="Link mutation crosses a project boundary")
                    reversal.append({"op": "remove-link", "link_id": link_id, "link_type_id": ltype,
                                     "source_object_id": str(src), "target_object_id": str(tgt),
                                     "properties": dict(link.properties or {})})
                    db.delete(link)
                links_changed.append(link_id)
        else:
            raise HTTPException(status_code=422, detail=f"Unknown mutation op '{op}'")


@router.post("/ontology/action-types/{action_type_id}/execute")
def execute_action_faithful(
    action_type_id: str,
    body: ActionExecuteRequest,
    principal: production_auth.Principal = Depends(production_auth.require_permission("execute")),
    db: Session = Depends(get_db),
):
    action = db.get(models.ActionType, action_type_id)
    if not action:
        raise HTTPException(status_code=404, detail=f"ActionType '{action_type_id}' not found")
    project_id = action.project_id or "default"
    tenancy.assert_project_permission(db, principal, project_id, "execute")
    rules = action.rules or {}
    risk_level = rules.get("risk_level", rules.get("risk", ""))
    if rules.get("requires_approval") or rules.get("approval_required") or str(risk_level).lower() in {"high", "critical"}:
        raise HTTPException(
            status_code=409,
            detail="Approval-gated actions must be executed through POST /actions/execute",
        )
    for mutation in rules.get("mutations") or rules.get("object_mutations") or []:
        object_type_id = mutation.get("object_type_id")
        if object_type_id:
            object_type = db.get(models.ObjectType, object_type_id)
            if not object_type:
                raise HTTPException(status_code=422, detail=f"Unknown object type '{object_type_id}'")
            if object_type.project_id != project_id:
                raise HTTPException(status_code=409, detail="Action mutation crosses a project boundary")
    params = body.parameters
    actor = principal.id if production_auth.auth_mode() == "oidc" else (body.actor or principal.id)

    # 1) typed parameter validation
    perrors = _validate_params(action, params, db)
    if perrors:
        raise HTTPException(status_code=422, detail={"parameter_errors": perrors})

    # 2) submission criteria
    failures = _evaluate_submission_criteria(rules.get("submission_criteria", []), params, db)
    if failures:
        raise HTTPException(status_code=422, detail={"submission_criteria_failed": failures})

    mutations = rules.get("mutations") or rules.get("object_mutations") or []
    side_effects = rules.get("side_effects", [])
    function_id = rules.get("function_id")

    if body.dry_run:
        return {"action_type_id": action_type_id, "submittable": True,
                "planned_mutations": len(mutations), "planned_side_effects": len(side_effects),
                "function_backed": bool(function_id)}

    mutated_objects: List[str] = []
    links_changed: List[str] = []
    reversal: List[Dict[str, Any]] = []
    now = _now()

    # 3a) FUNCTION-BACKED rule: delegate to the ontology function and apply its
    #     returned edits (in addition to any inline mutations on the action).
    if function_id:
        fn_mutations = _run_function_backed(action, function_id, params, db)
        _apply_mutation_set(fn_mutations, params, action_type_id, project_id, now, db,
                            mutated_objects, links_changed, reversal, actor=actor)

    # 3b) inline mutation set
    _apply_mutation_set(mutations, params, action_type_id, project_id, now, db,
                        mutated_objects, links_changed, reversal, actor=actor)

    # 4) side effects
    fired = []
    for eff in side_effects:
        etype = eff.get("type")
        if etype == "notification":
            _audit(db, actor, "action.notification", "action_type", action_type_id,
                   {"recipient": eff.get("recipient"), "message": _resolve(eff.get("message"), params)})
            fired.append("notification")
        elif etype == "webhook":
            db.add(models_action.OutboxEvent(
                id=uuid.uuid4().hex, project_id=project_id, action_type_id=action_type_id,
                payload={"url": eff.get("url"), "payload": eff.get("payload", params)},
                status="PENDING", created_at=now))
            fired.append("webhook")

    # 5) queryable action log (Act/act_) + control-plane audit
    log_id = uuid.uuid4().hex
    db.add(ActionLog(
        id=log_id, project_id=project_id, action_type_id=action_type_id, actor=actor,
        parameters=params, mutated_object_ids=mutated_objects, reversal=reversal,
        function_id=function_id, undone=0, created_at=now))
    _audit(db, actor, "ontology.action.executed", "action_type", action_type_id,
           {"mutated_objects": mutated_objects, "links_changed": links_changed,
            "side_effects": fired, "action_log_id": log_id, "project_id": project_id})
    db.commit()
    return {
        "action_type_id": action_type_id, "status": "applied",
        "mutated_object_ids": mutated_objects, "links_changed": links_changed,
        "side_effects_fired": fired, "submission": {"submittable": True},
        "action_log_id": log_id, "function_backed": bool(function_id),
    }


# ---------------------------------------------------------------------------
# Queryable ACTION LOG + UNDO
# ---------------------------------------------------------------------------
@router.get("/ontology/action-log", response_model=List[ActionLogRead])
def list_action_log(
    action_type_id: Optional[str] = None,
    actor: Optional[str] = None,
    limit: int = 100,
    db: Session = Depends(get_db),
    principal: production_auth.Principal = Depends(production_auth.require_permission("view")),
):
    q = semantic_scope.accessible_query(db, principal, ActionLog)
    if action_type_id is not None:
        q = q.filter(ActionLog.action_type_id == action_type_id)
    if actor is not None:
        q = q.filter(ActionLog.actor == actor)
    rows = q.order_by(ActionLog.created_at.desc()).limit(max(1, min(int(limit), 1000))).all()
    return rows


@router.get("/ontology/action-log/{log_id}", response_model=ActionLogRead)
def get_action_log(log_id: str, db: Session = Depends(get_db),
                   principal: production_auth.Principal = Depends(production_auth.require_permission("view"))):
    row = semantic_scope.owned_row(db, principal, ActionLog, log_id, "view", "ActionLog")
    return row


def _reversal_row(db: Session, model, row_id, project_id):
    """A row named by a reversal entry, but only from the log's own project.

    The reversal payload carries bare ids, so resolving one with `db.get` trusts the
    payload to name a row inside the project the caller was authorized for. It is the
    payload, not the caller, that decides which id is read, and an entry naming an id
    outside that project made undo modify or delete another tenant's row under a
    permission that looked correct. T2 of GOAL_TENANCY_2026-08-27.

    Existence checks before an insert are deliberately *not* routed through here: object
    and link ids are primary keys, so a row in another project still occupies the id, and
    scoping that check would turn a skipped restore into a duplicate-key insert.
    """
    if not row_id:
        return None
    return (db.query(model)
            .filter(model.id == str(row_id), model.project_id == project_id)
            .first())


@router.post("/ontology/action-log/{log_id}/undo")
def undo_action_log(log_id: str, actor: str = "system", db: Session = Depends(get_db),
                    principal: production_auth.Principal = Depends(production_auth.require_permission("execute"))):
    row = semantic_scope.owned_row(db, principal, ActionLog, log_id, "execute", "ActionLog")
    if row.undone:
        raise HTTPException(status_code=409, detail=f"ActionLog '{log_id}' has already been undone")

    now = _now()
    restored: List[str] = []
    # Reverse in LIFO order so dependent edits unwind cleanly.
    for entry in reversed(row.reversal or []):
        op = entry.get("op")
        if op == "modify-object":
            inst = _reversal_row(db, models.ObjectInstance, entry.get("object_id"), row.project_id)
            if inst is None:
                continue
            props = dict(inst.properties or {})
            before = entry.get("before") or {}
            present = entry.get("before_present") or {}
            for key in before:
                if present.get(key, True):
                    props[key] = before[key]
                else:
                    props.pop(key, None)
            object_writes.update_object(
                db, inst, properties=props, actor=actor,
                event_type="ontology.object.updated", source_type="action_undo",
                source_id=log_id, lineage={"undo_of_action_log": log_id}, now=now,
                merge=False,
                evidence={"undo_of_action_log": log_id},
            )
            restored.append(inst.id)
        elif op == "create-object":
            inst = _reversal_row(db, models.ObjectInstance, entry.get("object_id"), row.project_id)
            if inst is not None:
                db.delete(inst)
                restored.append(entry.get("object_id"))
        elif op == "delete-object":
            # Global on purpose: the id is a primary key. See _reversal_row.
            if db.get(models.ObjectInstance, entry.get("object_id")) is None:
                object_writes.create_object(
                    db, object_id=entry.get("object_id"), object_type_id=entry.get("object_type_id"),
                    project_id=row.project_id, properties=dict(entry.get("before") or {}),
                    actor=actor, event_type="ontology.object.created",
                    source_type="action_undo", source_id=log_id,
                    lineage={"restored_by_undo": log_id}, now=now,
                    evidence={"undo_of_action_log": log_id},
                )
                restored.append(entry.get("object_id"))
        elif op == "add-link":
            link = _reversal_row(db, models.LinkInstance, entry.get("link_id"), row.project_id)
            if link is not None:
                db.delete(link)
        elif op == "remove-link":
            # Global on purpose: the id is a primary key. See _reversal_row.
            if db.get(models.LinkInstance, entry.get("link_id")) is None:
                db.add(models.LinkInstance(
                    id=entry.get("link_id"), project_id=row.project_id, link_type_id=entry.get("link_type_id"),
                    source_object_id=entry.get("source_object_id"),
                    target_object_id=entry.get("target_object_id"),
                    properties=dict(entry.get("properties") or {}), created_at=now))

    row.undone = 1
    _audit(db, actor, "ontology.action.undone", "action_type", row.action_type_id,
           {"action_log_id": log_id, "restored_object_ids": restored})
    db.commit()
    return {"action_log_id": log_id, "status": "undone",
            "restored_object_ids": restored, "reversed_operations": len(row.reversal or [])}


# ---------------------------------------------------------------------------
# Object-type EDIT / DELETE
# ---------------------------------------------------------------------------
def _owning_project(properties) -> str:
    """The project a `__manager` blob names, read the way its consumers read it."""
    manager = (properties or {}).get("__manager")
    manager = manager if isinstance(manager, dict) else {}
    return str(manager.get("project_id") or "default")


@router.put("/ontology/object-types/{object_type_id}")
def update_object_type(object_type_id: str, body: ObjectTypeUpdate, db: Session = Depends(get_db),
                       principal: production_auth.Principal = Depends(
                           production_auth.require_permission("edit"))):
    # These two routes are the only path that mutates or destroys an object type,
    # and neither resolved it through semantic_scope, so a caller edited any
    # project's schema; both audited as actor "system", so the trail never named
    # them. T6 of GOAL_TENANCY_2026-08-27.
    obj_type = semantic_scope.object_type_for(db, principal, object_type_id, "edit")
    if body.display_name is not None:
        obj_type.display_name = body.display_name
    if body.description is not None:
        obj_type.description = body.description
    if body.properties is not None:
        # `properties["__manager"]["project_id"]` is not decoration: aip_agents,
        # apps and main all read it to decide which project owns this type, and
        # main uses it to refuse cross-project automation references. Replacing
        # `properties` wholesale could therefore re-home a type and defeat a check
        # in another module, which scoping the read alone does not prevent.
        before = _owning_project(obj_type.properties)
        after = _owning_project(body.properties)
        if after != before:
            raise HTTPException(
                status_code=403,
                detail=(f"an object type's owning project is not editable here "
                        f"('{before}' -> '{after}'); it decides who may reference it"))
        obj_type.properties = body.properties
    obj_type.updated_at = _now()
    _audit(db, principal.id, "ontology.object_type.updated", "object_type", object_type_id,
           {"display_name": obj_type.display_name})
    db.commit(); db.refresh(obj_type)
    return {
        "id": obj_type.id, "display_name": obj_type.display_name,
        "description": obj_type.description, "properties": obj_type.properties,
        "updated_at": obj_type.updated_at,
    }


@router.delete("/ontology/object-types/{object_type_id}")
def delete_object_type(object_type_id: str, db: Session = Depends(get_db),
                       principal: production_auth.Principal = Depends(
                           production_auth.require_permission("edit"))):
    obj_type = semantic_scope.object_type_for(db, principal, object_type_id, "edit")
    # Counted across every project on purpose. This is a refusal guard, and narrowing it
    # to the caller's project would let a delete proceed while instances of the type
    # survive elsewhere -- a filter here would weaken the check, not scope it.
    instance_count = db.query(models.ObjectInstance).filter(
        models.ObjectInstance.object_type_id == object_type_id).count()
    if instance_count:
        raise HTTPException(status_code=409,
                            detail=f"ObjectType '{object_type_id}' has {instance_count} instances; delete them first")
    profile = db.get(ObjectTypeProfile, object_type_id)
    if profile:
        db.delete(profile)
    db.delete(obj_type)
    _audit(db, principal.id, "ontology.object_type.deleted", "object_type", object_type_id, {})
    db.commit()
    return {"id": object_type_id, "deleted": True}


# ---------------------------------------------------------------------------
# Primary-key validation against existing ObjectInstances
# ---------------------------------------------------------------------------
@router.post("/ontology/object-types/{object_type_id}/validate-primary-key")
def validate_primary_key(object_type_id: str, body: ValidatePrimaryKeyRequest, db: Session = Depends(get_db)):
    obj_type = db.get(models.ObjectType, object_type_id)
    if not obj_type:
        raise HTTPException(status_code=404, detail=f"ObjectType '{object_type_id}' not found")
    profile = db.get(ObjectTypeProfile, object_type_id)
    if not profile or not profile.primary_key:
        raise HTTPException(status_code=404,
                            detail=f"ObjectType '{object_type_id}' has no profile primary key configured")
    pk = profile.primary_key
    if pk not in body.properties or body.properties.get(pk) is None:
        raise HTTPException(status_code=422,
                            detail={"errors": [f"primary_key '{pk}' is missing from supplied properties"]})
    pk_value = body.properties[pk]

    duplicates: List[str] = []
    for inst in db.query(models.ObjectInstance).filter(
            models.ObjectInstance.object_type_id == object_type_id).all():
        if (inst.properties or {}).get(pk) == pk_value:
            duplicates.append(inst.id)

    return {
        "object_type_id": object_type_id,
        "primary_key": pk,
        "value": pk_value,
        "unique": len(duplicates) == 0,
        "duplicate": len(duplicates) > 0,
        "conflicting_object_ids": duplicates,
    }

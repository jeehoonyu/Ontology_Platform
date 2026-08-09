"""
Ontology Manager: branching + proposals (governance of ontology changes).

Tables:
  - ontology_branches
  - ontology_proposals

Endpoints:
  POST /ontology/branches
  GET  /ontology/branches
  POST /ontology/proposals
  GET  /ontology/proposals
  GET  /ontology/proposals/{id}
  POST /ontology/proposals/{id}/submit
  POST /ontology/proposals/{id}/decision
  POST /ontology/proposals/{id}/merge
"""

import hashlib
import json
import re
import time
import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import JSON, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, Session, mapped_column

from . import models, models_action, ontology_core, semantic_scope, tenancy
from .database import Base, get_db
from .production_auth import Principal, require_permission

# ---------------------------------------------------------------------------
# SQLAlchemy Models
# ---------------------------------------------------------------------------


class OntologyBranch(Base):
    __tablename__ = "ontology_branches"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    project_id: Mapped[str] = mapped_column(String, nullable=False, default="default", index=True)
    display_name: Mapped[str] = mapped_column(String, nullable=False)
    base_branch: Mapped[str] = mapped_column(String, nullable=False, default="main")
    status: Mapped[str] = mapped_column(String, nullable=False, default="open")  # open | merged
    created_at: Mapped[int] = mapped_column(Integer, default=lambda: int(time.time()))


class OntologyProposal(Base):
    __tablename__ = "ontology_proposals"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    project_id: Mapped[str] = mapped_column(String, nullable=False, default="default", index=True)
    branch_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    title: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    changes: Mapped[List] = mapped_column(JSON, default=list)
    # status: draft | submitted | approved | merged | rejected
    status: Mapped[str] = mapped_column(String, nullable=False, default="draft")
    reviewer: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    created_at: Mapped[int] = mapped_column(Integer, default=lambda: int(time.time()))
    decided_at: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)


class OntologyRevision(Base):
    """Immutable project ontology snapshot used for review, release, and rollback."""
    __tablename__ = "ontology_revisions"
    __table_args__ = (UniqueConstraint("project_id", "revision", name="uq_ontology_revision_project_number"),)

    id: Mapped[str] = mapped_column(String, primary_key=True)
    project_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, default="DRAFT", index=True)
    parent_revision_id: Mapped[Optional[str]] = mapped_column(String, nullable=True, index=True)
    branch_id: Mapped[Optional[str]] = mapped_column(String, nullable=True, index=True)
    manifest: Mapped[dict] = mapped_column(JSON, default=dict)
    checksum: Mapped[str] = mapped_column(String, nullable=False)
    validation: Mapped[dict] = mapped_column(JSON, default=dict)
    created_by: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[int] = mapped_column(Integer, nullable=False)
    published_at: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)


class OntologyChangeSet(Base):
    """Reviewable set of semantic changes and its generated migration evidence."""
    __tablename__ = "ontology_change_sets"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    project_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    title: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    base_revision_id: Mapped[Optional[str]] = mapped_column(String, nullable=True, index=True)
    draft_revision_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    proposal_id: Mapped[Optional[str]] = mapped_column(String, nullable=True, index=True)
    status: Mapped[str] = mapped_column(String, nullable=False, default="DRAFT", index=True)
    changes: Mapped[list] = mapped_column(JSON, default=list)
    diff: Mapped[dict] = mapped_column(JSON, default=dict)
    impact: Mapped[dict] = mapped_column(JSON, default=dict)
    validation: Mapped[dict] = mapped_column(JSON, default=dict)
    migration_plan: Mapped[dict] = mapped_column(JSON, default=dict)
    created_by: Mapped[str] = mapped_column(String, nullable=False)
    reviewer: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    created_at: Mapped[int] = mapped_column(Integer, nullable=False)
    updated_at: Mapped[int] = mapped_column(Integer, nullable=False)


class OntologyEnvironment(Base):
    __tablename__ = "ontology_environments"
    __table_args__ = (UniqueConstraint("project_id", "name", name="uq_ontology_environment_project_name"),)

    id: Mapped[str] = mapped_column(String, primary_key=True)
    project_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    current_revision_id: Mapped[Optional[str]] = mapped_column(String, nullable=True, index=True)
    previous_revision_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    updated_by: Mapped[str] = mapped_column(String, nullable=False)
    updated_at: Mapped[int] = mapped_column(Integer, nullable=False)


# ---------------------------------------------------------------------------
# Pydantic Schemas
# ---------------------------------------------------------------------------

# -- Branch --

class BranchCreate(BaseModel):
    id: Optional[str] = None
    display_name: str
    base_branch: str = "main"
    project_id: str = "default"


class BranchRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    project_id: str
    display_name: str
    base_branch: str
    status: str
    created_at: int


# -- Proposal --

class ProposalCreate(BaseModel):
    id: Optional[str] = None
    branch_id: str
    title: str
    description: Optional[str] = None
    changes: List[Dict[str, Any]] = Field(default_factory=list)


class ProposalRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    project_id: str
    branch_id: str
    title: str
    description: Optional[str]
    changes: List[Dict[str, Any]]
    status: str
    reviewer: Optional[str]
    created_at: int
    decided_at: Optional[int]


class DecisionBody(BaseModel):
    approve: bool
    reviewer: str


class RevisionCaptureRequest(BaseModel):
    project_id: str = "default"
    branch_id: Optional[str] = None
    object_type_ids: List[str] = Field(default_factory=list)


class ChangeSetCreate(BaseModel):
    project_id: str = "default"
    title: str = Field(min_length=1, max_length=200)
    description: Optional[str] = None
    base_revision_id: Optional[str] = None
    branch_id: Optional[str] = None
    proposal_id: Optional[str] = None
    capture_current: bool = False
    changes: List[Dict[str, Any]] = Field(default_factory=list)


class ChangeSetDecision(BaseModel):
    approve: bool


class ChangeSetPublishRequest(BaseModel):
    environment: str = Field(default="production", pattern=r"^[A-Za-z][A-Za-z0-9_.-]*$")
    expected_checksum: Optional[str] = None
    allow_breaking: bool = False
    acknowledged_consumer_binding_ids: List[str] = Field(default_factory=list)


class EnvironmentRollbackRequest(BaseModel):
    project_id: str = "default"
    revision_id: str


API_NAME = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")
RESOURCE_ID = re.compile(r"^[A-Za-z][A-Za-z0-9_.-]*$")
SUPPORTED_PROPERTY_TYPES = {
    "string", "integer", "long", "short", "byte", "number", "double", "float", "decimal",
    "boolean", "date", "timestamp", "json", "array", "struct", "enum", "geometry", "geoshape", "geo",
}


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

router = APIRouter(tags=["ontology-versioning"])


def _branch_not_found(branch_id: str):
    raise HTTPException(status_code=404, detail=f"OntologyBranch '{branch_id}' not found")


def _proposal_not_found(proposal_id: str):
    raise HTTPException(status_code=404, detail=f"OntologyProposal '{proposal_id}' not found")


def _append_audit(
    db: Session,
    actor: str,
    event_type: str,
    subject_type: str,
    subject_id: str,
    payload: Dict[str, Any],
):
    db.add(
        models_action.AuditLog(
            id=uuid.uuid4().hex,
            actor=actor,
            event_type=event_type,
            subject_type=subject_type,
            subject_id=subject_id,
            payload=payload,
        )
    )


def _now() -> int:
    return int(time.time())


def _checksum(manifest: Dict[str, Any]) -> str:
    canonical = json.dumps(manifest, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _copy_json(value: Any) -> Any:
    return json.loads(json.dumps(value))


def _next_revision_number(db: Session, project_id: str) -> int:
    latest = db.query(OntologyRevision).filter(OntologyRevision.project_id == project_id).order_by(OntologyRevision.revision.desc()).first()
    return (latest.revision if latest else 0) + 1


def _revision_dict(row: OntologyRevision, include_manifest: bool = True) -> Dict[str, Any]:
    result = {
        "id": row.id,
        "project_id": row.project_id,
        "revision": row.revision,
        "status": row.status,
        "parent_revision_id": row.parent_revision_id,
        "branch_id": row.branch_id,
        "checksum": row.checksum,
        "validation": row.validation or {},
        "created_by": row.created_by,
        "created_at": row.created_at,
        "published_at": row.published_at,
    }
    if include_manifest:
        result["manifest"] = row.manifest or {}
    return result


def _change_set_dict(db: Session, row: OntologyChangeSet) -> Dict[str, Any]:
    draft = db.get(OntologyRevision, row.draft_revision_id)
    return {
        "id": row.id,
        "project_id": row.project_id,
        "title": row.title,
        "description": row.description,
        "base_revision_id": row.base_revision_id,
        "draft_revision_id": row.draft_revision_id,
        "proposal_id": row.proposal_id,
        "status": row.status,
        "changes": row.changes or [],
        "diff": row.diff or {},
        "impact": row.impact or {},
        "validation": row.validation or {},
        "migration_plan": row.migration_plan or {},
        "checksum": draft.checksum if draft else None,
        "created_by": row.created_by,
        "reviewer": row.reviewer,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


def _capture_manifest(db: Session, project_id: str, object_type_ids: Optional[List[str]] = None) -> Dict[str, Any]:
    selected = set(object_type_ids or [])
    object_query = db.query(models.ObjectType).filter(models.ObjectType.project_id == project_id)
    if selected:
        object_query = object_query.filter(models.ObjectType.id.in_(selected))
    object_rows = object_query.order_by(models.ObjectType.id).all()
    object_ids = {row.id for row in object_rows}
    object_types: List[Dict[str, Any]] = []
    for row in object_rows:
        raw_properties = row.properties or {}
        manager = _copy_json(raw_properties.get("__manager") or {})
        properties = {name: _copy_json(spec) for name, spec in raw_properties.items() if not name.startswith("__")}
        profile = db.get(ontology_core.ObjectTypeProfile, row.id)
        if profile:
            profile_properties = profile.properties or {}
            properties = {
                name: {**(spec if isinstance(spec, dict) else {}), **(profile_properties.get(name) or {})}
                for name, spec in properties.items()
            }
        profile_manifest = None if not profile else {
            "api_name": profile.api_name,
            "primary_key": profile.primary_key,
            "title_key": profile.title_key,
            "icon": profile.icon,
            "color": profile.color,
            "plural_name": profile.plural_name,
            "groups": profile.groups or [],
            "properties": profile.properties or {},
        }
        object_types.append({
            "id": row.id,
            "display_name": row.display_name,
            "description": row.description,
            "status": manager.get("status", "ACTIVE"),
            "primary_key": profile.primary_key if profile else manager.get("primary_key"),
            "title_key": profile.title_key if profile else manager.get("title_key"),
            "properties": properties,
            "manager": manager,
            "profile": profile_manifest,
        })
    links = db.query(models.LinkType).filter(
        models.LinkType.project_id == project_id,
        models.LinkType.source_object_type_id.in_(object_ids),
        models.LinkType.target_object_type_id.in_(object_ids),
    ).order_by(models.LinkType.id).all() if object_ids else []
    actions = db.query(models.ActionType).filter(models.ActionType.project_id == project_id).order_by(models.ActionType.id).all()
    return {
        "schema_version": 1,
        "project_id": project_id,
        "object_types": object_types,
        "link_types": [{
            "id": row.id,
            "display_name": row.display_name,
            "description": row.description,
            "source_object_type_id": row.source_object_type_id,
            "target_object_type_id": row.target_object_type_id,
            "cardinality": row.cardinality,
            "status": "ACTIVE",
        } for row in links],
        "action_types": [{
            "id": row.id,
            "display_name": row.display_name,
            "description": row.description,
            "parameters": _copy_json(row.parameters or {}),
            "rules": _copy_json(row.rules or {}),
            "status": str(((row.rules or {}).get("__manager") or {}).get("status") or "ACTIVE"),
        } for row in actions],
    }


def _resource_map(manifest: Dict[str, Any], key: str) -> Dict[str, Dict[str, Any]]:
    return {str(item.get("id")): item for item in (manifest.get(key) or []) if isinstance(item, dict) and item.get("id")}


def _validate_manifest(manifest: Dict[str, Any]) -> Dict[str, Any]:
    issues: List[Dict[str, str]] = []
    if manifest.get("schema_version") != 1:
        issues.append({"severity": "ERROR", "path": "schema_version", "code": "SCHEMA_VERSION", "message": "schema_version must be 1"})
    object_types = manifest.get("object_types") or []
    links = manifest.get("link_types") or []
    actions = manifest.get("action_types") or []
    if not all(isinstance(items, list) for items in (object_types, links, actions)):
        issues.append({"severity": "ERROR", "path": "resources", "code": "RESOURCE_SHAPE", "message": "Ontology resources must be arrays"})
        object_types, links, actions = [], [], []
    object_ids = [str(item.get("id", "")) for item in object_types if isinstance(item, dict)]
    if len(object_ids) != len(set(object_ids)):
        issues.append({"severity": "ERROR", "path": "object_types", "code": "DUPLICATE_ID", "message": "Object type IDs must be unique"})
    for index, item in enumerate(object_types):
        path = f"object_types[{index}]"
        if not isinstance(item, dict) or not RESOURCE_ID.match(str(item.get("id", ""))):
            issues.append({"severity": "ERROR", "path": f"{path}.id", "code": "INVALID_API_NAME", "message": "A valid object type resource ID is required"})
            continue
        properties = item.get("properties") or {}
        if not isinstance(properties, dict):
            issues.append({"severity": "ERROR", "path": f"{path}.properties", "code": "PROPERTY_SHAPE", "message": "Properties must be an object"})
            continue
        primary_key = item.get("primary_key")
        if primary_key and primary_key not in properties:
            issues.append({"severity": "ERROR", "path": f"{path}.primary_key", "code": "PRIMARY_KEY_MISSING", "message": "Primary key must reference a declared property"})
        for name, spec in properties.items():
            property_path = f"{path}.properties.{name}"
            if not API_NAME.match(str(name)):
                issues.append({"severity": "ERROR", "path": property_path, "code": "INVALID_PROPERTY_NAME", "message": "A valid property API name is required"})
                continue
            if not isinstance(spec, dict):
                issues.append({"severity": "ERROR", "path": property_path, "code": "PROPERTY_SPEC", "message": "Property configuration must be an object"})
                continue
            base_type = str(spec.get("base_type") or spec.get("type") or "string").lower()
            if base_type not in SUPPORTED_PROPERTY_TYPES:
                issues.append({"severity": "ERROR", "path": f"{property_path}.base_type", "code": "UNSUPPORTED_TYPE", "message": f"Unsupported property type '{base_type}'"})
    for index, item in enumerate(links):
        path = f"link_types[{index}]"
        if not isinstance(item, dict) or not RESOURCE_ID.match(str(item.get("id", ""))):
            issues.append({"severity": "ERROR", "path": f"{path}.id", "code": "INVALID_API_NAME", "message": "A valid link type resource ID is required"})
            continue
        if item.get("source_object_type_id") not in object_ids or item.get("target_object_type_id") not in object_ids:
            issues.append({"severity": "ERROR", "path": path, "code": "INVALID_LINK_ENDPOINT", "message": "Link endpoints must reference object types in the revision"})
        if item.get("cardinality", "MANY_TO_MANY") not in {"ONE_TO_ONE", "ONE_TO_MANY", "MANY_TO_ONE", "MANY_TO_MANY"}:
            issues.append({"severity": "ERROR", "path": f"{path}.cardinality", "code": "INVALID_CARDINALITY", "message": "Unsupported link cardinality"})
    for index, item in enumerate(actions):
        if not isinstance(item, dict) or not RESOURCE_ID.match(str(item.get("id", ""))):
            issues.append({"severity": "ERROR", "path": f"action_types[{index}].id", "code": "INVALID_API_NAME", "message": "A valid action type resource ID is required"})
    errors = sum(issue["severity"] == "ERROR" for issue in issues)
    warnings = sum(issue["severity"] == "WARN" for issue in issues)
    return {
        "status": "PASS" if errors == 0 else "FAIL",
        "summary": {"object_types": len(object_types), "link_types": len(links), "action_types": len(actions), "errors": errors, "warnings": warnings},
        "issues": issues,
        "validated_at": _now(),
    }


def _ontology_diff(before: Dict[str, Any], after: Dict[str, Any]) -> Dict[str, Any]:
    entries: List[Dict[str, Any]] = []
    for resource_key, resource_type in (("object_types", "object_type"), ("link_types", "link_type"), ("action_types", "action_type")):
        left = _resource_map(before, resource_key)
        right = _resource_map(after, resource_key)
        for resource_id in sorted(right.keys() - left.keys()):
            entries.append({"kind": "ADDED", "resource_type": resource_type, "resource_id": resource_id, "breaking": False})
        for resource_id in sorted(left.keys() - right.keys()):
            entries.append({"kind": "REMOVED", "resource_type": resource_type, "resource_id": resource_id, "breaking": True})
        for resource_id in sorted(left.keys() & right.keys()):
            if resource_type != "object_type":
                if left[resource_id] != right[resource_id]:
                    breaking = resource_type == "link_type" and left[resource_id].get("cardinality") != right[resource_id].get("cardinality")
                    entries.append({"kind": "CHANGED", "resource_type": resource_type, "resource_id": resource_id, "breaking": breaking, "before": left[resource_id], "after": right[resource_id]})
                continue
            old, new = left[resource_id], right[resource_id]
            old_properties = old.get("properties") or {}
            new_properties = new.get("properties") or {}
            for name in sorted(new_properties.keys() - old_properties.keys()):
                entries.append({"kind": "PROPERTY_ADDED", "resource_type": resource_type, "resource_id": resource_id, "property_name": name, "breaking": bool((new_properties[name] or {}).get("required"))})
            for name in sorted(old_properties.keys() - new_properties.keys()):
                entries.append({"kind": "PROPERTY_ARCHIVED", "resource_type": resource_type, "resource_id": resource_id, "property_name": name, "breaking": True})
            for name in sorted(old_properties.keys() & new_properties.keys()):
                old_spec, new_spec = old_properties[name], new_properties[name]
                if old_spec != new_spec:
                    old_type = str((old_spec or {}).get("base_type") or (old_spec or {}).get("type") or "string")
                    new_type = str((new_spec or {}).get("base_type") or (new_spec or {}).get("type") or "string")
                    breaking = old_type != new_type or (not bool((old_spec or {}).get("required")) and bool((new_spec or {}).get("required")))
                    entries.append({"kind": "PROPERTY_CHANGED", "resource_type": resource_type, "resource_id": resource_id, "property_name": name, "breaking": breaking, "before": old_spec, "after": new_spec})
            metadata_before = {key: old.get(key) for key in ("display_name", "description", "primary_key", "title_key", "status")}
            metadata_after = {key: new.get(key) for key in ("display_name", "description", "primary_key", "title_key", "status")}
            if metadata_before != metadata_after:
                entries.append({"kind": "METADATA_CHANGED", "resource_type": resource_type, "resource_id": resource_id, "breaking": metadata_before["primary_key"] != metadata_after["primary_key"], "before": metadata_before, "after": metadata_after})
    breaking = sum(bool(item.get("breaking")) for item in entries)
    return {
        "classification": "BREAKING" if breaking else ("NON_BREAKING" if entries else "NO_CHANGE"),
        "summary": {"changes": len(entries), "breaking": breaking, "non_breaking": len(entries) - breaking},
        "entries": entries,
    }


def _apply_changes(manifest: Dict[str, Any], changes: List[Dict[str, Any]]) -> Dict[str, Any]:
    result = _copy_json(manifest)
    for change in changes:
        operation = str(change.get("operation") or "").lower()
        resource_type = str(change.get("resource_type") or "object_type")
        collection_key = {"object_type": "object_types", "link_type": "link_types", "action_type": "action_types"}.get(resource_type)
        if operation in {"add_object_type", "add_link_type", "add_action_type"}:
            collection_key = operation.removeprefix("add_") + "s"
            resource = _copy_json(change.get("resource") or {})
            if not resource.get("id"):
                raise HTTPException(status_code=422, detail=f"{operation} requires resource.id")
            if resource["id"] in _resource_map(result, collection_key):
                raise HTTPException(status_code=409, detail=f"Resource '{resource['id']}' already exists")
            result.setdefault(collection_key, []).append(resource)
            continue
        if operation in {"update_object_type", "update_link_type", "update_action_type", "archive_object_type", "archive_link_type", "archive_action_type"}:
            collection_key = operation.split("_", 1)[1] + "s"
            resource_id = str(change.get("resource_id") or change.get("object_type_id") or "")
            resource = _resource_map(result, collection_key).get(resource_id)
            if not resource:
                raise HTTPException(status_code=404, detail=f"Resource '{resource_id}' is not present in the base revision")
            if operation.startswith("archive_"):
                resource["status"] = "ARCHIVED"
            else:
                resource.update(_copy_json(change.get("patch") or {}))
            continue
        object_type_id = str(change.get("object_type_id") or change.get("resource_id") or "")
        object_type = _resource_map(result, "object_types").get(object_type_id)
        if not object_type:
            raise HTTPException(status_code=404, detail=f"Object type '{object_type_id}' is not present in the base revision")
        properties = object_type.setdefault("properties", {})
        property_name = str(change.get("property_name") or "")
        if operation == "add_property":
            if not property_name or property_name in properties:
                raise HTTPException(status_code=409, detail=f"Property '{property_name}' already exists or is invalid")
            properties[property_name] = _copy_json(change.get("spec") or {})
        elif operation == "update_property":
            if property_name not in properties:
                raise HTTPException(status_code=404, detail=f"Property '{property_name}' not found")
            properties[property_name] = {**properties[property_name], **_copy_json(change.get("patch") or {})}
        elif operation == "archive_property":
            if property_name not in properties:
                raise HTTPException(status_code=404, detail=f"Property '{property_name}' not found")
            archived = object_type.setdefault("archived_properties", {})
            archived[property_name] = properties.pop(property_name)
        elif operation == "rename_property":
            new_name = str(change.get("new_name") or "")
            if property_name not in properties or not new_name or new_name in properties:
                raise HTTPException(status_code=422, detail="rename_property requires an existing property and an unused new_name")
            properties[new_name] = properties.pop(property_name)
            if object_type.get("primary_key") == property_name:
                object_type["primary_key"] = new_name
            if object_type.get("title_key") == property_name:
                object_type["title_key"] = new_name
        else:
            raise HTTPException(status_code=422, detail=f"Unsupported ontology change operation '{operation}'")
    for key in ("object_types", "link_types", "action_types"):
        result[key] = sorted(result.get(key) or [], key=lambda item: str(item.get("id", "")))
    return result


def _impact_and_migration(db: Session, project_id: str, diff: Dict[str, Any]) -> tuple[Dict[str, Any], Dict[str, Any]]:
    affected_types = sorted({item["resource_id"] for item in diff.get("entries", []) if item.get("resource_type") == "object_type"})
    object_counts = {
        object_type_id: db.query(models.ObjectInstance).filter(
            models.ObjectInstance.project_id == project_id,
            models.ObjectInstance.object_type_id == object_type_id,
        ).count()
        for object_type_id in affected_types
    }
    steps: List[Dict[str, Any]] = []
    for index, item in enumerate(diff.get("entries", []), start=1):
        strategy = "metadata_update"
        preserves_values = True
        requires_backfill = False
        if item["kind"] == "PROPERTY_ADDED":
            strategy = "add_nullable_field" if not item.get("breaking") else "backfill_required_field"
            requires_backfill = bool(item.get("breaking"))
        elif item["kind"] == "PROPERTY_ARCHIVED":
            strategy = "archive_schema_preserve_values"
        elif item["kind"] == "PROPERTY_CHANGED" and item.get("breaking"):
            strategy = "validate_and_backfill_type_change"
            requires_backfill = True
        elif item["kind"] in {"REMOVED", "METADATA_CHANGED"} and item.get("breaking"):
            strategy = "manual_review"
            requires_backfill = True
        steps.append({"order": index, "strategy": strategy, "resource_type": item["resource_type"], "resource_id": item["resource_id"], "property_name": item.get("property_name"), "requires_backfill": requires_backfill, "preserves_existing_values": preserves_values})
    blocking = [step for step in steps if step["requires_backfill"]]
    from . import ontology_runtime_v1
    change_entries: Dict[str, List[Dict[str, Any]]] = {}
    for item in diff.get("entries", []):
        if item.get("resource_type") == "object_type":
            change_entries.setdefault(str(item.get("resource_id")), []).append(item)
    binding_rows = db.query(ontology_runtime_v1.OntologyResourceDefinition).filter(
        ontology_runtime_v1.OntologyResourceDefinition.project_id == project_id,
        ontology_runtime_v1.OntologyResourceDefinition.resource_kind == "contract_binding",
        ontology_runtime_v1.OntologyResourceDefinition.status == "ACTIVE",
        ontology_runtime_v1.OntologyResourceDefinition.object_type_id.in_(affected_types),
    ).all() if affected_types else []
    affected_consumers: List[Dict[str, Any]] = []
    for binding in binding_rows:
        definition = binding.definition or {}
        entries = change_entries.get(str(binding.object_type_id), [])
        changed_properties = {str(item.get("property_name")) for item in entries if item.get("property_name")}
        whole_contract_change = any(item.get("kind") in {"REMOVED", "METADATA_CHANGED"} for item in entries)
        referenced_properties = set(definition.get("properties") or [])
        if changed_properties and referenced_properties and not whole_contract_change and changed_properties.isdisjoint(referenced_properties):
            continue
        relevant_entries = [
            item for item in entries
            if whole_contract_change or not item.get("property_name") or not referenced_properties or item.get("property_name") in referenced_properties
        ]
        affected_consumers.append({
            "binding_id": binding.id,
            "consumer_kind": definition.get("consumer_kind"),
            "consumer_id": definition.get("consumer_id"),
            "consumer_version": definition.get("consumer_version"),
            "object_type_id": binding.object_type_id,
            "referenced_properties": sorted(referenced_properties),
            "changed_properties": sorted(changed_properties),
            "bound_revision_id": binding.ontology_revision_id,
            "breaking": any(bool(item.get("breaking")) for item in relevant_entries),
        })
    impact = {
        "severity": "HIGH" if diff.get("summary", {}).get("breaking") else ("LOW" if diff.get("summary", {}).get("changes") else "NONE"),
        "affected_object_types": affected_types,
        "live_object_counts": object_counts,
        "live_objects": sum(object_counts.values()),
        "affected_consumer_count": len(affected_consumers),
        "affected_consumers": affected_consumers,
        "breaking_consumer_count": sum(bool(item["breaking"]) for item in affected_consumers),
        "requires_approval": bool(diff.get("summary", {}).get("breaking")),
    }
    migration = {"status": "REVIEW_REQUIRED" if blocking else "READY", "steps": steps, "blocking_steps": len(blocking), "preserves_existing_values": True}
    return impact, migration


def _apply_manifest(db: Session, project_id: str, manifest: Dict[str, Any]) -> Dict[str, Any]:
    applied = {"object_types": 0, "link_types": 0, "action_types": 0, "archived": 0}
    now = _now()
    for item in manifest.get("object_types") or []:
        row = db.get(models.ObjectType, item["id"])
        if row and row.project_id != project_id:
            raise HTTPException(status_code=409, detail=f"Object type '{row.id}' belongs to another project")
        manager = _copy_json(item.get("manager") or {})
        manager.update({"project_id": project_id, "status": item.get("status", "ACTIVE"), "primary_key": item.get("primary_key"), "title_key": item.get("title_key")})
        properties = {**_copy_json(item.get("properties") or {}), "__manager": manager}
        if item.get("archived_properties"):
            properties["__manager"]["archived_properties"] = _copy_json(item["archived_properties"])
        if not row:
            row = models.ObjectType(id=item["id"], project_id=project_id, display_name=item.get("display_name") or item["id"], description=item.get("description"), properties=properties, created_at=now, updated_at=now)
            db.add(row)
        else:
            row.display_name = item.get("display_name") or item["id"]
            row.description = item.get("description")
            row.properties = properties
            row.updated_at = now
        profile_data = item.get("profile") or {}
        profile = db.get(ontology_core.ObjectTypeProfile, item["id"])
        if profile:
            profile.api_name = profile_data.get("api_name") or profile.api_name
            profile.primary_key = item.get("primary_key")
            profile.title_key = item.get("title_key")
            profile.icon = profile_data.get("icon")
            profile.color = profile_data.get("color")
            profile.plural_name = profile_data.get("plural_name")
            profile.groups = profile_data.get("groups") or []
            profile.properties = _copy_json(item.get("properties") or {})
            profile.updated_at = now
        elif item.get("primary_key"):
            db.add(ontology_core.ObjectTypeProfile(object_type_id=item["id"], api_name=profile_data.get("api_name") or item["id"], primary_key=item.get("primary_key"), title_key=item.get("title_key"), icon=profile_data.get("icon"), color=profile_data.get("color"), plural_name=profile_data.get("plural_name"), groups=profile_data.get("groups") or [], properties=_copy_json(item.get("properties") or {}), created_at=now, updated_at=now))
        applied["object_types"] += 1
        if item.get("status") == "ARCHIVED":
            applied["archived"] += 1
    for item in manifest.get("link_types") or []:
        row = db.get(models.LinkType, item["id"])
        if item.get("status") == "ARCHIVED":
            if row and not db.query(models.LinkInstance).filter(models.LinkInstance.link_type_id == row.id).first():
                db.delete(row)
            applied["archived"] += 1
            continue
        if row and row.project_id != project_id:
            raise HTTPException(status_code=409, detail=f"Link type '{row.id}' belongs to another project")
        if not row:
            row = models.LinkType(id=item["id"], project_id=project_id, display_name=item.get("display_name") or item["id"], description=item.get("description"), source_object_type_id=item["source_object_type_id"], target_object_type_id=item["target_object_type_id"], cardinality=item.get("cardinality", "MANY_TO_MANY"))
            db.add(row)
        else:
            row.display_name = item.get("display_name") or item["id"]
            row.description = item.get("description")
            row.source_object_type_id = item["source_object_type_id"]
            row.target_object_type_id = item["target_object_type_id"]
            row.cardinality = item.get("cardinality", "MANY_TO_MANY")
        applied["link_types"] += 1
    for item in manifest.get("action_types") or []:
        row = db.get(models.ActionType, item["id"])
        if row and row.project_id != project_id:
            raise HTTPException(status_code=409, detail=f"Action type '{row.id}' belongs to another project")
        rules = _copy_json(item.get("rules") or {})
        if item.get("status") == "ARCHIVED":
            rules["__manager"] = {**(rules.get("__manager") or {}), "status": "ARCHIVED"}
            applied["archived"] += 1
        if not row:
            row = models.ActionType(id=item["id"], project_id=project_id, display_name=item.get("display_name") or item["id"], description=item.get("description"), parameters=_copy_json(item.get("parameters") or {}), rules=rules)
            db.add(row)
        else:
            row.display_name = item.get("display_name") or item["id"]
            row.description = item.get("description")
            row.parameters = _copy_json(item.get("parameters") or {})
            row.rules = rules
        applied["action_types"] += 1
    db.flush()
    return applied


# ---- Branch endpoints ----

@router.post("/ontology/branches", response_model=BranchRead)
def create_branch(body: BranchCreate, principal: Principal = Depends(require_permission("edit")), db: Session = Depends(get_db)):
    tenancy.assert_project_permission(db, principal, body.project_id, "edit")
    branch_id = body.id or uuid.uuid4().hex
    existing = db.query(OntologyBranch).filter(OntologyBranch.id == branch_id).first()
    if existing:
        raise HTTPException(status_code=400, detail="OntologyBranch already exists")
    branch = OntologyBranch(
        id=branch_id,
        project_id=body.project_id,
        display_name=body.display_name,
        base_branch=body.base_branch,
        status="open",
        created_at=int(time.time()),
    )
    db.add(branch)
    db.commit()
    db.refresh(branch)
    return branch


@router.get("/ontology/branches", response_model=List[BranchRead])
def list_branches(project_id: Optional[str] = None, principal: Principal = Depends(require_permission("view")), db: Session = Depends(get_db)):
    query = semantic_scope.accessible_query(db, principal, OntologyBranch)
    if project_id:
        tenancy.assert_project_permission(db, principal, project_id, "view")
        query = query.filter(OntologyBranch.project_id == project_id)
    return query.order_by(OntologyBranch.created_at.desc()).all()


# ---- Proposal endpoints ----

@router.post("/ontology/proposals", response_model=ProposalRead)
def create_proposal(body: ProposalCreate, principal: Principal = Depends(require_permission("edit")), db: Session = Depends(get_db)):
    branch = db.query(OntologyBranch).filter(OntologyBranch.id == body.branch_id).first()
    if not branch:
        _branch_not_found(body.branch_id)
    tenancy.assert_project_permission(db, principal, branch.project_id, "edit")
    if branch.status == "merged":
        raise HTTPException(status_code=400, detail="Cannot create proposal on a merged branch")

    proposal_id = body.id or uuid.uuid4().hex
    existing = db.query(OntologyProposal).filter(OntologyProposal.id == proposal_id).first()
    if existing:
        raise HTTPException(status_code=400, detail="OntologyProposal already exists")

    proposal = OntologyProposal(
        id=proposal_id,
        project_id=branch.project_id,
        branch_id=body.branch_id,
        title=body.title,
        description=body.description,
        changes=body.changes,
        status="draft",
        created_at=int(time.time()),
    )
    db.add(proposal)
    db.commit()
    db.refresh(proposal)
    return proposal


@router.get("/ontology/proposals", response_model=List[ProposalRead])
def list_proposals(branch_id: Optional[str] = None, project_id: Optional[str] = None, principal: Principal = Depends(require_permission("view")), db: Session = Depends(get_db)):
    query = semantic_scope.accessible_query(db, principal, OntologyProposal)
    if branch_id:
        query = query.filter(OntologyProposal.branch_id == branch_id)
    if project_id:
        tenancy.assert_project_permission(db, principal, project_id, "view")
        query = query.filter(OntologyProposal.project_id == project_id)
    return query.order_by(OntologyProposal.created_at.desc()).all()


@router.get("/ontology/proposals/{proposal_id}", response_model=ProposalRead)
def get_proposal(proposal_id: str, principal: Principal = Depends(require_permission("view")), db: Session = Depends(get_db)):
    proposal = db.query(OntologyProposal).filter(OntologyProposal.id == proposal_id).first()
    if not proposal:
        _proposal_not_found(proposal_id)
    tenancy.assert_project_permission(db, principal, proposal.project_id, "view")
    return proposal


@router.post("/ontology/proposals/{proposal_id}/submit", response_model=ProposalRead)
def submit_proposal(proposal_id: str, principal: Principal = Depends(require_permission("edit")), db: Session = Depends(get_db)):
    proposal = db.query(OntologyProposal).filter(OntologyProposal.id == proposal_id).first()
    if not proposal:
        _proposal_not_found(proposal_id)
    tenancy.assert_project_permission(db, principal, proposal.project_id, "edit")
    if proposal.status != "draft":
        raise HTTPException(
            status_code=400,
            detail=f"Proposal must be in 'draft' status to submit (current: {proposal.status})",
        )
    proposal.status = "submitted"
    db.commit()
    db.refresh(proposal)
    return proposal


@router.post("/ontology/proposals/{proposal_id}/decision", response_model=ProposalRead)
def decide_proposal(proposal_id: str, body: DecisionBody, principal: Principal = Depends(require_permission("approve")), db: Session = Depends(get_db)):
    proposal = db.query(OntologyProposal).filter(OntologyProposal.id == proposal_id).first()
    if not proposal:
        _proposal_not_found(proposal_id)
    tenancy.assert_project_permission(db, principal, proposal.project_id, "approve")
    if proposal.status != "submitted":
        raise HTTPException(
            status_code=400,
            detail=f"Proposal must be in 'submitted' status for a decision (current: {proposal.status})",
        )

    new_status = "approved" if body.approve else "rejected"
    proposal.status = new_status
    proposal.reviewer = body.reviewer
    proposal.decided_at = int(time.time())

    _append_audit(
        db,
        actor=body.reviewer,
        event_type="ontology.proposal.decided",
        subject_type="ontology_proposal",
        subject_id=proposal_id,
        payload={
            "decision": new_status,
            "reviewer": body.reviewer,
            "branch_id": proposal.branch_id,
            "title": proposal.title,
        },
    )
    db.commit()
    db.refresh(proposal)
    return proposal


@router.post("/ontology/proposals/{proposal_id}/merge", response_model=ProposalRead)
def merge_proposal(proposal_id: str, principal: Principal = Depends(require_permission("publish")), db: Session = Depends(get_db)):
    proposal = db.query(OntologyProposal).filter(OntologyProposal.id == proposal_id).first()
    if not proposal:
        _proposal_not_found(proposal_id)
    tenancy.assert_project_permission(db, principal, proposal.project_id, "publish")
    if proposal.status != "approved":
        raise HTTPException(
            status_code=400,
            detail=f"Proposal must be 'approved' before merging (current: {proposal.status})",
        )

    branch = db.query(OntologyBranch).filter(OntologyBranch.id == proposal.branch_id).first()
    if not branch:
        _branch_not_found(proposal.branch_id)

    proposal.status = "merged"
    branch.status = "merged"

    _append_audit(
        db,
        actor=proposal.reviewer or "system",
        event_type="ontology.proposal.merged",
        subject_type="ontology_proposal",
        subject_id=proposal_id,
        payload={
            "branch_id": proposal.branch_id,
            "title": proposal.title,
            "change_count": len(proposal.changes or []),
            "reviewer": proposal.reviewer,
        },
    )
    db.commit()
    db.refresh(proposal)
    return proposal


# ---- Immutable revision and release lifecycle ----

def _revision(db: Session, revision_id: str) -> OntologyRevision:
    row = db.get(OntologyRevision, revision_id)
    if not row:
        raise HTTPException(status_code=404, detail=f"Ontology revision '{revision_id}' not found")
    return row


def _change_set(db: Session, change_set_id: str) -> OntologyChangeSet:
    row = db.get(OntologyChangeSet, change_set_id)
    if not row:
        raise HTTPException(status_code=404, detail=f"Ontology change set '{change_set_id}' not found")
    return row


def _environment(db: Session, project_id: str, name: str, actor: str) -> OntologyEnvironment:
    row = db.query(OntologyEnvironment).filter(OntologyEnvironment.project_id == project_id, OntologyEnvironment.name == name).first()
    if row:
        return row
    row = OntologyEnvironment(id=f"ontology_env_{uuid.uuid4().hex}", project_id=project_id, name=name, current_revision_id=None, previous_revision_id=None, updated_by=actor, updated_at=_now())
    db.add(row)
    db.flush()
    return row


def _new_revision(db: Session, project_id: str, manifest: Dict[str, Any], actor: str, status: str = "DRAFT", parent_revision_id: Optional[str] = None, branch_id: Optional[str] = None) -> OntologyRevision:
    validation = _validate_manifest(manifest)
    row = OntologyRevision(
        id=f"ontology_revision_{uuid.uuid4().hex}",
        project_id=project_id,
        revision=_next_revision_number(db, project_id),
        status=status,
        parent_revision_id=parent_revision_id,
        branch_id=branch_id,
        manifest=_copy_json(manifest),
        checksum=_checksum(manifest),
        validation=validation,
        created_by=actor,
        created_at=_now(),
        published_at=_now() if status == "PUBLISHED" else None,
    )
    db.add(row)
    db.flush()
    return row


@router.post("/ontology/revisions/capture", status_code=201)
def capture_ontology_revision(body: RevisionCaptureRequest, principal: Principal = Depends(require_permission("edit")), db: Session = Depends(get_db)):
    tenancy.assert_project_permission(db, principal, body.project_id, "edit")
    if body.branch_id:
        branch = semantic_scope.owned_row(db, principal, OntologyBranch, body.branch_id, "edit", "OntologyBranch")
        if branch.project_id != body.project_id:
            raise HTTPException(status_code=409, detail="Branch and ontology revision must belong to the same project")
    manifest = _capture_manifest(db, body.project_id, body.object_type_ids)
    environment = db.query(OntologyEnvironment).filter(OntologyEnvironment.project_id == body.project_id, OntologyEnvironment.name == "production").first()
    row = _new_revision(db, body.project_id, manifest, principal.id, parent_revision_id=environment.current_revision_id if environment else None, branch_id=body.branch_id)
    _append_audit(db, principal.id, "ontology.revision.captured", "ontology_revision", row.id, {"project_id": body.project_id, "revision": row.revision, "checksum": row.checksum})
    db.commit()
    return _revision_dict(row)


@router.get("/ontology/revisions")
def list_ontology_revisions(project_id: Optional[str] = None, principal: Principal = Depends(require_permission("view")), db: Session = Depends(get_db)):
    query = semantic_scope.accessible_query(db, principal, OntologyRevision)
    if project_id:
        tenancy.assert_project_permission(db, principal, project_id, "view")
        query = query.filter(OntologyRevision.project_id == project_id)
    return [_revision_dict(row, False) for row in query.order_by(OntologyRevision.created_at.desc(), OntologyRevision.revision.desc()).all()]


@router.get("/ontology/revisions/{revision_id}")
def get_ontology_revision(revision_id: str, principal: Principal = Depends(require_permission("view")), db: Session = Depends(get_db)):
    row = semantic_scope.owned_row(db, principal, OntologyRevision, revision_id, "view", "OntologyRevision")
    return _revision_dict(row)


@router.get("/ontology/revisions/{revision_id}/diff")
def diff_ontology_revision(revision_id: str, against: Optional[str] = None, principal: Principal = Depends(require_permission("view")), db: Session = Depends(get_db)):
    row = semantic_scope.owned_row(db, principal, OntologyRevision, revision_id, "view", "OntologyRevision")
    comparison_id = against or row.parent_revision_id
    if comparison_id:
        comparison = semantic_scope.owned_row(db, principal, OntologyRevision, comparison_id, "view", "OntologyRevision")
        if comparison.project_id != row.project_id:
            raise HTTPException(status_code=409, detail="Ontology revisions must belong to the same project")
        before = comparison.manifest or {}
    else:
        before = {"schema_version": 1, "project_id": row.project_id, "object_types": [], "link_types": [], "action_types": []}
    return {"revision_id": row.id, "against_revision_id": comparison_id, **_ontology_diff(before, row.manifest or {})}


@router.post("/api/v1/ontology/change-sets", status_code=201)
@router.post("/ontology/change-sets", status_code=201)
def create_ontology_change_set(body: ChangeSetCreate, principal: Principal = Depends(require_permission("edit")), db: Session = Depends(get_db)):
    tenancy.assert_project_permission(db, principal, body.project_id, "edit")
    branch = None
    if body.branch_id:
        branch = semantic_scope.owned_row(db, principal, OntologyBranch, body.branch_id, "edit", "OntologyBranch")
        if branch.project_id != body.project_id:
            raise HTTPException(status_code=409, detail="Branch and change set must belong to the same project")
    proposal = None
    if body.proposal_id:
        proposal = semantic_scope.owned_row(db, principal, OntologyProposal, body.proposal_id, "edit", "OntologyProposal")
        if proposal.project_id != body.project_id:
            raise HTTPException(status_code=409, detail="Proposal and change set must belong to the same project")
    if body.base_revision_id:
        base = semantic_scope.owned_row(db, principal, OntologyRevision, body.base_revision_id, "view", "OntologyRevision")
        if base.project_id != body.project_id:
            raise HTTPException(status_code=409, detail="Base revision and change set must belong to the same project")
    else:
        environment = db.query(OntologyEnvironment).filter(OntologyEnvironment.project_id == body.project_id, OntologyEnvironment.name == "production").first()
        base = db.get(OntologyRevision, environment.current_revision_id) if environment and environment.current_revision_id else None
        if not base:
            base = _new_revision(db, body.project_id, _capture_manifest(db, body.project_id), principal.id, status="BASELINE", branch_id=body.branch_id)
    # Generator and structured manager edits already exist in the working
    # ontology. Capture them explicitly so review compares working state with
    # the published base instead of silently cloning an older revision.
    working_manifest = _capture_manifest(db, body.project_id) if body.capture_current else (base.manifest or {})
    manifest = _apply_changes(working_manifest, body.changes)
    draft = _new_revision(db, body.project_id, manifest, principal.id, parent_revision_id=base.id, branch_id=body.branch_id)
    diff = _ontology_diff(base.manifest or {}, manifest)
    impact, migration = _impact_and_migration(db, body.project_id, diff)
    now = _now()
    row = OntologyChangeSet(
        id=f"ontology_change_{uuid.uuid4().hex}",
        project_id=body.project_id,
        title=body.title,
        description=body.description,
        base_revision_id=base.id,
        draft_revision_id=draft.id,
        proposal_id=proposal.id if proposal else None,
        status="DRAFT",
        changes=_copy_json(body.changes),
        diff=diff,
        impact=impact,
        validation=draft.validation,
        migration_plan=migration,
        created_by=principal.id,
        reviewer=None,
        created_at=now,
        updated_at=now,
    )
    db.add(row)
    _append_audit(db, principal.id, "ontology.change_set.created", "ontology_change_set", row.id, {
        "project_id": body.project_id,
        "draft_revision_id": draft.id,
        "classification": diff["classification"],
        "capture_current": body.capture_current,
    })
    db.commit()
    return _change_set_dict(db, row)


@router.get("/api/v1/ontology/change-sets")
@router.get("/ontology/change-sets")
def list_ontology_change_sets(project_id: Optional[str] = None, status: Optional[str] = None, principal: Principal = Depends(require_permission("view")), db: Session = Depends(get_db)):
    query = semantic_scope.accessible_query(db, principal, OntologyChangeSet)
    if project_id:
        tenancy.assert_project_permission(db, principal, project_id, "view")
        query = query.filter(OntologyChangeSet.project_id == project_id)
    if status:
        query = query.filter(OntologyChangeSet.status == status.upper())
    return [_change_set_dict(db, row) for row in query.order_by(OntologyChangeSet.updated_at.desc()).all()]


@router.get("/api/v1/ontology/change-sets/{change_set_id}")
@router.get("/ontology/change-sets/{change_set_id}")
def get_ontology_change_set(change_set_id: str, principal: Principal = Depends(require_permission("view")), db: Session = Depends(get_db)):
    row = semantic_scope.owned_row(db, principal, OntologyChangeSet, change_set_id, "view", "OntologyChangeSet")
    return _change_set_dict(db, row)


@router.post("/api/v1/ontology/change-sets/{change_set_id}/validate")
@router.post("/ontology/change-sets/{change_set_id}/validate")
def validate_ontology_change_set(change_set_id: str, principal: Principal = Depends(require_permission("edit")), db: Session = Depends(get_db)):
    row = semantic_scope.owned_row(db, principal, OntologyChangeSet, change_set_id, "edit", "OntologyChangeSet")
    if row.status not in {"DRAFT", "VALIDATED"}:
        raise HTTPException(status_code=409, detail=f"Change set cannot be validated from status {row.status}")
    draft = _revision(db, row.draft_revision_id)
    validation = _validate_manifest(draft.manifest or {})
    base = _revision(db, row.base_revision_id) if row.base_revision_id else None
    diff = _ontology_diff(base.manifest or {}, draft.manifest or {}) if base else row.diff
    impact, migration = _impact_and_migration(db, row.project_id, diff)
    row.validation = validation
    row.diff = diff
    row.impact = impact
    row.migration_plan = migration
    row.status = "VALIDATED" if validation["status"] == "PASS" else "DRAFT"
    row.updated_at = _now()
    draft.validation = validation
    _append_audit(db, principal.id, "ontology.change_set.validated", "ontology_change_set", row.id, {"project_id": row.project_id, "status": validation["status"], "classification": diff["classification"]})
    db.commit()
    return _change_set_dict(db, row)


@router.post("/api/v1/ontology/change-sets/{change_set_id}/decision")
@router.post("/ontology/change-sets/{change_set_id}/decision")
def decide_ontology_change_set(change_set_id: str, body: ChangeSetDecision, principal: Principal = Depends(require_permission("approve")), db: Session = Depends(get_db)):
    row = semantic_scope.owned_row(db, principal, OntologyChangeSet, change_set_id, "approve", "OntologyChangeSet")
    if row.status != "VALIDATED":
        raise HTTPException(status_code=409, detail="Only a validated change set can be approved or rejected")
    row.status = "APPROVED" if body.approve else "REJECTED"
    row.reviewer = principal.id
    row.updated_at = _now()
    _append_audit(db, principal.id, "ontology.change_set.decided", "ontology_change_set", row.id, {"project_id": row.project_id, "decision": row.status})
    db.commit()
    return _change_set_dict(db, row)


@router.post("/api/v1/ontology/change-sets/{change_set_id}/publish")
@router.post("/ontology/change-sets/{change_set_id}/publish")
def publish_ontology_change_set(change_set_id: str, body: ChangeSetPublishRequest, principal: Principal = Depends(require_permission("publish")), db: Session = Depends(get_db)):
    row = semantic_scope.owned_row(db, principal, OntologyChangeSet, change_set_id, "publish", "OntologyChangeSet")
    if row.status != "APPROVED":
        raise HTTPException(status_code=409, detail="Change set must be approved before publication")
    draft = _revision(db, row.draft_revision_id)
    if body.expected_checksum and body.expected_checksum != draft.checksum:
        raise HTTPException(status_code=409, detail="Draft checksum changed")
    validation = _validate_manifest(draft.manifest or {})
    if validation["status"] != "PASS":
        raise HTTPException(status_code=422, detail={"message": "Ontology validation failed", "validation": validation})
    if row.diff.get("classification") == "BREAKING" and not body.allow_breaking:
        raise HTTPException(status_code=409, detail={"message": "Breaking ontology changes require explicit acknowledgement", "diff": row.diff, "migration_plan": row.migration_plan})
    current_impact, current_migration = _impact_and_migration(db, row.project_id, row.diff or {})
    required_binding_ids = {
        str(item["binding_id"])
        for item in current_impact.get("affected_consumers", [])
        if item.get("breaking") and item.get("binding_id")
    }
    acknowledged_binding_ids = {str(item) for item in body.acknowledged_consumer_binding_ids}
    if acknowledged_binding_ids != required_binding_ids:
        raise HTTPException(status_code=409, detail={
            "code": "DOWNSTREAM_CONSUMER_ACKNOWLEDGEMENT_REQUIRED",
            "message": "Downstream consumer impact changed or has not been acknowledged; validate and review the change set again",
            "required_consumer_binding_ids": sorted(required_binding_ids),
            "acknowledged_consumer_binding_ids": sorted(acknowledged_binding_ids),
            "missing_consumer_binding_ids": sorted(required_binding_ids - acknowledged_binding_ids),
            "stale_consumer_binding_ids": sorted(acknowledged_binding_ids - required_binding_ids),
            "impact": current_impact,
        })
    row.impact = current_impact
    row.migration_plan = current_migration
    applied = _apply_manifest(db, row.project_id, draft.manifest or {})
    environment = _environment(db, row.project_id, body.environment, principal.id)
    previous = db.get(OntologyRevision, environment.current_revision_id) if environment.current_revision_id else None
    if previous and previous.id != draft.id and previous.status == "PUBLISHED":
        previous.status = "SUPERSEDED"
    environment.previous_revision_id = environment.current_revision_id
    environment.current_revision_id = draft.id
    environment.updated_by = principal.id
    environment.updated_at = _now()
    draft.status = "PUBLISHED"
    draft.validation = validation
    draft.published_at = _now()
    row.status = "PUBLISHED"
    row.updated_at = _now()
    if row.proposal_id:
        proposal = db.get(OntologyProposal, row.proposal_id)
        if proposal and proposal.status == "approved":
            proposal.status = "merged"
            branch = db.get(OntologyBranch, proposal.branch_id)
            if branch:
                branch.status = "merged"
    _append_audit(db, principal.id, "ontology.change_set.published", "ontology_change_set", row.id, {"project_id": row.project_id, "environment": body.environment, "revision_id": draft.id, "checksum": draft.checksum, "applied": applied, "acknowledged_consumer_binding_ids": sorted(acknowledged_binding_ids)})
    from . import ontology_runtime_v1
    semantic_contract = ontology_runtime_v1.materialize_semantic_definitions(
        db, project_id=row.project_id, actor=principal.id, revision_id=draft.id,
    )
    downstream_contracts = ontology_runtime_v1.contract_binding_health(db, project_id=row.project_id)
    db.commit()
    return {"change_set": _change_set_dict(db, row), "revision": _revision_dict(draft), "environment": {"name": environment.name, "current_revision_id": environment.current_revision_id, "previous_revision_id": environment.previous_revision_id}, "applied": applied, "semantic_contract": semantic_contract, "downstream_contracts": downstream_contracts}


@router.get("/ontology/environments")
def list_ontology_environments(project_id: Optional[str] = None, principal: Principal = Depends(require_permission("view")), db: Session = Depends(get_db)):
    query = semantic_scope.accessible_query(db, principal, OntologyEnvironment)
    if project_id:
        tenancy.assert_project_permission(db, principal, project_id, "view")
        query = query.filter(OntologyEnvironment.project_id == project_id)
    return [{"id": row.id, "project_id": row.project_id, "name": row.name, "current_revision_id": row.current_revision_id, "previous_revision_id": row.previous_revision_id, "updated_by": row.updated_by, "updated_at": row.updated_at} for row in query.order_by(OntologyEnvironment.name).all()]


@router.post("/ontology/environments/{environment_name}/rollback")
def rollback_ontology_environment(environment_name: str, body: EnvironmentRollbackRequest, principal: Principal = Depends(require_permission("restore")), db: Session = Depends(get_db)):
    tenancy.assert_project_permission(db, principal, body.project_id, "restore")
    target = semantic_scope.owned_row(db, principal, OntologyRevision, body.revision_id, "view", "OntologyRevision")
    if target.project_id != body.project_id or target.status not in {"PUBLISHED", "SUPERSEDED"}:
        raise HTTPException(status_code=409, detail="Rollback target must be a published revision in the same project")
    environment = _environment(db, body.project_id, environment_name, principal.id)
    current = db.get(OntologyRevision, environment.current_revision_id) if environment.current_revision_id else None
    applied = _apply_manifest(db, body.project_id, target.manifest or {})
    rollback = _new_revision(db, body.project_id, target.manifest or {}, principal.id, status="PUBLISHED", parent_revision_id=current.id if current else None, branch_id=target.branch_id)
    if current and current.status == "PUBLISHED":
        current.status = "SUPERSEDED"
    environment.previous_revision_id = environment.current_revision_id
    environment.current_revision_id = rollback.id
    environment.updated_by = principal.id
    environment.updated_at = _now()
    _append_audit(db, principal.id, "ontology.environment.rolled_back", "ontology_environment", environment.id, {"project_id": body.project_id, "environment": environment_name, "restored_from_revision_id": target.id, "rollback_revision_id": rollback.id, "applied": applied})
    from . import ontology_runtime_v1
    semantic_contract = ontology_runtime_v1.materialize_semantic_definitions(
        db, project_id=body.project_id, actor=principal.id, revision_id=rollback.id,
    )
    downstream_contracts = ontology_runtime_v1.contract_binding_health(db, project_id=body.project_id)
    db.commit()
    return {"environment": {"id": environment.id, "project_id": environment.project_id, "name": environment.name, "current_revision_id": environment.current_revision_id, "previous_revision_id": environment.previous_revision_id}, "revision": _revision_dict(rollback), "restored_from_revision_id": target.id, "applied": applied, "semantic_contract": semantic_contract, "downstream_contracts": downstream_contracts}

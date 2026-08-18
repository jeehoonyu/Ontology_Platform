"""Versioned semantic contracts, temporal object history, and typed ontology queries.

The existing JSON schemas remain readable and writable while this module materializes
their query-critical metadata into normalized rows. This makes the migration additive
and allows old clients to continue operating during the OntologyOS transition.
"""

from __future__ import annotations

import base64
import hashlib
import json
import math
import os
import time
import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import (
    Boolean, Float, Index, Integer, JSON, String, UniqueConstraint, and_, case,
    cast, distinct, false, func, inspect, or_, select, text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.schema import CreateIndex
from sqlalchemy.sql.expression import Grouping
from sqlalchemy.orm import Mapped, Session, mapped_column

from . import models, ontology_core, ontology_versioning, semantic_scope, tenancy
from .database import Base, get_db
from .production_auth import Principal, require_permission
from .runtime import create_audit_log


router = APIRouter(prefix="/api/v1", tags=["ontologyos-v1"])


class OntologyPropertyDefinition(Base):
    __tablename__ = "ontology_property_definitions"
    __table_args__ = (
        UniqueConstraint("project_id", "object_type_id", "property_name", name="uq_ontology_property_project_type_name"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True)
    project_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    object_type_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    property_name: Mapped[str] = mapped_column(String, nullable=False)
    display_name: Mapped[str] = mapped_column(String, nullable=False)
    base_type: Mapped[str] = mapped_column(String, nullable=False, index=True)
    required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    primary_key: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    title_key: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    indexed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[str] = mapped_column(String, nullable=False, default="ACTIVE", index=True)
    definition: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    ontology_revision_id: Mapped[Optional[str]] = mapped_column(String, nullable=True, index=True)
    created_at: Mapped[int] = mapped_column(Integer, nullable=False)
    updated_at: Mapped[int] = mapped_column(Integer, nullable=False)


class OntologyResourceDefinition(Base):
    __tablename__ = "ontology_resource_definitions"
    __table_args__ = (
        UniqueConstraint("project_id", "resource_kind", "resource_id", name="uq_ontology_resource_project_kind_id"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True)
    project_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    resource_kind: Mapped[str] = mapped_column(String, nullable=False, index=True)
    resource_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    object_type_id: Mapped[Optional[str]] = mapped_column(String, nullable=True, index=True)
    display_name: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, default="ACTIVE", index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    definition: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    ontology_revision_id: Mapped[Optional[str]] = mapped_column(String, nullable=True, index=True)
    created_at: Mapped[int] = mapped_column(Integer, nullable=False)
    updated_at: Mapped[int] = mapped_column(Integer, nullable=False)


class OntologyIndexDefinition(Base):
    __tablename__ = "ontology_index_definitions"
    __table_args__ = (
        UniqueConstraint(
            "project_id", "object_type_id", "property_name", "strategy",
            name="uq_ontology_index_project_type_property_strategy",
        ),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True)
    project_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    object_type_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    property_name: Mapped[str] = mapped_column(String, nullable=False, index=True)
    base_type: Mapped[str] = mapped_column(String, nullable=False)
    index_name: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    strategy: Mapped[str] = mapped_column(String, nullable=False, default="BTREE_EXPRESSION")
    status: Mapped[str] = mapped_column(String, nullable=False, default="PLANNED", index=True)
    ddl: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    last_error: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    created_by: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[int] = mapped_column(Integer, nullable=False)
    updated_at: Mapped[int] = mapped_column(Integer, nullable=False)
    applied_at: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)


class ObjectChangeEvent(Base):
    __tablename__ = "object_change_events"
    __table_args__ = (
        UniqueConstraint("project_id", "object_id", "object_version", name="uq_object_change_project_object_version"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True)
    project_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    object_type_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    object_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    object_version: Mapped[int] = mapped_column(Integer, nullable=False)
    event_type: Mapped[str] = mapped_column(String, nullable=False, index=True)
    actor: Mapped[str] = mapped_column(String, nullable=False)
    source_type: Mapped[str] = mapped_column(String, nullable=False, index=True)
    source_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    before_state: Mapped[dict] = mapped_column(JSON().with_variant(JSONB(), "postgresql"), nullable=False, default=dict)
    after_state: Mapped[dict] = mapped_column(JSON().with_variant(JSONB(), "postgresql"), nullable=False, default=dict)
    changed_fields: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    evidence: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    ontology_revision_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    valid_from: Mapped[int] = mapped_column(Integer, nullable=False)
    valid_to: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    transaction_time: Mapped[int] = mapped_column(Integer, nullable=False, index=True)


class OntologyCompileRequest(BaseModel):
    project_id: str = "default"
    object_type_ids: List[str] = Field(default_factory=list)
    revision_id: Optional[str] = None


class OntologyContractRequest(BaseModel):
    project_id: str = "default"
    consumer_kind: str = Field(min_length=1, max_length=100)
    consumer_id: str = Field(min_length=1, max_length=200)
    consumer_version: str = Field(default="draft", min_length=1, max_length=100)
    payload: Dict[str, Any] = Field(default_factory=dict)


class OntologyIndexPlanRequest(BaseModel):
    project_id: str = "default"
    object_type_id: str = Field(min_length=1)
    property_names: List[str] = Field(default_factory=list)


class TypedFilter(BaseModel):
    field: str = Field(min_length=1, max_length=200)
    operator: str = Field(default="eq", pattern="^(eq|ne|gt|gte|lt|lte|in|contains|starts_with|is_null)$")
    value: Any = None


class TypedOrder(BaseModel):
    field: str = "updated_at"
    direction: str = Field(default="desc", pattern="^(asc|desc)$")


class SpatialConstraint(BaseModel):
    latitude_field: str = "latitude"
    longitude_field: str = "longitude"
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    radius_meters: float = Field(gt=0, le=2_000_000)


class TypedObjectQuery(BaseModel):
    project_id: str = "default"
    object_type_id: str
    filters: List[TypedFilter] = Field(default_factory=list)
    select: List[str] = Field(default_factory=list)
    order_by: List[TypedOrder] = Field(default_factory=lambda: [TypedOrder()])
    aggregates: List[Dict[str, Any]] = Field(default_factory=list)
    spatial: Optional[SpatialConstraint] = None
    as_of_transaction_time: Optional[int] = None
    as_of_valid_time: Optional[int] = None
    limit: int = Field(default=100, ge=1, le=1000)
    cursor: Optional[str] = None
    include_total: bool = True
    include_lineage: bool = True
    include_inactive: bool = False


class TypedGraphQuery(BaseModel):
    project_id: str = "default"
    seed_object_ids: List[str] = Field(min_length=1, max_length=100)
    depth: int = Field(default=1, ge=1, le=5)
    direction: str = Field(default="both", pattern="^(both|incoming|outgoing)$")
    link_type_ids: List[str] = Field(default_factory=list)
    object_type_ids: List[str] = Field(default_factory=list)
    max_nodes: int = Field(default=500, ge=1, le=5000)
    max_edges: int = Field(default=5000, ge=1, le=25000)
    include_inactive: bool = False


def _now() -> int:
    return int(time.time())


def _stable_id(*parts: str) -> str:
    digest = hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()[:32]
    return f"semantic_{digest}"


def _definition_dict(row: OntologyPropertyDefinition) -> Dict[str, Any]:
    return {
        "id": row.id,
        "project_id": row.project_id,
        "object_type_id": row.object_type_id,
        "property_name": row.property_name,
        "display_name": row.display_name,
        "base_type": row.base_type,
        "required": row.required,
        "primary_key": row.primary_key,
        "title_key": row.title_key,
        "indexed": row.indexed,
        "position": row.position,
        "status": row.status,
        "definition": row.definition or {},
        "ontology_revision_id": row.ontology_revision_id,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


def _resource_dict(row: OntologyResourceDefinition) -> Dict[str, Any]:
    return {
        "id": row.id,
        "project_id": row.project_id,
        "resource_kind": row.resource_kind,
        "resource_id": row.resource_id,
        "object_type_id": row.object_type_id,
        "display_name": row.display_name,
        "status": row.status,
        "version": row.version,
        "definition": row.definition or {},
        "ontology_revision_id": row.ontology_revision_id,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


def _index_dict(row: OntologyIndexDefinition) -> Dict[str, Any]:
    return {
        "id": row.id,
        "project_id": row.project_id,
        "object_type_id": row.object_type_id,
        "property_name": row.property_name,
        "base_type": row.base_type,
        "index_name": row.index_name,
        "strategy": row.strategy,
        "status": row.status,
        "ddl": row.ddl,
        "last_error": row.last_error,
        "created_by": row.created_by,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
        "applied_at": row.applied_at,
    }


def _plan_index_definition(db: Session, definition: OntologyPropertyDefinition, actor: str) -> OntologyIndexDefinition:
    # V3 appends the stable object id so ordered property queries can use the
    # same index for deterministic keyset pagination instead of sorting every
    # matching object. PostgreSQL can scan the pair in either direction.
    strategy = "BTREE_EXPRESSION_V3"
    row_id = _stable_id("index", definition.project_id, definition.object_type_id, definition.property_name, strategy)
    row = db.get(OntologyIndexDefinition, row_id)
    now = _now()
    if row is None:
        suffix = hashlib.sha256(row_id.encode("utf-8")).hexdigest()[:20]
        row = OntologyIndexDefinition(
            id=row_id,
            project_id=definition.project_id,
            object_type_id=definition.object_type_id,
            property_name=definition.property_name,
            base_type=definition.base_type,
            index_name=f"ix_oi_property_{suffix}",
            strategy=strategy,
            status="PLANNED",
            created_by=actor,
            created_at=now,
            updated_at=now,
        )
        db.add(row)
    else:
        if row.base_type != definition.base_type and row.status == "ACTIVE":
            row.status = "STALE"
        row.base_type = definition.base_type
        row.updated_at = now
    return row


def _event_dict(row: ObjectChangeEvent) -> Dict[str, Any]:
    return {
        "id": row.id,
        "project_id": row.project_id,
        "object_type_id": row.object_type_id,
        "object_id": row.object_id,
        "object_version": row.object_version,
        "event_type": row.event_type,
        "actor": row.actor,
        "source_type": row.source_type,
        "source_id": row.source_id,
        "before_state": row.before_state or {},
        "after_state": row.after_state or {},
        "changed_fields": row.changed_fields or [],
        "evidence": row.evidence or {},
        "ontology_revision_id": row.ontology_revision_id,
        "valid_from": row.valid_from,
        "valid_to": row.valid_to,
        "transaction_time": row.transaction_time,
    }


def _table_present(db: Session, bind: Any, table_name: str) -> bool:
    """Does `table_name` exist? Asked once per request, not once per row.

    Reflection is a database round-trip, and this question sits inside a loop
    that runs once per object written. A bulk hydrate asked it 1,002 times in a
    single request.

    Only a positive answer is cached. A missing table is the partial-schema
    compatibility path, where a caller may create the table later in the same
    session; a table that exists cannot stop existing under a live request, so
    that direction is safe to remember and is the one that repeats.
    """
    present = db.info.setdefault("_tables_present", set())
    if table_name in present:
        return True
    if inspect(bind).has_table(table_name):
        present.add(table_name)
        return True
    return False


def _active_revision_id(db: Session, project_id: str) -> Optional[str]:
    """The production revision for a project, looked up once per request.

    This sits in the same per-row loop as everything else here and was another
    ~1,000 statements on a bulk hydrate, all returning the same row.

    What is cached is the **entity, not the value**, and the difference is the
    whole reason this is safe. The industrial hydrate promotes a revision --
    `environment.current_revision_id = revision.id` -- and *then* writes the
    objects, in one request. A cached value would stamp every one of them with
    the superseded revision. A cached entity is the identity-mapped instance the
    promotion mutated, so reading the attribute here sees the new id; and if the
    session commits in between, the expired instance refreshes itself.

    Only a found row is cached: a project with no production environment yet may
    acquire one later in the same request.
    """
    cache = db.info.setdefault("_production_environments", {})
    environment = cache.get(project_id)
    if environment is None:
        environment = db.query(ontology_versioning.OntologyEnvironment).filter(
            ontology_versioning.OntologyEnvironment.project_id == project_id,
            ontology_versioning.OntologyEnvironment.name == "production",
        ).first()
        if environment is None:
            return None
        cache[project_id] = environment
    return environment.current_revision_id


_OBJECT_REFERENCE_KEYS = {
    "object_type_id", "source_object_type_id", "target_object_type_id",
    "object_type", "source_object_type", "target_object_type",
}
_ACTION_REFERENCE_KEYS = {"action_type_id"}
_PROPERTY_LIST_KEYS = {
    "properties", "property_names", "selected_properties", "selected_columns",
    "ontology_properties", "target_properties",
}


def _contract_enforcement_strict() -> bool:
    configured = os.getenv("ONTOLOGY_CONTRACT_ENFORCEMENT")
    if configured is not None:
        return configured.strip().lower() in {"strict", "true", "1", "on"}
    return os.getenv("APP_ENV", "development").strip().lower() == "production"


def _object_type_project_id(object_type: models.ObjectType) -> str:
    manager = ((object_type.properties or {}).get("__manager") or {}) if isinstance(object_type.properties, dict) else {}
    return str(manager.get("project_id") or object_type.project_id or "default")


def _extract_contract_references(payload: Any) -> Dict[str, Any]:
    """Extract ontology references from structured builder state without string scanning."""
    object_refs: Dict[str, Dict[str, Any]] = {}
    action_refs: Dict[str, set[str]] = {}

    def add_object(object_type_id: Any, path: str, properties: Optional[List[Any]] = None) -> Optional[str]:
        if not isinstance(object_type_id, str) or not object_type_id.strip():
            return None
        key = object_type_id.strip()
        entry = object_refs.setdefault(key, {"object_type_id": key, "properties": set(), "source_paths": set()})
        entry["source_paths"].add(path)
        for value in properties or []:
            if isinstance(value, str) and value and not value.startswith("__"):
                entry["properties"].add(value)
        return key

    def visit(value: Any, path: str, inherited_object_type: Optional[str] = None) -> None:
        if isinstance(value, list):
            for index, item in enumerate(value):
                visit(item, f"{path}[{index}]", inherited_object_type)
            return
        if not isinstance(value, dict):
            return

        local_types: List[str] = []
        for key in _OBJECT_REFERENCE_KEYS:
            candidate = value.get(key)
            resolved = add_object(candidate, f"{path}.{key}")
            if resolved:
                local_types.append(resolved)
        local_object_type = local_types[0] if len(local_types) == 1 else inherited_object_type

        for key in _ACTION_REFERENCE_KEYS:
            candidate = value.get(key)
            if isinstance(candidate, str) and candidate.strip():
                action_refs.setdefault(candidate.strip(), set()).add(f"{path}.{key}")

        if local_object_type:
            properties: List[Any] = []
            for key in _PROPERTY_LIST_KEYS:
                candidate = value.get(key)
                if isinstance(candidate, list):
                    properties.extend(candidate)
                elif isinstance(candidate, dict):
                    properties.extend(candidate.keys())
            for key in ("property_mapping", "mapping", "field_mapping"):
                candidate = value.get(key)
                if isinstance(candidate, dict):
                    properties.extend(candidate.values())
                elif isinstance(candidate, list):
                    properties.extend(
                        item.get("target_property")
                        for item in candidate if isinstance(item, dict)
                    )
            for key in ("property_name", "target_property", "ontology_property"):
                if key in value:
                    properties.append(value.get(key))
            add_object(local_object_type, path, properties)

        for key, child in value.items():
            visit(child, f"{path}.{key}", local_object_type)

    visit(payload, "payload")
    return {
        "object_types": [
            {
                "object_type_id": entry["object_type_id"],
                "properties": sorted(entry["properties"]),
                "source_paths": sorted(entry["source_paths"]),
            }
            for entry in sorted(object_refs.values(), key=lambda item: item["object_type_id"])
        ],
        "action_types": [
            {"action_type_id": action_id, "source_paths": sorted(paths)}
            for action_id, paths in sorted(action_refs.items())
        ],
    }


def validate_ontology_contract(
    db: Session,
    *,
    project_id: str,
    consumer_kind: str,
    consumer_id: str,
    consumer_version: str,
    payload: Dict[str, Any],
) -> Dict[str, Any]:
    references = _extract_contract_references(payload)
    revision_id = _active_revision_id(db, project_id)
    revision = db.get(ontology_versioning.OntologyRevision, revision_id) if revision_id else None
    issues: List[Dict[str, Any]] = []
    strict = _contract_enforcement_strict()
    has_references = bool(references["object_types"] or references["action_types"])
    if has_references and not revision:
        issues.append({
            "code": "ACTIVE_ONTOLOGY_REVISION_REQUIRED",
            "severity": "ERROR" if strict else "WARNING",
            "message": "Publish an ontology revision to the production environment before publishing this consumer.",
        })

    manifest = revision.manifest if revision else {}
    object_contracts = {
        str(item.get("id")): item for item in (manifest.get("object_types") or [])
        if isinstance(item, dict) and item.get("id")
    }
    action_contracts = {
        str(item.get("id")): item for item in (manifest.get("action_types") or [])
        if isinstance(item, dict) and item.get("id")
    }
    for reference in references["object_types"]:
        live_object_type = db.get(models.ObjectType, reference["object_type_id"])
        if not live_object_type:
            issues.append({"code": "OBJECT_TYPE_NOT_FOUND", "severity": "ERROR", **reference})
        elif _object_type_project_id(live_object_type) != project_id:
            issues.append({"code": "CROSS_PROJECT_OBJECT_TYPE", "severity": "ERROR", **reference})
    for reference in references["action_types"]:
        live_action = db.get(models.ActionType, reference["action_type_id"])
        if not live_action:
            issues.append({"code": "ACTION_TYPE_NOT_FOUND", "severity": "ERROR", **reference})
        elif live_action.project_id != project_id:
            issues.append({"code": "CROSS_PROJECT_ACTION_TYPE", "severity": "ERROR", **reference})
    if revision:
        for reference in references["object_types"]:
            object_type_id = reference["object_type_id"]
            contract = object_contracts.get(object_type_id)
            if not contract:
                issues.append({"code": "OBJECT_TYPE_NOT_IN_REVISION", "severity": "ERROR", "object_type_id": object_type_id, "source_paths": reference["source_paths"]})
                continue
            available = set((contract.get("properties") or {}).keys())
            missing = sorted(set(reference["properties"]) - available)
            if missing:
                issues.append({"code": "PROPERTIES_NOT_IN_REVISION", "severity": "ERROR", "object_type_id": object_type_id, "properties": missing, "source_paths": reference["source_paths"]})
        for reference in references["action_types"]:
            if reference["action_type_id"] not in action_contracts:
                issues.append({"code": "ACTION_TYPE_NOT_IN_REVISION", "severity": "ERROR", **reference})

    status = "FAIL" if any(item["severity"] == "ERROR" for item in issues) else "WARN" if issues else "PASS"
    return {
        "project_id": project_id,
        "consumer_kind": consumer_kind,
        "consumer_id": consumer_id,
        "consumer_version": consumer_version,
        "status": status,
        "strict": strict,
        "ontology_revision_id": revision.id if revision else None,
        "ontology_revision": revision.revision if revision else None,
        "ontology_checksum": revision.checksum if revision else None,
        "references": references,
        "issues": issues,
    }


def _contract_binding_health(row: OntologyResourceDefinition, revision: Optional[ontology_versioning.OntologyRevision]) -> Dict[str, Any]:
    definition = row.definition or {}
    if not revision:
        return {
            "status": "UNVERSIONED" if not row.ontology_revision_id else "NO_ACTIVE_REVISION",
            "compatible": not row.ontology_revision_id,
            "active_revision_id": None,
            "active_checksum": None,
            "missing_properties": [],
        }
    target_kind = str(definition.get("target_kind") or "object_type")
    target_id = str(definition.get("target_id") or row.object_type_id or "")
    collection = "action_types" if target_kind == "action_type" else "object_types"
    targets = {
        str(item.get("id")): item for item in (revision.manifest or {}).get(collection, [])
        if isinstance(item, dict) and item.get("id")
    }
    target = targets.get(target_id)
    missing_properties: List[str] = []
    reason = None
    if not target or str(target.get("status") or "ACTIVE").upper() == "ARCHIVED":
        reason = "TARGET_NOT_IN_ACTIVE_REVISION"
    elif target_kind == "object_type":
        available = set((target.get("properties") or {}).keys())
        missing_properties = sorted(set(definition.get("properties") or []) - available)
        if missing_properties:
            reason = "PROPERTIES_NOT_IN_ACTIVE_REVISION"
    compatible = reason is None
    if not compatible:
        status = "BROKEN"
    elif not row.ontology_revision_id:
        status = "UNVERSIONED"
    elif row.ontology_revision_id == revision.id:
        status = "CURRENT"
    else:
        status = "COMPATIBLE_STALE"
    return {
        "status": status,
        "compatible": compatible,
        "reason": reason,
        "bound_revision_id": row.ontology_revision_id,
        "bound_checksum": definition.get("ontology_checksum"),
        "active_revision_id": revision.id,
        "active_revision": revision.revision,
        "active_checksum": revision.checksum,
        "same_checksum": bool(definition.get("ontology_checksum") and definition.get("ontology_checksum") == revision.checksum),
        "missing_properties": missing_properties,
    }


def contract_binding_health(db: Session, *, project_id: str, object_type_id: Optional[str] = None) -> Dict[str, Any]:
    revision_id = _active_revision_id(db, project_id)
    revision = db.get(ontology_versioning.OntologyRevision, revision_id) if revision_id else None
    query = db.query(OntologyResourceDefinition).filter(
        OntologyResourceDefinition.project_id == project_id,
        OntologyResourceDefinition.resource_kind == "contract_binding",
        OntologyResourceDefinition.status == "ACTIVE",
    )
    if object_type_id:
        query = query.filter(OntologyResourceDefinition.object_type_id == object_type_id)
    rows = query.order_by(OntologyResourceDefinition.resource_id).all()
    bindings = [{**_resource_dict(row), "health": _contract_binding_health(row, revision)} for row in rows]
    counts = {status: 0 for status in ("CURRENT", "COMPATIBLE_STALE", "BROKEN", "UNVERSIONED", "NO_ACTIVE_REVISION")}
    for binding in bindings:
        status = binding["health"]["status"]
        counts[status] = counts.get(status, 0) + 1
    overall = "FAIL" if counts.get("BROKEN") or counts.get("NO_ACTIVE_REVISION") else "WARN" if counts.get("COMPATIBLE_STALE") or counts.get("UNVERSIONED") else "PASS"
    return {
        "project_id": project_id,
        "status": overall,
        "active_revision_id": revision.id if revision else None,
        "active_revision": revision.revision if revision else None,
        "active_checksum": revision.checksum if revision else None,
        "counts": counts,
        "binding_count": len(bindings),
        "bindings": bindings,
    }


def bind_ontology_contract(
    db: Session,
    *,
    project_id: str,
    consumer_kind: str,
    consumer_id: str,
    consumer_version: str,
    payload: Dict[str, Any],
    actor: str,
) -> Dict[str, Any]:
    result = validate_ontology_contract(
        db,
        project_id=project_id,
        consumer_kind=consumer_kind,
        consumer_id=consumer_id,
        consumer_version=consumer_version,
        payload=payload,
    )
    if result["status"] == "FAIL":
        raise HTTPException(status_code=422, detail={"message": "Ontology contract validation failed", **result})

    prefix = f"{consumer_kind}:{consumer_id}:"
    active_ids: set[str] = set()
    now = _now()
    candidates = db.query(OntologyResourceDefinition).filter(
        OntologyResourceDefinition.project_id == project_id,
        OntologyResourceDefinition.resource_kind == "contract_binding",
    ).all()
    consumer_rows = [
        row for row in candidates
        if (row.definition or {}).get("consumer_kind") == consumer_kind
        and (row.definition or {}).get("consumer_id") == consumer_id
    ]
    same_version = [row for row in consumer_rows if str((row.definition or {}).get("consumer_version")) == consumer_version]
    expected_targets = {
        ("object_type", reference["object_type_id"]): {
            "properties": reference["properties"], "source_paths": reference["source_paths"],
        }
        for reference in result["references"]["object_types"]
    }
    expected_targets.update({
        ("action_type", reference["action_type_id"]): {
            "properties": [], "source_paths": reference["source_paths"],
        }
        for reference in result["references"]["action_types"]
    })
    if same_version:
        existing_targets = {
            (str((row.definition or {}).get("target_kind")), str((row.definition or {}).get("target_id"))): {
                "properties": sorted((row.definition or {}).get("properties") or []),
                "source_paths": sorted((row.definition or {}).get("source_paths") or []),
            }
            for row in same_version
        }
        expected_comparable = {
            key: {"properties": sorted(value["properties"]), "source_paths": sorted(value["source_paths"])}
            for key, value in expected_targets.items()
        }
        bound_revisions = {row.ontology_revision_id for row in same_version}
        if existing_targets != expected_comparable or bound_revisions != {result["ontology_revision_id"]}:
            raise HTTPException(status_code=409, detail={
                "message": "Consumer version is immutable; publish a new consumer version to change its ontology contract",
                "consumer_kind": consumer_kind,
                "consumer_id": consumer_id,
                "consumer_version": consumer_version,
            })
    existing_by_target = {
        (str((row.definition or {}).get("target_kind")), str((row.definition or {}).get("target_id"))): row
        for row in same_version
    }
    for reference in result["references"]["object_types"]:
        object_type_id = reference["object_type_id"]
        prior = existing_by_target.get(("object_type", object_type_id))
        resource_id = prior.resource_id if prior else f"{prefix}{consumer_version}:object_type:{object_type_id}"
        active_ids.add(resource_id)
        _upsert_resource(
            db,
            project_id=project_id,
            kind="contract_binding",
            resource_id=resource_id,
            display_name=f"{consumer_kind} {consumer_id} -> {object_type_id}",
            object_type_id=object_type_id,
            revision_id=result["ontology_revision_id"],
            definition={
                "consumer_kind": consumer_kind,
                "consumer_id": consumer_id,
                "consumer_version": consumer_version,
                "target_kind": "object_type",
                "target_id": object_type_id,
                "properties": reference["properties"],
                "source_paths": reference["source_paths"],
                "ontology_revision": result["ontology_revision"],
                "ontology_checksum": result["ontology_checksum"],
                "binding_status": "ACTIVE" if result["ontology_revision_id"] else "UNVERSIONED",
            },
        )
    for reference in result["references"]["action_types"]:
        action_type_id = reference["action_type_id"]
        prior = existing_by_target.get(("action_type", action_type_id))
        resource_id = prior.resource_id if prior else f"{prefix}{consumer_version}:action_type:{action_type_id}"
        active_ids.add(resource_id)
        _upsert_resource(
            db,
            project_id=project_id,
            kind="contract_binding",
            resource_id=resource_id,
            display_name=f"{consumer_kind} {consumer_id} -> action {action_type_id}",
            revision_id=result["ontology_revision_id"],
            definition={
                "consumer_kind": consumer_kind,
                "consumer_id": consumer_id,
                "consumer_version": consumer_version,
                "target_kind": "action_type",
                "target_id": action_type_id,
                "source_paths": reference["source_paths"],
                "ontology_revision": result["ontology_revision"],
                "ontology_checksum": result["ontology_checksum"],
                "binding_status": "ACTIVE" if result["ontology_revision_id"] else "UNVERSIONED",
            },
        )

    for row in consumer_rows:
        if row.resource_id not in active_ids and row.status == "ACTIVE":
            row.status = "ARCHIVED"
            row.updated_at = now
            row.version += 1
    result["binding_count"] = len(active_ids)
    create_audit_log(
        db,
        actor=actor,
        event_type="ontology.contract.bound",
        subject_type="ontology_contract",
        subject_id=f"{consumer_kind}:{consumer_id}",
        payload={
            "project_id": project_id,
            "consumer_version": consumer_version,
            "ontology_revision_id": result["ontology_revision_id"],
            "binding_count": len(active_ids),
            "status": result["status"],
        },
    )
    return result


def _property_specs(db: Session, object_type: models.ObjectType) -> tuple[Dict[str, Any], Optional[ontology_core.ObjectTypeProfile]]:
    profile = db.get(ontology_core.ObjectTypeProfile, object_type.id)
    raw = profile.properties if profile and isinstance(profile.properties, dict) else (object_type.properties or {})
    return ({name: spec for name, spec in raw.items() if not str(name).startswith("__")}, profile)


def _upsert_resource(
    db: Session,
    *,
    project_id: str,
    kind: str,
    resource_id: str,
    display_name: str,
    definition: Dict[str, Any],
    revision_id: Optional[str],
    object_type_id: Optional[str] = None,
) -> OntologyResourceDefinition:
    row = db.query(OntologyResourceDefinition).filter(
        OntologyResourceDefinition.project_id == project_id,
        OntologyResourceDefinition.resource_kind == kind,
        OntologyResourceDefinition.resource_id == resource_id,
    ).first()
    now = _now()
    if row:
        changed = row.definition != definition or row.display_name != display_name or row.status != "ACTIVE"
        row.display_name = display_name
        row.object_type_id = object_type_id
        row.definition = definition
        row.status = "ACTIVE"
        row.ontology_revision_id = revision_id
        row.updated_at = now
        if changed:
            row.version += 1
        return row
    row = OntologyResourceDefinition(
        id=_stable_id(project_id, kind, resource_id),
        project_id=project_id,
        resource_kind=kind,
        resource_id=resource_id,
        object_type_id=object_type_id,
        display_name=display_name,
        status="ACTIVE",
        version=1,
        definition=definition,
        ontology_revision_id=revision_id,
        created_at=now,
        updated_at=now,
    )
    db.add(row)
    return row


def materialize_semantic_definitions(
    db: Session,
    *,
    project_id: str,
    actor: str,
    object_type_ids: Optional[List[str]] = None,
    revision_id: Optional[str] = None,
) -> Dict[str, Any]:
    db.flush()
    selected = set(object_type_ids or [])
    object_types = db.query(models.ObjectType).filter(models.ObjectType.project_id == project_id).order_by(models.ObjectType.id).all()
    if selected:
        missing = selected - {row.id for row in object_types}
        if missing:
            raise HTTPException(status_code=404, detail={"message": "Object types not found", "object_type_ids": sorted(missing)})
        object_types = [row for row in object_types if row.id in selected]
    revision_id = revision_id or _active_revision_id(db, project_id)
    now = _now()
    active_property_ids: set[str] = set()
    counts: Dict[str, int] = {"object_types": 0, "properties": 0, "constraints": 0, "links": 0, "actions": 0, "dependencies": 0}

    for object_type in object_types:
        specs, profile = _property_specs(db, object_type)
        _upsert_resource(
            db,
            project_id=project_id,
            kind="object_type",
            resource_id=object_type.id,
            display_name=object_type.display_name,
            object_type_id=object_type.id,
            revision_id=revision_id,
            definition={
                "description": object_type.description,
                "api_name": profile.api_name if profile else object_type.id,
                "primary_key": profile.primary_key if profile else None,
                "title_key": profile.title_key if profile else None,
                "groups": profile.groups if profile else [],
            },
        )
        counts["object_types"] += 1
        for position, (property_name, raw_spec) in enumerate(specs.items()):
            spec = dict(raw_spec) if isinstance(raw_spec, dict) else {"base_type": str(raw_spec)}
            definition_id = _stable_id(project_id, object_type.id, property_name)
            active_property_ids.add(definition_id)
            row = db.get(OntologyPropertyDefinition, definition_id)
            base_type = str(spec.get("base_type") or spec.get("type") or "string")
            if not row:
                row = OntologyPropertyDefinition(
                    id=definition_id,
                    project_id=project_id,
                    object_type_id=object_type.id,
                    property_name=property_name,
                    display_name=str(spec.get("display_name") or property_name),
                    base_type=base_type,
                    created_at=now,
                    updated_at=now,
                )
                db.add(row)
            row.display_name = str(spec.get("display_name") or property_name)
            row.base_type = base_type
            row.required = bool(spec.get("required"))
            row.primary_key = bool(profile and profile.primary_key == property_name)
            row.title_key = bool(profile and profile.title_key == property_name)
            row.indexed = bool(spec.get("indexed") or (profile and profile.primary_key == property_name))
            row.position = position
            row.status = str(spec.get("status") or "ACTIVE").upper()
            row.definition = spec
            row.ontology_revision_id = revision_id
            row.updated_at = now
            counts["properties"] += 1
            constraint_keys = {"minimum", "maximum", "min_length", "max_length", "pattern", "enum", "unit", "geometry_type"}
            constraints = {key: value for key, value in spec.items() if key in constraint_keys and value is not None}
            if constraints:
                _upsert_resource(
                    db,
                    project_id=project_id,
                    kind="constraint",
                    resource_id=f"{object_type.id}.{property_name}",
                    display_name=f"{object_type.display_name}.{property_name}",
                    object_type_id=object_type.id,
                    revision_id=revision_id,
                    definition=constraints,
                )
                counts["constraints"] += 1

    property_query = db.query(OntologyPropertyDefinition).filter(OntologyPropertyDefinition.project_id == project_id)
    if selected:
        property_query = property_query.filter(OntologyPropertyDefinition.object_type_id.in_(selected))
    for row in property_query.all():
        if row.id not in active_property_ids:
            row.status = "ARCHIVED"
            row.updated_at = now

    bind = db.get_bind()
    if bind is not None and inspect(bind).has_table(OntologyIndexDefinition.__tablename__):
        indexed_query = db.query(OntologyPropertyDefinition).filter(
            OntologyPropertyDefinition.project_id == project_id,
            OntologyPropertyDefinition.status == "ACTIVE",
            OntologyPropertyDefinition.indexed.is_(True),
        )
        if selected:
            indexed_query = indexed_query.filter(OntologyPropertyDefinition.object_type_id.in_(selected))
        for definition in indexed_query.all():
            _plan_index_definition(db, definition, actor)

    for link in db.query(models.LinkType).filter(models.LinkType.project_id == project_id).order_by(models.LinkType.id).all():
        if selected and not ({link.source_object_type_id, link.target_object_type_id} & selected):
            continue
        _upsert_resource(
            db, project_id=project_id, kind="link_type", resource_id=link.id,
            display_name=link.display_name, revision_id=revision_id,
            definition={
                "description": link.description,
                "source_object_type_id": link.source_object_type_id,
                "target_object_type_id": link.target_object_type_id,
                "cardinality": link.cardinality,
            },
        )
        counts["links"] += 1
        _upsert_resource(
            db, project_id=project_id, kind="dependency", resource_id=f"link:{link.id}",
            display_name=f"Dependency for {link.display_name}", revision_id=revision_id,
            definition={"source": link.source_object_type_id, "target": link.target_object_type_id, "via": link.id},
        )
        counts["dependencies"] += 1

    for action in db.query(models.ActionType).filter(models.ActionType.project_id == project_id).order_by(models.ActionType.id).all():
        target_types = sorted({str(item.get("object_type_id")) for item in (action.rules or {}).get("object_mutations", []) if item.get("object_type_id")})
        if selected and target_types and not (set(target_types) & selected):
            continue
        _upsert_resource(
            db, project_id=project_id, kind="action_type", resource_id=action.id,
            display_name=action.display_name, revision_id=revision_id,
            definition={"description": action.description, "parameters": action.parameters or {}, "rules": action.rules or {}, "target_object_types": target_types},
        )
        counts["actions"] += 1

    db.flush()
    canonical = {
        "project_id": project_id,
        "revision_id": revision_id,
        "properties": [
            {"object_type_id": row.object_type_id, "name": row.property_name, "type": row.base_type, "required": row.required, "status": row.status}
            for row in db.query(OntologyPropertyDefinition).filter(OntologyPropertyDefinition.project_id == project_id).order_by(OntologyPropertyDefinition.object_type_id, OntologyPropertyDefinition.position).all()
        ],
        "resources": [
            {"kind": row.resource_kind, "id": row.resource_id, "version": row.version, "status": row.status}
            for row in db.query(OntologyResourceDefinition).filter(OntologyResourceDefinition.project_id == project_id).order_by(OntologyResourceDefinition.resource_kind, OntologyResourceDefinition.resource_id).all()
        ],
    }
    checksum = hashlib.sha256(json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    create_audit_log(
        db, actor=actor, event_type="ontology.semantic_contract.compiled", subject_type="ontology_project", subject_id=project_id,
        payload={"project_id": project_id, "revision_id": revision_id, "counts": counts, "checksum": checksum},
    )
    return {"status": "COMPILED", "project_id": project_id, "revision_id": revision_id, "counts": counts, "checksum": checksum}


def record_object_change(
    db: Session,
    object_instance: models.ObjectInstance,
    *,
    before_state: Optional[Dict[str, Any]],
    event_type: str,
    actor: str,
    source_type: str,
    source_id: Optional[str] = None,
    evidence: Optional[Dict[str, Any]] = None,
    valid_from: Optional[int] = None,
) -> Optional[ObjectChangeEvent]:
    bind = db.get_bind()
    if bind is None or not _table_present(db, bind, ObjectChangeEvent.__tablename__):
        # Standalone compatibility routers may intentionally construct only a
        # subset of the schema. Production migrations require this table.
        return None
    db.flush()
    before = dict(before_state or {})
    after = dict(object_instance.properties or {})
    version = int(db.query(func.max(ObjectChangeEvent.object_version)).filter(
        ObjectChangeEvent.project_id == object_instance.project_id,
        ObjectChangeEvent.object_id == object_instance.id,
    ).scalar() or 0) + 1
    changed_fields = sorted(key for key in set(before) | set(after) if before.get(key) != after.get(key))
    now = _now()
    row = ObjectChangeEvent(
        id=f"object_event_{uuid.uuid4().hex}",
        project_id=object_instance.project_id,
        object_type_id=object_instance.object_type_id,
        object_id=object_instance.id,
        object_version=version,
        event_type=event_type,
        actor=actor,
        source_type=source_type,
        source_id=source_id,
        before_state=before,
        after_state=after,
        changed_fields=changed_fields,
        evidence=dict(evidence or {}),
        ontology_revision_id=_active_revision_id(db, object_instance.project_id),
        valid_from=valid_from or now,
        valid_to=None,
        transaction_time=now,
    )
    db.add(row)
    # Import lazily so the semantic runtime does not depend on transport setup
    # during module initialization or partial-schema compatibility tests.
    from . import event_outbox

    event_outbox.enqueue_domain_event(
        db,
        project_id=object_instance.project_id,
        topic="ontologyos.object_change",
        event_type=event_type,
        aggregate_type="ontology_object",
        aggregate_id=object_instance.id,
        actor=actor,
        payload={
            "evidence_id": row.id,
            "evidence_source": "object_change",
            "object_type_id": object_instance.object_type_id,
            "object_id": object_instance.id,
            "object_version": version,
            "before_state": before,
            "after_state": after,
            "changed_fields": changed_fields,
            "source_type": source_type,
            "source_id": source_id,
            "evidence": row.evidence,
            "ontology_revision_id": row.ontology_revision_id,
            "valid_from": row.valid_from,
            "transaction_time": row.transaction_time,
            "materialization": {
                "id": object_instance.materialization_id,
                "active": object_instance.is_active,
                "retired_at": object_instance.retired_at,
            },
        },
        idempotency_key=f"object_change:{row.id}",
        occurred_at=now,
        check_existing=False,
    )
    return row


def _field_value(item: Dict[str, Any], field: str) -> Any:
    if field in {"id", "object_type_id", "project_id", "created_at", "updated_at", "source_asset_id"}:
        return item.get(field)
    if field.startswith("properties."):
        field = field.split(".", 1)[1]
    return (item.get("properties") or {}).get(field)


def _matches_filter(item: Dict[str, Any], clause: TypedFilter) -> bool:
    actual = _field_value(item, clause.field)
    expected = clause.value
    if clause.operator == "eq":
        return actual == expected
    if clause.operator == "ne":
        return actual != expected
    if clause.operator == "is_null":
        return (actual is None) == (True if expected is None else bool(expected))
    if clause.operator == "in":
        return actual in (expected if isinstance(expected, list) else [expected])
    if clause.operator == "contains":
        return str(expected).lower() in str(actual or "").lower()
    if clause.operator == "starts_with":
        return str(actual or "").lower().startswith(str(expected).lower())
    if actual is None or expected is None:
        return False
    try:
        if clause.operator == "gt":
            return actual > expected
        if clause.operator == "gte":
            return actual >= expected
        if clause.operator == "lt":
            return actual < expected
        if clause.operator == "lte":
            return actual <= expected
    except TypeError:
        return False
    return False


def _distance_meters(latitude: float, longitude: float, target_latitude: float, target_longitude: float) -> float:
    radius = 6_371_000.0
    phi1, phi2 = math.radians(latitude), math.radians(target_latitude)
    delta_phi = math.radians(target_latitude - latitude)
    delta_lambda = math.radians(target_longitude - longitude)
    value = math.sin(delta_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2) ** 2
    return radius * 2 * math.atan2(math.sqrt(value), math.sqrt(1 - value))


def _matches_spatial(item: Dict[str, Any], spatial: SpatialConstraint) -> bool:
    try:
        latitude = float(_field_value(item, spatial.latitude_field))
        longitude = float(_field_value(item, spatial.longitude_field))
    except (TypeError, ValueError):
        return False
    return _distance_meters(latitude, longitude, spatial.latitude, spatial.longitude) <= spatial.radius_meters


def _cursor_hash(body: TypedObjectQuery) -> str:
    payload = body.model_dump(exclude={"cursor", "limit", "include_total"})
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode("utf-8")).hexdigest()[:16]


def _decode_cursor(cursor: Optional[str], expected_hash: str) -> int:
    if not cursor:
        return 0
    try:
        raw = base64.urlsafe_b64decode(cursor.encode("ascii") + b"===")
        payload = json.loads(raw.decode("utf-8"))
        if payload.get("query") != expected_hash:
            raise ValueError("query mismatch")
        return max(0, int(payload.get("offset", 0)))
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Invalid or stale cursor: {exc}")


def _encode_cursor(offset: int, query_hash: str) -> str:
    raw = json.dumps({"offset": offset, "query": query_hash}, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _decode_sql_cursor(cursor: Optional[str], expected_hash: str) -> tuple[int, Optional[List[Any]]]:
    if not cursor:
        return 0, None
    try:
        raw = base64.urlsafe_b64decode(cursor.encode("ascii") + b"===")
        payload = json.loads(raw.decode("utf-8"))
        if payload.get("query") != expected_hash:
            raise ValueError("query mismatch")
        if payload.get("version") == 2:
            keys = payload.get("keys")
            if not isinstance(keys, list):
                raise ValueError("missing keyset values")
            return 0, keys
        return max(0, int(payload.get("offset", 0))), None
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Invalid or stale cursor: {exc}")


def _encode_sql_cursor(keys: List[Any], query_hash: str) -> str:
    raw = json.dumps({"version": 2, "keys": keys, "query": query_hash}, separators=(",", ":"), default=str).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


_INTEGER_TYPES = {"byte", "short", "integer", "long"}
_NUMBER_TYPES = {"float", "double", "decimal", "number"}
_BOOLEAN_TYPES = {"boolean"}
_METADATA_FIELDS = {
    "id", "project_id", "object_type_id", "source_asset_id", "materialization_id",
    "is_active", "retired_at", "created_at", "updated_at",
}


def _query_source(db: Session, body: TypedObjectQuery):
    temporal = body.as_of_transaction_time is not None or body.as_of_valid_time is not None
    if not temporal:
        source = models.ObjectInstance.__table__
        columns = {name: source.c[name] for name in _METADATA_FIELDS}
        columns["properties"] = source.c.properties
        columns["lineage"] = source.c.lineage
        conditions = [source.c.project_id == body.project_id, source.c.object_type_id == body.object_type_id]
        if not body.include_inactive:
            conditions.append(source.c.is_active.is_(True))
        return source, columns, conditions, False

    event = ObjectChangeEvent.__table__
    conditions = [event.c.project_id == body.project_id, event.c.object_type_id == body.object_type_id]
    if body.as_of_transaction_time is not None:
        conditions.append(event.c.transaction_time <= body.as_of_transaction_time)
    if body.as_of_valid_time is not None:
        conditions.extend([
            event.c.valid_from <= body.as_of_valid_time,
            or_(event.c.valid_to.is_(None), event.c.valid_to > body.as_of_valid_time),
        ])
    ranked = select(
        event.c.object_id.label("id"), event.c.project_id, event.c.object_type_id,
        event.c.after_state.label("properties"), event.c.valid_from.label("created_at"),
        event.c.transaction_time.label("updated_at"), event.c.id.label("temporal_event_id"),
        event.c.object_version, event.c.event_type,
        case((event.c.event_type == "ontology.object.retired", False), else_=True).label("is_active"),
        case((event.c.event_type == "ontology.object.retired", event.c.transaction_time), else_=None).label("retired_at"),
        func.row_number().over(
            partition_by=event.c.object_id,
            order_by=(event.c.transaction_time.desc(), event.c.object_version.desc()),
        ).label("temporal_rank"),
    ).where(*conditions).subquery("ranked_object_events")
    columns = {
        "id": ranked.c.id,
        "project_id": ranked.c.project_id,
        "object_type_id": ranked.c.object_type_id,
        "source_asset_id": cast(None, String),
        "materialization_id": cast(None, String),
        "is_active": ranked.c.is_active,
        "retired_at": ranked.c.retired_at,
        "created_at": ranked.c.created_at,
        "updated_at": ranked.c.updated_at,
        "properties": ranked.c.properties,
        "temporal_event_id": ranked.c.temporal_event_id,
        "object_version": ranked.c.object_version,
    }
    conditions = [ranked.c.temporal_rank == 1, ranked.c.event_type != "ontology.object.deleted"]
    if not body.include_inactive:
        conditions.append(ranked.c.is_active.is_(True))
    return ranked, columns, conditions, True


def _json_value_expression(db: Session, properties, field: str, base_type: Optional[str]):
    raw = properties[field]
    dialect = db.get_bind().dialect.name
    text_value = properties.op("->>")(field) if dialect == "postgresql" else raw.as_string()
    json_type = func.jsonb_typeof(raw) if dialect == "postgresql" else func.json_type(properties, f'$."{field}"')
    normalized = str(base_type or "string").lower()
    if normalized in _INTEGER_TYPES:
        allowed = json_type == "number" if dialect == "postgresql" else json_type.in_(["integer", "real"])
        return case((allowed, cast(text_value, Integer)), else_=None)
    if normalized in _NUMBER_TYPES:
        allowed = json_type == "number" if dialect == "postgresql" else json_type.in_(["integer", "real"])
        return case((allowed, cast(text_value, Float)), else_=None)
    if normalized in _BOOLEAN_TYPES:
        allowed = json_type == "boolean" if dialect == "postgresql" else json_type.in_(["true", "false"])
        return case((allowed, raw.as_boolean()), else_=None)
    return text_value


def _sql_field_expression(db: Session, columns: Dict[str, Any], field: str, known_fields: Dict[str, str]):
    normalized = field.removeprefix("properties.")
    if normalized in _METADATA_FIELDS:
        return columns[normalized]
    return _json_value_expression(db, columns["properties"], normalized, known_fields.get(normalized))


def _physical_property_index(db: Session, row: OntologyIndexDefinition) -> Index:
    table = models.ObjectInstance.__table__
    existing = next((candidate for candidate in table.indexes if candidate.name == row.index_name), None)
    if existing is not None:
        return existing
    value = Grouping(_json_value_expression(db, table.c.properties, row.property_name, row.base_type))
    return Index(row.index_name, table.c.project_id, table.c.object_type_id, value, table.c.id)


def _filter_guarantees_non_null(body: TypedObjectQuery, field: str) -> bool:
    normalized = field.removeprefix("properties.")
    for clause in body.filters:
        if clause.field.removeprefix("properties.") != normalized:
            continue
        if clause.operator in {"gt", "gte", "lt", "lte", "contains", "starts_with"} and clause.value is not None:
            return True
        if clause.operator == "eq" and clause.value is not None:
            return True
        if clause.operator == "in":
            values = clause.value if isinstance(clause.value, list) else [clause.value]
            if values and all(value is not None for value in values):
                return True
        if clause.operator == "is_null" and clause.value is False:
            return True
    return False


def _compile_filter(expression, clause: TypedFilter):
    expected = clause.value
    if clause.operator == "eq":
        return expression.is_(None) if expected is None else expression == expected
    if clause.operator == "ne":
        return expression.is_not(None) if expected is None else or_(expression != expected, expression.is_(None))
    if clause.operator == "is_null":
        wants_null = True if expected is None else bool(expected)
        return expression.is_(None) if wants_null else expression.is_not(None)
    if clause.operator == "in":
        values = expected if isinstance(expected, list) else [expected]
        non_null = [value for value in values if value is not None]
        conditions = [expression.in_(non_null)] if non_null else []
        if any(value is None for value in values):
            conditions.append(expression.is_(None))
        return or_(*conditions) if conditions else false()
    if clause.operator == "contains":
        return func.lower(func.coalesce(cast(expression, String), "")).contains(str(expected).lower())
    if clause.operator == "starts_with":
        return func.lower(func.coalesce(cast(expression, String), "")).startswith(str(expected).lower())
    if expected is None:
        return false()
    return {"gt": expression > expected, "gte": expression >= expected, "lt": expression < expected, "lte": expression <= expected}[clause.operator]


def _spatial_sql_expression(db: Session, columns: Dict[str, Any], known_fields: Dict[str, str], spatial: SpatialConstraint):
    latitude = cast(_sql_field_expression(db, columns, spatial.latitude_field, {**known_fields, spatial.latitude_field: "double"}), Float)
    longitude = cast(_sql_field_expression(db, columns, spatial.longitude_field, {**known_fields, spatial.longitude_field: "double"}), Float)
    phi1 = func.radians(latitude)
    phi2 = math.radians(spatial.latitude)
    delta_phi = func.radians(spatial.latitude - latitude)
    delta_lambda = func.radians(spatial.longitude - longitude)
    haversine = func.pow(func.sin(delta_phi / 2.0), 2) + func.cos(phi1) * math.cos(phi2) * func.pow(func.sin(delta_lambda / 2.0), 2)
    distance = 6_371_000.0 * 2.0 * func.asin(func.sqrt(haversine))
    latitude_delta = spatial.radius_meters / 111_320.0
    longitude_scale = max(0.01, math.cos(math.radians(spatial.latitude)))
    longitude_delta = spatial.radius_meters / (111_320.0 * longitude_scale)
    return and_(
        latitude.between(spatial.latitude - latitude_delta, spatial.latitude + latitude_delta),
        longitude.between(spatial.longitude - longitude_delta, spatial.longitude + longitude_delta),
        distance <= spatial.radius_meters,
    )


def _keyset_predicate(ordering: List[tuple[Any, str]], keys: List[Any]):
    if len(keys) != len(ordering):
        raise HTTPException(status_code=422, detail="Cursor does not match query ordering")
    branches = []
    equal_prefix = []
    for (expression, direction), value in zip(ordering, keys):
        if value is not None:
            comparison = expression > value if direction == "asc" else expression < value
            branches.append(and_(*equal_prefix, or_(comparison, expression.is_(None))))
        equal_prefix.append(expression.is_(None) if value is None else expression == value)
    return or_(*branches) if branches else false()


def _compile_aggregates(db: Session, columns: Dict[str, Any], known_fields: Dict[str, str], specs: List[Dict[str, Any]]):
    expressions = []
    names = []
    for index, spec in enumerate(specs):
        operation = str(spec.get("operation") or spec.get("op") or "count").lower()
        field = str(spec.get("field") or "id")
        name = str(spec.get("name") or f"{operation}_{field.replace('.', '_')}_{index}")
        value = _sql_field_expression(db, columns, field, known_fields)
        if operation == "count":
            aggregate = func.count() if field == "id" else func.count(value)
        elif operation == "distinct_count":
            aggregate = func.count(distinct(value))
        elif operation == "sum":
            aggregate = func.sum(value)
        elif operation == "avg":
            aggregate = func.avg(value)
        elif operation == "min":
            aggregate = func.min(value)
        elif operation == "max":
            aggregate = func.max(value)
        else:
            raise HTTPException(status_code=422, detail=f"Unsupported aggregate operation '{operation}'")
        expressions.append(aggregate.label(name))
        names.append(name)
    return expressions, names


def _object_rows(db: Session, body: TypedObjectQuery) -> List[Dict[str, Any]]:
    if body.as_of_transaction_time is not None or body.as_of_valid_time is not None:
        query = db.query(ObjectChangeEvent).filter(
            ObjectChangeEvent.project_id == body.project_id,
            ObjectChangeEvent.object_type_id == body.object_type_id,
        )
        if body.as_of_transaction_time is not None:
            query = query.filter(ObjectChangeEvent.transaction_time <= body.as_of_transaction_time)
        if body.as_of_valid_time is not None:
            query = query.filter(ObjectChangeEvent.valid_from <= body.as_of_valid_time).filter(
                (ObjectChangeEvent.valid_to.is_(None)) | (ObjectChangeEvent.valid_to > body.as_of_valid_time)
            )
        latest: Dict[str, ObjectChangeEvent] = {}
        for event in query.order_by(ObjectChangeEvent.object_id, ObjectChangeEvent.object_version).all():
            latest[event.object_id] = event
        return [
            {
                "id": event.object_id,
                "project_id": event.project_id,
                "object_type_id": event.object_type_id,
                "properties": event.after_state or {},
                "lineage": {"temporal_event_id": event.id, "object_version": event.object_version},
                "created_at": event.valid_from,
                "updated_at": event.transaction_time,
            }
            for event in latest.values()
            if event.event_type != "ontology.object.deleted"
        ]
    rows = db.query(models.ObjectInstance).filter(
        models.ObjectInstance.project_id == body.project_id,
        models.ObjectInstance.object_type_id == body.object_type_id,
    )
    if not body.include_inactive:
        rows = rows.filter(models.ObjectInstance.is_active.is_(True))
    rows = rows.all()
    return [
        {
            "id": row.id,
            "project_id": row.project_id,
            "object_type_id": row.object_type_id,
            "properties": dict(row.properties or {}),
            "lineage": dict(row.lineage or {}),
            "source_asset_id": row.source_asset_id,
            "materialization_id": row.materialization_id,
            "is_active": row.is_active,
            "retired_at": row.retired_at,
            "created_at": row.created_at,
            "updated_at": row.updated_at,
        }
        for row in rows
    ]


def _aggregate(rows: List[Dict[str, Any]], specs: List[Dict[str, Any]]) -> Dict[str, Any]:
    output: Dict[str, Any] = {}
    for index, spec in enumerate(specs):
        operation = str(spec.get("operation") or spec.get("op") or "count").lower()
        field = str(spec.get("field") or "id")
        name = str(spec.get("name") or f"{operation}_{field.replace('.', '_')}_{index}")
        values = [_field_value(row, field) for row in rows]
        present = [value for value in values if value is not None]
        if operation == "count":
            output[name] = len(present) if field != "id" else len(rows)
        elif operation == "distinct_count":
            output[name] = len({json.dumps(value, sort_keys=True, default=str) for value in present})
        elif operation in {"sum", "avg", "min", "max"}:
            numeric = [float(value) for value in present if isinstance(value, (int, float)) and not isinstance(value, bool)]
            output[name] = None if not numeric else ({"sum": sum, "min": min, "max": max}[operation](numeric) if operation != "avg" else sum(numeric) / len(numeric))
        else:
            raise HTTPException(status_code=422, detail=f"Unsupported aggregate operation '{operation}'")
    return output


def _masked_fields_for_types(db: Session, principal: Principal, project_id: str, object_type_ids: set[str]) -> Dict[str, set[str]]:
    if "*" in principal.permissions or "view_sensitive" in principal.permissions or not object_type_ids:
        return {}
    rows = db.query(OntologyPropertyDefinition).filter(
        OntologyPropertyDefinition.project_id == project_id,
        OntologyPropertyDefinition.object_type_id.in_(object_type_ids),
        OntologyPropertyDefinition.status == "ACTIVE",
    ).all()
    output: Dict[str, set[str]] = {}
    for row in rows:
        if bool((row.definition or {}).get("masked") or (row.definition or {}).get("sensitive")):
            output.setdefault(row.object_type_id, set()).add(row.property_name)
    return output


@router.post("/ontology/compile")
def compile_ontology(body: OntologyCompileRequest, principal: Principal = Depends(require_permission("edit")), db: Session = Depends(get_db)):
    tenancy.assert_project_permission(db, principal, body.project_id, "edit")
    if body.revision_id:
        revision = semantic_scope.owned_row(db, principal, ontology_versioning.OntologyRevision, body.revision_id, "view", "OntologyRevision")
        if revision.project_id != body.project_id:
            raise HTTPException(status_code=409, detail="Ontology revision belongs to another project")
    result = materialize_semantic_definitions(
        db, project_id=body.project_id, actor=principal.id, object_type_ids=body.object_type_ids, revision_id=body.revision_id,
    )
    db.commit()
    return result


@router.post("/ontology/contracts/validate")
def validate_contract_endpoint(body: OntologyContractRequest, principal: Principal = Depends(require_permission("view")), db: Session = Depends(get_db)):
    tenancy.assert_project_permission(db, principal, body.project_id, "view")
    return validate_ontology_contract(
        db,
        project_id=body.project_id,
        consumer_kind=body.consumer_kind,
        consumer_id=body.consumer_id,
        consumer_version=body.consumer_version,
        payload=body.payload,
    )


@router.post("/ontology/contracts/bind")
def bind_contract_endpoint(body: OntologyContractRequest, principal: Principal = Depends(require_permission("publish")), db: Session = Depends(get_db)):
    tenancy.assert_project_permission(db, principal, body.project_id, "publish")
    result = bind_ontology_contract(
        db,
        project_id=body.project_id,
        consumer_kind=body.consumer_kind,
        consumer_id=body.consumer_id,
        consumer_version=body.consumer_version,
        payload=body.payload,
        actor=principal.id,
    )
    db.commit()
    return result


@router.get("/ontology/contracts/bindings")
def list_contract_bindings(
    project_id: str = "default",
    consumer_kind: Optional[str] = None,
    consumer_id: Optional[str] = None,
    object_type_id: Optional[str] = None,
    include_archived: bool = False,
    principal: Principal = Depends(require_permission("view")),
    db: Session = Depends(get_db),
):
    tenancy.assert_project_permission(db, principal, project_id, "view")
    query = db.query(OntologyResourceDefinition).filter(
        OntologyResourceDefinition.project_id == project_id,
        OntologyResourceDefinition.resource_kind == "contract_binding",
    )
    if not include_archived:
        query = query.filter(OntologyResourceDefinition.status == "ACTIVE")
    if object_type_id:
        query = query.filter(OntologyResourceDefinition.object_type_id == object_type_id)
    rows = query.order_by(OntologyResourceDefinition.resource_id).all()
    if consumer_kind:
        rows = [row for row in rows if (row.definition or {}).get("consumer_kind") == consumer_kind]
    if consumer_id:
        rows = [row for row in rows if (row.definition or {}).get("consumer_id") == consumer_id]
    revision_id = _active_revision_id(db, project_id)
    revision = db.get(ontology_versioning.OntologyRevision, revision_id) if revision_id else None
    return {
        "project_id": project_id,
        "count": len(rows),
        "bindings": [{**_resource_dict(row), "health": _contract_binding_health(row, revision)} for row in rows],
    }


@router.get("/ontology/contracts/health")
def read_contract_binding_health(
    project_id: str = "default",
    object_type_id: Optional[str] = None,
    principal: Principal = Depends(require_permission("view")),
    db: Session = Depends(get_db),
):
    tenancy.assert_project_permission(db, principal, project_id, "view")
    return contract_binding_health(db, project_id=project_id, object_type_id=object_type_id)


@router.get("/ontology/schema/definitions")
def list_semantic_definitions(project_id: str = "default", object_type_id: Optional[str] = None, principal: Principal = Depends(require_permission("view")), db: Session = Depends(get_db)):
    tenancy.assert_project_permission(db, principal, project_id, "view")
    property_query = db.query(OntologyPropertyDefinition).filter(OntologyPropertyDefinition.project_id == project_id)
    resource_query = db.query(OntologyResourceDefinition).filter(OntologyResourceDefinition.project_id == project_id)
    if object_type_id:
        semantic_scope.object_type_for(db, principal, object_type_id, "view")
        property_query = property_query.filter(OntologyPropertyDefinition.object_type_id == object_type_id)
        resource_query = resource_query.filter(OntologyResourceDefinition.object_type_id == object_type_id)
    properties = property_query.order_by(OntologyPropertyDefinition.object_type_id, OntologyPropertyDefinition.position).all()
    resources = resource_query.order_by(OntologyResourceDefinition.resource_kind, OntologyResourceDefinition.resource_id).all()
    return {"project_id": project_id, "properties": [_definition_dict(row) for row in properties], "resources": [_resource_dict(row) for row in resources]}


@router.post("/ontology/indexes/plan")
def plan_ontology_indexes(body: OntologyIndexPlanRequest, principal: Principal = Depends(require_permission("edit")), db: Session = Depends(get_db)):
    object_type = semantic_scope.object_type_for(db, principal, body.object_type_id, "edit")
    if object_type.project_id != body.project_id:
        raise HTTPException(status_code=409, detail="Object type belongs to another project")
    query = db.query(OntologyPropertyDefinition).filter(
        OntologyPropertyDefinition.project_id == body.project_id,
        OntologyPropertyDefinition.object_type_id == body.object_type_id,
        OntologyPropertyDefinition.status == "ACTIVE",
    )
    if body.property_names:
        query = query.filter(OntologyPropertyDefinition.property_name.in_(body.property_names))
    else:
        query = query.filter(OntologyPropertyDefinition.indexed.is_(True))
    definitions = query.order_by(OntologyPropertyDefinition.position).all()
    missing = set(body.property_names) - {row.property_name for row in definitions}
    if missing:
        raise HTTPException(status_code=422, detail={"message": "Properties are not active semantic definitions", "properties": sorted(missing)})
    plans = [_plan_index_definition(db, definition, principal.id) for definition in definitions]
    db.flush()
    create_audit_log(
        db, actor=principal.id, event_type="ontology.indexes.planned", subject_type="object_type",
        subject_id=body.object_type_id,
        payload={"project_id": body.project_id, "property_names": [row.property_name for row in plans]},
    )
    db.commit()
    return {"project_id": body.project_id, "object_type_id": body.object_type_id, "count": len(plans), "indexes": [_index_dict(row) for row in plans]}


@router.get("/ontology/indexes")
def list_ontology_indexes(project_id: str = "default", object_type_id: Optional[str] = None, principal: Principal = Depends(require_permission("view")), db: Session = Depends(get_db)):
    tenancy.assert_project_permission(db, principal, project_id, "view")
    query = db.query(OntologyIndexDefinition).filter(OntologyIndexDefinition.project_id == project_id)
    if object_type_id:
        object_type = semantic_scope.object_type_for(db, principal, object_type_id, "view")
        if object_type.project_id != project_id:
            raise HTTPException(status_code=409, detail="Object type belongs to another project")
        query = query.filter(OntologyIndexDefinition.object_type_id == object_type_id)
    rows = query.order_by(OntologyIndexDefinition.object_type_id, OntologyIndexDefinition.property_name).all()
    return {"project_id": project_id, "count": len(rows), "indexes": [_index_dict(row) for row in rows]}


@router.post("/ontology/indexes/{index_id}/apply")
def apply_ontology_index(index_id: str, principal: Principal = Depends(require_permission("administer")), db: Session = Depends(get_db)):
    row = db.get(OntologyIndexDefinition, index_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Ontology index plan not found")
    tenancy.assert_project_permission(db, principal, row.project_id, "administer")
    index = _physical_property_index(db, row)
    bind = db.get_bind()
    row.ddl = str(CreateIndex(index).compile(dialect=bind.dialect, compile_kwargs={"literal_binds": True}))
    row.updated_at = _now()
    try:
        index.create(bind=bind, checkfirst=True)
        if bind.dialect.name == "postgresql":
            # Expression-index selectivity is unknown until PostgreSQL samples
            # the new expression. Without this refresh the planner can prefer
            # an ordered primary-key scan and filter every ontology object.
            db.execute(text("ANALYZE object_instances"))
        row.status = "ACTIVE"
        row.last_error = None
        row.applied_at = _now()
        create_audit_log(
            db, actor=principal.id, event_type="ontology.index.applied", subject_type="ontology_index",
            subject_id=row.id,
            payload={"project_id": row.project_id, "object_type_id": row.object_type_id, "property_name": row.property_name, "index_name": row.index_name},
        )
        db.commit()
    except Exception as exc:
        failed_ddl = row.ddl
        db.rollback()
        failed = db.get(OntologyIndexDefinition, index_id)
        if failed is not None:
            failed.status = "FAILED"
            failed.ddl = failed_ddl
            failed.last_error = str(exc)[:2000]
            failed.updated_at = _now()
            db.commit()
        raise HTTPException(status_code=500, detail={"message": "Ontology index creation failed", "index_id": index_id}) from exc
    return _index_dict(row)


@router.post("/objects/query")
def query_objects(body: TypedObjectQuery, principal: Principal = Depends(require_permission("view")), db: Session = Depends(get_db)):
    object_type = semantic_scope.object_type_for(db, principal, body.object_type_id, "view")
    if object_type.project_id != body.project_id:
        raise HTTPException(status_code=409, detail="Object type belongs to another project")
    definitions = db.query(OntologyPropertyDefinition).filter(
        OntologyPropertyDefinition.project_id == body.project_id,
        OntologyPropertyDefinition.object_type_id == body.object_type_id,
        OntologyPropertyDefinition.status == "ACTIVE",
    ).all()
    active_indexes = db.query(OntologyIndexDefinition).filter(
        OntologyIndexDefinition.project_id == body.project_id,
        OntologyIndexDefinition.object_type_id == body.object_type_id,
        OntologyIndexDefinition.status == "ACTIVE",
    ).all()
    known_fields = {row.property_name: row.base_type for row in definitions}
    if known_fields:
        invalid = sorted({clause.field.removeprefix("properties.") for clause in body.filters if clause.field not in {"id", "created_at", "updated_at", "source_asset_id"} and clause.field.removeprefix("properties.") not in known_fields})
        invalid.extend(sorted({order.field.removeprefix("properties.") for order in body.order_by if order.field not in _METADATA_FIELDS and order.field.removeprefix("properties.") not in known_fields}))
        if body.spatial:
            invalid.extend(field for field in (body.spatial.latitude_field, body.spatial.longitude_field) if field.removeprefix("properties.") not in known_fields)
        if invalid:
            raise HTTPException(status_code=422, detail={"message": "Unknown ontology query fields", "fields": sorted(set(invalid))})

    source, columns, conditions, temporal = _query_source(db, body)
    conditions.extend(_compile_filter(_sql_field_expression(db, columns, clause.field, known_fields), clause) for clause in body.filters)
    if body.spatial:
        conditions.append(_spatial_sql_expression(db, columns, known_fields, body.spatial))

    ordering: List[tuple[Any, str]] = [
        (_sql_field_expression(db, columns, order.field, known_fields), order.direction)
        for order in body.order_by
    ]
    if not any(order.field == "id" for order in body.order_by):
        tie_break_direction = body.order_by[0].direction if len(body.order_by) == 1 else "asc"
        ordering.append((columns["id"], tie_break_direction))

    query_hash = _cursor_hash(body)
    legacy_offset, cursor_keys = _decode_sql_cursor(body.cursor, query_hash)
    page_conditions = list(conditions)
    if cursor_keys is not None:
        page_conditions.append(_keyset_predicate(ordering, cursor_keys))

    selected = [
        columns["id"].label("id"), columns["project_id"].label("project_id"),
        columns["object_type_id"].label("object_type_id"), columns["properties"].label("properties"),
        columns["source_asset_id"].label("source_asset_id"), columns["created_at"].label("created_at"),
        columns["updated_at"].label("updated_at"), columns["materialization_id"].label("materialization_id"),
        columns["is_active"].label("is_active"), columns["retired_at"].label("retired_at"),
    ]
    if temporal:
        selected.extend([
            columns["temporal_event_id"].label("temporal_event_id"),
            columns["object_version"].label("object_version"),
        ])
    else:
        selected.append(columns["lineage"].label("lineage"))
    selected.extend(expression.label(f"_order_{index}") for index, (expression, _direction) in enumerate(ordering))
    statement = select(*selected).select_from(source).where(*page_conditions)
    non_null_order_fields = {
        order.field.removeprefix("properties.")
        for order in body.order_by
        if _filter_guarantees_non_null(body, order.field)
    }
    for index, (expression, direction) in enumerate(ordering):
        ordered = expression.asc() if direction == "asc" else expression.desc()
        order_field = body.order_by[index].field.removeprefix("properties.") if index < len(body.order_by) else "id"
        statement = statement.order_by(ordered if order_field in non_null_order_fields or order_field == "id" else ordered.nulls_last())
    if legacy_offset:
        statement = statement.offset(legacy_offset)
    page_rows = list(db.execute(statement.limit(body.limit + 1)).mappings())
    has_more = len(page_rows) > body.limit
    page_rows = page_rows[:body.limit]

    total = None
    if body.include_total:
        count_statement = select(func.count()).select_from(source).where(*conditions)
        total = int(db.execute(count_statement).scalar_one())

    aggregates: Dict[str, Any] = {}
    if body.aggregates:
        aggregate_expressions, aggregate_names = _compile_aggregates(db, columns, known_fields, body.aggregates)
        aggregate_row = db.execute(select(*aggregate_expressions).select_from(source).where(*conditions)).mappings().one()
        aggregates = {name: aggregate_row[name] for name in aggregate_names}

    masked_by_type = _masked_fields_for_types(
        db, principal, body.project_id, {body.object_type_id},
    )
    masked_fields = masked_by_type.get(body.object_type_id, set())
    output = []
    for mapped in page_rows:
        row = dict(mapped)
        properties = {
            key: ("***" if key in masked_fields else value)
            for key, value in dict(row.get("properties") or {}).items()
        }
        if body.select:
            properties = {field: properties.get(field.removeprefix("properties.")) for field in body.select if field not in {"id", "created_at", "updated_at"}}
        item = {key: value for key, value in row.items() if not key.startswith("_order_") and key not in {"temporal_event_id", "object_version"}}
        item["properties"] = properties
        if temporal:
            item["lineage"] = {"temporal_event_id": row["temporal_event_id"], "object_version": row["object_version"]}
        if not body.include_lineage:
            item.pop("lineage", None)
        output.append(item)
    next_cursor = None
    if has_more and page_rows:
        last = page_rows[-1]
        next_cursor = _encode_sql_cursor([last[f"_order_{index}"] for index in range(len(ordering))], query_hash)
    return {
        "api_version": "v1",
        "project_id": body.project_id,
        "object_type_id": body.object_type_id,
        "count": len(output),
        "total": total,
        "objects": output,
        "next_cursor": next_cursor,
        "aggregates": aggregates,
        "query_plan": {
            "engine": "sqlalchemy+typed-sql",
            "project_scope": True,
            "temporal": temporal,
            "spatial": body.spatial is not None,
            "filter_pushdown": len(body.filters),
            "aggregate_pushdown": len(body.aggregates),
            "pagination": "keyset" if cursor_keys is not None or not legacy_offset else "legacy-offset",
            "indexed_fields": sorted(row.property_name for row in active_indexes),
            "planned_index_fields": sorted(row.property_name for row in definitions if row.indexed),
            "masked_fields": sorted(masked_fields),
        },
    }


@router.post("/graph/query")
def query_graph(body: TypedGraphQuery, principal: Principal = Depends(require_permission("view")), db: Session = Depends(get_db)):
    tenancy.assert_project_permission(db, principal, body.project_id, "view")
    seeds = db.query(models.ObjectInstance).filter(
        models.ObjectInstance.project_id == body.project_id,
        models.ObjectInstance.id.in_(body.seed_object_ids),
    )
    if not body.include_inactive:
        seeds = seeds.filter(models.ObjectInstance.is_active.is_(True))
    seeds = seeds.all()
    missing = set(body.seed_object_ids) - {row.id for row in seeds}
    if missing:
        raise HTTPException(status_code=404, detail={"message": "Seed objects not found", "object_ids": sorted(missing)})
    nodes: Dict[str, models.ObjectInstance] = {row.id: row for row in seeds}
    edges: Dict[str, models.LinkInstance] = {}
    frontier = set(nodes)
    query_batches = 1
    edge_truncated = False
    for _depth in range(body.depth):
        if not frontier or len(nodes) >= body.max_nodes or len(edges) >= body.max_edges:
            break
        query = db.query(models.LinkInstance).filter(models.LinkInstance.project_id == body.project_id)
        if body.link_type_ids:
            query = query.filter(models.LinkInstance.link_type_id.in_(body.link_type_ids))
        if edges:
            query = query.filter(~models.LinkInstance.id.in_(edges))
        if body.direction == "outgoing":
            query = query.filter(models.LinkInstance.source_object_id.in_(frontier))
        elif body.direction == "incoming":
            query = query.filter(models.LinkInstance.target_object_id.in_(frontier))
        else:
            query = query.filter((models.LinkInstance.source_object_id.in_(frontier)) | (models.LinkInstance.target_object_id.in_(frontier)))
        remaining_edges = body.max_edges - len(edges)
        link_rows = query.order_by(models.LinkInstance.id).limit(remaining_edges + 1).all()
        query_batches += 1
        if len(link_rows) > remaining_edges:
            edge_truncated = True
            link_rows = link_rows[:remaining_edges]
        candidate_ids = {
            object_id
            for link in link_rows
            for object_id in (link.source_object_id, link.target_object_id)
            if object_id not in nodes
        }
        candidate_rows: List[models.ObjectInstance] = []
        if candidate_ids:
            candidate_query = db.query(models.ObjectInstance).filter(
                models.ObjectInstance.project_id == body.project_id,
                models.ObjectInstance.id.in_(candidate_ids),
            )
            if body.object_type_ids:
                candidate_query = candidate_query.filter(models.ObjectInstance.object_type_id.in_(body.object_type_ids))
            if not body.include_inactive:
                candidate_query = candidate_query.filter(models.ObjectInstance.is_active.is_(True))
            candidate_rows = candidate_query.order_by(models.ObjectInstance.id).limit(max(0, body.max_nodes - len(nodes))).all()
            query_batches += 1
        next_frontier = {row.id for row in candidate_rows}
        nodes.update({row.id: row for row in candidate_rows})
        for link in link_rows:
            if link.source_object_id in nodes and link.target_object_id in nodes:
                edges[link.id] = link
        frontier = next_frontier
    masked_by_type = _masked_fields_for_types(db, principal, body.project_id, {row.object_type_id for row in nodes.values()})
    masked_fields = sorted({f"{object_type_id}.{field}" for object_type_id, fields in masked_by_type.items() for field in fields})

    def node_payload(row: models.ObjectInstance) -> Dict[str, Any]:
        masked = masked_by_type.get(row.object_type_id, set())
        properties = {key: ("***" if key in masked else value) for key, value in (row.properties or {}).items()}
        return {
            "id": row.id, "object_type_id": row.object_type_id, "properties": properties,
            "lineage": row.lineage or {}, "materialization_id": row.materialization_id,
            "is_active": row.is_active, "retired_at": row.retired_at,
        }

    ordered_nodes = sorted(nodes.values(), key=lambda row: row.id)
    ordered_edges = sorted(edges.values(), key=lambda row: row.id)
    return {
        "api_version": "v1",
        "project_id": body.project_id,
        "nodes": [node_payload(row) for row in ordered_nodes],
        "edges": [{"id": row.id, "link_type_id": row.link_type_id, "source": row.source_object_id, "target": row.target_object_id, "properties": row.properties or {}} for row in ordered_edges],
        "summary": {
            "node_count": len(nodes), "edge_count": len(edges), "depth": body.depth,
            "truncated": len(nodes) >= body.max_nodes or edge_truncated,
            "node_limit_reached": len(nodes) >= body.max_nodes,
            "edge_limit_reached": edge_truncated or len(edges) >= body.max_edges,
        },
        "query_plan": {"engine": "sqlalchemy+batched-bfs", "query_batches": query_batches, "n_plus_one": False, "masked_fields": masked_fields},
    }


@router.get("/objects/{object_type_id}/{object_id}/history")
def object_history(object_type_id: str, object_id: str, limit: int = 200, principal: Principal = Depends(require_permission("view")), db: Session = Depends(get_db)):
    obj = semantic_scope.object_for(db, principal, object_id, "view")
    if obj.object_type_id != object_type_id:
        raise HTTPException(status_code=404, detail="Object not found for object type")
    rows = db.query(ObjectChangeEvent).filter(
        ObjectChangeEvent.project_id == obj.project_id,
        ObjectChangeEvent.object_type_id == object_type_id,
        ObjectChangeEvent.object_id == object_id,
    ).order_by(ObjectChangeEvent.object_version.desc()).limit(max(1, min(limit, 1000))).all()
    return {"project_id": obj.project_id, "object_type_id": object_type_id, "object_id": object_id, "current_version": rows[0].object_version if rows else 0, "events": [_event_dict(row) for row in rows]}

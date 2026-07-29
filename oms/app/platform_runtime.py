"""Shared versioned artifacts, editing leases, and asynchronous job evidence."""
from __future__ import annotations

import asyncio
import hashlib
import json
import time
import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import Boolean, Integer, JSON, String, UniqueConstraint, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Mapped, Session, mapped_column

from . import models_action, ops_control, tenancy
from .database import Base, SessionLocal, get_db
from .production_auth import Principal, require_detached_permission, require_permission

router = APIRouter(tags=["platform_runtime"])


def _now() -> int:
    return int(time.time())


def _id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:16]}"


def _locked_artifact_for(
    db: Session,
    artifact_id: str,
    principal: Principal,
    permission: str,
) -> "PlatformArtifact":
    """Authorize and lock an artifact before allocating a new revision."""
    _artifact_for(db, artifact_id, principal, permission)
    if db.get_bind().dialect.name == "sqlite":
        # SQLite ignores SELECT FOR UPDATE. BEGIN IMMEDIATE serializes local
        # writers so autosave and explicit save cannot allocate one revision.
        db.rollback()
        db.execute(text("BEGIN IMMEDIATE"))
        return _artifact_for(db, artifact_id, principal, permission)
    row = db.query(PlatformArtifact).filter(PlatformArtifact.id == artifact_id).with_for_update().first()
    if not row:
        raise HTTPException(status_code=404, detail=f"Artifact '{artifact_id}' not found")
    return row


class PlatformArtifact(Base):
    __tablename__ = "platform_artifacts"

    id: Mapped[str] = mapped_column(String, primary_key=True, index=True)
    project_id: Mapped[str] = mapped_column(String, default="default", index=True)
    artifact_type: Mapped[str] = mapped_column(String, index=True)
    display_name: Mapped[str] = mapped_column(String)
    description: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    status: Mapped[str] = mapped_column(String, default="DRAFT", index=True)
    current_revision: Mapped[int] = mapped_column(Integer, default=1)
    published_revision: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    lock_version: Mapped[int] = mapped_column(Integer, default=1)
    owner: Mapped[str] = mapped_column(String, default="workspace", index=True)
    metadata_: Mapped[dict] = mapped_column("metadata", JSON, default=dict)
    created_at: Mapped[int] = mapped_column(Integer)
    updated_at: Mapped[int] = mapped_column(Integer)


class ArtifactRevision(Base):
    __tablename__ = "platform_artifact_revisions"
    __table_args__ = (UniqueConstraint("artifact_id", "revision", name="uq_artifact_revision"),)

    id: Mapped[str] = mapped_column(String, primary_key=True, index=True)
    artifact_id: Mapped[str] = mapped_column(String, index=True)
    revision: Mapped[int] = mapped_column(Integer)
    state: Mapped[dict] = mapped_column(JSON, default=dict)
    layout: Mapped[dict] = mapped_column(JSON, default=dict)
    validation: Mapped[dict] = mapped_column(JSON, default=dict)
    author: Mapped[str] = mapped_column(String)
    message: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    published: Mapped[bool] = mapped_column(Boolean, default=False)
    restored_from_revision: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    created_at: Mapped[int] = mapped_column(Integer)


class ArtifactLease(Base):
    __tablename__ = "platform_artifact_leases"

    id: Mapped[str] = mapped_column(String, primary_key=True, index=True)
    artifact_id: Mapped[str] = mapped_column(String, unique=True, index=True)
    holder: Mapped[str] = mapped_column(String, index=True)
    token: Mapped[str] = mapped_column(String, unique=True, index=True)
    created_at: Mapped[int] = mapped_column(Integer)
    updated_at: Mapped[int] = mapped_column(Integer)
    expires_at: Mapped[int] = mapped_column(Integer, index=True)


class ArtifactCollaborationParticipant(Base):
    __tablename__ = "platform_artifact_collaborators"
    __table_args__ = (UniqueConstraint("artifact_id", "principal_id", "client_id", name="uq_artifact_collaborator_client"),)

    id: Mapped[str] = mapped_column(String, primary_key=True, index=True)
    artifact_id: Mapped[str] = mapped_column(String, index=True)
    principal_id: Mapped[str] = mapped_column(String, index=True)
    display_name: Mapped[str] = mapped_column(String)
    client_id: Mapped[str] = mapped_column(String, index=True)
    token: Mapped[str] = mapped_column(String, unique=True, index=True)
    color: Mapped[str] = mapped_column(String)
    cursor: Mapped[dict] = mapped_column(JSON, default=dict)
    selection: Mapped[list] = mapped_column(JSON, default=list)
    joined_at: Mapped[int] = mapped_column(Integer)
    heartbeat_at: Mapped[int] = mapped_column(Integer)
    expires_at: Mapped[int] = mapped_column(Integer, index=True)


class ArtifactCollaborationEvent(Base):
    __tablename__ = "platform_artifact_collaboration_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    artifact_id: Mapped[str] = mapped_column(String, index=True)
    participant_id: Mapped[Optional[str]] = mapped_column(String, nullable=True, index=True)
    actor: Mapped[str] = mapped_column(String, index=True)
    event_type: Mapped[str] = mapped_column(String, index=True)
    lock_version: Mapped[int] = mapped_column(Integer)
    revision: Mapped[int] = mapped_column(Integer)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[int] = mapped_column(Integer, index=True)


class ArtifactCommandReceipt(Base):
    __tablename__ = "platform_artifact_command_receipts"
    __table_args__ = (
        UniqueConstraint("artifact_id", "command_scope", "idempotency_key", name="uq_artifact_command_receipt"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, index=True)
    artifact_id: Mapped[str] = mapped_column(String, index=True)
    project_id: Mapped[str] = mapped_column(String, index=True)
    command_scope: Mapped[str] = mapped_column(String, index=True)
    idempotency_key: Mapped[str] = mapped_column(String)
    request_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    revision: Mapped[int] = mapped_column(Integer)
    lock_version: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    participant_id: Mapped[Optional[str]] = mapped_column(String, nullable=True, index=True)
    command_ids: Mapped[list] = mapped_column(JSON, default=list)
    rebased_from_lock_version: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    created_at: Mapped[int] = mapped_column(Integer, index=True)


class PlatformJob(Base):
    __tablename__ = "platform_jobs"

    id: Mapped[str] = mapped_column(String, primary_key=True, index=True)
    project_id: Mapped[str] = mapped_column(String, default="default", index=True)
    job_type: Mapped[str] = mapped_column(String, index=True)
    status: Mapped[str] = mapped_column(String, default="QUEUED", index=True)
    actor: Mapped[str] = mapped_column(String, index=True)
    subject_type: Mapped[Optional[str]] = mapped_column(String, nullable=True, index=True)
    subject_id: Mapped[Optional[str]] = mapped_column(String, nullable=True, index=True)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    result: Mapped[dict] = mapped_column(JSON, default=dict)
    error: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    attempt: Mapped[int] = mapped_column(Integer, default=1)
    progress: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[int] = mapped_column(Integer)
    updated_at: Mapped[int] = mapped_column(Integer)
    started_at: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    completed_at: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)


class PlatformJobIdempotencyReceipt(Base):
    __tablename__ = "platform_job_idempotency_receipts"

    id: Mapped[str] = mapped_column(String, primary_key=True, index=True)
    scope_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    job_id: Mapped[str] = mapped_column(String, unique=True, index=True)
    project_id: Mapped[str] = mapped_column(String, index=True)
    actor: Mapped[str] = mapped_column(String, index=True)
    job_type: Mapped[str] = mapped_column(String, index=True)
    subject_type: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    subject_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    idempotency_key: Mapped[str] = mapped_column(String)
    request_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    created_at: Mapped[int] = mapped_column(Integer, index=True)


class PlatformJobEvent(Base):
    __tablename__ = "platform_job_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[str] = mapped_column(String, index=True)
    event_type: Mapped[str] = mapped_column(String, index=True)
    status: Mapped[str] = mapped_column(String, index=True)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[int] = mapped_column(Integer, index=True)


class PlatformJobLease(Base):
    __tablename__ = "platform_job_leases"

    id: Mapped[str] = mapped_column(String, primary_key=True, index=True)
    job_id: Mapped[str] = mapped_column(String, unique=True, index=True)
    worker_id: Mapped[str] = mapped_column(String, index=True)
    token: Mapped[str] = mapped_column(String, unique=True, index=True)
    claimed_at: Mapped[int] = mapped_column(Integer)
    heartbeat_at: Mapped[int] = mapped_column(Integer)
    expires_at: Mapped[int] = mapped_column(Integer, index=True)


class ArtifactCreate(BaseModel):
    id: Optional[str] = None
    project_id: str = "default"
    artifact_type: str
    display_name: str
    description: Optional[str] = None
    state: Dict[str, Any] = Field(default_factory=dict)
    layout: Dict[str, Any] = Field(default_factory=dict)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    message: Optional[str] = "Initial draft"


class ArtifactPatch(BaseModel):
    expected_lock_version: int
    display_name: Optional[str] = None
    description: Optional[str] = None
    state: Optional[Dict[str, Any]] = None
    layout: Optional[Dict[str, Any]] = None
    metadata: Optional[Dict[str, Any]] = None
    message: Optional[str] = None
    lease_token: Optional[str] = None


class LeaseRequest(BaseModel):
    ttl_seconds: int = Field(default=120, ge=30, le=900)
    token: Optional[str] = None


class CollaborationJoinRequest(BaseModel):
    client_id: str = Field(min_length=4, max_length=160)
    ttl_seconds: int = Field(default=90, ge=30, le=300)


class CollaborationHeartbeatRequest(BaseModel):
    participant_token: str = Field(min_length=16)
    ttl_seconds: int = Field(default=90, ge=30, le=300)
    cursor: Dict[str, Any] = Field(default_factory=dict)
    selection: List[str] = Field(default_factory=list, max_length=250)


class CollaborationLeaveRequest(BaseModel):
    participant_token: str = Field(min_length=16)


class PublishRequest(BaseModel):
    expected_lock_version: Optional[int] = None
    message: Optional[str] = "Published"


class JobCreate(BaseModel):
    project_id: str = "default"
    job_type: str
    subject_type: Optional[str] = None
    subject_id: Optional[str] = None
    payload: Dict[str, Any] = Field(default_factory=dict)
    priority: int = Field(default=50, ge=0, le=100)
    max_attempts: int = Field(default=3, ge=1, le=20)
    timeout_seconds: int = Field(default=900, ge=1, le=86400)
    available_at: Optional[int] = None
    idempotency_key: Optional[str] = Field(default=None, min_length=1, max_length=200)
    estimated_compute_seconds: float = Field(default=0.0, ge=0)
    estimated_cost_usd: float = Field(default=0.0, ge=0)
    estimated_tokens: float = Field(default=0.0, ge=0)
    estimated_records: float = Field(default=0.0, ge=0)


class JobClaimRequest(BaseModel):
    worker_id: str = Field(min_length=1, max_length=200)
    supported_job_types: List[str] = Field(default_factory=list)
    project_id: Optional[str] = None
    lease_seconds: int = Field(default=60, ge=10, le=900)
    job_id: Optional[str] = None


class JobHeartbeatRequest(BaseModel):
    lease_token: str = Field(min_length=1)
    progress: int = Field(ge=0, le=100)
    message: Optional[str] = Field(default=None, max_length=500)
    metrics: Dict[str, Any] = Field(default_factory=dict)
    lease_seconds: int = Field(default=60, ge=10, le=900)


class JobCompleteRequest(BaseModel):
    lease_token: str = Field(min_length=1)
    result: Dict[str, Any] = Field(default_factory=dict)


class JobFailRequest(BaseModel):
    lease_token: str = Field(min_length=1)
    error: str = Field(min_length=1, max_length=4000)
    retriable: bool = True
    retry_delay_seconds: int = Field(default=0, ge=0, le=86400)
    details: Dict[str, Any] = Field(default_factory=dict)


class ArtifactAdoptRequest(BaseModel):
    resource_type: str
    resource_id: str
    project_id: str = "default"
    display_name: Optional[str] = None


class BuilderCommand(BaseModel):
    command_id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    command: str
    payload: Dict[str, Any] = Field(default_factory=dict)


class BuilderCommandBatch(BaseModel):
    expected_lock_version: int
    commands: List[BuilderCommand] = Field(min_length=1, max_length=100)
    idempotency_key: str = Field(min_length=8, max_length=160)
    lease_token: Optional[str] = None
    message: Optional[str] = "Applied builder commands"


class CollaborationCommandBatch(BaseModel):
    participant_token: str = Field(min_length=16)
    expected_lock_version: int = Field(ge=1)
    commands: List[BuilderCommand] = Field(min_length=1, max_length=100)
    idempotency_key: str = Field(min_length=8, max_length=160)
    message: Optional[str] = "Collaborative visual edit"


class ArtifactPreviewRequest(BaseModel):
    sample_limit: int = Field(default=20, ge=1, le=200)
    inputs: Dict[str, Any] = Field(default_factory=dict)


class OntologyImpactRequest(BaseModel):
    object_type_id: str
    changes: List[Dict[str, Any]] = Field(default_factory=list, max_length=200)


BUILDER_CATALOGS: Dict[str, Dict[str, Any]] = {
    "pipeline": {
        "categories": ["Sources", "Prepare", "Combine", "Spatial", "Intelligence", "Outputs"],
        "nodes": [
            ("dataset_input", "Dataset", "Sources", "Read a versioned data asset", [], ["records"]),
            ("import_input", "Import", "Sources", "Read a validated import job", [], ["records"]),
            ("connector_input", "Connector", "Sources", "Read a connector preview or sync", [], ["records"]),
            ("stream_input", "Stream", "Sources", "Read replayable stream records", [], ["records"]),
            ("ontology_input", "Ontology objects", "Sources", "Read a governed object set", [], ["objects"]),
            ("select", "Select fields", "Prepare", "Choose and reorder fields", ["records"], ["records"]),
            ("rename", "Rename fields", "Prepare", "Rename fields with lineage preserved", ["records"], ["records"]),
            ("cast", "Cast types", "Prepare", "Coerce fields to supported types", ["records"], ["records"]),
            ("formula", "Formula", "Prepare", "Derive a field from a structured expression", ["records"], ["records"]),
            ("null_handling", "Null handling", "Prepare", "Fill, drop, or flag missing values", ["records"], ["records"]),
            ("normalize", "Normalize", "Prepare", "Normalize numeric or categorical values", ["records"], ["records"]),
            ("deduplicate", "Deduplicate", "Prepare", "Keep a deterministic record per key", ["records"], ["records"]),
            ("sort", "Sort", "Prepare", "Sort records by one or more fields", ["records"], ["records"]),
            ("limit", "Limit", "Prepare", "Limit output records", ["records"], ["records"]),
            ("filter", "Filter", "Prepare", "Apply structured field predicates", ["records"], ["records"]),
            ("validate", "Validate", "Prepare", "Evaluate data quality constraints", ["records"], ["valid", "invalid"]),
            ("join", "Join", "Combine", "Join two inputs by typed keys", ["left", "right"], ["records"]),
            ("union", "Union", "Combine", "Combine compatible input schemas", ["inputs"], ["records"]),
            ("aggregate", "Aggregate", "Combine", "Group and aggregate values", ["records"], ["records"]),
            ("pivot", "Pivot", "Combine", "Pivot categorical values into columns", ["records"], ["records"]),
            ("unpivot", "Unpivot", "Combine", "Convert fields into key-value rows", ["records"], ["records"]),
            ("window", "Window", "Combine", "Calculate ordered partition metrics", ["records"], ["records"]),
            ("unique_id", "Unique ID", "Combine", "Generate stable deterministic identifiers", ["records"], ["records"]),
            ("lat_lon", "Latitude / longitude", "Spatial", "Build point geometry", ["records"], ["records"]),
            ("mgrs", "MGRS", "Spatial", "Convert MGRS references to point geometry", ["records"], ["records"]),
            ("geometry", "Geometry", "Spatial", "Parse or construct geometry", ["records"], ["records"]),
            ("radius", "Radius", "Spatial", "Evaluate distance from a point", ["records"], ["records"]),
            ("geofence", "Geofence", "Spatial", "Evaluate polygon containment", ["records"], ["inside", "outside"]),
            ("spatial_join", "Spatial join", "Spatial", "Join records by spatial relation", ["left", "right"], ["records"]),
            ("model_inference", "Model inference", "Intelligence", "Run a governed model deployment", ["records"], ["predictions"]),
            ("aip_generate", "AIP generation", "Intelligence", "Generate governed structured values", ["records"], ["records"]),
            ("dataset_output", "Dataset output", "Outputs", "Write a transactional data asset", ["records"], []),
            ("ontology_output", "Ontology output", "Outputs", "Hydrate mapped ontology objects", ["records"], []),
        ],
        "commands": ["add_node", "update_node", "move_nodes", "duplicate_nodes", "remove_nodes", "add_edge", "remove_edges", "auto_layout", "replace_state"],
    },
    "ontology": {
        "categories": ["Semantic model", "Behavior", "Governance", "Operations"],
        "nodes": [
            ("object_type", "Object type", "Semantic model", "Model a governed business entity", [], ["objects"]),
            ("link_type", "Link type", "Semantic model", "Relate object types with cardinality", ["source", "target"], []),
            ("action_type", "Action type", "Behavior", "Define a governed object mutation", ["object"], ["result"]),
            ("interface", "Interface", "Behavior", "Declare reusable semantic capabilities", [], []),
            ("datasource", "Datasource mapping", "Operations", "Map dataset fields into objects", ["records"], ["objects"]),
            ("object_view", "Object view", "Operations", "Configure a human-facing object view", ["objects"], []),
            ("policy", "Policy", "Governance", "Apply access and approval rules", ["resource"], []),
            ("observability", "Observability", "Operations", "Attach data health and freshness checks", ["resource"], ["status"]),
        ],
        "commands": ["add_node", "update_node", "move_nodes", "duplicate_nodes", "archive_nodes", "remove_nodes", "add_edge", "remove_edges", "reorder_fields", "archive_field", "auto_layout", "replace_state"],
    },
    "workshop": {
        "categories": ["Data", "Visuals", "Interaction", "Intelligence"],
        "nodes": [
            ("object_table", "Object table", "Data", "Browse ontology objects", [], []),
            ("metric", "Metric", "Visuals", "Display an operational KPI", [], []),
            ("chart", "Chart", "Visuals", "Visualize grouped or temporal data", [], []),
            ("map", "Map", "Visuals", "Display geospatial object layers", [], []),
            ("graph", "Graph", "Visuals", "Explore linked objects", [], []),
            ("timeline", "Timeline", "Visuals", "Display object activity over time", [], []),
            ("filter", "Filter", "Interaction", "Control object or dataset filters", [], []),
            ("form", "Form", "Interaction", "Collect typed user input", [], []),
            ("action", "Action", "Interaction", "Run a governed action", [], []),
            ("risk", "Risk panel", "Intelligence", "Explain decision score drivers", [], []),
            ("aip_assist", "AIP Assist", "Intelligence", "Provide contextual recommendations", [], []),
        ],
        "commands": ["add_node", "update_node", "move_nodes", "duplicate_nodes", "archive_nodes", "remove_nodes", "reorder_fields", "auto_layout", "replace_state"],
    },
    "aip_logic": {
        "categories": ["Context", "Logic", "Intelligence", "Operations"],
        "nodes": [
            ("object_query", "Query objects", "Context", "Load typed ontology context", [], ["objects"]),
            ("function", "Function", "Logic", "Run deterministic platform logic", ["input"], ["output"]),
            ("branch", "Branch", "Logic", "Route execution from a condition", ["value"], ["true", "false"]),
            ("model", "Model", "Intelligence", "Invoke a governed deployment", ["records"], ["predictions"]),
            ("risk", "Score risk", "Intelligence", "Evaluate a decision scorecard", ["object"], ["score"]),
            ("scenario", "Run scenario", "Intelligence", "Compare before and after impact", ["seed"], ["impact"]),
            ("alert", "Create alert", "Operations", "Evaluate and stage an alert", ["finding"], ["alert"]),
            ("incident", "Create incident", "Operations", "Open an operational incident", ["alert"], ["incident"]),
            ("runbook", "Run runbook", "Operations", "Execute response steps", ["incident"], ["result"]),
            ("approval", "Request approval", "Operations", "Pause for human review", ["proposal"], ["decision"]),
            ("action", "Propose action", "Operations", "Stage a governed mutation", ["decision"], ["action"]),
        ],
        "commands": ["add_node", "update_node", "move_nodes", "duplicate_nodes", "archive_nodes", "remove_nodes", "add_edge", "remove_edges", "auto_layout", "replace_state"],
    },
}

BUILDER_CONFIGURATION_SCHEMAS: Dict[str, Dict[str, Dict[str, Any]]] = {
    "workshop": {
        "object_table": {"properties": {"object_type_id": {"label": "Object type", "type": "resource", "required": True}, "columns": {"label": "Columns", "type": "field_list"}, "page_size": {"label": "Rows per page", "type": "integer", "default": 25}}},
        "metric": {"properties": {"source": {"label": "Data source", "type": "string", "required": True}, "aggregation": {"label": "Aggregation", "type": "select", "options": ["count", "sum", "avg", "min", "max"]}, "label": {"label": "Display label", "type": "string"}}},
        "chart": {"properties": {"source": {"label": "Data source", "type": "string", "required": True}, "chart_type": {"label": "Chart type", "type": "select", "options": ["bar", "line", "area", "scatter"]}, "category_field": {"label": "Category field", "type": "field"}, "value_field": {"label": "Value field", "type": "field"}}},
        "map": {"properties": {"object_type_id": {"label": "Object type", "type": "resource", "required": True}, "geometry_field": {"label": "Geometry field", "type": "field", "required": True}, "color_field": {"label": "Color field", "type": "field"}, "enable_mgrs": {"label": "Show MGRS", "type": "boolean", "default": True}}},
        "graph": {"properties": {"seed_variable": {"label": "Seed object variable", "type": "string", "required": True}, "depth": {"label": "Traversal depth", "type": "integer", "default": 2}}},
        "timeline": {"properties": {"object_variable": {"label": "Object variable", "type": "string", "required": True}, "timestamp_field": {"label": "Timestamp field", "type": "field"}}},
        "filter": {"properties": {"target_variable": {"label": "Target variable", "type": "string", "required": True}, "property": {"label": "Property", "type": "field", "required": True}, "control": {"label": "Control", "type": "select", "options": ["select", "multi_select", "date_range", "slider", "search"]}}},
        "form": {"properties": {"variable": {"label": "Form variable", "type": "string", "required": True}, "fields": {"label": "Form fields", "type": "field_list", "required": True}, "submit_label": {"label": "Submit label", "type": "string", "default": "Submit"}}},
        "action": {"properties": {"action_type_id": {"label": "Action type", "type": "resource", "required": True}, "object_variable": {"label": "Object variable", "type": "string"}, "approval_mode": {"label": "Approval", "type": "select", "options": ["policy", "always", "never"], "default": "policy"}}},
        "risk": {"properties": {"object_variable": {"label": "Object variable", "type": "string", "required": True}, "scorecard_id": {"label": "Scorecard", "type": "resource"}, "show_drivers": {"label": "Show drivers", "type": "boolean", "default": True}}},
        "aip_assist": {"properties": {"prompt": {"label": "Instruction", "type": "textarea", "required": True}, "context_variables": {"label": "Context variables", "type": "field_list"}, "require_citations": {"label": "Require citations", "type": "boolean", "default": True}}},
    },
    "aip_logic": {
        "object_query": {"properties": {"object_type_id": {"label": "Object type", "type": "resource", "required": True}, "filter_expression": {"label": "Filter expression", "type": "textarea"}, "limit": {"label": "Limit", "type": "integer", "default": 100}}},
        "function": {"properties": {"function_id": {"label": "Function", "type": "resource", "required": True}, "timeout_seconds": {"label": "Timeout", "type": "integer", "default": 30}, "retries": {"label": "Retries", "type": "integer", "default": 1}}},
        "branch": {"properties": {"expression": {"label": "Condition", "type": "textarea", "required": True}, "true_label": {"label": "True branch", "type": "string", "default": "true"}, "false_label": {"label": "False branch", "type": "string", "default": "false"}}},
        "model": {"properties": {"deployment_id": {"label": "Model deployment", "type": "resource", "required": True}, "input_variable": {"label": "Input variable", "type": "string", "required": True}, "output_variable": {"label": "Output variable", "type": "string", "required": True}}},
        "risk": {"properties": {"object_variable": {"label": "Object variable", "type": "string", "required": True}, "scorecard_id": {"label": "Scorecard", "type": "resource"}, "output_variable": {"label": "Output variable", "type": "string", "default": "risk"}}},
        "scenario": {"properties": {"seed_variable": {"label": "Seed variable", "type": "string", "required": True}, "overrides_variable": {"label": "Overrides variable", "type": "string"}, "propagation_depth": {"label": "Propagation depth", "type": "integer", "default": 2}}},
        "alert": {"properties": {"title_template": {"label": "Alert title", "type": "string", "required": True}, "severity": {"label": "Severity", "type": "select", "options": ["low", "medium", "high", "critical"]}, "condition": {"label": "Condition", "type": "textarea", "required": True}}},
        "incident": {"properties": {"title_template": {"label": "Incident title", "type": "string", "required": True}, "severity_variable": {"label": "Severity variable", "type": "string"}, "link_object_variable": {"label": "Linked object variable", "type": "string"}}},
        "runbook": {"properties": {"runbook_id": {"label": "Runbook", "type": "resource", "required": True}, "incident_variable": {"label": "Incident variable", "type": "string"}, "stop_on_failure": {"label": "Stop on failure", "type": "boolean", "default": True}}},
        "approval": {"properties": {"proposal_variable": {"label": "Proposal variable", "type": "string", "required": True}, "risk_threshold": {"label": "Risk threshold", "type": "number", "default": 0.7}, "approver_role": {"label": "Approver role", "type": "string", "default": "approver"}}},
        "action": {"properties": {"action_type_id": {"label": "Action type", "type": "resource", "required": True}, "parameters_variable": {"label": "Parameters variable", "type": "string", "required": True}, "require_approval": {"label": "Require approval", "type": "boolean", "default": True}}},
    },
}


def _catalog(artifact_type: str) -> Dict[str, Any]:
    raw = BUILDER_CATALOGS.get(artifact_type)
    if not raw:
        raise HTTPException(status_code=404, detail=f"Builder catalog '{artifact_type}' not found")
    nodes = [{
        "type": item[0], "label": item[1], "category": item[2], "description": item[3],
        "inputs": [{"id": port, "label": port, "data_type": "records"} for port in item[4]],
        "outputs": [{"id": port, "label": port, "data_type": "records"} for port in item[5]],
        "configuration_schema": {"type": "object", **BUILDER_CONFIGURATION_SCHEMAS.get(artifact_type, {}).get(item[0], {"properties": {}})},
    } for item in raw["nodes"]]
    return {"artifact_type": artifact_type, "categories": raw["categories"], "nodes": nodes, "commands": raw["commands"], "version": 1}


def _audit(db: Session, actor: str, event_type: str, subject_type: str, subject_id: str, payload: Dict[str, Any]) -> None:
    db.add(models_action.AuditLog(
        id=uuid.uuid4().hex,
        actor=actor,
        event_type=event_type,
        subject_type=subject_type,
        subject_id=subject_id,
        payload=payload,
    ))
    db.add(ops_control.OpsEvent(
        id=_id("event"),
        source="platform_runtime",
        event_type=event_type,
        severity="info",
        status="OPEN",
        title=event_type.replace(".", " ").title(),
        subject_type=subject_type,
        subject_id=subject_id,
        payload=payload,
        created_at=_now(),
    ))


def _artifact(db: Session, artifact_id: str) -> PlatformArtifact:
    row = db.get(PlatformArtifact, artifact_id)
    if not row:
        raise HTTPException(status_code=404, detail=f"Artifact '{artifact_id}' not found")
    return row


def _artifact_for(db: Session, artifact_id: str, principal: Principal, permission: str) -> PlatformArtifact:
    row = _artifact(db, artifact_id)
    tenancy.assert_project_permission(db, principal, row.project_id, permission)
    return row


def _collaboration_event(
    db: Session,
    row: PlatformArtifact,
    event_type: str,
    *,
    actor: str,
    participant_id: Optional[str] = None,
    payload: Optional[Dict[str, Any]] = None,
) -> ArtifactCollaborationEvent:
    event = ArtifactCollaborationEvent(
        artifact_id=row.id,
        participant_id=participant_id,
        actor=actor,
        event_type=event_type,
        lock_version=row.lock_version,
        revision=row.current_revision,
        payload=payload or {},
        created_at=_now(),
    )
    db.add(event)
    return event


def _participant_dict(row: ArtifactCollaborationParticipant) -> Dict[str, Any]:
    return {
        "id": row.id,
        "artifact_id": row.artifact_id,
        "principal_id": row.principal_id,
        "display_name": row.display_name,
        "client_id": row.client_id,
        "color": row.color,
        "cursor": row.cursor or {},
        "selection": row.selection or [],
        "joined_at": row.joined_at,
        "heartbeat_at": row.heartbeat_at,
        "expires_at": row.expires_at,
    }


def _event_dict(row: ArtifactCollaborationEvent) -> Dict[str, Any]:
    return {
        "id": row.id,
        "artifact_id": row.artifact_id,
        "participant_id": row.participant_id,
        "actor": row.actor,
        "event_type": row.event_type,
        "lock_version": row.lock_version,
        "revision": row.revision,
        "payload": row.payload or {},
        "created_at": row.created_at,
    }


def _prune_collaborators(db: Session, row: PlatformArtifact) -> int:
    cutoff = _now()
    expired = db.query(ArtifactCollaborationParticipant).filter(
        ArtifactCollaborationParticipant.artifact_id == row.id,
        ArtifactCollaborationParticipant.expires_at <= cutoff,
    ).all()
    removed = 0
    for participant in expired:
        deleted = db.query(ArtifactCollaborationParticipant).filter(
            ArtifactCollaborationParticipant.id == participant.id,
            ArtifactCollaborationParticipant.expires_at <= cutoff,
        ).delete(synchronize_session=False)
        if not deleted:
            continue
        removed += 1
        _collaboration_event(
            db,
            row,
            "presence.left",
            actor=participant.principal_id,
            participant_id=participant.id,
            payload={"reason": "expired", "client_id": participant.client_id},
        )
        db.expunge(participant)
    return removed


def _require_collaborator(
    db: Session,
    artifact_id: str,
    token: str,
    principal: Principal,
) -> ArtifactCollaborationParticipant:
    participant = db.query(ArtifactCollaborationParticipant).filter(
        ArtifactCollaborationParticipant.artifact_id == artifact_id,
        ArtifactCollaborationParticipant.token == token,
    ).first()
    if not participant:
        raise HTTPException(status_code=401, detail="Collaboration participant token is invalid")
    if participant.principal_id != principal.id:
        raise HTTPException(status_code=403, detail="Collaboration participant belongs to another principal")
    if participant.expires_at <= _now():
        db.delete(participant)
        db.commit()
        raise HTTPException(status_code=410, detail="Collaboration participant session expired")
    return participant


def _command_targets(command: BuilderCommand) -> set[str]:
    payload = command.payload or {}
    name = command.command
    if name == "replace_state":
        return {"artifact:*"}
    if name == "add_node":
        node = payload.get("node") or {}
        return {f"node:{node.get('id', '*')}"}
    if name == "update_node":
        return {f"node:{payload.get('node_id', '*')}"}
    if name == "move_nodes":
        return {f"node:{node_id}" for node_id in (payload.get("positions") or {})}
    if name in {"remove_nodes", "archive_nodes", "duplicate_nodes"}:
        return {f"node:{node_id}" for node_id in (payload.get("node_ids") or [])}
    if name == "add_edge":
        edge = payload.get("edge") or {}
        edge_key = edge.get("id") or f"{edge.get('source', '*')}:{edge.get('target', '*')}"
        return {f"edge:{edge_key}"}
    if name == "remove_edges":
        return {f"edge:{edge_id}" for edge_id in (payload.get("edge_ids") or [])}
    if name == "auto_layout":
        return {"layout:*"}
    if name in {"reorder_fields", "archive_field"}:
        node_id = payload.get("node_id", "*")
        field_id = payload.get("field_id", "*")
        return {f"field:{node_id}:{field_id}"}
    return {"artifact:*"}


def _targets_conflict(incoming: set[str], concurrent: set[str]) -> bool:
    if not incoming or not concurrent:
        return False
    if "artifact:*" in incoming or "artifact:*" in concurrent:
        return True
    if "layout:*" in incoming and any(value.startswith("node:") or value == "layout:*" for value in concurrent):
        return True
    if "layout:*" in concurrent and any(value.startswith("node:") or value == "layout:*" for value in incoming):
        return True
    if incoming & concurrent:
        return True
    incoming_nodes = {value.split(":", 2)[1] for value in incoming if value.startswith("field:")}
    concurrent_nodes = {value.split(":", 2)[1] for value in concurrent if value.startswith("field:")}
    return bool(
        incoming_nodes & {value.split(":", 1)[1] for value in concurrent if value.startswith("node:")}
        or concurrent_nodes & {value.split(":", 1)[1] for value in incoming if value.startswith("node:")}
    )


def _revision(db: Session, artifact_id: str, revision: int) -> ArtifactRevision:
    row = db.query(ArtifactRevision).filter(
        ArtifactRevision.artifact_id == artifact_id,
        ArtifactRevision.revision == revision,
    ).first()
    if not row:
        raise HTTPException(status_code=404, detail=f"Revision {revision} not found")
    return row


def _validate_state(artifact_type: str, state: Dict[str, Any]) -> Dict[str, Any]:
    errors: List[Dict[str, Any]] = []
    warnings: List[Dict[str, Any]] = []
    if not isinstance(state, dict):
        errors.append({"path": "/state", "message": "Artifact state must be an object"})
    if artifact_type in {"pipeline", "aip_logic", "investigation_graph", "platform_graph", "entity_resolution"}:
        nodes = state.get("nodes", []) if isinstance(state, dict) else []
        edges = state.get("edges", []) if isinstance(state, dict) else []
        ids = [item.get("id") for item in nodes if isinstance(item, dict)]
        if len(ids) != len(set(ids)):
            errors.append({"path": "/state/nodes", "message": "Node IDs must be unique"})
        known = set(ids)
        schema_catalog = BUILDER_CONFIGURATION_SCHEMAS.get(artifact_type, {})
        for index, node in enumerate(nodes):
            data = node.get("data") if isinstance(node, dict) else {}
            if not isinstance(data, dict) or not data.get("configurationSchemaVersion"):
                continue
            node_type = str(data.get("nodeType") or node.get("type") or "")
            schema = schema_catalog.get(node_type, {})
            values = {str(field.get("name")): field.get("value") for field in data.get("fields", []) if isinstance(field, dict)}
            for field_name, definition in schema.get("properties", {}).items():
                if definition.get("required") and (values.get(field_name) is None or values.get(field_name) == ""):
                    errors.append({"path": f"/state/nodes/{index}/fields/{field_name}", "target_id": str(node.get("id")), "message": f"{definition.get('label', field_name)} is required"})
        for index, edge in enumerate(edges):
            if not isinstance(edge, dict) or edge.get("source") not in known or edge.get("target") not in known:
                errors.append({"path": f"/state/edges/{index}", "message": "Edge references an unknown node"})
        if not nodes:
            warnings.append({"path": "/state/nodes", "message": "The canvas has no nodes"})
    if artifact_type == "ontology":
        object_types = state.get("object_types", []) if isinstance(state, dict) else []
        if not object_types:
            warnings.append({"path": "/state/object_types", "message": "The ontology has no object types"})
    if artifact_type == "workshop" and not state.get("widgets") and not state.get("nodes"):
        warnings.append({"path": "/state/widgets", "message": "The application has no widgets"})
    targets = [
        {
            "target_type": "node" if "/nodes/" in str(item.get("path")) else "field" if "/fields/" in str(item.get("path")) else "artifact",
            "target_id": str(item.get("target_id") or item.get("path") or "/state"),
            "severity": severity,
            "message": item.get("message", "Validation issue"),
            "path": item.get("path", "/state"),
        }
        for severity, collection in (("error", errors), ("warning", warnings))
        for item in collection
    ]
    return {"status": "FAIL" if errors else ("WARN" if warnings else "PASS"), "errors": errors, "warnings": warnings, "targets": targets}


def _artifact_dict(db: Session, row: PlatformArtifact, principal: Optional[Principal] = None) -> Dict[str, Any]:
    revision = _revision(db, row.id, row.current_revision)
    lease = db.query(ArtifactLease).filter(ArtifactLease.artifact_id == row.id).first()
    if lease and lease.expires_at <= _now():
        db.delete(lease)
        lease = None
    last_job = db.query(PlatformJob).filter(
        PlatformJob.subject_type == "artifact", PlatformJob.subject_id == row.id,
    ).order_by(PlatformJob.updated_at.desc()).first()
    active_collaborators = db.query(ArtifactCollaborationParticipant).filter(
        ArtifactCollaborationParticipant.artifact_id == row.id,
        ArtifactCollaborationParticipant.expires_at > _now(),
    ).count()
    latest_collaboration_event = db.query(ArtifactCollaborationEvent.id).filter(
        ArtifactCollaborationEvent.artifact_id == row.id,
    ).order_by(ArtifactCollaborationEvent.id.desc()).first()
    project_allowed = tenancy.project_permissions(db, principal, row.project_id) if principal else {"*"}
    allowed = [
        name for name in ("view", "edit", "publish", "deploy", "execute", "approve", "export", "restore", "administer")
        if (not principal or principal.allows(name)) and ("*" in project_allowed or name in project_allowed)
    ]
    validation = revision.validation or {}
    return {
        "id": row.id,
        "project_id": row.project_id,
        "artifact_type": row.artifact_type,
        "display_name": row.display_name,
        "description": row.description,
        "status": row.status,
        "current_revision": row.current_revision,
        "published_revision": row.published_revision,
        "lock_version": row.lock_version,
        "owner": row.owner,
        "metadata": row.metadata_ or {},
        "state": revision.state or {},
        "layout": revision.layout or {},
        "validation": validation,
        "validation_targets": validation.get("targets", []),
        "lease": None if not lease else {"holder": lease.holder, "expires_at": lease.expires_at},
        "permissions": allowed,
        "dirty_revision": row.current_revision if row.current_revision != row.published_revision else None,
        "execution": None if not last_job else _job_dict(last_job),
        "collaboration": {
            "active_participants": active_collaborators,
            "event_cursor": latest_collaboration_event[0] if latest_collaboration_event else 0,
            "stream_href": f"/artifacts/{row.id}/collaboration/stream",
        },
        "evidence_links": [
            {"type": "revision", "label": f"Revision {row.current_revision}", "href": f"/artifacts/{row.id}/versions"},
            {"type": "audit", "label": "Audit evidence", "href": "/audit-logs/search?subject_type=artifact"},
            {"type": "events", "label": "Operational events", "href": f"/ops/events?subject_type=artifact&subject_id={row.id}"},
        ],
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


def _node_id(node: Dict[str, Any]) -> str:
    value = str(node.get("id") or "").strip()
    if not value:
        raise HTTPException(status_code=422, detail="Builder nodes require an id")
    return value


def _apply_builder_commands(state: Dict[str, Any], layout: Dict[str, Any], commands: List[BuilderCommand]) -> tuple[Dict[str, Any], Dict[str, Any], List[Dict[str, Any]]]:
    next_state = copy_json(state or {})
    next_layout = copy_json(layout or {})
    nodes = list(next_state.get("nodes") or [])
    edges = list(next_state.get("edges") or [])
    applied: List[Dict[str, Any]] = []

    def find_node(node_id: str) -> Dict[str, Any]:
        node = next((item for item in nodes if str(item.get("id")) == node_id), None)
        if not node:
            raise HTTPException(status_code=422, detail=f"Builder node '{node_id}' not found")
        return node

    for item in commands:
        command = item.command
        payload = copy_json(item.payload or {})
        if command == "replace_state":
            replacement = payload.get("state")
            if not isinstance(replacement, dict):
                raise HTTPException(status_code=422, detail="replace_state requires a state object")
            next_state = replacement
            nodes = list(next_state.get("nodes") or [])
            edges = list(next_state.get("edges") or [])
            next_layout = copy_json(payload.get("layout") or {str(node.get("id")): node.get("position", {}) for node in nodes})
        elif command == "add_node":
            node = payload.get("node")
            if not isinstance(node, dict):
                raise HTTPException(status_code=422, detail="add_node requires node")
            node_id = _node_id(node)
            if any(str(existing.get("id")) == node_id for existing in nodes):
                raise HTTPException(status_code=409, detail=f"Builder node '{node_id}' already exists")
            nodes.append(node)
            next_layout[node_id] = copy_json(node.get("position") or payload.get("position") or {"x": 0, "y": 0})
        elif command == "update_node":
            node_id = str(payload.get("node_id") or "")
            node = find_node(node_id)
            changes = payload.get("changes") or {}
            if not isinstance(changes, dict):
                raise HTTPException(status_code=422, detail="update_node changes must be an object")
            node.update(changes)
        elif command == "move_nodes":
            positions = payload.get("positions") or {}
            if not isinstance(positions, dict):
                raise HTTPException(status_code=422, detail="move_nodes positions must be an object")
            for node_id, position in positions.items():
                node = find_node(str(node_id))
                node["position"] = copy_json(position)
                next_layout[str(node_id)] = copy_json(position)
        elif command == "duplicate_nodes":
            source_ids = [str(value) for value in payload.get("node_ids") or []]
            offset = payload.get("offset") or {"x": 32, "y": 32}
            id_map: Dict[str, str] = {}
            for source_id in source_ids:
                source = copy_json(find_node(source_id))
                duplicate_id = str((payload.get("id_map") or {}).get(source_id) or f"{source_id}_copy_{uuid.uuid4().hex[:6]}")
                id_map[source_id] = duplicate_id
                source["id"] = duplicate_id
                position = source.get("position") or next_layout.get(source_id) or {"x": 0, "y": 0}
                source["position"] = {"x": float(position.get("x", 0)) + float(offset.get("x", 32)), "y": float(position.get("y", 0)) + float(offset.get("y", 32))}
                nodes.append(source)
                next_layout[duplicate_id] = source["position"]
            for edge in list(edges):
                if str(edge.get("source")) in id_map and str(edge.get("target")) in id_map:
                    duplicate_edge = copy_json(edge)
                    duplicate_edge["id"] = f"edge_{uuid.uuid4().hex[:10]}"
                    duplicate_edge["source"] = id_map[str(edge.get("source"))]
                    duplicate_edge["target"] = id_map[str(edge.get("target"))]
                    edges.append(duplicate_edge)
            payload["created_ids"] = list(id_map.values())
        elif command in {"remove_nodes", "archive_nodes"}:
            remove_ids = {str(value) for value in payload.get("node_ids") or []}
            if command == "archive_nodes":
                for node_id in remove_ids:
                    find_node(node_id).setdefault("data", {})["archived"] = True
            else:
                nodes = [node for node in nodes if str(node.get("id")) not in remove_ids]
                edges = [edge for edge in edges if str(edge.get("source")) not in remove_ids and str(edge.get("target")) not in remove_ids]
                for node_id in remove_ids:
                    next_layout.pop(node_id, None)
        elif command == "add_edge":
            edge = payload.get("edge")
            if not isinstance(edge, dict):
                raise HTTPException(status_code=422, detail="add_edge requires edge")
            find_node(str(edge.get("source") or ""))
            find_node(str(edge.get("target") or ""))
            edge.setdefault("id", f"edge_{uuid.uuid4().hex[:10]}")
            if any(str(existing.get("id")) == str(edge["id"]) for existing in edges):
                raise HTTPException(status_code=409, detail=f"Builder edge '{edge['id']}' already exists")
            edges.append(edge)
        elif command == "remove_edges":
            remove_ids = {str(value) for value in payload.get("edge_ids") or []}
            edges = [edge for edge in edges if str(edge.get("id")) not in remove_ids]
        elif command == "auto_layout":
            columns = max(1, int(payload.get("columns", 4)))
            for index, node in enumerate(nodes):
                position = {"x": 80 + (index % columns) * 280, "y": 80 + (index // columns) * 160}
                node["position"] = position
                next_layout[str(node.get("id"))] = position
        elif command == "reorder_fields":
            node = find_node(str(payload.get("node_id") or ""))
            fields = list((node.get("data") or {}).get("fields") or [])
            order = [str(value) for value in payload.get("field_ids") or []]
            by_id = {str(field.get("id")): field for field in fields}
            if set(order) != set(by_id):
                raise HTTPException(status_code=422, detail="field_ids must contain each field exactly once")
            node.setdefault("data", {})["fields"] = [by_id[field_id] for field_id in order]
        elif command == "archive_field":
            node = find_node(str(payload.get("node_id") or ""))
            field_id = str(payload.get("field_id") or "")
            field = next((value for value in (node.get("data") or {}).get("fields") or [] if str(value.get("id")) == field_id), None)
            if not field:
                raise HTTPException(status_code=422, detail=f"Field '{field_id}' not found")
            field["archived"] = True
        else:
            raise HTTPException(status_code=422, detail=f"Unsupported builder command '{command}'")
        applied.append({"command_id": item.command_id, "command": command, "payload": payload})

    next_state["nodes"] = nodes
    next_state["edges"] = edges
    return next_state, next_layout, applied


def _assert_lease(db: Session, artifact_id: str, actor: str, token: Optional[str]) -> None:
    lease = db.query(ArtifactLease).filter(ArtifactLease.artifact_id == artifact_id).first()
    if not lease or lease.expires_at <= _now():
        if lease:
            db.delete(lease)
        return
    if lease.holder != actor or not token or token != lease.token:
        raise HTTPException(status_code=423, detail={"message": "Artifact is being edited", "holder": lease.holder, "expires_at": lease.expires_at})


@router.post("/artifacts", status_code=201)
def create_artifact(body: ArtifactCreate, principal: Principal = Depends(require_permission("edit")), db: Session = Depends(get_db)):
    tenancy.assert_project_permission(db, principal, body.project_id, "edit")
    artifact_id = body.id or _id("artifact")
    if db.get(PlatformArtifact, artifact_id):
        raise HTTPException(status_code=409, detail="Artifact already exists")
    if body.artifact_type not in {"pipeline", "ontology", "workshop", "aip_logic", "investigation_graph", "platform_graph", "entity_resolution"}:
        raise HTTPException(status_code=422, detail="Unsupported artifact type")
    now = _now()
    validation = _validate_state(body.artifact_type, body.state)
    row = PlatformArtifact(
        id=artifact_id, project_id=body.project_id, artifact_type=body.artifact_type,
        display_name=body.display_name.strip(), description=body.description, owner=principal.id,
        metadata_=body.metadata, current_revision=1, lock_version=1,
        created_at=now, updated_at=now,
    )
    db.add(row)
    db.add(ArtifactRevision(
        id=_id("revision"), artifact_id=artifact_id, revision=1, state=body.state,
        layout=body.layout, validation=validation, author=principal.id, message=body.message,
        published=False, created_at=now,
    ))
    _audit(db, principal.id, "artifact.created", "artifact", artifact_id, {"artifact_type": body.artifact_type, "revision": 1})
    _collaboration_event(db, row, "artifact.created", actor=principal.id, payload={"targets": ["artifact:*"], "artifact_type": body.artifact_type})
    db.commit()
    return _artifact_dict(db, row, principal)


@router.get("/builder/catalogs/{artifact_type}")
def builder_catalog(artifact_type: str, principal: Principal = Depends(require_permission("view"))):
    result = _catalog(artifact_type)
    result["permissions"] = [name for name in ("view", "edit", "publish", "execute", "restore") if principal.allows(name)]
    return result


@router.post("/ontology/changes/impact")
def ontology_change_impact(body: OntologyImpactRequest, principal: Principal = Depends(require_permission("view")), db: Session = Depends(get_db)):
    from . import apps, investigations, models, pipeline_builder_ops

    object_type = db.get(models.ObjectType, body.object_type_id)
    if not object_type:
        raise HTTPException(status_code=404, detail=f"Object type '{body.object_type_id}' not found")
    project_id = str(((object_type.properties or {}).get("__manager") or {}).get("project_id") or "default")
    tenancy.assert_project_permission(db, principal, project_id, "view")
    objects = db.query(models.ObjectInstance).filter(models.ObjectInstance.object_type_id == body.object_type_id).count()
    links = db.query(models.LinkType).filter(
        (models.LinkType.source_object_type_id == body.object_type_id) | (models.LinkType.target_object_type_id == body.object_type_id)
    ).all()
    search_tokens = {body.object_type_id}
    pipeline_rows = db.query(pipeline_builder_ops.PipelineBuilderGraph).filter(pipeline_builder_ops.PipelineBuilderGraph.project_id == project_id).all()
    pipelines = [row for row in pipeline_rows if any(token in str(row.nodes or []) or token in str(row.edges or []) for token in search_tokens)]
    workshop_rows = db.query(apps.WorkshopModule).filter(apps.WorkshopModule.project_id == project_id).all()
    workshops = [row for row in workshop_rows if body.object_type_id in str({"layout": row.layout, "widgets": row.widgets, "variables": row.variables})]
    artifact_rows = db.query(PlatformArtifact).filter(PlatformArtifact.project_id == project_id).all()
    dependent_artifacts = [row for row in artifact_rows if body.object_type_id in str(_revision(db, row.id, row.current_revision).state or {})]
    destructive = [change for change in body.changes if str(change.get("operation") or change.get("type") or "").lower() in {"delete", "remove", "archive", "change_type", "change_primary_key"}]
    affected_property_names = [str(change.get("property_name") or change.get("field") or "") for change in destructive]
    populated_values = 0
    if affected_property_names:
        for instance in db.query(models.ObjectInstance).filter(models.ObjectInstance.object_type_id == body.object_type_id).all():
            populated_values += sum(1 for name in affected_property_names if name and name in (instance.properties or {}))
    severity = "HIGH" if destructive and (objects or populated_values) else "MEDIUM" if destructive else "LOW"
    warnings = []
    if populated_values:
        warnings.append({"code": "POPULATED_VALUES", "message": f"{populated_values} existing property values would become schema-orphaned; archive is recommended."})
    if pipelines:
        warnings.append({"code": "PIPELINE_DEPENDENCY", "message": f"{len(pipelines)} pipeline graph(s) reference this object type."})
    report_count = db.query(investigations.InvestigationReport).count()
    return {
        "object_type": {"id": object_type.id, "display_name": object_type.display_name, "project_id": project_id},
        "severity": severity,
        "safe_to_publish": severity != "HIGH",
        "destructive_changes": destructive,
        "summary": {
            "objects": objects, "populated_values": populated_values, "link_types": len(links),
            "pipelines": len(pipelines), "workshops": len(workshops), "artifacts": len(dependent_artifacts),
            "reports_reviewed": report_count,
        },
        "affected": {
            "objects": [{"id": body.object_type_id, "count": objects}],
            "links": [{"id": row.id, "display_name": row.display_name} for row in links],
            "pipelines": [{"id": row.id, "display_name": row.display_name} for row in pipelines],
            "workshops": [{"id": row.id, "display_name": row.display_name} for row in workshops],
            "artifacts": [{"id": row.id, "artifact_type": row.artifact_type, "display_name": row.display_name} for row in dependent_artifacts],
        },
        "warnings": warnings,
        "recommended_action": "Archive affected fields and publish a recoverable revision." if destructive else "Validate mappings and publish the draft.",
        "evidence_links": [{"type": "object_type", "label": object_type.display_name, "href": f"/ui-state/ontology/object-types/{object_type.id}"}],
    }


@router.post("/artifacts/adopt", status_code=201)
def adopt_resource(body: ArtifactAdoptRequest, principal: Principal = Depends(require_permission("edit")), db: Session = Depends(get_db)):
    """Create a versioned visual draft from an existing pipeline or ontology type."""
    from . import models, pipeline_builder_ops

    tenancy.assert_project_permission(db, principal, body.project_id, "edit")
    source_key = f"{body.resource_type}:{body.resource_id}"
    existing = db.query(PlatformArtifact).filter(PlatformArtifact.project_id == body.project_id).all()
    for artifact in existing:
        if (artifact.metadata_ or {}).get("source_key") == source_key:
            return _artifact_dict(db, artifact, principal)

    if body.resource_type == "pipeline_builder_graph":
        graph = db.get(pipeline_builder_ops.PipelineBuilderGraph, body.resource_id)
        if not graph:
            raise HTTPException(status_code=404, detail="Pipeline graph not found")
        if graph.project_id != body.project_id:
            raise HTTPException(status_code=403, detail="Pipeline graph belongs to another project")
        nodes = []
        for index, node in enumerate(graph.nodes or []):
            node_type = pipeline_builder_ops._node_type(node)
            position = pipeline_builder_ops._node_position(node, index)
            nodes.append({
                "id": pipeline_builder_ops._node_id(node, index),
                "position": position,
                "data": {
                    "label": node.get("label") or node_type.replace("_", " ").title(),
                    "description": (pipeline_builder_ops._node_catalog_by_type().get(node_type) or {}).get("description", ""),
                    "nodeType": node_type,
                    "fields": [{"id": f"{index}_{key}", "name": key, "value": str(value)} for key, value in pipeline_builder_ops._config(node).items()],
                },
            })
        state = {"nodes": nodes, "edges": copy_json(graph.edges or [])}
        artifact_type = "pipeline"
        display_name = body.display_name or graph.display_name
        description = graph.description
    elif body.resource_type == "object_type":
        selected = db.get(models.ObjectType, body.resource_id)
        if not selected:
            raise HTTPException(status_code=404, detail="Object type not found")
        object_project = str(((selected.properties or {}).get("__manager") or {}).get("project_id") or "default")
        if object_project != body.project_id:
            raise HTTPException(status_code=403, detail="Object type belongs to another project")
        links = db.query(models.LinkType).filter(
            (models.LinkType.source_object_type_id == selected.id) | (models.LinkType.target_object_type_id == selected.id)
        ).all()
        type_ids = {selected.id} | {link.source_object_type_id for link in links} | {link.target_object_type_id for link in links}
        object_types = [row for row in db.query(models.ObjectType).filter(models.ObjectType.id.in_(type_ids)).all()]
        nodes = [{
            "id": row.id,
            "position": {"x": 120 + index * 260, "y": 180 + (index % 2) * 140},
            "data": {
                "label": row.display_name,
                "description": row.description or "Ontology object type",
                "nodeType": "object_type",
                "fields": [{"id": f"{row.id}_{name}", "name": name, "value": str((spec or {}).get("type", "string")) if isinstance(spec, dict) else str(spec)} for name, spec in (row.properties or {}).items() if not name.startswith("__")],
            },
        } for index, row in enumerate(object_types)]
        state = {
            "nodes": nodes,
            "edges": [{"id": link.id, "source": link.source_object_type_id, "target": link.target_object_type_id, "data": {"label": link.display_name, "cardinality": link.cardinality}} for link in links],
            "object_types": [{"id": row.id, "display_name": row.display_name, "properties": row.properties or {}} for row in object_types],
        }
        artifact_type = "ontology"
        display_name = body.display_name or f"{selected.display_name} ontology"
        description = selected.description
    else:
        raise HTTPException(status_code=422, detail="resource_type must be pipeline_builder_graph or object_type")

    create = ArtifactCreate(
        project_id=body.project_id,
        artifact_type=artifact_type,
        display_name=display_name,
        description=description,
        state=state,
        layout={node["id"]: node["position"] for node in state["nodes"]},
        metadata={"source_key": source_key, "source_type": body.resource_type, "source_id": body.resource_id},
        message="Adopted existing resource",
    )
    return create_artifact(create, principal, db)


def copy_json(value: Any) -> Any:
    import copy
    return copy.deepcopy(value)


def _command_request_hash(commands: List[BuilderCommand]) -> str:
    canonical = [
        {"command": command.command, "payload": command.payload}
        for command in commands
    ]
    encoded = json.dumps(canonical, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _command_receipt_dict(row: ArtifactCommandReceipt) -> Dict[str, Any]:
    return {
        "id": row.id,
        "artifact_id": row.artifact_id,
        "project_id": row.project_id,
        "command_scope": row.command_scope,
        "idempotency_key": row.idempotency_key,
        "request_hash": row.request_hash,
        "revision": row.revision,
        "lock_version": row.lock_version,
        "participant_id": row.participant_id,
        "command_ids": row.command_ids or [],
        "rebased_from_lock_version": row.rebased_from_lock_version,
        "created_at": row.created_at,
    }


def _find_command_receipt(
    db: Session,
    artifact: PlatformArtifact,
    command_scope: str,
    idempotency_key: str,
    request_hash: str,
) -> Optional[ArtifactCommandReceipt]:
    row = db.query(ArtifactCommandReceipt).filter(
        ArtifactCommandReceipt.artifact_id == artifact.id,
        ArtifactCommandReceipt.command_scope == command_scope,
        ArtifactCommandReceipt.idempotency_key == idempotency_key,
    ).first()
    if row is None:
        legacy_key = "collaboration_receipts" if command_scope == "collaboration" else "command_receipts"
        legacy = next(
            (
                receipt
                for receipt in ((artifact.metadata_ or {}).get(legacy_key) or [])
                if receipt.get("idempotency_key") == idempotency_key
            ),
            None,
        )
        if legacy:
            row = ArtifactCommandReceipt(
                id=_id("receipt"),
                artifact_id=artifact.id,
                project_id=artifact.project_id,
                command_scope=command_scope,
                idempotency_key=idempotency_key,
                request_hash=None,
                revision=int(legacy.get("revision") or artifact.current_revision),
                lock_version=legacy.get("lock_version"),
                participant_id=legacy.get("participant_id"),
                command_ids=list(legacy.get("command_ids") or []),
                rebased_from_lock_version=legacy.get("rebased_from_lock_version"),
                created_at=int(legacy.get("created_at") or artifact.updated_at),
            )
            db.add(row)
            db.flush()
    if row is not None and row.request_hash and row.request_hash != request_hash:
        raise HTTPException(
            status_code=409,
            detail={
                "message": "Idempotency key was already used for a different command batch",
                "idempotency_key": idempotency_key,
                "command_scope": command_scope,
                "receipt_id": row.id,
            },
        )
    return row


@router.get("/artifacts")
def list_artifacts(project_id: Optional[str] = None, artifact_type: Optional[str] = None, principal: Principal = Depends(require_permission("view")), db: Session = Depends(get_db)):
    query = db.query(PlatformArtifact)
    if project_id:
        tenancy.assert_project_permission(db, principal, project_id, "view")
        query = query.filter(PlatformArtifact.project_id == project_id)
    else:
        allowed = tenancy.accessible_project_ids(db, principal, "view")
        if allowed is not None:
            query = query.filter(PlatformArtifact.project_id.in_(allowed)) if allowed else query.filter(PlatformArtifact.id == "__none__")
    if artifact_type:
        query = query.filter(PlatformArtifact.artifact_type == artifact_type)
    return [_artifact_dict(db, row, principal) for row in query.order_by(PlatformArtifact.updated_at.desc()).all()]


@router.get("/artifacts/{artifact_id}")
def get_artifact(artifact_id: str, principal: Principal = Depends(require_permission("view")), db: Session = Depends(get_db)):
    return _artifact_dict(db, _artifact_for(db, artifact_id, principal, "view"), principal)


@router.patch("/artifacts/{artifact_id}")
def update_artifact(artifact_id: str, body: ArtifactPatch, principal: Principal = Depends(require_permission("edit")), db: Session = Depends(get_db)):
    row = _locked_artifact_for(db, artifact_id, principal, "edit")
    if body.expected_lock_version != row.lock_version:
        raise HTTPException(status_code=409, detail={"message": "Artifact changed since it was loaded", "current_lock_version": row.lock_version})
    _assert_lease(db, artifact_id, principal.id, body.lease_token)
    current = _revision(db, artifact_id, row.current_revision)
    state = body.state if body.state is not None else dict(current.state or {})
    layout = body.layout if body.layout is not None else dict(current.layout or {})
    validation = _validate_state(row.artifact_type, state)
    row.current_revision += 1
    row.lock_version += 1
    row.updated_at = _now()
    row.status = "DRAFT"
    if body.display_name is not None:
        row.display_name = body.display_name.strip()
    if body.description is not None:
        row.description = body.description
    if body.metadata is not None:
        row.metadata_ = body.metadata
    db.add(ArtifactRevision(
        id=_id("revision"), artifact_id=row.id, revision=row.current_revision, state=state,
        layout=layout, validation=validation, author=principal.id, message=body.message or "Autosaved change",
        published=False, created_at=_now(),
    ))
    _audit(db, principal.id, "artifact.revision.created", "artifact", row.id, {"revision": row.current_revision, "lock_version": row.lock_version})
    _collaboration_event(db, row, "artifact.revision", actor=principal.id, payload={"targets": ["artifact:*"], "message": body.message or "Autosaved change"})
    db.commit()
    return _artifact_dict(db, row, principal)


@router.post("/artifacts/{artifact_id}/commands")
def apply_artifact_commands(artifact_id: str, body: BuilderCommandBatch, principal: Principal = Depends(require_permission("edit")), db: Session = Depends(get_db)):
    row = _locked_artifact_for(db, artifact_id, principal, "edit")
    request_hash = _command_request_hash(body.commands)
    prior = _find_command_receipt(db, row, "builder", body.idempotency_key, request_hash)
    if prior:
        db.commit()
        result = _artifact_dict(db, row, principal)
        result["command_receipt"] = _command_receipt_dict(prior)
        result["idempotent_replay"] = True
        return result
    if body.expected_lock_version != row.lock_version:
        raise HTTPException(status_code=409, detail={"message": "Artifact changed since it was loaded", "current_lock_version": row.lock_version})
    _assert_lease(db, artifact_id, principal.id, body.lease_token)
    current = _revision(db, artifact_id, row.current_revision)
    state, layout, applied = _apply_builder_commands(current.state or {}, current.layout or {}, body.commands)
    validation = _validate_state(row.artifact_type, state)
    row.current_revision += 1
    row.lock_version += 1
    row.updated_at = _now()
    row.status = "DRAFT"
    receipt = ArtifactCommandReceipt(
        id=_id("receipt"),
        artifact_id=row.id,
        project_id=row.project_id,
        command_scope="builder",
        idempotency_key=body.idempotency_key,
        request_hash=request_hash,
        revision=row.current_revision,
        lock_version=row.lock_version,
        participant_id=None,
        command_ids=[item.command_id for item in body.commands],
        rebased_from_lock_version=None,
        created_at=row.updated_at,
    )
    db.add(receipt)
    db.add(ArtifactRevision(
        id=_id("revision"), artifact_id=row.id, revision=row.current_revision, state=state,
        layout=layout, validation=validation, author=principal.id, message=body.message,
        published=False, created_at=row.updated_at,
    ))
    _audit(db, principal.id, "artifact.commands.applied", "artifact", row.id, {
        "revision": row.current_revision, "lock_version": row.lock_version,
        "commands": [{"command_id": item["command_id"], "command": item["command"]} for item in applied],
        "idempotency_key": body.idempotency_key,
    })
    command_targets = sorted({target for command in body.commands for target in _command_targets(command)})
    _collaboration_event(db, row, "artifact.commands", actor=principal.id, payload={
        "targets": command_targets,
        "commands": [{"command_id": item.command_id, "command": item.command} for item in body.commands],
        "message": body.message,
    })
    db.commit()
    result = _artifact_dict(db, row, principal)
    result["command_receipt"] = _command_receipt_dict(receipt)
    result["idempotent_replay"] = False
    return result


@router.post("/artifacts/{artifact_id}/preview", status_code=202)
def preview_artifact(artifact_id: str, body: ArtifactPreviewRequest, principal: Principal = Depends(require_permission("execute")), db: Session = Depends(get_db)):
    row = _artifact_for(db, artifact_id, principal, "execute")
    revision = _revision(db, artifact_id, row.current_revision)
    validation = _validate_state(row.artifact_type, revision.state or {})
    nodes = list((revision.state or {}).get("nodes") or [])
    edges = list((revision.state or {}).get("edges") or [])
    sample = []
    for node in nodes[:body.sample_limit]:
        data = node.get("data") or {}
        sample.append({
            "node_id": node.get("id"), "node_type": data.get("nodeType") or node.get("type") or "node",
            "label": data.get("label") or node.get("id"), "status": "READY",
        })
    now = _now()
    result = {
        "artifact_id": row.id,
        "revision": row.current_revision,
        "schema": [{"name": "node_id", "type": "string"}, {"name": "node_type", "type": "string"}, {"name": "status", "type": "string"}],
        "sample_output": sample,
        "warnings": validation.get("warnings", []),
        "metrics": {"node_count": len(nodes), "edge_count": len(edges), "sample_count": len(sample), "duration_ms": max(1, len(nodes) * 2)},
        "evidence_links": [{"type": "revision", "label": f"Revision {row.current_revision}", "href": f"/artifacts/{row.id}/versions"}],
        "trace": [{
            "sequence": index + 1, "node_id": value.get("node_id"), "status": "SUCCEEDED",
            "inputs": body.inputs, "outputs": {"sampled": True, "node_type": value.get("node_type")},
            **({
                "citations": [{"type": "artifact_revision", "id": f"{row.id}:{row.current_revision}"}],
                "policy_decision": "APPROVAL_REQUIRED" if value.get("node_type") in {"approval", "action"} else "ALLOWED",
                "approval_gate": value.get("node_type") in {"approval", "action"},
                "mutation_evidence": [] if value.get("node_type") != "action" else [{"status": "PROPOSED", "executed": False}],
            } if row.artifact_type == "aip_logic" else {}),
        } for index, value in enumerate(sample)],
    }
    job = PlatformJob(
        id=_id("job"), job_type=f"{row.artifact_type}.preview", status="SUCCEEDED", actor=principal.id,
        subject_type="artifact", subject_id=row.id, payload={"sample_limit": body.sample_limit, "inputs": body.inputs},
        result=result, attempt=1, progress=100, created_at=now, updated_at=now, started_at=now, completed_at=now,
    )
    db.add(job)
    db.flush()
    _job_event(db, job, "job.queued")
    _job_event(db, job, "job.started")
    _job_event(db, job, "job.succeeded", {"metrics": result["metrics"]})
    _audit(db, principal.id, "artifact.preview.completed", "artifact", row.id, {"job_id": job.id, "revision": row.current_revision})
    db.commit()
    return {"job_id": job.id, "status": job.status, **result}


@router.post("/artifacts/{artifact_id}/validate")
def validate_artifact(artifact_id: str, principal: Principal = Depends(require_permission("view")), db: Session = Depends(get_db)):
    row = _locked_artifact_for(db, artifact_id, principal, "view")
    revision = _revision(db, artifact_id, row.current_revision)
    revision.validation = _validate_state(row.artifact_type, revision.state or {})
    db.commit()
    return {"artifact_id": artifact_id, "revision": row.current_revision, **revision.validation}


@router.post("/artifacts/{artifact_id}/publish")
def publish_artifact(artifact_id: str, body: PublishRequest, principal: Principal = Depends(require_permission("publish")), db: Session = Depends(get_db)):
    row = _locked_artifact_for(db, artifact_id, principal, "publish")
    if body.expected_lock_version is not None and body.expected_lock_version != row.lock_version:
        raise HTTPException(status_code=409, detail={"message": "Artifact changed since it was loaded", "current_lock_version": row.lock_version})
    revision = _revision(db, artifact_id, row.current_revision)
    revision.validation = _validate_state(row.artifact_type, revision.state or {})
    if revision.validation.get("status") == "FAIL":
        raise HTTPException(status_code=422, detail={"message": "Artifact validation failed", "validation": revision.validation})
    revision.published = True
    revision.message = body.message or revision.message
    row.published_revision = row.current_revision
    row.status = "PUBLISHED"
    row.lock_version += 1
    row.updated_at = _now()
    _audit(db, principal.id, "artifact.published", "artifact", row.id, {"revision": row.current_revision})
    _collaboration_event(db, row, "artifact.published", actor=principal.id, payload={"targets": ["artifact:*"], "revision": row.current_revision})
    db.commit()
    return _artifact_dict(db, row, principal)


@router.get("/artifacts/{artifact_id}/versions")
def artifact_versions(artifact_id: str, principal: Principal = Depends(require_permission("view")), db: Session = Depends(get_db)):
    _artifact_for(db, artifact_id, principal, "view")
    rows = db.query(ArtifactRevision).filter(ArtifactRevision.artifact_id == artifact_id).order_by(ArtifactRevision.revision.desc()).all()
    return [{
        "id": row.id, "revision": row.revision, "author": row.author, "message": row.message,
        "published": row.published, "restored_from_revision": row.restored_from_revision,
        "validation": row.validation, "created_at": row.created_at,
    } for row in rows]


@router.get("/artifacts/{artifact_id}/diff")
def artifact_diff(artifact_id: str, from_revision: int = Query(...), to_revision: Optional[int] = None, principal: Principal = Depends(require_permission("view")), db: Session = Depends(get_db)):
    row = _artifact_for(db, artifact_id, principal, "view")
    before = _revision(db, artifact_id, from_revision)
    after = _revision(db, artifact_id, to_revision or row.current_revision)
    keys = sorted(set((before.state or {}).keys()) | set((after.state or {}).keys()))
    changed = [{"path": f"/{key}", "before": (before.state or {}).get(key), "after": (after.state or {}).get(key)} for key in keys if (before.state or {}).get(key) != (after.state or {}).get(key)]
    layout_changed = before.layout != after.layout
    return {"artifact_id": artifact_id, "from_revision": before.revision, "to_revision": after.revision, "changed": changed, "layout_changed": layout_changed}


@router.post("/artifacts/{artifact_id}/versions/{version}/restore")
def restore_artifact(artifact_id: str, version: int, principal: Principal = Depends(require_permission("restore")), db: Session = Depends(get_db)):
    row = _locked_artifact_for(db, artifact_id, principal, "restore")
    source = _revision(db, artifact_id, version)
    row.current_revision += 1
    row.lock_version += 1
    row.status = "DRAFT"
    row.updated_at = _now()
    db.add(ArtifactRevision(
        id=_id("revision"), artifact_id=artifact_id, revision=row.current_revision,
        state=source.state, layout=source.layout, validation=source.validation, author=principal.id,
        message=f"Restored revision {version}", published=False, restored_from_revision=version, created_at=_now(),
    ))
    _audit(db, principal.id, "artifact.restored", "artifact", artifact_id, {"source_revision": version, "revision": row.current_revision})
    _collaboration_event(db, row, "artifact.restored", actor=principal.id, payload={"targets": ["artifact:*"], "source_revision": version})
    db.commit()
    return _artifact_dict(db, row, principal)


@router.post("/artifacts/{artifact_id}/leases")
def acquire_lease(artifact_id: str, body: LeaseRequest, principal: Principal = Depends(require_permission("edit")), db: Session = Depends(get_db)):
    _artifact_for(db, artifact_id, principal, "edit")
    lease = db.query(ArtifactLease).filter(ArtifactLease.artifact_id == artifact_id).first()
    now = _now()
    expired = bool(lease and lease.expires_at <= now)
    if lease and not expired and lease.holder != principal.id:
        raise HTTPException(status_code=423, detail={"message": "Artifact is being edited", "holder": lease.holder, "expires_at": lease.expires_at})
    if lease and lease.holder == principal.id and body.token and body.token != lease.token:
        raise HTTPException(status_code=409, detail="Lease token does not match")
    if not lease:
        lease = ArtifactLease(id=_id("lease"), artifact_id=artifact_id, holder=principal.id, token=uuid.uuid4().hex, created_at=now, updated_at=now, expires_at=now + body.ttl_seconds)
        db.add(lease)
    else:
        lease.holder = principal.id
        lease.updated_at = now
        lease.expires_at = now + body.ttl_seconds
        if expired:
            lease.token = uuid.uuid4().hex
    db.commit()
    return {"artifact_id": artifact_id, "holder": lease.holder, "token": lease.token, "expires_at": lease.expires_at}


@router.post("/artifacts/{artifact_id}/collaboration/join")
def join_artifact_collaboration(
    artifact_id: str,
    body: CollaborationJoinRequest,
    principal: Principal = Depends(require_permission("edit")),
    db: Session = Depends(get_db),
):
    row = _artifact_for(db, artifact_id, principal, "edit")
    _prune_collaborators(db, row)
    now = _now()
    participant = db.query(ArtifactCollaborationParticipant).filter(
        ArtifactCollaborationParticipant.artifact_id == artifact_id,
        ArtifactCollaborationParticipant.principal_id == principal.id,
        ArtifactCollaborationParticipant.client_id == body.client_id,
    ).first()
    event_type = "presence.rejoined" if participant else "presence.joined"
    if participant:
        participant.display_name = principal.display_name
        participant.heartbeat_at = now
        participant.expires_at = now + body.ttl_seconds
    else:
        palette = ["#176b8f", "#16815f", "#9a6500", "#a43d5f", "#6956a8", "#3f6f45"]
        participant = ArtifactCollaborationParticipant(
            id=_id("participant"),
            artifact_id=artifact_id,
            principal_id=principal.id,
            display_name=principal.display_name,
            client_id=body.client_id,
            token=uuid.uuid4().hex,
            color=palette[sum(ord(char) for char in f"{principal.id}:{body.client_id}") % len(palette)],
            cursor={},
            selection=[],
            joined_at=now,
            heartbeat_at=now,
            expires_at=now + body.ttl_seconds,
        )
        db.add(participant)
    _collaboration_event(
        db,
        row,
        event_type,
        actor=principal.id,
        participant_id=participant.id,
        payload={"client_id": body.client_id, "display_name": principal.display_name, "color": participant.color},
    )
    db.commit()
    db.refresh(participant)
    latest = db.query(ArtifactCollaborationEvent.id).filter(ArtifactCollaborationEvent.artifact_id == artifact_id).order_by(ArtifactCollaborationEvent.id.desc()).first()
    return {
        "participant": {**_participant_dict(participant), "token": participant.token},
        "participant_token": participant.token,
        "artifact": _artifact_dict(db, row, principal),
        "event_cursor": latest[0] if latest else 0,
    }


@router.get("/artifacts/{artifact_id}/collaboration")
def artifact_collaboration_state(
    artifact_id: str,
    principal: Principal = Depends(require_permission("view")),
    db: Session = Depends(get_db),
):
    row = _artifact_for(db, artifact_id, principal, "view")
    expired = _prune_collaborators(db, row)
    if expired:
        db.commit()
    participants = db.query(ArtifactCollaborationParticipant).filter(
        ArtifactCollaborationParticipant.artifact_id == artifact_id,
        ArtifactCollaborationParticipant.expires_at > _now(),
    ).order_by(ArtifactCollaborationParticipant.joined_at).all()
    latest = db.query(ArtifactCollaborationEvent.id).filter(ArtifactCollaborationEvent.artifact_id == artifact_id).order_by(ArtifactCollaborationEvent.id.desc()).first()
    return {
        "artifact_id": artifact_id,
        "lock_version": row.lock_version,
        "revision": row.current_revision,
        "participants": [_participant_dict(participant) for participant in participants],
        "event_cursor": latest[0] if latest else 0,
        "last_updated": _now(),
    }


@router.post("/artifacts/{artifact_id}/collaboration/heartbeat")
def heartbeat_artifact_collaboration(
    artifact_id: str,
    body: CollaborationHeartbeatRequest,
    principal: Principal = Depends(require_permission("edit")),
    db: Session = Depends(get_db),
):
    row = _artifact_for(db, artifact_id, principal, "edit")
    participant = _require_collaborator(db, artifact_id, body.participant_token, principal)
    participant_id = participant.id
    participant_payload = _participant_dict(participant)
    now = _now()
    selection = [str(value) for value in body.selection]
    expires_at = now + body.ttl_seconds
    updated = db.query(ArtifactCollaborationParticipant).filter(
        ArtifactCollaborationParticipant.id == participant_id,
        ArtifactCollaborationParticipant.principal_id == principal.id,
        ArtifactCollaborationParticipant.expires_at > now,
    ).update({
        ArtifactCollaborationParticipant.cursor: body.cursor,
        ArtifactCollaborationParticipant.selection: selection,
        ArtifactCollaborationParticipant.heartbeat_at: now,
        ArtifactCollaborationParticipant.expires_at: expires_at,
    }, synchronize_session=False)
    if not updated:
        db.rollback()
        raise HTTPException(status_code=410, detail="Collaboration participant session expired")
    _collaboration_event(
        db,
        row,
        "presence.updated",
        actor=principal.id,
        participant_id=participant_id,
        payload={"cursor": body.cursor, "selection": selection},
    )
    db.commit()
    return {
        **participant_payload,
        "cursor": body.cursor,
        "selection": selection,
        "heartbeat_at": now,
        "expires_at": expires_at,
    }


@router.post("/artifacts/{artifact_id}/collaboration/leave")
def leave_artifact_collaboration(
    artifact_id: str,
    body: CollaborationLeaveRequest,
    principal: Principal = Depends(require_permission("edit")),
    db: Session = Depends(get_db),
):
    row = _artifact_for(db, artifact_id, principal, "edit")
    participant = _require_collaborator(db, artifact_id, body.participant_token, principal)
    participant_id = participant.id
    _collaboration_event(
        db,
        row,
        "presence.left",
        actor=principal.id,
        participant_id=participant.id,
        payload={"reason": "left", "client_id": participant.client_id},
    )
    db.delete(participant)
    db.commit()
    return {"artifact_id": artifact_id, "participant_id": participant_id, "status": "LEFT"}


@router.post("/artifacts/{artifact_id}/collaboration/commands")
def apply_collaborative_commands(
    artifact_id: str,
    body: CollaborationCommandBatch,
    principal: Principal = Depends(require_permission("edit")),
    db: Session = Depends(get_db),
):
    row = _locked_artifact_for(db, artifact_id, principal, "edit")
    participant = _require_collaborator(db, artifact_id, body.participant_token, principal)
    request_hash = _command_request_hash(body.commands)
    prior = _find_command_receipt(db, row, "collaboration", body.idempotency_key, request_hash)
    if prior:
        db.commit()
        result = _artifact_dict(db, row, principal)
        result["collaboration_receipt"] = _command_receipt_dict(prior)
        result["idempotent_replay"] = True
        return result
    if body.expected_lock_version > row.lock_version:
        raise HTTPException(status_code=409, detail={"message": "Client revision is newer than the artifact", "current_lock_version": row.lock_version})

    incoming_targets = {target for command in body.commands for target in _command_targets(command)}
    concurrent_events = db.query(ArtifactCollaborationEvent).filter(
        ArtifactCollaborationEvent.artifact_id == artifact_id,
        ArtifactCollaborationEvent.lock_version > body.expected_lock_version,
        ArtifactCollaborationEvent.event_type.in_(["artifact.commands", "artifact.revision", "artifact.published", "artifact.restored"]),
    ).order_by(ArtifactCollaborationEvent.id).all()
    concurrent_targets = {
        str(target)
        for event in concurrent_events
        for target in (event.payload or {}).get("targets", ["artifact:*"])
    }
    if _targets_conflict(incoming_targets, concurrent_targets):
        conflict_payload = {
            "message": "Concurrent edits overlap with this command batch",
            "current_lock_version": row.lock_version,
            "expected_lock_version": body.expected_lock_version,
            "incoming_targets": sorted(incoming_targets),
            "concurrent_targets": sorted(concurrent_targets),
            "conflicting_event_ids": [event.id for event in concurrent_events],
        }
        _collaboration_event(
            db,
            row,
            "artifact.conflict",
            actor=principal.id,
            participant_id=participant.id,
            payload=conflict_payload,
        )
        db.commit()
        raise HTTPException(status_code=409, detail=conflict_payload)

    current = _revision(db, artifact_id, row.current_revision)
    state, layout, applied = _apply_builder_commands(current.state or {}, current.layout or {}, body.commands)
    validation = _validate_state(row.artifact_type, state)
    rebased_from = body.expected_lock_version if body.expected_lock_version < row.lock_version else None
    row.current_revision += 1
    row.lock_version += 1
    row.updated_at = _now()
    row.status = "DRAFT"
    receipt = ArtifactCommandReceipt(
        id=_id("receipt"),
        artifact_id=row.id,
        project_id=row.project_id,
        command_scope="collaboration",
        idempotency_key=body.idempotency_key,
        request_hash=request_hash,
        revision=row.current_revision,
        lock_version=row.lock_version,
        participant_id=participant.id,
        command_ids=[command.command_id for command in body.commands],
        rebased_from_lock_version=rebased_from,
        created_at=row.updated_at,
    )
    db.add(receipt)
    participant.heartbeat_at = row.updated_at
    participant.expires_at = max(participant.expires_at, row.updated_at + 60)
    db.add(ArtifactRevision(
        id=_id("revision"),
        artifact_id=row.id,
        revision=row.current_revision,
        state=state,
        layout=layout,
        validation=validation,
        author=principal.id,
        message=body.message,
        published=False,
        created_at=row.updated_at,
    ))
    _audit(db, principal.id, "artifact.collaboration.commands_applied", "artifact", row.id, {
        "revision": row.current_revision,
        "lock_version": row.lock_version,
        "participant_id": participant.id,
        "rebased_from_lock_version": rebased_from,
        "commands": [{"command_id": item["command_id"], "command": item["command"]} for item in applied],
    })
    _collaboration_event(
        db,
        row,
        "artifact.commands",
        actor=principal.id,
        participant_id=participant.id,
        payload={
            "targets": sorted(incoming_targets),
            "commands": [{"command_id": item.command_id, "command": item.command} for item in body.commands],
            "rebased_from_lock_version": rebased_from,
            "message": body.message,
        },
    )
    db.commit()
    result = _artifact_dict(db, row, principal)
    result["collaboration_receipt"] = _command_receipt_dict(receipt)
    result["idempotent_replay"] = False
    return result


@router.get("/artifacts/{artifact_id}/collaboration/events")
def list_artifact_collaboration_events(
    artifact_id: str,
    after: int = 0,
    limit: int = Query(200, ge=1, le=500),
    principal: Principal = Depends(require_permission("view")),
    db: Session = Depends(get_db),
):
    _artifact_for(db, artifact_id, principal, "view")
    rows = db.query(ArtifactCollaborationEvent).filter(
        ArtifactCollaborationEvent.artifact_id == artifact_id,
        ArtifactCollaborationEvent.id > after,
    ).order_by(ArtifactCollaborationEvent.id).limit(limit).all()
    return {"events": [_event_dict(event) for event in rows], "next_cursor": rows[-1].id if rows else after}


@router.get("/artifacts/{artifact_id}/collaboration/stream")
async def stream_artifact_collaboration_events(
    artifact_id: str,
    request: Request,
    after: int = 0,
    once: bool = False,
    last_event_id: Optional[str] = Header(default=None, alias="Last-Event-ID"),
    principal: Principal = Depends(require_detached_permission("view")),
):
    db = SessionLocal()
    try:
        _artifact_for(db, artifact_id, principal, "view")
    finally:
        db.close()

    resume_cursor = after
    if last_event_id:
        try:
            resume_cursor = max(after, int(last_event_id))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Last-Event-ID must be an integer event cursor") from exc

    async def generate():
        cursor = resume_cursor
        idle_cycles = 0
        while True:
            event_db = SessionLocal()
            try:
                events = event_db.query(ArtifactCollaborationEvent).filter(
                    ArtifactCollaborationEvent.artifact_id == artifact_id,
                    ArtifactCollaborationEvent.id > cursor,
                ).order_by(ArtifactCollaborationEvent.id).limit(100).all()
                serialized_events = [
                    (
                        event.id,
                        event.event_type,
                        json.dumps(_event_dict(event), separators=(",", ":")),
                    )
                    for event in events
                ]
            finally:
                event_db.close()
            for event_id, event_type, event_data in serialized_events:
                cursor = event_id
                yield f"id: {event_id}\nevent: {event_type}\ndata: {event_data}\n\n"
            idle_cycles = 0 if serialized_events else idle_cycles + 1
            if once or await request.is_disconnected():
                break
            if idle_cycles >= 10:
                yield ": keepalive\n\n"
                idle_cycles = 0
            await asyncio.sleep(0.5)

    return StreamingResponse(generate(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


def _job_event(db: Session, row: PlatformJob, event_type: str, payload: Optional[Dict[str, Any]] = None) -> None:
    db.add(PlatformJobEvent(job_id=row.id, event_type=event_type, status=row.status, payload=payload or {}, created_at=_now()))


def _execution(row: PlatformJob) -> Dict[str, Any]:
    return dict((row.payload or {}).get("__execution") or {})


def _set_execution(row: PlatformJob, **changes: Any) -> None:
    payload = dict(row.payload or {})
    execution = dict(payload.get("__execution") or {})
    execution.update(changes)
    payload["__execution"] = execution
    row.payload = payload


def _job_idempotency_scope(body: JobCreate, actor: str) -> str:
    identity = {
        "project_id": body.project_id,
        "actor": actor,
        "job_type": body.job_type,
        "subject_type": body.subject_type,
        "subject_id": body.subject_id,
        "idempotency_key": body.idempotency_key,
    }
    encoded = json.dumps(identity, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _job_request_hash(body: JobCreate) -> str:
    request = body.model_dump(exclude={"idempotency_key"})
    encoded = json.dumps(request, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _job_replay(
    db: Session,
    scope_hash: str,
    request_hash: str,
) -> Optional[Dict[str, Any]]:
    receipt = db.query(PlatformJobIdempotencyReceipt).filter(
        PlatformJobIdempotencyReceipt.scope_hash == scope_hash,
    ).first()
    if not receipt:
        return None
    if receipt.request_hash and receipt.request_hash != request_hash:
        raise HTTPException(
            status_code=409,
            detail={
                "message": "Idempotency key was already used for a different job request",
                "job_id": receipt.job_id,
                "receipt_id": receipt.id,
            },
        )
    row = db.get(PlatformJob, receipt.job_id)
    if not row:
        raise HTTPException(status_code=409, detail="Idempotency receipt references a missing job")
    result = _job_dict(row, db)
    result["idempotent_replay"] = True
    result["idempotency_receipt_id"] = receipt.id
    return result


def _lease_for_job(db: Session, job_id: str) -> Optional[PlatformJobLease]:
    return db.query(PlatformJobLease).filter(PlatformJobLease.job_id == job_id).first()


def _require_job_lease(db: Session, row: PlatformJob, token: str) -> PlatformJobLease:
    lease = _lease_for_job(db, row.id)
    if not lease or lease.token != token:
        raise HTTPException(status_code=409, detail="Job lease is missing or no longer owned by this worker")
    if lease.expires_at <= _now():
        raise HTTPException(status_code=409, detail="Job lease has expired")
    return lease


def _release_job_lease(db: Session, job_id: str) -> None:
    lease = _lease_for_job(db, job_id)
    if lease:
        db.delete(lease)


def _reap_stale_jobs(db: Session) -> int:
    now = _now()
    reaped = 0
    running = db.query(PlatformJob).filter(
        PlatformJob.status == "RUNNING",
    ).with_for_update(skip_locked=True).all()
    for row in running:
        lease = _lease_for_job(db, row.id)
        execution = _execution(row)
        timed_out = bool(row.started_at and row.started_at + int(execution.get("timeout_seconds", 900)) <= now)
        lease_expired = not lease or lease.expires_at <= now
        if not timed_out and not lease_expired:
            continue
        max_attempts = int(execution.get("max_attempts", 3))
        reason = "timeout" if timed_out else "lease_expired"
        prior_worker_id = lease.worker_id if lease else None
        prior_lease_expires_at = lease.expires_at if lease else None
        _release_job_lease(db, row.id)
        row.updated_at = now
        row.error = f"Worker execution {reason.replace('_', ' ')}"
        if row.attempt < max_attempts:
            row.status = "QUEUED"
            row.attempt += 1
            row.progress = 0
            row.started_at = None
            _set_execution(row, available_at=now)
            _job_event(db, row, "job.requeued", {
                "reason": reason, "attempt": row.attempt, "prior_worker_id": prior_worker_id,
                "prior_lease_expires_at": prior_lease_expires_at,
            })
        else:
            row.status = "FAILED"
            row.completed_at = now
            _job_event(db, row, "job.failed", {
                "reason": reason, "attempt": row.attempt, "prior_worker_id": prior_worker_id,
                "prior_lease_expires_at": prior_lease_expires_at,
            })
        from . import runtime_observability
        if row.status == "QUEUED":
            runtime_observability.record_job_recovery(db, row, reason, prior_worker_id)
        else:
            runtime_observability.record_job_terminal(db, row, row.status, {"reason": reason}, row.error)
        evidence = {
            "job_type": row.job_type,
            "project_id": row.project_id,
            "reason": reason,
            "attempt": row.attempt,
            "prior_worker_id": prior_worker_id,
        }
        _audit(db, "system", "job.requeued" if row.status == "QUEUED" else "job.failed", "platform_job", row.id, evidence)
        ops_control.record_ops_event(
            db,
            source="runtime",
            event_type="job.requeued" if row.status == "QUEUED" else "job.retry_exhausted",
            severity="warning" if row.status == "QUEUED" else "error",
            title=f"Job {row.id} {'recovered' if row.status == 'QUEUED' else 'exhausted retries'}",
            message=row.error,
            subject_type="platform_job",
            subject_id=row.id,
            payload=evidence,
        )
        reaped += 1
    return reaped


@router.post("/jobs", status_code=201)
def create_job(body: JobCreate, principal: Principal = Depends(require_permission("execute")), db: Session = Depends(get_db)):
    tenancy.assert_project_permission(db, principal, body.project_id, "execute")
    from . import runtime_observability
    scope_hash = _job_idempotency_scope(body, principal.id) if body.idempotency_key else None
    request_hash = _job_request_hash(body) if body.idempotency_key else None
    if scope_hash and request_hash:
        replay = _job_replay(db, scope_hash, request_hash)
        if replay:
            return replay
    estimates = {
        "compute_seconds": body.estimated_compute_seconds,
        "estimated_cost_usd": body.estimated_cost_usd,
        "token_units": body.estimated_tokens,
        "record_units": body.estimated_records,
    }
    now = _now()
    admission = runtime_observability.check_job_admission(db, body.project_id, estimates)
    payload = dict(body.payload)
    payload["__execution"] = {
        "priority": body.priority,
        "max_attempts": body.max_attempts,
        "timeout_seconds": body.timeout_seconds,
        "available_at": body.available_at or now,
        "idempotency_key": body.idempotency_key,
    }
    row = PlatformJob(id=_id("job"), project_id=body.project_id, job_type=body.job_type, status="QUEUED", actor=principal.id, subject_type=body.subject_type, subject_id=body.subject_id, payload=payload, result={}, attempt=1, progress=0, created_at=now, updated_at=now)
    db.add(row)
    db.flush()
    receipt = None
    if scope_hash and request_hash:
        receipt = PlatformJobIdempotencyReceipt(
            id=_id("jobreceipt"), scope_hash=scope_hash, job_id=row.id,
            project_id=row.project_id, actor=row.actor, job_type=row.job_type,
            subject_type=row.subject_type, subject_id=row.subject_id,
            idempotency_key=str(body.idempotency_key), request_hash=request_hash,
            created_at=now,
        )
        db.add(receipt)
    runtime_observability.record_job_queued(db, row, estimates, admission)
    _job_event(db, row, "job.queued", {"priority": body.priority, "available_at": body.available_at or now})
    _audit(db, principal.id, "job.queued", "platform_job", row.id, {"job_type": row.job_type, "priority": body.priority})
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        if scope_hash and request_hash:
            replay = _job_replay(db, scope_hash, request_hash)
            if replay:
                return replay
        raise
    result = _job_dict(row, db)
    result["idempotent_replay"] = False
    if receipt:
        result["idempotency_receipt_id"] = receipt.id
    return result


def _job_dict(row: PlatformJob, db: Optional[Session] = None) -> Dict[str, Any]:
    result = {column: getattr(row, column) for column in ("id", "project_id", "job_type", "status", "actor", "subject_type", "subject_id", "payload", "result", "error", "attempt", "progress", "created_at", "updated_at", "started_at", "completed_at")}
    result["payload"] = {key: value for key, value in (row.payload or {}).items() if key != "__execution"}
    result["execution"] = _execution(row)
    if db:
        lease = _lease_for_job(db, row.id)
        result["lease"] = None if not lease else {"worker_id": lease.worker_id, "claimed_at": lease.claimed_at, "heartbeat_at": lease.heartbeat_at, "expires_at": lease.expires_at}
    return result


def _authorized_job(db: Session, principal: Principal, job_id: str, permission: str) -> PlatformJob:
    row = db.get(PlatformJob, job_id)
    if not row:
        raise HTTPException(status_code=404, detail="Job not found")
    tenancy.assert_project_permission(db, principal, row.project_id, permission)
    return row


@router.get("/jobs")
def list_jobs(status: Optional[str] = None, job_type: Optional[str] = None, project_id: Optional[str] = None, limit: int = Query(100, ge=1, le=500), principal: Principal = Depends(require_permission("view")), db: Session = Depends(get_db)):
    _reap_stale_jobs(db)
    db.commit()
    query = db.query(PlatformJob)
    if project_id:
        tenancy.assert_project_permission(db, principal, project_id, "view")
        query = query.filter(PlatformJob.project_id == project_id)
    else:
        accessible = tenancy.accessible_project_ids(db, principal)
        if accessible is not None:
            query = query.filter(PlatformJob.project_id.in_(accessible))
    if status:
        query = query.filter(PlatformJob.status == status.upper())
    if job_type:
        query = query.filter(PlatformJob.job_type == job_type)
    return [_job_dict(row, db) for row in query.order_by(PlatformJob.created_at.desc()).limit(limit).all()]


@router.post("/jobs/claim")
def claim_job(body: JobClaimRequest, principal: Principal = Depends(require_permission("execute")), db: Session = Depends(get_db)):
    now = _now()
    _reap_stale_jobs(db)
    from . import worker_control
    constraints = worker_control.worker_claim_constraints(
        db, principal, body.worker_id, body.supported_job_types, body.project_id,
    )
    if not constraints["capacity_available"]:
        db.commit()
        return {"job": None, "reason": "WORKER_CAPACITY"}
    query = db.query(PlatformJob).filter(PlatformJob.status == "QUEUED")
    accessible = tenancy.accessible_project_ids(db, principal, "execute")
    if accessible is not None:
        query = query.filter(PlatformJob.project_id.in_(accessible))
    if constraints["project_id"]:
        tenancy.assert_project_permission(db, principal, constraints["project_id"], "execute")
        query = query.filter(PlatformJob.project_id == constraints["project_id"])
    if body.job_id:
        query = query.filter(PlatformJob.id == body.job_id)
    if constraints["job_types"]:
        query = query.filter(PlatformJob.job_type.in_(constraints["job_types"]))
    candidates = query.order_by(PlatformJob.created_at).limit(250).all()
    candidates = [row for row in candidates if int(_execution(row).get("available_at", row.created_at)) <= now]
    candidates = worker_control.rank_candidates(db, candidates)
    for row in candidates:
        if not worker_control.queue_accepts_claim(db, row.project_id):
            continue
        if _lease_for_job(db, row.id):
            continue
        lease = PlatformJobLease(
            id=_id("joblease"), job_id=row.id, worker_id=body.worker_id, token=uuid.uuid4().hex,
            claimed_at=now, heartbeat_at=now, expires_at=now + body.lease_seconds,
        )
        db.add(lease)
        row.status = "RUNNING"
        row.started_at = row.started_at or now
        row.updated_at = now
        row.error = None
        _job_event(db, row, "job.claimed", {"worker_id": body.worker_id, "attempt": row.attempt, "lease_expires_at": lease.expires_at})
        from . import runtime_observability
        runtime_observability.record_job_progress(db, row, "Worker claimed job", {"worker_id": body.worker_id})
        worker_control.record_worker_claim(constraints["worker"])
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            continue
        result = _job_dict(row, db)
        result["lease_token"] = lease.token
        return {"job": result}
    db.commit()
    return {"job": None, "reason": "NO_COMPATIBLE_WORK"}


@router.get("/jobs/summary")
def job_summary(principal: Principal = Depends(require_permission("view")), db: Session = Depends(get_db)):
    reaped = _reap_stale_jobs(db)
    db.commit()
    query = db.query(PlatformJob)
    accessible = tenancy.accessible_project_ids(db, principal)
    if accessible is not None:
        query = query.filter(PlatformJob.project_id.in_(accessible))
    rows = query.all()
    counts: Dict[str, int] = {}
    by_type: Dict[str, Dict[str, int]] = {}
    for row in rows:
        counts[row.status] = counts.get(row.status, 0) + 1
        type_counts = by_type.setdefault(row.job_type, {})
        type_counts[row.status] = type_counts.get(row.status, 0) + 1
    queued = [row for row in rows if row.status == "QUEUED"]
    now = _now()
    return {
        "counts": counts,
        "by_job_type": by_type,
        "active_workers": len({lease.worker_id for lease in db.query(PlatformJobLease).join(PlatformJob, PlatformJob.id == PlatformJobLease.job_id).filter(PlatformJob.id.in_([row.id for row in rows])).all()}),
        "active_leases": db.query(PlatformJobLease).join(PlatformJob, PlatformJob.id == PlatformJobLease.job_id).filter(PlatformJob.id.in_([row.id for row in rows])).count() if rows else 0,
        "oldest_queued_seconds": max([now - row.created_at for row in queued], default=0),
        "reaped_stale_jobs": reaped,
        "last_updated": now,
    }


@router.post("/jobs/{job_id}/heartbeat")
def heartbeat_job(job_id: str, body: JobHeartbeatRequest, principal: Principal = Depends(require_permission("execute")), db: Session = Depends(get_db)):
    row = _authorized_job(db, principal, job_id, "execute")
    if row.status != "RUNNING":
        raise HTTPException(status_code=409, detail="Job is not running")
    lease = _require_job_lease(db, row, body.lease_token)
    now = _now()
    lease.heartbeat_at = now
    lease.expires_at = now + body.lease_seconds
    row.progress = body.progress
    row.updated_at = now
    _job_event(db, row, "job.progress", {"progress": body.progress, "message": body.message, "metrics": body.metrics})
    from . import runtime_observability
    runtime_observability.record_job_progress(db, row, body.message, body.metrics)
    db.commit()
    return _job_dict(row, db)


@router.post("/jobs/{job_id}/complete")
def complete_job(job_id: str, body: JobCompleteRequest, principal: Principal = Depends(require_permission("execute")), db: Session = Depends(get_db)):
    row = _authorized_job(db, principal, job_id, "execute")
    if row.status != "RUNNING":
        raise HTTPException(status_code=409, detail="Job is not running")
    lease = _require_job_lease(db, row, body.lease_token)
    now = _now()
    row.status = "SUCCEEDED"
    row.progress = 100
    row.result = body.result
    row.error = None
    row.updated_at = row.completed_at = now
    _job_event(db, row, "job.succeeded", {"worker_id": lease.worker_id, "duration_seconds": max(0, now - (row.started_at or now))})
    from . import runtime_observability
    runtime_observability.record_job_terminal(db, row, "SUCCEEDED", body.result)
    _release_job_lease(db, row.id)
    _audit(db, principal.id, "job.succeeded", "platform_job", row.id, {"job_type": row.job_type, "attempt": row.attempt})
    db.commit()
    return _job_dict(row, db)


@router.post("/jobs/{job_id}/fail")
def fail_job(job_id: str, body: JobFailRequest, principal: Principal = Depends(require_permission("execute")), db: Session = Depends(get_db)):
    row = _authorized_job(db, principal, job_id, "execute")
    if row.status != "RUNNING":
        raise HTTPException(status_code=409, detail="Job is not running")
    lease = _require_job_lease(db, row, body.lease_token)
    now = _now()
    max_attempts = int(_execution(row).get("max_attempts", 3))
    row.error = body.error
    row.updated_at = now
    _release_job_lease(db, row.id)
    if body.retriable and row.attempt < max_attempts:
        row.status = "QUEUED"
        row.attempt += 1
        row.progress = 0
        row.started_at = None
        _set_execution(row, available_at=now + body.retry_delay_seconds)
        _job_event(db, row, "job.retry_scheduled", {"worker_id": lease.worker_id, "attempt": row.attempt, "available_at": now + body.retry_delay_seconds, "error": body.error, "details": body.details})
    else:
        row.status = "FAILED"
        row.completed_at = now
        _job_event(db, row, "job.failed", {"worker_id": lease.worker_id, "attempt": row.attempt, "error": body.error, "details": body.details})
    from . import runtime_observability
    runtime_observability.record_job_terminal(db, row, row.status, body.details, body.error)
    _audit(db, principal.id, "job.failed" if row.status == "FAILED" else "job.retry_scheduled", "platform_job", row.id, {"job_type": row.job_type, "attempt": row.attempt})
    db.commit()
    return _job_dict(row, db)


@router.get("/jobs/{job_id}")
def get_job(job_id: str, principal: Principal = Depends(require_permission("view")), db: Session = Depends(get_db)):
    row = _authorized_job(db, principal, job_id, "view")
    _reap_stale_jobs(db)
    db.commit()
    db.refresh(row)
    result = _job_dict(row, db)
    result["events"] = [{"id": event.id, "event_type": event.event_type, "status": event.status, "payload": event.payload, "created_at": event.created_at} for event in db.query(PlatformJobEvent).filter(PlatformJobEvent.job_id == job_id).order_by(PlatformJobEvent.id).all()]
    return result


@router.post("/jobs/{job_id}/cancel")
def cancel_job(job_id: str, principal: Principal = Depends(require_permission("execute")), db: Session = Depends(get_db)):
    row = _authorized_job(db, principal, job_id, "execute")
    if row.status in {"SUCCEEDED", "FAILED", "CANCELLED"}:
        raise HTTPException(status_code=409, detail=f"Job is already {row.status}")
    row.status = "CANCELLED"
    row.updated_at = row.completed_at = _now()
    _release_job_lease(db, row.id)
    _job_event(db, row, "job.cancelled", {"actor": principal.id})
    from . import runtime_observability
    runtime_observability.record_job_terminal(db, row, "CANCELLED", {}, "Cancelled by user")
    _audit(db, principal.id, "job.cancelled", "platform_job", row.id, {})
    db.commit()
    return _job_dict(row, db)


@router.post("/jobs/{job_id}/retry")
def retry_job(job_id: str, principal: Principal = Depends(require_permission("execute")), db: Session = Depends(get_db)):
    row = _authorized_job(db, principal, job_id, "execute")
    if row.status not in {"FAILED", "CANCELLED"}:
        raise HTTPException(status_code=409, detail="Only failed or cancelled jobs can be retried")
    row.status = "QUEUED"
    row.attempt += 1
    row.progress = 0
    row.error = None
    row.result = {}
    row.started_at = row.completed_at = None
    row.updated_at = _now()
    _set_execution(row, available_at=_now())
    _release_job_lease(db, row.id)
    _job_event(db, row, "job.retried", {"attempt": row.attempt, "actor": principal.id})
    from . import runtime_observability
    runtime_observability.record_job_progress(db, row, "Job manually retried", {"attempt": row.attempt})
    _audit(db, principal.id, "job.retried", "platform_job", row.id, {"attempt": row.attempt})
    db.commit()
    return _job_dict(row, db)


@router.get("/events/stream")
async def event_stream(request: Request, after: int = 0, job_id: Optional[str] = None, once: bool = False, principal: Principal = Depends(require_detached_permission("view"))):
    scope_db = SessionLocal()
    try:
        allowed_projects = tenancy.accessible_project_ids(scope_db, principal)
    finally:
        scope_db.close()
    async def generate():
        cursor = after
        idle_cycles = 0
        while True:
            db = SessionLocal()
            try:
                query = db.query(PlatformJobEvent).filter(PlatformJobEvent.id > cursor)
                if job_id:
                    job = _authorized_job(db, principal, job_id, "view")
                    query = query.filter(PlatformJobEvent.job_id == job.id)
                elif allowed_projects is not None:
                    query = query.join(PlatformJob, PlatformJob.id == PlatformJobEvent.job_id).filter(PlatformJob.project_id.in_(allowed_projects))
                events = query.order_by(PlatformJobEvent.id).limit(100).all()
                serialized_events = [
                    (
                        event.id,
                        event.event_type,
                        json_dumps({"id": event.id, "job_id": event.job_id, "event_type": event.event_type, "status": event.status, "payload": event.payload, "created_at": event.created_at}),
                    )
                    for event in events
                ]
            finally:
                db.close()
            for event_id, event_type, event_data in serialized_events:
                cursor = event_id
                yield f"id: {event_id}\nevent: {event_type}\ndata: {event_data}\n\n"
            if once:
                break
            if await request.is_disconnected():
                break
            idle_cycles += 1
            if idle_cycles % 15 == 0:
                yield ": heartbeat\n\n"
            await asyncio.sleep(1)

    return StreamingResponse(generate(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


def json_dumps(value: Dict[str, Any]) -> str:
    import json
    return json.dumps(value, separators=(",", ":"), default=str)

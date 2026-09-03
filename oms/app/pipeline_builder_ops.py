"""
Pipeline Builder graph API.

The base platform already has datasets, pipeline runs, lineage helpers, and
transaction-backed dataset snapshots. This module adds the builder-facing graph
model and deterministic DAG execution used by the local UI.
"""
import copy
import hashlib
import math
import time
import uuid
from collections import defaultdict
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import JSON, Integer, String
from sqlalchemy.orm import Mapped, Session, mapped_column

from . import models, models_action, object_writes, platform_runtime, tenancy
from .database import Base, get_db
from .datasets_ext import DatasetTransaction, _fold, _next_seq, _txns_for
from .production_auth import Principal, require_permission

router = APIRouter(tags=["pipeline_builder"])


NODE_TYPES = {
    "input_dataset",
    "dataset_input",
    "filter",
    "project",
    "select",
    "rename",
    "cast",
    "derive",
    "fill_nulls",
    "normalize",
    "deduplicate",
    "join",
    "union",
    "aggregate",
    "sort",
    "limit",
    "unique_id",
    "pivot",
    "unpivot",
    "window",
    "validate",
    "derive_geo_point",
    "derive_mgrs",
    "spatial_filter",
    "spatial_join",
    "llm_assist",
    "llm",
    "ontology_output",
    "dataset_output",
    "output_dataset",
}

NODE_TYPE_CATALOG = [
    {"type": "input_dataset", "label": "Input Dataset", "category": "input", "description": "Read records from a local DataAsset."},
    {"type": "filter", "label": "Filter", "category": "transform", "description": "Keep rows matching deterministic filter criteria."},
    {"type": "project", "label": "Project / Select", "category": "transform", "description": "Select a subset of columns."},
    {"type": "rename", "label": "Rename", "category": "transform", "description": "Rename one or more fields."},
    {"type": "cast", "label": "Cast Types", "category": "transform", "description": "Coerce selected fields to typed values."},
    {"type": "derive", "label": "Derive / Formula", "category": "transform", "description": "Create fields with safe deterministic formula operations."},
    {"type": "fill_nulls", "label": "Fill Missing", "category": "transform", "description": "Replace missing values with configured defaults."},
    {"type": "normalize", "label": "Normalize", "category": "transform", "description": "Trim and normalize string values."},
    {"type": "deduplicate", "label": "Deduplicate", "category": "transform", "description": "Keep one row for each selected key."},
    {"type": "join", "label": "Join", "category": "transform", "description": "Join two upstream branches or a configured right-hand dataset."},
    {"type": "union", "label": "Union", "category": "transform", "description": "Append rows from another branch or dataset."},
    {"type": "aggregate", "label": "Aggregate", "category": "transform", "description": "Group rows and compute count, sum, avg, min, or max."},
    {"type": "sort", "label": "Sort", "category": "transform", "description": "Sort rows by a field."},
    {"type": "limit", "label": "Limit", "category": "transform", "description": "Keep the first N rows."},
    {"type": "unique_id", "label": "Unique ID", "category": "transform", "description": "Create a stable local identifier from selected fields."},
    {"type": "pivot", "label": "Pivot", "category": "transform", "description": "Turn category values into columns."},
    {"type": "unpivot", "label": "Unpivot", "category": "transform", "description": "Turn selected columns into name/value rows."},
    {"type": "window", "label": "Window", "category": "transform", "description": "Compute row numbers, ranks, and running totals."},
    {"type": "validate", "label": "Validate Rows", "category": "quality", "description": "Apply typed row-level quality rules."},
    {"type": "derive_geo_point", "label": "Latitude / Longitude", "category": "spatial", "description": "Create GeoJSON points from coordinates."},
    {"type": "derive_mgrs", "label": "MGRS", "category": "spatial", "description": "Encode coordinates as MGRS references."},
    {"type": "spatial_filter", "label": "Radius / Geofence", "category": "spatial", "description": "Keep records inside a radius or polygon."},
    {"type": "spatial_join", "label": "Spatial Join", "category": "spatial", "description": "Join branches by geographic distance."},
    {"type": "llm_assist", "label": "LLM Assist", "category": "ai", "description": "Deterministically summarize selected fields as a local LLM analogue."},
    {"type": "ontology_output", "label": "Ontology Output", "category": "output", "description": "Materialize rows into ontology object instances on delivery."},
    {"type": "dataset_output", "label": "Dataset Output", "category": "output", "description": "Write delivered rows to a local output DataAsset."},
]

NODE_CONFIGURATION_SCHEMAS: Dict[str, Dict[str, Any]] = {
    "input_dataset": {"fields": [
        {"name": "asset_id", "label": "Dataset", "type": "resource", "resource_type": "data_asset", "required": True},
    ]},
    "filter": {"fields": [
        {"name": "field", "label": "Field", "type": "field", "required": True},
        {"name": "operator", "label": "Operator", "type": "select", "options": ["eq", "ne", "gt", "gte", "lt", "lte", "contains", "in"], "required": True},
        {"name": "value", "label": "Value", "type": "scalar", "required": True},
    ]},
    "project": {"fields": [{"name": "fields", "label": "Fields", "type": "field_list", "required": True}]},
    "select": {"fields": [{"name": "fields", "label": "Fields", "type": "field_list", "required": True}]},
    "rename": {"fields": [{"name": "mapping", "label": "Rename mapping", "type": "key_value", "required": True}]},
    "cast": {"fields": [
        {"name": "field", "label": "Field", "type": "field", "required": True},
        {"name": "target_type", "label": "Target type", "type": "select", "options": ["string", "integer", "number", "boolean", "timestamp"], "required": True},
    ]},
    "derive": {"fields": [
        {"name": "target_field", "label": "Output field", "type": "string", "required": True},
        {"name": "operation", "label": "Operation", "type": "select", "options": ["copy", "concat", "add", "subtract", "multiply", "divide", "lower", "upper"], "required": True},
        {"name": "source_fields", "label": "Source fields", "type": "field_list", "required": True},
    ]},
    "fill_nulls": {"fields": [
        {"name": "field", "label": "Field", "type": "field", "required": True},
        {"name": "value", "label": "Default value", "type": "string", "required": True},
    ]},
    "normalize": {"fields": [
        {"name": "fields", "label": "Fields", "type": "field_list", "required": True},
        {"name": "mode", "label": "Mode", "type": "select", "options": ["trim", "lower", "upper", "title"], "required": True},
    ]},
    "deduplicate": {"fields": [
        {"name": "keys", "label": "Key fields", "type": "field_list", "required": True},
        {"name": "keep", "label": "Keep", "type": "select", "options": ["first", "last"], "required": True},
    ]},
    "join": {"fields": [
        {"name": "left_key", "label": "Left key", "type": "field", "required": True},
        {"name": "right_key", "label": "Right key", "type": "field", "required": True},
        {"name": "how", "label": "Join type", "type": "select", "options": ["inner", "left"], "required": True},
        {"name": "right_asset_id", "label": "Right dataset", "type": "resource", "resource_type": "data_asset"},
    ]},
    "union": {"fields": [{"name": "asset_id", "label": "Additional dataset", "type": "resource", "resource_type": "data_asset"}]},
    "aggregate": {"fields": [
        {"name": "group_by", "label": "Group fields", "type": "field_list"},
        {"name": "field", "label": "Value field", "type": "field"},
        {"name": "operation", "label": "Aggregation", "type": "select", "options": ["count", "sum", "avg", "min", "max"], "required": True},
        {"name": "target_field", "label": "Output field", "type": "string", "required": True},
    ]},
    "sort": {"fields": [
        {"name": "field", "label": "Sort field", "type": "field", "required": True},
        {"name": "direction", "label": "Direction", "type": "select", "options": ["asc", "desc"], "required": True},
    ]},
    "limit": {"fields": [{"name": "limit", "label": "Row limit", "type": "integer", "required": True, "minimum": 1}]},
    "unique_id": {"fields": [
        {"name": "fields", "label": "Identity fields", "type": "field_list", "required": True},
        {"name": "target_field", "label": "Output field", "type": "string", "required": True},
    ]},
    "pivot": {"fields": [
        {"name": "index", "label": "Index fields", "type": "field_list", "required": True},
        {"name": "column", "label": "Category field", "type": "field", "required": True},
        {"name": "value", "label": "Value field", "type": "field", "required": True},
        {"name": "aggregation", "label": "Aggregation", "type": "select", "options": ["first", "sum", "count"], "required": True},
    ]},
    "unpivot": {"fields": [
        {"name": "id_fields", "label": "Identity fields", "type": "field_list"},
        {"name": "value_fields", "label": "Value fields", "type": "field_list", "required": True},
        {"name": "name_field", "label": "Name output", "type": "string", "required": True},
        {"name": "value_field", "label": "Value output", "type": "string", "required": True},
    ]},
    "window": {"fields": [
        {"name": "partition_by", "label": "Partition fields", "type": "field_list"},
        {"name": "order_by", "label": "Order field", "type": "field", "required": True},
        {"name": "operation", "label": "Operation", "type": "select", "options": ["row_number", "rank", "running_sum"], "required": True},
        {"name": "value_field", "label": "Value field", "type": "field"},
        {"name": "target_field", "label": "Output field", "type": "string", "required": True},
    ]},
    "validate": {"fields": [
        {"name": "field", "label": "Field", "type": "field", "required": True},
        {"name": "check", "label": "Check", "type": "select", "options": ["required", "type", "range", "allowed"], "required": True},
        {"name": "severity", "label": "Severity", "type": "select", "options": ["warning", "error"], "required": True},
    ]},
    "derive_geo_point": {"fields": [
        {"name": "latitude_field", "label": "Latitude field", "type": "field", "required": True},
        {"name": "longitude_field", "label": "Longitude field", "type": "field", "required": True},
        {"name": "target_field", "label": "Geometry field", "type": "string", "required": True},
    ]},
    "derive_mgrs": {"fields": [
        {"name": "latitude_field", "label": "Latitude field", "type": "field", "required": True},
        {"name": "longitude_field", "label": "Longitude field", "type": "field", "required": True},
        {"name": "target_field", "label": "MGRS field", "type": "string", "required": True},
        {"name": "precision", "label": "Precision", "type": "integer", "minimum": 1, "maximum": 5},
    ]},
    "spatial_filter": {"fields": [
        {"name": "geometry_field", "label": "Geometry field", "type": "field", "required": True},
        {"name": "mode", "label": "Mode", "type": "select", "options": ["radius", "geofence"], "required": True},
        {"name": "radius_meters", "label": "Radius (meters)", "type": "number"},
    ]},
    "spatial_join": {"fields": [
        {"name": "left_geometry_field", "label": "Left geometry", "type": "field", "required": True},
        {"name": "right_geometry_field", "label": "Right geometry", "type": "field", "required": True},
        {"name": "distance_meters", "label": "Maximum distance", "type": "number", "required": True},
    ]},
    "llm_assist": {"fields": [
        {"name": "source_fields", "label": "Context fields", "type": "field_list", "required": True},
        {"name": "prompt", "label": "Prompt", "type": "textarea", "required": True},
        {"name": "target_field", "label": "Output field", "type": "string", "required": True},
    ]},
    "dataset_output": {"fields": [
        {"name": "asset_id", "label": "Output dataset", "type": "string", "required": True},
        {"name": "partition_by", "label": "Partition fields", "type": "field_list", "maximum_items": 8},
    ]},
    "ontology_output": {"fields": [
        {"name": "object_type_id", "label": "Object type", "type": "resource", "resource_type": "object_type", "required": True},
        {"name": "primary_key", "label": "Source primary key field", "type": "field", "required": True},
        {"name": "property_mapping", "label": "Property mapping", "type": "key_value", "required": True},
        {"name": "write_mode", "label": "Write mode", "type": "select", "options": ["upsert", "insert_only", "update_only"]},
        {"name": "on_error", "label": "Invalid row handling", "type": "select", "options": ["quarantine", "skip", "fail"]},
        {"name": "quarantine_asset_id", "label": "Quarantine dataset", "type": "string"},
        {"name": "source_asset_id", "label": "Source lineage dataset", "type": "resource", "resource_type": "data_asset"},
    ]},
}


class PipelineBuilderGraph(Base):
    __tablename__ = "pipeline_builder_graphs"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    project_id: Mapped[str] = mapped_column(String, default="default", index=True)
    display_name: Mapped[str] = mapped_column(String)
    description: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    nodes: Mapped[list] = mapped_column(JSON, default=list)
    edges: Mapped[list] = mapped_column(JSON, default=list)
    parameters: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String, default="DRAFT")
    created_at: Mapped[int] = mapped_column(Integer)
    updated_at: Mapped[int] = mapped_column(Integer)


class PipelineBuilderBuild(Base):
    __tablename__ = "pipeline_builder_builds"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    graph_id: Mapped[str] = mapped_column(String, index=True)
    status: Mapped[str] = mapped_column(String, default="SUCCESS")
    run_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    output_asset_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    preview: Mapped[dict] = mapped_column(JSON, default=dict)
    lineage: Mapped[dict] = mapped_column(JSON, default=dict)
    metrics: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[int] = mapped_column(Integer)


class PipelineOntologyContractRun(Base):
    """Immutable ontology-output reconciliation and quarantine evidence for a build."""
    __tablename__ = "pipeline_ontology_contract_runs"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    project_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    graph_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    build_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    node_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    object_type_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    status: Mapped[str] = mapped_column(String, nullable=False, index=True)
    input_rows: Mapped[int] = mapped_column(Integer, nullable=False)
    accepted_rows: Mapped[int] = mapped_column(Integer, nullable=False)
    rejected_rows: Mapped[int] = mapped_column(Integer, nullable=False)
    created_objects: Mapped[int] = mapped_column(Integer, nullable=False)
    updated_objects: Mapped[int] = mapped_column(Integer, nullable=False)
    unchanged_objects: Mapped[int] = mapped_column(Integer, nullable=False)
    quarantine_asset_id: Mapped[Optional[str]] = mapped_column(String, nullable=True, index=True)
    field_lineage: Mapped[list] = mapped_column(JSON, default=list)
    violations: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[int] = mapped_column(Integer, nullable=False, index=True)


def _contract_run_dict(row: PipelineOntologyContractRun) -> Dict[str, Any]:
    return {
        "id": row.id, "project_id": row.project_id, "graph_id": row.graph_id, "build_id": row.build_id,
        "node_id": row.node_id, "object_type_id": row.object_type_id, "status": row.status,
        "input_rows": row.input_rows, "accepted_rows": row.accepted_rows, "rejected_rows": row.rejected_rows,
        "created_objects": row.created_objects, "updated_objects": row.updated_objects, "unchanged_objects": row.unchanged_objects,
        "quarantine_asset_id": row.quarantine_asset_id, "field_lineage": row.field_lineage or [],
        "violations": row.violations or [], "created_at": row.created_at,
    }


class PipelineGraphCreate(BaseModel):
    id: Optional[str] = None
    project_id: str = "default"
    display_name: str
    description: Optional[str] = None
    nodes: List[Dict[str, Any]] = Field(default_factory=list)
    edges: List[Dict[str, Any]] = Field(default_factory=list)
    parameters: Dict[str, Any] = Field(default_factory=dict)
    status: str = "DRAFT"


class PipelineGraphUpdate(BaseModel):
    display_name: Optional[str] = None
    description: Optional[str] = None
    nodes: Optional[List[Dict[str, Any]]] = None
    edges: Optional[List[Dict[str, Any]]] = None
    parameters: Optional[Dict[str, Any]] = None
    status: Optional[str] = None


class PipelineGraphRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    project_id: str
    display_name: str
    description: Optional[str] = None
    nodes: List[Dict[str, Any]]
    edges: List[Dict[str, Any]]
    parameters: Dict[str, Any]
    status: str
    created_at: int
    updated_at: int


class PipelinePreviewRequest(BaseModel):
    limit: int = 50
    parameters: Dict[str, Any] = Field(default_factory=dict)


class PipelineDeliverRequest(BaseModel):
    output_asset_id: Optional[str] = None
    actor: str = "system"
    primary_key: str = "id"
    parameters: Dict[str, Any] = Field(default_factory=dict)
    execution_job_id: Optional[str] = None
    execution_lease_token: Optional[str] = None


class PipelineAsyncPreviewRequest(PipelinePreviewRequest):
    priority: int = Field(default=50, ge=0, le=100)
    max_attempts: int = Field(default=3, ge=1, le=20)
    timeout_seconds: int = Field(default=900, ge=1, le=86400)
    idempotency_key: Optional[str] = Field(default=None, min_length=1, max_length=200)


class PipelineAsyncDeliverRequest(PipelineDeliverRequest):
    priority: int = Field(default=75, ge=0, le=100)
    max_attempts: int = Field(default=3, ge=1, le=20)
    timeout_seconds: int = Field(default=3600, ge=1, le=86400)
    idempotency_key: Optional[str] = Field(default=None, min_length=1, max_length=200)


class PipelineWorkerRunRequest(BaseModel):
    worker_id: str = Field(default="pipeline-worker-local", min_length=1, max_length=200)
    lease_seconds: int = Field(default=120, ge=10, le=900)
    job_id: Optional[str] = None


class PipelineInsertNodeRequest(BaseModel):
    node_type: str = "filter"
    node_id: Optional[str] = None
    label: Optional[str] = None
    config: Dict[str, Any] = Field(default_factory=dict)
    position: Optional[Dict[str, float]] = None


class PipelineCreateNodeRequest(PipelineInsertNodeRequest):
    connect_from_node_id: Optional[str] = None
    actor: str = "pipeline_builder"


class PipelineLayoutRequest(BaseModel):
    positions: Dict[str, Dict[str, float]] = Field(default_factory=dict)
    nodes: List[Dict[str, Any]] = Field(default_factory=list)


class PipelineNodePreviewRequest(BaseModel):
    limit: int = 50
    parameters: Dict[str, Any] = Field(default_factory=dict)


class PipelineNodeUpdateRequest(BaseModel):
    label: Optional[str] = None
    config: Optional[Dict[str, Any]] = None
    actor: str = "pipeline_builder"


def _now() -> int:
    return int(time.time())


def _new_id() -> str:
    return uuid.uuid4().hex


@router.get("/pipeline-builder/node-types")
def list_node_types(_principal: Principal = Depends(require_permission("view"))):
    return {"node_types": _node_catalog_payload()}


def _node_catalog_payload() -> List[Dict[str, Any]]:
    return [{**item, "configuration_schema": NODE_CONFIGURATION_SCHEMAS.get(item["type"], {"fields": []})} for item in NODE_TYPE_CATALOG]


@router.get("/ui-state/pipeline")
def pipeline_ui_state(project_id: Optional[str] = None, principal: Principal = Depends(require_permission("view")), db: Session = Depends(get_db)):
    query = _accessible_graphs(db, principal, "view")
    if project_id:
        tenancy.assert_project_permission(db, principal, project_id, "view")
        query = query.filter(PipelineBuilderGraph.project_id == project_id)
    graphs = query.order_by(PipelineBuilderGraph.updated_at.desc()).all()
    selected = graphs[0] if graphs else None
    return {
        "summary": {
            "graph_count": len(graphs),
            "node_type_count": len(NODE_TYPE_CATALOG),
            "selected_graph_id": selected.id if selected else None,
        },
        "primary_actions": [
            {"id": "create_graph", "label": "Create graph", "method": "POST", "path": "/pipeline-builder/graphs"},
            {"id": "add_data", "label": "Add data", "method": "POST", "path": "/pipeline-builder/graphs/{graph_id}/nodes/{node_id}/insert-after"},
            {"id": "validate", "label": "Validate", "method": "POST", "path": "/pipeline-builder/graphs/{graph_id}/validate"},
            {"id": "deliver", "label": "Deliver", "method": "POST", "path": "/pipeline-builder/graphs/{graph_id}/deliver"},
            {"id": "version_draft", "label": "Create versioned draft", "method": "POST", "path": "/artifacts/adopt"},
        ],
        "graphs": [PipelineGraphRead.model_validate(graph).model_dump() for graph in graphs],
        "node_library": _node_catalog_payload(),
        "selected_canvas": _canvas_payload(db, selected) if selected else None,
        "empty_state": None if selected else {
            "title": "No pipeline graph yet",
            "action": "Generate an ontology draft or create a graph from imported data.",
        },
        "last_updated": max([graph.updated_at for graph in graphs], default=_now()),
    }


def _get_graph(db: Session, graph_id: str) -> PipelineBuilderGraph:
    graph = db.get(PipelineBuilderGraph, graph_id)
    if not graph:
        raise HTTPException(status_code=404, detail=f"PipelineBuilderGraph '{graph_id}' not found")
    return graph


def _graph_for(db: Session, graph_id: str, principal: Principal, permission: str) -> PipelineBuilderGraph:
    graph = _get_graph(db, graph_id)
    tenancy.assert_project_permission(db, principal, graph.project_id, permission)
    return graph


def _accessible_graphs(db: Session, principal: Principal, permission: str = "view"):
    query = db.query(PipelineBuilderGraph)
    project_ids = tenancy.accessible_project_ids(db, principal, permission)
    if project_ids is not None:
        query = query.filter(PipelineBuilderGraph.project_id.in_(project_ids)) if project_ids else query.filter(PipelineBuilderGraph.id == "__none__")
    return query


def _node_type(node: Dict[str, Any]) -> str:
    return str(node.get("type") or node.get("operation") or "").strip()


def _node_id(node: Dict[str, Any], index: int) -> str:
    return str(node.get("id") or f"node_{index}")


def _config(node: Dict[str, Any]) -> Dict[str, Any]:
    return node.get("config") or {k: v for k, v in node.items() if k not in {"id", "type", "operation", "label"}}


def _edge_source(edge: Dict[str, Any]) -> str:
    return str(edge.get("source") or edge.get("from") or "")


def _edge_target(edge: Dict[str, Any]) -> str:
    return str(edge.get("target") or edge.get("to") or "")


def _node_position(node: Dict[str, Any], index: int) -> Dict[str, float]:
    position = node.get("position") if isinstance(node.get("position"), dict) else {}
    return {
        "x": float(position.get("x", 120 + index * 260)),
        "y": float(position.get("y", 160 + (index % 3) * 120)),
    }


def _node_catalog_by_type() -> Dict[str, Dict[str, Any]]:
    return {item["type"]: item for item in NODE_TYPE_CATALOG}


def _audit_graph(db: Session, actor: str, event_type: str, graph: PipelineBuilderGraph, payload: Dict[str, Any]) -> None:
    db.add(models_action.AuditLog(
        id=_new_id(),
        actor=actor or "pipeline_builder",
        event_type=event_type,
        subject_type="pipeline_builder_graph",
        subject_id=graph.id,
        payload={"project_id": graph.project_id, **payload},
    ))


def _find_node(graph: PipelineBuilderGraph, node_id: str) -> Tuple[int, Dict[str, Any]]:
    for index, node in enumerate(graph.nodes or []):
        if _node_id(node, index) == node_id:
            return index, node
    raise HTTPException(status_code=404, detail=f"Pipeline node '{node_id}' not found")


def _unique_node_id(graph: PipelineBuilderGraph, node_type: str, requested_id: Optional[str] = None) -> str:
    existing_ids = {_node_id(node, index) for index, node in enumerate(graph.nodes or [])}
    new_id = requested_id or f"{node_type}_{len(existing_ids) + 1}"
    base_id = new_id
    suffix = 2
    while new_id in existing_ids:
        new_id = f"{base_id}_{suffix}"
        suffix += 1
    return new_id


def _node_from_request(graph: PipelineBuilderGraph, body: PipelineInsertNodeRequest, default_position: Dict[str, float]) -> Dict[str, Any]:
    node_type = str(body.node_type or "").strip()
    if node_type not in NODE_TYPES:
        raise HTTPException(status_code=422, detail=f"Unsupported node type '{node_type}'")
    new_id = _unique_node_id(graph, node_type, body.node_id)
    position = body.position or default_position
    catalog = _node_catalog_by_type().get(node_type, {})
    return {
        "id": new_id,
        "type": node_type,
        "label": body.label or catalog.get("label") or new_id,
        "position": {"x": float(position.get("x", 0)), "y": float(position.get("y", 0))},
        "config": _normalize_node_config(node_type, body.config or {}),
    }


def _normalize_node_config(node_type: str, config: Dict[str, Any]) -> Dict[str, Any]:
    """Keep saved pre-contract ontology nodes editable without a data migration."""
    normalized = copy.deepcopy(config or {})
    if node_type == "ontology_output":
        if "primary_key" not in normalized and normalized.get("id_field"):
            normalized["primary_key"] = normalized.pop("id_field")
        if "property_mapping" not in normalized and isinstance(normalized.get("mapping"), dict):
            normalized["property_mapping"] = normalized.pop("mapping")
        normalized.setdefault("write_mode", "upsert")
        normalized.setdefault("on_error", "quarantine")
    return normalized


def _validate_node_config(node_type: str, config: Dict[str, Any]) -> Dict[str, Any]:
    config = _normalize_node_config(node_type, config)
    schema = NODE_CONFIGURATION_SCHEMAS.get(node_type, {"fields": []})
    errors: List[Dict[str, Any]] = []
    warnings: List[Dict[str, Any]] = []
    for field in schema.get("fields", []):
        name = field["name"]
        value = config.get(name)
        if field.get("required") and (value is None or value == "" or value == [] or value == {}):
            errors.append({"field": name, "code": "REQUIRED", "message": f"{field.get('label', name)} is required"})
            continue
        if value is None:
            continue
        if field.get("type") == "integer":
            try:
                integer = int(value)
                if field.get("minimum") is not None and integer < int(field["minimum"]):
                    errors.append({"field": name, "code": "MINIMUM", "message": f"Value must be at least {field['minimum']}"})
                if field.get("maximum") is not None and integer > int(field["maximum"]):
                    errors.append({"field": name, "code": "MAXIMUM", "message": f"Value must be no more than {field['maximum']}"})
            except (TypeError, ValueError):
                errors.append({"field": name, "code": "TYPE", "message": "Value must be an integer"})
        if field.get("type") == "select" and value not in field.get("options", []):
            errors.append({"field": name, "code": "OPTION", "message": f"Choose one of: {', '.join(field.get('options', []))}"})
    unknown = sorted(set(config) - {field["name"] for field in schema.get("fields", [])})
    if unknown:
        warnings.append({"code": "UNKNOWN_CONFIG", "message": f"Unrecognized configuration fields: {', '.join(unknown)}"})
    return {"status": "INVALID" if errors else "VALID", "errors": errors, "warnings": warnings}


def _edge_exists(edges: List[Dict[str, Any]], source: str, target: str) -> bool:
    return any(_edge_source(edge) == source and _edge_target(edge) == target for edge in edges)


def _canvas_payload(db: Session, graph: PipelineBuilderGraph, *, selected_node_id: Optional[str] = None) -> Dict[str, Any]:
    catalog = _node_catalog_by_type()
    validation = _validate_graph(db, graph)
    execution: Optional[Dict[str, Any]] = None
    if validation["status"] == "VALID":
        try:
            execution = _execute_graph(db, graph, write_ontology=False)
        except HTTPException:
            execution = None
    node_outputs = (execution or {}).get("node_outputs", {})
    node_errors: Dict[str, List[Dict[str, Any]]] = {}
    for error in validation.get("errors", []):
        if error.get("node_id"):
            node_errors.setdefault(str(error["node_id"]), []).append(error)

    nodes = []
    for index, node in enumerate(graph.nodes or []):
        node_id = _node_id(node, index)
        node_type = _node_type(node)
        catalog_item = catalog.get(node_type, {})
        output = node_outputs.get(node_id, {})
        config = _config(node)
        nodes.append({
            "id": node_id,
            "label": node.get("label") or catalog_item.get("label") or node_id,
            "type": node_type,
            "category": catalog_item.get("category", "unknown"),
            "description": catalog_item.get("description", ""),
            "position": _node_position(node, index),
            "config": config,
            "ports": {
                "inputs": ["left", "right"] if node_type == "join" else (["input"] if node_type not in {"input_dataset", "dataset_input"} else []),
                "outputs": ["output"] if node_type not in {"dataset_output", "output_dataset", "ontology_output"} else [],
            },
            "status": "ERROR" if node_errors.get(node_id) else ("READY" if output else "CONFIGURE"),
            "errors": node_errors.get(node_id, []),
            "row_count": output.get("row_count"),
            "schema": output.get("schema", {"fields": []}),
            "sample": output.get("sample", []),
        })

    edges = [
        {
            "id": str(edge.get("id") or f"{_edge_source(edge)}__{_edge_target(edge)}"),
            "source": _edge_source(edge),
            "target": _edge_target(edge),
            "source_port": edge.get("source_port") or "output",
            "target_port": edge.get("target_port") or "input",
        }
        for edge in graph.edges or []
    ]
    selected_id = selected_node_id or (nodes[0]["id"] if nodes else None)
    selected = next((node for node in nodes if node["id"] == selected_id), None)
    recent_contracts = db.query(PipelineOntologyContractRun).filter(PipelineOntologyContractRun.graph_id == graph.id).order_by(PipelineOntologyContractRun.created_at.desc()).all()
    contracts_by_build: Dict[str, List[PipelineOntologyContractRun]] = defaultdict(list)
    for contract in recent_contracts:
        contracts_by_build[contract.build_id].append(contract)
    builds = [
        {
            "id": build.id,
            "status": build.status,
            "run_id": build.run_id,
            "output_asset_id": build.output_asset_id,
            "row_count": (build.preview or {}).get("row_count"),
            "created_at": build.created_at,
            "ontology_contracts": [_contract_run_dict(row) for row in contracts_by_build.get(build.id, [])],
        }
        for build in db.query(PipelineBuilderBuild).filter(PipelineBuilderBuild.graph_id == graph.id).order_by(PipelineBuilderBuild.created_at.desc()).limit(5).all()
    ]
    output_nodes = [node for node in nodes if node["type"] in {"dataset_output", "output_dataset", "ontology_output"}]
    return {
        "graph": PipelineGraphRead.model_validate(graph).model_dump(),
        "toolbar_groups": [
            {"id": "tools", "label": "Tools", "actions": ["pan", "select", "remove"]},
            {"id": "layout", "label": "Layout", "actions": ["auto_layout", "fit_to_view"]},
            {"id": "data", "label": "Add data", "actions": ["input_dataset", "connector_source", "stream_archive"]},
            {"id": "transform", "label": "Transform", "actions": ["filter", "project", "rename", "join", "union", "aggregate", "sort", "limit", "unique_id"]},
            {"id": "aip", "label": "AIP", "actions": ["llm_assist"]},
            {"id": "deploy", "label": "Deploy", "actions": ["validate", "preview", "deliver"]},
        ],
        "node_library": _node_catalog_payload(),
        "legend": [
            {"category": "input", "label": "Raw Input", "color": "#7d8b99"},
            {"category": "transform", "label": "Transform", "color": "#d49b00"},
            {"category": "ai", "label": "AIP", "color": "#7b61ff"},
            {"category": "output", "label": "Output", "color": "#1388b8"},
        ],
        "nodes": nodes,
        "edges": edges,
        "selected_node": selected,
        "bottom_tabs": ["selection_preview", "preview", "transformations", "suggestions", "pipeline_warnings"],
        "outputs": {
            "nodes": output_nodes,
            "builds": builds,
            "mapped_columns": (execution or {}).get("metrics", {}).get("records_out"),
            "target_ontology": (graph.parameters or {}).get("target_ontology") or "local",
            "output_folder": (graph.parameters or {}).get("output_folder"),
        },
        "validation": validation,
        "lineage": (execution or {}).get("lineage", {}),
        "metrics": (execution or {}).get("metrics", {}),
        "actions": [
            {"id": "validate", "label": "Validate", "method": "POST", "path": f"/pipeline-builder/graphs/{graph.id}/validate"},
            {"id": "preview", "label": "Preview", "method": "POST", "path": f"/pipeline-builder/graphs/{graph.id}/preview"},
            {"id": "deliver", "label": "Deliver", "method": "POST", "path": f"/pipeline-builder/graphs/{graph.id}/deliver"},
        ],
    }


def _node_details_payload(db: Session, graph: PipelineBuilderGraph, node_id: str) -> Dict[str, Any]:
    _index, node = _find_node(graph, node_id)
    canvas = _canvas_payload(db, graph, selected_node_id=node_id)
    selected = canvas.get("selected_node")
    preview: Dict[str, Any] = {
        "status": "NOT_AVAILABLE",
        "row_count": 0,
        "rows": [],
        "columns": [],
        "schema": {"fields": []},
    }
    execution: Dict[str, Any] = {}
    try:
        execution = _execute_graph(db, graph, write_ontology=False)
        output = execution.get("node_outputs", {}).get(node_id, {})
        schema = output.get("schema", {"fields": []})
        preview = {
            "status": "PREVIEW_READY" if output else "NOT_AVAILABLE",
            "row_count": output.get("row_count", 0),
            "rows": output.get("sample", []),
            "columns": schema.get("fields", []),
            "schema": schema,
        }
    except HTTPException as exc:
        preview = {
            "status": "ERROR",
            "row_count": 0,
            "rows": [],
            "columns": [],
            "schema": {"fields": []},
            "error": exc.detail,
        }
    node_type = _node_type(node)
    config = _config(node)
    available_fields = [field.get("name") for field in preview.get("columns", []) if field.get("name")]
    upstream_ids = _predecessors(graph).get(node_id, [])
    lineage_map = (execution or {}).get("lineage", {}).get("fields_by_node", {}).get(node_id, {})
    field_lineage = [{"field": field_name, "origins": lineage_map.get(field_name, []), "operation": node_type} for field_name in available_fields]
    ontology_contract = next((item for item in (execution or {}).get("ontology_contracts", []) if item.get("node_id") == node_id), None)
    context_actions = [
        {"id": "transform", "label": "Transform", "node_type": "filter"},
        {"id": "split", "label": "Split", "node_type": "project"},
        {"id": "join", "label": "Join", "node_type": "join"},
        {"id": "union", "label": "Union", "node_type": "union"},
        {"id": "use_llm", "label": "Use LLM", "node_type": "llm_assist"},
        {"id": "generate", "label": "Generate", "node_type": "unique_id"},
        {"id": "explain", "label": "Explain", "node_type": "llm_assist"},
        {"id": "add_output", "label": "Add output", "node_type": "dataset_output"},
    ]
    return {
        "graph_id": graph.id,
        "node_id": node_id,
        "node": selected or {
            "id": node_id,
            "label": node.get("label") or node_id,
            "type": node_type,
            "config": _config(node),
            "position": _node_position(node, _index),
        },
        "metadata": {
            "type": node_type,
            "config": config,
            "configuration_schema": NODE_CONFIGURATION_SCHEMAS.get(node_type, {"fields": []}),
            "configuration_validation": _validate_node_config(node_type, config),
            "available_fields": available_fields,
            "field_lineage": field_lineage,
            "ontology_contract": ontology_contract,
            "upstream": upstream_ids,
            "downstream": [_edge_target(edge) for edge in graph.edges or [] if _edge_source(edge) == node_id],
        },
        "preview": preview,
        "context_actions": context_actions,
        "suggestions": _node_suggestions_payload(db, graph, node_id),
    }


def _node_suggestions_payload(db: Session, graph: PipelineBuilderGraph, node_id: str) -> Dict[str, Any]:
    _index, node = _find_node(graph, node_id)
    node_type = _node_type(node)
    validation = _validate_graph(db, graph)
    preview: Dict[str, Any] = {}
    try:
        execution = _execute_graph(db, graph, write_ontology=False)
        preview = execution.get("node_outputs", {}).get(node_id, {})
    except HTTPException:
        preview = {}
    field_names = [field.get("name") for field in (preview.get("schema") or {}).get("fields", []) if field.get("name")]
    suggestions: List[Dict[str, Any]] = []
    if node_type in {"input_dataset", "dataset_input"}:
        if {"latitude", "longitude"} <= set(field_names):
            suggestions.append({"id": "derive_geo", "label": "Derive point geometry", "node_type": "project", "config": {"fields": field_names}})
        suggestions.append({"id": "clean_columns", "label": "Add transformation", "node_type": "rename", "config": {"mapping": {}}})
    if node_type == "join":
        suggestions.append({"id": "review_join_keys", "label": "Review join keys", "node_type": "join", "config": _config(node)})
    if node_type not in {"dataset_output", "output_dataset", "ontology_output"}:
        suggestions.append({"id": "add_output", "label": "Add output", "node_type": "dataset_output", "config": {"asset_id": f"{graph.id}_output"}})
    for error in validation.get("errors", []):
        if error.get("node_id") == node_id:
            suggestions.append({"id": f"fix_{error['code'].lower()}", "label": error.get("message"), "severity": "error"})
    return {
        "graph_id": graph.id,
        "node_id": node_id,
        "suggestions": suggestions,
        "insertable_node_types": _node_catalog_payload(),
        "warnings": validation.get("warnings", []),
        "errors": [error for error in validation.get("errors", []) if error.get("node_id") in {None, node_id}],
    }


def _validate_graph(db: Session, graph: PipelineBuilderGraph) -> Dict[str, Any]:
    nodes = graph.nodes or []
    edges = graph.edges or []
    errors: List[Dict[str, Any]] = []
    warnings: List[Dict[str, Any]] = []
    node_ids: List[str] = []
    id_set = set()

    for index, node in enumerate(nodes):
        node_id = _node_id(node, index)
        node_type = _node_type(node)
        if node_id in id_set:
            errors.append({"code": "DUPLICATE_NODE_ID", "node_id": node_id, "message": "Node id is duplicated"})
        id_set.add(node_id)
        node_ids.append(node_id)
        if node_type not in NODE_TYPES:
            errors.append({"code": "UNSUPPORTED_NODE_TYPE", "node_id": node_id, "message": f"Unsupported node type '{node_type}'"})
        if node_type in {"input_dataset", "dataset_input"}:
            asset_id = _config(node).get("asset_id") or _config(node).get("dataset_id")
            if not asset_id:
                errors.append({"code": "MISSING_INPUT_ASSET", "node_id": node_id, "message": "Input dataset node needs asset_id"})
            else:
                asset = db.get(models.DataAsset, asset_id)
                if not asset:
                    errors.append({"code": "INPUT_ASSET_NOT_FOUND", "node_id": node_id, "message": f"DataAsset '{asset_id}' not found"})
                elif asset.project_id != graph.project_id:
                    errors.append({"code": "INPUT_ASSET_PROJECT_MISMATCH", "node_id": node_id, "message": f"DataAsset '{asset_id}' belongs to another project"})
        if node_type == "ontology_output":
            output_config = _config(node)
            object_type_id = output_config.get("object_type_id")
            object_type = db.get(models.ObjectType, object_type_id) if object_type_id else None
            if not object_type:
                errors.append({"code": "ONTOLOGY_OUTPUT_TYPE_NOT_FOUND", "node_id": node_id, "message": f"Object type '{object_type_id or ''}' not found"})
            elif object_type.project_id != graph.project_id:
                errors.append({"code": "ONTOLOGY_OUTPUT_PROJECT_MISMATCH", "node_id": node_id, "message": f"Object type '{object_type_id}' belongs to another project"})
            else:
                properties, target_primary_key = _ontology_schema(db, object_type)
                mapping = output_config.get("property_mapping") or output_config.get("mapping") or {}
                primary_key = output_config.get("primary_key") or output_config.get("id_field")
                if not primary_key:
                    errors.append({"code": "ONTOLOGY_OUTPUT_PRIMARY_KEY_REQUIRED", "node_id": node_id, "message": "Ontology output needs a source primary key field"})
                if not mapping:
                    warnings.append({"code": "ONTOLOGY_OUTPUT_AUTO_MAPPING", "node_id": node_id, "message": "Matching source and ontology field names will be mapped automatically"})
                unknown_targets = sorted({str(target) for target in mapping.values()} - set(properties))
                if unknown_targets:
                    errors.append({"code": "ONTOLOGY_OUTPUT_UNKNOWN_PROPERTIES", "node_id": node_id, "message": f"Unknown target properties: {', '.join(unknown_targets)}"})
                mapped_targets = set(str(value) for value in mapping.values())
                required_targets = {name for name, spec in properties.items() if isinstance(spec, dict) and spec.get("required")}
                if mapping and target_primary_key and target_primary_key not in mapped_targets:
                    errors.append({"code": "ONTOLOGY_OUTPUT_PRIMARY_KEY_UNMAPPED", "node_id": node_id, "message": f"Target primary key '{target_primary_key}' is not mapped"})
                missing_required = sorted(required_targets - mapped_targets) if mapping else []
                if missing_required:
                    errors.append({"code": "ONTOLOGY_OUTPUT_REQUIRED_UNMAPPED", "node_id": node_id, "message": f"Required target properties are not mapped: {', '.join(missing_required)}"})

    for edge in edges:
        source = str(edge.get("source") or edge.get("from") or "")
        target = str(edge.get("target") or edge.get("to") or "")
        if source not in id_set or target not in id_set:
            errors.append({"code": "BROKEN_EDGE", "message": f"Edge {source}->{target} references a missing node"})

    if nodes and not any(_node_type(node) in {"input_dataset", "dataset_input"} for node in nodes):
        errors.append({"code": "NO_INPUT", "message": "Graph needs at least one input dataset node"})
    if nodes and not any(_node_type(node) in {"dataset_output", "output_dataset", "ontology_output"} for node in nodes):
        warnings.append({"code": "NO_OUTPUT", "message": "Graph has no explicit output node; preview will use the final transform"})

    try:
        _topological_nodes(graph)
    except ValueError as exc:
        errors.append({"code": "CYCLE_OR_ORDER", "message": str(exc)})

    return {
        "graph_id": graph.id,
        "status": "VALID" if not errors else "INVALID",
        "node_count": len(nodes),
        "edge_count": len(edges),
        "errors": errors,
        "warnings": warnings,
    }


def _topological_nodes(graph: PipelineBuilderGraph) -> List[Tuple[str, Dict[str, Any]]]:
    nodes = [(_node_id(node, index), node) for index, node in enumerate(graph.nodes or [])]
    if not graph.edges:
        return nodes

    node_map = {node_id: node for node_id, node in nodes}
    incoming = {node_id: set() for node_id in node_map}
    outgoing = {node_id: set() for node_id in node_map}
    for edge in graph.edges or []:
        source = str(edge.get("source") or edge.get("from") or "")
        target = str(edge.get("target") or edge.get("to") or "")
        if source in node_map and target in node_map:
            incoming[target].add(source)
            outgoing[source].add(target)

    ready = [node_id for node_id, _node in nodes if not incoming[node_id]]
    ordered: List[Tuple[str, Dict[str, Any]]] = []
    while ready:
        node_id = ready.pop(0)
        ordered.append((node_id, node_map[node_id]))
        for target in sorted(outgoing[node_id]):
            incoming[target].discard(node_id)
            if not incoming[target]:
                ready.append(target)
    if len(ordered) != len(nodes):
        raise ValueError("Graph contains a cycle or disconnected edge state")
    return ordered


def _predecessors(graph: PipelineBuilderGraph) -> Dict[str, List[str]]:
    incoming: Dict[str, List[str]] = {_node_id(node, index): [] for index, node in enumerate(graph.nodes or [])}
    for edge in graph.edges or []:
        source = str(edge.get("source") or edge.get("from") or "")
        target = str(edge.get("target") or edge.get("to") or "")
        if target in incoming:
            incoming[target].append(source)
    return incoming


def _value(row: Dict[str, Any], field: str) -> Any:
    value: Any = row
    for part in str(field).split("."):
        if not isinstance(value, dict):
            return None
        value = value.get(part)
    return value


def _compare(left: Any, op: str, right: Any) -> bool:
    op = str(op or "equals").lower()
    try:
        if op in {"equals", "eq", "=="}:
            return left == right
        if op in {"not_equals", "ne", "!="}:
            return left != right
        if op == "contains":
            return str(right).lower() in str(left).lower()
        if op == "in":
            return left in (right or [])
        if op in {"gt", ">"}:
            return left > right
        if op in {"gte", ">="}:
            return left >= right
        if op in {"lt", "<"}:
            return left < right
        if op in {"lte", "<="}:
            return left <= right
        if op == "exists":
            return (left is not None) is bool(right)
    except TypeError:
        return False
    return False


def _filter_rows(rows: List[Dict[str, Any]], config: Dict[str, Any]) -> List[Dict[str, Any]]:
    filters = config.get("filters")
    if isinstance(filters, dict):
        specs = [
            {"field": field, "op": next(iter(expr.keys())) if isinstance(expr, dict) else "equals", "value": next(iter(expr.values())) if isinstance(expr, dict) else expr}
            for field, expr in filters.items()
        ]
    elif isinstance(filters, list):
        specs = filters
    else:
        specs = [{"field": config.get("field"), "op": config.get("op") or config.get("operator", "equals"), "value": config.get("value")}]
    return [
        row for row in rows
        if all(_compare(_value(row, spec.get("field")), spec.get("op", "equals"), spec.get("value")) for spec in specs if spec.get("field"))
    ]


def _project_rows(rows: List[Dict[str, Any]], config: Dict[str, Any]) -> List[Dict[str, Any]]:
    fields = config.get("columns") or config.get("fields") or []
    return [{field: _value(row, field) for field in fields} for row in rows] if fields else rows


def _rename_rows(rows: List[Dict[str, Any]], config: Dict[str, Any]) -> List[Dict[str, Any]]:
    mapping = config.get("mapping") or {}
    return [{mapping.get(key, key): value for key, value in row.items()} for row in rows]


def _cast_value(value: Any, target_type: str) -> Any:
    if value is None:
        return None
    target = str(target_type).lower()
    if target in {"string", "str"}:
        return str(value)
    if target in {"integer", "int"}:
        return int(float(value))
    if target in {"number", "float", "double"}:
        return float(value)
    if target in {"boolean", "bool"}:
        if isinstance(value, str):
            lowered = value.strip().lower()
            if lowered in {"true", "1", "yes", "y"}:
                return True
            if lowered in {"false", "0", "no", "n"}:
                return False
            raise ValueError(f"Cannot cast '{value}' to boolean")
        return bool(value)
    raise ValueError(f"Unsupported cast type '{target_type}'")


def _cast_rows(rows: List[Dict[str, Any]], config: Dict[str, Any]) -> List[Dict[str, Any]]:
    mapping = config.get("mapping") or config.get("types") or ({config["field"]: config.get("target_type")} if config.get("field") and config.get("target_type") else {})
    on_error = str(config.get("on_error", "null")).lower()
    output = []
    for row in rows:
        result = copy.deepcopy(row)
        for field, target_type in mapping.items():
            try:
                result[field] = _cast_value(_value(row, field), str(target_type))
            except (TypeError, ValueError):
                if on_error == "fail":
                    raise HTTPException(status_code=422, detail=f"Cannot cast field '{field}' to {target_type}")
                if on_error == "keep":
                    continue
                result[field] = None
        output.append(result)
    return output


def _derive_value(row: Dict[str, Any], spec: Dict[str, Any]) -> Any:
    operation = str(spec.get("operation") or spec.get("op") or "copy").lower()
    fields = spec.get("fields") or ([spec.get("field")] if spec.get("field") else [])
    values = [_value(row, field) for field in fields]
    if operation == "copy":
        return values[0] if values else spec.get("value")
    if operation == "literal":
        return spec.get("value")
    if operation == "coalesce":
        return next((value for value in values if value is not None), spec.get("default"))
    if operation == "concat":
        return str(spec.get("separator", "")).join(str(value) for value in values if value is not None)
    if operation in {"lower", "upper", "trim"}:
        text = "" if not values or values[0] is None else str(values[0])
        return text.lower() if operation == "lower" else text.upper() if operation == "upper" else text.strip()
    numbers = [float(value) for value in values if value is not None]
    if operation == "add":
        return sum(numbers)
    if operation == "subtract":
        return numbers[0] - sum(numbers[1:]) if numbers else None
    if operation == "multiply":
        result = 1.0
        for value in numbers:
            result *= value
        return result
    if operation == "divide":
        return numbers[0] / numbers[1] if len(numbers) >= 2 and numbers[1] != 0 else None
    raise HTTPException(status_code=422, detail=f"Unsupported derive operation '{operation}'")


def _derive_rows(rows: List[Dict[str, Any]], config: Dict[str, Any]) -> List[Dict[str, Any]]:
    derivations = config.get("derivations") or [config]
    output = []
    for row in rows:
        result = copy.deepcopy(row)
        for spec in derivations:
            target = spec.get("target") or spec.get("target_field") or spec.get("as")
            if target:
                result[target] = _derive_value(result, spec)
        output.append(result)
    return output


def _fill_nulls(rows: List[Dict[str, Any]], config: Dict[str, Any]) -> List[Dict[str, Any]]:
    defaults = config.get("defaults") or config.get("mapping") or ({config["field"]: config.get("value")} if config.get("field") else {})
    return [{**row, **{field: value for field, value in defaults.items() if _value(row, field) is None}} for row in rows]


def _normalize_rows(rows: List[Dict[str, Any]], config: Dict[str, Any]) -> List[Dict[str, Any]]:
    fields = config.get("fields") or []
    case = str(config.get("case") or config.get("mode", "preserve")).lower()
    output = []
    for row in rows:
        result = copy.deepcopy(row)
        for field in fields:
            value = _value(row, field)
            if isinstance(value, str):
                value = value.strip()
                value = (
                    value.lower() if case == "lower"
                    else value.upper() if case == "upper"
                    else value.title() if case == "title"
                    else value
                )
                result[field] = value
        output.append(result)
    return output


def _deduplicate_rows(rows: List[Dict[str, Any]], config: Dict[str, Any]) -> List[Dict[str, Any]]:
    keys = config.get("keys") or config.get("fields") or []
    if not keys:
        keys = sorted({key for row in rows for key in row})
    keep = str(config.get("keep", "first")).lower()
    ordered = list(reversed(rows)) if keep == "last" else rows
    seen = set()
    output = []
    for row in ordered:
        signature = tuple(repr(_value(row, field)) for field in keys)
        if signature in seen:
            continue
        seen.add(signature)
        output.append(copy.deepcopy(row))
    return list(reversed(output)) if keep == "last" else output


def _pivot_rows(rows: List[Dict[str, Any]], config: Dict[str, Any]) -> List[Dict[str, Any]]:
    index_fields = config.get("index") or config.get("group_by") or []
    if isinstance(index_fields, str):
        index_fields = [index_fields]
    column_field = config.get("column") or config.get("column_field")
    value_field = config.get("value") or config.get("value_field")
    operation = str(config.get("operation") or config.get("aggregation", "first")).lower()
    grouped: Dict[Tuple[Any, ...], Dict[str, Any]] = {}
    for row in rows:
        key = tuple(_value(row, field) for field in index_fields)
        target = grouped.setdefault(key, {field: key[index] for index, field in enumerate(index_fields)})
        column = str(_value(row, column_field))
        value = _value(row, value_field)
        if operation == "sum":
            target[column] = float(target.get(column, 0) or 0) + float(value or 0)
        elif operation == "count":
            target[column] = int(target.get(column, 0) or 0) + 1
        elif column not in target:
            target[column] = value
    return list(grouped.values())


def _unpivot_rows(rows: List[Dict[str, Any]], config: Dict[str, Any]) -> List[Dict[str, Any]]:
    id_fields = config.get("id_fields") or []
    value_fields = config.get("value_fields") or []
    name_field = config.get("name_field") or "field"
    value_field = config.get("value_field") or "value"
    output = []
    for row in rows:
        base = {field: _value(row, field) for field in id_fields}
        for field in value_fields:
            output.append({**base, name_field: field, value_field: _value(row, field)})
    return output


def _window_rows(rows: List[Dict[str, Any]], config: Dict[str, Any]) -> List[Dict[str, Any]]:
    partition_by = config.get("partition_by") or []
    if isinstance(partition_by, str):
        partition_by = [partition_by]
    order_by = config.get("order_by")
    operation = str(config.get("operation", "row_number")).lower()
    target = config.get("target_field") or operation
    field = config.get("field") or config.get("value_field")
    partitions: Dict[Tuple[Any, ...], List[Dict[str, Any]]] = {}
    for row in rows:
        partitions.setdefault(tuple(_value(row, item) for item in partition_by), []).append(copy.deepcopy(row))
    output = []
    for partition in partitions.values():
        if order_by:
            partition.sort(key=lambda item: (_value(item, order_by) is None, _value(item, order_by)))
        running = 0.0
        previous = object()
        rank = 0
        for index, row in enumerate(partition, start=1):
            if operation == "row_number":
                row[target] = index
            elif operation == "rank":
                current = _value(row, order_by)
                if current != previous:
                    rank = index
                    previous = current
                row[target] = rank
            elif operation == "running_sum":
                value = _value(row, field)
                running += float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else 0
                row[target] = running
            output.append(row)
    return output


def _row_validation_errors(row: Dict[str, Any], checks: List[Dict[str, Any]]) -> List[str]:
    errors = []
    for check in checks:
        check_type = str(check.get("type", "required")).lower()
        field = check.get("field")
        value = _value(row, field) if field else None
        if check_type in {"required", "non_null"} and value is None:
            errors.append(f"{field} is required")
        elif check_type == "type" and value is not None:
            expected = str(check.get("expected", "string"))
            expected_types = {"string": str, "integer": int, "number": (int, float), "boolean": bool, "object": dict, "array": list}
            if expected in expected_types and (not isinstance(value, expected_types[expected]) or expected == "integer" and isinstance(value, bool)):
                errors.append(f"{field} must be {expected}")
        elif check_type == "range" and value is not None:
            if check.get("min") is not None and value < check["min"]:
                errors.append(f"{field} is below {check['min']}")
            if check.get("max") is not None and value > check["max"]:
                errors.append(f"{field} is above {check['max']}")
        elif check_type == "allowed_values" and value not in (check.get("values") or []):
            errors.append(f"{field} is not an allowed value")
    return errors


def _validate_rows(rows: List[Dict[str, Any]], config: Dict[str, Any]) -> List[Dict[str, Any]]:
    checks = config.get("checks") or ([{
        "field": config.get("field"), "type": config.get("check", "required"),
        "expected": config.get("expected"), "min": config.get("min"), "max": config.get("max"),
        "values": config.get("values") or config.get("allowed_values"),
    }] if config.get("field") else [])
    on_error = str(config.get("on_error", "annotate")).lower()
    output = []
    for row in rows:
        errors = _row_validation_errors(row, checks)
        if errors and on_error == "fail":
            raise HTTPException(status_code=422, detail={"message": "Row validation failed", "errors": errors})
        if errors and on_error == "drop":
            continue
        output.append({**row, **({"_validation_errors": errors} if errors else {})})
    return output


def _point(row: Dict[str, Any], field: Optional[str] = None) -> Optional[Tuple[float, float]]:
    value = _value(row, field) if field else row.get("geometry")
    if isinstance(value, dict) and value.get("type") == "Point" and isinstance(value.get("coordinates"), list) and len(value["coordinates"]) >= 2:
        return float(value["coordinates"][1]), float(value["coordinates"][0])
    lat = row.get("latitude")
    lon = row.get("longitude")
    return (float(lat), float(lon)) if lat is not None and lon is not None else None


def _distance_meters(left: Tuple[float, float], right: Tuple[float, float]) -> float:
    lat1, lon1, lat2, lon2 = map(math.radians, [left[0], left[1], right[0], right[1]])
    a = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return 6371000 * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _derive_geo_rows(rows: List[Dict[str, Any]], config: Dict[str, Any]) -> List[Dict[str, Any]]:
    latitude = config.get("latitude_field") or "latitude"
    longitude = config.get("longitude_field") or "longitude"
    target = config.get("target_field") or "geometry"
    return [{**row, target: {"type": "Point", "coordinates": [float(_value(row, longitude)), float(_value(row, latitude))]}} if _value(row, latitude) is not None and _value(row, longitude) is not None else copy.deepcopy(row) for row in rows]


def _derive_mgrs_rows(rows: List[Dict[str, Any]], config: Dict[str, Any]) -> List[Dict[str, Any]]:
    from .runtime import encode_mgrs
    latitude = config.get("latitude_field") or "latitude"
    longitude = config.get("longitude_field") or "longitude"
    target = config.get("target_field") or "mgrs"
    precision = int(config.get("precision", 5))
    output = []
    for row in rows:
        lat, lon = _value(row, latitude), _value(row, longitude)
        output.append({**row, **({target: encode_mgrs(float(lat), float(lon), precision)["mgrs"]} if lat is not None and lon is not None else {})})
    return output


def _spatial_filter_rows(rows: List[Dict[str, Any]], config: Dict[str, Any]) -> List[Dict[str, Any]]:
    mode = str(config.get("mode") or "radius").lower()
    geometry_field = config.get("geometry_field") or "geometry"
    if mode in {"geofence", "polygon"}:
        from .runtime import point_in_polygon, validate_geojson_geometry
        polygon = config.get("polygon") or config.get("geofence")
        if not validate_geojson_geometry(polygon) or polygon.get("type") != "Polygon":
            raise HTTPException(status_code=422, detail="Spatial geofence requires a GeoJSON Polygon")
        return [
            row for row in rows
            if (point := _point(row, geometry_field)) and point_in_polygon((point[1], point[0]), polygon)
        ]
    if mode != "radius":
        raise HTTPException(status_code=422, detail=f"Unsupported spatial filter mode '{mode}'")
    center = config.get("center") or {}
    center_point = (float(center.get("latitude")), float(center.get("longitude"))) if center.get("latitude") is not None and center.get("longitude") is not None else None
    radius = float(config.get("radius_meters", 0))
    if not center_point or radius <= 0:
        raise HTTPException(status_code=422, detail="Radius filter requires a center and positive radius_meters")
    return [row for row in rows if _point(row, geometry_field) and _distance_meters(_point(row, geometry_field), center_point) <= radius]


def _spatial_join_rows(left_rows: List[Dict[str, Any]], right_rows: List[Dict[str, Any]], config: Dict[str, Any]) -> List[Dict[str, Any]]:
    max_distance = float(config.get("max_distance_meters") or config.get("distance_meters", 1000))
    left_field = config.get("left_geometry_field") or "geometry"
    right_field = config.get("right_geometry_field") or "geometry"
    output = []
    for left in left_rows:
        left_point = _point(left, left_field)
        if not left_point:
            continue
        for right in right_rows:
            right_point = _point(right, right_field)
            if not right_point:
                continue
            distance = _distance_meters(left_point, right_point)
            if distance <= max_distance:
                merged = copy.deepcopy(left)
                for key, value in right.items():
                    merged[key if key not in merged else f"right_{key}"] = value
                merged[config.get("distance_field") or "distance_meters"] = round(distance, 3)
                output.append(merged)
    return output


def _join_rows(left_rows: List[Dict[str, Any]], right_rows: List[Dict[str, Any]], config: Dict[str, Any]) -> List[Dict[str, Any]]:
    left_key = config.get("left_key") or config.get("on")
    right_key = config.get("right_key") or config.get("on")
    if not left_key or not right_key:
        return left_rows
    right_index: Dict[Any, List[Dict[str, Any]]] = {}
    for row in right_rows:
        right_index.setdefault(_value(row, right_key), []).append(row)
    joined = []
    for left in left_rows:
        matches = right_index.get(_value(left, left_key), [])
        if not matches and config.get("how", "inner") in {"left", "outer"}:
            joined.append(copy.deepcopy(left))
        for right in matches:
            merged = copy.deepcopy(left)
            for key, value in right.items():
                merged[key if key not in merged else f"right_{key}"] = value
            joined.append(merged)
    return joined


def _aggregate_rows(rows: List[Dict[str, Any]], config: Dict[str, Any]) -> List[Dict[str, Any]]:
    group_by = config.get("group_by") or []
    if isinstance(group_by, str):
        group_by = [group_by]
    metrics = config.get("metrics") or [{
        "operation": config.get("operation", "count"), "field": config.get("field"),
        "alias": config.get("target_field") or config.get("alias") or "count",
    }]
    grouped: Dict[Tuple[Any, ...], List[Dict[str, Any]]] = {}
    for row in rows:
        key = tuple(_value(row, field) for field in group_by) if group_by else ("all",)
        grouped.setdefault(key, []).append(row)
    output = []
    for key, items in grouped.items():
        out = {field: key[index] for index, field in enumerate(group_by)}
        for metric in metrics:
            op = str(metric.get("operation") or metric.get("op") or "count").lower()
            field = metric.get("field")
            alias = metric.get("alias") or metric.get("as") or f"{op}_{field or 'rows'}"
            values = [_value(item, field) for item in items] if field else []
            nums = [float(value) for value in values if isinstance(value, (int, float)) and not isinstance(value, bool)]
            if op == "count":
                out[alias] = len([value for value in values if value is not None]) if field else len(items)
            elif op == "sum":
                out[alias] = sum(nums)
            elif op == "avg":
                out[alias] = (sum(nums) / len(nums)) if nums else None
            elif op == "min":
                out[alias] = min(nums) if nums else None
            elif op == "max":
                out[alias] = max(nums) if nums else None
        output.append(out)
    return output


def _stable_row_id(row: Dict[str, Any], fields: List[str]) -> str:
    payload = "|".join(str(_value(row, field)) for field in fields) if fields else repr(sorted(row.items()))
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()[:16]


def _schema(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    fields: Dict[str, str] = {}
    for row in rows[:200]:
        for key, value in row.items():
            if key not in fields:
                fields[key] = type(value).__name__
    return {"fields": [{"name": key, "type": value} for key, value in fields.items()]}


def _append_lineage_step(origins: List[Dict[str, Any]], node_id: str, operation: str) -> List[Dict[str, Any]]:
    result = copy.deepcopy(origins)
    if not result:
        result = [{"asset_id": None, "field": None, "path": []}]
    for origin in result:
        path = list(origin.get("path") or [])
        if not path or path[-1].get("node_id") != node_id:
            path.append({"node_id": node_id, "operation": operation})
        origin["path"] = path
    return result


def _field_lineage_for_node(
    node_id: str,
    node_type: str,
    config: Dict[str, Any],
    rows: List[Dict[str, Any]],
    parent_lineages: List[Dict[str, List[Dict[str, Any]]]],
    input_asset_id: Optional[str] = None,
) -> Dict[str, List[Dict[str, Any]]]:
    output_fields = [item["name"] for item in _schema(rows).get("fields", [])]
    if node_type in {"input_dataset", "dataset_input"}:
        return {field: [{"asset_id": input_asset_id, "field": field, "path": [{"node_id": node_id, "operation": node_type}]}] for field in output_fields}
    combined: Dict[str, List[Dict[str, Any]]] = {}
    for parent_index, lineage in enumerate(parent_lineages):
        for field, origins in lineage.items():
            output_name = field if field not in combined else f"right_{field}" if parent_index else field
            combined.setdefault(output_name, []).extend(copy.deepcopy(origins))
    rename_inverse = {target: source for source, target in (config.get("mapping") or {}).items()} if node_type == "rename" else {}
    derivations = config.get("derivations") or [config]
    generated_sources: Dict[str, List[str]] = {}
    if node_type == "derive":
        for spec in derivations:
            target = spec.get("target") or spec.get("target_field") or spec.get("as")
            if target:
                generated_sources[target] = list(spec.get("fields") or spec.get("source_fields") or ([spec.get("field")] if spec.get("field") else []))
    elif node_type in {"unique_id", "llm_assist", "llm"}:
        target = config.get("target_field") or config.get("output_field") or ("id" if node_type == "unique_id" else "llm_summary")
        generated_sources[target] = list(config.get("source_fields") or config.get("fields") or [])
    elif node_type in {"derive_geo_point", "derive_mgrs"}:
        target = config.get("target_field") or ("geometry" if node_type == "derive_geo_point" else "mgrs")
        generated_sources[target] = [config.get("latitude_field") or "latitude", config.get("longitude_field") or "longitude"]
    elif node_type == "window":
        target = config.get("target_field") or config.get("operation") or "row_number"
        generated_sources[target] = list(config.get("partition_by") or []) + [value for value in [config.get("order_by"), config.get("value_field") or config.get("field")] if value]
    elif node_type == "aggregate":
        metrics = config.get("metrics") or [{"field": config.get("field"), "alias": config.get("target_field") or config.get("alias") or "count"}]
        for metric in metrics:
            generated_sources[metric.get("alias") or metric.get("as") or "count"] = [metric.get("field")] if metric.get("field") else []
    elif node_type == "unpivot":
        generated_sources[config.get("name_field") or "field"] = list(config.get("value_fields") or [])
        generated_sources[config.get("value_field") or "value"] = list(config.get("value_fields") or [])
    elif node_type == "spatial_join":
        generated_sources[config.get("distance_field") or "distance_meters"] = [config.get("left_geometry_field") or "geometry", config.get("right_geometry_field") or "geometry"]

    result: Dict[str, List[Dict[str, Any]]] = {}
    for field in output_fields:
        source_field = rename_inverse.get(field, field)
        if field in generated_sources:
            origins = []
            for source in generated_sources[field]:
                origins.extend(combined.get(source, []))
        else:
            origins = combined.get(source_field, [])
        result[field] = _append_lineage_step(origins, node_id, node_type)
    return result


def _ontology_schema(db: Session, object_type: models.ObjectType) -> tuple[Dict[str, Dict[str, Any]], Optional[str]]:
    from . import ontology_core
    profile = db.get(ontology_core.ObjectTypeProfile, object_type.id)
    if profile and profile.properties:
        return dict(profile.properties), profile.primary_key
    manager = (object_type.properties or {}).get("__manager", {}) if isinstance(object_type.properties, dict) else {}
    properties = {
        name: spec if isinstance(spec, dict) else {"base_type": str(spec)}
        for name, spec in (object_type.properties or {}).items()
        if not str(name).startswith("__")
    }
    return properties, manager.get("primary_key") or manager.get("source_primary_key")


def _ontology_value_matches(value: Any, base_type: str) -> bool:
    if value is None:
        return True
    if base_type in {"string", "date", "timestamp", "attachment", "mediaReference", "timeSeries", "marking", "cipherText"}:
        return isinstance(value, str)
    if base_type in {"byte", "short", "integer", "long"}:
        return isinstance(value, int) and not isinstance(value, bool)
    if base_type in {"float", "double", "decimal", "number"}:
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if base_type == "boolean":
        return isinstance(value, bool)
    if base_type in {"array", "vector"}:
        return isinstance(value, list)
    if base_type in {"struct", "object", "json"}:
        return isinstance(value, dict)
    if base_type in {"geopoint", "geoshape", "geometry", "geojson"}:
        return isinstance(value, (dict, list, str))
    return True


def _quarantine_rows(db: Session, graph: PipelineBuilderGraph, node_id: str, asset_id: str, records: List[Dict[str, Any]]) -> str:
    now = _now()
    asset = db.get(models.DataAsset, asset_id)
    if asset and asset.project_id != graph.project_id:
        raise HTTPException(status_code=409, detail=f"Quarantine DataAsset '{asset_id}' belongs to another project")
    if not asset:
        asset = models.DataAsset(
            id=asset_id, project_id=graph.project_id, display_name=f"{graph.display_name} Quarantine",
            description=f"Rejected ontology rows from {graph.id}/{node_id}", kind="quarantine",
            asset_schema={"project_id": graph.project_id, "contract": "ontology_output_rejections"},
            records=[], created_at=now, updated_at=now,
        )
        db.add(asset)
        db.flush()
    _commit_snapshot_transaction(db, asset, records, "_row_index")
    return asset.id


def _execute_ontology_contract(
    db: Session,
    graph: PipelineBuilderGraph,
    node_id: str,
    config: Dict[str, Any],
    rows: List[Dict[str, Any]],
    source_lineage: Dict[str, List[Dict[str, Any]]],
    write_ontology: bool,
) -> Dict[str, Any]:
    object_type_id = str(config.get("object_type_id") or "")
    object_type = db.get(models.ObjectType, object_type_id) if object_type_id else None
    if not object_type:
        raise HTTPException(status_code=422, detail={"message": "Ontology output object type not found", "object_type_id": object_type_id})
    if object_type.project_id != graph.project_id:
        raise HTTPException(status_code=409, detail="Ontology output belongs to another project")
    properties, target_primary_key = _ontology_schema(db, object_type)
    primary_key = str(config.get("primary_key") or config.get("id_field") or target_primary_key or "id")
    mapping = config.get("property_mapping") or config.get("mapping") or {}
    if not mapping:
        mapping = {field: field for field in source_lineage if field in properties}
    write_mode = str(config.get("write_mode") or "upsert").lower()
    on_error = str(config.get("on_error") or "quarantine").lower()
    if write_mode not in {"upsert", "insert_only", "update_only"}:
        raise HTTPException(status_code=422, detail=f"Unsupported ontology write_mode '{write_mode}'")
    if on_error not in {"quarantine", "skip", "fail"}:
        raise HTTPException(status_code=422, detail=f"Unsupported ontology on_error '{on_error}'")
    unknown_targets = sorted({str(target) for target in mapping.values()} - set(properties))
    field_lineage = [
        {"source_field": source, "target_property": target, "origins": _append_lineage_step(source_lineage.get(source, []), node_id, "ontology_output")}
        for source, target in mapping.items()
    ]
    required_targets = {name for name, spec in properties.items() if isinstance(spec, dict) and spec.get("required")}
    accepted: List[tuple[int, Dict[str, Any], str, Dict[str, Any], Optional[models.ObjectInstance]]] = []
    violations: List[Dict[str, Any]] = []
    quarantine_records: List[Dict[str, Any]] = []
    created_count = updated_count = unchanged_count = 0
    for row_index, row in enumerate(rows):
        row_errors: List[Dict[str, Any]] = []
        object_id_value = _value(row, primary_key)
        if object_id_value in (None, ""):
            row_errors.append({"code": "PRIMARY_KEY_MISSING", "field": primary_key, "message": "Source primary key is missing"})
        for target in unknown_targets:
            row_errors.append({"code": "UNKNOWN_TARGET_PROPERTY", "field": target, "message": "Mapped ontology property does not exist"})
        mapped_properties = {str(target): _value(row, str(source)) for source, target in mapping.items() if str(target) in properties}
        if not mapping:
            mapped_properties = {name: _value(row, name) for name in properties if name in row}
        for target in required_targets:
            if mapped_properties.get(target) in (None, ""):
                row_errors.append({"code": "REQUIRED_PROPERTY_MISSING", "field": target, "message": "Required ontology property is missing"})
        for target, value in mapped_properties.items():
            spec = properties.get(target) or {}
            base_type = str(spec.get("base_type") or spec.get("type") or "string") if isinstance(spec, dict) else str(spec)
            if not _ontology_value_matches(value, base_type):
                row_errors.append({"code": "PROPERTY_TYPE_MISMATCH", "field": target, "message": f"Value is not compatible with {base_type}"})
        object_id = str(object_id_value) if object_id_value not in (None, "") else ""
        existing = db.get(models.ObjectInstance, object_id) if object_id else None
        if existing and (existing.project_id != graph.project_id or existing.object_type_id != object_type_id):
            row_errors.append({"code": "OBJECT_ID_CONFLICT", "field": primary_key, "message": "Object ID belongs to another type or project"})
        if write_mode == "insert_only" and existing:
            row_errors.append({"code": "INSERT_ONLY_CONFLICT", "field": primary_key, "message": "Object already exists"})
        if write_mode == "update_only" and not existing:
            row_errors.append({"code": "UPDATE_ONLY_MISSING", "field": primary_key, "message": "Object does not exist"})
        if row_errors:
            violation = {"row_index": row_index, "object_id": object_id or None, "errors": row_errors}
            violations.append(violation)
            quarantine_records.append({"_row_index": row_index, "_pipeline_graph_id": graph.id, "_node_id": node_id, "_object_type_id": object_type_id, "_errors": row_errors, "record": copy.deepcopy(row)})
        else:
            accepted.append((row_index, row, object_id, mapped_properties, existing))

    if violations and on_error == "fail":
        raise HTTPException(status_code=422, detail={"message": "Ontology contract rejected rows", "node_id": node_id, "rejected_rows": len(violations), "violations": violations[:25]})
    quarantine_asset_id = None
    if write_ontology and violations and on_error == "quarantine":
        quarantine_asset_id = _quarantine_rows(db, graph, node_id, str(config.get("quarantine_asset_id") or f"{graph.id}_{node_id}_quarantine"), quarantine_records)

    if write_ontology:
        from . import decision_intelligence, ontology_runtime_v1
        materialization_id = config.get("materialization_id")
        for _row_index, _row, object_id, mapped_properties, existing in accepted:
            if existing:
                before = dict(existing.properties or {})
                after = {**before, **mapped_properties}
                lifecycle_changed = bool(
                    materialization_id and (
                        existing.materialization_id != materialization_id
                        or not existing.is_active
                        or existing.retired_at is not None
                    )
                )
                if after == before and not lifecycle_changed:
                    unchanged_count += 1
                else:
                    was_active = existing.is_active
                    existing.properties = after
                    existing.source_asset_id = config.get("source_asset_id") or existing.source_asset_id
                    existing.materialization_id = materialization_id or existing.materialization_id
                    existing.is_active = True
                    existing.retired_at = None
                    existing.lineage = {
                        **(existing.lineage or {}), "pipeline_builder_graph_id": graph.id,
                        "node_id": node_id, "field_lineage": field_lineage,
                        **({
                            "materialization_id": materialization_id,
                            "materialization_active": True,
                            "retired_by_materialization_id": None,
                        } if materialization_id else {}),
                    }
                    existing.updated_at = _now()
                    updated_count += 1
                    event_type = "pipeline_builder.object.reactivated" if not was_active else (
                        "pipeline_builder.object.rematerialized" if after == before else "pipeline_builder.object.updated"
                    )
                    decision_intelligence.record_object_snapshot(db, existing, event_type=event_type, actor="pipeline_builder", source_type="pipeline_builder_graph", source_id=graph.id)
                    ontology_runtime_v1.record_object_change(
                        db, existing, before_state=before, event_type=event_type,
                        actor="pipeline_builder", source_type="pipeline_builder_graph", source_id=graph.id,
                        evidence={"node_id": node_id, "field_lineage": field_lineage, "materialization_id": materialization_id},
                    )
            else:
                created = object_writes.create_object(
                    db, object_id=object_id, project_id=graph.project_id,
                    object_type_id=object_type_id,
                    properties=mapped_properties, source_asset_id=config.get("source_asset_id"),
                    materialization_id=materialization_id, is_active=True, retired_at=None,
                    lineage={
                        "pipeline_builder_graph_id": graph.id, "node_id": node_id,
                        "field_lineage": field_lineage,
                        **({"materialization_id": materialization_id, "materialization_active": True} if materialization_id else {}),
                    },
                    actor="pipeline_builder",
                    event_type="pipeline_builder.object.created",
                    source_type="pipeline_builder_graph", source_id=graph.id,
                    evidence={"node_id": node_id, "field_lineage": field_lineage, "materialization_id": materialization_id},
                    now=_now(),
                )
                created_count += 1
    else:
        for _row_index, _row, _object_id, mapped_properties, existing in accepted:
            if not existing:
                created_count += 1
            elif {**(existing.properties or {}), **mapped_properties} == (existing.properties or {}):
                unchanged_count += 1
            else:
                updated_count += 1
    status = "SUCCESS" if not violations else ("PARTIAL" if accepted else "FAILED")
    return {
        "node_id": node_id, "object_type_id": object_type_id, "status": status,
        "input_rows": len(rows), "accepted_rows": len(accepted), "rejected_rows": len(violations),
        "created_objects": created_count, "updated_objects": updated_count, "unchanged_objects": unchanged_count,
        "quarantine_asset_id": quarantine_asset_id, "on_error": on_error, "write_mode": write_mode,
        "field_lineage": field_lineage, "violations": violations[:100],
    }


def _execute_graph(
    db: Session,
    graph: PipelineBuilderGraph,
    *,
    parameters: Optional[Dict[str, Any]] = None,
    write_ontology: bool = False,
) -> Dict[str, Any]:
    validation = _validate_graph(db, graph)
    if validation["errors"]:
        raise HTTPException(status_code=422, detail=validation["errors"])

    incoming = _predecessors(graph)
    ordered = _topological_nodes(graph)
    outputs: Dict[str, List[Dict[str, Any]]] = {}
    lineage_outputs: Dict[str, Dict[str, List[Dict[str, Any]]]] = {}
    current: List[Dict[str, Any]] = []
    final_node_id: Optional[str] = None
    step_metrics: List[Dict[str, Any]] = []
    input_asset_ids: List[str] = []
    materialized_objects = 0
    rejected_ontology_rows = 0
    ontology_contracts: List[Dict[str, Any]] = []

    for node_id, node in ordered:
        node_type = _node_type(node)
        config = {**_config(node), **((parameters or {}).get(node_id, {}) if isinstance((parameters or {}).get(node_id), dict) else {})}
        parents = [outputs[parent] for parent in incoming.get(node_id, []) if parent in outputs]
        parent_lineages = [lineage_outputs[parent] for parent in incoming.get(node_id, []) if parent in lineage_outputs]
        rows = copy.deepcopy(parents[0] if parents else current)
        records_in = len(rows)
        input_asset_for_lineage: Optional[str] = None

        if node_type in {"input_dataset", "dataset_input"}:
            asset_id = config.get("asset_id") or config.get("dataset_id")
            asset = db.get(models.DataAsset, asset_id)
            if not asset:
                raise HTTPException(status_code=404, detail=f"DataAsset '{asset_id}' not found")
            if asset.project_id != graph.project_id:
                raise HTTPException(status_code=409, detail=f"DataAsset '{asset_id}' belongs to another project")
            rows = copy.deepcopy(asset.records or [])
            input_asset_ids.append(asset.id)
            input_asset_for_lineage = asset.id
        elif node_type == "filter":
            rows = _filter_rows(rows, config)
        elif node_type in {"project", "select"}:
            rows = _project_rows(rows, config)
        elif node_type == "rename":
            rows = _rename_rows(rows, config)
        elif node_type == "cast":
            rows = _cast_rows(rows, config)
        elif node_type == "derive":
            rows = _derive_rows(rows, config)
        elif node_type == "fill_nulls":
            rows = _fill_nulls(rows, config)
        elif node_type == "normalize":
            rows = _normalize_rows(rows, config)
        elif node_type == "deduplicate":
            rows = _deduplicate_rows(rows, config)
        elif node_type == "join":
            right_rows = parents[1] if len(parents) > 1 else None
            if right_rows is None and config.get("right_asset_id"):
                right_asset = db.get(models.DataAsset, config["right_asset_id"])
                if not right_asset:
                    raise HTTPException(status_code=404, detail=f"DataAsset '{config['right_asset_id']}' not found")
                if right_asset.project_id != graph.project_id:
                    raise HTTPException(status_code=409, detail="Join dataset belongs to another project")
                right_rows = copy.deepcopy(right_asset.records or [])
            rows = _join_rows(rows, right_rows or [], config)
        elif node_type == "union":
            other_rows = parents[1] if len(parents) > 1 else []
            if config.get("asset_id"):
                other = db.get(models.DataAsset, config["asset_id"])
                if not other:
                    raise HTTPException(status_code=404, detail=f"DataAsset '{config['asset_id']}' not found")
                if other.project_id != graph.project_id:
                    raise HTTPException(status_code=409, detail="Union dataset belongs to another project")
                other_rows = copy.deepcopy(other.records or [])
            rows = rows + copy.deepcopy(other_rows)
        elif node_type == "aggregate":
            rows = _aggregate_rows(rows, config)
        elif node_type == "sort":
            field = config.get("field")
            rows = sorted(rows, key=lambda row: (_value(row, field) is None, _value(row, field)), reverse=str(config.get("direction", "")).lower() == "desc")
        elif node_type == "limit":
            rows = rows[: int(config.get("limit") or config.get("count") or len(rows))]
        elif node_type == "unique_id":
            target = config.get("target_field") or "id"
            fields = config.get("source_fields") or config.get("fields") or []
            rows = [{**row, target: row.get(target) or _stable_row_id(row, fields)} for row in rows]
        elif node_type == "pivot":
            rows = _pivot_rows(rows, config)
        elif node_type == "unpivot":
            rows = _unpivot_rows(rows, config)
        elif node_type == "window":
            rows = _window_rows(rows, config)
        elif node_type == "validate":
            rows = _validate_rows(rows, config)
        elif node_type == "derive_geo_point":
            rows = _derive_geo_rows(rows, config)
        elif node_type == "derive_mgrs":
            rows = _derive_mgrs_rows(rows, config)
        elif node_type == "spatial_filter":
            rows = _spatial_filter_rows(rows, config)
        elif node_type == "spatial_join":
            right_rows = parents[1] if len(parents) > 1 else []
            if config.get("right_asset_id"):
                right_asset = db.get(models.DataAsset, config["right_asset_id"])
                if not right_asset:
                    raise HTTPException(status_code=404, detail=f"DataAsset '{config['right_asset_id']}' not found")
                if right_asset.project_id != graph.project_id:
                    raise HTTPException(status_code=409, detail="Spatial join dataset belongs to another project")
                right_rows = copy.deepcopy(right_asset.records or [])
            rows = _spatial_join_rows(rows, right_rows, config)
        elif node_type in {"llm_assist", "llm"}:
            output_field = config.get("output_field") or "llm_summary"
            prompt = config.get("prompt") or "summarize"
            source_fields = config.get("source_fields") or []
            rows = [
                {
                    **row,
                    output_field: f"{prompt}: " + " | ".join(str(_value(row, field)) for field in source_fields if _value(row, field) is not None)[:240],
                }
                for row in rows
            ]
        elif node_type == "ontology_output":
            pass
        elif node_type in {"dataset_output", "output_dataset"}:
            final_node_id = node_id

        node_lineage = _field_lineage_for_node(node_id, node_type, config, rows, parent_lineages, input_asset_for_lineage)
        if node_type == "ontology_output":
            contract = _execute_ontology_contract(db, graph, node_id, config, rows, node_lineage, write_ontology)
            ontology_contracts.append(contract)
            if write_ontology:
                materialized_objects += contract["created_objects"] + contract["updated_objects"] + contract["unchanged_objects"]
                rejected_ontology_rows += contract["rejected_rows"]
        outputs[node_id] = rows
        lineage_outputs[node_id] = node_lineage
        current = rows
        step_metrics.append({
            "node_id": node_id,
            "type": node_type,
            "records_in": records_in,
            "records_out": len(rows),
        })

    return {
        "graph_id": graph.id,
        "input_asset_ids": input_asset_ids,
        "final_node_id": final_node_id or (ordered[-1][0] if ordered else None),
        "rows": current,
        "node_outputs": {
            node_id: {"row_count": len(rows), "schema": _schema(rows), "sample": rows[:5], "field_lineage": lineage_outputs.get(node_id, {})}
            for node_id, rows in outputs.items()
        },
        "lineage": {"graph_id": graph.id, "steps": step_metrics, "input_asset_ids": input_asset_ids, "fields_by_node": lineage_outputs},
        "ontology_contracts": ontology_contracts,
        "metrics": {"records_out": len(current), "materialized_objects": materialized_objects, "rejected_ontology_rows": rejected_ontology_rows, "steps": len(step_metrics)},
    }


def _output_asset_id(graph: PipelineBuilderGraph, override: Optional[str]) -> str:
    if override:
        return override
    for node in graph.nodes or []:
        if _node_type(node) in {"dataset_output", "output_dataset"}:
            config = _config(node)
            return config.get("asset_id") or config.get("dataset_id") or config.get("output_asset_id") or f"{graph.id}_output"
    return f"{graph.id}_output"


def _commit_snapshot_transaction(db: Session, asset: models.DataAsset, rows: List[Dict[str, Any]], primary_key: str) -> DatasetTransaction:
    txn = DatasetTransaction(
        id=_new_id(),
        dataset_id=asset.id,
        branch="master",
        txn_type="SNAPSHOT",
        primary_key=primary_key,
        records=rows,
        row_count=len(rows),
        status="COMMITTED",
        seq=_next_seq(db, asset.id, "master"),
        created_at=_now(),
    )
    db.add(txn)
    asset.records = _fold(_txns_for(db, asset.id, "master") + [txn])
    project_id = str((asset.asset_schema or {}).get("project_id") or "default")
    asset.asset_schema = {**_schema(asset.records or []), "project_id": project_id}
    asset.updated_at = _now()
    return txn


@router.post("/pipeline-builder/graphs", response_model=PipelineGraphRead, status_code=201)
def create_graph(body: PipelineGraphCreate, principal: Principal = Depends(require_permission("edit")), db: Session = Depends(get_db)):
    tenancy.assert_project_permission(db, principal, body.project_id, "edit")
    graph_id = body.id or _new_id()
    if db.get(PipelineBuilderGraph, graph_id):
        raise HTTPException(status_code=400, detail="PipelineBuilderGraph already exists")
    now = _now()
    graph = PipelineBuilderGraph(
        id=graph_id,
        project_id=body.project_id,
        display_name=body.display_name,
        description=body.description,
        nodes=body.nodes,
        edges=body.edges,
        parameters=body.parameters,
        status=body.status,
        created_at=now,
        updated_at=now,
    )
    db.add(graph)
    db.commit()
    db.refresh(graph)
    return graph


@router.get("/pipeline-builder/graphs", response_model=List[PipelineGraphRead])
def list_graphs(project_id: Optional[str] = None, principal: Principal = Depends(require_permission("view")), db: Session = Depends(get_db)):
    query = _accessible_graphs(db, principal, "view")
    if project_id:
        tenancy.assert_project_permission(db, principal, project_id, "view")
        query = query.filter(PipelineBuilderGraph.project_id == project_id)
    return query.order_by(PipelineBuilderGraph.updated_at.desc()).all()


@router.get("/pipeline-builder/graphs/{graph_id}", response_model=PipelineGraphRead)
def get_graph(graph_id: str, principal: Principal = Depends(require_permission("view")), db: Session = Depends(get_db)):
    return _graph_for(db, graph_id, principal, "view")


@router.get("/ui-state/pipeline/{graph_id}/canvas")
def pipeline_canvas_state(graph_id: str, selected_node_id: Optional[str] = None, principal: Principal = Depends(require_permission("view")), db: Session = Depends(get_db)):
    graph = _graph_for(db, graph_id, principal, "view")
    return _canvas_payload(db, graph, selected_node_id=selected_node_id)


@router.get("/ui-state/pipeline/{graph_id}/nodes/{node_id}/details")
def pipeline_node_details(graph_id: str, node_id: str, principal: Principal = Depends(require_permission("view")), db: Session = Depends(get_db)):
    graph = _graph_for(db, graph_id, principal, "view")
    return _node_details_payload(db, graph, node_id)


@router.get("/ui-state/pipeline/{graph_id}/outputs")
def pipeline_outputs_state(graph_id: str, principal: Principal = Depends(require_permission("view")), db: Session = Depends(get_db)):
    graph = _graph_for(db, graph_id, principal, "view")
    canvas = _canvas_payload(db, graph)
    return {
        "graph_id": graph.id,
        "outputs": canvas.get("outputs", {}),
        "validation": canvas.get("validation", {}),
        "legend": canvas.get("legend", []),
        "actions": canvas.get("actions", []),
        "summary": {
            "output_count": len(canvas.get("outputs", {}).get("nodes", []) or []),
            "output_node_count": len(canvas.get("outputs", {}).get("nodes", []) or []),
            "build_count": len(canvas.get("outputs", {}).get("builds", []) or []),
            "status": canvas.get("validation", {}).get("status", graph.status),
        },
    }


@router.patch("/pipeline-builder/graphs/{graph_id}", response_model=PipelineGraphRead)
def update_graph(graph_id: str, body: PipelineGraphUpdate, principal: Principal = Depends(require_permission("edit")), db: Session = Depends(get_db)):
    graph = _graph_for(db, graph_id, principal, "edit")
    patch = body.model_dump(exclude_unset=True)
    for field, value in patch.items():
        setattr(graph, field, value)
    if patch:
        graph.updated_at = _now()
    db.commit()
    db.refresh(graph)
    return graph


@router.patch("/pipeline-builder/graphs/{graph_id}/layout")
def update_graph_layout(graph_id: str, body: PipelineLayoutRequest, principal: Principal = Depends(require_permission("edit")), db: Session = Depends(get_db)):
    graph = _graph_for(db, graph_id, principal, "edit")
    positions = dict(body.positions or {})
    for item in body.nodes or []:
        node_id = str(item.get("id") or item.get("node_id") or "")
        position = item.get("position") if isinstance(item.get("position"), dict) else item
        if node_id:
            positions[node_id] = {
                "x": float(position.get("x", 0)),
                "y": float(position.get("y", 0)),
            }
    updated_nodes = []
    for index, node in enumerate(graph.nodes or []):
        node_id = _node_id(node, index)
        next_node = copy.deepcopy(node)
        if node_id in positions:
            position = positions[node_id]
            next_node["position"] = {"x": float(position.get("x", 0)), "y": float(position.get("y", 0))}
        updated_nodes.append(next_node)
    graph.nodes = updated_nodes
    graph.updated_at = _now()
    _audit_graph(db, principal.id, "pipeline_builder.graph.layout_updated", graph, {"positions": positions})
    db.commit()
    db.refresh(graph)
    return _canvas_payload(db, graph)


@router.patch("/pipeline-builder/graphs/{graph_id}/nodes/{node_id}")
def update_pipeline_node(graph_id: str, node_id: str, body: PipelineNodeUpdateRequest, principal: Principal = Depends(require_permission("edit")), db: Session = Depends(get_db)):
    graph = _graph_for(db, graph_id, principal, "edit")
    index, node = _find_node(graph, node_id)
    next_node = copy.deepcopy(node)
    if body.label is not None:
        label = body.label.strip()
        if not label:
            raise HTTPException(status_code=422, detail="Node label cannot be empty")
        next_node["label"] = label
    if body.config is not None:
        normalized_config = _normalize_node_config(_node_type(node), body.config)
        validation = _validate_node_config(_node_type(node), normalized_config)
        if validation["status"] == "INVALID":
            raise HTTPException(status_code=422, detail={"message": "Node configuration is invalid", "validation": validation})
        next_node["config"] = normalized_config
    nodes = list(graph.nodes or [])
    nodes[index] = next_node
    graph.nodes = nodes
    graph.updated_at = _now()
    _audit_graph(db, principal.id, "pipeline_builder.node.updated", graph, {
        "node_id": node_id, "node_type": _node_type(node), "config_fields": sorted((body.config or {}).keys()),
    })
    db.commit()
    db.refresh(graph)
    return _node_details_payload(db, graph, node_id)


@router.post("/pipeline-builder/graphs/{graph_id}/nodes")
def create_pipeline_node(graph_id: str, body: PipelineCreateNodeRequest, principal: Principal = Depends(require_permission("edit")), db: Session = Depends(get_db)):
    graph = _graph_for(db, graph_id, principal, "edit")
    new_node = _node_from_request(graph, body, {"x": 180, "y": 180})
    next_edges = [copy.deepcopy(edge) for edge in graph.edges or []]
    if body.connect_from_node_id:
        _find_node(graph, body.connect_from_node_id)
        next_edges.append({
            "source": body.connect_from_node_id,
            "target": new_node["id"],
            "source_port": "output",
            "target_port": "input",
        })
    graph.nodes = [copy.deepcopy(node) for node in graph.nodes or []] + [new_node]
    graph.edges = next_edges
    graph.updated_at = _now()
    _audit_graph(db, principal.id, "pipeline_builder.node.created", graph, {
        "node_id": new_node["id"],
        "node_type": new_node["type"],
        "position": new_node["position"],
        "connect_from_node_id": body.connect_from_node_id,
    })
    db.commit()
    db.refresh(graph)
    return _canvas_payload(db, graph, selected_node_id=new_node["id"])


@router.post("/pipeline-builder/graphs/{graph_id}/nodes/{node_id}/insert-after")
def insert_node_after(graph_id: str, node_id: str, body: PipelineInsertNodeRequest, principal: Principal = Depends(require_permission("edit")), db: Session = Depends(get_db)):
    graph = _graph_for(db, graph_id, principal, "edit")
    source_index, source_node = _find_node(graph, node_id)
    source_position = _node_position(source_node, source_index)
    new_node = _node_from_request(graph, body, {"x": source_position["x"] + 260, "y": source_position["y"]})
    outgoing = [edge for edge in graph.edges or [] if _edge_source(edge) == node_id]
    preserved_edges = [edge for edge in graph.edges or [] if _edge_source(edge) != node_id]
    next_edges = preserved_edges + [{"source": node_id, "target": new_node["id"], "source_port": "output", "target_port": "input"}]
    if outgoing:
        for edge in outgoing:
            next_edges.append({
                **copy.deepcopy(edge),
                "source": new_node["id"],
                "from": new_node["id"] if "from" in edge else edge.get("from"),
                "target": _edge_target(edge),
                "to": _edge_target(edge) if "to" in edge else edge.get("to"),
            })
    graph.nodes = (graph.nodes or []) + [new_node]
    graph.edges = next_edges
    graph.updated_at = _now()
    _audit_graph(db, principal.id, "pipeline_builder.node.inserted", graph, {
        "node_id": new_node["id"],
        "node_type": new_node["type"],
        "inserted_after": node_id,
    })
    db.commit()
    db.refresh(graph)
    return _canvas_payload(db, graph, selected_node_id=new_node["id"])


@router.delete("/pipeline-builder/graphs/{graph_id}/nodes/{node_id}")
def delete_pipeline_node(graph_id: str, node_id: str, principal: Principal = Depends(require_permission("edit")), db: Session = Depends(get_db)):
    graph = _graph_for(db, graph_id, principal, "edit")
    _find_node(graph, node_id)
    incoming = [copy.deepcopy(edge) for edge in graph.edges or [] if _edge_target(edge) == node_id]
    outgoing = [copy.deepcopy(edge) for edge in graph.edges or [] if _edge_source(edge) == node_id]
    next_edges = [
        copy.deepcopy(edge)
        for edge in graph.edges or []
        if _edge_source(edge) != node_id and _edge_target(edge) != node_id
    ]
    reconnected = False
    if len(incoming) == 1 and len(outgoing) == 1:
        source = _edge_source(incoming[0])
        target = _edge_target(outgoing[0])
        if source and target and source != target and not _edge_exists(next_edges, source, target):
            next_edges.append({
                "source": source,
                "target": target,
                "source_port": incoming[0].get("source_port") or "output",
                "target_port": outgoing[0].get("target_port") or "input",
            })
            reconnected = True
    graph.nodes = [
        copy.deepcopy(node)
        for index, node in enumerate(graph.nodes or [])
        if _node_id(node, index) != node_id
    ]
    graph.edges = next_edges
    graph.updated_at = _now()
    _audit_graph(db, principal.id, "pipeline_builder.node.deleted", graph, {
        "node_id": node_id,
        "incoming_edges": len(incoming),
        "outgoing_edges": len(outgoing),
        "reconnected": reconnected,
    })
    db.commit()
    db.refresh(graph)
    return _canvas_payload(db, graph)


@router.post("/pipeline-builder/graphs/{graph_id}/nodes/{node_id}/preview")
def preview_pipeline_node(graph_id: str, node_id: str, body: PipelineNodePreviewRequest = PipelineNodePreviewRequest(), principal: Principal = Depends(require_permission("execute")), db: Session = Depends(get_db)):
    graph = _graph_for(db, graph_id, principal, "execute")
    _find_node(graph, node_id)
    execution = _execute_graph(db, graph, parameters=body.parameters, write_ontology=False)
    output = execution["node_outputs"].get(node_id)
    if output is None:
        raise HTTPException(status_code=404, detail=f"Node '{node_id}' did not produce preview rows")
    limit = max(1, min(int(body.limit), 500))
    rows = output.get("sample", [])[:limit]
    schema = output.get("schema", {"fields": []})
    return {
        "graph_id": graph.id,
        "node_id": node_id,
        "status": "PREVIEW_READY",
        "row_count": output.get("row_count", 0),
        "rows": rows,
        "schema": schema,
        "columns": schema.get("fields", []),
        "lineage": execution.get("lineage", {}),
        "metrics": execution.get("metrics", {}),
    }


@router.post("/pipeline-builder/graphs/{graph_id}/nodes/{node_id}/suggestions")
def suggest_pipeline_node_actions(graph_id: str, node_id: str, principal: Principal = Depends(require_permission("view")), db: Session = Depends(get_db)):
    graph = _graph_for(db, graph_id, principal, "view")
    return _node_suggestions_payload(db, graph, node_id)


@router.post("/pipeline-builder/graphs/{graph_id}/validate")
def validate_graph(graph_id: str, principal: Principal = Depends(require_permission("execute")), db: Session = Depends(get_db)):
    graph = _graph_for(db, graph_id, principal, "execute")
    validation = _validate_graph(db, graph)
    try:
        from . import ops_control
        ops_control.record_ops_event(
            db,
            source="pipeline_builder",
            event_type="pipeline_builder.graph.validated",
            severity="high" if validation.get("status") == "INVALID" else "info",
            title=f"Pipeline graph {graph.display_name} validation {validation.get('status')}",
            subject_type="pipeline_builder_graph",
            subject_id=graph.id,
            payload=validation,
        )
        db.commit()
    except Exception:
        db.rollback()
    return validation


@router.post("/pipeline-builder/graphs/{graph_id}/preview/async", status_code=202)
def enqueue_graph_preview(graph_id: str, body: PipelineAsyncPreviewRequest = PipelineAsyncPreviewRequest(), principal: Principal = Depends(require_permission("execute")), db: Session = Depends(get_db)):
    graph = _graph_for(db, graph_id, principal, "execute")
    return platform_runtime.create_job(platform_runtime.JobCreate(
        project_id=graph.project_id,
        job_type="pipeline.preview",
        subject_type="pipeline_builder_graph",
        subject_id=graph.id,
        payload={"graph_id": graph.id, "limit": body.limit, "parameters": body.parameters},
        priority=body.priority,
        max_attempts=body.max_attempts,
        timeout_seconds=body.timeout_seconds,
        idempotency_key=body.idempotency_key,
    ), principal, db)


@router.post("/pipeline-builder/graphs/{graph_id}/deliver/async", status_code=202)
def enqueue_graph_delivery(graph_id: str, body: PipelineAsyncDeliverRequest = PipelineAsyncDeliverRequest(), principal: Principal = Depends(require_permission("deploy")), db: Session = Depends(get_db)):
    graph = _graph_for(db, graph_id, principal, "deploy")
    return platform_runtime.create_job(platform_runtime.JobCreate(
        project_id=graph.project_id,
        job_type="pipeline.deliver",
        subject_type="pipeline_builder_graph",
        subject_id=graph.id,
        payload={
            "graph_id": graph.id,
            "output_asset_id": body.output_asset_id,
            "actor": principal.id,
            "primary_key": body.primary_key,
            "parameters": body.parameters,
        },
        priority=body.priority,
        max_attempts=body.max_attempts,
        timeout_seconds=body.timeout_seconds,
        idempotency_key=body.idempotency_key,
    ), principal, db)


@router.post("/pipeline-builder/workers/run-next")
def run_next_pipeline_job(body: PipelineWorkerRunRequest = PipelineWorkerRunRequest(), principal: Principal = Depends(require_permission("execute")), db: Session = Depends(get_db)):
    from . import worker_control
    supported_job_types = worker_control.effective_worker_job_types(
        db, principal, body.worker_id, [
            "pipeline.preview", "pipeline.deliver",
            "pipeline.duckdb.preview", "pipeline.duckdb.deliver",
            "pipeline.duckdb.partition", "pipeline.duckdb.finalize",
            "industrial.ontology_hydrate",
        ],
    )
    claim_result = platform_runtime.claim_job(platform_runtime.JobClaimRequest(
        worker_id=body.worker_id,
        supported_job_types=supported_job_types,
        lease_seconds=body.lease_seconds,
        job_id=body.job_id,
    ), principal, db)
    claimed = claim_result.get("job")
    if not claimed:
        return {"job": None, "result": None}

    job_id = str(claimed["id"])
    lease_token = str(claimed["lease_token"])
    payload = dict(claimed.get("payload") or {})
    graph_id = str(payload.get("graph_id") or claimed.get("subject_id") or "")
    try:
        graph = _graph_for(db, graph_id, principal, "execute")
        validation = _validate_graph(db, graph)
        if validation.get("errors"):
            failed = platform_runtime.fail_job(job_id, platform_runtime.JobFailRequest(
                lease_token=lease_token,
                error="Pipeline validation failed",
                retriable=False,
                details={"validation": validation},
            ), principal, db)
            return {"job": failed, "result": None}

        platform_runtime.heartbeat_job(job_id, platform_runtime.JobHeartbeatRequest(
            lease_token=lease_token,
            progress=15,
            message="Pipeline validated; preparing deterministic execution",
            metrics={"node_count": len(graph.nodes or []), "edge_count": len(graph.edges or [])},
            lease_seconds=body.lease_seconds,
        ), principal, db)

        if claimed["job_type"] == "industrial.ontology_hydrate":
            from . import industrial_workflow
            industrial_lease_seconds = max(body.lease_seconds, 900)
            platform_runtime.heartbeat_job(job_id, platform_runtime.JobHeartbeatRequest(
                lease_token=lease_token, progress=20,
                message="Industrial contract compiled; delivering immutable snapshot",
                metrics={"source_snapshot_id": payload.get("source_snapshot_id")},
                lease_seconds=industrial_lease_seconds,
            ), principal, db)
            result = industrial_workflow.execute_industrial_onboarding_job(
                db, payload=payload, actor=principal.id, job_id=job_id,
                lease_token=lease_token, lease_seconds=industrial_lease_seconds,
                principal=principal,
            )
        elif claimed["job_type"] == "pipeline.duckdb.partition":
            from . import data_plane
            result = data_plane.execute_duckdb_snapshot_partition(
                db,
                str(payload.get("plan_id") or claimed.get("subject_id") or ""),
                source_snapshot_id=str(payload.get("source_snapshot_id") or ""),
                source_files=list(payload.get("source_files") or []),
                parameters=dict(payload.get("parameters") or {}),
                execution_group_id=str(payload.get("execution_group_id") or ""),
                partition_index=int(payload.get("partition_index") or 0),
                partition_count=int(payload.get("partition_count") or 0),
                actor=principal.id,
                expected_project_id=str(claimed.get("project_id") or ""),
            )
        elif claimed["job_type"] == "pipeline.duckdb.finalize":
            from . import data_plane
            result = data_plane.finalize_duckdb_snapshot_partitions(
                db,
                str(payload.get("plan_id") or claimed.get("subject_id") or ""),
                partition_job_ids=list(payload.get("partition_job_ids") or []),
                source_snapshot_id=str(payload.get("source_snapshot_id") or ""),
                output_asset_id=payload.get("output_asset_id"),
                parameters=dict(payload.get("parameters") or {}),
                execution_group_id=str(payload.get("execution_group_id") or ""),
                actor=principal.id,
                execution_job_id=job_id,
                execution_lease_token=lease_token,
            )
        elif claimed["job_type"].startswith("pipeline.duckdb."):
            from . import data_plane
            result = data_plane.execute_duckdb_snapshot_plan(
                db,
                str(payload.get("plan_id") or claimed.get("subject_id") or ""),
                mode="deliver" if claimed["job_type"] == "pipeline.duckdb.deliver" else "preview",
                limit=int(payload.get("limit") or 100), output_asset_id=payload.get("output_asset_id"),
                parameters=dict(payload.get("parameters") or {}), actor=principal.id,
                execution_job_id=job_id, execution_fence_job_id=job_id,
                execution_lease_token=lease_token,
                # The payload names the plan; only the job's own project was authorized.
                expected_project_id=str(claimed.get("project_id") or ""),
            )
        elif claimed["job_type"] == "pipeline.preview":
            result = preview_graph(graph_id, PipelinePreviewRequest(
                limit=int(payload.get("limit") or 50),
                parameters=dict(payload.get("parameters") or {}),
            ), principal, db)
        else:
            result = deliver_graph(graph_id, PipelineDeliverRequest(
                output_asset_id=payload.get("output_asset_id"),
                actor=str(payload.get("actor") or principal.id),
                primary_key=str(payload.get("primary_key") or "id"),
                parameters=dict(payload.get("parameters") or {}),
                execution_job_id=job_id,
                execution_lease_token=lease_token,
            ), principal, db)

        db.expire_all()
        current = db.get(platform_runtime.PlatformJob, job_id)
        if current and current.status == "CANCELLED":
            return {"job": platform_runtime.get_job(job_id, principal, db), "result": None}
        completed = platform_runtime.complete_job(job_id, platform_runtime.JobCompleteRequest(
            lease_token=lease_token,
            result=result,
        ), principal, db)
        return {"job": completed, "result": result}
    except HTTPException as exc:
        db.rollback()
        current = db.get(platform_runtime.PlatformJob, job_id)
        if not current or current.status != "RUNNING":
            return {"job": platform_runtime.get_job(job_id, principal, db) if current else None, "result": None}
        failed = platform_runtime.fail_job(job_id, platform_runtime.JobFailRequest(
            lease_token=lease_token,
            error=str(exc.detail),
            retriable=exc.status_code >= 500,
            details={"status_code": exc.status_code},
        ), principal, db)
        return {"job": failed, "result": None}
    except Exception as exc:
        db.rollback()
        current = db.get(platform_runtime.PlatformJob, job_id)
        if not current or current.status != "RUNNING":
            return {"job": platform_runtime.get_job(job_id, principal, db) if current else None, "result": None}
        failed = platform_runtime.fail_job(job_id, platform_runtime.JobFailRequest(
            lease_token=lease_token,
            error=str(exc),
            retriable=True,
            details={"exception_type": type(exc).__name__},
        ), principal, db)
        return {"job": failed, "result": None}


@router.post("/pipeline-builder/graphs/{graph_id}/preview")
def preview_graph(graph_id: str, body: PipelinePreviewRequest = PipelinePreviewRequest(), principal: Principal = Depends(require_permission("execute")), db: Session = Depends(get_db)):
    graph = _graph_for(db, graph_id, principal, "execute")
    execution = _execute_graph(db, graph, parameters=body.parameters, write_ontology=False)
    limit = max(1, min(int(body.limit), 500))
    result = {
        "graph_id": graph.id,
        "status": "PREVIEW_READY",
        "row_count": len(execution["rows"]),
        "rows": execution["rows"][:limit],
        "schema": _schema(execution["rows"]),
        "node_outputs": execution["node_outputs"],
        "lineage": execution["lineage"],
        "ontology_contracts": execution["ontology_contracts"],
        "metrics": execution["metrics"],
    }
    try:
        from . import ops_control
        ops_control.record_ops_event(
            db,
            source="pipeline_builder",
            event_type="pipeline_builder.graph.previewed",
            severity="info",
            title=f"Pipeline graph {graph.display_name} previewed",
            subject_type="pipeline_builder_graph",
            subject_id=graph.id,
            payload={"project_id": graph.project_id, "row_count": result["row_count"], "schema": result["schema"]},
        )
        db.commit()
    except Exception:
        db.rollback()
    return result


@router.post("/pipeline-builder/graphs/{graph_id}/deliver")
def deliver_graph(graph_id: str, body: PipelineDeliverRequest = PipelineDeliverRequest(), principal: Principal = Depends(require_permission("deploy")), db: Session = Depends(get_db)):
    graph = _graph_for(db, graph_id, principal, "execute" if body.execution_job_id else "deploy")
    if body.execution_job_id:
        prior_builds = db.query(PipelineBuilderBuild).filter(PipelineBuilderBuild.graph_id == graph.id).order_by(PipelineBuilderBuild.created_at.desc()).all()
        prior = next((build for build in prior_builds if (build.metrics or {}).get("execution_job_id") == body.execution_job_id), None)
        if prior:
            return {
                "graph_id": graph.id,
                "status": "DELIVERED",
                "run_id": prior.run_id,
                "build_id": prior.id,
                "output_asset_id": prior.output_asset_id,
                "transaction_id": (prior.metrics or {}).get("transaction_id"),
                "records_out": (prior.preview or {}).get("row_count", 0),
                "lineage": prior.lineage or {},
                "metrics": prior.metrics or {},
                "idempotent_replay": True,
            }
    execution = _execute_graph(db, graph, parameters=body.parameters, write_ontology=True)
    output_asset_id = _output_asset_id(graph, body.output_asset_id)
    now = _now()
    asset = db.get(models.DataAsset, output_asset_id)
    if asset and asset.project_id != graph.project_id:
        raise HTTPException(status_code=409, detail="Output DataAsset ID is owned by another project")
    if not asset:
        asset = models.DataAsset(
            id=output_asset_id,
            project_id=graph.project_id,
            display_name=f"{graph.display_name} Output",
            description=f"Delivered output from Pipeline Builder graph {graph.id}",
            kind="dataset",
            asset_schema={"project_id": graph.project_id},
            records=[],
            created_at=now,
            updated_at=now,
        )
        db.add(asset)

    input_asset_id = execution["input_asset_ids"][0] if execution["input_asset_ids"] else output_asset_id
    pipeline = db.get(models.PipelineDefinition, graph.id)
    if pipeline and pipeline.project_id != graph.project_id:
        raise HTTPException(status_code=409, detail="Pipeline ID is owned by another project")
    if not pipeline:
        pipeline = models.PipelineDefinition(
            id=graph.id,
            project_id=graph.project_id,
            display_name=graph.display_name,
            description=graph.description,
            input_asset_id=input_asset_id,
            output_asset_id=output_asset_id,
            mode="batch",
            schedule=None,
            steps=[{"operation": _node_type(node), **_config(node)} for node in graph.nodes or [] if _node_type(node) not in {"input_dataset", "dataset_input", "dataset_output", "output_dataset"}],
            created_at=now,
            updated_at=now,
        )
        db.add(pipeline)
    else:
        pipeline.display_name = graph.display_name
        pipeline.description = graph.description
        pipeline.input_asset_id = input_asset_id
        pipeline.output_asset_id = output_asset_id
        pipeline.steps = [{"operation": _node_type(node), **_config(node)} for node in graph.nodes or []]
        pipeline.updated_at = now

    run = models.PipelineRun(
        id=_new_id(),
        project_id=graph.project_id,
        pipeline_id=pipeline.id,
        status="SUCCESS",
        input_asset_id=input_asset_id,
        output_asset_id=output_asset_id,
        records_in=0,
        records_out=len(execution["rows"]),
        lineage=execution["lineage"],
        metrics=execution["metrics"],
        error=None,
        created_at=now,
        completed_at=now,
    )
    db.add(run)
    txn = _commit_snapshot_transaction(db, asset, execution["rows"], body.primary_key)
    build = PipelineBuilderBuild(
        id=_new_id(),
        graph_id=graph.id,
        status="SUCCESS",
        run_id=run.id,
        output_asset_id=asset.id,
        preview={"row_count": len(execution["rows"]), "rows": execution["rows"][:10], "schema": _schema(execution["rows"])},
        lineage=execution["lineage"],
        metrics={**execution["metrics"], "transaction_id": txn.id, "execution_job_id": body.execution_job_id},
        created_at=now,
    )
    db.add(build)
    contract_run_ids: List[str] = []
    previous_contract = db.query(PipelineOntologyContractRun).filter(
        PipelineOntologyContractRun.graph_id == graph.id,
    ).order_by(PipelineOntologyContractRun.created_at.desc()).first()
    contract_created_at = max(now, (previous_contract.created_at + 1) if previous_contract else now)
    for contract in execution.get("ontology_contracts", []):
        contract_row = PipelineOntologyContractRun(
            id=_new_id(), project_id=graph.project_id, graph_id=graph.id, build_id=build.id,
            node_id=contract["node_id"], object_type_id=contract["object_type_id"], status=contract["status"],
            input_rows=contract["input_rows"], accepted_rows=contract["accepted_rows"], rejected_rows=contract["rejected_rows"],
            created_objects=contract["created_objects"], updated_objects=contract["updated_objects"], unchanged_objects=contract["unchanged_objects"],
            quarantine_asset_id=contract.get("quarantine_asset_id"), field_lineage=contract.get("field_lineage") or [],
            violations=contract.get("violations") or [], created_at=contract_created_at,
        )
        db.add(contract_row)
        contract_run_ids.append(contract_row.id)
        db.add(models_action.AuditLog(
            id=_new_id(), actor=principal.id, event_type="pipeline_builder.ontology_contract.evaluated",
            subject_type="pipeline_ontology_contract_run", subject_id=contract_row.id,
            payload={"project_id": graph.project_id, "graph_id": graph.id, "build_id": build.id, "status": contract_row.status, "accepted_rows": contract_row.accepted_rows, "rejected_rows": contract_row.rejected_rows, "quarantine_asset_id": contract_row.quarantine_asset_id},
        ))
        try:
            from . import ops_control
            ops_control.record_ops_event(
                db, source="pipeline_builder", event_type="pipeline_builder.ontology_contract.evaluated",
                severity="high" if contract_row.status == "FAILED" else ("medium" if contract_row.status == "PARTIAL" else "info"),
                title=f"Ontology contract {contract_row.status} for {contract_row.object_type_id}",
                subject_type="pipeline_ontology_contract_run", subject_id=contract_row.id,
                object_type_id=contract_row.object_type_id,
                payload={"project_id": graph.project_id, "graph_id": graph.id, "build_id": build.id, "accepted_rows": contract_row.accepted_rows, "rejected_rows": contract_row.rejected_rows, "quarantine_asset_id": contract_row.quarantine_asset_id},
                evaluate_alerts=True,
            )
        except Exception:
            pass
        contract_created_at += 1
    build.metrics = {**(build.metrics or {}), "ontology_contract_run_ids": contract_run_ids}
    run.metrics = {**(run.metrics or {}), "ontology_contract_run_ids": contract_run_ids}
    from . import ontology_runtime_v1
    contract_binding = ontology_runtime_v1.bind_ontology_contract(
        db,
        project_id=graph.project_id,
        consumer_kind="pipeline",
        consumer_id=graph.id,
        consumer_version=build.id,
        payload={"nodes": graph.nodes or [], "edges": graph.edges or []},
        actor=principal.id,
    )
    build.metrics = {**(build.metrics or {}), "ontology_revision_id": contract_binding.get("ontology_revision_id"), "ontology_binding_count": contract_binding.get("binding_count", 0)}
    run.metrics = {**(run.metrics or {}), "ontology_revision_id": contract_binding.get("ontology_revision_id"), "ontology_binding_count": contract_binding.get("binding_count", 0)}
    db.add(models_action.AuditLog(
        id=_new_id(),
        actor=principal.id,
        event_type="pipeline_builder.graph.delivered",
        subject_type="pipeline_builder_graph",
        subject_id=graph.id,
        payload={"project_id": graph.project_id, "run_id": run.id, "output_asset_id": asset.id, "records_out": len(execution["rows"])},
    ))
    try:
        from . import ops_control
        ops_control.record_ops_event(
            db,
            source="pipeline_builder",
            event_type="pipeline_builder.graph.delivered",
            severity="info",
            title=f"Pipeline graph {graph.display_name} delivered",
            subject_type="pipeline_builder_graph",
            subject_id=graph.id,
            payload={"project_id": graph.project_id, "run_id": run.id, "output_asset_id": asset.id, "records_out": len(execution["rows"])},
        )
    except Exception:
        pass
    graph.status = "DELIVERED"
    graph.updated_at = now
    if body.execution_job_id:
        db.flush()
        active_job = db.query(platform_runtime.PlatformJob).filter(
            platform_runtime.PlatformJob.id == body.execution_job_id,
        ).with_for_update().first()
        active_lease = db.query(platform_runtime.PlatformJobLease).filter(
            platform_runtime.PlatformJobLease.job_id == body.execution_job_id,
        ).with_for_update().first()
        if (
            not active_job
            or active_job.status != "RUNNING"
            or not active_lease
            or active_lease.token != body.execution_lease_token
            or active_lease.expires_at <= _now()
        ):
            db.rollback()
            raise HTTPException(status_code=409, detail="Pipeline delivery was cancelled or lost its worker lease before commit")
    db.commit()
    return {
        "graph_id": graph.id,
        "status": "DELIVERED",
        "run_id": run.id,
        "build_id": build.id,
        "output_asset_id": asset.id,
        "transaction_id": txn.id,
        "records_out": len(execution["rows"]),
        "lineage": execution["lineage"],
        "metrics": build.metrics,
    }


@router.get("/pipeline-builder/graphs/{graph_id}/ontology-contracts")
def list_graph_ontology_contracts(graph_id: str, limit: int = 50, principal: Principal = Depends(require_permission("view")), db: Session = Depends(get_db)):
    graph = _graph_for(db, graph_id, principal, "view")
    rows = db.query(PipelineOntologyContractRun).filter(
        PipelineOntologyContractRun.graph_id == graph.id,
        PipelineOntologyContractRun.project_id == graph.project_id,
    ).order_by(PipelineOntologyContractRun.created_at.desc()).limit(max(1, min(limit, 250))).all()
    return {"graph_id": graph.id, "count": len(rows), "contracts": [_contract_run_dict(row) for row in rows]}


@router.get("/pipeline-builder/builds/{build_id}/ontology-contracts")
def list_build_ontology_contracts(build_id: str, principal: Principal = Depends(require_permission("view")), db: Session = Depends(get_db)):
    build = db.get(PipelineBuilderBuild, build_id)
    if not build:
        raise HTTPException(status_code=404, detail="Pipeline build not found")
    graph = _graph_for(db, build.graph_id, principal, "view")
    rows = db.query(PipelineOntologyContractRun).filter(
        PipelineOntologyContractRun.build_id == build.id,
        PipelineOntologyContractRun.project_id == graph.project_id,
    ).order_by(PipelineOntologyContractRun.created_at.desc()).all()
    return {"graph_id": graph.id, "build_id": build.id, "count": len(rows), "contracts": [_contract_run_dict(row) for row in rows]}


@router.get("/pipeline-builder/ontology-contracts/{contract_run_id}")
def get_ontology_contract_run(contract_run_id: str, principal: Principal = Depends(require_permission("view")), db: Session = Depends(get_db)):
    row = db.get(PipelineOntologyContractRun, contract_run_id)
    if not row:
        raise HTTPException(status_code=404, detail="Ontology contract run not found")
    _graph_for(db, row.graph_id, principal, "view")
    return _contract_run_dict(row)


@router.get("/pipeline-builder/ontology-contracts/{contract_run_id}/quarantine")
def get_ontology_contract_quarantine(contract_run_id: str, principal: Principal = Depends(require_permission("view")), db: Session = Depends(get_db)):
    row = db.get(PipelineOntologyContractRun, contract_run_id)
    if not row:
        raise HTTPException(status_code=404, detail="Ontology contract run not found")
    graph = _graph_for(db, row.graph_id, principal, "view")
    if not row.quarantine_asset_id:
        return {"contract_run_id": row.id, "status": "EMPTY", "asset": None, "records": []}
    asset = db.get(models.DataAsset, row.quarantine_asset_id)
    if not asset or asset.project_id != graph.project_id:
        raise HTTPException(status_code=404, detail="Quarantine dataset not found")
    return {
        "contract_run_id": row.id, "status": "AVAILABLE",
        "asset": {"id": asset.id, "display_name": asset.display_name, "row_count": len(asset.records or []), "schema": asset.asset_schema or {}},
        "records": (asset.records or [])[:100],
    }


@router.get("/ui-state/pipeline/{graph_id}/ontology-contracts")
def ontology_contract_ui_state(graph_id: str, principal: Principal = Depends(require_permission("view")), db: Session = Depends(get_db)):
    graph = _graph_for(db, graph_id, principal, "view")
    rows = db.query(PipelineOntologyContractRun).filter(PipelineOntologyContractRun.graph_id == graph.id).order_by(PipelineOntologyContractRun.created_at.desc()).limit(50).all()
    latest_by_node: Dict[str, PipelineOntologyContractRun] = {}
    for row in rows:
        latest_by_node.setdefault(row.node_id, row)
    latest = list(latest_by_node.values())
    rejected = sum(row.rejected_rows for row in latest)
    status = "FAIL" if any(row.status == "FAILED" for row in latest) else ("WARN" if rejected else ("PASS" if latest else "NOT_RUN"))
    return {
        "summary": {"status": status, "outputs": len(latest), "accepted_rows": sum(row.accepted_rows for row in latest), "rejected_rows": rejected},
        "primary_actions": [{"id": "deliver", "label": "Deliver and reconcile", "method": "POST", "path": f"/pipeline-builder/graphs/{graph.id}/deliver"}],
        "sections": {"latest": [_contract_run_dict(row) for row in latest], "history": [_contract_run_dict(row) for row in rows]},
        "evidence_links": [{"label": f"Contract {row.node_id}", "href": f"/pipeline-builder/ontology-contracts/{row.id}", "kind": "ontology_contract"} for row in latest],
        "warnings": [{"code": "ONTOLOGY_ROWS_REJECTED", "message": f"{rejected} rows were rejected by ontology contracts."}] if rejected else [],
        "permissions": sorted(tenancy.project_permissions(db, principal, graph.project_id)),
        "last_updated": max((row.created_at for row in rows), default=graph.updated_at),
    }

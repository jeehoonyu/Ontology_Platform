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
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import JSON, Integer, String
from sqlalchemy.orm import Mapped, Session, mapped_column

from . import models, models_action
from .database import Base, get_db
from .datasets_ext import DatasetTransaction, _fold, _next_seq, _txns_for

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


class PipelineBuilderGraph(Base):
    __tablename__ = "pipeline_builder_graphs"

    id: Mapped[str] = mapped_column(String, primary_key=True, index=True)
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

    id: Mapped[str] = mapped_column(String, primary_key=True, index=True)
    graph_id: Mapped[str] = mapped_column(String, index=True)
    status: Mapped[str] = mapped_column(String, default="SUCCESS")
    run_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    output_asset_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    preview: Mapped[dict] = mapped_column(JSON, default=dict)
    lineage: Mapped[dict] = mapped_column(JSON, default=dict)
    metrics: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[int] = mapped_column(Integer)


class PipelineGraphCreate(BaseModel):
    id: Optional[str] = None
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


def _now() -> int:
    return int(time.time())


def _new_id() -> str:
    return uuid.uuid4().hex


@router.get("/pipeline-builder/node-types")
def list_node_types():
    return {"node_types": NODE_TYPE_CATALOG}


@router.get("/ui-state/pipeline")
def pipeline_ui_state(db: Session = Depends(get_db)):
    graphs = db.query(PipelineBuilderGraph).order_by(PipelineBuilderGraph.updated_at.desc()).all()
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
        "node_library": NODE_TYPE_CATALOG,
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
        payload=payload,
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
        "config": body.config or {},
    }


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
    builds = [
        {
            "id": build.id,
            "status": build.status,
            "run_id": build.run_id,
            "output_asset_id": build.output_asset_id,
            "row_count": (build.preview or {}).get("row_count"),
            "created_at": build.created_at,
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
        "node_library": NODE_TYPE_CATALOG,
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
            "config": _config(node),
            "upstream": _predecessors(graph).get(node_id, []),
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
        "insertable_node_types": NODE_TYPE_CATALOG,
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
            elif not db.get(models.DataAsset, asset_id):
                errors.append({"code": "INPUT_ASSET_NOT_FOUND", "node_id": node_id, "message": f"DataAsset '{asset_id}' not found"})

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
        specs = [{"field": config.get("field"), "op": config.get("op", "equals"), "value": config.get("value")}]
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
    mapping = config.get("mapping") or config.get("types") or {}
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
    defaults = config.get("defaults") or config.get("mapping") or {}
    return [{**row, **{field: value for field, value in defaults.items() if _value(row, field) is None}} for row in rows]


def _normalize_rows(rows: List[Dict[str, Any]], config: Dict[str, Any]) -> List[Dict[str, Any]]:
    fields = config.get("fields") or []
    case = str(config.get("case", "preserve")).lower()
    output = []
    for row in rows:
        result = copy.deepcopy(row)
        for field in fields:
            value = _value(row, field)
            if isinstance(value, str):
                value = value.strip()
                value = value.lower() if case == "lower" else value.upper() if case == "upper" else value
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
    operation = str(config.get("operation", "first")).lower()
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
    field = config.get("field")
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
    checks = config.get("checks") or []
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
        output.append({**row, **({target: encode_mgrs(float(lat), float(lon), precision)} if lat is not None and lon is not None else {})})
    return output


def _spatial_filter_rows(rows: List[Dict[str, Any]], config: Dict[str, Any]) -> List[Dict[str, Any]]:
    center = config.get("center") or {}
    center_point = (float(center.get("latitude")), float(center.get("longitude"))) if center.get("latitude") is not None and center.get("longitude") is not None else None
    radius = float(config.get("radius_meters", 0))
    geometry_field = config.get("geometry_field") or "geometry"
    if not center_point or radius <= 0:
        return rows
    return [row for row in rows if _point(row, geometry_field) and _distance_meters(_point(row, geometry_field), center_point) <= radius]


def _spatial_join_rows(left_rows: List[Dict[str, Any]], right_rows: List[Dict[str, Any]], config: Dict[str, Any]) -> List[Dict[str, Any]]:
    max_distance = float(config.get("max_distance_meters", 1000))
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
    metrics = config.get("metrics") or [{"operation": "count", "alias": "count"}]
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
    current: List[Dict[str, Any]] = []
    final_node_id: Optional[str] = None
    step_metrics: List[Dict[str, Any]] = []
    input_asset_ids: List[str] = []
    materialized_objects = 0

    for node_id, node in ordered:
        node_type = _node_type(node)
        config = {**_config(node), **((parameters or {}).get(node_id, {}) if isinstance((parameters or {}).get(node_id), dict) else {})}
        parents = [outputs[parent] for parent in incoming.get(node_id, []) if parent in outputs]
        rows = copy.deepcopy(parents[0] if parents else current)
        records_in = len(rows)

        if node_type in {"input_dataset", "dataset_input"}:
            asset_id = config.get("asset_id") or config.get("dataset_id")
            asset = db.get(models.DataAsset, asset_id)
            if not asset:
                raise HTTPException(status_code=404, detail=f"DataAsset '{asset_id}' not found")
            rows = copy.deepcopy(asset.records or [])
            input_asset_ids.append(asset.id)
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
                right_rows = copy.deepcopy(right_asset.records or [])
            rows = _join_rows(rows, right_rows or [], config)
        elif node_type == "union":
            other_rows = parents[1] if len(parents) > 1 else []
            if config.get("asset_id"):
                other = db.get(models.DataAsset, config["asset_id"])
                if not other:
                    raise HTTPException(status_code=404, detail=f"DataAsset '{config['asset_id']}' not found")
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
            if write_ontology:
                object_type_id = config.get("object_type_id")
                id_field = config.get("id_field") or "id"
                mapping = config.get("mapping") or {}
                if object_type_id and db.get(models.ObjectType, object_type_id):
                    from . import decision_intelligence
                    for row in rows:
                        object_id = str(_value(row, id_field) or _stable_row_id(row, list(row.keys())))
                        properties = {target: _value(row, source) for source, target in mapping.items()} if mapping else copy.deepcopy(row)
                        existing = db.get(models.ObjectInstance, object_id)
                        if existing:
                            existing.properties = {**(existing.properties or {}), **properties}
                            existing.lineage = {
                                **(existing.lineage or {}),
                                "pipeline_builder_graph_id": graph.id,
                                "node_id": node_id,
                            }
                            existing.updated_at = _now()
                            decision_intelligence.record_object_snapshot(
                                db,
                                existing,
                                event_type="pipeline_builder.object.updated",
                                actor="pipeline_builder",
                                source_type="pipeline_builder_graph",
                                source_id=graph.id,
                            )
                        else:
                            created = models.ObjectInstance(
                                id=object_id,
                                object_type_id=object_type_id,
                                properties=properties,
                                source_asset_id=config.get("source_asset_id"),
                                lineage={"pipeline_builder_graph_id": graph.id, "node_id": node_id},
                                created_at=_now(),
                                updated_at=_now(),
                            )
                            db.add(created)
                            decision_intelligence.record_object_snapshot(
                                db,
                                created,
                                event_type="pipeline_builder.object.created",
                                actor="pipeline_builder",
                                source_type="pipeline_builder_graph",
                                source_id=graph.id,
                            )
                        materialized_objects += 1
        elif node_type in {"dataset_output", "output_dataset"}:
            final_node_id = node_id

        outputs[node_id] = rows
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
            node_id: {"row_count": len(rows), "schema": _schema(rows), "sample": rows[:5]}
            for node_id, rows in outputs.items()
        },
        "lineage": {"graph_id": graph.id, "steps": step_metrics, "input_asset_ids": input_asset_ids},
        "metrics": {"records_out": len(current), "materialized_objects": materialized_objects, "steps": len(step_metrics)},
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
    asset.asset_schema = _schema(asset.records or [])
    asset.updated_at = _now()
    return txn


@router.post("/pipeline-builder/graphs", response_model=PipelineGraphRead, status_code=201)
def create_graph(body: PipelineGraphCreate, db: Session = Depends(get_db)):
    graph_id = body.id or _new_id()
    if db.get(PipelineBuilderGraph, graph_id):
        raise HTTPException(status_code=400, detail="PipelineBuilderGraph already exists")
    now = _now()
    graph = PipelineBuilderGraph(
        id=graph_id,
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
def list_graphs(db: Session = Depends(get_db)):
    return db.query(PipelineBuilderGraph).order_by(PipelineBuilderGraph.updated_at.desc()).all()


@router.get("/pipeline-builder/graphs/{graph_id}", response_model=PipelineGraphRead)
def get_graph(graph_id: str, db: Session = Depends(get_db)):
    return _get_graph(db, graph_id)


@router.get("/ui-state/pipeline/{graph_id}/canvas")
def pipeline_canvas_state(graph_id: str, selected_node_id: Optional[str] = None, db: Session = Depends(get_db)):
    graph = _get_graph(db, graph_id)
    return _canvas_payload(db, graph, selected_node_id=selected_node_id)


@router.get("/ui-state/pipeline/{graph_id}/nodes/{node_id}/details")
def pipeline_node_details(graph_id: str, node_id: str, db: Session = Depends(get_db)):
    graph = _get_graph(db, graph_id)
    return _node_details_payload(db, graph, node_id)


@router.get("/ui-state/pipeline/{graph_id}/outputs")
def pipeline_outputs_state(graph_id: str, db: Session = Depends(get_db)):
    graph = _get_graph(db, graph_id)
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
def update_graph(graph_id: str, body: PipelineGraphUpdate, db: Session = Depends(get_db)):
    graph = _get_graph(db, graph_id)
    patch = body.model_dump(exclude_unset=True)
    for field, value in patch.items():
        setattr(graph, field, value)
    if patch:
        graph.updated_at = _now()
    db.commit()
    db.refresh(graph)
    return graph


@router.patch("/pipeline-builder/graphs/{graph_id}/layout")
def update_graph_layout(graph_id: str, body: PipelineLayoutRequest, db: Session = Depends(get_db)):
    graph = _get_graph(db, graph_id)
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
    _audit_graph(db, "pipeline_builder", "pipeline_builder.graph.layout_updated", graph, {"positions": positions})
    db.commit()
    db.refresh(graph)
    return _canvas_payload(db, graph)


@router.post("/pipeline-builder/graphs/{graph_id}/nodes")
def create_pipeline_node(graph_id: str, body: PipelineCreateNodeRequest, db: Session = Depends(get_db)):
    graph = _get_graph(db, graph_id)
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
    _audit_graph(db, body.actor, "pipeline_builder.node.created", graph, {
        "node_id": new_node["id"],
        "node_type": new_node["type"],
        "position": new_node["position"],
        "connect_from_node_id": body.connect_from_node_id,
    })
    db.commit()
    db.refresh(graph)
    return _canvas_payload(db, graph, selected_node_id=new_node["id"])


@router.post("/pipeline-builder/graphs/{graph_id}/nodes/{node_id}/insert-after")
def insert_node_after(graph_id: str, node_id: str, body: PipelineInsertNodeRequest, db: Session = Depends(get_db)):
    graph = _get_graph(db, graph_id)
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
    _audit_graph(db, "pipeline_builder", "pipeline_builder.node.inserted", graph, {
        "node_id": new_node["id"],
        "node_type": new_node["type"],
        "inserted_after": node_id,
    })
    db.commit()
    db.refresh(graph)
    return _canvas_payload(db, graph, selected_node_id=new_node["id"])


@router.delete("/pipeline-builder/graphs/{graph_id}/nodes/{node_id}")
def delete_pipeline_node(graph_id: str, node_id: str, db: Session = Depends(get_db)):
    graph = _get_graph(db, graph_id)
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
    _audit_graph(db, "pipeline_builder", "pipeline_builder.node.deleted", graph, {
        "node_id": node_id,
        "incoming_edges": len(incoming),
        "outgoing_edges": len(outgoing),
        "reconnected": reconnected,
    })
    db.commit()
    db.refresh(graph)
    return _canvas_payload(db, graph)


@router.post("/pipeline-builder/graphs/{graph_id}/nodes/{node_id}/preview")
def preview_pipeline_node(graph_id: str, node_id: str, body: PipelineNodePreviewRequest = PipelineNodePreviewRequest(), db: Session = Depends(get_db)):
    graph = _get_graph(db, graph_id)
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
def suggest_pipeline_node_actions(graph_id: str, node_id: str, db: Session = Depends(get_db)):
    graph = _get_graph(db, graph_id)
    return _node_suggestions_payload(db, graph, node_id)


@router.post("/pipeline-builder/graphs/{graph_id}/validate")
def validate_graph(graph_id: str, db: Session = Depends(get_db)):
    graph = _get_graph(db, graph_id)
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


@router.post("/pipeline-builder/graphs/{graph_id}/preview")
def preview_graph(graph_id: str, body: PipelinePreviewRequest = PipelinePreviewRequest(), db: Session = Depends(get_db)):
    graph = _get_graph(db, graph_id)
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
            payload={"row_count": result["row_count"], "schema": result["schema"]},
        )
        db.commit()
    except Exception:
        db.rollback()
    return result


@router.post("/pipeline-builder/graphs/{graph_id}/deliver")
def deliver_graph(graph_id: str, body: PipelineDeliverRequest = PipelineDeliverRequest(), db: Session = Depends(get_db)):
    graph = _get_graph(db, graph_id)
    execution = _execute_graph(db, graph, parameters=body.parameters, write_ontology=True)
    output_asset_id = _output_asset_id(graph, body.output_asset_id)
    now = _now()
    asset = db.get(models.DataAsset, output_asset_id)
    if not asset:
        asset = models.DataAsset(
            id=output_asset_id,
            display_name=f"{graph.display_name} Output",
            description=f"Delivered output from Pipeline Builder graph {graph.id}",
            kind="dataset",
            asset_schema={},
            records=[],
            created_at=now,
            updated_at=now,
        )
        db.add(asset)

    input_asset_id = execution["input_asset_ids"][0] if execution["input_asset_ids"] else output_asset_id
    pipeline = db.get(models.PipelineDefinition, graph.id)
    if not pipeline:
        pipeline = models.PipelineDefinition(
            id=graph.id,
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
        metrics={**execution["metrics"], "transaction_id": txn.id},
        created_at=now,
    )
    db.add(build)
    db.add(models_action.AuditLog(
        id=_new_id(),
        actor=body.actor,
        event_type="pipeline_builder.graph.delivered",
        subject_type="pipeline_builder_graph",
        subject_id=graph.id,
        payload={"run_id": run.id, "output_asset_id": asset.id, "records_out": len(execution["rows"])},
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
            payload={"run_id": run.id, "output_asset_id": asset.id, "records_out": len(execution["rows"])},
        )
    except Exception:
        pass
    graph.status = "DELIVERED"
    graph.updated_at = now
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

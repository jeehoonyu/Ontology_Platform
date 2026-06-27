"""
Pipeline Builder graph API.

The base platform already has datasets, pipeline runs, lineage helpers, and
transaction-backed dataset snapshots. This module adds the builder-facing graph
model and deterministic DAG execution used by the local UI.
"""
import copy
import hashlib
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
    "join",
    "union",
    "aggregate",
    "sort",
    "limit",
    "unique_id",
    "llm_assist",
    "llm",
    "ontology_output",
    "dataset_output",
    "output_dataset",
}


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


def _now() -> int:
    return int(time.time())


def _new_id() -> str:
    return uuid.uuid4().hex


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
                    for row in rows:
                        object_id = str(_value(row, id_field) or _stable_row_id(row, list(row.keys())))
                        properties = {target: _value(row, source) for source, target in mapping.items()} if mapping else copy.deepcopy(row)
                        existing = db.get(models.ObjectInstance, object_id)
                        if existing:
                            existing.properties = {**(existing.properties or {}), **properties}
                            existing.updated_at = _now()
                        else:
                            db.add(models.ObjectInstance(
                                id=object_id,
                                object_type_id=object_type_id,
                                properties=properties,
                                source_asset_id=config.get("source_asset_id"),
                                lineage={"pipeline_builder_graph_id": graph.id, "node_id": node_id},
                                created_at=_now(),
                                updated_at=_now(),
                            ))
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


@router.post("/pipeline-builder/graphs/{graph_id}/validate")
def validate_graph(graph_id: str, db: Session = Depends(get_db)):
    return _validate_graph(db, _get_graph(db, graph_id))


@router.post("/pipeline-builder/graphs/{graph_id}/preview")
def preview_graph(graph_id: str, body: PipelinePreviewRequest = PipelinePreviewRequest(), db: Session = Depends(get_db)):
    graph = _get_graph(db, graph_id)
    execution = _execute_graph(db, graph, parameters=body.parameters, write_ontology=False)
    limit = max(1, min(int(body.limit), 500))
    return {
        "graph_id": graph.id,
        "status": "PREVIEW_READY",
        "row_count": len(execution["rows"]),
        "rows": execution["rows"][:limit],
        "schema": _schema(execution["rows"]),
        "node_outputs": execution["node_outputs"],
        "lineage": execution["lineage"],
        "metrics": execution["metrics"],
    }


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

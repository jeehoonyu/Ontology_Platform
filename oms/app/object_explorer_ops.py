"""
Object Explorer — histograms & property statistics (deep-fidelity pass 8, Analytics).

Deepens Object Explorer beyond search/filter with the documented analysis features:
numeric/categorical **histograms** and per-**property statistics** over an object set.
Additive; deterministic; reuses the runtime object-set query.
"""
import json
import time
import uuid
from typing import Optional, List, Any, Dict

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import JSON, Integer, String
from sqlalchemy.orm import Session
from sqlalchemy.orm import Mapped, mapped_column
from pydantic import BaseModel, ConfigDict, Field

from .database import Base, get_db
from . import models, production_auth, runtime, semantic_scope

router = APIRouter(tags=["object_explorer_ops"])


class ObjectExplorerExploration(Base):
    __tablename__ = "object_explorer_explorations"

    id: Mapped[str] = mapped_column(String, primary_key=True, index=True)
    project_id: Mapped[str] = mapped_column(String, default="default", server_default="default", index=True)
    display_name: Mapped[str] = mapped_column(String)
    description: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    object_type_id: Mapped[str] = mapped_column(String, index=True)
    filters: Mapped[dict] = mapped_column(JSON, default=dict)
    columns: Mapped[list] = mapped_column(JSON, default=list)
    charts: Mapped[list] = mapped_column(JSON, default=list)
    perspective: Mapped[dict] = mapped_column(JSON, default=dict)
    owner: Mapped[str] = mapped_column(String, default="system")
    created_at: Mapped[int] = mapped_column(Integer)
    updated_at: Mapped[int] = mapped_column(Integer)


class ExplorationCreate(BaseModel):
    id: Optional[str] = None
    project_id: str = "default"
    display_name: str
    description: Optional[str] = None
    object_type_id: str
    filters: Dict[str, Any] = Field(default_factory=dict)
    columns: List[str] = Field(default_factory=list)
    charts: List[Dict[str, Any]] = Field(default_factory=list)
    perspective: Dict[str, Any] = Field(default_factory=dict)
    owner: str = "system"


class ExplorationUpdate(BaseModel):
    display_name: Optional[str] = None
    description: Optional[str] = None
    object_type_id: Optional[str] = None
    filters: Optional[Dict[str, Any]] = None
    columns: Optional[List[str]] = None
    charts: Optional[List[Dict[str, Any]]] = None
    perspective: Optional[Dict[str, Any]] = None
    owner: Optional[str] = None


class ExplorationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    project_id: str
    display_name: str
    description: Optional[str] = None
    object_type_id: str
    filters: Dict[str, Any]
    columns: List[str]
    charts: List[Dict[str, Any]]
    perspective: Dict[str, Any]
    owner: str
    created_at: int
    updated_at: int


class ObjectExplorerQueryRequest(BaseModel):
    object_type_id: str
    query: Optional[str] = None
    filters: Any = Field(default_factory=dict)
    columns: List[str] = Field(default_factory=list)
    chart_fields: List[str] = Field(default_factory=list)
    selected_ids: List[str] = Field(default_factory=list)
    limit: int = 100
    include_lineage: bool = False


class ObjectExplorerQueryResponse(BaseModel):
    object_type_id: str
    filters: Any = Field(default_factory=dict)
    result_count: int
    objects: List[Dict[str, Any]] = Field(default_factory=list)
    columns: List[str] = Field(default_factory=list)
    facets: List[Dict[str, Any]] = Field(default_factory=list)
    selected_objects: List[Dict[str, Any]] = Field(default_factory=list)
    available_actions: List[Dict[str, Any]] = Field(default_factory=list)
    object_type: Optional[Dict[str, Any]] = None


def _now() -> int:
    return int(time.time())


def _new_id() -> str:
    return uuid.uuid4().hex


def _require_object_type(db: Session, object_type_id: str, principal: production_auth.Principal) -> models.ObjectType:
    return semantic_scope.object_type_for(db, principal, object_type_id, "view")


class HistogramRequest(BaseModel):
    object_type_id: str
    field: str
    bins: int = 10
    filters: Dict[str, Any] = Field(default_factory=dict)


class PropertyStatsRequest(BaseModel):
    object_type_id: str
    field: str
    filters: Dict[str, Any] = Field(default_factory=dict)


def _values(db: Session, body, project_id: str) -> List[Any]:
    rows, _ = runtime._logic_object_rows(db, body.object_type_id, body.filters, limit=10 ** 9, project_id=project_id)
    return [(r.properties or {}).get(body.field) for r in rows]


def _is_num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _object_schema_columns(object_type: Optional[models.ObjectType], objects: List[Dict[str, Any]]) -> List[str]:
    columns: List[str] = []
    schema = object_type.properties if object_type else {}
    if isinstance(schema, dict):
        properties = schema.get("properties") if isinstance(schema.get("properties"), dict) else schema
        columns.extend([str(key) for key in properties.keys()])
    for obj in objects:
        for key in (obj.get("properties") or {}).keys():
            if key not in columns:
                columns.append(key)
    preferred = ["name", "title", "status", "criticality", "priority", "owner", "updated_at"]
    ordered = [field for field in preferred if field in columns]
    ordered.extend([field for field in columns if field not in ordered])
    return ordered[:12]


def _matches_text(obj: Dict[str, Any], query: Optional[str]) -> bool:
    if not query:
        return True
    return query.lower() in json.dumps(obj, default=str).lower()


def _facet(field: str, objects: List[Dict[str, Any]], bins: int = 8) -> Dict[str, Any]:
    values = [runtime._record_value(obj, field) for obj in objects]
    values = [value for value in values if value is not None]
    nums = [value for value in values if _is_num(value)]
    if nums and len(nums) == len(values):
        lo, hi = min(nums), max(nums)
        if lo == hi:
            buckets = [{"range": [lo, hi], "label": str(lo), "count": len(nums)}]
        else:
            width = (hi - lo) / max(1, bins)
            buckets = []
            for index in range(bins):
                b_lo = lo + index * width
                b_hi = hi if index == bins - 1 else lo + (index + 1) * width
                count = sum(1 for num in nums if (b_lo <= num < b_hi) or (index == bins - 1 and num == hi))
                buckets.append({
                    "range": [round(b_lo, 6), round(b_hi, 6)],
                    "label": f"{round(b_lo, 2)} - {round(b_hi, 2)}",
                    "count": count,
                })
        return {"field": field, "type": "histogram", "buckets": buckets}

    counts: Dict[str, int] = {}
    for value in values:
        counts[str(value)] = counts.get(str(value), 0) + 1
    return {
        "field": field,
        "type": "listogram",
        "buckets": [
            {"value": key, "label": key, "count": count}
            for key, count in sorted(counts.items(), key=lambda item: item[1], reverse=True)[:20]
        ],
    }


def _available_actions(db: Session, object_type_id: str, project_id: str) -> List[Dict[str, Any]]:
    actions: List[Dict[str, Any]] = []
    for action in db.query(models.ActionType).filter(models.ActionType.project_id == project_id).all():
        rules = action.rules or {}
        parameters = action.parameters or {}
        explicit_types = (
            rules.get("object_type_ids")
            or rules.get("allowed_object_types")
            or rules.get("target_object_type_ids")
            or parameters.get("object_type_ids")
            or []
        )
        if isinstance(explicit_types, str):
            explicit_types = [explicit_types]
        serialized = json.dumps({"rules": rules, "parameters": parameters}, default=str)
        if explicit_types and object_type_id not in explicit_types:
            continue
        if not explicit_types and object_type_id not in serialized and "object_id" not in serialized:
            continue
        actions.append({
            "id": action.id,
            "display_name": action.display_name,
            "description": action.description,
            "parameters": parameters,
        })
    return actions


def _get_exploration_or_404(db: Session, exploration_id: str, principal: production_auth.Principal, permission: str = "view") -> ObjectExplorerExploration:
    row = db.query(ObjectExplorerExploration).filter(ObjectExplorerExploration.id == exploration_id).first()
    if not row:
        raise HTTPException(status_code=404, detail=f"ObjectExplorerExploration '{exploration_id}' not found")
    semantic_scope.assert_project(db, principal, row.project_id, permission)
    return row


@router.post("/object-explorer/explorations", response_model=ExplorationRead, status_code=201)
def create_exploration(body: ExplorationCreate, db: Session = Depends(get_db),
                       principal: production_auth.Principal = Depends(production_auth.require_permission("edit"))):
    object_type = _require_object_type(db, body.object_type_id, principal)
    semantic_scope.assert_project(db, principal, body.project_id, "edit")
    if object_type.project_id != body.project_id:
        raise HTTPException(status_code=409, detail="Object type belongs to another project")
    exploration_id = body.id or _new_id()
    if db.get(ObjectExplorerExploration, exploration_id):
        raise HTTPException(status_code=400, detail="ObjectExplorerExploration already exists")
    now = _now()
    row = ObjectExplorerExploration(
        id=exploration_id,
        project_id=body.project_id,
        display_name=body.display_name,
        description=body.description,
        object_type_id=body.object_type_id,
        filters=body.filters,
        columns=body.columns,
        charts=body.charts,
        perspective=body.perspective,
        owner=body.owner,
        created_at=now,
        updated_at=now,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@router.get("/object-explorer/explorations", response_model=List[ExplorationRead])
def list_explorations(db: Session = Depends(get_db),
                      principal: production_auth.Principal = Depends(production_auth.require_permission("view"))):
    return semantic_scope.accessible_query(db, principal, ObjectExplorerExploration).order_by(ObjectExplorerExploration.updated_at.desc()).all()


@router.get("/object-explorer/explorations/{exploration_id}", response_model=ExplorationRead)
def get_exploration(exploration_id: str, db: Session = Depends(get_db),
                    principal: production_auth.Principal = Depends(production_auth.require_permission("view"))):
    return _get_exploration_or_404(db, exploration_id, principal)


@router.patch("/object-explorer/explorations/{exploration_id}", response_model=ExplorationRead)
def update_exploration(exploration_id: str, body: ExplorationUpdate, db: Session = Depends(get_db),
                       principal: production_auth.Principal = Depends(production_auth.require_permission("edit"))):
    row = _get_exploration_or_404(db, exploration_id, principal, "edit")
    patch = body.model_dump(exclude_unset=True)
    if "object_type_id" in patch:
        object_type = _require_object_type(db, patch["object_type_id"], principal)
        if object_type.project_id != row.project_id:
            raise HTTPException(status_code=409, detail="Object type belongs to another project")
    for field, value in patch.items():
        setattr(row, field, value)
    if patch:
        row.updated_at = _now()
    db.commit()
    db.refresh(row)
    return row


@router.post("/object-explorer/query", response_model=ObjectExplorerQueryResponse)
def object_explorer_query(body: ObjectExplorerQueryRequest, db: Session = Depends(get_db),
                          principal: production_auth.Principal = Depends(production_auth.require_permission("view"))):
    object_type = _require_object_type(db, body.object_type_id, principal)
    result = runtime.query_object_set(
        db,
        object_type_id=body.object_type_id,
        project_id=object_type.project_id,
        filters=body.filters,
        limit=max(1, min(body.limit, 10000)),
        include_lineage=body.include_lineage,
    )
    objects = [obj for obj in result["objects"] if _matches_text(obj, body.query)]
    selected_columns = body.columns or _object_schema_columns(object_type, objects)
    chart_fields = body.chart_fields or selected_columns[:4]
    selected_objects = []
    for selected_id in body.selected_ids[:10]:
        try:
            selected_objects.append(runtime.build_object_profile(db, object_type_id=body.object_type_id, object_id=selected_id, project_id=object_type.project_id))
        except ValueError:
            continue
    return {
        "object_type_id": body.object_type_id,
        "filters": body.filters or {},
        "result_count": len(objects),
        "objects": objects,
        "columns": selected_columns,
        "facets": [_facet(field, objects) for field in chart_fields if field],
        "selected_objects": selected_objects,
        "available_actions": _available_actions(db, body.object_type_id, object_type.project_id),
        "object_type": {
            "id": object_type.id,
            "display_name": object_type.display_name,
            "description": object_type.description,
            "properties": object_type.properties,
        } if object_type else None,
    }


@router.post("/object-explorer/histogram")
def histogram(body: HistogramRequest, db: Session = Depends(get_db),
              principal: production_auth.Principal = Depends(production_auth.require_permission("view"))):
    object_type = _require_object_type(db, body.object_type_id, principal)
    values = [v for v in _values(db, body, object_type.project_id) if v is not None]
    nums = [v for v in values if _is_num(v)]
    if nums and len(nums) == len(values):
        lo, hi = min(nums), max(nums)
        if lo == hi:
            return {"type": "numeric", "field": body.field, "buckets": [{"range": [lo, hi], "count": len(nums)}]}
        width = (hi - lo) / body.bins
        buckets = []
        for i in range(body.bins):
            b_lo = lo + i * width
            b_hi = hi if i == body.bins - 1 else lo + (i + 1) * width
            count = sum(1 for n in nums if (b_lo <= n < b_hi) or (i == body.bins - 1 and n == hi))
            buckets.append({"range": [round(b_lo, 6), round(b_hi, 6)], "count": count})
        return {"type": "numeric", "field": body.field, "min": lo, "max": hi, "buckets": buckets}
    # categorical
    counts: Dict[str, int] = {}
    for v in values:
        counts[str(v)] = counts.get(str(v), 0) + 1
    ordered = sorted(counts.items(), key=lambda kv: kv[1], reverse=True)
    return {"type": "categorical", "field": body.field,
            "buckets": [{"value": k, "count": c} for k, c in ordered]}


@router.post("/object-explorer/property-stats")
def property_stats(body: PropertyStatsRequest, db: Session = Depends(get_db),
                   principal: production_auth.Principal = Depends(production_auth.require_permission("view"))):
    object_type = _require_object_type(db, body.object_type_id, principal)
    values = _values(db, body, object_type.project_id)
    non_null = [v for v in values if v is not None]
    nums = [v for v in non_null if _is_num(v)]
    stats: Dict[str, Any] = {
        "object_type_id": body.object_type_id, "field": body.field,
        "count": len(values), "non_null": len(non_null), "null": len(values) - len(non_null),
        "distinct": len({str(v) for v in non_null}),
    }
    if nums:
        stats["numeric"] = {"min": min(nums), "max": max(nums),
                            "avg": round(sum(nums) / len(nums), 6), "sum": round(sum(nums), 6)}
    counts: Dict[str, int] = {}
    for v in non_null:
        counts[str(v)] = counts.get(str(v), 0) + 1
    stats["top_values"] = [{"value": k, "count": c} for k, c in sorted(counts.items(), key=lambda kv: kv[1], reverse=True)[:5]]
    return stats


# ---------------------------------------------------------------------------
# Chart aggregations (Object Explorer chart cards)
# ---------------------------------------------------------------------------

class ListogramRequest(BaseModel):
    object_type_id: str
    field: str
    keep: Optional[List[str]] = None       # if set, only these category values are kept
    exclude: Optional[List[str]] = None    # if set, these category values are dropped
    filters: Dict[str, Any] = Field(default_factory=dict)


class StatisticsTableRequest(BaseModel):
    object_type_id: str
    fields: List[str]
    filters: Dict[str, Any] = Field(default_factory=dict)


class SingleStatisticRequest(BaseModel):
    object_type_id: str
    field: str
    statistic: str = "count"  # count | sum | avg | min | max | distinct
    filters: Dict[str, Any] = Field(default_factory=dict)


class GridPlotRequest(BaseModel):
    object_type_id: str
    row_field: str
    col_field: str
    filters: Dict[str, Any] = Field(default_factory=dict)


def _field_values(db: Session, object_type_id: str, field: str, filters: Dict[str, Any], project_id: str) -> List[Any]:
    rows, _ = runtime._logic_object_rows(db, object_type_id, filters, limit=10 ** 9, project_id=project_id)
    return [(r.properties or {}).get(field) for r in rows]


@router.post("/object-explorer/listogram")
def listogram(body: ListogramRequest, db: Session = Depends(get_db),
              principal: production_auth.Principal = Depends(production_auth.require_permission("view"))):
    """Categorical value counts with keep/exclude category filtering."""
    object_type = _require_object_type(db, body.object_type_id, principal)
    values = [str(v) for v in _field_values(db, body.object_type_id, body.field, body.filters, object_type.project_id) if v is not None]
    counts: Dict[str, int] = {}
    for v in values:
        counts[v] = counts.get(v, 0) + 1
    if body.keep is not None:
        keep = {str(k) for k in body.keep}
        counts = {k: c for k, c in counts.items() if k in keep}
    if body.exclude is not None:
        drop = {str(k) for k in body.exclude}
        counts = {k: c for k, c in counts.items() if k not in drop}
    ordered = sorted(counts.items(), key=lambda kv: kv[1], reverse=True)
    return {"field": body.field, "categories": [{"value": k, "count": c} for k, c in ordered],
            "total": sum(counts.values())}


@router.post("/object-explorer/statistics-table")
def statistics_table(body: StatisticsTableRequest, db: Session = Depends(get_db),
                     principal: production_auth.Principal = Depends(production_auth.require_permission("view"))):
    """Per-field count/min/max/avg/sum table over the object set."""
    object_type = _require_object_type(db, body.object_type_id, principal)
    rows, _ = runtime._logic_object_rows(db, body.object_type_id, body.filters, limit=10 ** 9, project_id=object_type.project_id)
    table = []
    for field in body.fields:
        vals = [(r.properties or {}).get(field) for r in rows]
        non_null = [v for v in vals if v is not None]
        nums = [v for v in non_null if _is_num(v)]
        entry: Dict[str, Any] = {"field": field, "count": len(non_null), "distinct": len({str(v) for v in non_null})}
        if nums:
            entry.update({"min": min(nums), "max": max(nums),
                          "avg": round(sum(nums) / len(nums), 6), "sum": round(sum(nums), 6)})
        table.append(entry)
    return {"object_type_id": body.object_type_id, "rows": table}


@router.post("/object-explorer/single-statistic")
def single_statistic(body: SingleStatisticRequest, db: Session = Depends(get_db),
                     principal: production_auth.Principal = Depends(production_auth.require_permission("view"))):
    """A single aggregate value over one field."""
    object_type = _require_object_type(db, body.object_type_id, principal)
    vals = _field_values(db, body.object_type_id, body.field, body.filters, object_type.project_id)
    non_null = [v for v in vals if v is not None]
    nums = [v for v in non_null if _is_num(v)]
    stat = body.statistic.lower()
    if stat == "count":
        value = len(non_null)
    elif stat == "distinct":
        value = len({str(v) for v in non_null})
    elif stat == "sum":
        value = round(sum(nums), 6)
    elif stat == "avg":
        value = round(sum(nums) / len(nums), 6) if nums else None
    elif stat == "min":
        value = min(nums) if nums else None
    elif stat == "max":
        value = max(nums) if nums else None
    else:
        raise HTTPException(status_code=422, detail=f"unknown statistic '{body.statistic}'")
    return {"field": body.field, "statistic": stat, "value": value}


@router.post("/object-explorer/grid-plot")
def grid_plot(body: GridPlotRequest, db: Session = Depends(get_db),
              principal: production_auth.Principal = Depends(production_auth.require_permission("view"))):
    """Two-way (row_field x col_field) count grid."""
    object_type = _require_object_type(db, body.object_type_id, principal)
    rows, _ = runtime._logic_object_rows(db, body.object_type_id, body.filters, limit=10 ** 9, project_id=object_type.project_id)
    grid: Dict[str, Dict[str, int]] = {}
    row_keys, col_keys = set(), set()
    for r in rows:
        props = r.properties or {}
        rk = str(props.get(body.row_field))
        ck = str(props.get(body.col_field))
        row_keys.add(rk); col_keys.add(ck)
        grid.setdefault(rk, {})
        grid[rk][ck] = grid[rk].get(ck, 0) + 1
    return {"row_field": body.row_field, "col_field": body.col_field,
            "row_values": sorted(row_keys), "col_values": sorted(col_keys),
            "cells": [{"row": rk, "col": ck, "count": grid.get(rk, {}).get(ck, 0)}
                      for rk in sorted(row_keys) for ck in sorted(col_keys)]}

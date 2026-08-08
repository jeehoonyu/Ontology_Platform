"""
Foundry-style analytics module:
  - CONTOUR  tabular step analysis over DataAsset records
  - QUIVER   time-series over ObjectInstance properties
  - FUSION   spreadsheet formulas over ObjectInstance object sets
"""

from __future__ import annotations

import math
import re
import time
import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import String, Integer, JSON, Boolean, Float
from sqlalchemy.orm import Mapped, mapped_column, Session

from .database import Base, get_db
from . import models, models_action
from . import contour_ops

router = APIRouter(tags=["analytics"])

# ---------------------------------------------------------------------------
# SQLAlchemy models
# ---------------------------------------------------------------------------

class ContourAnalysis(Base):
    """Tabular step-analysis (CONTOUR) over a DataAsset."""
    __tablename__ = "contour_analyses"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    display_name: Mapped[str] = mapped_column(String)
    input_asset_id: Mapped[str] = mapped_column(String, index=True)
    boards: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[int] = mapped_column(Integer)
    updated_at: Mapped[int] = mapped_column(Integer)


class QuiverAnalysis(Base):
    """Time-series analysis (QUIVER) over ObjectInstance properties."""
    __tablename__ = "quiver_analyses"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    display_name: Mapped[str] = mapped_column(String)
    object_type_id: Mapped[str] = mapped_column(String, index=True)
    time_field: Mapped[str] = mapped_column(String)
    value_field: Mapped[str] = mapped_column(String)
    created_at: Mapped[int] = mapped_column(Integer)


class FusionWorkbook(Base):
    """Spreadsheet-over-object-sets (FUSION)."""
    __tablename__ = "fusion_workbooks"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    display_name: Mapped[str] = mapped_column(String)
    object_type_id: Mapped[str] = mapped_column(String, index=True)
    cells: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[int] = mapped_column(Integer)
    updated_at: Mapped[int] = mapped_column(Integer)


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------

class BoardStep(BaseModel):
    # Allow extra top-level keys so the UNIFIED board schema survives
    # persistence (e.g. {"op":"filter","field":"city","equals":"LA"} and the
    # extended data-producing / transform boards that use top-level args).
    model_config = ConfigDict(extra="allow")

    op: str                       # filter|aggregate|derive|chart_series|...
    config: Dict[str, Any] = Field(default_factory=dict)


class ContourCreate(BaseModel):
    id: Optional[str] = None
    display_name: str
    input_asset_id: str
    boards: List[BoardStep] = Field(default_factory=list)


class ContourRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    display_name: str
    input_asset_id: str
    boards: List[Any]
    created_at: int
    updated_at: int


class ContourRunResponse(BaseModel):
    analysis_id: str
    rows: List[Dict[str, Any]]
    row_count: int


# ----------

class QuiverCreate(BaseModel):
    id: Optional[str] = None
    display_name: str
    object_type_id: str
    time_field: str
    value_field: str


class QuiverRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    display_name: str
    object_type_id: str
    time_field: str
    value_field: str
    created_at: int


class QuiverComputeResponse(BaseModel):
    analysis_id: str
    series: List[Dict[str, Any]]
    stats: Dict[str, Any]


# ----------

class FusionCreate(BaseModel):
    id: Optional[str] = None
    display_name: str
    object_type_id: str
    cells: Dict[str, str] = Field(default_factory=dict)


class FusionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    display_name: str
    object_type_id: str
    cells: Dict[str, Any]
    created_at: int
    updated_at: int


class FusionEvaluateResponse(BaseModel):
    workbook_id: str
    results: Dict[str, Any]


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _now() -> int:
    return int(time.time())


def _audit(
    db: Session,
    actor: str,
    event_type: str,
    subject_type: str,
    subject_id: str,
    payload: Optional[Dict[str, Any]] = None,
) -> None:
    db.add(
        models_action.AuditLog(
            id=uuid.uuid4().hex,
            actor=actor,
            event_type=event_type,
            subject_type=subject_type,
            subject_id=subject_id,
            payload=payload or {},
        )
    )


# --- CONTOUR board execution ---

def _apply_filter(rows: List[Dict], config: Dict, field: Any = None, equals: Any = None) -> List[Dict]:
    """
    Keep rows where row[field] == value.

    UNIFIED filter schema: read EITHER the analytics form (config.field /
    config.value) OR the contour_ops form (top-level field / equals). Top-level
    args win when provided.
    """
    field = field if field is not None else config.get("field", "")
    if equals is not None:
        value = equals
    elif "value" in config:
        value = config.get("value")
    else:
        value = config.get("equals")
    if not field:
        return rows
    return [r for r in rows if str(r.get(field, "")) == str(value)]


def _apply_aggregate(rows: List[Dict], config: Dict) -> List[Dict]:
    """Group by `group_by` field, then compute count/sum/avg of `agg_field`."""
    group_by = config.get("group_by", "")
    agg_field = config.get("agg_field", "")
    agg_op = config.get("agg_op", "count").lower()

    if not group_by:
        # No group-by: single row result
        nums = [_to_num(r.get(agg_field)) for r in rows if _to_num(r.get(agg_field)) is not None]
        result_val = _compute_agg(agg_op, nums)
        return [{"group": "__all__", agg_op: result_val, "count": len(rows)}]

    groups: Dict[str, List] = {}
    for r in rows:
        key = str(r.get(group_by, "__null__"))
        groups.setdefault(key, []).append(r)

    out = []
    for key, group_rows in groups.items():
        nums = [_to_num(r.get(agg_field)) for r in group_rows if _to_num(r.get(agg_field)) is not None]
        result_val = _compute_agg(agg_op, nums)
        out.append({group_by: key, agg_op: result_val, "count": len(group_rows)})
    return out


def _apply_derive(rows: List[Dict], config: Dict) -> List[Dict]:
    """Derive new_field = a (op) b where a/b are field names or numeric literals."""
    new_field = config.get("new_field", "derived")
    a_ref = config.get("a", "")
    b_ref = config.get("b", "")
    op = config.get("op", "+")

    out = []
    for r in rows:
        a_val = _resolve_ref(r, a_ref)
        b_val = _resolve_ref(r, b_ref)
        derived = _numeric_op(a_val, b_val, op)
        new_row = dict(r)
        new_row[new_field] = derived
        out.append(new_row)
    return out


def _resolve_ref(row: Dict, ref: str) -> Any:
    """Return numeric value from row field or parse as literal."""
    if ref in row:
        return _to_num(row[ref])
    try:
        return float(ref)
    except (TypeError, ValueError):
        return None


def _to_num(val: Any) -> Optional[float]:
    if val is None:
        return None
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


def _numeric_op(a: Optional[float], b: Optional[float], op: str) -> Optional[float]:
    if a is None or b is None:
        return None
    if op == "+":
        return a + b
    if op == "-":
        return a - b
    if op == "*":
        return a * b
    if op == "/":
        return (a / b) if b != 0 else None
    return None


def _compute_agg(op: str, nums: List[float]) -> Optional[float]:
    if not nums and op != "count":
        return None
    if op == "count":
        return float(len(nums))
    if op == "sum":
        return sum(nums)
    if op == "avg":
        return sum(nums) / len(nums) if nums else None
    return None


# Ops handled natively by analytics' own (config-shaped) executor.
_ANALYTICS_NATIVE_OPS = {"filter", "aggregate", "derive"}


def _execute_boards(records: List[Dict], boards: List[Any]) -> List[Dict]:
    rows = [dict(r) for r in records]
    for step in boards:
        if isinstance(step, dict):
            op = step.get("op", "")
            config = step.get("config", {})
            top = step
        else:
            # BoardStep pydantic object
            op = step.op
            config = step.config
            top = {"op": op, "config": config}
        if op == "filter":
            # UNIFIED: accept config.field/config.value OR top-level field/equals
            rows = _apply_filter(rows, config, field=top.get("field"), equals=top.get("equals"))
        elif op == "aggregate":
            rows = _apply_aggregate(rows, config)
        elif op == "derive":
            rows = _apply_derive(rows, config)
        else:
            # Extended ops (chart_series/histogram/distribution/time_series/
            # enrich/join/set_math/unpivot/pivot/sort/top_n/group_by/summary)
            # are delegated to the shared contour board executor. The board's
            # `config` is flattened to top-level so either schema works.
            merged = {**(config or {}), **{k: v for k, v in top.items() if k != "config"}}
            result = contour_ops.execute_board_pipeline(rows, [merged])
            # Terminal boards (summary/distribution) emit a single-row payload.
            if op == "summary":
                rows = [result.get("summary", {})]
            elif op == "distribution":
                rows = [result.get("distribution", {})]
            else:
                rows = result.get("records", rows)
    return rows


# --- FUSION formula evaluation ---

_COUNT_RE = re.compile(r"^=COUNT\((\w+)\)$", re.IGNORECASE)
_SUM_RE = re.compile(r"^=SUM\((\w+)\.(\w+)\)$", re.IGNORECASE)
_AVG_RE = re.compile(r"^=AVG\((\w+)\.(\w+)\)$", re.IGNORECASE)
_MIN_RE = re.compile(r"^=MIN\((\w+)\.(\w+)\)$", re.IGNORECASE)
_MAX_RE = re.compile(r"^=MAX\((\w+)\.(\w+)\)$", re.IGNORECASE)


def _eval_formula(formula: str, db: Session) -> Any:
    """Evaluate a single cell formula deterministically."""
    formula = formula.strip()

    m = _COUNT_RE.match(formula)
    if m:
        ot_id = m.group(1)
        return db.query(models.ObjectInstance).filter(
            models.ObjectInstance.object_type_id == ot_id
        ).count()

    for pattern, agg_op in [(_SUM_RE, "sum"), (_AVG_RE, "avg"), (_MIN_RE, "min"), (_MAX_RE, "max")]:
        m = pattern.match(formula)
        if m:
            ot_id, field = m.group(1), m.group(2)
            instances = db.query(models.ObjectInstance).filter(
                models.ObjectInstance.object_type_id == ot_id
            ).all()
            nums = [_to_num((inst.properties or {}).get(field)) for inst in instances]
            nums = [n for n in nums if n is not None]
            if not nums:
                return None
            if agg_op == "sum":
                return sum(nums)
            if agg_op == "avg":
                return sum(nums) / len(nums)
            if agg_op == "min":
                return min(nums)
            if agg_op == "max":
                return max(nums)

    # Literal / unrecognized — return as-is
    return formula


# ---------------------------------------------------------------------------
# CONTOUR endpoints
# ---------------------------------------------------------------------------

@router.post("/analytics/contour", response_model=ContourRead)
def create_contour(body: ContourCreate, db: Session = Depends(get_db)) -> ContourRead:
    analysis_id = body.id or uuid.uuid4().hex
    existing = db.query(ContourAnalysis).filter(ContourAnalysis.id == analysis_id).first()
    if existing:
        raise HTTPException(status_code=400, detail="ContourAnalysis already exists")

    asset = db.query(models.DataAsset).filter(models.DataAsset.id == body.input_asset_id).first()
    if not asset:
        raise HTTPException(status_code=404, detail=f"DataAsset '{body.input_asset_id}' not found")

    now = _now()
    row = ContourAnalysis(
        id=analysis_id,
        display_name=body.display_name,
        input_asset_id=body.input_asset_id,
        boards=[s.model_dump() for s in body.boards],
        created_at=now,
        updated_at=now,
    )
    db.add(row)
    _audit(db, "system", "analytics.contour.created", "contour_analysis", analysis_id,
           {"input_asset_id": body.input_asset_id})
    db.commit()
    db.refresh(row)
    return row


@router.get("/analytics/contour", response_model=List[ContourRead])
def list_contour(db: Session = Depends(get_db)) -> List[ContourRead]:
    return db.query(ContourAnalysis).order_by(ContourAnalysis.updated_at.desc()).all()


@router.post("/analytics/contour/{analysis_id}/run", response_model=ContourRunResponse)
def run_contour(analysis_id: str, db: Session = Depends(get_db)) -> ContourRunResponse:
    analysis = db.query(ContourAnalysis).filter(ContourAnalysis.id == analysis_id).first()
    if not analysis:
        raise HTTPException(status_code=404, detail=f"ContourAnalysis '{analysis_id}' not found")

    asset = db.query(models.DataAsset).filter(models.DataAsset.id == analysis.input_asset_id).first()
    if not asset:
        raise HTTPException(status_code=404, detail=f"DataAsset '{analysis.input_asset_id}' not found")

    rows = _execute_boards(asset.records or [], analysis.boards or [])
    _audit(db, "system", "analytics.contour.run", "contour_analysis", analysis_id,
           {"row_count": len(rows)})
    db.commit()
    return ContourRunResponse(analysis_id=analysis_id, rows=rows, row_count=len(rows))


# ---------------------------------------------------------------------------
# QUIVER endpoints
# ---------------------------------------------------------------------------

@router.post("/analytics/quiver", response_model=QuiverRead)
def create_quiver(body: QuiverCreate, db: Session = Depends(get_db)) -> QuiverRead:
    analysis_id = body.id or uuid.uuid4().hex
    existing = db.query(QuiverAnalysis).filter(QuiverAnalysis.id == analysis_id).first()
    if existing:
        raise HTTPException(status_code=400, detail="QuiverAnalysis already exists")

    now = _now()
    row = QuiverAnalysis(
        id=analysis_id,
        display_name=body.display_name,
        object_type_id=body.object_type_id,
        time_field=body.time_field,
        value_field=body.value_field,
        created_at=now,
    )
    db.add(row)
    _audit(db, "system", "analytics.quiver.created", "quiver_analysis", analysis_id,
           {"object_type_id": body.object_type_id})
    db.commit()
    db.refresh(row)
    return row


@router.get("/analytics/quiver", response_model=List[QuiverRead])
def list_quiver(db: Session = Depends(get_db)) -> List[QuiverRead]:
    return db.query(QuiverAnalysis).order_by(QuiverAnalysis.created_at.desc()).all()


@router.post("/analytics/quiver/{analysis_id}/compute", response_model=QuiverComputeResponse)
def compute_quiver(analysis_id: str, db: Session = Depends(get_db)) -> QuiverComputeResponse:
    analysis = db.query(QuiverAnalysis).filter(QuiverAnalysis.id == analysis_id).first()
    if not analysis:
        raise HTTPException(status_code=404, detail=f"QuiverAnalysis '{analysis_id}' not found")

    instances = db.query(models.ObjectInstance).filter(
        models.ObjectInstance.object_type_id == analysis.object_type_id
    ).all()

    series = []
    for inst in instances:
        props = inst.properties or {}
        t_raw = props.get(analysis.time_field)
        v_raw = props.get(analysis.value_field)
        t_num = _to_num(t_raw)
        v_num = _to_num(v_raw)
        if t_raw is not None:
            series.append({
                "object_id": inst.id,
                analysis.time_field: t_raw,
                analysis.value_field: v_raw,
                "_t": t_num if t_num is not None else str(t_raw),
            })

    # Sort by time dimension (numeric first, then lexicographic fallback)
    try:
        series.sort(key=lambda x: float(x["_t"]) if isinstance(x["_t"], (int, float)) else 0)
    except Exception:
        series.sort(key=lambda x: str(x["_t"]))

    # Drop helper key
    for s in series:
        s.pop("_t", None)

    values = [_to_num(s.get(analysis.value_field)) for s in series]
    values = [v for v in values if v is not None]
    stats: Dict[str, Any] = {
        "count": len(series),
        "min": min(values) if values else None,
        "max": max(values) if values else None,
        "avg": (sum(values) / len(values)) if values else None,
    }

    _audit(db, "system", "analytics.quiver.computed", "quiver_analysis", analysis_id,
           {"count": len(series)})
    db.commit()
    return QuiverComputeResponse(analysis_id=analysis_id, series=series, stats=stats)


# ---------------------------------------------------------------------------
# FUSION endpoints
# ---------------------------------------------------------------------------

@router.post("/analytics/fusion", response_model=FusionRead)
def create_fusion(body: FusionCreate, db: Session = Depends(get_db)) -> FusionRead:
    workbook_id = body.id or uuid.uuid4().hex
    existing = db.query(FusionWorkbook).filter(FusionWorkbook.id == workbook_id).first()
    if existing:
        raise HTTPException(status_code=400, detail="FusionWorkbook already exists")

    now = _now()
    row = FusionWorkbook(
        id=workbook_id,
        display_name=body.display_name,
        object_type_id=body.object_type_id,
        cells=body.cells,
        created_at=now,
        updated_at=now,
    )
    db.add(row)
    _audit(db, "system", "analytics.fusion.created", "fusion_workbook", workbook_id,
           {"object_type_id": body.object_type_id, "cell_count": len(body.cells)})
    db.commit()
    db.refresh(row)
    return row


@router.get("/analytics/fusion", response_model=List[FusionRead])
def list_fusion(db: Session = Depends(get_db)) -> List[FusionRead]:
    return db.query(FusionWorkbook).order_by(FusionWorkbook.updated_at.desc()).all()


@router.post("/analytics/fusion/{workbook_id}/evaluate", response_model=FusionEvaluateResponse)
def evaluate_fusion(workbook_id: str, db: Session = Depends(get_db)) -> FusionEvaluateResponse:
    workbook = db.query(FusionWorkbook).filter(FusionWorkbook.id == workbook_id).first()
    if not workbook:
        raise HTTPException(status_code=404, detail=f"FusionWorkbook '{workbook_id}' not found")

    results: Dict[str, Any] = {}
    for ref, formula in (workbook.cells or {}).items():
        results[ref] = _eval_formula(str(formula), db)

    _audit(db, "system", "analytics.fusion.evaluated", "fusion_workbook", workbook_id,
           {"cell_count": len(results)})
    db.commit()
    return FusionEvaluateResponse(workbook_id=workbook_id, results=results)

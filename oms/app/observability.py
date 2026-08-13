import time
import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import String, Integer, JSON, Float
from sqlalchemy.orm import Mapped, mapped_column, Session

from .database import Base, get_db
from . import models, models_action

router = APIRouter(tags=["observability"])


# ---------------------------------------------------------------------------
# SQLAlchemy Models
# ---------------------------------------------------------------------------

class MonitoringView(Base):
    __tablename__ = "monitoring_views"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    display_name: Mapped[str] = mapped_column(String, nullable=False)
    scope: Mapped[dict] = mapped_column(JSON, default=dict)
    checks: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[int] = mapped_column(Integer, default=lambda: int(time.time()))


class PlatformTrace(Base):
    __tablename__ = "platform_traces"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    workflow: Mapped[str] = mapped_column(String, nullable=False)
    spans: Mapped[list] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String, default="ok")
    created_at: Mapped[int] = mapped_column(Integer, default=lambda: int(time.time()))


class PlatformMetric(Base):
    __tablename__ = "platform_metrics"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    subject_type: Mapped[str] = mapped_column(String, nullable=False, index=True)
    subject_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    value: Mapped[float] = mapped_column(Float, nullable=False)
    created_at: Mapped[int] = mapped_column(Integer, default=lambda: int(time.time()))


# ---------------------------------------------------------------------------
# Pydantic Schemas
# ---------------------------------------------------------------------------

class MonitoringViewCreate(BaseModel):
    id: Optional[str] = None
    display_name: str
    scope: Dict[str, Any] = Field(default_factory=dict)
    checks: List[Dict[str, Any]] = Field(default_factory=list)


class MonitoringViewRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    display_name: str
    scope: Dict[str, Any]
    checks: List[Dict[str, Any]]
    created_at: int


class CheckResult(BaseModel):
    type: str
    status: str  # ok | stale | failed | no_runs | warn | unknown
    config: Dict[str, Any]
    detail: Optional[Dict[str, Any]] = None


class MonitoringViewEvaluateResponse(BaseModel):
    view_id: str
    overall: str  # ok | stale | failed | warn | unknown (worst of the checks)
    results: List[CheckResult]


class PlatformTraceCreate(BaseModel):
    id: Optional[str] = None
    workflow: str
    spans: List[Dict[str, Any]] = Field(default_factory=list)
    status: str = "ok"


class PlatformTraceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    workflow: str
    spans: List[Dict[str, Any]]
    status: str
    created_at: int


class PlatformMetricCreate(BaseModel):
    id: Optional[str] = None
    subject_type: str
    subject_id: str
    name: str
    value: float


class PlatformMetricRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    subject_type: str
    subject_id: str
    name: str
    value: float
    created_at: int


class ObservabilitySummary(BaseModel):
    total_traces: int
    total_metrics: int
    trace_status_counts: Dict[str, int]
    metric_subject_type_counts: Dict[str, int]


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

_HEALTHY_RUN = {"SUCCESS", "SUCCEEDED", "COMPLETED", "OK"}


def _latest_run(db: Session, pipeline_id: str):
    return (db.query(models.PipelineRun)
            .filter(models.PipelineRun.pipeline_id == pipeline_id)
            .order_by(models.PipelineRun.created_at.desc())
            .first())


def _evaluate_check(db: Session, check: Dict[str, Any]) -> CheckResult:
    """Dispatch each monitoring check to a real evaluator against platform state.

    Supported types (Foundry health-check families): freshness / time_since_last_updated,
    row_count, build_status / schedule_status, sync_freshness, schema. Unknown types
    return 'unknown'. Status is computed from data, not a fixed default.
    """
    check_type = str(check.get("type", "unknown"))
    config = {k: v for k, v in check.items() if k != "type"}
    now = int(time.time())

    if check_type in {"freshness", "time_since_last_updated", "sync_freshness"}:
        asset = db.query(models.DataAsset).filter(models.DataAsset.id == config.get("dataset_id")).first()
        if not asset:
            return CheckResult(type=check_type, status="unknown", config=config,
                               detail={"reason": "dataset not found"})
        age = now - int(asset.updated_at or 0)
        max_age = int(config.get("max_age_seconds", 86400))
        ok = age <= max_age
        return CheckResult(type=check_type, status="ok" if ok else "stale", config=config,
                           detail={"age_seconds": age, "max_age_seconds": max_age})

    if check_type == "row_count":
        asset = db.query(models.DataAsset).filter(models.DataAsset.id == config.get("dataset_id")).first()
        if not asset:
            return CheckResult(type=check_type, status="unknown", config=config,
                               detail={"reason": "dataset not found"})
        count = len(asset.records or [])
        failures = []
        if "min" in config and count < config["min"]:
            failures.append(f"count {count} < min {config['min']}")
        if "max" in config and count > config["max"]:
            failures.append(f"count {count} > max {config['max']}")
        return CheckResult(type=check_type, status="ok" if not failures else "failed", config=config,
                           detail={"row_count": count, "failures": failures})

    if check_type in {"build_status", "schedule_status"}:
        run = _latest_run(db, config.get("pipeline_id", ""))
        if not run:
            return CheckResult(type=check_type, status="no_runs", config=config)
        healthy = str(run.status).upper() in _HEALTHY_RUN
        return CheckResult(type=check_type, status="ok" if healthy else "failed", config=config,
                           detail={"last_run_id": run.id, "last_status": run.status})

    if check_type == "schema":
        asset = db.query(models.DataAsset).filter(models.DataAsset.id == config.get("dataset_id")).first()
        if not asset:
            return CheckResult(type=check_type, status="unknown", config=config,
                               detail={"reason": "dataset not found"})
        expected = set(config.get("expected_columns", []))
        actual = set((asset.asset_schema or {}).keys()) if isinstance(asset.asset_schema, dict) else set()
        missing = sorted(expected - actual)
        return CheckResult(type=check_type, status="ok" if not missing else "failed", config=config,
                           detail={"missing_columns": missing})

    # deterministic test/sentinel types
    if check_type == "always_ok":
        return CheckResult(type=check_type, status="ok", config=config)
    if check_type == "always_warn":
        return CheckResult(type=check_type, status="warn", config=config)
    return CheckResult(type=check_type, status="unknown", config=config)


# ---------------------------------------------------------------------------
# Monitoring Views Endpoints
# ---------------------------------------------------------------------------

@router.post("/observability/monitoring-views", response_model=MonitoringViewRead)
def create_monitoring_view(
    body: MonitoringViewCreate,
    db: Session = Depends(get_db),
) -> MonitoringViewRead:
    view_id = body.id or uuid.uuid4().hex
    existing = db.query(MonitoringView).filter(MonitoringView.id == view_id).first()
    if existing:
        raise HTTPException(status_code=400, detail="MonitoringView already exists")

    row = MonitoringView(
        id=view_id,
        display_name=body.display_name,
        scope=body.scope,
        checks=body.checks,
        created_at=int(time.time()),
    )
    db.add(row)
    db.add(models_action.AuditLog(
        id=uuid.uuid4().hex,
        actor="system",
        event_type="observability.monitoring_view.created",
        subject_type="monitoring_view",
        subject_id=view_id,
        payload={"display_name": body.display_name, "checks": len(body.checks)},
    ))
    db.commit()
    db.refresh(row)
    return MonitoringViewRead.model_validate(row)


@router.get("/observability/monitoring-views", response_model=List[MonitoringViewRead])
def list_monitoring_views(db: Session = Depends(get_db)) -> List[MonitoringViewRead]:
    rows = db.query(MonitoringView).order_by(MonitoringView.created_at.desc()).all()
    return [MonitoringViewRead.model_validate(r) for r in rows]


@router.post(
    "/observability/monitoring-views/{view_id}/evaluate",
    response_model=MonitoringViewEvaluateResponse,
)
def evaluate_monitoring_view(
    view_id: str,
    db: Session = Depends(get_db),
) -> MonitoringViewEvaluateResponse:
    view = db.query(MonitoringView).filter(MonitoringView.id == view_id).first()
    if not view:
        raise HTTPException(status_code=404, detail=f"MonitoringView '{view_id}' not found")

    results = [_evaluate_check(db, chk) for chk in (view.checks or [])]
    # overall = worst status present (failed > stale > warn > unknown > ok)
    severity = {"failed": 4, "stale": 3, "no_runs": 3, "warn": 2, "unknown": 1, "ok": 0}
    overall = "ok"
    if results:
        overall = max((r.status for r in results), key=lambda s: severity.get(s, 1))
    return MonitoringViewEvaluateResponse(view_id=view_id, overall=overall, results=results)


# ---------------------------------------------------------------------------
# Traces Endpoints
# ---------------------------------------------------------------------------

@router.post("/observability/traces", response_model=PlatformTraceRead)
def create_trace(
    body: PlatformTraceCreate,
    db: Session = Depends(get_db),
) -> PlatformTraceRead:
    trace_id = body.id or uuid.uuid4().hex
    existing = db.query(PlatformTrace).filter(PlatformTrace.id == trace_id).first()
    if existing:
        raise HTTPException(status_code=400, detail="PlatformTrace already exists")

    row = PlatformTrace(
        id=trace_id,
        workflow=body.workflow,
        spans=body.spans,
        status=body.status,
        created_at=int(time.time()),
    )
    db.add(row)
    db.add(models_action.AuditLog(
        id=uuid.uuid4().hex,
        actor="system",
        event_type="observability.trace.created",
        subject_type="platform_trace",
        subject_id=trace_id,
        payload={"workflow": body.workflow, "span_count": len(body.spans)},
    ))
    db.commit()
    db.refresh(row)
    return PlatformTraceRead.model_validate(row)


@router.get("/observability/traces", response_model=List[PlatformTraceRead])
def list_traces(db: Session = Depends(get_db)) -> List[PlatformTraceRead]:
    rows = db.query(PlatformTrace).order_by(PlatformTrace.created_at.desc()).all()
    return [PlatformTraceRead.model_validate(r) for r in rows]


@router.get("/observability/traces/{trace_id}", response_model=PlatformTraceRead)
def get_trace(trace_id: str, db: Session = Depends(get_db)) -> PlatformTraceRead:
    row = db.query(PlatformTrace).filter(PlatformTrace.id == trace_id).first()
    if not row:
        raise HTTPException(status_code=404, detail=f"PlatformTrace '{trace_id}' not found")
    return PlatformTraceRead.model_validate(row)


# ---------------------------------------------------------------------------
# Metrics Endpoints
# ---------------------------------------------------------------------------

@router.post("/observability/metrics", response_model=PlatformMetricRead)
def create_metric(
    body: PlatformMetricCreate,
    db: Session = Depends(get_db),
) -> PlatformMetricRead:
    metric_id = body.id or uuid.uuid4().hex
    existing = db.query(PlatformMetric).filter(PlatformMetric.id == metric_id).first()
    if existing:
        raise HTTPException(status_code=400, detail="PlatformMetric already exists")

    row = PlatformMetric(
        id=metric_id,
        subject_type=body.subject_type,
        subject_id=body.subject_id,
        name=body.name,
        value=body.value,
        created_at=int(time.time()),
    )
    db.add(row)
    db.add(models_action.AuditLog(
        id=uuid.uuid4().hex,
        actor="system",
        event_type="observability.metric.created",
        subject_type="platform_metric",
        subject_id=metric_id,
        payload={"name": body.name, "subject_type": body.subject_type, "value": body.value},
    ))
    db.commit()
    db.refresh(row)
    return PlatformMetricRead.model_validate(row)


@router.get("/observability/metrics", response_model=List[PlatformMetricRead])
def list_metrics(
    subject_id: Optional[str] = Query(default=None),
    db: Session = Depends(get_db),
) -> List[PlatformMetricRead]:
    q = db.query(PlatformMetric)
    if subject_id:
        q = q.filter(PlatformMetric.subject_id == subject_id)
    rows = q.order_by(PlatformMetric.created_at.desc()).all()
    return [PlatformMetricRead.model_validate(r) for r in rows]


# ---------------------------------------------------------------------------
# Summary Endpoint
# ---------------------------------------------------------------------------

@router.get("/observability/summary", response_model=ObservabilitySummary)
def observability_summary(db: Session = Depends(get_db)) -> ObservabilitySummary:
    traces = db.query(PlatformTrace).all()
    metrics = db.query(PlatformMetric).all()

    trace_status_counts: Dict[str, int] = {}
    for t in traces:
        s = t.status or "unknown"
        trace_status_counts[s] = trace_status_counts.get(s, 0) + 1

    metric_subject_type_counts: Dict[str, int] = {}
    for m in metrics:
        st = m.subject_type or "unknown"
        metric_subject_type_counts[st] = metric_subject_type_counts.get(st, 0) + 1

    return ObservabilitySummary(
        total_traces=len(traces),
        total_metrics=len(metrics),
        trace_status_counts=trace_status_counts,
        metric_subject_type_counts=metric_subject_type_counts,
    )

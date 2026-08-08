"""Project-scoped job observability, SLO evaluation, and budget admission."""
from __future__ import annotations

import math
import time
import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import Float, Integer, JSON, String, UniqueConstraint
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Mapped, Session, mapped_column

from .database import Base, get_db
from .production_auth import Principal, require_permission
from . import models_action, ops_control, tenancy

router = APIRouter(tags=["runtime_observability"])


def _now() -> int:
    return int(time.time())


class RuntimeJobObservation(Base):
    __tablename__ = "runtime_job_observations"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    project_id: Mapped[str] = mapped_column(String, index=True)
    job_id: Mapped[str] = mapped_column(String, unique=True, index=True)
    correlation_id: Mapped[str] = mapped_column(String, index=True)
    job_type: Mapped[str] = mapped_column(String, index=True)
    actor: Mapped[str] = mapped_column(String, index=True)
    status: Mapped[str] = mapped_column(String, index=True)
    attempt: Mapped[int] = mapped_column(Integer, default=1)
    progress: Mapped[int] = mapped_column(Integer, default=0)
    queue_latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    compute_seconds: Mapped[float] = mapped_column(Float, default=0.0)
    token_units: Mapped[float] = mapped_column(Float, default=0.0)
    record_units: Mapped[float] = mapped_column(Float, default=0.0)
    estimated_cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    metrics: Mapped[dict] = mapped_column(JSON, default=dict)
    spans: Mapped[list] = mapped_column(JSON, default=list)
    error: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    created_at: Mapped[int] = mapped_column(Integer)
    updated_at: Mapped[int] = mapped_column(Integer)
    completed_at: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)


class RuntimeBudgetPolicy(Base):
    __tablename__ = "runtime_budget_policies"
    __table_args__ = (UniqueConstraint("project_id", "metric", name="uq_runtime_project_budget_metric"),)

    id: Mapped[str] = mapped_column(String, primary_key=True)
    project_id: Mapped[str] = mapped_column(String, index=True)
    metric: Mapped[str] = mapped_column(String, index=True)
    limit_value: Mapped[float] = mapped_column(Float)
    window_seconds: Mapped[int] = mapped_column(Integer, default=86400)
    enforcement: Mapped[str] = mapped_column(String, default="HARD")
    enabled: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[int] = mapped_column(Integer)
    updated_at: Mapped[int] = mapped_column(Integer)


class RuntimeSloPolicy(Base):
    __tablename__ = "runtime_slo_policies"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    project_id: Mapped[str] = mapped_column(String, index=True)
    display_name: Mapped[str] = mapped_column(String)
    job_type: Mapped[Optional[str]] = mapped_column(String, nullable=True, index=True)
    metric: Mapped[str] = mapped_column(String)
    operator: Mapped[str] = mapped_column(String)
    threshold: Mapped[float] = mapped_column(Float)
    window_seconds: Mapped[int] = mapped_column(Integer, default=86400)
    severity: Mapped[str] = mapped_column(String, default="warning")
    enabled: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[int] = mapped_column(Integer)
    updated_at: Mapped[int] = mapped_column(Integer)


class RuntimeSloEvaluation(Base):
    __tablename__ = "runtime_slo_evaluations"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    project_id: Mapped[str] = mapped_column(String, index=True)
    policy_id: Mapped[str] = mapped_column(String, index=True)
    status: Mapped[str] = mapped_column(String, index=True)
    observed_value: Mapped[float] = mapped_column(Float)
    threshold: Mapped[float] = mapped_column(Float)
    sample_count: Mapped[int] = mapped_column(Integer)
    details: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[int] = mapped_column(Integer)


class RuntimeBudgetUpsert(BaseModel):
    project_id: str
    metric: str = Field(pattern="^(executions|compute_seconds|token_units|record_units|estimated_cost_usd)$")
    limit_value: float = Field(gt=0)
    window_seconds: int = Field(default=86400, ge=60, le=31536000)
    enforcement: str = Field(default="HARD", pattern="^(HARD|WARN)$")
    enabled: bool = True


class RuntimeSloCreate(BaseModel):
    id: Optional[str] = None
    project_id: str
    display_name: str = Field(min_length=1, max_length=200)
    job_type: Optional[str] = None
    metric: str = Field(pattern="^(availability|error_rate|latency_p95_ms|queue_p95_ms|cost_usd|throughput_per_minute)$")
    operator: str = Field(pattern="^(gte|lte)$")
    threshold: float
    window_seconds: int = Field(default=86400, ge=60, le=31536000)
    severity: str = Field(default="warning", pattern="^(info|warning|error|critical)$")
    enabled: bool = True


def _observation_dict(row: RuntimeJobObservation) -> Dict[str, Any]:
    return {name: getattr(row, name) for name in (
        "id", "project_id", "job_id", "correlation_id", "job_type", "actor", "status", "attempt",
        "progress", "queue_latency_ms", "duration_ms", "compute_seconds", "token_units", "record_units",
        "estimated_cost_usd", "metrics", "spans", "error", "created_at", "updated_at", "completed_at",
    )}


def _budget_dict(row: RuntimeBudgetPolicy) -> Dict[str, Any]:
    return {name: getattr(row, name) for name in ("id", "project_id", "metric", "limit_value", "window_seconds", "enforcement", "enabled", "created_at", "updated_at")}


def _slo_dict(row: RuntimeSloPolicy) -> Dict[str, Any]:
    return {name: getattr(row, name) for name in ("id", "project_id", "display_name", "job_type", "metric", "operator", "threshold", "window_seconds", "severity", "enabled", "created_at", "updated_at")}


def _evaluation_dict(row: RuntimeSloEvaluation) -> Dict[str, Any]:
    return {name: getattr(row, name) for name in ("id", "project_id", "policy_id", "status", "observed_value", "threshold", "sample_count", "details", "created_at")}


def _metric_value(row: RuntimeJobObservation, metric: str) -> float:
    return {
        "executions": 1.0,
        "compute_seconds": float(row.compute_seconds),
        "token_units": float(row.token_units),
        "record_units": float(row.record_units),
        "estimated_cost_usd": float(row.estimated_cost_usd),
    }[metric]


def check_job_admission(db: Session, project_id: str, estimates: Dict[str, float]) -> List[Dict[str, Any]]:
    """Evaluate rolling project budgets before a durable job enters the queue."""
    now = _now()
    proposed = {
        "executions": 1.0,
        "compute_seconds": float(estimates.get("compute_seconds", 0.0)),
        "token_units": float(estimates.get("token_units", 0.0)),
        "record_units": float(estimates.get("record_units", 0.0)),
        "estimated_cost_usd": float(estimates.get("estimated_cost_usd", 0.0)),
    }
    checks: List[Dict[str, Any]] = []
    policies = db.query(RuntimeBudgetPolicy).filter(RuntimeBudgetPolicy.project_id == project_id, RuntimeBudgetPolicy.enabled == True).all()  # noqa: E712
    for policy in policies:
        cutoff = now - policy.window_seconds
        observations = db.query(RuntimeJobObservation).filter(
            RuntimeJobObservation.project_id == project_id,
            RuntimeJobObservation.created_at >= cutoff,
            RuntimeJobObservation.status.notin_(["CANCELLED"]),
        ).all()
        usage = sum(_metric_value(row, policy.metric) for row in observations)
        projected = usage + proposed[policy.metric]
        check = {
            "metric": policy.metric, "usage": round(usage, 8), "proposed": proposed[policy.metric],
            "projected": round(projected, 8), "limit": policy.limit_value,
            "within_limit": projected <= policy.limit_value, "enforcement": policy.enforcement,
        }
        checks.append(check)
        if not check["within_limit"] and policy.enforcement == "HARD":
            raise HTTPException(status_code=429, detail={"message": "Runtime project budget exceeded", "check": check})
    return checks


def record_job_queued(db: Session, job: Any, estimates: Dict[str, float], admission: List[Dict[str, Any]]) -> RuntimeJobObservation:
    now = _now()
    row = RuntimeJobObservation(
        id=f"obs_{uuid.uuid4().hex}", project_id=job.project_id, job_id=job.id,
        correlation_id=str((job.payload or {}).get("correlation_id") or job.id), job_type=job.job_type,
        actor=job.actor, status=job.status, attempt=job.attempt, progress=job.progress,
        queue_latency_ms=0, duration_ms=0, compute_seconds=float(estimates.get("compute_seconds", 0.0)),
        token_units=float(estimates.get("token_units", 0.0)), record_units=float(estimates.get("record_units", 0.0)),
        estimated_cost_usd=float(estimates.get("estimated_cost_usd", 0.0)),
        metrics={"estimates": estimates, "admission": admission},
        spans=[{"name": "queue", "status": "QUEUED", "timestamp": now}], error=None,
        created_at=now, updated_at=now, completed_at=None,
    )
    db.add(row)
    return row


def _merge_numeric_metrics(row: RuntimeJobObservation, metrics: Dict[str, Any]) -> None:
    aliases = {
        "compute_seconds": "compute_seconds", "duration_seconds": "compute_seconds",
        "tokens": "token_units", "token_units": "token_units", "records": "record_units",
        "records_out": "record_units", "estimated_cost_usd": "estimated_cost_usd", "cost_usd": "estimated_cost_usd",
    }
    for key, attribute in aliases.items():
        value = metrics.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            setattr(row, attribute, max(float(getattr(row, attribute)), float(value)))


def record_job_progress(db: Session, job: Any, message: Optional[str], metrics: Dict[str, Any]) -> None:
    row = db.query(RuntimeJobObservation).filter(RuntimeJobObservation.job_id == job.id).first()
    if not row:
        return
    now = _now()
    row.status, row.attempt, row.progress, row.updated_at = job.status, job.attempt, job.progress, now
    if job.started_at:
        row.queue_latency_ms = max(0, job.started_at - job.created_at) * 1000
        row.duration_ms = max(0, now - job.started_at) * 1000
    merged = dict(row.metrics or {})
    merged["latest"] = metrics
    row.metrics = merged
    _merge_numeric_metrics(row, metrics)
    row.spans = list(row.spans or []) + [{"name": "progress", "status": job.status, "progress": job.progress, "message": message, "metrics": metrics, "timestamp": now}]


def record_job_recovery(db: Session, job: Any, reason: str, worker_id: Optional[str]) -> None:
    row = db.query(RuntimeJobObservation).filter(RuntimeJobObservation.job_id == job.id).first()
    if not row:
        return
    now = _now()
    row.status, row.attempt, row.progress, row.updated_at = job.status, job.attempt, job.progress, now
    row.completed_at = None
    row.error = job.error
    metrics = dict(row.metrics or {})
    metrics["recovery_count"] = int(metrics.get("recovery_count") or 0) + 1
    metrics["latest_recovery"] = {"reason": reason, "worker_id": worker_id, "attempt": job.attempt}
    row.metrics = metrics
    row.spans = list(row.spans or []) + [{
        "name": "recovery",
        "status": job.status,
        "attempt": job.attempt,
        "reason": reason,
        "worker_id": worker_id,
        "timestamp": now,
    }]


def record_job_terminal(db: Session, job: Any, status: str, metrics: Optional[Dict[str, Any]] = None, error: Optional[str] = None) -> None:
    row = db.query(RuntimeJobObservation).filter(RuntimeJobObservation.job_id == job.id).first()
    if not row:
        return
    now = _now()
    row.status, row.attempt, row.progress, row.updated_at = status, job.attempt, job.progress, now
    row.completed_at = now if status in {"SUCCEEDED", "FAILED", "CANCELLED"} else None
    row.error = error
    if job.started_at:
        row.queue_latency_ms = max(0, job.started_at - job.created_at) * 1000
        row.duration_ms = max(0, now - job.started_at) * 1000
        row.compute_seconds = max(row.compute_seconds, row.duration_ms / 1000.0)
    final_metrics = dict(metrics or {})
    _merge_numeric_metrics(row, final_metrics)
    merged = dict(row.metrics or {})
    merged["result"] = final_metrics
    row.metrics = merged
    row.spans = list(row.spans or []) + [{"name": "terminal", "status": status, "error": error, "metrics": final_metrics, "timestamp": now}]


def _percentile(values: List[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, math.ceil(percentile * len(ordered)) - 1))
    return float(ordered[index])


def _evaluate_policy(db: Session, policy: RuntimeSloPolicy) -> RuntimeSloEvaluation:
    cutoff = _now() - policy.window_seconds
    query = db.query(RuntimeJobObservation).filter(RuntimeJobObservation.project_id == policy.project_id, RuntimeJobObservation.created_at >= cutoff)
    if policy.job_type:
        query = query.filter(RuntimeJobObservation.job_type == policy.job_type)
    rows = query.all()
    terminal = [row for row in rows if row.status in {"SUCCEEDED", "FAILED", "CANCELLED"}]
    successes = [row for row in terminal if row.status == "SUCCEEDED"]
    if policy.metric == "availability":
        observed = len(successes) / len(terminal) if terminal else 0.0
    elif policy.metric == "error_rate":
        observed = len([row for row in terminal if row.status == "FAILED"]) / len(terminal) if terminal else 0.0
    elif policy.metric == "latency_p95_ms":
        observed = _percentile([row.duration_ms for row in terminal], 0.95)
    elif policy.metric == "queue_p95_ms":
        observed = _percentile([row.queue_latency_ms for row in rows], 0.95)
    elif policy.metric == "cost_usd":
        observed = sum(row.estimated_cost_usd for row in rows)
    else:
        observed = (len(successes) * 60.0) / policy.window_seconds
    passed = observed >= policy.threshold if policy.operator == "gte" else observed <= policy.threshold
    evaluation = RuntimeSloEvaluation(
        id=f"sloeval_{uuid.uuid4().hex}", project_id=policy.project_id, policy_id=policy.id,
        status="PASS" if passed else "FAIL", observed_value=round(observed, 8), threshold=policy.threshold,
        sample_count=len(rows), details={"job_type": policy.job_type, "metric": policy.metric, "operator": policy.operator, "window_seconds": policy.window_seconds}, created_at=_now(),
    )
    db.add(evaluation)
    if not passed:
        ops_control.record_ops_event(
            db, source="runtime_observability", event_type="runtime.slo.breached", severity=policy.severity,
            title=f"SLO breached: {policy.display_name}", subject_type="runtime_slo_policy", subject_id=policy.id,
            payload={"project_id": policy.project_id, "observed": observed, "threshold": policy.threshold, "metric": policy.metric},
        )
    return evaluation


def backfill_observations(db: Session, project_id: str) -> int:
    from . import platform_runtime
    known = {row.job_id for row in db.query(RuntimeJobObservation).filter(RuntimeJobObservation.project_id == project_id).all()}
    created = 0
    for job in db.query(platform_runtime.PlatformJob).filter(platform_runtime.PlatformJob.project_id == project_id).all():
        if job.id in known:
            continue
        try:
            with db.begin_nested():
                record_job_queued(db, job, {}, [])
                db.flush()
                if job.status == "RUNNING":
                    record_job_progress(db, job, "Backfilled running job", {})
                elif job.status in {"SUCCEEDED", "FAILED", "CANCELLED"}:
                    record_job_terminal(db, job, job.status, dict(job.result or {}), job.error)
                db.flush()
            created += 1
            known.add(job.id)
        except IntegrityError:
            # A concurrent summary request inserted the same historical job.
            continue
    return created


@router.put("/runtime/observability/budgets")
def upsert_budget(body: RuntimeBudgetUpsert, principal: Principal = Depends(require_permission("administer")), db: Session = Depends(get_db)):
    tenancy.assert_project_permission(db, principal, body.project_id, "administer")
    row = db.query(RuntimeBudgetPolicy).filter(RuntimeBudgetPolicy.project_id == body.project_id, RuntimeBudgetPolicy.metric == body.metric).first()
    now = _now()
    if not row:
        row = RuntimeBudgetPolicy(id=f"rtbudget_{uuid.uuid4().hex}", project_id=body.project_id, metric=body.metric, limit_value=body.limit_value, window_seconds=body.window_seconds, enforcement=body.enforcement, enabled=body.enabled, created_at=now, updated_at=now)
        db.add(row)
    else:
        row.limit_value, row.window_seconds, row.enforcement, row.enabled, row.updated_at = body.limit_value, body.window_seconds, body.enforcement, body.enabled, now
    db.add(models_action.AuditLog(id=uuid.uuid4().hex, actor=principal.id, event_type="runtime.budget.updated", subject_type="runtime_budget", subject_id=row.id, payload={"project_id": body.project_id, "metric": body.metric, "limit": body.limit_value, "enforcement": body.enforcement}))
    db.commit()
    return _budget_dict(row)


@router.get("/runtime/observability/budgets")
def list_budgets(project_id: str = "default", principal: Principal = Depends(require_permission("view")), db: Session = Depends(get_db)):
    tenancy.assert_project_permission(db, principal, project_id, "view")
    return [_budget_dict(row) for row in db.query(RuntimeBudgetPolicy).filter(RuntimeBudgetPolicy.project_id == project_id).order_by(RuntimeBudgetPolicy.metric).all()]


@router.post("/runtime/observability/slo-policies", status_code=201)
def create_slo(body: RuntimeSloCreate, principal: Principal = Depends(require_permission("administer")), db: Session = Depends(get_db)):
    tenancy.assert_project_permission(db, principal, body.project_id, "administer")
    row = RuntimeSloPolicy(id=body.id or f"slo_{uuid.uuid4().hex}", project_id=body.project_id, display_name=body.display_name, job_type=body.job_type, metric=body.metric, operator=body.operator, threshold=body.threshold, window_seconds=body.window_seconds, severity=body.severity, enabled=body.enabled, created_at=_now(), updated_at=_now())
    if db.get(RuntimeSloPolicy, row.id):
        raise HTTPException(status_code=409, detail="Runtime SLO policy already exists")
    db.add(row)
    db.commit()
    return _slo_dict(row)


@router.get("/runtime/observability/slo-policies")
def list_slos(project_id: str = "default", principal: Principal = Depends(require_permission("view")), db: Session = Depends(get_db)):
    tenancy.assert_project_permission(db, principal, project_id, "view")
    return [_slo_dict(row) for row in db.query(RuntimeSloPolicy).filter(RuntimeSloPolicy.project_id == project_id).order_by(RuntimeSloPolicy.created_at.desc()).all()]


@router.post("/runtime/observability/slo-policies/{policy_id}/evaluate")
def evaluate_slo(policy_id: str, principal: Principal = Depends(require_permission("execute")), db: Session = Depends(get_db)):
    policy = db.get(RuntimeSloPolicy, policy_id)
    if not policy:
        raise HTTPException(status_code=404, detail="Runtime SLO policy not found")
    tenancy.assert_project_permission(db, principal, policy.project_id, "execute")
    evaluation = _evaluate_policy(db, policy)
    db.commit()
    return _evaluation_dict(evaluation)


@router.get("/runtime/observability/jobs")
def list_observations(project_id: str = "default", status: Optional[str] = None, job_type: Optional[str] = None, limit: int = Query(100, ge=1, le=500), principal: Principal = Depends(require_permission("view")), db: Session = Depends(get_db)):
    tenancy.assert_project_permission(db, principal, project_id, "view")
    backfill_observations(db, project_id)
    db.commit()
    query = db.query(RuntimeJobObservation).filter(RuntimeJobObservation.project_id == project_id)
    if status:
        query = query.filter(RuntimeJobObservation.status == status.upper())
    if job_type:
        query = query.filter(RuntimeJobObservation.job_type == job_type)
    return [_observation_dict(row) for row in query.order_by(RuntimeJobObservation.created_at.desc()).limit(limit).all()]


@router.get("/runtime/observability/jobs/{job_id}")
def get_observation(job_id: str, principal: Principal = Depends(require_permission("view")), db: Session = Depends(get_db)):
    row = db.query(RuntimeJobObservation).filter(RuntimeJobObservation.job_id == job_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Runtime job observation not found")
    tenancy.assert_project_permission(db, principal, row.project_id, "view")
    return _observation_dict(row)


@router.get("/runtime/observability/summary")
def runtime_summary(project_id: str = "default", principal: Principal = Depends(require_permission("view")), db: Session = Depends(get_db)):
    tenancy.assert_project_permission(db, principal, project_id, "view")
    backfill_observations(db, project_id)
    db.commit()
    rows = db.query(RuntimeJobObservation).filter(RuntimeJobObservation.project_id == project_id).all()
    terminal = [row for row in rows if row.status in {"SUCCEEDED", "FAILED", "CANCELLED"}]
    successes = [row for row in terminal if row.status == "SUCCEEDED"]
    status_counts: Dict[str, int] = {}
    for row in rows:
        status_counts[row.status] = status_counts.get(row.status, 0) + 1
    worker_ids = {
        str((span.get("metrics") or {}).get("worker_id"))
        for row in rows for span in (row.spans or [])
        if (span.get("metrics") or {}).get("worker_id")
    }
    policies = db.query(RuntimeSloPolicy).filter(RuntimeSloPolicy.project_id == project_id, RuntimeSloPolicy.enabled == True).all()  # noqa: E712
    latest_evaluations = []
    for policy in policies:
        latest = db.query(RuntimeSloEvaluation).filter(RuntimeSloEvaluation.policy_id == policy.id).order_by(RuntimeSloEvaluation.created_at.desc()).first()
        if latest:
            latest_evaluations.append({**_evaluation_dict(latest), "display_name": policy.display_name, "metric": policy.metric, "severity": policy.severity})
    return {
        "project_id": project_id, "total_jobs": len(rows), "status_counts": status_counts,
        "availability": round(len(successes) / len(terminal), 6) if terminal else 0.0,
        "latency_p95_ms": _percentile([row.duration_ms for row in terminal], 0.95),
        "queue_p95_ms": _percentile([row.queue_latency_ms for row in rows], 0.95),
        "compute_seconds": round(sum(row.compute_seconds for row in rows), 6),
        "token_units": round(sum(row.token_units for row in rows), 6),
        "record_units": round(sum(row.record_units for row in rows), 6),
        "estimated_cost_usd": round(sum(row.estimated_cost_usd for row in rows), 8),
        "active_workers": len(worker_ids),
        "slo_evaluations": latest_evaluations,
        "warnings": [f"{row['display_name']} is breaching" for row in latest_evaluations if row["status"] == "FAIL"],
        "last_updated": _now(),
    }


@router.get("/ui-state/runtime-operations")
def ui_state(project_id: str = "default", principal: Principal = Depends(require_permission("view")), db: Session = Depends(get_db)):
    summary = runtime_summary(project_id, principal, db)
    jobs = list_observations(project_id=project_id, limit=50, principal=principal, db=db)
    budgets = list_budgets(project_id, principal, db)
    slos = list_slos(project_id, principal, db)
    return {
        "summary": summary,
        "primary_actions": [{"id": "refresh", "label": "Refresh runtime"}, {"id": "evaluate_slos", "label": "Evaluate SLOs"}],
        "sections": [{"id": "jobs", "title": "Durable jobs", "rows": jobs}, {"id": "budgets", "title": "Project budgets", "rows": budgets}, {"id": "slos", "title": "Service objectives", "rows": slos}],
        "evidence_links": [{"label": "Job events", "href": "/jobs"}, {"label": "Ingestion runtime", "href": "/ingestion/summary"}],
        "warnings": summary["warnings"], "permissions": sorted(tenancy.project_permissions(db, principal, project_id)), "last_updated": summary["last_updated"],
    }

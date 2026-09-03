"""
Observability — real health checks, trace rollups & metric aggregation
(deep-fidelity pass 7, Observability).

The base observability module's monitoring-view evaluate returns a default status.
This module adds checks that actually inspect platform state: dataset **freshness**
(from `DataAsset.updated_at`), **build status** (latest `PipelineRun`), **row-count**
bounds, plus stateless **trace rollup** and **metric aggregation** (avg/min/max/p50).
Additive; deterministic.
"""
import time
from typing import Optional, List, Any, Dict

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel, Field

from .database import get_db
from . import models, production_auth, semantic_scope

router = APIRouter(tags=["observability_checks"])


def _now() -> int:
    return int(time.time())


class FreshnessRequest(BaseModel):
    dataset_id: str
    max_age_seconds: int = 86400


class RowCountRequest(BaseModel):
    dataset_id: str
    min: Optional[int] = None
    max: Optional[int] = None


class TraceRollupRequest(BaseModel):
    spans: List[Dict[str, Any]]


class MetricAggregateRequest(BaseModel):
    name: Optional[str] = None
    values: List[float] = Field(default_factory=list)


@router.post("/observability/checks/freshness")
def check_freshness(body: FreshnessRequest, db: Session = Depends(get_db),
                    principal: production_auth.Principal = Depends(
                       production_auth.require_permission("view"))):
    # These three routes take a dataset or pipeline id from the caller and answer questions
    # about it: whether it exists, how stale it is, how many rows it holds, and -- for a
    # build -- its last run id, status, record count and error text. Unauthorized, that is a
    # monitoring console for every project in the installation.
    # T2 of GOAL_TENANCY_2026-08-27.
    asset = semantic_scope.asset_for(db, principal, body.dataset_id, "view")
    age = _now() - int(asset.updated_at or 0)
    ok = age <= body.max_age_seconds
    return {"dataset_id": body.dataset_id, "age_seconds": age, "max_age_seconds": body.max_age_seconds,
            "status": "ok" if ok else "stale"}


@router.post("/observability/checks/build-status")
def check_build_status(pipeline_id: str, db: Session = Depends(get_db),
                       principal: production_auth.Principal = Depends(
                       production_auth.require_permission("view"))):
    # A pipeline the caller cannot see reports "no_runs" rather than 403, so the route does
    # not become a way to ask which pipeline ids exist elsewhere.
    pipeline = (semantic_scope.accessible_query(db, principal, models.PipelineDefinition, "view")
                .filter(models.PipelineDefinition.id == pipeline_id).first())
    run = None if pipeline is None else (
        db.query(models.PipelineRun)
        .filter(models.PipelineRun.pipeline_id == pipeline_id,
                models.PipelineRun.project_id == pipeline.project_id)
        .order_by(models.PipelineRun.created_at.desc()).first())
    if not run:
        return {"pipeline_id": pipeline_id, "status": "no_runs"}
    healthy = str(run.status).upper() in {"SUCCESS", "SUCCEEDED", "COMPLETED", "OK"}
    return {"pipeline_id": pipeline_id, "last_run_id": run.id, "last_status": run.status,
            "status": "ok" if healthy else "failed",
            "records_out": run.records_out, "error": run.error}


@router.post("/observability/checks/row-count")
def check_row_count(body: RowCountRequest, db: Session = Depends(get_db),
                    principal: production_auth.Principal = Depends(
                       production_auth.require_permission("view"))):
    asset = semantic_scope.asset_for(db, principal, body.dataset_id, "view")
    count = len(asset.records or [])
    failures = []
    if body.min is not None and count < body.min:
        failures.append(f"row count {count} < min {body.min}")
    if body.max is not None and count > body.max:
        failures.append(f"row count {count} > max {body.max}")
    return {"dataset_id": body.dataset_id, "row_count": count,
            "status": "ok" if not failures else "failed", "failures": failures}


@router.post("/observability/traces/rollup")
def trace_rollup(body: TraceRollupRequest):
    spans = body.spans or []
    total = sum(float(s.get("duration_ms", 0)) for s in spans)
    by_status: Dict[str, int] = {}
    for s in spans:
        st = str(s.get("status", "ok"))
        by_status[st] = by_status.get(st, 0) + 1
    slowest = max(spans, key=lambda s: float(s.get("duration_ms", 0)), default=None)
    return {"span_count": len(spans), "total_duration_ms": round(total, 3),
            "by_status": by_status, "slowest_span": slowest.get("name") if slowest else None,
            "ok": by_status.get("error", 0) == 0}


@router.post("/observability/metrics/aggregate")
def metric_aggregate(body: MetricAggregateRequest):
    vals = sorted(float(v) for v in body.values if isinstance(v, (int, float)) and not isinstance(v, bool))
    if not vals:
        return {"name": body.name, "count": 0}
    n = len(vals)
    p50 = vals[n // 2] if n % 2 else (vals[n // 2 - 1] + vals[n // 2]) / 2
    p95 = vals[min(n - 1, int(round(0.95 * (n - 1))))]
    return {"name": body.name, "count": n, "min": vals[0], "max": vals[-1],
            "avg": round(sum(vals) / n, 6), "p50": p50, "p95": p95}

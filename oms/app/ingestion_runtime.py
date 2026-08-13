"""Durable, project-scoped connector and stream ingestion runtime."""
from __future__ import annotations

import json
import time
import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import Float, Integer, JSON, String, UniqueConstraint
from sqlalchemy.orm import Mapped, Session, mapped_column

from .database import Base, get_db
from .production_auth import Principal, require_permission
from . import admin_usage, connectivity, connectivity_ops, connector_runtime, models, models_action, ops_control, platform_runtime, streaming, tenancy

router = APIRouter(tags=["ingestion_runtime"])


def _now() -> int:
    return int(time.time())


class IngestionRun(Base):
    __tablename__ = "ingestion_runs"
    __table_args__ = (UniqueConstraint("project_id", "idempotency_key", name="uq_ingestion_project_idempotency"),)

    id: Mapped[str] = mapped_column(String, primary_key=True)
    project_id: Mapped[str] = mapped_column(String, index=True)
    job_id: Mapped[Optional[str]] = mapped_column(String, nullable=True, unique=True, index=True)
    idempotency_key: Mapped[str] = mapped_column(String)
    run_type: Mapped[str] = mapped_column(String, index=True)
    resource_type: Mapped[str] = mapped_column(String)
    resource_id: Mapped[str] = mapped_column(String, index=True)
    status: Mapped[str] = mapped_column(String, default="QUEUED", index=True)
    records_in: Mapped[int] = mapped_column(Integer, default=0)
    records_out: Mapped[int] = mapped_column(Integer, default=0)
    bytes_processed: Mapped[int] = mapped_column(Integer, default=0)
    estimated_cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    metrics: Mapped[dict] = mapped_column(JSON, default=dict)
    error: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    created_at: Mapped[int] = mapped_column(Integer)
    started_at: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    completed_at: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)


class IngestionBudget(Base):
    __tablename__ = "ingestion_budgets"
    __table_args__ = (UniqueConstraint("project_id", "metric", name="uq_ingestion_project_budget_metric"),)

    id: Mapped[str] = mapped_column(String, primary_key=True)
    project_id: Mapped[str] = mapped_column(String, index=True)
    metric: Mapped[str] = mapped_column(String, index=True)
    limit_value: Mapped[float] = mapped_column(Float)
    window_seconds: Mapped[int] = mapped_column(Integer, default=86400)
    enforcement: Mapped[str] = mapped_column(String, default="HARD")
    created_at: Mapped[int] = mapped_column(Integer)
    updated_at: Mapped[int] = mapped_column(Integer)


class IngestionDeadLetter(Base):
    __tablename__ = "ingestion_dead_letters"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    project_id: Mapped[str] = mapped_column(String, index=True)
    run_id: Mapped[str] = mapped_column(String, index=True)
    resource_type: Mapped[str] = mapped_column(String)
    resource_id: Mapped[str] = mapped_column(String, index=True)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    error: Mapped[str] = mapped_column(String)
    status: Mapped[str] = mapped_column(String, default="PENDING", index=True)
    replay_job_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[int] = mapped_column(Integer)
    updated_at: Mapped[int] = mapped_column(Integer)


class EnqueueSyncRequest(BaseModel):
    records: Optional[List[Dict[str, Any]]] = None
    priority: int = Field(default=50, ge=0, le=100)
    max_attempts: int = Field(default=3, ge=1, le=20)
    timeout_seconds: int = Field(default=900, ge=1, le=86400)
    idempotency_key: Optional[str] = Field(default=None, min_length=1, max_length=200)


class EnqueueReplayRequest(BaseModel):
    records: List[Dict[str, Any]] = Field(default_factory=list)
    timestamp_field: Optional[str] = None
    start_ts: Optional[int] = None
    interval_seconds: int = Field(default=1, ge=0)
    target_asset_id: Optional[str] = None
    archive_to_dataset: bool = False
    priority: int = Field(default=50, ge=0, le=100)
    max_attempts: int = Field(default=3, ge=1, le=20)
    timeout_seconds: int = Field(default=900, ge=1, le=86400)
    idempotency_key: Optional[str] = Field(default=None, min_length=1, max_length=200)


class WorkerRequest(BaseModel):
    worker_id: str = Field(default="ingestion-worker", min_length=1, max_length=200)
    lease_seconds: int = Field(default=60, ge=10, le=900)
    job_id: Optional[str] = None
    inject_failure: bool = False


class BudgetUpsert(BaseModel):
    project_id: str
    metric: str = Field(pattern="^(records|bytes|estimated_cost_usd)$")
    limit_value: float = Field(gt=0)
    window_seconds: int = Field(default=86400, ge=60, le=31536000)
    enforcement: str = Field(default="HARD", pattern="^(HARD|WARN)$")


def _run_dict(row: IngestionRun) -> Dict[str, Any]:
    return {name: getattr(row, name) for name in (
        "id", "project_id", "job_id", "idempotency_key", "run_type", "resource_type", "resource_id",
        "status", "records_in", "records_out", "bytes_processed", "estimated_cost_usd", "metrics",
        "error", "created_at", "started_at", "completed_at",
    )}


def _dead_letter_dict(row: IngestionDeadLetter) -> Dict[str, Any]:
    return {name: getattr(row, name) for name in (
        "id", "project_id", "run_id", "resource_type", "resource_id", "payload", "error", "status",
        "replay_job_id", "attempts", "created_at", "updated_at",
    )}


def _payload_size(records: List[Dict[str, Any]]) -> int:
    return len(json.dumps(records, sort_keys=True, separators=(",", ":")).encode("utf-8"))


def _estimate_cost(records: int, payload_bytes: int) -> float:
    return round((records * 0.000001) + (payload_bytes / 1_000_000_000), 8)


def _budget_value(run: IngestionRun, metric: str) -> float:
    return {"records": float(run.records_in), "bytes": float(run.bytes_processed), "estimated_cost_usd": float(run.estimated_cost_usd)}[metric]


def _budget_check(db: Session, project_id: str, records: int, payload_bytes: int) -> List[Dict[str, Any]]:
    now = _now()
    proposed = {"records": float(records), "bytes": float(payload_bytes), "estimated_cost_usd": _estimate_cost(records, payload_bytes)}
    checks: List[Dict[str, Any]] = []
    for budget in db.query(IngestionBudget).filter(IngestionBudget.project_id == project_id).all():
        cutoff = now - budget.window_seconds
        prior = sum(_budget_value(run, budget.metric) for run in db.query(IngestionRun).filter(
            IngestionRun.project_id == project_id,
            IngestionRun.created_at >= cutoff,
            IngestionRun.status.in_(["SUCCEEDED", "WARN"]),
        ).all())
        projected = prior + proposed[budget.metric]
        check = {
            "metric": budget.metric, "usage": round(prior, 8), "proposed": proposed[budget.metric],
            "projected": round(projected, 8), "limit": budget.limit_value,
            "within_limit": projected <= budget.limit_value, "enforcement": budget.enforcement,
        }
        checks.append(check)
        if not check["within_limit"] and budget.enforcement == "HARD":
            raise HTTPException(status_code=429, detail={"message": "Ingestion budget exceeded", "check": check})
    return checks


def _enqueue(db: Session, principal: Principal, project_id: str, run_type: str, resource_type: str, resource_id: str, payload: Dict[str, Any], priority: int, max_attempts: int, timeout_seconds: int, idempotency_key: Optional[str]) -> Dict[str, Any]:
    tenancy.assert_project_permission(db, principal, project_id, "execute")
    key = idempotency_key or uuid.uuid4().hex
    existing = db.query(IngestionRun).filter(IngestionRun.project_id == project_id, IngestionRun.idempotency_key == key).first()
    if existing:
        return {"run": _run_dict(existing), "job": platform_runtime.get_job(existing.job_id, principal, db) if existing.job_id else None, "idempotent_replay": True}
    now = _now()
    run = IngestionRun(
        id=f"ingrun_{uuid.uuid4().hex}", project_id=project_id, job_id=None, idempotency_key=key,
        run_type=run_type, resource_type=resource_type, resource_id=resource_id, status="QUEUED",
        records_in=0, records_out=0, bytes_processed=0, estimated_cost_usd=0.0, metrics={}, error=None,
        created_at=now, started_at=None, completed_at=None,
    )
    db.add(run)
    db.flush()
    job = platform_runtime.create_job(platform_runtime.JobCreate(
        project_id=project_id, job_type=run_type, subject_type=resource_type, subject_id=resource_id,
        payload={**payload, "ingestion_run_id": run.id}, priority=priority, max_attempts=max_attempts,
        timeout_seconds=timeout_seconds, idempotency_key=key,
    ), principal, db)
    run.job_id = job["id"]
    db.commit()
    return {"run": _run_dict(run), "job": job, "idempotent_replay": False}


def _record_dead_letter(db: Session, run: IngestionRun, payload: Dict[str, Any], error: str) -> IngestionDeadLetter:
    row = IngestionDeadLetter(
        id=f"dlq_{uuid.uuid4().hex}", project_id=run.project_id, run_id=run.id,
        resource_type=run.resource_type, resource_id=run.resource_id, payload=payload, error=error,
        status="PENDING", replay_job_id=None, attempts=0, created_at=_now(), updated_at=_now(),
    )
    db.add(row)
    return row


def _valid_records(db: Session, run: IngestionRun, records: List[Any]) -> tuple[List[Dict[str, Any]], int]:
    valid: List[Dict[str, Any]] = []
    rejected = 0
    for payload in records:
        if not isinstance(payload, dict):
            _record_dead_letter(db, run, {"value": payload}, "Record must be an object")
            rejected += 1
        elif payload.get("__ingestion_error"):
            _record_dead_letter(db, run, dict(payload), str(payload.get("__ingestion_error")))
            rejected += 1
        else:
            valid.append(dict(payload))
    return valid, rejected


def _execute_sync(db: Session, run: IngestionRun, payload: Dict[str, Any]) -> Dict[str, Any]:
    sync = db.get(connectivity.ConnectionSync, run.resource_id)
    if not sync or sync.project_id != run.project_id:
        raise HTTPException(status_code=404, detail="Project-scoped connection sync not found")
    asset = db.get(models.DataAsset, sync.target_asset_id)
    if not asset:
        raise HTTPException(status_code=404, detail=f"Target dataset '{sync.target_asset_id}' not found")
    source = db.get(connectivity.ConnectionSource, sync.source_id)
    if not source or source.project_id != run.project_id:
        raise HTTPException(status_code=404, detail="Project-scoped connection source not found")
    supplied_records = payload.get("records")
    live = supplied_records is None and str((source.config or {}).get("execution_mode") or "sample").lower() == "live"
    state = db.get(connectivity_ops.SyncCursorState, sync.id) if sync.mode == "incremental" else None
    previous_cursor = state.last_value.get("value") if state and isinstance(state.last_value, dict) else None
    adapter_result = None
    if live:
        adapter_result = connector_runtime.fetch_records(
            db, source, cursor=previous_cursor, cursor_field=sync.cursor_field,
            limit=max(1, min(100000, int((source.config or {}).get("batch_size", 1000)))),
            sync_id=sync.id, ingestion_run_id=run.id, operation="sync",
        )
        source_records: List[Any] = adapter_result.records
    else:
        source_records = supplied_records if supplied_records is not None else list(sync.sample_records or [])
    adapter_managed_cursor = bool(live and adapter_result and adapter_result.next_cursor is not None)
    if sync.mode == "incremental" and not live:
        if not sync.cursor_field:
            raise HTTPException(status_code=422, detail="Incremental sample sync requires a cursor_field")

        def newer(value: Any) -> bool:
            if previous_cursor is None:
                return True
            try:
                return value > previous_cursor
            except TypeError:
                return str(value) > str(previous_cursor)

        source_records = [row for row in source_records if isinstance(row, dict) and row.get(sync.cursor_field) is not None and newer(row.get(sync.cursor_field))]
    elif sync.mode == "incremental" and not adapter_managed_cursor and not sync.cursor_field:
        raise HTTPException(status_code=422, detail="Live incremental connector did not provide a cursor")
    records, rejected = _valid_records(db, run, source_records)
    payload_bytes = _payload_size(records)
    budget_checks = _budget_check(db, run.project_id, len(records), payload_bytes)
    asset.records = list(asset.records or []) + records
    asset.asset_schema = {**dict(asset.asset_schema or {}), "project_id": run.project_id, "last_ingestion_run_id": run.id, "source_adapter_id": connector_runtime.adapter_id_for_source(source) if live else "sample"}
    asset.updated_at = _now()
    next_cursor = adapter_result.next_cursor if adapter_managed_cursor else previous_cursor
    if sync.mode == "incremental" and not adapter_managed_cursor and sync.cursor_field:
        cursor_values = [row.get(sync.cursor_field) for row in records if row.get(sync.cursor_field) is not None]
        next_cursor = max(cursor_values) if cursor_values else previous_cursor
    if sync.mode == "incremental":
        if state:
            state.last_value = {"value": next_cursor}
            state.cursor_field = sync.cursor_field or "__connector_cursor"
            state.runs += 1
            state.updated_at = _now()
        else:
            db.add(connectivity_ops.SyncCursorState(sync_id=sync.id, cursor_field=sync.cursor_field or "__connector_cursor", last_value={"value": next_cursor}, runs=1, updated_at=_now()))
    sync_run = connectivity.SyncRun(
        id=f"sync_{run.id}", sync_id=sync.id, status="completed" if not rejected else "completed_with_errors",
        records_in=len(records) + rejected, records_out=len(records), created_at=run.started_at or _now(), completed_at=_now(),
    )
    db.add(sync_run)
    return {
        "records_in": len(records) + rejected, "records_out": len(records), "rejected": rejected,
        "bytes_processed": payload_bytes, "budget_checks": budget_checks, "target_asset_id": sync.target_asset_id,
        "adapter_id": connector_runtime.adapter_id_for_source(source) if live else "sample", "live_fetch": live,
        "previous_cursor": previous_cursor, "next_cursor": next_cursor,
        "fetch_metadata": adapter_result.metadata if adapter_result else {},
    }


def _execute_replay(db: Session, run: IngestionRun, payload: Dict[str, Any]) -> Dict[str, Any]:
    stream = db.get(streaming.Stream, run.resource_id)
    if not stream or stream.project_id != run.project_id:
        raise HTTPException(status_code=404, detail="Project-scoped stream not found")
    records = list(payload.get("records") or (stream.schema_ or {}).get("sample_records") or [])
    records, rejected = _valid_records(db, run, records)
    from . import stream_processing
    stream_processing.enforce_publish_capacity(db, stream.id, len(records))
    payload_bytes = _payload_size(records)
    budget_checks = _budget_check(db, run.project_id, len(records), payload_bytes)
    start_ts = payload.get("start_ts") if payload.get("start_ts") is not None else _now()
    interval = int(payload.get("interval_seconds", 1))
    timestamp_field = payload.get("timestamp_field")
    pending_records = [
        (index, record, f"streamrec_{run.id}_{index}")
        for index, record in enumerate(records)
        if not db.get(streaming.StreamRecord, f"streamrec_{run.id}_{index}")
    ]
    sequences = iter(streaming.allocate_sequences(db, stream.id, len(pending_records)))
    for index, record, record_id in pending_records:
        ts = start_ts + index * interval
        if timestamp_field and record.get(timestamp_field) is not None:
            try:
                ts = int(record[timestamp_field])
            except (TypeError, ValueError):
                pass
        db.add(streaming.StreamRecord(
            id=record_id, stream_id=stream.id, sequence=next(sequences), payload=record,
            ts=ts, archived=False, archived_at=None, created_at=_now(),
        ))
    target_asset_id = payload.get("target_asset_id")
    if payload.get("archive_to_dataset") and target_asset_id:
        asset = db.get(models.DataAsset, target_asset_id)
        if not asset:
            raise HTTPException(status_code=404, detail=f"Target dataset '{target_asset_id}' not found")
        asset.records = list(asset.records or []) + records
        asset.asset_schema = {**dict(asset.asset_schema or {}), "project_id": run.project_id, "source_stream_id": stream.id, "last_ingestion_run_id": run.id}
        asset.updated_at = _now()
    return {"records_in": len(records) + rejected, "records_out": len(records), "rejected": rejected, "bytes_processed": payload_bytes, "budget_checks": budget_checks, "target_asset_id": target_asset_id}


def _finish_run(db: Session, run: IngestionRun, result: Dict[str, Any]) -> None:
    now = _now()
    run.records_in = int(result["records_in"])
    run.records_out = int(result["records_out"])
    run.bytes_processed = int(result["bytes_processed"])
    run.estimated_cost_usd = _estimate_cost(run.records_in, run.bytes_processed)
    run.status = "WARN" if result.get("rejected") else "SUCCEEDED"
    run.metrics = {**result, "duration_ms": max(0, now - (run.started_at or now)) * 1000}
    run.error = None
    run.completed_at = now
    db.add(admin_usage.UsageRecord(
        id=uuid.uuid4().hex, principal="ingestion-worker", project=run.project_id, organization=None,
        resource_type=run.resource_type, resource_id=run.resource_id, metric="rows", value=float(run.records_in), created_at=now,
    ))
    db.add(models_action.AuditLog(
        id=uuid.uuid4().hex, actor="ingestion-worker", event_type="ingestion.run.completed",
        subject_type="ingestion_run", subject_id=run.id, payload={"project_id": run.project_id, **result},
    ))
    ops_control.record_ops_event(
        db, source="ingestion", event_type="ingestion.run.completed", severity="warn" if result.get("rejected") else "info",
        title=f"{run.run_type} processed {run.records_out} record(s)", subject_type="ingestion_run", subject_id=run.id,
        payload={"project_id": run.project_id, **result},
    )


@router.get("/ingestion/connectors/catalog")
def connector_catalog(principal: Principal = Depends(require_permission("view"))):
    catalog = connector_runtime.adapter_catalog(principal)
    return {**catalog, "runtime": "durable_project_scoped_live_adapters"}


@router.post("/ingestion/syncs/{sync_id}/enqueue", status_code=202)
def enqueue_sync(sync_id: str, body: EnqueueSyncRequest = EnqueueSyncRequest(), principal: Principal = Depends(require_permission("execute")), db: Session = Depends(get_db)):
    sync = connectivity._sync_or_404(db, sync_id, principal, "execute")
    return _enqueue(db, principal, sync.project_id, "ingestion.connector_sync", "connection_sync", sync.id, {"records": body.records}, body.priority, body.max_attempts, body.timeout_seconds, body.idempotency_key)


@router.post("/ingestion/streams/{stream_id}/replay/enqueue", status_code=202)
def enqueue_stream_replay(stream_id: str, body: EnqueueReplayRequest, principal: Principal = Depends(require_permission("execute")), db: Session = Depends(get_db)):
    stream = streaming._get_stream_or_404(stream_id, db, principal, "execute")
    payload = body.model_dump(exclude={"priority", "max_attempts", "timeout_seconds", "idempotency_key"})
    return _enqueue(db, principal, stream.project_id, "ingestion.stream_replay", "stream", stream.id, payload, body.priority, body.max_attempts, body.timeout_seconds, body.idempotency_key)


@router.post("/ingestion/workers/run-next")
def run_next(body: WorkerRequest = WorkerRequest(), principal: Principal = Depends(require_permission("execute")), db: Session = Depends(get_db)):
    from . import worker_control
    supported_job_types = worker_control.effective_worker_job_types(
        db, principal, body.worker_id, ["ingestion.connector_sync", "ingestion.stream_replay"],
    )
    claimed = platform_runtime.claim_job(platform_runtime.JobClaimRequest(
        worker_id=body.worker_id, supported_job_types=supported_job_types,
        lease_seconds=body.lease_seconds, job_id=body.job_id,
    ), principal, db).get("job")
    if not claimed:
        return {"job": None, "run": None}
    run = db.get(IngestionRun, (claimed.get("payload") or {}).get("ingestion_run_id"))
    if not run:
        platform_runtime.fail_job(claimed["id"], platform_runtime.JobFailRequest(lease_token=claimed["lease_token"], error="Ingestion run not found", retriable=False), principal, db)
        return {"job": platform_runtime.get_job(claimed["id"], principal, db), "run": None}
    if run.status in {"SUCCEEDED", "WARN"}:
        completed = platform_runtime.complete_job(claimed["id"], platform_runtime.JobCompleteRequest(lease_token=claimed["lease_token"], result=_run_dict(run)), principal, db)
        return {"job": completed, "run": _run_dict(run), "recovered_after_commit": True}
    run.status = "RUNNING"
    run.started_at = run.started_at or _now()
    run.error = None
    db.commit()
    try:
        platform_runtime.heartbeat_job(claimed["id"], platform_runtime.JobHeartbeatRequest(lease_token=claimed["lease_token"], progress=10, message="Validated project-scoped ingestion lease", lease_seconds=body.lease_seconds), principal, db)
        if body.inject_failure:
            raise RuntimeError("Injected ingestion worker failure")
        payload = dict(claimed.get("payload") or {})
        result = _execute_sync(db, run, payload) if run.run_type == "ingestion.connector_sync" else _execute_replay(db, run, payload)
        _finish_run(db, run, result)
        db.commit()
        completed = platform_runtime.complete_job(claimed["id"], platform_runtime.JobCompleteRequest(lease_token=claimed["lease_token"], result=_run_dict(run)), principal, db)
        return {"job": completed, "run": _run_dict(run)}
    except Exception as exc:
        db.rollback()
        run = db.get(IngestionRun, run.id)
        run.error = str(exc.detail if isinstance(exc, HTTPException) else exc)
        job = db.get(platform_runtime.PlatformJob, claimed["id"])
        max_attempts = int((job.payload or {}).get("__execution", {}).get("max_attempts", 3)) if job else 1
        retriable = not isinstance(exc, HTTPException) or exc.status_code >= 500
        run.status = "RETRYING" if retriable and job and job.attempt < max_attempts else "FAILED"
        if run.status == "FAILED":
            run.completed_at = _now()
            _record_dead_letter(db, run, {"job_payload": claimed.get("payload") or {}}, run.error)
        db.commit()
        failed = platform_runtime.fail_job(claimed["id"], platform_runtime.JobFailRequest(
            lease_token=claimed["lease_token"], error=run.error, retriable=retriable, retry_delay_seconds=0,
            details={"ingestion_run_id": run.id},
        ), principal, db)
        return {"job": failed, "run": _run_dict(run)}


@router.put("/ingestion/budgets")
def upsert_budget(body: BudgetUpsert, principal: Principal = Depends(require_permission("administer")), db: Session = Depends(get_db)):
    tenancy.assert_project_permission(db, principal, body.project_id, "administer")
    row = db.query(IngestionBudget).filter(IngestionBudget.project_id == body.project_id, IngestionBudget.metric == body.metric).first()
    now = _now()
    if not row:
        row = IngestionBudget(id=f"budget_{uuid.uuid4().hex}", project_id=body.project_id, metric=body.metric, created_at=now, updated_at=now, limit_value=body.limit_value, window_seconds=body.window_seconds, enforcement=body.enforcement)
        db.add(row)
    else:
        row.limit_value, row.window_seconds, row.enforcement, row.updated_at = body.limit_value, body.window_seconds, body.enforcement, now
    db.commit()
    return {name: getattr(row, name) for name in ("id", "project_id", "metric", "limit_value", "window_seconds", "enforcement", "created_at", "updated_at")}


@router.get("/ingestion/runs")
def list_runs(project_id: Optional[str] = None, status: Optional[str] = None, limit: int = Query(100, ge=1, le=500), principal: Principal = Depends(require_permission("view")), db: Session = Depends(get_db)):
    query = db.query(IngestionRun)
    if project_id:
        tenancy.assert_project_permission(db, principal, project_id, "view")
        query = query.filter(IngestionRun.project_id == project_id)
    else:
        accessible = tenancy.accessible_project_ids(db, principal)
        if accessible is not None:
            query = query.filter(IngestionRun.project_id.in_(accessible))
    if status:
        query = query.filter(IngestionRun.status == status.upper())
    return [_run_dict(row) for row in query.order_by(IngestionRun.created_at.desc()).limit(limit).all()]


@router.get("/ingestion/dead-letters")
def list_dead_letters(project_id: Optional[str] = None, status: str = "PENDING", principal: Principal = Depends(require_permission("view")), db: Session = Depends(get_db)):
    query = db.query(IngestionDeadLetter).filter(IngestionDeadLetter.status == status.upper())
    if project_id:
        tenancy.assert_project_permission(db, principal, project_id, "view")
        query = query.filter(IngestionDeadLetter.project_id == project_id)
    else:
        accessible = tenancy.accessible_project_ids(db, principal)
        if accessible is not None:
            query = query.filter(IngestionDeadLetter.project_id.in_(accessible))
    return [_dead_letter_dict(row) for row in query.order_by(IngestionDeadLetter.created_at.desc()).all()]


@router.post("/ingestion/dead-letters/{dead_letter_id}/replay", status_code=202)
def replay_dead_letter(dead_letter_id: str, principal: Principal = Depends(require_permission("execute")), db: Session = Depends(get_db)):
    row = db.get(IngestionDeadLetter, dead_letter_id)
    if not row:
        raise HTTPException(status_code=404, detail="Dead letter not found")
    tenancy.assert_project_permission(db, principal, row.project_id, "execute")
    source_run = db.get(IngestionRun, row.run_id)
    records = [row.payload] if "job_payload" not in row.payload else (row.payload["job_payload"].get("records") or [])
    result = _enqueue(db, principal, row.project_id, source_run.run_type, row.resource_type, row.resource_id, {"records": records}, 75, 3, 900, f"dlq:{row.id}:{row.attempts + 1}")
    row.status = "REPLAYED"
    row.replay_job_id = result["job"]["id"]
    row.attempts += 1
    row.updated_at = _now()
    db.commit()
    return {"dead_letter": _dead_letter_dict(row), **result}


@router.get("/ingestion/summary")
def summary(project_id: str = "default", principal: Principal = Depends(require_permission("view")), db: Session = Depends(get_db)):
    tenancy.assert_project_permission(db, principal, project_id, "view")
    runs = db.query(IngestionRun).filter(IngestionRun.project_id == project_id).all()
    counts: Dict[str, int] = {}
    for run in runs:
        counts[run.status] = counts.get(run.status, 0) + 1
    budgets = db.query(IngestionBudget).filter(IngestionBudget.project_id == project_id).all()
    pending_dlq = db.query(IngestionDeadLetter).filter(IngestionDeadLetter.project_id == project_id, IngestionDeadLetter.status == "PENDING").count()
    return {
        "project_id": project_id, "runs": len(runs), "status_counts": counts,
        "records_processed": sum(row.records_out for row in runs),
        "bytes_processed": sum(row.bytes_processed for row in runs),
        "estimated_cost_usd": round(sum(row.estimated_cost_usd for row in runs), 8),
        "pending_dead_letters": pending_dlq,
        "budgets": [{"metric": row.metric, "limit": row.limit_value, "window_seconds": row.window_seconds, "enforcement": row.enforcement} for row in budgets],
        "last_updated": _now(),
    }

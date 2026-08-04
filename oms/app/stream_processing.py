"""Durable event-time stream processing over project-scoped StreamRecord rows."""

from __future__ import annotations

import hashlib
import json
import math
import time
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import JSON, Boolean, Float, Integer, String, UniqueConstraint, exists, func, inspect, or_
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, Session, mapped_column

from . import models, models_action, ops_control, platform_runtime, streaming, tenancy
from .database import Base, get_db
from .production_auth import Principal, require_permission


router = APIRouter(prefix="/api/v1", tags=["stream-processing"])
STREAM_JSON = JSON().with_variant(JSONB(), "postgresql")


def _now() -> int:
    return int(time.time())


def _id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:20]}"


class StreamProcessor(Base):
    __tablename__ = "stream_processors"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    project_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    stream_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    display_name: Mapped[str] = mapped_column(String, nullable=False)
    timestamp_field: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    partition_key_field: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    allowed_lateness_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    late_policy: Mapped[str] = mapped_column(String, nullable=False, default="quarantine")
    window_size_seconds: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    value_field: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    aggregation: Mapped[str] = mapped_column(String, nullable=False, default="count")
    target_asset_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    join_stream_id: Mapped[Optional[str]] = mapped_column(String, nullable=True, index=True)
    join_left_key: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    join_right_key: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    join_time_tolerance_seconds: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    max_batch_records: Mapped[int] = mapped_column(Integer, nullable=False, default=1000)
    max_backlog_records: Mapped[int] = mapped_column(Integer, nullable=False, default=10000)
    backpressure_mode: Mapped[str] = mapped_column(String, nullable=False, default="reject")
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_by: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[int] = mapped_column(Integer, nullable=False)
    updated_at: Mapped[int] = mapped_column(Integer, nullable=False)


class StreamPartitionState(Base):
    __tablename__ = "stream_partition_states"
    __table_args__ = (UniqueConstraint("processor_id", "partition_key", name="uq_stream_processor_partition"),)

    id: Mapped[str] = mapped_column(String, primary_key=True)
    processor_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    project_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    partition_key: Mapped[str] = mapped_column(String, nullable=False)
    max_event_time: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    watermark: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    processed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    late_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    quarantined_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    updated_at: Mapped[int] = mapped_column(Integer, nullable=False)


class StreamWindowState(Base):
    __tablename__ = "stream_window_states"
    __table_args__ = (
        UniqueConstraint("processor_id", "partition_key", "window_start", name="uq_stream_processor_window"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True)
    processor_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    project_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    partition_key: Mapped[str] = mapped_column(String, nullable=False)
    window_start: Mapped[float] = mapped_column(Float, nullable=False)
    window_end: Mapped[float] = mapped_column(Float, nullable=False)
    count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    numeric_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    value_sum: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    value_min: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    value_max: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(String, nullable=False, default="OPEN", index=True)
    emitted_at: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    updated_at: Mapped[int] = mapped_column(Integer, nullable=False)


class StreamProcessingReceipt(Base):
    __tablename__ = "stream_processing_receipts"
    __table_args__ = (UniqueConstraint("processor_id", "record_id", name="uq_stream_processor_record"),)

    id: Mapped[str] = mapped_column(String, primary_key=True)
    processor_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    project_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    record_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    partition_key: Mapped[str] = mapped_column(String, nullable=False)
    event_time: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(String, nullable=False, index=True)
    reason: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    run_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    created_at: Mapped[int] = mapped_column(Integer, nullable=False)


class StreamJoinInput(Base):
    __tablename__ = "stream_join_inputs"
    __table_args__ = (
        UniqueConstraint("processor_id", "record_id", name="uq_stream_join_input_record"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True)
    processor_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    project_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    record_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    stream_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    side: Mapped[str] = mapped_column(String, nullable=False)
    join_key: Mapped[str] = mapped_column(String, nullable=False, index=True)
    event_time: Mapped[float] = mapped_column(Float, nullable=False, index=True)
    created_at: Mapped[int] = mapped_column(Integer, nullable=False)


class StreamJoinReceipt(Base):
    __tablename__ = "stream_join_receipts"
    __table_args__ = (
        UniqueConstraint(
            "processor_id", "left_record_id", "right_record_id",
            name="uq_stream_join_pair",
        ),
        UniqueConstraint("output_record_id", name="uq_stream_join_output"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True)
    processor_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    project_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    left_record_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    right_record_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    output_record_id: Mapped[str] = mapped_column(String, nullable=False)
    join_key: Mapped[str] = mapped_column(String, nullable=False, index=True)
    left_event_time: Mapped[float] = mapped_column(Float, nullable=False)
    right_event_time: Mapped[float] = mapped_column(Float, nullable=False)
    run_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    created_at: Mapped[int] = mapped_column(Integer, nullable=False)


class StreamQuarantineRecord(Base):
    __tablename__ = "stream_quarantine_records"
    __table_args__ = (UniqueConstraint("processor_id", "record_id", name="uq_stream_quarantine_record"),)

    id: Mapped[str] = mapped_column(String, primary_key=True)
    processor_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    project_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    record_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    partition_key: Mapped[str] = mapped_column(String, nullable=False)
    event_time: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    watermark: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    reason: Mapped[str] = mapped_column(String, nullable=False)
    payload: Mapped[dict] = mapped_column(STREAM_JSON, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String, nullable=False, default="PENDING", index=True)
    created_at: Mapped[int] = mapped_column(Integer, nullable=False)
    resolved_at: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)


class StreamProcessingRun(Base):
    __tablename__ = "stream_processing_runs"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    processor_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    project_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    job_id: Mapped[Optional[str]] = mapped_column(String, nullable=True, index=True)
    status: Mapped[str] = mapped_column(String, nullable=False, index=True)
    backlog_before: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    backlog_after: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    records_processed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    records_late: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    records_quarantined: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    windows_emitted: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    joins_emitted: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    metrics: Mapped[dict] = mapped_column(STREAM_JSON, nullable=False, default=dict)
    error: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    created_at: Mapped[int] = mapped_column(Integer, nullable=False)
    completed_at: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)


class ProcessorCreate(BaseModel):
    id: Optional[str] = None
    project_id: str = "default"
    stream_id: str
    display_name: str
    timestamp_field: Optional[str] = None
    partition_key_field: Optional[str] = None
    allowed_lateness_seconds: int = Field(default=0, ge=0, le=31_536_000)
    late_policy: str = Field(default="quarantine", pattern="^(quarantine|drop|accept)$")
    window_size_seconds: Optional[int] = Field(default=None, ge=1, le=31_536_000)
    value_field: Optional[str] = None
    aggregation: str = Field(default="count", pattern="^(count|sum|avg|min|max)$")
    target_asset_id: Optional[str] = None
    join_stream_id: Optional[str] = None
    join_left_key: Optional[str] = Field(default=None, min_length=1, max_length=255)
    join_right_key: Optional[str] = Field(default=None, min_length=1, max_length=255)
    join_time_tolerance_seconds: Optional[int] = Field(default=None, ge=0, le=31_536_000)
    max_batch_records: int = Field(default=1000, ge=1, le=10000)
    max_backlog_records: int = Field(default=10000, ge=1, le=10_000_000)
    backpressure_mode: str = Field(default="reject", pattern="^(reject|warn)$")


class ProcessorPatch(BaseModel):
    display_name: Optional[str] = None
    allowed_lateness_seconds: Optional[int] = Field(default=None, ge=0, le=31_536_000)
    late_policy: Optional[str] = Field(default=None, pattern="^(quarantine|drop|accept)$")
    max_batch_records: Optional[int] = Field(default=None, ge=1, le=10000)
    max_backlog_records: Optional[int] = Field(default=None, ge=1, le=10_000_000)
    backpressure_mode: Optional[str] = Field(default=None, pattern="^(reject|warn)$")
    enabled: Optional[bool] = None


class ProcessRequest(BaseModel):
    max_records: Optional[int] = Field(default=None, ge=1, le=10000)
    inject_failure_after_records: Optional[int] = Field(default=None, ge=1, le=10000)


class EnqueueRequest(BaseModel):
    max_records: Optional[int] = Field(default=None, ge=1, le=10000)
    priority: int = Field(default=50, ge=0, le=100)
    max_attempts: int = Field(default=3, ge=1, le=20)
    timeout_seconds: int = Field(default=900, ge=1, le=86400)
    idempotency_key: Optional[str] = Field(default=None, min_length=1, max_length=200)


class WorkerRequest(BaseModel):
    worker_id: str = Field(default="stream-processor", min_length=1, max_length=200)
    lease_seconds: int = Field(default=120, ge=10, le=900)
    job_id: Optional[str] = None
    inject_failure_after_records: Optional[int] = Field(default=None, ge=1, le=10000)


def _processor_dict(row: StreamProcessor) -> Dict[str, Any]:
    return {name: getattr(row, name) for name in (
        "id", "project_id", "stream_id", "display_name", "timestamp_field", "partition_key_field",
        "allowed_lateness_seconds", "late_policy", "window_size_seconds", "value_field", "aggregation",
        "target_asset_id", "join_stream_id", "join_left_key", "join_right_key",
        "join_time_tolerance_seconds", "max_batch_records", "max_backlog_records", "backpressure_mode", "enabled",
        "created_by", "created_at", "updated_at",
    )}


def _run_dict(row: StreamProcessingRun) -> Dict[str, Any]:
    return {name: getattr(row, name) for name in (
        "id", "processor_id", "project_id", "job_id", "status", "backlog_before", "backlog_after",
        "records_processed", "records_late", "records_quarantined", "windows_emitted", "joins_emitted", "metrics",
        "error", "created_at", "completed_at",
    )}


def _event_time(record: streaming.StreamRecord, field: Optional[str]) -> Optional[float]:
    value = (record.payload or {}).get(field) if field else record.ts
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(value)
    except (TypeError, ValueError):
        try:
            return datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()
        except ValueError:
            return None


def _partition(payload: Dict[str, Any], field: Optional[str]) -> str:
    value = payload.get(field) if field else "_default"
    if value is None:
        value = "_null"
    if isinstance(value, (dict, list)):
        return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return str(value)


def _processor_stream_ids(processor: StreamProcessor) -> List[str]:
    return [processor.stream_id, *([processor.join_stream_id] if processor.join_stream_id else [])]


def _backlog(db: Session, processor: StreamProcessor) -> int:
    handled = exists().where(
        StreamProcessingReceipt.processor_id == processor.id,
        StreamProcessingReceipt.record_id == streaming.StreamRecord.id,
    )
    return db.query(func.count(streaming.StreamRecord.id)).filter(
        streaming.StreamRecord.stream_id.in_(_processor_stream_ids(processor)), ~handled,
    ).scalar() or 0


def enforce_publish_capacity(db: Session, stream_id: str, incoming_count: int) -> List[Dict[str, Any]]:
    warnings = []
    if incoming_count <= 0:
        return warnings
    if not inspect(db.get_bind()).has_table(StreamProcessor.__tablename__):
        return warnings
    for processor in db.query(StreamProcessor).filter(
        or_(StreamProcessor.stream_id == stream_id, StreamProcessor.join_stream_id == stream_id),
        StreamProcessor.enabled.is_(True)
    ).all():
        backlog = _backlog(db, processor)
        projected = backlog + incoming_count
        if projected <= processor.max_backlog_records:
            continue
        detail = {
            "processor_id": processor.id, "backlog": backlog, "incoming": incoming_count,
            "projected_backlog": projected, "max_backlog_records": processor.max_backlog_records,
        }
        if processor.backpressure_mode == "reject":
            raise HTTPException(
                status_code=429, detail={"message": "Stream processor backlog limit exceeded", **detail},
                headers={"Retry-After": "1"},
            )
        warnings.append(detail)
        ops_control.record_ops_event(
            db, source="streaming", event_type="stream.backpressure.warning", severity="warning",
            title=f"Stream processor {processor.display_name} backlog exceeded",
            subject_type="stream_processor", subject_id=processor.id,
            payload={"project_id": processor.project_id, **detail}, project_id=processor.project_id,
        )
    return warnings


def _state(db: Session, processor: StreamProcessor, partition_key: str) -> StreamPartitionState:
    row = db.query(StreamPartitionState).filter(
        StreamPartitionState.processor_id == processor.id,
        StreamPartitionState.partition_key == partition_key,
    ).first()
    if row:
        return row
    row = StreamPartitionState(
        id=_id("partition"), processor_id=processor.id, project_id=processor.project_id,
        partition_key=partition_key, max_event_time=None, watermark=None,
        processed_count=0, late_count=0, quarantined_count=0, updated_at=_now(),
    )
    db.add(row)
    db.flush()
    return row


def _window(db: Session, processor: StreamProcessor, partition_key: str, event_time: float) -> StreamWindowState:
    size = int(processor.window_size_seconds or 1)
    start = math.floor(event_time / size) * size
    row = db.query(StreamWindowState).filter(
        StreamWindowState.processor_id == processor.id,
        StreamWindowState.partition_key == partition_key,
        StreamWindowState.window_start == float(start),
    ).first()
    if row:
        return row
    row = StreamWindowState(
        id=_id("window"), processor_id=processor.id, project_id=processor.project_id,
        partition_key=partition_key, window_start=float(start), window_end=float(start + size),
        count=0, numeric_count=0, value_sum=0.0, value_min=None, value_max=None,
        status="OPEN", emitted_at=None, updated_at=_now(),
    )
    db.add(row)
    db.flush()
    return row


def _window_value(processor: StreamProcessor, row: StreamWindowState) -> Any:
    if processor.aggregation == "count":
        return row.count
    if processor.aggregation == "sum":
        return row.value_sum
    if processor.aggregation == "avg":
        return row.value_sum / row.numeric_count if row.numeric_count else None
    if processor.aggregation == "min":
        return row.value_min
    return row.value_max


def _join_key(payload: Dict[str, Any], field: str) -> Optional[str]:
    value = payload.get(field)
    if value is None or isinstance(value, (dict, list)):
        return None
    normalized = str(value).strip()
    return normalized or None


def _join_input(
    db: Session,
    processor: StreamProcessor,
    record: streaming.StreamRecord,
    *,
    side: str,
    join_key: str,
    event_time: float,
) -> StreamJoinInput:
    row = db.query(StreamJoinInput).filter(
        StreamJoinInput.processor_id == processor.id,
        StreamJoinInput.record_id == record.id,
    ).first()
    if row:
        return row
    row = StreamJoinInput(
        id=_id("joininput"), processor_id=processor.id, project_id=processor.project_id,
        record_id=record.id, stream_id=record.stream_id, side=side,
        join_key=join_key, event_time=event_time, created_at=_now(),
    )
    db.add(row)
    db.flush()
    return row


def _join_matches(
    db: Session,
    processor: StreamProcessor,
    row: StreamJoinInput,
) -> List[StreamJoinInput]:
    tolerance = float(processor.join_time_tolerance_seconds or 0)
    return db.query(StreamJoinInput).filter(
        StreamJoinInput.processor_id == processor.id,
        StreamJoinInput.side != row.side,
        StreamJoinInput.join_key == row.join_key,
        StreamJoinInput.event_time >= row.event_time - tolerance,
        StreamJoinInput.event_time <= row.event_time + tolerance,
    ).order_by(StreamJoinInput.event_time, StreamJoinInput.record_id).all()


def _emit_join_pairs(
    db: Session,
    processor: StreamProcessor,
    current: StreamJoinInput,
    run: StreamProcessingRun,
    outputs: List[Dict[str, Any]],
) -> int:
    emitted = 0
    current_record = db.get(streaming.StreamRecord, current.record_id)
    if current_record is None:
        raise HTTPException(status_code=409, detail="Join input record is missing")
    for opposite in _join_matches(db, processor, current):
        left = current if current.side == "left" else opposite
        right = opposite if current.side == "left" else current
        exists_pair = db.query(StreamJoinReceipt.id).filter(
            StreamJoinReceipt.processor_id == processor.id,
            StreamJoinReceipt.left_record_id == left.record_id,
            StreamJoinReceipt.right_record_id == right.record_id,
        ).first()
        if exists_pair:
            continue
        opposite_record = db.get(streaming.StreamRecord, opposite.record_id)
        if opposite_record is None:
            raise HTTPException(status_code=409, detail="Opposite join input record is missing")
        left_record = current_record if current.side == "left" else opposite_record
        right_record = opposite_record if current.side == "left" else current_record
        digest = hashlib.sha256(
            f"{processor.id}\x1f{left.record_id}\x1f{right.record_id}".encode("utf-8")
        ).hexdigest()
        output_id = f"stream_join_{digest}"
        output = {
            "_stream_join_id": output_id,
            "processor_id": processor.id,
            "join_key": current.join_key,
            "left_record_id": left.record_id,
            "right_record_id": right.record_id,
            "left_event_time": left.event_time,
            "right_event_time": right.event_time,
            "event_time_delta_seconds": abs(left.event_time - right.event_time),
            "left": dict(left_record.payload or {}),
            "right": dict(right_record.payload or {}),
        }
        outputs.append(output)
        db.add(StreamJoinReceipt(
            id=f"joinreceipt_{digest}", processor_id=processor.id,
            project_id=processor.project_id, left_record_id=left.record_id,
            right_record_id=right.record_id, output_record_id=output_id,
            join_key=current.join_key, left_event_time=left.event_time,
            right_event_time=right.event_time, run_id=run.id, created_at=_now(),
        ))
        emitted += 1
    return emitted


def _materialize_join_outputs(
    db: Session,
    processor: StreamProcessor,
    outputs: List[Dict[str, Any]],
) -> None:
    if not outputs:
        return
    asset = db.get(models.DataAsset, processor.target_asset_id)
    if not asset or asset.project_id != processor.project_id:
        raise HTTPException(status_code=409, detail="Join target dataset is missing or belongs to another project")
    records = list(asset.records or [])
    indexes = {
        str(item.get("_stream_join_id")): index
        for index, item in enumerate(records)
        if isinstance(item, dict) and item.get("_stream_join_id")
    }
    for output in outputs:
        output_id = output["_stream_join_id"]
        if output_id in indexes:
            records[indexes[output_id]] = output
        else:
            indexes[output_id] = len(records)
            records.append(output)
    asset.records = records
    asset.asset_schema = {
        **dict(asset.asset_schema or {}),
        "project_id": processor.project_id,
        "source_stream_id": processor.stream_id,
        "join_stream_id": processor.join_stream_id,
        "stream_processor_id": processor.id,
        "join_left_key": processor.join_left_key,
        "join_right_key": processor.join_right_key,
        "join_time_tolerance_seconds": processor.join_time_tolerance_seconds,
        "last_stream_join_count": len(outputs),
    }
    asset.updated_at = _now()


def _emit_closed_windows(db: Session, processor: StreamProcessor, states: Dict[str, StreamPartitionState]) -> int:
    emitted = 0
    asset = db.get(models.DataAsset, processor.target_asset_id) if processor.target_asset_id else None
    if processor.target_asset_id and (not asset or asset.project_id != processor.project_id):
        raise HTTPException(status_code=409, detail="Processor target dataset is missing or belongs to another project")
    records = list(asset.records or []) if asset else []
    record_index = {str(item.get("_stream_window_id")): index for index, item in enumerate(records) if isinstance(item, dict)}
    for partition_key, state in states.items():
        if state.watermark is None:
            continue
        windows = db.query(StreamWindowState).filter(
            StreamWindowState.processor_id == processor.id,
            StreamWindowState.partition_key == partition_key,
            StreamWindowState.status == "OPEN",
            StreamWindowState.window_end <= state.watermark,
        ).order_by(StreamWindowState.window_start).all()
        for window in windows:
            stable_id = hashlib.sha256(
                f"{processor.id}\x1f{partition_key}\x1f{window.window_start}".encode("utf-8")
            ).hexdigest()
            output = {
                "_stream_window_id": stable_id, "processor_id": processor.id,
                "partition_key": partition_key, "window_start": window.window_start,
                "window_end": window.window_end, "aggregation": processor.aggregation,
                "value": _window_value(processor, window), "count": window.count,
                "watermark": state.watermark,
            }
            if asset:
                if stable_id in record_index:
                    records[record_index[stable_id]] = output
                else:
                    record_index[stable_id] = len(records)
                    records.append(output)
            window.status = "EMITTED"
            window.emitted_at = _now()
            window.updated_at = _now()
            emitted += 1
    if asset and emitted:
        asset.records = records
        asset.asset_schema = {
            **dict(asset.asset_schema or {}), "project_id": processor.project_id,
            "source_stream_id": processor.stream_id, "stream_processor_id": processor.id,
            "last_stream_window_count": emitted,
        }
        asset.updated_at = _now()
    return emitted


def execute_batch(
    db: Session, processor_id: str, *, max_records: Optional[int] = None,
    job_id: Optional[str] = None, inject_failure_after_records: Optional[int] = None,
) -> StreamProcessingRun:
    query = db.query(StreamProcessor).filter(StreamProcessor.id == processor_id)
    if db.get_bind().dialect.name == "postgresql":
        query = query.with_for_update()
    processor = query.one_or_none()
    if not processor:
        raise HTTPException(status_code=404, detail="Stream processor not found")
    if not processor.enabled:
        raise HTTPException(status_code=409, detail="Stream processor is disabled")
    limit = min(max_records or processor.max_batch_records, processor.max_batch_records, 10000)
    backlog_before = _backlog(db, processor)
    run = StreamProcessingRun(
        id=_id("streamrun"), processor_id=processor.id, project_id=processor.project_id,
        job_id=job_id, status="RUNNING", backlog_before=backlog_before, backlog_after=backlog_before,
        records_processed=0, records_late=0, records_quarantined=0, windows_emitted=0,
        joins_emitted=0,
        metrics={}, error=None, created_at=_now(), completed_at=None,
    )
    db.add(run)
    db.flush()
    handled = exists().where(
        StreamProcessingReceipt.processor_id == processor.id,
        StreamProcessingReceipt.record_id == streaming.StreamRecord.id,
    )
    records = db.query(streaming.StreamRecord).filter(
        streaming.StreamRecord.stream_id.in_(_processor_stream_ids(processor)), ~handled,
    ).order_by(
        streaming.StreamRecord.created_at, streaming.StreamRecord.stream_id,
        streaming.StreamRecord.sequence, streaming.StreamRecord.id,
    ).limit(limit).all()
    states: Dict[str, StreamPartitionState] = {}
    join_outputs: List[Dict[str, Any]] = []
    for index, record in enumerate(records, start=1):
        payload = dict(record.payload or {})
        side = "right" if processor.join_stream_id and record.stream_id == processor.join_stream_id else "left"
        partition_key = _partition(payload, processor.partition_key_field)
        state_key = f"{side}:{partition_key}" if processor.join_stream_id else partition_key
        state = states.get(state_key) or _state(db, processor, state_key)
        states[state_key] = state
        event_time = _event_time(record, processor.timestamp_field)
        prior_watermark = state.watermark
        status, reason = "PROCESSED", None
        join_key = None
        if event_time is None:
            status, reason = "QUARANTINED", "invalid_event_time"
        elif processor.join_stream_id:
            key_field = processor.join_right_key if side == "right" else processor.join_left_key
            join_key = _join_key(payload, str(key_field))
            if join_key is None:
                status, reason = "QUARANTINED", "invalid_join_key"
        if status == "PROCESSED" and prior_watermark is not None and event_time < prior_watermark:
            run.records_late += 1
            state.late_count += 1
            if processor.late_policy == "quarantine":
                status, reason = "QUARANTINED", "event_time_before_watermark"
            elif processor.late_policy == "drop":
                status, reason = "DROPPED", "event_time_before_watermark"
        if status == "PROCESSED" and event_time is not None:
            state.max_event_time = max(state.max_event_time, event_time) if state.max_event_time is not None else event_time
            state.watermark = state.max_event_time - processor.allowed_lateness_seconds
            state.processed_count += 1
            if processor.join_stream_id and join_key is not None:
                join_input = _join_input(
                    db, processor, record, side=side, join_key=join_key, event_time=event_time,
                )
                run.joins_emitted += _emit_join_pairs(
                    db, processor, join_input, run, join_outputs,
                )
            elif processor.window_size_seconds:
                window = _window(db, processor, partition_key, event_time)
                if window.status == "EMITTED":
                    status, reason = "QUARANTINED", "window_already_emitted"
                    state.processed_count -= 1
                else:
                    window.count += 1
                    value = payload.get(processor.value_field) if processor.value_field else None
                    if isinstance(value, (int, float)) and not isinstance(value, bool):
                        numeric = float(value)
                        window.numeric_count += 1
                        window.value_sum += numeric
                        window.value_min = numeric if window.value_min is None else min(window.value_min, numeric)
                        window.value_max = numeric if window.value_max is None else max(window.value_max, numeric)
                    window.updated_at = _now()
        if status == "QUARANTINED":
            run.records_quarantined += 1
            state.quarantined_count += 1
            db.add(StreamQuarantineRecord(
                id=_id("quarantine"), processor_id=processor.id, project_id=processor.project_id,
                record_id=record.id, partition_key=partition_key, event_time=event_time,
                watermark=prior_watermark, reason=reason or "quarantined", payload=payload,
                status="PENDING", created_at=_now(), resolved_at=None,
            ))
        state.updated_at = _now()
        db.add(StreamProcessingReceipt(
            id=_id("streamreceipt"), processor_id=processor.id, project_id=processor.project_id,
            record_id=record.id, partition_key=partition_key, event_time=event_time,
            status=status, reason=reason, run_id=run.id, created_at=_now(),
        ))
        run.records_processed += 1
        if inject_failure_after_records and index >= inject_failure_after_records:
            raise RuntimeError("Injected stream processor failure")
    run.windows_emitted = _emit_closed_windows(db, processor, states)
    _materialize_join_outputs(db, processor, join_outputs)
    run.backlog_after = max(0, backlog_before - run.records_processed)
    run.status = "WARN" if run.records_quarantined else "SUCCEEDED"
    run.completed_at = _now()
    run.metrics = {
        "batch_limit": limit, "partitions_touched": len(states),
        "input_streams": _processor_stream_ids(processor),
        "joins_emitted": run.joins_emitted,
        "backpressure_active": run.backlog_after >= processor.max_backlog_records,
        "duration_ms": max(0, run.completed_at - run.created_at) * 1000,
    }
    db.add(models_action.AuditLog(
        id=uuid.uuid4().hex, actor="stream-processor", event_type="stream.processor.completed",
        subject_type="stream_processor", subject_id=processor.id,
        payload={"project_id": processor.project_id, **_run_dict(run)},
    ))
    ops_control.record_ops_event(
        db, source="streaming", event_type="stream.processor.completed",
        severity="warning" if run.records_quarantined else "info",
        title=f"Stream processor {processor.display_name} handled {run.records_processed} record(s)",
        subject_type="stream_processor", subject_id=processor.id,
        payload={"project_id": processor.project_id, **_run_dict(run)}, project_id=processor.project_id,
    )
    return run


def _processor(db: Session, processor_id: str, principal: Principal, permission: str) -> StreamProcessor:
    row = db.get(StreamProcessor, processor_id)
    if not row:
        raise HTTPException(status_code=404, detail="Stream processor not found")
    tenancy.assert_project_permission(db, principal, row.project_id, permission)
    return row


@router.post("/streams/processors", status_code=201)
def create_processor(body: ProcessorCreate, principal: Principal = Depends(require_permission("edit")), db: Session = Depends(get_db)):
    tenancy.assert_project_permission(db, principal, body.project_id, "edit")
    stream = streaming._get_stream_or_404(body.stream_id, db, principal, "view")
    if stream.project_id != body.project_id:
        raise HTTPException(status_code=409, detail="Stream belongs to another project")
    join_fields = (
        body.join_stream_id, body.join_left_key, body.join_right_key,
        body.join_time_tolerance_seconds,
    )
    if any(value is not None for value in join_fields) and not all(value is not None for value in join_fields):
        raise HTTPException(
            status_code=422,
            detail="join_stream_id, join_left_key, join_right_key, and join_time_tolerance_seconds are required together",
        )
    if body.join_stream_id:
        if body.join_stream_id == body.stream_id:
            raise HTTPException(status_code=422, detail="Join streams must be distinct")
        right_stream = streaming._get_stream_or_404(body.join_stream_id, db, principal, "view")
        if right_stream.project_id != body.project_id:
            raise HTTPException(status_code=409, detail="Join stream belongs to another project")
        if not body.target_asset_id:
            raise HTTPException(status_code=422, detail="target_asset_id is required for stream joins")
        if body.window_size_seconds:
            raise HTTPException(status_code=422, detail="Window aggregation and stream join cannot be combined in one processor")
    if body.target_asset_id:
        asset = db.get(models.DataAsset, body.target_asset_id)
        if not asset or asset.project_id != body.project_id:
            raise HTTPException(status_code=409, detail="Target dataset is missing or belongs to another project")
    if body.aggregation != "count" and not body.value_field:
        raise HTTPException(status_code=422, detail="value_field is required for numeric aggregation")
    now = _now()
    row = StreamProcessor(
        id=body.id or _id("processor"), created_by=principal.id, created_at=now, updated_at=now,
        enabled=True, **body.model_dump(exclude={"id"}),
    )
    db.add(row)
    db.add(models_action.AuditLog(
        id=uuid.uuid4().hex, actor=principal.id, event_type="stream.processor.created",
        subject_type="stream_processor", subject_id=row.id,
        payload={"project_id": row.project_id, "stream_id": row.stream_id},
    ))
    db.commit()
    return _processor_dict(row)


@router.get("/streams/processors")
def list_processors(project_id: str = "default", principal: Principal = Depends(require_permission("view")), db: Session = Depends(get_db)):
    tenancy.assert_project_permission(db, principal, project_id, "view")
    return [_processor_dict(row) for row in db.query(StreamProcessor).filter(
        StreamProcessor.project_id == project_id
    ).order_by(StreamProcessor.created_at.desc()).all()]


@router.get("/streams/processors/{processor_id}")
def get_processor(processor_id: str, principal: Principal = Depends(require_permission("view")), db: Session = Depends(get_db)):
    row = _processor(db, processor_id, principal, "view")
    result = _processor_dict(row)
    result["backlog"] = _backlog(db, row)
    result["partitions"] = [{name: getattr(state, name) for name in (
        "partition_key", "max_event_time", "watermark", "processed_count", "late_count",
        "quarantined_count", "updated_at",
    )} for state in db.query(StreamPartitionState).filter(StreamPartitionState.processor_id == row.id).all()]
    return result


@router.patch("/streams/processors/{processor_id}")
def patch_processor(processor_id: str, body: ProcessorPatch, principal: Principal = Depends(require_permission("edit")), db: Session = Depends(get_db)):
    row = _processor(db, processor_id, principal, "edit")
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(row, field, value)
    row.updated_at = _now()
    db.commit()
    return _processor_dict(row)


@router.post("/streams/processors/{processor_id}/process")
def process_processor(processor_id: str, body: ProcessRequest = ProcessRequest(), principal: Principal = Depends(require_permission("execute")), db: Session = Depends(get_db)):
    _processor(db, processor_id, principal, "execute")
    try:
        run = execute_batch(
            db, processor_id, max_records=body.max_records,
            inject_failure_after_records=body.inject_failure_after_records,
        )
        db.commit()
        return _run_dict(run)
    except Exception:
        db.rollback()
        raise


@router.post("/streams/processors/{processor_id}/enqueue", status_code=202)
def enqueue_processor(processor_id: str, body: EnqueueRequest = EnqueueRequest(), principal: Principal = Depends(require_permission("execute")), db: Session = Depends(get_db)):
    row = _processor(db, processor_id, principal, "execute")
    return platform_runtime.create_job(platform_runtime.JobCreate(
        project_id=row.project_id, job_type="stream.process", subject_type="stream_processor",
        subject_id=row.id, payload={"processor_id": row.id, "max_records": body.max_records},
        priority=body.priority, max_attempts=body.max_attempts, timeout_seconds=body.timeout_seconds,
        idempotency_key=body.idempotency_key,
        estimated_records=float(body.max_records or row.max_batch_records),
    ), principal, db)


@router.post("/streams/processors/workers/run-next")
def run_next_processor(body: WorkerRequest = WorkerRequest(), principal: Principal = Depends(require_permission("execute")), db: Session = Depends(get_db)):
    from . import worker_control
    supported = worker_control.effective_worker_job_types(db, principal, body.worker_id, ["stream.process"])
    claimed = platform_runtime.claim_job(platform_runtime.JobClaimRequest(
        worker_id=body.worker_id, supported_job_types=supported,
        lease_seconds=body.lease_seconds, job_id=body.job_id,
    ), principal, db).get("job")
    if not claimed:
        return {"job": None, "run": None}
    payload = dict(claimed.get("payload") or {})
    try:
        run = execute_batch(
            db, payload["processor_id"], max_records=payload.get("max_records"),
            job_id=claimed["id"], inject_failure_after_records=body.inject_failure_after_records,
        )
        db.commit()
        completed = platform_runtime.complete_job(
            claimed["id"], platform_runtime.JobCompleteRequest(
                lease_token=claimed["lease_token"], result=_run_dict(run),
            ), principal, db,
        )
        return {"job": completed, "run": _run_dict(run)}
    except Exception as exc:
        db.rollback()
        failed = platform_runtime.fail_job(
            claimed["id"], platform_runtime.JobFailRequest(
                lease_token=claimed["lease_token"], error=str(exc), retriable=True,
                retry_delay_seconds=0, details={"processor_id": payload.get("processor_id")},
            ), principal, db,
        )
        return {"job": failed, "run": None}


@router.get("/streams/processors/{processor_id}/runs")
def list_processor_runs(processor_id: str, limit: int = Query(100, ge=1, le=500), principal: Principal = Depends(require_permission("view")), db: Session = Depends(get_db)):
    _processor(db, processor_id, principal, "view")
    return [_run_dict(row) for row in db.query(StreamProcessingRun).filter(
        StreamProcessingRun.processor_id == processor_id
    ).order_by(StreamProcessingRun.created_at.desc()).limit(limit).all()]


@router.get("/streams/processors/{processor_id}/quarantine")
def list_quarantine(processor_id: str, status: Optional[str] = None, limit: int = Query(100, ge=1, le=500), principal: Principal = Depends(require_permission("view")), db: Session = Depends(get_db)):
    _processor(db, processor_id, principal, "view")
    query = db.query(StreamQuarantineRecord).filter(StreamQuarantineRecord.processor_id == processor_id)
    if status:
        query = query.filter(StreamQuarantineRecord.status == status.upper())
    rows = query.order_by(StreamQuarantineRecord.created_at.desc()).limit(limit).all()
    return [{name: getattr(row, name) for name in (
        "id", "processor_id", "project_id", "record_id", "partition_key", "event_time",
        "watermark", "reason", "payload", "status", "created_at", "resolved_at",
    )} for row in rows]


@router.get("/streams/processing/summary")
def processing_summary(project_id: str = "default", principal: Principal = Depends(require_permission("view")), db: Session = Depends(get_db)):
    tenancy.assert_project_permission(db, principal, project_id, "view")
    processors = db.query(StreamProcessor).filter(StreamProcessor.project_id == project_id).all()
    backlog = sum(_backlog(db, row) for row in processors)
    quarantined = db.query(StreamQuarantineRecord).filter(
        StreamQuarantineRecord.project_id == project_id,
        StreamQuarantineRecord.status == "PENDING",
    ).count()
    return {
        "project_id": project_id, "processors": len(processors),
        "enabled_processors": sum(1 for row in processors if row.enabled),
        "backlog": backlog, "quarantined": quarantined,
        "backpressure_active": any(_backlog(db, row) >= row.max_backlog_records for row in processors if row.enabled),
    }

"""Transactional event outbox and durable internal event log.

Audit and operational events are converted to outbox rows by a SQLAlchemy session
listener, so the domain mutation, evidence row, and delivery intent commit together.
Workers claim with leases and publish idempotently into the internal event log.
"""

from __future__ import annotations

import asyncio
import fnmatch
import hashlib
import json
import os
import time
import uuid
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, Header, HTTPException
from kafka import KafkaProducer
from kafka.errors import KafkaError
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import Boolean, ForeignKey, JSON, Integer, String, UniqueConstraint, event, func, inspect, or_
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Mapped, Session, mapped_column

from . import models_action, ops_control, tenancy
from .database import Base, SessionLocal, get_db
from .production_auth import Principal, require_detached_permission, require_permission


router = APIRouter(prefix="/api/v1", tags=["event-outbox"])
OUTBOX_JSON = JSON().with_variant(JSONB(), "postgresql")


def _now() -> int:
    return int(time.time())


def _id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:20]}"


class EventOutbox(Base):
    __tablename__ = "event_outbox"
    __table_args__ = (
        UniqueConstraint("project_id", "idempotency_key", name="uq_event_outbox_project_idempotency"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True)
    project_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    topic: Mapped[str] = mapped_column(String, nullable=False, index=True)
    event_type: Mapped[str] = mapped_column(String, nullable=False, index=True)
    aggregate_type: Mapped[str] = mapped_column(String, nullable=False, index=True)
    aggregate_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    actor: Mapped[str] = mapped_column(String, nullable=False)
    payload: Mapped[dict] = mapped_column(OUTBOX_JSON, nullable=False, default=dict)
    headers: Mapped[dict] = mapped_column(OUTBOX_JSON, nullable=False, default=dict)
    idempotency_key: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, default="PENDING", index=True)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=5)
    available_at: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    lease_owner: Mapped[Optional[str]] = mapped_column(String, nullable=True, index=True)
    lease_token: Mapped[Optional[str]] = mapped_column(String, nullable=True, unique=True)
    lease_expires_at: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    last_error: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    created_at: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    updated_at: Mapped[int] = mapped_column(Integer, nullable=False)
    published_at: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)


class PlatformEventLog(Base):
    __tablename__ = "platform_event_log"
    __table_args__ = (
        UniqueConstraint("outbox_event_id", name="uq_platform_event_log_outbox_event"),
    )

    sequence: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_id: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    outbox_event_id: Mapped[str] = mapped_column(String, nullable=False)
    project_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    topic: Mapped[str] = mapped_column(String, nullable=False, index=True)
    event_type: Mapped[str] = mapped_column(String, nullable=False, index=True)
    aggregate_type: Mapped[str] = mapped_column(String, nullable=False, index=True)
    aggregate_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    actor: Mapped[str] = mapped_column(String, nullable=False)
    payload: Mapped[dict] = mapped_column(OUTBOX_JSON, nullable=False, default=dict)
    headers: Mapped[dict] = mapped_column(OUTBOX_JSON, nullable=False, default=dict)
    occurred_at: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    published_at: Mapped[int] = mapped_column(Integer, nullable=False, index=True)


class EventTransportReceipt(Base):
    __tablename__ = "event_transport_receipts"
    __table_args__ = (
        UniqueConstraint("outbox_event_id", "transport", "destination", name="uq_event_transport_destination"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True)
    outbox_event_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    project_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    transport: Mapped[str] = mapped_column(String, nullable=False, index=True)
    destination: Mapped[str] = mapped_column(String, nullable=False, index=True)
    status: Mapped[str] = mapped_column(String, nullable=False, default="PENDING", index=True)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=5)
    available_at: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    lease_owner: Mapped[Optional[str]] = mapped_column(String, nullable=True, index=True)
    lease_token: Mapped[Optional[str]] = mapped_column(String, nullable=True, unique=True)
    lease_expires_at: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    broker_metadata: Mapped[dict] = mapped_column(OUTBOX_JSON, nullable=False, default=dict)
    last_error: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    created_at: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    updated_at: Mapped[int] = mapped_column(Integer, nullable=False)
    delivered_at: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)


class EventStreamBinding(Base):
    __tablename__ = "event_stream_bindings"
    __table_args__ = (
        UniqueConstraint("project_id", "display_name", name="uq_event_stream_binding_project_name"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True)
    project_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    display_name: Mapped[str] = mapped_column(String, nullable=False)
    target_stream_id: Mapped[str] = mapped_column(String, ForeignKey("streams.id"), nullable=False, index=True)
    topics: Mapped[list] = mapped_column(OUTBOX_JSON, nullable=False, default=list)
    event_types: Mapped[list] = mapped_column(OUTBOX_JSON, nullable=False, default=list)
    aggregate_types: Mapped[list] = mapped_column(OUTBOX_JSON, nullable=False, default=list)
    object_type_ids: Mapped[list] = mapped_column(OUTBOX_JSON, nullable=False, default=list)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    cursor_sequence: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_by: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[int] = mapped_column(Integer, nullable=False)
    updated_at: Mapped[int] = mapped_column(Integer, nullable=False)


class EventStreamReceipt(Base):
    __tablename__ = "event_stream_receipts"
    __table_args__ = (
        UniqueConstraint("binding_id", "event_id", name="uq_event_stream_binding_event"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True)
    project_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    binding_id: Mapped[str] = mapped_column(String, ForeignKey("event_stream_bindings.id"), nullable=False, index=True)
    event_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    event_sequence: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    stream_record_id: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    created_at: Mapped[int] = mapped_column(Integer, nullable=False)


class OutboxWorkerRequest(BaseModel):
    worker_id: str = Field(default="event-dispatcher", min_length=1, max_length=200)
    lease_seconds: int = Field(default=60, ge=10, le=900)
    event_id: Optional[str] = None
    inject_failure: Optional[str] = Field(default=None, pattern="^(before_publish|after_publish)$")


class OutboxReplayRequest(BaseModel):
    reset_attempts: bool = True


class TransportWorkerRequest(BaseModel):
    worker_id: str = Field(default="event-transport-dispatcher", min_length=1, max_length=200)
    lease_seconds: int = Field(default=60, ge=10, le=900)
    event_id: Optional[str] = None
    inject_failure: Optional[str] = Field(default=None, pattern="^(before_publish|after_publish)$")


class EventStreamBindingCreate(BaseModel):
    id: Optional[str] = None
    project_id: str = "default"
    display_name: str = Field(min_length=1, max_length=200)
    target_stream_id: str = Field(min_length=1, max_length=255)
    topics: list[str] = Field(default_factory=list, max_length=100)
    event_types: list[str] = Field(default_factory=list, max_length=100)
    aggregate_types: list[str] = Field(default_factory=list, max_length=100)
    object_type_ids: list[str] = Field(default_factory=list, max_length=100)
    active: bool = True
    start_sequence: int = Field(default=0, ge=0)


class EventStreamBindingPatch(BaseModel):
    display_name: Optional[str] = Field(default=None, min_length=1, max_length=200)
    topics: Optional[list[str]] = Field(default=None, max_length=100)
    event_types: Optional[list[str]] = Field(default=None, max_length=100)
    aggregate_types: Optional[list[str]] = Field(default=None, max_length=100)
    object_type_ids: Optional[list[str]] = Field(default=None, max_length=100)
    active: Optional[bool] = None


class EventStreamRouteRequest(BaseModel):
    max_events: int = Field(default=1000, ge=1, le=10000)
    inject_failure_after_records: Optional[int] = Field(default=None, ge=1, le=10000)


class EventStreamEnqueueRequest(BaseModel):
    max_events: int = Field(default=1000, ge=1, le=10000)
    priority: int = Field(default=50, ge=0, le=100)
    max_attempts: int = Field(default=5, ge=1, le=20)
    timeout_seconds: int = Field(default=3600, ge=10, le=86400)
    idempotency_key: Optional[str] = Field(default=None, max_length=255)


class EventStreamWorkerRequest(BaseModel):
    worker_id: str = Field(default="event-stream-router", min_length=1, max_length=200)
    lease_seconds: int = Field(default=120, ge=10, le=900)
    job_id: Optional[str] = None
    inject_failure_after_records: Optional[int] = Field(default=None, ge=1, le=10000)


def _outbox_dict(row: EventOutbox) -> Dict[str, Any]:
    return {
        "id": row.id, "project_id": row.project_id, "topic": row.topic,
        "event_type": row.event_type, "aggregate_type": row.aggregate_type,
        "aggregate_id": row.aggregate_id, "actor": row.actor,
        "payload": row.payload or {}, "headers": row.headers or {},
        "idempotency_key": row.idempotency_key, "status": row.status,
        "attempts": row.attempts, "max_attempts": row.max_attempts,
        "available_at": row.available_at, "lease_owner": row.lease_owner,
        "lease_expires_at": row.lease_expires_at, "last_error": row.last_error,
        "created_at": row.created_at, "updated_at": row.updated_at,
        "published_at": row.published_at,
    }


def _event_dict(row: PlatformEventLog) -> Dict[str, Any]:
    return {
        "sequence": row.sequence, "event_id": row.event_id,
        "outbox_event_id": row.outbox_event_id, "project_id": row.project_id,
        "topic": row.topic, "event_type": row.event_type,
        "aggregate_type": row.aggregate_type, "aggregate_id": row.aggregate_id,
        "actor": row.actor, "payload": row.payload or {}, "headers": row.headers or {},
        "occurred_at": row.occurred_at, "published_at": row.published_at,
    }


def _binding_dict(row: EventStreamBinding) -> Dict[str, Any]:
    return {
        "id": row.id, "project_id": row.project_id, "display_name": row.display_name,
        "target_stream_id": row.target_stream_id, "topics": row.topics or [],
        "event_types": row.event_types or [], "aggregate_types": row.aggregate_types or [],
        "object_type_ids": row.object_type_ids or [], "active": row.active,
        "cursor_sequence": row.cursor_sequence, "created_by": row.created_by,
        "created_at": row.created_at, "updated_at": row.updated_at,
    }


def _stream_receipt_dict(row: EventStreamReceipt) -> Dict[str, Any]:
    return {
        "id": row.id, "project_id": row.project_id, "binding_id": row.binding_id,
        "event_id": row.event_id, "event_sequence": row.event_sequence,
        "stream_record_id": row.stream_record_id, "created_at": row.created_at,
    }


def _receipt_dict(row: EventTransportReceipt) -> Dict[str, Any]:
    return {
        "id": row.id, "outbox_event_id": row.outbox_event_id,
        "project_id": row.project_id, "transport": row.transport,
        "destination": row.destination, "status": row.status,
        "attempts": row.attempts, "max_attempts": row.max_attempts,
        "available_at": row.available_at, "lease_owner": row.lease_owner,
        "lease_expires_at": row.lease_expires_at,
        "broker_metadata": row.broker_metadata or {}, "last_error": row.last_error,
        "created_at": row.created_at, "updated_at": row.updated_at,
        "delivered_at": row.delivered_at,
    }


def _project_id(payload: Dict[str, Any]) -> str:
    return str(payload.get("project_id") or payload.get("project") or "default")


def _matches_patterns(value: str, patterns: list[str]) -> bool:
    return not patterns or any(fnmatch.fnmatchcase(value, pattern) for pattern in patterns)


def _event_matches_binding(row: PlatformEventLog, binding: EventStreamBinding) -> bool:
    payload = row.payload or {}
    return (
        _matches_patterns(row.topic, binding.topics or [])
        and _matches_patterns(row.event_type, binding.event_types or [])
        and _matches_patterns(row.aggregate_type, binding.aggregate_types or [])
        and (
            not (binding.object_type_ids or [])
            or str(payload.get("object_type_id") or "") in set(binding.object_type_ids or [])
        )
    )


def enqueue_domain_event(
    session: Session,
    *,
    project_id: str,
    topic: str,
    event_type: str,
    aggregate_type: str,
    aggregate_id: str,
    actor: str,
    payload: Dict[str, Any],
    idempotency_key: str,
    occurred_at: Optional[int] = None,
    check_existing: bool = True,
) -> Optional[EventOutbox]:
    """Persist a domain delivery intent in the caller's transaction."""
    available = session.info.get("event_outbox_table_available")
    if available is None:
        bind = session.get_bind()
        available = bool(bind is not None and inspect(bind).has_table(EventOutbox.__tablename__))
        session.info["event_outbox_table_available"] = available
    if not available:
        return None

    pending_key = (project_id, idempotency_key)
    pending_events = session.info.setdefault("pending_domain_events", {})
    pending = pending_events.get(pending_key)
    if pending is not None and pending in session.new:
        return pending
    pending_events.pop(pending_key, None)
    if check_existing:
        with session.no_autoflush:
            existing = session.query(EventOutbox).filter(
                EventOutbox.project_id == project_id,
                EventOutbox.idempotency_key == idempotency_key,
            ).first()
        if existing is not None:
            return existing

    now = occurred_at or _now()
    outbox = EventOutbox(
        id=_id("outbox"), project_id=project_id, topic=topic,
        event_type=event_type, aggregate_type=aggregate_type, aggregate_id=aggregate_id,
        actor=actor, payload=dict(payload),
        headers={"schema_version": 1, "content_type": "application/json"},
        idempotency_key=idempotency_key, status="PENDING", attempts=0,
        max_attempts=5, available_at=now, created_at=now, updated_at=now,
    )
    session.add(outbox)
    pending_events[pending_key] = outbox
    if os.getenv("EVENT_KAFKA_BOOTSTRAP_SERVERS", "").strip():
        destination = _kafka_destination(outbox)
        session.add(EventTransportReceipt(
            id=_id("delivery"), outbox_event_id=outbox.id, project_id=project_id,
            transport="kafka", destination=destination, status="PENDING",
            attempts=0, max_attempts=5, available_at=now,
            broker_metadata={}, created_at=now, updated_at=now,
        ))
    return outbox


def _enqueue_from_evidence(session: Session, evidence: Any, *, source: str) -> EventOutbox:
    payload = dict(getattr(evidence, "payload", None) or {})
    evidence_id = str(evidence.id)
    event_type = str(evidence.event_type)
    project_id = str(getattr(evidence, "project_id", None) or _project_id(payload))
    aggregate_type = str(getattr(evidence, "subject_type", None) or source)
    aggregate_id = str(getattr(evidence, "subject_id", None) or evidence_id)
    outbox = enqueue_domain_event(
        session, project_id=project_id, topic=f"ontologyos.{source}",
        event_type=event_type, aggregate_type=aggregate_type, aggregate_id=aggregate_id,
        actor=str(getattr(evidence, "actor", None) or source),
        payload={"evidence_id": evidence_id, "evidence_source": source, **payload},
        idempotency_key=f"{source}:{evidence_id}",
        check_existing=False,
    )
    if outbox is None:
        raise RuntimeError("Event outbox table disappeared during evidence capture")
    return outbox


@event.listens_for(Session, "before_flush")
def _capture_evidence_events(session: Session, _flush_context, _instances) -> None:
    if session.info.get("suppress_event_outbox"):
        return
    existing_pairs = {
        (row.project_id, row.idempotency_key)
        for row in session.new if isinstance(row, EventOutbox)
    }
    candidates = []
    for row in list(session.new):
        source = "audit" if isinstance(row, models_action.AuditLog) else "ops" if isinstance(row, ops_control.OpsEvent) else None
        if source is None or not getattr(row, "id", None):
            continue
        key = f"{source}:{row.id}"
        project_id = str(getattr(row, "project_id", None) or _project_id(dict(getattr(row, "payload", None) or {})))
        candidates.append((row, source, project_id, key))

    candidate_keys = {key for _, _, _, key in candidates}
    if candidate_keys:
        with session.no_autoflush:
            persisted = session.query(EventOutbox.project_id, EventOutbox.idempotency_key).filter(
                EventOutbox.idempotency_key.in_(candidate_keys)
            ).all()
        existing_pairs.update((str(project_id), str(key)) for project_id, key in persisted)

    for row, source, project_id, key in candidates:
        if (project_id, key) in existing_pairs:
            continue
        _enqueue_from_evidence(session, row, source=source)
        existing_pairs.add((project_id, key))


def _claim(db: Session, body: OutboxWorkerRequest) -> Optional[EventOutbox]:
    now = _now()
    query = db.query(EventOutbox).filter(
        EventOutbox.status.in_(["PENDING", "RETRY", "IN_FLIGHT"]),
        EventOutbox.available_at <= now,
        or_(EventOutbox.lease_expires_at.is_(None), EventOutbox.lease_expires_at <= now),
    )
    if body.event_id:
        query = query.filter(EventOutbox.id == body.event_id)
    query = query.order_by(EventOutbox.available_at, EventOutbox.created_at, EventOutbox.id)
    if db.get_bind().dialect.name == "postgresql":
        query = query.with_for_update(skip_locked=True)
    row = query.first()
    if row is None:
        return None
    row.status = "IN_FLIGHT"
    row.attempts += 1
    row.lease_owner = body.worker_id
    row.lease_token = uuid.uuid4().hex
    row.lease_expires_at = now + body.lease_seconds
    row.updated_at = now
    db.flush()
    return row


def _publish_internal(db: Session, row: EventOutbox) -> PlatformEventLog:
    existing = db.query(PlatformEventLog).filter(PlatformEventLog.outbox_event_id == row.id).first()
    if existing is not None:
        return existing
    published_at = _now()
    event_id = hashlib.sha256(f"{row.project_id}\x1f{row.idempotency_key}".encode("utf-8")).hexdigest()
    published = PlatformEventLog(
        event_id=event_id, outbox_event_id=row.id, project_id=row.project_id,
        topic=row.topic, event_type=row.event_type, aggregate_type=row.aggregate_type,
        aggregate_id=row.aggregate_id, actor=row.actor, payload=row.payload or {},
        headers=row.headers or {}, occurred_at=row.created_at, published_at=published_at,
    )
    db.add(published)
    db.flush()
    return published


def _kafka_settings() -> Dict[str, Any]:
    brokers = [value.strip() for value in os.getenv("EVENT_KAFKA_BOOTSTRAP_SERVERS", "").split(",") if value.strip()]
    if not brokers:
        raise HTTPException(status_code=503, detail="Kafka event transport is not configured")
    protocol = os.getenv("EVENT_KAFKA_SECURITY_PROTOCOL", "SASL_SSL").strip().upper()
    if protocol not in {"PLAINTEXT", "SSL", "SASL_PLAINTEXT", "SASL_SSL"}:
        raise HTTPException(status_code=503, detail="Kafka event transport security protocol is invalid")
    production = os.getenv("APP_ENV", "development").strip().lower() == "production"
    allow_plaintext = os.getenv("EVENT_KAFKA_ALLOW_PLAINTEXT", "false").strip().lower() in {"1", "true", "yes"}
    if production and protocol in {"PLAINTEXT", "SASL_PLAINTEXT"} and not allow_plaintext:
        raise HTTPException(status_code=503, detail="Plaintext Kafka event transport is disabled in production")
    settings: Dict[str, Any] = {
        "bootstrap_servers": brokers,
        "security_protocol": protocol,
        "client_id": os.getenv("EVENT_KAFKA_CLIENT_ID", "ontologyos-event-publisher"),
        "acks": "all",
        "retries": 5,
        "max_in_flight_requests_per_connection": 1,
        "request_timeout_ms": max(1000, int(os.getenv("EVENT_KAFKA_REQUEST_TIMEOUT_MS", "30000"))),
        "max_block_ms": max(1000, int(os.getenv("EVENT_KAFKA_MAX_BLOCK_MS", "10000"))),
    }
    if protocol.startswith("SASL"):
        username = os.getenv("EVENT_KAFKA_SASL_USERNAME", "").strip()
        password = os.getenv("EVENT_KAFKA_SASL_PASSWORD", "")
        if not username or not password:
            raise HTTPException(status_code=503, detail="Kafka SASL credentials are not configured")
        settings.update({
            "sasl_mechanism": os.getenv("EVENT_KAFKA_SASL_MECHANISM", "PLAIN").strip().upper(),
            "sasl_plain_username": username,
            "sasl_plain_password": password,
        })
    return settings


def _kafka_destination(row: EventOutbox) -> str:
    prefix = os.getenv("EVENT_KAFKA_TOPIC_PREFIX", "").strip().strip(".")
    return f"{prefix}.{row.topic}" if prefix else row.topic


def _publish_kafka(row: EventOutbox, destination: str, settings: Dict[str, Any]) -> Dict[str, Any]:
    envelope = {
        "event_id": hashlib.sha256(f"{row.project_id}\x1f{row.idempotency_key}".encode("utf-8")).hexdigest(),
        "outbox_event_id": row.id,
        "project_id": row.project_id,
        "event_type": row.event_type,
        "aggregate_type": row.aggregate_type,
        "aggregate_id": row.aggregate_id,
        "actor": row.actor,
        "payload": row.payload or {},
        "headers": row.headers or {},
        "occurred_at": row.created_at,
    }
    producer = KafkaProducer(
        **settings,
        key_serializer=lambda value: value.encode("utf-8"),
        value_serializer=lambda value: json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8"),
    )
    try:
        future = producer.send(
            destination,
            key=f"{row.aggregate_type}:{row.aggregate_id}",
            value=envelope,
            headers=[
                ("ontologyos-event-id", envelope["event_id"].encode("utf-8")),
                ("ontologyos-project-id", row.project_id.encode("utf-8")),
                ("ontologyos-event-type", row.event_type.encode("utf-8")),
            ],
        )
        metadata = future.get(timeout=max(1, int(settings["request_timeout_ms"]) // 1000 + 1))
        producer.flush(timeout=max(1, int(settings["request_timeout_ms"]) // 1000 + 1))
        return {
            "topic": metadata.topic, "partition": metadata.partition,
            "offset": metadata.offset, "timestamp": metadata.timestamp,
            "event_id": envelope["event_id"],
        }
    except KafkaError as exc:
        raise RuntimeError(f"Kafka publish failed: {type(exc).__name__}") from exc
    finally:
        producer.close(timeout=5)


def _ensure_transport_receipt(db: Session, row: EventOutbox, transport: str, destination: str) -> EventTransportReceipt:
    receipt = db.query(EventTransportReceipt).filter(
        EventTransportReceipt.outbox_event_id == row.id,
        EventTransportReceipt.transport == transport,
        EventTransportReceipt.destination == destination,
    ).first()
    if receipt is not None:
        return receipt
    now = _now()
    receipt = EventTransportReceipt(
        id=_id("delivery"), outbox_event_id=row.id, project_id=row.project_id,
        transport=transport, destination=destination, status="PENDING",
        attempts=0, max_attempts=5, available_at=now,
        broker_metadata={}, created_at=now, updated_at=now,
    )
    try:
        with db.begin_nested():
            db.add(receipt)
            db.flush()
    except IntegrityError:
        receipt = db.query(EventTransportReceipt).filter(
            EventTransportReceipt.outbox_event_id == row.id,
            EventTransportReceipt.transport == transport,
            EventTransportReceipt.destination == destination,
        ).one()
    return receipt


def _claim_transport_receipt(db: Session, body: TransportWorkerRequest, transport: str, destination_for) -> Optional[EventTransportReceipt]:
    now = _now()
    query = db.query(EventTransportReceipt).join(
        EventOutbox, EventOutbox.id == EventTransportReceipt.outbox_event_id
    ).filter(
        EventTransportReceipt.transport == transport,
        EventOutbox.status == "PUBLISHED",
        EventTransportReceipt.status.in_(["PENDING", "RETRY", "IN_FLIGHT"]),
        EventTransportReceipt.available_at <= now,
        or_(EventTransportReceipt.lease_expires_at.is_(None), EventTransportReceipt.lease_expires_at <= now),
    )
    if body.event_id:
        query = query.filter(EventTransportReceipt.outbox_event_id == body.event_id)
    query = query.order_by(EventTransportReceipt.available_at, EventTransportReceipt.created_at, EventTransportReceipt.id)
    if db.get_bind().dialect.name == "postgresql":
        query = query.with_for_update(skip_locked=True)
    receipt = query.first()
    if receipt is None:
        source = db.query(EventOutbox).filter(EventOutbox.status == "PUBLISHED")
        if body.event_id:
            source = source.filter(EventOutbox.id == body.event_id)
        source = source.filter(~db.query(EventTransportReceipt).filter(
            EventTransportReceipt.outbox_event_id == EventOutbox.id,
            EventTransportReceipt.transport == transport,
        ).exists()).order_by(EventOutbox.published_at, EventOutbox.id)
        if db.get_bind().dialect.name == "postgresql":
            source = source.with_for_update(skip_locked=True)
        outbox = source.first()
        if outbox is None:
            return None
        receipt = _ensure_transport_receipt(db, outbox, transport, destination_for(outbox))
    receipt.status = "IN_FLIGHT"
    receipt.attempts += 1
    receipt.lease_owner = body.worker_id
    receipt.lease_token = uuid.uuid4().hex
    receipt.lease_expires_at = now + body.lease_seconds
    receipt.updated_at = now
    db.flush()
    return receipt


def _event_stream_binding(
    db: Session,
    binding_id: str,
    principal: Principal,
    permission: str,
    *,
    lock: bool = False,
) -> EventStreamBinding:
    query = db.query(EventStreamBinding).filter(EventStreamBinding.id == binding_id)
    if lock and db.get_bind().dialect.name == "postgresql":
        query = query.with_for_update()
    row = query.first()
    if row is None:
        raise HTTPException(status_code=404, detail="Event stream binding not found")
    tenancy.assert_project_permission(db, principal, row.project_id, permission)
    return row


def route_event_stream_binding(
    db: Session,
    binding_id: str,
    *,
    principal: Principal,
    max_events: int,
    inject_failure_after_records: Optional[int] = None,
) -> Dict[str, Any]:
    from . import stream_processing, streaming

    binding = _event_stream_binding(db, binding_id, principal, "execute", lock=True)
    if not binding.active:
        raise HTTPException(status_code=409, detail="Event stream binding is inactive")
    stream = streaming._get_stream_or_404(binding.target_stream_id, db, principal, "execute")
    if stream.project_id != binding.project_id:
        raise HTTPException(status_code=409, detail="Target stream belongs to another project")
    events = db.query(PlatformEventLog).filter(
        PlatformEventLog.project_id == binding.project_id,
        PlatformEventLog.sequence > binding.cursor_sequence,
    ).order_by(PlatformEventLog.sequence).limit(max_events).all()
    if not events:
        return {
            "binding": _binding_dict(binding), "scanned": 0, "matched": 0,
            "routed": 0, "duplicates": 0, "cursor_sequence": binding.cursor_sequence,
            "stream_record_ids": [],
        }

    matches = [row for row in events if _event_matches_binding(row, binding)]
    event_ids = [row.event_id for row in matches]
    existing_ids = set()
    if event_ids:
        existing_ids = {
            event_id for (event_id,) in db.query(EventStreamReceipt.event_id).filter(
                EventStreamReceipt.binding_id == binding.id,
                EventStreamReceipt.event_id.in_(event_ids),
            ).all()
        }
    pending = [row for row in matches if row.event_id not in existing_ids]
    stream_processing.enforce_publish_capacity(db, stream.id, len(pending))
    sequences = streaming.allocate_sequences(db, stream.id, len(pending))
    now = _now()
    record_ids = []
    for index, (event_row, sequence) in enumerate(zip(pending, sequences), start=1):
        digest = hashlib.sha256(f"{binding.id}:{event_row.event_id}".encode("utf-8")).hexdigest()[:32]
        record_id = f"event_stream_record_{digest}"
        envelope = _event_dict(event_row)
        db.add(streaming.StreamRecord(
            id=record_id, stream_id=stream.id, sequence=sequence,
            payload=envelope, ts=event_row.occurred_at, created_at=now,
        ))
        db.add(EventStreamReceipt(
            id=f"event_stream_receipt_{digest}", project_id=binding.project_id,
            binding_id=binding.id, event_id=event_row.event_id,
            event_sequence=event_row.sequence, stream_record_id=record_id, created_at=now,
        ))
        record_ids.append(record_id)
        if inject_failure_after_records is not None and index >= inject_failure_after_records:
            raise RuntimeError("Injected event-to-stream routing failure")
    binding.cursor_sequence = events[-1].sequence
    binding.updated_at = now
    db.flush()
    return {
        "binding": _binding_dict(binding), "scanned": len(events), "matched": len(matches),
        "routed": len(pending), "duplicates": len(matches) - len(pending),
        "cursor_sequence": binding.cursor_sequence, "stream_record_ids": record_ids,
    }


@router.post("/event-stream-bindings", status_code=201)
def create_event_stream_binding(
    body: EventStreamBindingCreate,
    principal: Principal = Depends(require_permission("edit")),
    db: Session = Depends(get_db),
):
    from . import streaming

    tenancy.assert_project_permission(db, principal, body.project_id, "edit")
    stream = streaming._get_stream_or_404(body.target_stream_id, db, principal, "view")
    if stream.project_id != body.project_id:
        raise HTTPException(status_code=409, detail="Target stream belongs to another project")
    binding_id = body.id or _id("event_stream_binding")
    if db.get(EventStreamBinding, binding_id):
        raise HTTPException(status_code=409, detail="Event stream binding already exists")
    now = _now()
    row = EventStreamBinding(
        id=binding_id, project_id=body.project_id, display_name=body.display_name,
        target_stream_id=body.target_stream_id, topics=body.topics,
        event_types=body.event_types, aggregate_types=body.aggregate_types,
        object_type_ids=body.object_type_ids, active=body.active,
        cursor_sequence=body.start_sequence, created_by=principal.id,
        created_at=now, updated_at=now,
    )
    db.add(row)
    db.commit()
    return _binding_dict(row)


@router.get("/event-stream-bindings")
def list_event_stream_bindings(
    project_id: str = "default",
    principal: Principal = Depends(require_permission("view")),
    db: Session = Depends(get_db),
):
    tenancy.assert_project_permission(db, principal, project_id, "view")
    rows = db.query(EventStreamBinding).filter(
        EventStreamBinding.project_id == project_id,
    ).order_by(EventStreamBinding.created_at.desc(), EventStreamBinding.id).all()
    return {"count": len(rows), "bindings": [_binding_dict(row) for row in rows]}


@router.get("/event-stream-bindings/{binding_id}")
def get_event_stream_binding(
    binding_id: str,
    principal: Principal = Depends(require_permission("view")),
    db: Session = Depends(get_db),
):
    row = _event_stream_binding(db, binding_id, principal, "view")
    result = _binding_dict(row)
    result["receipt_count"] = db.query(EventStreamReceipt).filter(
        EventStreamReceipt.binding_id == row.id,
    ).count()
    return result


@router.patch("/event-stream-bindings/{binding_id}")
def patch_event_stream_binding(
    binding_id: str,
    body: EventStreamBindingPatch,
    principal: Principal = Depends(require_permission("edit")),
    db: Session = Depends(get_db),
):
    row = _event_stream_binding(db, binding_id, principal, "edit", lock=True)
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(row, field, value)
    row.updated_at = _now()
    db.commit()
    return _binding_dict(row)


@router.post("/event-stream-bindings/{binding_id}/route")
def route_event_stream_binding_now(
    binding_id: str,
    body: EventStreamRouteRequest = EventStreamRouteRequest(),
    principal: Principal = Depends(require_permission("execute")),
    db: Session = Depends(get_db),
):
    try:
        result = route_event_stream_binding(
            db, binding_id, principal=principal, max_events=body.max_events,
            inject_failure_after_records=body.inject_failure_after_records,
        )
        db.commit()
        return result
    except Exception:
        db.rollback()
        raise


@router.get("/event-stream-bindings/{binding_id}/receipts")
def list_event_stream_receipts(
    binding_id: str,
    limit: int = 100,
    principal: Principal = Depends(require_permission("view")),
    db: Session = Depends(get_db),
):
    row = _event_stream_binding(db, binding_id, principal, "view")
    receipts = db.query(EventStreamReceipt).filter(
        EventStreamReceipt.binding_id == row.id,
    ).order_by(EventStreamReceipt.event_sequence.desc()).limit(max(1, min(limit, 1000))).all()
    return {"count": len(receipts), "receipts": [_stream_receipt_dict(receipt) for receipt in receipts]}


@router.post("/event-stream-bindings/{binding_id}/enqueue", status_code=202)
def enqueue_event_stream_binding(
    binding_id: str,
    body: EventStreamEnqueueRequest = EventStreamEnqueueRequest(),
    principal: Principal = Depends(require_permission("execute")),
    db: Session = Depends(get_db),
):
    from . import platform_runtime

    row = _event_stream_binding(db, binding_id, principal, "execute")
    latest = int(db.query(func.max(PlatformEventLog.sequence)).filter(
        PlatformEventLog.project_id == row.project_id,
    ).scalar() or row.cursor_sequence)
    idempotency_key = body.idempotency_key or f"event-stream-route:{row.id}:{row.cursor_sequence}:{latest}"
    return platform_runtime.create_job(platform_runtime.JobCreate(
        project_id=row.project_id, job_type="event.stream.route",
        subject_type="event_stream_binding", subject_id=row.id,
        payload={"binding_id": row.id, "max_events": body.max_events},
        priority=body.priority, max_attempts=body.max_attempts,
        timeout_seconds=body.timeout_seconds, idempotency_key=idempotency_key,
        estimated_records=float(max(0, latest - row.cursor_sequence)),
    ), principal, db)


@router.post("/event-stream-bindings/workers/run-next")
def run_next_event_stream_binding(
    body: EventStreamWorkerRequest = EventStreamWorkerRequest(),
    principal: Principal = Depends(require_permission("execute")),
    db: Session = Depends(get_db),
):
    from . import platform_runtime, worker_control

    supported = worker_control.effective_worker_job_types(db, principal, body.worker_id, ["event.stream.route"])
    claimed = platform_runtime.claim_job(platform_runtime.JobClaimRequest(
        worker_id=body.worker_id, supported_job_types=supported,
        lease_seconds=body.lease_seconds, job_id=body.job_id,
    ), principal, db).get("job")
    if not claimed:
        return {"job": None, "routing": None}
    payload = dict(claimed.get("payload") or {})
    try:
        routing = route_event_stream_binding(
            db, payload["binding_id"], principal=principal,
            max_events=int(payload.get("max_events") or 1000),
            inject_failure_after_records=body.inject_failure_after_records,
        )
        db.commit()
        completed = platform_runtime.complete_job(
            claimed["id"], platform_runtime.JobCompleteRequest(
                lease_token=claimed["lease_token"], result=routing,
            ), principal, db,
        )
        return {"job": completed, "routing": routing}
    except Exception as exc:
        db.rollback()
        failed = platform_runtime.fail_job(
            claimed["id"], platform_runtime.JobFailRequest(
                lease_token=claimed["lease_token"], error=str(exc), retriable=True,
                retry_delay_seconds=0, details={"binding_id": payload.get("binding_id")},
            ), principal, db,
        )
        return {"job": failed, "routing": None}


@router.get("/outbox/summary")
def outbox_summary(project_id: str = "default", principal: Principal = Depends(require_permission("view")), db: Session = Depends(get_db)):
    tenancy.assert_project_permission(db, principal, project_id, "view")
    counts = dict(db.query(EventOutbox.status, func.count(EventOutbox.id)).filter(EventOutbox.project_id == project_id).group_by(EventOutbox.status).all())
    latest = db.query(PlatformEventLog).filter(PlatformEventLog.project_id == project_id).order_by(PlatformEventLog.sequence.desc()).first()
    delivery_counts = {
        f"{transport}:{status}": count
        for transport, status, count in db.query(
            EventTransportReceipt.transport, EventTransportReceipt.status, func.count(EventTransportReceipt.id)
        ).filter(EventTransportReceipt.project_id == project_id).group_by(
            EventTransportReceipt.transport, EventTransportReceipt.status
        ).all()
    }
    return {
        "project_id": project_id, "counts": counts,
        "pending": sum(counts.get(status, 0) for status in ("PENDING", "RETRY", "IN_FLIGHT")),
        "dead_letter": counts.get("DEAD_LETTER", 0),
        "latest_sequence": latest.sequence if latest else 0,
        "transport_deliveries": delivery_counts,
        "configured_transports": {
            "internal": True,
            "kafka": bool(os.getenv("EVENT_KAFKA_BOOTSTRAP_SERVERS", "").strip()),
        },
    }


@router.get("/outbox/events")
def list_outbox_events(project_id: str = "default", status: Optional[str] = None, limit: int = 100, principal: Principal = Depends(require_permission("view")), db: Session = Depends(get_db)):
    tenancy.assert_project_permission(db, principal, project_id, "view")
    query = db.query(EventOutbox).filter(EventOutbox.project_id == project_id)
    if status:
        query = query.filter(EventOutbox.status == status.upper())
    rows = query.order_by(EventOutbox.created_at.desc(), EventOutbox.id).limit(max(1, min(limit, 1000))).all()
    return {"project_id": project_id, "count": len(rows), "events": [_outbox_dict(row) for row in rows]}


@router.get("/outbox/transport-receipts")
def list_transport_receipts(
    project_id: str = "default", transport: Optional[str] = None,
    status: Optional[str] = None, limit: int = 100,
    principal: Principal = Depends(require_permission("view")), db: Session = Depends(get_db),
):
    tenancy.assert_project_permission(db, principal, project_id, "view")
    query = db.query(EventTransportReceipt).filter(EventTransportReceipt.project_id == project_id)
    if transport:
        query = query.filter(EventTransportReceipt.transport == transport.lower())
    if status:
        query = query.filter(EventTransportReceipt.status == status.upper())
    rows = query.order_by(EventTransportReceipt.created_at.desc(), EventTransportReceipt.id).limit(max(1, min(limit, 1000))).all()
    return {"project_id": project_id, "count": len(rows), "receipts": [_receipt_dict(row) for row in rows]}


@router.get("/events/log")
def list_event_log(project_id: str = "default", after_sequence: int = 0, limit: int = 100, principal: Principal = Depends(require_permission("view")), db: Session = Depends(get_db)):
    tenancy.assert_project_permission(db, principal, project_id, "view")
    rows = db.query(PlatformEventLog).filter(
        PlatformEventLog.project_id == project_id,
        PlatformEventLog.sequence > max(0, after_sequence),
    ).order_by(PlatformEventLog.sequence).limit(max(1, min(limit, 1000))).all()
    return {"project_id": project_id, "count": len(rows), "events": [_event_dict(row) for row in rows], "next_sequence": rows[-1].sequence if rows else after_sequence}


@router.get("/events/stream")
def stream_event_log(
    project_id: str = "default",
    after_sequence: int = 0,
    last_event_id: Optional[str] = Header(default=None, alias="Last-Event-ID"),
    principal: Principal = Depends(require_detached_permission("view")),
):
    try:
        cursor = max(0, int(last_event_id)) if last_event_id else max(0, after_sequence)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="Last-Event-ID must be an integer sequence") from exc
    with SessionLocal() as auth_db:
        tenancy.assert_project_permission(auth_db, principal, project_id, "view")

    async def generate():
        nonlocal cursor
        idle_ticks = 0
        while True:
            with SessionLocal() as poll_db:
                rows = poll_db.query(PlatformEventLog).filter(
                    PlatformEventLog.project_id == project_id,
                    PlatformEventLog.sequence > cursor,
                ).order_by(PlatformEventLog.sequence).limit(100).all()
                payloads = [_event_dict(row) for row in rows]
            if payloads:
                idle_ticks = 0
                for payload in payloads:
                    cursor = int(payload["sequence"])
                    data = json.dumps(payload, separators=(",", ":"), default=str)
                    yield f"id: {cursor}\nevent: {payload['event_type']}\ndata: {data}\n\n"
                continue
            idle_ticks += 1
            if idle_ticks >= 15:
                idle_ticks = 0
                yield f": heartbeat {int(time.time())}\n\n"
            await asyncio.sleep(1)

    return StreamingResponse(
        generate(), media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/outbox/workers/run-next")
def run_next_outbox_event(body: OutboxWorkerRequest, principal: Principal = Depends(require_permission("execute")), db: Session = Depends(get_db)):
    row = _claim(db, body)
    if row is None:
        db.commit()
        return {"claimed": False}
    tenancy.assert_project_permission(db, principal, row.project_id, "execute")
    row_id = row.id
    lease_token = row.lease_token
    db.commit()
    row = db.get(EventOutbox, row_id)
    if row is None or row.status != "IN_FLIGHT" or row.lease_token != lease_token:
        raise HTTPException(status_code=409, detail="Outbox claim lease was lost before dispatch")
    try:
        if body.inject_failure == "before_publish":
            raise RuntimeError("Injected outbox failure before publish")
        published = _publish_internal(db, row)
        if body.inject_failure == "after_publish":
            raise RuntimeError("Injected outbox failure after publish")
        row.status = "PUBLISHED"
        row.published_at = published.published_at
        row.last_error = None
        row.lease_owner = None
        row.lease_token = None
        row.lease_expires_at = None
        row.updated_at = _now()
        db.commit()
        return {"claimed": True, "outbox": _outbox_dict(row), "event": _event_dict(published)}
    except Exception as exc:
        db.rollback()
        failed = db.get(EventOutbox, row_id)
        if failed is None:
            raise
        failed.last_error = str(exc)[:2000]
        failed.lease_owner = None
        failed.lease_token = None
        failed.lease_expires_at = None
        failed.updated_at = _now()
        if failed.attempts >= failed.max_attempts:
            failed.status = "DEAD_LETTER"
        else:
            failed.status = "RETRY"
            failed.available_at = _now() + min(300, 2 ** max(0, failed.attempts - 1))
        db.commit()
        return {"claimed": True, "failed": True, "outbox": _outbox_dict(failed)}


@router.post("/outbox/kafka/workers/run-next")
def run_next_kafka_delivery(
    body: TransportWorkerRequest,
    principal: Principal = Depends(require_permission("execute")),
    db: Session = Depends(get_db),
):
    settings = _kafka_settings()
    receipt = _claim_transport_receipt(db, body, "kafka", _kafka_destination)
    if receipt is None:
        db.commit()
        return {"claimed": False}
    tenancy.assert_project_permission(db, principal, receipt.project_id, "execute")
    receipt_id = receipt.id
    lease_token = receipt.lease_token
    outbox_id = receipt.outbox_event_id
    destination = receipt.destination
    db.commit()
    receipt = db.get(EventTransportReceipt, receipt_id)
    outbox = db.get(EventOutbox, outbox_id)
    if receipt is None or outbox is None or receipt.status != "IN_FLIGHT" or receipt.lease_token != lease_token:
        raise HTTPException(status_code=409, detail="Kafka delivery claim lease was lost before dispatch")
    try:
        if body.inject_failure == "before_publish":
            raise RuntimeError("Injected Kafka delivery failure before publish")
        broker_metadata = _publish_kafka(outbox, destination, settings)
        if body.inject_failure == "after_publish":
            raise RuntimeError("Injected Kafka delivery failure after publish")
        receipt.status = "DELIVERED"
        receipt.broker_metadata = broker_metadata
        receipt.delivered_at = _now()
        receipt.last_error = None
        receipt.lease_owner = None
        receipt.lease_token = None
        receipt.lease_expires_at = None
        receipt.updated_at = _now()
        db.commit()
        return {"claimed": True, "delivery": _receipt_dict(receipt), "outbox": _outbox_dict(outbox)}
    except Exception as exc:
        db.rollback()
        failed = db.get(EventTransportReceipt, receipt_id)
        if failed is None:
            raise
        failed.last_error = str(exc)[:2000]
        failed.lease_owner = None
        failed.lease_token = None
        failed.lease_expires_at = None
        failed.updated_at = _now()
        if failed.attempts >= failed.max_attempts:
            failed.status = "DEAD_LETTER"
        else:
            failed.status = "RETRY"
            failed.available_at = _now() + min(300, 2 ** max(0, failed.attempts - 1))
        db.commit()
        return {"claimed": True, "failed": True, "delivery": _receipt_dict(failed), "outbox": _outbox_dict(outbox)}


@router.post("/outbox/transport-receipts/{receipt_id}/replay")
def replay_transport_receipt(
    receipt_id: str, body: OutboxReplayRequest,
    principal: Principal = Depends(require_permission("execute")), db: Session = Depends(get_db),
):
    receipt = db.get(EventTransportReceipt, receipt_id)
    if receipt is None:
        raise HTTPException(status_code=404, detail="Transport delivery receipt not found")
    tenancy.assert_project_permission(db, principal, receipt.project_id, "execute")
    if receipt.status not in {"DEAD_LETTER", "RETRY", "DELIVERED"}:
        raise HTTPException(status_code=409, detail="Only failed, dead-letter, or delivered receipts can be replayed")
    receipt.status = "PENDING"
    receipt.available_at = _now()
    receipt.last_error = None
    receipt.lease_owner = None
    receipt.lease_token = None
    receipt.lease_expires_at = None
    if body.reset_attempts:
        receipt.attempts = 0
    receipt.updated_at = _now()
    db.commit()
    return _receipt_dict(receipt)


@router.post("/outbox/events/{event_id}/replay")
def replay_outbox_event(event_id: str, body: OutboxReplayRequest, principal: Principal = Depends(require_permission("execute")), db: Session = Depends(get_db)):
    row = db.get(EventOutbox, event_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Outbox event not found")
    tenancy.assert_project_permission(db, principal, row.project_id, "execute")
    if row.status not in {"DEAD_LETTER", "RETRY", "PUBLISHED"}:
        raise HTTPException(status_code=409, detail="Only failed, dead-letter, or published events can be replayed")
    row.status = "PENDING"
    row.available_at = _now()
    row.last_error = None
    row.lease_owner = None
    row.lease_token = None
    row.lease_expires_at = None
    if body.reset_attempts:
        row.attempts = 0
    row.updated_at = _now()
    db.commit()
    return _outbox_dict(row)

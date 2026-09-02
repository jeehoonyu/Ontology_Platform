import time
import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import String, Integer, JSON, ForeignKey, Boolean, update
from sqlalchemy.orm import Mapped, mapped_column, Session, relationship

from .database import Base, get_db
from . import models, models_action, ops_control, tenancy
from .production_auth import Principal, require_permission

# ---------------------------------------------------------------------------
# SQLAlchemy ORM models
# ---------------------------------------------------------------------------

class Stream(Base):
    __tablename__ = "streams"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    project_id: Mapped[str] = mapped_column(String, default="default", index=True)
    display_name: Mapped[str] = mapped_column(String)
    schema_: Mapped[dict] = mapped_column("schema", JSON, default=dict)
    retention_seconds: Mapped[int] = mapped_column(Integer, default=86400)
    # Auto-archive policy: {"max_age_seconds": int|None, "max_records": int|None}.
    # Empty dict means no policy configured (default for existing rows).
    archive_policy: Mapped[dict] = mapped_column(JSON, default=dict)
    next_sequence: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[int] = mapped_column(Integer)

    records: Mapped[list] = relationship("StreamRecord", back_populates="stream", cascade="all, delete-orphan")


class StreamRecord(Base):
    __tablename__ = "stream_records"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    stream_id: Mapped[str] = mapped_column(String, ForeignKey("streams.id"), index=True)
    sequence: Mapped[int] = mapped_column(Integer, index=True)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    ts: Mapped[int] = mapped_column(Integer)
    # Set when an auto-archive policy moves the record out of the live window.
    # Defaults to False so existing rows / publishers are unaffected.
    archived: Mapped[bool] = mapped_column(Boolean, default=False)
    archived_at: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    created_at: Mapped[int] = mapped_column(Integer)

    stream: Mapped["Stream"] = relationship("Stream", back_populates="records")


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------

class StreamCreate(BaseModel):
    id: Optional[str] = None
    project_id: str = "default"
    display_name: str
    schema_: Dict[str, Any] = Field(default_factory=dict, alias="schema")
    retention_seconds: int = 86400

    model_config = ConfigDict(populate_by_name=True)


class StreamRead(BaseModel):
    id: str
    project_id: str
    display_name: str
    schema_: Dict[str, Any] = Field(alias="schema")
    retention_seconds: int
    created_at: int

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    @classmethod
    def from_orm_obj(cls, obj: Stream) -> "StreamRead":
        return cls(
            id=obj.id,
            project_id=obj.project_id,
            display_name=obj.display_name,
            schema=obj.schema_,
            retention_seconds=obj.retention_seconds,
            created_at=obj.created_at,
        )


class StreamRecordRead(BaseModel):
    id: str
    stream_id: str
    sequence: int
    payload: Dict[str, Any]
    ts: int
    created_at: int

    model_config = ConfigDict(from_attributes=True)


class PublishRequest(BaseModel):
    records: List[Dict[str, Any]]


class PublishResponse(BaseModel):
    published: int


class ArchiveRequest(BaseModel):
    target_asset_id: str


class ArchiveResponse(BaseModel):
    archived: int


class ArchivePolicyRequest(BaseModel):
    """Auto-archive policy. Both bounds are optional; omitting both clears the policy."""
    max_age_seconds: Optional[int] = Field(default=None, ge=0)
    max_records: Optional[int] = Field(default=None, ge=0)


class ArchivePolicyRead(BaseModel):
    stream_id: str
    max_age_seconds: Optional[int] = None
    max_records: Optional[int] = None


class ApplyArchivePolicyRequest(BaseModel):
    # Deterministic clock for age-based archiving; defaults to the wall clock.
    now: Optional[int] = None


class ApplyArchivePolicyResponse(BaseModel):
    stream_id: str
    archived: int
    remaining: int
    now: int


class StreamMetricsRead(BaseModel):
    stream_id: str
    record_count: int
    first_ts: Optional[int] = None
    last_ts: Optional[int] = None
    records_per_second: float


class StreamReplayRequest(BaseModel):
    records: List[Dict[str, Any]] = Field(default_factory=list)
    timestamp_field: Optional[str] = None
    start_ts: Optional[int] = None
    interval_seconds: int = Field(default=1, ge=0)
    target_asset_id: Optional[str] = None
    archive_to_dataset: bool = False
    create_target_asset: bool = True
    target_display_name: Optional[str] = None
    actor: str = "workspace"


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

router = APIRouter(tags=["streaming"])


def _now() -> int:
    return int(time.time())


def _get_stream_or_404(stream_id: str, db: Session, principal: Optional[Principal] = None, permission: str = "view") -> Stream:
    stream = db.query(Stream).filter(Stream.id == stream_id).first()
    if not stream:
        raise HTTPException(status_code=404, detail=f"Stream '{stream_id}' not found")
    if principal:
        tenancy.assert_project_permission(db, principal, stream.project_id, permission)
    return stream


def allocate_sequences(db: Session, stream_id: str, count: int) -> List[int]:
    """Reserve a contiguous arrival-order range for one stream."""
    if count <= 0:
        return []
    last = db.execute(
        update(Stream)
        .where(Stream.id == stream_id)
        .values(next_sequence=Stream.next_sequence + count)
        .returning(Stream.next_sequence)
    ).scalar_one_or_none()
    if last is None:
        raise HTTPException(status_code=404, detail=f"Stream '{stream_id}' not found")
    first = int(last) - count + 1
    return list(range(first, first + count))


# POST /streams - create a stream
@router.post("/streams", response_model=StreamRead)
def create_stream(body: StreamCreate, principal: Principal = Depends(require_permission("edit")), db: Session = Depends(get_db)):
    tenancy.assert_project_permission(db, principal, body.project_id, "edit")
    stream_id = body.id or uuid.uuid4().hex
    existing = db.query(Stream).filter(Stream.id == stream_id).first()
    if existing:
        raise HTTPException(status_code=400, detail="Stream already exists")

    now = _now()
    db_stream = Stream(
        id=stream_id,
        project_id=body.project_id,
        display_name=body.display_name,
        schema_=body.schema_,
        retention_seconds=body.retention_seconds,
        next_sequence=0,
        created_at=now,
    )
    db.add(db_stream)
    db.commit()
    db.refresh(db_stream)
    return StreamRead.from_orm_obj(db_stream)


# GET /streams - list all streams
@router.get("/streams", response_model=List[StreamRead])
def list_streams(project_id: Optional[str] = None, principal: Principal = Depends(require_permission("view")), db: Session = Depends(get_db)):
    query = db.query(Stream)
    if project_id:
        tenancy.assert_project_permission(db, principal, project_id, "view")
        query = query.filter(Stream.project_id == project_id)
    else:
        accessible = tenancy.accessible_project_ids(db, principal)
        if accessible is not None:
            query = query.filter(Stream.project_id.in_(accessible))
    streams = query.order_by(Stream.created_at.desc()).all()
    return [StreamRead.from_orm_obj(s) for s in streams]


# GET /streams/{id} - get a single stream
@router.get("/streams/{stream_id}", response_model=StreamRead)
def get_stream(stream_id: str, principal: Principal = Depends(require_permission("view")), db: Session = Depends(get_db)):
    stream = _get_stream_or_404(stream_id, db, principal)
    return StreamRead.from_orm_obj(stream)


# POST /streams/{id}/publish - append records to the stream
@router.post("/streams/{stream_id}/publish", response_model=PublishResponse)
def publish_to_stream(
    stream_id: str,
    body: PublishRequest,
    principal: Principal = Depends(require_permission("execute")),
    db: Session = Depends(get_db),
):
    _get_stream_or_404(stream_id, db, principal, "execute")
    from . import stream_processing
    stream_processing.enforce_publish_capacity(db, stream_id, len(body.records))

    now = _now()
    sequences = allocate_sequences(db, stream_id, len(body.records))
    for record_payload, sequence in zip(body.records, sequences):
        db.add(StreamRecord(
            id=uuid.uuid4().hex,
            stream_id=stream_id,
            sequence=sequence,
            payload=record_payload,
            ts=now,
            created_at=now,
        ))

    db.commit()
    return PublishResponse(published=len(body.records))


# GET /streams/{id}/records - retrieve recent records
@router.get("/streams/{stream_id}/records", response_model=List[StreamRecordRead])
def get_stream_records(
    stream_id: str,
    limit: int = Query(default=100, ge=1, le=10000),
    principal: Principal = Depends(require_permission("view")),
    db: Session = Depends(get_db),
):
    _get_stream_or_404(stream_id, db, principal)

    rows = (
        db.query(StreamRecord)
        .filter(StreamRecord.stream_id == stream_id)
        .order_by(StreamRecord.sequence.desc())
        .limit(limit)
        .all()
    )
    return rows


# POST /streams/{id}/archive - copy stream payloads into a DataAsset and log it
@router.post("/streams/{stream_id}/archive", response_model=ArchiveResponse)
def archive_stream(
    stream_id: str,
    body: ArchiveRequest,
    actor: str = "system",
    principal: Principal = Depends(require_permission("execute")),
    db: Session = Depends(get_db),
):
    stream = _get_stream_or_404(stream_id, db, principal, "execute")

    # `target_asset_id` comes from the request body, and the permission above is about the
    # stream. Archiving copies this stream's payloads *into* the asset it names, so an
    # unscoped lookup let a caller write their records into another project's dataset --
    # the one defect of this shape that writes rather than discloses.
    # T2 of GOAL_TENANCY_2026-08-27.
    asset = db.query(models.DataAsset).filter(
        models.DataAsset.id == body.target_asset_id,
        models.DataAsset.project_id == stream.project_id,
    ).first()
    if not asset:
        raise HTTPException(
            status_code=404,
            detail=f"DataAsset '{body.target_asset_id}' not found",
        )

    rows = (
        db.query(StreamRecord)
        .filter(StreamRecord.stream_id == stream_id)
        .order_by(StreamRecord.sequence.asc())
        .all()
    )

    new_records = [r.payload for r in rows]
    existing = list(asset.records or [])
    asset.records = existing + new_records
    asset.updated_at = _now()

    db.add(
        models_action.AuditLog(
            id=uuid.uuid4().hex,
            actor=actor,
            event_type="stream.archived",
            subject_type="stream",
            subject_id=stream_id,
            payload={
                "target_asset_id": body.target_asset_id,
                "archived": len(new_records),
            },
        )
    )
    ops_control.record_ops_event(
        db,
        source="streaming",
        event_type="stream.archived",
        severity="info",
        title=f"Stream archived to dataset {body.target_asset_id}",
        subject_type="stream",
        subject_id=stream_id,
        payload={"target_asset_id": body.target_asset_id, "archived": len(new_records)},
    )
    db.commit()
    return ArchiveResponse(archived=len(new_records))


@router.post("/streams/{stream_id}/replay")
def replay_stream(stream_id: str, body: StreamReplayRequest, principal: Principal = Depends(require_permission("execute")), db: Session = Depends(get_db)):
    stream = _get_stream_or_404(stream_id, db, principal, "execute")
    now = body.start_ts if body.start_ts is not None else _now()
    records = [dict(row or {}) for row in body.records]
    if not records:
        cfg_records = []
        if isinstance(stream.schema_, dict):
            cfg_records = stream.schema_.get("sample_records") or stream.schema_.get("sample") or []
        records = [dict(row) for row in cfg_records if isinstance(row, dict)]
    if not records:
        raise HTTPException(status_code=400, detail="Replay requires records or stream schema sample_records")
    from . import stream_processing
    stream_processing.enforce_publish_capacity(db, stream_id, len(records))

    created_records: List[StreamRecord] = []
    sequences = allocate_sequences(db, stream_id, len(records))
    for index, (payload, sequence) in enumerate(zip(records, sequences)):
        ts = now + (index * body.interval_seconds)
        if body.timestamp_field and payload.get(body.timestamp_field) not in (None, ""):
            try:
                ts = int(payload[body.timestamp_field])
            except (TypeError, ValueError):
                ts = now + (index * body.interval_seconds)
        row = StreamRecord(
            id=uuid.uuid4().hex,
            stream_id=stream_id,
            sequence=sequence,
            payload=payload,
            ts=ts,
            created_at=now,
        )
        created_records.append(row)
        db.add(row)

    archived = 0
    target_asset_id = body.target_asset_id
    if body.archive_to_dataset and target_asset_id:
        asset = db.query(models.DataAsset).filter(models.DataAsset.id == target_asset_id).first()
        if not asset and body.create_target_asset:
            asset = models.DataAsset(
                id=target_asset_id,
                project_id=stream.project_id,
                display_name=body.target_display_name or f"{stream.display_name} Replay Archive",
                description=f"Archived replay records from stream {stream.id}.",
                kind="dataset",
                asset_schema={"project_id": stream.project_id, "source_stream_id": stream.id, "record_count": len(records)},
                records=[],
                created_at=now,
                updated_at=now,
            )
            db.add(asset)
        if not asset:
            raise HTTPException(status_code=404, detail=f"DataAsset '{target_asset_id}' not found")
        if asset.project_id != stream.project_id:
            raise HTTPException(status_code=409, detail="Target dataset belongs to another project")
        asset.records = list(asset.records or []) + records
        asset.updated_at = now
        archived = len(records)

    db.add(
        models_action.AuditLog(
            id=uuid.uuid4().hex,
            actor=body.actor,
            event_type="stream.replayed",
            subject_type="stream",
            subject_id=stream_id,
            payload={
                "published": len(records),
                "archived": archived,
                "target_asset_id": target_asset_id,
                "first_ts": created_records[0].ts,
                "last_ts": created_records[-1].ts,
            },
        )
    )
    ops_control.record_ops_event(
        db,
        source="streaming",
        event_type="stream.replayed",
        severity="info",
        title=f"Stream replayed {len(records)} record(s)",
        subject_type="stream",
        subject_id=stream_id,
        payload={"published": len(records), "archived": archived, "target_asset_id": target_asset_id},
    )
    db.commit()
    return {
        "stream_id": stream_id,
        "published": len(records),
        "archived": archived,
        "target_asset_id": target_asset_id,
        "first_ts": created_records[0].ts,
        "last_ts": created_records[-1].ts,
        "record_ids": [row.id for row in created_records],
    }


# POST /streams/{id}/archive-policy - store an auto-archive policy on the stream
@router.post("/streams/{stream_id}/archive-policy", response_model=ArchivePolicyRead)
def set_archive_policy(
    stream_id: str,
    body: ArchivePolicyRequest,
    actor: str = "system",
    principal: Principal = Depends(require_permission("edit")),
    db: Session = Depends(get_db),
):
    stream = _get_stream_or_404(stream_id, db, principal, "edit")

    policy: Dict[str, Any] = {}
    if body.max_age_seconds is not None:
        policy["max_age_seconds"] = body.max_age_seconds
    if body.max_records is not None:
        policy["max_records"] = body.max_records
    stream.archive_policy = policy

    db.add(
        models_action.AuditLog(
            id=uuid.uuid4().hex,
            actor=actor,
            event_type="stream.archive_policy.set",
            subject_type="stream",
            subject_id=stream_id,
            payload=dict(policy),
        )
    )
    db.commit()
    db.refresh(stream)
    return ArchivePolicyRead(
        stream_id=stream_id,
        max_age_seconds=policy.get("max_age_seconds"),
        max_records=policy.get("max_records"),
    )


# GET /streams/{id}/archive-policy - read the configured policy
@router.get("/streams/{stream_id}/archive-policy", response_model=ArchivePolicyRead)
def get_archive_policy(stream_id: str, principal: Principal = Depends(require_permission("view")), db: Session = Depends(get_db)):
    stream = _get_stream_or_404(stream_id, db, principal)
    policy = dict(stream.archive_policy or {})
    return ArchivePolicyRead(
        stream_id=stream_id,
        max_age_seconds=policy.get("max_age_seconds"),
        max_records=policy.get("max_records"),
    )


# POST /streams/{id}/apply-archive-policy - archive records exceeding the policy
@router.post("/streams/{stream_id}/apply-archive-policy", response_model=ApplyArchivePolicyResponse)
def apply_archive_policy(
    stream_id: str,
    body: ApplyArchivePolicyRequest,
    actor: str = "system",
    principal: Principal = Depends(require_permission("execute")),
    db: Session = Depends(get_db),
):
    """
    Mark live (non-archived) records that exceed the stream's archive policy as
    archived. Age-based archiving uses the deterministic `now` param (record.ts is
    older than now - max_age_seconds). Count-based archiving keeps the newest
    `max_records` live records and archives the rest. Idempotent: already-archived
    records are never re-counted.
    """
    stream = _get_stream_or_404(stream_id, db, principal, "execute")
    policy = dict(stream.archive_policy or {})
    now = body.now if body.now is not None else _now()

    live = (
        db.query(StreamRecord)
        .filter(StreamRecord.stream_id == stream_id, StreamRecord.archived == False)  # noqa: E712
        .order_by(StreamRecord.sequence.asc())
        .all()
    )

    to_archive: set = set()
    max_age = policy.get("max_age_seconds")
    if max_age is not None:
        cutoff = now - int(max_age)
        for r in live:
            if r.ts < cutoff:
                to_archive.add(r.id)

    max_records = policy.get("max_records")
    if max_records is not None:
        # Keep the newest max_records live records; archive older overflow.
        ordered = sorted(live, key=lambda r: r.sequence)
        overflow = len(ordered) - int(max_records)
        if overflow > 0:
            for r in ordered[:overflow]:
                to_archive.add(r.id)

    archived = 0
    for r in live:
        if r.id in to_archive:
            r.archived = True
            r.archived_at = now
            archived += 1

    remaining = len(live) - archived

    db.add(
        models_action.AuditLog(
            id=uuid.uuid4().hex,
            actor=actor,
            event_type="stream.archive_policy.applied",
            subject_type="stream",
            subject_id=stream_id,
            payload={"archived": archived, "remaining": remaining, "now": now, "policy": policy},
        )
    )
    db.commit()
    return ApplyArchivePolicyResponse(
        stream_id=stream_id, archived=archived, remaining=remaining, now=now
    )


# GET /streams/{id}/metrics - record throughput metrics over record timestamps
@router.get("/streams/{stream_id}/metrics", response_model=StreamMetricsRead)
def get_stream_metrics(stream_id: str, principal: Principal = Depends(require_permission("view")), db: Session = Depends(get_db)):
    _get_stream_or_404(stream_id, db, principal)

    rows = (
        db.query(StreamRecord)
        .filter(StreamRecord.stream_id == stream_id)
        .order_by(StreamRecord.ts.asc())
        .all()
    )
    count = len(rows)
    if count == 0:
        return StreamMetricsRead(
            stream_id=stream_id, record_count=0, first_ts=None, last_ts=None, records_per_second=0.0
        )

    first_ts = rows[0].ts
    last_ts = rows[-1].ts
    span = last_ts - first_ts
    if span > 0:
        rps = round(count / span, 6)
    else:
        # All records share one timestamp (or single record): undefined rate -> count.
        rps = float(count)

    return StreamMetricsRead(
        stream_id=stream_id,
        record_count=count,
        first_ts=first_ts,
        last_ts=last_ts,
        records_per_second=rps,
    )

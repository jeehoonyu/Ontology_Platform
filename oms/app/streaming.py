import time
import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import String, Integer, JSON, ForeignKey, Boolean
from sqlalchemy.orm import Mapped, mapped_column, Session, relationship

from .database import Base, get_db
from . import models, models_action

# ---------------------------------------------------------------------------
# SQLAlchemy ORM models
# ---------------------------------------------------------------------------

class Stream(Base):
    __tablename__ = "streams"

    id: Mapped[str] = mapped_column(String, primary_key=True, index=True)
    display_name: Mapped[str] = mapped_column(String)
    schema_: Mapped[dict] = mapped_column("schema", JSON, default=dict)
    retention_seconds: Mapped[int] = mapped_column(Integer, default=86400)
    # Auto-archive policy: {"max_age_seconds": int|None, "max_records": int|None}.
    # Empty dict means no policy configured (default for existing rows).
    archive_policy: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[int] = mapped_column(Integer)

    records: Mapped[list] = relationship("StreamRecord", back_populates="stream", cascade="all, delete-orphan")


class StreamRecord(Base):
    __tablename__ = "stream_records"

    id: Mapped[str] = mapped_column(String, primary_key=True, index=True)
    stream_id: Mapped[str] = mapped_column(String, ForeignKey("streams.id"), index=True)
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
    display_name: str
    schema_: Dict[str, Any] = Field(default_factory=dict, alias="schema")
    retention_seconds: int = 86400

    model_config = ConfigDict(populate_by_name=True)


class StreamRead(BaseModel):
    id: str
    display_name: str
    schema_: Dict[str, Any] = Field(alias="schema")
    retention_seconds: int
    created_at: int

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    @classmethod
    def from_orm_obj(cls, obj: Stream) -> "StreamRead":
        return cls(
            id=obj.id,
            display_name=obj.display_name,
            schema=obj.schema_,
            retention_seconds=obj.retention_seconds,
            created_at=obj.created_at,
        )


class StreamRecordRead(BaseModel):
    id: str
    stream_id: str
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


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

router = APIRouter(tags=["streaming"])


def _now() -> int:
    return int(time.time())


def _get_stream_or_404(stream_id: str, db: Session) -> Stream:
    stream = db.query(Stream).filter(Stream.id == stream_id).first()
    if not stream:
        raise HTTPException(status_code=404, detail=f"Stream '{stream_id}' not found")
    return stream


# POST /streams — create a stream
@router.post("/streams", response_model=StreamRead)
def create_stream(body: StreamCreate, db: Session = Depends(get_db)):
    stream_id = body.id or uuid.uuid4().hex
    existing = db.query(Stream).filter(Stream.id == stream_id).first()
    if existing:
        raise HTTPException(status_code=400, detail="Stream already exists")

    now = _now()
    db_stream = Stream(
        id=stream_id,
        display_name=body.display_name,
        schema_=body.schema_,
        retention_seconds=body.retention_seconds,
        created_at=now,
    )
    db.add(db_stream)
    db.commit()
    db.refresh(db_stream)
    return StreamRead.from_orm_obj(db_stream)


# GET /streams — list all streams
@router.get("/streams", response_model=List[StreamRead])
def list_streams(db: Session = Depends(get_db)):
    streams = db.query(Stream).order_by(Stream.created_at.desc()).all()
    return [StreamRead.from_orm_obj(s) for s in streams]


# GET /streams/{id} — get a single stream
@router.get("/streams/{stream_id}", response_model=StreamRead)
def get_stream(stream_id: str, db: Session = Depends(get_db)):
    stream = _get_stream_or_404(stream_id, db)
    return StreamRead.from_orm_obj(stream)


# POST /streams/{id}/publish — append records to the stream
@router.post("/streams/{stream_id}/publish", response_model=PublishResponse)
def publish_to_stream(
    stream_id: str,
    body: PublishRequest,
    db: Session = Depends(get_db),
):
    _get_stream_or_404(stream_id, db)

    now = _now()
    for record_payload in body.records:
        db.add(StreamRecord(
            id=uuid.uuid4().hex,
            stream_id=stream_id,
            payload=record_payload,
            ts=now,
            created_at=now,
        ))

    db.commit()
    return PublishResponse(published=len(body.records))


# GET /streams/{id}/records — retrieve recent records
@router.get("/streams/{stream_id}/records", response_model=List[StreamRecordRead])
def get_stream_records(
    stream_id: str,
    limit: int = Query(default=100, ge=1, le=10000),
    db: Session = Depends(get_db),
):
    _get_stream_or_404(stream_id, db)

    rows = (
        db.query(StreamRecord)
        .filter(StreamRecord.stream_id == stream_id)
        .order_by(StreamRecord.ts.desc(), StreamRecord.created_at.desc())
        .limit(limit)
        .all()
    )
    return rows


# POST /streams/{id}/archive — copy stream payloads into a DataAsset and log it
@router.post("/streams/{stream_id}/archive", response_model=ArchiveResponse)
def archive_stream(
    stream_id: str,
    body: ArchiveRequest,
    actor: str = "system",
    db: Session = Depends(get_db),
):
    _get_stream_or_404(stream_id, db)

    asset = db.query(models.DataAsset).filter(models.DataAsset.id == body.target_asset_id).first()
    if not asset:
        raise HTTPException(
            status_code=404,
            detail=f"DataAsset '{body.target_asset_id}' not found",
        )

    rows = (
        db.query(StreamRecord)
        .filter(StreamRecord.stream_id == stream_id)
        .order_by(StreamRecord.ts.asc())
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
    db.commit()
    return ArchiveResponse(archived=len(new_records))


# POST /streams/{id}/archive-policy — store an auto-archive policy on the stream
@router.post("/streams/{stream_id}/archive-policy", response_model=ArchivePolicyRead)
def set_archive_policy(
    stream_id: str,
    body: ArchivePolicyRequest,
    actor: str = "system",
    db: Session = Depends(get_db),
):
    stream = _get_stream_or_404(stream_id, db)

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


# GET /streams/{id}/archive-policy — read the configured policy
@router.get("/streams/{stream_id}/archive-policy", response_model=ArchivePolicyRead)
def get_archive_policy(stream_id: str, db: Session = Depends(get_db)):
    stream = _get_stream_or_404(stream_id, db)
    policy = dict(stream.archive_policy or {})
    return ArchivePolicyRead(
        stream_id=stream_id,
        max_age_seconds=policy.get("max_age_seconds"),
        max_records=policy.get("max_records"),
    )


# POST /streams/{id}/apply-archive-policy — archive records exceeding the policy
@router.post("/streams/{stream_id}/apply-archive-policy", response_model=ApplyArchivePolicyResponse)
def apply_archive_policy(
    stream_id: str,
    body: ApplyArchivePolicyRequest,
    actor: str = "system",
    db: Session = Depends(get_db),
):
    """
    Mark live (non-archived) records that exceed the stream's archive policy as
    archived. Age-based archiving uses the deterministic `now` param (record.ts is
    older than now - max_age_seconds). Count-based archiving keeps the newest
    `max_records` live records and archives the rest. Idempotent: already-archived
    records are never re-counted.
    """
    stream = _get_stream_or_404(stream_id, db)
    policy = dict(stream.archive_policy or {})
    now = body.now if body.now is not None else _now()

    live = (
        db.query(StreamRecord)
        .filter(StreamRecord.stream_id == stream_id, StreamRecord.archived == False)  # noqa: E712
        .order_by(StreamRecord.ts.asc(), StreamRecord.created_at.asc())
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
        ordered = sorted(live, key=lambda r: (r.ts, r.created_at))
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


# GET /streams/{id}/metrics — record throughput metrics over record timestamps
@router.get("/streams/{stream_id}/metrics", response_model=StreamMetricsRead)
def get_stream_metrics(stream_id: str, db: Session = Depends(get_db)):
    _get_stream_or_404(stream_id, db)

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

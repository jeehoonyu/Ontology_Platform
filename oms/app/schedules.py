import time
import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import Boolean, Integer, JSON, String
from sqlalchemy.orm import Mapped, mapped_column, Session

from . import models, models_action
from .database import Base, get_db

router = APIRouter(tags=["schedules"])


# ---------------------------------------------------------------------------
# SQLAlchemy Models
# ---------------------------------------------------------------------------

class Schedule(Base):
    """First-class schedule resource targeting pipelines, logic functions, or automations."""

    __tablename__ = "schedules"

    id: Mapped[str] = mapped_column(String, primary_key=True, index=True)
    display_name: Mapped[str] = mapped_column(String, nullable=False)
    target_type: Mapped[str] = mapped_column(String, nullable=False)  # pipeline/logic/automation
    target_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    trigger_type: Mapped[str] = mapped_column(String, nullable=False)  # cron/event
    cron: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    event_input: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True, default=None)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[int] = mapped_column(Integer, nullable=False)
    updated_at: Mapped[int] = mapped_column(Integer, nullable=False)


class Build(Base):
    """Execution record produced when a schedule triggers a target."""

    __tablename__ = "builds"

    id: Mapped[str] = mapped_column(String, primary_key=True, index=True)
    schedule_id: Mapped[Optional[str]] = mapped_column(String, nullable=True, index=True)
    target_type: Mapped[str] = mapped_column(String, nullable=False)
    target_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    status: Mapped[str] = mapped_column(String, nullable=False)  # queued/success/failed/ignored
    triggered_by: Mapped[str] = mapped_column(String, nullable=False, default="system")
    metrics: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[int] = mapped_column(Integer, nullable=False)
    completed_at: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)


# ---------------------------------------------------------------------------
# Pydantic Schemas
# ---------------------------------------------------------------------------

class ScheduleCreate(BaseModel):
    id: Optional[str] = None
    display_name: str
    target_type: str = Field(..., pattern="^(pipeline|logic|automation)$")
    target_id: str
    trigger_type: str = Field(..., pattern="^(cron|event)$")
    cron: Optional[str] = None
    event_input: Optional[Dict[str, Any]] = None
    enabled: bool = True


class ScheduleRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    display_name: str
    target_type: str
    target_id: str
    trigger_type: str
    cron: Optional[str]
    event_input: Optional[Dict[str, Any]]
    enabled: bool
    created_at: int
    updated_at: int


class ScheduleEnableRequest(BaseModel):
    enabled: bool


class BuildRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    schedule_id: Optional[str]
    target_type: str
    target_id: str
    status: str
    triggered_by: str
    metrics: Dict[str, Any]
    created_at: int
    completed_at: Optional[int]


class ScheduleRunRequest(BaseModel):
    """Evaluate the schedule's trigger against this context, then record a build.

    If the trigger evaluates FALSE, a build with status 'ignored' is recorded
    (instead of 'success'), mirroring Foundry's 'ignored' run outcome.
    """
    context: Dict[str, Any] = Field(default_factory=dict)


class ScheduleMetricsRead(BaseModel):
    schedule_id: str
    total: int
    success: int
    failed: int
    ignored: int
    last_run: Optional[int] = None
    last_status: Optional[str] = None


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

_VALID_TARGET_TYPES = {"pipeline", "logic", "automation"}
_VALID_TRIGGER_TYPES = {"cron", "event"}


def _now() -> int:
    return int(time.time())


def _append_audit(
    db: Session,
    *,
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


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("/schedules", response_model=ScheduleRead, status_code=201)
def create_schedule(body: ScheduleCreate, db: Session = Depends(get_db)) -> Schedule:
    """Create a new schedule resource."""
    schedule_id = body.id or uuid.uuid4().hex
    existing = db.query(Schedule).filter(Schedule.id == schedule_id).first()
    if existing:
        raise HTTPException(status_code=400, detail=f"Schedule '{schedule_id}' already exists")

    if body.trigger_type == "cron" and not body.cron:
        raise HTTPException(status_code=422, detail="cron expression required when trigger_type is 'cron'")

    now = _now()
    row = Schedule(
        id=schedule_id,
        display_name=body.display_name,
        target_type=body.target_type,
        target_id=body.target_id,
        trigger_type=body.trigger_type,
        cron=body.cron,
        event_input=body.event_input,
        enabled=body.enabled,
        created_at=now,
        updated_at=now,
    )
    db.add(row)
    _append_audit(
        db,
        actor="system",
        event_type="schedule.created",
        subject_type="schedule",
        subject_id=schedule_id,
        payload={"target_type": body.target_type, "target_id": body.target_id, "trigger_type": body.trigger_type},
    )
    db.commit()
    db.refresh(row)
    return row


@router.get("/schedules", response_model=List[ScheduleRead])
def list_schedules(db: Session = Depends(get_db)) -> List[Schedule]:
    """List all schedules ordered by creation time descending."""
    return db.query(Schedule).order_by(Schedule.created_at.desc()).all()


@router.get("/schedules/{schedule_id}", response_model=ScheduleRead)
def get_schedule(schedule_id: str, db: Session = Depends(get_db)) -> Schedule:
    """Retrieve a single schedule by ID."""
    row = db.query(Schedule).filter(Schedule.id == schedule_id).first()
    if not row:
        raise HTTPException(status_code=404, detail=f"Schedule '{schedule_id}' not found")
    return row


@router.post("/schedules/{schedule_id}/enable", response_model=ScheduleRead)
def set_schedule_enabled(
    schedule_id: str,
    body: ScheduleEnableRequest,
    db: Session = Depends(get_db),
) -> Schedule:
    """Enable or disable a schedule."""
    row = db.query(Schedule).filter(Schedule.id == schedule_id).first()
    if not row:
        raise HTTPException(status_code=404, detail=f"Schedule '{schedule_id}' not found")

    row.enabled = body.enabled
    row.updated_at = _now()
    _append_audit(
        db,
        actor="system",
        event_type="schedule.enabled_changed",
        subject_type="schedule",
        subject_id=schedule_id,
        payload={"enabled": body.enabled},
    )
    db.commit()
    db.refresh(row)
    return row


@router.post("/schedules/{schedule_id}/trigger", response_model=BuildRead, status_code=201)
def trigger_schedule(
    schedule_id: str,
    actor: str = "system",
    db: Session = Depends(get_db),
) -> Build:
    """Manually trigger a schedule, creating a build record with status 'success'."""
    row = db.query(Schedule).filter(Schedule.id == schedule_id).first()
    if not row:
        raise HTTPException(status_code=404, detail=f"Schedule '{schedule_id}' not found")

    build_id = uuid.uuid4().hex
    now = _now()
    build = Build(
        id=build_id,
        schedule_id=schedule_id,
        target_type=row.target_type,
        target_id=row.target_id,
        status="success",
        triggered_by=actor,
        metrics={"duration_ms": 0},
        created_at=now,
        completed_at=now,
    )
    db.add(build)
    _append_audit(
        db,
        actor=actor,
        event_type="schedule.triggered",
        subject_type="schedule",
        subject_id=schedule_id,
        payload={
            "build_id": build_id,
            "target_type": row.target_type,
            "target_id": row.target_id,
        },
    )
    db.commit()
    db.refresh(build)
    return build


@router.post("/schedules/{schedule_id}/run", response_model=BuildRead, status_code=201)
def run_schedule(
    schedule_id: str,
    body: ScheduleRunRequest,
    actor: str = "system",
    db: Session = Depends(get_db),
) -> Build:
    """
    Evaluate the schedule's trigger against the supplied context and record a
    build. If the trigger is satisfied the build status is 'success'; if the
    trigger evaluates FALSE the build is recorded with status 'IGNORED' (a
    distinct outcome from success/failed). This does not change the existing
    /trigger endpoint, which always records 'success'.
    """
    row = db.query(Schedule).filter(Schedule.id == schedule_id).first()
    if not row:
        raise HTTPException(status_code=404, detail=f"Schedule '{schedule_id}' not found")

    # Lazy import to avoid a top-level import cycle (schedules_ops imports schedules).
    from . import schedules_ops as _ops

    trigger = (row.event_input or {}).get("trigger") if isinstance(row.event_input, dict) else None
    if not trigger:
        if row.trigger_type == "cron":
            trigger = {"type": "time", "cron": row.cron or "* * * * *"}
        else:
            ev = (row.event_input or {}).get("event") if isinstance(row.event_input, dict) else row.target_id
            trigger = {"type": "event", "event": ev}

    # Manual run: ensure 'manual' triggers can fire unless caller overrode context.
    context = dict(body.context)
    context.setdefault("manual", True)

    result = _ops.evaluate_trigger(trigger, context)
    satisfied = bool(result.get("satisfied"))
    status = "success" if satisfied else "IGNORED"

    build_id = uuid.uuid4().hex
    now = _now()
    build = Build(
        id=build_id,
        schedule_id=schedule_id,
        target_type=row.target_type,
        target_id=row.target_id,
        status=status,
        triggered_by=actor,
        metrics={"duration_ms": 0, "satisfied": satisfied, "trigger": trigger},
        created_at=now,
        completed_at=now,
    )
    db.add(build)
    _append_audit(
        db,
        actor=actor,
        event_type="schedule.run",
        subject_type="schedule",
        subject_id=schedule_id,
        payload={"build_id": build_id, "status": status, "satisfied": satisfied},
    )
    db.commit()
    db.refresh(build)
    return build


@router.get("/schedules/{schedule_id}/metrics", response_model=ScheduleMetricsRead)
def get_schedule_metrics(schedule_id: str, db: Session = Depends(get_db)) -> ScheduleMetricsRead:
    """Aggregate build outcomes for a schedule by status, plus the last run."""
    row = db.query(Schedule).filter(Schedule.id == schedule_id).first()
    if not row:
        raise HTTPException(status_code=404, detail=f"Schedule '{schedule_id}' not found")

    builds = (
        db.query(Build)
        .filter(Build.schedule_id == schedule_id)
        .order_by(Build.created_at.desc())
        .all()
    )

    def _norm(s: str) -> str:
        return (s or "").lower()

    success = sum(1 for b in builds if _norm(b.status) == "success")
    failed = sum(1 for b in builds if _norm(b.status) == "failed")
    ignored = sum(1 for b in builds if _norm(b.status) == "ignored")

    last_run = builds[0].created_at if builds else None
    last_status = builds[0].status if builds else None

    return ScheduleMetricsRead(
        schedule_id=schedule_id,
        total=len(builds),
        success=success,
        failed=failed,
        ignored=ignored,
        last_run=last_run,
        last_status=last_status,
    )


@router.get("/builds", response_model=List[BuildRead])
def list_builds(
    target_id: Optional[str] = Query(default=None),
    db: Session = Depends(get_db),
) -> List[Build]:
    """List builds, optionally filtered by target_id."""
    query = db.query(Build)
    if target_id:
        query = query.filter(Build.target_id == target_id)
    return query.order_by(Build.created_at.desc()).all()

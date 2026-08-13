"""Authenticated recovery markers for isolated RPO and RTO rehearsals.

The endpoints live below ``/health`` so a restored API can be measured before
an interactive OIDC session exists. They are not public health checks: every
request requires a separate high-entropy bearer secret, and the surface is
disabled when that secret is not configured.
"""
from __future__ import annotations

import hmac
import os
import re
import time
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.orm import Session

from .database import get_db
from .event_outbox import EventOutbox
from .pilot_evidence import current_migration_head

router = APIRouter(prefix="/health/pilot-recovery", tags=["pilot_recovery"])

RUN_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
MIN_PRODUCTION_TOKEN_LENGTH = 32


class RecoveryMarkWrite(BaseModel):
    run_id: str
    sequence: int = Field(ge=1)
    written_at: int = Field(ge=1)
    project_id: str = "default"
    migration_head: str


class RecoveryWriteProbe(BaseModel):
    run_id: str
    project_id: str = "default"
    migration_head: str


def _configured_token() -> str:
    token = os.getenv("PILOT_RECOVERY_TOKEN", "").strip()
    if not token:
        raise HTTPException(status_code=404, detail="Recovery probe is disabled")
    if (
        os.getenv("APP_ENV", "development").strip().lower() in {"production", "prod"}
        and len(token) < MIN_PRODUCTION_TOKEN_LENGTH
    ):
        raise HTTPException(status_code=503, detail="Recovery probe token is not production-safe")
    return token


def require_recovery_token(authorization: Optional[str] = Header(default=None)) -> None:
    configured = _configured_token()
    supplied = ""
    if authorization and authorization.startswith("Bearer "):
        supplied = authorization[7:]
    if not supplied or not hmac.compare_digest(supplied, configured):
        raise HTTPException(status_code=401, detail="Invalid recovery probe credential")


def _validate_identity(run_id: str, project_id: str, migration_head: str) -> None:
    if not RUN_ID_PATTERN.fullmatch(run_id):
        raise HTTPException(status_code=422, detail="run_id contains unsupported characters")
    if not project_id or len(project_id) > 128:
        raise HTTPException(status_code=422, detail="project_id is invalid")
    if not migration_head or len(migration_head) > 128:
        raise HTTPException(status_code=422, detail="migration_head is invalid")


def _database_head(db: Session) -> Optional[str]:
    try:
        return db.execute(text("SELECT version_num FROM alembic_version LIMIT 1")).scalar_one_or_none()
    except Exception:
        return None


def _response(row: EventOutbox, db: Session) -> dict:
    payload = row.payload or {}
    return {
        "run_id": row.aggregate_id,
        "project_id": row.project_id,
        "kind": payload.get("kind"),
        "sequence": payload.get("sequence"),
        "written_at": payload.get("written_at"),
        "migration_head": payload.get("migration_head"),
        "database_migration_head": _database_head(db),
        "runtime_migration_head": current_migration_head(),
    }


@router.post("/marks", dependencies=[Depends(require_recovery_token)])
def write_recovery_mark(body: RecoveryMarkWrite, db: Session = Depends(get_db)):
    _validate_identity(body.run_id, body.project_id, body.migration_head)
    identifier = f"pilot-recovery-mark:{body.run_id}:{body.sequence:012d}"
    existing = db.get(EventOutbox, identifier)
    if existing:
        expected = {
            "kind": "mark", "sequence": body.sequence,
            "written_at": body.written_at, "migration_head": body.migration_head,
        }
        if (
            existing.aggregate_id != body.run_id
            or existing.project_id != body.project_id
            or existing.event_type != "pilot.recovery.mark"
            or existing.payload != expected
        ):
            raise HTTPException(status_code=409, detail="Recovery mark identity was reused with different data")
        return _response(existing, db)
    now = int(time.time())
    row = EventOutbox(
        id=identifier,
        project_id=body.project_id,
        topic="pilot.recovery",
        event_type="pilot.recovery.mark",
        aggregate_type="pilot_recovery_run",
        aggregate_id=body.run_id,
        actor="pilot-recovery-observer",
        payload={
            "kind": "mark", "sequence": body.sequence,
            "written_at": body.written_at, "migration_head": body.migration_head,
        },
        headers={"internal": True},
        idempotency_key=identifier,
        status="PENDING",
        attempts=0,
        max_attempts=5,
        available_at=now,
        created_at=now,
        updated_at=now,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _response(row, db)


@router.get("/marks/{run_id}/highest", dependencies=[Depends(require_recovery_token)])
def highest_recovery_mark(run_id: str, project_id: str = "default", db: Session = Depends(get_db)):
    _validate_identity(run_id, project_id, current_migration_head())
    row = (
        db.query(EventOutbox)
        .filter(
            EventOutbox.aggregate_id == run_id,
            EventOutbox.project_id == project_id,
            EventOutbox.event_type == "pilot.recovery.mark",
        )
        .order_by(EventOutbox.id.desc())
        .first()
    )
    if not row:
        raise HTTPException(status_code=404, detail="No recovery mark survived")
    return _response(row, db)


@router.post("/write-probes", dependencies=[Depends(require_recovery_token)])
def write_recovery_probe(body: RecoveryWriteProbe, db: Session = Depends(get_db)):
    _validate_identity(body.run_id, body.project_id, body.migration_head)
    identifier = f"pilot-recovery-probe:{body.run_id}:000000000001"
    existing = db.get(EventOutbox, identifier)
    if existing:
        payload = existing.payload or {}
        if (
            existing.project_id != body.project_id
            or existing.aggregate_id != body.run_id
            or existing.event_type != "pilot.recovery.write_probe"
            or payload.get("migration_head") != body.migration_head
        ):
            raise HTTPException(status_code=409, detail="Recovery probe identity was reused with different data")
        return _response(existing, db)
    now = int(time.time())
    row = EventOutbox(
        id=identifier,
        project_id=body.project_id,
        topic="pilot.recovery",
        event_type="pilot.recovery.write_probe",
        aggregate_type="pilot_recovery_run",
        aggregate_id=body.run_id,
        actor="pilot-recovery-observer",
        payload={
            "kind": "write_probe", "sequence": 1,
            "written_at": now, "migration_head": body.migration_head,
        },
        headers={"internal": True},
        idempotency_key=identifier,
        status="PENDING",
        attempts=0,
        max_attempts=1,
        available_at=now,
        created_at=now,
        updated_at=now,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _response(row, db)

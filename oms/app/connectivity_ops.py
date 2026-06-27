"""
Data Connection — incremental sync with cursor high-water-mark
(deep-fidelity pass 11). Based on documented incremental sync semantics: an
incremental sync pulls only rows whose cursor field is greater than the last seen
value, appends them, and advances the stored cursor. Additive; deterministic.
"""
import time
import uuid
from typing import Optional, List, Any, Dict

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import String, Integer, JSON
from sqlalchemy.orm import Mapped, mapped_column, Session
from pydantic import BaseModel, Field

from .database import Base, get_db
from . import models, models_action, connectivity as _conn

router = APIRouter(tags=["connectivity_ops"])


def _now() -> int:
    return int(time.time())


class SyncCursorState(Base):
    __tablename__ = "sync_cursor_state"
    sync_id: Mapped[str] = mapped_column(String, primary_key=True, index=True)
    cursor_field: Mapped[str] = mapped_column(String)
    last_value: Mapped[dict] = mapped_column(JSON, default=dict)  # {"value": ...}
    runs: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[int] = mapped_column(Integer)


class IncrementalRunRequest(BaseModel):
    batch: List[Dict[str, Any]]          # records "pulled" from the source this run
    cursor_field: Optional[str] = None   # overrides the sync's cursor_field


@router.post("/connections/syncs/{sync_id}/run-incremental")
def run_incremental(sync_id: str, body: IncrementalRunRequest, db: Session = Depends(get_db)):
    sync = db.get(_conn.ConnectionSync, sync_id)
    if not sync:
        raise HTTPException(status_code=404, detail=f"Sync '{sync_id}' not found")
    cursor_field = body.cursor_field or sync.cursor_field
    if not cursor_field:
        raise HTTPException(status_code=422, detail="incremental sync requires a cursor_field")

    state = db.get(SyncCursorState, sync_id)
    last = state.last_value.get("value") if (state and isinstance(state.last_value, dict)) else None

    def _gt(a, b):
        if b is None:
            return True
        try:
            return a > b
        except TypeError:
            return str(a) > str(b)

    new_rows = [r for r in body.batch if cursor_field in r and _gt(r[cursor_field], last)]
    skipped = len(body.batch) - len(new_rows)

    target = db.get(models.DataAsset, sync.target_asset_id)
    if not target:
        raise HTTPException(status_code=404, detail=f"Target dataset '{sync.target_asset_id}' not found")
    target.records = (target.records or []) + new_rows
    target.updated_at = _now()

    new_cursor = last
    for r in new_rows:
        if _gt(r[cursor_field], new_cursor):
            new_cursor = r[cursor_field]

    if state:
        state.last_value = {"value": new_cursor}
        state.cursor_field = cursor_field
        state.runs += 1
        state.updated_at = _now()
    else:
        state = SyncCursorState(sync_id=sync_id, cursor_field=cursor_field,
                                last_value={"value": new_cursor}, runs=1, updated_at=_now())
        db.add(state)

    db.add(models_action.AuditLog(id=uuid.uuid4().hex, actor="system", event_type="connection.sync.incremental",
                                  subject_type="sync", subject_id=sync_id,
                                  payload={"pulled": len(new_rows), "skipped": skipped, "cursor": new_cursor}))
    db.commit()
    return {"sync_id": sync_id, "cursor_field": cursor_field, "pulled": len(new_rows),
            "skipped_not_newer": skipped, "previous_cursor": last, "new_cursor": new_cursor,
            "target_row_count": len(target.records)}


@router.get("/connections/syncs/{sync_id}/cursor")
def get_cursor(sync_id: str, db: Session = Depends(get_db)):
    state = db.get(SyncCursorState, sync_id)
    if not state:
        return {"sync_id": sync_id, "cursor_field": None, "last_value": None, "runs": 0}
    return {"sync_id": sync_id, "cursor_field": state.cursor_field,
            "last_value": state.last_value.get("value"), "runs": state.runs}

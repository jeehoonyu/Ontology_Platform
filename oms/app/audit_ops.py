"""
audit_ops.py — Read-only search and views over the control-plane audit log.

This module READS the existing ``models_action.AuditLog`` table (append-only
control plane log). It creates NO new tables and performs NO writes.

Endpoints:
    GET /audit-logs/search      — filter audit rows by actor / event_type /
                                  subject_type / time-range / category / result,
                                  returned newest-first.
    GET /audit-logs/action-log  — convenience view: only events whose
                                  event_type starts with 'action', newest-first.

Two derived dimensions are computed on the fly from each row (they are not
stored columns):

    category — bucketed from the ``event_type`` prefix:
        security.*                 -> "security"
        ontology.*                 -> "ontology"
        data.* / pipeline.*        -> "data"
        admin.*                    -> "admin"
        aip.*                      -> "aip"
        everything else            -> "other"

    result  — "failure" when the event_type ends in '.failed' OR the payload
              carries a truthy ``error`` (also ``failed``/``success: false``);
              otherwise "success".
"""

from typing import Optional, List, Dict, Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from .database import get_db
from . import models_action

router = APIRouter(tags=["audit-ops"])


# ---------------------------------------------------------------------------
# Derivation helpers
# ---------------------------------------------------------------------------

VALID_CATEGORIES = {"security", "ontology", "data", "admin", "aip", "other"}
VALID_RESULTS = {"success", "failure"}


def derive_category(event_type: Optional[str]) -> str:
    """Bucket an event_type into a coarse category from its dotted prefix."""
    et = (event_type or "").lower()
    prefix = et.split(".", 1)[0] if et else ""
    if prefix == "security":
        return "security"
    if prefix == "ontology":
        return "ontology"
    if prefix in ("data", "pipeline"):
        return "data"
    if prefix == "admin":
        return "admin"
    if prefix == "aip":
        return "aip"
    return "other"


def derive_result(event_type: Optional[str], payload: Optional[Dict[str, Any]]) -> str:
    """
    Classify an audit row as 'success' or 'failure'.

    Failure when the event_type ends in '.failed'/'.failure'/'.error', or the
    payload signals an error (truthy ``error``, truthy ``failed``, or an explicit
    ``success: false`` / ``result: "failure"``). Otherwise success.
    """
    et = (event_type or "").lower()
    if et.endswith((".failed", ".failure", ".error")):
        return "failure"

    if isinstance(payload, dict):
        if payload.get("error"):
            return "failure"
        if payload.get("failed"):
            return "failure"
        if payload.get("success") is False:
            return "failure"
        res = payload.get("result")
        if isinstance(res, str) and res.lower() in ("failure", "failed", "error"):
            return "failure"

    return "success"


# ---------------------------------------------------------------------------
# Pydantic schemas (read-only)
# ---------------------------------------------------------------------------

class AuditLogRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    actor: str
    event_type: str
    subject_type: str
    subject_id: str
    payload: Optional[Dict[str, Any]] = None
    created_at: Optional[int] = None
    # derived (not stored on the row)
    category: str
    result: str


class AuditSearchResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    count: int
    results: List[AuditLogRead]


def _to_read(row: "models_action.AuditLog") -> AuditLogRead:
    """Materialize a stored AuditLog row into the read model with derived fields."""
    return AuditLogRead(
        id=row.id,
        actor=row.actor,
        event_type=row.event_type,
        subject_type=row.subject_type,
        subject_id=row.subject_id,
        payload=row.payload,
        created_at=row.created_at,
        category=derive_category(row.event_type),
        result=derive_result(row.event_type, row.payload),
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/audit-logs/search", response_model=AuditSearchResponse)
def search_audit_logs(
    actor: Optional[str] = Query(None, description="Exact actor match"),
    event_type: Optional[str] = Query(None, description="Exact event_type match"),
    subject_type: Optional[str] = Query(None, description="Exact subject_type match"),
    start_ts: Optional[int] = Query(None, description="Inclusive lower bound on created_at"),
    end_ts: Optional[int] = Query(None, description="Inclusive upper bound on created_at"),
    category: Optional[str] = Query(None, description="Derived category filter"),
    result: Optional[str] = Query(None, description="Derived result filter (success|failure)"),
    limit: int = Query(100, ge=1, le=1000, description="Maximum rows returned"),
    db: Session = Depends(get_db),
) -> AuditSearchResponse:
    """
    Search the append-only audit log. All filters are AND-combined. Column
    filters (actor / event_type / subject_type / time range) are pushed down to
    SQL; the derived ``category`` and ``result`` filters are applied in Python
    because they are computed, not stored. Rows are returned newest-first by
    ``created_at`` (ties broken by id for determinism).
    """
    q = db.query(models_action.AuditLog)

    if actor is not None:
        q = q.filter(models_action.AuditLog.actor == actor)
    if event_type is not None:
        q = q.filter(models_action.AuditLog.event_type == event_type)
    if subject_type is not None:
        q = q.filter(models_action.AuditLog.subject_type == subject_type)
    if start_ts is not None:
        q = q.filter(models_action.AuditLog.created_at >= start_ts)
    if end_ts is not None:
        q = q.filter(models_action.AuditLog.created_at <= end_ts)

    # Newest-first; created_at may be NULL for unflushed defaults, so order by
    # it descending with id as a stable secondary key.
    q = q.order_by(
        models_action.AuditLog.created_at.desc(),
        models_action.AuditLog.id.desc(),
    )

    # Normalize derived filters (case-insensitive, ignore unknown values rather
    # than 500-ing — keeps the read endpoint forgiving).
    cat_filter = category.lower() if isinstance(category, str) else None
    res_filter = result.lower() if isinstance(result, str) else None

    out: List[AuditLogRead] = []
    for row in q.all():
        read = _to_read(row)
        if cat_filter is not None and read.category != cat_filter:
            continue
        if res_filter is not None and read.result != res_filter:
            continue
        out.append(read)
        if len(out) >= limit:
            break

    return AuditSearchResponse(count=len(out), results=out)


@router.get("/audit-logs/action-log", response_model=AuditSearchResponse)
def action_log(
    limit: int = Query(100, ge=1, le=1000, description="Maximum rows returned"),
    db: Session = Depends(get_db),
) -> AuditSearchResponse:
    """
    Convenience view over action-oriented audit events: only rows whose
    ``event_type`` begins with 'action' (e.g. 'action.executed',
    'action.approval.requested'). Returned newest-first.
    """
    q = (
        db.query(models_action.AuditLog)
        .filter(models_action.AuditLog.event_type.like("action%"))
        .order_by(
            models_action.AuditLog.created_at.desc(),
            models_action.AuditLog.id.desc(),
        )
    )

    out: List[AuditLogRead] = []
    for row in q.all():
        out.append(_to_read(row))
        if len(out) >= limit:
            break

    return AuditSearchResponse(count=len(out), results=out)

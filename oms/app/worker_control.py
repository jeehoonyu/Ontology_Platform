"""Worker fleet registration, queue policy, and fair dispatch controls."""
from __future__ import annotations

import time
import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import Boolean, Integer, JSON, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, Session, mapped_column

from . import tenancy
from .database import Base, get_db
from .production_auth import Principal, require_permission

router = APIRouter(tags=["worker_control"])


def _now() -> int:
    return int(time.time())


def _organization_id(principal: Principal) -> str:
    return principal.organization_id or "local"


class RuntimeWorker(Base):
    __tablename__ = "runtime_workers"
    __table_args__ = (UniqueConstraint("organization_id", "worker_name", name="uq_runtime_worker_org_name"),)

    id: Mapped[str] = mapped_column(String, primary_key=True)
    organization_id: Mapped[str] = mapped_column(String, index=True)
    worker_name: Mapped[str] = mapped_column(String, index=True)
    principal_id: Mapped[str] = mapped_column(String, index=True)
    project_id: Mapped[Optional[str]] = mapped_column(String, nullable=True, index=True)
    status: Mapped[str] = mapped_column(String, default="ACTIVE", index=True)
    supported_job_types: Mapped[list] = mapped_column(JSON, default=list)
    max_concurrency: Mapped[int] = mapped_column(Integer, default=1)
    labels: Mapped[dict] = mapped_column(JSON, default=dict)
    started_at: Mapped[int] = mapped_column(Integer)
    heartbeat_at: Mapped[int] = mapped_column(Integer, index=True)
    last_claimed_at: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    drain_requested_at: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)


class RuntimeQueuePolicy(Base):
    __tablename__ = "runtime_queue_policies"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    project_id: Mapped[str] = mapped_column(String, unique=True, index=True)
    weight: Mapped[int] = mapped_column(Integer, default=1)
    max_concurrency: Mapped[int] = mapped_column(Integer, default=10)
    paused: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_by: Mapped[str] = mapped_column(String)
    created_at: Mapped[int] = mapped_column(Integer)
    updated_at: Mapped[int] = mapped_column(Integer)


class WorkerRegistration(BaseModel):
    project_id: Optional[str] = None
    supported_job_types: List[str] = Field(default_factory=list, max_length=100)
    max_concurrency: int = Field(default=1, ge=1, le=100)
    labels: Dict[str, str] = Field(default_factory=dict)


class WorkerHeartbeat(BaseModel):
    labels: Optional[Dict[str, str]] = None


class QueuePolicyUpsert(BaseModel):
    weight: int = Field(default=1, ge=1, le=100)
    max_concurrency: int = Field(default=10, ge=1, le=1000)
    paused: bool = False


def _worker_query(db: Session, principal: Principal, worker_name: str):
    return db.query(RuntimeWorker).filter(
        RuntimeWorker.organization_id == _organization_id(principal),
        RuntimeWorker.worker_name == worker_name,
    )


def registered_worker(db: Session, principal: Principal, worker_name: str) -> Optional[RuntimeWorker]:
    return _worker_query(db, principal, worker_name).first()


def effective_worker_job_types(
    db: Session,
    principal: Principal,
    worker_name: str,
    domain_job_types: List[str],
) -> List[str]:
    """Constrain a domain adapter to the registered worker capability subset."""
    worker = registered_worker(db, principal, worker_name)
    if not worker:
        return list(domain_job_types)
    registered = {str(value) for value in (worker.supported_job_types or [])}
    effective = [job_type for job_type in domain_job_types if job_type in registered]
    if not effective:
        raise HTTPException(status_code=403, detail="Worker has no capability for this execution domain")
    return effective


def worker_claim_constraints(
    db: Session,
    principal: Principal,
    worker_name: str,
    requested_job_types: List[str],
    requested_project_id: Optional[str],
) -> Dict[str, Any]:
    """Return enforced worker scope while preserving legacy unregistered workers."""
    worker_query = _worker_query(db, principal, worker_name)
    if db.get_bind().dialect.name == "postgresql":
        worker_query = worker_query.with_for_update()
    worker = worker_query.first()
    if not worker:
        return {
            "worker": None,
            "project_id": requested_project_id,
            "job_types": requested_job_types,
            "capacity_available": True,
        }
    if worker.status != "ACTIVE":
        raise HTTPException(status_code=409, detail={"message": "Worker is not accepting jobs", "status": worker.status})
    if requested_project_id and worker.project_id and requested_project_id != worker.project_id:
        raise HTTPException(status_code=403, detail="Worker is registered to a different project")
    project_id = worker.project_id or requested_project_id
    registered_types = set(str(value) for value in (worker.supported_job_types or []))
    requested_types = set(requested_job_types)
    if registered_types and requested_types and not requested_types.issubset(registered_types):
        raise HTTPException(status_code=403, detail="Requested job type is outside worker capabilities")
    job_types = sorted(requested_types or registered_types)

    from .platform_runtime import PlatformJob, PlatformJobLease
    active_query = db.query(PlatformJobLease).join(PlatformJob, PlatformJob.id == PlatformJobLease.job_id).filter(
        PlatformJobLease.worker_id == worker_name,
        PlatformJob.status == "RUNNING",
    )
    accessible = tenancy.accessible_project_ids(db, principal, "execute")
    if accessible is not None:
        active_query = active_query.filter(PlatformJob.project_id.in_(accessible))
    if project_id:
        active_query = active_query.filter(PlatformJob.project_id == project_id)
    return {
        "worker": worker,
        "project_id": project_id,
        "job_types": job_types,
        "capacity_available": active_query.count() < worker.max_concurrency,
    }


def rank_candidates(db: Session, candidates: List[Any]) -> List[Any]:
    """Weighted fair ordering across projects, then priority ordering within a project."""
    if not candidates:
        return []
    from .platform_runtime import PlatformJob, PlatformJobEvent, PlatformJobLease, _execution

    project_ids = sorted({row.project_id for row in candidates})
    policies = {
        row.project_id: row
        for row in db.query(RuntimeQueuePolicy).filter(RuntimeQueuePolicy.project_id.in_(project_ids)).all()
    }
    active_counts = dict(
        db.query(PlatformJob.project_id, func.count(PlatformJobLease.id))
        .join(PlatformJobLease, PlatformJobLease.job_id == PlatformJob.id)
        .filter(PlatformJob.project_id.in_(project_ids), PlatformJob.status == "RUNNING")
        .group_by(PlatformJob.project_id).all()
    )
    dispatch_counts = dict(
        db.query(PlatformJob.project_id, func.count(PlatformJobEvent.id))
        .join(PlatformJobEvent, PlatformJobEvent.job_id == PlatformJob.id)
        .filter(PlatformJob.project_id.in_(project_ids), PlatformJobEvent.event_type == "job.claimed")
        .group_by(PlatformJob.project_id).all()
    )

    groups: Dict[str, List[Any]] = {}
    for row in candidates:
        policy = policies.get(row.project_id)
        if policy and (policy.paused or active_counts.get(row.project_id, 0) >= policy.max_concurrency):
            continue
        groups.setdefault(row.project_id, []).append(row)
    for rows in groups.values():
        rows.sort(key=lambda row: (-int(_execution(row).get("priority", 50)), row.created_at, row.id))

    ordered: List[Any] = []
    project_order = sorted(
        groups,
        key=lambda project_id: (
            dispatch_counts.get(project_id, 0) / max(1, (policies.get(project_id).weight if policies.get(project_id) else 1)),
            project_id,
        ),
    )
    while project_order:
        next_round: List[str] = []
        for project_id in project_order:
            rows = groups[project_id]
            if rows:
                ordered.append(rows.pop(0))
            if rows:
                next_round.append(project_id)
        project_order = next_round
    return ordered


def queue_accepts_claim(db: Session, project_id: str) -> bool:
    """Serialize project admission when a queue policy defines a hard limit."""
    from .platform_runtime import PlatformJob, PlatformJobLease

    query = db.query(RuntimeQueuePolicy).filter(RuntimeQueuePolicy.project_id == project_id)
    if db.get_bind().dialect.name == "postgresql":
        query = query.with_for_update()
    policy = query.first()
    if not policy:
        return True
    if policy.paused:
        return False
    active = (
        db.query(PlatformJobLease)
        .join(PlatformJob, PlatformJob.id == PlatformJobLease.job_id)
        .filter(PlatformJob.project_id == project_id, PlatformJob.status == "RUNNING")
        .count()
    )
    return active < policy.max_concurrency


def record_worker_claim(worker: Optional[RuntimeWorker]) -> None:
    if worker:
        worker.heartbeat_at = worker.last_claimed_at = _now()


def _audit_control(db: Session, principal: Principal, event_type: str, subject_type: str, subject_id: str, payload: Dict[str, Any]) -> None:
    from .platform_runtime import _audit
    _audit(db, principal.id, event_type, subject_type, subject_id, payload)


def _worker_dict(db: Session, row: RuntimeWorker, principal: Principal) -> Dict[str, Any]:
    from .platform_runtime import PlatformJob, PlatformJobLease
    query = db.query(PlatformJobLease).join(PlatformJob, PlatformJob.id == PlatformJobLease.job_id).filter(
        PlatformJobLease.worker_id == row.worker_name,
        PlatformJob.status == "RUNNING",
    )
    if row.project_id:
        query = query.filter(PlatformJob.project_id == row.project_id)
    accessible = tenancy.accessible_project_ids(db, principal)
    if accessible is not None:
        query = query.filter(PlatformJob.project_id.in_(accessible))
    active = query.count()
    effective_status = row.status
    if effective_status == "ACTIVE" and row.heartbeat_at < _now() - 120:
        effective_status = "OFFLINE"
    return {
        "id": row.id,
        "worker_name": row.worker_name,
        "organization_id": row.organization_id,
        "project_id": row.project_id,
        "principal_id": row.principal_id,
        "status": effective_status,
        "configured_status": row.status,
        "supported_job_types": row.supported_job_types or [],
        "max_concurrency": row.max_concurrency,
        "active_jobs": active,
        "available_slots": max(0, row.max_concurrency - active),
        "labels": row.labels or {},
        "started_at": row.started_at,
        "heartbeat_at": row.heartbeat_at,
        "last_claimed_at": row.last_claimed_at,
        "drain_requested_at": row.drain_requested_at,
    }


def _policy_dict(row: RuntimeQueuePolicy) -> Dict[str, Any]:
    return {
        "id": row.id,
        "project_id": row.project_id,
        "weight": row.weight,
        "max_concurrency": row.max_concurrency,
        "paused": row.paused,
        "updated_by": row.updated_by,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


@router.put("/runtime/workers/{worker_name}")
def register_worker(worker_name: str, body: WorkerRegistration, principal: Principal = Depends(require_permission("execute")), db: Session = Depends(get_db)):
    if body.project_id:
        tenancy.assert_project_permission(db, principal, body.project_id, "execute")
    row = registered_worker(db, principal, worker_name)
    now = _now()
    if not row:
        row = RuntimeWorker(
            id=f"worker_{uuid.uuid4().hex}", organization_id=_organization_id(principal), worker_name=worker_name,
            principal_id=principal.id, project_id=body.project_id, status="ACTIVE",
            supported_job_types=body.supported_job_types, max_concurrency=body.max_concurrency,
            labels=body.labels, started_at=now, heartbeat_at=now,
        )
        db.add(row)
    else:
        if row.principal_id != principal.id and "administer" not in principal.permissions and "*" not in principal.permissions:
            raise HTTPException(status_code=403, detail="Worker is owned by another principal")
        row.principal_id = principal.id
        row.project_id = body.project_id
        row.status = "ACTIVE"
        row.supported_job_types = body.supported_job_types
        row.max_concurrency = body.max_concurrency
        row.labels = body.labels
        row.heartbeat_at = now
        row.drain_requested_at = None
    _audit_control(db, principal, "runtime.worker.registered", "runtime_worker", row.id, {
        "worker_name": worker_name, "project_id": body.project_id, "max_concurrency": body.max_concurrency,
        "supported_job_types": body.supported_job_types,
    })
    db.commit()
    return _worker_dict(db, row, principal)


@router.post("/runtime/workers/{worker_name}/heartbeat")
def heartbeat_worker(worker_name: str, body: WorkerHeartbeat, principal: Principal = Depends(require_permission("execute")), db: Session = Depends(get_db)):
    row = registered_worker(db, principal, worker_name)
    if not row:
        raise HTTPException(status_code=404, detail="Worker is not registered")
    if row.principal_id != principal.id and "administer" not in principal.permissions and "*" not in principal.permissions:
        raise HTTPException(status_code=403, detail="Worker is owned by another principal")
    row.heartbeat_at = _now()
    if body.labels is not None:
        row.labels = body.labels
    db.commit()
    return _worker_dict(db, row, principal)


@router.post("/runtime/workers/{worker_name}/drain")
def drain_worker(worker_name: str, principal: Principal = Depends(require_permission("execute")), db: Session = Depends(get_db)):
    row = registered_worker(db, principal, worker_name)
    if not row:
        raise HTTPException(status_code=404, detail="Worker is not registered")
    if row.principal_id != principal.id and "administer" not in principal.permissions and "*" not in principal.permissions:
        raise HTTPException(status_code=403, detail="Worker is owned by another principal")
    row.status = "DRAINING"
    row.drain_requested_at = row.heartbeat_at = _now()
    _audit_control(db, principal, "runtime.worker.draining", "runtime_worker", row.id, {"worker_name": worker_name, "project_id": row.project_id})
    db.commit()
    return _worker_dict(db, row, principal)


@router.post("/runtime/workers/{worker_name}/resume")
def resume_worker(worker_name: str, principal: Principal = Depends(require_permission("execute")), db: Session = Depends(get_db)):
    row = registered_worker(db, principal, worker_name)
    if not row:
        raise HTTPException(status_code=404, detail="Worker is not registered")
    if row.principal_id != principal.id and "administer" not in principal.permissions and "*" not in principal.permissions:
        raise HTTPException(status_code=403, detail="Worker is owned by another principal")
    row.status = "ACTIVE"
    row.drain_requested_at = None
    row.heartbeat_at = _now()
    _audit_control(db, principal, "runtime.worker.resumed", "runtime_worker", row.id, {"worker_name": worker_name, "project_id": row.project_id})
    db.commit()
    return _worker_dict(db, row, principal)


@router.get("/runtime/workers")
def list_workers(project_id: Optional[str] = None, principal: Principal = Depends(require_permission("view")), db: Session = Depends(get_db)):
    if project_id:
        tenancy.assert_project_permission(db, principal, project_id, "view")
    query = db.query(RuntimeWorker).filter(RuntimeWorker.organization_id == _organization_id(principal))
    if project_id:
        query = query.filter((RuntimeWorker.project_id == project_id) | (RuntimeWorker.project_id.is_(None)))
    return [_worker_dict(db, row, principal) for row in query.order_by(RuntimeWorker.worker_name).all()]


@router.put("/runtime/queues/{project_id}")
def upsert_queue_policy(project_id: str, body: QueuePolicyUpsert, principal: Principal = Depends(require_permission("administer")), db: Session = Depends(get_db)):
    tenancy.assert_project_permission(db, principal, project_id, "administer")
    row = db.query(RuntimeQueuePolicy).filter(RuntimeQueuePolicy.project_id == project_id).first()
    now = _now()
    if not row:
        row = RuntimeQueuePolicy(id=f"queue_{uuid.uuid4().hex}", project_id=project_id, created_at=now, updated_at=now, updated_by=principal.id)
        db.add(row)
    row.weight = body.weight
    row.max_concurrency = body.max_concurrency
    row.paused = body.paused
    row.updated_by = principal.id
    row.updated_at = now
    _audit_control(db, principal, "runtime.queue_policy.updated", "runtime_queue_policy", row.id, {
        "project_id": project_id, "weight": body.weight, "max_concurrency": body.max_concurrency, "paused": body.paused,
    })
    db.commit()
    return _policy_dict(row)


@router.get("/runtime/queues")
def list_queue_policies(project_id: Optional[str] = None, principal: Principal = Depends(require_permission("view")), db: Session = Depends(get_db)):
    query = db.query(RuntimeQueuePolicy)
    if project_id:
        tenancy.assert_project_permission(db, principal, project_id, "view")
        query = query.filter(RuntimeQueuePolicy.project_id == project_id)
    else:
        accessible = tenancy.accessible_project_ids(db, principal)
        if accessible is not None:
            query = query.filter(RuntimeQueuePolicy.project_id.in_(accessible))
    return [_policy_dict(row) for row in query.order_by(RuntimeQueuePolicy.project_id).all()]


@router.get("/ui-state/worker-fleet")
def worker_fleet_ui_state(project_id: Optional[str] = None, principal: Principal = Depends(require_permission("view")), db: Session = Depends(get_db)):
    workers = list_workers(project_id, principal, db)
    policies = list_queue_policies(project_id, principal, db)
    return {
        "summary": {
            "workers": len(workers),
            "active": sum(1 for row in workers if row["status"] == "ACTIVE"),
            "draining": sum(1 for row in workers if row["status"] == "DRAINING"),
            "offline": sum(1 for row in workers if row["status"] == "OFFLINE"),
            "active_jobs": sum(row["active_jobs"] for row in workers),
        },
        "primary_actions": ["register_worker", "drain_worker", "configure_queue"],
        "sections": {"workers": workers, "queue_policies": policies},
        "evidence_links": [{"label": "Job queue", "href": "/jobs/summary"}, {"label": "Runtime SLOs", "href": "/runtime/observability/summary"}],
        "warnings": ["No active workers are registered"] if not any(row["status"] == "ACTIVE" for row in workers) else [],
        "permissions": sorted(principal.permissions),
        "last_updated": _now(),
    }

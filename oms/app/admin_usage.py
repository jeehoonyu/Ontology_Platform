"""
Management & Enablement — resource & usage management (deep-fidelity pass 12).
Based on /docs/foundry/administration/overview "Resource & Usage Management":
granular usage metrics tied to accounts/projects/resources, with quotas and
quota checks. Additive; deterministic; local.
"""
import time
import uuid
from typing import Optional, List, Any, Dict

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import String, Integer, Float, JSON
from sqlalchemy.orm import Mapped, mapped_column, Session
from pydantic import BaseModel, Field

from .database import Base, get_db
from .production_auth import Principal, require_permission
from . import tenancy

router = APIRouter(tags=["admin_usage"])


def _now() -> int:
    return int(time.time())


class UsageRecord(Base):
    __tablename__ = "admin_usage_records"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    principal: Mapped[str] = mapped_column(String, index=True)
    project: Mapped[str] = mapped_column(String, index=True)
    organization: Mapped[Optional[str]] = mapped_column(String, index=True, nullable=True)
    resource_type: Mapped[str] = mapped_column(String)
    resource_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    metric: Mapped[str] = mapped_column(String, index=True)   # compute_seconds | storage_bytes | rows
    value: Mapped[float] = mapped_column(Float, default=0.0)
    created_at: Mapped[int] = mapped_column(Integer)


class UsageQuota(Base):
    __tablename__ = "admin_usage_quotas"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    scope_type: Mapped[str] = mapped_column(String, index=True)  # project | organization
    scope_id: Mapped[str] = mapped_column(String, index=True)
    metric: Mapped[str] = mapped_column(String, index=True)
    limit_value: Mapped[float] = mapped_column(Float)
    created_at: Mapped[int] = mapped_column(Integer)


class UsageRecordCreate(BaseModel):
    principal: str
    project: str
    organization: Optional[str] = None
    resource_type: str = "dataset"
    resource_id: Optional[str] = None
    metric: str = "compute_seconds"
    value: float = 0.0


class QuotaCreate(BaseModel):
    scope_type: str = "project"
    scope_id: str
    metric: str = "compute_seconds"
    limit_value: float


class QuotaCheckRequest(BaseModel):
    scope_type: str = "project"
    scope_id: str
    metric: str = "compute_seconds"


@router.post("/admin/usage/record", status_code=201)
def record_usage(body: UsageRecordCreate, principal: Principal = Depends(require_permission("administer")), db: Session = Depends(get_db)):
    tenancy.assert_project_permission(db, principal, body.project, "administer")
    rid = uuid.uuid4().hex
    db.add(UsageRecord(id=rid, principal=body.principal, project=body.project, organization=body.organization,
                       resource_type=body.resource_type, resource_id=body.resource_id, metric=body.metric,
                       value=body.value, created_at=_now()))
    db.commit()
    return {"id": rid, "project": body.project, "organization": body.organization,
            "metric": body.metric, "value": body.value}


@router.get("/admin/usage/summary")
def usage_summary(project: Optional[str] = Query(default=None), metric: Optional[str] = Query(default=None),
                  group_by: str = Query(default="project"), principal: Principal = Depends(require_permission("view")), db: Session = Depends(get_db)):
    q = db.query(UsageRecord)
    if project:
        tenancy.assert_project_permission(db, principal, project, "view")
        q = q.filter(UsageRecord.project == project)
    else:
        accessible = tenancy.accessible_project_ids(db, principal)
        if accessible is not None:
            q = q.filter(UsageRecord.project.in_(accessible))
    if metric:
        q = q.filter(UsageRecord.metric == metric)
    rows = q.all()
    totals: Dict[str, float] = {}
    for r in rows:
        key = {"project": r.project, "principal": r.principal, "organization": r.organization or "(none)",
               "resource": r.resource_id or r.resource_type, "metric": r.metric}.get(group_by, r.project)
        totals[str(key)] = totals.get(str(key), 0.0) + r.value
    top = sorted(totals.items(), key=lambda kv: kv[1], reverse=True)
    return {"group_by": group_by, "record_count": len(rows), "total": round(sum(totals.values()), 6),
            "breakdown": [{"key": k, "value": round(v, 6)} for k, v in top]}


@router.post("/admin/usage/quotas", status_code=201)
def create_quota(body: QuotaCreate, principal: Principal = Depends(require_permission("administer")), db: Session = Depends(get_db)):
    if body.scope_type == "project":
        tenancy.assert_project_permission(db, principal, body.scope_id, "administer")
    elif body.scope_type == "organization" and principal.organization_id and principal.organization_id != body.scope_id and "*" not in principal.project_ids:
        raise HTTPException(status_code=403, detail="Cannot administer another organization")
    qid = uuid.uuid4().hex
    db.add(UsageQuota(id=qid, scope_type=body.scope_type, scope_id=body.scope_id,
                      metric=body.metric, limit_value=body.limit_value, created_at=_now()))
    db.commit()
    return {"id": qid, "scope": f"{body.scope_type}:{body.scope_id}", "metric": body.metric, "limit_value": body.limit_value}


@router.get("/admin/usage/quotas")
def list_quotas(principal: Principal = Depends(require_permission("view")), db: Session = Depends(get_db)):
    accessible = tenancy.accessible_project_ids(db, principal)
    return [{"scope_type": q.scope_type, "scope_id": q.scope_id, "metric": q.metric, "limit_value": q.limit_value}
            for q in db.query(UsageQuota).all() if (q.scope_type == "project" and (accessible is None or q.scope_id in accessible)) or (q.scope_type == "organization" and (not principal.organization_id or principal.organization_id == q.scope_id or "*" in principal.project_ids))]


@router.post("/admin/usage/check-quota")
def check_quota(body: QuotaCheckRequest, principal: Principal = Depends(require_permission("view")), db: Session = Depends(get_db)):
    if body.scope_type == "project":
        tenancy.assert_project_permission(db, principal, body.scope_id, "view")
    elif body.scope_type == "organization" and principal.organization_id and principal.organization_id != body.scope_id and "*" not in principal.project_ids:
        raise HTTPException(status_code=403, detail="Cannot inspect another organization")
    quota = (db.query(UsageQuota).filter(UsageQuota.scope_type == body.scope_type,
             UsageQuota.scope_id == body.scope_id, UsageQuota.metric == body.metric).first())
    # current usage = sum of records for that scope+metric
    uq = db.query(UsageRecord).filter(UsageRecord.metric == body.metric)
    if body.scope_type == "project":
        uq = uq.filter(UsageRecord.project == body.scope_id)
    elif body.scope_type == "organization":
        uq = uq.filter(UsageRecord.organization == body.scope_id)
    usage = round(sum(r.value for r in uq.all()), 6)
    if not quota:
        return {"scope": f"{body.scope_type}:{body.scope_id}", "metric": body.metric,
                "usage": usage, "limit": None, "within_limit": True, "note": "no quota set"}
    remaining = quota.limit_value - usage
    return {"scope": f"{body.scope_type}:{body.scope_id}", "metric": body.metric, "usage": usage,
            "limit": quota.limit_value, "remaining": round(remaining, 6), "within_limit": usage <= quota.limit_value}

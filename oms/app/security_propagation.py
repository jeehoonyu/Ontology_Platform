"""
Security — marking assignment, propagation through lineage & access decisions
(deep-fidelity pass 8, Security & Governance).

Deepens the markings model: assign markings to resources, **propagate** them
downstream through pipeline lineage (outputs inherit input markings — Foundry's
mandatory-control propagation), and make an **access decision** that requires a
principal to hold every effective marking. Additive; deterministic; local.
"""
import time
import uuid
from typing import Optional, List, Any, Dict, Set

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import String, Integer
from sqlalchemy.orm import Mapped, mapped_column, Session
from pydantic import BaseModel, Field

from .database import Base, get_db
from . import models, models_action, production_auth, security_data as _sec, semantic_scope

router = APIRouter(tags=["security_propagation"])


def _now() -> int:
    return int(time.time())


class ResourceMarking(Base):
    __tablename__ = "resource_markings"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    resource_type: Mapped[str] = mapped_column(String, index=True)
    resource_id: Mapped[str] = mapped_column(String, index=True)
    marking_id: Mapped[str] = mapped_column(String, index=True)
    created_at: Mapped[int] = mapped_column(Integer)


class ResourceMarkingCreate(BaseModel):
    resource_type: str = "dataset"
    resource_id: str
    marking_id: str
    # OPT-IN enforcement: when an actor is supplied, assigning a marking to a
    # resource requires the actor to hold the APPLY permission on that marking.
    # When omitted (None) no enforcement happens, preserving historical behavior.
    actor: Optional[str] = None


class ResourceMarkingStripRequest(BaseModel):
    # OPT-IN enforcement: when an actor is supplied, stripping a marking requires
    # the actor to hold the REMOVE permission. When omitted no enforcement.
    actor: Optional[str] = None


class AccessDecisionRequest(BaseModel):
    principal: str
    resource_type: str = "dataset"
    resource_id: str


def _markings_for(db: Session, resource_id: str) -> Set[str]:
    return {r.marking_id for r in db.query(ResourceMarking).filter(ResourceMarking.resource_id == resource_id).all()}


@router.post("/security/resource-markings", status_code=201)
def assign_marking(body: ResourceMarkingCreate, db: Session = Depends(get_db)):
    if not db.get(_sec.Marking, body.marking_id):
        raise HTTPException(status_code=404, detail=f"Marking '{body.marking_id}' not found")
    # OPT-IN enforcement: only check APPLY when an actor is supplied. Assigning a
    # marking to a resource requires the APPLY permission (Foundry "apply marking").
    if body.actor is not None and not _sec.principal_has_marking_permission(
        db, body.actor, body.marking_id, "apply"
    ):
        raise HTTPException(
            status_code=403,
            detail=(
                f"Actor '{body.actor}' lacks APPLY permission on marking "
                f"'{body.marking_id}'"
            ),
        )
    rm = ResourceMarking(id=uuid.uuid4().hex, resource_type=body.resource_type,
                         resource_id=body.resource_id, marking_id=body.marking_id, created_at=_now())
    db.add(rm)
    db.add(models_action.AuditLog(id=uuid.uuid4().hex, actor=body.actor or "system",
                                  event_type="security.marking.assigned",
                                  subject_type=body.resource_type, subject_id=body.resource_id,
                                  payload={"marking_id": body.marking_id, "actor": body.actor}))
    db.commit()
    return {"id": rm.id, "resource_id": body.resource_id, "marking_id": body.marking_id}


@router.get("/security/resource-markings/{resource_id}")
def list_resource_markings(resource_id: str, db: Session = Depends(get_db)):
    return {"resource_id": resource_id, "marking_ids": sorted(_markings_for(db, resource_id))}


@router.delete("/security/resource-markings/{resource_marking_id}")
def strip_resource_marking(
    resource_marking_id: str,
    actor: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """Strip (remove) a marking from a resource.

    OPT-IN enforcement: when an ``actor`` is supplied (query param), removing a
    marking requires the actor to hold the REMOVE permission on that marking
    (Foundry "remove marking" / expand-access). When omitted, no enforcement
    happens, preserving the permissive default of the rest of this module.
    """
    rm = db.get(ResourceMarking, resource_marking_id)
    if not rm:
        raise HTTPException(
            status_code=404,
            detail=f"ResourceMarking '{resource_marking_id}' not found",
        )
    if actor is not None and not _sec.principal_has_marking_permission(
        db, actor, rm.marking_id, "remove"
    ):
        raise HTTPException(
            status_code=403,
            detail=f"Actor '{actor}' lacks REMOVE permission on marking '{rm.marking_id}'",
        )
    resource_id = rm.resource_id
    marking_id = rm.marking_id
    db.delete(rm)
    db.add(models_action.AuditLog(id=uuid.uuid4().hex, actor=actor or "system",
                                  event_type="security.marking.stripped",
                                  subject_type=rm.resource_type, subject_id=resource_id,
                                  payload={"marking_id": marking_id, "actor": actor}))
    db.commit()
    return {"stripped": True, "id": resource_marking_id,
            "resource_id": resource_id, "marking_id": marking_id}


@router.post("/security/markings/propagate")
def propagate_markings(dataset_id: str, db: Session = Depends(get_db),
                       principal: production_auth.Principal = Depends(
                           production_auth.require_permission("administer"))):
    """Walk pipeline lineage; downstream output datasets inherit the source markings."""
    # The router's `administer` is a tier check with no project argument, and this route
    # both writes and reads across the boundary: it applied ResourceMarking rows -- mandatory
    # controls -- to datasets it reached, and returned each one's id and effective markings,
    # enumerating other tenants' lineage. The dataset is now resolved against the caller, and
    # the edge graph is built only from pipelines they can administer, so a legitimate
    # multi-project propagation still works for someone who holds both and stops at the edge
    # of what they hold. T2 of GOAL_TENANCY_2026-08-27.
    semantic_scope.asset_for(db, principal, dataset_id, "administer")
    source_markings = _markings_for(db, dataset_id)
    # build input -> [output] edges from pipeline definitions
    edges: Dict[str, List[str]] = {}
    for p in semantic_scope.accessible_query(
            db, principal, models.PipelineDefinition, "administer").all():
        if p.input_asset_id and p.output_asset_id:
            edges.setdefault(p.input_asset_id, []).append(p.output_asset_id)
    downstream: List[Dict[str, Any]] = []
    visited: Set[str] = set()
    frontier = [dataset_id]
    while frontier:
        current = frontier.pop()
        for out in edges.get(current, []):
            if out in visited:
                continue
            visited.add(out)
            existing = _markings_for(db, out)
            inherited = source_markings - existing
            for mid in inherited:  # actually apply propagation (mandatory controls flow with data)
                db.add(ResourceMarking(id=uuid.uuid4().hex, resource_type="dataset", resource_id=out,
                                       marking_id=mid, created_at=_now()))
            downstream.append({"dataset_id": out, "inherited_markings": sorted(inherited),
                               "effective_markings": sorted(existing | source_markings)})
            frontier.append(out)
    db.commit()
    return {"dataset_id": dataset_id, "source_markings": sorted(source_markings),
            "downstream_count": len(downstream), "downstream": downstream}


@router.post("/security/access-decision")
def access_decision(body: AccessDecisionRequest, db: Session = Depends(get_db)):
    required = _markings_for(db, body.resource_id)
    held = {g.marking_id for g in db.query(_sec.MarkingGrant).filter(_sec.MarkingGrant.principal == body.principal).all()}
    missing = sorted(required - held)
    return {"principal": body.principal, "resource_id": body.resource_id,
            "required_markings": sorted(required), "held_markings": sorted(held & required),
            "allowed": not missing, "missing_markings": missing}

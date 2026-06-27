"""
Ontology Manager: branching + proposals (governance of ontology changes).

Tables:
  - ontology_branches
  - ontology_proposals

Endpoints:
  POST /ontology/branches
  GET  /ontology/branches
  POST /ontology/proposals
  GET  /ontology/proposals
  GET  /ontology/proposals/{id}
  POST /ontology/proposals/{id}/submit
  POST /ontology/proposals/{id}/decision
  POST /ontology/proposals/{id}/merge
"""

import time
import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import JSON, Integer, String
from sqlalchemy.orm import Mapped, Session, mapped_column

from . import models, models_action
from .database import Base, get_db

# ---------------------------------------------------------------------------
# SQLAlchemy Models
# ---------------------------------------------------------------------------


class OntologyBranch(Base):
    __tablename__ = "ontology_branches"

    id: Mapped[str] = mapped_column(String, primary_key=True, index=True)
    display_name: Mapped[str] = mapped_column(String, nullable=False)
    base_branch: Mapped[str] = mapped_column(String, nullable=False, default="main")
    status: Mapped[str] = mapped_column(String, nullable=False, default="open")  # open | merged
    created_at: Mapped[int] = mapped_column(Integer, default=lambda: int(time.time()))


class OntologyProposal(Base):
    __tablename__ = "ontology_proposals"

    id: Mapped[str] = mapped_column(String, primary_key=True, index=True)
    branch_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    title: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    changes: Mapped[List] = mapped_column(JSON, default=list)
    # status: draft | submitted | approved | merged | rejected
    status: Mapped[str] = mapped_column(String, nullable=False, default="draft")
    reviewer: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    created_at: Mapped[int] = mapped_column(Integer, default=lambda: int(time.time()))
    decided_at: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)


# ---------------------------------------------------------------------------
# Pydantic Schemas
# ---------------------------------------------------------------------------

# -- Branch --

class BranchCreate(BaseModel):
    id: Optional[str] = None
    display_name: str
    base_branch: str = "main"


class BranchRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    display_name: str
    base_branch: str
    status: str
    created_at: int


# -- Proposal --

class ProposalCreate(BaseModel):
    id: Optional[str] = None
    branch_id: str
    title: str
    description: Optional[str] = None
    changes: List[Dict[str, Any]] = Field(default_factory=list)


class ProposalRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    branch_id: str
    title: str
    description: Optional[str]
    changes: List[Dict[str, Any]]
    status: str
    reviewer: Optional[str]
    created_at: int
    decided_at: Optional[int]


class DecisionBody(BaseModel):
    approve: bool
    reviewer: str


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

router = APIRouter(tags=["ontology-versioning"])


def _branch_not_found(branch_id: str):
    raise HTTPException(status_code=404, detail=f"OntologyBranch '{branch_id}' not found")


def _proposal_not_found(proposal_id: str):
    raise HTTPException(status_code=404, detail=f"OntologyProposal '{proposal_id}' not found")


def _append_audit(
    db: Session,
    actor: str,
    event_type: str,
    subject_type: str,
    subject_id: str,
    payload: Dict[str, Any],
):
    db.add(
        models_action.AuditLog(
            id=uuid.uuid4().hex,
            actor=actor,
            event_type=event_type,
            subject_type=subject_type,
            subject_id=subject_id,
            payload=payload,
        )
    )


# ---- Branch endpoints ----

@router.post("/ontology/branches", response_model=BranchRead)
def create_branch(body: BranchCreate, db: Session = Depends(get_db)):
    branch_id = body.id or uuid.uuid4().hex
    existing = db.query(OntologyBranch).filter(OntologyBranch.id == branch_id).first()
    if existing:
        raise HTTPException(status_code=400, detail="OntologyBranch already exists")
    branch = OntologyBranch(
        id=branch_id,
        display_name=body.display_name,
        base_branch=body.base_branch,
        status="open",
        created_at=int(time.time()),
    )
    db.add(branch)
    db.commit()
    db.refresh(branch)
    return branch


@router.get("/ontology/branches", response_model=List[BranchRead])
def list_branches(db: Session = Depends(get_db)):
    return db.query(OntologyBranch).order_by(OntologyBranch.created_at.desc()).all()


# ---- Proposal endpoints ----

@router.post("/ontology/proposals", response_model=ProposalRead)
def create_proposal(body: ProposalCreate, db: Session = Depends(get_db)):
    branch = db.query(OntologyBranch).filter(OntologyBranch.id == body.branch_id).first()
    if not branch:
        _branch_not_found(body.branch_id)
    if branch.status == "merged":
        raise HTTPException(status_code=400, detail="Cannot create proposal on a merged branch")

    proposal_id = body.id or uuid.uuid4().hex
    existing = db.query(OntologyProposal).filter(OntologyProposal.id == proposal_id).first()
    if existing:
        raise HTTPException(status_code=400, detail="OntologyProposal already exists")

    proposal = OntologyProposal(
        id=proposal_id,
        branch_id=body.branch_id,
        title=body.title,
        description=body.description,
        changes=body.changes,
        status="draft",
        created_at=int(time.time()),
    )
    db.add(proposal)
    db.commit()
    db.refresh(proposal)
    return proposal


@router.get("/ontology/proposals", response_model=List[ProposalRead])
def list_proposals(branch_id: Optional[str] = None, db: Session = Depends(get_db)):
    query = db.query(OntologyProposal)
    if branch_id:
        query = query.filter(OntologyProposal.branch_id == branch_id)
    return query.order_by(OntologyProposal.created_at.desc()).all()


@router.get("/ontology/proposals/{proposal_id}", response_model=ProposalRead)
def get_proposal(proposal_id: str, db: Session = Depends(get_db)):
    proposal = db.query(OntologyProposal).filter(OntologyProposal.id == proposal_id).first()
    if not proposal:
        _proposal_not_found(proposal_id)
    return proposal


@router.post("/ontology/proposals/{proposal_id}/submit", response_model=ProposalRead)
def submit_proposal(proposal_id: str, db: Session = Depends(get_db)):
    proposal = db.query(OntologyProposal).filter(OntologyProposal.id == proposal_id).first()
    if not proposal:
        _proposal_not_found(proposal_id)
    if proposal.status != "draft":
        raise HTTPException(
            status_code=400,
            detail=f"Proposal must be in 'draft' status to submit (current: {proposal.status})",
        )
    proposal.status = "submitted"
    db.commit()
    db.refresh(proposal)
    return proposal


@router.post("/ontology/proposals/{proposal_id}/decision", response_model=ProposalRead)
def decide_proposal(proposal_id: str, body: DecisionBody, db: Session = Depends(get_db)):
    proposal = db.query(OntologyProposal).filter(OntologyProposal.id == proposal_id).first()
    if not proposal:
        _proposal_not_found(proposal_id)
    if proposal.status != "submitted":
        raise HTTPException(
            status_code=400,
            detail=f"Proposal must be in 'submitted' status for a decision (current: {proposal.status})",
        )

    new_status = "approved" if body.approve else "rejected"
    proposal.status = new_status
    proposal.reviewer = body.reviewer
    proposal.decided_at = int(time.time())

    _append_audit(
        db,
        actor=body.reviewer,
        event_type="ontology.proposal.decided",
        subject_type="ontology_proposal",
        subject_id=proposal_id,
        payload={
            "decision": new_status,
            "reviewer": body.reviewer,
            "branch_id": proposal.branch_id,
            "title": proposal.title,
        },
    )
    db.commit()
    db.refresh(proposal)
    return proposal


@router.post("/ontology/proposals/{proposal_id}/merge", response_model=ProposalRead)
def merge_proposal(proposal_id: str, db: Session = Depends(get_db)):
    proposal = db.query(OntologyProposal).filter(OntologyProposal.id == proposal_id).first()
    if not proposal:
        _proposal_not_found(proposal_id)
    if proposal.status != "approved":
        raise HTTPException(
            status_code=400,
            detail=f"Proposal must be 'approved' before merging (current: {proposal.status})",
        )

    branch = db.query(OntologyBranch).filter(OntologyBranch.id == proposal.branch_id).first()
    if not branch:
        _branch_not_found(proposal.branch_id)

    proposal.status = "merged"
    branch.status = "merged"

    _append_audit(
        db,
        actor=proposal.reviewer or "system",
        event_type="ontology.proposal.merged",
        subject_type="ontology_proposal",
        subject_id=proposal_id,
        payload={
            "branch_id": proposal.branch_id,
            "title": proposal.title,
            "change_count": len(proposal.changes or []),
            "reviewer": proposal.reviewer,
        },
    )
    db.commit()
    db.refresh(proposal)
    return proposal

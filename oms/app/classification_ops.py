"""
Classification-Based Access Control (CBAC) — security & governance.

Implements the documented Foundry CBAC mechanics that were entirely missing:
  * file / data / project CLASSIFICATIONS, each carrying a hierarchical LEVEL
    (e.g. unclassified < confidential < secret < top_secret) plus CATEGORIES
    (compartments / dissemination controls).
  * CLEARANCES held by principals: a max level + the categories they hold.
  * HIERARCHICAL access: a higher clearance level satisfies a lower data level
    (Top Secret clearance can read Secret data; Secret clearance cannot read Top Secret).
  * DISJUNCTIVE-OR CATEGORY GROUPS: categories are organised into groups; within a
    group holding ANY one required category satisfies it (OR); every group with a
    requirement must be satisfied (AND). Ungrouped categories are individually required.
  * DATA classification AUTO-COMPUTED as the STRICTEST UNION of upstream sources
    (max level + union of categories).

Additive; deterministic; local. Prefix: Cls / cls_.
"""
import time
import uuid
from typing import Optional, List, Any, Dict

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import String, Integer, JSON
from sqlalchemy.orm import Mapped, mapped_column, Session
from pydantic import BaseModel, ConfigDict, Field

from .database import Base, get_db
from . import models_action

router = APIRouter(tags=["classification"])


def _now() -> int:
    return int(time.time())


def _audit(db: Session, actor: str, event: str, subject_type: str, subject_id: str, payload: dict) -> None:
    db.add(models_action.AuditLog(id=uuid.uuid4().hex, actor=actor, event_type=event,
                                  subject_type=subject_type, subject_id=subject_id, payload=payload))


# ---------------------------------------------------------------------------
# ORM
# ---------------------------------------------------------------------------

class ClsScheme(Base):
    """A classification system: an ordered list of levels + disjunctive category groups."""
    __tablename__ = "cls_schemes"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    display_name: Mapped[str] = mapped_column(String)
    levels: Mapped[list] = mapped_column(JSON, default=list)            # low -> high
    category_groups: Mapped[list] = mapped_column(JSON, default=list)   # [[cat,...], ...] (OR within a group)
    created_at: Mapped[int] = mapped_column(Integer)


class ClsClassification(Base):
    """A classification applied to a file / dataset / project."""
    __tablename__ = "cls_classifications"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    scheme_id: Mapped[str] = mapped_column(String, index=True)
    kind: Mapped[str] = mapped_column(String)          # file | data | project
    level: Mapped[str] = mapped_column(String)
    categories: Mapped[list] = mapped_column(JSON, default=list)
    derived: Mapped[bool] = mapped_column(default=False)  # True if auto-computed from upstreams
    created_at: Mapped[int] = mapped_column(Integer)


class ClsClearance(Base):
    """A clearance held by a principal within a scheme."""
    __tablename__ = "cls_clearances"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    principal_id: Mapped[str] = mapped_column(String, index=True)
    scheme_id: Mapped[str] = mapped_column(String, index=True)
    max_level: Mapped[str] = mapped_column(String)
    categories: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[int] = mapped_column(Integer)


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class SchemeCreate(BaseModel):
    id: Optional[str] = None
    display_name: str
    levels: List[str]                       # ordered low -> high
    category_groups: List[List[str]] = Field(default_factory=list)


class SchemeRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    display_name: str
    levels: List[str]
    category_groups: List[List[str]]
    created_at: int


class ClassificationCreate(BaseModel):
    id: Optional[str] = None
    scheme_id: str
    kind: str = "data"
    level: str
    categories: List[str] = Field(default_factory=list)


class ClassificationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    scheme_id: str
    kind: str
    level: str
    categories: List[str]
    derived: bool
    created_at: int


class ClearanceCreate(BaseModel):
    id: Optional[str] = None
    principal_id: str
    scheme_id: str
    max_level: str
    categories: List[str] = Field(default_factory=list)


class AccessCheckRequest(BaseModel):
    principal_id: str
    classification_id: str


class ComputeDataRequest(BaseModel):
    scheme_id: str
    upstream_classification_ids: List[str]
    kind: str = "data"
    persist: bool = False
    id: Optional[str] = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _scheme(db: Session, scheme_id: str) -> ClsScheme:
    s = db.query(ClsScheme).filter(ClsScheme.id == scheme_id).first()
    if not s:
        raise HTTPException(status_code=404, detail=f"ClsScheme '{scheme_id}' not found")
    return s


def _level_index(scheme: ClsScheme, level: str) -> int:
    levels = scheme.levels or []
    if level not in levels:
        raise HTTPException(status_code=422, detail=f"level '{level}' not in scheme levels {levels}")
    return levels.index(level)


def _category_decision(scheme: ClsScheme, required: List[str], held: List[str]) -> Dict[str, Any]:
    """Disjunctive-OR groups: within a group with a requirement, holding ANY one suffices;
    ungrouped required categories must each be held. Returns {ok, failures}."""
    required_set, held_set = set(required or []), set(held or [])
    groups = [set(g) for g in (scheme.category_groups or [])]
    grouped = set().union(*groups) if groups else set()
    failures: List[str] = []

    for g in groups:
        req_in_group = required_set & g
        if req_in_group and not (held_set & req_in_group):
            failures.append(f"need one of {sorted(req_in_group)}")

    for cat in sorted(required_set - grouped):  # ungrouped -> individually required
        if cat not in held_set:
            failures.append(f"missing category '{cat}'")

    return {"ok": not failures, "failures": failures}


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("/classification/schemes", response_model=SchemeRead, status_code=201)
def create_scheme(body: SchemeCreate, db: Session = Depends(get_db)):
    if not body.levels:
        raise HTTPException(status_code=422, detail="levels must be a non-empty ordered list")
    sid = body.id or uuid.uuid4().hex
    if db.query(ClsScheme).filter(ClsScheme.id == sid).first():
        raise HTTPException(status_code=400, detail="ClsScheme already exists")
    row = ClsScheme(id=sid, display_name=body.display_name, levels=body.levels,
                    category_groups=body.category_groups, created_at=_now())
    db.add(row)
    _audit(db, "system", "classification.scheme.created", "cls_scheme", sid, {"levels": body.levels})
    db.commit(); db.refresh(row)
    return row


@router.get("/classification/schemes", response_model=List[SchemeRead])
def list_schemes(db: Session = Depends(get_db)):
    return db.query(ClsScheme).all()


@router.get("/classification/schemes/{scheme_id}", response_model=SchemeRead)
def get_scheme(scheme_id: str, db: Session = Depends(get_db)):
    return _scheme(db, scheme_id)


@router.post("/classification/classifications", response_model=ClassificationRead, status_code=201)
def create_classification(body: ClassificationCreate, db: Session = Depends(get_db)):
    if body.kind not in {"file", "data", "project"}:
        raise HTTPException(status_code=422, detail="kind must be file|data|project")
    scheme = _scheme(db, body.scheme_id)
    _level_index(scheme, body.level)  # validates level membership
    cid = body.id or uuid.uuid4().hex
    if db.query(ClsClassification).filter(ClsClassification.id == cid).first():
        raise HTTPException(status_code=400, detail="ClsClassification already exists")
    row = ClsClassification(id=cid, scheme_id=body.scheme_id, kind=body.kind, level=body.level,
                            categories=body.categories, derived=False, created_at=_now())
    db.add(row)
    _audit(db, "system", "classification.applied", "cls_classification", cid,
           {"kind": body.kind, "level": body.level, "categories": body.categories})
    db.commit(); db.refresh(row)
    return row


@router.get("/classification/classifications", response_model=List[ClassificationRead])
def list_classifications(db: Session = Depends(get_db)):
    return db.query(ClsClassification).all()


@router.get("/classification/classifications/{cid}", response_model=ClassificationRead)
def get_classification(cid: str, db: Session = Depends(get_db)):
    row = db.query(ClsClassification).filter(ClsClassification.id == cid).first()
    if not row:
        raise HTTPException(status_code=404, detail=f"ClsClassification '{cid}' not found")
    return row


@router.post("/classification/clearances", status_code=201)
def create_clearance(body: ClearanceCreate, db: Session = Depends(get_db)):
    scheme = _scheme(db, body.scheme_id)
    _level_index(scheme, body.max_level)
    clid = body.id or uuid.uuid4().hex
    row = ClsClearance(id=clid, principal_id=body.principal_id, scheme_id=body.scheme_id,
                       max_level=body.max_level, categories=body.categories, created_at=_now())
    db.add(row)
    _audit(db, "system", "classification.clearance.granted", "cls_clearance", clid,
           {"principal": body.principal_id, "max_level": body.max_level})
    db.commit()
    return {"id": clid, "principal_id": body.principal_id, "max_level": body.max_level}


@router.post("/classification/check-access")
def check_access(body: AccessCheckRequest, db: Session = Depends(get_db)):
    cls = db.query(ClsClassification).filter(ClsClassification.id == body.classification_id).first()
    if not cls:
        raise HTTPException(status_code=404, detail=f"ClsClassification '{body.classification_id}' not found")
    scheme = _scheme(db, cls.scheme_id)
    clr = (db.query(ClsClearance)
           .filter(ClsClearance.principal_id == body.principal_id, ClsClearance.scheme_id == cls.scheme_id)
           .order_by(ClsClearance.created_at.desc()).first())
    if not clr:
        return {"allowed": False, "reason": "no clearance in scheme", "level_ok": False, "category_failures": []}

    data_level = _level_index(scheme, cls.level)
    clr_level = _level_index(scheme, clr.max_level)
    level_ok = clr_level >= data_level  # hierarchical: higher clearance satisfies lower requirement

    cat = _category_decision(scheme, cls.categories or [], clr.categories or [])
    allowed = level_ok and cat["ok"]
    reason = "granted" if allowed else (
        "insufficient level" if not level_ok else "category requirement not met")
    return {"allowed": allowed, "reason": reason, "level_ok": level_ok,
            "required_level": cls.level, "clearance_level": clr.max_level,
            "category_failures": cat["failures"]}


@router.post("/classification/compute-data", response_model=ClassificationRead, status_code=201)
def compute_data_classification(body: ComputeDataRequest, db: Session = Depends(get_db)):
    """Derive the strictest classification: max level + union of categories across upstreams."""
    scheme = _scheme(db, body.scheme_id)
    if not body.upstream_classification_ids:
        raise HTTPException(status_code=422, detail="upstream_classification_ids must be non-empty")
    upstreams = []
    for uid in body.upstream_classification_ids:
        u = db.query(ClsClassification).filter(ClsClassification.id == uid).first()
        if not u:
            raise HTTPException(status_code=404, detail=f"upstream classification '{uid}' not found")
        if u.scheme_id != body.scheme_id:
            raise HTTPException(status_code=422, detail=f"upstream '{uid}' belongs to a different scheme")
        upstreams.append(u)

    max_idx = max(_level_index(scheme, u.level) for u in upstreams)
    derived_level = scheme.levels[max_idx]
    derived_categories = sorted(set().union(*[set(u.categories or []) for u in upstreams]))

    cid = body.id or uuid.uuid4().hex
    row = ClsClassification(id=cid, scheme_id=body.scheme_id, kind=body.kind, level=derived_level,
                            categories=derived_categories, derived=True, created_at=_now())
    if body.persist:
        db.add(row)
        _audit(db, "system", "classification.derived", "cls_classification", cid,
               {"from": body.upstream_classification_ids, "level": derived_level})
        db.commit(); db.refresh(row)
    return row

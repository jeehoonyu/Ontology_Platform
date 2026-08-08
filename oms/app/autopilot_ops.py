"""
Autopilot — operational workflow management over the ontology (Applications).

Implements the documented Autopilot mechanics (previously entirely missing):
  * BOARDS that organise objects of a type into workflow STATE columns (Kanban).
  * STATE INFERENCE — a board may read a direct ``state_property`` OR compute each
    object's state from ordered predicate RULES (first match wins), mirroring how
    Autopilot derives an item's column from its data/automation conditions.
  * WORKFLOW DEPENDENCY GRAPH — steps (automation / action / function nodes) with
    ``depends_on`` edges, returned with a topological order and cycle detection,
    the backend equivalent of Autopilot's dependency view.

Read/compute layer; deterministic; local. Prefix: Ap / ap_.
"""
import time
import uuid
from typing import Optional, List, Any, Dict

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import String, Integer, JSON, Boolean
from sqlalchemy.orm import Mapped, mapped_column, Session
from pydantic import BaseModel, ConfigDict, Field

from .database import Base, get_db
from . import models

router = APIRouter(tags=["autopilot"])


def _now() -> int:
    return int(time.time())


# ---------------------------------------------------------------------------
# ORM
# ---------------------------------------------------------------------------

class ApBoard(Base):
    __tablename__ = "ap_boards"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    display_name: Mapped[str] = mapped_column(String)
    object_type_id: Mapped[str] = mapped_column(String, index=True)
    state_property: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    columns: Mapped[list] = mapped_column(JSON, default=list)   # ordered state names
    created_at: Mapped[int] = mapped_column(Integer)


class ApStateRule(Base):
    """Ordered predicate -> state mapping for computed (inferred) board state."""
    __tablename__ = "ap_state_rules"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    board_id: Mapped[str] = mapped_column(String, index=True)
    state: Mapped[str] = mapped_column(String)
    prop: Mapped[str] = mapped_column(String)
    op: Mapped[str] = mapped_column(String)        # == != > >= < <= in
    value: Mapped[Any] = mapped_column(JSON)
    rule_order: Mapped[int] = mapped_column(Integer, default=0)


class ApWorkflow(Base):
    __tablename__ = "ap_workflows"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    display_name: Mapped[str] = mapped_column(String)
    created_at: Mapped[int] = mapped_column(Integer)


class ApWorkflowStep(Base):
    __tablename__ = "ap_workflow_steps"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    workflow_id: Mapped[str] = mapped_column(String, index=True)
    name: Mapped[str] = mapped_column(String)
    step_type: Mapped[str] = mapped_column(String)   # automation | action | function
    depends_on: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[int] = mapped_column(Integer)


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class BoardCreate(BaseModel):
    id: Optional[str] = None
    display_name: str
    object_type_id: str
    state_property: Optional[str] = None
    columns: List[str] = Field(default_factory=list)


class BoardRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    display_name: str
    object_type_id: str
    state_property: Optional[str]
    columns: List[str]
    created_at: int


class StateRuleCreate(BaseModel):
    state: str
    prop: str
    op: str = "=="
    value: Any = None
    rule_order: int = 0


class WorkflowCreate(BaseModel):
    id: Optional[str] = None
    display_name: str


class StepCreate(BaseModel):
    id: Optional[str] = None
    name: str
    step_type: str = "automation"
    depends_on: List[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _board(db: Session, board_id: str) -> ApBoard:
    b = db.query(ApBoard).filter(ApBoard.id == board_id).first()
    if not b:
        raise HTTPException(status_code=404, detail=f"ApBoard '{board_id}' not found")
    return b


def _predicate(value: Any, op: str, target: Any) -> bool:
    try:
        if op == "==":
            return value == target
        if op == "!=":
            return value != target
        if op == "in":
            return value in (target or [])
        if op == ">":
            return value is not None and value > target
        if op == ">=":
            return value is not None and value >= target
        if op == "<":
            return value is not None and value < target
        if op == "<=":
            return value is not None and value <= target
    except TypeError:
        return False
    return False


def _infer_state(board: ApBoard, rules: List[ApStateRule], props: Dict[str, Any]) -> Optional[str]:
    if rules:
        for r in sorted(rules, key=lambda x: x.rule_order):
            if _predicate(props.get(r.prop), r.op, r.value):
                return r.state
        return None
    if board.state_property:
        v = props.get(board.state_property)
        return None if v is None else str(v)
    return None


# ---------------------------------------------------------------------------
# Board endpoints
# ---------------------------------------------------------------------------

@router.post("/autopilot/boards", response_model=BoardRead, status_code=201)
def create_board(body: BoardCreate, db: Session = Depends(get_db)):
    if not db.query(models.ObjectType).filter(models.ObjectType.id == body.object_type_id).first():
        raise HTTPException(status_code=404, detail=f"ObjectType '{body.object_type_id}' not found")
    if not body.state_property and not body.columns:
        raise HTTPException(status_code=422, detail="provide state_property and/or columns")
    bid = body.id or uuid.uuid4().hex
    if db.query(ApBoard).filter(ApBoard.id == bid).first():
        raise HTTPException(status_code=400, detail="ApBoard already exists")
    row = ApBoard(id=bid, display_name=body.display_name, object_type_id=body.object_type_id,
                  state_property=body.state_property, columns=body.columns, created_at=_now())
    db.add(row); db.commit(); db.refresh(row)
    return row


@router.get("/autopilot/boards", response_model=List[BoardRead])
def list_boards(db: Session = Depends(get_db)):
    return db.query(ApBoard).all()


@router.get("/autopilot/boards/{board_id}", response_model=BoardRead)
def get_board(board_id: str, db: Session = Depends(get_db)):
    return _board(db, board_id)


@router.post("/autopilot/boards/{board_id}/state-rules", status_code=201)
def add_state_rule(board_id: str, body: StateRuleCreate, db: Session = Depends(get_db)):
    _board(db, board_id)
    rid = uuid.uuid4().hex
    db.add(ApStateRule(id=rid, board_id=board_id, state=body.state, prop=body.prop,
                       op=body.op, value=body.value, rule_order=body.rule_order))
    db.commit()
    return {"id": rid, "board_id": board_id, "state": body.state}


@router.get("/autopilot/boards/{board_id}/state-rules")
def list_state_rules(board_id: str, db: Session = Depends(get_db)):
    _board(db, board_id)
    rules = db.query(ApStateRule).filter(ApStateRule.board_id == board_id).all()
    return [{"id": r.id, "state": r.state, "prop": r.prop, "op": r.op, "value": r.value,
             "rule_order": r.rule_order} for r in rules]


@router.get("/autopilot/boards/{board_id}/kanban")
def board_kanban(board_id: str, db: Session = Depends(get_db)):
    """Group the board's objects into state columns (inferred via rules or a state property)."""
    board = _board(db, board_id)
    rules = db.query(ApStateRule).filter(ApStateRule.board_id == board_id).all()
    objs = db.query(models.ObjectInstance).filter(
        models.ObjectInstance.object_type_id == board.object_type_id).all()

    columns = list(board.columns or [])
    # if no explicit columns, derive them from the rule states (in order)
    if not columns and rules:
        seen: List[str] = []
        for r in sorted(rules, key=lambda x: x.rule_order):
            if r.state not in seen:
                seen.append(r.state)
        columns = seen

    buckets: Dict[str, List[Dict[str, Any]]] = {c: [] for c in columns}
    unassigned: List[Dict[str, Any]] = []
    for o in objs:
        state = _infer_state(board, rules, o.properties or {})
        card = {"id": o.id, "state": state, "properties": o.properties or {}}
        if state in buckets:
            buckets[state].append(card)
        else:
            unassigned.append(card)
    return {
        "board_id": board_id,
        "object_type_id": board.object_type_id,
        "columns": [{"state": c, "count": len(buckets[c]), "objects": buckets[c]} for c in columns],
        "unassigned": {"count": len(unassigned), "objects": unassigned},
        "total": len(objs),
    }


# ---------------------------------------------------------------------------
# Workflow dependency graph
# ---------------------------------------------------------------------------

@router.post("/autopilot/workflows", status_code=201)
def create_workflow(body: WorkflowCreate, db: Session = Depends(get_db)):
    wid = body.id or uuid.uuid4().hex
    if db.query(ApWorkflow).filter(ApWorkflow.id == wid).first():
        raise HTTPException(status_code=400, detail="ApWorkflow already exists")
    db.add(ApWorkflow(id=wid, display_name=body.display_name, created_at=_now()))
    db.commit()
    return {"id": wid, "display_name": body.display_name}


@router.get("/autopilot/workflows")
def list_workflows(db: Session = Depends(get_db)):
    return [{"id": w.id, "display_name": w.display_name} for w in db.query(ApWorkflow).all()]


@router.post("/autopilot/workflows/{workflow_id}/steps", status_code=201)
def add_step(workflow_id: str, body: StepCreate, db: Session = Depends(get_db)):
    if not db.query(ApWorkflow).filter(ApWorkflow.id == workflow_id).first():
        raise HTTPException(status_code=404, detail=f"ApWorkflow '{workflow_id}' not found")
    sid = body.id or uuid.uuid4().hex
    if db.query(ApWorkflowStep).filter(ApWorkflowStep.id == sid).first():
        raise HTTPException(status_code=400, detail="step id already exists")
    db.add(ApWorkflowStep(id=sid, workflow_id=workflow_id, name=body.name, step_type=body.step_type,
                          depends_on=body.depends_on, created_at=_now()))
    db.commit()
    return {"id": sid, "workflow_id": workflow_id, "name": body.name}


@router.get("/autopilot/workflows/{workflow_id}/dependency-graph")
def dependency_graph(workflow_id: str, db: Session = Depends(get_db)):
    if not db.query(ApWorkflow).filter(ApWorkflow.id == workflow_id).first():
        raise HTTPException(status_code=404, detail=f"ApWorkflow '{workflow_id}' not found")
    steps = db.query(ApWorkflowStep).filter(ApWorkflowStep.workflow_id == workflow_id).all()
    ids = {s.id for s in steps}
    nodes = [{"id": s.id, "name": s.name, "type": s.step_type} for s in steps]
    edges = []
    indeg: Dict[str, int] = {s.id: 0 for s in steps}
    adj: Dict[str, List[str]] = {s.id: [] for s in steps}
    for s in steps:
        for dep in (s.depends_on or []):
            if dep in ids:
                edges.append({"from": dep, "to": s.id})
                adj[dep].append(s.id)
                indeg[s.id] += 1

    # Kahn topological sort (deterministic: process ready nodes in sorted order)
    ready = sorted([n for n, d in indeg.items() if d == 0])
    order: List[str] = []
    while ready:
        n = ready.pop(0)
        order.append(n)
        for m in sorted(adj[n]):
            indeg[m] -= 1
            if indeg[m] == 0:
                ready.append(m)
        ready.sort()
    has_cycle = len(order) != len(steps)
    return {"workflow_id": workflow_id, "nodes": nodes, "edges": edges,
            "topological_order": order if not has_cycle else [], "has_cycle": has_cycle}

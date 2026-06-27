"""
Datasets — transactions, branches, time-travel & incremental deltas
(deep-fidelity pass 4, Data integration).

The base `DataAsset` stores a single `records` blob. Foundry datasets are
versioned: every change is an atomic **transaction** (SNAPSHOT / APPEND / UPDATE /
DELETE), changes live on **branches**, and the current rows are the fold of the
transaction log (enabling **time-travel** and **incremental** deltas). This module
adds that model additively over existing `data_assets` ids. Deterministic; local.
"""
import copy
import time
import uuid
from typing import Optional, List, Any, Dict

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import String, Integer, JSON
from sqlalchemy.orm import Mapped, mapped_column, Session
from pydantic import BaseModel, ConfigDict, Field

from .database import Base, get_db
from . import models, models_action

router = APIRouter(tags=["datasets"])

TXN_TYPES = {"SNAPSHOT", "APPEND", "UPDATE", "DELETE"}


def _now() -> int:
    return int(time.time())


class DatasetTransaction(Base):
    __tablename__ = "dataset_transactions"
    id: Mapped[str] = mapped_column(String, primary_key=True, index=True)
    dataset_id: Mapped[str] = mapped_column(String, index=True)
    branch: Mapped[str] = mapped_column(String, default="master", index=True)
    txn_type: Mapped[str] = mapped_column(String)            # SNAPSHOT/APPEND/UPDATE/DELETE
    primary_key: Mapped[str] = mapped_column(String, default="id")
    records: Mapped[list] = mapped_column(JSON, default=list)
    row_count: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String, default="COMMITTED")
    seq: Mapped[int] = mapped_column(Integer, default=0)     # monotonic per dataset+branch
    created_at: Mapped[int] = mapped_column(Integer)


class DatasetBranch(Base):
    __tablename__ = "dataset_branches"
    id: Mapped[str] = mapped_column(String, primary_key=True, index=True)
    dataset_id: Mapped[str] = mapped_column(String, index=True)
    name: Mapped[str] = mapped_column(String, index=True)
    base_branch: Mapped[str] = mapped_column(String, default="master")
    created_at: Mapped[int] = mapped_column(Integer)


class DatasetSchemaDef(Base):
    """
    Stored, declared schema for a dataset: an ordered list of {name, type} columns.
    Mirrors Foundry's notion of a dataset having an applied schema separate from its
    raw rows. Keyed by dataset id (one schema per dataset). PUT upserts; GET 404s
    until a schema has been declared.
    """
    __tablename__ = "dataset_schema_defs"
    dataset_id: Mapped[str] = mapped_column(String, primary_key=True, index=True)
    columns: Mapped[list] = mapped_column(JSON, default=list)  # [{"name": str, "type": str}]
    created_at: Mapped[int] = mapped_column(Integer)
    updated_at: Mapped[int] = mapped_column(Integer)


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------
class TransactionCreate(BaseModel):
    branch: str = "master"
    txn_type: str
    primary_key: str = "id"
    records: List[Dict[str, Any]] = Field(default_factory=list)


class TransactionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    dataset_id: str
    branch: str
    txn_type: str
    primary_key: str
    row_count: int
    status: str
    seq: int
    created_at: int


class BranchCreate(BaseModel):
    name: str
    base_branch: str = "master"


class SchemaColumn(BaseModel):
    name: str
    type: str


class DatasetSchemaUpsert(BaseModel):
    columns: List[SchemaColumn] = Field(default_factory=list)


class DatasetSchemaRead(BaseModel):
    dataset_id: str
    columns: List[Dict[str, Any]]
    created_at: int
    updated_at: int


# ---------------------------------------------------------------------------
# Fold engine
# ---------------------------------------------------------------------------
def _txns_for(db: Session, dataset_id: str, branch: str) -> List[DatasetTransaction]:
    return (
        db.query(DatasetTransaction)
        .filter(DatasetTransaction.dataset_id == dataset_id, DatasetTransaction.branch == branch)
        .order_by(DatasetTransaction.seq.asc(), DatasetTransaction.created_at.asc())
        .all()
    )


def _fold(txns: List[DatasetTransaction], up_to_seq: Optional[int] = None) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for t in txns:
        if up_to_seq is not None and t.seq > up_to_seq:
            break
        pk = t.primary_key or "id"
        payload = copy.deepcopy(t.records or [])
        if t.txn_type == "SNAPSHOT":
            rows = payload
        elif t.txn_type == "APPEND":
            rows = rows + payload
        elif t.txn_type == "UPDATE":
            index = {r.get(pk): i for i, r in enumerate(rows)}
            for rec in payload:
                key = rec.get(pk)
                if key in index:
                    rows[index[key]] = {**rows[index[key]], **rec}
                else:
                    rows.append(rec)
        elif t.txn_type == "DELETE":
            keys = {rec.get(pk) for rec in payload}
            rows = [r for r in rows if r.get(pk) not in keys]
    return rows


def _next_seq(db: Session, dataset_id: str, branch: str) -> int:
    last = (
        db.query(DatasetTransaction)
        .filter(DatasetTransaction.dataset_id == dataset_id, DatasetTransaction.branch == branch)
        .order_by(DatasetTransaction.seq.desc())
        .first()
    )
    return (last.seq + 1) if last else 0


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------
@router.post("/datasets/{dataset_id}/transactions", response_model=TransactionRead, status_code=201)
def create_transaction(dataset_id: str, body: TransactionCreate, db: Session = Depends(get_db)):
    if not db.get(models.DataAsset, dataset_id):
        raise HTTPException(status_code=404, detail=f"Dataset '{dataset_id}' not found")
    if body.txn_type not in TXN_TYPES:
        raise HTTPException(status_code=422, detail=f"txn_type must be one of {sorted(TXN_TYPES)}")
    seq = _next_seq(db, dataset_id, body.branch)
    txn = DatasetTransaction(
        id=uuid.uuid4().hex, dataset_id=dataset_id, branch=body.branch, txn_type=body.txn_type,
        primary_key=body.primary_key, records=body.records, row_count=len(body.records),
        status="COMMITTED", seq=seq, created_at=_now(),
    )
    db.add(txn)
    # keep the DataAsset.records mirror in sync with the master branch view
    if body.branch == "master":
        asset = db.get(models.DataAsset, dataset_id)
        asset.records = _fold(_txns_for(db, dataset_id, "master") + [txn])
        asset.updated_at = _now()
    db.add(models_action.AuditLog(id=uuid.uuid4().hex, actor="system", event_type="dataset.transaction.committed",
                                  subject_type="dataset", subject_id=dataset_id,
                                  payload={"txn_type": body.txn_type, "branch": body.branch, "rows": len(body.records)}))
    db.commit(); db.refresh(txn)
    return txn


@router.get("/datasets/{dataset_id}/transactions", response_model=List[TransactionRead])
def list_transactions(dataset_id: str, branch: str = Query(default="master"), db: Session = Depends(get_db)):
    return _txns_for(db, dataset_id, branch)


@router.get("/datasets/{dataset_id}/view")
def dataset_view(dataset_id: str, branch: str = Query(default="master"),
                 as_of_seq: Optional[int] = Query(default=None), db: Session = Depends(get_db)):
    if not db.get(models.DataAsset, dataset_id):
        raise HTTPException(status_code=404, detail=f"Dataset '{dataset_id}' not found")
    rows = _fold(_txns_for(db, dataset_id, branch), up_to_seq=as_of_seq)
    return {"dataset_id": dataset_id, "branch": branch, "as_of_seq": as_of_seq,
            "row_count": len(rows), "rows": rows}


@router.get("/datasets/{dataset_id}/changes")
def dataset_changes(dataset_id: str, branch: str = Query(default="master"),
                    since_seq: int = Query(default=-1), db: Session = Depends(get_db)):
    """Incremental delta: rows introduced by APPEND/UPDATE transactions after `since_seq`."""
    if not db.get(models.DataAsset, dataset_id):
        raise HTTPException(status_code=404, detail=f"Dataset '{dataset_id}' not found")
    delta: List[Dict[str, Any]] = []
    latest = since_seq
    for t in _txns_for(db, dataset_id, branch):
        if t.seq > since_seq and t.txn_type in {"APPEND", "UPDATE", "SNAPSHOT"}:
            delta.extend(t.records or [])
        latest = max(latest, t.seq)
    return {"dataset_id": dataset_id, "branch": branch, "since_seq": since_seq,
            "latest_seq": latest, "change_count": len(delta), "changes": delta}


@router.post("/datasets/{dataset_id}/branches", status_code=201)
def create_branch(dataset_id: str, body: BranchCreate, db: Session = Depends(get_db)):
    if not db.get(models.DataAsset, dataset_id):
        raise HTTPException(status_code=404, detail=f"Dataset '{dataset_id}' not found")
    branch = DatasetBranch(id=uuid.uuid4().hex, dataset_id=dataset_id, name=body.name,
                           base_branch=body.base_branch, created_at=_now())
    db.add(branch)
    # seed the new branch with a SNAPSHOT of the base branch's current view
    base_rows = _fold(_txns_for(db, dataset_id, body.base_branch))
    db.add(DatasetTransaction(id=uuid.uuid4().hex, dataset_id=dataset_id, branch=body.name, txn_type="SNAPSHOT",
                              primary_key="id", records=base_rows, row_count=len(base_rows), status="COMMITTED",
                              seq=0, created_at=_now()))
    db.add(models_action.AuditLog(id=uuid.uuid4().hex, actor="system", event_type="dataset.branch.created",
                                  subject_type="dataset", subject_id=dataset_id, payload={"branch": body.name}))
    db.commit()
    return {"id": branch.id, "dataset_id": dataset_id, "name": body.name, "base_branch": body.base_branch,
            "seeded_rows": len(base_rows)}


@router.get("/datasets/{dataset_id}/branches")
def list_branches(dataset_id: str, db: Session = Depends(get_db)):
    rows = db.query(DatasetBranch).filter(DatasetBranch.dataset_id == dataset_id).all()
    return [{"id": b.id, "name": b.name, "base_branch": b.base_branch, "created_at": b.created_at} for b in rows]


# ---------------------------------------------------------------------------
# Dataset schema (declared {name, type} columns) — PUT upserts, GET returns it
# ---------------------------------------------------------------------------
@router.put("/datasets/{dataset_id}/schema", response_model=DatasetSchemaRead)
def put_dataset_schema(dataset_id: str, body: DatasetSchemaUpsert, db: Session = Depends(get_db)):
    if not db.get(models.DataAsset, dataset_id):
        raise HTTPException(status_code=404, detail=f"Dataset '{dataset_id}' not found")
    cols = [{"name": c.name, "type": c.type} for c in body.columns]
    now = _now()
    row = db.get(DatasetSchemaDef, dataset_id)
    if row:
        row.columns = cols
        row.updated_at = now
    else:
        row = DatasetSchemaDef(dataset_id=dataset_id, columns=cols, created_at=now, updated_at=now)
        db.add(row)
    db.add(models_action.AuditLog(id=uuid.uuid4().hex, actor="system", event_type="dataset.schema.upserted",
                                  subject_type="dataset", subject_id=dataset_id,
                                  payload={"column_count": len(cols)}))
    db.commit(); db.refresh(row)
    return DatasetSchemaRead(dataset_id=row.dataset_id, columns=row.columns,
                             created_at=row.created_at, updated_at=row.updated_at)


@router.get("/datasets/{dataset_id}/schema", response_model=DatasetSchemaRead)
def get_dataset_schema(dataset_id: str, db: Session = Depends(get_db)):
    row = db.get(DatasetSchemaDef, dataset_id)
    if not row:
        raise HTTPException(status_code=404, detail=f"No schema declared for dataset '{dataset_id}'")
    return DatasetSchemaRead(dataset_id=row.dataset_id, columns=row.columns,
                             created_at=row.created_at, updated_at=row.updated_at)

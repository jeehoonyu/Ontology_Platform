"""
Datasets — transactions, branches, time-travel & incremental deltas
(deep-fidelity pass 4, Data integration).

The base `DataAsset` stores a single `records` blob. Foundry datasets are
versioned: every change is an atomic **transaction** (SNAPSHOT / APPEND / UPDATE /
DELETE), changes live on **branches**, and the current rows are the fold of the
transaction log (enabling **time-travel** and **incremental** deltas). This module
adds that model additively over existing `data_assets` ids. Deterministic; local.
Rows written to `records` outside the log (`POST /data-assets`, an upload, a sync, a
pipeline run) are recorded as a SNAPSHOT the first time a transaction or a branch reads
master, so no transaction starts from rows the log never saw.

Every route resolves its dataset through `semantic_scope.asset_for`, with `edit` for a
write and `view` for a read, against the dataset's own project. The router's mount
checks only that the caller may edit somewhere, and until 2026-09-23 that was all these
routes checked: an editor in one project could read and write another project's
transactions, branches, schema and uploaded file. The child tables carry no project of
their own; a dataset id authorizes them because it is the parent's primary key.
"""
import copy
import csv
import io
import json
import time
import uuid
from typing import Optional, List, Any, Dict

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File, Form
from fastapi.responses import Response
from sqlalchemy import Index, String, Integer, JSON
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Mapped, mapped_column, Session
from pydantic import BaseModel, ConfigDict, Field

from .database import Base, get_db
from . import models, models_action, semantic_scope, storage
from .production_auth import Principal, require_permission

router = APIRouter(tags=["datasets"])

TXN_TYPES = {"SNAPSHOT", "APPEND", "UPDATE", "DELETE"}


def _now() -> int:
    return int(time.time())


class DatasetTransaction(Base):
    __tablename__ = "dataset_transactions"
    # One transaction per sequence number on a branch. `seq` was read as the branch's
    # highest plus one and written with nothing to stop two requests reading the same
    # highest, so two commits at once shared a number -- and on master the mirror kept
    # only the second. The index makes the second commit fail, and the writer retries
    # it against the log the first one left. Migration 0046 renumbers what already
    # collided before building it.
    __table_args__ = (
        Index("uq_dataset_transactions_dataset_branch_seq", "dataset_id", "branch", "seq", unique=True),
    )
    id: Mapped[str] = mapped_column(String, primary_key=True)
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
    id: Mapped[str] = mapped_column(String, primary_key=True)
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
    dataset_id: Mapped[str] = mapped_column(String, primary_key=True)
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
    """The next number on the branch, counting rows this session added and has not written.

    With autoflush off a pending row is invisible to the query, so two writes to one
    dataset in one session -- a delivery whose quarantine and output are the same asset --
    took the same number, which the unique index now refuses.
    """
    last = (
        db.query(DatasetTransaction)
        .filter(DatasetTransaction.dataset_id == dataset_id, DatasetTransaction.branch == branch)
        .order_by(DatasetTransaction.seq.desc())
        .first()
    )
    pending = [row.seq for row in db.new
               if isinstance(row, DatasetTransaction) and row.dataset_id == dataset_id
               and row.branch == branch and row.seq is not None]
    return max([(last.seq + 1) if last else 0] + [seq + 1 for seq in pending])


def _existing_branches(db: Session, dataset_id: str, names) -> set:
    """Which of `names` exist: master always; any other branch once created -- or, for a
    log written before branches had to exist, once it holds a transaction. One query per
    table for all the names, not one pair per name."""
    names = set(names)
    found = names & {"master"}
    wanted = names - found
    if wanted:
        found |= {name for (name,) in db.query(DatasetBranch.name).filter(
            DatasetBranch.dataset_id == dataset_id, DatasetBranch.name.in_(wanted)).all()}
    unseen = wanted - found
    if unseen:
        found |= {branch for (branch,) in db.query(DatasetTransaction.branch).filter(
            DatasetTransaction.dataset_id == dataset_id, DatasetTransaction.branch.in_(unseen)).distinct().all()}
    return found


# Commits that lose the race for a sequence number retry against the log the winner left.
# A handful covers any real contention; running out answers 409 rather than looping.
COMMIT_ATTEMPTS = 5


def _reconcile_master(db: Session, asset: models.DataAsset, primary_key: Optional[str]) -> List[DatasetTransaction]:
    """Master's log, with a baseline SNAPSHOT added when its fold is not the dataset's rows.

    The fold starts from nothing, so rows the log never saw were dropped by the next
    transaction: APPEND kept only the appended rows and DELETE emptied the dataset. The
    baseline is pending, not flushed: with autoflush off, a later query cannot return it
    or the caller's transaction, which is why `base + [txn]` applies each exactly once.
    """
    txns = _txns_for(db, asset.id, "master")
    live = list(asset.records or [])
    if _fold(txns) == live:
        return txns
    baseline = DatasetTransaction(
        id=uuid.uuid4().hex, dataset_id=asset.id, branch="master", txn_type="SNAPSHOT",
        primary_key=primary_key or "id", records=copy.deepcopy(live), row_count=len(live),
        status="COMMITTED", seq=(txns[-1].seq + 1) if txns else 0, created_at=_now(),
    )
    db.add(baseline)
    db.add(models_action.AuditLog(id=uuid.uuid4().hex, actor="system", event_type="dataset.transaction.baseline_recorded",
                                  subject_type="dataset", subject_id=asset.id,
                                  payload={"branch": "master", "rows": len(live), "seq": baseline.seq,
                                           "reason": "no_history" if not txns else "records_changed_outside_log"}))
    return txns + [baseline]


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------
@router.post("/datasets/{dataset_id}/transactions", response_model=TransactionRead, status_code=201)
def create_transaction(dataset_id: str, body: TransactionCreate,
                       principal: Principal = Depends(require_permission("edit")), db: Session = Depends(get_db)):
    asset = semantic_scope.asset_for(db, principal, dataset_id, "edit")
    if body.txn_type not in TXN_TYPES:
        raise HTTPException(status_code=422, detail=f"txn_type must be one of {sorted(TXN_TYPES)}")
    # A branch is created before it is written. A transaction to a name nobody created
    # used to be accepted as seq 0 of a branch that then existed only in the log.
    if body.branch not in _existing_branches(db, dataset_id, {body.branch}):
        raise HTTPException(status_code=404, detail=f"Branch '{body.branch}' not found on dataset '{dataset_id}'")
    for _attempt in range(COMMIT_ATTEMPTS):
        # Everything is built afresh each attempt: a rollback drops the pending rows and
        # expires `asset`, so its records reload with the winner's rows and the mirror
        # below folds both commits instead of keeping only the last.
        base = _reconcile_master(db, asset, body.primary_key) if body.branch == "master" else None
        if base is None:
            seq = _next_seq(db, dataset_id, body.branch)
        else:
            seq = (base[-1].seq + 1) if base else 0
        txn = DatasetTransaction(
            id=uuid.uuid4().hex, dataset_id=dataset_id, branch=body.branch, txn_type=body.txn_type,
            primary_key=body.primary_key, records=body.records, row_count=len(body.records),
            status="COMMITTED", seq=seq, created_at=_now(),
        )
        db.add(txn)
        committed = {"txn_type": body.txn_type, "branch": body.branch, "rows": len(body.records), "seq": seq}
        # keep the DataAsset.records mirror in sync with the master branch view
        if base is not None:
            asset.records = _fold(base + [txn])
            asset.updated_at = _now()
            committed["dataset_rows"] = len(asset.records)
        db.add(models_action.AuditLog(id=uuid.uuid4().hex, actor=principal.id, event_type="dataset.transaction.committed",
                                      subject_type="dataset", subject_id=dataset_id, payload=committed))
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            continue
        db.refresh(txn)
        return txn
    raise HTTPException(status_code=409, detail=f"Concurrent transactions on branch '{body.branch}' kept taking the same sequence number; retry")


@router.get("/datasets/{dataset_id}/transactions", response_model=List[TransactionRead])
def list_transactions(dataset_id: str, branch: str = Query(default="master"),
                      principal: Principal = Depends(require_permission("view")), db: Session = Depends(get_db)):
    semantic_scope.asset_for(db, principal, dataset_id, "view")
    return _txns_for(db, dataset_id, branch)


@router.get("/datasets/{dataset_id}/view")
def dataset_view(dataset_id: str, branch: str = Query(default="master"),
                 as_of_seq: Optional[int] = Query(default=None),
                 principal: Principal = Depends(require_permission("view")), db: Session = Depends(get_db)):
    semantic_scope.asset_for(db, principal, dataset_id, "view")
    rows = _fold(_txns_for(db, dataset_id, branch), up_to_seq=as_of_seq)
    return {"dataset_id": dataset_id, "branch": branch, "as_of_seq": as_of_seq,
            "row_count": len(rows), "rows": rows}


@router.get("/datasets/{dataset_id}/changes")
def dataset_changes(dataset_id: str, branch: str = Query(default="master"),
                    since_seq: int = Query(default=-1),
                    principal: Principal = Depends(require_permission("view")), db: Session = Depends(get_db)):
    """Incremental delta: rows introduced by APPEND/UPDATE transactions after `since_seq`."""
    semantic_scope.asset_for(db, principal, dataset_id, "view")
    delta: List[Dict[str, Any]] = []
    latest = since_seq
    for t in _txns_for(db, dataset_id, branch):
        if t.seq > since_seq and t.txn_type in {"APPEND", "UPDATE", "SNAPSHOT"}:
            delta.extend(t.records or [])
        latest = max(latest, t.seq)
    return {"dataset_id": dataset_id, "branch": branch, "since_seq": since_seq,
            "latest_seq": latest, "change_count": len(delta), "changes": delta}


@router.post("/datasets/{dataset_id}/branches", status_code=201)
def create_branch(dataset_id: str, body: BranchCreate,
                  principal: Principal = Depends(require_permission("edit")), db: Session = Depends(get_db)):
    asset = semantic_scope.asset_for(db, principal, dataset_id, "edit")
    # Creating a branch that exists wrote a second branch row and a second seq-0 SNAPSHOT
    # on it -- and naming `master` wrote one on master. It is refused now, and a base
    # nobody created is refused rather than seeding an empty snapshot.
    existing = _existing_branches(db, dataset_id, {body.name, body.base_branch})
    if body.name in existing:
        raise HTTPException(status_code=409, detail=f"Branch '{body.name}' already exists on dataset '{dataset_id}'")
    if body.base_branch not in existing:
        raise HTTPException(status_code=404, detail=f"Branch '{body.base_branch}' not found on dataset '{dataset_id}'")
    for _attempt in range(COMMIT_ATTEMPTS):
        branch = DatasetBranch(id=uuid.uuid4().hex, dataset_id=dataset_id, name=body.name,
                               base_branch=body.base_branch, created_at=_now())
        db.add(branch)
        # seed the new branch with a SNAPSHOT of the base branch's current view; master's
        # view is its real rows, recorded first if the log never saw them
        if body.base_branch == "master":
            base_rows = _fold(_reconcile_master(db, asset, "id"))
        else:
            base_rows = _fold(_txns_for(db, dataset_id, body.base_branch))
        db.add(DatasetTransaction(id=uuid.uuid4().hex, dataset_id=dataset_id, branch=body.name, txn_type="SNAPSHOT",
                                  primary_key="id", records=base_rows, row_count=len(base_rows), status="COMMITTED",
                                  seq=0, created_at=_now()))
        db.add(models_action.AuditLog(id=uuid.uuid4().hex, actor=principal.id, event_type="dataset.branch.created",
                                      subject_type="dataset", subject_id=dataset_id, payload={"branch": body.name}))
        try:
            db.commit()
            break
        except IntegrityError:
            db.rollback()
            # The seed's seq 0 collides only with a branch created concurrently; anything
            # else was master's baseline losing a race, which the next attempt re-reads.
            if body.name in _existing_branches(db, dataset_id, {body.name}):
                raise HTTPException(status_code=409, detail=f"Branch '{body.name}' already exists on dataset '{dataset_id}'")
    else:
        raise HTTPException(status_code=409, detail=f"Concurrent writes to dataset '{dataset_id}' kept colliding; retry")
    return {"id": branch.id, "dataset_id": dataset_id, "name": body.name, "base_branch": body.base_branch,
            "seeded_rows": len(base_rows)}


@router.get("/datasets/{dataset_id}/branches")
def list_branches(dataset_id: str, principal: Principal = Depends(require_permission("view")),
                  db: Session = Depends(get_db)):
    semantic_scope.asset_for(db, principal, dataset_id, "view")
    rows = db.query(DatasetBranch).filter(DatasetBranch.dataset_id == dataset_id).all()
    return [{"id": b.id, "name": b.name, "base_branch": b.base_branch, "created_at": b.created_at} for b in rows]


# ---------------------------------------------------------------------------
# Dataset schema (declared {name, type} columns) — PUT upserts, GET returns it
# ---------------------------------------------------------------------------
@router.put("/datasets/{dataset_id}/schema", response_model=DatasetSchemaRead)
def put_dataset_schema(dataset_id: str, body: DatasetSchemaUpsert,
                       principal: Principal = Depends(require_permission("edit")), db: Session = Depends(get_db)):
    semantic_scope.asset_for(db, principal, dataset_id, "edit")
    cols = [{"name": c.name, "type": c.type} for c in body.columns]
    now = _now()
    row = db.get(DatasetSchemaDef, dataset_id)
    if row:
        row.columns = cols
        row.updated_at = now
    else:
        row = DatasetSchemaDef(dataset_id=dataset_id, columns=cols, created_at=now, updated_at=now)
        db.add(row)
    db.add(models_action.AuditLog(id=uuid.uuid4().hex, actor=principal.id, event_type="dataset.schema.upserted",
                                  subject_type="dataset", subject_id=dataset_id,
                                  payload={"column_count": len(cols)}))
    db.commit(); db.refresh(row)
    return DatasetSchemaRead(dataset_id=row.dataset_id, columns=row.columns,
                             created_at=row.created_at, updated_at=row.updated_at)


@router.get("/datasets/{dataset_id}/schema", response_model=DatasetSchemaRead)
def get_dataset_schema(dataset_id: str, principal: Principal = Depends(require_permission("view")),
                       db: Session = Depends(get_db)):
    semantic_scope.asset_for(db, principal, dataset_id, "view")
    row = db.get(DatasetSchemaDef, dataset_id)
    if not row:
        raise HTTPException(status_code=404, detail=f"No schema declared for dataset '{dataset_id}'")
    return DatasetSchemaRead(dataset_id=row.dataset_id, columns=row.columns,
                             created_at=row.created_at, updated_at=row.updated_at)


# ---------------------------------------------------------------------------
# Real file upload/download — CSV / JSON / JSONL / Parquet -> records + schema.
# ---------------------------------------------------------------------------

def _coerce_cell(v: Any) -> Any:
    """Best-effort scalar coercion for CSV cells (bool / int / float / null / str)."""
    if v is None:
        return None
    s = str(v).strip()
    if s == "":
        return None
    low = s.lower()
    if low in ("true", "false"):
        return low == "true"
    try:
        return int(s)
    except ValueError:
        pass
    try:
        return float(s)
    except ValueError:
        pass
    return v


def _infer_asset_schema(records: List[dict]) -> Dict[str, str]:
    schema: Dict[str, str] = {}
    for rec in records:
        if not isinstance(rec, dict):
            continue
        for key, val in rec.items():
            if key in schema or val is None:
                continue
            if isinstance(val, bool):
                schema[key] = "boolean"
            elif isinstance(val, int):
                schema[key] = "integer"
            elif isinstance(val, float):
                schema[key] = "double"
            else:
                schema[key] = "string"
    return schema


def _detect_format(filename: Optional[str], override: Optional[str]) -> str:
    if override:
        return override.lower()
    name = (filename or "").lower()
    if name.endswith(".csv"):
        return "csv"
    if name.endswith((".jsonl", ".ndjson")):
        return "jsonl"
    if name.endswith((".parquet", ".pq")):
        return "parquet"
    return "json"


def _parse_upload(raw: bytes, fmt: str) -> List[dict]:
    if fmt == "csv":
        reader = csv.DictReader(io.StringIO(raw.decode("utf-8-sig")))
        return [{k: _coerce_cell(v) for k, v in row.items()} for row in reader]
    if fmt == "jsonl":
        out: List[dict] = []
        for line in raw.decode("utf-8").splitlines():
            line = line.strip()
            if line:
                out.append(json.loads(line))
        return out
    if fmt == "json":
        data = json.loads(raw.decode("utf-8"))
        if isinstance(data, list):
            return data
        if isinstance(data, dict) and isinstance(data.get("records"), list):
            return data["records"]
        if isinstance(data, dict):
            return [data]
        raise HTTPException(status_code=422, detail="JSON must be a list, {records:[...]}, or an object")
    if fmt == "parquet":
        try:
            import pyarrow.parquet as pq  # optional dependency
        except ImportError:
            raise HTTPException(status_code=422, detail="Parquet upload requires the optional 'pyarrow' package")
        return pq.read_table(io.BytesIO(raw)).to_pylist()
    raise HTTPException(status_code=422, detail=f"unsupported format '{fmt}'")


@router.post("/data-assets/{dataset_id}/upload")
async def upload_dataset_file(
    dataset_id: str,
    file: UploadFile = File(...),
    format: Optional[str] = Form(default=None),
    mode: str = Form(default="replace"),   # replace | append
    principal: Principal = Depends(require_permission("edit")),
    db: Session = Depends(get_db),
):
    """Ingest a real file (CSV/JSON/JSONL/Parquet) into a dataset: parse rows, infer
    the schema, and keep the raw file in object storage. Backward compatible with the
    inline-records model — the parsed rows land in `records` just like an API insert."""
    asset = semantic_scope.asset_for(db, principal, dataset_id, "edit")
    if mode not in ("replace", "append"):
        raise HTTPException(status_code=422, detail="mode must be 'replace' or 'append'")
    raw = await file.read()
    fmt = _detect_format(file.filename, format)
    parsed = _parse_upload(raw, fmt)
    uri = storage.put(f"datasets/{dataset_id}/{file.filename or 'upload'}", raw)

    asset.records = (list(asset.records or []) + parsed) if mode == "append" else parsed
    asset.asset_schema = _infer_asset_schema(asset.records or [])
    asset.file_ref = uri
    asset.source_format = fmt
    asset.updated_at = _now()
    db.add(models_action.AuditLog(
        id=uuid.uuid4().hex, actor=principal.id, event_type="data.asset.uploaded",
        subject_type="data_asset", subject_id=dataset_id,
        payload={"format": fmt, "records": len(parsed), "mode": mode, "bytes": len(raw)}))
    db.commit()
    return {
        "dataset_id": dataset_id, "source_format": fmt, "added": len(parsed),
        "record_count": len(asset.records or []), "columns": list((asset.asset_schema or {}).keys()),
        "file_ref": uri, "bytes": len(raw),
    }


@router.get("/data-assets/{dataset_id}/download")
def download_dataset_file(dataset_id: str, principal: Principal = Depends(require_permission("view")),
                          db: Session = Depends(get_db)):
    asset = semantic_scope.asset_for(db, principal, dataset_id, "view")
    data = storage.open_bytes(asset.file_ref)
    if data is None:
        raise HTTPException(status_code=404, detail="no uploaded file stored for this dataset")
    filename = (asset.file_ref or "download").split("/")[-1]
    return Response(content=data, media_type="application/octet-stream",
                    headers={"Content-Disposition": f'attachment; filename="{filename}"'})

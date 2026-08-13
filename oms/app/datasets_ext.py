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
import csv
import io
import json
import time
import uuid
from typing import Optional, List, Any, Dict

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File, Form
from fastapi.responses import Response
from sqlalchemy import String, Integer, JSON
from sqlalchemy.orm import Mapped, mapped_column, Session
from pydantic import BaseModel, ConfigDict, Field

from .database import Base, get_db
from . import models, models_action, storage

router = APIRouter(tags=["datasets"])

TXN_TYPES = {"SNAPSHOT", "APPEND", "UPDATE", "DELETE"}


def _now() -> int:
    return int(time.time())


class DatasetTransaction(Base):
    __tablename__ = "dataset_transactions"
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
    db: Session = Depends(get_db),
):
    """Ingest a real file (CSV/JSON/JSONL/Parquet) into a dataset: parse rows, infer
    the schema, and keep the raw file in object storage. Backward compatible with the
    inline-records model — the parsed rows land in `records` just like an API insert."""
    asset = db.get(models.DataAsset, dataset_id)
    if not asset:
        raise HTTPException(status_code=404, detail=f"DataAsset '{dataset_id}' not found")
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
        id=uuid.uuid4().hex, actor="system", event_type="data.asset.uploaded",
        subject_type="data_asset", subject_id=dataset_id,
        payload={"format": fmt, "records": len(parsed), "mode": mode, "bytes": len(raw)}))
    db.commit()
    return {
        "dataset_id": dataset_id, "source_format": fmt, "added": len(parsed),
        "record_count": len(asset.records or []), "columns": list((asset.asset_schema or {}).keys()),
        "file_ref": uri, "bytes": len(raw),
    }


@router.get("/data-assets/{dataset_id}/download")
def download_dataset_file(dataset_id: str, db: Session = Depends(get_db)):
    asset = db.get(models.DataAsset, dataset_id)
    if not asset:
        raise HTTPException(status_code=404, detail=f"DataAsset '{dataset_id}' not found")
    data = storage.open_bytes(asset.file_ref)
    if data is None:
        raise HTTPException(status_code=404, detail="no uploaded file stored for this dataset")
    filename = (asset.file_ref or "download").split("/")[-1]
    return Response(content=data, media_type="application/octet-stream",
                    headers={"Content-Disposition": f'attachment; filename="{filename}"'})

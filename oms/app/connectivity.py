"""
Foundry DATA CONNECTION module: connection sources, syncs, sync runs, and exports.
"""
from typing import Optional, List, Any, Dict
import time
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import String, Integer, JSON, Boolean, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, Session, relationship

from .database import Base, get_db
from . import models, models_action

# ---------------------------------------------------------------------------
# SQLAlchemy models
# ---------------------------------------------------------------------------

class ConnectionSource(Base):
    """External data source: JDBC, S3, SFTP, REST, or Kafka."""
    __tablename__ = "connection_sources"

    id: Mapped[str] = mapped_column(String, primary_key=True, index=True)
    display_name: Mapped[str] = mapped_column(String)
    source_type: Mapped[str] = mapped_column(String)  # jdbc/s3/sftp/rest/kafka
    config: Mapped[dict] = mapped_column(JSON, default=dict)
    uses_agent: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String, default="connected")
    created_at: Mapped[int] = mapped_column(Integer)

    syncs: Mapped[List["ConnectionSync"]] = relationship("ConnectionSync", back_populates="source")


class ConnectionSync(Base):
    """Sync configuration from a source into a DataAsset."""
    __tablename__ = "connection_syncs"

    id: Mapped[str] = mapped_column(String, primary_key=True, index=True)
    source_id: Mapped[str] = mapped_column(String, ForeignKey("connection_sources.id"), index=True)
    target_asset_id: Mapped[str] = mapped_column(String, index=True)
    mode: Mapped[str] = mapped_column(String, default="snapshot")  # snapshot/incremental
    cursor_field: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    sample_records: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[int] = mapped_column(Integer)

    source: Mapped["ConnectionSource"] = relationship("ConnectionSource", back_populates="syncs")
    runs: Mapped[List["SyncRun"]] = relationship("SyncRun", back_populates="sync")


class SyncRun(Base):
    """Execution record for a ConnectionSync."""
    __tablename__ = "sync_runs"

    id: Mapped[str] = mapped_column(String, primary_key=True, index=True)
    sync_id: Mapped[str] = mapped_column(String, ForeignKey("connection_syncs.id"), index=True)
    status: Mapped[str] = mapped_column(String, default="completed")
    records_in: Mapped[int] = mapped_column(Integer, default=0)
    records_out: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[int] = mapped_column(Integer)
    completed_at: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    sync: Mapped["ConnectionSync"] = relationship("ConnectionSync", back_populates="runs")


class ConnectionExport(Base):
    """Export configuration from a DataAsset to an external sink."""
    __tablename__ = "connection_exports"

    id: Mapped[str] = mapped_column(String, primary_key=True, index=True)
    source_asset_id: Mapped[str] = mapped_column(String, index=True)
    destination: Mapped[str] = mapped_column(String)
    format: Mapped[str] = mapped_column(String, default="csv")  # csv/json/parquet
    created_at: Mapped[int] = mapped_column(Integer)


class ConnectionExportCheckpoint(Base):
    """
    Delta checkpoint (high-water-mark) for an export. Records how many rows of the
    source asset have already been exported so a subsequent delta=true run only
    emits rows appended since the last checkpoint. Stored per export id.
    """
    __tablename__ = "connection_export_checkpoints"

    export_id: Mapped[str] = mapped_column(String, primary_key=True, index=True)
    last_exported_count: Mapped[int] = mapped_column(Integer, default=0)
    runs: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[int] = mapped_column(Integer)


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------

class ConnectionSourceCreate(BaseModel):
    id: Optional[str] = None
    display_name: str
    source_type: str = Field(..., pattern="^(jdbc|s3|sftp|rest|kafka)$")
    config: Dict[str, Any] = Field(default_factory=dict)
    uses_agent: bool = False
    status: str = "connected"


class ConnectionSourceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    display_name: str
    source_type: str
    config: Dict[str, Any]
    uses_agent: bool
    status: str
    created_at: int


class ConnectionSyncCreate(BaseModel):
    id: Optional[str] = None
    target_asset_id: str
    mode: str = Field(default="snapshot", pattern="^(snapshot|incremental)$")
    cursor_field: Optional[str] = None
    sample_records: List[Any] = Field(default_factory=list)


class ConnectionSyncRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    source_id: str
    target_asset_id: str
    mode: str
    cursor_field: Optional[str]
    sample_records: List[Any]
    created_at: int


class SyncRunRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    sync_id: str
    status: str
    records_in: int
    records_out: int
    created_at: int
    completed_at: Optional[int]


class ConnectionExportCreate(BaseModel):
    id: Optional[str] = None
    source_asset_id: str
    destination: str
    format: str = Field(default="csv", pattern="^(csv|json|parquet)$")


class ConnectionExportRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    source_asset_id: str
    destination: str
    format: str
    created_at: int


# ---------------------------------------------------------------------------
# Source connection validation + schema inference helpers
# ---------------------------------------------------------------------------

# Required config keys per source_type. Each entry is a list of requirements;
# a requirement is either a single key (str) that must be present, or a tuple of
# alternative keys where at least one must be present (e.g. password OR private_key).
REQUIRED_CONFIG_KEYS: Dict[str, List[Any]] = {
    "jdbc": ["jdbc_url", "driver_class"],
    "s3": ["bucket", "region"],
    "sftp": ["host", "username", ("password", "private_key")],
    "rest": ["base_url"],
    "kafka": ["bootstrap_servers", "topic"],
}


def _validate_source_config(source_type: str, config: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Deterministic per-key validation. Returns one check entry per requirement of
    the given source_type. A check passes when the required key (or one of the
    alternatives) is present and non-empty in config.
    """
    cfg = config or {}
    checks: List[Dict[str, Any]] = []
    for req in REQUIRED_CONFIG_KEYS.get(source_type, []):
        if isinstance(req, tuple):
            present = any(cfg.get(k) not in (None, "", [], {}) for k in req)
            label = " | ".join(req)
        else:
            present = cfg.get(req) not in (None, "", [], {})
            label = req
        checks.append({
            "key": label,
            "required": True,
            "present": present,
            "message": "ok" if present else f"missing required config key: {label}",
        })
    return checks


# Inference order matters: bool must be checked before int (bool is an int subclass).
def _infer_type(value: Any) -> str:
    if value is None:
        return "string"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "double"
    if isinstance(value, (list, dict)):
        return "json"
    return "string"


def _infer_schema(records: List[Any]) -> List[Dict[str, str]]:
    """
    Infer a dataset schema (ordered list of {name, type}) from sample records.
    Column order follows first appearance; a column's type is taken from the first
    record where it is non-null (falling back to 'string').
    """
    columns: List[str] = []
    types: Dict[str, str] = {}
    for rec in records or []:
        if not isinstance(rec, dict):
            continue
        for k, v in rec.items():
            if k not in types:
                columns.append(k)
                types[k] = _infer_type(v)
            elif types[k] == "string" and v is not None:
                # upgrade a placeholder string type once a typed value is seen
                inferred = _infer_type(v)
                if inferred != "string":
                    types[k] = inferred
    return [{"name": c, "type": types[c]} for c in columns]


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

router = APIRouter(tags=["connectivity"])


# --- Sources ---

@router.post("/connections/sources", response_model=ConnectionSourceRead)
def create_source(body: ConnectionSourceCreate, db: Session = Depends(get_db)):
    row = ConnectionSource(
        id=body.id or uuid.uuid4().hex,
        display_name=body.display_name,
        source_type=body.source_type,
        config=body.config,
        uses_agent=body.uses_agent,
        status=body.status,
        created_at=int(time.time()),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@router.get("/connections/sources", response_model=List[ConnectionSourceRead])
def list_sources(db: Session = Depends(get_db)):
    return db.query(ConnectionSource).all()


@router.get("/connections/sources/{source_id}", response_model=ConnectionSourceRead)
def get_source(source_id: str, db: Session = Depends(get_db)):
    row = db.query(ConnectionSource).filter(ConnectionSource.id == source_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Source not found")
    return row


@router.post("/connections/sources/{source_id}/test")
def test_source(source_id: str, actor: str = Query(default="system"), db: Session = Depends(get_db)):
    """
    Deterministic connection validation. Verifies that the required config keys for
    the source's source_type are present; the connection is reported ok only when
    every required-key check passes. Faithful to Foundry's "test connection" step
    that surfaces connection/credential issues before a source can be explored.
    """
    source = db.query(ConnectionSource).filter(ConnectionSource.id == source_id).first()
    if not source:
        raise HTTPException(status_code=404, detail="Source not found")

    checks = _validate_source_config(source.source_type, source.config or {})
    ok = all(c["present"] for c in checks)
    missing = [c["key"] for c in checks if not c["present"]]

    db.add(models_action.AuditLog(
        id=uuid.uuid4().hex,
        actor=actor,
        event_type="connection.source.tested",
        subject_type="connection_source",
        subject_id=source_id,
        payload={"ok": ok, "missing": missing, "source_type": source.source_type},
    ))
    db.commit()

    return {
        "source_id": source_id,
        "source_type": source.source_type,
        "ok": ok,
        "missing": missing,
        "checks": checks,
    }


@router.get("/connections/sources/{source_id}/schema")
def get_source_schema(source_id: str, db: Session = Depends(get_db)):
    """
    Infer a tabular schema (column names + inferred base types) for a source. Sample
    rows are taken from the source's syncs' sample_records when available, otherwise
    from a 'sample_records' / 'sample' list embedded in the source config.
    """
    source = db.query(ConnectionSource).filter(ConnectionSource.id == source_id).first()
    if not source:
        raise HTTPException(status_code=404, detail="Source not found")

    samples: List[Any] = []
    syncs = db.query(ConnectionSync).filter(ConnectionSync.source_id == source_id).all()
    for s in syncs:
        if s.sample_records:
            samples.extend(s.sample_records)
    if not samples:
        cfg = source.config or {}
        cfg_samples = cfg.get("sample_records") or cfg.get("sample") or []
        if isinstance(cfg_samples, list):
            samples.extend(cfg_samples)

    schema = _infer_schema(samples)
    return {
        "source_id": source_id,
        "source_type": source.source_type,
        "sample_count": len(samples),
        "schema": schema,
    }


# --- Syncs ---

@router.post("/connections/sources/{source_id}/syncs", response_model=ConnectionSyncRead)
def create_sync(source_id: str, body: ConnectionSyncCreate, db: Session = Depends(get_db)):
    source = db.query(ConnectionSource).filter(ConnectionSource.id == source_id).first()
    if not source:
        raise HTTPException(status_code=404, detail="Source not found")
    row = ConnectionSync(
        id=body.id or uuid.uuid4().hex,
        source_id=source_id,
        target_asset_id=body.target_asset_id,
        mode=body.mode,
        cursor_field=body.cursor_field,
        sample_records=body.sample_records,
        created_at=int(time.time()),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@router.get("/connections/syncs", response_model=List[ConnectionSyncRead])
def list_syncs(source_id: Optional[str] = Query(None), db: Session = Depends(get_db)):
    q = db.query(ConnectionSync)
    if source_id:
        q = q.filter(ConnectionSync.source_id == source_id)
    return q.all()


@router.post("/connections/syncs/{sync_id}/run", response_model=SyncRunRead)
def run_sync(sync_id: str, actor: str = Query(default="system"), db: Session = Depends(get_db)):
    sync = db.query(ConnectionSync).filter(ConnectionSync.id == sync_id).first()
    if not sync:
        raise HTTPException(status_code=404, detail="Sync not found")

    # Append sample_records into the target DataAsset
    asset = db.query(models.DataAsset).filter(models.DataAsset.id == sync.target_asset_id).first()
    records_written = 0
    if asset is not None and sync.sample_records:
        current = list(asset.records) if asset.records else []
        current.extend(sync.sample_records)
        asset.records = current
        asset.updated_at = int(time.time())
        records_written = len(sync.sample_records)

    now = int(time.time())
    run = SyncRun(
        id=uuid.uuid4().hex,
        sync_id=sync_id,
        status="completed",
        records_in=len(sync.sample_records),
        records_out=records_written,
        created_at=now,
        completed_at=now,
    )
    db.add(run)

    db.add(models_action.AuditLog(
        id=uuid.uuid4().hex,
        actor=actor,
        event_type="sync_run",
        subject_type="connection_sync",
        subject_id=sync_id,
        payload={"records_in": run.records_in, "records_out": run.records_out, "target_asset_id": sync.target_asset_id},
    ))
    db.commit()
    db.refresh(run)
    return run


# --- Exports ---

@router.post("/connections/exports", response_model=ConnectionExportRead)
def create_export(body: ConnectionExportCreate, db: Session = Depends(get_db)):
    row = ConnectionExport(
        id=body.id or uuid.uuid4().hex,
        source_asset_id=body.source_asset_id,
        destination=body.destination,
        format=body.format,
        created_at=int(time.time()),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@router.get("/connections/exports", response_model=List[ConnectionExportRead])
def list_exports(db: Session = Depends(get_db)):
    return db.query(ConnectionExport).all()


@router.post("/connections/exports/{export_id}/run")
def run_export(
    export_id: str,
    actor: str = Query(default="system"),
    delta: bool = Query(default=False),
    db: Session = Depends(get_db),
):
    """
    Run an export. By default a full export of the source asset's current rows.

    DELTA checkpointing (opt-in via delta=true): each run records a checkpoint of
    how many rows have been exported (high-water-mark on the source asset's row
    count). A subsequent delta=true run exports only the rows appended since the
    last checkpoint, advancing the checkpoint. The default (delta omitted/false)
    path is unchanged and does NOT read or write a checkpoint, preserving existing
    behavior exactly.
    """
    export = db.query(ConnectionExport).filter(ConnectionExport.id == export_id).first()
    if not export:
        raise HTTPException(status_code=404, detail="Export not found")

    asset = db.query(models.DataAsset).filter(models.DataAsset.id == export.source_asset_id).first()
    all_records = list(asset.records) if asset and asset.records else []
    total_rows = len(all_records)

    if not delta:
        # ---- existing full-export behavior (UNCHANGED) ----
        db.add(models_action.AuditLog(
            id=uuid.uuid4().hex,
            actor=actor,
            event_type="export_run",
            subject_type="connection_export",
            subject_id=export_id,
            payload={"rows": total_rows, "destination": export.destination, "format": export.format},
        ))
        db.commit()
        return {"rows": total_rows, "destination": export.destination,
                "format": export.format, "export_id": export_id}

    # ---- delta export with checkpoint ----
    checkpoint = db.query(ConnectionExportCheckpoint).filter(
        ConnectionExportCheckpoint.export_id == export_id
    ).first()
    previous_count = checkpoint.last_exported_count if checkpoint else 0
    # guard against the source asset shrinking (e.g. snapshot replace)
    start = min(previous_count, total_rows)
    delta_rows = all_records[start:]
    exported = len(delta_rows)
    now = int(time.time())

    if checkpoint:
        checkpoint.last_exported_count = total_rows
        checkpoint.runs += 1
        checkpoint.updated_at = now
    else:
        checkpoint = ConnectionExportCheckpoint(
            export_id=export_id,
            last_exported_count=total_rows,
            runs=1,
            updated_at=now,
        )
        db.add(checkpoint)

    db.add(models_action.AuditLog(
        id=uuid.uuid4().hex,
        actor=actor,
        event_type="export_run",
        subject_type="connection_export",
        subject_id=export_id,
        payload={"rows": exported, "delta": True, "previous_checkpoint": previous_count,
                 "new_checkpoint": total_rows, "destination": export.destination, "format": export.format},
    ))
    db.commit()

    return {
        "export_id": export_id,
        "delta": True,
        "rows": exported,
        "previous_checkpoint": previous_count,
        "new_checkpoint": total_rows,
        "total_rows": total_rows,
        "destination": export.destination,
        "format": export.format,
        "delta_records": delta_rows,
    }


@router.get("/connections/exports/{export_id}/checkpoint")
def get_export_checkpoint(export_id: str, db: Session = Depends(get_db)):
    """Return the current delta checkpoint (high-water-mark) for an export."""
    export = db.query(ConnectionExport).filter(ConnectionExport.id == export_id).first()
    if not export:
        raise HTTPException(status_code=404, detail="Export not found")
    checkpoint = db.query(ConnectionExportCheckpoint).filter(
        ConnectionExportCheckpoint.export_id == export_id
    ).first()
    if not checkpoint:
        return {"export_id": export_id, "last_exported_count": 0, "runs": 0}
    return {
        "export_id": export_id,
        "last_exported_count": checkpoint.last_exported_count,
        "runs": checkpoint.runs,
        "updated_at": checkpoint.updated_at,
    }

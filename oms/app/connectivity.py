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
from . import imports_ops, models, models_action, ops_control, tenancy
from .production_auth import Principal, require_permission

# ---------------------------------------------------------------------------
# SQLAlchemy models
# ---------------------------------------------------------------------------

class ConnectionSource(Base):
    """External data source: JDBC, S3, SFTP, REST, or Kafka."""
    __tablename__ = "connection_sources"

    id: Mapped[str] = mapped_column(String, primary_key=True, index=True)
    project_id: Mapped[str] = mapped_column(String, default="default", index=True)
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
    project_id: Mapped[str] = mapped_column(String, default="default", index=True)
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
    project_id: Mapped[str] = mapped_column(String, default="default", index=True)
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
    project_id: str = "default"
    display_name: str
    source_type: str = Field(..., pattern="^(jdbc|s3|sftp|rest|kafka)$")
    config: Dict[str, Any] = Field(default_factory=dict)
    uses_agent: bool = False
    status: str = "connected"


class ConnectionSourceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    project_id: str
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
    project_id: str
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
    project_id: str = "default"
    source_asset_id: str
    destination: str
    format: str = Field(default="csv", pattern="^(csv|json|parquet)$")


class ConnectionExportRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    project_id: str
    source_asset_id: str
    destination: str
    format: str
    created_at: int


class SourcePreviewRequest(BaseModel):
    limit: int = Field(default=25, ge=1, le=500)
    sample_records: Optional[List[Dict[str, Any]]] = None


class SourceGenerateImportJobRequest(BaseModel):
    id: Optional[str] = None
    display_name: Optional[str] = None
    target_dataset_id: Optional[str] = None
    template: Optional[str] = None
    limit: int = Field(default=500, ge=1, le=10000)
    actor: str = "workspace"


class SyncValidateRequest(BaseModel):
    require_target_asset: bool = True
    sample_records: Optional[List[Dict[str, Any]]] = None


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


def _source_or_404(db: Session, source_id: str, principal: Optional[Principal] = None, permission: str = "view") -> ConnectionSource:
    source = db.query(ConnectionSource).filter(ConnectionSource.id == source_id).first()
    if not source:
        raise HTTPException(status_code=404, detail="Source not found")
    if principal:
        tenancy.assert_project_permission(db, principal, source.project_id, permission)
    return source


def _sync_or_404(db: Session, sync_id: str, principal: Optional[Principal] = None, permission: str = "view") -> ConnectionSync:
    sync = db.query(ConnectionSync).filter(ConnectionSync.id == sync_id).first()
    if not sync:
        raise HTTPException(status_code=404, detail="Sync not found")
    if principal:
        tenancy.assert_project_permission(db, principal, sync.project_id, permission)
    return sync


def _source_sample_records(db: Session, source: ConnectionSource, limit: int = 25, override: Optional[List[Dict[str, Any]]] = None) -> List[Dict[str, Any]]:
    samples: List[Any] = []
    if override is not None:
        samples.extend(override)
    if not samples:
        cfg = source.config or {}
        cfg_samples = cfg.get("sample_records") or cfg.get("sample") or cfg.get("preview_records") or []
        if isinstance(cfg_samples, list):
            samples.extend(cfg_samples)
    if not samples:
        for sync in db.query(ConnectionSync).filter(ConnectionSync.source_id == source.id).all():
            if sync.sample_records:
                samples.extend(sync.sample_records)
    rows = [dict(row) for row in samples if isinstance(row, dict)]
    return rows[:limit]


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

router = APIRouter(tags=["connectivity"])


# --- Sources ---

@router.post("/connections/sources", response_model=ConnectionSourceRead)
def create_source(body: ConnectionSourceCreate, principal: Principal = Depends(require_permission("edit")), db: Session = Depends(get_db)):
    tenancy.assert_project_permission(db, principal, body.project_id, "edit")
    row = ConnectionSource(
        id=body.id or uuid.uuid4().hex,
        project_id=body.project_id,
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
def list_sources(project_id: Optional[str] = None, principal: Principal = Depends(require_permission("view")), db: Session = Depends(get_db)):
    query = db.query(ConnectionSource)
    if project_id:
        tenancy.assert_project_permission(db, principal, project_id, "view")
        query = query.filter(ConnectionSource.project_id == project_id)
    else:
        accessible = tenancy.accessible_project_ids(db, principal)
        if accessible is not None:
            query = query.filter(ConnectionSource.project_id.in_(accessible))
    return query.all()


@router.get("/connections/sources/{source_id}", response_model=ConnectionSourceRead)
def get_source(source_id: str, principal: Principal = Depends(require_permission("view")), db: Session = Depends(get_db)):
    return _source_or_404(db, source_id, principal)


@router.post("/connections/sources/{source_id}/test")
def test_source(source_id: str, actor: str = Query(default="system"), principal: Principal = Depends(require_permission("execute")), db: Session = Depends(get_db)):
    """
    Deterministic connection validation. Verifies that the required config keys for
    the source's source_type are present; the connection is reported ok only when
    every required-key check passes. Faithful to Foundry's "test connection" step
    that surfaces connection/credential issues before a source can be explored.
    """
    source = _source_or_404(db, source_id, principal, "execute")

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
def get_source_schema(source_id: str, principal: Principal = Depends(require_permission("view")), db: Session = Depends(get_db)):
    """
    Infer a tabular schema (column names + inferred base types) for a source. Sample
    rows are taken from the source's syncs' sample_records when available, otherwise
    from a 'sample_records' / 'sample' list embedded in the source config.
    """
    source = _source_or_404(db, source_id, principal)

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


@router.post("/connections/sources/{source_id}/preview")
def preview_source(source_id: str, body: SourcePreviewRequest = SourcePreviewRequest(), principal: Principal = Depends(require_permission("view")), db: Session = Depends(get_db)):
    source = _source_or_404(db, source_id, principal)
    checks = _validate_source_config(source.source_type, source.config or {})
    rows = _source_sample_records(db, source, body.limit, body.sample_records)
    schema = _infer_schema(rows)
    ok = all(check["present"] for check in checks)
    return {
        "source_id": source.id,
        "source_type": source.source_type,
        "status": "READY" if ok else "WARN",
        "checks": checks,
        "schema": schema,
        "record_count": len(rows),
        "preview_rows": rows,
    }


@router.post("/connections/sources/{source_id}/generate-import-job")
def generate_import_job_from_source(source_id: str, body: SourceGenerateImportJobRequest = SourceGenerateImportJobRequest(), principal: Principal = Depends(require_permission("edit")), db: Session = Depends(get_db)):
    source = _source_or_404(db, source_id, principal, "edit")
    rows = _source_sample_records(db, source, body.limit)
    if not rows:
        raise HTTPException(status_code=400, detail="Source has no sample records to import")
    job = imports_ops._create_job(
        db,
        source_type=f"connection:{source.source_type}",
        filename=f"{source.id}.connection",
        display_name=body.display_name or f"{source.display_name} Preview Import",
        target_dataset_id=body.target_dataset_id,
        records=rows,
        errors=[],
        requested_id=body.id,
        actor=body.actor,
    )
    if body.template:
        validation = imports_ops._validate_job_template(job, body.template)
        imports_ops._apply_validation(job, validation)
        imports_ops._audit(db, body.actor, "import.job.validated", "import_job", job.id, validation)
    models_action_row = models_action.AuditLog(
        id=uuid.uuid4().hex,
        actor=body.actor,
        event_type="connection.source.generated_import_job",
        subject_type="connection_source",
        subject_id=source.id,
        payload={"import_job_id": job.id, "record_count": len(rows), "template": body.template},
    )
    db.add(models_action_row)
    ops_control.record_ops_event(
        db,
        source="connectivity",
        event_type="connection.source.generated_import_job",
        severity="info",
        title=f"Connection source generated import job {job.id}",
        subject_type="import_job",
        subject_id=job.id,
        payload={"source_id": source.id, "record_count": len(rows)},
    )
    db.commit()
    db.refresh(job)
    return {
        "status": "IMPORT_JOB_CREATED",
        "source_id": source.id,
        "job": imports_ops._job_dict(job),
    }


# --- Syncs ---

@router.post("/connections/sources/{source_id}/syncs", response_model=ConnectionSyncRead)
def create_sync(source_id: str, body: ConnectionSyncCreate, principal: Principal = Depends(require_permission("edit")), db: Session = Depends(get_db)):
    source = _source_or_404(db, source_id, principal, "edit")
    row = ConnectionSync(
        id=body.id or uuid.uuid4().hex,
        project_id=source.project_id,
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
def list_syncs(source_id: Optional[str] = Query(None), project_id: Optional[str] = None, principal: Principal = Depends(require_permission("view")), db: Session = Depends(get_db)):
    q = db.query(ConnectionSync)
    if project_id:
        tenancy.assert_project_permission(db, principal, project_id, "view")
        q = q.filter(ConnectionSync.project_id == project_id)
    else:
        accessible = tenancy.accessible_project_ids(db, principal)
        if accessible is not None:
            q = q.filter(ConnectionSync.project_id.in_(accessible))
    if source_id:
        q = q.filter(ConnectionSync.source_id == source_id)
    return q.all()


@router.post("/connections/syncs/{sync_id}/run", response_model=SyncRunRead)
def run_sync(sync_id: str, actor: str = Query(default="system"), principal: Principal = Depends(require_permission("execute")), db: Session = Depends(get_db)):
    sync = _sync_or_404(db, sync_id, principal, "execute")

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
    ops_control.record_ops_event(
        db,
        source="connectivity",
        event_type="connection.sync.run",
        severity="info" if records_written == len(sync.sample_records) else "warn",
        title=f"Connection sync run {sync_id}",
        subject_type="connection_sync",
        subject_id=sync_id,
        payload={"records_in": run.records_in, "records_out": run.records_out, "target_asset_id": sync.target_asset_id},
    )
    db.commit()
    db.refresh(run)
    return run


@router.post("/connections/syncs/{sync_id}/validate")
def validate_sync(sync_id: str, body: SyncValidateRequest = SyncValidateRequest(), principal: Principal = Depends(require_permission("execute")), db: Session = Depends(get_db)):
    sync = _sync_or_404(db, sync_id, principal, "execute")
    source = _source_or_404(db, sync.source_id, principal, "execute")
    source_checks = _validate_source_config(source.source_type, source.config or {})
    target = db.query(models.DataAsset).filter(models.DataAsset.id == sync.target_asset_id).first()
    records = body.sample_records if body.sample_records is not None else sync.sample_records
    schema = _infer_schema(records or [])
    checks = [
        {"name": "source config", "status": "PASS" if all(row["present"] for row in source_checks) else "WARN", "details": source_checks},
        {"name": "target dataset", "status": "PASS" if target is not None or not body.require_target_asset else "FAIL", "target_asset_id": sync.target_asset_id},
        {"name": "sample records", "status": "PASS" if records else "WARN", "record_count": len(records or [])},
        {"name": "incremental cursor", "status": "PASS" if sync.mode != "incremental" or bool(sync.cursor_field) else "FAIL", "cursor_field": sync.cursor_field},
    ]
    status = "FAIL" if any(check["status"] == "FAIL" for check in checks) else ("WARN" if any(check["status"] == "WARN" for check in checks) else "PASS")
    db.add(models_action.AuditLog(
        id=uuid.uuid4().hex,
        actor="workspace",
        event_type="connection.sync.validated",
        subject_type="connection_sync",
        subject_id=sync.id,
        payload={"status": status, "checks": checks},
    ))
    ops_control.record_ops_event(
        db,
        source="connectivity",
        event_type="connection.sync.validated",
        severity="error" if status == "FAIL" else ("warn" if status == "WARN" else "info"),
        title=f"Connection sync validation {status}: {sync.id}",
        subject_type="connection_sync",
        subject_id=sync.id,
        payload={"checks": checks},
    )
    db.commit()
    return {
        "sync_id": sync.id,
        "source_id": source.id,
        "target_asset_id": sync.target_asset_id,
        "status": status,
        "schema": schema,
        "checks": checks,
    }


# --- Exports ---

@router.post("/connections/exports", response_model=ConnectionExportRead)
def create_export(body: ConnectionExportCreate, principal: Principal = Depends(require_permission("edit")), db: Session = Depends(get_db)):
    tenancy.assert_project_permission(db, principal, body.project_id, "edit")
    row = ConnectionExport(
        id=body.id or uuid.uuid4().hex,
        project_id=body.project_id,
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
def list_exports(project_id: Optional[str] = None, principal: Principal = Depends(require_permission("view")), db: Session = Depends(get_db)):
    query = db.query(ConnectionExport)
    if project_id:
        tenancy.assert_project_permission(db, principal, project_id, "view")
        query = query.filter(ConnectionExport.project_id == project_id)
    else:
        accessible = tenancy.accessible_project_ids(db, principal)
        if accessible is not None:
            query = query.filter(ConnectionExport.project_id.in_(accessible))
    return query.all()


@router.post("/connections/exports/{export_id}/run")
def run_export(
    export_id: str,
    actor: str = Query(default="system"),
    delta: bool = Query(default=False),
    principal: Principal = Depends(require_permission("execute")),
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
    tenancy.assert_project_permission(db, principal, export.project_id, "execute")

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
def get_export_checkpoint(export_id: str, principal: Principal = Depends(require_permission("view")), db: Session = Depends(get_db)):
    """Return the current delta checkpoint (high-water-mark) for an export."""
    export = db.query(ConnectionExport).filter(ConnectionExport.id == export_id).first()
    if not export:
        raise HTTPException(status_code=404, detail="Export not found")
    tenancy.assert_project_permission(db, principal, export.project_id, "view")
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

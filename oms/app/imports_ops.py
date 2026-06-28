"""
Local deterministic data import jobs.

This module gives the demo a practical path from user-provided CSV/JSON into
the existing DataAsset runtime. Imports are stored as reviewable jobs first so
the UI can show schema inference, preview rows, validation errors, audit logs,
and a deliberate "promote to dataset" step.
"""
from __future__ import annotations

import csv
import io
import json
import re
import time
import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import Integer, JSON, String
from sqlalchemy.orm import Mapped, Session, mapped_column

from . import models, models_action, ops_control
from .database import Base, get_db

router = APIRouter(tags=["imports"])


class ImportJob(Base):
    __tablename__ = "import_jobs"

    id: Mapped[str] = mapped_column(String, primary_key=True, index=True)
    source_type: Mapped[str] = mapped_column(String, index=True)
    filename: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    display_name: Mapped[str] = mapped_column(String)
    target_dataset_id: Mapped[Optional[str]] = mapped_column(String, nullable=True, index=True)
    status: Mapped[str] = mapped_column(String, default="READY", index=True)
    inferred_schema: Mapped[dict] = mapped_column(JSON, default=dict)
    preview_rows: Mapped[list] = mapped_column(JSON, default=list)
    validation_errors: Mapped[list] = mapped_column(JSON, default=list)
    records: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[int] = mapped_column(Integer)
    updated_at: Mapped[int] = mapped_column(Integer)
    promoted_at: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)


class CsvImportRequest(BaseModel):
    id: Optional[str] = None
    filename: Optional[str] = None
    display_name: Optional[str] = None
    content: str
    delimiter: str = ","
    target_dataset_id: Optional[str] = None


class JsonImportRequest(BaseModel):
    id: Optional[str] = None
    filename: Optional[str] = None
    display_name: Optional[str] = None
    content: Optional[str] = None
    records: Optional[List[Dict[str, Any]]] = None
    target_dataset_id: Optional[str] = None


class PromoteImportRequest(BaseModel):
    dataset_id: Optional[str] = None
    display_name: Optional[str] = None
    description: Optional[str] = None
    actor: str = "workspace"
    replace: bool = True


def _now() -> int:
    return int(time.time())


def _slug(value: str, fallback: str = "imported_dataset") -> str:
    text = re.sub(r"[^a-zA-Z0-9]+", "_", value or "").strip("_").lower()
    return text or fallback


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def _ensure_tables(db: Session) -> None:
    ImportJob.__table__.create(bind=db.get_bind(), checkfirst=True)
    ops_control._ensure_tables(db)


def _audit(db: Session, actor: str, event_type: str, subject_type: str, subject_id: str, payload: Dict[str, Any]) -> None:
    db.add(models_action.AuditLog(
        id=uuid.uuid4().hex,
        actor=actor,
        event_type=event_type,
        subject_type=subject_type,
        subject_id=subject_id,
        payload=payload,
    ))


def _field_order(records: List[Dict[str, Any]]) -> List[str]:
    fields: List[str] = []
    seen = set()
    for row in records:
        for key in row.keys():
            if key not in seen:
                seen.add(key)
                fields.append(str(key))
    return fields


def _jsonable_key(value: Any) -> str:
    try:
        return json.dumps(value, sort_keys=True, default=str)
    except TypeError:
        return str(value)


def _value_type(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int) and not isinstance(value, bool):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    return "string"


def _merge_types(types: List[str]) -> str:
    concrete = {item for item in types if item != "null"}
    if not concrete:
        return "string"
    if concrete <= {"integer"}:
        return "integer"
    if concrete <= {"integer", "number"}:
        return "number"
    if len(concrete) == 1:
        return next(iter(concrete))
    return "string"


def _infer_schema(records: List[Dict[str, Any]]) -> Dict[str, Any]:
    fields = _field_order(records)
    field_specs = []
    for field in fields:
        values = [(row or {}).get(field) for row in records]
        non_null = [value for value in values if value is not None]
        field_specs.append({
            "name": field,
            "type": _merge_types([_value_type(value) for value in values]),
            "missing_count": len(values) - len(non_null),
            "unique_count": len({_jsonable_key(value) for value in non_null}),
            "sample_values": non_null[:5],
        })
    return {
        "fields": field_specs,
        "field_count": len(field_specs),
        "record_count": len(records),
    }


def _convert_scalar(value: Any) -> Any:
    if value is None or not isinstance(value, str):
        return value
    text = value.strip()
    if text == "":
        return None
    lowered = text.lower()
    if lowered in {"true", "false"}:
        return lowered == "true"
    if re.fullmatch(r"-?\d+", text):
        unsigned = text[1:] if text.startswith("-") else text
        if not (len(unsigned) > 1 and unsigned.startswith("0")):
            try:
                return int(text)
            except ValueError:
                return text
    if re.fullmatch(r"-?(?:\d+\.\d+|\d+\.\d*|\.\d+)", text):
        try:
            return float(text)
        except ValueError:
            return text
    return text


def _parse_csv(content: str, delimiter: str = ",") -> tuple[List[Dict[str, Any]], List[Dict[str, str]]]:
    errors: List[Dict[str, str]] = []
    if not content.strip():
        return [], [{"code": "EMPTY_CONTENT", "message": "CSV content is empty."}]
    if len(delimiter) != 1:
        return [], [{"code": "INVALID_DELIMITER", "message": "CSV delimiter must be one character."}]
    try:
        reader = csv.DictReader(io.StringIO(content), delimiter=delimiter)
        if not reader.fieldnames:
            return [], [{"code": "MISSING_HEADER", "message": "CSV header row is required."}]
        fieldnames = [str(field or "").strip() for field in reader.fieldnames]
        if any(not field for field in fieldnames):
            errors.append({"code": "EMPTY_HEADER", "message": "CSV header names cannot be empty."})
        if len(set(fieldnames)) != len(fieldnames):
            errors.append({"code": "DUPLICATE_HEADER", "message": "CSV header names must be unique."})
        rows = []
        for index, raw in enumerate(reader, start=2):
            row: Dict[str, Any] = {}
            for original, clean in zip(reader.fieldnames or [], fieldnames):
                row[clean] = _convert_scalar(raw.get(original))
            overflow = raw.get(None)
            if overflow:
                errors.append({"code": "ROW_WIDTH", "message": f"Row {index} has extra values."})
            rows.append(row)
        if not rows:
            errors.append({"code": "NO_RECORDS", "message": "CSV contains no data rows."})
        return rows, errors
    except csv.Error as exc:
        return [], [{"code": "CSV_PARSE_ERROR", "message": str(exc)}]


def _parse_json(body: JsonImportRequest) -> tuple[List[Dict[str, Any]], List[Dict[str, str]]]:
    errors: List[Dict[str, str]] = []
    payload: Any = body.records
    if payload is None:
        if not body.content or not body.content.strip():
            return [], [{"code": "EMPTY_CONTENT", "message": "JSON content or records are required."}]
        try:
            payload = json.loads(body.content)
        except json.JSONDecodeError as exc:
            return [], [{"code": "JSON_PARSE_ERROR", "message": str(exc)}]
    if isinstance(payload, dict) and isinstance(payload.get("records"), list):
        payload = payload["records"]
    elif isinstance(payload, dict):
        payload = [payload]
    if not isinstance(payload, list):
        return [], [{"code": "INVALID_JSON_SHAPE", "message": "JSON import must be an object, an array of objects, or {records:[...]}."}]
    rows: List[Dict[str, Any]] = []
    for index, row in enumerate(payload):
        if not isinstance(row, dict):
            errors.append({"code": "NON_OBJECT_ROW", "message": f"Row {index + 1} is not an object."})
            continue
        rows.append(dict(row))
    if not rows:
        errors.append({"code": "NO_RECORDS", "message": "JSON contains no object records."})
    return rows, errors


def _job_dict(row: ImportJob, include_records: bool = False) -> Dict[str, Any]:
    payload = {
        "id": row.id,
        "source_type": row.source_type,
        "filename": row.filename,
        "display_name": row.display_name,
        "target_dataset_id": row.target_dataset_id,
        "status": row.status,
        "schema": row.inferred_schema or {},
        "preview_rows": row.preview_rows or [],
        "validation_errors": row.validation_errors or [],
        "record_count": len(row.records or []),
        "created_at": row.created_at,
        "updated_at": row.updated_at,
        "promoted_at": row.promoted_at,
    }
    if include_records:
        payload["records"] = row.records or []
    return payload


def _create_job(
    db: Session,
    *,
    source_type: str,
    filename: Optional[str],
    display_name: Optional[str],
    target_dataset_id: Optional[str],
    records: List[Dict[str, Any]],
    errors: List[Dict[str, str]],
    requested_id: Optional[str] = None,
    actor: str = "workspace",
) -> ImportJob:
    _ensure_tables(db)
    base_name = display_name or filename or f"{source_type.upper()} Import"
    job_id = requested_id or _new_id("import")
    if db.query(ImportJob).filter(ImportJob.id == job_id).first():
        raise HTTPException(status_code=400, detail="Import job already exists")
    schema = _infer_schema(records) if records else {"fields": [], "field_count": 0, "record_count": 0}
    now = _now()
    job = ImportJob(
        id=job_id,
        source_type=source_type,
        filename=filename,
        display_name=base_name,
        target_dataset_id=target_dataset_id,
        status="INVALID" if errors else "READY",
        inferred_schema=schema,
        preview_rows=records[:25],
        validation_errors=errors,
        records=records,
        created_at=now,
        updated_at=now,
    )
    db.add(job)
    _audit(db, actor, "import.job.created", "import_job", job.id, {
        "source_type": source_type,
        "filename": filename,
        "status": job.status,
        "record_count": len(records),
        "validation_errors": errors,
    })
    ops_control.record_ops_event(
        db,
        source="imports",
        event_type="import.job.created",
        severity="warn" if errors else "info",
        title=f"Import job {job.status}: {base_name}",
        subject_type="import_job",
        subject_id=job.id,
        payload={"source_type": source_type, "record_count": len(records), "errors": errors},
    )
    db.commit()
    db.refresh(job)
    return job


@router.post("/imports/csv", status_code=201)
def import_csv(body: CsvImportRequest, db: Session = Depends(get_db)):
    records, errors = _parse_csv(body.content, body.delimiter)
    job = _create_job(
        db,
        source_type="csv",
        filename=body.filename,
        display_name=body.display_name,
        target_dataset_id=body.target_dataset_id,
        records=records,
        errors=errors,
        requested_id=body.id,
    )
    return _job_dict(job)


@router.post("/imports/json", status_code=201)
def import_json(body: JsonImportRequest, db: Session = Depends(get_db)):
    records, errors = _parse_json(body)
    job = _create_job(
        db,
        source_type="json",
        filename=body.filename,
        display_name=body.display_name,
        target_dataset_id=body.target_dataset_id,
        records=records,
        errors=errors,
        requested_id=body.id,
    )
    return _job_dict(job)


@router.get("/imports/jobs")
def list_import_jobs(
    status: Optional[str] = None,
    limit: int = Query(50, ge=1, le=500),
    db: Session = Depends(get_db),
):
    _ensure_tables(db)
    query = db.query(ImportJob)
    if status:
        query = query.filter(ImportJob.status == status.upper())
    rows = query.order_by(ImportJob.created_at.desc()).limit(limit).all()
    return {"count": len(rows), "jobs": [_job_dict(row) for row in rows]}


@router.get("/imports/jobs/{job_id}")
def get_import_job(job_id: str, include_records: bool = False, db: Session = Depends(get_db)):
    _ensure_tables(db)
    job = db.query(ImportJob).filter(ImportJob.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail=f"Import job '{job_id}' not found")
    return _job_dict(job, include_records=include_records)


@router.post("/imports/jobs/{job_id}/promote-to-dataset")
def promote_import_job(job_id: str, body: PromoteImportRequest, db: Session = Depends(get_db)):
    _ensure_tables(db)
    job = db.query(ImportJob).filter(ImportJob.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail=f"Import job '{job_id}' not found")
    if job.status == "INVALID":
        raise HTTPException(status_code=400, detail="Cannot promote an invalid import job")
    dataset_id = body.dataset_id or job.target_dataset_id or _slug(job.display_name or job.filename or job.id)
    now = _now()
    asset = db.query(models.DataAsset).filter(models.DataAsset.id == dataset_id).first()
    schema = dict(job.inferred_schema or {})
    schema["source_import_job_id"] = job.id
    schema["source_type"] = job.source_type
    schema["record_count"] = len(job.records or [])
    if asset and not body.replace:
        raise HTTPException(status_code=409, detail="DataAsset already exists")
    if not asset:
        asset = models.DataAsset(
            id=dataset_id,
            display_name=body.display_name or job.display_name,
            description=body.description or f"Promoted from import job {job.id}.",
            kind="dataset",
            asset_schema=schema,
            records=job.records or [],
            created_at=now,
            updated_at=now,
        )
        db.add(asset)
    else:
        asset.display_name = body.display_name or asset.display_name or job.display_name
        asset.description = body.description if body.description is not None else asset.description
        asset.asset_schema = schema
        asset.records = job.records or []
        asset.updated_at = now
    job.status = "PROMOTED"
    job.target_dataset_id = asset.id
    job.promoted_at = now
    job.updated_at = now
    _audit(db, body.actor, "import.job.promoted", "import_job", job.id, {
        "dataset_id": asset.id,
        "record_count": len(asset.records or []),
        "field_count": schema.get("field_count", 0),
    })
    _audit(db, body.actor, "data.asset.promoted_from_import", "data_asset", asset.id, {
        "import_job_id": job.id,
        "source_type": job.source_type,
    })
    ops_control.record_ops_event(
        db,
        source="imports",
        event_type="import.job.promoted",
        severity="info",
        title=f"Import promoted to dataset {asset.id}",
        subject_type="data_asset",
        subject_id=asset.id,
        payload={"import_job_id": job.id, "record_count": len(asset.records or [])},
    )
    db.commit()
    db.refresh(job)
    db.refresh(asset)
    return {
        "status": "PROMOTED",
        "job": _job_dict(job),
        "dataset": {
            "id": asset.id,
            "display_name": asset.display_name,
            "description": asset.description,
            "kind": asset.kind,
            "asset_schema": asset.asset_schema or {},
            "records": asset.records or [],
            "created_at": asset.created_at,
            "updated_at": asset.updated_at,
        },
    }


@router.get("/imports/summary")
def imports_summary(db: Session = Depends(get_db)):
    _ensure_tables(db)
    rows = db.query(ImportJob).order_by(ImportJob.created_at.desc()).limit(25).all()
    counts: Dict[str, int] = {}
    for row in db.query(ImportJob).all():
        counts[row.status] = counts.get(row.status, 0) + 1
    return {
        "counts": counts,
        "latest_jobs": [_job_dict(row) for row in rows],
    }

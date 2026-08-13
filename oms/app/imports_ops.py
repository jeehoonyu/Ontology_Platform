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
import os
import re
import time
import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse, PlainTextResponse
from pydantic import BaseModel, Field
from sqlalchemy import Integer, JSON, String
from sqlalchemy.orm import Mapped, Session, mapped_column

from . import models, models_action, ontology_generator, ops_control, tenancy
from .database import Base, get_db
from .production_auth import Principal, require_permission

router = APIRouter(tags=["imports"])


class ImportJob(Base):
    __tablename__ = "import_jobs"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    project_id: Mapped[str] = mapped_column(String, default="default", index=True)
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
    project_id: str = "default"
    id: Optional[str] = None
    filename: Optional[str] = None
    display_name: Optional[str] = None
    content: str
    delimiter: str = ","
    target_dataset_id: Optional[str] = None


class JsonImportRequest(BaseModel):
    project_id: str = "default"
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


class ImportJobPatchRequest(BaseModel):
    display_name: Optional[str] = None
    target_dataset_id: Optional[str] = None
    template: Optional[str] = None
    mapping: Optional[Dict[str, str]] = None


class ImportValidateRequest(BaseModel):
    template: str = "asset"
    mapping: Dict[str, str] = Field(default_factory=dict)


class ImportGenerateDraftRequest(BaseModel):
    draft_id: Optional[str] = None
    display_name: Optional[str] = None
    object_type_id: Optional[str] = None
    include_actions: bool = True
    create_pipeline_graph: bool = True
    actor: str = "workspace"
    promote_dataset_id: Optional[str] = None


class ImportTransformStep(BaseModel):
    op: str
    source: Optional[str] = None
    target: Optional[str] = None
    field: Optional[str] = None
    target_type: Optional[str] = None
    mapping: Dict[str, Any] = Field(default_factory=dict)
    from_unit: Optional[str] = None
    to_unit: Optional[str] = None
    factor: Optional[float] = None
    offset: float = 0.0
    latitude_field: Optional[str] = None
    longitude_field: Optional[str] = None
    keys: List[str] = Field(default_factory=list)


class ImportTransformRequest(BaseModel):
    steps: List[ImportTransformStep] = Field(default_factory=list)
    preview_only: bool = False
    actor: str = "workspace"


IMPORT_TEMPLATES: Dict[str, Dict[str, Any]] = {
    "asset": {
        "display_name": "Asset",
        "object_type_id": "asset",
        "required": ["asset_id", "name"],
        "fields": {
            "asset_id": {"type": "string", "aliases": ["id", "assetid", "equipment_id"]},
            "name": {"type": "string", "aliases": ["asset_name", "title", "label"]},
            "status": {"type": "string", "aliases": ["state", "condition"]},
            "criticality": {"type": "string", "aliases": ["priority", "severity"]},
            "facility_id": {"type": "string", "aliases": ["site_id", "plant_id"]},
            "vibration_mm_s": {"type": "number", "aliases": ["vibration", "vibration_mms"]},
            "temperature_c": {"type": "number", "aliases": ["temperature", "temp_c"]},
            "longitude": {"type": "number", "aliases": ["lon", "lng"]},
            "latitude": {"type": "number", "aliases": ["lat"]},
        },
        "sample": [
            {"asset_id": "asset_user_1", "name": "User Pump", "status": "DEGRADED", "criticality": "high", "vibration_mm_s": 9.7, "temperature_c": 91.2, "longitude": -122.4012, "latitude": 37.7924}
        ],
    },
    "work_order": {
        "display_name": "Work Order",
        "object_type_id": "work_order",
        "required": ["work_order_id", "asset_id", "status"],
        "fields": {
            "work_order_id": {"type": "string", "aliases": ["id", "wo_id", "ticket_id"]},
            "asset_id": {"type": "string", "aliases": ["equipment_id"]},
            "title": {"type": "string", "aliases": ["name", "summary"]},
            "status": {"type": "string", "aliases": ["state"]},
            "priority": {"type": "string", "aliases": ["severity", "criticality"]},
            "created_at": {"type": "string", "aliases": ["opened_at", "created"]},
        },
        "sample": [
            {"work_order_id": "wo_user_1", "asset_id": "asset_user_1", "title": "Inspect pump", "status": "OPEN", "priority": "high"}
        ],
    },
    "sensor_reading": {
        "display_name": "Sensor Reading",
        "object_type_id": "sensor_reading",
        "required": ["reading_id", "asset_id", "observed_at"],
        "fields": {
            "reading_id": {"type": "string", "aliases": ["id", "event_id"]},
            "asset_id": {"type": "string", "aliases": ["equipment_id"]},
            "vibration_mm_s": {"type": "number", "aliases": ["vibration", "vibration_mms"]},
            "temperature_c": {"type": "number", "aliases": ["temperature", "temp_c"]},
            "observed_at": {"type": "string", "aliases": ["timestamp", "time", "ts"]},
        },
        "sample": [
            {"reading_id": "sensor_user_1", "asset_id": "asset_user_1", "vibration_mm_s": 9.7, "temperature_c": 91.2, "observed_at": "2026-06-28T12:00:00Z"}
        ],
    },
    "facility": {
        "display_name": "Facility",
        "object_type_id": "facility",
        "required": ["facility_id", "name"],
        "fields": {
            "facility_id": {"type": "string", "aliases": ["id", "site_id", "plant_id"]},
            "name": {"type": "string", "aliases": ["facility_name", "site_name"]},
            "region": {"type": "string", "aliases": ["area"]},
            "longitude": {"type": "number", "aliases": ["lon", "lng"]},
            "latitude": {"type": "number", "aliases": ["lat"]},
        },
        "sample": [
            {"facility_id": "facility_user_1", "name": "User Facility", "region": "west", "longitude": -122.4012, "latitude": 37.7924}
        ],
    },
}


def _now() -> int:
    return int(time.time())


def _slug(value: str, fallback: str = "imported_dataset") -> str:
    text = re.sub(r"[^a-zA-Z0-9]+", "_", value or "").strip("_").lower()
    return text or fallback


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def _ensure_tables(db: Session) -> None:
    if os.getenv("APP_ENV", "").strip().lower() == "production":
        return
    ImportJob.__table__.create(bind=db.get_bind(), checkfirst=True)
    ops_control._ensure_tables(db)


def _job_for(db: Session, job_id: str, principal: Principal, permission: str) -> ImportJob:
    _ensure_tables(db)
    job = db.query(ImportJob).filter(ImportJob.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail=f"Import job '{job_id}' not found")
    tenancy.assert_project_permission(db, principal, job.project_id, permission)
    return job


def _accessible_jobs(db: Session, principal: Principal, permission: str = "view"):
    query = db.query(ImportJob)
    project_ids = tenancy.accessible_project_ids(db, principal, permission)
    if project_ids is not None:
        query = query.filter(ImportJob.project_id.in_(project_ids)) if project_ids else query.filter(ImportJob.id == "__none__")
    return query


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


def _normalize_field(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").lower())


def _template_or_404(template_id: str) -> Dict[str, Any]:
    template = IMPORT_TEMPLATES.get(template_id)
    if not template:
        raise HTTPException(status_code=404, detail=f"Import template '{template_id}' not found")
    return template


def _suggest_mapping(fields: List[str], template_id: str) -> Dict[str, str]:
    template = _template_or_404(template_id)
    by_normalized = {_normalize_field(field): field for field in fields}
    mapping: Dict[str, str] = {}
    for target, spec in template["fields"].items():
        candidates = [target, *spec.get("aliases", [])]
        for candidate in candidates:
            source = by_normalized.get(_normalize_field(candidate))
            if source:
                mapping[target] = source
                break
    return mapping


def _coerce_type(value: Any, expected_type: str) -> bool:
    if value is None:
        return True
    if expected_type == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected_type == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected_type == "boolean":
        return isinstance(value, bool)
    if expected_type == "object":
        return isinstance(value, dict)
    if expected_type == "array":
        return isinstance(value, list)
    return True


def _mapped_records(records: List[Dict[str, Any]], mapping: Dict[str, str], *, include_unmapped: bool = True) -> List[Dict[str, Any]]:
    mapped: List[Dict[str, Any]] = []
    used_sources = {source for source in mapping.values() if source}
    for row in records:
        out: Dict[str, Any] = {}
        for target, source in mapping.items():
            if source:
                out[target] = (row or {}).get(source)
        if include_unmapped:
            for key, value in (row or {}).items():
                if key not in used_sources and key not in out:
                    out[key] = value
        mapped.append(out)
    return mapped


def _validate_job_template(job: ImportJob, template_id: str, mapping: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    template = _template_or_404(template_id)
    records = job.records or []
    fields = _field_order(records)
    mapping = mapping or _suggest_mapping(fields, template_id)
    source_fields = set(fields)
    errors: List[Dict[str, str]] = []
    warnings: List[Dict[str, str]] = []
    for target in template.get("required", []):
        source = mapping.get(target)
        if not source:
            errors.append({"code": "REQUIRED_MAPPING_MISSING", "field": target, "message": f"Required semantic field '{target}' is not mapped."})
        elif source not in source_fields:
            errors.append({"code": "SOURCE_FIELD_NOT_FOUND", "field": target, "message": f"Mapped source field '{source}' does not exist."})
    for target, source in mapping.items():
        if source and source not in source_fields:
            errors.append({"code": "SOURCE_FIELD_NOT_FOUND", "field": target, "message": f"Mapped source field '{source}' does not exist."})
            continue
        spec = template["fields"].get(target)
        if not spec or not source:
            continue
        missing = sum(1 for row in records if (row or {}).get(source) is None)
        if missing:
            warnings.append({"code": "MISSING_VALUES", "field": target, "message": f"{missing} row(s) are missing semantic field '{target}'."})
        mismatches = [
            index + 1
            for index, row in enumerate(records[:50])
            if not _coerce_type((row or {}).get(source), spec.get("type", "string"))
        ]
        if mismatches:
            warnings.append({"code": "TYPE_SHAPE", "field": target, "message": f"Field '{target}' expects {spec.get('type')} but row(s) {mismatches[:5]} differ."})
    mapped_preview = _mapped_records(records[:10], mapping)
    return {
        "status": "INVALID" if errors else "READY",
        "template": template_id,
        "template_display_name": template["display_name"],
        "mapping": mapping,
        "errors": errors,
        "warnings": warnings,
        "semantic_preview": mapped_preview,
        "summary": {
            "records": len(records),
            "mapped_fields": len([value for value in mapping.values() if value]),
            "errors": len(errors),
            "warnings": len(warnings),
        },
    }


def _apply_validation(job: ImportJob, validation: Dict[str, Any]) -> None:
    schema = dict(job.inferred_schema or {})
    schema["template"] = validation["template"]
    schema["semantic_mapping"] = validation["mapping"]
    schema["mapping_warnings"] = validation["warnings"]
    schema["semantic_preview"] = validation["semantic_preview"]
    schema["validation_summary"] = validation["summary"]
    job.inferred_schema = schema
    job.validation_errors = validation["errors"]
    if job.status != "PROMOTED":
        job.status = validation["status"]
    job.updated_at = _now()


def _records_for_dataset(job: ImportJob) -> List[Dict[str, Any]]:
    schema = job.inferred_schema or {}
    mapping = schema.get("semantic_mapping") or {}
    if isinstance(mapping, dict) and mapping:
        return _mapped_records(job.records or [], {str(k): str(v) for k, v in mapping.items() if v})
    return job.records or []


def _coerce_value(value: Any, target_type: str) -> Any:
    if value is None:
        return None
    target = (target_type or "string").lower()
    if target in {"string", "str"}:
        return str(value)
    if target in {"number", "float", "double"}:
        if isinstance(value, bool):
            raise ValueError("boolean is not numeric")
        return float(value)
    if target in {"integer", "int", "long"}:
        if isinstance(value, bool):
            raise ValueError("boolean is not integer")
        return int(float(value))
    if target in {"boolean", "bool"}:
        if isinstance(value, bool):
            return value
        lowered = str(value).strip().lower()
        if lowered in {"true", "1", "yes", "y"}:
            return True
        if lowered in {"false", "0", "no", "n"}:
            return False
        raise ValueError("value is not boolean-like")
    if target == "json":
        if isinstance(value, (dict, list)):
            return value
        return json.loads(str(value))
    return value


def _normalize_timestamp(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return int(value)
    text = str(value).strip()
    if not text:
        return None
    # Keep the runtime dependency-free: normalize common ISO-like timestamps
    # into a stable UTC-ish string instead of requiring dateutil.
    normalized = text.replace(" ", "T")
    if normalized.endswith("Z") or re.search(r"[+-]\d{2}:?\d{2}$", normalized):
        return normalized
    return f"{normalized}Z"


def _unit_factor(from_unit: Optional[str], to_unit: Optional[str], explicit_factor: Optional[float]) -> tuple[float, float]:
    if explicit_factor is not None:
        return float(explicit_factor), 0.0
    src = (from_unit or "").lower()
    dst = (to_unit or "").lower()
    if src in {"f", "fahrenheit"} and dst in {"c", "celsius"}:
        return 5.0 / 9.0, -32.0 * 5.0 / 9.0
    if src in {"c", "celsius"} and dst in {"f", "fahrenheit"}:
        return 9.0 / 5.0, 32.0
    if src in {"ips", "in_s", "inch_per_second"} and dst in {"mm_s", "mms", "millimeter_per_second"}:
        return 25.4, 0.0
    if src in {"mm_s", "mms", "millimeter_per_second"} and dst in {"ips", "in_s", "inch_per_second"}:
        return 1.0 / 25.4, 0.0
    return 1.0, 0.0


def _decode_mgrs_point(value: Any) -> Optional[Dict[str, Any]]:
    if value in (None, ""):
        return None
    from .runtime import decode_mgrs

    decoded = decode_mgrs(str(value))
    return {"type": "Point", "coordinates": [decoded["longitude"], decoded["latitude"]]}


def _apply_transform_steps(records: List[Dict[str, Any]], steps: List[ImportTransformStep]) -> Dict[str, Any]:
    rows = [dict(row or {}) for row in records]
    warnings: List[Dict[str, Any]] = []
    duplicate_rows: List[Dict[str, Any]] = []
    applied: List[Dict[str, Any]] = []

    for index, step in enumerate(steps):
        op = (step.op or "").strip().lower().replace("-", "_")
        applied.append(step.model_dump(exclude_none=True))
        try:
            if op in {"rename", "map_column"}:
                source = step.source or step.field
                target = step.target
                if not source or not target:
                    raise ValueError("rename requires source and target")
                for row in rows:
                    if source in row:
                        row[target] = row.pop(source)
            elif op in {"coerce", "type_coerce"}:
                field = step.field or step.source
                if not field or not step.target_type:
                    raise ValueError("coerce requires field and target_type")
                for row_number, row in enumerate(rows, start=1):
                    try:
                        row[field] = _coerce_value(row.get(field), step.target_type)
                    except Exception as exc:  # noqa: BLE001 - returned as user-facing validation evidence.
                        warnings.append({"code": "COERCE_FAILED", "step": index, "row": row_number, "field": field, "message": str(exc)})
            elif op == "enum_cleanup":
                field = step.field or step.source
                if not field:
                    raise ValueError("enum_cleanup requires field")
                mapping = {str(k).strip().lower(): v for k, v in (step.mapping or {}).items()}
                for row in rows:
                    value = row.get(field)
                    if value is None:
                        continue
                    key = str(value).strip().lower()
                    row[field] = mapping.get(key, key)
            elif op in {"parse_timestamp", "timestamp"}:
                source = step.source or step.field
                target = step.target or source
                if not source or not target:
                    raise ValueError("parse_timestamp requires source or field")
                for row in rows:
                    row[target] = _normalize_timestamp(row.get(source))
            elif op in {"normalize_unit", "unit_normalize"}:
                source = step.source or step.field
                target = step.target or source
                if not source or not target:
                    raise ValueError("normalize_unit requires source or field")
                factor, default_offset = _unit_factor(step.from_unit, step.to_unit, step.factor)
                offset = step.offset if step.factor is not None else default_offset
                for row_number, row in enumerate(rows, start=1):
                    value = row.get(source)
                    if value is None:
                        row[target] = None
                        continue
                    try:
                        row[target] = (float(value) * factor) + offset
                    except Exception as exc:  # noqa: BLE001
                        warnings.append({"code": "UNIT_NORMALIZE_FAILED", "step": index, "row": row_number, "field": source, "message": str(exc)})
            elif op in {"derive_point", "latlon_to_point"}:
                lat_field = step.latitude_field or "latitude"
                lon_field = step.longitude_field or "longitude"
                target = step.target or "geometry"
                for row_number, row in enumerate(rows, start=1):
                    lat = row.get(lat_field)
                    lon = row.get(lon_field)
                    if lat in (None, "") or lon in (None, ""):
                        continue
                    try:
                        row[target] = {"type": "Point", "coordinates": [float(lon), float(lat)]}
                    except Exception as exc:  # noqa: BLE001
                        warnings.append({"code": "POINT_DERIVE_FAILED", "step": index, "row": row_number, "message": str(exc)})
            elif op in {"mgrs_to_point", "mgrs"}:
                source = step.source or step.field or "mgrs"
                target = step.target or "geometry"
                for row_number, row in enumerate(rows, start=1):
                    try:
                        point = _decode_mgrs_point(row.get(source))
                        if point:
                            row[target] = point
                    except Exception as exc:  # noqa: BLE001
                        warnings.append({"code": "MGRS_DECODE_FAILED", "step": index, "row": row_number, "field": source, "message": str(exc)})
            elif op in {"deduplicate", "dedupe"}:
                keys = step.keys or ([step.field] if step.field else [])
                if not keys:
                    raise ValueError("deduplicate requires keys")
                seen = set()
                deduped: List[Dict[str, Any]] = []
                for row_number, row in enumerate(rows, start=1):
                    fingerprint = tuple(_jsonable_key(row.get(key)) for key in keys)
                    if fingerprint in seen:
                        duplicate_rows.append({"row": row_number, "keys": keys, "fingerprint": list(fingerprint)})
                        continue
                    seen.add(fingerprint)
                    deduped.append(row)
                rows = deduped
            else:
                raise ValueError(f"Unsupported transform op '{step.op}'")
        except ValueError as exc:
            warnings.append({"code": "TRANSFORM_STEP_SKIPPED", "step": index, "op": step.op, "message": str(exc)})

    return {
        "records": rows,
        "warnings": warnings,
        "duplicate_rows": duplicate_rows,
        "applied_steps": applied,
        "preview_rows": rows[:25],
        "schema": _infer_schema(rows),
        "summary": {
            "input_records": len(records),
            "output_records": len(rows),
            "steps": len(steps),
            "warnings": len(warnings),
            "duplicates_removed": len(duplicate_rows),
        },
    }


def _source_type_from_filename(filename: Optional[str], content_type: str = "") -> str:
    lowered = (filename or "").lower()
    if lowered.endswith(".json") or "json" in content_type.lower():
        return "json"
    return "csv"


def _parse_multipart_text(body: bytes, content_type: str) -> Dict[str, Any]:
    match = re.search(r'boundary="?([^";]+)"?', content_type)
    if not match:
        raise HTTPException(status_code=400, detail="Multipart boundary missing")
    boundary = match.group(1).encode()
    result: Dict[str, Any] = {"fields": {}, "file_content": "", "filename": None}
    for raw_part in body.split(b"--" + boundary):
        part = raw_part.strip(b"\r\n")
        if not part or part == b"--":
            continue
        header_blob, sep, content = part.partition(b"\r\n\r\n")
        if not sep:
            continue
        headers = header_blob.decode("utf-8", errors="ignore")
        name_match = re.search(r'name="([^"]+)"', headers)
        if not name_match:
            continue
        name = name_match.group(1)
        filename_match = re.search(r'filename="([^"]*)"', headers)
        text = content.rstrip(b"\r\n").decode("utf-8-sig", errors="replace")
        if filename_match:
            result["filename"] = filename_match.group(1)
            result["file_content"] = text
        else:
            result["fields"][name] = text
    return result


def _job_dict(row: ImportJob, include_records: bool = False) -> Dict[str, Any]:
    schema = row.inferred_schema or {}
    payload = {
        "id": row.id,
        "project_id": row.project_id,
        "source_type": row.source_type,
        "filename": row.filename,
        "display_name": row.display_name,
        "target_dataset_id": row.target_dataset_id,
        "status": row.status,
        "schema": schema,
        "template": schema.get("template"),
        "semantic_mapping": schema.get("semantic_mapping") or {},
        "mapping_warnings": schema.get("mapping_warnings") or [],
        "semantic_preview": schema.get("semantic_preview") or [],
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
    project_id: str,
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
        project_id=project_id,
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
        "project_id": project_id,
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
        payload={"project_id": project_id, "source_type": source_type, "record_count": len(records), "errors": errors},
    )
    db.commit()
    db.refresh(job)
    return job


@router.post("/imports/csv", status_code=201)
def import_csv(body: CsvImportRequest, principal: Principal = Depends(require_permission("edit")), db: Session = Depends(get_db)):
    tenancy.assert_project_permission(db, principal, body.project_id, "edit")
    records, errors = _parse_csv(body.content, body.delimiter)
    job = _create_job(
        db,
        project_id=body.project_id,
        source_type="csv",
        filename=body.filename,
        display_name=body.display_name,
        target_dataset_id=body.target_dataset_id,
        records=records,
        errors=errors,
        requested_id=body.id,
        actor=principal.id,
    )
    return _job_dict(job)


@router.post("/imports/json", status_code=201)
def import_json(body: JsonImportRequest, principal: Principal = Depends(require_permission("edit")), db: Session = Depends(get_db)):
    tenancy.assert_project_permission(db, principal, body.project_id, "edit")
    records, errors = _parse_json(body)
    job = _create_job(
        db,
        project_id=body.project_id,
        source_type="json",
        filename=body.filename,
        display_name=body.display_name,
        target_dataset_id=body.target_dataset_id,
        records=records,
        errors=errors,
        requested_id=body.id,
        actor=principal.id,
    )
    return _job_dict(job)


@router.post("/imports/files", status_code=201)
async def import_file(
    request: Request,
    id: Optional[str] = None,
    filename: Optional[str] = None,
    display_name: Optional[str] = None,
    target_dataset_id: Optional[str] = None,
    project_id: str = "default",
    source_type: Optional[str] = None,
    template: Optional[str] = None,
    principal: Principal = Depends(require_permission("edit")),
    db: Session = Depends(get_db),
):
    content_type = request.headers.get("content-type", "")
    body = await request.body()
    fields: Dict[str, Any] = {}
    content = body.decode("utf-8-sig", errors="replace")
    upload_filename = filename
    if "multipart/form-data" in content_type.lower():
        parsed = _parse_multipart_text(body, content_type)
        fields = parsed.get("fields") or {}
        content = parsed.get("file_content") or ""
        upload_filename = upload_filename or parsed.get("filename")
    requested_id = id or fields.get("id") or None
    selected_project_id = str(fields.get("project_id") or project_id)
    tenancy.assert_project_permission(db, principal, selected_project_id, "edit")
    display = display_name or fields.get("display_name") or upload_filename
    dataset_id = target_dataset_id or fields.get("target_dataset_id") or None
    kind = (source_type or fields.get("source_type") or _source_type_from_filename(upload_filename, content_type)).lower()
    if kind == "json":
        records, errors = _parse_json(JsonImportRequest(content=content))
    elif kind == "csv":
        records, errors = _parse_csv(content)
    else:
        raise HTTPException(status_code=400, detail="source_type must be csv or json")
    job = _create_job(
        db,
        project_id=selected_project_id,
        source_type=kind,
        filename=upload_filename,
        display_name=display,
        target_dataset_id=dataset_id,
        records=records,
        errors=errors,
        requested_id=requested_id,
        actor=principal.id,
    )
    selected_template = template or fields.get("template")
    if selected_template:
        validation = _validate_job_template(job, selected_template)
        _apply_validation(job, validation)
        _audit(db, principal.id, "import.job.validated", "import_job", job.id, validation)
        db.commit()
        db.refresh(job)
    return _job_dict(job)


@router.get("/imports/templates")
def list_import_templates(_principal: Principal = Depends(require_permission("view"))):
    return {
        "templates": [
            {
                "id": template_id,
                "display_name": template["display_name"],
                "object_type_id": template["object_type_id"],
                "required": template["required"],
                "fields": template["fields"],
            }
            for template_id, template in IMPORT_TEMPLATES.items()
        ]
    }


@router.get("/imports/templates/{template_id}/sample")
def import_template_sample(template_id: str, format: str = Query("csv", pattern="^(csv|json)$"), _principal: Principal = Depends(require_permission("view"))):
    template = _template_or_404(template_id)
    rows = template["sample"]
    if format == "json":
        return JSONResponse(rows)
    fields = list(rows[0].keys()) if rows else []
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=fields)
    writer.writeheader()
    writer.writerows(rows)
    return PlainTextResponse(buffer.getvalue(), media_type="text/csv")


@router.get("/imports/jobs")
def list_import_jobs(
    status: Optional[str] = None,
    project_id: Optional[str] = None,
    limit: int = Query(50, ge=1, le=500),
    principal: Principal = Depends(require_permission("view")),
    db: Session = Depends(get_db),
):
    _ensure_tables(db)
    query = _accessible_jobs(db, principal)
    if project_id:
        tenancy.assert_project_permission(db, principal, project_id, "view")
        query = query.filter(ImportJob.project_id == project_id)
    if status:
        query = query.filter(ImportJob.status == status.upper())
    rows = query.order_by(ImportJob.created_at.desc()).limit(limit).all()
    return {"count": len(rows), "jobs": [_job_dict(row) for row in rows]}


@router.get("/ui-state/imports")
def imports_ui_state(project_id: Optional[str] = None, principal: Principal = Depends(require_permission("view")), db: Session = Depends(get_db)):
    _ensure_tables(db)
    query = _accessible_jobs(db, principal)
    if project_id:
        tenancy.assert_project_permission(db, principal, project_id, "view")
        query = query.filter(ImportJob.project_id == project_id)
    jobs = query.order_by(ImportJob.updated_at.desc()).limit(50).all()
    job_payloads = [_job_dict(row) for row in jobs]
    status_counts: Dict[str, int] = {}
    for row in jobs:
        status_counts[row.status] = status_counts.get(row.status, 0) + 1
    templates = [
        {
            "id": template_id,
            "display_name": template["display_name"],
            "object_type_id": template["object_type_id"],
            "required": template["required"],
            "field_count": len(template["fields"]),
        }
        for template_id, template in IMPORT_TEMPLATES.items()
    ]
    warnings = [
        {
            "id": f"{job.id}_validation",
            "job_id": job.id,
            "message": f"{job.display_name} has {len(job.validation_errors or [])} validation issue(s).",
            "severity": "warn",
        }
        for job in jobs
        if job.validation_errors
    ]
    promoted_jobs = [job for job in jobs if job.status == "PROMOTED"]
    latest_job = jobs[0] if jobs else None
    sections = [
        {
            "id": "upload",
            "title": "Upload or paste records",
            "status": "complete" if jobs else "active",
            "description": "Create a reviewable import job before data reaches a dataset.",
            "metrics": {"job_count": len(jobs), "template_count": len(templates)},
            "rows": job_payloads[:8],
            "href": "/workspace/imports",
        },
        {
            "id": "mapping",
            "title": "Map and validate",
            "status": "complete" if any(job.status in {"READY", "PROMOTED"} for job in jobs) else "available",
            "description": "Apply semantic templates, required-field checks, and type warnings.",
            "metrics": {"ready": status_counts.get("READY", 0), "invalid": status_counts.get("INVALID", 0)},
            "rows": warnings or [{"message": "No validation warnings for recent import jobs.", "status": "PASS"}],
            "href": "/workspace/imports",
        },
        {
            "id": "transform",
            "title": "Clean and enrich",
            "status": "available" if jobs else "blocked",
            "description": "Normalize units, enums, timestamps, MGRS/geometry, and duplicates before promotion.",
            "metrics": {"recent_job": getattr(latest_job, "id", None), "transformed": sum(1 for job in jobs if (job.inferred_schema or {}).get("transformations"))},
            "rows": [
                {"operation": "enum cleanup", "supported": True},
                {"operation": "unit normalization", "supported": True},
                {"operation": "MGRS or lat/lon geometry", "supported": True},
                {"operation": "duplicate detection", "supported": True},
            ],
            "href": "/workspace/imports",
        },
        {
            "id": "promote",
            "title": "Promote to dataset",
            "status": "complete" if promoted_jobs else ("available" if jobs else "blocked"),
            "description": "Create a local DataAsset that can feed ontology generation and pipelines.",
            "metrics": {"promoted": len(promoted_jobs), "dataset_count": len({job.target_dataset_id for job in promoted_jobs if job.target_dataset_id})},
            "rows": [{"job_id": job.id, "dataset_id": job.target_dataset_id, "status": job.status} for job in promoted_jobs[:8]],
            "href": "/workspace/ontology",
        },
    ]
    return {
        "summary": {
            "job_count": len(jobs),
            "template_count": len(templates),
            "status_counts": status_counts,
            "latest_job_id": getattr(latest_job, "id", None),
        },
        "primary_actions": [
            {"id": "create_csv", "label": "Import CSV", "method": "POST", "path": "/imports/csv"},
            {"id": "upload_file", "label": "Upload file", "method": "POST", "path": "/imports/files"},
            {"id": "generate_draft", "label": "Generate ontology draft", "method": "POST", "path": "/imports/jobs/{job_id}/generate-ontology-draft"},
        ],
        "sections": sections,
        "evidence_links": [
            {"kind": "import_job", "id": job.id, "href": f"/imports/jobs/{job.id}"}
            for job in jobs[:12]
        ] + [
            {"kind": "data_asset", "id": job.target_dataset_id, "href": "/workspace/ontology"}
            for job in promoted_jobs[:12]
            if job.target_dataset_id
        ],
        "warnings": warnings,
        "templates": templates,
        "jobs": job_payloads,
        "last_updated": max([job.updated_at for job in jobs], default=_now()),
    }


@router.get("/imports/jobs/{job_id}")
def get_import_job(job_id: str, include_records: bool = False, principal: Principal = Depends(require_permission("view")), db: Session = Depends(get_db)):
    job = _job_for(db, job_id, principal, "view")
    return _job_dict(job, include_records=include_records)


@router.get("/imports/jobs/{job_id}/mapping-suggestions")
def import_mapping_suggestions(job_id: str, template: str = Query("asset"), principal: Principal = Depends(require_permission("view")), db: Session = Depends(get_db)):
    job = _job_for(db, job_id, principal, "view")
    template_spec = _template_or_404(template)
    fields = _field_order(job.records or [])
    mapping = _suggest_mapping(fields, template)
    suggestions = []
    normalized_fields = {_normalize_field(field): field for field in fields}
    for target, spec in template_spec["fields"].items():
        source = mapping.get(target)
        reason = "matched target or alias" if source else "no matching source field"
        confidence = 0.95 if source and _normalize_field(source) == _normalize_field(target) else (0.8 if source else 0.0)
        candidates = []
        for candidate in [target, *spec.get("aliases", [])]:
            matched = normalized_fields.get(_normalize_field(candidate))
            if matched and matched not in candidates:
                candidates.append(matched)
        suggestions.append({
            "target": target,
            "source": source,
            "required": target in template_spec.get("required", []),
            "type": spec.get("type", "string"),
            "confidence": confidence,
            "reason": reason,
            "candidates": candidates,
        })
    return {
        "job_id": job.id,
        "template": template,
        "template_display_name": template_spec["display_name"],
        "fields": fields,
        "mapping": mapping,
        "suggestions": suggestions,
    }


@router.patch("/imports/jobs/{job_id}")
def patch_import_job(job_id: str, body: ImportJobPatchRequest, principal: Principal = Depends(require_permission("edit")), db: Session = Depends(get_db)):
    job = _job_for(db, job_id, principal, "edit")
    if body.display_name is not None:
        job.display_name = body.display_name
    if body.target_dataset_id is not None:
        job.target_dataset_id = body.target_dataset_id
    if body.template:
        validation = _validate_job_template(job, body.template, body.mapping)
        _apply_validation(job, validation)
    elif body.mapping is not None:
        schema = dict(job.inferred_schema or {})
        template = schema.get("template") or "asset"
        validation = _validate_job_template(job, template, body.mapping)
        _apply_validation(job, validation)
    job.updated_at = _now()
    _audit(db, principal.id, "import.job.updated", "import_job", job.id, {
        "display_name": job.display_name,
        "target_dataset_id": job.target_dataset_id,
        "template": (job.inferred_schema or {}).get("template"),
    })
    db.commit()
    db.refresh(job)
    return _job_dict(job)


@router.post("/imports/jobs/{job_id}/validate")
def validate_import_job(job_id: str, body: ImportValidateRequest, principal: Principal = Depends(require_permission("edit")), db: Session = Depends(get_db)):
    job = _job_for(db, job_id, principal, "edit")
    mapping = body.mapping or _suggest_mapping(_field_order(job.records or []), body.template)
    validation = _validate_job_template(job, body.template, mapping)
    _apply_validation(job, validation)
    _audit(db, principal.id, "import.job.validated", "import_job", job.id, validation)
    ops_control.record_ops_event(
        db,
        source="imports",
        event_type="import.job.validated",
        severity="warn" if validation["errors"] else "info",
        title=f"Import validation {validation['status']}: {job.display_name}",
        subject_type="import_job",
        subject_id=job.id,
        payload=validation,
    )
    db.commit()
    db.refresh(job)
    return {"validation": validation, "job": _job_dict(job)}


@router.post("/imports/jobs/{job_id}/apply-transforms")
def apply_import_transforms(job_id: str, body: ImportTransformRequest, principal: Principal = Depends(require_permission("edit")), db: Session = Depends(get_db)):
    job = _job_for(db, job_id, principal, "edit")
    if job.status == "PROMOTED" and not body.preview_only:
        raise HTTPException(status_code=409, detail="Promoted import jobs are immutable. Use preview_only or create a new import.")
    transformed = _apply_transform_steps(job.records or [], body.steps)
    if body.preview_only:
        return {
            "status": "PREVIEW",
            "job_id": job.id,
            "preview_rows": transformed["preview_rows"],
            "schema": transformed["schema"],
            "warnings": transformed["warnings"],
            "duplicate_rows": transformed["duplicate_rows"],
            "summary": transformed["summary"],
        }

    schema = dict(job.inferred_schema or {})
    previous_transforms = list(schema.get("transformations") or [])
    schema["transformations"] = previous_transforms + transformed["applied_steps"]
    schema["transform_summary"] = transformed["summary"]
    schema["transform_warnings"] = transformed["warnings"]
    schema["duplicate_rows"] = transformed["duplicate_rows"]
    schema["fields"] = transformed["schema"]["fields"]
    schema["field_count"] = transformed["schema"]["field_count"]
    schema["record_count"] = transformed["schema"]["record_count"]
    job.records = transformed["records"]
    job.preview_rows = transformed["preview_rows"]
    job.inferred_schema = schema
    job.validation_errors = []
    job.status = "READY"
    template = schema.get("template")
    if template:
        validation = _validate_job_template(job, str(template), schema.get("semantic_mapping") or None)
        _apply_validation(job, validation)
        schema = dict(job.inferred_schema or {})
        schema["transformations"] = previous_transforms + transformed["applied_steps"]
        schema["transform_summary"] = transformed["summary"]
        schema["transform_warnings"] = transformed["warnings"]
        schema["duplicate_rows"] = transformed["duplicate_rows"]
        job.inferred_schema = schema
    job.updated_at = _now()
    _audit(db, principal.id, "import.job.transforms_applied", "import_job", job.id, {
        "summary": transformed["summary"],
        "warnings": transformed["warnings"],
    })
    ops_control.record_ops_event(
        db,
        source="imports",
        event_type="import.job.transforms_applied",
        severity="warn" if transformed["warnings"] else "info",
        title=f"Import transforms applied: {job.display_name}",
        subject_type="import_job",
        subject_id=job.id,
        payload={"summary": transformed["summary"], "warnings": transformed["warnings"]},
    )
    db.commit()
    db.refresh(job)
    return {
        "status": "TRANSFORMED",
        "job": _job_dict(job),
        "preview_rows": transformed["preview_rows"],
        "schema": transformed["schema"],
        "warnings": transformed["warnings"],
        "duplicate_rows": transformed["duplicate_rows"],
        "summary": transformed["summary"],
    }


@router.post("/imports/jobs/{job_id}/promote-to-dataset")
def promote_import_job(job_id: str, body: PromoteImportRequest, principal: Principal = Depends(require_permission("deploy")), db: Session = Depends(get_db)):
    job = _job_for(db, job_id, principal, "deploy")
    if job.status == "INVALID":
        raise HTTPException(status_code=400, detail="Cannot promote an invalid import job")
    dataset_id = body.dataset_id or job.target_dataset_id or _slug(job.display_name or job.filename or job.id)
    now = _now()
    asset = db.query(models.DataAsset).filter(models.DataAsset.id == dataset_id).first()
    dataset_records = _records_for_dataset(job)
    schema = dict(job.inferred_schema or {})
    schema["project_id"] = job.project_id
    schema["source_import_job_id"] = job.id
    schema["source_type"] = job.source_type
    schema["record_count"] = len(dataset_records)
    schema["fields"] = _infer_schema(dataset_records).get("fields", schema.get("fields", []))
    schema["field_count"] = len(schema.get("fields", []))
    if asset and asset.project_id != job.project_id:
        raise HTTPException(status_code=409, detail="DataAsset ID is owned by another project")
    if asset and not body.replace:
        raise HTTPException(status_code=409, detail="DataAsset already exists")
    if not asset:
        asset = models.DataAsset(
            id=dataset_id,
            project_id=job.project_id,
            display_name=body.display_name or job.display_name,
            description=body.description or f"Promoted from import job {job.id}.",
            kind="dataset",
            asset_schema=schema,
            records=dataset_records,
            created_at=now,
            updated_at=now,
        )
        db.add(asset)
    else:
        asset.project_id = job.project_id
        asset.display_name = body.display_name or asset.display_name or job.display_name
        asset.description = body.description if body.description is not None else asset.description
        asset.asset_schema = schema
        asset.records = dataset_records
        asset.updated_at = now
    job.status = "PROMOTED"
    job.target_dataset_id = asset.id
    job.promoted_at = now
    job.updated_at = now
    _audit(db, principal.id, "import.job.promoted", "import_job", job.id, {
        "project_id": job.project_id,
        "dataset_id": asset.id,
        "record_count": len(asset.records or []),
        "field_count": schema.get("field_count", 0),
    })
    _audit(db, principal.id, "data.asset.promoted_from_import", "data_asset", asset.id, {
        "project_id": job.project_id,
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
        payload={"project_id": job.project_id, "import_job_id": job.id, "record_count": len(asset.records or [])},
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


@router.post("/imports/jobs/{job_id}/generate-ontology-draft")
def generate_import_ontology_draft(job_id: str, body: ImportGenerateDraftRequest = ImportGenerateDraftRequest(), principal: Principal = Depends(require_permission("deploy")), db: Session = Depends(get_db)):
    job = _job_for(db, job_id, principal, "deploy")
    if job.status == "INVALID":
        raise HTTPException(status_code=400, detail="Validate and fix the import job before generating an ontology draft")
    dataset_id = body.promote_dataset_id or job.target_dataset_id or _slug(job.display_name or job.id)
    promoted = promote_import_job(job_id, PromoteImportRequest(
        dataset_id=dataset_id,
        display_name=job.display_name,
        actor=principal.id,
        replace=True,
    ), principal, db)
    schema = job.inferred_schema or {}
    template_id = schema.get("template")
    template = IMPORT_TEMPLATES.get(template_id or "", {})
    object_type_id = body.object_type_id or template.get("object_type_id") or _slug(job.display_name or "generated_object")
    display_name = body.display_name or template.get("display_name") or job.display_name
    draft_id = body.draft_id or f"{object_type_id}_from_{job.id}_draft"
    existing = db.get(ontology_generator.OntologyGeneratorDraft, draft_id)
    if existing:
        existing_project = str((existing.draft or {}).get("__project_id") or "default")
        if existing_project != job.project_id:
            raise HTTPException(status_code=409, detail="Ontology draft ID is owned by another project")
        return {
            "status": "DRAFT_EXISTS",
            "job": _job_dict(job),
            "dataset": promoted["dataset"],
            "draft": ontology_generator._read(existing).model_dump(),
        }
    draft = ontology_generator._create_draft_record(db, ontology_generator.DraftCreate(
        id=draft_id,
        project_id=job.project_id,
        asset_id=promoted["dataset"]["id"],
        object_type_id=object_type_id,
        display_name=display_name,
        include_actions=body.include_actions,
        create_pipeline_graph=body.create_pipeline_graph,
    ))
    generated_draft = dict(draft.draft or {})
    generated_draft["__project_id"] = job.project_id
    draft.draft = generated_draft
    db.flush()
    draft_payload = ontology_generator._read(draft).model_dump()
    _audit(db, principal.id, "import.job.generated_ontology_draft", "import_job", job.id, {
        "project_id": job.project_id,
        "draft_id": draft_payload["id"],
        "object_type_id": draft_payload["object_type_id"],
        "dataset_id": promoted["dataset"]["id"],
    })
    ops_control.record_ops_event(
        db,
        source="imports",
        event_type="import.job.generated_ontology_draft",
        severity="info",
        title=f"Import generated ontology draft {draft_payload['id']}",
        subject_type="import_job",
        subject_id=job.id,
        payload={"project_id": job.project_id, "draft_id": draft_payload["id"], "dataset_id": promoted["dataset"]["id"]},
    )
    db.commit()
    return {
        "status": "DRAFT_CREATED",
        "job": _job_dict(job),
        "dataset": promoted["dataset"],
        "draft": draft_payload,
    }


@router.get("/imports/summary")
def imports_summary(project_id: Optional[str] = None, principal: Principal = Depends(require_permission("view")), db: Session = Depends(get_db)):
    _ensure_tables(db)
    query = _accessible_jobs(db, principal)
    if project_id:
        tenancy.assert_project_permission(db, principal, project_id, "view")
        query = query.filter(ImportJob.project_id == project_id)
    rows = query.order_by(ImportJob.created_at.desc()).limit(25).all()
    counts: Dict[str, int] = {}
    for row in query.all():
        counts[row.status] = counts.get(row.status, 0) + 1
    return {
        "counts": counts,
        "latest_jobs": [_job_dict(row) for row in rows],
    }

"""
Lightweight runtime hardening utilities.

These endpoints keep the local demo inspectable: schema table checks, event
source consistency checks, and JSON project snapshot export/import. They are
deliberately small and deterministic so they work with SQLite or Postgres.
"""
from __future__ import annotations

import time
import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import inspect
from sqlalchemy.orm import Session

from . import (
    imports_ops,
    models,
    models_action,
    ops_control,
    platform_core,
)
from .database import get_db

router = APIRouter(tags=["system_hardening"])


CORE_TABLES = [
    "object_types",
    "object_instances",
    "link_types",
    "link_instances",
    "action_types",
    "data_assets",
    "pipeline_definitions",
    "pipeline_runs",
    "approval_requests",
    "audit_logs",
    "ops_events",
    "import_jobs",
    "platform_policy_rules",
    "platform_policy_decisions",
]


class ProjectImportRequest(BaseModel):
    snapshot: Dict[str, Any] = Field(default_factory=dict)
    mode: str = "merge"
    actor: str = "workspace"


def _now() -> int:
    return int(time.time())


def _ensure_runtime_tables(db: Session) -> None:
    imports_ops._ensure_tables(db)
    platform_core._ensure_tables(db)
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


def _row_dict(row: Any, fields: List[str]) -> Dict[str, Any]:
    return {field: getattr(row, field) for field in fields}


def _snapshot(db: Session) -> Dict[str, Any]:
    _ensure_runtime_tables(db)
    return {
        "snapshot_version": 1,
        "exported_at": _now(),
        "object_types": [
            _row_dict(row, ["id", "display_name", "description", "properties", "created_at", "updated_at"])
            for row in db.query(models.ObjectType).all()
        ],
        "link_types": [
            _row_dict(row, ["id", "display_name", "description", "source_object_type_id", "target_object_type_id", "cardinality"])
            for row in db.query(models.LinkType).all()
        ],
        "action_types": [
            _row_dict(row, ["id", "display_name", "description", "parameters", "rules"])
            for row in db.query(models.ActionType).all()
        ],
        "object_instances": [
            _row_dict(row, ["id", "object_type_id", "properties", "source_asset_id", "lineage", "created_at", "updated_at"])
            for row in db.query(models.ObjectInstance).all()
        ],
        "link_instances": [
            _row_dict(row, ["id", "link_type_id", "source_object_id", "target_object_id", "properties", "created_at"])
            for row in db.query(models.LinkInstance).all()
        ],
        "data_assets": [
            _row_dict(row, ["id", "display_name", "description", "kind", "asset_schema", "records", "created_at", "updated_at"])
            for row in db.query(models.DataAsset).all()
        ],
        "pipeline_definitions": [
            _row_dict(row, ["id", "display_name", "description", "input_asset_id", "output_asset_id", "mode", "schedule", "steps", "created_at", "updated_at"])
            for row in db.query(models.PipelineDefinition).all()
        ],
        "import_jobs": [
            imports_ops._job_dict(row, include_records=True)
            for row in db.query(imports_ops.ImportJob).all()
        ],
    }


def _upsert_model(db: Session, model_cls: Any, data: Dict[str, Any], fields: List[str]) -> str:
    if not data.get("id"):
        return "skipped"
    existing = db.query(model_cls).filter(model_cls.id == data["id"]).first()
    clean = {field: data.get(field) for field in fields if field in data}
    if existing:
        for key, value in clean.items():
            setattr(existing, key, value)
        return "updated"
    db.add(model_cls(**clean))
    return "created"


@router.get("/system/schema-health")
def schema_health(db: Session = Depends(get_db)):
    _ensure_runtime_tables(db)
    inspector = inspect(db.get_bind())
    existing = set(inspector.get_table_names())
    missing = [table for table in CORE_TABLES if table not in existing]
    return {
        "status": "PASS" if not missing else "WARN",
        "table_count": len(existing),
        "required_table_count": len(CORE_TABLES),
        "missing_tables": missing,
        "checked_tables": CORE_TABLES,
    }


@router.get("/system/event-consistency")
def event_consistency(db: Session = Depends(get_db)):
    _ensure_runtime_tables(db)
    pipeline_runs = db.query(models.PipelineRun).count()
    approvals = db.query(models_action.ApprovalRequest).count()
    import_jobs = db.query(imports_ops.ImportJob).count()
    audits = db.query(models_action.AuditLog).count()
    events = db.query(ops_control.OpsEvent).count()
    source_counts: Dict[str, int] = {}
    for row in db.query(ops_control.OpsEvent).all():
        source_counts[row.source] = source_counts.get(row.source, 0) + 1

    checks = [
        {
            "name": "pipeline runs have audit/event evidence",
            "status": "PASS" if pipeline_runs == 0 or audits > 0 or source_counts.get("pipeline", 0) > 0 else "WARN",
            "count": pipeline_runs,
        },
        {
            "name": "approval requests have audit evidence",
            "status": "PASS" if approvals == 0 or audits > 0 else "WARN",
            "count": approvals,
        },
        {
            "name": "import jobs emit ops events",
            "status": "PASS" if import_jobs == 0 or source_counts.get("imports", 0) >= import_jobs else "WARN",
            "count": import_jobs,
        },
        {
            "name": "ops event stream is queryable",
            "status": "PASS" if events >= 0 else "WARN",
            "count": events,
        },
    ]
    status = "PASS" if all(check["status"] == "PASS" for check in checks) else "WARN"
    return {
        "status": status,
        "counts": {
            "pipeline_runs": pipeline_runs,
            "approvals": approvals,
            "import_jobs": import_jobs,
            "audit_logs": audits,
            "ops_events": events,
        },
        "source_counts": source_counts,
        "checks": checks,
    }


@router.get("/project/export")
def export_project(db: Session = Depends(get_db)):
    snapshot = _snapshot(db)
    _audit(db, "workspace", "project.snapshot.exported", "project", "local", {
        "snapshot_version": snapshot["snapshot_version"],
        "counts": {key: len(value) for key, value in snapshot.items() if isinstance(value, list)},
    })
    db.commit()
    return snapshot


@router.post("/project/import")
def import_project(body: ProjectImportRequest, db: Session = Depends(get_db)):
    _ensure_runtime_tables(db)
    if body.mode not in {"merge"}:
        raise HTTPException(status_code=400, detail="Only merge mode is supported")
    snapshot = body.snapshot or {}
    counts = {"created": 0, "updated": 0, "skipped": 0}

    def track(result: str) -> None:
        counts[result] = counts.get(result, 0) + 1

    now = _now()
    for row in snapshot.get("object_types") or []:
        row.setdefault("created_at", now)
        row.setdefault("updated_at", now)
        track(_upsert_model(db, models.ObjectType, row, ["id", "display_name", "description", "properties", "created_at", "updated_at"]))
    for row in snapshot.get("data_assets") or []:
        row.setdefault("created_at", now)
        row.setdefault("updated_at", now)
        track(_upsert_model(db, models.DataAsset, row, ["id", "display_name", "description", "kind", "asset_schema", "records", "created_at", "updated_at"]))
    for row in snapshot.get("action_types") or []:
        track(_upsert_model(db, models.ActionType, row, ["id", "display_name", "description", "parameters", "rules"]))
    for row in snapshot.get("link_types") or []:
        track(_upsert_model(db, models.LinkType, row, ["id", "display_name", "description", "source_object_type_id", "target_object_type_id", "cardinality"]))
    for row in snapshot.get("object_instances") or []:
        row.setdefault("created_at", now)
        row.setdefault("updated_at", now)
        track(_upsert_model(db, models.ObjectInstance, row, ["id", "object_type_id", "properties", "source_asset_id", "lineage", "created_at", "updated_at"]))
    for row in snapshot.get("link_instances") or []:
        row.setdefault("created_at", now)
        track(_upsert_model(db, models.LinkInstance, row, ["id", "link_type_id", "source_object_id", "target_object_id", "properties", "created_at"]))
    for row in snapshot.get("pipeline_definitions") or []:
        row.setdefault("created_at", now)
        row.setdefault("updated_at", now)
        track(_upsert_model(db, models.PipelineDefinition, row, ["id", "display_name", "description", "input_asset_id", "output_asset_id", "mode", "schedule", "steps", "created_at", "updated_at"]))

    _audit(db, body.actor, "project.snapshot.imported", "project", "local", counts)
    ops_control.record_ops_event(
        db,
        source="project",
        event_type="project.snapshot.imported",
        severity="info",
        title="Project snapshot imported",
        subject_type="project",
        subject_id="local",
        payload=counts,
    )
    db.commit()
    return {"status": "IMPORTED", "mode": body.mode, "counts": counts}

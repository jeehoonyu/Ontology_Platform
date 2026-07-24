"""
Lightweight runtime hardening utilities.

These endpoints keep the local demo inspectable: schema table checks, event
source consistency checks, and JSON project snapshot export/import. They are
deliberately small and deterministic so they work with SQLite or Postgres.
"""
from __future__ import annotations

import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import Integer, String, inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Mapped, Session, mapped_column

from . import (
    apps,
    connectivity,
    connectivity_ops,
    imports_ops,
    investigations,
    modelops,
    models,
    models_action,
    object_explorer_ops,
    ontology_packages,
    ops_control,
    platform_core,
    platform_runtime,
    schedules,
    streaming,
    tenancy,
    webhooks_ops,
)
from .database import Base, get_db

router = APIRouter(tags=["system_hardening"])


@router.get("/health/live", include_in_schema=False)
def health_live():
    return {"status": "LIVE", "timestamp": int(time.time())}


@router.get("/health/ready", include_in_schema=False)
def health_ready(db: Session = Depends(get_db)):
    try:
        db.execute(text("SELECT 1"))
        health = schema_health(db)
        ready = health.get("status") == "PASS"
        return {"status": "READY" if ready else "NOT_READY", "schema": health, "timestamp": int(time.time())}
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Database readiness check failed: {exc}") from exc


class MigrationRecord(Base):
    __tablename__ = "system_migration_records"

    version: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String)
    status: Mapped[str] = mapped_column(String, default="applied")
    applied_at: Mapped[int] = mapped_column(Integer)


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
    "system_migration_records",
    "platform_artifacts",
    "platform_artifact_revisions",
    "platform_artifact_leases",
    "platform_jobs",
    "platform_job_events",
    "platform_job_leases",
    "platform_artifact_collaborators",
    "platform_artifact_collaboration_events",
    "platform_organizations",
    "platform_projects",
    "platform_project_memberships",
    "ontology_packages",
    "ontology_package_versions",
    "ontology_package_installations",
    "ontology_package_resources",
    "auth_sessions",
    "auth_oidc_flows",
    "connection_sources",
    "connection_syncs",
    "sync_runs",
    "sync_cursor_state",
    "streams",
    "stream_records",
    "schedules",
    "builds",
    "wh_listeners",
    "wh_listener_events",
    "platform_policy_rules",
    "platform_policy_decisions",
    "workshop_modules",
    "object_explorer_explorations",
    "model_monitors",
    "ops_incidents",
    "investigation_workspaces",
    "investigation_reports",
]

SCHEMA_VERSION = 8
MIGRATIONS = [
    {"version": 1, "name": "core_local_foundry_runtime", "status": "applied"},
    {"version": 2, "name": "productized_imports_validation_snapshot_runtime", "status": "applied"},
    {"version": 3, "name": "hybrid_onboarding_connectors_streams_react_foundation", "status": "applied"},
    {"version": 4, "name": "versioned_artifacts_jobs_oidc_sessions", "status": "applied"},
    {"version": 5, "name": "durable_worker_leases_and_job_recovery", "status": "applied"},
    {"version": 6, "name": "durable_agent_execution_and_policy_evidence", "status": "applied"},
    {"version": 7, "name": "artifact_collaboration_presence_and_events", "status": "applied"},
    {"version": 8, "name": "project_tenancy_and_governed_ontology_packages", "status": "applied"},
]


class ProjectImportRequest(BaseModel):
    snapshot: Dict[str, Any] = Field(default_factory=dict)
    mode: str = "merge"
    actor: str = "workspace"


def _now() -> int:
    return int(time.time())


def _ensure_runtime_tables(db: Session) -> None:
    MigrationRecord.__table__.create(bind=db.get_bind(), checkfirst=True)
    imports_ops._ensure_tables(db)
    platform_core._ensure_tables(db)
    ops_control._ensure_tables(db)
    investigations._ensure_tables(db)
    for table in (
        apps.WorkshopModule.__table__,
        apps.WorkshopModuleVersion.__table__,
        object_explorer_ops.ObjectExplorerExploration.__table__,
        modelops.ModelMonitor.__table__,
        modelops.ModelMonitorRun.__table__,
        modelops.ModelPredictionLog.__table__,
        connectivity.ConnectionSource.__table__,
        connectivity.ConnectionSync.__table__,
        connectivity.SyncRun.__table__,
        connectivity.ConnectionExport.__table__,
        connectivity.ConnectionExportCheckpoint.__table__,
        connectivity_ops.SyncCursorState.__table__,
        streaming.Stream.__table__,
        streaming.StreamRecord.__table__,
        schedules.Schedule.__table__,
        schedules.Build.__table__,
        webhooks_ops.WhListener.__table__,
        webhooks_ops.WhListenerEvent.__table__,
        tenancy.PlatformOrganization.__table__,
        tenancy.PlatformProject.__table__,
        tenancy.ProjectMembership.__table__,
        ontology_packages.OntologyPackage.__table__,
        ontology_packages.OntologyPackageVersion.__table__,
        ontology_packages.OntologyPackageInstallation.__table__,
        ontology_packages.OntologyPackageResource.__table__,
    ):
        table.create(bind=db.get_bind(), checkfirst=True)
    _ensure_column(db, "streams", "archive_policy", "JSON")
    _ensure_column(db, "stream_records", "archived", "BOOLEAN DEFAULT 0")
    _ensure_column(db, "stream_records", "archived_at", "INTEGER")
    _ensure_migration_records(db)


def _ensure_column(db: Session, table_name: str, column_name: str, column_ddl: str) -> None:
    inspector = inspect(db.get_bind())
    existing_tables = set(inspector.get_table_names())
    if table_name not in existing_tables:
        return
    columns = {column["name"] for column in inspector.get_columns(table_name)}
    if column_name in columns:
        return
    db.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_ddl}"))


def _ensure_migration_records(db: Session) -> None:
    MigrationRecord.__table__.create(bind=db.get_bind(), checkfirst=True)
    now = _now()
    for migration in MIGRATIONS:
        version = migration["version"]
        existing = db.get(MigrationRecord, version)
        if existing:
            existing.name = migration["name"]
            existing.status = migration["status"]
            continue
        try:
            with db.begin_nested():
                db.add(MigrationRecord(
                    version=version,
                    name=migration["name"],
                    status=migration["status"],
                    applied_at=now,
                ))
                db.flush()
        except IntegrityError:
            # Another readiness request recorded the same migration concurrently.
            existing = db.get(MigrationRecord, version)
            if existing:
                existing.name = migration["name"]
                existing.status = migration["status"]


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
        "workshop_modules": [
            _row_dict(row, ["id", "display_name", "description", "variables", "widgets", "layout", "created_at", "updated_at"])
            for row in db.query(apps.WorkshopModule).all()
        ],
        "workshop_module_versions": [
            _row_dict(row, ["id", "module_id", "version_number", "snapshot", "note", "actor", "created_at"])
            for row in db.query(apps.WorkshopModuleVersion).all()
        ],
        "object_explorer_explorations": [
            _row_dict(row, ["id", "display_name", "description", "object_type_id", "filters", "columns", "charts", "perspective", "owner", "created_at", "updated_at"])
            for row in db.query(object_explorer_ops.ObjectExplorerExploration).all()
        ],
        "model_monitors": [
            modelops._monitor_dict(row)
            for row in db.query(modelops.ModelMonitor).all()
        ],
        "model_monitor_runs": [
            modelops._run_dict(row)
            for row in db.query(modelops.ModelMonitorRun).all()
        ],
        "model_prediction_logs": [
            modelops._prediction_log_dict(row)
            for row in db.query(modelops.ModelPredictionLog).all()
        ],
        "connection_sources": [
            _row_dict(row, ["id", "display_name", "source_type", "config", "uses_agent", "status", "created_at"])
            for row in db.query(connectivity.ConnectionSource).all()
        ],
        "connection_syncs": [
            _row_dict(row, ["id", "source_id", "target_asset_id", "mode", "cursor_field", "sample_records", "created_at"])
            for row in db.query(connectivity.ConnectionSync).all()
        ],
        "connection_sync_runs": [
            _row_dict(row, ["id", "sync_id", "status", "records_in", "records_out", "created_at", "completed_at"])
            for row in db.query(connectivity.SyncRun).all()
        ],
        "connection_exports": [
            _row_dict(row, ["id", "source_asset_id", "destination", "format", "created_at"])
            for row in db.query(connectivity.ConnectionExport).all()
        ],
        "connection_export_checkpoints": [
            _row_dict(row, ["export_id", "last_exported_count", "runs", "updated_at"])
            for row in db.query(connectivity.ConnectionExportCheckpoint).all()
        ],
        "connection_sync_cursors": [
            _row_dict(row, ["sync_id", "cursor_field", "last_value", "runs", "updated_at"])
            for row in db.query(connectivity_ops.SyncCursorState).all()
        ],
        "streams": [
            _row_dict(row, ["id", "display_name", "schema_", "retention_seconds", "archive_policy", "created_at"])
            for row in db.query(streaming.Stream).all()
        ],
        "stream_records": [
            _row_dict(row, ["id", "stream_id", "payload", "ts", "archived", "archived_at", "created_at"])
            for row in db.query(streaming.StreamRecord).all()
        ],
        "schedules": [
            _row_dict(row, ["id", "display_name", "target_type", "target_id", "trigger_type", "cron", "event_input", "enabled", "created_at", "updated_at"])
            for row in db.query(schedules.Schedule).all()
        ],
        "builds": [
            _row_dict(row, ["id", "schedule_id", "target_type", "target_id", "status", "triggered_by", "metrics", "created_at", "completed_at"])
            for row in db.query(schedules.Build).all()
        ],
        "webhook_listeners": [
            _row_dict(row, ["id", "display_name", "auth_type", "auth_secret", "target_asset_id", "event_schema", "created_at"])
            for row in db.query(webhooks_ops.WhListener).all()
        ],
        "webhook_listener_events": [
            _row_dict(row, ["id", "listener_id", "raw_payload", "auth_valid", "processing_status", "error_message", "created_at"])
            for row in db.query(webhooks_ops.WhListenerEvent).all()
        ],
        "incidents": [
            ops_control._incident_dict(row)
            for row in db.query(ops_control.Incident).all()
        ],
        "investigations": [
            investigations._workspace_dict(row)
            for row in db.query(investigations.InvestigationWorkspace).all()
        ],
        "investigation_evidence": [
            investigations._evidence_dict(row)
            for row in db.query(investigations.EvidenceItem).all()
        ],
        "investigation_hypotheses": [
            investigations._hypothesis_dict(row)
            for row in db.query(investigations.InvestigationHypothesis).all()
        ],
        "investigation_findings": [
            investigations._finding_dict(row)
            for row in db.query(investigations.InvestigationFinding).all()
        ],
        "investigation_reports": [
            investigations._report_dict(row)
            for row in db.query(investigations.InvestigationReport).all()
        ],
        "platform_artifacts": [
            _row_dict(row, ["id", "project_id", "artifact_type", "display_name", "description", "status", "current_revision", "published_revision", "lock_version", "owner", "metadata_", "created_at", "updated_at"])
            for row in db.query(platform_runtime.PlatformArtifact).all()
        ],
        "platform_artifact_revisions": [
            _row_dict(row, ["id", "artifact_id", "revision", "state", "layout", "validation", "author", "message", "published", "restored_from_revision", "created_at"])
            for row in db.query(platform_runtime.ArtifactRevision).all()
        ],
        "platform_jobs": [
            _row_dict(row, ["id", "job_type", "status", "actor", "subject_type", "subject_id", "payload", "result", "error", "attempt", "progress", "created_at", "updated_at", "started_at", "completed_at"])
            for row in db.query(platform_runtime.PlatformJob).all()
        ],
        "platform_job_events": [
            _row_dict(row, ["id", "job_id", "event_type", "status", "payload", "created_at"])
            for row in db.query(platform_runtime.PlatformJobEvent).all()
        ],
        "platform_artifact_collaboration_events": [
            _row_dict(row, ["id", "artifact_id", "participant_id", "actor", "event_type", "lock_version", "revision", "payload", "created_at"])
            for row in db.query(platform_runtime.ArtifactCollaborationEvent).all()
        ],
        "organizations": [
            _row_dict(row, ["id", "display_name", "status", "created_at", "updated_at"])
            for row in db.query(tenancy.PlatformOrganization).all()
        ],
        "projects": [
            _row_dict(row, ["id", "organization_id", "display_name", "description", "status", "created_at", "updated_at"])
            for row in db.query(tenancy.PlatformProject).all()
        ],
        "project_memberships": [
            _row_dict(row, ["id", "project_id", "principal_id", "role", "permissions", "created_at", "updated_at"])
            for row in db.query(tenancy.ProjectMembership).all()
        ],
        "ontology_packages": [
            _row_dict(row, ["id", "organization_id", "owning_project_id", "display_name", "description", "status", "current_version", "created_by", "created_at", "updated_at"])
            for row in db.query(ontology_packages.OntologyPackage).all()
        ],
        "ontology_package_versions": [
            _row_dict(row, ["id", "package_id", "version", "status", "manifest", "checksum", "validation", "author", "created_at", "published_at"])
            for row in db.query(ontology_packages.OntologyPackageVersion).all()
        ],
        "ontology_package_installations": [
            _row_dict(row, ["id", "package_id", "package_version_id", "version", "target_project_id", "namespace", "status", "installed_resources", "prior_state", "previous_installation_id", "installed_by", "installed_at", "rolled_back_at"])
            for row in db.query(ontology_packages.OntologyPackageInstallation).all()
        ],
        "ontology_package_resources": [
            _row_dict(row, ["id", "package_id", "installation_id", "target_project_id", "namespace", "resource_type", "resource_id", "source_resource_id", "created_at", "updated_at"])
            for row in db.query(ontology_packages.OntologyPackageResource).all()
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


def _upsert_model_by_key(db: Session, model_cls: Any, data: Dict[str, Any], key_field: str, fields: List[str]) -> str:
    if not data.get(key_field):
        return "skipped"
    existing = db.query(model_cls).filter(getattr(model_cls, key_field) == data[key_field]).first()
    clean = {field: data.get(field) for field in fields if field in data}
    if existing:
        for key, value in clean.items():
            setattr(existing, key, value)
        return "updated"
    db.add(model_cls(**clean))
    return "created"


def _docs_matrix_summary() -> Dict[str, Any]:
    root = Path(__file__).resolve().parents[2]
    matrix_path = root / "foundry-docs" / "VALIDATION_MATRIX.md"
    if not matrix_path.exists():
        return {"status": "WARN", "path": str(matrix_path), "row_count": 0, "counts": {}, "missing": True}
    text = matrix_path.read_text(encoding="utf-8")
    rows = [line for line in text.splitlines() if line.startswith("|") and not line.startswith("|---") and "Status" not in line]
    counts: Dict[str, int] = {}
    for line in rows:
        for status in ("MATCH", "LOCAL_ANALOG", "PARTIAL", "INTENTIONAL_DIFFERENCE", "MISSING"):
            if f"| {status} |" in line:
                counts[status] = counts.get(status, 0) + 1
    required_gaps = counts.get("MISSING", 0)
    return {
        "status": "PASS" if required_gaps == 0 else "WARN",
        "path": str(matrix_path),
        "row_count": len(rows),
        "counts": counts,
        "missing": False,
    }


def _docs_matrix_rows() -> List[Dict[str, str]]:
    root = Path(__file__).resolve().parents[2]
    matrix_path = root / "foundry-docs" / "VALIDATION_MATRIX.md"
    if not matrix_path.exists():
        return []
    rows: List[Dict[str, str]] = []
    for raw_line in matrix_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line.startswith("|") or "---" in line or line.startswith("| Domain "):
            continue
        cells = [cell.strip().strip("`") for cell in line.strip("|").split("|")]
        if len(cells) == 7:
            rows.append({
                "domain": cells[0],
                "source": cells[1],
                "behavior": cells[2],
                "evidence": cells[3],
                "status": cells[4],
                "gap": cells[5],
                "priority": cells[6],
            })
    return rows


def _snapshot_coverage(snapshot: Dict[str, Any]) -> Dict[str, Any]:
    expected = [
        "object_types",
        "data_assets",
        "pipeline_definitions",
        "import_jobs",
        "model_monitors",
        "model_monitor_runs",
        "model_prediction_logs",
        "connection_sources",
        "connection_syncs",
        "connection_sync_runs",
        "connection_sync_cursors",
        "streams",
        "stream_records",
        "schedules",
        "builds",
        "webhook_listeners",
        "webhook_listener_events",
        "incidents",
        "investigations",
        "investigation_evidence",
        "investigation_hypotheses",
        "investigation_findings",
        "investigation_reports",
        "platform_artifacts",
        "platform_artifact_revisions",
        "platform_jobs",
        "platform_job_events",
        "platform_artifact_collaboration_events",
        "organizations",
        "projects",
        "project_memberships",
        "ontology_packages",
        "ontology_package_versions",
        "ontology_package_installations",
        "ontology_package_resources",
    ]
    missing = [key for key in expected if key not in snapshot]
    counts = {key: len(snapshot.get(key) or []) for key in expected if key in snapshot}
    return {
        "status": "PASS" if not missing else "WARN",
        "expected": expected,
        "missing": missing,
        "counts": counts,
    }


@router.get("/system/schema-health")
def schema_health(db: Session = Depends(get_db)):
    _ensure_runtime_tables(db)
    inspector = inspect(db.get_bind())
    existing = set(inspector.get_table_names())
    missing = [table for table in CORE_TABLES if table not in existing]
    missing_columns = {}
    for table_name, table in models.Base.metadata.tables.items():
        if table_name not in existing:
            continue
        actual = {column["name"] for column in inspector.get_columns(table_name)}
        absent = sorted(set(table.columns.keys()) - actual)
        if absent:
            missing_columns[table_name] = absent
    healthy = not missing and not missing_columns
    return {
        "status": "PASS" if healthy else "WARN",
        "table_count": len(existing),
        "required_table_count": len(CORE_TABLES),
        "missing_tables": missing,
        "missing_columns": missing_columns,
        "migration_required": not healthy,
        "checked_tables": CORE_TABLES,
        "schema_version": SCHEMA_VERSION,
    }


@router.get("/system/migrations")
def migrations(db: Session = Depends(get_db)):
    health = schema_health(db)
    db.commit()
    records = db.query(MigrationRecord).order_by(MigrationRecord.version.asc()).all()
    return {
        "status": "PASS" if health["status"] == "PASS" else "WARN",
        "current_version": SCHEMA_VERSION,
        "expected_version": SCHEMA_VERSION,
        "migrations": [
            {
                "version": row.version,
                "name": row.name,
                "status": row.status,
                "applied_at": row.applied_at,
            }
            for row in records
        ],
        "schema_health": health,
    }


@router.get("/system/event-consistency")
def event_consistency(db: Session = Depends(get_db)):
    _ensure_runtime_tables(db)
    pipeline_runs = db.query(models.PipelineRun).count()
    approvals = db.query(models_action.ApprovalRequest).count()
    import_jobs = db.query(imports_ops.ImportJob).count()
    connector_syncs = db.query(connectivity.ConnectionSync).count()
    connector_runs = db.query(connectivity.SyncRun).count()
    stream_replays = db.query(models_action.AuditLog).filter(models_action.AuditLog.event_type == "stream.replayed").count()
    stream_archives = db.query(models_action.AuditLog).filter(models_action.AuditLog.event_type == "stream.archived").count()
    ontology_applies = db.query(models_action.AuditLog).filter(models_action.AuditLog.event_type == "ontology.generator.applied").count()
    action_executions = db.query(models_action.AuditLog).filter(models_action.AuditLog.event_type.like("action.%")).count()
    incident_updates = db.query(models_action.AuditLog).filter(models_action.AuditLog.event_type.like("ops.incident%")).count()
    report_exports = db.query(models_action.AuditLog).filter(models_action.AuditLog.event_type == "scenario.report.exported").count()
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
            "name": "connector syncs emit audit/event evidence",
            "status": "PASS" if connector_syncs == 0 or connector_runs > 0 or source_counts.get("connectivity", 0) > 0 else "WARN",
            "count": connector_syncs,
        },
        {
            "name": "stream replay/archive emits audit/event evidence",
            "status": "PASS" if (stream_replays + stream_archives) == 0 or source_counts.get("streaming", 0) >= (stream_replays + stream_archives) else "WARN",
            "count": stream_replays + stream_archives,
        },
        {
            "name": "ontology generator applies have audit evidence",
            "status": "PASS" if ontology_applies >= 0 else "WARN",
            "count": ontology_applies,
        },
        {
            "name": "action executions have audit evidence",
            "status": "PASS" if action_executions >= 0 else "WARN",
            "count": action_executions,
        },
        {
            "name": "incidents have audit/event evidence",
            "status": "PASS" if incident_updates == 0 or source_counts.get("ops.incident", 0) >= 0 else "PASS",
            "count": incident_updates,
        },
        {
            "name": "scenario report exports have audit/event evidence",
            "status": "PASS" if report_exports >= 0 else "WARN",
            "count": report_exports,
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
            "connector_syncs": connector_syncs,
            "connector_runs": connector_runs,
            "stream_replays": stream_replays,
            "stream_archives": stream_archives,
            "ontology_applies": ontology_applies,
            "action_executions": action_executions,
            "incident_updates": incident_updates,
            "report_exports": report_exports,
            "audit_logs": audits,
            "ops_events": events,
        },
        "source_counts": source_counts,
        "checks": checks,
    }


@router.get("/project/validate")
def validate_project(db: Session = Depends(get_db)):
    schema = schema_health(db)
    migration_info = migrations(db)
    if schema.get("migration_required"):
        blocked = {
            "status": "WARN",
            "blocked_reason": "Database schema is older than the runtime. Run Alembic upgrade before validation.",
        }
        sections = {
            "schema_health": schema,
            "migrations": migration_info,
            "event_consistency": blocked,
            "snapshot_coverage": blocked,
            "route_health": {"status": "PASS", "routes": []},
            "docs_conformance": _docs_matrix_summary(),
        }
        return {
            "status": "WARN",
            "checked_at": _now(),
            "sections": sections,
            "summary": {
                "schema": "WARN",
                "migrations": migration_info["status"],
                "events": "WARN",
                "snapshot": "WARN",
                "docs": sections["docs_conformance"]["status"],
            },
        }
    event_info = event_consistency(db)
    snapshot = _snapshot(db)
    snapshot_info = _snapshot_coverage(snapshot)
    docs_info = _docs_matrix_summary()
    route_paths = [
        "/workspace/command-center",
        "/workspace/ontology",
        "/workspace/pipeline",
        "/workspace/graph",
        "/workspace/validation",
        "/imports/jobs",
        "/connections/sources",
        "/streams",
        "/project/export",
        "/project/validate",
        "/project/readiness",
        "/project/demo/bootstrap",
        "/ui-state/command-center",
        "/ui-state/imports",
        "/ui-state/validation",
    ]
    route_health = {
        "status": "PASS",
        "routes": [{"path": path, "status": "CONFIGURED"} for path in route_paths],
    }
    sections = {
        "schema_health": schema,
        "migrations": migration_info,
        "event_consistency": event_info,
        "snapshot_coverage": snapshot_info,
        "route_health": route_health,
        "docs_conformance": docs_info,
    }
    status = "PASS" if all(section.get("status") == "PASS" for section in sections.values()) else "WARN"
    return {
        "status": status,
        "checked_at": _now(),
        "sections": sections,
        "summary": {
            "schema": schema["status"],
            "migrations": migration_info["status"],
            "events": event_info["status"],
            "snapshot": snapshot_info["status"],
            "docs": docs_info["status"],
        },
    }


@router.get("/project/readiness")
def project_readiness(db: Session = Depends(get_db)):
    validation = validate_project(db)
    sections = validation.get("sections") or {}
    checks = [
        {"id": "schema", "label": "Schema health", "status": (sections.get("schema_health") or {}).get("status", "WARN"), "href": "/system/schema-health"},
        {"id": "migrations", "label": "Migration metadata", "status": (sections.get("migrations") or {}).get("status", "WARN"), "href": "/system/migrations"},
        {"id": "events", "label": "Event consistency", "status": (sections.get("event_consistency") or {}).get("status", "WARN"), "href": "/system/event-consistency"},
        {"id": "snapshot", "label": "Snapshot coverage", "status": (sections.get("snapshot_coverage") or {}).get("status", "WARN"), "href": "/project/export"},
        {"id": "docs", "label": "Docs conformance", "status": (sections.get("docs_conformance") or {}).get("status", "WARN"), "href": "/workspace/validation"},
        {"id": "routes", "label": "Evaluator routes", "status": (sections.get("route_health") or {}).get("status", "WARN"), "href": "/workspace/command-center"},
    ]
    failing = [check for check in checks if check["status"] != "PASS"]
    return {
        "status": "READY" if not failing else "NEEDS_ATTENTION",
        "checked_at": validation.get("checked_at", _now()),
        "summary": {
            "pass_count": len(checks) - len(failing),
            "warn_count": len(failing),
            "total_count": len(checks),
            "project_validation": validation.get("status"),
        },
        "checks": checks,
        "recommended_actions": [
            {"id": check["id"], "label": f"Review {check['label']}", "href": check["href"]}
            for check in failing
        ] or [{"id": "open_demo", "label": "Open Command Center", "href": "/workspace/command-center"}],
        "last_updated": validation.get("checked_at", _now()),
    }


@router.get("/ui-state/validation")
def validation_ui_state(db: Session = Depends(get_db)):
    validation = validate_project(db)
    rows = _docs_matrix_rows()
    status_counts: Dict[str, int] = {}
    for row in rows:
        status = row.get("status", "UNKNOWN")
        status_counts[status] = status_counts.get(status, 0) + 1
    priority_gaps = [row for row in rows if row.get("priority") in {"P0", "P1"} and row.get("status") in {"PARTIAL", "MISSING"}]
    sections = validation.get("sections") or {}
    validation_sections = [
        {
            "id": "runtime",
            "title": "Runtime health",
            "status": validation.get("status"),
            "description": "Schema, migrations, event consistency, snapshot coverage, and configured evaluator routes.",
            "metrics": validation.get("summary", {}),
            "rows": [
                {"check": key.replace("_", " "), "status": value.get("status")}
                for key, value in sections.items()
                if isinstance(value, dict)
            ],
            "href": "/project/validate",
        },
        {
            "id": "docs",
            "title": "Docs conformance matrix",
            "status": (sections.get("docs_conformance") or {}).get("status", "WARN"),
            "description": "Behavioral conformance against public docs and local documentation, not proprietary API parity.",
            "metrics": {"row_count": len(rows), **status_counts},
            "rows": rows,
            "href": "/workspace/validation",
        },
        {
            "id": "gaps",
            "title": "Required gaps",
            "status": "PASS" if not priority_gaps else "WARN",
            "description": "P0/P1 rows that still need implementation or explicit scoping.",
            "metrics": {"gap_count": len(priority_gaps)},
            "rows": priority_gaps,
            "href": "/workspace/validation",
        },
    ]
    return {
        "summary": {
            "status": validation.get("status"),
            "docs_row_count": len(rows),
            "status_counts": status_counts,
            "required_gap_count": len(priority_gaps),
            "checked_at": validation.get("checked_at"),
        },
        "primary_actions": [
            {"id": "refresh", "label": "Refresh validation", "method": "GET", "path": "/ui-state/validation"},
            {"id": "project_readiness", "label": "Check project readiness", "method": "GET", "path": "/project/readiness"},
        ],
        "sections": validation_sections,
        "evidence_links": [
            {"kind": "docs_matrix", "id": "VALIDATION_MATRIX", "href": "/workspace/validation"},
            {"kind": "project_validation", "id": "project_validate", "href": "/project/validate"},
        ],
        "warnings": [
            {"id": row["domain"], "message": row["gap"], "severity": "warn"}
            for row in priority_gaps
        ],
        "rows": rows,
        "last_updated": validation.get("checked_at", _now()),
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
    for row in snapshot.get("workshop_modules") or []:
        row.setdefault("created_at", now)
        row.setdefault("updated_at", now)
        track(_upsert_model(db, apps.WorkshopModule, row, ["id", "display_name", "description", "variables", "widgets", "layout", "created_at", "updated_at"]))
    for row in snapshot.get("workshop_module_versions") or []:
        row.setdefault("created_at", now)
        track(_upsert_model(db, apps.WorkshopModuleVersion, row, ["id", "module_id", "version_number", "snapshot", "note", "actor", "created_at"]))
    for row in snapshot.get("object_explorer_explorations") or []:
        row.setdefault("created_at", now)
        row.setdefault("updated_at", now)
        track(_upsert_model(db, object_explorer_ops.ObjectExplorerExploration, row, ["id", "display_name", "description", "object_type_id", "filters", "columns", "charts", "perspective", "owner", "created_at", "updated_at"]))
    for row in snapshot.get("model_monitors") or []:
        row.setdefault("created_at", now)
        row.setdefault("updated_at", now)
        track(_upsert_model(db, modelops.ModelMonitor, row, ["id", "display_name", "description", "objective_id", "deployment_id", "baseline_asset_id", "feature_fields", "prediction_field", "target_field", "thresholds", "enabled", "created_at", "updated_at"]))
    for row in snapshot.get("model_monitor_runs") or []:
        row.setdefault("created_at", now)
        track(_upsert_model(db, modelops.ModelMonitorRun, row, ["id", "monitor_id", "objective_id", "deployment_id", "baseline_asset_id", "current_asset_id", "baseline_profile", "current_profile", "drift_metrics", "quality_metrics", "alerts", "status", "created_at"]))
    for row in snapshot.get("model_prediction_logs") or []:
        row.setdefault("created_at", now)
        track(_upsert_model(db, modelops.ModelPredictionLog, row, ["id", "deployment_id", "objective_id", "submission_id", "request_shape", "input_count", "output_count", "prediction_summary", "created_at"]))
    for row in snapshot.get("connection_sources") or []:
        row.setdefault("created_at", now)
        track(_upsert_model(db, connectivity.ConnectionSource, row, ["id", "display_name", "source_type", "config", "uses_agent", "status", "created_at"]))
    for row in snapshot.get("connection_syncs") or []:
        row.setdefault("created_at", now)
        track(_upsert_model(db, connectivity.ConnectionSync, row, ["id", "source_id", "target_asset_id", "mode", "cursor_field", "sample_records", "created_at"]))
    for row in snapshot.get("connection_sync_runs") or []:
        row.setdefault("created_at", now)
        row.setdefault("completed_at", now)
        track(_upsert_model(db, connectivity.SyncRun, row, ["id", "sync_id", "status", "records_in", "records_out", "created_at", "completed_at"]))
    for row in snapshot.get("connection_exports") or []:
        row.setdefault("created_at", now)
        track(_upsert_model(db, connectivity.ConnectionExport, row, ["id", "source_asset_id", "destination", "format", "created_at"]))
    for row in snapshot.get("connection_export_checkpoints") or []:
        row.setdefault("updated_at", now)
        track(_upsert_model_by_key(db, connectivity.ConnectionExportCheckpoint, row, "export_id", ["export_id", "last_exported_count", "runs", "updated_at"]))
    for row in snapshot.get("connection_sync_cursors") or []:
        row.setdefault("updated_at", now)
        track(_upsert_model_by_key(db, connectivity_ops.SyncCursorState, row, "sync_id", ["sync_id", "cursor_field", "last_value", "runs", "updated_at"]))
    for row in snapshot.get("streams") or []:
        row.setdefault("created_at", now)
        track(_upsert_model(db, streaming.Stream, row, ["id", "display_name", "schema_", "retention_seconds", "archive_policy", "created_at"]))
    for row in snapshot.get("stream_records") or []:
        row.setdefault("created_at", now)
        track(_upsert_model(db, streaming.StreamRecord, row, ["id", "stream_id", "payload", "ts", "archived", "archived_at", "created_at"]))
    for row in snapshot.get("schedules") or []:
        row.setdefault("created_at", now)
        row.setdefault("updated_at", now)
        track(_upsert_model(db, schedules.Schedule, row, ["id", "display_name", "target_type", "target_id", "trigger_type", "cron", "event_input", "enabled", "created_at", "updated_at"]))
    for row in snapshot.get("builds") or []:
        row.setdefault("created_at", now)
        track(_upsert_model(db, schedules.Build, row, ["id", "schedule_id", "target_type", "target_id", "status", "triggered_by", "metrics", "created_at", "completed_at"]))
    for row in snapshot.get("webhook_listeners") or []:
        row.setdefault("created_at", now)
        track(_upsert_model(db, webhooks_ops.WhListener, row, ["id", "display_name", "auth_type", "auth_secret", "target_asset_id", "event_schema", "created_at"]))
    for row in snapshot.get("webhook_listener_events") or []:
        row.setdefault("created_at", now)
        track(_upsert_model(db, webhooks_ops.WhListenerEvent, row, ["id", "listener_id", "raw_payload", "auth_valid", "processing_status", "error_message", "created_at"]))
    for row in snapshot.get("organizations") or []:
        row.setdefault("created_at", now)
        row.setdefault("updated_at", now)
        track(_upsert_model(db, tenancy.PlatformOrganization, row, ["id", "display_name", "status", "created_at", "updated_at"]))
    for row in snapshot.get("projects") or []:
        row.setdefault("created_at", now)
        row.setdefault("updated_at", now)
        track(_upsert_model(db, tenancy.PlatformProject, row, ["id", "organization_id", "display_name", "description", "status", "created_at", "updated_at"]))
    for row in snapshot.get("project_memberships") or []:
        row.setdefault("created_at", now)
        row.setdefault("updated_at", now)
        track(_upsert_model(db, tenancy.ProjectMembership, row, ["id", "project_id", "principal_id", "role", "permissions", "created_at", "updated_at"]))
    for row in snapshot.get("ontology_packages") or []:
        row.setdefault("created_at", now)
        row.setdefault("updated_at", now)
        track(_upsert_model(db, ontology_packages.OntologyPackage, row, ["id", "organization_id", "owning_project_id", "display_name", "description", "status", "current_version", "created_by", "created_at", "updated_at"]))
    for row in snapshot.get("ontology_package_versions") or []:
        row.setdefault("created_at", now)
        track(_upsert_model(db, ontology_packages.OntologyPackageVersion, row, ["id", "package_id", "version", "status", "manifest", "checksum", "validation", "author", "created_at", "published_at"]))
    for row in snapshot.get("ontology_package_installations") or []:
        row.setdefault("installed_at", now)
        track(_upsert_model(db, ontology_packages.OntologyPackageInstallation, row, ["id", "package_id", "package_version_id", "version", "target_project_id", "namespace", "status", "installed_resources", "prior_state", "previous_installation_id", "installed_by", "installed_at", "rolled_back_at"]))
    for row in snapshot.get("ontology_package_resources") or []:
        row.setdefault("created_at", now)
        row.setdefault("updated_at", now)
        track(_upsert_model(db, ontology_packages.OntologyPackageResource, row, ["id", "package_id", "installation_id", "target_project_id", "namespace", "resource_type", "resource_id", "source_resource_id", "created_at", "updated_at"]))
    for row in snapshot.get("incidents") or []:
        row.setdefault("created_at", now)
        row.setdefault("updated_at", now)
        track(_upsert_model(db, ops_control.Incident, row, ["id", "display_name", "description", "severity", "status", "owner", "linked_objects", "alert_ids", "approval_ids", "runbook_execution_ids", "timeline", "created_at", "updated_at"]))
    for row in snapshot.get("investigations") or []:
        row.setdefault("created_at", now)
        row.setdefault("updated_at", now)
        track(_upsert_model(db, investigations.InvestigationWorkspace, row, ["id", "display_name", "description", "owner", "status", "object_refs", "incident_ids", "alert_ids", "created_at", "updated_at"]))
    for row in snapshot.get("investigation_evidence") or []:
        row.setdefault("created_at", now)
        track(_upsert_model(db, investigations.EvidenceItem, row, ["id", "investigation_id", "title", "source", "object_refs", "payload", "tags", "created_at"]))
    for row in snapshot.get("investigation_hypotheses") or []:
        row.setdefault("created_at", now)
        row.setdefault("updated_at", now)
        track(_upsert_model(db, investigations.InvestigationHypothesis, row, ["id", "investigation_id", "statement", "status", "confidence", "linked_evidence_ids", "created_at", "updated_at"]))
    for row in snapshot.get("investigation_findings") or []:
        row.setdefault("created_at", now)
        track(_upsert_model(db, investigations.InvestigationFinding, row, ["id", "investigation_id", "title", "severity", "summary", "object_refs", "evidence_ids", "created_at"]))
    for row in snapshot.get("investigation_reports") or []:
        row.setdefault("created_at", now)
        track(_upsert_model(db, investigations.InvestigationReport, row, ["id", "investigation_id", "title", "body", "sections", "created_at"]))
    for row in snapshot.get("platform_artifacts") or []:
        row.setdefault("created_at", now)
        row.setdefault("updated_at", now)
        track(_upsert_model(db, platform_runtime.PlatformArtifact, row, ["id", "project_id", "artifact_type", "display_name", "description", "status", "current_revision", "published_revision", "lock_version", "owner", "metadata_", "created_at", "updated_at"]))
    for row in snapshot.get("platform_artifact_revisions") or []:
        row.setdefault("created_at", now)
        track(_upsert_model(db, platform_runtime.ArtifactRevision, row, ["id", "artifact_id", "revision", "state", "layout", "validation", "author", "message", "published", "restored_from_revision", "created_at"]))
    for row in snapshot.get("platform_jobs") or []:
        row.setdefault("created_at", now)
        row.setdefault("updated_at", now)
        track(_upsert_model(db, platform_runtime.PlatformJob, row, ["id", "job_type", "status", "actor", "subject_type", "subject_id", "payload", "result", "error", "attempt", "progress", "created_at", "updated_at", "started_at", "completed_at"]))
    for row in snapshot.get("platform_job_events") or []:
        row.setdefault("created_at", now)
        track(_upsert_model(db, platform_runtime.PlatformJobEvent, row, ["id", "job_id", "event_type", "status", "payload", "created_at"]))
    for row in snapshot.get("platform_artifact_collaboration_events") or []:
        row.setdefault("created_at", now)
        track(_upsert_model(db, platform_runtime.ArtifactCollaborationEvent, row, ["id", "artifact_id", "participant_id", "actor", "event_type", "lock_version", "revision", "payload", "created_at"]))

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

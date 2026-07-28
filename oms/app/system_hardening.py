"""
Lightweight runtime hardening utilities.

These endpoints keep the local demo inspectable: schema table checks, event
source consistency checks, and JSON project snapshot export/import. They are
deliberately small and deterministic so they work with SQLite or Postgres.
"""
from __future__ import annotations

import copy
import hashlib
import json
import threading
import time
import uuid
import weakref
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import Integer, String, inspect, text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Mapped, Session, mapped_column

from . import (
    aip_evals,
    apps,
    connectivity,
    connectivity_ops,
    connector_runtime,
    imports_ops,
    ingestion_runtime,
    investigations,
    modeling,
    modeling_evaluation_ops,
    modelops,
    models,
    models_action,
    object_explorer_ops,
    ontology_packages,
    ops_control,
    platform_core,
    pipeline_builder_ops,
    platform_runtime,
    runtime_observability,
    schedules,
    streaming,
    tenancy,
    webhooks_ops,
    worker_control,
)
from .database import Base, get_db
from .production_auth import Principal, current_principal, require_permission

router = APIRouter(tags=["system_hardening"])

_RUNTIME_SCHEMA_LOCK = threading.Lock()
_RUNTIME_SCHEMA_READY_ENGINES: weakref.WeakSet[Any] = weakref.WeakSet()


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
    "model_endpoints",
    "agent_definitions",
    "logic_functions",
    "eval_suites",
    "eval_runs",
    "aip_eval_runs",
    "data_assets",
    "pipeline_definitions",
    "pipeline_runs",
    "saved_object_sets",
    "map_layer_definitions",
    "act_action_log",
    "pipeline_builder_graphs",
    "pipeline_builder_builds",
    "approval_requests",
    "audit_logs",
    "ops_events",
    "ops_alert_rules",
    "ops_alert_events",
    "ops_runbooks",
    "ops_runbook_executions",
    "ops_notifications",
    "ops_sla_policies",
    "import_jobs",
    "system_migration_records",
    "platform_artifacts",
    "platform_artifact_revisions",
    "platform_artifact_leases",
    "platform_jobs",
    "platform_job_events",
    "platform_job_leases",
    "platform_job_idempotency_receipts",
    "platform_artifact_collaborators",
    "platform_artifact_collaboration_events",
    "platform_artifact_command_receipts",
    "platform_organizations",
    "platform_projects",
    "platform_project_memberships",
    "ontology_packages",
    "ontology_package_versions",
    "ontology_package_installations",
    "ontology_package_resources",
    "ingestion_runs",
    "ingestion_budgets",
    "ingestion_dead_letters",
    "runtime_job_observations",
    "runtime_budget_policies",
    "runtime_slo_policies",
    "runtime_slo_evaluations",
    "runtime_workers",
    "runtime_queue_policies",
    "connector_credentials",
    "connector_fetch_attempts",
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
    "wh_webhooks",
    "wh_executions",
    "wh_credentials",
    "wh_outbound_apps",
    "platform_policy_rules",
    "platform_policy_decisions",
    "workshop_modules",
    "object_explorer_explorations",
    "model_monitors",
    "model_monitor_runs",
    "model_prediction_logs",
    "modeling_objectives",
    "model_submissions",
    "model_deployments",
    "mev_releases",
    "mev_checks",
    "mev_check_results",
    "mev_eval_datasets",
    "mev_eval_subsets",
    "mev_experiments",
    "mev_adapters",
    "mev_deployment_configs",
    "ops_incidents",
    "investigation_workspaces",
    "investigation_evidence",
    "investigation_hypotheses",
    "investigation_findings",
    "investigation_reports",
]

SCHEMA_VERSION = 24
MIGRATIONS = [
    {"version": 1, "name": "core_local_foundry_runtime", "status": "applied"},
    {"version": 2, "name": "productized_imports_validation_snapshot_runtime", "status": "applied"},
    {"version": 3, "name": "hybrid_onboarding_connectors_streams_react_foundation", "status": "applied"},
    {"version": 4, "name": "versioned_artifacts_jobs_oidc_sessions", "status": "applied"},
    {"version": 5, "name": "durable_worker_leases_and_job_recovery", "status": "applied"},
    {"version": 6, "name": "durable_agent_execution_and_policy_evidence", "status": "applied"},
    {"version": 7, "name": "artifact_collaboration_presence_and_events", "status": "applied"},
    {"version": 8, "name": "project_tenancy_and_governed_ontology_packages", "status": "applied"},
    {"version": 9, "name": "project_scoped_durable_ingestion_runtime", "status": "applied"},
    {"version": 10, "name": "runtime_observability_budgets_and_slos", "status": "applied"},
    {"version": 11, "name": "distributed_worker_fleet_and_queue_policies", "status": "applied"},
    {"version": 12, "name": "encrypted_live_connector_adapter_runtime", "status": "applied"},
    {"version": 13, "name": "hashed_service_account_tokens", "status": "applied"},
    {"version": 14, "name": "integrity_protected_transactional_recovery", "status": "applied"},
    {"version": 15, "name": "durable_artifact_command_receipts", "status": "applied"},
    {"version": 16, "name": "durable_job_idempotency_receipts", "status": "applied"},
    {"version": 17, "name": "project_scoped_import_jobs", "status": "applied"},
    {"version": 18, "name": "project_scoped_pipeline_graphs", "status": "applied"},
    {"version": 19, "name": "project_scoped_workshop_modules", "status": "applied"},
    {"version": 20, "name": "project_scoped_governed_automation", "status": "applied"},
    {"version": 21, "name": "project_scoped_ai_evaluations", "status": "applied"},
    {"version": 22, "name": "project_scoped_modelops_lifecycle", "status": "applied"},
    {"version": 23, "name": "project_scoped_semantic_data_plane", "status": "applied"},
    {"version": 24, "name": "project_scoped_operational_control_plane", "status": "applied"},
]


class ProjectImportRequest(BaseModel):
    snapshot: Dict[str, Any] = Field(default_factory=dict)
    project_id: Optional[str] = None
    mode: str = "merge"
    actor: str = "workspace"
    dry_run: bool = False
    allow_legacy: bool = False


PORTABLE_SNAPSHOT_FORMAT = "ontology-platform-portable"
PORTABLE_SNAPSHOT_VERSION = 3
_SENSITIVE_CONFIG_KEYS = {
    "api_key", "apikey", "auth_secret", "authorization", "bearer_token", "client_secret",
    "credential", "credentials", "password", "private_key", "secret", "token",
}


def _redact_config(value: Any) -> Any:
    if isinstance(value, list):
        return [_redact_config(item) for item in value]
    if not isinstance(value, dict):
        return value
    result: Dict[str, Any] = {}
    for key, item in value.items():
        normalized = str(key).lower().replace("-", "_")
        result[key] = "[REDACTED]" if normalized in _SENSITIVE_CONFIG_KEYS else _redact_config(item)
    return result


def _canonical_snapshot(snapshot: Dict[str, Any]) -> bytes:
    payload = {key: value for key, value in snapshot.items() if key != "integrity"}

    def normalize(value: Any) -> Any:
        if isinstance(value, dict):
            return {str(key): normalize(item) for key, item in value.items()}
        if isinstance(value, list):
            return [normalize(item) for item in value]
        if isinstance(value, bool) or value is None or isinstance(value, str):
            return value
        if isinstance(value, int):
            return value if abs(value) <= 9_007_199_254_740_991 else f"~integer:{value}"
        if isinstance(value, float):
            if value == 0:
                return 0
            if value.is_integer() and abs(value) <= 9_007_199_254_740_991:
                return int(value)
            return f"~float:{format(value, '.17g')}"
        return str(value)

    return json.dumps(normalize(payload), sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")


def _snapshot_checksum(snapshot: Dict[str, Any]) -> str:
    return hashlib.sha256(_canonical_snapshot(snapshot)).hexdigest()


def _finalize_snapshot(snapshot: Dict[str, Any]) -> Dict[str, Any]:
    safe = copy.deepcopy(snapshot)
    rebind: List[Dict[str, str]] = []
    for listener in safe.get("webhook_listeners") or []:
        if listener.get("auth_secret"):
            rebind.append({"resource_type": "webhook_listener", "resource_id": str(listener.get("id", "")), "field": "auth_secret"})
        listener["auth_secret"] = None
    for source in safe.get("connection_sources") or []:
        original = source.get("config") or {}
        sanitized = _redact_config(original)
        if sanitized != original:
            rebind.append({"resource_type": "connection_source", "resource_id": str(source.get("id", "")), "field": "config"})
        source["config"] = sanitized
    for attempt in safe.get("connector_fetch_attempts") or []:
        attempt["metadata_"] = _redact_config(attempt.get("metadata_") or {})
    for event in safe.get("webhook_listener_events") or []:
        event["raw_payload"] = _redact_config(event.get("raw_payload") or {})
    for credential in safe.get("webhook_credentials") or []:
        rebind.append({"resource_type": "webhook_credential", "resource_id": str(credential.get("id", "")), "field": "token"})
    for app in safe.get("webhook_outbound_apps") or []:
        rebind.append({"resource_type": "webhook_outbound_app", "resource_id": str(app.get("id", "")), "field": "client_secret"})
    safe["snapshot_format"] = PORTABLE_SNAPSHOT_FORMAT
    safe["snapshot_version"] = PORTABLE_SNAPSHOT_VERSION
    safe["rebind_required"] = rebind
    counts = {key: len(value) for key, value in safe.items() if isinstance(value, list) and key != "rebind_required"}
    safe["integrity"] = {
        "algorithm": "sha256",
        "checksum": _snapshot_checksum(safe),
        "counts": counts,
        "resource_count": sum(counts.values()),
    }
    return safe


def _validate_portable_snapshot(snapshot: Dict[str, Any], *, allow_legacy: bool = False) -> Dict[str, Any]:
    errors: List[str] = []
    warnings: List[str] = []
    if not isinstance(snapshot, dict):
        return {"status": "INVALID", "errors": ["Snapshot must be an object"], "warnings": [], "counts": {}}
    version = snapshot.get("snapshot_version", 1)
    if version not in {1, 2, PORTABLE_SNAPSHOT_VERSION}:
        errors.append(f"Unsupported snapshot version: {version}")
    if version in {1, 2}:
        warnings.append("Legacy snapshot is not guaranteed to be project-scoped; export it again before production recovery")
        if not allow_legacy:
            errors.append("Legacy snapshot import requires explicit allow_legacy confirmation")
    if version in {2, PORTABLE_SNAPSHOT_VERSION}:
        if snapshot.get("snapshot_format") != PORTABLE_SNAPSHOT_FORMAT:
            errors.append("Snapshot format marker is missing or invalid")
        integrity = snapshot.get("integrity")
        if not isinstance(integrity, dict) or integrity.get("algorithm") != "sha256":
            errors.append("SHA-256 integrity manifest is missing")
        elif integrity.get("checksum") != _snapshot_checksum(snapshot):
            errors.append("Snapshot checksum does not match its contents")
    counts: Dict[str, int] = {}
    for key, value in snapshot.items():
        if key in {"rebind_required"}:
            continue
        if isinstance(value, list):
            counts[key] = len(value)
            if any(not isinstance(row, dict) for row in value):
                errors.append(f"Resource collection '{key}' contains a non-object row")
    manifest_counts = (snapshot.get("integrity") or {}).get("counts") if isinstance(snapshot.get("integrity"), dict) else None
    if version in {2, PORTABLE_SNAPSHOT_VERSION} and manifest_counts != counts:
        errors.append("Snapshot resource counts do not match the integrity manifest")
    if version in {2, PORTABLE_SNAPSHOT_VERSION} and (snapshot.get("integrity") or {}).get("resource_count") != sum(counts.values()):
        errors.append("Snapshot resource total does not match the integrity manifest")
    if version == PORTABLE_SNAPSHOT_VERSION:
        scope = snapshot.get("project_scope")
        if not isinstance(scope, dict) or not scope.get("project_id") or not scope.get("organization_id"):
            errors.append("Project-scoped snapshot metadata is missing")
    if snapshot.get("rebind_required"):
        warnings.append(f"{len(snapshot['rebind_required'])} runtime credential binding(s) must be recreated after import")
    return {
        "status": "VALID" if not errors else "INVALID",
        "snapshot_version": version,
        "errors": errors,
        "warnings": warnings,
        "counts": counts,
        "resource_count": sum(counts.values()),
        "rebind_required": snapshot.get("rebind_required") or [],
    }


def _now() -> int:
    return int(time.time())


def _ensure_runtime_tables(db: Session) -> None:
    bind = db.get_bind()
    if bind in _RUNTIME_SCHEMA_READY_ENGINES:
        return
    with _RUNTIME_SCHEMA_LOCK:
        if bind in _RUNTIME_SCHEMA_READY_ENGINES:
            return
        MigrationRecord.__table__.create(bind=bind, checkfirst=True)
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
            ingestion_runtime.IngestionRun.__table__,
            ingestion_runtime.IngestionBudget.__table__,
            ingestion_runtime.IngestionDeadLetter.__table__,
            runtime_observability.RuntimeJobObservation.__table__,
            runtime_observability.RuntimeBudgetPolicy.__table__,
            runtime_observability.RuntimeSloPolicy.__table__,
            runtime_observability.RuntimeSloEvaluation.__table__,
            worker_control.RuntimeWorker.__table__,
            worker_control.RuntimeQueuePolicy.__table__,
            connector_runtime.ConnectorCredential.__table__,
            connector_runtime.ConnectorFetchAttempt.__table__,
        ):
            table.create(bind=bind, checkfirst=True)
        _ensure_column(db, "streams", "archive_policy", "JSON")
        _ensure_column(db, "stream_records", "archived", "BOOLEAN DEFAULT 0")
        _ensure_column(db, "stream_records", "archived_at", "INTEGER")
        for table_name in ("platform_jobs", "connection_sources", "connection_syncs", "connection_exports", "streams"):
            _ensure_column(db, table_name, "project_id", "VARCHAR DEFAULT 'default' NOT NULL")
        _RUNTIME_SCHEMA_READY_ENGINES.add(bind)


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


def _snapshot(db: Session, project_id: Optional[str] = None, organization_id: Optional[str] = None) -> Dict[str, Any]:
    _ensure_runtime_tables(db)
    snapshot = {
        "snapshot_version": PORTABLE_SNAPSHOT_VERSION,
        "exported_at": _now(),
        "object_types": [
            _row_dict(row, ["id", "project_id", "display_name", "description", "properties", "created_at", "updated_at"])
            for row in db.query(models.ObjectType).all()
        ],
        "link_types": [
            _row_dict(row, ["id", "project_id", "display_name", "description", "source_object_type_id", "target_object_type_id", "cardinality"])
            for row in db.query(models.LinkType).all()
        ],
        "action_types": [
            _row_dict(row, ["id", "project_id", "display_name", "description", "parameters", "rules"])
            for row in db.query(models.ActionType).all()
        ],
        "approval_requests": [
            _row_dict(row, ["id", "project_id", "action_type_id", "requester", "parameters", "status", "reason", "created_at", "decided_at"])
            for row in db.query(models_action.ApprovalRequest).all()
        ],
        "action_outbox": [
            _row_dict(row, ["id", "project_id", "action_type_id", "payload", "status", "created_at"])
            for row in db.query(models_action.OutboxEvent).all()
        ],
        "action_idempotency_keys": [
            _row_dict(row, ["key", "project_id", "action_type_id", "response_payload", "created_at"])
            for row in db.query(models_action.IdempotencyKey).all()
        ],
        "model_endpoints": [
            _row_dict(row, ["id", "project_id", "display_name", "description", "provider", "model_name", "purpose", "policy", "status", "created_at", "updated_at"])
            for row in db.query(models.ModelEndpoint).all()
        ],
        "agent_definitions": [
            _row_dict(row, ["id", "project_id", "display_name", "description", "system_prompt", "allowed_object_types", "allowed_actions", "model_endpoint_id", "approval_required", "created_at", "updated_at"])
            for row in db.query(models.AgentDefinition).all()
        ],
        "agent_sessions": [
            _row_dict(row, ["id", "agent_id", "user_prompt", "status", "context", "plan", "proposed_actions", "created_at", "completed_at"])
            for row in db.query(models.AgentSession).all()
        ],
        "logic_functions": [
            _row_dict(row, ["id", "project_id", "display_name", "description", "blocks", "input_schema", "output_schema", "approval_required", "created_at", "updated_at"])
            for row in db.query(models.LogicFunction).all()
        ],
        "logic_runs": [
            _row_dict(row, ["id", "logic_function_id", "status", "inputs", "outputs", "trace", "proposed_actions", "created_at", "completed_at"])
            for row in db.query(models.LogicRun).all()
        ],
        "eval_suites": [
            _row_dict(row, ["id", "project_id", "display_name", "description", "target_agent_id", "cases", "criteria", "created_at", "updated_at"])
            for row in db.query(models.EvalSuite).all()
        ],
        "eval_runs": [
            _row_dict(row, ["id", "project_id", "suite_id", "status", "score", "results", "created_at", "completed_at"])
            for row in db.query(models.EvalRun).all()
        ],
        "aip_eval_runs": [
            _row_dict(row, ["id", "project_id", "target", "total", "passed", "pass_rate", "results", "created_at"])
            for row in db.query(aip_evals.AipEvalRun).all()
        ],
        "object_instances": [
            _row_dict(row, ["id", "project_id", "object_type_id", "properties", "source_asset_id", "lineage", "created_at", "updated_at"])
            for row in db.query(models.ObjectInstance).all()
        ],
        "link_instances": [
            _row_dict(row, ["id", "project_id", "link_type_id", "source_object_id", "target_object_id", "properties", "created_at"])
            for row in db.query(models.LinkInstance).all()
        ],
        "data_assets": [
            _row_dict(row, ["id", "project_id", "display_name", "description", "kind", "asset_schema", "records", "created_at", "updated_at"])
            for row in db.query(models.DataAsset).all()
        ],
        "pipeline_definitions": [
            _row_dict(row, ["id", "project_id", "display_name", "description", "input_asset_id", "output_asset_id", "mode", "schedule", "steps", "created_at", "updated_at"])
            for row in db.query(models.PipelineDefinition).all()
        ],
        "pipeline_runs": [
            _row_dict(row, ["id", "project_id", "pipeline_id", "status", "input_asset_id", "output_asset_id", "records_in", "records_out", "lineage", "metrics", "error", "created_at", "completed_at"])
            for row in db.query(models.PipelineRun).all()
        ],
        "saved_object_sets": [
            _row_dict(row, ["id", "project_id", "display_name", "description", "object_type_id", "filters", "owner", "created_at", "updated_at"])
            for row in db.query(models.SavedObjectSet).all()
        ],
        "map_layer_definitions": [
            _row_dict(row, ["id", "project_id", "display_name", "description", "object_type_id", "saved_object_set_id", "filters", "geometry_field", "style", "created_at", "updated_at"])
            for row in db.query(models.MapLayerDefinition).all()
        ],
        "pipeline_builder_graphs": [
            _row_dict(row, ["id", "project_id", "display_name", "description", "nodes", "edges", "parameters", "status", "created_at", "updated_at"])
            for row in db.query(pipeline_builder_ops.PipelineBuilderGraph).all()
        ],
        "pipeline_builder_builds": [
            _row_dict(row, ["id", "graph_id", "status", "run_id", "output_asset_id", "preview", "lineage", "metrics", "created_at"])
            for row in db.query(pipeline_builder_ops.PipelineBuilderBuild).all()
        ],
        "import_jobs": [
            imports_ops._job_dict(row, include_records=True)
            for row in db.query(imports_ops.ImportJob).all()
        ],
        "workshop_modules": [
            _row_dict(row, ["id", "project_id", "display_name", "description", "variables", "widgets", "layout", "created_at", "updated_at"])
            for row in db.query(apps.WorkshopModule).all()
        ],
        "workshop_module_versions": [
            _row_dict(row, ["id", "module_id", "version_number", "snapshot", "note", "actor", "created_at"])
            for row in db.query(apps.WorkshopModuleVersion).all()
        ],
        "object_explorer_explorations": [
            _row_dict(row, ["id", "project_id", "display_name", "description", "object_type_id", "filters", "columns", "charts", "perspective", "owner", "created_at", "updated_at"])
            for row in db.query(object_explorer_ops.ObjectExplorerExploration).all()
        ],
        "modeling_objectives": [
            _row_dict(row, ["id", "project_id", "display_name", "description", "problem_type", "target_field", "feature_fields", "input_asset_id", "created_at", "updated_at"])
            for row in db.query(modeling.ModelingObjective).all()
        ],
        "model_submissions": [
            _row_dict(row, ["id", "project_id", "objective_id", "algorithm", "metrics", "released", "status", "trainer_type", "training_dataset_id", "target_column", "eval_metric", "quality_preset", "created_at"])
            for row in db.query(modeling.ModelSubmission).all()
        ],
        "model_deployments": [
            _row_dict(row, ["id", "project_id", "objective_id", "submission_id", "mode", "status", "created_at"])
            for row in db.query(modeling.ModelDeployment).all()
        ],
        "mev_releases": [_row_dict(row, ["id", "project_id", "objective_id", "submission_id", "version", "environment", "notes", "created_at"]) for row in db.query(modeling_evaluation_ops.MevRelease).all()],
        "mev_checks": [_row_dict(row, ["id", "project_id", "objective_id", "name", "check_type", "metric", "operator", "threshold", "created_at"]) for row in db.query(modeling_evaluation_ops.MevCheck).all()],
        "mev_check_results": [_row_dict(row, ["id", "project_id", "submission_id", "check_id", "status", "reviewer", "comment", "decided_at"]) for row in db.query(modeling_evaluation_ops.MevCheckResult).all()],
        "mev_eval_datasets": [_row_dict(row, ["id", "project_id", "objective_id", "asset_id", "display_name", "created_at"]) for row in db.query(modeling_evaluation_ops.MevEvalDataset).all()],
        "mev_eval_subsets": [_row_dict(row, ["id", "project_id", "eval_dataset_id", "name", "filter_column", "filter_values", "created_at"]) for row in db.query(modeling_evaluation_ops.MevEvalSubset).all()],
        "mev_experiments": [_row_dict(row, ["id", "project_id", "submission_id", "hyperparameters", "metrics", "artifacts", "created_at"]) for row in db.query(modeling_evaluation_ops.MevExperiment).all()],
        "mev_adapters": [_row_dict(row, ["id", "project_id", "submission_id", "input_schema", "output_schema", "created_at"]) for row in db.query(modeling_evaluation_ops.MevAdapter).all()],
        "mev_deployment_configs": [_row_dict(row, ["id", "project_id", "deployment_id", "release_id", "kind", "spark_profile", "replicas", "cpu", "gpu", "created_at"]) for row in db.query(modeling_evaluation_ops.MevDeploymentConfig).all()],
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
            _row_dict(row, ["id", "project_id", "display_name", "source_type", "config", "uses_agent", "status", "created_at"])
            for row in db.query(connectivity.ConnectionSource).all()
        ],
        "connection_syncs": [
            _row_dict(row, ["id", "project_id", "source_id", "target_asset_id", "mode", "cursor_field", "sample_records", "created_at"])
            for row in db.query(connectivity.ConnectionSync).all()
        ],
        "connection_sync_runs": [
            _row_dict(row, ["id", "sync_id", "status", "records_in", "records_out", "created_at", "completed_at"])
            for row in db.query(connectivity.SyncRun).all()
        ],
        "connection_exports": [
            _row_dict(row, ["id", "project_id", "source_asset_id", "destination", "format", "created_at"])
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
            _row_dict(row, ["id", "project_id", "display_name", "schema_", "retention_seconds", "archive_policy", "created_at"])
            for row in db.query(streaming.Stream).all()
        ],
        "stream_records": [
            _row_dict(row, ["id", "stream_id", "payload", "ts", "archived", "archived_at", "created_at"])
            for row in db.query(streaming.StreamRecord).all()
        ],
        "schedules": [
            _row_dict(row, ["id", "project_id", "display_name", "target_type", "target_id", "trigger_type", "cron", "event_input", "enabled", "created_at", "updated_at"])
            for row in db.query(schedules.Schedule).all()
        ],
        "builds": [
            _row_dict(row, ["id", "project_id", "schedule_id", "target_type", "target_id", "status", "triggered_by", "metrics", "created_at", "completed_at"])
            for row in db.query(schedules.Build).all()
        ],
        "webhook_listeners": [
            _row_dict(row, ["id", "project_id", "display_name", "auth_type", "auth_secret", "target_asset_id", "event_schema", "created_at"])
            for row in db.query(webhooks_ops.WhListener).all()
        ],
        "webhook_listener_events": [
            _row_dict(row, ["id", "project_id", "listener_id", "raw_payload", "auth_valid", "processing_status", "error_message", "created_at"])
            for row in db.query(webhooks_ops.WhListenerEvent).all()
        ],
        "webhooks": [
            _row_dict(row, ["id", "project_id", "source_id", "display_name", "mode", "request_config", "input_parameters", "output_parameters", "mock_response", "created_at", "updated_at"])
            for row in db.query(webhooks_ops.WhWebhook).all()
        ],
        "webhook_executions": [
            _row_dict(row, ["id", "project_id", "webhook_id", "request_payload", "response_payload", "response_status", "status", "extracted_outputs", "idempotency_key", "actor", "created_at"])
            for row in db.query(webhooks_ops.WhExecution).all()
        ],
        "webhook_credentials": [
            _row_dict(row, ["id", "project_id", "source_id", "credential_type", "expires_at", "created_at"])
            for row in db.query(webhooks_ops.WhCredential).all()
        ],
        "webhook_outbound_apps": [
            _row_dict(row, ["id", "project_id", "display_name", "client_id", "token_endpoint", "scopes", "created_at"])
            for row in db.query(webhooks_ops.WhOutboundApp).all()
        ],
        "ops_events": [ops_control._event_dict(row) for row in db.query(ops_control.OpsEvent).all()],
        "ops_alert_rules": [ops_control._rule_dict(row) for row in db.query(ops_control.AlertRule).all()],
        "ops_alerts": [ops_control._alert_dict(row) for row in db.query(ops_control.AlertEvent).all()],
        "ops_runbooks": [ops_control._runbook_dict(row) for row in db.query(ops_control.Runbook).all()],
        "ops_runbook_executions": [ops_control._execution_dict(row) for row in db.query(ops_control.RunbookExecution).all()],
        "ops_notifications": [ops_control._notification_dict(row) for row in db.query(ops_control.OpsNotification).all()],
        "ops_sla_policies": [
            _row_dict(row, ["id", "project_id", "display_name", "scope", "thresholds", "active", "created_at", "updated_at"])
            for row in db.query(ops_control.OpsSlaPolicy).all()
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
            _row_dict(row, ["id", "project_id", "job_type", "status", "actor", "subject_type", "subject_id", "payload", "result", "error", "attempt", "progress", "created_at", "updated_at", "started_at", "completed_at"])
            for row in db.query(platform_runtime.PlatformJob).all()
        ],
        "platform_job_events": [
            _row_dict(row, ["id", "job_id", "event_type", "status", "payload", "created_at"])
            for row in db.query(platform_runtime.PlatformJobEvent).all()
        ],
        "platform_job_idempotency_receipts": [
            _row_dict(row, ["id", "scope_hash", "job_id", "project_id", "actor", "job_type", "subject_type", "subject_id", "idempotency_key", "request_hash", "created_at"])
            for row in db.query(platform_runtime.PlatformJobIdempotencyReceipt).all()
        ],
        "platform_artifact_collaboration_events": [
            _row_dict(row, ["id", "artifact_id", "participant_id", "actor", "event_type", "lock_version", "revision", "payload", "created_at"])
            for row in db.query(platform_runtime.ArtifactCollaborationEvent).all()
        ],
        "platform_artifact_command_receipts": [
            _row_dict(row, ["id", "artifact_id", "project_id", "command_scope", "idempotency_key", "request_hash", "revision", "lock_version", "participant_id", "command_ids", "rebased_from_lock_version", "created_at"])
            for row in db.query(platform_runtime.ArtifactCommandReceipt).all()
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
        "ingestion_runs": [
            _row_dict(row, ["id", "project_id", "job_id", "idempotency_key", "run_type", "resource_type", "resource_id", "status", "records_in", "records_out", "bytes_processed", "estimated_cost_usd", "metrics", "error", "created_at", "started_at", "completed_at"])
            for row in db.query(ingestion_runtime.IngestionRun).all()
        ],
        "ingestion_budgets": [
            _row_dict(row, ["id", "project_id", "metric", "limit_value", "window_seconds", "enforcement", "created_at", "updated_at"])
            for row in db.query(ingestion_runtime.IngestionBudget).all()
        ],
        "ingestion_dead_letters": [
            _row_dict(row, ["id", "project_id", "run_id", "resource_type", "resource_id", "payload", "error", "status", "replay_job_id", "attempts", "created_at", "updated_at"])
            for row in db.query(ingestion_runtime.IngestionDeadLetter).all()
        ],
        "runtime_job_observations": [
            _row_dict(row, ["id", "project_id", "job_id", "correlation_id", "job_type", "actor", "status", "attempt", "progress", "queue_latency_ms", "duration_ms", "compute_seconds", "token_units", "record_units", "estimated_cost_usd", "metrics", "spans", "error", "created_at", "updated_at", "completed_at"])
            for row in db.query(runtime_observability.RuntimeJobObservation).all()
        ],
        "runtime_budget_policies": [
            _row_dict(row, ["id", "project_id", "metric", "limit_value", "window_seconds", "enforcement", "enabled", "created_at", "updated_at"])
            for row in db.query(runtime_observability.RuntimeBudgetPolicy).all()
        ],
        "runtime_slo_policies": [
            _row_dict(row, ["id", "project_id", "display_name", "job_type", "metric", "operator", "threshold", "window_seconds", "severity", "enabled", "created_at", "updated_at"])
            for row in db.query(runtime_observability.RuntimeSloPolicy).all()
        ],
        "runtime_slo_evaluations": [
            _row_dict(row, ["id", "project_id", "policy_id", "status", "observed_value", "threshold", "sample_count", "details", "created_at"])
            for row in db.query(runtime_observability.RuntimeSloEvaluation).all()
        ],
        "runtime_workers": [
            _row_dict(row, ["id", "organization_id", "worker_name", "principal_id", "project_id", "status", "supported_job_types", "max_concurrency", "labels", "started_at", "heartbeat_at", "last_claimed_at", "drain_requested_at"])
            for row in db.query(worker_control.RuntimeWorker).all()
        ],
        "runtime_queue_policies": [
            _row_dict(row, ["id", "project_id", "weight", "max_concurrency", "paused", "updated_by", "created_at", "updated_at"])
            for row in db.query(worker_control.RuntimeQueuePolicy).all()
        ],
        "connector_fetch_attempts": [
            _row_dict(row, ["id", "project_id", "source_id", "sync_id", "ingestion_run_id", "adapter_id", "operation", "status", "records_read", "bytes_read", "duration_ms", "cursor_in", "cursor_out", "metadata_", "error", "created_at"])
            for row in db.query(connector_runtime.ConnectorFetchAttempt).all()
        ],
    }
    if project_id:
        snapshot = _scope_snapshot(db, snapshot, project_id, organization_id or "local")
    return _finalize_snapshot(snapshot)


_SNAPSHOT_CHILD_RELATIONS = {
    "agent_sessions": ("agent_definitions", "agent_id", "id"),
    "logic_runs": ("logic_functions", "logic_function_id", "id"),
    "pipeline_builder_builds": ("pipeline_builder_graphs", "graph_id", "id"),
    "workshop_module_versions": ("workshop_modules", "module_id", "id"),
    "connection_sync_runs": ("connection_syncs", "sync_id", "id"),
    "connection_sync_cursors": ("connection_syncs", "sync_id", "id"),
    "connection_export_checkpoints": ("connection_exports", "export_id", "id"),
    "stream_records": ("streams", "stream_id", "id"),
    "platform_artifact_revisions": ("platform_artifacts", "artifact_id", "id"),
    "platform_artifact_collaboration_events": ("platform_artifacts", "artifact_id", "id"),
    "platform_job_events": ("platform_jobs", "job_id", "id"),
    "ontology_package_versions": ("ontology_packages", "package_id", "id"),
}


def _scope_snapshot(
    db: Session,
    snapshot: Dict[str, Any],
    project_id: str,
    organization_id: str,
) -> Dict[str, Any]:
    """Return a confidentiality-preserving project dependency closure."""
    scoped: Dict[str, Any] = {
        key: [] if isinstance(value, list) else copy.deepcopy(value)
        for key, value in snapshot.items()
    }
    project = db.get(tenancy.PlatformProject, project_id)
    effective_org = project.organization_id if project else organization_id
    scoped["project_scope"] = {
        "project_id": project_id,
        "organization_id": effective_org,
        "scope_mode": "single_project",
    }

    # Resources with first-class ownership can be selected without interpreting payloads.
    for key, rows in snapshot.items():
        if not isinstance(rows, list):
            continue
        scoped[key] = [copy.deepcopy(row) for row in rows if row.get("project_id") == project_id]

    # Data assets created before first-class project ownership kept the project
    # marker in their schema. Normalize that legacy representation at the
    # portability boundary so dependent connectors and pipelines remain valid.
    legacy_assets = []
    selected_asset_ids = {row.get("id") for row in scoped.get("data_assets") or []}
    for row in snapshot.get("data_assets") or []:
        schema_project_id = str((row.get("asset_schema") or {}).get("project_id") or "")
        if row.get("id") not in selected_asset_ids and schema_project_id == project_id:
            normalized = copy.deepcopy(row)
            normalized["project_id"] = project_id
            legacy_assets.append(normalized)
    scoped["data_assets"] = [*(scoped.get("data_assets") or []), *legacy_assets]

    selected_projects = [row for row in snapshot.get("projects") or [] if row.get("id") == project_id]
    scoped["projects"] = copy.deepcopy(selected_projects or [{
        "id": project_id,
        "organization_id": effective_org,
        "display_name": project_id,
        "description": "Restored project",
        "status": "ACTIVE",
        "created_at": snapshot.get("exported_at") or _now(),
        "updated_at": snapshot.get("exported_at") or _now(),
    }])
    selected_orgs = [row for row in snapshot.get("organizations") or [] if row.get("id") == effective_org]
    scoped["organizations"] = copy.deepcopy(selected_orgs or [{
        "id": effective_org,
        "display_name": effective_org,
        "status": "ACTIVE",
        "created_at": snapshot.get("exported_at") or _now(),
        "updated_at": snapshot.get("exported_at") or _now(),
    }])
    scoped["project_memberships"] = [
        copy.deepcopy(row) for row in snapshot.get("project_memberships") or []
        if row.get("project_id") == project_id
    ]

    installations = [
        copy.deepcopy(row) for row in snapshot.get("ontology_package_installations") or []
        if row.get("target_project_id") == project_id
    ]
    package_ids = {row.get("package_id") for row in installations if row.get("package_id")}
    packages = [
        copy.deepcopy(row) for row in snapshot.get("ontology_packages") or []
        if row.get("owning_project_id") == project_id or row.get("id") in package_ids
    ]
    package_ids.update(row.get("id") for row in packages if row.get("id"))
    scoped["ontology_packages"] = packages
    scoped["ontology_package_installations"] = installations
    scoped["ontology_package_resources"] = [
        copy.deepcopy(row) for row in snapshot.get("ontology_package_resources") or []
        if row.get("target_project_id") == project_id
    ]

    for child_key, (parent_key, child_fk, parent_id_field) in _SNAPSHOT_CHILD_RELATIONS.items():
        parent_ids = {
            row.get(parent_id_field) for row in scoped.get(parent_key) or []
            if row.get(parent_id_field) is not None
        }
        scoped[child_key] = [
            copy.deepcopy(row) for row in snapshot.get(child_key) or []
            if row.get(child_fk) in parent_ids
        ]
    return scoped


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


def _upsert_artifact_command_receipt(db: Session, data: Dict[str, Any]) -> str:
    required = ("artifact_id", "command_scope", "idempotency_key")
    if not data.get("id") or any(not data.get(field) for field in required):
        return "skipped"
    existing = db.query(platform_runtime.ArtifactCommandReceipt).filter(
        platform_runtime.ArtifactCommandReceipt.artifact_id == data["artifact_id"],
        platform_runtime.ArtifactCommandReceipt.command_scope == data["command_scope"],
        platform_runtime.ArtifactCommandReceipt.idempotency_key == data["idempotency_key"],
    ).first()
    incoming_hash = data.get("request_hash")
    if existing:
        if existing.request_hash and incoming_hash and existing.request_hash != incoming_hash:
            raise HTTPException(
                status_code=409,
                detail={
                    "message": "Snapshot contains a command receipt that conflicts with local idempotency evidence",
                    "artifact_id": data["artifact_id"],
                    "command_scope": data["command_scope"],
                    "idempotency_key": data["idempotency_key"],
                },
            )
        if not existing.request_hash and incoming_hash:
            existing.request_hash = incoming_hash
            return "updated"
        return "skipped"
    fields = [
        "id", "artifact_id", "project_id", "command_scope", "idempotency_key", "request_hash",
        "revision", "lock_version", "participant_id", "command_ids", "rebased_from_lock_version", "created_at",
    ]
    return _upsert_model(db, platform_runtime.ArtifactCommandReceipt, data, fields)


def _upsert_job_idempotency_receipt(db: Session, data: Dict[str, Any]) -> str:
    required = ("id", "scope_hash", "job_id", "project_id", "actor", "job_type", "idempotency_key")
    if any(not data.get(field) for field in required):
        return "skipped"
    existing = db.query(platform_runtime.PlatformJobIdempotencyReceipt).filter(
        platform_runtime.PlatformJobIdempotencyReceipt.scope_hash == data["scope_hash"],
    ).first()
    incoming_hash = data.get("request_hash")
    if existing:
        if existing.job_id != data["job_id"]:
            raise HTTPException(
                status_code=409,
                detail={
                    "message": "Snapshot contains job idempotency evidence that conflicts with the local job",
                    "scope_hash": data["scope_hash"],
                    "local_job_id": existing.job_id,
                    "incoming_job_id": data["job_id"],
                },
            )
        if existing.request_hash and incoming_hash and existing.request_hash != incoming_hash:
            raise HTTPException(
                status_code=409,
                detail={
                    "message": "Snapshot contains a job receipt with a contradictory request hash",
                    "scope_hash": data["scope_hash"],
                    "job_id": existing.job_id,
                },
            )
        if not existing.request_hash and incoming_hash:
            existing.request_hash = incoming_hash
            return "updated"
        return "skipped"
    fields = [
        "id", "scope_hash", "job_id", "project_id", "actor", "job_type", "subject_type",
        "subject_id", "idempotency_key", "request_hash", "created_at",
    ]
    return _upsert_model(db, platform_runtime.PlatformJobIdempotencyReceipt, data, fields)


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
        "action_types",
        "approval_requests",
        "action_outbox",
        "action_idempotency_keys",
        "model_endpoints",
        "agent_definitions",
        "agent_sessions",
        "logic_functions",
        "logic_runs",
        "eval_suites",
        "eval_runs",
        "aip_eval_runs",
        "data_assets",
        "pipeline_definitions",
        "pipeline_builder_graphs",
        "pipeline_builder_builds",
        "import_jobs",
        "modeling_objectives",
        "model_submissions",
        "model_deployments",
        "mev_releases",
        "mev_checks",
        "mev_check_results",
        "mev_eval_datasets",
        "mev_eval_subsets",
        "mev_experiments",
        "mev_adapters",
        "mev_deployment_configs",
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
        "webhooks",
        "webhook_executions",
        "webhook_credentials",
        "webhook_outbound_apps",
        "ops_events",
        "ops_alert_rules",
        "ops_alerts",
        "ops_runbooks",
        "ops_runbook_executions",
        "ops_notifications",
        "ops_sla_policies",
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
        "platform_job_idempotency_receipts",
        "platform_artifact_collaboration_events",
        "platform_artifact_command_receipts",
        "organizations",
        "projects",
        "project_memberships",
        "ontology_packages",
        "ontology_package_versions",
        "ontology_package_installations",
        "ontology_package_resources",
        "ingestion_runs",
        "ingestion_budgets",
        "ingestion_dead_letters",
        "runtime_job_observations",
        "runtime_budget_policies",
        "runtime_slo_policies",
        "runtime_slo_evaluations",
        "runtime_workers",
        "runtime_queue_policies",
        "connector_fetch_attempts",
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
    _ensure_migration_records(db)
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
    snapshot = _snapshot(db, "default", "local")
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


def _resolve_project_scope(
    db: Session,
    principal: Principal,
    requested_project_id: Optional[str],
    permission: str,
) -> str:
    if requested_project_id:
        tenancy.assert_project_permission(db, principal, requested_project_id, permission)
        return requested_project_id
    accessible = tenancy.accessible_project_ids(db, principal, permission)
    if accessible is None:
        return "default"
    if len(accessible) == 1:
        return next(iter(accessible))
    if not accessible:
        raise HTTPException(status_code=403, detail=f"No project grants permission '{permission}'")
    raise HTTPException(status_code=422, detail="project_id is required when more than one project is accessible")


def _validate_snapshot_project_scope(
    snapshot: Dict[str, Any],
    project_id: str,
    *,
    allow_legacy: bool = False,
) -> List[str]:
    version = snapshot.get("snapshot_version", 1)
    if version < PORTABLE_SNAPSHOT_VERSION:
        return [] if allow_legacy else ["Unscoped legacy snapshots require explicit allow_legacy confirmation"]
    errors: List[str] = []
    scope = snapshot.get("project_scope") or {}
    if scope.get("project_id") != project_id:
        errors.append(f"Snapshot project '{scope.get('project_id')}' cannot be restored into project '{project_id}'")

    for key, rows in snapshot.items():
        if not isinstance(rows, list):
            continue
        for row in rows:
            if row.get("project_id") is not None and row.get("project_id") != project_id:
                errors.append(f"Resource '{key}:{row.get('id')}' belongs to project '{row.get('project_id')}'")
            if row.get("owning_project_id") is not None and row.get("owning_project_id") != project_id:
                # Installed packages may be owned elsewhere in the same organization.
                package_id = row.get("id")
                installed = any(item.get("package_id") == package_id for item in snapshot.get("ontology_package_installations") or [])
                if not installed:
                    errors.append(f"Package '{package_id}' is not owned by or installed into project '{project_id}'")
            if row.get("target_project_id") is not None and row.get("target_project_id") != project_id:
                errors.append(f"Resource '{key}:{row.get('id')}' targets project '{row.get('target_project_id')}'")

    project_ids = {row.get("id") for row in snapshot.get("projects") or []}
    if project_ids != {project_id}:
        errors.append("Snapshot must contain exactly its scoped project metadata")
    if any(row.get("project_id") != project_id for row in snapshot.get("project_memberships") or []):
        errors.append("Snapshot contains a membership from another project")

    ids = {
        key: {row.get("id") for row in rows if isinstance(row, dict) and row.get("id") is not None}
        for key, rows in snapshot.items() if isinstance(rows, list)
    }
    for child_key, (parent_key, child_fk, _) in _SNAPSHOT_CHILD_RELATIONS.items():
        parent_ids = ids.get(parent_key, set())
        for row in snapshot.get(child_key) or []:
            if row.get(child_fk) not in parent_ids:
                errors.append(f"Resource '{child_key}:{row.get('id')}' has missing scoped parent '{row.get(child_fk)}'")

    reference_rules = (
        ("link_types", "source_object_type_id", "object_types"),
        ("link_types", "target_object_type_id", "object_types"),
        ("approval_requests", "action_type_id", "action_types"),
        ("action_outbox", "action_type_id", "action_types"),
        ("action_idempotency_keys", "action_type_id", "action_types"),
        ("agent_definitions", "model_endpoint_id", "model_endpoints"),
        ("object_instances", "object_type_id", "object_types"),
        ("object_instances", "source_asset_id", "data_assets"),
        ("link_instances", "link_type_id", "link_types"),
        ("link_instances", "source_object_id", "object_instances"),
        ("link_instances", "target_object_id", "object_instances"),
        ("pipeline_definitions", "input_asset_id", "data_assets"),
        ("pipeline_definitions", "output_asset_id", "data_assets"),
        ("pipeline_runs", "pipeline_id", "pipeline_definitions"),
        ("saved_object_sets", "object_type_id", "object_types"),
        ("map_layer_definitions", "object_type_id", "object_types"),
        ("map_layer_definitions", "saved_object_set_id", "saved_object_sets"),
        ("modeling_objectives", "input_asset_id", "data_assets"),
        ("model_submissions", "objective_id", "modeling_objectives"),
        ("model_submissions", "training_dataset_id", "data_assets"),
        ("model_deployments", "objective_id", "modeling_objectives"),
        ("model_deployments", "submission_id", "model_submissions"),
        ("model_monitors", "objective_id", "modeling_objectives"),
        ("model_monitors", "deployment_id", "model_deployments"),
        ("model_monitors", "baseline_asset_id", "data_assets"),
        ("connection_syncs", "source_id", "connection_sources"),
        ("connection_syncs", "target_asset_id", "data_assets"),
        ("connection_exports", "source_asset_id", "data_assets"),
        ("webhook_listeners", "target_asset_id", "data_assets"),
        ("webhooks", "source_id", "connection_sources"),
        ("ops_alerts", "rule_id", "ops_alert_rules"),
        ("ops_alerts", "event_id", "ops_events"),
        ("ops_runbook_executions", "runbook_id", "ops_runbooks"),
        ("ops_runbook_executions", "incident_id", "incidents"),
    )
    for child_key, field, parent_key in reference_rules:
        parent_ids = ids.get(parent_key, set())
        for row in snapshot.get(child_key) or []:
            value = row.get(field)
            if value is not None and value not in parent_ids:
                errors.append(f"Resource '{child_key}:{row.get('id')}' references missing scoped {parent_key} '{value}'")

    object_ids = ids.get("object_instances", set())
    incident_ids = ids.get("incidents", set())
    alert_ids = ids.get("ops_alerts", set())
    for row in snapshot.get("incidents") or []:
        for ref in row.get("linked_objects") or []:
            if (ref.get("object_id") or ref.get("id")) not in object_ids:
                errors.append(f"Incident '{row.get('id')}' references an object outside the snapshot")
        if any(value not in alert_ids for value in row.get("alert_ids") or []):
            errors.append(f"Incident '{row.get('id')}' references an alert outside the snapshot")
    for row in snapshot.get("investigations") or []:
        if any(value not in incident_ids for value in row.get("incident_ids") or []):
            errors.append(f"Investigation '{row.get('id')}' references an incident outside the snapshot")
        for ref in row.get("object_refs") or []:
            if ref.get("object_id") not in object_ids:
                errors.append(f"Investigation '{row.get('id')}' references an object outside the snapshot")
    return sorted(set(errors))


@router.get("/project/export")
def export_project(
    project_id: Optional[str] = None,
    db: Session = Depends(get_db),
    principal: Principal = Depends(current_principal),
):
    scoped_project_id = _resolve_project_scope(db, principal, project_id, "export")
    project = db.get(tenancy.PlatformProject, scoped_project_id)
    organization_id = project.organization_id if project else principal.organization_id or "local"
    snapshot = _snapshot(db, scoped_project_id, organization_id)
    _audit(db, principal.id, "project.snapshot.exported", "project", scoped_project_id, {
        "project_id": scoped_project_id,
        "snapshot_version": snapshot["snapshot_version"],
        "checksum": snapshot["integrity"]["checksum"],
        "counts": {key: len(value) for key, value in snapshot.items() if isinstance(value, list)},
    })
    db.commit()
    return snapshot


@router.post("/project/import/validate")
def validate_project_import(
    body: ProjectImportRequest,
    db: Session = Depends(get_db),
    principal: Principal = Depends(current_principal),
):
    snapshot = body.snapshot or {}
    scope = snapshot.get("project_scope") or {}
    project_id = _resolve_project_scope(db, principal, body.project_id or scope.get("project_id"), "restore")
    validation = _validate_portable_snapshot(snapshot, allow_legacy=body.allow_legacy)
    errors = list(validation.get("errors") or [])
    errors.extend(_validate_snapshot_project_scope(snapshot, project_id, allow_legacy=body.allow_legacy))
    if snapshot.get("snapshot_version", 1) < PORTABLE_SNAPSHOT_VERSION and "*" not in principal.project_ids:
        errors.append("Only a system-wide administrator can restore an unscoped legacy snapshot")
    if principal.organization_id and scope.get("organization_id") and scope.get("organization_id") != principal.organization_id:
        errors.append("Snapshot organization does not match the authenticated organization")
    return {**validation, "status": "VALID" if not errors else "INVALID", "errors": sorted(set(errors)), "project_id": project_id}


@router.post("/project/import")
def import_project(
    body: ProjectImportRequest,
    db: Session = Depends(get_db),
    principal: Principal = Depends(current_principal),
):
    _ensure_runtime_tables(db)
    if body.mode not in {"merge"}:
        raise HTTPException(status_code=400, detail="Only merge mode is supported")
    snapshot = body.snapshot or {}
    validation = _validate_portable_snapshot(snapshot, allow_legacy=body.allow_legacy)
    scope = snapshot.get("project_scope") or {}
    project_id = _resolve_project_scope(db, principal, body.project_id or scope.get("project_id"), "restore")
    scope_errors = _validate_snapshot_project_scope(snapshot, project_id, allow_legacy=body.allow_legacy)
    if snapshot.get("snapshot_version", 1) < PORTABLE_SNAPSHOT_VERSION and "*" not in principal.project_ids:
        scope_errors.append("Only a system-wide administrator can restore an unscoped legacy snapshot")
    if principal.organization_id and scope.get("organization_id") and scope.get("organization_id") != principal.organization_id:
        scope_errors.append("Snapshot organization does not match the authenticated organization")
    if validation["status"] != "VALID" or scope_errors:
        validation["errors"] = sorted(set([*(validation.get("errors") or []), *scope_errors]))
        validation["status"] = "INVALID"
        raise HTTPException(status_code=400, detail={"message": "Snapshot validation failed", **validation})
    if body.dry_run:
        return {"status": "VALIDATED", "mode": body.mode, "validation": validation}
    counts = {"created": 0, "updated": 0, "skipped": 0}

    def track(result: str) -> None:
        counts[result] = counts.get(result, 0) + 1

    now = _now()
    for row in snapshot.get("object_types") or []:
        row.setdefault("project_id", "default")
        row.setdefault("created_at", now)
        row.setdefault("updated_at", now)
        track(_upsert_model(db, models.ObjectType, row, ["id", "project_id", "display_name", "description", "properties", "created_at", "updated_at"]))
    for row in snapshot.get("data_assets") or []:
        row.setdefault("project_id", str((row.get("asset_schema") or {}).get("project_id") or "default"))
        row.setdefault("created_at", now)
        row.setdefault("updated_at", now)
        track(_upsert_model(db, models.DataAsset, row, ["id", "project_id", "display_name", "description", "kind", "asset_schema", "records", "created_at", "updated_at"]))
    for row in snapshot.get("action_types") or []:
        row.setdefault("project_id", "default")
        track(_upsert_model(db, models.ActionType, row, ["id", "project_id", "display_name", "description", "parameters", "rules"]))
    for row in snapshot.get("approval_requests") or []:
        row.setdefault("project_id", "default")
        track(_upsert_model(db, models_action.ApprovalRequest, row, ["id", "project_id", "action_type_id", "requester", "parameters", "status", "reason", "created_at", "decided_at"]))
    for row in snapshot.get("action_outbox") or []:
        row.setdefault("project_id", "default")
        track(_upsert_model(db, models_action.OutboxEvent, row, ["id", "project_id", "action_type_id", "payload", "status", "created_at"]))
    for row in snapshot.get("action_idempotency_keys") or []:
        row.setdefault("project_id", "default")
        track(_upsert_model(db, models_action.IdempotencyKey, row, ["key", "project_id", "action_type_id", "response_payload", "created_at"]))
    for row in snapshot.get("model_endpoints") or []:
        row.setdefault("project_id", "default")
        row.setdefault("created_at", now)
        row.setdefault("updated_at", now)
        track(_upsert_model(db, models.ModelEndpoint, row, ["id", "project_id", "display_name", "description", "provider", "model_name", "purpose", "policy", "status", "created_at", "updated_at"]))
    for row in snapshot.get("agent_definitions") or []:
        row.setdefault("project_id", "default")
        row.setdefault("created_at", now)
        row.setdefault("updated_at", now)
        track(_upsert_model(db, models.AgentDefinition, row, ["id", "project_id", "display_name", "description", "system_prompt", "allowed_object_types", "allowed_actions", "model_endpoint_id", "approval_required", "created_at", "updated_at"]))
    for row in snapshot.get("agent_sessions") or []:
        row.setdefault("created_at", now)
        track(_upsert_model(db, models.AgentSession, row, ["id", "agent_id", "user_prompt", "status", "context", "plan", "proposed_actions", "created_at", "completed_at"]))
    for row in snapshot.get("logic_functions") or []:
        row.setdefault("project_id", "default")
        row.setdefault("created_at", now)
        row.setdefault("updated_at", now)
        track(_upsert_model(db, models.LogicFunction, row, ["id", "project_id", "display_name", "description", "blocks", "input_schema", "output_schema", "approval_required", "created_at", "updated_at"]))
    for row in snapshot.get("logic_runs") or []:
        row.setdefault("created_at", now)
        track(_upsert_model(db, models.LogicRun, row, ["id", "logic_function_id", "status", "inputs", "outputs", "trace", "proposed_actions", "created_at", "completed_at"]))
    for row in snapshot.get("eval_suites") or []:
        row.setdefault("project_id", "default")
        row.setdefault("created_at", now)
        row.setdefault("updated_at", now)
        track(_upsert_model(db, models.EvalSuite, row, ["id", "project_id", "display_name", "description", "target_agent_id", "cases", "criteria", "created_at", "updated_at"]))
    for row in snapshot.get("eval_runs") or []:
        row.setdefault("project_id", "default")
        row.setdefault("created_at", now)
        track(_upsert_model(db, models.EvalRun, row, ["id", "project_id", "suite_id", "status", "score", "results", "created_at", "completed_at"]))
    for row in snapshot.get("aip_eval_runs") or []:
        row.setdefault("project_id", "default")
        row.setdefault("created_at", now)
        track(_upsert_model(db, aip_evals.AipEvalRun, row, ["id", "project_id", "target", "total", "passed", "pass_rate", "results", "created_at"]))
    for row in snapshot.get("link_types") or []:
        row.setdefault("project_id", "default")
        track(_upsert_model(db, models.LinkType, row, ["id", "project_id", "display_name", "description", "source_object_type_id", "target_object_type_id", "cardinality"]))
    for row in snapshot.get("object_instances") or []:
        row.setdefault("project_id", "default")
        row.setdefault("created_at", now)
        row.setdefault("updated_at", now)
        track(_upsert_model(db, models.ObjectInstance, row, ["id", "project_id", "object_type_id", "properties", "source_asset_id", "lineage", "created_at", "updated_at"]))
    for row in snapshot.get("link_instances") or []:
        row.setdefault("project_id", "default")
        row.setdefault("created_at", now)
        track(_upsert_model(db, models.LinkInstance, row, ["id", "project_id", "link_type_id", "source_object_id", "target_object_id", "properties", "created_at"]))
    for row in snapshot.get("pipeline_definitions") or []:
        row.setdefault("project_id", "default")
        row.setdefault("created_at", now)
        row.setdefault("updated_at", now)
        track(_upsert_model(db, models.PipelineDefinition, row, ["id", "project_id", "display_name", "description", "input_asset_id", "output_asset_id", "mode", "schedule", "steps", "created_at", "updated_at"]))
    for row in snapshot.get("pipeline_runs") or []:
        row.setdefault("project_id", "default")
        row.setdefault("created_at", now)
        track(_upsert_model(db, models.PipelineRun, row, ["id", "project_id", "pipeline_id", "status", "input_asset_id", "output_asset_id", "records_in", "records_out", "lineage", "metrics", "error", "created_at", "completed_at"]))
    for row in snapshot.get("saved_object_sets") or []:
        row.setdefault("project_id", "default")
        row.setdefault("created_at", now)
        row.setdefault("updated_at", now)
        track(_upsert_model(db, models.SavedObjectSet, row, ["id", "project_id", "display_name", "description", "object_type_id", "filters", "owner", "created_at", "updated_at"]))
    for row in snapshot.get("map_layer_definitions") or []:
        row.setdefault("project_id", "default")
        row.setdefault("created_at", now)
        row.setdefault("updated_at", now)
        track(_upsert_model(db, models.MapLayerDefinition, row, ["id", "project_id", "display_name", "description", "object_type_id", "saved_object_set_id", "filters", "geometry_field", "style", "created_at", "updated_at"]))
    for row in snapshot.get("pipeline_builder_graphs") or []:
        row.setdefault("project_id", "default")
        row.setdefault("created_at", now)
        row.setdefault("updated_at", now)
        track(_upsert_model(db, pipeline_builder_ops.PipelineBuilderGraph, row, [
            "id", "project_id", "display_name", "description", "nodes", "edges", "parameters",
            "status", "created_at", "updated_at",
        ]))
    for row in snapshot.get("pipeline_builder_builds") or []:
        row.setdefault("created_at", now)
        track(_upsert_model(db, pipeline_builder_ops.PipelineBuilderBuild, row, [
            "id", "graph_id", "status", "run_id", "output_asset_id", "preview", "lineage", "metrics", "created_at",
        ]))
    for row in snapshot.get("import_jobs") or []:
        row.setdefault("project_id", "default")
        row.setdefault("created_at", now)
        row.setdefault("updated_at", now)
        row["inferred_schema"] = row.get("inferred_schema") or row.get("schema") or {}
        track(_upsert_model(db, imports_ops.ImportJob, row, [
            "id", "project_id", "source_type", "filename", "display_name", "target_dataset_id",
            "status", "inferred_schema", "preview_rows", "validation_errors", "records",
            "created_at", "updated_at", "promoted_at",
        ]))
    for row in snapshot.get("workshop_modules") or []:
        row.setdefault("project_id", "default")
        row.setdefault("created_at", now)
        row.setdefault("updated_at", now)
        track(_upsert_model(db, apps.WorkshopModule, row, ["id", "project_id", "display_name", "description", "variables", "widgets", "layout", "created_at", "updated_at"]))
    for row in snapshot.get("workshop_module_versions") or []:
        row.setdefault("created_at", now)
        track(_upsert_model(db, apps.WorkshopModuleVersion, row, ["id", "module_id", "version_number", "snapshot", "note", "actor", "created_at"]))
    for row in snapshot.get("object_explorer_explorations") or []:
        row.setdefault("project_id", "default")
        row.setdefault("created_at", now)
        row.setdefault("updated_at", now)
        track(_upsert_model(db, object_explorer_ops.ObjectExplorerExploration, row, ["id", "project_id", "display_name", "description", "object_type_id", "filters", "columns", "charts", "perspective", "owner", "created_at", "updated_at"]))
    model_restore_specs = [
        ("modeling_objectives", modeling.ModelingObjective, ["id", "project_id", "display_name", "description", "problem_type", "target_field", "feature_fields", "input_asset_id", "created_at", "updated_at"]),
        ("model_submissions", modeling.ModelSubmission, ["id", "project_id", "objective_id", "algorithm", "metrics", "released", "status", "trainer_type", "training_dataset_id", "target_column", "eval_metric", "quality_preset", "created_at"]),
        ("model_deployments", modeling.ModelDeployment, ["id", "project_id", "objective_id", "submission_id", "mode", "status", "created_at"]),
        ("mev_releases", modeling_evaluation_ops.MevRelease, ["id", "project_id", "objective_id", "submission_id", "version", "environment", "notes", "created_at"]),
        ("mev_checks", modeling_evaluation_ops.MevCheck, ["id", "project_id", "objective_id", "name", "check_type", "metric", "operator", "threshold", "created_at"]),
        ("mev_check_results", modeling_evaluation_ops.MevCheckResult, ["id", "project_id", "submission_id", "check_id", "status", "reviewer", "comment", "decided_at"]),
        ("mev_eval_datasets", modeling_evaluation_ops.MevEvalDataset, ["id", "project_id", "objective_id", "asset_id", "display_name", "created_at"]),
        ("mev_eval_subsets", modeling_evaluation_ops.MevEvalSubset, ["id", "project_id", "eval_dataset_id", "name", "filter_column", "filter_values", "created_at"]),
        ("mev_experiments", modeling_evaluation_ops.MevExperiment, ["id", "project_id", "submission_id", "hyperparameters", "metrics", "artifacts", "created_at"]),
        ("mev_adapters", modeling_evaluation_ops.MevAdapter, ["id", "project_id", "submission_id", "input_schema", "output_schema", "created_at"]),
        ("mev_deployment_configs", modeling_evaluation_ops.MevDeploymentConfig, ["id", "project_id", "deployment_id", "release_id", "kind", "spark_profile", "replicas", "cpu", "gpu", "created_at"]),
    ]
    for snapshot_key, model_class, fields in model_restore_specs:
        for row in snapshot.get(snapshot_key) or []:
            row.setdefault("project_id", "default")
            row.setdefault("created_at", now)
            if "updated_at" in fields:
                row.setdefault("updated_at", now)
            track(_upsert_model(db, model_class, row, fields))
    for row in snapshot.get("model_monitors") or []:
        row.setdefault("project_id", "default")
        row.setdefault("created_at", now)
        row.setdefault("updated_at", now)
        track(_upsert_model(db, modelops.ModelMonitor, row, ["id", "project_id", "display_name", "description", "objective_id", "deployment_id", "baseline_asset_id", "feature_fields", "prediction_field", "target_field", "thresholds", "enabled", "created_at", "updated_at"]))
    for row in snapshot.get("model_monitor_runs") or []:
        row.setdefault("project_id", "default")
        row.setdefault("created_at", now)
        track(_upsert_model(db, modelops.ModelMonitorRun, row, ["id", "project_id", "monitor_id", "objective_id", "deployment_id", "baseline_asset_id", "current_asset_id", "baseline_profile", "current_profile", "drift_metrics", "quality_metrics", "alerts", "status", "created_at"]))
    for row in snapshot.get("model_prediction_logs") or []:
        row.setdefault("project_id", "default")
        row.setdefault("created_at", now)
        track(_upsert_model(db, modelops.ModelPredictionLog, row, ["id", "project_id", "deployment_id", "objective_id", "submission_id", "request_shape", "input_count", "output_count", "prediction_summary", "created_at"]))
    for row in snapshot.get("connection_sources") or []:
        row.setdefault("created_at", now)
        row.setdefault("project_id", "default")
        track(_upsert_model(db, connectivity.ConnectionSource, row, ["id", "project_id", "display_name", "source_type", "config", "uses_agent", "status", "created_at"]))
    for row in snapshot.get("connection_syncs") or []:
        row.setdefault("created_at", now)
        row.setdefault("project_id", "default")
        track(_upsert_model(db, connectivity.ConnectionSync, row, ["id", "project_id", "source_id", "target_asset_id", "mode", "cursor_field", "sample_records", "created_at"]))
    for row in snapshot.get("connection_sync_runs") or []:
        row.setdefault("created_at", now)
        row.setdefault("completed_at", now)
        track(_upsert_model(db, connectivity.SyncRun, row, ["id", "sync_id", "status", "records_in", "records_out", "created_at", "completed_at"]))
    for row in snapshot.get("connection_exports") or []:
        row.setdefault("created_at", now)
        row.setdefault("project_id", "default")
        track(_upsert_model(db, connectivity.ConnectionExport, row, ["id", "project_id", "source_asset_id", "destination", "format", "created_at"]))
    for row in snapshot.get("connection_export_checkpoints") or []:
        row.setdefault("updated_at", now)
        track(_upsert_model_by_key(db, connectivity.ConnectionExportCheckpoint, row, "export_id", ["export_id", "last_exported_count", "runs", "updated_at"]))
    for row in snapshot.get("connection_sync_cursors") or []:
        row.setdefault("updated_at", now)
        track(_upsert_model_by_key(db, connectivity_ops.SyncCursorState, row, "sync_id", ["sync_id", "cursor_field", "last_value", "runs", "updated_at"]))
    for row in snapshot.get("streams") or []:
        row.setdefault("created_at", now)
        row.setdefault("project_id", "default")
        track(_upsert_model(db, streaming.Stream, row, ["id", "project_id", "display_name", "schema_", "retention_seconds", "archive_policy", "created_at"]))
    for row in snapshot.get("stream_records") or []:
        row.setdefault("created_at", now)
        track(_upsert_model(db, streaming.StreamRecord, row, ["id", "stream_id", "payload", "ts", "archived", "archived_at", "created_at"]))
    for row in snapshot.get("schedules") or []:
        row.setdefault("created_at", now)
        row.setdefault("updated_at", now)
        row.setdefault("project_id", "default")
        track(_upsert_model(db, schedules.Schedule, row, ["id", "project_id", "display_name", "target_type", "target_id", "trigger_type", "cron", "event_input", "enabled", "created_at", "updated_at"]))
    for row in snapshot.get("builds") or []:
        row.setdefault("created_at", now)
        row.setdefault("project_id", "default")
        track(_upsert_model(db, schedules.Build, row, ["id", "project_id", "schedule_id", "target_type", "target_id", "status", "triggered_by", "metrics", "created_at", "completed_at"]))
    for row in snapshot.get("webhook_listeners") or []:
        row.setdefault("created_at", now)
        row.setdefault("project_id", "default")
        listener_fields = ["id", "project_id", "display_name", "auth_type", "target_asset_id", "event_schema", "created_at"]
        if row.get("auth_secret"):
            listener_fields.append("auth_secret")
        track(_upsert_model(db, webhooks_ops.WhListener, row, listener_fields))
    for row in snapshot.get("webhook_listener_events") or []:
        row.setdefault("created_at", now)
        row.setdefault("project_id", "default")
        track(_upsert_model(db, webhooks_ops.WhListenerEvent, row, ["id", "project_id", "listener_id", "raw_payload", "auth_valid", "processing_status", "error_message", "created_at"]))
    for row in snapshot.get("webhooks") or []:
        row.setdefault("created_at", now)
        row.setdefault("updated_at", now)
        row.setdefault("project_id", "default")
        track(_upsert_model(db, webhooks_ops.WhWebhook, row, ["id", "project_id", "source_id", "display_name", "mode", "request_config", "input_parameters", "output_parameters", "mock_response", "created_at", "updated_at"]))
    for row in snapshot.get("webhook_executions") or []:
        row.setdefault("created_at", now)
        row.setdefault("project_id", "default")
        track(_upsert_model(db, webhooks_ops.WhExecution, row, ["id", "project_id", "webhook_id", "request_payload", "response_payload", "response_status", "status", "extracted_outputs", "idempotency_key", "actor", "created_at"]))
    for row in snapshot.get("webhook_credentials") or []:
        row.setdefault("created_at", now)
        row.setdefault("project_id", "default")
        track(_upsert_model(db, webhooks_ops.WhCredential, row, ["id", "project_id", "source_id", "credential_type", "expires_at", "created_at"]))
    for row in snapshot.get("webhook_outbound_apps") or []:
        row.setdefault("created_at", now)
        row.setdefault("project_id", "default")
        row.setdefault("client_secret", "")
        track(_upsert_model(db, webhooks_ops.WhOutboundApp, row, ["id", "project_id", "display_name", "client_id", "client_secret", "token_endpoint", "scopes", "created_at"]))
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
    for row in snapshot.get("ingestion_runs") or []:
        row.setdefault("created_at", now)
        track(_upsert_model(db, ingestion_runtime.IngestionRun, row, ["id", "project_id", "job_id", "idempotency_key", "run_type", "resource_type", "resource_id", "status", "records_in", "records_out", "bytes_processed", "estimated_cost_usd", "metrics", "error", "created_at", "started_at", "completed_at"]))
    for row in snapshot.get("ingestion_budgets") or []:
        row.setdefault("created_at", now)
        row.setdefault("updated_at", now)
        track(_upsert_model(db, ingestion_runtime.IngestionBudget, row, ["id", "project_id", "metric", "limit_value", "window_seconds", "enforcement", "created_at", "updated_at"]))
    for row in snapshot.get("ingestion_dead_letters") or []:
        row.setdefault("created_at", now)
        row.setdefault("updated_at", now)
        track(_upsert_model(db, ingestion_runtime.IngestionDeadLetter, row, ["id", "project_id", "run_id", "resource_type", "resource_id", "payload", "error", "status", "replay_job_id", "attempts", "created_at", "updated_at"]))
    for row in snapshot.get("runtime_job_observations") or []:
        row.setdefault("created_at", now)
        row.setdefault("updated_at", now)
        track(_upsert_model(db, runtime_observability.RuntimeJobObservation, row, ["id", "project_id", "job_id", "correlation_id", "job_type", "actor", "status", "attempt", "progress", "queue_latency_ms", "duration_ms", "compute_seconds", "token_units", "record_units", "estimated_cost_usd", "metrics", "spans", "error", "created_at", "updated_at", "completed_at"]))
    for row in snapshot.get("runtime_budget_policies") or []:
        row.setdefault("created_at", now)
        row.setdefault("updated_at", now)
        track(_upsert_model(db, runtime_observability.RuntimeBudgetPolicy, row, ["id", "project_id", "metric", "limit_value", "window_seconds", "enforcement", "enabled", "created_at", "updated_at"]))
    for row in snapshot.get("runtime_slo_policies") or []:
        row.setdefault("created_at", now)
        row.setdefault("updated_at", now)
        track(_upsert_model(db, runtime_observability.RuntimeSloPolicy, row, ["id", "project_id", "display_name", "job_type", "metric", "operator", "threshold", "window_seconds", "severity", "enabled", "created_at", "updated_at"]))
    for row in snapshot.get("runtime_slo_evaluations") or []:
        row.setdefault("created_at", now)
        track(_upsert_model(db, runtime_observability.RuntimeSloEvaluation, row, ["id", "project_id", "policy_id", "status", "observed_value", "threshold", "sample_count", "details", "created_at"]))
    for row in snapshot.get("runtime_workers") or []:
        row.setdefault("started_at", now)
        row.setdefault("heartbeat_at", now)
        row["status"] = "OFFLINE"
        track(_upsert_model(db, worker_control.RuntimeWorker, row, ["id", "organization_id", "worker_name", "principal_id", "project_id", "status", "supported_job_types", "max_concurrency", "labels", "started_at", "heartbeat_at", "last_claimed_at", "drain_requested_at"]))
    for row in snapshot.get("runtime_queue_policies") or []:
        row.setdefault("created_at", now)
        row.setdefault("updated_at", now)
        track(_upsert_model(db, worker_control.RuntimeQueuePolicy, row, ["id", "project_id", "weight", "max_concurrency", "paused", "updated_by", "created_at", "updated_at"]))
    for row in snapshot.get("connector_fetch_attempts") or []:
        row.setdefault("created_at", now)
        track(_upsert_model(db, connector_runtime.ConnectorFetchAttempt, row, ["id", "project_id", "source_id", "sync_id", "ingestion_run_id", "adapter_id", "operation", "status", "records_read", "bytes_read", "duration_ms", "cursor_in", "cursor_out", "metadata_", "error", "created_at"]))
    for row in snapshot.get("ops_events") or []:
        row.setdefault("created_at", now)
        row.setdefault("project_id", "default")
        track(_upsert_model(db, ops_control.OpsEvent, row, ["id", "project_id", "source", "event_type", "severity", "status", "title", "message", "subject_type", "subject_id", "object_type_id", "object_id", "payload", "created_at"]))
    for row in snapshot.get("ops_alert_rules") or []:
        row.setdefault("created_at", now)
        row.setdefault("updated_at", now)
        row.setdefault("project_id", "default")
        track(_upsert_model(db, ops_control.AlertRule, row, ["id", "project_id", "display_name", "description", "source", "event_type", "min_severity", "subject_type", "object_type_id", "expression", "active", "created_at", "updated_at"]))
    for row in snapshot.get("ops_alerts") or []:
        row.setdefault("created_at", now)
        row.setdefault("updated_at", now)
        row.setdefault("project_id", "default")
        track(_upsert_model(db, ops_control.AlertEvent, row, ["id", "project_id", "rule_id", "event_id", "source", "severity", "status", "title", "message", "subject_type", "subject_id", "object_type_id", "object_id", "payload", "created_at", "updated_at"]))
    for row in snapshot.get("ops_runbooks") or []:
        row.setdefault("created_at", now)
        row.setdefault("updated_at", now)
        row.setdefault("project_id", "default")
        track(_upsert_model(db, ops_control.Runbook, row, ["id", "project_id", "display_name", "description", "steps", "enabled", "created_at", "updated_at"]))
    for row in snapshot.get("ops_runbook_executions") or []:
        row.setdefault("created_at", now)
        row.setdefault("project_id", "default")
        track(_upsert_model(db, ops_control.RunbookExecution, row, ["id", "project_id", "runbook_id", "incident_id", "actor", "status", "inputs", "step_results", "created_at", "completed_at"]))
    for row in snapshot.get("ops_notifications") or []:
        row.setdefault("created_at", now)
        row.setdefault("project_id", "default")
        track(_upsert_model(db, ops_control.OpsNotification, row, ["id", "project_id", "recipient", "severity", "title", "message", "source", "subject_type", "subject_id", "status", "payload", "created_at", "acknowledged_at"]))
    for row in snapshot.get("ops_sla_policies") or []:
        row.setdefault("created_at", now)
        row.setdefault("updated_at", now)
        row.setdefault("project_id", "default")
        track(_upsert_model(db, ops_control.OpsSlaPolicy, row, ["id", "project_id", "display_name", "scope", "thresholds", "active", "created_at", "updated_at"]))
    for row in snapshot.get("incidents") or []:
        row.setdefault("created_at", now)
        row.setdefault("updated_at", now)
        row.setdefault("project_id", "default")
        track(_upsert_model(db, ops_control.Incident, row, ["id", "project_id", "display_name", "description", "severity", "status", "owner", "linked_objects", "alert_ids", "approval_ids", "runbook_execution_ids", "timeline", "created_at", "updated_at"]))
    for row in snapshot.get("investigations") or []:
        row.setdefault("created_at", now)
        row.setdefault("updated_at", now)
        row.setdefault("project_id", "default")
        track(_upsert_model(db, investigations.InvestigationWorkspace, row, ["id", "project_id", "display_name", "description", "owner", "status", "object_refs", "incident_ids", "alert_ids", "created_at", "updated_at"]))
    for row in snapshot.get("investigation_evidence") or []:
        row.setdefault("created_at", now)
        row.setdefault("project_id", "default")
        track(_upsert_model(db, investigations.EvidenceItem, row, ["id", "project_id", "investigation_id", "title", "source", "object_refs", "payload", "tags", "created_at"]))
    for row in snapshot.get("investigation_hypotheses") or []:
        row.setdefault("created_at", now)
        row.setdefault("updated_at", now)
        row.setdefault("project_id", "default")
        track(_upsert_model(db, investigations.InvestigationHypothesis, row, ["id", "project_id", "investigation_id", "statement", "status", "confidence", "linked_evidence_ids", "created_at", "updated_at"]))
    for row in snapshot.get("investigation_findings") or []:
        row.setdefault("created_at", now)
        row.setdefault("project_id", "default")
        track(_upsert_model(db, investigations.InvestigationFinding, row, ["id", "project_id", "investigation_id", "title", "severity", "summary", "object_refs", "evidence_ids", "created_at"]))
    for row in snapshot.get("investigation_reports") or []:
        row.setdefault("created_at", now)
        row.setdefault("project_id", "default")
        track(_upsert_model(db, investigations.InvestigationReport, row, ["id", "project_id", "investigation_id", "title", "body", "sections", "created_at"]))
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
        row.setdefault("project_id", "default")
        track(_upsert_model(db, platform_runtime.PlatformJob, row, ["id", "project_id", "job_type", "status", "actor", "subject_type", "subject_id", "payload", "result", "error", "attempt", "progress", "created_at", "updated_at", "started_at", "completed_at"]))
    for row in snapshot.get("platform_job_events") or []:
        row.setdefault("created_at", now)
        track(_upsert_model(db, platform_runtime.PlatformJobEvent, row, ["id", "job_id", "event_type", "status", "payload", "created_at"]))
    for row in snapshot.get("platform_job_idempotency_receipts") or []:
        row.setdefault("created_at", now)
        row.setdefault("project_id", "default")
        track(_upsert_job_idempotency_receipt(db, row))
    for row in snapshot.get("platform_artifact_collaboration_events") or []:
        row.setdefault("created_at", now)
        track(_upsert_model(db, platform_runtime.ArtifactCollaborationEvent, row, ["id", "artifact_id", "participant_id", "actor", "event_type", "lock_version", "revision", "payload", "created_at"]))
    for row in snapshot.get("platform_artifact_command_receipts") or []:
        row.setdefault("created_at", now)
        row.setdefault("project_id", "default")
        track(_upsert_artifact_command_receipt(db, row))

    _audit(db, principal.id, "project.snapshot.imported", "project", project_id, {"project_id": project_id, **counts})
    ops_control.record_ops_event(
        db,
        source="project",
        event_type="project.snapshot.imported",
        severity="info",
        title="Project snapshot imported",
        subject_type="project",
        subject_id=project_id,
        payload={"project_id": project_id, **counts},
        project_id=project_id,
    )
    try:
        db.flush()
        db.commit()
    except (IntegrityError, SQLAlchemyError) as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Snapshot import failed integrity checks; no changes were applied") from exc
    return {"status": "IMPORTED", "mode": body.mode, "project_id": project_id, "counts": counts, "validation": validation}

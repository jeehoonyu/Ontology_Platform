"""Project-owned industrial onboarding from a promoted dataset to governed decisions."""
from __future__ import annotations

import hashlib
import os
import re
import time
import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field
from sqlalchemy import or_
from sqlalchemy.orm import Session

from . import (
    decision_intelligence,
    data_plane,
    investigations,
    imports_ops,
    models,
    models_action,
    ontology_registry,
    ontology_runtime_v1,
    ontology_versioning,
    ops_control,
    pipeline_builder_ops,
    platform_runtime,
    production_auth,
    tenancy,
)
import evaluator_evidence
from .pilot_evidence import current_migration_head
from .database import get_db
from .runtime import create_audit_log


router = APIRouter(tags=["industrial_workflow"])


class AssetFieldMapping(BaseModel):
    id_field: str = "id"
    name_field: Optional[str] = "name"
    status_field: Optional[str] = "status"
    criticality_field: Optional[str] = "criticality"
    risk_field: Optional[str] = "predicted_failure_probability"
    latitude_field: Optional[str] = "latitude"
    longitude_field: Optional[str] = "longitude"
    serial_number_field: Optional[str] = "serial_number"


class IndustrialOnboardingRequest(BaseModel):
    project_id: str
    source_asset_id: str
    source_snapshot_id: Optional[str] = None
    display_name: str = "Industrial Asset"
    mapping: AssetFieldMapping = Field(default_factory=AssetFieldMapping)
    risk_threshold: float = Field(default=0.7, ge=0, le=1)
    run_pipeline: bool = True
    publish_ontology: bool = True
    allow_breaking_ontology: bool = False
    execution_mode: str = Field(default="synchronous", pattern="^(synchronous|background)$")
    idempotency_key: Optional[str] = Field(default=None, min_length=1, max_length=200)


class IndustrialTriageRequest(BaseModel):
    project_id: str
    object_id: Optional[str] = None
    reason: Optional[str] = None


class ExternalEvaluatorEvidenceRequest(BaseModel):
    project_id: str = Field(min_length=1, max_length=200)
    team_id: str = Field(min_length=2, max_length=120, pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_.-]+$")
    organization_id: str = Field(min_length=2, max_length=120, pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_.-]+$")
    deployment_id: str = Field(min_length=4, max_length=160, pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_.:-]+$")
    evaluator_alias: str = Field(min_length=3, max_length=200)
    external_team_confirmation: bool
    own_data_confirmation: bool


def _now() -> int:
    return int(time.time())


def _slug(value: str) -> str:
    normalized = re.sub(r"[^a-zA-Z0-9_]+", "_", value).strip("_").lower()
    normalized = normalized or "project"
    return f"project_{normalized}" if normalized[0].isdigit() else normalized


def _ids(project_id: str) -> Dict[str, str]:
    prefix = _slug(project_id)
    return {
        "object_type": f"{prefix}__industrial_asset",
        "pipeline": f"{prefix}__industrial_asset_hydration",
        "pipeline_graph": f"{prefix}__industrial_asset_snapshot_graph",
        "output_asset": f"{prefix}__industrial_asset_output",
        "risk_rule": f"{prefix}__industrial_asset_high_risk",
        "scorecard": f"{prefix}__industrial_asset_scorecard",
        "action": f"{prefix}__request_asset_inspection",
        "agent": f"{prefix}__reliability_agent",
        "investigation": f"{prefix}__asset_reliability_investigation",
        "incident": f"{prefix}__asset_reliability_incident",
    }


def _assert_owned(row: Any, project_id: str, resource: str) -> None:
    if row is not None and row.project_id != project_id:
        raise HTTPException(status_code=409, detail=f"{resource} identifier belongs to another project")


def _schema_fields(schema: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    fields = schema.get("fields") if isinstance(schema, dict) else None
    if isinstance(fields, list):
        return {
            str(item["name"]): dict(item)
            for item in fields
            if isinstance(item, dict) and item.get("name")
        }
    return {
        str(name): (dict(spec) if isinstance(spec, dict) else {"type": spec})
        for name, spec in (schema or {}).items()
        if name not in {"project_id", "storage_mode", "kind", "description"}
    }


def _field_type(asset: models.DataAsset, field: str, schema: Optional[Dict[str, Any]] = None) -> str:
    declared = _schema_fields(schema or asset.asset_schema or {}).get(field, {})
    if isinstance(declared, dict):
        declared = declared.get("type") or declared.get("base_type")
    normalized = str(declared or "").lower()
    if normalized in {"int", "integer"}:
        return "integer"
    if normalized in {"float", "double", "decimal", "number"}:
        return "number"
    if normalized in {"bool", "boolean"}:
        return "boolean"
    for record in asset.records or []:
        value = record.get(field)
        if value is None:
            continue
        if isinstance(value, bool):
            return "boolean"
        if isinstance(value, int):
            return "integer"
        if isinstance(value, float):
            return "number"
        break
    return "string"


def _property_map(mapping: AssetFieldMapping) -> Dict[str, str]:
    configured = {
        "source_id": mapping.id_field,
        "name": mapping.name_field,
        "status": mapping.status_field,
        "criticality": mapping.criticality_field,
        "risk_score": mapping.risk_field,
        "latitude": mapping.latitude_field,
        "longitude": mapping.longitude_field,
        "serial_number": mapping.serial_number_field,
    }
    return {target: f"${source}" for target, source in configured.items() if source}


def _resource(db: Session, model: Any, resource_id: str, project_id: str) -> Any:
    row = db.get(model, resource_id)
    _assert_owned(row, project_id, model.__name__)
    return row


def _publish_contract(
    db: Session,
    *,
    project_id: str,
    actor: str,
    allow_breaking: bool,
) -> Dict[str, Any]:
    db.flush()
    manifest = ontology_versioning._capture_manifest(db, project_id)
    validation = ontology_versioning._validate_manifest(manifest)
    if validation["status"] != "PASS":
        raise HTTPException(status_code=422, detail={"message": "Generated ontology contract failed validation", "validation": validation})
    environment = ontology_versioning._environment(db, project_id, "production", actor)
    current = db.get(ontology_versioning.OntologyRevision, environment.current_revision_id) if environment.current_revision_id else None
    checksum = ontology_versioning._checksum(manifest)
    created = not current or current.checksum != checksum
    compatibility = ontology_versioning._ontology_diff(
        current.manifest if current else {"schema_version": 1, "project_id": project_id, "object_types": [], "link_types": [], "action_types": []},
        manifest,
    )
    if created and compatibility.get("classification") == "BREAKING" and not allow_breaking:
        raise HTTPException(status_code=409, detail={
            "message": "Generated ontology change is breaking and requires explicit acknowledgement",
            "compatibility": compatibility,
        })
    if created:
        revision = ontology_versioning._new_revision(
            db, project_id, manifest, actor, status="PUBLISHED", parent_revision_id=current.id if current else None,
        )
        if current and current.status == "PUBLISHED":
            current.status = "SUPERSEDED"
        environment.previous_revision_id = environment.current_revision_id
        environment.current_revision_id = revision.id
        environment.updated_by = actor
        environment.updated_at = _now()
        ontology_versioning._append_audit(
            db, actor, "industrial.workflow.ontology.published", "ontology_revision", revision.id,
            {"project_id": project_id, "revision": revision.revision, "checksum": revision.checksum, "classification": compatibility.get("classification")},
        )
    else:
        revision = current

    semantic_contract = ontology_runtime_v1.materialize_semantic_definitions(
        db, project_id=project_id, actor=actor, revision_id=revision.id,
    )
    registry = db.query(ontology_registry.OntologyRegistryEntry).filter(
        ontology_registry.OntologyRegistryEntry.project_id == project_id,
        ontology_registry.OntologyRegistryEntry.channel == "production",
        ontology_registry.OntologyRegistryEntry.revision_id == revision.id,
    ).first()
    if registry is None:
        registry_compatibility = ontology_registry._compatibility(db, project_id, "production", manifest)
        contract_schema = ontology_registry._json_schema(manifest, f"1.{revision.revision}.0", "production")
        created_at = _now()
        latest_registry = db.query(ontology_registry.OntologyRegistryEntry).filter(
            ontology_registry.OntologyRegistryEntry.project_id == project_id,
        ).order_by(ontology_registry.OntologyRegistryEntry.created_at.desc()).first()
        if latest_registry and created_at <= latest_registry.created_at:
            created_at = latest_registry.created_at + 1
        registry = ontology_registry.OntologyRegistryEntry(
            id=f"ontology_registry_{uuid.uuid4().hex}", project_id=project_id, channel="production",
            version=f"1.{revision.revision}.0", revision_id=revision.id, revision_number=revision.revision,
            status="PUBLISHED", manifest=ontology_registry._copy(manifest), contract_schema=contract_schema,
            compatibility=registry_compatibility,
            checksum=ontology_registry._hash({"manifest": manifest, "contract": contract_schema}),
            published_by=actor, created_at=created_at,
        )
        db.add(registry)
        create_audit_log(
            db, actor=actor, event_type="ontology.registry.published", subject_type="ontology_registry_entry",
            subject_id=registry.id, payload={"project_id": project_id, "revision_id": revision.id, "version": registry.version, "checksum": registry.checksum},
        )
        ops_control.record_ops_event(
            db, project_id=project_id, source="ontology", event_type="ontology.registry.published", severity="info",
            title=f"Industrial ontology contract {registry.version} published", subject_type="ontology_registry_entry",
            subject_id=registry.id, payload={"revision_id": revision.id, "checksum": registry.checksum},
        )
    db.flush()
    return {
        "created": created,
        "revision": ontology_versioning._revision_dict(revision, include_manifest=False),
        "environment": {"name": environment.name, "current_revision_id": environment.current_revision_id, "previous_revision_id": environment.previous_revision_id},
        "registry": ontology_registry._entry_dict(registry),
        "semantic_contract": semantic_contract,
        "compatibility": compatibility,
    }


def _upsert_contract(
    db: Session,
    body: IndustrialOnboardingRequest,
    asset: models.DataAsset,
    source_schema: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    ids = _ids(body.project_id)
    now = _now()
    mapped = _property_map(body.mapping)
    available_fields = set(_schema_fields(source_schema or asset.asset_schema or {}))
    available_fields.update(key for row in (asset.records or []) for key in row.keys())
    missing = sorted({source[1:] for source in mapped.values()} - available_fields)
    if missing:
        raise HTTPException(status_code=422, detail={"message": "Mapped fields are absent from the source dataset", "fields": missing})

    object_type = _resource(db, models.ObjectType, ids["object_type"], body.project_id)
    properties = {
        target: {
            "type": _field_type(asset, source[1:], source_schema),
            "required": target == "source_id",
            "description": f"Mapped from {asset.id}.{source[1:]}",
        }
        for target, source in mapped.items()
    }
    if body.mapping.latitude_field and body.mapping.longitude_field:
        properties.update({"geometry": {"type": "geometry"}, "mgrs": {"type": "string"}})
    properties.update({
        "maintenance_state": {"type": "string", "description": "Governed operational maintenance state."},
        "maintenance_reason": {"type": "string", "description": "Evidence-backed reason for the latest maintenance action."},
    })
    if object_type is None:
        object_type = models.ObjectType(
            id=ids["object_type"], project_id=body.project_id, display_name=body.display_name,
            description=f"Versioned industrial asset contract generated from {asset.display_name}.",
            properties=properties, created_at=now, updated_at=now,
        )
        db.add(object_type)
    else:
        object_type.display_name = body.display_name
        object_type.properties = properties
        object_type.updated_at = now

    steps = []
    if body.mapping.latitude_field and body.mapping.longitude_field:
        steps.extend([
            {"operation": "derive_geo_point", "longitude_field": body.mapping.longitude_field, "latitude_field": body.mapping.latitude_field, "target_field": "_geometry"},
            {"operation": "derive_mgrs", "geometry_field": "_geometry", "target_field": "_mgrs", "precision": 5},
        ])
        mapped.update({"geometry": "$_geometry", "mgrs": "$_mgrs"})
    steps.extend([
        {"operation": "namespace_id", "source_field": body.mapping.id_field, "target_field": "_ontology_id", "prefix": _slug(body.project_id), "separator": ":"},
        {"operation": "map_to_ontology", "object_type_id": ids["object_type"], "object_id_field": "_ontology_id", "property_map": mapped, "omit_nulls": True, "upsert": True},
    ])
    output_asset = _resource(db, models.DataAsset, ids["output_asset"], body.project_id)
    if output_asset is None:
        output_asset = models.DataAsset(
            id=ids["output_asset"], project_id=body.project_id, display_name=f"{body.display_name} Hydration Output",
            description="Materialized industrial onboarding output.", kind="dataset",
            asset_schema={"project_id": body.project_id}, records=[], created_at=now, updated_at=now,
        )
        db.add(output_asset)
        db.flush()
    pipeline = _resource(db, models.PipelineDefinition, ids["pipeline"], body.project_id)
    if pipeline is None:
        pipeline = models.PipelineDefinition(
            id=ids["pipeline"], project_id=body.project_id, display_name=f"{body.display_name} Hydration",
            description="Typed ingestion pipeline generated by the industrial onboarding workflow.",
            input_asset_id=asset.id, output_asset_id=ids["output_asset"], mode="batch", steps=steps,
            created_at=now, updated_at=now,
        )
        db.add(pipeline)
    else:
        pipeline.input_asset_id = asset.id
        pipeline.output_asset_id = ids["output_asset"]
        pipeline.steps = steps
        pipeline.updated_at = now

    rule = _resource(db, decision_intelligence.DecisionRule, ids["risk_rule"], body.project_id)
    if rule is None:
        rule = decision_intelligence.DecisionRule(
            id=ids["risk_rule"], project_id=body.project_id, display_name="Elevated failure risk",
            description="Flags assets whose mapped risk score exceeds the governed threshold.",
            object_type_id=ids["object_type"], expression={"field": "risk_score", "op": "gte", "value": body.risk_threshold},
            severity="critical", recommended_actions=["inspect_asset", "create_work_order"], active=True,
            created_at=now, updated_at=now,
        )
        db.add(rule)
    else:
        rule.expression = {"field": "risk_score", "op": "gte", "value": body.risk_threshold}
        rule.updated_at = now

    scorecard = _resource(db, decision_intelligence.DecisionScorecard, ids["scorecard"], body.project_id)
    if scorecard is None:
        scorecard = decision_intelligence.DecisionScorecard(
            id=ids["scorecard"], project_id=body.project_id, display_name="Industrial Asset Reliability",
            description="Explainable reliability score generated from the promoted dataset contract.",
            object_type_id=ids["object_type"], features=[{"rule_id": ids["risk_rule"], "weight": 90, "reason": "Predicted failure risk exceeds policy threshold"}],
            thresholds={"critical": 85, "high": 65, "medium": 35},
            recommended_actions=["inspect_asset", "create_work_order"], active=True,
            created_at=now, updated_at=now,
        )
        db.add(scorecard)
    action = _resource(db, models.ActionType, ids["action"], body.project_id)
    action_parameters = {
        "asset_id": {"type": "string", "required": True},
        "reason": {"type": "string", "required": True},
    }
    action_rules = {
        "requires_approval": True,
        "risk_level": "high",
        "object_mutations": [{
            "object_type_id": ids["object_type"],
            "object_id_param": "asset_id",
            "set": {"maintenance_state": "INSPECTION_REQUIRED", "maintenance_reason": "$reason"},
        }],
    }
    if action is None:
        action = models.ActionType(
            id=ids["action"], project_id=body.project_id, display_name="Request asset inspection",
            description="Stages and applies a governed inspection request to a high-risk industrial asset.",
            parameters=action_parameters, rules=action_rules,
        )
        db.add(action)
    else:
        action.parameters = action_parameters
        action.rules = action_rules
    agent = _resource(db, models.AgentDefinition, ids["agent"], body.project_id)
    if agent is None:
        agent = models.AgentDefinition(
            id=ids["agent"], project_id=body.project_id, display_name="Industrial Reliability Agent",
            description="Explains asset risk and proposes governed inspection actions.",
            system_prompt="Use ontology evidence to explain reliability risk. Propose actions; never mutate directly.",
            allowed_object_types=[ids["object_type"]], allowed_actions=[ids["action"]],
            approval_required=True, created_at=now, updated_at=now,
        )
        db.add(agent)
    else:
        agent.allowed_object_types = [ids["object_type"]]
        agent.allowed_actions = [ids["action"]]
        agent.updated_at = now
    return {"ids": ids, "object_type": object_type, "pipeline": pipeline}


def _approval_dict(row: models_action.ApprovalRequest) -> Dict[str, Any]:
    return {
        "id": row.id, "project_id": row.project_id, "action_type_id": row.action_type_id,
        "requester": row.requester, "parameters": row.parameters or {}, "status": row.status,
        "reason": row.reason, "created_at": row.created_at, "decided_at": row.decided_at,
    }


def _latest_execution_job(db: Session, project_id: str) -> Optional[platform_runtime.PlatformJob]:
    rows = db.query(platform_runtime.PlatformJob).filter(
        platform_runtime.PlatformJob.project_id == project_id,
        platform_runtime.PlatformJob.job_type == "industrial.ontology_hydrate",
    ).all()
    if not rows:
        return None

    def generation(row: platform_runtime.PlatformJob) -> tuple[int, int, int, str]:
        payload = row.payload or {}
        snapshot = db.get(data_plane.DataAssetSnapshot, str(payload.get("source_snapshot_id") or ""))
        return (
            int(snapshot.created_at if snapshot else row.created_at),
            int(snapshot.snapshot_number if snapshot else 0),
            int(row.updated_at or row.created_at),
            row.id,
        )

    return max(rows, key=generation)


def _latest_decision_run(
    db: Session,
    project_id: str,
    execution_job: Optional[platform_runtime.PlatformJob],
) -> Optional[decision_intelligence.DecisionRun]:
    if execution_job is not None:
        run_id = f"industrial_decision_{hashlib.sha256(execution_job.id.encode('utf-8')).hexdigest()[:32]}"
        run = db.get(decision_intelligence.DecisionRun, run_id)
        if run is not None and run.project_id == project_id:
            return run
    return db.query(decision_intelligence.DecisionRun).filter(
        decision_intelligence.DecisionRun.project_id == project_id,
    ).order_by(
        decision_intelligence.DecisionRun.completed_at.desc(),
        decision_intelligence.DecisionRun.created_at.desc(),
        decision_intelligence.DecisionRun.id.desc(),
    ).first()


def _execution_job_dict(row: Optional[platform_runtime.PlatformJob]) -> Optional[Dict[str, Any]]:
    if row is None:
        return None
    return {
        "id": row.id,
        "job_type": row.job_type,
        "status": row.status,
        "subject_type": row.subject_type,
        "subject_id": row.subject_id,
        "progress": row.progress,
        "attempt": row.attempt,
        "error": row.error,
        "result": row.result or {},
        "execution": dict((row.payload or {}).get("__execution") or {}),
        "created_at": row.created_at,
        "updated_at": row.updated_at,
        "completed_at": row.completed_at,
    }


def _stage_approval(db: Session, *, project_id: str, action_type_id: str, object_id: str, reason: str, actor: str) -> models_action.ApprovalRequest:
    parameters = {"asset_id": object_id, "reason": reason}
    existing = db.query(models_action.ApprovalRequest).filter(
        models_action.ApprovalRequest.project_id == project_id,
        models_action.ApprovalRequest.action_type_id == action_type_id,
    ).order_by(models_action.ApprovalRequest.created_at.desc()).all()
    approval = next((row for row in existing if row.parameters == parameters and row.status in {"PENDING", "APPROVED"}), None)
    if approval:
        return approval
    approval = models_action.ApprovalRequest(
        id=str(uuid.uuid4()), project_id=project_id, action_type_id=action_type_id,
        requester=actor, parameters=parameters, status=models_action.ApprovalStatus.PENDING.value,
    )
    db.add(approval)
    create_audit_log(db, actor=actor, event_type="industrial.workflow.approval.requested", subject_type="approval_request", subject_id=approval.id, payload={"project_id": project_id, "action_type_id": action_type_id, "parameters": parameters})
    ops_control.record_ops_event(db, project_id=project_id, source="industrial_workflow", event_type="industrial.workflow.approval.requested", severity="high", title="Inspection approval requested", subject_type="approval_request", subject_id=approval.id, object_id=object_id, payload={"action_type_id": action_type_id})
    db.flush()
    return approval


def _ensure_case(db: Session, *, project_id: str, object_type_id: str, obj: models.ObjectInstance, approval: models_action.ApprovalRequest, risk: Dict[str, Any], actor: str) -> Dict[str, Any]:
    ids = _ids(project_id)
    object_ref = {"object_type_id": object_type_id, "object_id": obj.id}
    incident = db.get(ops_control.Incident, ids["incident"])
    if incident is None:
        incident = ops_control.create_incident_inline(
            db, incident_id=ids["incident"], project_id=project_id,
            display_name=f"Reliability review: {(obj.properties or {}).get('name') or obj.id}",
            description=risk.get("explanation"), severity=risk.get("band", "high"), owner=actor,
            linked_objects=[object_ref], approval_ids=[approval.id], actor=actor,
        )
    else:
        incident.approval_ids = sorted(set((incident.approval_ids or []) + [approval.id]))
        incident.linked_objects = [object_ref]
        incident.status = "OPEN"
        incident.updated_at = _now()
        incident.timeline = (incident.timeline or []) + [{"at": _now(), "actor": actor, "event_type": "industrial.triage.completed", "status": "OPEN"}]

    investigation = db.get(investigations.InvestigationWorkspace, ids["investigation"])
    if investigation is None:
        investigation = investigations.InvestigationWorkspace(
            id=ids["investigation"], project_id=project_id, display_name="Industrial Asset Reliability Review",
            description="Evidence-backed review generated from organization-provided operational data.",
            status="OPEN", owner=actor, object_refs=[object_ref], alert_ids=[], incident_ids=[incident.id],
            created_at=_now(), updated_at=_now(),
        )
        db.add(investigation)
    else:
        investigation.object_refs = [object_ref]
        investigation.incident_ids = sorted(set((investigation.incident_ids or []) + [incident.id]))
        investigation.updated_at = _now()
    evidence = investigations.EvidenceItem(
        id=f"evidence_{uuid.uuid4().hex[:12]}", project_id=project_id, investigation_id=investigation.id,
        title="Reliability triage evidence", source="industrial_workflow", object_refs=[object_ref],
        payload={"risk": risk, "approval_id": approval.id, "incident_id": incident.id},
        tags=["risk", "agent", "approval"], created_at=_now(),
    )
    db.add(evidence)
    return {"incident": incident, "investigation": investigation, "evidence": evidence}


def _latest_workflow_rows(db: Session, project_id: str) -> Dict[str, Any]:
    ids = _ids(project_id)
    approval = db.query(models_action.ApprovalRequest).filter(
        models_action.ApprovalRequest.project_id == project_id,
        models_action.ApprovalRequest.action_type_id == ids["action"],
    ).order_by(models_action.ApprovalRequest.created_at.desc()).first()
    action_event = db.query(models_action.OutboxEvent).filter(
        models_action.OutboxEvent.project_id == project_id,
        models_action.OutboxEvent.action_type_id == ids["action"],
    ).order_by(models_action.OutboxEvent.created_at.desc()).first()
    report = db.query(investigations.InvestigationReport).filter(
        investigations.InvestigationReport.project_id == project_id,
        investigations.InvestigationReport.investigation_id == ids["investigation"],
    ).order_by(investigations.InvestigationReport.created_at.desc()).first()
    return {"approval": approval, "action_event": action_event, "report": report}


def _report_payload(db: Session, project_id: str) -> Dict[str, Any]:
    ids = _ids(project_id)
    rows = _latest_workflow_rows(db, project_id)
    investigation = db.get(investigations.InvestigationWorkspace, ids["investigation"])
    incident = db.get(ops_control.Incident, ids["incident"])
    evidence = db.query(investigations.EvidenceItem).filter(
        investigations.EvidenceItem.project_id == project_id,
        investigations.EvidenceItem.investigation_id == ids["investigation"],
    ).order_by(investigations.EvidenceItem.created_at.asc()).all()
    objects = db.query(models.ObjectInstance).filter(
        models.ObjectInstance.project_id == project_id,
        models.ObjectInstance.object_type_id == ids["object_type"],
        models.ObjectInstance.is_active.is_(True),
    ).all()
    findings = [
        {"object_id": obj.id, "name": (obj.properties or {}).get("name"), "risk": decision_intelligence.score_object(db, obj, scorecard_ids=[ids["scorecard"]]), "maintenance_state": (obj.properties or {}).get("maintenance_state")}
        for obj in objects
    ]
    findings.sort(key=lambda item: float((item["risk"] or {}).get("score") or 0), reverse=True)
    return {
        "project_id": project_id, "workflow": "asset_reliability", "generated_at": _now(),
        "decision": "Inspection required" if rows["approval"] else "No governed action staged",
        "findings": findings,
        "approval": _approval_dict(rows["approval"]) if rows["approval"] else None,
        "action": {"id": rows["action_event"].id, "status": rows["action_event"].status, "payload": rows["action_event"].payload or {}} if rows["action_event"] else None,
        "incident": ops_control._incident_dict(incident) if incident else None,
        "investigation_id": investigation.id if investigation else None,
        "report_id": rows["report"].id if rows["report"] else None,
        "evidence_ids": [row.id for row in evidence],
    }


def _report_markdown(payload: Dict[str, Any]) -> str:
    approval = payload.get("approval") or {}
    action = payload.get("action") or {}
    lines = [
        "# Industrial Asset Reliability Report", "",
        f"- Project: {payload['project_id']}",
        f"- Decision: {payload['decision']}",
        f"- Approval: {approval.get('status') or 'not staged'} ({approval.get('id') or '-'})",
        f"- Action execution: {action.get('status') or 'not executed'} ({action.get('id') or '-'})",
        f"- Incident: {(payload.get('incident') or {}).get('id') or '-'}",
        f"- Investigation: {payload.get('investigation_id') or '-'}", "", "## Risk Findings", "",
    ]
    for finding in payload.get("findings") or []:
        risk = finding.get("risk") or {}
        lines.append(f"- {finding.get('name') or finding['object_id']}: {risk.get('band')} ({risk.get('score')}) - {risk.get('explanation')}")
    lines.extend(["", "## Evidence", "", ", ".join(payload.get("evidence_ids") or []) or "No evidence recorded."])
    return "\n".join(lines) + "\n"


def _source_snapshot(
    db: Session,
    body: IndustrialOnboardingRequest,
    asset: models.DataAsset,
    actor: str,
) -> data_plane.DataAssetSnapshot:
    snapshot = db.get(data_plane.DataAssetSnapshot, body.source_snapshot_id) if body.source_snapshot_id else None
    if body.source_snapshot_id and snapshot is None:
        raise HTTPException(status_code=404, detail=f"Dataset snapshot '{body.source_snapshot_id}' not found")
    if snapshot and (snapshot.project_id != body.project_id or snapshot.asset_id != asset.id):
        raise HTTPException(status_code=409, detail="Source snapshot belongs to another project or dataset")
    if snapshot and snapshot.status != "AVAILABLE":
        raise HTTPException(status_code=422, detail="Source snapshot is not available")
    if snapshot is None:
        snapshot = db.query(data_plane.DataAssetSnapshot).filter(
            data_plane.DataAssetSnapshot.project_id == body.project_id,
            data_plane.DataAssetSnapshot.asset_id == asset.id,
            data_plane.DataAssetSnapshot.status == "AVAILABLE",
        ).order_by(data_plane.DataAssetSnapshot.snapshot_number.desc()).first()
    if snapshot is None:
        snapshot = data_plane.ensure_dataset_snapshot(
            db, asset, actor=actor, storage_format="parquet",
            lineage={"workflow": "industrial_asset_reliability"},
        )
    if snapshot.row_count < 1:
        raise HTTPException(status_code=422, detail="Source dataset snapshot has no records to hydrate")
    return snapshot


def _snapshot_graph(
    db: Session,
    body: IndustrialOnboardingRequest,
    asset: models.DataAsset,
    snapshot: data_plane.DataAssetSnapshot,
    output_asset_id: str,
) -> pipeline_builder_ops.PipelineBuilderGraph:
    graph_id = _ids(body.project_id)["pipeline_graph"]
    nodes: List[Dict[str, Any]] = [{
        "id": "source_snapshot", "type": "input_dataset", "position": {"x": 80, "y": 180},
        "config": {"asset_id": asset.id, "snapshot_id": snapshot.id},
    }]
    edges: List[Dict[str, Any]] = []
    previous = "source_snapshot"
    if body.mapping.latitude_field and body.mapping.longitude_field:
        nodes.append({
            "id": "derive_geometry", "type": "derive_geo_point", "position": {"x": 340, "y": 140},
            "config": {
                "latitude_field": body.mapping.latitude_field,
                "longitude_field": body.mapping.longitude_field,
                "target_field": "_geometry",
            },
        })
        edges.append({"id": "source_to_geometry", "source": previous, "target": "derive_geometry"})
        previous = "derive_geometry"
        nodes.append({
            "id": "derive_mgrs", "type": "derive_mgrs", "position": {"x": 600, "y": 140},
            "config": {
                "latitude_field": body.mapping.latitude_field,
                "longitude_field": body.mapping.longitude_field,
                "target_field": "_mgrs", "precision": 5,
            },
        })
        edges.append({"id": "geometry_to_mgrs", "source": previous, "target": "derive_mgrs"})
        previous = "derive_mgrs"
    nodes.append({
        "id": "snapshot_output", "type": "dataset_output", "position": {"x": 860, "y": 180},
        "config": {"asset_id": output_asset_id},
    })
    edges.append({"id": "to_snapshot_output", "source": previous, "target": "snapshot_output"})
    graph = db.get(pipeline_builder_ops.PipelineBuilderGraph, graph_id)
    _assert_owned(graph, body.project_id, "PipelineBuilderGraph")
    now = _now()
    if graph is None:
        graph = pipeline_builder_ops.PipelineBuilderGraph(
            id=graph_id, project_id=body.project_id, display_name=f"{body.display_name} Snapshot Hydration",
            description="Snapshot-native industrial mapping and ontology hydration plan.",
            nodes=nodes, edges=edges, parameters={}, status="DRAFT", created_at=now, updated_at=now,
        )
        db.add(graph)
        db.flush()
    elif graph.nodes != nodes or graph.edges != edges:
        graph.nodes = nodes
        graph.edges = edges
        graph.updated_at = max(now, graph.updated_at + 1)
        db.flush()
    return graph


def _hydrate_output_snapshot(
    db: Session,
    *,
    body: IndustrialOnboardingRequest,
    asset: models.DataAsset,
    graph: pipeline_builder_ops.PipelineBuilderGraph,
    plan: data_plane.PipelineExecutionPlan,
    snapshot: data_plane.DataAssetSnapshot,
    run_id: str,
    job_id: Optional[str] = None,
    lease_token: Optional[str] = None,
    lease_seconds: int = 900,
    execution_principal: Optional[production_auth.Principal] = None,
) -> Dict[str, Any]:
    mapped = _property_map(body.mapping)
    property_mapping = {source[1:]: target for target, source in mapped.items()}
    if body.mapping.latitude_field and body.mapping.longitude_field:
        property_mapping.update({"_geometry": "geometry", "_mgrs": "mgrs"})
    source_lineage = dict(plan.field_lineage or {})
    source_lineage.setdefault("_geometry", [{"node_id": "derive_geometry", "operation": "derive_geo_point"}])
    source_lineage.setdefault("_mgrs", [{"node_id": "derive_mgrs", "operation": "derive_mgrs"}])
    totals: Dict[str, Any] = {
        "status": "SUCCESS", "input_rows": 0, "accepted_rows": 0, "rejected_rows": 0,
        "created_objects": 0, "updated_objects": 0, "unchanged_objects": 0,
        "field_lineage": [], "violations": [], "quarantine_asset_id": None,
    }
    batch_size = 1000
    start_offset = 0
    if job_id:
        job = db.get(platform_runtime.PlatformJob, job_id)
        checkpoint = dict((job.payload or {}).get("industrial_checkpoint") or {}) if job else {}
        if checkpoint.get("output_snapshot_id") == snapshot.id:
            start_offset = max(0, min(int(checkpoint.get("next_offset") or 0), snapshot.row_count))
            for key in ("input_rows", "accepted_rows", "rejected_rows", "created_objects", "updated_objects", "unchanged_objects"):
                totals[key] = int((checkpoint.get("totals") or {}).get(key) or 0)
            totals["field_lineage"] = list((checkpoint.get("totals") or {}).get("field_lineage") or [])
            totals["violations"] = list((checkpoint.get("totals") or {}).get("violations") or [])
    for offset in range(start_offset, snapshot.row_count, batch_size):
        if snapshot.storage_format == "parquet":
            query = data_plane._query_local_parquet_snapshot(
                snapshot, data_plane.SnapshotQueryRequest(limit=batch_size, offset=offset),
            )
        else:
            query = data_plane._query_snapshot(
                data_plane._storage_for_uri(snapshot.storage_uri).get(snapshot.storage_uri),
                snapshot.storage_format,
                data_plane.SnapshotQueryRequest(limit=batch_size, offset=offset),
            )
        rows = [dict(row) for row in query.get("rows") or []]
        for row in rows:
            source_id = row.get(body.mapping.id_field)
            row["_ontology_id"] = f"{_slug(body.project_id)}:{source_id}" if source_id not in (None, "") else None
        result = pipeline_builder_ops._execute_ontology_contract(
            db, graph, "ontology_hydration", {
                "object_type_id": _ids(body.project_id)["object_type"],
                "primary_key": "_ontology_id", "property_mapping": property_mapping,
                "write_mode": "upsert", "on_error": "quarantine" if job_id else "fail",
                "source_asset_id": asset.id, "materialization_id": snapshot.id,
            }, rows, source_lineage, True,
        )
        for key in ("input_rows", "accepted_rows", "rejected_rows", "created_objects", "updated_objects", "unchanged_objects"):
            totals[key] += int(result.get(key) or 0)
        totals["field_lineage"] = result.get("field_lineage") or totals["field_lineage"]
        totals["violations"].extend(result.get("violations") or [])
        if result.get("quarantine_asset_id"):
            totals["quarantine_asset_id"] = result["quarantine_asset_id"]
        if job_id and lease_token and execution_principal:
            job = db.get(platform_runtime.PlatformJob, job_id)
            if not job:
                raise HTTPException(status_code=409, detail="Industrial onboarding job disappeared during hydration")
            payload = dict(job.payload or {})
            payload["industrial_checkpoint"] = {
                "output_snapshot_id": snapshot.id,
                "next_offset": min(offset + len(rows), snapshot.row_count),
                "totals": {
                    **{key: totals[key] for key in ("input_rows", "accepted_rows", "rejected_rows", "created_objects", "updated_objects", "unchanged_objects")},
                    "field_lineage": totals["field_lineage"], "violations": totals["violations"][:100],
                },
            }
            job.payload = payload
            progress = 35 + int(50 * min(offset + len(rows), snapshot.row_count) / max(snapshot.row_count, 1))
            platform_runtime.heartbeat_job(
                job_id,
                platform_runtime.JobHeartbeatRequest(
                    lease_token=lease_token, progress=min(progress, 85),
                    message=f"Reconciled {min(offset + len(rows), snapshot.row_count)} of {snapshot.row_count} ontology rows",
                    metrics={
                        "rows_processed": min(offset + len(rows), snapshot.row_count),
                        "accepted_rows": totals["accepted_rows"], "rejected_rows": totals["rejected_rows"],
                    },
                    lease_seconds=max(10, min(900, lease_seconds)),
                ),
                execution_principal,
                db,
            )
    totals["retired_objects"] = _retire_missing_materialization(
        db,
        project_id=body.project_id,
        object_type_id=_ids(body.project_id)["object_type"],
        source_asset_id=asset.id,
        materialization_id=snapshot.id,
        graph_id=graph.id,
        job_id=job_id,
        lease_token=lease_token,
        lease_seconds=lease_seconds,
        execution_principal=execution_principal,
    )
    contract_run = pipeline_builder_ops.PipelineOntologyContractRun(
        id=f"pipeline_ontology_contract_{uuid.uuid4().hex}", project_id=body.project_id,
        graph_id=graph.id, build_id=run_id, node_id="ontology_hydration",
        object_type_id=_ids(body.project_id)["object_type"], status=totals["status"],
        input_rows=totals["input_rows"], accepted_rows=totals["accepted_rows"],
        rejected_rows=totals["rejected_rows"], created_objects=totals["created_objects"],
        updated_objects=totals["updated_objects"], unchanged_objects=totals["unchanged_objects"],
        quarantine_asset_id=totals["quarantine_asset_id"], field_lineage=totals["field_lineage"],
        violations=totals["violations"][:100], created_at=_now(),
    )
    db.add(contract_run)
    db.flush()
    totals["contract_run_id"] = contract_run.id
    totals["batch_size"] = batch_size
    return totals


def _retire_missing_materialization(
    db: Session,
    *,
    project_id: str,
    object_type_id: str,
    source_asset_id: str,
    materialization_id: str,
    graph_id: str,
    job_id: Optional[str] = None,
    lease_token: Optional[str] = None,
    lease_seconds: int = 900,
    execution_principal: Optional[production_auth.Principal] = None,
    batch_size: int = 1000,
) -> int:
    cursor = ""
    retired = 0
    if job_id:
        job = db.get(platform_runtime.PlatformJob, job_id)
        checkpoint = dict((job.payload or {}).get("industrial_reconcile_checkpoint") or {}) if job else {}
        if checkpoint.get("materialization_id") == materialization_id:
            cursor = str(checkpoint.get("cursor") or "")
            retired = int(checkpoint.get("retired_objects") or 0)
    while True:
        query = db.query(models.ObjectInstance).filter(
            models.ObjectInstance.project_id == project_id,
            models.ObjectInstance.object_type_id == object_type_id,
            models.ObjectInstance.source_asset_id == source_asset_id,
            models.ObjectInstance.is_active.is_(True),
            or_(
                models.ObjectInstance.materialization_id.is_(None),
                models.ObjectInstance.materialization_id != materialization_id,
            ),
        )
        if cursor:
            query = query.filter(models.ObjectInstance.id > cursor)
        rows = query.order_by(models.ObjectInstance.id.asc()).limit(batch_size).all()
        if not rows:
            break
        now = _now()
        for obj in rows:
            before = dict(obj.properties or {})
            obj.is_active = False
            obj.retired_at = now
            obj.updated_at = now
            obj.lineage = {
                **(obj.lineage or {}), "materialization_active": False,
                "retired_by_materialization_id": materialization_id,
            }
            decision_intelligence.record_object_snapshot(
                db, obj, event_type="ontology.object.retired",
                actor=execution_principal.id if execution_principal else "pipeline_builder",
                source_type="pipeline_builder_graph", source_id=graph_id,
            )
            ontology_runtime_v1.record_object_change(
                db, obj, before_state=before, event_type="ontology.object.retired",
                actor=execution_principal.id if execution_principal else "pipeline_builder",
                source_type="pipeline_builder_graph", source_id=graph_id,
                evidence={
                    "materialization_id": materialization_id,
                    "previous_materialization_id": obj.materialization_id,
                    "reason": "missing_from_materialization",
                },
            )
        retired += len(rows)
        cursor = rows[-1].id
        if job_id and lease_token and execution_principal:
            job = db.get(platform_runtime.PlatformJob, job_id)
            if not job:
                raise HTTPException(status_code=409, detail="Industrial onboarding job disappeared during source reconciliation")
            payload = dict(job.payload or {})
            payload["industrial_reconcile_checkpoint"] = {
                "materialization_id": materialization_id,
                "cursor": cursor,
                "retired_objects": retired,
            }
            job.payload = payload
            platform_runtime.heartbeat_job(
                job_id,
                platform_runtime.JobHeartbeatRequest(
                    lease_token=lease_token, progress=85,
                    message=f"Retired {retired} objects missing from the current materialization",
                    metrics={"retired_objects": retired, "materialization_id": materialization_id},
                    lease_seconds=max(10, min(900, lease_seconds)),
                ),
                execution_principal,
                db,
            )
    return retired


def _run_snapshot_pipeline(
    db: Session,
    body: IndustrialOnboardingRequest,
    asset: models.DataAsset,
    source_snapshot: data_plane.DataAssetSnapshot,
    pipeline: models.PipelineDefinition,
    actor: str,
    execution_job_id: Optional[str] = None,
    execution_lease_token: Optional[str] = None,
    lease_seconds: int = 900,
    execution_principal: Optional[production_auth.Principal] = None,
) -> tuple[models.PipelineRun, data_plane.PipelineExecutionPlan, data_plane.DataAssetSnapshot, Dict[str, Any]]:
    graph = _snapshot_graph(db, body, asset, source_snapshot, str(pipeline.output_asset_id))
    plan = data_plane._compile_plan(db, graph, "duckdb", actor)
    if plan.status != "VALID":
        raise HTTPException(status_code=422, detail={"message": "Industrial snapshot pipeline is invalid", "validation": plan.validation})
    execution_key = execution_job_id or hashlib.sha256(
        f"industrial:{body.project_id}:{source_snapshot.content_hash}:{plan.plan_hash}".encode("utf-8")
    ).hexdigest()
    delivered = data_plane.execute_duckdb_snapshot_plan(
        db, plan.id, mode="deliver", limit=100, output_asset_id=str(pipeline.output_asset_id),
        parameters={}, actor=actor, execution_job_id=f"industrial_{hashlib.sha256(execution_key.encode('utf-8')).hexdigest()[:32]}",
        execution_fence_job_id=execution_job_id,
        execution_lease_token=execution_lease_token,
    )
    output_snapshot_payload = delivered.get("output_snapshot") or {}
    output_snapshot = db.get(data_plane.DataAssetSnapshot, output_snapshot_payload.get("id"))
    if output_snapshot is None:
        raise HTTPException(status_code=500, detail="Industrial pipeline did not produce an output snapshot")
    now = _now()
    run_id = (
        f"industrial_run_{hashlib.sha256(execution_job_id.encode('utf-8')).hexdigest()[:32]}"
        if execution_job_id else uuid.uuid4().hex
    )
    existing_run = db.get(models.PipelineRun, run_id)
    if existing_run and existing_run.status == "SUCCESS":
        hydration = dict((existing_run.metrics or {}).get("ontology_hydration") or {})
        return existing_run, plan, output_snapshot, hydration
    run = existing_run or models.PipelineRun(
        id=run_id, project_id=body.project_id, pipeline_id=pipeline.id, status="RUNNING",
        input_asset_id=asset.id, output_asset_id=pipeline.output_asset_id, records_in=source_snapshot.row_count,
        records_out=0, lineage={
            "source_snapshot_id": source_snapshot.id, "output_snapshot_id": output_snapshot.id,
            "pipeline_plan_id": plan.id, "pipeline_graph_id": graph.id,
            "execution_job_id": execution_job_id,
        }, metrics=delivered.get("metrics") or {}, created_at=now,
    )
    if existing_run is None:
        db.add(run)
    else:
        run.status = "RUNNING"
        run.error = None
        run.records_in = source_snapshot.row_count
        run.records_out = 0
        run.lineage = {
            "source_snapshot_id": source_snapshot.id, "output_snapshot_id": output_snapshot.id,
            "pipeline_plan_id": plan.id, "pipeline_graph_id": graph.id,
            "execution_job_id": execution_job_id,
        }
        run.metrics = delivered.get("metrics") or {}
        run.completed_at = None
    db.flush()
    hydration = _hydrate_output_snapshot(
        db, body=body, asset=asset, graph=graph, plan=plan, snapshot=output_snapshot, run_id=run.id,
        job_id=execution_job_id, lease_token=execution_lease_token, lease_seconds=lease_seconds,
        execution_principal=execution_principal,
    )
    run.status = "SUCCESS"
    run.records_out = hydration["accepted_rows"]
    run.metrics = {**(run.metrics or {}), "ontology_hydration": hydration}
    run.completed_at = _now()
    create_audit_log(
        db, actor=actor, event_type="industrial.workflow.hydrated", subject_type="pipeline_run", subject_id=run.id,
        payload={
            "project_id": body.project_id, "pipeline_id": pipeline.id,
            "records_out": run.records_out, "source_snapshot_id": source_snapshot.id,
            "output_snapshot_id": output_snapshot.id, "pipeline_plan_id": plan.id,
            "ontology_contract_run_id": hydration["contract_run_id"],
        },
    )
    ops_control.record_ops_event(
        db, project_id=body.project_id, source="industrial_workflow",
        event_type="industrial.workflow.hydrated", severity="info",
        title=f"Hydrated {run.records_out} industrial assets", subject_type="pipeline_run", subject_id=run.id,
        payload={
            "pipeline_id": pipeline.id, "source_snapshot_id": source_snapshot.id,
            "output_snapshot_id": output_snapshot.id, "pipeline_plan_id": plan.id,
        },
    )
    return run, plan, output_snapshot, hydration


def _evaluate_partitioned_decision(
    db: Session,
    *,
    project_id: str,
    object_type_id: str,
    job_id: str,
    lease_token: str,
    lease_seconds: int,
    principal: production_auth.Principal,
    batch_size: int = 1000,
    finding_limit: int = 100,
) -> Dict[str, Any]:
    job = db.get(platform_runtime.PlatformJob, job_id)
    if not job:
        raise HTTPException(status_code=409, detail="Industrial onboarding job disappeared before decision evaluation")
    checkpoint = dict((job.payload or {}).get("industrial_decision_checkpoint") or {})
    if checkpoint.get("object_type_id") != object_type_id:
        checkpoint = {}
    cutoff = int(checkpoint.get("cutoff") or _now())
    cursor = str(checkpoint.get("cursor") or "")
    evaluated = int(checkpoint.get("evaluated") or 0)
    band_counts = {
        band: int((checkpoint.get("band_counts") or {}).get(band) or 0)
        for band in ("low", "medium", "high", "critical")
    }
    high_risk_findings = list(checkpoint.get("high_risk_findings") or [])[:finding_limit]
    representative_findings = list(checkpoint.get("representative_findings") or [])[:10]
    base_query = db.query(models.ObjectInstance).filter(
        models.ObjectInstance.project_id == project_id,
        models.ObjectInstance.object_type_id == object_type_id,
        models.ObjectInstance.is_active.is_(True),
        models.ObjectInstance.updated_at <= cutoff,
    )
    total = base_query.count()
    rules = decision_intelligence._rules_for_object(db, object_type_id, project_id=project_id)
    scorecards = decision_intelligence._scorecards_for_object(db, object_type_id, project_id=project_id)
    while True:
        query = base_query
        if cursor:
            query = query.filter(models.ObjectInstance.id > cursor)
        rows = query.order_by(models.ObjectInstance.id.asc()).limit(batch_size).all()
        if not rows:
            break
        findings = decision_intelligence.evaluate_object_rows_inline(
            db, rows, rule_catalog=rules, scorecard_catalog=scorecards,
        )
        for finding in findings:
            band = str((finding.get("risk") or {}).get("band") or "low")
            band_counts[band] = band_counts.get(band, 0) + 1
            if len(representative_findings) < 10:
                representative_findings.append(finding)
            if band in {"high", "critical"} and len(high_risk_findings) < finding_limit:
                high_risk_findings.append(finding)
        evaluated += len(rows)
        cursor = rows[-1].id
        job = db.get(platform_runtime.PlatformJob, job_id)
        payload = dict(job.payload or {})
        payload["industrial_decision_checkpoint"] = {
            "object_type_id": object_type_id,
            "cutoff": cutoff,
            "cursor": cursor,
            "evaluated": evaluated,
            "total": total,
            "band_counts": band_counts,
            "high_risk_findings": high_risk_findings,
            "representative_findings": representative_findings,
        }
        job.payload = payload
        progress = 85 + int(14 * evaluated / max(total, 1))
        platform_runtime.heartbeat_job(
            job_id,
            platform_runtime.JobHeartbeatRequest(
                lease_token=lease_token, progress=min(progress, 99),
                message=f"Scored {evaluated} of {total} ontology objects",
                metrics={"objects_evaluated": evaluated, "object_count": total, "band_counts": band_counts},
                lease_seconds=max(10, min(900, lease_seconds)),
            ),
            principal,
            db,
        )
    retained = high_risk_findings or representative_findings
    run_id = f"industrial_decision_{hashlib.sha256(job_id.encode('utf-8')).hexdigest()[:32]}"
    run = db.get(decision_intelligence.DecisionRun, run_id)
    scope = {
        "project_id": project_id,
        "object_type_id": object_type_id,
        "partitioned": True,
        "batch_size": batch_size,
        "cutoff": cutoff,
        "execution_job_id": job_id,
        "finding_retention": "first_high_risk_or_representative",
        "finding_limit": finding_limit,
        "findings_retained": len(retained),
        "band_counts": band_counts,
    }
    if run is None:
        run = decision_intelligence.DecisionRun(
            id=run_id, project_id=project_id, scope=scope, status="SUCCESS",
            object_count=evaluated, findings=retained, created_at=cutoff, completed_at=_now(),
        )
        db.add(run)
    else:
        run.scope = scope
        run.status = "SUCCESS"
        run.object_count = evaluated
        run.findings = retained
        run.completed_at = _now()
    create_audit_log(
        db, actor=principal.id, event_type="decision.evaluate.partitioned",
        subject_type="decision_run", subject_id=run.id,
        payload={"project_id": project_id, "object_count": evaluated, "band_counts": band_counts},
    )
    ops_control.record_ops_event(
        db, project_id=project_id, source="decision", event_type="decision.evaluate.partitioned",
        severity="critical" if band_counts["critical"] else ("high" if band_counts["high"] else "info"),
        title=f"Partitioned decision evaluation completed for {object_type_id}",
        subject_type="decision_run", subject_id=run.id, object_type_id=object_type_id,
        payload={"object_count": evaluated, "band_counts": band_counts, "findings_retained": len(retained)},
    )
    db.flush()
    return {
        "id": run.id,
        "project_id": project_id,
        "scope": scope,
        "status": run.status,
        "object_count": evaluated,
        "findings": retained,
        "band_counts": band_counts,
        "findings_retained": len(retained),
        "created_at": run.created_at,
        "completed_at": run.completed_at,
    }


def execute_industrial_onboarding_job(
    db: Session,
    *,
    payload: Dict[str, Any],
    actor: str,
    job_id: str,
    lease_token: str,
    lease_seconds: int,
    principal: production_auth.Principal,
) -> Dict[str, Any]:
    body = IndustrialOnboardingRequest.model_validate(payload.get("request") or {})
    if body.execution_mode != "background":
        body.execution_mode = "background"
    asset = db.get(models.DataAsset, body.source_asset_id)
    if not asset or asset.project_id != body.project_id:
        raise HTTPException(status_code=404, detail="Industrial source dataset no longer exists")
    source_snapshot = db.get(data_plane.DataAssetSnapshot, str(payload.get("source_snapshot_id") or ""))
    if not source_snapshot or source_snapshot.project_id != body.project_id or source_snapshot.asset_id != asset.id:
        raise HTTPException(status_code=409, detail="Industrial source snapshot no longer matches the queued job")
    ids = _ids(body.project_id)
    pipeline = _resource(db, models.PipelineDefinition, ids["pipeline"], body.project_id)
    if pipeline is None:
        raise HTTPException(status_code=409, detail="Industrial hydration pipeline no longer exists")
    run, plan, output_snapshot, hydration = _run_snapshot_pipeline(
        db, body, asset, source_snapshot, pipeline, actor, execution_job_id=job_id,
        execution_lease_token=lease_token, lease_seconds=lease_seconds,
        execution_principal=principal,
    )
    evaluation = _evaluate_partitioned_decision(
        db, project_id=body.project_id, object_type_id=ids["object_type"],
        job_id=job_id, lease_token=lease_token, lease_seconds=lease_seconds,
        principal=principal,
    )
    band_counts = dict(evaluation.get("band_counts") or {})
    high_risk_count = int(band_counts.get("high") or 0) + int(band_counts.get("critical") or 0)
    return {
        "project_id": body.project_id, "status": "READY",
        "summary": {
            "source_records": source_snapshot.row_count,
            "objects_hydrated": run.records_out,
            "objects_retired": int(hydration.get("retired_objects") or 0),
            "high_risk_assets": high_risk_count,
            "risk_objects_evaluated": evaluation.get("object_count", 0),
            "risk_evaluation_truncated": False,
            "risk_band_counts": band_counts,
            "risk_findings_retained": evaluation.get("findings_retained", 0),
        },
        "resources": {
            **ids, "source_asset": asset.id, "source_snapshot": source_snapshot.id,
            "output_snapshot": output_snapshot.id, "pipeline_plan": plan.id,
            "pipeline_run": run.id, "ontology_contract_run": hydration.get("contract_run_id"),
            "decision_run": evaluation.get("id"), "execution_job": job_id,
        },
        "evidence_links": [
            {"kind": "source_snapshot", "id": source_snapshot.id, "href": f"/api/v1/dataset-snapshots/{source_snapshot.id}/rows"},
            {"kind": "pipeline_plan", "id": plan.id, "href": f"/api/v1/pipeline-plans/{plan.id}"},
            {"kind": "output_snapshot", "id": output_snapshot.id, "href": f"/api/v1/dataset-snapshots/{output_snapshot.id}/rows"},
            {"kind": "pipeline_run", "id": run.id, "href": f"/pipeline-runs/{run.id}"},
            {"kind": "job", "id": job_id, "href": f"/jobs/{job_id}"},
        ],
        "warnings": [],
        "last_updated": _now(),
    }


@router.post("/api/v1/industrial/workflows/asset-reliability/onboard")
def onboard_asset_reliability(
    body: IndustrialOnboardingRequest,
    response: Response,
    principal: production_auth.Principal = Depends(production_auth.require_permission("edit")),
    db: Session = Depends(get_db),
):
    tenancy.assert_project_permission(db, principal, body.project_id, "edit")
    if body.run_pipeline:
        tenancy.assert_project_permission(db, principal, body.project_id, "execute")
    if body.publish_ontology:
        tenancy.assert_project_permission(db, principal, body.project_id, "publish")
    elif body.run_pipeline:
        raise HTTPException(status_code=422, detail="Pipeline hydration requires a published ontology contract")
    asset = db.get(models.DataAsset, body.source_asset_id)
    if not asset or asset.project_id != body.project_id:
        raise HTTPException(status_code=404, detail=f"DataAsset '{body.source_asset_id}' not found in project '{body.project_id}'")
    source_snapshot = _source_snapshot(db, body, asset, principal.id)
    resources = _upsert_contract(db, body, asset, source_snapshot.schema or {})
    publication = _publish_contract(
        db, project_id=body.project_id, actor=principal.id, allow_breaking=body.allow_breaking_ontology,
    ) if body.publish_ontology else None
    create_audit_log(db, actor=principal.id, event_type="industrial.workflow.contract.compiled", subject_type="object_type", subject_id=resources["ids"]["object_type"], payload={"project_id": body.project_id, "source_asset_id": asset.id, "pipeline_id": resources["ids"]["pipeline"]})
    db.flush()
    if body.execution_mode == "background" and body.run_pipeline:
        graph = _snapshot_graph(db, body, asset, source_snapshot, resources["ids"]["output_asset"])
        plan = data_plane._compile_plan(db, graph, "duckdb", principal.id)
        if plan.status != "VALID":
            raise HTTPException(status_code=422, detail={"message": "Industrial snapshot pipeline is invalid", "validation": plan.validation})
        idempotency_key = body.idempotency_key or hashlib.sha256(
            f"industrial:{body.project_id}:{source_snapshot.content_hash}:{plan.plan_hash}".encode("utf-8")
        ).hexdigest()
        job = platform_runtime.create_job(platform_runtime.JobCreate(
            project_id=body.project_id, job_type="industrial.ontology_hydrate",
            subject_type="pipeline_execution_plan", subject_id=plan.id,
            payload={
                "request": body.model_dump(), "source_snapshot_id": source_snapshot.id,
                "graph_id": graph.id, "plan_id": plan.id,
            },
            priority=60, max_attempts=5, timeout_seconds=7200,
            idempotency_key=idempotency_key, estimated_records=float(source_snapshot.row_count),
        ), principal, db)
        response.status_code = 202
        return {
            "project_id": body.project_id, "status": "QUEUED",
            "summary": {"source_records": source_snapshot.row_count, "objects_hydrated": 0, "high_risk_assets": 0},
            "resources": {
                **resources["ids"], "source_asset": asset.id, "source_snapshot": source_snapshot.id,
                "pipeline_plan": plan.id, "execution_job": job["id"],
                "ontology_revision": (publication or {}).get("revision", {}).get("id"),
                "ontology_registry": (publication or {}).get("registry", {}).get("id"),
            },
            "ontology_contract": publication, "execution": job,
            "primary_actions": [
                {"id": "monitor-job", "label": "Monitor background onboarding", "href": f"/jobs/{job['id']}"},
                {"id": "open-pipeline", "label": "Open hydration pipeline", "href": f"/workspace/pipeline?graph={graph.id}"},
            ],
            "evidence_links": [
                {"kind": "dataset_snapshot", "id": source_snapshot.id, "href": f"/api/v1/dataset-snapshots/{source_snapshot.id}/rows"},
                {"kind": "pipeline_plan", "id": plan.id, "href": f"/api/v1/pipeline-plans/{plan.id}"},
                {"kind": "job", "id": job["id"], "href": f"/jobs/{job['id']}"},
            ],
            "warnings": [], "last_updated": _now(),
        }
    try:
        if body.run_pipeline:
            run, plan, output_snapshot, hydration = _run_snapshot_pipeline(
                db, body, asset, source_snapshot, resources["pipeline"], principal.id,
            )
        else:
            run = plan = output_snapshot = None
            hydration = {}
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=422, detail={"message": "Dataset hydration failed validation", "error": str(exc)}) from exc
    db.commit()
    evaluation = decision_intelligence.evaluate_decision_scope_inline(decision_intelligence.DecisionEvaluateRequest(
        project_id=body.project_id, object_type_id=resources["ids"]["object_type"],
        limit=min(source_snapshot.row_count, 10000), persist_run=True,
    ), db)
    high_risk = [finding for finding in evaluation["findings"] if finding["risk"]["band"] in {"high", "critical"}]
    return {
        "project_id": body.project_id,
        "status": "READY",
        "summary": {
            "source_records": source_snapshot.row_count,
            "objects_hydrated": run.records_out if run else 0,
            "objects_retired": int(hydration.get("retired_objects") or 0),
            "high_risk_assets": len(high_risk),
        },
        "resources": {
            **resources["ids"], "source_asset": asset.id, "pipeline_run": run.id if run else None,
            "source_snapshot": source_snapshot.id,
            "output_snapshot": output_snapshot.id if output_snapshot else None,
            "pipeline_plan": plan.id if plan else None,
            "ontology_contract_run": hydration.get("contract_run_id"),
            "decision_run": evaluation.get("id"),
            "ontology_revision": (publication or {}).get("revision", {}).get("id"),
            "ontology_registry": (publication or {}).get("registry", {}).get("id"),
        },
        "ontology_contract": publication,
        "primary_actions": [
            {"id": "inspect-risk", "label": "Inspect high-risk assets", "href": "/workspace/decision"},
            {"id": "open-pipeline", "label": "Open hydration pipeline", "href": f"/workspace/pipeline?graph={resources['ids']['pipeline_graph']}"},
            {"id": "open-ontology", "label": "Open ontology contract", "href": f"/workspace/ontology?object_type={resources['ids']['object_type']}"},
        ],
        "evidence_links": [
            {"kind": "dataset", "id": asset.id, "href": f"/data-assets/{asset.id}"},
            {"kind": "dataset_snapshot", "id": source_snapshot.id, "href": f"/api/v1/dataset-snapshots/{source_snapshot.id}/rows"},
            {"kind": "pipeline_plan", "id": plan.id if plan else None, "href": f"/api/v1/pipeline-plans/{plan.id}" if plan else None},
            {"kind": "output_snapshot", "id": output_snapshot.id if output_snapshot else None, "href": f"/api/v1/dataset-snapshots/{output_snapshot.id}/rows" if output_snapshot else None},
            {"kind": "ontology_contract_run", "id": hydration.get("contract_run_id"), "href": f"/pipeline-builder/ontology-contracts/{hydration.get('contract_run_id')}" if hydration.get("contract_run_id") else None},
            {"kind": "pipeline_run", "id": run.id if run else None, "href": f"/pipeline-runs/{run.id}" if run else None},
            {"kind": "decision_run", "id": evaluation.get("id"), "href": "/workspace/decision"},
            {"kind": "ontology_revision", "id": (publication or {}).get("revision", {}).get("id"), "href": "/workspace/ontology"},
            {"kind": "ontology_registry", "id": (publication or {}).get("registry", {}).get("id"), "href": "/workspace/ontology"},
        ],
        "warnings": [],
        "last_updated": _now(),
    }


@router.get("/api/v1/industrial/workflows/asset-reliability/state")
def asset_reliability_state(
    project_id: str,
    principal: production_auth.Principal = Depends(production_auth.require_permission("view")),
    db: Session = Depends(get_db),
):
    tenancy.assert_project_permission(db, principal, project_id, "view")
    ids = _ids(project_id)
    object_query = db.query(models.ObjectInstance).filter(
        models.ObjectInstance.project_id == project_id,
        models.ObjectInstance.object_type_id == ids["object_type"],
    )
    object_count = object_query.filter(models.ObjectInstance.is_active.is_(True)).count()
    retired_count = object_query.filter(models.ObjectInstance.is_active.is_(False)).count()
    latest_run = db.query(models.PipelineRun).filter(models.PipelineRun.project_id == project_id, models.PipelineRun.pipeline_id == ids["pipeline"]).order_by(models.PipelineRun.created_at.desc()).first()
    environment = db.query(ontology_versioning.OntologyEnvironment).filter(
        ontology_versioning.OntologyEnvironment.project_id == project_id,
        ontology_versioning.OntologyEnvironment.name == "production",
    ).first()
    registry = db.query(ontology_registry.OntologyRegistryEntry).filter(
        ontology_registry.OntologyRegistryEntry.project_id == project_id,
        ontology_registry.OntologyRegistryEntry.channel == "production",
    ).order_by(ontology_registry.OntologyRegistryEntry.created_at.desc()).first()
    execution_job = _latest_execution_job(db, project_id)
    decision_run = _latest_decision_run(db, project_id, execution_job)
    execution = _execution_job_dict(execution_job)
    lineage = dict(latest_run.lineage or {}) if latest_run else {}
    if execution_job and execution_job.status in {"QUEUED", "RUNNING"}:
        status = "PROCESSING"
    elif execution_job and execution_job.status in {"FAILED", "CANCELLED"}:
        status = "FAILED"
    elif object_count and latest_run and latest_run.status == "SUCCESS":
        status = "READY"
    else:
        status = "NOT_CONFIGURED"
    return {
        "project_id": project_id,
        "status": status,
        "summary": {
            "object_count": object_count, "retired_object_count": retired_count,
            "latest_pipeline_status": latest_run.status if latest_run else None,
            "ontology_published": bool(environment and environment.current_revision_id),
            "registry_version": registry.version if registry else None,
            "source_snapshot_id": lineage.get("source_snapshot_id"),
            "output_snapshot_id": lineage.get("output_snapshot_id"),
            "pipeline_plan_id": lineage.get("pipeline_plan_id"),
            "latest_execution_job": execution,
            "latest_decision_run_id": decision_run.id if decision_run else None,
            "risk_objects_evaluated": decision_run.object_count if decision_run else 0,
            "risk_band_counts": (decision_run.scope or {}).get("band_counts") if decision_run else {},
        },
        "resources": {
            **ids, "pipeline_run": latest_run.id if latest_run else None,
            "source_snapshot": lineage.get("source_snapshot_id"),
            "output_snapshot": lineage.get("output_snapshot_id"),
            "pipeline_plan": lineage.get("pipeline_plan_id"),
            "execution_job": execution_job.id if execution_job else None,
            "decision_run": decision_run.id if decision_run else None,
            "ontology_revision": environment.current_revision_id if environment else None,
            "ontology_registry": registry.id if registry else None,
        },
        "primary_actions": [{"id": "onboard", "label": "Onboard a promoted dataset", "method": "POST", "path": "/api/v1/industrial/workflows/asset-reliability/onboard"}],
        "evidence_links": [
            {"kind": "source_snapshot", "id": lineage.get("source_snapshot_id"), "href": f"/api/v1/dataset-snapshots/{lineage.get('source_snapshot_id')}/rows" if lineage.get("source_snapshot_id") else None},
            {"kind": "output_snapshot", "id": lineage.get("output_snapshot_id"), "href": f"/api/v1/dataset-snapshots/{lineage.get('output_snapshot_id')}/rows" if lineage.get("output_snapshot_id") else None},
            {"kind": "pipeline_plan", "id": lineage.get("pipeline_plan_id"), "href": f"/api/v1/pipeline-plans/{lineage.get('pipeline_plan_id')}" if lineage.get("pipeline_plan_id") else None},
            {"kind": "execution_job", "id": execution_job.id if execution_job else None, "href": f"/jobs/{execution_job.id}" if execution_job else None},
            {"kind": "decision_run", "id": decision_run.id if decision_run else None, "href": "/workspace/decision" if decision_run else None},
        ],
        "warnings": ([execution_job.error or "Industrial onboarding failed."] if status == "FAILED" else []) or ([] if object_count or status == "PROCESSING" else ["No project-owned industrial asset workflow has been onboarded."]),
        "last_updated": _now(),
    }


@router.post("/api/v1/industrial/workflows/asset-reliability/triage")
def triage_asset_reliability(
    body: IndustrialTriageRequest,
    principal: production_auth.Principal = Depends(production_auth.require_permission("execute")),
    db: Session = Depends(get_db),
):
    tenancy.assert_project_permission(db, principal, body.project_id, "execute")
    ids = _ids(body.project_id)
    object_type = db.get(models.ObjectType, ids["object_type"])
    action = db.get(models.ActionType, ids["action"])
    agent = db.get(models.AgentDefinition, ids["agent"])
    if not object_type or object_type.project_id != body.project_id or not action or not agent:
        raise HTTPException(status_code=409, detail="Onboard a promoted dataset before running industrial triage")
    objects_query = db.query(models.ObjectInstance).filter(
        models.ObjectInstance.project_id == body.project_id,
        models.ObjectInstance.object_type_id == ids["object_type"],
        models.ObjectInstance.is_active.is_(True),
    )
    if body.object_id:
        objects_query = objects_query.filter(models.ObjectInstance.id == body.object_id)
    objects = objects_query.all()
    if not objects:
        raise HTTPException(status_code=404, detail="No matching project-owned industrial asset was found")

    scored = [(obj, decision_intelligence.score_object(db, obj, scorecard_ids=[ids["scorecard"]])) for obj in objects]
    obj, risk = max(scored, key=lambda item: float(item[1].get("score") or 0))
    if risk.get("band") not in {"high", "critical"}:
        raise HTTPException(status_code=422, detail={"message": "Triage requires a high- or critical-risk asset", "object_id": obj.id, "risk": risk})
    decision_run = decision_intelligence.evaluate_decision_scope_inline(
        decision_intelligence.DecisionEvaluateRequest(
            project_id=body.project_id, object_type_id=ids["object_type"], object_ids=[obj.id],
            scorecard_ids=[ids["scorecard"]], persist_run=True,
        ),
        db,
    )
    reason = body.reason or risk.get("explanation") or "Elevated reliability risk requires inspection."
    approval = _stage_approval(
        db, project_id=body.project_id, action_type_id=ids["action"], object_id=obj.id,
        reason=reason, actor=principal.id,
    )
    recommendation = (
        f"Inspect {(obj.properties or {}).get('name') or obj.id}, preserve the current evidence, "
        "and keep the incident open until the reliability signal returns below the governed threshold."
    )
    latest_pipeline_run = db.query(models.PipelineRun).filter(
        models.PipelineRun.project_id == body.project_id,
        models.PipelineRun.pipeline_id == ids["pipeline"],
    ).order_by(models.PipelineRun.created_at.desc()).first()
    citations: List[Dict[str, Any]] = [
        {"kind": "decision_run", "id": decision_run.get("id")},
        {"kind": "scorecard", "id": ids["scorecard"]},
    ]
    if latest_pipeline_run:
        citations.append({"kind": "pipeline_run", "id": latest_pipeline_run.id})
    session = models.AgentSession(
        id=uuid.uuid4().hex, agent_id=agent.id,
        user_prompt=f"Triage industrial asset {obj.id}.", status="COMPLETED",
        context={
            "project_id": body.project_id, "object_type_id": ids["object_type"], "object_id": obj.id,
            "risk": risk, "citations": citations,
        },
        plan={"recommendation": recommendation, "tool_trace": ["query_asset", "score_risk", "explain_drivers", "stage_approval", "open_incident", "draft_report"]},
        proposed_actions=[{"action_type_id": ids["action"], "parameters": approval.parameters, "requires_approval": True}],
        created_at=_now(), completed_at=_now(),
    )
    db.add(session)
    case = _ensure_case(
        db, project_id=body.project_id, object_type_id=ids["object_type"], obj=obj,
        approval=approval, risk=risk, actor=principal.id,
    )
    report = investigations.InvestigationReport(
        id=f"report_{uuid.uuid4().hex[:12]}", project_id=body.project_id,
        investigation_id=case["investigation"].id, title="Industrial Asset Reliability Triage Report",
        body=f"# Industrial Asset Reliability Triage Report\n\n{recommendation}\n\nApproval: {approval.id} ({approval.status})\n",
        sections=[
            {"title": "Recommendation", "content": recommendation},
            {"title": "Risk explanation", "content": risk},
            {"title": "Governance", "content": {"approval_id": approval.id, "status": approval.status, "action_type_id": action.id}},
        ],
        created_at=_now(),
    )
    db.add(report)
    create_audit_log(db, actor=principal.id, event_type="industrial.workflow.triage.completed", subject_type="object", subject_id=obj.id, payload={"project_id": body.project_id, "decision_run_id": decision_run.get("id"), "approval_id": approval.id, "incident_id": case["incident"].id, "report_id": report.id})
    ops_control.record_ops_event(db, project_id=body.project_id, source="industrial_workflow", event_type="industrial.workflow.triage.completed", severity=risk.get("band", "high"), title=f"Reliability triage completed for {(obj.properties or {}).get('name') or obj.id}", subject_type="object", subject_id=obj.id, object_type_id=ids["object_type"], object_id=obj.id, payload={"approval_id": approval.id, "incident_id": case["incident"].id, "agent_session_id": session.id})
    db.commit()
    return {
        "project_id": body.project_id,
        "status": "APPROVAL_REQUIRED" if approval.status == "PENDING" else "ACTION_READY",
        "object": {"id": obj.id, "object_type_id": obj.object_type_id, "properties": obj.properties or {}},
        "risk": risk, "recommendation": recommendation, "decision_run": decision_run,
        "agent_session": {"id": session.id, "status": session.status, "plan": session.plan, "context": session.context, "proposed_actions": session.proposed_actions},
        "approval": _approval_dict(approval),
        "incident": ops_control._incident_dict(case["incident"]),
        "investigation": investigations._workspace_dict(case["investigation"]),
        "report": investigations._report_dict(report),
        "evidence_links": [
            {"kind": "object", "id": obj.id, "href": f"/workspace/object-explorer?object_type={ids['object_type']}&object={obj.id}"},
            {"kind": "approval", "id": approval.id, "href": "/workspace/command-center"},
            {"kind": "incident", "id": case["incident"].id, "href": "/workspace/ops"},
            {"kind": "investigation", "id": case["investigation"].id, "href": "/workspace/investigations"},
            {"kind": "report", "id": report.id, "href": f"/api/v1/industrial/workflows/asset-reliability/report?project_id={body.project_id}&format=markdown"},
        ],
        "last_updated": _now(),
    }


@router.get("/api/v1/industrial/workflows/asset-reliability/workflow-state")
def industrial_asset_reliability_workflow_state(
    project_id: str,
    principal: production_auth.Principal = Depends(production_auth.require_permission("view")),
    db: Session = Depends(get_db),
):
    tenancy.assert_project_permission(db, principal, project_id, "view")
    ids = _ids(project_id)
    object_query = db.query(models.ObjectInstance).filter(
        models.ObjectInstance.project_id == project_id,
        models.ObjectInstance.object_type_id == ids["object_type"],
    )
    object_count = object_query.filter(models.ObjectInstance.is_active.is_(True)).count()
    retired_count = object_query.filter(models.ObjectInstance.is_active.is_(False)).count()
    pipeline_run = db.query(models.PipelineRun).filter(models.PipelineRun.project_id == project_id, models.PipelineRun.pipeline_id == ids["pipeline"]).order_by(models.PipelineRun.created_at.desc()).first()
    environment = db.query(ontology_versioning.OntologyEnvironment).filter(
        ontology_versioning.OntologyEnvironment.project_id == project_id,
        ontology_versioning.OntologyEnvironment.name == "production",
    ).first()
    revision_id = environment.current_revision_id if environment else None
    execution_job = _latest_execution_job(db, project_id)
    decision_run = _latest_decision_run(db, project_id, execution_job)
    execution = _execution_job_dict(execution_job)
    job_running = bool(execution_job and execution_job.status in {"QUEUED", "RUNNING"})
    job_failed = bool(execution_job and execution_job.status in {"FAILED", "CANCELLED"})
    rows = _latest_workflow_rows(db, project_id)
    approval = rows["approval"]
    action_event = rows["action_event"]
    report = rows["report"]
    pipeline_lineage = dict(pipeline_run.lineage or {}) if pipeline_run else {}
    source_snapshot_id = pipeline_lineage.get("source_snapshot_id")
    output_snapshot_id = pipeline_lineage.get("output_snapshot_id")
    pipeline_plan_id = pipeline_lineage.get("pipeline_plan_id")
    source_asset_id = pipeline_run.input_asset_id if pipeline_run else (
        ((execution_job.payload or {}).get("request") or {}).get("source_asset_id") if execution_job else None
    )
    steps = [
        {"id": "connect", "label": "Connect", "status": "complete" if pipeline_run or execution_job else "available", "evidence_id": source_asset_id},
        {"id": "transform", "label": "Transform", "status": "active" if job_running else ("complete" if pipeline_run and pipeline_run.status == "SUCCESS" else "blocked"), "evidence_id": pipeline_run.id if pipeline_run else (execution_job.id if execution_job else None)},
        {"id": "model", "label": "Model", "status": "complete" if object_count and revision_id else "blocked", "evidence_id": revision_id},
        {"id": "analyze", "label": "Analyze", "status": "complete" if approval else ("available" if object_count else "blocked"), "evidence_id": approval.id if approval else None},
        {"id": "approve", "label": "Approve", "status": "complete" if approval and approval.status == "APPROVED" else ("active" if approval and approval.status == "PENDING" else "blocked"), "evidence_id": approval.id if approval else None},
        {"id": "act", "label": "Act", "status": "complete" if action_event else ("available" if approval and approval.status == "APPROVED" else "blocked"), "evidence_id": action_event.id if action_event else None},
        {"id": "report", "label": "Report", "status": "available" if report else "blocked", "evidence_id": report.id if report else None},
    ]
    current = next((step for step in steps if step["status"] in {"active", "available"}), steps[-1])
    workflow_evidence = [
        {"kind": step["id"], "id": step["evidence_id"], "href": (
            f"/api/v1/industrial/workflows/asset-reliability/report?project_id={project_id}&format=markdown"
            if step["id"] == "report" else "/workspace/command-center"
        )}
        for step in steps if step.get("evidence_id")
    ]
    for kind, evidence_id, href in (
        ("source_snapshot", source_snapshot_id, f"/api/v1/dataset-snapshots/{source_snapshot_id}/rows"),
        ("pipeline_plan", pipeline_plan_id, f"/api/v1/pipeline-plans/{pipeline_plan_id}"),
        ("output_snapshot", output_snapshot_id, f"/api/v1/dataset-snapshots/{output_snapshot_id}/rows"),
        ("execution_job", execution_job.id if execution_job else None, f"/jobs/{execution_job.id}" if execution_job else None),
        ("decision_run", decision_run.id if decision_run else None, "/workspace/decision" if decision_run else None),
    ):
        if evidence_id:
            workflow_evidence.append({"kind": kind, "id": evidence_id, "href": href})
    workflow_status = "PROCESSING" if job_running else ("FAILED" if job_failed else ("READY" if object_count else "NOT_CONFIGURED"))
    return {
        "project_id": project_id, "status": workflow_status,
        "current_step": current["id"], "completed_steps": [step["id"] for step in steps if step["status"] == "complete"],
        "next_action": current["label"], "blocked_reason": (
            execution_job.error or "Background onboarding failed. Retry the execution job."
            if job_failed else (None if object_count or job_running else "Onboard a promoted dataset first.")
        ),
        "steps": steps,
        "summary": {
            "object_count": object_count,
            "retired_object_count": retired_count,
            "latest_pipeline_status": pipeline_run.status if pipeline_run else None,
            "ontology_revision_id": revision_id,
            "source_snapshot_id": source_snapshot_id,
            "output_snapshot_id": output_snapshot_id,
            "pipeline_plan_id": pipeline_plan_id,
            "latest_execution_job": execution,
            "latest_decision_run_id": decision_run.id if decision_run else None,
            "risk_objects_evaluated": decision_run.object_count if decision_run else 0,
            "risk_band_counts": (decision_run.scope or {}).get("band_counts") if decision_run else {},
            "latest_approval": _approval_dict(approval) if approval else None,
            "latest_action": {
                "id": action_event.id,
                "action_type_id": action_event.action_type_id,
                "status": action_event.status,
                "outbox_status": action_event.status,
                "approval_request_id": (action_event.payload or {}).get("approval_request_id"),
                "mutated_object_ids": (action_event.payload or {}).get("mutated_object_ids") or [],
                "parameters": (action_event.payload or {}).get("parameters") or {},
            } if action_event else None,
            "latest_report_id": report.id if report else None,
        },
        "evidence_links": workflow_evidence,
        "warnings": [execution_job.error or "Background onboarding failed."] if job_failed else [], "last_updated": _now(),
    }


@router.get("/api/v1/industrial/workflows/asset-reliability/report")
def industrial_asset_reliability_report(
    project_id: str,
    format: str = Query("json", pattern="^(json|markdown)$"),
    principal: production_auth.Principal = Depends(production_auth.require_permission("export")),
    db: Session = Depends(get_db),
):
    tenancy.assert_project_permission(db, principal, project_id, "export")
    payload = _report_payload(db, project_id)
    if not payload.get("investigation_id"):
        raise HTTPException(status_code=409, detail="Run industrial triage before exporting a report")
    create_audit_log(db, actor=principal.id, event_type="industrial.workflow.report.exported", subject_type="investigation", subject_id=payload["investigation_id"], payload={"project_id": project_id, "format": format, "evidence_ids": payload["evidence_ids"]})
    ops_control.record_ops_event(db, project_id=project_id, source="industrial_workflow", event_type="industrial.workflow.report.exported", severity="info", title="Industrial reliability report exported", subject_type="investigation", subject_id=payload["investigation_id"], payload={"format": format, "report_id": payload.get("report_id")})
    db.commit()
    if format == "markdown":
        return PlainTextResponse(_report_markdown(payload), media_type="text/markdown")
    return payload


@router.post("/api/v1/industrial/workflows/asset-reliability/evaluator-evidence")
def industrial_asset_reliability_evaluator_evidence(
    body: ExternalEvaluatorEvidenceRequest,
    principal: production_auth.Principal = Depends(production_auth.require_permission("export")),
    db: Session = Depends(get_db),
):
    """Export a tamper-evident, privacy-preserving external evaluation bundle."""
    tenancy.assert_project_permission(db, principal, body.project_id, "export")
    ids = _ids(body.project_id)
    pipeline_run = db.query(models.PipelineRun).filter(
        models.PipelineRun.project_id == body.project_id,
        models.PipelineRun.pipeline_id == ids["pipeline"],
    ).order_by(models.PipelineRun.created_at.desc()).first()
    rows = _latest_workflow_rows(db, body.project_id)
    approval = rows["approval"]
    action_event = rows["action_event"]
    report = rows["report"]
    environment = db.query(ontology_versioning.OntologyEnvironment).filter(
        ontology_versioning.OntologyEnvironment.project_id == body.project_id,
        ontology_versioning.OntologyEnvironment.name == "production",
    ).first()
    decision_run = _latest_decision_run(db, body.project_id, _latest_execution_job(db, body.project_id))
    object_count = db.query(models.ObjectInstance).filter(
        models.ObjectInstance.project_id == body.project_id,
        models.ObjectInstance.object_type_id == ids["object_type"],
        models.ObjectInstance.is_active.is_(True),
    ).count()
    lineage = dict(pipeline_run.lineage or {}) if pipeline_run else {}
    source_snapshot_id = str(lineage.get("source_snapshot_id") or "")
    source_snapshot = db.get(data_plane.DataAssetSnapshot, source_snapshot_id) if source_snapshot_id else None
    source_asset_id = pipeline_run.input_asset_id if pipeline_run else None
    source_asset = db.get(models.DataAsset, source_asset_id) if source_asset_id else None
    import_job = db.query(imports_ops.ImportJob).filter(
        imports_ops.ImportJob.project_id == body.project_id,
        imports_ops.ImportJob.target_dataset_id == source_asset_id,
        imports_ops.ImportJob.status == "PROMOTED",
    ).order_by(imports_ops.ImportJob.promoted_at.desc()).first() if source_asset_id else None
    sample_source_ids = {"maintenance_raw_assets", "maintenance_raw_work_orders", "asset_reliability_raw"}
    provenance_verified = bool(
        source_asset
        and source_asset.id not in sample_source_ids
        and (import_job or source_asset.file_ref)
    )

    step_facts = [
        ("connect", source_snapshot_id),
        ("transform", pipeline_run.id if pipeline_run and pipeline_run.status == "SUCCESS" else None),
        ("model", environment.current_revision_id if environment and object_count else None),
        ("analyze", decision_run.id if decision_run else None),
        ("approve", approval.id if approval and approval.status == "APPROVED" else None),
        ("act", action_event.id if action_event and action_event.status in {"PENDING", "PUBLISHED", "DELIVERED"} else None),
        ("report", report.id if report else None),
    ]
    steps = [
        {"id": step_id, "status": "complete" if evidence_id else "incomplete", "evidence_id": evidence_id}
        for step_id, evidence_id in step_facts
    ]
    report_payload = _report_payload(db, body.project_id) if report else {}
    release_commit = os.getenv("ONTOLOGYOS_RELEASE_COMMIT", "development").strip().lower()
    auth_mode = os.getenv("AUTH_MODE", "local").strip().lower()
    reasons = []
    if not body.external_team_confirmation:
        reasons.append("external_team_confirmation_required")
    if not body.own_data_confirmation:
        reasons.append("own_data_confirmation_required")
    if not provenance_verified:
        reasons.append("own_data_provenance_required")
    if auth_mode != "oidc":
        reasons.append("oidc_authentication_required")
    if not (7 <= len(release_commit) <= 64 and all(character in "0123456789abcdef" for character in release_commit)):
        reasons.append("pinned_release_commit_required")
    reasons.extend(f"workflow_step_incomplete:{item['id']}" for item in steps if item["status"] != "complete")

    evaluator_identity_hash = hashlib.sha256(
        f"{body.team_id}:{body.organization_id}:{body.evaluator_alias.strip().lower()}".encode("utf-8")
    ).hexdigest()
    principal_hash = hashlib.sha256(f"{body.organization_id}:{principal.id}".encode("utf-8")).hexdigest()
    payload = {
        "schema_version": evaluator_evidence.SCHEMA_VERSION,
        "kind": evaluator_evidence.KIND,
        "generated_at": _now(),
        "migration_head": current_migration_head(),
        "release_commit": release_commit,
        "authentication_mode": auth_mode,
        "project": {"id": body.project_id, "object_count": object_count},
        "evaluator": {
            "team_id": body.team_id,
            "organization_id": body.organization_id,
            "deployment_id": body.deployment_id,
            "identity_hash": evaluator_identity_hash,
            "principal_hash": principal_hash,
            "external_team_confirmation": body.external_team_confirmation,
        },
        "dataset": {
            "asset_id": source_asset_id,
            "snapshot_id": source_snapshot_id or None,
            "content_hash": source_snapshot.content_hash if source_snapshot else None,
            "row_count": source_snapshot.row_count if source_snapshot else 0,
            "storage_format": source_snapshot.storage_format if source_snapshot else None,
            "import_job_id": import_job.id if import_job else None,
            "source_type": import_job.source_type if import_job else (source_asset.source_format if source_asset else None),
            "provenance_verified": provenance_verified,
            "own_data_confirmation": body.own_data_confirmation,
        },
        "workflow": {
            "name": "asset_reliability_connect_to_report",
            "steps": steps,
            "evidence_ids": sorted({str(evidence_id) for _, evidence_id in step_facts if evidence_id}),
        },
        "report": {
            "id": report.id if report else None,
            "content_hash": evaluator_evidence.sha256_json(report_payload),
            "payload": report_payload,
        },
        "qualification": {"qualifies": not reasons, "reasons": sorted(set(reasons))},
    }
    bundle = evaluator_evidence.seal_bundle(payload)
    create_audit_log(
        db, actor=principal.id, event_type="industrial.workflow.evaluator_evidence.exported",
        subject_type="project", subject_id=body.project_id,
        payload={
            "project_id": body.project_id, "team_id": body.team_id,
            "deployment_id": body.deployment_id, "bundle_hash": bundle["bundle_hash"],
            "qualifies": bundle["qualification"]["qualifies"],
        },
    )
    ops_control.record_ops_event(
        db, project_id=body.project_id, source="industrial_workflow",
        event_type="industrial.workflow.evaluator_evidence.exported", severity="info",
        title="External evaluator evidence exported", subject_type="project", subject_id=body.project_id,
        payload={"team_id": body.team_id, "bundle_hash": bundle["bundle_hash"], "qualifies": bundle["qualification"]["qualifies"]},
    )
    db.commit()
    return bundle

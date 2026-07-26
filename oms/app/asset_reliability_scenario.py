"""
Operational MVP scenario: Asset Reliability Command Center.

This module wires existing deterministic platform services into one useful
workflow: raw maintenance data -> pipelines -> ontology -> reliability checks
-> model monitor -> risk scoring -> agent recommendation -> approval/incident
-> investigation report.
"""
from __future__ import annotations

import time
import uuid
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from . import (
    decision_intelligence,
    investigations,
    modelops,
    modeling,
    models,
    models_action,
    ops_control,
    platform_core,
    reliability_ops,
)
from .database import get_db
from .domain_maintenance import (
    _upsert_data_asset,
    _upsert_pipeline,
    bootstrap_maintenance_copilot,
    maintenance_summary,
)
from .runtime import create_audit_log, execute_pipeline_steps, now_ts

router = APIRouter(tags=["asset_reliability_scenario"])

SCENARIO_ID = "asset_reliability"
HIGH_RISK_ASSET_ID = "asset_pump_4"
DEFAULT_WORK_ORDER_ID = "wo_pump_urgent"
SCENARIO_PIPELINES = [
    "hydrate_maintenance_facilities",
    "hydrate_maintenance_assets",
    "hydrate_maintenance_technicians",
    "hydrate_maintenance_parts",
    "hydrate_maintenance_work_orders",
    "hydrate_asset_reliability_signals",
]
SIGNAL_CURRENT_ASSET_ID = "asset_reliability_current"
SIGNAL_BASELINE_ASSET_ID = "asset_reliability_baseline"
SENSOR_ASSET_ID = "maintenance_sensor_readings"
DATA_CONTRACT_ID = "asset_reliability_sensor_contract"
MODEL_OBJECTIVE_ID = "asset_failure_risk_objective"
MODEL_DEPLOYMENT_ID = "asset_failure_risk_deployment"
MODEL_MONITOR_ID = "asset_failure_drift_monitor"
DECISION_SCORECARD_ID = "asset_reliability_scorecard"
INVESTIGATION_ID = "asset_reliability_case"
ALERT_RULE_ID = "asset_reliability_high_risk_alert"
POLICY_RULE_ID = "asset_reliability_high_risk_approval_policy"


class ScenarioBootstrapRequest(BaseModel):
    actor: str = "workspace"
    run_pipelines: bool = True
    run_checks: bool = True


class ProjectDemoRequest(BaseModel):
    actor: str = "workspace"
    run_pipelines: bool = True
    run_checks: bool = True


class ScenarioTriageRequest(BaseModel):
    actor: str = "workspace"
    asset_id: str = HIGH_RISK_ASSET_ID
    work_order_id: str = DEFAULT_WORK_ORDER_ID
    reason: Optional[str] = None


def _now() -> int:
    return int(time.time())


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def _resource_action(resource_type: str, resource_id: str, action: str) -> Dict[str, str]:
    return {"resource_type": resource_type, "id": resource_id, "action": action}


def _object_dict(obj: Optional[models.ObjectInstance]) -> Optional[Dict[str, Any]]:
    if not obj:
        return None
    return {
        "id": obj.id,
        "object_type_id": obj.object_type_id,
        "properties": obj.properties or {},
        "source_asset_id": obj.source_asset_id,
        "lineage": obj.lineage or {},
        "created_at": obj.created_at,
        "updated_at": obj.updated_at,
    }


def _pipeline_run_dict(run: models.PipelineRun) -> Dict[str, Any]:
    return {
        "id": run.id,
        "pipeline_id": run.pipeline_id,
        "status": run.status,
        "input_asset_id": run.input_asset_id,
        "output_asset_id": run.output_asset_id,
        "records_in": run.records_in,
        "records_out": run.records_out,
        "metrics": run.metrics or {},
        "lineage": run.lineage or {},
        "error": run.error,
        "created_at": run.created_at,
        "completed_at": run.completed_at,
    }


def _approval_dict(row: models_action.ApprovalRequest) -> Dict[str, Any]:
    return {
        "id": row.id,
        "action_type_id": row.action_type_id,
        "requester": row.requester,
        "parameters": row.parameters or {},
        "status": row.status,
        "reason": row.reason,
        "created_at": row.created_at,
        "decided_at": row.decided_at,
    }


def _agent_session_dict(row: models.AgentSession) -> Dict[str, Any]:
    return {
        "id": row.id,
        "agent_id": row.agent_id,
        "user_prompt": row.user_prompt,
        "status": row.status,
        "context": row.context or {},
        "plan": row.plan or {},
        "proposed_actions": row.proposed_actions or [],
        "created_at": row.created_at,
        "completed_at": row.completed_at,
    }


def _upsert_asset_reliability_data(db: Session) -> List[Dict[str, str]]:
    resources: List[Dict[str, str]] = []
    current_records = [
        {
            "asset_id": "asset_pump_4",
            "id": "asset_pump_4",
            "name": "Line 4 Pump",
            "facility_id": "facility_1",
            "asset_class": "pump",
            "status": "DEGRADED",
            "criticality": "high",
            "vibration_mm_s": 11.8,
            "temperature_c": 94.0,
            "runtime_hours": 1830,
            "predicted_failure_probability": 0.91,
            "actual_failure": 1,
            "last_seen_at": "2026-06-27T16:00:00Z",
            "longitude": -122.4012,
            "latitude": 37.7924,
        },
        {
            "asset_id": "asset_chiller_2",
            "id": "asset_chiller_2",
            "name": "Chiller 2",
            "facility_id": "facility_1",
            "asset_class": "chiller",
            "status": "RUNNING",
            "criticality": "medium",
            "vibration_mm_s": 3.1,
            "temperature_c": 73.2,
            "runtime_hours": 920,
            "predicted_failure_probability": 0.28,
            "actual_failure": 0,
            "last_seen_at": "2026-06-27T16:00:00Z",
            "longitude": -122.4072,
            "latitude": 37.7893,
        },
    ]
    baseline_records = [
        {"asset_id": "asset_pump_4", "asset_class": "pump", "vibration_mm_s": 2.4, "temperature_c": 68.0, "runtime_hours": 1140, "failure_risk": 0.18, "actual_failure": 0},
        {"asset_id": "asset_pump_4", "asset_class": "pump", "vibration_mm_s": 2.9, "temperature_c": 70.0, "runtime_hours": 1160, "failure_risk": 0.21, "actual_failure": 0},
        {"asset_id": "asset_chiller_2", "asset_class": "chiller", "vibration_mm_s": 2.2, "temperature_c": 67.5, "runtime_hours": 740, "failure_risk": 0.13, "actual_failure": 0},
        {"asset_id": "asset_chiller_2", "asset_class": "chiller", "vibration_mm_s": 2.0, "temperature_c": 66.8, "runtime_hours": 760, "failure_risk": 0.12, "actual_failure": 0},
    ]
    sensor_records = [
        {"reading_id": "sensor_1", "asset_id": "asset_pump_4", "vibration_mm_s": 11.8, "temperature_c": 94.0, "observed_at": "2026-06-27T16:00:00Z"},
        {"reading_id": "sensor_2", "asset_id": "asset_pump_4", "vibration_mm_s": 18.2, "temperature_c": 105.0, "observed_at": "2026-06-27T16:05:00Z"},
        {"reading_id": "sensor_3", "asset_id": "asset_chiller_2", "vibration_mm_s": 3.1, "temperature_c": "", "observed_at": "2026-06-27T16:00:00Z"},
    ]
    schema = {
        "asset_id": "string",
        "vibration_mm_s": "number",
        "temperature_c": "number",
        "runtime_hours": "number",
        "predicted_failure_probability": "number",
        "actual_failure": "integer",
    }
    resources.append(_upsert_data_asset(
        db,
        id=SIGNAL_CURRENT_ASSET_ID,
        display_name="Asset Reliability Current Signals",
        description="Current sensor and model features used by the command-center workflow.",
        records=current_records,
        asset_schema=schema,
    ))
    resources.append(_upsert_data_asset(
        db,
        id=SIGNAL_BASELINE_ASSET_ID,
        display_name="Asset Reliability Baseline Signals",
        description="Baseline feature profile for deterministic model drift checks.",
        records=baseline_records,
        asset_schema=schema,
    ))
    resources.append(_upsert_data_asset(
        db,
        id=SENSOR_ASSET_ID,
        display_name="Maintenance Sensor Readings",
        description="Raw sensor readings with deliberate quality issues for reliability checks.",
        records=sensor_records,
        asset_schema={"reading_id": "string", "asset_id": "string", "vibration_mm_s": "number", "temperature_c": "number", "observed_at": "string"},
    ))
    resources.append(_upsert_pipeline(
        db,
        id="hydrate_asset_reliability_signals",
        display_name="Hydrate Asset Reliability Signals",
        description="Hydrate current sensor/model signals onto asset ontology objects.",
        input_asset_id=SIGNAL_CURRENT_ASSET_ID,
        steps=[
            {"operation": "derive_geo_point", "longitude_field": "longitude", "latitude_field": "latitude", "target_field": "geometry"},
            {"operation": "derive_mgrs", "geometry_field": "geometry", "target_field": "mgrs", "precision": 5},
            {
                "operation": "map_to_ontology",
                "object_type_id": "asset",
                "object_id_field": "asset_id",
                "property_map": {
                    "name": "$name",
                    "facility_id": "$facility_id",
                    "asset_class": "$asset_class",
                    "status": "$status",
                    "criticality": "$criticality",
                    "geometry": "$geometry",
                    "mgrs": "$mgrs",
                    "vibration_mm_s": "$vibration_mm_s",
                    "temperature_c": "$temperature_c",
                    "runtime_hours": "$runtime_hours",
                    "predicted_failure_probability": "$predicted_failure_probability",
                    "actual_failure": "$actual_failure",
                    "last_seen_at": "$last_seen_at",
                },
            },
        ],
    ))
    return resources


def _run_pipeline_inline(db: Session, pipeline_id: str, *, actor: str) -> Dict[str, Any]:
    pipeline = db.get(models.PipelineDefinition, pipeline_id)
    if not pipeline:
        raise HTTPException(status_code=404, detail=f"PipelineDefinition '{pipeline_id}' not found")
    input_asset = db.get(models.DataAsset, pipeline.input_asset_id)
    if not input_asset:
        raise HTTPException(status_code=404, detail=f"DataAsset '{pipeline.input_asset_id}' not found")
    run = models.PipelineRun(
        id=str(uuid.uuid4()),
        pipeline_id=pipeline.id,
        status="RUNNING",
        input_asset_id=input_asset.id,
        output_asset_id=pipeline.output_asset_id,
        records_in=len(input_asset.records or []),
        records_out=0,
        lineage={},
        metrics={},
        created_at=now_ts(),
    )
    db.add(run)
    ops_control.record_ops_event(
        db,
        source="scenario",
        event_type="scenario.pipeline.started",
        severity="info",
        title=f"{pipeline.display_name} started",
        subject_type="pipeline_run",
        subject_id=run.id,
        payload={"pipeline_id": pipeline.id, "actor": actor},
    )
    try:
        output_records, lineage, metrics = execute_pipeline_steps(db, pipeline=pipeline, run_id=run.id, input_asset=input_asset)
        output_asset_id = pipeline.output_asset_id or f"{pipeline.id}_output"
        output_asset = db.get(models.DataAsset, output_asset_id)
        if not output_asset:
            output_asset = models.DataAsset(
                id=output_asset_id,
                display_name=f"{pipeline.display_name} Output",
                description=f"Output generated by {pipeline.display_name}",
                kind="dataset",
                asset_schema={},
                records=[],
                created_at=now_ts(),
                updated_at=now_ts(),
            )
            db.add(output_asset)
        output_asset.records = output_records
        output_asset.updated_at = now_ts()
        run.status = "SUCCESS"
        run.output_asset_id = output_asset.id
        run.records_out = len(output_records)
        run.lineage = lineage
        run.metrics = metrics
        run.completed_at = now_ts()
        ops_control.record_ops_event(
            db,
            source="scenario",
            event_type="scenario.pipeline.completed",
            severity="info",
            title=f"{pipeline.display_name} completed",
            subject_type="pipeline_run",
            subject_id=run.id,
            payload={"pipeline_id": pipeline.id, "records_out": len(output_records), "metrics": metrics},
        )
    except Exception as exc:
        run.status = "FAILED"
        run.error = str(exc)
        run.completed_at = now_ts()
        ops_control.record_ops_event(
            db,
            source="scenario",
            event_type="scenario.pipeline.failed",
            severity="high",
            title=f"{pipeline.display_name} failed",
            subject_type="pipeline_run",
            subject_id=run.id,
            payload={"pipeline_id": pipeline.id, "error": str(exc)},
        )
    db.commit()
    db.refresh(run)
    return _pipeline_run_dict(run)


def _ensure_link(db: Session, link_type_id: str, source_id: str, target_id: str) -> Optional[Dict[str, str]]:
    if not db.get(models.LinkType, link_type_id):
        return None
    if not db.get(models.ObjectInstance, source_id) or not db.get(models.ObjectInstance, target_id):
        return None
    link_id = f"{link_type_id}:{source_id}:{target_id}"
    existing = db.get(models.LinkInstance, link_id)
    if existing:
        return _resource_action("link", link_id, "exists")
    db.add(models.LinkInstance(
        id=link_id,
        link_type_id=link_type_id,
        source_object_id=source_id,
        target_object_id=target_id,
        properties={},
        created_at=now_ts(),
    ))
    return _resource_action("link", link_id, "created")


def _ensure_links(db: Session) -> List[Dict[str, str]]:
    resources = []
    for item in [
        _ensure_link(db, "facility_has_asset", "facility_1", "asset_pump_4"),
        _ensure_link(db, "facility_has_asset", "facility_1", "asset_chiller_2"),
        _ensure_link(db, "asset_has_work_order", "asset_pump_4", "wo_pump_urgent"),
        _ensure_link(db, "asset_has_work_order", "asset_chiller_2", "wo_chiller_inspect"),
        _ensure_link(db, "technician_assigned_work_order", "tech_amy", "wo_pump_urgent"),
    ]:
        if item:
            resources.append(item)
    db.commit()
    return resources


def _upsert_decision_resources(db: Session) -> List[Dict[str, str]]:
    now = _now()
    resources: List[Dict[str, str]] = []
    rules = [
        {
            "id": "asset_status_degraded_rule",
            "display_name": "Asset is degraded",
            "description": "Asset operational status is degraded.",
            "expression": {"field": "status", "op": "eq", "value": "DEGRADED"},
            "severity": "high",
            "recommended_actions": ["inspect_asset", "escalate_work_order"],
        },
        {
            "id": "asset_vibration_high_rule",
            "display_name": "Vibration above limit",
            "description": "Current vibration exceeds safe operating range.",
            "expression": {"field": "vibration_mm_s", "op": "gte", "value": 8},
            "severity": "high",
            "recommended_actions": ["reduce_load", "dispatch_technician"],
        },
        {
            "id": "asset_failure_probability_high_rule",
            "display_name": "Failure probability high",
            "description": "Model-estimated failure probability is elevated.",
            "expression": {"field": "predicted_failure_probability", "op": "gte", "value": 0.7},
            "severity": "critical",
            "recommended_actions": ["stage_escalation", "open_incident"],
        },
    ]
    for payload in rules:
        row = db.get(decision_intelligence.DecisionRule, payload["id"])
        if row:
            for key, value in payload.items():
                setattr(row, key, value)
            row.object_type_id = "asset"
            row.active = True
            row.updated_at = now
            action = "updated"
        else:
            db.add(decision_intelligence.DecisionRule(
                object_type_id="asset",
                active=True,
                created_at=now,
                updated_at=now,
                **payload,
            ))
            action = "created"
        resources.append(_resource_action("decision_rule", payload["id"], action))
    scorecard_payload = {
        "display_name": "Asset Reliability Risk Scorecard",
        "description": "Combines operational status, sensor thresholds, and model risk.",
        "object_type_id": "asset",
        "features": [
            {"rule_id": "asset_status_degraded_rule", "weight": 30, "reason": "asset status is degraded"},
            {"rule_id": "asset_vibration_high_rule", "weight": 25, "reason": "vibration exceeds safe limit"},
            {"rule_id": "asset_failure_probability_high_rule", "weight": 35, "reason": "failure probability is elevated"},
            {"field": "criticality", "op": "eq", "value": "high", "weight": 15, "reason": "asset is business critical"},
        ],
        "thresholds": {"medium": 35, "high": 65, "critical": 85},
        "recommended_actions": ["open_incident", "stage_escalation", "dispatch_available_technician"],
        "active": True,
    }
    scorecard = db.get(decision_intelligence.DecisionScorecard, DECISION_SCORECARD_ID)
    if scorecard:
        for key, value in scorecard_payload.items():
            setattr(scorecard, key, value)
        scorecard.updated_at = now
        action = "updated"
    else:
        db.add(decision_intelligence.DecisionScorecard(id=DECISION_SCORECARD_ID, created_at=now, updated_at=now, **scorecard_payload))
        action = "created"
    resources.append(_resource_action("decision_scorecard", DECISION_SCORECARD_ID, action))
    db.commit()
    return resources


def _upsert_data_contract(db: Session) -> Dict[str, str]:
    reliability_ops._ensure_tables(db)
    payload = {
        "display_name": "Asset Reliability Sensor Contract",
        "description": "Checks sensor rows used by the command center.",
        "asset_id": SENSOR_ASSET_ID,
        "checks": [
            {"type": "required_fields", "fields": ["reading_id", "asset_id", "vibration_mm_s", "temperature_c", "observed_at"]},
            {"type": "range", "field": "vibration_mm_s", "min": 0, "max": 12},
            {"type": "missing_rate", "field": "temperature_c", "max": 0},
            {"type": "unique", "field": "reading_id"},
        ],
        "enabled": True,
    }
    row = db.get(reliability_ops.DataQualityContract, DATA_CONTRACT_ID)
    now = _now()
    if row:
        for key, value in payload.items():
            setattr(row, key, value)
        row.updated_at = now
        action = "updated"
    else:
        db.add(reliability_ops.DataQualityContract(id=DATA_CONTRACT_ID, created_at=now, updated_at=now, **payload))
        action = "created"
    db.commit()
    return _resource_action("data_quality_contract", DATA_CONTRACT_ID, action)


def _upsert_model_lifecycle(db: Session) -> List[Dict[str, str]]:
    for table in (modelops.ModelMonitor.__table__, modelops.ModelMonitorRun.__table__, modelops.ModelPredictionLog.__table__):
        table.create(bind=db.get_bind(), checkfirst=True)
    resources: List[Dict[str, str]] = []
    now = _now()
    objective = db.get(modeling.ModelingObjective, MODEL_OBJECTIVE_ID)
    objective_payload = {
        "display_name": "Asset Failure Risk Objective",
        "description": "Deterministic regression objective for failure risk.",
        "problem_type": "regression",
        "target_field": "failure_risk",
        "feature_fields": ["vibration_mm_s", "temperature_c", "runtime_hours"],
        "input_asset_id": SIGNAL_BASELINE_ASSET_ID,
    }
    if objective:
        for key, value in objective_payload.items():
            setattr(objective, key, value)
        objective.updated_at = now
        resources.append(_resource_action("modeling_objective", MODEL_OBJECTIVE_ID, "updated"))
    else:
        db.add(modeling.ModelingObjective(id=MODEL_OBJECTIVE_ID, created_at=now, updated_at=now, **objective_payload))
        resources.append(_resource_action("modeling_objective", MODEL_OBJECTIVE_ID, "created"))

    submission = db.query(modeling.ModelSubmission).filter(
        modeling.ModelSubmission.objective_id == MODEL_OBJECTIVE_ID,
        modeling.ModelSubmission.released == True,  # noqa: E712
    ).first()
    if not submission:
        submission = modeling.ModelSubmission(
            id=_new_id("model_submission"),
            objective_id=MODEL_OBJECTIVE_ID,
            algorithm="regression",
            metrics={"mae": 0.74, "rmse": 1.18, "r2": 0.88},
            released=True,
            status="success",
            trainer_type="regression",
            training_dataset_id=SIGNAL_BASELINE_ASSET_ID,
            target_column="failure_risk",
            eval_metric="rmse",
            quality_preset="balanced",
            created_at=now,
        )
        db.add(submission)
        resources.append(_resource_action("model_submission", submission.id, "created"))
    else:
        submission.metrics = {"mae": 0.74, "rmse": 1.18, "r2": 0.88}
        submission.released = True
        resources.append(_resource_action("model_submission", submission.id, "exists"))

    deployment = db.get(modeling.ModelDeployment, MODEL_DEPLOYMENT_ID)
    if deployment:
        deployment.objective_id = MODEL_OBJECTIVE_ID
        deployment.submission_id = submission.id
        deployment.mode = "live"
        deployment.status = "running"
        resources.append(_resource_action("model_deployment", MODEL_DEPLOYMENT_ID, "updated"))
    else:
        db.add(modeling.ModelDeployment(
            id=MODEL_DEPLOYMENT_ID,
            objective_id=MODEL_OBJECTIVE_ID,
            submission_id=submission.id,
            mode="live",
            status="running",
            created_at=now,
        ))
        resources.append(_resource_action("model_deployment", MODEL_DEPLOYMENT_ID, "created"))

    monitor_payload = {
        "display_name": "Asset Failure Drift Monitor",
        "description": "Compares current asset sensor features against baseline operation.",
        "objective_id": MODEL_OBJECTIVE_ID,
        "deployment_id": MODEL_DEPLOYMENT_ID,
        "baseline_asset_id": SIGNAL_BASELINE_ASSET_ID,
        "feature_fields": ["vibration_mm_s", "temperature_c", "runtime_hours", "asset_class"],
        "prediction_field": "prediction",
        "target_field": "actual_failure",
        "thresholds": {
            "numeric_mean_shift_warn": 0.15,
            "numeric_mean_shift_fail": 0.35,
            "unseen_category_rate_warn": 0.25,
            "unseen_category_rate_fail": 0.5,
            "quality_r2_warn": 0.2,
        },
        "enabled": True,
    }
    monitor = db.get(modelops.ModelMonitor, MODEL_MONITOR_ID)
    if monitor:
        for key, value in monitor_payload.items():
            setattr(monitor, key, value)
        monitor.updated_at = now
        resources.append(_resource_action("model_monitor", MODEL_MONITOR_ID, "updated"))
    else:
        db.add(modelops.ModelMonitor(id=MODEL_MONITOR_ID, created_at=now, updated_at=now, **monitor_payload))
        resources.append(_resource_action("model_monitor", MODEL_MONITOR_ID, "created"))
    db.commit()
    return resources


def _upsert_ops_policy_and_map(db: Session) -> List[Dict[str, str]]:
    resources: List[Dict[str, str]] = []
    ops_control._ensure_tables(db)
    now = _now()
    rule = db.get(ops_control.AlertRule, ALERT_RULE_ID)
    alert_payload = {
        "display_name": "Asset Reliability High Risk Alert",
        "description": "Alert on high-severity asset reliability events.",
        "source": "decision",
        "event_type": None,
        "min_severity": "high",
        "subject_type": None,
        "object_type_id": "asset",
        "expression": {},
        "active": True,
    }
    if rule:
        for key, value in alert_payload.items():
            setattr(rule, key, value)
        rule.updated_at = now
        resources.append(_resource_action("alert_rule", ALERT_RULE_ID, "updated"))
    else:
        db.add(ops_control.AlertRule(id=ALERT_RULE_ID, created_at=now, updated_at=now, **alert_payload))
        resources.append(_resource_action("alert_rule", ALERT_RULE_ID, "created"))

    platform_core._ensure_tables(db)
    policy = db.get(platform_core.PolicyRule, POLICY_RULE_ID)
    policy_payload = {
        "display_name": "Require Approval for Reliability Escalations",
        "description": "High-risk reliability escalations require human approval.",
        "effect": "REQUIRE_APPROVAL",
        "principal": None,
        "action": "escalate_work_order",
        "resource_kind": "action",
        "resource_id": "escalate_work_order",
        "object_type_id": "work_order",
        "purpose": "asset_reliability_triage",
        "condition": {},
        "mask_properties": [],
        "row_filter": {},
        "approval": {"required": True, "reason": "critical asset reliability escalation"},
        "break_glass_allowed": False,
        "priority": 10,
        "active": True,
    }
    if policy:
        for key, value in policy_payload.items():
            setattr(policy, key, value)
        policy.updated_at = now
        resources.append(_resource_action("policy_rule", POLICY_RULE_ID, "updated"))
    else:
        db.add(platform_core.PolicyRule(id=POLICY_RULE_ID, created_at=now, updated_at=now, **policy_payload))
        resources.append(_resource_action("policy_rule", POLICY_RULE_ID, "created"))

    saved = db.get(models.SavedObjectSet, "asset_reliability_high_risk_assets")
    saved_payload = {
        "display_name": "Asset Reliability High Risk Assets",
        "description": "Assets with criticality and degraded reliability posture.",
        "object_type_id": "asset",
        "filters": {"criticality": "high"},
        "owner": "workspace",
    }
    if saved:
        for key, value in saved_payload.items():
            setattr(saved, key, value)
        saved.updated_at = now
        resources.append(_resource_action("saved_object_set", saved.id, "updated"))
    else:
        db.add(models.SavedObjectSet(id="asset_reliability_high_risk_assets", created_at=now, updated_at=now, **saved_payload))
        resources.append(_resource_action("saved_object_set", "asset_reliability_high_risk_assets", "created"))

    layer = db.get(models.MapLayerDefinition, "asset_reliability_risk_layer")
    layer_payload = {
        "display_name": "Asset Reliability Risk Layer",
        "description": "Risk-colored map layer for command-center assets.",
        "object_type_id": "asset",
        "saved_object_set_id": "asset_reliability_high_risk_assets",
        "geometry_field": "geometry",
        "filters": {},
        "style": {"marker_color": "#b43b3b", "marker_size": 12, "risk_colored": True},
        "visible": True,
        "owner": "workspace",
    }
    if layer:
        for key, value in layer_payload.items():
            setattr(layer, key, value)
        layer.updated_at = now
        resources.append(_resource_action("map_layer", layer.id, "updated"))
    else:
        db.add(models.MapLayerDefinition(id="asset_reliability_risk_layer", created_at=now, updated_at=now, **layer_payload))
        resources.append(_resource_action("map_layer", "asset_reliability_risk_layer", "created"))
    db.commit()
    return resources


def _latest_data_contract_run(db: Session) -> Optional[Dict[str, Any]]:
    reliability_ops._ensure_tables(db)
    run = db.query(reliability_ops.DataQualityRun).filter(
        reliability_ops.DataQualityRun.contract_id == DATA_CONTRACT_ID
    ).order_by(reliability_ops.DataQualityRun.created_at.desc()).first()
    return reliability_ops._run_dict(run) if run else None


def _latest_monitor_run(db: Session) -> Optional[Dict[str, Any]]:
    modelops.ModelMonitorRun.__table__.create(bind=db.get_bind(), checkfirst=True)
    run = db.query(modelops.ModelMonitorRun).filter(
        modelops.ModelMonitorRun.monitor_id == MODEL_MONITOR_ID
    ).order_by(modelops.ModelMonitorRun.created_at.desc()).first()
    return modelops._run_dict(run) if run else None


def _latest_report(db: Session) -> Optional[Dict[str, Any]]:
    report = db.query(investigations.InvestigationReport).filter(
        investigations.InvestigationReport.investigation_id == INVESTIGATION_ID
    ).order_by(investigations.InvestigationReport.created_at.desc()).first()
    return investigations._report_dict(report) if report else None


def _scenario_report_payload(db: Session, *, asset_id: str = HIGH_RISK_ASSET_ID) -> Dict[str, Any]:
    summary = _summarize(db, asset_id=asset_id)
    report = summary.get("latest_report")
    pipeline_runs = [
        _pipeline_run_dict(row)
        for row in db.query(models.PipelineRun).order_by(models.PipelineRun.created_at.desc()).limit(12).all()
    ]
    evidence = {
        "asset_id": asset_id,
        "selected_asset_id": (summary.get("selected_asset") or {}).get("id"),
        "selected_work_order_id": (summary.get("selected_work_order") or {}).get("id"),
        "pipeline_run_ids": [row["id"] for row in pipeline_runs],
        "data_contract_status": (summary.get("data_contract") or {}).get("status"),
        "model_monitor_status": (summary.get("model_monitor") or {}).get("status"),
        "approval_ids": [row.get("id") for row in summary.get("approvals", [])],
        "incident_ids": [row.get("id") for row in summary.get("incidents", [])],
        "report_id": (report or {}).get("id"),
        "timeline_ids": [row.get("id") for row in summary.get("timeline", []) if row.get("id")],
    }
    return {
        "scenario_id": SCENARIO_ID,
        "generated_at": _now(),
        "summary": summary,
        "report": report,
        "pipeline_runs": pipeline_runs,
        "evidence": evidence,
    }


def _scenario_report_markdown(payload: Dict[str, Any]) -> str:
    summary = payload.get("summary") or {}
    kpis = summary.get("kpis") or {}
    report = payload.get("report") or {}
    evidence = payload.get("evidence") or {}
    lines = [
        "# Asset Reliability Command Center Report",
        "",
        f"- Scenario: {payload.get('scenario_id')}",
        f"- Generated at: {payload.get('generated_at')}",
        f"- High-risk assets: {kpis.get('high_risk_assets', 0)}",
        f"- Open approvals: {kpis.get('open_approvals', 0)}",
        f"- Open incidents: {kpis.get('open_incidents', 0)}",
        f"- Data contract: {kpis.get('data_contract_status', 'NOT_RUN')}",
        f"- Model monitor: {kpis.get('model_monitor_status', 'NOT_RUN')}",
        "",
        "## Evidence IDs",
        "",
        f"- Asset: {evidence.get('selected_asset_id') or '-'}",
        f"- Work order: {evidence.get('selected_work_order_id') or '-'}",
        f"- Pipeline runs: {', '.join(evidence.get('pipeline_run_ids') or []) or '-'}",
        f"- Approvals: {', '.join(evidence.get('approval_ids') or []) or '-'}",
        f"- Incidents: {', '.join(evidence.get('incident_ids') or []) or '-'}",
        f"- Report: {evidence.get('report_id') or '-'}",
        "",
        "## Narrative",
        "",
        report.get("body") or "No generated report body is available yet.",
    ]
    return "\n".join(lines)


def _risk_findings(db: Session) -> List[Dict[str, Any]]:
    rows = db.query(models.ObjectInstance).filter(models.ObjectInstance.object_type_id == "asset").all()
    findings = []
    for obj in rows:
        risk = decision_intelligence.score_object(db, obj, scorecard_ids=[DECISION_SCORECARD_ID])
        findings.append({"object": _object_dict(obj), "object_id": obj.id, "risk": risk})
    findings.sort(key=lambda item: item["risk"].get("score", 0), reverse=True)
    return findings


def _open_alerts(db: Session) -> List[Dict[str, Any]]:
    ops_control._ensure_tables(db)
    return [
        ops_control._alert_dict(row)
        for row in db.query(ops_control.AlertEvent).filter(ops_control.AlertEvent.status == "OPEN").order_by(ops_control.AlertEvent.created_at.desc()).limit(20).all()
    ]


def _open_approvals(db: Session) -> List[Dict[str, Any]]:
    return [
        _approval_dict(row)
        for row in db.query(models_action.ApprovalRequest).filter(models_action.ApprovalRequest.status == models_action.ApprovalStatus.PENDING.value).order_by(models_action.ApprovalRequest.created_at.desc()).limit(20).all()
    ]


def _incidents(db: Session) -> List[Dict[str, Any]]:
    ops_control._ensure_tables(db)
    return [
        ops_control._incident_dict(row)
        for row in db.query(ops_control.Incident).order_by(ops_control.Incident.updated_at.desc()).limit(20).all()
    ]


def _summarize(db: Session, *, asset_id: str = HIGH_RISK_ASSET_ID) -> Dict[str, Any]:
    asset = db.get(models.ObjectInstance, asset_id)
    work_order = db.get(models.ObjectInstance, DEFAULT_WORK_ORDER_ID)
    risk_findings = _risk_findings(db)
    high_risk_assets = [
        item for item in risk_findings
        if item["risk"].get("band") in {"high", "critical"}
    ]
    data_contract_run = _latest_data_contract_run(db)
    monitor_run = _latest_monitor_run(db)
    alerts = _open_alerts(db)
    approvals = _open_approvals(db)
    incidents = _incidents(db)
    timeline = platform_core._build_timeline(
        db,
        subject_type=None,
        subject_id=None,
        object_type_id="asset" if asset else None,
        object_id=asset_id if asset else None,
        limit=25,
    )
    graph = platform_core._graph_overview(db, 80)
    return {
        "scenario_id": SCENARIO_ID,
        "asset_id": asset_id,
        "maintenance": maintenance_summary(db),
        "kpis": {
            "asset_count": db.query(models.ObjectInstance).filter(models.ObjectInstance.object_type_id == "asset").count(),
            "open_work_orders": len(maintenance_summary(db).get("open_work_orders", [])),
            "high_risk_assets": len(high_risk_assets),
            "open_alerts": len(alerts),
            "open_approvals": len(approvals),
            "open_incidents": sum(1 for item in incidents if item.get("status") != "CLOSED"),
            "data_contract_status": (data_contract_run or {}).get("status", "NOT_RUN"),
            "model_monitor_status": (monitor_run or {}).get("status", "NOT_RUN"),
        },
        "selected_asset": _object_dict(asset),
        "selected_work_order": _object_dict(work_order),
        "risk_findings": risk_findings,
        "high_risk_assets": high_risk_assets,
        "data_contract": data_contract_run,
        "model_monitor": monitor_run,
        "alerts": alerts,
        "approvals": approvals,
        "incidents": incidents,
        "latest_report": _latest_report(db),
        "timeline": timeline.get("timeline", []),
        "graph": graph,
    }


def _workflow_state(db: Session, *, asset_id: str = HIGH_RISK_ASSET_ID) -> Dict[str, Any]:
    summary = _summarize(db, asset_id=asset_id)
    try:
        from . import imports_ops, ontology_generator, pipeline_builder_ops
        latest_import = db.query(imports_ops.ImportJob).order_by(imports_ops.ImportJob.updated_at.desc()).first()
        latest_draft = db.query(ontology_generator.OntologyGeneratorDraft).order_by(ontology_generator.OntologyGeneratorDraft.updated_at.desc()).first()
        latest_graph = db.query(pipeline_builder_ops.PipelineBuilderGraph).order_by(pipeline_builder_ops.PipelineBuilderGraph.updated_at.desc()).first()
    except Exception:
        latest_import = latest_draft = latest_graph = None
    latest_run = db.query(models.PipelineRun).order_by(models.PipelineRun.created_at.desc()).first()
    latest_approval = db.query(models_action.ApprovalRequest).order_by(models_action.ApprovalRequest.created_at.desc()).first()
    report = summary.get("latest_report")
    selected_asset = summary.get("selected_asset") or {}
    steps = [
        {
            "id": "bootstrap",
            "label": "Start with sample data",
            "status": "complete" if selected_asset else "active",
            "evidence_id": selected_asset.get("id"),
            "href": "/workspace/command-center",
        },
        {
            "id": "import",
            "label": "Import or connect data",
            "status": "complete" if latest_import else "available",
            "evidence_id": getattr(latest_import, "id", None),
            "href": "/workspace/imports",
        },
        {
            "id": "ontology",
            "label": "Generate ontology",
            "status": "complete" if latest_draft or selected_asset else "available",
            "evidence_id": getattr(latest_draft, "object_type_id", None) or selected_asset.get("object_type_id"),
            "href": "/workspace/ontology",
        },
        {
            "id": "pipeline",
            "label": "Deliver pipeline",
            "status": "complete" if latest_run else "available",
            "evidence_id": getattr(latest_run, "id", None),
            "href": "/workspace/pipeline",
            "graph_id": getattr(latest_graph, "id", None),
        },
        {
            "id": "triage",
            "label": "Run reliability triage",
            "status": "complete" if summary.get("approvals") else ("available" if selected_asset else "blocked"),
            "evidence_id": (summary.get("approvals") or [{}])[0].get("id") if summary.get("approvals") else None,
            "href": "/workspace/command-center",
        },
        {
            "id": "approval",
            "label": "Approve governed action",
            "status": "complete" if latest_approval and latest_approval.status != models_action.ApprovalStatus.PENDING.value else ("active" if latest_approval else "available"),
            "evidence_id": getattr(latest_approval, "id", None),
            "href": "/workspace/command-center",
        },
        {
            "id": "report",
            "label": "Export proof report",
            "status": "complete" if report else "available",
            "evidence_id": (report or {}).get("id"),
            "href": "/scenarios/asset-reliability/report?format=markdown",
        },
    ]
    blocked = next((step for step in steps if step["status"] == "blocked"), None)
    active = next((step for step in steps if step["status"] == "active"), None)
    next_step = active or next((step for step in steps if step["status"] == "available"), None)
    return {
        "scenario_id": SCENARIO_ID,
        "asset_id": asset_id,
        "current_step": (next_step or steps[-1])["id"],
        "completed_steps": [step["id"] for step in steps if step["status"] == "complete"],
        "blocked_step": blocked,
        "next_action": next_step,
        "steps": steps,
        "evidence_links": [
            {"kind": "asset", "id": selected_asset.get("id"), "href": "/workspace/object-explorer?legacy=1"},
            {"kind": "import_job", "id": getattr(latest_import, "id", None), "href": "/workspace/imports"},
            {"kind": "ontology_object_type", "id": selected_asset.get("object_type_id"), "href": "/workspace/ontology"},
            {"kind": "pipeline_graph", "id": getattr(latest_graph, "id", None), "href": "/workspace/pipeline"},
            {"kind": "pipeline_run", "id": getattr(latest_run, "id", None), "href": "/workspace/pipeline"},
            {"kind": "approval", "id": getattr(latest_approval, "id", None), "href": "/workspace/command-center"},
            {"kind": "report", "id": (report or {}).get("id"), "href": "/scenarios/asset-reliability/report?format=markdown"},
        ],
        "summary": summary,
    }


def _step_status(workflow: Dict[str, Any], step_id: str) -> str:
    for step in workflow.get("steps", []):
        if step.get("id") == step_id:
            return str(step.get("status") or "available")
    return "available"


def _command_center_ui_state(db: Session, *, asset_id: str = HIGH_RISK_ASSET_ID) -> Dict[str, Any]:
    workflow = _workflow_state(db, asset_id=asset_id)
    summary = workflow.get("summary") or {}
    kpis = summary.get("kpis") or {}
    high_risk_assets = summary.get("high_risk_assets") or []
    top_risk = high_risk_assets[0] if high_risk_assets else ((summary.get("risk_findings") or [{}])[0] if summary.get("risk_findings") else {})
    top_risk_score = top_risk.get("risk") or {}
    selected_asset = summary.get("selected_asset") or {}
    selected_work_order = summary.get("selected_work_order") or {}
    approvals = summary.get("approvals") or []
    incidents = summary.get("incidents") or []
    report = summary.get("latest_report") or {}
    data_contract = summary.get("data_contract") or {}
    model_monitor = summary.get("model_monitor") or {}
    warnings: List[Dict[str, Any]] = []
    if not selected_asset:
        warnings.append({"id": "sample_data_missing", "message": "Start with sample data to populate the evaluator workflow.", "severity": "info"})
    if data_contract.get("status") in {"WARN", "FAIL"}:
        warnings.append({"id": "data_quality", "message": f"Data contract status is {data_contract.get('status')}.", "severity": "warn"})
    if model_monitor.get("status") in {"WARN", "FAIL"}:
        warnings.append({"id": "model_monitor", "message": f"Model monitor status is {model_monitor.get('status')}.", "severity": "warn"})
    if approvals and approvals[0].get("status") == "PENDING":
        warnings.append({"id": "approval_pending", "message": "A governed action is staged and waiting for approval.", "severity": "high"})
    risk_drivers = top_risk_score.get("drivers") or []
    recommended_actions = top_risk_score.get("recommended_actions") or []
    recommendation = (
        recommended_actions[0]
        if recommended_actions
        else "Escalate the work order and keep the incident open until reliability signals return to baseline."
    )
    evaluator_summary = {
        "title": "Reliability decision summary",
        "decision": "Approval required" if approvals else ("Run triage" if selected_asset else "Bootstrap sample data"),
        "recommendation": recommendation,
        "why": top_risk_score.get("explanation") or "The workflow combines pipeline evidence, ontology objects, risk scoring, checks, approvals, and report output.",
        "selected_asset": selected_asset.get("id"),
        "risk_band": top_risk_score.get("band", "not_scored"),
        "risk_score": top_risk_score.get("score"),
        "drivers": risk_drivers,
        "next_action": workflow.get("next_action"),
    }
    sections = [
        {
            "id": "start",
            "title": "Start or import data",
            "status": _step_status(workflow, "bootstrap"),
            "description": "Load the deterministic asset reliability scenario or bring in your own records.",
            "metrics": {"asset_count": kpis.get("asset_count", 0), "open_work_orders": kpis.get("open_work_orders", 0)},
            "rows": [{"asset": selected_asset.get("id"), "work_order": selected_work_order.get("id"), "status": selected_asset.get("properties", {}).get("status")}],
            "href": "/workspace/imports",
        },
        {
            "id": "risk",
            "title": "Risk and checks",
            "status": "complete" if top_risk_score else "available",
            "description": "Risk, data quality, and model monitor evidence used by the triage recommendation.",
            "metrics": {
                "risk_band": top_risk_score.get("band", "not_scored"),
                "risk_score": top_risk_score.get("score", 0),
                "data_contract": kpis.get("data_contract_status", "NOT_RUN"),
                "model_monitor": kpis.get("model_monitor_status", "NOT_RUN"),
            },
            "rows": [
                {"check": "Risk explanation", "status": top_risk_score.get("band", "not_scored"), "detail": top_risk_score.get("explanation")},
                {"check": "Data contract", "status": data_contract.get("status", "NOT_RUN"), "detail": data_contract.get("summary", {})},
                {"check": "Model monitor", "status": model_monitor.get("status", "NOT_RUN"), "detail": model_monitor.get("alerts", [])},
            ],
            "href": "/workspace/command-center",
        },
        {
            "id": "approval",
            "title": "Approval and action",
            "status": _step_status(workflow, "approval"),
            "description": "High-risk operational changes are staged for human approval instead of mutating directly.",
            "metrics": {"open_approvals": kpis.get("open_approvals", 0), "open_incidents": kpis.get("open_incidents", 0)},
            "rows": approvals[:6],
            "href": "/workspace/command-center",
        },
        {
            "id": "report",
            "title": "Incident and report",
            "status": _step_status(workflow, "report"),
            "description": "Export the decision narrative with linked evidence IDs.",
            "metrics": {"incident_count": len(incidents), "latest_report": report.get("id")},
            "rows": incidents[:6],
            "href": "/scenarios/asset-reliability/report?format=markdown",
        },
    ]
    return {
        "summary": {
            "scenario_id": SCENARIO_ID,
            "asset_id": asset_id,
            "current_step": workflow.get("current_step"),
            "completed_step_count": len(workflow.get("completed_steps") or []),
            "kpis": kpis,
        },
        "primary_actions": [
            {"id": "bootstrap", "label": "Start with sample data", "method": "POST", "path": "/project/demo/bootstrap"},
            {"id": "triage", "label": "Run reliability triage", "method": "POST", "path": "/scenarios/asset-reliability/run-triage"},
            {"id": "report", "label": "Export proof report", "method": "GET", "path": "/scenarios/asset-reliability/report?format=markdown"},
        ],
        "sections": sections,
        "evidence_links": workflow.get("evidence_links", []),
        "warnings": warnings,
        "last_updated": _now(),
        "workflow": workflow,
        "evaluator_summary": evaluator_summary,
    }


def _ensure_investigation(db: Session) -> investigations.InvestigationWorkspace:
    investigations._ensure_tables(db)
    workspace = db.get(investigations.InvestigationWorkspace, INVESTIGATION_ID)
    object_refs = [
        {"object_type_id": "asset", "object_id": HIGH_RISK_ASSET_ID},
        {"object_type_id": "work_order", "object_id": DEFAULT_WORK_ORDER_ID},
    ]
    now = _now()
    if workspace:
        workspace.display_name = "Asset Reliability Incident Review"
        workspace.description = "Command-center investigation for Line 4 Pump reliability risk."
        workspace.object_refs = object_refs
        workspace.incident_ids = sorted(set((workspace.incident_ids or []) + ["asset_reliability_incident"]))
        workspace.status = "ACTIVE"
        workspace.updated_at = now
    else:
        workspace = investigations.InvestigationWorkspace(
            id=INVESTIGATION_ID,
            display_name="Asset Reliability Incident Review",
            description="Command-center investigation for Line 4 Pump reliability risk.",
            owner="workspace",
            status="ACTIVE",
            object_refs=object_refs,
            alert_ids=[],
            incident_ids=["asset_reliability_incident"],
            created_at=now,
            updated_at=now,
        )
        db.add(workspace)
    db.commit()
    return workspace


def _add_investigation_evidence(db: Session, *, title: str, payload: Dict[str, Any], tags: List[str]) -> Dict[str, Any]:
    investigations._ensure_tables(db)
    _ensure_investigation(db)
    now = _now()
    evidence = investigations.EvidenceItem(
        id=_new_id("evidence"),
        investigation_id=INVESTIGATION_ID,
        title=title,
        source="asset_reliability_scenario",
        object_refs=[{"object_type_id": "asset", "object_id": HIGH_RISK_ASSET_ID}, {"object_type_id": "work_order", "object_id": DEFAULT_WORK_ORDER_ID}],
        payload=payload,
        tags=tags,
        created_at=now,
    )
    db.add(evidence)
    db.commit()
    return investigations._evidence_dict(evidence)


def _ensure_incident(db: Session, *, alert_ids: Optional[List[str]] = None, approval_ids: Optional[List[str]] = None) -> Dict[str, Any]:
    ops_control._ensure_tables(db)
    incident = db.get(ops_control.Incident, "asset_reliability_incident")
    linked_objects = [
        {"object_type_id": "asset", "object_id": HIGH_RISK_ASSET_ID},
        {"object_type_id": "work_order", "object_id": DEFAULT_WORK_ORDER_ID},
    ]
    if not incident:
        incident = ops_control.create_incident_inline(
            db,
            incident_id="asset_reliability_incident",
            display_name="Line 4 Pump reliability incident",
            description="High vibration, degraded status, and model drift indicate production risk.",
            severity="high",
            owner="maintenance-ops",
            linked_objects=linked_objects,
            alert_ids=alert_ids or [],
            approval_ids=approval_ids or [],
            actor="asset_reliability_scenario",
        )
    else:
        incident.linked_objects = linked_objects
        incident.alert_ids = sorted(set((incident.alert_ids or []) + (alert_ids or [])))
        incident.approval_ids = sorted(set((incident.approval_ids or []) + (approval_ids or [])))
        incident.status = "OPEN"
        incident.updated_at = _now()
        incident.timeline = (incident.timeline or []) + [{"at": _now(), "actor": "asset_reliability_scenario", "event_type": "incident.updated", "status": incident.status}]
    db.commit()
    db.refresh(incident)
    return ops_control._incident_dict(incident)


def _stage_escalation_approval(db: Session, *, actor: str, work_order_id: str, reason: str) -> Dict[str, Any]:
    parameters = {"work_order_id": work_order_id, "reason": reason}
    existing = db.query(models_action.ApprovalRequest).filter(
        models_action.ApprovalRequest.action_type_id == "escalate_work_order",
        models_action.ApprovalRequest.status == models_action.ApprovalStatus.PENDING.value,
    ).all()
    for row in existing:
        if row.parameters == parameters:
            return _approval_dict(row)
    approval = models_action.ApprovalRequest(
        id=str(uuid.uuid4()),
        project_id="default",
        action_type_id="escalate_work_order",
        requester=actor,
        parameters=parameters,
        status=models_action.ApprovalStatus.PENDING.value,
    )
    db.add(approval)
    create_audit_log(
        db,
        actor=actor,
        event_type="scenario.approval.requested",
        subject_type="approval_request",
        subject_id=approval.id,
        payload={"action_type_id": approval.action_type_id, "parameters": parameters},
    )
    ops_control.record_ops_event(
        db,
        source="scenario",
        event_type="scenario.approval.requested",
        severity="high",
        title="Approval requested for Line 4 Pump escalation",
        subject_type="approval_request",
        subject_id=approval.id,
        object_type_id="work_order",
        object_id=work_order_id,
        payload={"action_type_id": approval.action_type_id, "parameters": parameters},
    )
    db.commit()
    return _approval_dict(approval)


def _create_agent_recommendation(
    db: Session,
    *,
    actor: str,
    asset_id: str,
    work_order_id: str,
    risk: Dict[str, Any],
    data_contract_run: Dict[str, Any],
    monitor_run: Dict[str, Any],
    policy_decision: Dict[str, Any],
) -> Dict[str, Any]:
    prompt = f"Triage asset {asset_id} and work order {work_order_id}."
    recommendation = (
        "Escalate the urgent pump work order, dispatch an available pump technician, "
        "and keep the incident open until vibration and temperature return to baseline."
    )
    proposed_action = {
        "action_type_id": "escalate_work_order",
        "parameters": {
            "work_order_id": work_order_id,
            "reason": risk.get("explanation") or recommendation,
        },
        "requires_approval": True,
        "policy_decision": policy_decision.get("decision"),
    }
    session = models.AgentSession(
        id=_new_id("agent_session"),
        agent_id="maintenance_ops_agent",
        user_prompt=prompt,
        status="COMPLETED",
        context={
            "asset_id": asset_id,
            "work_order_id": work_order_id,
            "risk": risk,
            "data_contract": data_contract_run,
            "model_monitor": monitor_run,
            "citations": [
                {"type": "decision_risk", "id": DECISION_SCORECARD_ID},
                {"type": "data_contract_run", "id": data_contract_run.get("id")},
                {"type": "model_monitor_run", "id": monitor_run.get("id")},
                {"type": "policy_decision", "id": policy_decision.get("id")},
            ],
        },
        plan={
            "recommendation": recommendation,
            "tool_trace": [
                "score_asset_risk",
                "run_data_contract",
                "run_model_monitor",
                "evaluate_policy",
                "stage_approval",
                "update_incident",
                "draft_report",
            ],
        },
        proposed_actions=[proposed_action],
        created_at=_now(),
        completed_at=_now(),
    )
    db.add(session)
    create_audit_log(db, actor=actor, event_type="scenario.agent.recommendation.created", subject_type="agent_session", subject_id=session.id, payload=session.plan)
    ops_control.record_ops_event(
        db,
        source="agent",
        event_type="scenario.agent.recommendation.created",
        severity="high",
        title="Agent recommended reliability escalation",
        subject_type="agent_session",
        subject_id=session.id,
        object_type_id="asset",
        object_id=asset_id,
        payload={"proposed_actions": [proposed_action], "recommendation": recommendation},
    )
    db.commit()
    return _agent_session_dict(session)


def _validation_dashboard(db: Session, *, include_summary: bool = True) -> Dict[str, Any]:
    root = Path(__file__).resolve().parents[2]
    matrix_path = root / "foundry-docs" / "VALIDATION_MATRIX.md"
    rows: List[Dict[str, str]] = []
    if matrix_path.exists():
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
    status_counts = dict(Counter(row["status"] for row in rows))
    priority_gaps = [row for row in rows if row["priority"] in {"P0", "P1"} and row["status"] in {"PARTIAL", "MISSING"}]
    return {
        "matrix_path": str(matrix_path),
        "row_count": len(rows),
        "status_counts": status_counts,
        "priority_gaps": priority_gaps,
        "rows": rows,
        "scenario_summary": _summarize(db) if include_summary else None,
    }


@router.post("/scenarios/asset-reliability/bootstrap")
def bootstrap_asset_reliability(body: ScenarioBootstrapRequest = ScenarioBootstrapRequest(), db: Session = Depends(get_db)):
    resources: List[Dict[str, str]] = []
    maintenance = bootstrap_maintenance_copilot(db, actor=body.actor)
    resources.extend(maintenance.get("resources", []))
    resources.extend(_upsert_asset_reliability_data(db))
    resources.extend(_upsert_decision_resources(db))
    resources.append(_upsert_data_contract(db))
    resources.extend(_upsert_model_lifecycle(db))
    resources.extend(_upsert_ops_policy_and_map(db))

    pipeline_runs: List[Dict[str, Any]] = []
    if body.run_pipelines:
        for pipeline_id in SCENARIO_PIPELINES:
            pipeline_runs.append(_run_pipeline_inline(db, pipeline_id, actor=body.actor))
        resources.extend(_ensure_links(db))

    decision_result = decision_intelligence.evaluate_decision_scope(
        decision_intelligence.DecisionEvaluateRequest(
            object_type_id="asset",
            scorecard_ids=[DECISION_SCORECARD_ID],
            persist_run=True,
            limit=50,
        ),
        db,
    )
    if body.run_checks:
        data_contract_run = reliability_ops.run_data_contract_inline(db, contract_id=DATA_CONTRACT_ID)
        db.commit()
        monitor_run = modelops.run_monitor(MODEL_MONITOR_ID, modelops.ModelMonitorRunRequest(current_asset_id=SIGNAL_CURRENT_ASSET_ID, actual_field="actual_failure"), db)
    else:
        data_contract_run = _latest_data_contract_run(db) or {"status": "NOT_RUN", "summary": {}}
        monitor_run = _latest_monitor_run(db) or {"status": "NOT_RUN", "alerts": []}

    decision_event = ops_control.record_ops_event(
        db,
        source="decision",
        event_type="asset_reliability.risk.detected",
        severity="critical",
        title="Critical reliability risk detected for Line 4 Pump",
        message="Degraded status, high vibration, and elevated model risk require review.",
        subject_type="object",
        subject_id=HIGH_RISK_ASSET_ID,
        object_type_id="asset",
        object_id=HIGH_RISK_ASSET_ID,
        payload={"scorecard_id": DECISION_SCORECARD_ID},
        evaluate_alerts=True,
    )
    db.commit()
    _ensure_investigation(db)
    incident = _ensure_incident(db, alert_ids=[alert["id"] for alert in _open_alerts(db)])
    _add_investigation_evidence(db, title="Bootstrap reliability evidence", payload={"decision_event_id": decision_event.id, "data_contract_status": data_contract_run["status"], "monitor_status": monitor_run["status"]}, tags=["bootstrap", "risk"])
    report = investigations.create_report(INVESTIGATION_ID, investigations.ReportRequest(title="Asset Reliability Bootstrap Report"), db)

    return {
        "scenario_id": SCENARIO_ID,
        "resources": resources,
        "pipeline_runs": pipeline_runs,
        "decision_run": decision_result,
        "risk_findings": decision_result.get("findings", []),
        "data_contract_run": data_contract_run,
        "model_monitor_run": monitor_run,
        "alerts": _open_alerts(db),
        "incident": incident,
        "report": report,
        "summary": _summarize(db),
    }


@router.get("/scenarios/asset-reliability/summary")
def asset_reliability_summary(asset_id: str = Query(HIGH_RISK_ASSET_ID), db: Session = Depends(get_db)):
    return _summarize(db, asset_id=asset_id)


@router.get("/scenarios/asset-reliability/workflow-state")
def asset_reliability_workflow_state(asset_id: str = Query(HIGH_RISK_ASSET_ID), db: Session = Depends(get_db)):
    return _workflow_state(db, asset_id=asset_id)


@router.get("/ui-state/command-center")
def command_center_ui_state(asset_id: str = Query(HIGH_RISK_ASSET_ID), db: Session = Depends(get_db)):
    return _command_center_ui_state(db, asset_id=asset_id)


@router.post("/project/demo/bootstrap")
def bootstrap_project_demo(body: ProjectDemoRequest = ProjectDemoRequest(), db: Session = Depends(get_db)):
    result = bootstrap_asset_reliability(
        ScenarioBootstrapRequest(actor=body.actor, run_pipelines=body.run_pipelines, run_checks=body.run_checks),
        db,
    )
    return {
        "status": "READY",
        "mode": "idempotent_bootstrap",
        "scenario": result,
        "workflow_state": _workflow_state(db),
        "ui_state": _command_center_ui_state(db),
    }


@router.post("/project/demo/reset")
def reset_project_demo(body: ProjectDemoRequest = ProjectDemoRequest(), db: Session = Depends(get_db)):
    result = bootstrap_asset_reliability(
        ScenarioBootstrapRequest(actor=body.actor, run_pipelines=body.run_pipelines, run_checks=body.run_checks),
        db,
    )
    return {
        "status": "READY",
        "mode": "idempotent_reset",
        "note": "Local demo reset is non-destructive: it re-upserts the sample workflow and leaves unrelated user data intact.",
        "scenario": result,
        "workflow_state": _workflow_state(db),
        "ui_state": _command_center_ui_state(db),
    }


@router.post("/scenarios/asset-reliability/run-triage")
def run_asset_reliability_triage(body: ScenarioTriageRequest = ScenarioTriageRequest(), db: Session = Depends(get_db)):
    asset = db.get(models.ObjectInstance, body.asset_id)
    if not asset:
        raise HTTPException(status_code=404, detail=f"Asset '{body.asset_id}' not found. Run /scenarios/asset-reliability/bootstrap first.")
    if not db.get(models.ObjectInstance, body.work_order_id):
        raise HTTPException(status_code=404, detail=f"Work order '{body.work_order_id}' not found")
    decision_result = decision_intelligence.evaluate_decision_scope(
        decision_intelligence.DecisionEvaluateRequest(
            object_type_id="asset",
            object_ids=[body.asset_id],
            scorecard_ids=[DECISION_SCORECARD_ID],
            persist_run=True,
        ),
        db,
    )
    risk = decision_result["findings"][0]["risk"] if decision_result.get("findings") else decision_intelligence.score_object(db, asset, scorecard_ids=[DECISION_SCORECARD_ID])
    data_contract_run = reliability_ops.run_data_contract_inline(db, contract_id=DATA_CONTRACT_ID)
    db.commit()
    monitor_run = modelops.run_monitor(MODEL_MONITOR_ID, modelops.ModelMonitorRunRequest(current_asset_id=SIGNAL_CURRENT_ASSET_ID, actual_field="actual_failure"), db)
    policy_decision = platform_core.evaluate_policy(
        platform_core.PolicyEvaluateRequest(
            principal=body.actor,
            action="escalate_work_order",
            resource_kind="action",
            resource_id="escalate_work_order",
            object_type_id="work_order",
            purpose="asset_reliability_triage",
            context={"asset_id": body.asset_id, "work_order_id": body.work_order_id, "risk": risk},
        ),
        db,
    )
    reason = body.reason or risk.get("explanation") or "Critical reliability risk detected."
    agent_session = _create_agent_recommendation(
        db,
        actor=body.actor,
        asset_id=body.asset_id,
        work_order_id=body.work_order_id,
        risk=risk,
        data_contract_run=data_contract_run,
        monitor_run=monitor_run,
        policy_decision=policy_decision,
    )
    approval = _stage_escalation_approval(db, actor=body.actor, work_order_id=body.work_order_id, reason=reason)
    incident = _ensure_incident(db, alert_ids=[alert["id"] for alert in _open_alerts(db)], approval_ids=[approval["id"]])
    evidence = _add_investigation_evidence(
        db,
        title="Triage run evidence",
        payload={"risk": risk, "data_contract_run": data_contract_run, "model_monitor_run": monitor_run, "policy_decision": policy_decision, "approval": approval, "agent_session": agent_session},
        tags=["triage", "agent", "approval"],
    )
    report = investigations.create_report(INVESTIGATION_ID, investigations.ReportRequest(title="Asset Reliability Triage Report"), db)
    return {
        "scenario_id": SCENARIO_ID,
        "status": "APPROVAL_REQUIRED",
        "asset_id": body.asset_id,
        "work_order_id": body.work_order_id,
        "decision_run": decision_result,
        "risk": risk,
        "data_contract_run": data_contract_run,
        "model_monitor_run": monitor_run,
        "policy_decision": policy_decision,
        "agent_session": agent_session,
        "approval": approval,
        "incident": incident,
        "evidence": evidence,
        "report": report,
        "summary": _summarize(db, asset_id=body.asset_id),
    }


@router.get("/scenarios/asset-reliability/validation-dashboard")
def asset_reliability_validation_dashboard(db: Session = Depends(get_db)):
    return _validation_dashboard(db)


@router.get("/scenarios/asset-reliability/report")
def asset_reliability_report(
    asset_id: str = Query(HIGH_RISK_ASSET_ID),
    format: str = Query("json", pattern="^(json|markdown)$"),
    actor: str = Query("workspace"),
    db: Session = Depends(get_db),
):
    payload = _scenario_report_payload(db, asset_id=asset_id)
    create_audit_log(
        db,
        actor=actor,
        event_type="scenario.report.exported",
        subject_type="scenario",
        subject_id=SCENARIO_ID,
        payload={"asset_id": asset_id, "format": format, "evidence": payload["evidence"]},
    )
    ops_control.record_ops_event(
        db,
        source="scenario",
        event_type="scenario.report.exported",
        severity="info",
        title="Asset reliability report exported",
        subject_type="scenario",
        subject_id=SCENARIO_ID,
        object_type_id="asset",
        object_id=asset_id,
        payload={"format": format, "evidence": payload["evidence"]},
    )
    db.commit()
    if format == "markdown":
        return PlainTextResponse(_scenario_report_markdown(payload), media_type="text/markdown")
    return payload

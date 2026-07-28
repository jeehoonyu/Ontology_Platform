"""
Local deterministic operational control plane.

This module provides an append-only operational event stream, alert rules,
incidents, runbooks, notifications, and SLA metadata. It is intentionally
bounded: runbook steps call local deterministic APIs and high-impact actions are
staged as approvals instead of mutating objects directly.
"""
from __future__ import annotations

import time
import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import Boolean, Integer, JSON, String
from sqlalchemy.orm import Mapped, Session, mapped_column

from . import models, models_action, production_auth, semantic_scope
from .database import Base, get_db

router = APIRouter(tags=["ops_control"])


SEVERITY_RANK = {"info": 0, "low": 1, "medium": 2, "warn": 2, "high": 3, "critical": 4}


def _now() -> int:
    return int(time.time())


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


class OpsEvent(Base):
    __tablename__ = "ops_events"

    id: Mapped[str] = mapped_column(String, primary_key=True, index=True)
    project_id: Mapped[str] = mapped_column(String, default="default", server_default="default", index=True)
    source: Mapped[str] = mapped_column(String, index=True)
    event_type: Mapped[str] = mapped_column(String, index=True)
    severity: Mapped[str] = mapped_column(String, default="info", index=True)
    status: Mapped[str] = mapped_column(String, default="OPEN", index=True)
    title: Mapped[str] = mapped_column(String)
    message: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    subject_type: Mapped[Optional[str]] = mapped_column(String, nullable=True, index=True)
    subject_id: Mapped[Optional[str]] = mapped_column(String, nullable=True, index=True)
    object_type_id: Mapped[Optional[str]] = mapped_column(String, nullable=True, index=True)
    object_id: Mapped[Optional[str]] = mapped_column(String, nullable=True, index=True)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[int] = mapped_column(Integer, index=True)


class AlertRule(Base):
    __tablename__ = "ops_alert_rules"

    id: Mapped[str] = mapped_column(String, primary_key=True, index=True)
    project_id: Mapped[str] = mapped_column(String, default="default", server_default="default", index=True)
    display_name: Mapped[str] = mapped_column(String)
    description: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    source: Mapped[Optional[str]] = mapped_column(String, nullable=True, index=True)
    event_type: Mapped[Optional[str]] = mapped_column(String, nullable=True, index=True)
    min_severity: Mapped[str] = mapped_column(String, default="high")
    subject_type: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    object_type_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    expression: Mapped[dict] = mapped_column(JSON, default=dict)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[int] = mapped_column(Integer)
    updated_at: Mapped[int] = mapped_column(Integer)


class AlertEvent(Base):
    __tablename__ = "ops_alert_events"

    id: Mapped[str] = mapped_column(String, primary_key=True, index=True)
    project_id: Mapped[str] = mapped_column(String, default="default", server_default="default", index=True)
    rule_id: Mapped[str] = mapped_column(String, index=True)
    event_id: Mapped[str] = mapped_column(String, index=True)
    source: Mapped[str] = mapped_column(String, index=True)
    severity: Mapped[str] = mapped_column(String, default="high", index=True)
    status: Mapped[str] = mapped_column(String, default="OPEN", index=True)
    title: Mapped[str] = mapped_column(String)
    message: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    subject_type: Mapped[Optional[str]] = mapped_column(String, nullable=True, index=True)
    subject_id: Mapped[Optional[str]] = mapped_column(String, nullable=True, index=True)
    object_type_id: Mapped[Optional[str]] = mapped_column(String, nullable=True, index=True)
    object_id: Mapped[Optional[str]] = mapped_column(String, nullable=True, index=True)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[int] = mapped_column(Integer)
    updated_at: Mapped[int] = mapped_column(Integer)


class Incident(Base):
    __tablename__ = "ops_incidents"

    id: Mapped[str] = mapped_column(String, primary_key=True, index=True)
    project_id: Mapped[str] = mapped_column(String, default="default", server_default="default", index=True)
    display_name: Mapped[str] = mapped_column(String)
    description: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    severity: Mapped[str] = mapped_column(String, default="medium", index=True)
    status: Mapped[str] = mapped_column(String, default="OPEN", index=True)
    owner: Mapped[Optional[str]] = mapped_column(String, nullable=True, index=True)
    linked_objects: Mapped[list] = mapped_column(JSON, default=list)
    alert_ids: Mapped[list] = mapped_column(JSON, default=list)
    approval_ids: Mapped[list] = mapped_column(JSON, default=list)
    runbook_execution_ids: Mapped[list] = mapped_column(JSON, default=list)
    timeline: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[int] = mapped_column(Integer)
    updated_at: Mapped[int] = mapped_column(Integer)


class Runbook(Base):
    __tablename__ = "ops_runbooks"

    id: Mapped[str] = mapped_column(String, primary_key=True, index=True)
    project_id: Mapped[str] = mapped_column(String, default="default", server_default="default", index=True)
    display_name: Mapped[str] = mapped_column(String)
    description: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    steps: Mapped[list] = mapped_column(JSON, default=list)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[int] = mapped_column(Integer)
    updated_at: Mapped[int] = mapped_column(Integer)


class RunbookExecution(Base):
    __tablename__ = "ops_runbook_executions"

    id: Mapped[str] = mapped_column(String, primary_key=True, index=True)
    project_id: Mapped[str] = mapped_column(String, default="default", server_default="default", index=True)
    runbook_id: Mapped[str] = mapped_column(String, index=True)
    incident_id: Mapped[Optional[str]] = mapped_column(String, nullable=True, index=True)
    actor: Mapped[str] = mapped_column(String, default="workspace")
    status: Mapped[str] = mapped_column(String, default="RUNNING", index=True)
    inputs: Mapped[dict] = mapped_column(JSON, default=dict)
    step_results: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[int] = mapped_column(Integer)
    completed_at: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)


class OpsNotification(Base):
    __tablename__ = "ops_notifications"

    id: Mapped[str] = mapped_column(String, primary_key=True, index=True)
    project_id: Mapped[str] = mapped_column(String, default="default", server_default="default", index=True)
    recipient: Mapped[str] = mapped_column(String, default="workspace", index=True)
    severity: Mapped[str] = mapped_column(String, default="info", index=True)
    title: Mapped[str] = mapped_column(String)
    message: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    source: Mapped[str] = mapped_column(String, default="ops", index=True)
    subject_type: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    subject_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    status: Mapped[str] = mapped_column(String, default="UNREAD", index=True)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[int] = mapped_column(Integer)
    acknowledged_at: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)


class OpsSlaPolicy(Base):
    __tablename__ = "ops_sla_policies"

    id: Mapped[str] = mapped_column(String, primary_key=True, index=True)
    project_id: Mapped[str] = mapped_column(String, default="default", server_default="default", index=True)
    display_name: Mapped[str] = mapped_column(String)
    scope: Mapped[dict] = mapped_column(JSON, default=dict)
    thresholds: Mapped[dict] = mapped_column(JSON, default=dict)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[int] = mapped_column(Integer)
    updated_at: Mapped[int] = mapped_column(Integer)


class OpsEventIngest(BaseModel):
    project_id: str = "default"
    source: str
    event_type: str
    severity: str = "info"
    status: str = "OPEN"
    title: str
    message: Optional[str] = None
    subject_type: Optional[str] = None
    subject_id: Optional[str] = None
    object_type_id: Optional[str] = None
    object_id: Optional[str] = None
    payload: Dict[str, Any] = Field(default_factory=dict)


class AlertRuleCreate(BaseModel):
    id: Optional[str] = None
    project_id: str = "default"
    display_name: str
    description: Optional[str] = None
    source: Optional[str] = None
    event_type: Optional[str] = None
    min_severity: str = "high"
    subject_type: Optional[str] = None
    object_type_id: Optional[str] = None
    expression: Dict[str, Any] = Field(default_factory=dict)
    active: bool = True


class AlertRulePatch(BaseModel):
    display_name: Optional[str] = None
    description: Optional[str] = None
    source: Optional[str] = None
    event_type: Optional[str] = None
    min_severity: Optional[str] = None
    subject_type: Optional[str] = None
    object_type_id: Optional[str] = None
    expression: Optional[Dict[str, Any]] = None
    active: Optional[bool] = None


class AlertEvaluateRequest(BaseModel):
    source: Optional[str] = None
    event_type: Optional[str] = None
    status: Optional[str] = None
    limit: int = 500


class IncidentCreate(BaseModel):
    id: Optional[str] = None
    project_id: str = "default"
    display_name: str
    description: Optional[str] = None
    severity: str = "medium"
    status: str = "OPEN"
    owner: Optional[str] = None
    linked_objects: List[Dict[str, Any]] = Field(default_factory=list)
    alert_ids: List[str] = Field(default_factory=list)
    approval_ids: List[str] = Field(default_factory=list)


class IncidentPatch(BaseModel):
    display_name: Optional[str] = None
    description: Optional[str] = None
    severity: Optional[str] = None
    status: Optional[str] = None
    owner: Optional[str] = None


class IncidentLinkObject(BaseModel):
    object_type_id: str
    object_id: str
    label: Optional[str] = None
    reason: Optional[str] = None


class RunbookCreate(BaseModel):
    id: Optional[str] = None
    project_id: str = "default"
    display_name: str
    description: Optional[str] = None
    steps: List[Dict[str, Any]] = Field(default_factory=list)
    enabled: bool = True


class RunbookExecutionRequest(BaseModel):
    incident_id: Optional[str] = None
    inputs: Dict[str, Any] = Field(default_factory=dict)
    actor: str = "workspace"


def _audit(db: Session, event_type: str, subject_type: str, subject_id: str, payload: Dict[str, Any]) -> None:
    db.add(models_action.AuditLog(
        id=uuid.uuid4().hex,
        actor="ops",
        event_type=event_type,
        subject_type=subject_type,
        subject_id=subject_id,
        payload=payload,
    ))


def _event_dict(event: OpsEvent) -> Dict[str, Any]:
    return {
        "id": event.id,
        "project_id": event.project_id,
        "source": event.source,
        "event_type": event.event_type,
        "severity": event.severity,
        "status": event.status,
        "title": event.title,
        "message": event.message,
        "subject_type": event.subject_type,
        "subject_id": event.subject_id,
        "object_type_id": event.object_type_id,
        "object_id": event.object_id,
        "payload": event.payload or {},
        "created_at": event.created_at,
    }


def _rule_dict(rule: AlertRule) -> Dict[str, Any]:
    return {
        "id": rule.id,
        "project_id": rule.project_id,
        "display_name": rule.display_name,
        "description": rule.description,
        "source": rule.source,
        "event_type": rule.event_type,
        "min_severity": rule.min_severity,
        "subject_type": rule.subject_type,
        "object_type_id": rule.object_type_id,
        "expression": rule.expression or {},
        "active": rule.active,
        "created_at": rule.created_at,
        "updated_at": rule.updated_at,
    }


def _alert_dict(alert: AlertEvent) -> Dict[str, Any]:
    return {
        "id": alert.id,
        "project_id": alert.project_id,
        "rule_id": alert.rule_id,
        "event_id": alert.event_id,
        "source": alert.source,
        "severity": alert.severity,
        "status": alert.status,
        "title": alert.title,
        "message": alert.message,
        "subject_type": alert.subject_type,
        "subject_id": alert.subject_id,
        "object_type_id": alert.object_type_id,
        "object_id": alert.object_id,
        "payload": alert.payload or {},
        "created_at": alert.created_at,
        "updated_at": alert.updated_at,
    }


def _incident_dict(incident: Incident) -> Dict[str, Any]:
    return {
        "id": incident.id,
        "project_id": incident.project_id,
        "display_name": incident.display_name,
        "description": incident.description,
        "severity": incident.severity,
        "status": incident.status,
        "owner": incident.owner,
        "linked_objects": incident.linked_objects or [],
        "alert_ids": incident.alert_ids or [],
        "approval_ids": incident.approval_ids or [],
        "runbook_execution_ids": incident.runbook_execution_ids or [],
        "timeline": incident.timeline or [],
        "created_at": incident.created_at,
        "updated_at": incident.updated_at,
    }


def _runbook_dict(runbook: Runbook) -> Dict[str, Any]:
    return {
        "id": runbook.id,
        "project_id": runbook.project_id,
        "display_name": runbook.display_name,
        "description": runbook.description,
        "steps": runbook.steps or [],
        "enabled": runbook.enabled,
        "created_at": runbook.created_at,
        "updated_at": runbook.updated_at,
    }


def _execution_dict(execution: RunbookExecution) -> Dict[str, Any]:
    return {
        "id": execution.id,
        "project_id": execution.project_id,
        "runbook_id": execution.runbook_id,
        "incident_id": execution.incident_id,
        "actor": execution.actor,
        "status": execution.status,
        "inputs": execution.inputs or {},
        "step_results": execution.step_results or [],
        "created_at": execution.created_at,
        "completed_at": execution.completed_at,
    }


def _notification_dict(notification: OpsNotification) -> Dict[str, Any]:
    return {
        "id": notification.id,
        "project_id": notification.project_id,
        "recipient": notification.recipient,
        "severity": notification.severity,
        "title": notification.title,
        "message": notification.message,
        "source": notification.source,
        "subject_type": notification.subject_type,
        "subject_id": notification.subject_id,
        "status": notification.status,
        "payload": notification.payload or {},
        "created_at": notification.created_at,
        "acknowledged_at": notification.acknowledged_at,
    }


def _ensure_tables(db: Session) -> None:
    for table in (
        OpsEvent.__table__,
        AlertRule.__table__,
        AlertEvent.__table__,
        Incident.__table__,
        Runbook.__table__,
        RunbookExecution.__table__,
        OpsNotification.__table__,
        OpsSlaPolicy.__table__,
    ):
        table.create(bind=db.get_bind(), checkfirst=True)


def _get_path(data: Dict[str, Any], field: str) -> Any:
    current: Any = data
    for part in str(field).split("."):
        if isinstance(current, dict):
            current = current.get(part)
        else:
            return None
    return current


def _compare(value: Any, op: str, expected: Any) -> bool:
    if op in {"eq", "=", "=="}:
        return value == expected
    if op in {"ne", "!="}:
        return value != expected
    if op == "contains":
        return str(expected).lower() in str(value).lower()
    if op == "not_null":
        return value is not None
    if op == "truthy":
        return bool(value)
    try:
        left = float(value)
        right = float(expected)
    except (TypeError, ValueError):
        return False
    if op == "gt":
        return left > right
    if op == "gte":
        return left >= right
    if op == "lt":
        return left < right
    if op == "lte":
        return left <= right
    return False


def _matches_expression(event: OpsEvent, expression: Dict[str, Any]) -> bool:
    if not expression:
        return True
    if "all" in expression:
        return all(_matches_expression(event, item) for item in expression.get("all") or [])
    if "any" in expression:
        return any(_matches_expression(event, item) for item in expression.get("any") or [])
    event_payload = _event_dict(event)
    field = expression.get("field")
    if not field:
        return True
    value = _get_path(event_payload, field)
    return _compare(value, expression.get("op", "eq"), expression.get("value"))


def _matches_rule(event: OpsEvent, rule: AlertRule) -> bool:
    if not rule.active:
        return False
    if rule.source and rule.source != event.source:
        return False
    if rule.event_type and rule.event_type != event.event_type:
        return False
    if rule.subject_type and rule.subject_type != event.subject_type:
        return False
    if rule.object_type_id and rule.object_type_id != event.object_type_id:
        return False
    if SEVERITY_RANK.get(event.severity, 0) < SEVERITY_RANK.get(rule.min_severity, 3):
        return False
    return _matches_expression(event, rule.expression or {})


def _create_notification(
    db: Session,
    *,
    title: str,
    message: Optional[str] = None,
    severity: str = "info",
    source: str = "ops",
    subject_type: Optional[str] = None,
    subject_id: Optional[str] = None,
    payload: Optional[Dict[str, Any]] = None,
    recipient: str = "workspace",
    project_id: str = "default",
) -> OpsNotification:
    notification = OpsNotification(
        id=_new_id("note"),
        project_id=project_id,
        recipient=recipient,
        severity=severity,
        title=title,
        message=message,
        source=source,
        subject_type=subject_type,
        subject_id=subject_id,
        status="UNREAD",
        payload=payload or {},
        created_at=_now(),
    )
    db.add(notification)
    return notification


def _evaluate_alert_rules(db: Session, events: List[OpsEvent]) -> List[AlertEvent]:
    _ensure_tables(db)
    rules = db.query(AlertRule).filter(AlertRule.active == True).all()  # noqa: E712
    created: List[AlertEvent] = []
    now = _now()
    for event in events:
        for rule in rules:
            if rule.project_id != event.project_id:
                continue
            if not _matches_rule(event, rule):
                continue
            existing = (
                db.query(AlertEvent)
                .filter(AlertEvent.rule_id == rule.id, AlertEvent.event_id == event.id)
                .first()
            )
            if existing:
                continue
            alert = AlertEvent(
                id=_new_id("alert"),
                project_id=event.project_id,
                rule_id=rule.id,
                event_id=event.id,
                source=event.source,
                severity=event.severity,
                status="OPEN",
                title=f"{rule.display_name}: {event.title}",
                message=event.message,
                subject_type=event.subject_type,
                subject_id=event.subject_id,
                object_type_id=event.object_type_id,
                object_id=event.object_id,
                payload={"event": _event_dict(event), "rule": _rule_dict(rule)},
                created_at=now,
                updated_at=now,
            )
            db.add(alert)
            _create_notification(
                db,
                title=alert.title,
                message=alert.message,
                severity=alert.severity,
                source="ops.alert",
                subject_type="alert",
                subject_id=alert.id,
                payload={"event_id": event.id, "rule_id": rule.id},
                project_id=event.project_id,
            )
            created.append(alert)
    return created


def record_ops_event(
    db: Session,
    *,
    source: str,
    event_type: str,
    severity: str = "info",
    title: str,
    message: Optional[str] = None,
    subject_type: Optional[str] = None,
    subject_id: Optional[str] = None,
    object_type_id: Optional[str] = None,
    object_id: Optional[str] = None,
    payload: Optional[Dict[str, Any]] = None,
    status: str = "OPEN",
    evaluate_alerts: bool = True,
    project_id: Optional[str] = None,
) -> OpsEvent:
    _ensure_tables(db)
    event_payload = payload or {}
    effective_project_id = str(project_id or event_payload.get("project_id") or "default")
    event = OpsEvent(
        id=_new_id("ops_evt"),
        project_id=effective_project_id,
        source=source,
        event_type=event_type,
        severity=severity.lower(),
        status=status,
        title=title,
        message=message,
        subject_type=subject_type,
        subject_id=subject_id,
        object_type_id=object_type_id,
        object_id=object_id,
        payload=event_payload,
        created_at=_now(),
    )
    db.add(event)
    if evaluate_alerts:
        _evaluate_alert_rules(db, [event])
    return event


def create_incident_inline(
    db: Session,
    *,
    display_name: str,
    description: Optional[str] = None,
    severity: str = "medium",
    status: str = "OPEN",
    owner: Optional[str] = None,
    linked_objects: Optional[List[Dict[str, Any]]] = None,
    alert_ids: Optional[List[str]] = None,
    approval_ids: Optional[List[str]] = None,
    actor: str = "workspace",
    incident_id: Optional[str] = None,
    project_id: str = "default",
) -> Incident:
    _ensure_tables(db)
    for ref in linked_objects or []:
        object_id = ref.get("object_id") or ref.get("id")
        obj = db.get(models.ObjectInstance, object_id) if object_id else None
        if not obj or obj.project_id != project_id:
            raise HTTPException(status_code=422, detail=f"Linked object '{object_id}' is not in project '{project_id}'")
    for alert_id in alert_ids or []:
        alert = db.get(AlertEvent, alert_id)
        if not alert or alert.project_id != project_id:
            raise HTTPException(status_code=422, detail=f"Alert '{alert_id}' is not in project '{project_id}'")
    for approval_id in approval_ids or []:
        approval = db.get(models_action.ApprovalRequest, approval_id)
        if not approval or approval.project_id != project_id:
            raise HTTPException(status_code=422, detail=f"Approval '{approval_id}' is not in project '{project_id}'")
    now = _now()
    incident = Incident(
        id=incident_id or _new_id("incident"),
        project_id=project_id,
        display_name=display_name,
        description=description,
        severity=severity,
        status=status,
        owner=owner,
        linked_objects=linked_objects or [],
        alert_ids=alert_ids or [],
        approval_ids=approval_ids or [],
        runbook_execution_ids=[],
        timeline=[{"at": now, "actor": actor, "event_type": "incident.created", "status": status}],
        created_at=now,
        updated_at=now,
    )
    db.add(incident)
    _audit(db, "ops.incident.created", "incident", incident.id, _incident_dict(incident))
    record_ops_event(
        db,
        source="ops",
        event_type="incident.created",
        severity=severity,
        title=display_name,
        message=description,
        subject_type="incident",
        subject_id=incident.id,
        payload={"status": status, "linked_objects": linked_objects or [], "alert_ids": alert_ids or []},
        project_id=project_id,
    )
    return incident


def _resolve(value: Any, context: Dict[str, Any]) -> Any:
    if isinstance(value, str) and value.startswith("$"):
        current: Any = context
        for part in value[1:].split("."):
            if isinstance(current, dict):
                current = current.get(part)
            elif isinstance(current, list) and part.isdigit():
                current = current[int(part)] if int(part) < len(current) else None
            else:
                return None
        return current
    if isinstance(value, dict):
        return {key: _resolve(item, context) for key, item in value.items()}
    if isinstance(value, list):
        return [_resolve(item, context) for item in value]
    return value


def _object_matches(obj: models.ObjectInstance, filters: Dict[str, Any]) -> bool:
    props = obj.properties or {}
    for key, expected in (filters or {}).items():
        actual = props.get(key)
        if isinstance(expected, dict):
            for op, value in expected.items():
                if not _compare(actual, op, value):
                    return False
        elif actual != expected:
            return False
    return True


def execute_runbook_inline(
    db: Session,
    *,
    runbook_id: str,
    incident_id: Optional[str] = None,
    inputs: Optional[Dict[str, Any]] = None,
    actor: str = "workspace",
    project_id: Optional[str] = None,
) -> Dict[str, Any]:
    _ensure_tables(db)
    runbook = db.get(Runbook, runbook_id)
    if not runbook:
        raise HTTPException(status_code=404, detail=f"Runbook '{runbook_id}' not found")
    if project_id and runbook.project_id != project_id:
        raise HTTPException(status_code=404, detail=f"Runbook '{runbook_id}' not found")
    if not runbook.enabled:
        raise HTTPException(status_code=409, detail="Runbook is disabled")

    execution = RunbookExecution(
        id=_new_id("runbook_exec"),
        project_id=runbook.project_id,
        runbook_id=runbook.id,
        incident_id=incident_id,
        actor=actor,
        status="RUNNING",
        inputs=inputs or {},
        step_results=[],
        created_at=_now(),
    )
    db.add(execution)
    context: Dict[str, Any] = dict(inputs or {})
    if incident_id and not str(incident_id).startswith("$"):
        incident = db.get(Incident, incident_id)
        if not incident or incident.project_id != runbook.project_id:
            raise HTTPException(status_code=404, detail=f"Incident '{incident_id}' not found")
    if incident_id:
        context["incident_id"] = incident_id
    results: List[Dict[str, Any]] = []

    try:
        for index, step in enumerate(runbook.steps or []):
            step_type = step.get("type")
            output = step.get("output") or f"step_{index + 1}"
            result: Dict[str, Any]

            if step_type == "query_objects":
                object_type_id = _resolve(step.get("object_type_id"), context)
                filters = _resolve(step.get("filters") or {}, context)
                limit = int(step.get("limit") or 25)
                rows = [
                    obj for obj in db.query(models.ObjectInstance).filter(
                        models.ObjectInstance.project_id == runbook.project_id,
                        models.ObjectInstance.object_type_id == object_type_id,
                    ).all()
                    if _object_matches(obj, filters)
                ][:limit]
                result = {
                    "object_type_id": object_type_id,
                    "count": len(rows),
                    "objects": [{"id": obj.id, "object_type_id": obj.object_type_id, "properties": obj.properties or {}} for obj in rows],
                }
            elif step_type == "score_risk":
                from . import decision_intelligence
                object_type_id = _resolve(step.get("object_type_id"), context)
                object_id = _resolve(step.get("object_id"), context)
                if not object_id and isinstance(context.get("objects"), dict):
                    object_id = (context["objects"].get("objects") or [{}])[0].get("id")
                result = decision_intelligence.score_object_by_id(db, str(object_type_id), str(object_id), step.get("scorecard_ids") or [])
            elif step_type == "run_model_monitor":
                from . import modelops
                monitor_id = _resolve(step.get("monitor_id"), context)
                current_asset_id = _resolve(step.get("current_asset_id"), context)
                result = modelops.run_monitor(monitor_id, modelops.ModelMonitorRunRequest(current_asset_id=current_asset_id), db)
            elif step_type == "run_data_contract":
                from . import reliability_ops
                contract_id = _resolve(step.get("contract_id"), context)
                asset_id = _resolve(step.get("asset_id"), context) if step.get("asset_id") else None
                result = reliability_ops.run_data_contract_inline(db, contract_id=contract_id, asset_id=asset_id)
            elif step_type == "evaluate_alert_rules":
                result = evaluate_alert_rules_inline(db, limit=int(step.get("limit") or 500), project_id=runbook.project_id)
            elif step_type == "propose_action":
                action_id = _resolve(step.get("action_type_id"), context)
                parameters = _resolve(step.get("parameters") or {}, context)
                action = db.get(models.ActionType, action_id)
                if not action or action.project_id != runbook.project_id:
                    raise HTTPException(status_code=404, detail=f"ActionType '{action_id}' not found")
                rules = action.rules or {}
                requires_approval = bool(
                    rules.get("requires_approval")
                    or rules.get("approval_required")
                    or str(rules.get("risk_level", "")).lower() in {"high", "critical"}
                )
                result = {"action_type_id": action_id, "parameters": parameters, "requires_approval": requires_approval, "status": "ACTION_PROPOSED"}
            elif step_type == "request_approval":
                action_id = _resolve(step.get("action_type_id"), context)
                parameters = _resolve(step.get("parameters") or {}, context)
                action = db.get(models.ActionType, action_id)
                if not action or action.project_id != runbook.project_id:
                    raise HTTPException(status_code=404, detail=f"ActionType '{action_id}' not found")
                approval = models_action.ApprovalRequest(
                    id=str(uuid.uuid4()),
                    project_id=action.project_id,
                    action_type_id=action_id,
                    requester=actor,
                    parameters=parameters,
                    status=models_action.ApprovalStatus.PENDING.value,
                )
                db.add(approval)
                if incident_id:
                    incident = db.get(Incident, incident_id)
                    if incident:
                        incident.approval_ids = list(dict.fromkeys([*(incident.approval_ids or []), approval.id]))
                        incident.updated_at = _now()
                result = {"status": "APPROVAL_REQUESTED", "approval_request_id": approval.id, "action_type_id": action_id}
            elif step_type == "create_notification":
                notification = _create_notification(
                    db,
                    title=str(_resolve(step.get("title") or "Runbook notification", context)),
                    message=_resolve(step.get("message"), context),
                    severity=str(_resolve(step.get("severity") or "info", context)),
                    source="runbook",
                    subject_type="runbook_execution",
                    subject_id=execution.id,
                    payload={"runbook_id": runbook.id, "incident_id": incident_id},
                    project_id=runbook.project_id,
                )
                result = _notification_dict(notification)
            elif step_type == "open_incident":
                incident = create_incident_inline(
                    db,
                    display_name=str(_resolve(step.get("display_name") or "Runbook Incident", context)),
                    description=_resolve(step.get("description"), context),
                    severity=str(_resolve(step.get("severity") or "medium", context)),
                    linked_objects=_resolve(step.get("linked_objects") or [], context),
                    actor=actor,
                    project_id=runbook.project_id,
                )
                incident_id = incident.id
                execution.incident_id = incident.id
                result = _incident_dict(incident)
            elif step_type == "update_incident":
                target_incident_id = _resolve(step.get("incident_id") or "$incident_id", context)
                incident = db.get(Incident, target_incident_id)
                if not incident or incident.project_id != runbook.project_id:
                    raise HTTPException(status_code=404, detail=f"Incident '{target_incident_id}' not found")
                for field in ("display_name", "description", "severity", "status", "owner"):
                    if field in step:
                        setattr(incident, field, _resolve(step[field], context))
                incident.updated_at = _now()
                incident.timeline = [*(incident.timeline or []), {"at": incident.updated_at, "actor": actor, "event_type": "incident.updated", "status": incident.status}]
                result = _incident_dict(incident)
            else:
                result = {"status": "SKIPPED", "message": f"Unsupported runbook step '{step_type}'"}

            context[output] = result
            if output == "objects":
                context["objects"] = result
            results.append({"index": index, "type": step_type, "output": output, "result": result})

        execution.status = "SUCCESS"
    except Exception as exc:
        execution.status = "FAILED"
        results.append({"index": len(results), "type": "error", "result": {"message": str(exc)}})

    execution.step_results = results
    execution.completed_at = _now()
    if execution.incident_id:
        incident = db.get(Incident, execution.incident_id)
        if incident:
            incident.runbook_execution_ids = list(dict.fromkeys([*(incident.runbook_execution_ids or []), execution.id]))
            incident.timeline = [*(incident.timeline or []), {"at": execution.completed_at, "actor": actor, "event_type": "runbook.executed", "status": execution.status, "runbook_id": runbook.id}]
            incident.updated_at = execution.completed_at
    record_ops_event(
        db,
        source="runbook",
        event_type="runbook.executed",
        severity="high" if execution.status == "FAILED" else "info",
        title=f"Runbook {runbook.display_name} {execution.status.lower()}",
        subject_type="runbook_execution",
        subject_id=execution.id,
        payload={"runbook_id": runbook.id, "incident_id": execution.incident_id, "status": execution.status},
        project_id=runbook.project_id,
    )
    _audit(db, "ops.runbook.executed", "runbook_execution", execution.id, {"status": execution.status, "runbook_id": runbook.id})
    return _execution_dict(execution)


def evaluate_alert_rules_inline(db: Session, *, limit: int = 500, source: Optional[str] = None, event_type: Optional[str] = None, status: Optional[str] = None, project_id: Optional[str] = None) -> Dict[str, Any]:
    _ensure_tables(db)
    query = db.query(OpsEvent).order_by(OpsEvent.created_at.desc())
    if project_id:
        query = query.filter(OpsEvent.project_id == project_id)
    if source:
        query = query.filter(OpsEvent.source == source)
    if event_type:
        query = query.filter(OpsEvent.event_type == event_type)
    if status:
        query = query.filter(OpsEvent.status == status)
    events = query.limit(max(1, min(limit, 2000))).all()
    alerts = _evaluate_alert_rules(db, events)
    return {"evaluated_events": len(events), "created_alerts": len(alerts), "alerts": [_alert_dict(alert) for alert in alerts]}


@router.get("/ops/summary")
def ops_summary(db: Session = Depends(get_db), principal: production_auth.Principal = Depends(production_auth.require_permission("view"))):
    _ensure_tables(db)
    open_alerts = semantic_scope.accessible_query(db, principal, AlertEvent).filter(AlertEvent.status == "OPEN").all()
    open_incidents = semantic_scope.accessible_query(db, principal, Incident).filter(Incident.status.in_(["OPEN", "TRIAGE", "INVESTIGATING"])).all()
    pending_approvals = semantic_scope.accessible_query(db, principal, models_action.ApprovalRequest).filter(models_action.ApprovalRequest.status == models_action.ApprovalStatus.PENDING.value).all()
    failed_pipelines = semantic_scope.accessible_query(db, principal, models.PipelineRun).filter(models.PipelineRun.status == "FAILED").order_by(models.PipelineRun.created_at.desc()).limit(10).all()
    latest_events = semantic_scope.accessible_query(db, principal, OpsEvent).order_by(OpsEvent.created_at.desc()).limit(10).all()
    severity_counts: Dict[str, int] = {}
    for alert in open_alerts:
        severity_counts[alert.severity] = severity_counts.get(alert.severity, 0) + 1
    return {
        "events": semantic_scope.accessible_query(db, principal, OpsEvent).count(),
        "open_alerts": len(open_alerts),
        "open_incidents": len(open_incidents),
        "runbooks": semantic_scope.accessible_query(db, principal, Runbook).count(),
        "pending_approvals": len(pending_approvals),
        "unread_notifications": semantic_scope.accessible_query(db, principal, OpsNotification).filter(OpsNotification.status == "UNREAD").count(),
        "failed_pipelines": [{"id": run.id, "pipeline_id": run.pipeline_id, "error": run.error} for run in failed_pipelines],
        "severity_counts": severity_counts,
        "latest_events": [_event_dict(event) for event in latest_events],
        "latest_alerts": [_alert_dict(alert) for alert in open_alerts[:10]],
        "latest_incidents": [_incident_dict(incident) for incident in open_incidents[:10]],
    }


@router.get("/ops/events")
def list_events(
    source: Optional[str] = None,
    severity: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = Query(default=100, ge=1, le=1000),
    db: Session = Depends(get_db),
    principal: production_auth.Principal = Depends(production_auth.require_permission("view")),
):
    _ensure_tables(db)
    query = semantic_scope.accessible_query(db, principal, OpsEvent)
    if source:
        query = query.filter(OpsEvent.source == source)
    if severity:
        query = query.filter(OpsEvent.severity == severity)
    if status:
        query = query.filter(OpsEvent.status == status)
    return [_event_dict(event) for event in query.order_by(OpsEvent.created_at.desc()).limit(limit).all()]


@router.post("/ops/events/ingest")
def ingest_event(body: OpsEventIngest, db: Session = Depends(get_db), principal: production_auth.Principal = Depends(production_auth.require_permission("execute"))):
    semantic_scope.assert_project(db, principal, body.project_id, "execute")
    event = record_ops_event(db, **body.model_dump())
    _audit(db, "ops.event.ingested", "ops_event", event.id, _event_dict(event))
    db.commit()
    db.refresh(event)
    return _event_dict(event)


@router.post("/ops/alert-rules")
def create_alert_rule(body: AlertRuleCreate, db: Session = Depends(get_db), principal: production_auth.Principal = Depends(production_auth.require_permission("edit"))):
    _ensure_tables(db)
    semantic_scope.assert_project(db, principal, body.project_id, "edit")
    rule_id = body.id or _new_id("alert_rule")
    if db.get(AlertRule, rule_id):
        raise HTTPException(status_code=400, detail="AlertRule already exists")
    now = _now()
    rule = AlertRule(id=rule_id, created_at=now, updated_at=now, **body.model_dump(exclude={"id"}))
    db.add(rule)
    _audit(db, "ops.alert_rule.created", "alert_rule", rule.id, _rule_dict(rule))
    db.commit()
    db.refresh(rule)
    return _rule_dict(rule)


@router.get("/ops/alert-rules")
def list_alert_rules(db: Session = Depends(get_db), principal: production_auth.Principal = Depends(production_auth.require_permission("view"))):
    _ensure_tables(db)
    return [_rule_dict(rule) for rule in semantic_scope.accessible_query(db, principal, AlertRule).order_by(AlertRule.updated_at.desc()).all()]


@router.patch("/ops/alert-rules/{rule_id}")
def patch_alert_rule(rule_id: str, body: AlertRulePatch, db: Session = Depends(get_db), principal: production_auth.Principal = Depends(production_auth.require_permission("edit"))):
    rule = semantic_scope.owned_row(db, principal, AlertRule, rule_id, "edit", "AlertRule")
    patch = body.model_dump(exclude_unset=True)
    for key, value in patch.items():
        setattr(rule, key, value)
    rule.updated_at = _now()
    _audit(db, "ops.alert_rule.updated", "alert_rule", rule.id, patch)
    db.commit()
    db.refresh(rule)
    return _rule_dict(rule)


@router.post("/ops/alerts/evaluate")
def evaluate_alerts(body: AlertEvaluateRequest = AlertEvaluateRequest(), db: Session = Depends(get_db), principal: production_auth.Principal = Depends(production_auth.require_permission("execute"))):
    projects = semantic_scope.accessible_query(db, principal, OpsEvent, "execute").with_entities(OpsEvent.project_id).distinct().all()
    alerts: List[Dict[str, Any]] = []
    evaluated = 0
    for (project_id,) in projects:
        project_result = evaluate_alert_rules_inline(db, limit=body.limit, source=body.source, event_type=body.event_type, status=body.status, project_id=project_id)
        evaluated += project_result["evaluated_events"]
        alerts.extend(project_result["alerts"])
    result = {"evaluated_events": evaluated, "created_alerts": len(alerts), "alerts": alerts}
    db.commit()
    return result


@router.get("/ops/alerts")
def list_alerts(status: Optional[str] = None, severity: Optional[str] = None, db: Session = Depends(get_db), principal: production_auth.Principal = Depends(production_auth.require_permission("view"))):
    _ensure_tables(db)
    query = semantic_scope.accessible_query(db, principal, AlertEvent)
    if status:
        query = query.filter(AlertEvent.status == status)
    if severity:
        query = query.filter(AlertEvent.severity == severity)
    return [_alert_dict(alert) for alert in query.order_by(AlertEvent.created_at.desc()).all()]


@router.post("/ops/incidents")
def create_incident(body: IncidentCreate, db: Session = Depends(get_db), principal: production_auth.Principal = Depends(production_auth.require_permission("edit"))):
    semantic_scope.assert_project(db, principal, body.project_id, "edit")
    payload = body.model_dump(exclude={"id"})
    incident = create_incident_inline(db, **payload, actor="workspace", incident_id=body.id)
    db.commit()
    db.refresh(incident)
    return _incident_dict(incident)


@router.get("/ops/incidents")
def list_incidents(status: Optional[str] = None, db: Session = Depends(get_db), principal: production_auth.Principal = Depends(production_auth.require_permission("view"))):
    _ensure_tables(db)
    query = semantic_scope.accessible_query(db, principal, Incident)
    if status:
        query = query.filter(Incident.status == status)
    return [_incident_dict(incident) for incident in query.order_by(Incident.updated_at.desc()).all()]


@router.get("/ops/incidents/{incident_id}")
def get_incident(incident_id: str, db: Session = Depends(get_db), principal: production_auth.Principal = Depends(production_auth.require_permission("view"))):
    incident = semantic_scope.owned_row(db, principal, Incident, incident_id, "view", "Incident")
    return _incident_dict(incident)


@router.patch("/ops/incidents/{incident_id}")
def patch_incident(incident_id: str, body: IncidentPatch, db: Session = Depends(get_db), principal: production_auth.Principal = Depends(production_auth.require_permission("edit"))):
    incident = semantic_scope.owned_row(db, principal, Incident, incident_id, "edit", "Incident")
    patch = body.model_dump(exclude_unset=True)
    for key, value in patch.items():
        setattr(incident, key, value)
    incident.updated_at = _now()
    incident.timeline = [*(incident.timeline or []), {"at": incident.updated_at, "actor": "workspace", "event_type": "incident.updated", "patch": patch}]
    _audit(db, "ops.incident.updated", "incident", incident.id, patch)
    db.commit()
    db.refresh(incident)
    return _incident_dict(incident)


@router.post("/ops/incidents/{incident_id}/link-object")
def link_incident_object(incident_id: str, body: IncidentLinkObject, db: Session = Depends(get_db), principal: production_auth.Principal = Depends(production_auth.require_permission("edit"))):
    incident = semantic_scope.owned_row(db, principal, Incident, incident_id, "edit", "Incident")
    obj = db.get(models.ObjectInstance, body.object_id)
    if not obj or obj.project_id != incident.project_id or obj.object_type_id != body.object_type_id:
        raise HTTPException(status_code=404, detail=f"Object '{body.object_id}' not found")
    link = body.model_dump()
    links = incident.linked_objects or []
    if not any(item.get("object_id") == body.object_id and item.get("object_type_id") == body.object_type_id for item in links):
        links.append(link)
    incident.linked_objects = links
    incident.updated_at = _now()
    incident.timeline = [*(incident.timeline or []), {"at": incident.updated_at, "actor": "workspace", "event_type": "incident.object_linked", **link}]
    db.commit()
    db.refresh(incident)
    return _incident_dict(incident)


@router.post("/ops/runbooks")
def create_runbook(body: RunbookCreate, db: Session = Depends(get_db), principal: production_auth.Principal = Depends(production_auth.require_permission("edit"))):
    _ensure_tables(db)
    semantic_scope.assert_project(db, principal, body.project_id, "edit")
    runbook_id = body.id or _new_id("runbook")
    if db.get(Runbook, runbook_id):
        raise HTTPException(status_code=400, detail="Runbook already exists")
    now = _now()
    runbook = Runbook(id=runbook_id, created_at=now, updated_at=now, **body.model_dump(exclude={"id"}))
    db.add(runbook)
    _audit(db, "ops.runbook.created", "runbook", runbook.id, _runbook_dict(runbook))
    db.commit()
    db.refresh(runbook)
    return _runbook_dict(runbook)


@router.get("/ops/runbooks")
def list_runbooks(db: Session = Depends(get_db), principal: production_auth.Principal = Depends(production_auth.require_permission("view"))):
    _ensure_tables(db)
    return [_runbook_dict(runbook) for runbook in semantic_scope.accessible_query(db, principal, Runbook).order_by(Runbook.updated_at.desc()).all()]


@router.post("/ops/runbooks/{runbook_id}/execute")
def execute_runbook(runbook_id: str, body: RunbookExecutionRequest = RunbookExecutionRequest(), db: Session = Depends(get_db), principal: production_auth.Principal = Depends(production_auth.require_permission("execute"))):
    runbook = semantic_scope.owned_row(db, principal, Runbook, runbook_id, "execute", "Runbook")
    result = execute_runbook_inline(db, runbook_id=runbook_id, incident_id=body.incident_id, inputs=body.inputs, actor=body.actor, project_id=runbook.project_id)
    db.commit()
    return result


@router.get("/ops/inbox")
def inbox(status: Optional[str] = None, recipient: str = "workspace", db: Session = Depends(get_db), principal: production_auth.Principal = Depends(production_auth.require_permission("view"))):
    _ensure_tables(db)
    query = semantic_scope.accessible_query(db, principal, OpsNotification).filter(OpsNotification.recipient == recipient)
    if status:
        query = query.filter(OpsNotification.status == status)
    return [_notification_dict(note) for note in query.order_by(OpsNotification.created_at.desc()).all()]


@router.post("/ops/inbox/{notification_id}/ack")
def ack_notification(notification_id: str, db: Session = Depends(get_db), principal: production_auth.Principal = Depends(production_auth.require_permission("edit"))):
    note = semantic_scope.owned_row(db, principal, OpsNotification, notification_id, "edit", "OpsNotification")
    note.status = "ACKED"
    note.acknowledged_at = _now()
    db.commit()
    db.refresh(note)
    return _notification_dict(note)

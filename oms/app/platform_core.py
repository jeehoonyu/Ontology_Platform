"""
Unified operational intelligence platform layer.

This module is the connective tissue across the existing local Foundry-style
runtime. It deliberately reuses current tables and services where possible:
Ops events become the platform event bus, audit logs and snapshots become
shared timelines, and existing ontology/data/model/ops resources are indexed by
global search.
"""
from __future__ import annotations

import json
import os
import time
import uuid
from collections import Counter
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import Boolean, Integer, JSON, String
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Mapped, Session, mapped_column

from . import models, models_action, ops_control, production_auth, semantic_scope, tenancy
from .database import Base, get_db

router = APIRouter(tags=["platform_core"])


def _now() -> int:
    return int(time.time())


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


SEVERITY_RANK = {"info": 0, "low": 1, "medium": 2, "warn": 2, "high": 3, "critical": 4}
POLICY_EFFECTS = {"ALLOW", "DENY", "MASK", "ROW_FILTER", "REQUIRE_APPROVAL"}


class EventSubscription(Base):
    __tablename__ = "platform_event_subscriptions"

    id: Mapped[str] = mapped_column(String, primary_key=True, index=True)
    display_name: Mapped[str] = mapped_column(String)
    description: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    filters: Mapped[dict] = mapped_column(JSON, default=dict)
    target: Mapped[dict] = mapped_column(JSON, default=dict)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[int] = mapped_column(Integer)
    updated_at: Mapped[int] = mapped_column(Integer)


class PolicyRule(Base):
    __tablename__ = "platform_policy_rules"

    id: Mapped[str] = mapped_column(String, primary_key=True, index=True)
    display_name: Mapped[str] = mapped_column(String)
    description: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    effect: Mapped[str] = mapped_column(String, default="ALLOW", index=True)
    principal: Mapped[Optional[str]] = mapped_column(String, nullable=True, index=True)
    action: Mapped[Optional[str]] = mapped_column(String, nullable=True, index=True)
    resource_kind: Mapped[Optional[str]] = mapped_column(String, nullable=True, index=True)
    resource_id: Mapped[Optional[str]] = mapped_column(String, nullable=True, index=True)
    object_type_id: Mapped[Optional[str]] = mapped_column(String, nullable=True, index=True)
    purpose: Mapped[Optional[str]] = mapped_column(String, nullable=True, index=True)
    condition: Mapped[dict] = mapped_column(JSON, default=dict)
    mask_properties: Mapped[list] = mapped_column(JSON, default=list)
    row_filter: Mapped[dict] = mapped_column(JSON, default=dict)
    approval: Mapped[dict] = mapped_column(JSON, default=dict)
    break_glass_allowed: Mapped[bool] = mapped_column(Boolean, default=False)
    priority: Mapped[int] = mapped_column(Integer, default=100)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[int] = mapped_column(Integer)
    updated_at: Mapped[int] = mapped_column(Integer)


class PolicyDecisionLog(Base):
    __tablename__ = "platform_policy_decisions"

    id: Mapped[str] = mapped_column(String, primary_key=True, index=True)
    principal: Mapped[str] = mapped_column(String, index=True)
    action: Mapped[str] = mapped_column(String, index=True)
    resource_kind: Mapped[str] = mapped_column(String, index=True)
    resource_id: Mapped[Optional[str]] = mapped_column(String, nullable=True, index=True)
    decision: Mapped[str] = mapped_column(String, index=True)
    allowed: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    matched_rule_ids: Mapped[list] = mapped_column(JSON, default=list)
    masks: Mapped[list] = mapped_column(JSON, default=list)
    row_filter: Mapped[dict] = mapped_column(JSON, default=dict)
    approval: Mapped[dict] = mapped_column(JSON, default=dict)
    break_glass: Mapped[dict] = mapped_column(JSON, default=dict)
    explanation: Mapped[str] = mapped_column(String)
    context: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[int] = mapped_column(Integer)


class EventPublishRequest(BaseModel):
    source: str
    event_type: str
    severity: str = "info"
    title: str
    message: Optional[str] = None
    subject_type: Optional[str] = None
    subject_id: Optional[str] = None
    object_type_id: Optional[str] = None
    object_id: Optional[str] = None
    payload: Dict[str, Any] = Field(default_factory=dict)
    status: str = "OPEN"
    evaluate_alerts: bool = True


class EventSubscriptionCreate(BaseModel):
    id: Optional[str] = None
    display_name: str
    description: Optional[str] = None
    filters: Dict[str, Any] = Field(default_factory=dict)
    target: Dict[str, Any] = Field(default_factory=dict)
    active: bool = True


class PolicyRuleCreate(BaseModel):
    id: Optional[str] = None
    display_name: str
    description: Optional[str] = None
    effect: str = "ALLOW"
    principal: Optional[str] = None
    action: Optional[str] = None
    resource_kind: Optional[str] = None
    resource_id: Optional[str] = None
    object_type_id: Optional[str] = None
    purpose: Optional[str] = None
    condition: Dict[str, Any] = Field(default_factory=dict)
    mask_properties: List[str] = Field(default_factory=list)
    row_filter: Dict[str, Any] = Field(default_factory=dict)
    approval: Dict[str, Any] = Field(default_factory=dict)
    break_glass_allowed: bool = False
    priority: int = 100
    active: bool = True


class PolicyRulePatch(BaseModel):
    display_name: Optional[str] = None
    description: Optional[str] = None
    effect: Optional[str] = None
    principal: Optional[str] = None
    action: Optional[str] = None
    resource_kind: Optional[str] = None
    resource_id: Optional[str] = None
    object_type_id: Optional[str] = None
    purpose: Optional[str] = None
    condition: Optional[Dict[str, Any]] = None
    mask_properties: Optional[List[str]] = None
    row_filter: Optional[Dict[str, Any]] = None
    approval: Optional[Dict[str, Any]] = None
    break_glass_allowed: Optional[bool] = None
    priority: Optional[int] = None
    active: Optional[bool] = None


class PolicyEvaluateRequest(BaseModel):
    principal: str
    action: str
    resource_kind: str
    resource_id: Optional[str] = None
    object_type_id: Optional[str] = None
    purpose: Optional[str] = None
    context: Dict[str, Any] = Field(default_factory=dict)
    break_glass_reason: Optional[str] = None


class PolicySimulationRequest(PolicyEvaluateRequest):
    hypothetical_rules: List[PolicyRuleCreate] = Field(default_factory=list)
    persist: bool = False


class SearchRequest(BaseModel):
    q: str = ""
    kinds: List[str] = Field(default_factory=list)
    limit: int = 25
    include_payload: bool = False


def _ensure_tables(db: Session) -> None:
    if os.getenv("APP_ENV", "").strip().lower() == "production":
        return
    ops_control._ensure_tables(db)
    for table in (EventSubscription.__table__, PolicyRule.__table__, PolicyDecisionLog.__table__):
        table.create(bind=db.get_bind(), checkfirst=True)


def _audit(db: Session, event_type: str, subject_type: str, subject_id: str, payload: Dict[str, Any], actor: str = "platform") -> None:
    db.add(models_action.AuditLog(
        id=uuid.uuid4().hex,
        actor=actor,
        event_type=event_type,
        subject_type=subject_type,
        subject_id=subject_id,
        payload=payload,
    ))


def _event_dict(event: ops_control.OpsEvent) -> Dict[str, Any]:
    return ops_control._event_dict(event)


def _subscription_dict(row: EventSubscription) -> Dict[str, Any]:
    return {
        "id": row.id,
        "display_name": row.display_name,
        "description": row.description,
        "filters": row.filters or {},
        "target": row.target or {},
        "active": row.active,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


def _policy_dict(row: PolicyRule) -> Dict[str, Any]:
    return {
        "id": row.id,
        "display_name": row.display_name,
        "description": row.description,
        "effect": row.effect,
        "principal": row.principal,
        "action": row.action,
        "resource_kind": row.resource_kind,
        "resource_id": row.resource_id,
        "object_type_id": row.object_type_id,
        "purpose": row.purpose,
        "condition": row.condition or {},
        "mask_properties": row.mask_properties or [],
        "row_filter": row.row_filter or {},
        "approval": row.approval or {},
        "break_glass_allowed": row.break_glass_allowed,
        "priority": row.priority,
        "active": row.active,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


def _decision_dict(row: PolicyDecisionLog) -> Dict[str, Any]:
    return {
        "id": row.id,
        "principal": row.principal,
        "action": row.action,
        "resource_kind": row.resource_kind,
        "resource_id": row.resource_id,
        "decision": row.decision,
        "allowed": row.allowed,
        "matched_rule_ids": row.matched_rule_ids or [],
        "masks": row.masks or [],
        "row_filter": row.row_filter or {},
        "approval": row.approval or {},
        "break_glass": row.break_glass or {},
        "explanation": row.explanation,
        "context": row.context or {},
        "created_at": row.created_at,
    }


def _get_path(data: Dict[str, Any], field: str) -> Any:
    value: Any = data
    for part in str(field or "").split("."):
        if isinstance(value, dict):
            value = value.get(part)
        else:
            return None
    return value


def _compare(value: Any, op: str, expected: Any) -> bool:
    if op in {"eq", "=", "=="}:
        return value == expected
    if op in {"ne", "!="}:
        return value != expected
    if op == "contains":
        return str(expected).lower() in str(value or "").lower()
    if op == "not_null":
        return value is not None
    if op == "truthy":
        return bool(value)
    if op == "in":
        return value in (expected or [])
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


def _matches_expression(data: Dict[str, Any], expression: Dict[str, Any]) -> bool:
    if not expression:
        return True
    if "all" in expression:
        return all(_matches_expression(data, item) for item in expression.get("all") or [])
    if "any" in expression:
        return any(_matches_expression(data, item) for item in expression.get("any") or [])
    field = expression.get("field")
    if not field:
        return True
    return _compare(_get_path(data, field), expression.get("op", "eq"), expression.get("value"))


def _matches_event_filters(event: Dict[str, Any], filters: Dict[str, Any]) -> bool:
    if not filters:
        return True
    for field in ("source", "event_type", "subject_type", "subject_id", "object_type_id", "object_id", "status"):
        expected = filters.get(field)
        if expected is not None and event.get(field) != expected:
            return False
    min_severity = filters.get("min_severity")
    if min_severity and SEVERITY_RANK.get(str(event.get("severity", "info")).lower(), 0) < SEVERITY_RANK.get(str(min_severity).lower(), 0):
        return False
    return _matches_expression(event, filters.get("expression") or {})


def _resource_text(*parts: Any) -> str:
    return " ".join(json.dumps(part, default=str, sort_keys=True) if isinstance(part, (dict, list)) else str(part or "") for part in parts)


def _search_score(text: str, query: str) -> int:
    if not query:
        return 1
    text_l = text.lower()
    terms = [term for term in query.lower().split() if term]
    if not terms:
        return 1
    score = 0
    for term in terms:
        if term in text_l:
            score += 10
        if text_l.startswith(term):
            score += 5
    return score


def _add_search_result(results: List[Dict[str, Any]], *, kind: str, resource_id: str, title: str, subtitle: str, url: str, query: str, payload: Optional[Dict[str, Any]] = None, include_payload: bool = False) -> None:
    text = _resource_text(kind, resource_id, title, subtitle, payload or {})
    score = _search_score(text, query)
    if query and score == 0:
        return
    row = {
        "kind": kind,
        "id": resource_id,
        "title": title,
        "subtitle": subtitle,
        "url": url,
        "score": score,
    }
    if include_payload:
        row["payload"] = payload or {}
    results.append(row)


def _safe_all(db: Session, model, principal: production_auth.Principal) -> List[Any]:
    try:
        if hasattr(model, "project_id"):
            return semantic_scope.accessible_query(db, principal, model).all()
        return db.query(model).all()
    except OperationalError:
        db.rollback()
        return []


def _search_resources(db: Session, query: str, kinds: List[str], limit: int, include_payload: bool,
                      principal: production_auth.Principal) -> List[Dict[str, Any]]:
    kind_filter = {kind.lower() for kind in kinds if kind}
    results: List[Dict[str, Any]] = []

    def allowed(kind: str) -> bool:
        return not kind_filter or kind in kind_filter

    if allowed("object_type"):
        for row in _safe_all(db, models.ObjectType, principal):
            _add_search_result(results, kind="object_type", resource_id=row.id, title=row.display_name or row.id, subtitle=row.description or "Ontology object type", url=f"/workspace/object-explorer?type={row.id}", query=query, payload={"properties": row.properties or {}}, include_payload=include_payload)

    if allowed("object"):
        for row in _safe_all(db, models.ObjectInstance, principal):
            title = (row.properties or {}).get("name") or (row.properties or {}).get("title") or row.id
            _add_search_result(results, kind="object", resource_id=row.id, title=str(title), subtitle=f"{row.object_type_id} object", url=f"/objects/{row.object_type_id}/{row.id}/profile", query=query, payload={"object_type_id": row.object_type_id, "properties": row.properties or {}}, include_payload=include_payload)

    if allowed("dataset"):
        for row in _safe_all(db, models.DataAsset, principal):
            _add_search_result(results, kind="dataset", resource_id=row.id, title=row.display_name or row.id, subtitle=f"{row.kind} - {len(row.records or [])} records", url=f"/data-assets/{row.id}", query=query, payload={"schema": row.asset_schema or {}}, include_payload=include_payload)

    if allowed("pipeline"):
        for row in _safe_all(db, models.PipelineDefinition, principal):
            _add_search_result(results, kind="pipeline", resource_id=row.id, title=row.display_name or row.id, subtitle=f"{row.mode} pipeline", url=f"/pipelines/{row.id}", query=query, payload={"input_asset_id": row.input_asset_id, "output_asset_id": row.output_asset_id, "steps": row.steps or []}, include_payload=include_payload)

    if allowed("action"):
        for row in _safe_all(db, models.ActionType, principal):
            _add_search_result(results, kind="action", resource_id=row.id, title=row.display_name or row.id, subtitle=row.description or "Governed action type", url=f"/action-types/{row.id}", query=query, payload={"parameters": row.parameters or {}, "rules": row.rules or {}}, include_payload=include_payload)

    if allowed("logic"):
        for row in _safe_all(db, models.LogicFunction, principal):
            _add_search_result(results, kind="logic", resource_id=row.id, title=row.display_name or row.id, subtitle=row.description or "AIP Logic function", url=f"/logic-functions/{row.id}", query=query, payload={"blocks": row.blocks or []}, include_payload=include_payload)

    if allowed("agent"):
        for row in _safe_all(db, models.AgentDefinition, principal):
            _add_search_result(results, kind="agent", resource_id=row.id, title=row.display_name or row.id, subtitle=row.description or "Agent", url=f"/agents/{row.id}", query=query, payload={"allowed_object_types": row.allowed_object_types or [], "allowed_actions": row.allowed_actions or []}, include_payload=include_payload)

    if allowed("event"):
        ops_control._ensure_tables(db)
        accessible = tenancy.accessible_project_ids(db, semantic_scope.effective_principal(principal), "view")
        for row in db.query(ops_control.OpsEvent).all():
            event_project = (row.payload or {}).get("project_id")
            if accessible is not None and event_project not in accessible:
                continue
            _add_search_result(results, kind="event", resource_id=row.id, title=row.title, subtitle=f"{row.source} {row.event_type} {row.severity}", url=f"/events/{row.id}", query=query, payload=_event_dict(row), include_payload=include_payload)

    if allowed("incident"):
        ops_control._ensure_tables(db)
        for row in db.query(ops_control.Incident).all():
            _add_search_result(results, kind="incident", resource_id=row.id, title=row.display_name, subtitle=f"{row.severity} {row.status}", url=f"/ops/incidents/{row.id}", query=query, payload=ops_control._incident_dict(row), include_payload=include_payload)

    try:
        from . import investigations
        if allowed("investigation"):
            for row in _safe_all(db, investigations.InvestigationWorkspace, principal):
                _add_search_result(results, kind="investigation", resource_id=row.id, title=row.display_name, subtitle=f"{row.status} investigation", url=f"/investigations/{row.id}", query=query, payload={"object_refs": row.object_refs or []}, include_payload=include_payload)
    except OperationalError:
        db.rollback()

    try:
        from . import modeling
        if allowed("model"):
            for row in _safe_all(db, modeling.ModelingObjective, principal):
                _add_search_result(results, kind="model", resource_id=row.id, title=row.display_name, subtitle=f"{row.problem_type} objective", url=f"/modeling/objectives/{row.id}", query=query, payload={"target_field": row.target_field, "feature_fields": row.feature_fields or []}, include_payload=include_payload)
    except OperationalError:
        db.rollback()

    results.sort(key=lambda item: (-item["score"], item["kind"], item["title"]))
    return results[: max(1, min(limit, 250))]


def _policy_matches(rule: PolicyRule, req: PolicyEvaluateRequest) -> bool:
    if not rule.active:
        return False
    if rule.principal and rule.principal != req.principal:
        return False
    if rule.action and rule.action != req.action:
        return False
    if rule.resource_kind and rule.resource_kind != req.resource_kind:
        return False
    if rule.resource_id and rule.resource_id != req.resource_id:
        return False
    if rule.object_type_id and rule.object_type_id != req.object_type_id:
        return False
    if rule.purpose and rule.purpose != req.purpose:
        return False
    data = {
        "principal": req.principal,
        "action": req.action,
        "resource_kind": req.resource_kind,
        "resource_id": req.resource_id,
        "object_type_id": req.object_type_id,
        "purpose": req.purpose,
        "context": req.context or {},
    }
    return _matches_expression(data, rule.condition or {})


def _evaluate_policy_rules(rules: List[PolicyRule], req: PolicyEvaluateRequest) -> Dict[str, Any]:
    matched = sorted([rule for rule in rules if _policy_matches(rule, req)], key=lambda item: (item.priority, item.id))
    masks: List[str] = []
    row_filter: Dict[str, Any] = {}
    approval: Dict[str, Any] = {}
    denied_by: List[str] = []
    allowed_by: List[str] = []
    break_glass_used = False
    break_glass_rules: List[str] = []

    for rule in matched:
        effect = rule.effect.upper()
        if effect == "ALLOW":
            allowed_by.append(rule.id)
        elif effect == "DENY":
            if req.break_glass_reason and rule.break_glass_allowed:
                break_glass_used = True
                break_glass_rules.append(rule.id)
            else:
                denied_by.append(rule.id)
        elif effect == "MASK":
            for prop in rule.mask_properties or []:
                if prop not in masks:
                    masks.append(prop)
        elif effect == "ROW_FILTER":
            row_filter.update(rule.row_filter or {})
        elif effect == "REQUIRE_APPROVAL":
            approval = {
                **(rule.approval or {}),
                "required": True,
                "rule_id": rule.id,
                "reason": (rule.approval or {}).get("reason") or rule.description or rule.display_name,
            }

    allowed = not denied_by
    decision = "DENY" if denied_by else "ALLOW"
    if approval:
        decision = "REQUIRE_APPROVAL" if allowed else decision
    if masks and allowed and decision == "ALLOW":
        decision = "ALLOW_WITH_MASKS"
    if break_glass_used and allowed:
        decision = f"{decision}_BREAK_GLASS"

    if denied_by:
        explanation = f"Denied by policy rule(s): {', '.join(denied_by)}."
    elif approval:
        explanation = f"Allowed conditionally; approval required by policy rule {approval['rule_id']}."
    elif masks or row_filter:
        explanation = "Allowed with masking or row filters."
    elif allowed_by:
        explanation = f"Allowed by policy rule(s): {', '.join(allowed_by)}."
    else:
        explanation = "Allowed by default; no active policy rule denied the request."

    return {
        "decision": decision,
        "allowed": allowed,
        "matched_rule_ids": [rule.id for rule in matched],
        "masks": masks,
        "row_filter": row_filter,
        "approval": approval,
        "break_glass": {
            "used": break_glass_used,
            "reason": req.break_glass_reason,
            "rule_ids": break_glass_rules,
        },
        "explanation": explanation,
    }


def _persist_policy_decision(db: Session, req: PolicyEvaluateRequest, result: Dict[str, Any]) -> PolicyDecisionLog:
    row = PolicyDecisionLog(
        id=_new_id("policy_decision"),
        principal=req.principal,
        action=req.action,
        resource_kind=req.resource_kind,
        resource_id=req.resource_id,
        decision=result["decision"],
        allowed=bool(result["allowed"]),
        matched_rule_ids=result.get("matched_rule_ids") or [],
        masks=result.get("masks") or [],
        row_filter=result.get("row_filter") or {},
        approval=result.get("approval") or {},
        break_glass=result.get("break_glass") or {},
        explanation=result.get("explanation") or "",
        context={
            "object_type_id": req.object_type_id,
            "purpose": req.purpose,
            "context": req.context or {},
        },
        created_at=_now(),
    )
    db.add(row)
    _audit(db, "policy.decision.evaluated", "policy_decision", row.id, _decision_dict(row), actor=req.principal)
    ops_control.record_ops_event(
        db,
        source="policy",
        event_type="policy.decision.evaluated",
        severity="high" if not row.allowed else "info",
        title=f"Policy {row.decision} for {req.action} on {req.resource_kind}",
        subject_type="policy_decision",
        subject_id=row.id,
        payload=_decision_dict(row),
        evaluate_alerts=True,
    )
    return row


def _timeline_row(kind: str, row_id: str, title: str, created_at: Optional[int], payload: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "kind": kind,
        "id": row_id,
        "title": title,
        "created_at": created_at or 0,
        "payload": payload,
    }


def _build_timeline(db: Session, *, subject_type: Optional[str], subject_id: Optional[str], object_type_id: Optional[str], object_id: Optional[str], limit: int) -> Dict[str, Any]:
    rows: List[Dict[str, Any]] = []
    ops_control._ensure_tables(db)

    q_events = db.query(ops_control.OpsEvent)
    if subject_type:
        q_events = q_events.filter(ops_control.OpsEvent.subject_type == subject_type)
    if subject_id:
        q_events = q_events.filter(ops_control.OpsEvent.subject_id == subject_id)
    if object_type_id:
        q_events = q_events.filter(ops_control.OpsEvent.object_type_id == object_type_id)
    if object_id:
        q_events = q_events.filter(ops_control.OpsEvent.object_id == object_id)
    for event in q_events.all():
        rows.append(_timeline_row("ops_event", event.id, event.title, event.created_at, _event_dict(event)))

    q_audit = db.query(models_action.AuditLog)
    if subject_type:
        q_audit = q_audit.filter(models_action.AuditLog.subject_type == subject_type)
    if subject_id:
        q_audit = q_audit.filter(models_action.AuditLog.subject_id == subject_id)
    for audit in q_audit.all():
        rows.append(_timeline_row("audit_log", audit.id, audit.event_type, audit.created_at, {
            "actor": audit.actor,
            "event_type": audit.event_type,
            "subject_type": audit.subject_type,
            "subject_id": audit.subject_id,
            "payload": audit.payload or {},
        }))

    if object_type_id and object_id:
        try:
            from . import decision_intelligence
            decision_intelligence.ObjectSnapshot.__table__.create(bind=db.get_bind(), checkfirst=True)
            snapshots = db.query(decision_intelligence.ObjectSnapshot).filter(
                decision_intelligence.ObjectSnapshot.object_type_id == object_type_id,
                decision_intelligence.ObjectSnapshot.object_id == object_id,
            ).all()
            for snapshot in snapshots:
                rows.append(_timeline_row("object_snapshot", snapshot.id, snapshot.event_type, snapshot.created_at, {
                    "object_type_id": snapshot.object_type_id,
                    "object_id": snapshot.object_id,
                    "seq": snapshot.seq,
                    "actor": snapshot.actor,
                    "properties": snapshot.properties or {},
                    "lineage": snapshot.lineage or {},
                }))
        except OperationalError:
            db.rollback()

        for incident in db.query(ops_control.Incident).all():
            linked = incident.linked_objects or []
            if any(ref.get("object_type_id") == object_type_id and ref.get("object_id") == object_id for ref in linked):
                rows.append(_timeline_row("incident", incident.id, incident.display_name, incident.created_at, ops_control._incident_dict(incident)))

    rows.sort(key=lambda item: (item["created_at"], item["kind"], item["id"]), reverse=True)
    return {
        "count": min(len(rows), max(1, limit)),
        "timeline": rows[: max(1, min(limit, 500))],
        "filters": {
            "subject_type": subject_type,
            "subject_id": subject_id,
            "object_type_id": object_type_id,
            "object_id": object_id,
        },
    }


def _graph_overview(db: Session, limit: int, principal: Optional[production_auth.Principal] = None) -> Dict[str, Any]:
    nodes: Dict[str, Dict[str, Any]] = {}
    edges: List[Dict[str, Any]] = []

    def add_node(kind: str, node_id: str, label: str, payload: Optional[Dict[str, Any]] = None) -> None:
        key = f"{kind}:{node_id}"
        nodes[key] = {"id": key, "kind": kind, "resource_id": node_id, "label": label, "payload": payload or {}}

    def add_edge(source: str, target: str, kind: str, label: Optional[str] = None) -> None:
        if source in nodes and target in nodes:
            edges.append({"source": source, "target": target, "kind": kind, "label": label or kind})

    for ot in semantic_scope.accessible_query(db, principal, models.ObjectType).limit(limit).all():
        add_node("object_type", ot.id, ot.display_name or ot.id)
    visible_objects = semantic_scope.accessible_query(db, principal, models.ObjectInstance).limit(limit).all()
    visible_object_ids = {obj.id for obj in visible_objects}
    for obj in visible_objects:
        label = (obj.properties or {}).get("name") or (obj.properties or {}).get("title") or obj.id
        add_node("object", obj.id, str(label), {"object_type_id": obj.object_type_id})
        add_edge(f"object_type:{obj.object_type_id}", f"object:{obj.id}", "has_instance")
        if obj.source_asset_id:
            add_node("dataset", obj.source_asset_id, obj.source_asset_id)
            add_edge(f"dataset:{obj.source_asset_id}", f"object:{obj.id}", "hydrates")
    for link in semantic_scope.accessible_query(db, principal, models.LinkInstance).limit(limit).all():
        add_edge(f"object:{link.source_object_id}", f"object:{link.target_object_id}", "object_link", link.link_type_id)
    for asset in semantic_scope.accessible_query(db, principal, models.DataAsset).limit(limit).all():
        add_node("dataset", asset.id, asset.display_name or asset.id, {"kind": asset.kind})
    for pipeline in semantic_scope.accessible_query(db, principal, models.PipelineDefinition).limit(limit).all():
        add_node("pipeline", pipeline.id, pipeline.display_name or pipeline.id)
        add_node("dataset", pipeline.input_asset_id, pipeline.input_asset_id)
        add_edge(f"dataset:{pipeline.input_asset_id}", f"pipeline:{pipeline.id}", "pipeline_input")
        if pipeline.output_asset_id:
            add_node("dataset", pipeline.output_asset_id, pipeline.output_asset_id)
            add_edge(f"pipeline:{pipeline.id}", f"dataset:{pipeline.output_asset_id}", "pipeline_output")
    ops_control._ensure_tables(db)
    accessible_projects = tenancy.accessible_project_ids(db, semantic_scope.effective_principal(principal), "view")
    for incident in db.query(ops_control.Incident).limit(limit).all():
        linked_ids = {str(ref.get("object_id")) for ref in (incident.linked_objects or []) if ref.get("object_id")}
        if accessible_projects is not None and (not linked_ids or not linked_ids.intersection(visible_object_ids)):
            continue
        add_node("incident", incident.id, incident.display_name, {"severity": incident.severity, "status": incident.status})
        for ref in incident.linked_objects or []:
            add_edge(f"incident:{incident.id}", f"object:{ref.get('object_id')}", "incident_object")

    return {
        "node_count": len(nodes),
        "edge_count": len(edges),
        "nodes": list(nodes.values()),
        "edges": edges[: max(1, min(limit * 3, 1000))],
        "summary": dict(Counter(node["kind"] for node in nodes.values())),
    }


@router.post("/events/publish")
def publish_event(body: EventPublishRequest, db: Session = Depends(get_db)):
    _ensure_tables(db)
    event = ops_control.record_ops_event(
        db,
        source=body.source,
        event_type=body.event_type,
        severity=body.severity,
        title=body.title,
        message=body.message,
        subject_type=body.subject_type,
        subject_id=body.subject_id,
        object_type_id=body.object_type_id,
        object_id=body.object_id,
        payload=body.payload,
        status=body.status,
        evaluate_alerts=body.evaluate_alerts,
    )
    _audit(db, "platform.event.published", "ops_event", event.id, _event_dict(event))
    db.commit()
    return _event_dict(event)


@router.get("/events")
def list_platform_events(
    source: Optional[str] = None,
    event_type: Optional[str] = None,
    severity: Optional[str] = None,
    status: Optional[str] = None,
    subject_type: Optional[str] = None,
    subject_id: Optional[str] = None,
    object_type_id: Optional[str] = None,
    object_id: Optional[str] = None,
    limit: int = Query(100, ge=1, le=1000),
    db: Session = Depends(get_db),
):
    _ensure_tables(db)
    q = db.query(ops_control.OpsEvent)
    for field, value in {
        "source": source,
        "event_type": event_type,
        "severity": severity,
        "status": status,
        "subject_type": subject_type,
        "subject_id": subject_id,
        "object_type_id": object_type_id,
        "object_id": object_id,
    }.items():
        if value is not None:
            q = q.filter(getattr(ops_control.OpsEvent, field) == value)
    rows = q.order_by(ops_control.OpsEvent.created_at.desc()).limit(limit).all()
    return {"count": len(rows), "events": [_event_dict(row) for row in rows]}


@router.get("/events/summary")
def events_summary(db: Session = Depends(get_db)):
    _ensure_tables(db)
    rows = db.query(ops_control.OpsEvent).all()
    return {
        "total": len(rows),
        "by_source": dict(Counter(row.source for row in rows)),
        "by_severity": dict(Counter(row.severity for row in rows)),
        "by_status": dict(Counter(row.status for row in rows)),
        "latest": [_event_dict(row) for row in sorted(rows, key=lambda item: item.created_at, reverse=True)[:10]],
    }


@router.post("/events/subscriptions", status_code=201)
def create_event_subscription(body: EventSubscriptionCreate, db: Session = Depends(get_db)):
    _ensure_tables(db)
    sub_id = body.id or _new_id("event_sub")
    if db.get(EventSubscription, sub_id):
        raise HTTPException(status_code=400, detail="EventSubscription already exists")
    now = _now()
    row = EventSubscription(
        id=sub_id,
        display_name=body.display_name,
        description=body.description,
        filters=body.filters,
        target=body.target,
        active=body.active,
        created_at=now,
        updated_at=now,
    )
    db.add(row)
    _audit(db, "platform.event_subscription.created", "event_subscription", sub_id, _subscription_dict(row))
    db.commit()
    return _subscription_dict(row)


@router.get("/events/subscriptions")
def list_event_subscriptions(db: Session = Depends(get_db)):
    _ensure_tables(db)
    rows = db.query(EventSubscription).order_by(EventSubscription.updated_at.desc()).all()
    return {"count": len(rows), "subscriptions": [_subscription_dict(row) for row in rows]}


@router.post("/events/subscriptions/{subscription_id}/evaluate")
def evaluate_event_subscription(subscription_id: str, limit: int = Query(100, ge=1, le=1000), db: Session = Depends(get_db)):
    _ensure_tables(db)
    sub = db.get(EventSubscription, subscription_id)
    if not sub:
        raise HTTPException(status_code=404, detail=f"EventSubscription '{subscription_id}' not found")
    events = [_event_dict(row) for row in db.query(ops_control.OpsEvent).order_by(ops_control.OpsEvent.created_at.desc()).limit(limit).all()]
    matches = [event for event in events if _matches_event_filters(event, sub.filters or {})]
    return {"subscription": _subscription_dict(sub), "match_count": len(matches), "events": matches}


@router.post("/search/query")
def search_query(body: SearchRequest, db: Session = Depends(get_db),
                 principal: production_auth.Principal = Depends(production_auth.require_permission("view"))):
    _ensure_tables(db)
    results = _search_resources(db, body.q.strip(), body.kinds, body.limit, body.include_payload, principal)
    return {"query": body.q, "count": len(results), "results": results}


@router.get("/search")
def search_get(q: str = "", kind: Optional[str] = None, limit: int = Query(25, ge=1, le=250), db: Session = Depends(get_db),
               principal: production_auth.Principal = Depends(production_auth.require_permission("view"))):
    kinds = [kind] if kind else []
    results = _search_resources(db, q.strip(), kinds, limit, False, principal)
    return {"query": q, "count": len(results), "results": results}


@router.get("/search/commands")
def search_commands():
    commands = [
        {"id": "open-search", "title": "Open Search Workspace", "route": "/workspace/search", "category": "navigation"},
        {"id": "open-graph", "title": "Open Graph Workspace", "route": "/workspace/graph", "category": "navigation"},
        {"id": "open-ops", "title": "Open Ops Control Plane", "route": "/workspace/ops", "category": "navigation"},
        {"id": "open-decision", "title": "Open Decision Intelligence", "route": "/workspace/decision", "category": "navigation"},
        {"id": "open-map", "title": "Open Map Workspace", "route": "/workspace/map", "category": "navigation"},
        {"id": "evaluate-alerts", "title": "Evaluate Alert Rules", "route": "/ops/alerts/evaluate", "category": "operation"},
        {"id": "validate-ontology", "title": "Validate Ontology", "route": "/ontology/validate", "category": "operation"},
    ]
    return {"count": len(commands), "commands": commands}


@router.post("/policies", status_code=201)
def create_policy(body: PolicyRuleCreate, db: Session = Depends(get_db)):
    _ensure_tables(db)
    effect = body.effect.upper()
    if effect not in POLICY_EFFECTS:
        raise HTTPException(status_code=422, detail=f"effect must be one of {sorted(POLICY_EFFECTS)}")
    policy_id = body.id or _new_id("policy")
    if db.get(PolicyRule, policy_id):
        raise HTTPException(status_code=400, detail="PolicyRule already exists")
    now = _now()
    row = PolicyRule(
        id=policy_id,
        display_name=body.display_name,
        description=body.description,
        effect=effect,
        principal=body.principal,
        action=body.action,
        resource_kind=body.resource_kind,
        resource_id=body.resource_id,
        object_type_id=body.object_type_id,
        purpose=body.purpose,
        condition=body.condition,
        mask_properties=body.mask_properties,
        row_filter=body.row_filter,
        approval=body.approval,
        break_glass_allowed=body.break_glass_allowed,
        priority=body.priority,
        active=body.active,
        created_at=now,
        updated_at=now,
    )
    db.add(row)
    _audit(db, "policy.rule.created", "policy_rule", row.id, _policy_dict(row))
    db.commit()
    return _policy_dict(row)


@router.get("/policies")
def list_policies(active: Optional[bool] = None, db: Session = Depends(get_db)):
    _ensure_tables(db)
    q = db.query(PolicyRule)
    if active is not None:
        q = q.filter(PolicyRule.active == active)
    rows = q.order_by(PolicyRule.priority.asc(), PolicyRule.created_at.desc()).all()
    return {"count": len(rows), "policies": [_policy_dict(row) for row in rows]}


@router.patch("/policies/{policy_id}")
def patch_policy(policy_id: str, body: PolicyRulePatch, db: Session = Depends(get_db)):
    _ensure_tables(db)
    row = db.get(PolicyRule, policy_id)
    if not row:
        raise HTTPException(status_code=404, detail=f"PolicyRule '{policy_id}' not found")
    patch = body.model_dump(exclude_unset=True)
    if "effect" in patch and patch["effect"] is not None:
        patch["effect"] = patch["effect"].upper()
        if patch["effect"] not in POLICY_EFFECTS:
            raise HTTPException(status_code=422, detail=f"effect must be one of {sorted(POLICY_EFFECTS)}")
    for field, value in patch.items():
        setattr(row, field, value)
    if patch:
        row.updated_at = _now()
    db.commit()
    return _policy_dict(row)


@router.post("/policies/evaluate")
def evaluate_policy(body: PolicyEvaluateRequest, db: Session = Depends(get_db)):
    _ensure_tables(db)
    rules = db.query(PolicyRule).filter(PolicyRule.active == True).all()  # noqa: E712
    result = _evaluate_policy_rules(rules, body)
    row = _persist_policy_decision(db, body, result)
    db.commit()
    return _decision_dict(row)


@router.post("/policies/simulate")
def simulate_policy(body: PolicySimulationRequest, db: Session = Depends(get_db)):
    _ensure_tables(db)
    existing = db.query(PolicyRule).filter(PolicyRule.active == True).all()  # noqa: E712
    now = _now()
    hypothetical: List[PolicyRule] = []
    for index, rule in enumerate(body.hypothetical_rules):
        effect = rule.effect.upper()
        if effect not in POLICY_EFFECTS:
            raise HTTPException(status_code=422, detail=f"effect must be one of {sorted(POLICY_EFFECTS)}")
        hypothetical.append(PolicyRule(
            id=rule.id or f"hypothetical_{index}",
            display_name=rule.display_name,
            description=rule.description,
            effect=effect,
            principal=rule.principal,
            action=rule.action,
            resource_kind=rule.resource_kind,
            resource_id=rule.resource_id,
            object_type_id=rule.object_type_id,
            purpose=rule.purpose,
            condition=rule.condition,
            mask_properties=rule.mask_properties,
            row_filter=rule.row_filter,
            approval=rule.approval,
            break_glass_allowed=rule.break_glass_allowed,
            priority=rule.priority,
            active=rule.active,
            created_at=now,
            updated_at=now,
        ))
    req = PolicyEvaluateRequest(**body.model_dump(exclude={"hypothetical_rules", "persist"}))
    result = _evaluate_policy_rules(existing + hypothetical, req)
    if body.persist:
        row = _persist_policy_decision(db, req, result)
        db.commit()
        return {"persisted": True, "decision": _decision_dict(row), "hypothetical_rule_count": len(hypothetical)}
    return {"persisted": False, "decision": result, "hypothetical_rule_count": len(hypothetical)}


@router.get("/policies/decisions")
def list_policy_decisions(principal: Optional[str] = None, resource_kind: Optional[str] = None, limit: int = Query(100, ge=1, le=1000), db: Session = Depends(get_db)):
    _ensure_tables(db)
    q = db.query(PolicyDecisionLog)
    if principal:
        q = q.filter(PolicyDecisionLog.principal == principal)
    if resource_kind:
        q = q.filter(PolicyDecisionLog.resource_kind == resource_kind)
    rows = q.order_by(PolicyDecisionLog.created_at.desc()).limit(limit).all()
    return {"count": len(rows), "decisions": [_decision_dict(row) for row in rows]}


@router.get("/activity/timeline")
def activity_timeline(
    subject_type: Optional[str] = None,
    subject_id: Optional[str] = None,
    object_type_id: Optional[str] = None,
    object_id: Optional[str] = None,
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
):
    _ensure_tables(db)
    return _build_timeline(db, subject_type=subject_type, subject_id=subject_id, object_type_id=object_type_id, object_id=object_id, limit=limit)


@router.get("/activity/objects/{object_type_id}/{object_id}/timeline")
def object_activity_timeline(object_type_id: str, object_id: str, limit: int = Query(100, ge=1, le=500), db: Session = Depends(get_db)):
    _ensure_tables(db)
    return _build_timeline(db, subject_type=None, subject_id=None, object_type_id=object_type_id, object_id=object_id, limit=limit)


@router.get("/graph/overview")
def graph_overview(limit: int = Query(200, ge=1, le=1000), db: Session = Depends(get_db),
                   principal: production_auth.Principal = Depends(production_auth.require_permission("view"))):
    _ensure_tables(db)
    return _graph_overview(db, limit, principal)

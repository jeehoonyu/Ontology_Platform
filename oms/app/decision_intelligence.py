"""
Local deterministic decision intelligence layer.

This module turns ontology objects into explainable, temporal, risk-scored,
mergeable, scenario-aware records without relying on external services.
"""
from __future__ import annotations

import copy
import difflib
import os
import re
import time
import uuid
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import Boolean, Integer, JSON, String
from sqlalchemy.orm import Mapped, Session, mapped_column

from . import models, models_action, production_auth, tenancy
from .database import Base, get_db

router = APIRouter(tags=["decision_intelligence"])


def _now() -> int:
    return int(time.time())


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def _ensure_object_snapshot_table(db: Session) -> None:
    """Support legacy standalone callers that create Base tables before this module is imported."""
    if os.getenv("APP_ENV", "").strip().lower() == "production":
        return
    ObjectSnapshot.__table__.create(bind=db.get_bind(), checkfirst=True)


class DecisionRule(Base):
    __tablename__ = "decision_rules"

    id: Mapped[str] = mapped_column(String, primary_key=True, index=True)
    project_id: Mapped[str] = mapped_column(String, default="default", server_default="default", index=True)
    display_name: Mapped[str] = mapped_column(String)
    description: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    object_type_id: Mapped[str] = mapped_column(String, index=True)
    expression: Mapped[dict] = mapped_column(JSON, default=dict)
    output_property: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    severity: Mapped[str] = mapped_column(String, default="info")
    recommended_actions: Mapped[list] = mapped_column(JSON, default=list)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[int] = mapped_column(Integer)
    updated_at: Mapped[int] = mapped_column(Integer)


class DecisionScorecard(Base):
    __tablename__ = "decision_scorecards"

    id: Mapped[str] = mapped_column(String, primary_key=True, index=True)
    project_id: Mapped[str] = mapped_column(String, default="default", server_default="default", index=True)
    display_name: Mapped[str] = mapped_column(String)
    description: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    object_type_id: Mapped[str] = mapped_column(String, index=True)
    features: Mapped[list] = mapped_column(JSON, default=list)
    thresholds: Mapped[dict] = mapped_column(JSON, default=dict)
    recommended_actions: Mapped[list] = mapped_column(JSON, default=list)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[int] = mapped_column(Integer)
    updated_at: Mapped[int] = mapped_column(Integer)


class DecisionRun(Base):
    __tablename__ = "decision_runs"

    id: Mapped[str] = mapped_column(String, primary_key=True, index=True)
    project_id: Mapped[str] = mapped_column(String, default="default", server_default="default", index=True)
    scope: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String, default="RUNNING")
    object_count: Mapped[int] = mapped_column(Integer, default=0)
    findings: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[int] = mapped_column(Integer)
    completed_at: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)


class ObjectSnapshot(Base):
    __tablename__ = "object_snapshots"

    id: Mapped[str] = mapped_column(String, primary_key=True, index=True)
    project_id: Mapped[str] = mapped_column(String, default="default", server_default="default", index=True)
    object_id: Mapped[str] = mapped_column(String, index=True)
    object_type_id: Mapped[str] = mapped_column(String, index=True)
    properties: Mapped[dict] = mapped_column(JSON, default=dict)
    lineage: Mapped[dict] = mapped_column(JSON, default=dict)
    event_type: Mapped[str] = mapped_column(String, index=True)
    actor: Mapped[str] = mapped_column(String, default="system")
    source_type: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    source_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    created_at: Mapped[int] = mapped_column(Integer)
    seq: Mapped[int] = mapped_column(Integer, default=1)


class EntityResolutionJob(Base):
    __tablename__ = "entity_resolution_jobs"

    id: Mapped[str] = mapped_column(String, primary_key=True, index=True)
    project_id: Mapped[str] = mapped_column(String, default="default", server_default="default", index=True)
    object_type_id: Mapped[str] = mapped_column(String, index=True)
    fields: Mapped[list] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String, default="RUNNING")
    created_at: Mapped[int] = mapped_column(Integer)
    completed_at: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    candidate_count: Mapped[int] = mapped_column(Integer, default=0)


class EntityCandidate(Base):
    __tablename__ = "entity_candidates"

    id: Mapped[str] = mapped_column(String, primary_key=True, index=True)
    project_id: Mapped[str] = mapped_column(String, default="default", server_default="default", index=True)
    job_id: Mapped[str] = mapped_column(String, index=True)
    object_type_id: Mapped[str] = mapped_column(String, index=True)
    object_ids: Mapped[list] = mapped_column(JSON, default=list)
    score: Mapped[int] = mapped_column(Integer, default=0)
    reasons: Mapped[list] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String, default="PENDING")
    merged_object_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    created_at: Mapped[int] = mapped_column(Integer)
    decided_at: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)


class DecisionScenario(Base):
    __tablename__ = "decision_scenarios"

    id: Mapped[str] = mapped_column(String, primary_key=True, index=True)
    project_id: Mapped[str] = mapped_column(String, default="default", server_default="default", index=True)
    display_name: Mapped[str] = mapped_column(String)
    description: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    seed_object_ids: Mapped[list] = mapped_column(JSON, default=list)
    overrides: Mapped[dict] = mapped_column(JSON, default=dict)
    propagation_rules: Mapped[list] = mapped_column(JSON, default=list)
    baseline: Mapped[dict] = mapped_column(JSON, default=dict)
    scenario_output: Mapped[dict] = mapped_column(JSON, default=dict)
    impact: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[int] = mapped_column(Integer)
    updated_at: Mapped[int] = mapped_column(Integer)


class DecisionRuleCreate(BaseModel):
    id: Optional[str] = None
    project_id: Optional[str] = None
    display_name: str
    description: Optional[str] = None
    object_type_id: str
    expression: Dict[str, Any] = Field(default_factory=dict)
    output_property: Optional[str] = None
    severity: str = "info"
    recommended_actions: List[Any] = Field(default_factory=list)
    active: bool = True


class DecisionScorecardCreate(BaseModel):
    id: Optional[str] = None
    project_id: Optional[str] = None
    display_name: str
    description: Optional[str] = None
    object_type_id: str
    features: List[Dict[str, Any]] = Field(default_factory=list)
    thresholds: Dict[str, Any] = Field(default_factory=dict)
    recommended_actions: List[Any] = Field(default_factory=list)
    active: bool = True


class DecisionEvaluateRequest(BaseModel):
    project_id: Optional[str] = None
    object_type_id: str
    filters: Any = Field(default_factory=dict)
    object_ids: List[str] = Field(default_factory=list)
    rule_ids: List[str] = Field(default_factory=list)
    scorecard_ids: List[str] = Field(default_factory=list)
    limit: int = 100
    persist_run: bool = True
    include_inactive: bool = False


class EntityResolutionJobRequest(BaseModel):
    project_id: Optional[str] = None
    object_type_id: str
    fields: List[str] = Field(default_factory=list)
    threshold: int = 70
    limit: int = 1000


class EntityAcceptRequest(BaseModel):
    actor: str = "entity_resolution"
    merged_object_id: Optional[str] = None


class EntityRejectRequest(BaseModel):
    actor: str = "entity_resolution"
    reason: Optional[str] = None


class EntitySplitRequest(BaseModel):
    actor: str = "entity_resolution"
    reason: Optional[str] = None


class DecisionScenarioRequest(BaseModel):
    id: Optional[str] = None
    project_id: str = "default"
    display_name: str = "Decision Scenario"
    description: Optional[str] = None
    seed_object_ids: List[str] = Field(default_factory=list)
    overrides: Dict[str, Dict[str, Any]] = Field(default_factory=dict)
    propagation_rules: List[Dict[str, Any]] = Field(default_factory=list)


class DecisionBootstrapRequest(BaseModel):
    object_type_id: Optional[str] = None
    project_id: str = "default"


def _object_dict(obj: models.ObjectInstance) -> Dict[str, Any]:
    return {
        "id": obj.id,
        "object_type_id": obj.object_type_id,
        "properties": obj.properties or {},
        "lineage": obj.lineage or {},
        "source_asset_id": obj.source_asset_id,
        "materialization_id": obj.materialization_id,
        "is_active": obj.is_active,
        "retired_at": obj.retired_at,
        "created_at": obj.created_at,
        "updated_at": obj.updated_at,
    }


def _rule_dict(rule: DecisionRule) -> Dict[str, Any]:
    return {
        "id": rule.id,
        "project_id": rule.project_id,
        "display_name": rule.display_name,
        "description": rule.description,
        "object_type_id": rule.object_type_id,
        "expression": rule.expression or {},
        "output_property": rule.output_property,
        "severity": rule.severity,
        "recommended_actions": rule.recommended_actions or [],
        "active": rule.active,
        "created_at": rule.created_at,
        "updated_at": rule.updated_at,
    }


def _scorecard_dict(scorecard: DecisionScorecard) -> Dict[str, Any]:
    return {
        "id": scorecard.id,
        "project_id": scorecard.project_id,
        "display_name": scorecard.display_name,
        "description": scorecard.description,
        "object_type_id": scorecard.object_type_id,
        "features": scorecard.features or [],
        "thresholds": scorecard.thresholds or {},
        "recommended_actions": scorecard.recommended_actions or [],
        "active": scorecard.active,
        "created_at": scorecard.created_at,
        "updated_at": scorecard.updated_at,
    }


def _snapshot_dict(snapshot: ObjectSnapshot) -> Dict[str, Any]:
    return {
        "id": snapshot.id,
        "project_id": snapshot.project_id,
        "object_id": snapshot.object_id,
        "object_type_id": snapshot.object_type_id,
        "properties": snapshot.properties or {},
        "lineage": snapshot.lineage or {},
        "event_type": snapshot.event_type,
        "actor": snapshot.actor,
        "source_type": snapshot.source_type,
        "source_id": snapshot.source_id,
        "created_at": snapshot.created_at,
        "seq": snapshot.seq,
    }


def _candidate_dict(candidate: EntityCandidate, db: Optional[Session] = None) -> Dict[str, Any]:
    payload = {
        "id": candidate.id,
        "project_id": candidate.project_id,
        "job_id": candidate.job_id,
        "object_type_id": candidate.object_type_id,
        "object_ids": candidate.object_ids or [],
        "score": candidate.score,
        "reasons": candidate.reasons or [],
        "status": candidate.status,
        "merged_object_id": candidate.merged_object_id,
        "created_at": candidate.created_at,
        "decided_at": candidate.decided_at,
    }
    if db:
        objects = []
        for object_id in candidate.object_ids or []:
            obj = db.get(models.ObjectInstance, object_id)
            if obj and obj.project_id == candidate.project_id:
                objects.append(_object_dict(obj))
        payload["objects"] = objects
    return payload


def _job_dict(job: EntityResolutionJob) -> Dict[str, Any]:
    return {
        "id": job.id,
        "project_id": job.project_id,
        "object_type_id": job.object_type_id,
        "fields": job.fields or [],
        "status": job.status,
        "candidate_count": job.candidate_count,
        "created_at": job.created_at,
        "completed_at": job.completed_at,
    }


def _scenario_dict(scenario: DecisionScenario) -> Dict[str, Any]:
    return {
        "id": scenario.id,
        "project_id": scenario.project_id,
        "display_name": scenario.display_name,
        "description": scenario.description,
        "seed_object_ids": scenario.seed_object_ids or [],
        "overrides": scenario.overrides or {},
        "propagation_rules": scenario.propagation_rules or [],
        "baseline": scenario.baseline or {},
        "scenario_output": scenario.scenario_output or {},
        "impact": scenario.impact or {},
        "created_at": scenario.created_at,
        "updated_at": scenario.updated_at,
    }


def _audit(db: Session, event_type: str, subject_type: str, subject_id: str, payload: Dict[str, Any], actor: str = "system") -> None:
    db.add(models_action.AuditLog(
        id=uuid.uuid4().hex,
        actor=actor,
        event_type=event_type,
        subject_type=subject_type,
        subject_id=subject_id,
        payload=payload,
    ))


def _object_type_project(db: Session, object_type_id: str) -> str:
    object_type = db.get(models.ObjectType, object_type_id)
    if not object_type:
        raise HTTPException(status_code=404, detail=f"ObjectType '{object_type_id}' not found")
    return object_type.project_id


def _request_project(db: Session, object_type_id: str, requested: Optional[str] = None) -> str:
    project_id = _object_type_project(db, object_type_id)
    if requested and requested != project_id:
        raise HTTPException(status_code=422, detail=f"ObjectType '{object_type_id}' is not in project '{requested}'")
    return project_id


def _scoped_query(db: Session, principal: production_auth.Principal, model: Any, permission: str = "view"):
    query = db.query(model)
    project_ids = tenancy.accessible_project_ids(db, principal, permission)
    if project_ids is not None:
        query = query.filter(model.project_id.in_(project_ids)) if project_ids else query.filter(model.project_id == "__none__")
    return query


def _get_object(db: Session, object_type_id: str, object_id: str, project_id: Optional[str] = None) -> models.ObjectInstance:
    obj = db.query(models.ObjectInstance).filter(
        models.ObjectInstance.id == object_id,
        models.ObjectInstance.object_type_id == object_type_id,
    ).first()
    if not obj:
        raise HTTPException(status_code=404, detail=f"ObjectInstance '{object_id}' not found")
    if project_id and obj.project_id != project_id:
        raise HTTPException(status_code=404, detail=f"ObjectInstance '{object_id}' not found")
    return obj


def _field_value(obj: models.ObjectInstance, field: Optional[str]) -> Any:
    if not field:
        return None
    field = field[1:] if field.startswith("$") else field
    record = _object_dict(obj)
    if field in record:
        return record[field]
    if field.startswith("properties."):
        value: Any = record["properties"]
        parts = field.split(".")[1:]
    elif field.startswith("lineage."):
        value = record["lineage"]
        parts = field.split(".")[1:]
    else:
        value = record["properties"]
        parts = field.split(".")
    for part in parts:
        if not isinstance(value, dict):
            return None
        value = value.get(part)
    return value


def _compare(left: Any, op: str, right: Any) -> bool:
    op = (op or "eq").lower()
    if op in {"eq", "equals", "=="}:
        return left == right
    if op in {"ne", "not_equals", "!=", "neq"}:
        return left != right
    if op == "contains":
        if isinstance(left, list):
            return right in left
        return str(right).lower() in str(left or "").lower()
    if op == "in":
        return left in (right or [])
    if op in {"exists", "not_null"}:
        return (left is not None) == bool(right if right is not None else True)
    if op == "truthy":
        return bool(left)
    try:
        l_num = float(left)
        r_num = float(right)
    except (TypeError, ValueError):
        return False
    if op in {"gt", ">"}:
        return l_num > r_num
    if op in {"gte", ">="}:
        return l_num >= r_num
    if op in {"lt", "<"}:
        return l_num < r_num
    if op in {"lte", "<="}:
        return l_num <= r_num
    return False


def _linked_count(db: Session, obj: models.ObjectInstance, expression: Dict[str, Any]) -> int:
    direction = str(expression.get("direction", "both")).lower()
    link_type_id = expression.get("link_type_id")
    query = db.query(models.LinkInstance).filter(models.LinkInstance.project_id == obj.project_id)
    if link_type_id:
        query = query.filter(models.LinkInstance.link_type_id == link_type_id)
    if direction == "outgoing":
        query = query.filter(models.LinkInstance.source_object_id == obj.id)
    elif direction == "incoming":
        query = query.filter(models.LinkInstance.target_object_id == obj.id)
    else:
        query = query.filter(
            (models.LinkInstance.source_object_id == obj.id) |
            (models.LinkInstance.target_object_id == obj.id)
        )
    return query.count()


def evaluate_expression(db: Session, obj: models.ObjectInstance, expression: Dict[str, Any]) -> bool:
    if not expression:
        return True
    op = str(expression.get("op", "eq")).lower()
    if op == "and":
        return all(evaluate_expression(db, obj, item) for item in expression.get("conditions", []))
    if op == "or":
        return any(evaluate_expression(db, obj, item) for item in expression.get("conditions", []))
    if op == "not":
        return not evaluate_expression(db, obj, expression.get("condition", {}))
    if op == "link_count":
        count = _linked_count(db, obj, expression)
        return _compare(count, str(expression.get("compare", expression.get("count_op", "gte"))), expression.get("value", 1))

    field = expression.get("field")
    if not field:
        return False
    if op == "exists" and "value" not in expression:
        return _field_value(obj, field) is not None
    return _compare(_field_value(obj, field), op, expression.get("value"))


def _matching_filters(db: Session, obj: models.ObjectInstance, filters: Any) -> bool:
    if not filters:
        return True
    if isinstance(filters, dict):
        for field, expected in filters.items():
            if isinstance(expected, dict):
                for op, value in expected.items():
                    if not _compare(_field_value(obj, field), op, value):
                        return False
            elif _field_value(obj, field) != expected:
                return False
        return True
    if isinstance(filters, list):
        return all(evaluate_expression(db, obj, item) for item in filters if isinstance(item, dict))
    return True


def _objects_for_scope(db: Session, body: DecisionEvaluateRequest) -> List[models.ObjectInstance]:
    project_id = body.project_id or _object_type_project(db, body.object_type_id)
    query = db.query(models.ObjectInstance).filter(
        models.ObjectInstance.project_id == project_id,
        models.ObjectInstance.object_type_id == body.object_type_id,
    )
    if body.object_ids:
        query = query.filter(models.ObjectInstance.id.in_(body.object_ids))
    if not body.include_inactive:
        query = query.filter(models.ObjectInstance.is_active.is_(True))
    limit = max(0, min(int(body.limit or 100), 10000))
    if not body.filters:
        return query.order_by(models.ObjectInstance.id.asc()).limit(limit).all()
    rows = query.order_by(models.ObjectInstance.id.asc()).all()
    if body.filters:
        rows = [row for row in rows if _matching_filters(db, row, body.filters)]
    return rows[:limit]


def _rules_for_object(db: Session, object_type_id: str, rule_ids: Optional[List[str]] = None, project_id: Optional[str] = None) -> List[DecisionRule]:
    effective_project = project_id or _object_type_project(db, object_type_id)
    query = db.query(DecisionRule).filter(DecisionRule.project_id == effective_project, DecisionRule.object_type_id == object_type_id, DecisionRule.active == True)  # noqa: E712
    if rule_ids:
        query = query.filter(DecisionRule.id.in_(rule_ids))
    return query.order_by(DecisionRule.updated_at.desc()).all()


def _scorecards_for_object(db: Session, object_type_id: str, scorecard_ids: Optional[List[str]] = None, project_id: Optional[str] = None) -> List[DecisionScorecard]:
    effective_project = project_id or _object_type_project(db, object_type_id)
    query = db.query(DecisionScorecard).filter(
        DecisionScorecard.project_id == effective_project,
        DecisionScorecard.object_type_id == object_type_id,
        DecisionScorecard.active == True,  # noqa: E712
    )
    if scorecard_ids:
        query = query.filter(DecisionScorecard.id.in_(scorecard_ids))
    return query.order_by(DecisionScorecard.updated_at.desc()).all()


def evaluate_rule(db: Session, rule: DecisionRule, obj: models.ObjectInstance) -> Dict[str, Any]:
    matched = evaluate_expression(db, obj, rule.expression or {})
    return {
        "rule_id": rule.id,
        "display_name": rule.display_name,
        "matched": matched,
        "severity": rule.severity,
        "recommended_actions": rule.recommended_actions or [],
        "expression": rule.expression or {},
    }


def _risk_band(score: int, thresholds: Dict[str, Any]) -> str:
    medium = int(thresholds.get("medium", 35))
    high = int(thresholds.get("high", 65))
    critical = int(thresholds.get("critical", 85))
    if score >= critical:
        return "critical"
    if score >= high:
        return "high"
    if score >= medium:
        return "medium"
    return "low"


def _severity_weight(severity: str) -> int:
    return {
        "critical": 45,
        "high": 30,
        "medium": 15,
        "low": 5,
        "info": 0,
    }.get(str(severity or "info").lower(), 0)


def _feature_matches(db: Session, obj: models.ObjectInstance, feature: Dict[str, Any], rules_by_id: Dict[str, DecisionRule]) -> bool:
    if feature.get("rule_id"):
        rule = rules_by_id.get(feature["rule_id"])
        return bool(rule and evaluate_expression(db, obj, rule.expression or {}))
    expression = feature.get("expression")
    if expression:
        return evaluate_expression(db, obj, expression)
    if feature.get("field"):
        return evaluate_expression(db, obj, {
            "field": feature.get("field"),
            "op": feature.get("op", "eq"),
            "value": feature.get("value"),
        })
    return False


def score_object(
    db: Session,
    obj: models.ObjectInstance,
    *,
    rule_ids: Optional[List[str]] = None,
    scorecard_ids: Optional[List[str]] = None,
    rule_catalog: Optional[List[DecisionRule]] = None,
    scorecard_catalog: Optional[List[DecisionScorecard]] = None,
) -> Dict[str, Any]:
    rules = rule_catalog if rule_catalog is not None else _rules_for_object(db, obj.object_type_id, rule_ids, obj.project_id)
    scorecards = scorecard_catalog if scorecard_catalog is not None else _scorecards_for_object(db, obj.object_type_id, scorecard_ids, obj.project_id)
    rules_by_id = {rule.id: rule for rule in rules}
    drivers: List[Dict[str, Any]] = []
    recommended_actions: List[Any] = []
    score = 0
    thresholds: Dict[str, Any] = {"medium": 35, "high": 65, "critical": 85}

    if scorecards:
        for scorecard in scorecards:
            thresholds = {**thresholds, **(scorecard.thresholds or {})}
            for feature in scorecard.features or []:
                if not _feature_matches(db, obj, feature, rules_by_id):
                    continue
                weight = int(feature.get("weight", 0))
                score += weight
                recommended_actions.extend(feature.get("recommended_actions") or [])
                drivers.append({
                    "source": "scorecard",
                    "scorecard_id": scorecard.id,
                    "feature": feature.get("reason") or feature.get("label") or feature.get("field") or feature.get("rule_id"),
                    "weight": weight,
                })
            recommended_actions.extend(scorecard.recommended_actions or [])
    else:
        for rule in rules:
            result = evaluate_rule(db, rule, obj)
            if not result["matched"]:
                continue
            weight = _severity_weight(rule.severity)
            score += weight
            recommended_actions.extend(rule.recommended_actions or [])
            drivers.append({
                "source": "rule",
                "rule_id": rule.id,
                "feature": rule.display_name,
                "severity": rule.severity,
                "weight": weight,
            })

    score = max(0, min(100, score))
    band = _risk_band(score, thresholds)
    unique_actions = []
    seen_actions = set()
    for action in recommended_actions:
        key = action if isinstance(action, str) else repr(sorted(action.items())) if isinstance(action, dict) else repr(action)
        if key not in seen_actions:
            seen_actions.add(key)
            unique_actions.append(action)

    explanation = (
        f"{obj.id} is {band} risk with score {score}. "
        + ("Top drivers: " + "; ".join(str(driver.get("feature")) for driver in drivers[:3]) if drivers else "No active risk drivers matched.")
    )
    return {
        "score": score,
        "band": band,
        "drivers": drivers,
        "recommended_actions": unique_actions,
        "explanation": explanation,
    }


def rule_results_for_object(
    db: Session,
    obj: models.ObjectInstance,
    rule_ids: Optional[List[str]] = None,
    rule_catalog: Optional[List[DecisionRule]] = None,
) -> List[Dict[str, Any]]:
    rules = rule_catalog if rule_catalog is not None else _rules_for_object(db, obj.object_type_id, rule_ids, obj.project_id)
    return [evaluate_rule(db, rule, obj) for rule in rules]


def evaluate_object_rows_inline(
    db: Session,
    rows: List[models.ObjectInstance],
    *,
    rule_ids: Optional[List[str]] = None,
    scorecard_ids: Optional[List[str]] = None,
    rule_catalog: Optional[List[DecisionRule]] = None,
    scorecard_catalog: Optional[List[DecisionScorecard]] = None,
) -> List[Dict[str, Any]]:
    if not rows:
        return []
    object_type_id = rows[0].object_type_id
    project_id = rows[0].project_id
    rules = rule_catalog if rule_catalog is not None else _rules_for_object(db, object_type_id, rule_ids, project_id)
    scorecards = scorecard_catalog if scorecard_catalog is not None else _scorecards_for_object(db, object_type_id, scorecard_ids, project_id)
    return [{
        "object": _object_dict(obj),
        "object_id": obj.id,
        "object_type_id": obj.object_type_id,
        "rule_results": rule_results_for_object(db, obj, rule_ids, rules),
        "risk": score_object(
            db, obj, rule_ids=rule_ids, scorecard_ids=scorecard_ids,
            rule_catalog=rules, scorecard_catalog=scorecards,
        ),
    } for obj in rows]


def _pending_duplicate_warnings(db: Session, object_id: str, project_id: str) -> List[Dict[str, Any]]:
    candidates = db.query(EntityCandidate).filter(EntityCandidate.project_id == project_id, EntityCandidate.status == "PENDING").all()
    return [
        _candidate_dict(candidate)
        for candidate in candidates
        if object_id in (candidate.object_ids or [])
    ][:5]


def explain_object_by_id(
    db: Session,
    object_type_id: str,
    object_id: str,
    *,
    rule_ids: Optional[List[str]] = None,
    scorecard_ids: Optional[List[str]] = None,
    project_id: Optional[str] = None,
) -> Dict[str, Any]:
    obj = _get_object(db, object_type_id, object_id, project_id)
    risk = score_object(db, obj, rule_ids=rule_ids, scorecard_ids=scorecard_ids)
    rule_results = rule_results_for_object(db, obj, rule_ids)
    snapshots = db.query(ObjectSnapshot).filter(
        ObjectSnapshot.project_id == obj.project_id,
        ObjectSnapshot.object_id == object_id,
        ObjectSnapshot.object_type_id == object_type_id,
    ).order_by(ObjectSnapshot.seq.asc()).all()
    temporal_summary = {
        "snapshot_count": len(snapshots),
        "first_seen": snapshots[0].created_at if snapshots else obj.created_at,
        "last_seen": snapshots[-1].created_at if snapshots else obj.updated_at,
        "last_event_type": snapshots[-1].event_type if snapshots else "current_state",
    }
    return {
        "object": _object_dict(obj),
        "risk": risk,
        "rule_results": rule_results,
        "temporal_summary": temporal_summary,
        "duplicate_warnings": _pending_duplicate_warnings(db, object_id, obj.project_id),
        "recommended_actions": risk["recommended_actions"],
        "explanation": risk["explanation"],
    }


def score_object_by_id(db: Session, object_type_id: str, object_id: str, scorecard_ids: Optional[List[str]] = None, project_id: Optional[str] = None) -> Dict[str, Any]:
    obj = _get_object(db, object_type_id, object_id, project_id)
    return score_object(db, obj, scorecard_ids=scorecard_ids)


def record_object_snapshot(
    db: Session,
    obj: models.ObjectInstance,
    *,
    event_type: str,
    actor: str = "system",
    source_type: Optional[str] = None,
    source_id: Optional[str] = None,
    extra_lineage: Optional[Dict[str, Any]] = None,
) -> ObjectSnapshot:
    _ensure_object_snapshot_table(db)
    last = db.query(ObjectSnapshot).filter(
        ObjectSnapshot.project_id == obj.project_id,
        ObjectSnapshot.object_id == obj.id,
        ObjectSnapshot.object_type_id == obj.object_type_id,
    ).order_by(ObjectSnapshot.seq.desc()).first()
    lineage = copy.deepcopy(obj.lineage or {})
    if extra_lineage:
        lineage.update(extra_lineage)
    snapshot = ObjectSnapshot(
        id=_new_id("snapshot"),
        project_id=obj.project_id,
        object_id=obj.id,
        object_type_id=obj.object_type_id,
        properties=copy.deepcopy(obj.properties or {}),
        lineage=lineage,
        event_type=event_type,
        actor=actor,
        source_type=source_type,
        source_id=source_id,
        created_at=_now(),
        seq=(last.seq + 1) if last else 1,
    )
    db.add(snapshot)
    return snapshot


def _dict_diff(before: Dict[str, Any], after: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    changed: Dict[str, Dict[str, Any]] = {}
    for key in sorted(set(before.keys()) | set(after.keys())):
        if before.get(key) != after.get(key):
            changed[key] = {"before": before.get(key), "after": after.get(key)}
    return changed


def _timeline(db: Session, object_type_id: str, object_id: str) -> List[Dict[str, Any]]:
    obj = _get_object(db, object_type_id, object_id)
    snapshots = db.query(ObjectSnapshot).filter(
        ObjectSnapshot.project_id == obj.project_id,
        ObjectSnapshot.object_id == object_id,
        ObjectSnapshot.object_type_id == object_type_id,
    ).order_by(ObjectSnapshot.seq.asc()).all()
    if snapshots:
        return [_snapshot_dict(snapshot) for snapshot in snapshots]
    return [{
        "id": "current_state",
        "object_id": obj.id,
        "object_type_id": obj.object_type_id,
        "properties": obj.properties or {},
        "lineage": obj.lineage or {},
        "event_type": "current_state",
        "actor": "system",
        "source_type": None,
        "source_id": None,
        "created_at": obj.updated_at,
        "seq": 0,
    }]


def _normalize_text(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").lower()).strip()


def _similarity(left: Any, right: Any) -> int:
    left_norm = _normalize_text(left)
    right_norm = _normalize_text(right)
    if not left_norm or not right_norm:
        return 0
    if left_norm == right_norm:
        return 100
    if left_norm in right_norm or right_norm in left_norm:
        return 88
    return int(round(difflib.SequenceMatcher(None, left_norm, right_norm).ratio() * 100))


def _default_resolution_fields(db: Session, object_type_id: str) -> List[str]:
    object_type = db.get(models.ObjectType, object_type_id)
    props = object_type.properties or {} if object_type else {}
    for preferred in ("name", "title", "label", "serial", "email"):
        if preferred in props:
            return [preferred]
    return list(props.keys())[:2] or ["name"]


def _build_entity_candidates(
    db: Session,
    job: EntityResolutionJob,
    *,
    threshold: int,
    limit: int,
) -> List[EntityCandidate]:
    rows = db.query(models.ObjectInstance).filter(
        models.ObjectInstance.project_id == job.project_id,
        models.ObjectInstance.object_type_id == job.object_type_id
    ).limit(max(2, min(limit, 5000))).all()
    fields = job.fields or _default_resolution_fields(db, job.object_type_id)
    candidates: List[EntityCandidate] = []
    for left_idx, left in enumerate(rows):
        for right in rows[left_idx + 1:]:
            field_scores = []
            reasons = []
            for field in fields:
                score = _similarity(_field_value(left, field), _field_value(right, field))
                field_scores.append(score)
                if score >= threshold:
                    reasons.append({
                        "field": field,
                        "score": score,
                        "left": _field_value(left, field),
                        "right": _field_value(right, field),
                    })
            if not field_scores:
                continue
            score = int(round(sum(field_scores) / len(field_scores)))
            if score < threshold:
                continue
            candidate = EntityCandidate(
                id=_new_id("candidate"),
                project_id=job.project_id,
                job_id=job.id,
                object_type_id=job.object_type_id,
                object_ids=[left.id, right.id],
                score=score,
                reasons=reasons or [{"field": ",".join(fields), "score": score, "left": left.id, "right": right.id}],
                status="PENDING",
                created_at=_now(),
            )
            db.add(candidate)
            candidates.append(candidate)
    return candidates


def _scenario_baseline(db: Session, seed_object_ids: List[str], project_id: str) -> Dict[str, Dict[str, Any]]:
    baseline = {}
    for object_id in seed_object_ids:
        obj = db.get(models.ObjectInstance, object_id)
        if obj and obj.project_id == project_id:
            baseline[obj.id] = _object_dict(obj)
    return baseline


def run_scenario_inline(
    db: Session,
    *,
    seed_object_ids: List[str],
    overrides: Dict[str, Dict[str, Any]],
    propagation_rules: Optional[List[Dict[str, Any]]] = None,
    project_id: str = "default",
) -> Dict[str, Any]:
    propagation_rules = propagation_rules or []
    baseline = _scenario_baseline(db, seed_object_ids, project_id)
    scenario_output = copy.deepcopy(baseline)

    for object_id, patch in (overrides or {}).items():
        obj = db.get(models.ObjectInstance, object_id)
        if not obj or obj.project_id != project_id:
            continue
        if object_id not in scenario_output:
            scenario_output[object_id] = _object_dict(obj)
            baseline[object_id] = _object_dict(obj)
        scenario_output[object_id]["properties"] = {
            **(scenario_output[object_id].get("properties") or {}),
            **(patch or {}),
        }

    for rule in propagation_rules:
        link_type_id = rule.get("link_type_id")
        direction = str(rule.get("direction", "both")).lower()
        set_values = rule.get("set") or {}
        impacted_ids = set(seed_object_ids) | set((overrides or {}).keys())
        query = db.query(models.LinkInstance).filter(models.LinkInstance.project_id == project_id)
        if link_type_id:
            query = query.filter(models.LinkInstance.link_type_id == link_type_id)
        for link in query.all():
            targets = []
            if direction in {"outgoing", "both"} and link.source_object_id in impacted_ids:
                targets.append(link.target_object_id)
            if direction in {"incoming", "both"} and link.target_object_id in impacted_ids:
                targets.append(link.source_object_id)
            for target_id in targets:
                obj = db.get(models.ObjectInstance, target_id)
                if not obj or obj.project_id != project_id:
                    continue
                if target_id not in scenario_output:
                    baseline[target_id] = _object_dict(obj)
                    scenario_output[target_id] = _object_dict(obj)
                scenario_output[target_id]["properties"] = {
                    **(scenario_output[target_id].get("properties") or {}),
                    **set_values,
                    "scenario_impacted": True,
                }

    by_object = {}
    for object_id, scenario_obj in scenario_output.items():
        before = (baseline.get(object_id) or {}).get("properties", {})
        after = scenario_obj.get("properties", {})
        changes = _dict_diff(before, after)
        if changes:
            by_object[object_id] = {"properties": changes}

    return {
        "baseline": baseline,
        "scenario_output": scenario_output,
        "impact": {
            "changed_object_count": len(by_object),
            "changed_object_ids": sorted(by_object.keys()),
            "by_object": by_object,
        },
    }


def build_decision_context(db: Session, context: Dict[str, Any], project_id: Optional[str] = None) -> Dict[str, Any]:
    object_risk = []
    duplicate_warnings = []
    for pack in context.get("packs", []):
        object_type_id = pack.get("object_type_id")
        for obj_ref in (pack.get("objects") or [])[:5]:
            object_id = obj_ref.get("id")
            if not object_id:
                continue
            try:
                explanation = explain_object_by_id(db, object_type_id, object_id, project_id=project_id)
            except HTTPException:
                continue
            object_risk.append({
                "object_id": object_id,
                "object_type_id": object_type_id,
                "score": explanation["risk"]["score"],
                "band": explanation["risk"]["band"],
                "drivers": explanation["risk"]["drivers"][:3],
                "explanation": explanation["risk"]["explanation"],
            })
            duplicate_warnings.extend(explanation.get("duplicate_warnings", []))
    high_risk = [item for item in object_risk if item["band"] in {"high", "critical"}]
    return {
        "object_risk": object_risk,
        "high_risk_object_ids": [item["object_id"] for item in high_risk],
        "duplicate_warnings": duplicate_warnings[:10],
    }


@router.post("/decision/bootstrap")
def bootstrap_decision_layer(body: DecisionBootstrapRequest = DecisionBootstrapRequest(), principal: production_auth.Principal = Depends(production_auth.require_permission("edit")), db: Session = Depends(get_db)):
    tenancy.assert_project_permission(db, principal, body.project_id, "edit")
    object_type_id = body.object_type_id
    if not object_type_id:
        object_type = db.query(models.ObjectType).filter(models.ObjectType.project_id == body.project_id).first()
        if not object_type:
            raise HTTPException(status_code=404, detail=f"No object types available in project '{body.project_id}'")
        object_type_id = object_type.id
    project_id = _request_project(db, object_type_id, body.project_id)

    now = _now()
    created = []
    rule_specs = [
        {
            "id": f"{object_type_id}_status_degraded",
            "display_name": "Status is degraded",
            "expression": {"field": "status", "op": "eq", "value": "DEGRADED"},
            "severity": "high",
            "recommended_actions": ["inspect_object", "stage_remediation_action"],
        },
        {
            "id": f"{object_type_id}_criticality_high",
            "display_name": "Criticality is high",
            "expression": {"field": "criticality", "op": "eq", "value": "high"},
            "severity": "medium",
            "recommended_actions": ["prioritize_review"],
        },
    ]
    for spec in rule_specs:
        if db.get(DecisionRule, spec["id"]):
            continue
        rule = DecisionRule(
            id=spec["id"],
            project_id=project_id,
            display_name=spec["display_name"],
            description="Default local decision intelligence rule.",
            object_type_id=object_type_id,
            expression=spec["expression"],
            severity=spec["severity"],
            recommended_actions=spec["recommended_actions"],
            active=True,
            created_at=now,
            updated_at=now,
        )
        db.add(rule)
        created.append(rule.id)

    scorecard_id = f"{object_type_id}_default_risk"
    if not db.get(DecisionScorecard, scorecard_id):
        scorecard = DecisionScorecard(
            id=scorecard_id,
            project_id=project_id,
            display_name="Default Risk Scorecard",
            description="Default local scorecard for operational risk.",
            object_type_id=object_type_id,
            features=[
                {"rule_id": f"{object_type_id}_status_degraded", "weight": 55, "reason": "Object is degraded"},
                {"rule_id": f"{object_type_id}_criticality_high", "weight": 35, "reason": "Object is high criticality"},
            ],
            thresholds={"medium": 35, "high": 65, "critical": 85},
            recommended_actions=["review_timeline", "check_duplicates"],
            active=True,
            created_at=now,
            updated_at=now,
        )
        db.add(scorecard)
        created.append(scorecard.id)
    _audit(db, "decision.bootstrap", "object_type", object_type_id, {"project_id": project_id, "created": created}, actor=principal.id)
    db.commit()
    return {"object_type_id": object_type_id, "created": created}


@router.post("/decision/rules")
def create_decision_rule(body: DecisionRuleCreate, principal: production_auth.Principal = Depends(production_auth.require_permission("edit")), db: Session = Depends(get_db)):
    project_id = _request_project(db, body.object_type_id, body.project_id)
    tenancy.assert_project_permission(db, principal, project_id, "edit")
    rule_id = body.id or _new_id("rule")
    if db.get(DecisionRule, rule_id):
        raise HTTPException(status_code=400, detail="DecisionRule already exists")
    now = _now()
    rule = DecisionRule(
        id=rule_id,
        project_id=project_id,
        display_name=body.display_name,
        description=body.description,
        object_type_id=body.object_type_id,
        expression=body.expression,
        output_property=body.output_property,
        severity=body.severity,
        recommended_actions=body.recommended_actions,
        active=body.active,
        created_at=now,
        updated_at=now,
    )
    db.add(rule)
    _audit(db, "decision.rule.created", "decision_rule", rule.id, _rule_dict(rule), actor=principal.id)
    db.commit()
    db.refresh(rule)
    return _rule_dict(rule)


@router.get("/decision/rules")
def list_decision_rules(
    object_type_id: Optional[str] = None,
    project_id: Optional[str] = None,
    active_only: bool = True,
    principal: production_auth.Principal = Depends(production_auth.require_permission("view")),
    db: Session = Depends(get_db),
):
    query = _scoped_query(db, principal, DecisionRule)
    if project_id:
        tenancy.assert_project_permission(db, principal, project_id, "view")
        query = query.filter(DecisionRule.project_id == project_id)
    if object_type_id:
        object_project = _request_project(db, object_type_id, project_id)
        tenancy.assert_project_permission(db, principal, object_project, "view")
        query = query.filter(DecisionRule.object_type_id == object_type_id)
    if active_only:
        query = query.filter(DecisionRule.active == True)  # noqa: E712
    return [_rule_dict(rule) for rule in query.order_by(DecisionRule.updated_at.desc()).all()]


@router.post("/decision/scorecards")
def create_decision_scorecard(body: DecisionScorecardCreate, principal: production_auth.Principal = Depends(production_auth.require_permission("edit")), db: Session = Depends(get_db)):
    project_id = _request_project(db, body.object_type_id, body.project_id)
    tenancy.assert_project_permission(db, principal, project_id, "edit")
    scorecard_id = body.id or _new_id("scorecard")
    if db.get(DecisionScorecard, scorecard_id):
        raise HTTPException(status_code=400, detail="DecisionScorecard already exists")
    now = _now()
    scorecard = DecisionScorecard(
        id=scorecard_id,
        project_id=project_id,
        display_name=body.display_name,
        description=body.description,
        object_type_id=body.object_type_id,
        features=body.features,
        thresholds=body.thresholds,
        recommended_actions=body.recommended_actions,
        active=body.active,
        created_at=now,
        updated_at=now,
    )
    db.add(scorecard)
    _audit(db, "decision.scorecard.created", "decision_scorecard", scorecard.id, _scorecard_dict(scorecard), actor=principal.id)
    db.commit()
    db.refresh(scorecard)
    return _scorecard_dict(scorecard)


@router.get("/decision/scorecards")
def list_decision_scorecards(
    object_type_id: Optional[str] = None,
    project_id: Optional[str] = None,
    active_only: bool = True,
    principal: production_auth.Principal = Depends(production_auth.require_permission("view")),
    db: Session = Depends(get_db),
):
    query = _scoped_query(db, principal, DecisionScorecard)
    if project_id:
        tenancy.assert_project_permission(db, principal, project_id, "view")
        query = query.filter(DecisionScorecard.project_id == project_id)
    if object_type_id:
        object_project = _request_project(db, object_type_id, project_id)
        tenancy.assert_project_permission(db, principal, object_project, "view")
        query = query.filter(DecisionScorecard.object_type_id == object_type_id)
    if active_only:
        query = query.filter(DecisionScorecard.active == True)  # noqa: E712
    return [_scorecard_dict(scorecard) for scorecard in query.order_by(DecisionScorecard.updated_at.desc()).all()]


def evaluate_decision_scope_inline(body: DecisionEvaluateRequest, db: Session) -> Dict[str, Any]:
    project_id = _request_project(db, body.object_type_id, body.project_id)
    body = body.model_copy(update={"project_id": project_id})
    rows = _objects_for_scope(db, body)
    findings = evaluate_object_rows_inline(
        db, rows, rule_ids=body.rule_ids, scorecard_ids=body.scorecard_ids,
    )
    payload = {
        "id": _new_id("decision_run"),
        "project_id": project_id,
        "scope": body.model_dump(),
        "status": "SUCCESS",
        "object_count": len(rows),
        "findings": findings,
        "created_at": _now(),
        "completed_at": _now(),
    }
    if body.persist_run:
        run = DecisionRun(**payload)
        db.add(run)
        _audit(db, "decision.evaluate", "decision_run", run.id, {"object_count": len(rows)})
        try:
            from . import ops_control
            bands = [item.get("risk", {}).get("band") for item in findings]
            severity = "critical" if "critical" in bands else "high" if "high" in bands else "medium" if "medium" in bands else "info"
            ops_control.record_ops_event(
                db,
                project_id=project_id,
                source="decision",
                event_type="decision.evaluate",
                severity=severity,
                title=f"Decision evaluation completed for {body.object_type_id}",
                subject_type="decision_run",
                subject_id=run.id,
                object_type_id=body.object_type_id,
                payload={"object_count": len(rows), "bands": bands},
            )
        except Exception:
            pass
        db.commit()
        db.refresh(run)
        payload["id"] = run.id
    return payload


@router.post("/decision/evaluate")
def evaluate_decision_scope(body: DecisionEvaluateRequest, principal: production_auth.Principal = Depends(production_auth.require_permission("execute")), db: Session = Depends(get_db)):
    project_id = _request_project(db, body.object_type_id, body.project_id)
    tenancy.assert_project_permission(db, principal, project_id, "execute")
    return evaluate_decision_scope_inline(body.model_copy(update={"project_id": project_id}), db)


@router.get("/decision/objects/{object_type_id}/{object_id}/explain")
def explain_decision_object(object_type_id: str, object_id: str, principal: production_auth.Principal = Depends(production_auth.require_permission("view")), db: Session = Depends(get_db)):
    obj = _get_object(db, object_type_id, object_id)
    tenancy.assert_project_permission(db, principal, obj.project_id, "view")
    return explain_object_by_id(db, object_type_id, object_id)


@router.get("/temporal/objects/{object_type_id}/{object_id}/timeline")
def object_timeline(object_type_id: str, object_id: str, principal: production_auth.Principal = Depends(production_auth.require_permission("view")), db: Session = Depends(get_db)):
    obj = _get_object(db, object_type_id, object_id)
    tenancy.assert_project_permission(db, principal, obj.project_id, "view")
    return {
        "object_type_id": object_type_id,
        "object_id": object_id,
        "timeline": _timeline(db, object_type_id, object_id),
    }


@router.get("/temporal/objects/{object_type_id}/{object_id}/diff")
def object_diff(
    object_type_id: str,
    object_id: str,
    from_seq: Optional[int] = Query(default=None),
    to_seq: Optional[int] = Query(default=None),
    principal: production_auth.Principal = Depends(production_auth.require_permission("view")),
    db: Session = Depends(get_db),
):
    obj = _get_object(db, object_type_id, object_id)
    tenancy.assert_project_permission(db, principal, obj.project_id, "view")
    timeline = _timeline(db, object_type_id, object_id)
    if not timeline:
        raise HTTPException(status_code=404, detail="No timeline available")
    by_seq = {item["seq"]: item for item in timeline}
    if to_seq is None:
        to_snap = timeline[-1]
    else:
        to_snap = by_seq.get(to_seq)
    if not to_snap:
        raise HTTPException(status_code=404, detail=f"Snapshot seq '{to_seq}' not found")
    if from_seq is None:
        idx = timeline.index(to_snap)
        from_snap = timeline[idx - 1] if idx > 0 else {"seq": 0, "properties": {}, "lineage": {}}
    else:
        from_snap = by_seq.get(from_seq)
    if not from_snap:
        raise HTTPException(status_code=404, detail=f"Snapshot seq '{from_seq}' not found")
    return {
        "object_type_id": object_type_id,
        "object_id": object_id,
        "from_seq": from_snap["seq"],
        "to_seq": to_snap["seq"],
        "before": from_snap,
        "after": to_snap,
        "changed": {
            "properties": _dict_diff(from_snap.get("properties") or {}, to_snap.get("properties") or {}),
            "lineage": _dict_diff(from_snap.get("lineage") or {}, to_snap.get("lineage") or {}),
        },
    }


@router.post("/entity-resolution/jobs")
def create_entity_resolution_job(body: EntityResolutionJobRequest, principal: production_auth.Principal = Depends(production_auth.require_permission("edit")), db: Session = Depends(get_db)):
    project_id = _request_project(db, body.object_type_id, body.project_id)
    tenancy.assert_project_permission(db, principal, project_id, "edit")
    now = _now()
    job = EntityResolutionJob(
        id=_new_id("er_job"),
        project_id=project_id,
        object_type_id=body.object_type_id,
        fields=body.fields or _default_resolution_fields(db, body.object_type_id),
        status="RUNNING",
        created_at=now,
    )
    db.add(job)
    candidates = _build_entity_candidates(db, job, threshold=body.threshold, limit=body.limit)
    job.status = "COMPLETED"
    job.completed_at = _now()
    job.candidate_count = len(candidates)
    _audit(db, "entity_resolution.job.completed", "entity_resolution_job", job.id, {"project_id": project_id, "candidate_count": len(candidates)}, actor=principal.id)
    db.commit()
    db.refresh(job)
    return {**_job_dict(job), "candidates": [_candidate_dict(candidate, db) for candidate in candidates]}


@router.get("/entity-resolution/jobs")
def list_entity_resolution_jobs(project_id: Optional[str] = None, principal: production_auth.Principal = Depends(production_auth.require_permission("view")), db: Session = Depends(get_db)):
    query = _scoped_query(db, principal, EntityResolutionJob)
    if project_id:
        tenancy.assert_project_permission(db, principal, project_id, "view")
        query = query.filter(EntityResolutionJob.project_id == project_id)
    return [_job_dict(job) for job in query.order_by(EntityResolutionJob.created_at.desc()).all()]


@router.get("/entity-resolution/jobs/{job_id}/candidates")
def list_entity_resolution_candidates(job_id: str, principal: production_auth.Principal = Depends(production_auth.require_permission("view")), db: Session = Depends(get_db)):
    job = db.get(EntityResolutionJob, job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"EntityResolutionJob '{job_id}' not found")
    tenancy.assert_project_permission(db, principal, job.project_id, "view")
    candidates = db.query(EntityCandidate).filter(EntityCandidate.project_id == job.project_id, EntityCandidate.job_id == job_id).order_by(EntityCandidate.score.desc()).all()
    return {
        "job": _job_dict(job),
        "candidates": [_candidate_dict(candidate, db) for candidate in candidates],
    }


@router.post("/entity-resolution/candidates/{candidate_id}/accept")
def accept_entity_candidate(candidate_id: str, body: EntityAcceptRequest = EntityAcceptRequest(), principal: production_auth.Principal = Depends(production_auth.require_permission("execute")), db: Session = Depends(get_db)):
    candidate = db.get(EntityCandidate, candidate_id)
    if not candidate:
        raise HTTPException(status_code=404, detail=f"EntityCandidate '{candidate_id}' not found")
    tenancy.assert_project_permission(db, principal, candidate.project_id, "execute")
    if candidate.status != "PENDING":
        raise HTTPException(status_code=409, detail=f"Candidate is already {candidate.status}")
    object_ids = candidate.object_ids or []
    if len(object_ids) < 2:
        raise HTTPException(status_code=422, detail="Candidate must contain at least two objects")
    canonical_id = body.merged_object_id or object_ids[0]
    canonical = db.get(models.ObjectInstance, canonical_id)
    if not canonical or canonical.project_id != candidate.project_id:
        raise HTTPException(status_code=404, detail=f"ObjectInstance '{canonical_id}' not found")
    conflicts = {}
    for object_id in object_ids:
        if object_id == canonical_id:
            continue
        duplicate = db.get(models.ObjectInstance, object_id)
        if not duplicate or duplicate.project_id != candidate.project_id:
            continue
        for key, value in (duplicate.properties or {}).items():
            if key not in (canonical.properties or {}) or (canonical.properties or {}).get(key) in {None, ""}:
                canonical.properties = {**(canonical.properties or {}), key: value}
            elif (canonical.properties or {}).get(key) != value:
                conflicts.setdefault(object_id, {})[key] = value
        duplicate.lineage = {
            **(duplicate.lineage or {}),
            "merged_into": canonical_id,
            "entity_candidate_id": candidate.id,
            "resolution_status": "MERGED",
        }
        duplicate.updated_at = _now()
        record_object_snapshot(
            db,
            duplicate,
            event_type="entity_resolution.merged_into",
            actor=principal.id,
            source_type="entity_candidate",
            source_id=candidate.id,
        )
    canonical.lineage = {
        **(canonical.lineage or {}),
        "entity_candidate_id": candidate.id,
        "merge_conflicts": conflicts,
        "resolution_status": "CANONICAL",
    }
    canonical.updated_at = _now()
    record_object_snapshot(
        db,
        canonical,
        event_type="entity_resolution.merged",
        actor=principal.id,
        source_type="entity_candidate",
        source_id=candidate.id,
    )
    candidate.status = "ACCEPTED"
    candidate.merged_object_id = canonical_id
    candidate.decided_at = _now()
    _audit(db, "entity_resolution.candidate.accepted", "entity_candidate", candidate.id, {"project_id": candidate.project_id, "merged_object_id": canonical_id}, actor=principal.id)
    db.commit()
    db.refresh(candidate)
    return _candidate_dict(candidate, db)


@router.post("/entity-resolution/candidates/{candidate_id}/reject")
def reject_entity_candidate(candidate_id: str, body: EntityRejectRequest = EntityRejectRequest(), principal: production_auth.Principal = Depends(production_auth.require_permission("execute")), db: Session = Depends(get_db)):
    candidate = db.get(EntityCandidate, candidate_id)
    if not candidate:
        raise HTTPException(status_code=404, detail=f"EntityCandidate '{candidate_id}' not found")
    tenancy.assert_project_permission(db, principal, candidate.project_id, "execute")
    if candidate.status != "PENDING":
        raise HTTPException(status_code=409, detail=f"Candidate is already {candidate.status}")
    candidate.status = "REJECTED"
    candidate.decided_at = _now()
    _audit(db, "entity_resolution.candidate.rejected", "entity_candidate", candidate.id, {"project_id": candidate.project_id, "reason": body.reason}, actor=principal.id)
    db.commit()
    db.refresh(candidate)
    return _candidate_dict(candidate, db)


@router.post("/entity-resolution/objects/{object_id}/split")
def split_entity_object(object_id: str, body: EntitySplitRequest = EntitySplitRequest(), principal: production_auth.Principal = Depends(production_auth.require_permission("execute")), db: Session = Depends(get_db)):
    obj = db.get(models.ObjectInstance, object_id)
    if not obj:
        raise HTTPException(status_code=404, detail=f"ObjectInstance '{object_id}' not found")
    tenancy.assert_project_permission(db, principal, obj.project_id, "execute")
    lineage = dict(obj.lineage or {})
    lineage.pop("merged_into", None)
    lineage.pop("merge_conflicts", None)
    lineage["resolution_status"] = "SPLIT"
    lineage["split_reason"] = body.reason
    obj.lineage = lineage
    obj.updated_at = _now()
    record_object_snapshot(
        db,
        obj,
        event_type="entity_resolution.split",
        actor=principal.id,
        source_type="entity_resolution",
        source_id=object_id,
    )
    _audit(db, "entity_resolution.object.split", "object_instance", object_id, {"project_id": obj.project_id, "reason": body.reason}, actor=principal.id)
    db.commit()
    db.refresh(obj)
    return _object_dict(obj)


@router.post("/decision/scenarios")
def create_decision_scenario(body: DecisionScenarioRequest, principal: production_auth.Principal = Depends(production_auth.require_permission("edit")), db: Session = Depends(get_db)):
    tenancy.assert_project_permission(db, principal, body.project_id, "edit")
    referenced_ids = set(body.seed_object_ids) | set(body.overrides.keys())
    for object_id in referenced_ids:
        obj = db.get(models.ObjectInstance, object_id)
        if not obj or obj.project_id != body.project_id:
            raise HTTPException(status_code=422, detail=f"ObjectInstance '{object_id}' is not in project '{body.project_id}'")
    scenario_id = body.id or _new_id("scenario")
    if db.get(DecisionScenario, scenario_id):
        raise HTTPException(status_code=400, detail="DecisionScenario already exists")
    result = run_scenario_inline(
        db,
        seed_object_ids=body.seed_object_ids,
        overrides=body.overrides,
        propagation_rules=body.propagation_rules,
        project_id=body.project_id,
    )
    now = _now()
    scenario = DecisionScenario(
        id=scenario_id,
        project_id=body.project_id,
        display_name=body.display_name,
        description=body.description,
        seed_object_ids=body.seed_object_ids,
        overrides=body.overrides,
        propagation_rules=body.propagation_rules,
        baseline=result["baseline"],
        scenario_output=result["scenario_output"],
        impact=result["impact"],
        created_at=now,
        updated_at=now,
    )
    db.add(scenario)
    _audit(db, "decision.scenario.created", "decision_scenario", scenario.id, {"project_id": body.project_id, "changed_object_count": result["impact"]["changed_object_count"]}, actor=principal.id)
    try:
        from . import ops_control
        changed = int(result["impact"].get("changed_object_count") or 0)
        ops_control.record_ops_event(
            db,
            project_id=body.project_id,
            source="decision",
            event_type="decision.scenario.created",
            severity="high" if changed else "info",
            title=f"Scenario {scenario.display_name} created",
            subject_type="decision_scenario",
            subject_id=scenario.id,
            payload={"changed_object_count": changed, "seed_object_ids": scenario.seed_object_ids or []},
        )
    except Exception:
        pass
    db.commit()
    db.refresh(scenario)
    return _scenario_dict(scenario)


@router.get("/decision/scenarios/{scenario_id}")
def get_decision_scenario(scenario_id: str, principal: production_auth.Principal = Depends(production_auth.require_permission("view")), db: Session = Depends(get_db)):
    scenario = db.get(DecisionScenario, scenario_id)
    if not scenario:
        raise HTTPException(status_code=404, detail=f"DecisionScenario '{scenario_id}' not found")
    tenancy.assert_project_permission(db, principal, scenario.project_id, "view")
    return _scenario_dict(scenario)


@router.post("/decision/scenarios/{scenario_id}/run")
def run_decision_scenario(scenario_id: str, principal: production_auth.Principal = Depends(production_auth.require_permission("execute")), db: Session = Depends(get_db)):
    scenario = db.get(DecisionScenario, scenario_id)
    if not scenario:
        raise HTTPException(status_code=404, detail=f"DecisionScenario '{scenario_id}' not found")
    tenancy.assert_project_permission(db, principal, scenario.project_id, "execute")
    result = run_scenario_inline(
        db,
        seed_object_ids=scenario.seed_object_ids or [],
        overrides=scenario.overrides or {},
        propagation_rules=scenario.propagation_rules or [],
        project_id=scenario.project_id,
    )
    scenario.baseline = result["baseline"]
    scenario.scenario_output = result["scenario_output"]
    scenario.impact = result["impact"]
    scenario.updated_at = _now()
    _audit(db, "decision.scenario.ran", "decision_scenario", scenario.id, {"project_id": scenario.project_id, "changed_object_count": result["impact"]["changed_object_count"]}, actor=principal.id)
    try:
        from . import ops_control
        changed = int(result["impact"].get("changed_object_count") or 0)
        ops_control.record_ops_event(
            db,
            project_id=scenario.project_id,
            source="decision",
            event_type="decision.scenario.ran",
            severity="high" if changed else "info",
            title=f"Scenario {scenario.display_name} ran",
            subject_type="decision_scenario",
            subject_id=scenario.id,
            payload={"changed_object_count": changed, "seed_object_ids": scenario.seed_object_ids or []},
        )
    except Exception:
        pass
    db.commit()
    db.refresh(scenario)
    return _scenario_dict(scenario)

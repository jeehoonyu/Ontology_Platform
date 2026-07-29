"""Operational health, governance, and generated-view services for the ontology."""
from __future__ import annotations

import time
import uuid
from collections import Counter, defaultdict
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import Integer, JSON, String
from sqlalchemy.orm import Mapped, Session, mapped_column

from . import models, models_action, object_views_ops, ontology_core, ops_control, platform_core, tenancy
from .database import Base, get_db
from .production_auth import Principal, require_permission

router = APIRouter(tags=["ontology-health"])


class OntologyHealthRun(Base):
    __tablename__ = "ontology_health_runs"

    id: Mapped[str] = mapped_column(String, primary_key=True, index=True)
    project_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    object_type_id: Mapped[Optional[str]] = mapped_column(String, nullable=True, index=True)
    status: Mapped[str] = mapped_column(String, nullable=False, index=True)
    score: Mapped[int] = mapped_column(Integer, nullable=False)
    summary: Mapped[dict] = mapped_column(JSON, default=dict)
    metrics: Mapped[dict] = mapped_column(JSON, default=dict)
    findings: Mapped[list] = mapped_column(JSON, default=list)
    created_by: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[int] = mapped_column(Integer, nullable=False, index=True)


class OntologyHealthRequest(BaseModel):
    project_id: str = "default"
    object_type_id: Optional[str] = None
    stale_after_seconds: int = Field(default=30 * 24 * 60 * 60, ge=60)


class StandardViewGenerateRequest(BaseModel):
    replace: bool = False
    publish: bool = True


class OntologyPolicySimulationRequest(BaseModel):
    principal: str
    action: str = "view"
    purpose: Optional[str] = None
    resource_id: Optional[str] = None
    context: Dict[str, Any] = Field(default_factory=dict)
    hypothetical_rules: List[platform_core.PolicyRuleCreate] = Field(default_factory=list)


def _now() -> int:
    return int(time.time())


def _next_run_timestamp(db: Session, project_id: str) -> int:
    latest = db.query(OntologyHealthRun.created_at).filter(OntologyHealthRun.project_id == project_id).order_by(OntologyHealthRun.created_at.desc()).first()
    return max(_now(), int(latest[0]) + 1 if latest else 0)


def _run_dict(row: OntologyHealthRun) -> Dict[str, Any]:
    return {
        "id": row.id,
        "project_id": row.project_id,
        "object_type_id": row.object_type_id,
        "status": row.status,
        "score": row.score,
        "summary": row.summary or {},
        "metrics": row.metrics or {},
        "findings": row.findings or [],
        "created_by": row.created_by,
        "created_at": row.created_at,
    }


def _property_schema(db: Session, object_type: models.ObjectType) -> tuple[Dict[str, Any], Optional[ontology_core.ObjectTypeProfile]]:
    profile = db.get(ontology_core.ObjectTypeProfile, object_type.id)
    if profile and profile.properties:
        return dict(profile.properties), profile
    return {
        name: spec if isinstance(spec, dict) else {"base_type": str(spec)}
        for name, spec in (object_type.properties or {}).items()
        if not str(name).startswith("__")
    }, profile


def _matches_type(value: Any, base_type: str) -> bool:
    if value is None:
        return True
    kind = base_type or "string"
    if kind in {"string", "date", "timestamp", "attachment", "mediaReference", "timeSeries", "marking", "cipherText"}:
        return isinstance(value, str)
    if kind in {"byte", "short", "integer", "long"}:
        return isinstance(value, int) and not isinstance(value, bool)
    if kind in {"float", "double", "decimal"}:
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if kind == "boolean":
        return isinstance(value, bool)
    if kind in {"array", "vector"}:
        return isinstance(value, list)
    if kind in {"struct", "object", "json"}:
        return isinstance(value, dict)
    if kind in {"geopoint", "geoshape", "geometry", "geojson"}:
        return isinstance(value, (dict, list, str))
    return True


def _finding(findings: List[Dict[str, Any]], *, code: str, severity: str, category: str,
             resource_type: str, resource_id: str, title: str, detail: str,
             recommendation: str, object_type_id: Optional[str] = None, count: int = 1) -> None:
    findings.append({
        "id": f"{code.lower()}_{len(findings) + 1}",
        "code": code,
        "severity": severity,
        "category": category,
        "resource_type": resource_type,
        "resource_id": resource_id,
        "object_type_id": object_type_id,
        "title": title,
        "detail": detail,
        "recommendation": recommendation,
        "count": count,
        "target_href": f"/workspace/ontology?objectType={object_type_id or resource_id}",
    })


def _evaluate_health(db: Session, body: OntologyHealthRequest) -> tuple[List[Dict[str, Any]], Dict[str, Any]]:
    type_query = db.query(models.ObjectType).filter(models.ObjectType.project_id == body.project_id)
    if body.object_type_id:
        type_query = type_query.filter(models.ObjectType.id == body.object_type_id)
    object_types = type_query.order_by(models.ObjectType.id).all()
    if body.object_type_id and not object_types:
        raise HTTPException(status_code=404, detail=f"ObjectType '{body.object_type_id}' not found in project '{body.project_id}'")

    type_ids = {row.id for row in object_types}
    findings: List[Dict[str, Any]] = []
    total_properties = 0
    total_objects = 0
    valid_values = 0
    checked_values = 0
    sourced_objects = 0
    now = _now()

    object_rows: Dict[str, List[models.ObjectInstance]] = {}
    for object_type in object_types:
        properties, profile = _property_schema(db, object_type)
        total_properties += len(properties)
        objects = db.query(models.ObjectInstance).filter(
            models.ObjectInstance.project_id == body.project_id,
            models.ObjectInstance.object_type_id == object_type.id,
        ).all()
        object_rows[object_type.id] = objects
        total_objects += len(objects)
        sourced_objects += sum(1 for item in objects if item.source_asset_id)

        if not object_type.description:
            _finding(findings, code="MISSING_DESCRIPTION", severity="WARN", category="metadata", resource_type="object_type",
                     resource_id=object_type.id, object_type_id=object_type.id, title="Object type has no description",
                     detail=f"{object_type.display_name} is harder to discover and govern without a description.",
                     recommendation="Add an operational description and ownership context.")
        if not properties:
            _finding(findings, code="EMPTY_SCHEMA", severity="ERROR", category="schema", resource_type="object_type",
                     resource_id=object_type.id, object_type_id=object_type.id, title="Object type has no visible properties",
                     detail="The object type cannot carry a useful operational state.", recommendation="Add a primary key and operational properties.")
        primary_key = profile.primary_key if profile else None
        title_key = profile.title_key if profile else None
        if not primary_key or primary_key not in properties:
            _finding(findings, code="MISSING_PRIMARY_KEY", severity="ERROR", category="identity", resource_type="object_type",
                     resource_id=object_type.id, object_type_id=object_type.id, title="Stable primary key is not configured",
                     detail="Objects cannot be deterministically hydrated or deduplicated without a primary key.",
                     recommendation="Select a stable, high-cardinality property as the primary key.")
        if not title_key or title_key not in properties:
            _finding(findings, code="MISSING_TITLE_KEY", severity="WARN", category="usability", resource_type="object_type",
                     resource_id=object_type.id, object_type_id=object_type.id, title="Human-readable title key is not configured",
                     detail="Object lists and links will fall back to opaque identifiers.", recommendation="Select a concise display property as the title key.")

        invalid_specs = [name for name, spec in properties.items() if str((spec or {}).get("base_type") or (spec or {}).get("type") or "string") not in ontology_core.FOUNDRY_BASE_TYPES and str((spec or {}).get("base_type") or (spec or {}).get("type") or "string") not in ontology_core.LOCAL_SCHEMA_TYPES]
        if invalid_specs:
            _finding(findings, code="UNSUPPORTED_PROPERTY_TYPE", severity="ERROR", category="schema", resource_type="object_type",
                     resource_id=object_type.id, object_type_id=object_type.id, title="Unsupported property base types",
                     detail=f"Unsupported type definitions: {', '.join(invalid_specs[:8])}.", recommendation="Replace them with a supported ontology base type.", count=len(invalid_specs))

        required = [name for name, spec in properties.items() if isinstance(spec, dict) and spec.get("required")]
        missing_required: Counter[str] = Counter()
        invalid_types: Counter[str] = Counter()
        primary_values: Counter[str] = Counter()
        stale_count = 0
        for item in objects:
            values = item.properties or {}
            if now - int(item.updated_at or item.created_at or now) > body.stale_after_seconds:
                stale_count += 1
            if primary_key and values.get(primary_key) not in (None, ""):
                primary_values[str(values.get(primary_key))] += 1
            for name, spec in properties.items():
                value = values.get(name)
                if name in required and value in (None, ""):
                    missing_required[name] += 1
                if value is not None:
                    checked_values += 1
                    base_type = str((spec or {}).get("base_type") or (spec or {}).get("type") or "string") if isinstance(spec, dict) else str(spec)
                    if _matches_type(value, base_type):
                        valid_values += 1
                    else:
                        invalid_types[name] += 1
        if missing_required:
            _finding(findings, code="REQUIRED_VALUE_MISSING", severity="ERROR", category="data_quality", resource_type="object_type",
                     resource_id=object_type.id, object_type_id=object_type.id, title="Required object values are missing",
                     detail=", ".join(f"{name}: {count}" for name, count in missing_required.most_common(6)),
                     recommendation="Correct source mappings or quarantine incomplete records.", count=sum(missing_required.values()))
        if invalid_types:
            _finding(findings, code="RUNTIME_TYPE_MISMATCH", severity="ERROR", category="data_quality", resource_type="object_type",
                     resource_id=object_type.id, object_type_id=object_type.id, title="Runtime values violate property types",
                     detail=", ".join(f"{name}: {count}" for name, count in invalid_types.most_common(6)),
                     recommendation="Add coercion and validation transforms before ontology hydration.", count=sum(invalid_types.values()))
        duplicate_count = sum(count - 1 for count in primary_values.values() if count > 1)
        if duplicate_count:
            _finding(findings, code="DUPLICATE_PRIMARY_KEY", severity="ERROR", category="identity", resource_type="object_type",
                     resource_id=object_type.id, object_type_id=object_type.id, title="Duplicate primary-key values detected",
                     detail=f"{duplicate_count} object rows conflict with an existing primary key.",
                     recommendation="Deduplicate upstream records before hydration.", count=duplicate_count)
        if objects and stale_count:
            _finding(findings, code="STALE_OBJECTS", severity="WARN", category="freshness", resource_type="object_type",
                     resource_id=object_type.id, object_type_id=object_type.id, title="Objects have not been refreshed",
                     detail=f"{stale_count} of {len(objects)} objects exceed the freshness threshold.",
                     recommendation="Inspect the producing pipeline, connector, or schedule.", count=stale_count)
        if not objects:
            _finding(findings, code="NO_RUNTIME_OBJECTS", severity="WARN", category="materialization", resource_type="object_type",
                     resource_id=object_type.id, object_type_id=object_type.id, title="Object type has no hydrated objects",
                     detail="The schema exists but has no operational instances.", recommendation="Map and deliver a dataset to this object type.")
        elif not any(item.source_asset_id for item in objects):
            _finding(findings, code="MISSING_OBJECT_LINEAGE", severity="WARN", category="lineage", resource_type="object_type",
                     resource_id=object_type.id, object_type_id=object_type.id, title="Hydrated objects lack source dataset lineage",
                     detail="No object instance records a source asset.", recommendation="Hydrate through an ontology-output pipeline node.", count=len(objects))

        if not db.query(object_views_ops.OvView).filter(object_views_ops.OvView.object_type_id == object_type.id).first():
            _finding(findings, code="MISSING_OBJECT_VIEW", severity="WARN", category="usability", resource_type="object_type",
                     resource_id=object_type.id, object_type_id=object_type.id, title="No configured object view",
                     detail="Users only receive the generated fallback presentation.", recommendation="Generate and publish a standard object view.")
        if not db.query(platform_core.PolicyRule).filter(platform_core.PolicyRule.object_type_id == object_type.id, platform_core.PolicyRule.active == True).first():  # noqa: E712
            _finding(findings, code="MISSING_POLICY_COVERAGE", severity="WARN", category="governance", resource_type="object_type",
                     resource_id=object_type.id, object_type_id=object_type.id, title="No explicit object-type policy",
                     detail="Access and action behavior currently relies on project defaults.", recommendation="Add and simulate a scoped policy before production use.")

    link_types = db.query(models.LinkType).filter(models.LinkType.project_id == body.project_id).all()
    scoped_links = [link for link in link_types if not body.object_type_id or link.source_object_type_id in type_ids or link.target_object_type_id in type_ids]
    all_object_ids = {row.id for row in db.query(models.ObjectInstance.id).filter(models.ObjectInstance.project_id == body.project_id).all()}
    link_instances = db.query(models.LinkInstance).filter(models.LinkInstance.project_id == body.project_id).all()
    link_instances = [row for row in link_instances if any(link.id == row.link_type_id for link in scoped_links)]
    invalid_link_types = [link for link in scoped_links if not db.get(models.ObjectType, link.source_object_type_id) or not db.get(models.ObjectType, link.target_object_type_id)]
    for link in invalid_link_types:
        _finding(findings, code="BROKEN_LINK_TYPE", severity="ERROR", category="relationships", resource_type="link_type", resource_id=link.id,
                 object_type_id=link.source_object_type_id, title="Link type references a missing object type",
                 detail=f"{link.source_object_type_id} -> {link.target_object_type_id}", recommendation="Restore the object type or archive the link definition.")
    orphan_links = [row for row in link_instances if row.source_object_id not in all_object_ids or row.target_object_id not in all_object_ids]
    if orphan_links:
        _finding(findings, code="ORPHAN_LINK_INSTANCE", severity="ERROR", category="relationships", resource_type="link_instance", resource_id=orphan_links[0].id,
                 title="Link instances reference missing objects", detail=f"{len(orphan_links)} orphan link instances were found.",
                 recommendation="Rehydrate missing objects or quarantine the invalid links.", count=len(orphan_links))
    by_link: Dict[str, List[models.LinkInstance]] = defaultdict(list)
    for row in link_instances:
        by_link[row.link_type_id].append(row)
    for link in scoped_links:
        rows = by_link.get(link.id, [])
        duplicate_pairs = len(rows) - len({(row.source_object_id, row.target_object_id) for row in rows})
        violations = duplicate_pairs
        if link.cardinality == "ONE_TO_ONE":
            violations += sum(value - 1 for value in Counter(row.source_object_id for row in rows).values() if value > 1)
            violations += sum(value - 1 for value in Counter(row.target_object_id for row in rows).values() if value > 1)
        elif link.cardinality == "ONE_TO_MANY":
            violations += sum(value - 1 for value in Counter(row.target_object_id for row in rows).values() if value > 1)
        if violations:
            _finding(findings, code="CARDINALITY_VIOLATION", severity="ERROR", category="relationships", resource_type="link_type", resource_id=link.id,
                     object_type_id=link.source_object_type_id, title="Link cardinality is violated",
                     detail=f"{violations} relationship assignments conflict with {link.cardinality}.",
                     recommendation="Deduplicate link inputs and enforce relationship validation.", count=violations)

    metrics = {
        "object_types": len(object_types),
        "properties": total_properties,
        "objects": total_objects,
        "link_types": len(scoped_links),
        "links": len(link_instances),
        "schema_coverage": round(sum(1 for row in object_types if _property_schema(db, row)[0]) / len(object_types), 4) if object_types else 0,
        "type_conformance": round(valid_values / checked_values, 4) if checked_values else 1.0,
        "lineage_coverage": round(sourced_objects / total_objects, 4) if total_objects else 0,
    }
    return findings, metrics


def _create_standard_view(db: Session, object_type: models.ObjectType, actor: str, replace: bool, publish: bool) -> Dict[str, Any]:
    existing = db.query(object_views_ops.OvView).filter(object_views_ops.OvView.object_type_id == object_type.id).first()
    if existing and not replace:
        return {"created": False, "view_id": existing.id, "object_type_id": object_type.id, "published_version_id": existing.published_version_id}
    if existing:
        tabs = db.query(object_views_ops.OvTab).filter(object_views_ops.OvTab.view_id == existing.id).all()
        for tab in tabs:
            db.query(object_views_ops.OvWidget).filter(object_views_ops.OvWidget.tab_id == tab.id).delete()
            db.delete(tab)
        db.query(object_views_ops.OvVersion).filter(object_views_ops.OvVersion.view_id == existing.id).delete()
        view = existing
    else:
        view = object_views_ops.OvView(
            id=f"object_view_{uuid.uuid4().hex}", object_type_id=object_type.id, form_factor="full",
            panel_mode=None, panel_config={}, auto_publish=True, created_at=_now(), updated_at=_now(),
        )
        db.add(view)
        db.flush()
    tab = object_views_ops.OvTab(
        id=f"object_view_tab_{uuid.uuid4().hex}", view_id=view.id, tab_type="workshop",
        display_name="Overview", tab_order=0, conditional_visibility={}, created_at=_now(),
    )
    db.add(tab)
    properties, _ = _property_schema(db, object_type)
    visible = list(properties)
    db.add(object_views_ops.OvWidget(
        id=f"object_view_widget_{uuid.uuid4().hex}", tab_id=tab.id, widget_type="property_list",
        widget_order=0, config={"properties": visible, "prominent_only": False}, created_at=_now(),
    ))
    linked = object_views_ops._linked_object_types(db, object_type.id)
    db.add(object_views_ops.OvWidget(
        id=f"object_view_widget_{uuid.uuid4().hex}", tab_id=tab.id, widget_type="links",
        widget_order=1, config={"link_types": [item["link_type_id"] for item in linked]}, created_at=_now(),
    ))
    view.default_tab_id = tab.id
    view.updated_at = _now()
    db.flush()
    version_id = None
    if publish:
        version = object_views_ops.OvVersion(
            id=f"object_view_version_{uuid.uuid4().hex}", view_id=view.id, version_number=1,
            is_published=True, content_snapshot=object_views_ops._view_content_snapshot(db, view),
            description="Generated standard object view", author=actor, created_at=_now(),
        )
        db.add(version)
        view.published_version_id = version.id
        version_id = version.id
    return {"created": True, "view_id": view.id, "object_type_id": object_type.id, "published_version_id": version_id, "property_count": len(visible), "link_type_count": len(linked)}


@router.post("/ontology/health/run")
def run_ontology_health(body: OntologyHealthRequest, principal: Principal = Depends(require_permission("execute")), db: Session = Depends(get_db)):
    tenancy.assert_project_permission(db, principal, body.project_id, "execute")
    findings, metrics = _evaluate_health(db, body)
    severity_counts = Counter(item["severity"] for item in findings)
    score = max(0, 100 - severity_counts["ERROR"] * 12 - severity_counts["WARN"] * 4)
    status = "FAIL" if severity_counts["ERROR"] else ("WARN" if severity_counts["WARN"] else "PASS")
    row = OntologyHealthRun(
        id=f"ontology_health_{uuid.uuid4().hex}", project_id=body.project_id, object_type_id=body.object_type_id,
        status=status, score=score, summary={"findings": len(findings), "errors": severity_counts["ERROR"], "warnings": severity_counts["WARN"], "info": severity_counts["INFO"]},
        metrics=metrics, findings=findings, created_by=principal.id, created_at=_next_run_timestamp(db, body.project_id),
    )
    db.add(row)
    db.add(models_action.AuditLog(id=uuid.uuid4().hex, actor=principal.id, event_type="ontology.health.evaluated", subject_type="ontology_health_run", subject_id=row.id, payload={"project_id": body.project_id, "status": status, "score": score, "summary": row.summary}))
    ops_control.record_ops_event(db, source="ontology", event_type="ontology.health.evaluated", severity="high" if status == "FAIL" else ("medium" if status == "WARN" else "info"), title=f"Ontology health {status}", subject_type="ontology_health_run", subject_id=row.id, payload={"project_id": body.project_id, "score": score, "summary": row.summary}, evaluate_alerts=True)
    db.commit()
    return _run_dict(row)


@router.get("/ontology/health/runs")
def list_ontology_health_runs(project_id: str = "default", object_type_id: Optional[str] = None, limit: int = Query(25, ge=1, le=250), principal: Principal = Depends(require_permission("view")), db: Session = Depends(get_db)):
    tenancy.assert_project_permission(db, principal, project_id, "view")
    query = db.query(OntologyHealthRun).filter(OntologyHealthRun.project_id == project_id)
    if object_type_id:
        query = query.filter(OntologyHealthRun.object_type_id == object_type_id)
    rows = query.order_by(OntologyHealthRun.created_at.desc()).limit(limit).all()
    return {"count": len(rows), "runs": [_run_dict(row) for row in rows]}


@router.get("/ontology/health/latest")
def latest_ontology_health(project_id: str = "default", object_type_id: Optional[str] = None, principal: Principal = Depends(require_permission("view")), db: Session = Depends(get_db)):
    tenancy.assert_project_permission(db, principal, project_id, "view")
    query = db.query(OntologyHealthRun).filter(OntologyHealthRun.project_id == project_id)
    if object_type_id:
        query = query.filter(OntologyHealthRun.object_type_id == object_type_id)
    row = query.order_by(OntologyHealthRun.created_at.desc()).first()
    return _run_dict(row) if row else {"status": "NOT_RUN", "score": None, "summary": {}, "metrics": {}, "findings": [], "project_id": project_id, "object_type_id": object_type_id, "created_at": None}


@router.get("/ontology/health/runs/{run_id}")
def get_ontology_health_run(run_id: str, principal: Principal = Depends(require_permission("view")), db: Session = Depends(get_db)):
    row = db.get(OntologyHealthRun, run_id)
    if not row:
        raise HTTPException(status_code=404, detail="Ontology health run not found")
    tenancy.assert_project_permission(db, principal, row.project_id, "view")
    return _run_dict(row)


@router.get("/ui-state/ontology/health")
def ontology_health_ui_state(project_id: str = "default", object_type_id: Optional[str] = None, principal: Principal = Depends(require_permission("view")), db: Session = Depends(get_db)):
    tenancy.assert_project_permission(db, principal, project_id, "view")
    query = db.query(OntologyHealthRun).filter(OntologyHealthRun.project_id == project_id)
    if object_type_id:
        query = query.filter(OntologyHealthRun.object_type_id == object_type_id)
    latest = query.order_by(OntologyHealthRun.created_at.desc()).first()
    latest_value = _run_dict(latest) if latest else {"status": "NOT_RUN", "score": None, "summary": {}, "metrics": {}, "findings": [], "created_at": None}
    return {
        "summary": {"status": latest_value["status"], "score": latest_value["score"], **latest_value.get("summary", {})},
        "primary_actions": [
            {"id": "run_health", "label": "Run health evaluation", "method": "POST", "path": "/ontology/health/run"},
            {"id": "simulate_policy", "label": "Simulate policy", "method": "POST", "path": "/ontology/policies/simulate"},
        ],
        "sections": {"metrics": latest_value.get("metrics", {}), "findings": latest_value.get("findings", []), "latest_run": latest_value},
        "evidence_links": [{"label": "Health run", "href": f"/ontology/health/runs/{latest.id}", "kind": "ontology_health_run"}] if latest else [],
        "warnings": [item for item in latest_value.get("findings", []) if item.get("severity") in {"ERROR", "WARN"}],
        "permissions": sorted(tenancy.project_permissions(db, principal, project_id)),
        "last_updated": latest_value.get("created_at"),
    }


@router.post("/ontology/object-types/{object_type_id}/generate-standard-view")
def generate_standard_object_view(object_type_id: str, body: StandardViewGenerateRequest, principal: Principal = Depends(require_permission("edit")), db: Session = Depends(get_db)):
    object_type = db.get(models.ObjectType, object_type_id)
    if not object_type:
        raise HTTPException(status_code=404, detail="Object type not found")
    tenancy.assert_project_permission(db, principal, object_type.project_id, "edit")
    result = _create_standard_view(db, object_type, principal.id, body.replace, body.publish)
    db.add(models_action.AuditLog(id=uuid.uuid4().hex, actor=principal.id, event_type="ontology.object_view.generated", subject_type="object_view", subject_id=result["view_id"], payload=result))
    ops_control.record_ops_event(db, source="ontology", event_type="ontology.object_view.generated", severity="info", title=f"Standard view generated for {object_type.display_name}", subject_type="object_view", subject_id=result["view_id"], object_type_id=object_type.id, payload=result, evaluate_alerts=False)
    db.commit()
    return result


@router.post("/ontology/object-types/{object_type_id}/policies/simulate")
def simulate_object_type_policy(object_type_id: str, body: OntologyPolicySimulationRequest, principal: Principal = Depends(require_permission("view")), db: Session = Depends(get_db)):
    object_type = db.get(models.ObjectType, object_type_id)
    if not object_type:
        raise HTTPException(status_code=404, detail="Object type not found")
    tenancy.assert_project_permission(db, principal, object_type.project_id, "view")
    request = platform_core.PolicySimulationRequest(
        principal=body.principal, action=body.action, resource_kind="object_type", resource_id=body.resource_id or object_type_id,
        object_type_id=object_type_id, purpose=body.purpose, context=body.context, hypothetical_rules=body.hypothetical_rules, persist=False,
    )
    existing = db.query(platform_core.PolicyRule).filter(platform_core.PolicyRule.active == True).all()  # noqa: E712
    now = _now()
    hypothetical = [platform_core.PolicyRule(
        id=rule.id or f"hypothetical_{index}", display_name=rule.display_name, description=rule.description,
        effect=rule.effect.upper(), principal=rule.principal, action=rule.action, resource_kind=rule.resource_kind,
        resource_id=rule.resource_id, object_type_id=rule.object_type_id or object_type_id, purpose=rule.purpose,
        condition=rule.condition, mask_properties=rule.mask_properties, row_filter=rule.row_filter, approval=rule.approval,
        break_glass_allowed=rule.break_glass_allowed, priority=rule.priority, active=rule.active, created_at=now, updated_at=now,
    ) for index, rule in enumerate(request.hypothetical_rules)]
    evaluation = platform_core.PolicyEvaluateRequest(**request.model_dump(exclude={"hypothetical_rules", "persist"}))
    result = platform_core._evaluate_policy_rules(existing + hypothetical, evaluation)
    return {"object_type_id": object_type_id, "persisted": False, "decision": result, "hypothetical_rule_count": len(hypothetical)}

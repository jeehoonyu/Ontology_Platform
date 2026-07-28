"""
Gotham-style local investigation workspace.

The module builds on ontology objects, links, audit logs, temporal snapshots,
and decision risk explanations to provide case boards, evidence, hypotheses,
entity graphs, timelines, and deterministic reports.
"""
from __future__ import annotations

import time
import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import Integer, JSON, String
from sqlalchemy.orm import Mapped, Session, mapped_column

from . import models, models_action, production_auth, semantic_scope
from .database import Base, get_db

router = APIRouter(tags=["investigations"])


def _now() -> int:
    return int(time.time())


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


class InvestigationWorkspace(Base):
    __tablename__ = "investigation_workspaces"

    id: Mapped[str] = mapped_column(String, primary_key=True, index=True)
    project_id: Mapped[str] = mapped_column(String, default="default", server_default="default", index=True)
    display_name: Mapped[str] = mapped_column(String)
    description: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    status: Mapped[str] = mapped_column(String, default="OPEN", index=True)
    owner: Mapped[Optional[str]] = mapped_column(String, nullable=True, index=True)
    object_refs: Mapped[list] = mapped_column(JSON, default=list)
    alert_ids: Mapped[list] = mapped_column(JSON, default=list)
    incident_ids: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[int] = mapped_column(Integer)
    updated_at: Mapped[int] = mapped_column(Integer)


class EvidenceItem(Base):
    __tablename__ = "investigation_evidence"

    id: Mapped[str] = mapped_column(String, primary_key=True, index=True)
    project_id: Mapped[str] = mapped_column(String, default="default", server_default="default", index=True)
    investigation_id: Mapped[str] = mapped_column(String, index=True)
    title: Mapped[str] = mapped_column(String)
    source: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    object_refs: Mapped[list] = mapped_column(JSON, default=list)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    tags: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[int] = mapped_column(Integer)


class InvestigationHypothesis(Base):
    __tablename__ = "investigation_hypotheses"

    id: Mapped[str] = mapped_column(String, primary_key=True, index=True)
    project_id: Mapped[str] = mapped_column(String, default="default", server_default="default", index=True)
    investigation_id: Mapped[str] = mapped_column(String, index=True)
    statement: Mapped[str] = mapped_column(String)
    status: Mapped[str] = mapped_column(String, default="OPEN", index=True)
    confidence: Mapped[int] = mapped_column(Integer, default=50)
    linked_evidence_ids: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[int] = mapped_column(Integer)
    updated_at: Mapped[int] = mapped_column(Integer)


class InvestigationFinding(Base):
    __tablename__ = "investigation_findings"

    id: Mapped[str] = mapped_column(String, primary_key=True, index=True)
    project_id: Mapped[str] = mapped_column(String, default="default", server_default="default", index=True)
    investigation_id: Mapped[str] = mapped_column(String, index=True)
    title: Mapped[str] = mapped_column(String)
    severity: Mapped[str] = mapped_column(String, default="medium")
    summary: Mapped[str] = mapped_column(String)
    object_refs: Mapped[list] = mapped_column(JSON, default=list)
    evidence_ids: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[int] = mapped_column(Integer)


class InvestigationReport(Base):
    __tablename__ = "investigation_reports"

    id: Mapped[str] = mapped_column(String, primary_key=True, index=True)
    project_id: Mapped[str] = mapped_column(String, default="default", server_default="default", index=True)
    investigation_id: Mapped[str] = mapped_column(String, index=True)
    title: Mapped[str] = mapped_column(String)
    body: Mapped[str] = mapped_column(String)
    sections: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[int] = mapped_column(Integer)


class InvestigationCreate(BaseModel):
    id: Optional[str] = None
    project_id: str = "default"
    display_name: str
    description: Optional[str] = None
    status: str = "OPEN"
    owner: Optional[str] = None
    object_refs: List[Dict[str, Any]] = Field(default_factory=list)
    alert_ids: List[str] = Field(default_factory=list)
    incident_ids: List[str] = Field(default_factory=list)


class InvestigationPatch(BaseModel):
    display_name: Optional[str] = None
    description: Optional[str] = None
    status: Optional[str] = None
    owner: Optional[str] = None
    object_refs: Optional[List[Dict[str, Any]]] = None
    alert_ids: Optional[List[str]] = None
    incident_ids: Optional[List[str]] = None


class EvidenceCreate(BaseModel):
    id: Optional[str] = None
    title: str
    source: Optional[str] = None
    object_refs: List[Dict[str, Any]] = Field(default_factory=list)
    payload: Dict[str, Any] = Field(default_factory=dict)
    tags: List[str] = Field(default_factory=list)


class HypothesisCreate(BaseModel):
    id: Optional[str] = None
    statement: str
    status: str = "OPEN"
    confidence: int = 50
    linked_evidence_ids: List[str] = Field(default_factory=list)


class HypothesisPatch(BaseModel):
    statement: Optional[str] = None
    status: Optional[str] = None
    confidence: Optional[int] = None
    linked_evidence_ids: Optional[List[str]] = None


class ReportRequest(BaseModel):
    title: Optional[str] = None
    include_risk: bool = True


def _ensure_tables(db: Session) -> None:
    for table in (
        InvestigationWorkspace.__table__,
        EvidenceItem.__table__,
        InvestigationHypothesis.__table__,
        InvestigationFinding.__table__,
        InvestigationReport.__table__,
    ):
        table.create(bind=db.get_bind(), checkfirst=True)


def _audit(db: Session, event_type: str, subject_type: str, subject_id: str, payload: Dict[str, Any]) -> None:
    db.add(models_action.AuditLog(
        id=uuid.uuid4().hex,
        actor="investigations",
        event_type=event_type,
        subject_type=subject_type,
        subject_id=subject_id,
        payload=payload,
    ))


def _workspace_dict(row: InvestigationWorkspace) -> Dict[str, Any]:
    return {
        "id": row.id,
        "project_id": row.project_id,
        "display_name": row.display_name,
        "description": row.description,
        "status": row.status,
        "owner": row.owner,
        "object_refs": row.object_refs or [],
        "alert_ids": row.alert_ids or [],
        "incident_ids": row.incident_ids or [],
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


def _evidence_dict(row: EvidenceItem) -> Dict[str, Any]:
    return {
        "id": row.id,
        "project_id": row.project_id,
        "investigation_id": row.investigation_id,
        "title": row.title,
        "source": row.source,
        "object_refs": row.object_refs or [],
        "payload": row.payload or {},
        "tags": row.tags or [],
        "created_at": row.created_at,
    }


def _hypothesis_dict(row: InvestigationHypothesis) -> Dict[str, Any]:
    return {
        "id": row.id,
        "project_id": row.project_id,
        "investigation_id": row.investigation_id,
        "statement": row.statement,
        "status": row.status,
        "confidence": row.confidence,
        "linked_evidence_ids": row.linked_evidence_ids or [],
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


def _finding_dict(row: InvestigationFinding) -> Dict[str, Any]:
    return {
        "id": row.id,
        "project_id": row.project_id,
        "investigation_id": row.investigation_id,
        "title": row.title,
        "severity": row.severity,
        "summary": row.summary,
        "object_refs": row.object_refs or [],
        "evidence_ids": row.evidence_ids or [],
        "created_at": row.created_at,
    }


def _report_dict(row: InvestigationReport) -> Dict[str, Any]:
    return {
        "id": row.id,
        "project_id": row.project_id,
        "investigation_id": row.investigation_id,
        "title": row.title,
        "body": row.body,
        "sections": row.sections or [],
        "created_at": row.created_at,
    }


def _get_workspace(db: Session, investigation_id: str, principal: Optional[production_auth.Principal] = None, permission: str = "view") -> InvestigationWorkspace:
    _ensure_tables(db)
    if principal is None:
        workspace = db.get(InvestigationWorkspace, investigation_id)
        if not workspace:
            raise HTTPException(status_code=404, detail=f"InvestigationWorkspace '{investigation_id}' not found")
        return workspace
    return semantic_scope.owned_row(db, principal, InvestigationWorkspace, investigation_id, permission, "InvestigationWorkspace")


def _validate_refs(db: Session, project_id: str, refs: List[Dict[str, Any]]) -> None:
    for ref in refs or []:
        object_id = ref.get("object_id")
        obj = db.get(models.ObjectInstance, object_id) if object_id else None
        if not obj or obj.project_id != project_id or obj.object_type_id != ref.get("object_type_id"):
            raise HTTPException(status_code=422, detail=f"Object reference '{object_id}' is not valid for project '{project_id}'")


def _validate_case_links(db: Session, project_id: str, alert_ids: List[str], incident_ids: List[str]) -> None:
    from . import ops_control
    for alert_id in alert_ids or []:
        alert = db.get(ops_control.AlertEvent, alert_id)
        if not alert or alert.project_id != project_id:
            raise HTTPException(status_code=422, detail=f"Alert '{alert_id}' is not valid for project '{project_id}'")
    for incident_id in incident_ids or []:
        incident = db.get(ops_control.Incident, incident_id)
        if not incident or incident.project_id != project_id:
            raise HTTPException(status_code=422, detail=f"Incident '{incident_id}' is not valid for project '{project_id}'")


def _object_ref_key(ref: Dict[str, Any]) -> str:
    return f"{ref.get('object_type_id')}:{ref.get('object_id')}"


def _object_payload(db: Session, ref: Dict[str, Any], project_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
    object_id = ref.get("object_id")
    if not object_id:
        return None
    obj = db.get(models.ObjectInstance, object_id)
    if not obj or (project_id and obj.project_id != project_id):
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


def _risk_for_ref(db: Session, ref: Dict[str, Any], project_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
    try:
        obj = db.get(models.ObjectInstance, ref.get("object_id"))
        if not obj or (project_id and obj.project_id != project_id):
            return None
        from . import decision_intelligence
        return decision_intelligence.score_object_by_id(db, str(ref.get("object_type_id")), str(ref.get("object_id")))
    except Exception:
        return None


def _all_object_refs(workspace: InvestigationWorkspace, evidence: List[EvidenceItem]) -> List[Dict[str, Any]]:
    refs: Dict[str, Dict[str, Any]] = {}
    for ref in workspace.object_refs or []:
        refs[_object_ref_key(ref)] = ref
    for item in evidence:
        for ref in item.object_refs or []:
            refs[_object_ref_key(ref)] = ref
    return list(refs.values())


@router.post("/investigations")
def create_investigation(body: InvestigationCreate, db: Session = Depends(get_db), principal: production_auth.Principal = Depends(production_auth.require_permission("edit"))):
    _ensure_tables(db)
    semantic_scope.assert_project(db, principal, body.project_id, "edit")
    _validate_refs(db, body.project_id, body.object_refs)
    _validate_case_links(db, body.project_id, body.alert_ids, body.incident_ids)
    investigation_id = body.id or _new_id("inv")
    if db.get(InvestigationWorkspace, investigation_id):
        raise HTTPException(status_code=400, detail="InvestigationWorkspace already exists")
    now = _now()
    workspace = InvestigationWorkspace(id=investigation_id, created_at=now, updated_at=now, **body.model_dump(exclude={"id"}))
    db.add(workspace)
    _audit(db, "investigation.created", "investigation", workspace.id, _workspace_dict(workspace))
    try:
        from . import ops_control
        ops_control.record_ops_event(
            db,
            source="investigation",
            event_type="investigation.created",
            severity="info",
            title=workspace.display_name,
            subject_type="investigation",
            subject_id=workspace.id,
            payload={"object_refs": workspace.object_refs or []},
            project_id=workspace.project_id,
        )
    except Exception:
        pass
    db.commit()
    db.refresh(workspace)
    return _workspace_dict(workspace)


@router.get("/investigations")
def list_investigations(status: Optional[str] = None, db: Session = Depends(get_db), principal: production_auth.Principal = Depends(production_auth.require_permission("view"))):
    _ensure_tables(db)
    query = semantic_scope.accessible_query(db, principal, InvestigationWorkspace)
    if status:
        query = query.filter(InvestigationWorkspace.status == status)
    return [_workspace_dict(row) for row in query.order_by(InvestigationWorkspace.updated_at.desc()).all()]


@router.get("/investigations/{investigation_id}")
def get_investigation(investigation_id: str, db: Session = Depends(get_db), principal: production_auth.Principal = Depends(production_auth.require_permission("view"))):
    workspace = _get_workspace(db, investigation_id, principal)
    evidence = db.query(EvidenceItem).filter(EvidenceItem.project_id == workspace.project_id, EvidenceItem.investigation_id == investigation_id).order_by(EvidenceItem.created_at.desc()).all()
    hypotheses = db.query(InvestigationHypothesis).filter(InvestigationHypothesis.project_id == workspace.project_id, InvestigationHypothesis.investigation_id == investigation_id).order_by(InvestigationHypothesis.updated_at.desc()).all()
    findings = db.query(InvestigationFinding).filter(InvestigationFinding.project_id == workspace.project_id, InvestigationFinding.investigation_id == investigation_id).order_by(InvestigationFinding.created_at.desc()).all()
    reports = db.query(InvestigationReport).filter(InvestigationReport.project_id == workspace.project_id, InvestigationReport.investigation_id == investigation_id).order_by(InvestigationReport.created_at.desc()).all()
    object_refs = _all_object_refs(workspace, evidence)
    return {
        **_workspace_dict(workspace),
        "evidence": [_evidence_dict(row) for row in evidence],
        "hypotheses": [_hypothesis_dict(row) for row in hypotheses],
        "findings": [_finding_dict(row) for row in findings],
        "reports": [_report_dict(row) for row in reports],
        "objects": [_object_payload(db, ref, workspace.project_id) for ref in object_refs if _object_payload(db, ref, workspace.project_id)],
        "risk": {_object_ref_key(ref): _risk_for_ref(db, ref, workspace.project_id) for ref in object_refs},
    }


@router.patch("/investigations/{investigation_id}")
def patch_investigation(investigation_id: str, body: InvestigationPatch, db: Session = Depends(get_db), principal: production_auth.Principal = Depends(production_auth.require_permission("edit"))):
    workspace = _get_workspace(db, investigation_id, principal, "edit")
    patch = body.model_dump(exclude_unset=True)
    _validate_refs(db, workspace.project_id, patch.get("object_refs") or [])
    _validate_case_links(db, workspace.project_id, patch.get("alert_ids") or [], patch.get("incident_ids") or [])
    for key, value in patch.items():
        setattr(workspace, key, value)
    workspace.updated_at = _now()
    _audit(db, "investigation.updated", "investigation", workspace.id, patch)
    db.commit()
    db.refresh(workspace)
    return _workspace_dict(workspace)


@router.post("/investigations/{investigation_id}/evidence")
def add_evidence(investigation_id: str, body: EvidenceCreate, db: Session = Depends(get_db), principal: production_auth.Principal = Depends(production_auth.require_permission("edit"))):
    workspace = _get_workspace(db, investigation_id, principal, "edit")
    _validate_refs(db, workspace.project_id, body.object_refs)
    evidence_id = body.id or _new_id("evidence")
    if db.get(EvidenceItem, evidence_id):
        raise HTTPException(status_code=400, detail="EvidenceItem already exists")
    evidence = EvidenceItem(id=evidence_id, project_id=workspace.project_id, investigation_id=investigation_id, created_at=_now(), **body.model_dump(exclude={"id"}))
    db.add(evidence)
    existing_refs = {_object_ref_key(ref): ref for ref in workspace.object_refs or []}
    for ref in body.object_refs:
        existing_refs[_object_ref_key(ref)] = ref
    workspace.object_refs = list(existing_refs.values())
    workspace.updated_at = _now()
    _audit(db, "investigation.evidence.added", "evidence", evidence.id, _evidence_dict(evidence))
    db.commit()
    db.refresh(evidence)
    return _evidence_dict(evidence)


@router.get("/investigations/{investigation_id}/evidence")
def list_evidence(investigation_id: str, db: Session = Depends(get_db), principal: production_auth.Principal = Depends(production_auth.require_permission("view"))):
    workspace = _get_workspace(db, investigation_id, principal)
    return [
        _evidence_dict(row)
        for row in db.query(EvidenceItem).filter(EvidenceItem.project_id == workspace.project_id, EvidenceItem.investigation_id == investigation_id).order_by(EvidenceItem.created_at.desc()).all()
    ]


@router.post("/investigations/{investigation_id}/hypotheses")
def add_hypothesis(investigation_id: str, body: HypothesisCreate, db: Session = Depends(get_db), principal: production_auth.Principal = Depends(production_auth.require_permission("edit"))):
    workspace = _get_workspace(db, investigation_id, principal, "edit")
    for evidence_id in body.linked_evidence_ids:
        evidence = db.get(EvidenceItem, evidence_id)
        if not evidence or evidence.project_id != workspace.project_id or evidence.investigation_id != investigation_id:
            raise HTTPException(status_code=422, detail=f"Evidence '{evidence_id}' is not valid for this investigation")
    hypothesis_id = body.id or _new_id("hyp")
    if db.get(InvestigationHypothesis, hypothesis_id):
        raise HTTPException(status_code=400, detail="InvestigationHypothesis already exists")
    now = _now()
    hypothesis = InvestigationHypothesis(id=hypothesis_id, project_id=workspace.project_id, investigation_id=investigation_id, created_at=now, updated_at=now, **body.model_dump(exclude={"id"}))
    db.add(hypothesis)
    _audit(db, "investigation.hypothesis.added", "hypothesis", hypothesis.id, _hypothesis_dict(hypothesis))
    db.commit()
    db.refresh(hypothesis)
    return _hypothesis_dict(hypothesis)


@router.patch("/investigations/{investigation_id}/hypotheses/{hypothesis_id}")
def patch_hypothesis(investigation_id: str, hypothesis_id: str, body: HypothesisPatch, db: Session = Depends(get_db), principal: production_auth.Principal = Depends(production_auth.require_permission("edit"))):
    workspace = _get_workspace(db, investigation_id, principal, "edit")
    hypothesis = db.get(InvestigationHypothesis, hypothesis_id)
    if not hypothesis or hypothesis.project_id != workspace.project_id or hypothesis.investigation_id != investigation_id:
        raise HTTPException(status_code=404, detail=f"InvestigationHypothesis '{hypothesis_id}' not found")
    patch = body.model_dump(exclude_unset=True)
    for evidence_id in patch.get("linked_evidence_ids") or []:
        evidence = db.get(EvidenceItem, evidence_id)
        if not evidence or evidence.project_id != workspace.project_id or evidence.investigation_id != investigation_id:
            raise HTTPException(status_code=422, detail=f"Evidence '{evidence_id}' is not valid for this investigation")
    for key, value in patch.items():
        setattr(hypothesis, key, value)
    hypothesis.updated_at = _now()
    _audit(db, "investigation.hypothesis.updated", "hypothesis", hypothesis.id, patch)
    db.commit()
    db.refresh(hypothesis)
    return _hypothesis_dict(hypothesis)


@router.get("/investigations/{investigation_id}/graph")
def investigation_graph(investigation_id: str, db: Session = Depends(get_db), principal: production_auth.Principal = Depends(production_auth.require_permission("view"))):
    workspace = _get_workspace(db, investigation_id, principal)
    evidence = db.query(EvidenceItem).filter(EvidenceItem.project_id == workspace.project_id, EvidenceItem.investigation_id == investigation_id).all()
    hypotheses = db.query(InvestigationHypothesis).filter(InvestigationHypothesis.project_id == workspace.project_id, InvestigationHypothesis.investigation_id == investigation_id).all()
    refs = _all_object_refs(workspace, evidence)
    nodes: Dict[str, Dict[str, Any]] = {
        f"investigation:{workspace.id}": {"id": f"investigation:{workspace.id}", "kind": "investigation", "label": workspace.display_name, "status": workspace.status}
    }
    edges: List[Dict[str, Any]] = []

    for ref in refs:
        obj = _object_payload(db, ref, workspace.project_id)
        if not obj:
            continue
        node_id = f"object:{obj['id']}"
        props = obj.get("properties") or {}
        risk = _risk_for_ref(db, ref, workspace.project_id)
        nodes[node_id] = {
            "id": node_id,
            "kind": "object",
            "label": props.get("name") or props.get("title") or obj["id"],
            "object_type_id": obj["object_type_id"],
            "risk": risk,
            "properties": props,
        }
        edges.append({"source": f"investigation:{workspace.id}", "target": node_id, "kind": "contains"})

    for item in evidence:
        node_id = f"evidence:{item.id}"
        nodes[node_id] = {"id": node_id, "kind": "evidence", "label": item.title, "tags": item.tags or []}
        edges.append({"source": f"investigation:{workspace.id}", "target": node_id, "kind": "has_evidence"})
        for ref in item.object_refs or []:
            target = f"object:{ref.get('object_id')}"
            if target in nodes:
                edges.append({"source": node_id, "target": target, "kind": "supports"})

    for hypothesis in hypotheses:
        node_id = f"hypothesis:{hypothesis.id}"
        nodes[node_id] = {"id": node_id, "kind": "hypothesis", "label": hypothesis.statement, "status": hypothesis.status, "confidence": hypothesis.confidence}
        edges.append({"source": f"investigation:{workspace.id}", "target": node_id, "kind": "has_hypothesis"})
        for evidence_id in hypothesis.linked_evidence_ids or []:
            target = f"evidence:{evidence_id}"
            if target in nodes:
                edges.append({"source": target, "target": node_id, "kind": "informs"})

    object_ids = [ref.get("object_id") for ref in refs]
    links = db.query(models.LinkInstance).filter(
        models.LinkInstance.project_id == workspace.project_id,
        (models.LinkInstance.source_object_id.in_(object_ids)) | (models.LinkInstance.target_object_id.in_(object_ids))
    ).all() if object_ids else []
    for link in links:
        source = f"object:{link.source_object_id}"
        target = f"object:{link.target_object_id}"
        if source in nodes and target in nodes:
            edges.append({"source": source, "target": target, "kind": link.link_type_id, "properties": link.properties or {}})

    return {"nodes": list(nodes.values()), "edges": edges, "node_count": len(nodes), "edge_count": len(edges)}


@router.get("/investigations/{investigation_id}/timeline")
def investigation_timeline(investigation_id: str, db: Session = Depends(get_db), principal: production_auth.Principal = Depends(production_auth.require_permission("view"))):
    workspace = _get_workspace(db, investigation_id, principal)
    evidence = db.query(EvidenceItem).filter(EvidenceItem.project_id == workspace.project_id, EvidenceItem.investigation_id == investigation_id).all()
    hypotheses = db.query(InvestigationHypothesis).filter(InvestigationHypothesis.project_id == workspace.project_id, InvestigationHypothesis.investigation_id == investigation_id).all()
    reports = db.query(InvestigationReport).filter(InvestigationReport.project_id == workspace.project_id, InvestigationReport.investigation_id == investigation_id).all()
    events = [
        {"at": workspace.created_at, "kind": "investigation", "title": "Investigation created", "id": workspace.id},
        {"at": workspace.updated_at, "kind": "investigation", "title": "Investigation updated", "id": workspace.id},
    ]
    events.extend({"at": item.created_at, "kind": "evidence", "title": item.title, "id": item.id} for item in evidence)
    events.extend({"at": item.updated_at, "kind": "hypothesis", "title": item.statement, "id": item.id, "status": item.status} for item in hypotheses)
    events.extend({"at": item.created_at, "kind": "report", "title": item.title, "id": item.id} for item in reports)

    refs = _all_object_refs(workspace, evidence)
    try:
        from . import decision_intelligence
        for ref in refs:
            for snap in decision_intelligence._timeline(db, str(ref.get("object_type_id")), str(ref.get("object_id"))):
                events.append({
                    "at": snap.get("created_at"),
                    "kind": "object_snapshot",
                    "title": snap.get("event_type"),
                    "id": snap.get("id"),
                    "object_id": ref.get("object_id"),
                    "seq": snap.get("seq"),
                })
    except Exception:
        pass
    return {"investigation_id": investigation_id, "timeline": sorted(events, key=lambda item: item.get("at") or 0)}


@router.post("/investigations/{investigation_id}/report")
def create_report(investigation_id: str, body: ReportRequest = ReportRequest(), db: Session = Depends(get_db), principal: production_auth.Principal = Depends(production_auth.require_permission("export"))):
    workspace = _get_workspace(db, investigation_id, principal, "export")
    evidence = db.query(EvidenceItem).filter(EvidenceItem.project_id == workspace.project_id, EvidenceItem.investigation_id == investigation_id).order_by(EvidenceItem.created_at.asc()).all()
    hypotheses = db.query(InvestigationHypothesis).filter(InvestigationHypothesis.project_id == workspace.project_id, InvestigationHypothesis.investigation_id == investigation_id).order_by(InvestigationHypothesis.updated_at.desc()).all()
    refs = _all_object_refs(workspace, evidence)
    risks = {ref.get("object_id"): _risk_for_ref(db, ref, workspace.project_id) for ref in refs}
    high_risk = [
        {"object_id": object_id, "band": risk.get("band"), "score": risk.get("score")}
        for object_id, risk in risks.items()
        if risk and risk.get("band") in {"high", "critical"}
    ]
    title = body.title or f"{workspace.display_name} Report"
    sections = [
        {"title": "Summary", "content": f"{workspace.display_name} has {len(refs)} linked object(s), {len(evidence)} evidence item(s), and {len(hypotheses)} hypothesis record(s)."},
        {"title": "High Risk Objects", "content": high_risk},
        {"title": "Evidence", "content": [_evidence_dict(item) for item in evidence]},
        {"title": "Hypotheses", "content": [_hypothesis_dict(item) for item in hypotheses]},
    ]
    body_text = "\n\n".join([
        f"# {title}",
        sections[0]["content"],
        "High risk objects: " + (", ".join(f"{item['object_id']} ({item['band']} {item['score']})" for item in high_risk) or "none"),
        "Evidence: " + (", ".join(item.title for item in evidence) or "none"),
        "Hypotheses: " + (", ".join(f"{item.statement} [{item.status}]" for item in hypotheses) or "none"),
    ])
    report = InvestigationReport(
        id=_new_id("report"),
        project_id=workspace.project_id,
        investigation_id=investigation_id,
        title=title,
        body=body_text,
        sections=sections,
        created_at=_now(),
    )
    db.add(report)
    finding = InvestigationFinding(
        id=_new_id("finding"),
        project_id=workspace.project_id,
        investigation_id=investigation_id,
        title="Report generated",
        severity="high" if high_risk else "medium",
        summary=f"Generated report with {len(high_risk)} high-risk object(s).",
        object_refs=refs,
        evidence_ids=[item.id for item in evidence],
        created_at=_now(),
    )
    db.add(finding)
    _audit(db, "investigation.report.created", "investigation_report", report.id, {"investigation_id": investigation_id, "high_risk": len(high_risk)})
    db.commit()
    db.refresh(report)
    return _report_dict(report)

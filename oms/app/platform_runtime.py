"""Shared versioned artifacts, editing leases, and asynchronous job evidence."""
from __future__ import annotations

import asyncio
import time
import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import Boolean, Integer, JSON, String, UniqueConstraint
from sqlalchemy.orm import Mapped, Session, mapped_column

from . import models_action, ops_control
from .database import Base, get_db
from .production_auth import Principal, require_permission

router = APIRouter(tags=["platform_runtime"])


def _now() -> int:
    return int(time.time())


def _id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:16]}"


class PlatformArtifact(Base):
    __tablename__ = "platform_artifacts"

    id: Mapped[str] = mapped_column(String, primary_key=True, index=True)
    project_id: Mapped[str] = mapped_column(String, default="default", index=True)
    artifact_type: Mapped[str] = mapped_column(String, index=True)
    display_name: Mapped[str] = mapped_column(String)
    description: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    status: Mapped[str] = mapped_column(String, default="DRAFT", index=True)
    current_revision: Mapped[int] = mapped_column(Integer, default=1)
    published_revision: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    lock_version: Mapped[int] = mapped_column(Integer, default=1)
    owner: Mapped[str] = mapped_column(String, default="workspace", index=True)
    metadata_: Mapped[dict] = mapped_column("metadata", JSON, default=dict)
    created_at: Mapped[int] = mapped_column(Integer)
    updated_at: Mapped[int] = mapped_column(Integer)


class ArtifactRevision(Base):
    __tablename__ = "platform_artifact_revisions"
    __table_args__ = (UniqueConstraint("artifact_id", "revision", name="uq_artifact_revision"),)

    id: Mapped[str] = mapped_column(String, primary_key=True, index=True)
    artifact_id: Mapped[str] = mapped_column(String, index=True)
    revision: Mapped[int] = mapped_column(Integer)
    state: Mapped[dict] = mapped_column(JSON, default=dict)
    layout: Mapped[dict] = mapped_column(JSON, default=dict)
    validation: Mapped[dict] = mapped_column(JSON, default=dict)
    author: Mapped[str] = mapped_column(String)
    message: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    published: Mapped[bool] = mapped_column(Boolean, default=False)
    restored_from_revision: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    created_at: Mapped[int] = mapped_column(Integer)


class ArtifactLease(Base):
    __tablename__ = "platform_artifact_leases"

    id: Mapped[str] = mapped_column(String, primary_key=True, index=True)
    artifact_id: Mapped[str] = mapped_column(String, unique=True, index=True)
    holder: Mapped[str] = mapped_column(String, index=True)
    token: Mapped[str] = mapped_column(String, unique=True, index=True)
    created_at: Mapped[int] = mapped_column(Integer)
    updated_at: Mapped[int] = mapped_column(Integer)
    expires_at: Mapped[int] = mapped_column(Integer, index=True)


class PlatformJob(Base):
    __tablename__ = "platform_jobs"

    id: Mapped[str] = mapped_column(String, primary_key=True, index=True)
    job_type: Mapped[str] = mapped_column(String, index=True)
    status: Mapped[str] = mapped_column(String, default="QUEUED", index=True)
    actor: Mapped[str] = mapped_column(String, index=True)
    subject_type: Mapped[Optional[str]] = mapped_column(String, nullable=True, index=True)
    subject_id: Mapped[Optional[str]] = mapped_column(String, nullable=True, index=True)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    result: Mapped[dict] = mapped_column(JSON, default=dict)
    error: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    attempt: Mapped[int] = mapped_column(Integer, default=1)
    progress: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[int] = mapped_column(Integer)
    updated_at: Mapped[int] = mapped_column(Integer)
    started_at: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    completed_at: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)


class PlatformJobEvent(Base):
    __tablename__ = "platform_job_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[str] = mapped_column(String, index=True)
    event_type: Mapped[str] = mapped_column(String, index=True)
    status: Mapped[str] = mapped_column(String, index=True)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[int] = mapped_column(Integer, index=True)


class ArtifactCreate(BaseModel):
    id: Optional[str] = None
    project_id: str = "default"
    artifact_type: str
    display_name: str
    description: Optional[str] = None
    state: Dict[str, Any] = Field(default_factory=dict)
    layout: Dict[str, Any] = Field(default_factory=dict)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    message: Optional[str] = "Initial draft"


class ArtifactPatch(BaseModel):
    expected_lock_version: int
    display_name: Optional[str] = None
    description: Optional[str] = None
    state: Optional[Dict[str, Any]] = None
    layout: Optional[Dict[str, Any]] = None
    metadata: Optional[Dict[str, Any]] = None
    message: Optional[str] = None
    lease_token: Optional[str] = None


class LeaseRequest(BaseModel):
    ttl_seconds: int = Field(default=120, ge=30, le=900)
    token: Optional[str] = None


class PublishRequest(BaseModel):
    expected_lock_version: Optional[int] = None
    message: Optional[str] = "Published"


class JobCreate(BaseModel):
    job_type: str
    subject_type: Optional[str] = None
    subject_id: Optional[str] = None
    payload: Dict[str, Any] = Field(default_factory=dict)


class ArtifactAdoptRequest(BaseModel):
    resource_type: str
    resource_id: str
    project_id: str = "default"
    display_name: Optional[str] = None


def _audit(db: Session, actor: str, event_type: str, subject_type: str, subject_id: str, payload: Dict[str, Any]) -> None:
    db.add(models_action.AuditLog(
        id=uuid.uuid4().hex,
        actor=actor,
        event_type=event_type,
        subject_type=subject_type,
        subject_id=subject_id,
        payload=payload,
    ))
    db.add(ops_control.OpsEvent(
        id=_id("event"),
        source="platform_runtime",
        event_type=event_type,
        severity="info",
        status="OPEN",
        title=event_type.replace(".", " ").title(),
        subject_type=subject_type,
        subject_id=subject_id,
        payload=payload,
        created_at=_now(),
    ))


def _artifact(db: Session, artifact_id: str) -> PlatformArtifact:
    row = db.get(PlatformArtifact, artifact_id)
    if not row:
        raise HTTPException(status_code=404, detail=f"Artifact '{artifact_id}' not found")
    return row


def _revision(db: Session, artifact_id: str, revision: int) -> ArtifactRevision:
    row = db.query(ArtifactRevision).filter(
        ArtifactRevision.artifact_id == artifact_id,
        ArtifactRevision.revision == revision,
    ).first()
    if not row:
        raise HTTPException(status_code=404, detail=f"Revision {revision} not found")
    return row


def _validate_state(artifact_type: str, state: Dict[str, Any]) -> Dict[str, Any]:
    errors: List[Dict[str, Any]] = []
    warnings: List[Dict[str, Any]] = []
    if not isinstance(state, dict):
        errors.append({"path": "/state", "message": "Artifact state must be an object"})
    if artifact_type in {"pipeline", "aip_logic", "investigation_graph", "platform_graph", "entity_resolution"}:
        nodes = state.get("nodes", []) if isinstance(state, dict) else []
        edges = state.get("edges", []) if isinstance(state, dict) else []
        ids = [item.get("id") for item in nodes if isinstance(item, dict)]
        if len(ids) != len(set(ids)):
            errors.append({"path": "/state/nodes", "message": "Node IDs must be unique"})
        known = set(ids)
        for index, edge in enumerate(edges):
            if not isinstance(edge, dict) or edge.get("source") not in known or edge.get("target") not in known:
                errors.append({"path": f"/state/edges/{index}", "message": "Edge references an unknown node"})
        if not nodes:
            warnings.append({"path": "/state/nodes", "message": "The canvas has no nodes"})
    if artifact_type == "ontology":
        object_types = state.get("object_types", []) if isinstance(state, dict) else []
        if not object_types:
            warnings.append({"path": "/state/object_types", "message": "The ontology has no object types"})
    if artifact_type == "workshop" and not state.get("widgets"):
        warnings.append({"path": "/state/widgets", "message": "The application has no widgets"})
    return {"status": "FAIL" if errors else ("WARN" if warnings else "PASS"), "errors": errors, "warnings": warnings}


def _artifact_dict(db: Session, row: PlatformArtifact) -> Dict[str, Any]:
    revision = _revision(db, row.id, row.current_revision)
    lease = db.query(ArtifactLease).filter(ArtifactLease.artifact_id == row.id).first()
    if lease and lease.expires_at <= _now():
        db.delete(lease)
        lease = None
    return {
        "id": row.id,
        "project_id": row.project_id,
        "artifact_type": row.artifact_type,
        "display_name": row.display_name,
        "description": row.description,
        "status": row.status,
        "current_revision": row.current_revision,
        "published_revision": row.published_revision,
        "lock_version": row.lock_version,
        "owner": row.owner,
        "metadata": row.metadata_ or {},
        "state": revision.state or {},
        "layout": revision.layout or {},
        "validation": revision.validation or {},
        "lease": None if not lease else {"holder": lease.holder, "expires_at": lease.expires_at},
        "permissions": ["view", "edit", "publish", "restore"],
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


def _assert_lease(db: Session, artifact_id: str, actor: str, token: Optional[str]) -> None:
    lease = db.query(ArtifactLease).filter(ArtifactLease.artifact_id == artifact_id).first()
    if not lease or lease.expires_at <= _now():
        if lease:
            db.delete(lease)
        return
    if lease.holder != actor or not token or token != lease.token:
        raise HTTPException(status_code=423, detail={"message": "Artifact is being edited", "holder": lease.holder, "expires_at": lease.expires_at})


@router.post("/artifacts", status_code=201)
def create_artifact(body: ArtifactCreate, principal: Principal = Depends(require_permission("edit")), db: Session = Depends(get_db)):
    artifact_id = body.id or _id("artifact")
    if db.get(PlatformArtifact, artifact_id):
        raise HTTPException(status_code=409, detail="Artifact already exists")
    if body.artifact_type not in {"pipeline", "ontology", "workshop", "aip_logic", "investigation_graph", "platform_graph", "entity_resolution"}:
        raise HTTPException(status_code=422, detail="Unsupported artifact type")
    now = _now()
    validation = _validate_state(body.artifact_type, body.state)
    row = PlatformArtifact(
        id=artifact_id, project_id=body.project_id, artifact_type=body.artifact_type,
        display_name=body.display_name.strip(), description=body.description, owner=principal.id,
        metadata_=body.metadata, created_at=now, updated_at=now,
    )
    db.add(row)
    db.add(ArtifactRevision(
        id=_id("revision"), artifact_id=artifact_id, revision=1, state=body.state,
        layout=body.layout, validation=validation, author=principal.id, message=body.message,
        published=False, created_at=now,
    ))
    _audit(db, principal.id, "artifact.created", "artifact", artifact_id, {"artifact_type": body.artifact_type, "revision": 1})
    db.commit()
    return _artifact_dict(db, row)


@router.post("/artifacts/adopt", status_code=201)
def adopt_resource(body: ArtifactAdoptRequest, principal: Principal = Depends(require_permission("edit")), db: Session = Depends(get_db)):
    """Create a versioned visual draft from an existing pipeline or ontology type."""
    from . import models, pipeline_builder_ops

    source_key = f"{body.resource_type}:{body.resource_id}"
    existing = db.query(PlatformArtifact).filter(PlatformArtifact.project_id == body.project_id).all()
    for artifact in existing:
        if (artifact.metadata_ or {}).get("source_key") == source_key:
            return _artifact_dict(db, artifact)

    if body.resource_type == "pipeline_builder_graph":
        graph = db.get(pipeline_builder_ops.PipelineBuilderGraph, body.resource_id)
        if not graph:
            raise HTTPException(status_code=404, detail="Pipeline graph not found")
        nodes = []
        for index, node in enumerate(graph.nodes or []):
            node_type = pipeline_builder_ops._node_type(node)
            position = pipeline_builder_ops._node_position(node, index)
            nodes.append({
                "id": pipeline_builder_ops._node_id(node, index),
                "position": position,
                "data": {
                    "label": node.get("label") or node_type.replace("_", " ").title(),
                    "description": (pipeline_builder_ops._node_catalog_by_type().get(node_type) or {}).get("description", ""),
                    "nodeType": node_type,
                    "fields": [{"id": f"{index}_{key}", "name": key, "value": str(value)} for key, value in pipeline_builder_ops._config(node).items()],
                },
            })
        state = {"nodes": nodes, "edges": copy_json(graph.edges or [])}
        artifact_type = "pipeline"
        display_name = body.display_name or graph.display_name
        description = graph.description
    elif body.resource_type == "object_type":
        selected = db.get(models.ObjectType, body.resource_id)
        if not selected:
            raise HTTPException(status_code=404, detail="Object type not found")
        links = db.query(models.LinkType).filter(
            (models.LinkType.source_object_type_id == selected.id) | (models.LinkType.target_object_type_id == selected.id)
        ).all()
        type_ids = {selected.id} | {link.source_object_type_id for link in links} | {link.target_object_type_id for link in links}
        object_types = [row for row in db.query(models.ObjectType).filter(models.ObjectType.id.in_(type_ids)).all()]
        nodes = [{
            "id": row.id,
            "position": {"x": 120 + index * 260, "y": 180 + (index % 2) * 140},
            "data": {
                "label": row.display_name,
                "description": row.description or "Ontology object type",
                "nodeType": "object_type",
                "fields": [{"id": f"{row.id}_{name}", "name": name, "value": str((spec or {}).get("type", "string")) if isinstance(spec, dict) else str(spec)} for name, spec in (row.properties or {}).items() if not name.startswith("__")],
            },
        } for index, row in enumerate(object_types)]
        state = {
            "nodes": nodes,
            "edges": [{"id": link.id, "source": link.source_object_type_id, "target": link.target_object_type_id, "data": {"label": link.display_name, "cardinality": link.cardinality}} for link in links],
            "object_types": [{"id": row.id, "display_name": row.display_name, "properties": row.properties or {}} for row in object_types],
        }
        artifact_type = "ontology"
        display_name = body.display_name or f"{selected.display_name} ontology"
        description = selected.description
    else:
        raise HTTPException(status_code=422, detail="resource_type must be pipeline_builder_graph or object_type")

    create = ArtifactCreate(
        project_id=body.project_id,
        artifact_type=artifact_type,
        display_name=display_name,
        description=description,
        state=state,
        layout={node["id"]: node["position"] for node in state["nodes"]},
        metadata={"source_key": source_key, "source_type": body.resource_type, "source_id": body.resource_id},
        message="Adopted existing resource",
    )
    return create_artifact(create, principal, db)


def copy_json(value: Any) -> Any:
    import copy
    return copy.deepcopy(value)


@router.get("/artifacts")
def list_artifacts(project_id: Optional[str] = None, artifact_type: Optional[str] = None, principal: Principal = Depends(require_permission("view")), db: Session = Depends(get_db)):
    query = db.query(PlatformArtifact)
    if project_id:
        query = query.filter(PlatformArtifact.project_id == project_id)
    if artifact_type:
        query = query.filter(PlatformArtifact.artifact_type == artifact_type)
    return [_artifact_dict(db, row) for row in query.order_by(PlatformArtifact.updated_at.desc()).all()]


@router.get("/artifacts/{artifact_id}")
def get_artifact(artifact_id: str, principal: Principal = Depends(require_permission("view")), db: Session = Depends(get_db)):
    return _artifact_dict(db, _artifact(db, artifact_id))


@router.patch("/artifacts/{artifact_id}")
def update_artifact(artifact_id: str, body: ArtifactPatch, principal: Principal = Depends(require_permission("edit")), db: Session = Depends(get_db)):
    row = _artifact(db, artifact_id)
    if body.expected_lock_version != row.lock_version:
        raise HTTPException(status_code=409, detail={"message": "Artifact changed since it was loaded", "current_lock_version": row.lock_version})
    _assert_lease(db, artifact_id, principal.id, body.lease_token)
    current = _revision(db, artifact_id, row.current_revision)
    state = body.state if body.state is not None else dict(current.state or {})
    layout = body.layout if body.layout is not None else dict(current.layout or {})
    validation = _validate_state(row.artifact_type, state)
    row.current_revision += 1
    row.lock_version += 1
    row.updated_at = _now()
    row.status = "DRAFT"
    if body.display_name is not None:
        row.display_name = body.display_name.strip()
    if body.description is not None:
        row.description = body.description
    if body.metadata is not None:
        row.metadata_ = body.metadata
    db.add(ArtifactRevision(
        id=_id("revision"), artifact_id=row.id, revision=row.current_revision, state=state,
        layout=layout, validation=validation, author=principal.id, message=body.message or "Autosaved change",
        published=False, created_at=_now(),
    ))
    _audit(db, principal.id, "artifact.revision.created", "artifact", row.id, {"revision": row.current_revision, "lock_version": row.lock_version})
    db.commit()
    return _artifact_dict(db, row)


@router.post("/artifacts/{artifact_id}/validate")
def validate_artifact(artifact_id: str, principal: Principal = Depends(require_permission("view")), db: Session = Depends(get_db)):
    row = _artifact(db, artifact_id)
    revision = _revision(db, artifact_id, row.current_revision)
    revision.validation = _validate_state(row.artifact_type, revision.state or {})
    db.commit()
    return {"artifact_id": artifact_id, "revision": row.current_revision, **revision.validation}


@router.post("/artifacts/{artifact_id}/publish")
def publish_artifact(artifact_id: str, body: PublishRequest, principal: Principal = Depends(require_permission("publish")), db: Session = Depends(get_db)):
    row = _artifact(db, artifact_id)
    if body.expected_lock_version is not None and body.expected_lock_version != row.lock_version:
        raise HTTPException(status_code=409, detail={"message": "Artifact changed since it was loaded", "current_lock_version": row.lock_version})
    revision = _revision(db, artifact_id, row.current_revision)
    revision.validation = _validate_state(row.artifact_type, revision.state or {})
    if revision.validation.get("status") == "FAIL":
        raise HTTPException(status_code=422, detail={"message": "Artifact validation failed", "validation": revision.validation})
    revision.published = True
    revision.message = body.message or revision.message
    row.published_revision = row.current_revision
    row.status = "PUBLISHED"
    row.lock_version += 1
    row.updated_at = _now()
    _audit(db, principal.id, "artifact.published", "artifact", row.id, {"revision": row.current_revision})
    db.commit()
    return _artifact_dict(db, row)


@router.get("/artifacts/{artifact_id}/versions")
def artifact_versions(artifact_id: str, principal: Principal = Depends(require_permission("view")), db: Session = Depends(get_db)):
    _artifact(db, artifact_id)
    rows = db.query(ArtifactRevision).filter(ArtifactRevision.artifact_id == artifact_id).order_by(ArtifactRevision.revision.desc()).all()
    return [{
        "id": row.id, "revision": row.revision, "author": row.author, "message": row.message,
        "published": row.published, "restored_from_revision": row.restored_from_revision,
        "validation": row.validation, "created_at": row.created_at,
    } for row in rows]


@router.get("/artifacts/{artifact_id}/diff")
def artifact_diff(artifact_id: str, from_revision: int = Query(...), to_revision: Optional[int] = None, principal: Principal = Depends(require_permission("view")), db: Session = Depends(get_db)):
    row = _artifact(db, artifact_id)
    before = _revision(db, artifact_id, from_revision)
    after = _revision(db, artifact_id, to_revision or row.current_revision)
    keys = sorted(set((before.state or {}).keys()) | set((after.state or {}).keys()))
    changed = [{"path": f"/{key}", "before": (before.state or {}).get(key), "after": (after.state or {}).get(key)} for key in keys if (before.state or {}).get(key) != (after.state or {}).get(key)]
    layout_changed = before.layout != after.layout
    return {"artifact_id": artifact_id, "from_revision": before.revision, "to_revision": after.revision, "changed": changed, "layout_changed": layout_changed}


@router.post("/artifacts/{artifact_id}/versions/{version}/restore")
def restore_artifact(artifact_id: str, version: int, principal: Principal = Depends(require_permission("restore")), db: Session = Depends(get_db)):
    row = _artifact(db, artifact_id)
    source = _revision(db, artifact_id, version)
    row.current_revision += 1
    row.lock_version += 1
    row.status = "DRAFT"
    row.updated_at = _now()
    db.add(ArtifactRevision(
        id=_id("revision"), artifact_id=artifact_id, revision=row.current_revision,
        state=source.state, layout=source.layout, validation=source.validation, author=principal.id,
        message=f"Restored revision {version}", published=False, restored_from_revision=version, created_at=_now(),
    ))
    _audit(db, principal.id, "artifact.restored", "artifact", artifact_id, {"source_revision": version, "revision": row.current_revision})
    db.commit()
    return _artifact_dict(db, row)


@router.post("/artifacts/{artifact_id}/leases")
def acquire_lease(artifact_id: str, body: LeaseRequest, principal: Principal = Depends(require_permission("edit")), db: Session = Depends(get_db)):
    _artifact(db, artifact_id)
    lease = db.query(ArtifactLease).filter(ArtifactLease.artifact_id == artifact_id).first()
    now = _now()
    expired = bool(lease and lease.expires_at <= now)
    if lease and not expired and lease.holder != principal.id:
        raise HTTPException(status_code=423, detail={"message": "Artifact is being edited", "holder": lease.holder, "expires_at": lease.expires_at})
    if lease and lease.holder == principal.id and body.token and body.token != lease.token:
        raise HTTPException(status_code=409, detail="Lease token does not match")
    if not lease:
        lease = ArtifactLease(id=_id("lease"), artifact_id=artifact_id, holder=principal.id, token=uuid.uuid4().hex, created_at=now, updated_at=now, expires_at=now + body.ttl_seconds)
        db.add(lease)
    else:
        lease.holder = principal.id
        lease.updated_at = now
        lease.expires_at = now + body.ttl_seconds
        if expired:
            lease.token = uuid.uuid4().hex
    db.commit()
    return {"artifact_id": artifact_id, "holder": lease.holder, "token": lease.token, "expires_at": lease.expires_at}


def _job_event(db: Session, row: PlatformJob, event_type: str, payload: Optional[Dict[str, Any]] = None) -> None:
    db.add(PlatformJobEvent(job_id=row.id, event_type=event_type, status=row.status, payload=payload or {}, created_at=_now()))


@router.post("/jobs", status_code=201)
def create_job(body: JobCreate, principal: Principal = Depends(require_permission("execute")), db: Session = Depends(get_db)):
    now = _now()
    row = PlatformJob(id=_id("job"), job_type=body.job_type, status="QUEUED", actor=principal.id, subject_type=body.subject_type, subject_id=body.subject_id, payload=body.payload, result={}, attempt=1, progress=0, created_at=now, updated_at=now)
    db.add(row)
    db.flush()
    _job_event(db, row, "job.queued")
    _audit(db, principal.id, "job.queued", "platform_job", row.id, {"job_type": row.job_type})
    db.commit()
    return _job_dict(row)


def _job_dict(row: PlatformJob) -> Dict[str, Any]:
    return {column: getattr(row, column) for column in ("id", "job_type", "status", "actor", "subject_type", "subject_id", "payload", "result", "error", "attempt", "progress", "created_at", "updated_at", "started_at", "completed_at")}


@router.get("/jobs/{job_id}")
def get_job(job_id: str, principal: Principal = Depends(require_permission("view")), db: Session = Depends(get_db)):
    row = db.get(PlatformJob, job_id)
    if not row:
        raise HTTPException(status_code=404, detail="Job not found")
    result = _job_dict(row)
    result["events"] = [{"id": event.id, "event_type": event.event_type, "status": event.status, "payload": event.payload, "created_at": event.created_at} for event in db.query(PlatformJobEvent).filter(PlatformJobEvent.job_id == job_id).order_by(PlatformJobEvent.id).all()]
    return result


@router.post("/jobs/{job_id}/cancel")
def cancel_job(job_id: str, principal: Principal = Depends(require_permission("execute")), db: Session = Depends(get_db)):
    row = db.get(PlatformJob, job_id)
    if not row:
        raise HTTPException(status_code=404, detail="Job not found")
    if row.status in {"SUCCEEDED", "FAILED", "CANCELLED"}:
        raise HTTPException(status_code=409, detail=f"Job is already {row.status}")
    row.status = "CANCELLED"
    row.updated_at = row.completed_at = _now()
    _job_event(db, row, "job.cancelled", {"actor": principal.id})
    _audit(db, principal.id, "job.cancelled", "platform_job", row.id, {})
    db.commit()
    return _job_dict(row)


@router.post("/jobs/{job_id}/retry")
def retry_job(job_id: str, principal: Principal = Depends(require_permission("execute")), db: Session = Depends(get_db)):
    row = db.get(PlatformJob, job_id)
    if not row:
        raise HTTPException(status_code=404, detail="Job not found")
    if row.status not in {"FAILED", "CANCELLED"}:
        raise HTTPException(status_code=409, detail="Only failed or cancelled jobs can be retried")
    row.status = "QUEUED"
    row.attempt += 1
    row.progress = 0
    row.error = None
    row.result = {}
    row.started_at = row.completed_at = None
    row.updated_at = _now()
    _job_event(db, row, "job.retried", {"attempt": row.attempt, "actor": principal.id})
    _audit(db, principal.id, "job.retried", "platform_job", row.id, {"attempt": row.attempt})
    db.commit()
    return _job_dict(row)


@router.get("/events/stream")
async def event_stream(request: Request, after: int = 0, job_id: Optional[str] = None, once: bool = False, principal: Principal = Depends(require_permission("view"))):
    async def generate():
        cursor = after
        idle_cycles = 0
        while True:
            db = next(get_db())
            try:
                query = db.query(PlatformJobEvent).filter(PlatformJobEvent.id > cursor)
                if job_id:
                    query = query.filter(PlatformJobEvent.job_id == job_id)
                events = query.order_by(PlatformJobEvent.id).limit(100).all()
                for event in events:
                    cursor = event.id
                    data = json_dumps({"id": event.id, "job_id": event.job_id, "event_type": event.event_type, "status": event.status, "payload": event.payload, "created_at": event.created_at})
                    yield f"id: {event.id}\nevent: {event.event_type}\ndata: {data}\n\n"
            finally:
                db.close()
            if once:
                break
            if await request.is_disconnected():
                break
            idle_cycles += 1
            if idle_cycles % 15 == 0:
                yield ": heartbeat\n\n"
            await asyncio.sleep(1)

    return StreamingResponse(generate(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


def json_dumps(value: Dict[str, Any]) -> str:
    import json
    return json.dumps(value, separators=(",", ":"), default=str)

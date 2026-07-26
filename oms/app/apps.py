"""
apps.py — Foundry WORKSHOP, SLATE, and CARBON module implementations.

- WorkshopModule  → operational app modules with widget-based layouts
- SlateApp        → low-code app builder with queries, widgets, and functions
- CarbonWorkspace → workspace bundling that composes multiple modules
"""
import time
import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import JSON, Integer, String
from sqlalchemy.orm import Mapped, Session, mapped_column

from . import models, models_action, tenancy
from .database import Base, get_db
from .production_auth import Principal, require_permission

# ---------------------------------------------------------------------------
# SQLAlchemy ORM Models
# ---------------------------------------------------------------------------


class WorkshopModule(Base):
    """Foundry Workshop operational app module."""

    __tablename__ = "workshop_modules"

    id: Mapped[str] = mapped_column(String, primary_key=True, index=True)
    project_id: Mapped[str] = mapped_column(String, default="default", index=True)
    display_name: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    variables: Mapped[dict] = mapped_column(JSON, default=dict)
    widgets: Mapped[list] = mapped_column(JSON, default=list)
    layout: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[int] = mapped_column(Integer)
    updated_at: Mapped[int] = mapped_column(Integer)


class WorkshopModuleVersion(Base):
    """Published immutable snapshot of a Workshop module."""

    __tablename__ = "workshop_module_versions"

    id: Mapped[str] = mapped_column(String, primary_key=True, index=True)
    module_id: Mapped[str] = mapped_column(String, index=True)
    version_number: Mapped[int] = mapped_column(Integer)
    snapshot: Mapped[dict] = mapped_column(JSON, default=dict)
    note: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    actor: Mapped[str] = mapped_column(String, default="system")
    created_at: Mapped[int] = mapped_column(Integer)


class SlateApp(Base):
    """Foundry Slate low-code application."""

    __tablename__ = "slate_apps"

    id: Mapped[str] = mapped_column(String, primary_key=True, index=True)
    display_name: Mapped[str] = mapped_column(String, nullable=False)
    queries: Mapped[dict] = mapped_column(JSON, default=dict)
    widgets: Mapped[dict] = mapped_column(JSON, default=dict)
    functions: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[int] = mapped_column(Integer)
    updated_at: Mapped[int] = mapped_column(Integer)


class SlateAppVersion(Base):
    """Published immutable snapshot of a Slate app (mirrors WorkshopModuleVersion)."""

    __tablename__ = "slate_app_versions"

    id: Mapped[str] = mapped_column(String, primary_key=True, index=True)
    app_id: Mapped[str] = mapped_column(String, index=True)
    version_number: Mapped[int] = mapped_column(Integer)
    snapshot: Mapped[dict] = mapped_column(JSON, default=dict)
    note: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    actor: Mapped[str] = mapped_column(String, default="system")
    created_at: Mapped[int] = mapped_column(Integer)


class CarbonWorkspace(Base):
    """Foundry Carbon workspace that bundles multiple modules."""

    __tablename__ = "carbon_workspaces"

    id: Mapped[str] = mapped_column(String, primary_key=True, index=True)
    display_name: Mapped[str] = mapped_column(String, nullable=False)
    module_ids: Mapped[list] = mapped_column(JSON, default=list)
    navigation: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[int] = mapped_column(Integer)
    updated_at: Mapped[int] = mapped_column(Integer)


# ---------------------------------------------------------------------------
# Pydantic Schemas
# ---------------------------------------------------------------------------

# --- Workshop ---

class WidgetSchema(BaseModel):
    type: str
    title: str
    variable: Optional[str] = None          # binds the widget to a Workshop variable
    object_type_id: Optional[str] = None
    saved_object_set_id: Optional[str] = None
    action_type_id: Optional[str] = None
    config: Optional[Dict[str, Any]] = Field(default_factory=dict)


class WorkshopModuleCreate(BaseModel):
    id: Optional[str] = None
    project_id: str = "default"
    display_name: str
    description: Optional[str] = None
    variables: Optional[Dict[str, Any]] = Field(default_factory=dict)
    widgets: Optional[List[WidgetSchema]] = Field(default_factory=list)
    layout: Optional[Dict[str, Any]] = Field(default_factory=dict)
    actor: Optional[str] = "system"


class WorkshopModuleRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    project_id: str
    display_name: str
    description: Optional[str] = None
    variables: Dict[str, Any]
    widgets: List[Any]
    layout: Dict[str, Any]
    created_at: int
    updated_at: int


class WorkshopModuleUpdate(BaseModel):
    display_name: Optional[str] = None
    description: Optional[str] = None
    variables: Optional[Dict[str, Any]] = None
    widgets: Optional[List[Any]] = None
    layout: Optional[Dict[str, Any]] = None
    actor: Optional[str] = "system"


class WorkshopPublishRequest(BaseModel):
    note: Optional[str] = None
    actor: Optional[str] = "system"


class WorkshopModuleVersionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    module_id: str
    version_number: int
    snapshot: Dict[str, Any]
    note: Optional[str] = None
    actor: str
    created_at: int


class ResolvedWidget(BaseModel):
    type: str
    title: str
    object_type_id: Optional[str] = None
    saved_object_set_id: Optional[str] = None
    action_type_id: Optional[str] = None
    config: Optional[Dict[str, Any]] = None
    resolved: Optional[Dict[str, Any]] = None


class WorkshopRenderResponse(BaseModel):
    module_id: str
    widgets: List[ResolvedWidget]


# --- Slate ---

class SlateAppCreate(BaseModel):
    id: Optional[str] = None
    display_name: str
    queries: Optional[Dict[str, Any]] = Field(default_factory=dict)
    widgets: Optional[Dict[str, Any]] = Field(default_factory=dict)
    functions: Optional[Dict[str, Any]] = Field(default_factory=dict)
    actor: Optional[str] = "system"


class SlateAppRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    display_name: str
    queries: Dict[str, Any]
    widgets: Dict[str, Any]
    functions: Dict[str, Any]
    created_at: int
    updated_at: int


class SlateAppUpdate(BaseModel):
    display_name: Optional[str] = None
    queries: Optional[Dict[str, Any]] = None
    widgets: Optional[Dict[str, Any]] = None
    functions: Optional[Dict[str, Any]] = None
    actor: Optional[str] = "system"


class SlatePublishRequest(BaseModel):
    note: Optional[str] = None
    actor: Optional[str] = "system"


class SlateAppVersionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    app_id: str
    version_number: int
    snapshot: Dict[str, Any]
    note: Optional[str] = None
    actor: str
    created_at: int


# --- Carbon ---

class CarbonWorkspaceCreate(BaseModel):
    id: Optional[str] = None
    display_name: str
    module_ids: Optional[List[str]] = Field(default_factory=list)
    navigation: Optional[Dict[str, Any]] = Field(default_factory=dict)
    actor: Optional[str] = "system"


class CarbonWorkspaceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    display_name: str
    module_ids: List[str]
    navigation: Dict[str, Any]
    created_at: int
    updated_at: int


class CarbonWorkspaceDetail(BaseModel):
    id: str
    display_name: str
    module_ids: List[str]
    navigation: Dict[str, Any]
    created_at: int
    updated_at: int
    resolved_modules: List[Dict[str, Any]]


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

router = APIRouter(tags=["apps"])

_PREVIEW_LIMIT = 5


def _now() -> int:
    return int(time.time())


def _gen_id() -> str:
    return uuid.uuid4().hex


def _append_audit(
    db: Session,
    *,
    actor: str,
    event_type: str,
    subject_type: str,
    subject_id: str,
    payload: Dict[str, Any],
) -> None:
    db.add(
        models_action.AuditLog(
            id=_gen_id(),
            actor=actor,
            event_type=event_type,
            subject_type=subject_type,
            subject_id=subject_id,
            payload=payload,
        )
    )


def _get_workshop_module_or_404(
    db: Session,
    module_id: str,
    principal: Optional[Principal] = None,
    permission: str = "view",
) -> WorkshopModule:
    obj = db.query(WorkshopModule).filter(WorkshopModule.id == module_id).first()
    if not obj:
        raise HTTPException(status_code=404, detail=f"WorkshopModule '{module_id}' not found")
    if principal:
        tenancy.assert_project_permission(db, principal, obj.project_id, permission)
    return obj


def _workshop_snapshot(module: WorkshopModule) -> Dict[str, Any]:
    return {
        "id": module.id,
        "project_id": module.project_id,
        "display_name": module.display_name,
        "description": module.description,
        "variables": module.variables or {},
        "widgets": module.widgets or [],
        "layout": module.layout or {},
        "updated_at": module.updated_at,
    }


def _assert_workshop_object_type_references(
    db: Session,
    project_id: str,
    variables: Dict[str, Any],
    widgets: List[Any],
) -> None:
    referenced = {
        str(spec.get("object_type_id"))
        for spec in (variables or {}).values()
        if isinstance(spec, dict) and spec.get("object_type_id")
    }
    referenced.update(
        str(widget.get("object_type_id"))
        for widget in (widgets or [])
        if isinstance(widget, dict) and widget.get("object_type_id")
    )
    for object_type_id in sorted(referenced):
        object_type = db.get(models.ObjectType, object_type_id)
        if not object_type:
            raise HTTPException(status_code=422, detail=f"Object type '{object_type_id}' not found")
        owning_project = str(((object_type.properties or {}).get("__manager") or {}).get("project_id") or "default")
        if owning_project != project_id:
            raise HTTPException(status_code=403, detail={
                "message": "Workshop cannot reference an object type owned by another project",
                "project_id": project_id,
                "object_type_id": object_type_id,
            })


def _get_slate_app_or_404(db: Session, app_id: str) -> SlateApp:
    obj = db.query(SlateApp).filter(SlateApp.id == app_id).first()
    if not obj:
        raise HTTPException(status_code=404, detail=f"SlateApp '{app_id}' not found")
    return obj


def _slate_snapshot(app_obj: SlateApp) -> Dict[str, Any]:
    return {
        "id": app_obj.id,
        "display_name": app_obj.display_name,
        "queries": app_obj.queries or {},
        "widgets": app_obj.widgets or {},
        "functions": app_obj.functions or {},
        "updated_at": app_obj.updated_at,
    }


# ---------------------------------------------------------------------------
# Workshop Endpoints
# ---------------------------------------------------------------------------


@router.post("/apps/workshop", response_model=WorkshopModuleRead)
def create_workshop_module(
    body: WorkshopModuleCreate,
    principal: Principal = Depends(require_permission("edit")),
    db: Session = Depends(get_db),
) -> WorkshopModule:
    tenancy.assert_project_permission(db, principal, body.project_id, "edit")
    module_id = body.id or _gen_id()
    existing = db.query(WorkshopModule).filter(WorkshopModule.id == module_id).first()
    if existing:
        raise HTTPException(status_code=400, detail="WorkshopModule already exists")

    now = _now()
    widgets_data = [
        w.model_dump() if isinstance(w, WidgetSchema) else w
        for w in (body.widgets or [])
    ]
    _assert_workshop_object_type_references(db, body.project_id, body.variables or {}, widgets_data)
    db_obj = WorkshopModule(
        id=module_id,
        project_id=body.project_id,
        display_name=body.display_name,
        description=body.description,
        variables=body.variables or {},
        widgets=widgets_data,
        layout=body.layout or {},
        created_at=now,
        updated_at=now,
    )
    db.add(db_obj)
    _append_audit(
        db,
        actor=principal.id,
        event_type="apps.workshop.created",
        subject_type="workshop_module",
        subject_id=module_id,
        payload={"project_id": body.project_id, "display_name": body.display_name, "widget_count": len(widgets_data)},
    )
    db.commit()
    db.refresh(db_obj)
    return db_obj


@router.get("/apps/workshop", response_model=List[WorkshopModuleRead])
def list_workshop_modules(
    project_id: Optional[str] = None,
    principal: Principal = Depends(require_permission("view")),
    db: Session = Depends(get_db),
) -> List[WorkshopModule]:
    query = db.query(WorkshopModule)
    if project_id:
        tenancy.assert_project_permission(db, principal, project_id, "view")
        query = query.filter(WorkshopModule.project_id == project_id)
    else:
        accessible = tenancy.accessible_project_ids(db, principal, "view")
        if accessible is not None:
            query = query.filter(WorkshopModule.project_id.in_(accessible)) if accessible else query.filter(WorkshopModule.id == "__none__")
    return query.order_by(WorkshopModule.updated_at.desc()).all()


@router.get("/apps/workshop/{module_id}", response_model=WorkshopModuleRead)
def get_workshop_module(
    module_id: str,
    principal: Principal = Depends(require_permission("view")),
    db: Session = Depends(get_db),
) -> WorkshopModule:
    return _get_workshop_module_or_404(db, module_id, principal, "view")


@router.patch("/apps/workshop/{module_id}", response_model=WorkshopModuleRead)
def update_workshop_module(
    module_id: str,
    body: WorkshopModuleUpdate,
    principal: Principal = Depends(require_permission("edit")),
    db: Session = Depends(get_db),
) -> WorkshopModule:
    obj = _get_workshop_module_or_404(db, module_id, principal, "edit")
    patch = body.model_dump(exclude_unset=True)
    patch.pop("actor", None)
    prospective_variables = patch.get("variables", obj.variables or {})
    prospective_widgets = patch.get("widgets", obj.widgets or [])
    _assert_workshop_object_type_references(db, obj.project_id, prospective_variables, prospective_widgets)
    changed: List[str] = []

    for field in ("display_name", "description", "variables", "widgets", "layout"):
        if field in patch:
            setattr(obj, field, patch[field])
            changed.append(field)

    if changed:
        obj.updated_at = _now()
        _append_audit(
            db,
            actor=principal.id,
            event_type="apps.workshop.updated",
            subject_type="workshop_module",
            subject_id=module_id,
            payload={"project_id": obj.project_id, "changed": changed},
        )
    db.commit()
    db.refresh(obj)
    return obj


@router.post("/apps/workshop/{module_id}/publish", response_model=WorkshopModuleVersionRead)
def publish_workshop_module(
    module_id: str,
    body: WorkshopPublishRequest = WorkshopPublishRequest(),
    principal: Principal = Depends(require_permission("publish")),
    db: Session = Depends(get_db),
) -> WorkshopModuleVersion:
    module = _get_workshop_module_or_404(db, module_id, principal, "publish")
    latest = (
        db.query(WorkshopModuleVersion)
        .filter(WorkshopModuleVersion.module_id == module_id)
        .order_by(WorkshopModuleVersion.version_number.desc())
        .first()
    )
    version = WorkshopModuleVersion(
        id=_gen_id(),
        module_id=module_id,
        version_number=(latest.version_number + 1) if latest else 1,
        snapshot=_workshop_snapshot(module),
        note=body.note,
        actor=principal.id,
        created_at=_now(),
    )
    db.add(version)
    _append_audit(
        db,
        actor=principal.id,
        event_type="apps.workshop.published",
        subject_type="workshop_module",
        subject_id=module_id,
        payload={"project_id": module.project_id, "version_number": version.version_number, "version_id": version.id},
    )
    db.commit()
    db.refresh(version)
    return version


@router.get("/apps/workshop/{module_id}/versions", response_model=List[WorkshopModuleVersionRead])
def list_workshop_versions(
    module_id: str,
    principal: Principal = Depends(require_permission("view")),
    db: Session = Depends(get_db),
) -> List[WorkshopModuleVersion]:
    _get_workshop_module_or_404(db, module_id, principal, "view")
    return (
        db.query(WorkshopModuleVersion)
        .filter(WorkshopModuleVersion.module_id == module_id)
        .order_by(WorkshopModuleVersion.version_number.desc())
        .all()
    )


@router.post("/apps/workshop/{module_id}/versions/{version_id}/restore", response_model=WorkshopModuleRead)
def restore_workshop_version(
    module_id: str,
    version_id: str,
    body: WorkshopPublishRequest = WorkshopPublishRequest(),
    principal: Principal = Depends(require_permission("restore")),
    db: Session = Depends(get_db),
) -> WorkshopModule:
    module = _get_workshop_module_or_404(db, module_id, principal, "restore")
    version_query = db.query(WorkshopModuleVersion).filter(
        WorkshopModuleVersion.module_id == module_id,
        WorkshopModuleVersion.id == version_id,
    )
    if version_id.isdigit():
        version_query = db.query(WorkshopModuleVersion).filter(
            WorkshopModuleVersion.module_id == module_id,
            WorkshopModuleVersion.version_number == int(version_id),
        )
    version = version_query.first()
    if not version:
        raise HTTPException(status_code=404, detail=f"WorkshopModuleVersion '{version_id}' not found")

    snapshot = version.snapshot or {}
    module.display_name = snapshot.get("display_name", module.display_name)
    module.description = snapshot.get("description")
    module.variables = snapshot.get("variables", {})
    module.widgets = snapshot.get("widgets", [])
    module.layout = snapshot.get("layout", {})
    module.updated_at = _now()
    _append_audit(
        db,
        actor=principal.id,
        event_type="apps.workshop.version_restored",
        subject_type="workshop_module",
        subject_id=module_id,
        payload={"project_id": module.project_id, "version_number": version.version_number, "version_id": version.id},
    )
    db.commit()
    db.refresh(module)
    return module


@router.get("/apps/workshop/{module_id}/render", response_model=WorkshopRenderResponse)
def render_workshop_module(
    module_id: str,
    principal: Principal = Depends(require_permission("view")),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """
    Deterministically resolve each widget:
    - object_type widgets: return count + first few ObjectInstance ids
    - saved_object_set widgets: return set display_name + count
    - action_type widgets: return action display_name
    - other widgets: pass through with empty resolved dict
    """
    obj = _get_workshop_module_or_404(db, module_id, principal, "view")

    resolved_widgets: List[Dict[str, Any]] = []
    for raw_widget in obj.widgets or []:
        w = dict(raw_widget)
        resolved: Dict[str, Any] = {}

        ot_id: Optional[str] = w.get("object_type_id")
        sos_id: Optional[str] = w.get("saved_object_set_id")
        at_id: Optional[str] = w.get("action_type_id")

        if ot_id:
            instances = (
                db.query(models.ObjectInstance)
                .filter(models.ObjectInstance.object_type_id == ot_id)
                .limit(_PREVIEW_LIMIT)
                .all()
            )
            total = (
                db.query(models.ObjectInstance)
                .filter(models.ObjectInstance.object_type_id == ot_id)
                .count()
            )
            resolved = {
                "object_type_id": ot_id,
                "total_count": total,
                "preview_ids": [inst.id for inst in instances],
            }
        elif sos_id:
            saved = (
                db.query(models.SavedObjectSet)
                .filter(models.SavedObjectSet.id == sos_id)
                .first()
            )
            if saved:
                count = (
                    db.query(models.ObjectInstance)
                    .filter(models.ObjectInstance.object_type_id == saved.object_type_id)
                    .count()
                )
                resolved = {
                    "saved_object_set_id": sos_id,
                    "display_name": saved.display_name,
                    "object_type_id": saved.object_type_id,
                    "count": count,
                }
            else:
                resolved = {"saved_object_set_id": sos_id, "warning": "not_found"}
        elif at_id:
            action = (
                db.query(models.ActionType)
                .filter(models.ActionType.id == at_id)
                .first()
            )
            resolved = {
                "action_type_id": at_id,
                "display_name": action.display_name if action else None,
                "found": action is not None,
            }

        resolved_widgets.append(
            {
                "type": w.get("type", "unknown"),
                "title": w.get("title", ""),
                "object_type_id": w.get("object_type_id"),
                "saved_object_set_id": w.get("saved_object_set_id"),
                "action_type_id": w.get("action_type_id"),
                "config": w.get("config", {}),
                "resolved": resolved,
            }
        )

    return {"module_id": module_id, "widgets": resolved_widgets}


# ---------------------------------------------------------------------------
# Slate Endpoints
# ---------------------------------------------------------------------------


@router.post("/apps/slate", response_model=SlateAppRead)
def create_slate_app(
    body: SlateAppCreate,
    db: Session = Depends(get_db),
) -> SlateApp:
    app_id = body.id or _gen_id()
    existing = db.query(SlateApp).filter(SlateApp.id == app_id).first()
    if existing:
        raise HTTPException(status_code=400, detail="SlateApp already exists")

    now = _now()
    db_obj = SlateApp(
        id=app_id,
        display_name=body.display_name,
        queries=body.queries or {},
        widgets=body.widgets or {},
        functions=body.functions or {},
        created_at=now,
        updated_at=now,
    )
    db.add(db_obj)
    _append_audit(
        db,
        actor=body.actor or "system",
        event_type="apps.slate.created",
        subject_type="slate_app",
        subject_id=app_id,
        payload={"display_name": body.display_name},
    )
    db.commit()
    db.refresh(db_obj)
    return db_obj


@router.get("/apps/slate", response_model=List[SlateAppRead])
def list_slate_apps(db: Session = Depends(get_db)) -> List[SlateApp]:
    return db.query(SlateApp).order_by(SlateApp.updated_at.desc()).all()


@router.get("/apps/slate/{app_id}", response_model=SlateAppRead)
def get_slate_app(
    app_id: str,
    db: Session = Depends(get_db),
) -> SlateApp:
    return _get_slate_app_or_404(db, app_id)


@router.patch("/apps/slate/{app_id}", response_model=SlateAppRead)
def update_slate_app(
    app_id: str,
    body: SlateAppUpdate,
    db: Session = Depends(get_db),
) -> SlateApp:
    """Edit a Slate app's queries / widgets / functions / display_name in place."""
    obj = _get_slate_app_or_404(db, app_id)
    patch = body.model_dump(exclude_unset=True)
    actor = patch.pop("actor", None) or "system"
    changed: List[str] = []

    for field in ("display_name", "queries", "widgets", "functions"):
        if field in patch:
            setattr(obj, field, patch[field])
            changed.append(field)

    if changed:
        obj.updated_at = _now()
        _append_audit(
            db,
            actor=actor,
            event_type="apps.slate.updated",
            subject_type="slate_app",
            subject_id=app_id,
            payload={"changed": changed},
        )
    db.commit()
    db.refresh(obj)
    return obj


@router.delete("/apps/slate/{app_id}")
def delete_slate_app(
    app_id: str,
    actor: str = "system",
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """Delete a Slate app and all of its published versions."""
    obj = _get_slate_app_or_404(db, app_id)
    version_count = (
        db.query(SlateAppVersion).filter(SlateAppVersion.app_id == app_id).count()
    )
    db.query(SlateAppVersion).filter(SlateAppVersion.app_id == app_id).delete()
    db.delete(obj)
    _append_audit(
        db,
        actor=actor or "system",
        event_type="apps.slate.deleted",
        subject_type="slate_app",
        subject_id=app_id,
        payload={"versions_deleted": version_count},
    )
    db.commit()
    return {"deleted": True, "id": app_id, "versions_deleted": version_count}


@router.post("/apps/slate/{app_id}/publish", response_model=SlateAppVersionRead)
def publish_slate_app(
    app_id: str,
    body: SlatePublishRequest = SlatePublishRequest(),
    db: Session = Depends(get_db),
) -> SlateAppVersion:
    """Publish an immutable snapshot of the current Slate app state."""
    app_obj = _get_slate_app_or_404(db, app_id)
    latest = (
        db.query(SlateAppVersion)
        .filter(SlateAppVersion.app_id == app_id)
        .order_by(SlateAppVersion.version_number.desc())
        .first()
    )
    version = SlateAppVersion(
        id=_gen_id(),
        app_id=app_id,
        version_number=(latest.version_number + 1) if latest else 1,
        snapshot=_slate_snapshot(app_obj),
        note=body.note,
        actor=body.actor or "system",
        created_at=_now(),
    )
    db.add(version)
    _append_audit(
        db,
        actor=body.actor or "system",
        event_type="apps.slate.published",
        subject_type="slate_app",
        subject_id=app_id,
        payload={"version_number": version.version_number, "version_id": version.id},
    )
    db.commit()
    db.refresh(version)
    return version


@router.get("/apps/slate/{app_id}/versions", response_model=List[SlateAppVersionRead])
def list_slate_versions(
    app_id: str,
    db: Session = Depends(get_db),
) -> List[SlateAppVersion]:
    _get_slate_app_or_404(db, app_id)
    return (
        db.query(SlateAppVersion)
        .filter(SlateAppVersion.app_id == app_id)
        .order_by(SlateAppVersion.version_number.desc())
        .all()
    )


@router.post("/apps/slate/{app_id}/versions/{version_id}/restore", response_model=SlateAppRead)
def restore_slate_version(
    app_id: str,
    version_id: str,
    body: SlatePublishRequest = SlatePublishRequest(),
    db: Session = Depends(get_db),
) -> SlateApp:
    """Restore a Slate app to a previously published version (by id or version number)."""
    app_obj = _get_slate_app_or_404(db, app_id)
    version_query = db.query(SlateAppVersion).filter(
        SlateAppVersion.app_id == app_id,
        SlateAppVersion.id == version_id,
    )
    if version_id.isdigit():
        version_query = db.query(SlateAppVersion).filter(
            SlateAppVersion.app_id == app_id,
            SlateAppVersion.version_number == int(version_id),
        )
    version = version_query.first()
    if not version:
        raise HTTPException(status_code=404, detail=f"SlateAppVersion '{version_id}' not found")

    snapshot = version.snapshot or {}
    app_obj.display_name = snapshot.get("display_name", app_obj.display_name)
    app_obj.queries = snapshot.get("queries", {})
    app_obj.widgets = snapshot.get("widgets", {})
    app_obj.functions = snapshot.get("functions", {})
    app_obj.updated_at = _now()
    _append_audit(
        db,
        actor=body.actor or "system",
        event_type="apps.slate.version_restored",
        subject_type="slate_app",
        subject_id=app_id,
        payload={"version_number": version.version_number, "version_id": version.id},
    )
    db.commit()
    db.refresh(app_obj)
    return app_obj


# ---------------------------------------------------------------------------
# Carbon Endpoints
# ---------------------------------------------------------------------------


@router.post("/apps/carbon", response_model=CarbonWorkspaceRead)
def create_carbon_workspace(
    body: CarbonWorkspaceCreate,
    db: Session = Depends(get_db),
) -> CarbonWorkspace:
    ws_id = body.id or _gen_id()
    existing = db.query(CarbonWorkspace).filter(CarbonWorkspace.id == ws_id).first()
    if existing:
        raise HTTPException(status_code=400, detail="CarbonWorkspace already exists")

    now = _now()
    db_obj = CarbonWorkspace(
        id=ws_id,
        display_name=body.display_name,
        module_ids=body.module_ids or [],
        navigation=body.navigation or {},
        created_at=now,
        updated_at=now,
    )
    db.add(db_obj)
    _append_audit(
        db,
        actor=body.actor or "system",
        event_type="apps.carbon.created",
        subject_type="carbon_workspace",
        subject_id=ws_id,
        payload={"display_name": body.display_name, "module_ids": body.module_ids or []},
    )
    db.commit()
    db.refresh(db_obj)
    return db_obj


@router.get("/apps/carbon", response_model=List[CarbonWorkspaceRead])
def list_carbon_workspaces(db: Session = Depends(get_db)) -> List[CarbonWorkspace]:
    return db.query(CarbonWorkspace).order_by(CarbonWorkspace.updated_at.desc()).all()


@router.get("/apps/carbon/{workspace_id}", response_model=CarbonWorkspaceDetail)
def get_carbon_workspace(
    workspace_id: str,
    principal: Principal = Depends(require_permission("view")),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """Return workspace with resolved display names for each referenced module."""
    obj = db.query(CarbonWorkspace).filter(CarbonWorkspace.id == workspace_id).first()
    if not obj:
        raise HTTPException(
            status_code=404, detail=f"CarbonWorkspace '{workspace_id}' not found"
        )

    resolved_modules: List[Dict[str, Any]] = []
    for mid in obj.module_ids or []:
        mod = db.query(WorkshopModule).filter(WorkshopModule.id == mid).first()
        if mod:
            tenancy.assert_project_permission(db, principal, mod.project_id, "view")
            resolved_modules.append(
                {"id": mod.id, "display_name": mod.display_name, "widget_count": len(mod.widgets or [])}
            )
        else:
            resolved_modules.append({"id": mid, "display_name": None, "warning": "not_found"})

    return {
        "id": obj.id,
        "display_name": obj.display_name,
        "module_ids": obj.module_ids,
        "navigation": obj.navigation,
        "created_at": obj.created_at,
        "updated_at": obj.updated_at,
        "resolved_modules": resolved_modules,
    }

"""Project boundaries for the core ontology and dataset data plane."""
from __future__ import annotations

from typing import Optional, Type, TypeVar

from fastapi import HTTPException
from sqlalchemy.orm import Session

from . import models, production_auth, tenancy
from .production_auth import Principal

T = TypeVar("T")


def effective_principal(principal: Principal) -> Principal:
    """Keep direct Python callers compatible while HTTP always resolves auth dependencies."""
    return principal if isinstance(principal, Principal) else production_auth._local_principal()


def principal_id(principal: Principal) -> str:
    return effective_principal(principal).id


def assert_project(db: Session, principal: Principal, project_id: str, permission: str) -> None:
    tenancy.assert_project_permission(db, effective_principal(principal), project_id, permission)


def accessible_query(db: Session, principal: Principal, model: Type[T], permission: str = "view"):
    query = db.query(model)
    projects = tenancy.accessible_project_ids(db, effective_principal(principal), permission)
    if projects is not None:
        query = query.filter(model.project_id.in_(projects)) if projects else query.filter(model.id == "__none__")
    return query


def owned_row(db: Session, principal: Principal, model: Type[T], resource_id: str,
              permission: str = "view", label: Optional[str] = None) -> T:
    row = db.get(model, resource_id)
    if not row:
        raise HTTPException(status_code=404, detail=f"{label or model.__name__} '{resource_id}' not found")
    assert_project(db, principal, row.project_id, permission)
    return row


def object_type_project(object_type) -> str:
    """The project owning an object type, from the two places this schema records it.

    `ObjectType.project_id` is a column; `properties["__manager"]["project_id"]` is a blob
    written by the ontology generator and read as the owning project by seven modules,
    each with its own copy of the same expression. Nothing keeps the two in agreement, so
    a row can belong to different projects depending on which module reaches it -- that is
    T11 of GOAL_TENANCY_2026-08-27, and it is why threading a project into the runtime's
    object reads made a Workshop console render nothing.

    The column wins where it says anything, because it is what authorization already uses:
    `owned_row` checks it, and `POST /objects` refuses with a 409 when it disagrees with
    the object being created. Where the column was never set -- it defaults to "default" --
    a `__manager` naming a real project is the only record there is, and dropping it would
    silently move those types into the default project. So the fallback is deliberate and
    narrow, and it is here rather than in seven modules so that tightening it later is one
    edit and one decision.
    """
    column = str(getattr(object_type, "project_id", "") or "")
    manager = (getattr(object_type, "properties", None) or {}).get("__manager")
    manager = manager if isinstance(manager, dict) else {}
    named = str(manager.get("project_id") or "")
    if column and column != "default":
        return column
    return named or column or "default"


def object_type_for(db: Session, principal: Principal, object_type_id: str, permission: str = "view") -> models.ObjectType:
    return owned_row(db, principal, models.ObjectType, object_type_id, permission, "ObjectType")


def object_for(db: Session, principal: Principal, object_id: str, permission: str = "view") -> models.ObjectInstance:
    row = owned_row(db, principal, models.ObjectInstance, object_id, permission, "ObjectInstance")
    object_type = db.get(models.ObjectType, row.object_type_id)
    if not object_type or object_type.project_id != row.project_id:
        raise HTTPException(status_code=409, detail="Object instance has an invalid cross-project type reference")
    return row


def link_type_for(db: Session, principal: Principal, link_type_id: str, permission: str = "view") -> models.LinkType:
    row = owned_row(db, principal, models.LinkType, link_type_id, permission, "LinkType")
    source = db.get(models.ObjectType, row.source_object_type_id)
    target = db.get(models.ObjectType, row.target_object_type_id)
    if not source or not target or source.project_id != row.project_id or target.project_id != row.project_id:
        raise HTTPException(status_code=409, detail="Link type has an invalid cross-project object-type reference")
    return row


def link_for(db: Session, principal: Principal, link_id: str, permission: str = "view") -> models.LinkInstance:
    row = owned_row(db, principal, models.LinkInstance, link_id, permission, "LinkInstance")
    link_type = db.get(models.LinkType, row.link_type_id)
    source = db.get(models.ObjectInstance, row.source_object_id)
    target = db.get(models.ObjectInstance, row.target_object_id)
    if any(item is None or item.project_id != row.project_id for item in (link_type, source, target)):
        raise HTTPException(status_code=409, detail="Link instance has an invalid cross-project reference")
    return row


def asset_for(db: Session, principal: Principal, asset_id: str, permission: str = "view") -> models.DataAsset:
    return owned_row(db, principal, models.DataAsset, asset_id, permission, "DataAsset")


def pipeline_for(db: Session, principal: Principal, pipeline_id: str, permission: str = "view") -> models.PipelineDefinition:
    row = owned_row(db, principal, models.PipelineDefinition, pipeline_id, permission, "PipelineDefinition")
    input_asset = db.get(models.DataAsset, row.input_asset_id)
    output_asset = db.get(models.DataAsset, row.output_asset_id) if row.output_asset_id else None
    if not input_asset or input_asset.project_id != row.project_id or (output_asset and output_asset.project_id != row.project_id):
        raise HTTPException(status_code=409, detail="Pipeline has an invalid cross-project dataset reference")
    return row

"""Organization and project authorization boundaries for production resources."""
from __future__ import annotations

import time
import uuid
from typing import Dict, List, Optional, Set

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import Integer, JSON, String, UniqueConstraint
from sqlalchemy.orm import Mapped, Session, mapped_column

from .database import Base, get_db
from .production_auth import Principal, require_permission

router = APIRouter(tags=["tenancy"])

PROJECT_ROLE_PERMISSIONS: Dict[str, Set[str]] = {
    "viewer": {"view"},
    "editor": {"view", "edit"},
    "operator": {"view", "edit", "execute", "export"},
    "publisher": {"view", "edit", "publish", "restore", "export"},
    "approver": {"view", "approve"},
    "administrator": {"view", "edit", "execute", "approve", "publish", "deploy", "export", "restore", "administer"},
}


def _now() -> int:
    return int(time.time())


class PlatformOrganization(Base):
    __tablename__ = "platform_organizations"

    id: Mapped[str] = mapped_column(String, primary_key=True, index=True)
    display_name: Mapped[str] = mapped_column(String)
    status: Mapped[str] = mapped_column(String, default="ACTIVE", index=True)
    created_at: Mapped[int] = mapped_column(Integer)
    updated_at: Mapped[int] = mapped_column(Integer)


class PlatformProject(Base):
    __tablename__ = "platform_projects"

    id: Mapped[str] = mapped_column(String, primary_key=True, index=True)
    organization_id: Mapped[str] = mapped_column(String, index=True)
    display_name: Mapped[str] = mapped_column(String)
    description: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    status: Mapped[str] = mapped_column(String, default="ACTIVE", index=True)
    created_at: Mapped[int] = mapped_column(Integer)
    updated_at: Mapped[int] = mapped_column(Integer)


class ProjectMembership(Base):
    __tablename__ = "platform_project_memberships"
    __table_args__ = (UniqueConstraint("project_id", "principal_id", name="uq_project_membership_principal"),)

    id: Mapped[str] = mapped_column(String, primary_key=True, index=True)
    project_id: Mapped[str] = mapped_column(String, index=True)
    principal_id: Mapped[str] = mapped_column(String, index=True)
    role: Mapped[str] = mapped_column(String)
    permissions: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[int] = mapped_column(Integer)
    updated_at: Mapped[int] = mapped_column(Integer)


class OrganizationCreate(BaseModel):
    id: str = Field(min_length=2, max_length=120, pattern=r"^[A-Za-z][A-Za-z0-9_.-]*$")
    display_name: str = Field(min_length=1, max_length=200)


class ProjectCreate(BaseModel):
    id: str = Field(min_length=2, max_length=120, pattern=r"^[A-Za-z][A-Za-z0-9_.-]*$")
    organization_id: str
    display_name: str = Field(min_length=1, max_length=200)
    description: Optional[str] = None


class MembershipUpsert(BaseModel):
    principal_id: str = Field(min_length=1, max_length=240)
    role: str = "viewer"
    permissions: List[str] = Field(default_factory=list)


class TenancyBootstrapRequest(BaseModel):
    organization_id: str = Field(default="local", pattern=r"^[A-Za-z][A-Za-z0-9_.-]*$")
    organization_name: str = "Local Organization"
    project_id: str = Field(default="default", pattern=r"^[A-Za-z][A-Za-z0-9_.-]*$")
    project_name: str = "Default Project"


def project_permissions(db: Session, principal: Principal, project_id: str) -> Set[str]:
    if "*" in principal.project_ids:
        return set(principal.permissions) | {"*"}
    if principal.organization_id:
        project = db.get(PlatformProject, project_id)
        if project and project.organization_id != principal.organization_id:
            return set()
    result: Set[str] = set()
    if project_id in principal.project_ids:
        result.update(principal.permissions)
    membership = db.query(ProjectMembership).filter(
        ProjectMembership.project_id == project_id,
        ProjectMembership.principal_id == principal.id,
    ).first()
    if membership:
        result.update(PROJECT_ROLE_PERMISSIONS.get(membership.role.lower(), set()))
        result.update(str(value) for value in (membership.permissions or []))
    return result


def assert_project_permission(db: Session, principal: Principal, project_id: str, permission: str) -> None:
    permissions = project_permissions(db, principal, project_id)
    if "*" not in permissions and permission not in permissions:
        raise HTTPException(status_code=403, detail={
            "message": f"Project permission '{permission}' is required",
            "project_id": project_id,
        })


def accessible_project_ids(db: Session, principal: Principal, permission: str = "view") -> Optional[Set[str]]:
    if "*" in principal.project_ids:
        return None
    candidates = set(principal.project_ids)
    candidates.update(row.project_id for row in db.query(ProjectMembership).filter(ProjectMembership.principal_id == principal.id).all())
    return {project_id for project_id in candidates if permission in project_permissions(db, principal, project_id) or "*" in project_permissions(db, principal, project_id)}


def _organization_dict(row: PlatformOrganization) -> dict:
    return {"id": row.id, "display_name": row.display_name, "status": row.status, "created_at": row.created_at, "updated_at": row.updated_at}


def _project_dict(db: Session, row: PlatformProject, principal: Principal) -> dict:
    permissions = sorted(project_permissions(db, principal, row.id))
    return {
        "id": row.id,
        "organization_id": row.organization_id,
        "display_name": row.display_name,
        "description": row.description,
        "status": row.status,
        "permissions": permissions,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


@router.post("/tenancy/organizations", status_code=201)
def create_organization(body: OrganizationCreate, principal: Principal = Depends(require_permission("administer")), db: Session = Depends(get_db)):
    if db.get(PlatformOrganization, body.id):
        raise HTTPException(status_code=409, detail="Organization already exists")
    now = _now()
    row = PlatformOrganization(id=body.id, display_name=body.display_name, status="ACTIVE", created_at=now, updated_at=now)
    db.add(row)
    db.commit()
    return _organization_dict(row)


@router.post("/tenancy/bootstrap")
def bootstrap_tenancy(body: TenancyBootstrapRequest, principal: Principal = Depends(require_permission("administer")), db: Session = Depends(get_db)):
    organization_id = principal.organization_id or body.organization_id
    organization = db.get(PlatformOrganization, organization_id)
    now = _now()
    if not organization:
        organization = PlatformOrganization(id=organization_id, display_name=body.organization_name, status="ACTIVE", created_at=now, updated_at=now)
        db.add(organization)
    project = db.get(PlatformProject, body.project_id)
    if project and project.organization_id != organization_id:
        raise HTTPException(status_code=409, detail="Project ID is already owned by another organization")
    if not project:
        project = PlatformProject(id=body.project_id, organization_id=organization_id, display_name=body.project_name, description="Bootstrapped project", status="ACTIVE", created_at=now, updated_at=now)
        db.add(project)
    membership = db.query(ProjectMembership).filter(ProjectMembership.project_id == project.id, ProjectMembership.principal_id == principal.id).first()
    if not membership:
        db.add(ProjectMembership(id=f"membership_{uuid.uuid4().hex}", project_id=project.id, principal_id=principal.id, role="administrator", permissions=[], created_at=now, updated_at=now))
    db.commit()
    return {"organization": _organization_dict(organization), "project": _project_dict(db, project, principal), "status": "READY"}


@router.post("/tenancy/projects", status_code=201)
def create_project(body: ProjectCreate, principal: Principal = Depends(require_permission("administer")), db: Session = Depends(get_db)):
    if db.get(PlatformProject, body.id):
        raise HTTPException(status_code=409, detail="Project already exists")
    organization = db.get(PlatformOrganization, body.organization_id)
    if not organization:
        raise HTTPException(status_code=404, detail="Organization not found")
    if principal.organization_id and principal.organization_id != body.organization_id:
        raise HTTPException(status_code=403, detail="Cannot create a project in another organization")
    now = _now()
    row = PlatformProject(id=body.id, organization_id=body.organization_id, display_name=body.display_name, description=body.description, status="ACTIVE", created_at=now, updated_at=now)
    db.add(row)
    db.add(ProjectMembership(
        id=f"membership_{uuid.uuid4().hex}", project_id=row.id, principal_id=principal.id,
        role="administrator", permissions=[], created_at=now, updated_at=now,
    ))
    db.commit()
    return _project_dict(db, row, principal)


@router.get("/tenancy/projects")
def list_projects(principal: Principal = Depends(require_permission("view")), db: Session = Depends(get_db)):
    allowed = accessible_project_ids(db, principal)
    query = db.query(PlatformProject).filter(PlatformProject.status == "ACTIVE")
    if allowed is not None:
        query = query.filter(PlatformProject.id.in_(allowed)) if allowed else query.filter(PlatformProject.id == "__none__")
    return [_project_dict(db, row, principal) for row in query.order_by(PlatformProject.display_name).all()]


@router.put("/tenancy/projects/{project_id}/members/{principal_id}")
def upsert_project_member(
    project_id: str,
    principal_id: str,
    body: MembershipUpsert,
    principal: Principal = Depends(require_permission("administer")),
    db: Session = Depends(get_db),
):
    assert_project_permission(db, principal, project_id, "administer")
    if body.principal_id != principal_id:
        raise HTTPException(status_code=422, detail="Path and body principal IDs must match")
    role = body.role.lower()
    if role not in PROJECT_ROLE_PERMISSIONS:
        raise HTTPException(status_code=422, detail=f"Unsupported project role '{body.role}'")
    row = db.query(ProjectMembership).filter(ProjectMembership.project_id == project_id, ProjectMembership.principal_id == principal_id).first()
    now = _now()
    if row:
        row.role = role
        row.permissions = sorted(set(body.permissions))
        row.updated_at = now
    else:
        row = ProjectMembership(id=f"membership_{uuid.uuid4().hex}", project_id=project_id, principal_id=principal_id, role=role, permissions=sorted(set(body.permissions)), created_at=now, updated_at=now)
        db.add(row)
    db.commit()
    return {"id": row.id, "project_id": row.project_id, "principal_id": row.principal_id, "role": row.role, "permissions": sorted(project_permissions(db, Principal(principal_id, principal_id, None, [], [], project_ids=[]), project_id))}


@router.get("/tenancy/projects/{project_id}/members")
def list_project_members(project_id: str, principal: Principal = Depends(require_permission("view")), db: Session = Depends(get_db)):
    assert_project_permission(db, principal, project_id, "view")
    rows = db.query(ProjectMembership).filter(ProjectMembership.project_id == project_id).order_by(ProjectMembership.principal_id).all()
    return [{"id": row.id, "principal_id": row.principal_id, "role": row.role, "permissions": sorted(set(PROJECT_ROLE_PERMISSIONS.get(row.role, set())) | set(row.permissions or []))} for row in rows]

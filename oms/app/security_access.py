"""
Foundry PROJECTS / ROLES / PERMISSIONS access model.

Tables: projects, roles, role_grants
"""
import uuid
import time
from typing import Optional, List, Any, Dict

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import String, Integer, JSON, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, Session, relationship
from pydantic import BaseModel, ConfigDict, Field

from .database import Base, get_db
from . import models, models_action


# ---------------------------------------------------------------------------
# SQLAlchemy ORM models
# ---------------------------------------------------------------------------

class Project(Base):
    """A Foundry project that groups resources and governs access."""

    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    display_name: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    organization: Mapped[str] = mapped_column(String, default="default")
    created_at: Mapped[int] = mapped_column(Integer)
    updated_at: Mapped[int] = mapped_column(Integer)

    grants: Mapped[List["RoleGrant"]] = relationship(
        "RoleGrant", back_populates="project", cascade="all, delete-orphan"
    )


class Role(Base):
    """A named set of permissions that can be granted to principals on a project."""

    __tablename__ = "roles"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    display_name: Mapped[str] = mapped_column(String, nullable=False)
    permissions: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[int] = mapped_column(Integer)


class RoleGrant(Base):
    """Associates a principal (user or group id) with a role on a specific project."""

    __tablename__ = "role_grants"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    project_id: Mapped[str] = mapped_column(String, ForeignKey("projects.id"), index=True, nullable=False)
    principal: Mapped[str] = mapped_column(String, nullable=False, index=True)
    role_id: Mapped[str] = mapped_column(String, ForeignKey("roles.id"), nullable=False, index=True)
    created_at: Mapped[int] = mapped_column(Integer)

    project: Mapped["Project"] = relationship("Project", back_populates="grants")
    role: Mapped["Role"] = relationship("Role")


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------

class ProjectCreate(BaseModel):
    id: Optional[str] = None
    display_name: str
    description: Optional[str] = None
    organization: str = "default"


class ProjectRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    display_name: str
    description: Optional[str]
    organization: str
    created_at: int
    updated_at: int


class RoleCreate(BaseModel):
    id: Optional[str] = None
    display_name: str
    permissions: List[str] = Field(default_factory=list)


class RoleRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    display_name: str
    permissions: List[str]
    created_at: int


class GrantCreate(BaseModel):
    principal: str
    role_id: str


class RoleGrantRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    project_id: str
    principal: str
    role_id: str
    created_at: int


class AccessCheckRequest(BaseModel):
    project_id: str
    principal: str
    permission: str


class AccessCheckResponse(BaseModel):
    allowed: bool
    project_id: str
    principal: str
    permission: str
    matched_roles: List[str]


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

router = APIRouter(tags=["security_access"])


def _now() -> int:
    return int(time.time())


def _not_found(resource: str, resource_id: str):
    raise HTTPException(status_code=404, detail=f"{resource} '{resource_id}' not found")


# --- Projects ---

@router.post("/projects", response_model=ProjectRead, status_code=201)
def create_project(body: ProjectCreate, db: Session = Depends(get_db)):
    project_id = body.id or uuid.uuid4().hex
    existing = db.query(Project).filter(Project.id == project_id).first()
    if existing:
        raise HTTPException(status_code=400, detail=f"Project '{project_id}' already exists")

    now = _now()
    project = Project(
        id=project_id,
        display_name=body.display_name,
        description=body.description,
        organization=body.organization,
        created_at=now,
        updated_at=now,
    )
    db.add(project)
    db.commit()
    db.refresh(project)
    return project


@router.get("/projects", response_model=List[ProjectRead])
def list_projects(db: Session = Depends(get_db)):
    return db.query(Project).order_by(Project.created_at.desc()).all()


@router.get("/projects/{project_id}", response_model=ProjectRead)
def get_project(project_id: str, db: Session = Depends(get_db)):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        _not_found("Project", project_id)
    return project


# --- Roles ---

@router.post("/roles", response_model=RoleRead, status_code=201)
def create_role(body: RoleCreate, db: Session = Depends(get_db)):
    role_id = body.id or uuid.uuid4().hex
    existing = db.query(Role).filter(Role.id == role_id).first()
    if existing:
        raise HTTPException(status_code=400, detail=f"Role '{role_id}' already exists")

    role = Role(
        id=role_id,
        display_name=body.display_name,
        permissions=body.permissions,
        created_at=_now(),
    )
    db.add(role)
    db.commit()
    db.refresh(role)
    return role


@router.get("/roles", response_model=List[RoleRead])
def list_roles(db: Session = Depends(get_db)):
    return db.query(Role).order_by(Role.created_at.desc()).all()


# --- Role Grants ---

@router.post("/projects/{project_id}/grants", response_model=RoleGrantRead, status_code=201)
def create_grant(
    project_id: str,
    body: GrantCreate,
    actor: str = "system",
    db: Session = Depends(get_db),
):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        _not_found("Project", project_id)

    role = db.query(Role).filter(Role.id == body.role_id).first()
    if not role:
        _not_found("Role", body.role_id)

    # Prevent duplicate grants for the same principal + role on the same project
    existing = (
        db.query(RoleGrant)
        .filter(
            RoleGrant.project_id == project_id,
            RoleGrant.principal == body.principal,
            RoleGrant.role_id == body.role_id,
        )
        .first()
    )
    if existing:
        raise HTTPException(
            status_code=400,
            detail=f"Grant already exists for principal '{body.principal}' with role '{body.role_id}' on project '{project_id}'",
        )

    grant = RoleGrant(
        id=uuid.uuid4().hex,
        project_id=project_id,
        principal=body.principal,
        role_id=body.role_id,
        created_at=_now(),
    )
    db.add(grant)

    db.add(
        models_action.AuditLog(
            id=uuid.uuid4().hex,
            actor=actor,
            event_type="access.grant.created",
            subject_type="project",
            subject_id=project_id,
            payload={
                "principal": body.principal,
                "role_id": body.role_id,
                "permissions": role.permissions,
            },
        )
    )
    db.commit()
    db.refresh(grant)
    return grant


@router.get("/projects/{project_id}/grants", response_model=List[RoleGrantRead])
def list_grants(project_id: str, db: Session = Depends(get_db)):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        _not_found("Project", project_id)
    return db.query(RoleGrant).filter(RoleGrant.project_id == project_id).all()


# --- Access Check ---

@router.post("/access/check", response_model=AccessCheckResponse)
def check_access(body: AccessCheckRequest, db: Session = Depends(get_db)):
    """
    Returns {allowed: bool} by checking whether the principal holds any role on
    the project whose permissions list contains the requested permission.

    Inheritance rule: a grant on a project applies to all of its resources.
    """
    project = db.query(Project).filter(Project.id == body.project_id).first()
    if not project:
        _not_found("Project", body.project_id)

    grants = (
        db.query(RoleGrant)
        .filter(
            RoleGrant.project_id == body.project_id,
            RoleGrant.principal == body.principal,
        )
        .all()
    )

    matched_roles: List[str] = []
    for grant in grants:
        role = db.query(Role).filter(Role.id == grant.role_id).first()
        if role and body.permission in (role.permissions or []):
            matched_roles.append(role.id)

    return AccessCheckResponse(
        allowed=len(matched_roles) > 0,
        project_id=body.project_id,
        principal=body.principal,
        permission=body.permission,
        matched_roles=matched_roles,
    )

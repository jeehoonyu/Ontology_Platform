"""
Management & Enablement — Control Panel directory: enrollments, organizations,
spaces, users, groups, memberships, and scope-level role grants with real
access resolution (deep-fidelity pass 12). Based on
/docs/foundry/administration/overview and /platform-security-management/*:
an enrollment contains organizations; access is controlled at user/group level;
roles are granted at a scope and map to capabilities; membership can expire.
Additive; deterministic; local.
"""
import time
import uuid
from typing import Optional, List, Any, Dict, Set, Tuple

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import String, Integer, Boolean, JSON
from sqlalchemy.orm import Mapped, mapped_column, Session
from pydantic import BaseModel, ConfigDict, Field

from .database import Base, get_db
from . import models_action

router = APIRouter(tags=["admin_directory"])


def _now() -> int:
    return int(time.time())


# Roles -> capabilities (documented: a role grants a set of workflows/capabilities)
ROLE_CAPABILITIES: Dict[str, List[str]] = {
    "viewer": ["view"],
    "editor": ["view", "edit"],
    "owner": ["view", "edit", "manage"],
    "administrator": ["view", "edit", "manage", "administer"],
}


# ---------------------------------------------------------------------------
# ORM models
# ---------------------------------------------------------------------------
class Enrollment(Base):
    __tablename__ = "admin_enrollments"
    id: Mapped[str] = mapped_column(String, primary_key=True, index=True)
    display_name: Mapped[str] = mapped_column(String)
    created_at: Mapped[int] = mapped_column(Integer)


class Organization(Base):
    __tablename__ = "admin_organizations"
    id: Mapped[str] = mapped_column(String, primary_key=True, index=True)
    enrollment_id: Mapped[str] = mapped_column(String, index=True)
    display_name: Mapped[str] = mapped_column(String)
    created_at: Mapped[int] = mapped_column(Integer)


class Space(Base):
    __tablename__ = "admin_spaces"
    id: Mapped[str] = mapped_column(String, primary_key=True, index=True)
    organization_id: Mapped[str] = mapped_column(String, index=True)
    display_name: Mapped[str] = mapped_column(String)
    created_at: Mapped[int] = mapped_column(Integer)


class AdminUser(Base):
    __tablename__ = "admin_users"
    id: Mapped[str] = mapped_column(String, primary_key=True, index=True)
    username: Mapped[str] = mapped_column(String, index=True)
    display_name: Mapped[str] = mapped_column(String)
    email: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    status: Mapped[str] = mapped_column(String, default="active")  # active | inactive
    organization_ids: Mapped[list] = mapped_column(JSON, default=list)
    marking_ids: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[int] = mapped_column(Integer)
    updated_at: Mapped[int] = mapped_column(Integer)


class AdminProject(Base):
    """A project lives inside a space. Used so project-scoped role grants can
    inherit up the hierarchy (project -> space -> organization -> enrollment)."""
    __tablename__ = "admin_projects"
    id: Mapped[str] = mapped_column(String, primary_key=True, index=True)
    space_id: Mapped[str] = mapped_column(String, index=True)
    display_name: Mapped[str] = mapped_column(String)
    created_at: Mapped[int] = mapped_column(Integer)


class AdminGroup(Base):
    __tablename__ = "admin_groups"
    id: Mapped[str] = mapped_column(String, primary_key=True, index=True)
    organization_id: Mapped[Optional[str]] = mapped_column(String, nullable=True, index=True)
    display_name: Mapped[str] = mapped_column(String)
    created_at: Mapped[int] = mapped_column(Integer)


class GroupMembership(Base):
    __tablename__ = "admin_group_memberships"
    id: Mapped[str] = mapped_column(String, primary_key=True, index=True)
    group_id: Mapped[str] = mapped_column(String, index=True)
    user_id: Mapped[str] = mapped_column(String, index=True)
    expiration: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    manage_permission: Mapped[bool] = mapped_column(Boolean, default=False)
    manage_membership: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[int] = mapped_column(Integer)


class AdminRoleGrant(Base):
    __tablename__ = "admin_role_grants"
    id: Mapped[str] = mapped_column(String, primary_key=True, index=True)
    scope_type: Mapped[str] = mapped_column(String, index=True)   # enrollment|organization|space|project
    scope_id: Mapped[str] = mapped_column(String, index=True)
    principal_type: Mapped[str] = mapped_column(String)           # user|group
    principal_id: Mapped[str] = mapped_column(String, index=True)
    role: Mapped[str] = mapped_column(String)
    created_at: Mapped[int] = mapped_column(Integer)


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------
class EnrollmentCreate(BaseModel):
    id: Optional[str] = None
    display_name: str


class OrganizationCreate(BaseModel):
    id: Optional[str] = None
    enrollment_id: str
    display_name: str


class SpaceCreate(BaseModel):
    id: Optional[str] = None
    organization_id: str
    display_name: str


class ProjectCreate(BaseModel):
    id: Optional[str] = None
    space_id: str
    display_name: str


class UserCreate(BaseModel):
    id: Optional[str] = None
    username: str
    display_name: str
    email: Optional[str] = None
    organization_ids: List[str] = Field(default_factory=list)
    marking_ids: List[str] = Field(default_factory=list)


class StatusUpdate(BaseModel):
    status: str  # active | inactive


class GroupCreate(BaseModel):
    id: Optional[str] = None
    organization_id: Optional[str] = None
    display_name: str


class MembershipCreate(BaseModel):
    user_id: str
    expiration: Optional[int] = None
    manage_permission: bool = False
    manage_membership: bool = False
    # OPT-IN enforcement: when provided, the actor must already hold
    # 'manage_membership' on this group (or be an administrator at an enclosing
    # scope) to add members. When omitted, behavior is unchanged (permissive).
    actor: Optional[str] = None


class AdminRoleGrantCreate(BaseModel):
    scope_type: str
    scope_id: str
    principal_type: str   # user | group
    principal_id: str
    role: str


class AccessCheckRequest(BaseModel):
    user_id: str
    scope_type: str
    scope_id: str
    capability: str       # view | edit | manage | administer


# ---------------------------------------------------------------------------
# CRUD endpoints
# ---------------------------------------------------------------------------
def _create(db, model, body, **extra):
    rid = (body.id if getattr(body, "id", None) else None) or uuid.uuid4().hex
    now = _now()
    payload = body.model_dump(exclude={"id"}) if hasattr(body, "model_dump") else {}
    payload.update(extra)
    obj = model(id=rid, created_at=now, **payload)
    db.add(obj)
    return obj, rid, now


@router.post("/admin/enrollments", status_code=201)
def create_enrollment(body: EnrollmentCreate, db: Session = Depends(get_db)):
    obj, rid, _ = _create(db, Enrollment, body)
    db.commit()
    return {"id": rid, "display_name": body.display_name}


@router.get("/admin/enrollments")
def list_enrollments(db: Session = Depends(get_db)):
    return [{"id": e.id, "display_name": e.display_name} for e in db.query(Enrollment).all()]


@router.post("/admin/organizations", status_code=201)
def create_organization(body: OrganizationCreate, db: Session = Depends(get_db)):
    if not db.get(Enrollment, body.enrollment_id):
        raise HTTPException(status_code=404, detail="enrollment not found")
    obj, rid, _ = _create(db, Organization, body)
    db.commit()
    return {"id": rid, "enrollment_id": body.enrollment_id, "display_name": body.display_name}


@router.get("/admin/organizations")
def list_organizations(db: Session = Depends(get_db)):
    return [{"id": o.id, "enrollment_id": o.enrollment_id, "display_name": o.display_name} for o in db.query(Organization).all()]


@router.post("/admin/spaces", status_code=201)
def create_space(body: SpaceCreate, db: Session = Depends(get_db)):
    if not db.get(Organization, body.organization_id):
        raise HTTPException(status_code=404, detail="organization not found")
    obj, rid, _ = _create(db, Space, body)
    db.commit()
    return {"id": rid, "organization_id": body.organization_id, "display_name": body.display_name}


@router.get("/admin/spaces")
def list_spaces(organization_id: Optional[str] = None, db: Session = Depends(get_db)):
    q = db.query(Space)
    if organization_id:
        q = q.filter(Space.organization_id == organization_id)
    return [{"id": s.id, "organization_id": s.organization_id, "display_name": s.display_name} for s in q.all()]


@router.post("/admin/projects", status_code=201)
def create_admin_project(body: ProjectCreate, db: Session = Depends(get_db)):
    if not db.get(Space, body.space_id):
        raise HTTPException(status_code=404, detail="space not found")
    obj, rid, _ = _create(db, AdminProject, body)
    db.commit()
    return {"id": rid, "space_id": body.space_id, "display_name": body.display_name}


@router.get("/admin/projects")
def list_admin_projects(space_id: Optional[str] = None, db: Session = Depends(get_db)):
    q = db.query(AdminProject)
    if space_id:
        q = q.filter(AdminProject.space_id == space_id)
    return [{"id": p.id, "space_id": p.space_id, "display_name": p.display_name} for p in q.all()]


@router.post("/admin/users", status_code=201)
def create_user(body: UserCreate, db: Session = Depends(get_db)):
    obj, rid, now = _create(db, AdminUser, body, status="active", updated_at=_now())
    db.add(models_action.AuditLog(id=uuid.uuid4().hex, actor="admin", event_type="admin.user.created",
                                  subject_type="user", subject_id=rid, payload={"username": body.username}))
    db.commit()
    return {"id": rid, "username": body.username, "status": "active",
            "organization_ids": body.organization_ids, "marking_ids": body.marking_ids}


@router.get("/admin/users")
def list_users(db: Session = Depends(get_db)):
    return [{"id": u.id, "username": u.username, "status": u.status,
             "organization_ids": u.organization_ids, "marking_ids": u.marking_ids} for u in db.query(AdminUser).all()]


@router.post("/admin/users/{user_id}/status")
def set_user_status(user_id: str, body: StatusUpdate, db: Session = Depends(get_db)):
    u = db.get(AdminUser, user_id)
    if not u:
        raise HTTPException(status_code=404, detail="user not found")
    u.status = body.status
    u.updated_at = _now()
    db.add(models_action.AuditLog(id=uuid.uuid4().hex, actor="admin", event_type="admin.user.status",
                                  subject_type="user", subject_id=user_id, payload={"status": body.status}))
    db.commit()
    # tokens for inactive users are treated as invalid (enforced at token validation)
    return {"id": user_id, "status": u.status,
            "note": "tokens are invalid while the account is inactive"}


@router.post("/admin/groups", status_code=201)
def create_group(body: GroupCreate, db: Session = Depends(get_db)):
    obj, rid, _ = _create(db, AdminGroup, body)
    db.commit()
    return {"id": rid, "organization_id": body.organization_id, "display_name": body.display_name}


@router.get("/admin/groups")
def list_groups(organization_id: Optional[str] = None, db: Session = Depends(get_db)):
    q = db.query(AdminGroup)
    if organization_id:
        q = q.filter(AdminGroup.organization_id == organization_id)
    return [{"id": g.id, "organization_id": g.organization_id, "display_name": g.display_name} for g in q.all()]


def _can_manage_membership(db: Session, group_id: str, actor: str) -> bool:
    """An actor may manage membership of a group if they (a) hold a membership on
    that group flagged manage_membership, or (b) have an 'administer' capability
    granted at the group's organization (or any enclosing scope) hierarchy."""
    now = _now()
    for m in db.query(GroupMembership).filter(
        GroupMembership.group_id == group_id, GroupMembership.user_id == actor
    ).all():
        if m.manage_membership and (m.expiration is None or m.expiration >= now):
            return True
    # Fall back to administrator capability at the group's org scope hierarchy.
    grp = db.get(AdminGroup, group_id)
    if grp and grp.organization_id:
        actor_groups = [
            gm.group_id for gm in db.query(GroupMembership).filter(GroupMembership.user_id == actor).all()
            if gm.expiration is None or gm.expiration >= now
        ]
        for st, sid in _ancestors(db, "organization", grp.organization_id):
            for g in db.query(AdminRoleGrant).filter(
                AdminRoleGrant.scope_type == st, AdminRoleGrant.scope_id == sid
            ).all():
                if (g.principal_type == "user" and g.principal_id == actor) or \
                   (g.principal_type == "group" and g.principal_id in actor_groups):
                    if "administer" in ROLE_CAPABILITIES.get(g.role, []):
                        return True
    return False


@router.post("/admin/groups/{group_id}/members", status_code=201)
def add_member(group_id: str, body: MembershipCreate, db: Session = Depends(get_db)):
    if not db.get(AdminGroup, group_id):
        raise HTTPException(status_code=404, detail="group not found")
    if not db.get(AdminUser, body.user_id):
        raise HTTPException(status_code=404, detail="user not found")
    # OPT-IN enforcement: only when an actor is supplied. No actor -> unchanged.
    if body.actor and not _can_manage_membership(db, group_id, body.actor):
        raise HTTPException(status_code=403, detail="actor lacks manage_membership on this group")
    m = GroupMembership(id=uuid.uuid4().hex, group_id=group_id, user_id=body.user_id,
                        expiration=body.expiration, manage_permission=body.manage_permission,
                        manage_membership=body.manage_membership, created_at=_now())
    db.add(m)
    db.commit()
    return {"id": m.id, "group_id": group_id, "user_id": body.user_id, "expiration": body.expiration}


@router.get("/admin/groups/{group_id}/members")
def list_members(group_id: str, db: Session = Depends(get_db)):
    now = _now()
    out = []
    for m in db.query(GroupMembership).filter(GroupMembership.group_id == group_id).all():
        out.append({"user_id": m.user_id, "expiration": m.expiration,
                    "expired": m.expiration is not None and m.expiration < now,
                    "manage_permission": m.manage_permission, "manage_membership": m.manage_membership})
    return out


@router.post("/admin/roles/grant", status_code=201)
def grant_role(body: AdminRoleGrantCreate, db: Session = Depends(get_db)):
    if body.role not in ROLE_CAPABILITIES:
        raise HTTPException(status_code=422, detail=f"role must be one of {sorted(ROLE_CAPABILITIES)}")
    rg = AdminRoleGrant(id=uuid.uuid4().hex, scope_type=body.scope_type, scope_id=body.scope_id,
                   principal_type=body.principal_type, principal_id=body.principal_id, role=body.role, created_at=_now())
    db.add(rg)
    db.add(models_action.AuditLog(id=uuid.uuid4().hex, actor="admin", event_type="admin.role.granted",
                                  subject_type=body.scope_type, subject_id=body.scope_id,
                                  payload={"principal": body.principal_id, "role": body.role}))
    db.commit()
    return {"id": rg.id, "scope": f"{body.scope_type}:{body.scope_id}", "principal": body.principal_id, "role": body.role}


@router.get("/admin/roles")
def list_grants(scope_id: Optional[str] = None, db: Session = Depends(get_db)):
    q = db.query(AdminRoleGrant)
    if scope_id:
        q = q.filter(AdminRoleGrant.scope_id == scope_id)
    return [{"scope_type": g.scope_type, "scope_id": g.scope_id, "principal_type": g.principal_type,
             "principal_id": g.principal_id, "role": g.role} for g in q.all()]


def _ancestors(db: Session, scope_type: str, scope_id: str) -> List[Tuple[str, str]]:
    chain = [(scope_type, scope_id)]
    if scope_type == "project":
        # project -> space -> organization -> enrollment
        proj = db.get(AdminProject, scope_id)
        if proj:
            chain.append(("space", proj.space_id))
            sp = db.get(Space, proj.space_id)
            if sp:
                chain.append(("organization", sp.organization_id))
                org = db.get(Organization, sp.organization_id)
                if org:
                    chain.append(("enrollment", org.enrollment_id))
    elif scope_type == "space":
        sp = db.get(Space, scope_id)
        if sp:
            chain.append(("organization", sp.organization_id))
            org = db.get(Organization, sp.organization_id)
            if org:
                chain.append(("enrollment", org.enrollment_id))
    elif scope_type == "organization":
        org = db.get(Organization, scope_id)
        if org:
            chain.append(("enrollment", org.enrollment_id))
    return chain


@router.post("/admin/access-check")
def access_check(body: AccessCheckRequest, db: Session = Depends(get_db)):
    user = db.get(AdminUser, body.user_id)
    if not user:
        raise HTTPException(status_code=404, detail="user not found")
    if user.status != "active":
        return {"allowed": False, "reason": "user inactive", "effective_roles": []}

    now = _now()
    group_ids = [m.group_id for m in db.query(GroupMembership).filter(GroupMembership.user_id == body.user_id).all()
                 if m.expiration is None or m.expiration >= now]

    scopes = _ancestors(db, body.scope_type, body.scope_id)  # role grants inherit down the hierarchy
    roles: Set[str] = set()
    for st, sid in scopes:
        for g in db.query(AdminRoleGrant).filter(AdminRoleGrant.scope_type == st, AdminRoleGrant.scope_id == sid).all():
            if (g.principal_type == "user" and g.principal_id == body.user_id) or \
               (g.principal_type == "group" and g.principal_id in group_ids):
                roles.add(g.role)

    caps: Set[str] = set()
    for r in roles:
        caps.update(ROLE_CAPABILITIES.get(r, []))
    return {"user_id": body.user_id, "scope": f"{body.scope_type}:{body.scope_id}",
            "effective_roles": sorted(roles), "capabilities": sorted(caps),
            "allowed": body.capability in caps, "via_groups": group_ids,
            "scopes_considered": [f"{t}:{i}" for t, i in scopes]}

import re
import time
import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import JSON, Boolean, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, Session, mapped_column, relationship

from . import models, models_action
from .database import Base, get_db

router = APIRouter(tags=["security"])


# ---------------------------------------------------------------------------
# SQLAlchemy models (2.0 style)
# ---------------------------------------------------------------------------

class Marking(Base):
    __tablename__ = "markings"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    display_name: Mapped[str] = mapped_column(String, nullable=False)
    category: Mapped[str] = mapped_column(String, nullable=False)  # PII/PHI/SECRET/CUI/custom
    description: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    created_at: Mapped[int] = mapped_column(Integer, default=lambda: int(time.time()))

    grants: Mapped[List["MarkingGrant"]] = relationship("MarkingGrant", back_populates="marking")


# Granular marking permission types (Foundry: manage permissions / apply / remove /
# members). A "full"/permissive grant (the historical behavior of POST
# /markings/{id}/grant) is modeled as the sentinel permission "*" which satisfies
# every permission check.
MARKING_PERMISSIONS = {"manage", "apply", "remove", "members"}
MARKING_PERMISSION_FULL = "*"


class MarkingGrant(Base):
    __tablename__ = "marking_grants"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    marking_id: Mapped[str] = mapped_column(String, ForeignKey("markings.id"), nullable=False, index=True)
    principal: Mapped[str] = mapped_column(String, nullable=False, index=True)
    # Granular permission carried by this grant. Defaults to the full/permissive
    # sentinel so historical rows (and the legacy /grant endpoint) keep working.
    permission: Mapped[str] = mapped_column(String, nullable=False, default=MARKING_PERMISSION_FULL)
    created_at: Mapped[int] = mapped_column(Integer, default=lambda: int(time.time()))

    marking: Mapped["Marking"] = relationship("Marking", back_populates="grants")


# ---------------------------------------------------------------------------
# Marking CATEGORY governance (new prefixed tables)
#
# A marking category groups related markings and carries its own governance:
#   - visibility: "visible" (default) | "hidden" (only Category Viewers see it)
#   - org_restriction: optional org id limiting the category to one organization
# Category-level role grants (Admin / Viewer) are tracked separately.
# ---------------------------------------------------------------------------

MARKING_CATEGORY_VISIBILITIES = {"visible", "hidden"}
MARKING_CATEGORY_ROLES = {"admin", "viewer"}


class MarkingCategory(Base):
    __tablename__ = "mkcat_categories"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    visibility: Mapped[str] = mapped_column(String, nullable=False, default="visible")  # visible/hidden
    org_restriction: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    description: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    created_at: Mapped[int] = mapped_column(Integer, default=lambda: int(time.time()))


class MarkingCategoryRoleGrant(Base):
    __tablename__ = "mkcat_role_grants"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    category_id: Mapped[str] = mapped_column(
        String, ForeignKey("mkcat_categories.id"), nullable=False, index=True
    )
    principal: Mapped[str] = mapped_column(String, nullable=False, index=True)
    role: Mapped[str] = mapped_column(String, nullable=False, default="viewer")  # admin/viewer
    created_at: Mapped[int] = mapped_column(Integer, default=lambda: int(time.time()))


class RestrictedView(Base):
    __tablename__ = "restricted_views"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    display_name: Mapped[str] = mapped_column(String, nullable=False)
    object_type_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    row_filter: Mapped[Dict] = mapped_column(JSON, default=dict)
    masked_properties: Mapped[List] = mapped_column(JSON, default=list)
    required_marking_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    created_at: Mapped[int] = mapped_column(Integer, default=lambda: int(time.time()))


class RetentionPolicy(Base):
    __tablename__ = "retention_policies"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    resource_type: Mapped[str] = mapped_column(String, nullable=False)
    resource_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    ttl_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    action: Mapped[str] = mapped_column(String, nullable=False, default="delete")  # delete/archive
    # Lifecycle status of the policy's target resource: active -> expired/archived
    status: Mapped[str] = mapped_column(String, nullable=False, default="active")  # active/expired/archived
    enforced_at: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    created_at: Mapped[int] = mapped_column(Integer, default=lambda: int(time.time()))


class Checkpoint(Base):
    __tablename__ = "checkpoints"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    action_label: Mapped[str] = mapped_column(String, nullable=False)
    requires_approval: Mapped[bool] = mapped_column(Boolean, default=True)
    status: Mapped[str] = mapped_column(String, nullable=False, default="open")  # open/passed
    # Checkpoint record fields captured at pass time (Foundry checkpoint record:
    # actor, justification, trigger, resource).
    justification: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    trigger: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    resource_type: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    resource_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    passed_by: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    passed_at: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    created_at: Mapped[int] = mapped_column(Integer, default=lambda: int(time.time()))


# ---------------------------------------------------------------------------
# Pydantic schemas (inline, v2)
# ---------------------------------------------------------------------------

class MarkingCreate(BaseModel):
    id: Optional[str] = None
    display_name: str
    category: str
    description: Optional[str] = None


class MarkingRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    display_name: str
    category: str
    description: Optional[str] = None
    created_at: int


class MarkingGrantCreate(BaseModel):
    principal: str


class MarkingPermissionGrantCreate(BaseModel):
    """Granular grant: bind a single marking permission to a principal."""
    principal: str
    permission: str  # manage|apply|remove|members


class MarkingGrantRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    marking_id: str
    principal: str
    # Defaulted so legacy callers/rows (no explicit permission) deserialize as
    # the full/permissive grant.
    permission: str = MARKING_PERMISSION_FULL
    created_at: int


class MarkingCategoryCreate(BaseModel):
    id: Optional[str] = None
    name: str
    visibility: str = "visible"  # visible|hidden
    org_restriction: Optional[str] = None
    description: Optional[str] = None


class MarkingCategoryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    name: str
    visibility: str
    org_restriction: Optional[str] = None
    description: Optional[str] = None
    created_at: int


class MarkingCategoryRoleGrantCreate(BaseModel):
    principal: str
    role: str = "viewer"  # admin|viewer


class MarkingCategoryRoleGrantRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    category_id: str
    principal: str
    role: str
    created_at: int


class RestrictedViewCreate(BaseModel):
    id: Optional[str] = None
    display_name: str
    object_type_id: str
    row_filter: Dict[str, Any] = Field(default_factory=dict)
    masked_properties: List[str] = Field(default_factory=list)
    required_marking_id: Optional[str] = None


class RestrictedViewRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    display_name: str
    object_type_id: str
    row_filter: Dict[str, Any]
    masked_properties: List[str]
    required_marking_id: Optional[str]
    created_at: int


class RestrictedViewApplyRequest(BaseModel):
    principal: str
    rows: List[Dict[str, Any]]


class RetentionPolicyCreate(BaseModel):
    id: Optional[str] = None
    resource_type: str
    resource_id: str
    ttl_seconds: int
    action: str = "delete"


class RetentionPolicyRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    resource_type: str
    resource_id: str
    ttl_seconds: int
    action: str
    status: str
    enforced_at: Optional[int] = None
    created_at: int


class RetentionSweepRequest(BaseModel):
    # Deterministic clock: epoch seconds used to evaluate elapsed TTLs.
    # Defaults to wall-clock if not supplied.
    now: Optional[int] = None
    # Optionally limit the sweep to a single resource_type.
    resource_type: Optional[str] = None


class RetentionExpiredItem(BaseModel):
    policy_id: str
    resource_type: str
    resource_id: str
    action: str  # delete -> expired ; archive -> archived
    status: str  # expired/archived
    expires_at: int
    enforced_at: int


class RetentionSweepResponse(BaseModel):
    now: int
    expired: List[RetentionExpiredItem]
    expired_count: int


class CheckpointCreate(BaseModel):
    id: Optional[str] = None
    action_label: str
    requires_approval: bool = True


class CheckpointPassRequest(BaseModel):
    justification: str = Field(..., min_length=1)
    actor: str = "system"
    trigger: Optional[str] = None
    resource_type: Optional[str] = None
    resource_id: Optional[str] = None


class CheckpointRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    action_label: str
    requires_approval: bool
    status: str
    justification: Optional[str] = None
    trigger: Optional[str] = None
    resource_type: Optional[str] = None
    resource_id: Optional[str] = None
    passed_by: Optional[str] = None
    passed_at: Optional[int] = None
    created_at: int


class ScanRequest(BaseModel):
    records: List[Dict[str, Any]]


class ScanFinding(BaseModel):
    field: str
    pattern: str


class ScanResponse(BaseModel):
    findings: List[ScanFinding]


# ---------------------------------------------------------------------------
# Regex patterns for governance scanner
# ---------------------------------------------------------------------------

_SCAN_PATTERNS: List[tuple] = [
    ("email", re.compile(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z]{2,}")),
    ("ssn", re.compile(r"\b\d{3}-\d{2}-\d{4}\b")),
    ("phone", re.compile(r"\b(?:\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]\d{3}[-.\s]\d{4}\b")),
    ("credit_card", re.compile(r"\b(?:\d{4}[-\s]?){3}\d{4}\b")),
]


def _scan_value(value: str) -> List[str]:
    matched = []
    for pattern_name, pattern in _SCAN_PATTERNS:
        if pattern.search(value):
            matched.append(pattern_name)
    return matched


# ---------------------------------------------------------------------------
# Helper: check if principal holds a marking
# ---------------------------------------------------------------------------

def _principal_holds_marking(db: Session, principal: str, marking_id: str) -> bool:
    grant = (
        db.query(MarkingGrant)
        .filter(MarkingGrant.marking_id == marking_id, MarkingGrant.principal == principal)
        .first()
    )
    return grant is not None


def principal_has_marking_permission(
    db: Session, principal: str, marking_id: str, permission: str
) -> bool:
    """Return True if ``principal`` holds the requested granular ``permission`` on
    the marking. A full/permissive grant (permission == "*") satisfies every
    permission, preserving the historical semantics of POST /markings/{id}/grant.
    """
    grants = (
        db.query(MarkingGrant)
        .filter(MarkingGrant.marking_id == marking_id, MarkingGrant.principal == principal)
        .all()
    )
    for g in grants:
        if g.permission == MARKING_PERMISSION_FULL or g.permission == permission:
            return True
    return False


# ---------------------------------------------------------------------------
# Endpoints: /markings
# ---------------------------------------------------------------------------

@router.post("/markings", response_model=MarkingRead)
def create_marking(body: MarkingCreate, db: Session = Depends(get_db)):
    marking_id = body.id or uuid.uuid4().hex
    existing = db.query(Marking).filter(Marking.id == marking_id).first()
    if existing:
        raise HTTPException(status_code=400, detail="Marking already exists")
    row = Marking(
        id=marking_id,
        display_name=body.display_name,
        category=body.category,
        description=body.description,
        created_at=int(time.time()),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@router.get("/markings", response_model=List[MarkingRead])
def list_markings(db: Session = Depends(get_db)):
    return db.query(Marking).order_by(Marking.created_at.desc()).all()


# ---------------------------------------------------------------------------
# Endpoints: /markings/{id}/grant and /markings/{id}/grants
# ---------------------------------------------------------------------------

@router.post("/markings/{marking_id}/grant", response_model=MarkingGrantRead)
def grant_marking(marking_id: str, body: MarkingGrantCreate, db: Session = Depends(get_db)):
    marking = db.query(Marking).filter(Marking.id == marking_id).first()
    if not marking:
        raise HTTPException(status_code=404, detail=f"Marking '{marking_id}' not found")
    existing = (
        db.query(MarkingGrant)
        .filter(MarkingGrant.marking_id == marking_id, MarkingGrant.principal == body.principal)
        .first()
    )
    if existing:
        return existing
    grant_id = uuid.uuid4().hex
    grant = MarkingGrant(
        id=grant_id,
        marking_id=marking_id,
        principal=body.principal,
        created_at=int(time.time()),
    )
    db.add(grant)
    db.add(
        models_action.AuditLog(
            id=uuid.uuid4().hex,
            actor="system",
            event_type="security.marking.granted",
            subject_type="marking_grant",
            subject_id=grant_id,
            payload={"marking_id": marking_id, "principal": body.principal},
        )
    )
    db.commit()
    db.refresh(grant)
    return grant


@router.post("/markings/{marking_id}/grant-permission", response_model=MarkingGrantRead)
def grant_marking_permission(
    marking_id: str,
    body: MarkingPermissionGrantCreate,
    db: Session = Depends(get_db),
):
    """Granular grant: bind a single marking permission (manage|apply|remove|members)
    to a principal. Unlike the legacy /grant (which issues a full/permissive grant),
    this scopes the grant to exactly one permission so callers can grant APPLY
    without REMOVE, etc.
    """
    marking = db.query(Marking).filter(Marking.id == marking_id).first()
    if not marking:
        raise HTTPException(status_code=404, detail=f"Marking '{marking_id}' not found")
    if body.permission not in MARKING_PERMISSIONS:
        raise HTTPException(
            status_code=422,
            detail=f"permission must be one of {sorted(MARKING_PERMISSIONS)}",
        )
    existing = (
        db.query(MarkingGrant)
        .filter(
            MarkingGrant.marking_id == marking_id,
            MarkingGrant.principal == body.principal,
            MarkingGrant.permission == body.permission,
        )
        .first()
    )
    if existing:
        return existing
    grant_id = uuid.uuid4().hex
    grant = MarkingGrant(
        id=grant_id,
        marking_id=marking_id,
        principal=body.principal,
        permission=body.permission,
        created_at=int(time.time()),
    )
    db.add(grant)
    db.add(
        models_action.AuditLog(
            id=uuid.uuid4().hex,
            actor="system",
            event_type="security.marking.permission_granted",
            subject_type="marking_grant",
            subject_id=grant_id,
            payload={
                "marking_id": marking_id,
                "principal": body.principal,
                "permission": body.permission,
            },
        )
    )
    db.commit()
    db.refresh(grant)
    return grant


@router.get("/markings/{marking_id}/grants", response_model=List[MarkingGrantRead])
def list_marking_grants(marking_id: str, db: Session = Depends(get_db)):
    marking = db.query(Marking).filter(Marking.id == marking_id).first()
    if not marking:
        raise HTTPException(status_code=404, detail=f"Marking '{marking_id}' not found")
    return db.query(MarkingGrant).filter(MarkingGrant.marking_id == marking_id).all()


# ---------------------------------------------------------------------------
# Endpoints: /marking-categories (CATEGORY governance)
# ---------------------------------------------------------------------------

@router.post("/marking-categories", response_model=MarkingCategoryRead)
def create_marking_category(body: MarkingCategoryCreate, db: Session = Depends(get_db)):
    category_id = body.id or uuid.uuid4().hex
    existing = db.query(MarkingCategory).filter(MarkingCategory.id == category_id).first()
    if existing:
        raise HTTPException(status_code=400, detail="MarkingCategory already exists")
    if body.visibility not in MARKING_CATEGORY_VISIBILITIES:
        raise HTTPException(
            status_code=422,
            detail=f"visibility must be one of {sorted(MARKING_CATEGORY_VISIBILITIES)}",
        )
    row = MarkingCategory(
        id=category_id,
        name=body.name,
        visibility=body.visibility,
        org_restriction=body.org_restriction,
        description=body.description,
        created_at=int(time.time()),
    )
    db.add(row)
    db.add(
        models_action.AuditLog(
            id=uuid.uuid4().hex,
            actor="system",
            event_type="security.marking_category.created",
            subject_type="marking_category",
            subject_id=category_id,
            payload={
                "name": body.name,
                "visibility": body.visibility,
                "org_restriction": body.org_restriction,
            },
        )
    )
    db.commit()
    db.refresh(row)
    return row


@router.get("/marking-categories", response_model=List[MarkingCategoryRead])
def list_marking_categories(db: Session = Depends(get_db)):
    return db.query(MarkingCategory).order_by(MarkingCategory.created_at.desc()).all()


@router.post(
    "/marking-categories/{category_id}/roles",
    response_model=MarkingCategoryRoleGrantRead,
)
def grant_marking_category_role(
    category_id: str,
    body: MarkingCategoryRoleGrantCreate,
    db: Session = Depends(get_db),
):
    """Grant a category-level role (admin|viewer). Category Admins can manage the
    category and its markings; Category Viewers can see a hidden category and its
    markings.
    """
    category = db.query(MarkingCategory).filter(MarkingCategory.id == category_id).first()
    if not category:
        raise HTTPException(status_code=404, detail=f"MarkingCategory '{category_id}' not found")
    if body.role not in MARKING_CATEGORY_ROLES:
        raise HTTPException(
            status_code=422,
            detail=f"role must be one of {sorted(MARKING_CATEGORY_ROLES)}",
        )
    existing = (
        db.query(MarkingCategoryRoleGrant)
        .filter(
            MarkingCategoryRoleGrant.category_id == category_id,
            MarkingCategoryRoleGrant.principal == body.principal,
            MarkingCategoryRoleGrant.role == body.role,
        )
        .first()
    )
    if existing:
        return existing
    grant_id = uuid.uuid4().hex
    grant = MarkingCategoryRoleGrant(
        id=grant_id,
        category_id=category_id,
        principal=body.principal,
        role=body.role,
        created_at=int(time.time()),
    )
    db.add(grant)
    db.add(
        models_action.AuditLog(
            id=uuid.uuid4().hex,
            actor="system",
            event_type="security.marking_category.role_granted",
            subject_type="marking_category",
            subject_id=category_id,
            payload={"principal": body.principal, "role": body.role},
        )
    )
    db.commit()
    db.refresh(grant)
    return grant


@router.get(
    "/marking-categories/{category_id}/roles",
    response_model=List[MarkingCategoryRoleGrantRead],
)
def list_marking_category_roles(category_id: str, db: Session = Depends(get_db)):
    category = db.query(MarkingCategory).filter(MarkingCategory.id == category_id).first()
    if not category:
        raise HTTPException(status_code=404, detail=f"MarkingCategory '{category_id}' not found")
    return (
        db.query(MarkingCategoryRoleGrant)
        .filter(MarkingCategoryRoleGrant.category_id == category_id)
        .all()
    )


# ---------------------------------------------------------------------------
# Endpoints: /restricted-views
# ---------------------------------------------------------------------------

@router.post("/restricted-views", response_model=RestrictedViewRead)
def create_restricted_view(body: RestrictedViewCreate, db: Session = Depends(get_db)):
    view_id = body.id or uuid.uuid4().hex
    existing = db.query(RestrictedView).filter(RestrictedView.id == view_id).first()
    if existing:
        raise HTTPException(status_code=400, detail="RestrictedView already exists")
    row = RestrictedView(
        id=view_id,
        display_name=body.display_name,
        object_type_id=body.object_type_id,
        row_filter=body.row_filter,
        masked_properties=body.masked_properties,
        required_marking_id=body.required_marking_id,
        created_at=int(time.time()),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@router.get("/restricted-views", response_model=List[RestrictedViewRead])
def list_restricted_views(db: Session = Depends(get_db)):
    return db.query(RestrictedView).order_by(RestrictedView.created_at.desc()).all()


@router.post("/restricted-views/{view_id}/apply")
def apply_restricted_view(
    view_id: str,
    body: RestrictedViewApplyRequest,
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    view = db.query(RestrictedView).filter(RestrictedView.id == view_id).first()
    if not view:
        raise HTTPException(status_code=404, detail=f"RestrictedView '{view_id}' not found")

    principal = body.principal
    row_filter: Dict[str, Any] = view.row_filter or {}
    masked_props: List[str] = list(view.masked_properties or [])
    required_marking_id: Optional[str] = view.required_marking_id

    # Determine whether this principal can see unmasked data
    principal_cleared = (
        required_marking_id is None
        or _principal_holds_marking(db, principal, required_marking_id)
    )

    filtered_rows: List[Dict[str, Any]] = []
    for row in body.rows:
        # Apply row_filter: each key in row_filter must match the row value
        passes_filter = True
        for fk, fv in row_filter.items():
            if row.get(fk) != fv:
                passes_filter = False
                break
        if not passes_filter:
            continue

        # Mask properties if not cleared
        out_row = dict(row)
        if not principal_cleared:
            for prop in masked_props:
                if prop in out_row:
                    out_row[prop] = "***"
        filtered_rows.append(out_row)

    return {"view_id": view_id, "principal": principal, "rows": filtered_rows, "total": len(filtered_rows)}


# ---------------------------------------------------------------------------
# Endpoint: /governance/scan
# ---------------------------------------------------------------------------

@router.post("/governance/scan", response_model=ScanResponse)
def governance_scan(body: ScanRequest, db: Session = Depends(get_db)) -> ScanResponse:
    findings: List[ScanFinding] = []
    for record in body.records:
        for field, value in record.items():
            if not isinstance(value, str):
                value = str(value) if value is not None else ""
            matched_patterns = _scan_value(value)
            for pattern_name in matched_patterns:
                findings.append(ScanFinding(field=field, pattern=pattern_name))
    try:
        from . import ops_control
        ops_control.record_ops_event(
            db,
            source="security",
            event_type="governance.scan",
            severity="high" if findings else "info",
            title="Governance scan completed",
            subject_type="governance_scan",
            subject_id=uuid.uuid4().hex,
            payload={"finding_count": len(findings), "findings": [finding.model_dump() for finding in findings[:50]]},
        )
        db.commit()
    except Exception:
        db.rollback()
    return ScanResponse(findings=findings)


# ---------------------------------------------------------------------------
# Endpoints: /retention-policies
# ---------------------------------------------------------------------------

@router.post("/retention-policies", response_model=RetentionPolicyRead)
def create_retention_policy(body: RetentionPolicyCreate, db: Session = Depends(get_db)):
    policy_id = body.id or uuid.uuid4().hex
    existing = db.query(RetentionPolicy).filter(RetentionPolicy.id == policy_id).first()
    if existing:
        raise HTTPException(status_code=400, detail="RetentionPolicy already exists")
    if body.action not in ("delete", "archive"):
        raise HTTPException(status_code=422, detail="action must be 'delete' or 'archive'")
    row = RetentionPolicy(
        id=policy_id,
        resource_type=body.resource_type,
        resource_id=body.resource_id,
        ttl_seconds=body.ttl_seconds,
        action=body.action,
        created_at=int(time.time()),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@router.get("/retention-policies", response_model=List[RetentionPolicyRead])
def list_retention_policies(db: Session = Depends(get_db)):
    return db.query(RetentionPolicy).order_by(RetentionPolicy.created_at.desc()).all()


@router.post("/retention-policies/enforce", response_model=RetentionSweepResponse)
def enforce_retention_policies(
    body: RetentionSweepRequest,
    db: Session = Depends(get_db),
) -> RetentionSweepResponse:
    """Sweep retention policies and expire/archive resources whose TTL has elapsed.

    A policy's resource is considered elapsed when ``created_at + ttl_seconds <= now``.
    The sweep is deterministic: callers pass an explicit ``now`` epoch for testability
    (defaults to wall clock). Policies are only enforced once: those already in a
    terminal state (``expired``/``archived``) are skipped, so the sweep is idempotent.
    An AuditLog row is written for each resource expired/archived.
    """
    now = body.now if body.now is not None else int(time.time())

    q = db.query(RetentionPolicy).filter(RetentionPolicy.status == "active")
    if body.resource_type is not None:
        q = q.filter(RetentionPolicy.resource_type == body.resource_type)

    expired: List[RetentionExpiredItem] = []
    for policy in q.order_by(RetentionPolicy.created_at).all():
        expires_at = policy.created_at + policy.ttl_seconds
        if expires_at > now:
            continue
        new_status = "archived" if policy.action == "archive" else "expired"
        policy.status = new_status
        policy.enforced_at = now
        db.add(
            models_action.AuditLog(
                id=uuid.uuid4().hex,
                actor="system",
                event_type=f"security.retention.{new_status}",
                subject_type=policy.resource_type,
                subject_id=policy.resource_id,
                payload={
                    "policy_id": policy.id,
                    "action": policy.action,
                    "ttl_seconds": policy.ttl_seconds,
                    "expires_at": expires_at,
                    "enforced_at": now,
                },
            )
        )
        expired.append(
            RetentionExpiredItem(
                policy_id=policy.id,
                resource_type=policy.resource_type,
                resource_id=policy.resource_id,
                action=policy.action,
                status=new_status,
                expires_at=expires_at,
                enforced_at=now,
            )
        )

    db.commit()
    return RetentionSweepResponse(now=now, expired=expired, expired_count=len(expired))


# ---------------------------------------------------------------------------
# Endpoints: /checkpoints
# ---------------------------------------------------------------------------

@router.post("/checkpoints", response_model=CheckpointRead)
def create_checkpoint(body: CheckpointCreate, db: Session = Depends(get_db)):
    checkpoint_id = body.id or uuid.uuid4().hex
    existing = db.query(Checkpoint).filter(Checkpoint.id == checkpoint_id).first()
    if existing:
        raise HTTPException(status_code=400, detail="Checkpoint already exists")
    row = Checkpoint(
        id=checkpoint_id,
        action_label=body.action_label,
        requires_approval=body.requires_approval,
        status="open",
        created_at=int(time.time()),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@router.get("/checkpoints", response_model=List[CheckpointRead])
def list_checkpoints(db: Session = Depends(get_db)):
    return db.query(Checkpoint).order_by(Checkpoint.created_at.desc()).all()


@router.post("/checkpoints/{checkpoint_id}/pass", response_model=CheckpointRead)
def pass_checkpoint(
    checkpoint_id: str,
    body: CheckpointPassRequest,
    db: Session = Depends(get_db),
):
    """Pass a checkpoint.

    A justification is mandatory (Foundry checkpoints always require a
    user-supplied justification; it cannot be autofilled). The request may
    optionally bind a ``trigger`` describing the interaction and a checkpointed
    ``resource`` (resource_type + resource_id). Passing writes an append-only
    AuditLog row capturing the checkpoint record.
    """
    checkpoint = db.query(Checkpoint).filter(Checkpoint.id == checkpoint_id).first()
    if not checkpoint:
        raise HTTPException(status_code=404, detail=f"Checkpoint '{checkpoint_id}' not found")
    # Justification is required; an empty/whitespace-only value is rejected.
    if not body.justification or not body.justification.strip():
        raise HTTPException(status_code=422, detail="justification is required to pass a checkpoint")
    if checkpoint.status == "passed":
        return checkpoint

    now = int(time.time())
    checkpoint.status = "passed"
    checkpoint.justification = body.justification
    checkpoint.trigger = body.trigger
    checkpoint.resource_type = body.resource_type
    checkpoint.resource_id = body.resource_id
    checkpoint.passed_by = body.actor
    checkpoint.passed_at = now

    db.add(
        models_action.AuditLog(
            id=uuid.uuid4().hex,
            actor=body.actor,
            event_type="security.checkpoint.passed",
            subject_type="checkpoint",
            subject_id=checkpoint_id,
            payload={
                "action_label": checkpoint.action_label,
                "justification": body.justification,
                "trigger": body.trigger,
                "resource_type": body.resource_type,
                "resource_id": body.resource_id,
                "passed_at": now,
            },
        )
    )
    db.commit()
    db.refresh(checkpoint)
    return checkpoint

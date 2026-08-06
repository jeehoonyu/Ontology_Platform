"""
Foundry ONTOLOGY INTERFACES (deepening): inheritance resolution, explicit object-type
implementations, polymorphic queries, interface link-type constraints, and interface actions.

Docs basis: interfaces/{interface-overview,create-interface,implement-interface,
extend-interface,interface-link-types-overview,interface-metadata},
action-types/actions-on-interfaces.

This module REUSES (read-only) the base interface tables defined in
`app/ontology_interfaces.py`:
    OntologyInterface (ontology_interfaces) - id, display_name, description,
        properties{name->{base_type,required}}, extends[parent ids], created_at, updated_at
    SharedPropertyType (shared_property_types)
    VALID_BASE_TYPES
It does NOT redefine or modify them.

NEW tables (all prefixed Iface/iface_ to avoid Base collisions):
    IfaceLinkConstraint  (iface_link_constraints)
    IfaceImplementation  (iface_implementations)
    IfaceAction          (iface_actions)
"""

from .database import Base, get_db
from . import models, models_action, production_auth, tenancy
from .ontology_interfaces import OntologyInterface, SharedPropertyType, VALID_BASE_TYPES  # noqa: F401  (read-only reuse)
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import String, Integer, JSON, Boolean, Float, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, Session
from pydantic import BaseModel, ConfigDict, Field
from typing import Optional, List, Any, Dict
import time, uuid


# ---------------------------------------------------------------------------
# SQLAlchemy models (NEW, prefixed)
# ---------------------------------------------------------------------------

class IfaceLinkConstraint(Base):
    """A link constraint declared on an interface (an interface link type)."""
    __tablename__ = "iface_link_constraints"

    id: Mapped[str] = mapped_column(String, primary_key=True, index=True)
    interface_id: Mapped[str] = mapped_column(String, ForeignKey("ontology_interfaces.id"), index=True)
    api_name: Mapped[str] = mapped_column(String)
    target_kind: Mapped[str] = mapped_column(String)  # "interface" | "object_type"
    target_id: Mapped[str] = mapped_column(String)
    cardinality: Mapped[str] = mapped_column(String)  # "ONE" | "MANY"
    required: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[int] = mapped_column(Integer)


class IfaceImplementation(Base):
    """An explicit declaration that an object type implements an interface."""
    __tablename__ = "iface_implementations"

    id: Mapped[str] = mapped_column(String, primary_key=True, index=True)
    object_type_id: Mapped[str] = mapped_column(String, ForeignKey("object_types.id"), index=True)
    interface_id: Mapped[str] = mapped_column(String, ForeignKey("ontology_interfaces.id"), index=True)
    # {interface_prop -> object_type_prop}
    property_mappings: Mapped[dict] = mapped_column(JSON, default=dict)
    # {constraint_api_name -> link_type_id}
    link_mappings: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[int] = mapped_column(Integer)


class IfaceAction(Base):
    """An interface action (create/modify/delete) defined polymorphically on an interface."""
    __tablename__ = "iface_actions"

    id: Mapped[str] = mapped_column(String, primary_key=True, index=True)
    interface_id: Mapped[str] = mapped_column(String, ForeignKey("ontology_interfaces.id"), index=True)
    api_name: Mapped[str] = mapped_column(String)
    operation: Mapped[str] = mapped_column(String)  # "create" | "modify" | "delete"
    # shared property used as primary key for create actions (see CRITICAL doc rule)
    parameter_property: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    created_at: Mapped[int] = mapped_column(Integer)


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------

class LinkConstraintCreate(BaseModel):
    id: Optional[str] = None
    api_name: str
    target_kind: str  # interface | object_type
    target_id: str
    cardinality: str = "MANY"  # ONE | MANY
    required: bool = False


class LinkConstraintRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    interface_id: str
    api_name: str
    target_kind: str
    target_id: str
    cardinality: str
    required: bool
    created_at: int


class ImplementInterfaceRequest(BaseModel):
    interface_id: str
    property_mappings: Dict[str, str] = Field(default_factory=dict)
    link_mappings: Dict[str, str] = Field(default_factory=dict)


class ImplementationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    object_type_id: str
    interface_id: str
    property_mappings: Dict[str, str]
    link_mappings: Dict[str, str]
    created_at: int


class CheckObjectTypeRequest(BaseModel):
    object_type_id: str


class CheckObjectTypeResult(BaseModel):
    conforms: bool
    missing_properties: List[str]
    missing_link_constraints: List[str]


class QueryObjectsRequest(BaseModel):
    filters: Dict[str, Any] = Field(default_factory=dict)
    limit: Optional[int] = None
    # Narrows the query to one project. Omitting it does not widen the query
    # past what the caller may read; it means "every project I can read".
    project_id: Optional[str] = None


class InterfaceActionCreate(BaseModel):
    id: Optional[str] = None
    api_name: str
    operation: str  # create | modify | delete
    parameter_property: Optional[str] = None


class InterfaceActionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    interface_id: str
    api_name: str
    operation: str
    parameter_property: Optional[str] = None
    created_at: int


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

router = APIRouter(tags=["ontology-interfaces-ops"])

VALID_TARGET_KINDS = {"interface", "object_type"}
VALID_CARDINALITIES = {"ONE", "MANY"}
VALID_OPERATIONS = {"create", "modify", "delete"}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_interface(db: Session, interface_id: str) -> OntologyInterface:
    iface = db.query(OntologyInterface).filter(OntologyInterface.id == interface_id).first()
    if not iface:
        raise HTTPException(status_code=404, detail=f"OntologyInterface '{interface_id}' not found")
    return iface


def _resolve_properties(db: Session, interface_id: str) -> (Dict[str, dict], Dict[str, str]):
    """
    BFS the `extends` chain (cycle-safe). Union parents' properties with local;
    local overrides parent on name clash. Returns (flattened_props, inherited_from).

    Resolution order: parents first (so locals override), so we walk ancestors and
    apply the most-derived definition last. We accumulate from the root down by
    processing the inheritance tree breadth-first and letting nearer-to-self
    definitions win.
    """
    # Collect interfaces in order from self outward (self, then parents, then grandparents...).
    order: List[str] = []
    seen = set()
    queue = [interface_id]
    while queue:
        cur = queue.pop(0)
        if cur in seen:
            continue
        seen.add(cur)
        node = db.query(OntologyInterface).filter(OntologyInterface.id == cur).first()
        if not node:
            continue
        order.append(cur)
        for parent in (node.extends or []):
            if parent not in seen:
                queue.append(parent)

    # Build the flattened dict: process from farthest ancestor to self so that
    # nearer (more-derived) definitions overwrite. `order` is self-first BFS, so
    # reverse it -> ancestors first, self last.
    flattened: Dict[str, dict] = {}
    inherited_from: Dict[str, str] = {}
    for iface_id in reversed(order):
        node = db.query(OntologyInterface).filter(OntologyInterface.id == iface_id).first()
        if not node:
            continue
        for prop_name, spec in (node.properties or {}).items():
            flattened[prop_name] = dict(spec)
            inherited_from[prop_name] = iface_id
    return flattened, inherited_from


# A declared base type satisfies an interface requirement when it is the same
# type, or a widening that discards nothing the interface asked for. A geopoint
# satisfies a geoshape requirement because a point is a geometry; the reverse is
# not true, and neither direction holds for a string.
_WIDENING: Dict[str, set] = {
    "byte": {"short", "integer", "long", "float", "double", "decimal"},
    "short": {"integer", "long", "float", "double", "decimal"},
    "integer": {"long", "double", "decimal"},
    "long": {"decimal"},
    "float": {"double", "decimal"},
    "double": {"decimal"},
    "date": {"timestamp"},
    "geopoint": {"geoshape"},
}

# Legacy ObjectType.properties uses JSON-schema style names. Map them onto the
# ontology base-type vocabulary so an object type that predates a normalized
# profile can still be judged rather than waved through.
_LEGACY_TO_BASE = {
    "string": "string", "integer": "integer", "number": "double",
    "boolean": "boolean", "array": "array", "object": "struct",
    "json": "struct", "geometry": "geoshape", "geojson": "geoshape",
    "any": "", "": "",
}


def _declared_base_types(db: Session, object_type_id: str) -> Dict[str, str]:
    """Property name -> declared base type, normalized profile first.

    The profile is authoritative because it records real base types. The legacy
    JSON schema on ObjectType is the fallback for types that predate a profile,
    mapped onto the base vocabulary rather than compared as free text.
    """
    from sqlalchemy import inspect as sa_inspect

    from .ontology_core import ObjectTypeProfile

    # The normalized profile table is absent in partial schemas, so its presence
    # is checked rather than assumed. Falling back to the legacy bag keeps an
    # older deployment judging conformance instead of failing the request.
    bind = db.get_bind()
    profile = None
    if bind is not None and sa_inspect(bind).has_table(ObjectTypeProfile.__tablename__):
        profile = db.get(ObjectTypeProfile, object_type_id)
    if profile is not None and profile.properties:
        return {
            name: ((spec or {}).get("base_type") or "") if isinstance(spec, dict) else ""
            for name, spec in profile.properties.items()
        }
    obj = db.query(models.ObjectType).filter(models.ObjectType.id == object_type_id).first()
    if obj is None:
        return {}
    resolved: Dict[str, str] = {}
    for name, spec in (obj.properties or {}).items():
        raw = (spec or {}).get("type", "") if isinstance(spec, dict) else ""
        resolved[name] = _LEGACY_TO_BASE.get(str(raw).lower(), str(raw))
    return resolved


def base_type_satisfies(declared: str, required: str) -> bool:
    """Whether a declared property type meets an interface's required type."""
    from .ontology_interfaces import normalize_base_type

    # An interface may still carry a legacy name such as "geo"; resolve both
    # sides onto the ontology vocabulary before comparing.
    declared = normalize_base_type(declared)
    required = normalize_base_type(required)
    if not required:
        return True
    if not declared:
        # The object type declares no type for this property, so the requirement
        # can be neither confirmed nor refuted. It is allowed rather than
        # refused: legacy property bags frequently omit a type, and rejecting
        # them would break implementations that already exist, which the goal's
        # compatibility-preserving rule forbids. The guarantee is therefore
        # enforced wherever a type is declared and unavailable where it is not,
        # which is a real limit on what an interface promises over legacy data.
        return True
    if declared == required:
        return True
    return required in _WIDENING.get(declared, set())


def _resolve_link_constraints(db: Session, interface_id: str) -> Dict[str, IfaceLinkConstraint]:
    """
    Resolve inherited link constraints over the `extends` chain (cycle-safe).
    Keyed by api_name; nearer (more-derived) definitions override ancestors.
    """
    order: List[str] = []
    seen = set()
    queue = [interface_id]
    while queue:
        cur = queue.pop(0)
        if cur in seen:
            continue
        seen.add(cur)
        node = db.query(OntologyInterface).filter(OntologyInterface.id == cur).first()
        if not node:
            continue
        order.append(cur)
        for parent in (node.extends or []):
            if parent not in seen:
                queue.append(parent)

    resolved: Dict[str, IfaceLinkConstraint] = {}
    for iface_id in reversed(order):  # ancestors first, self last (self wins)
        constraints = (
            db.query(IfaceLinkConstraint)
            .filter(IfaceLinkConstraint.interface_id == iface_id)
            .all()
        )
        for c in constraints:
            resolved[c.api_name] = c
    return resolved


# ---------------------------------------------------------------------------
# Link-type constraints
# ---------------------------------------------------------------------------

@router.post("/interfaces/{interface_id}/link-type-constraints", response_model=LinkConstraintRead)
def create_link_constraint(
    interface_id: str,
    body: LinkConstraintCreate,
    db: Session = Depends(get_db),
):
    _get_interface(db, interface_id)
    if body.target_kind not in VALID_TARGET_KINDS:
        raise HTTPException(status_code=422, detail=f"target_kind must be one of {sorted(VALID_TARGET_KINDS)}")
    if body.cardinality not in VALID_CARDINALITIES:
        raise HTTPException(status_code=422, detail=f"cardinality must be one of {sorted(VALID_CARDINALITIES)}")

    # Validate target reference exists.
    if body.target_kind == "interface":
        if not db.query(OntologyInterface).filter(OntologyInterface.id == body.target_id).first():
            raise HTTPException(status_code=404, detail=f"Target interface '{body.target_id}' not found")
    else:
        if not db.query(models.ObjectType).filter(models.ObjectType.id == body.target_id).first():
            raise HTTPException(status_code=404, detail=f"Target object type '{body.target_id}' not found")

    cid = body.id or uuid.uuid4().hex
    if db.query(IfaceLinkConstraint).filter(IfaceLinkConstraint.id == cid).first():
        raise HTTPException(status_code=400, detail="IfaceLinkConstraint already exists")

    row = IfaceLinkConstraint(
        id=cid,
        interface_id=interface_id,
        api_name=body.api_name,
        target_kind=body.target_kind,
        target_id=body.target_id,
        cardinality=body.cardinality,
        required=body.required,
        created_at=int(time.time()),
    )
    db.add(row)
    db.add(models_action.AuditLog(
        id=uuid.uuid4().hex,
        actor="system",
        event_type="interfaces.link_constraint.created",
        subject_type="iface_link_constraint",
        subject_id=cid,
        payload={"interface_id": interface_id, "api_name": body.api_name},
    ))
    db.commit()
    db.refresh(row)
    return row


@router.get("/interfaces/{interface_id}/link-type-constraints")
def list_link_constraints(
    interface_id: str,
    resolved: bool = Query(False, description="If true, include inherited constraints"),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    _get_interface(db, interface_id)
    if resolved:
        resolved_map = _resolve_link_constraints(db, interface_id)
        constraints = list(resolved_map.values())
    else:
        constraints = (
            db.query(IfaceLinkConstraint)
            .filter(IfaceLinkConstraint.interface_id == interface_id)
            .all()
        )
    return {
        "interface_id": interface_id,
        "resolved": resolved,
        "constraints": [LinkConstraintRead.model_validate(c).model_dump() for c in constraints],
    }


@router.delete("/interfaces/{interface_id}/link-type-constraints/{cid}")
def delete_link_constraint(
    interface_id: str,
    cid: str,
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    _get_interface(db, interface_id)
    row = (
        db.query(IfaceLinkConstraint)
        .filter(IfaceLinkConstraint.id == cid, IfaceLinkConstraint.interface_id == interface_id)
        .first()
    )
    if not row:
        raise HTTPException(status_code=404, detail=f"IfaceLinkConstraint '{cid}' not found")
    db.delete(row)
    db.commit()
    return {"deleted": cid}


# ---------------------------------------------------------------------------
# Inherited property resolution
# ---------------------------------------------------------------------------

@router.get("/interfaces/{interface_id}/all-properties")
def get_all_properties(interface_id: str, db: Session = Depends(get_db)) -> Dict[str, Any]:
    _get_interface(db, interface_id)
    flattened, inherited_from = _resolve_properties(db, interface_id)
    link_constraints = _resolve_link_constraints(db, interface_id)
    return {
        "interface_id": interface_id,
        "properties": flattened,
        "inherited_from": inherited_from,
        "count": len(flattened),
        "link_constraints": {
            api_name: LinkConstraintRead.model_validate(c).model_dump()
            for api_name, c in link_constraints.items()
        },
    }


# ---------------------------------------------------------------------------
# Implementation declaration
# ---------------------------------------------------------------------------

@router.post("/object-types/{object_type_id}/implement-interface", response_model=ImplementationRead)
def implement_interface(
    object_type_id: str,
    body: ImplementInterfaceRequest,
    db: Session = Depends(get_db),
):
    # Validate the object type exists.
    ot = db.query(models.ObjectType).filter(models.ObjectType.id == object_type_id).first()
    if not ot:
        raise HTTPException(status_code=404, detail=f"ObjectType '{object_type_id}' not found")
    iface = _get_interface(db, body.interface_id)

    # Enforce uniqueness on (object_type_id, interface_id).
    existing = (
        db.query(IfaceImplementation)
        .filter(
            IfaceImplementation.object_type_id == object_type_id,
            IfaceImplementation.interface_id == body.interface_id,
        )
        .first()
    )
    if existing:
        raise HTTPException(
            status_code=400,
            detail=f"ObjectType '{object_type_id}' already implements interface '{body.interface_id}'",
        )

    flattened, _ = _resolve_properties(db, body.interface_id)
    ot_prop_names = set((ot.properties or {}).keys())
    declared_types = _declared_base_types(db, object_type_id)
    ot_prop_names |= set(declared_types)

    unmet: List[str] = []

    # For every REQUIRED resolved interface property there must be a mapping to an
    # existing object-type property whose declared base type satisfies the
    # requirement. Checking only that the name exists would let a string satisfy
    # a geopoint, which makes the interface a suggestion: every consumer of an
    # interface-scoped query relies on the type holding for every implementer.
    for prop_name, spec in flattened.items():
        if not spec.get("required", False):
            continue
        mapped = body.property_mappings.get(prop_name)
        if mapped is None:
            unmet.append(f"property:{prop_name} (no mapping)")
            continue
        if mapped not in ot_prop_names:
            unmet.append(f"property:{prop_name} -> '{mapped}' (object-type property not found)")
            continue
        required_type = str(spec.get("base_type") or "")
        declared_type = declared_types.get(mapped, "")
        if not base_type_satisfies(declared_type, required_type):
            unmet.append(
                f"property:{prop_name} -> '{mapped}' "
                f"(declared {declared_type or 'untyped'}, interface requires {required_type})"
            )

    # For every REQUIRED resolved link constraint there must be a link_mapping to an
    # existing LinkType whose source == ot (and target matches when target_kind=object_type).
    resolved_constraints = _resolve_link_constraints(db, body.interface_id)
    for api_name, constraint in resolved_constraints.items():
        if not constraint.required:
            continue
        mapped_lt = body.link_mappings.get(api_name)
        if mapped_lt is None:
            unmet.append(f"link:{api_name} (no link_mapping)")
            continue
        lt = db.query(models.LinkType).filter(models.LinkType.id == mapped_lt).first()
        if not lt:
            unmet.append(f"link:{api_name} -> '{mapped_lt}' (LinkType not found)")
            continue
        if lt.source_object_type_id != object_type_id:
            unmet.append(f"link:{api_name} -> '{mapped_lt}' (LinkType source != '{object_type_id}')")
            continue
        if constraint.target_kind == "object_type" and lt.target_object_type_id != constraint.target_id:
            unmet.append(
                f"link:{api_name} -> '{mapped_lt}' "
                f"(LinkType target != required '{constraint.target_id}')"
            )

    if unmet:
        raise HTTPException(
            status_code=422,
            detail={"message": "unmet interface requirements", "unmet": unmet},
        )

    impl_id = body.id if getattr(body, "id", None) else uuid.uuid4().hex
    row = IfaceImplementation(
        id=impl_id,
        object_type_id=object_type_id,
        interface_id=body.interface_id,
        property_mappings=dict(body.property_mappings),
        link_mappings=dict(body.link_mappings),
        created_at=int(time.time()),
    )
    db.add(row)
    db.add(models_action.AuditLog(
        id=uuid.uuid4().hex,
        actor="system",
        event_type="interfaces.implementation.created",
        subject_type="iface_implementation",
        subject_id=impl_id,
        payload={"object_type_id": object_type_id, "interface_id": body.interface_id},
    ))
    db.commit()
    db.refresh(row)
    return row


@router.get("/object-types/{object_type_id}/implemented-interfaces")
def list_implemented_interfaces(object_type_id: str, db: Session = Depends(get_db)) -> Dict[str, Any]:
    ot = db.query(models.ObjectType).filter(models.ObjectType.id == object_type_id).first()
    if not ot:
        raise HTTPException(status_code=404, detail=f"ObjectType '{object_type_id}' not found")
    impls = (
        db.query(IfaceImplementation)
        .filter(IfaceImplementation.object_type_id == object_type_id)
        .all()
    )
    return {
        "object_type_id": object_type_id,
        "implementations": [ImplementationRead.model_validate(i).model_dump() for i in impls],
    }


@router.get("/interfaces/{interface_id}/implementations")
def list_interface_implementations(interface_id: str, db: Session = Depends(get_db)) -> Dict[str, Any]:
    _get_interface(db, interface_id)
    impls = (
        db.query(IfaceImplementation)
        .filter(IfaceImplementation.interface_id == interface_id)
        .all()
    )
    return {
        "interface_id": interface_id,
        "implementations": [ImplementationRead.model_validate(i).model_dump() for i in impls],
    }


# ---------------------------------------------------------------------------
# Conformance check
# ---------------------------------------------------------------------------

@router.post("/interfaces/{interface_id}/check-object-type", response_model=CheckObjectTypeResult)
def check_object_type(
    interface_id: str,
    body: CheckObjectTypeRequest,
    db: Session = Depends(get_db),
):
    _get_interface(db, interface_id)
    ot = db.query(models.ObjectType).filter(models.ObjectType.id == body.object_type_id).first()
    if not ot:
        raise HTTPException(status_code=404, detail=f"ObjectType '{body.object_type_id}' not found")

    flattened, _ = _resolve_properties(db, interface_id)
    resolved_constraints = _resolve_link_constraints(db, interface_id)
    ot_prop_names = set((ot.properties or {}).keys())

    # Use recorded implementation (if any) for mapping-aware conformance.
    impl = (
        db.query(IfaceImplementation)
        .filter(
            IfaceImplementation.object_type_id == body.object_type_id,
            IfaceImplementation.interface_id == interface_id,
        )
        .first()
    )
    prop_mappings = (impl.property_mappings if impl else {}) or {}
    link_mappings = (impl.link_mappings if impl else {}) or {}

    missing_properties: List[str] = []
    for prop_name, spec in flattened.items():
        if not spec.get("required", False):
            continue
        if prop_name in prop_mappings:
            # mapping recorded -> target property must exist
            if prop_mappings[prop_name] not in ot_prop_names:
                missing_properties.append(prop_name)
        else:
            # no recorded mapping -> fall back to raw property-name presence
            if prop_name not in ot_prop_names:
                missing_properties.append(prop_name)

    missing_link_constraints: List[str] = []
    for api_name, constraint in resolved_constraints.items():
        if not constraint.required:
            continue
        mapped_lt = link_mappings.get(api_name)
        if not mapped_lt:
            missing_link_constraints.append(api_name)
            continue
        lt = db.query(models.LinkType).filter(models.LinkType.id == mapped_lt).first()
        if not lt or lt.source_object_type_id != body.object_type_id:
            missing_link_constraints.append(api_name)
            continue
        if constraint.target_kind == "object_type" and lt.target_object_type_id != constraint.target_id:
            missing_link_constraints.append(api_name)

    conforms = not missing_properties and not missing_link_constraints
    return CheckObjectTypeResult(
        conforms=conforms,
        missing_properties=sorted(missing_properties),
        missing_link_constraints=sorted(missing_link_constraints),
    )


# ---------------------------------------------------------------------------
# Polymorphic query
# ---------------------------------------------------------------------------

@router.post("/interfaces/{interface_id}/query-objects")
def query_objects(
    interface_id: str,
    body: QueryObjectsRequest,
    db: Session = Depends(get_db),
    principal: production_auth.Principal = Depends(production_auth.require_permission("view")),
) -> Dict[str, Any]:
    _get_interface(db, interface_id)
    flattened, _ = _resolve_properties(db, interface_id)
    iface_prop_names = set(flattened.keys())

    # An interface names a capability, not a tenancy scope. Walking its
    # implementers crosses projects by construction, so the object types are
    # filtered to what this principal may read before any instance is touched.
    # Without this the query returned committed instance data from every project
    # in the deployment (GOAL2-006).
    allowed_projects = tenancy.accessible_project_ids(db, principal, "view")
    if body.project_id is not None:
        tenancy.assert_project_permission(db, principal, body.project_id, "view")
        allowed_projects = {body.project_id}

    impls = (
        db.query(IfaceImplementation)
        .filter(IfaceImplementation.interface_id == interface_id)
        .all()
    )
    if allowed_projects is not None:
        readable_type_ids = {
            row.id for row in db.query(models.ObjectType.id, models.ObjectType.project_id)
            .filter(models.ObjectType.project_id.in_(allowed_projects))
            .all()
        } if allowed_projects else set()
        impls = [impl for impl in impls if impl.object_type_id in readable_type_ids]

    object_type_ids_searched: List[str] = []
    results: List[Dict[str, Any]] = []
    seen_object_ids = set()

    filters = body.filters or {}
    # Only consider filter keys that are interface properties.
    active_filters = {k: v for k, v in filters.items() if k in iface_prop_names}

    for impl in impls:
        object_type_ids_searched.append(impl.object_type_id)
        mappings = impl.property_mappings or {}

        instance_query = db.query(models.ObjectInstance).filter(
            models.ObjectInstance.object_type_id == impl.object_type_id
        )
        # Instances carry their own project. An object type readable in one
        # project must not surface rows another project wrote against it.
        if allowed_projects is not None:
            instance_query = instance_query.filter(
                models.ObjectInstance.project_id.in_(allowed_projects)
            )
        instances = instance_query.all()

        for inst in instances:
            inst_props = inst.properties or {}

            # Translate interface filters to this type's mapped property names and apply.
            match = True
            for iface_prop, want in active_filters.items():
                ot_prop = mappings.get(iface_prop, iface_prop)
                if inst_props.get(ot_prop) != want:
                    match = False
                    break
            if not match:
                continue

            if inst.id in seen_object_ids:
                continue
            seen_object_ids.add(inst.id)

            # Normalize result back to interface property names.
            normalized: Dict[str, Any] = {}
            for iface_prop in iface_prop_names:
                ot_prop = mappings.get(iface_prop, iface_prop)
                if ot_prop in inst_props:
                    normalized[iface_prop] = inst_props.get(ot_prop)

            results.append({
                "id": inst.id,
                "object_type_id": inst.object_type_id,
                "interface_properties": normalized,
            })

    if body.limit is not None:
        results = results[: body.limit]

    return {
        "interface_id": interface_id,
        "object_type_ids_searched": object_type_ids_searched,
        "objects": results,
        "count": len(results),
    }


# ---------------------------------------------------------------------------
# Interface actions
# ---------------------------------------------------------------------------

@router.post("/interfaces/{interface_id}/actions", response_model=InterfaceActionRead)
def create_interface_action(
    interface_id: str,
    body: InterfaceActionCreate,
    db: Session = Depends(get_db),
):
    _get_interface(db, interface_id)
    if body.operation not in VALID_OPERATIONS:
        raise HTTPException(status_code=422, detail=f"operation must be one of {sorted(VALID_OPERATIONS)}")

    # CRITICAL doc rule: a `create` interface action MUST declare a parameter_property that is
    # a shared property usable as a primary key across all implementers. Reject (422) if absent
    # or not one of the interface's resolved properties. Modify/delete actions don't need it.
    if body.operation == "create":
        flattened, _ = _resolve_properties(db, interface_id)
        if not body.parameter_property:
            raise HTTPException(
                status_code=422,
                detail="create interface action requires a parameter_property (primary key shared property)",
            )
        if body.parameter_property not in flattened:
            raise HTTPException(
                status_code=422,
                detail=(
                    f"parameter_property '{body.parameter_property}' is not one of the interface's "
                    f"resolved properties {sorted(flattened.keys())}"
                ),
            )

    action_id = body.id or uuid.uuid4().hex
    if db.query(IfaceAction).filter(IfaceAction.id == action_id).first():
        raise HTTPException(status_code=400, detail="IfaceAction already exists")

    row = IfaceAction(
        id=action_id,
        interface_id=interface_id,
        api_name=body.api_name,
        operation=body.operation,
        parameter_property=body.parameter_property,
        created_at=int(time.time()),
    )
    db.add(row)
    db.add(models_action.AuditLog(
        id=uuid.uuid4().hex,
        actor="system",
        event_type="interfaces.action.created",
        subject_type="iface_action",
        subject_id=action_id,
        payload={"interface_id": interface_id, "api_name": body.api_name, "operation": body.operation},
    ))
    db.commit()
    db.refresh(row)
    return row


@router.get("/interfaces/{interface_id}/actions")
def list_interface_actions(interface_id: str, db: Session = Depends(get_db)) -> Dict[str, Any]:
    _get_interface(db, interface_id)
    actions = (
        db.query(IfaceAction)
        .filter(IfaceAction.interface_id == interface_id)
        .all()
    )
    return {
        "interface_id": interface_id,
        "actions": [InterfaceActionRead.model_validate(a).model_dump() for a in actions],
    }

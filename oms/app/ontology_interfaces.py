"""
Foundry INTERFACES (polymorphic shared contracts) and SHARED PROPERTY TYPES.

Tables:
    shared_property_types  - reusable property definitions with base type + constraints
    ontology_interfaces    - named interface contracts that object types can implement
"""

from .database import Base, get_db
from . import models, models_action
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import String, Integer, JSON, Boolean, Float, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, Session
from pydantic import BaseModel, ConfigDict, Field
from typing import Optional, List, Any, Dict
import time, uuid

# ---------------------------------------------------------------------------
# SQLAlchemy models
# ---------------------------------------------------------------------------

def _interface_base_types() -> set:
    """Interfaces must speak the same type language as object types.

    This set was previously seven names of its own, including "geo", which no
    object type can declare -- the ontology vocabulary has geopoint and
    geoshape. An interface therefore could not express a geometry requirement
    that an object type could satisfy, which is why conformance compared
    property names and ignored types entirely.

    The legacy names are retained as aliases so interfaces created under the old
    vocabulary keep validating.
    """
    from .ontology_core import FOUNDRY_BASE_TYPES

    return set(FOUNDRY_BASE_TYPES) | LEGACY_BASE_TYPE_ALIASES.keys()


# Old interface-only names -> the ontology base type they mean.
LEGACY_BASE_TYPE_ALIASES = {"geo": "geoshape"}


def normalize_base_type(base_type: str) -> str:
    """Resolve a legacy interface type name onto the ontology vocabulary."""
    return LEGACY_BASE_TYPE_ALIASES.get(base_type, base_type)


class _ValidBaseTypes(frozenset):
    """Membership is evaluated against the live ontology vocabulary.

    Kept as a set-like object because callers do `x in VALID_BASE_TYPES` and
    `sorted(VALID_BASE_TYPES)`; resolving lazily avoids an import cycle with
    ontology_core at module load.
    """

    def __contains__(self, item):  # type: ignore[override]
        return item in _interface_base_types()

    def __iter__(self):
        return iter(sorted(_interface_base_types()))

    def __len__(self):
        return len(_interface_base_types())


VALID_BASE_TYPES = _ValidBaseTypes()


class SharedPropertyType(Base):
    """Reusable, governed property definition that can be referenced by interfaces."""
    __tablename__ = "shared_property_types"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    display_name: Mapped[str] = mapped_column(String)
    base_type: Mapped[str] = mapped_column(String)  # string/integer/double/boolean/date/timestamp/geo
    description: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    constraints: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[int] = mapped_column(Integer)


class SptApplication(Base):
    """
    Link table tracking applications of a SharedPropertyType onto a specific
    object-type property. When a shared property type is applied, its governed
    metadata (base_type, display_name, description) is written into the target
    ObjectType.properties[property_name] and locked. Detach removes the lock.
    """
    __tablename__ = "spt_applications"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    shared_property_type_id: Mapped[str] = mapped_column(
        String, ForeignKey("shared_property_types.id"), index=True
    )
    object_type_id: Mapped[str] = mapped_column(
        String, ForeignKey("object_types.id"), index=True
    )
    property_name: Mapped[str] = mapped_column(String, index=True)
    locked: Mapped[bool] = mapped_column(Boolean, default=True)
    inherited_metadata: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[int] = mapped_column(Integer)


class OntologyInterface(Base):
    """Polymorphic shared contract that multiple object types can implement."""
    __tablename__ = "ontology_interfaces"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    display_name: Mapped[str] = mapped_column(String)
    description: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    # {prop_name: {base_type: str, required: bool}}
    properties: Mapped[dict] = mapped_column(JSON, default=dict)
    # list of interface ids this interface extends
    extends: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[int] = mapped_column(Integer)
    updated_at: Mapped[int] = mapped_column(Integer)


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------

class SharedPropertyTypeCreate(BaseModel):
    id: Optional[str] = None
    display_name: str
    base_type: str
    description: Optional[str] = None
    constraints: Dict[str, Any] = Field(default_factory=dict)


class SharedPropertyTypeRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    display_name: str
    base_type: str
    description: Optional[str] = None
    constraints: Dict[str, Any]
    created_at: int


class SptApplyRequest(BaseModel):
    object_type_id: str
    property_name: str


class SptApplicationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    shared_property_type_id: str
    object_type_id: str
    property_name: str
    locked: bool
    inherited_metadata: Dict[str, Any]
    created_at: int


class InterfacePropertySpec(BaseModel):
    base_type: str
    required: bool = False


class OntologyInterfaceCreate(BaseModel):
    id: Optional[str] = None
    display_name: str
    description: Optional[str] = None
    properties: Dict[str, InterfacePropertySpec] = Field(default_factory=dict)
    extends: List[str] = Field(default_factory=list)


class OntologyInterfaceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    display_name: str
    description: Optional[str] = None
    properties: Dict[str, Any]
    extends: List[str]
    created_at: int
    updated_at: int


class CheckObjectTypeRequest(BaseModel):
    object_type_id: str


class CheckObjectTypeResponse(BaseModel):
    conforms: bool
    missing: List[str]


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

router = APIRouter(tags=["ontology-interfaces"])


# ---------------------------------------------------------------------------
# Shared Property Types endpoints
# ---------------------------------------------------------------------------

@router.post("/shared-property-types", response_model=SharedPropertyTypeRead)
def create_shared_property_type(
    body: SharedPropertyTypeCreate,
    db: Session = Depends(get_db),
):
    if body.base_type not in VALID_BASE_TYPES:
        raise HTTPException(
            status_code=422,
            detail=f"base_type must be one of {sorted(VALID_BASE_TYPES)}",
        )
    spt_id = body.id or uuid.uuid4().hex
    existing = db.query(SharedPropertyType).filter(SharedPropertyType.id == spt_id).first()
    if existing:
        raise HTTPException(status_code=400, detail="SharedPropertyType already exists")

    row = SharedPropertyType(
        id=spt_id,
        display_name=body.display_name,
        base_type=body.base_type,
        description=body.description,
        constraints=body.constraints,
        created_at=int(time.time()),
    )
    db.add(row)
    db.add(models_action.AuditLog(
        id=uuid.uuid4().hex,
        actor="system",
        event_type="ontology.shared_property_type.created",
        subject_type="shared_property_type",
        subject_id=spt_id,
        payload={"display_name": body.display_name, "base_type": body.base_type},
    ))
    db.commit()
    db.refresh(row)
    return row


@router.get("/shared-property-types", response_model=List[SharedPropertyTypeRead])
def list_shared_property_types(db: Session = Depends(get_db)):
    return db.query(SharedPropertyType).order_by(SharedPropertyType.display_name).all()


# ---------------------------------------------------------------------------
# Shared Property Type INHERITANCE (apply / detach / consumers)
# ---------------------------------------------------------------------------

@router.post(
    "/shared-property-types/{spt_id}/apply",
    response_model=SptApplicationRead,
)
def apply_shared_property_type(
    spt_id: str,
    body: SptApplyRequest,
    db: Session = Depends(get_db),
):
    """
    Link an object-type property to a shared property type. The shared metadata
    (base_type, display_name, description) PROPAGATES into the target
    ObjectType.properties[property_name] and is LOCKED so it tracks the governed
    definition rather than a free-form per-object override.
    """
    spt = db.query(SharedPropertyType).filter(SharedPropertyType.id == spt_id).first()
    if not spt:
        raise HTTPException(status_code=404, detail=f"SharedPropertyType '{spt_id}' not found")

    ot = db.query(models.ObjectType).filter(
        models.ObjectType.id == body.object_type_id
    ).first()
    if not ot:
        raise HTTPException(
            status_code=404,
            detail=f"ObjectType '{body.object_type_id}' not found",
        )

    # Reject re-applying to a property that is already locked by another SPT.
    existing = db.query(SptApplication).filter(
        SptApplication.object_type_id == body.object_type_id,
        SptApplication.property_name == body.property_name,
    ).first()
    if existing and existing.shared_property_type_id != spt_id:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Property '{body.property_name}' is already locked to shared "
                f"property type '{existing.shared_property_type_id}'"
            ),
        )

    inherited = {
        "base_type": spt.base_type,
        "display_name": spt.display_name,
        "description": spt.description,
        "shared_property_type_id": spt.id,
        "locked": True,
    }

    # Propagate the inherited metadata into the object type's property schema.
    # Reassign the whole dict so SQLAlchemy detects the JSON mutation.
    props = dict(ot.properties or {})
    existing_prop = dict(props.get(body.property_name) or {})
    existing_prop.update(inherited)
    props[body.property_name] = existing_prop
    ot.properties = props
    ot.updated_at = int(time.time())

    if existing:
        app_row = existing
        app_row.locked = True
        app_row.inherited_metadata = inherited
    else:
        app_row = SptApplication(
            id=uuid.uuid4().hex,
            shared_property_type_id=spt_id,
            object_type_id=body.object_type_id,
            property_name=body.property_name,
            locked=True,
            inherited_metadata=inherited,
            created_at=int(time.time()),
        )
        db.add(app_row)

    db.add(models_action.AuditLog(
        id=uuid.uuid4().hex,
        actor="system",
        event_type="ontology.shared_property_type.applied",
        subject_type="shared_property_type",
        subject_id=spt_id,
        payload={
            "object_type_id": body.object_type_id,
            "property_name": body.property_name,
            "inherited_metadata": inherited,
        },
    ))
    db.commit()
    db.refresh(app_row)
    return app_row


@router.post("/shared-property-types/{spt_id}/detach")
def detach_shared_property_type(
    spt_id: str,
    body: SptApplyRequest,
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """
    Remove the inheritance link between a shared property type and an object-type
    property. Unlocks the property (clears the lock flag + shared linkage) but
    leaves the materialized metadata in place so the property is not lost.
    """
    spt = db.query(SharedPropertyType).filter(SharedPropertyType.id == spt_id).first()
    if not spt:
        raise HTTPException(status_code=404, detail=f"SharedPropertyType '{spt_id}' not found")

    app_row = db.query(SptApplication).filter(
        SptApplication.shared_property_type_id == spt_id,
        SptApplication.object_type_id == body.object_type_id,
        SptApplication.property_name == body.property_name,
    ).first()
    if not app_row:
        raise HTTPException(
            status_code=404,
            detail=(
                f"No application of shared property type '{spt_id}' found on "
                f"'{body.object_type_id}.{body.property_name}'"
            ),
        )

    ot = db.query(models.ObjectType).filter(
        models.ObjectType.id == body.object_type_id
    ).first()
    if ot:
        props = dict(ot.properties or {})
        prop = props.get(body.property_name)
        if isinstance(prop, dict):
            prop = dict(prop)
            prop["locked"] = False
            prop.pop("shared_property_type_id", None)
            props[body.property_name] = prop
            ot.properties = props
            ot.updated_at = int(time.time())

    db.delete(app_row)
    db.add(models_action.AuditLog(
        id=uuid.uuid4().hex,
        actor="system",
        event_type="ontology.shared_property_type.detached",
        subject_type="shared_property_type",
        subject_id=spt_id,
        payload={
            "object_type_id": body.object_type_id,
            "property_name": body.property_name,
        },
    ))
    db.commit()
    return {
        "detached": True,
        "shared_property_type_id": spt_id,
        "object_type_id": body.object_type_id,
        "property_name": body.property_name,
    }


@router.get(
    "/shared-property-types/{spt_id}/consumers",
    response_model=List[SptApplicationRead],
)
def list_shared_property_type_consumers(
    spt_id: str,
    db: Session = Depends(get_db),
):
    """List every object-type property currently inheriting from this SPT."""
    spt = db.query(SharedPropertyType).filter(SharedPropertyType.id == spt_id).first()
    if not spt:
        raise HTTPException(status_code=404, detail=f"SharedPropertyType '{spt_id}' not found")
    return (
        db.query(SptApplication)
        .filter(SptApplication.shared_property_type_id == spt_id)
        .order_by(SptApplication.created_at)
        .all()
    )


# ---------------------------------------------------------------------------
# Interfaces endpoints
# ---------------------------------------------------------------------------

@router.post("/interfaces", response_model=OntologyInterfaceRead)
def create_interface(
    body: OntologyInterfaceCreate,
    db: Session = Depends(get_db),
):
    iface_id = body.id or uuid.uuid4().hex
    existing = db.query(OntologyInterface).filter(OntologyInterface.id == iface_id).first()
    if existing:
        raise HTTPException(status_code=400, detail="OntologyInterface already exists")

    # Validate extends references
    for parent_id in body.extends:
        if not db.query(OntologyInterface).filter(OntologyInterface.id == parent_id).first():
            raise HTTPException(status_code=404, detail=f"Parent interface '{parent_id}' not found")

    # Validate property base types
    for prop_name, spec in body.properties.items():
        if spec.base_type not in VALID_BASE_TYPES:
            raise HTTPException(
                status_code=422,
                detail=f"Property '{prop_name}' has invalid base_type '{spec.base_type}'",
            )

    now = int(time.time())
    props_dict = {name: spec.model_dump() for name, spec in body.properties.items()}
    row = OntologyInterface(
        id=iface_id,
        display_name=body.display_name,
        description=body.description,
        properties=props_dict,
        extends=body.extends,
        created_at=now,
        updated_at=now,
    )
    db.add(row)
    db.add(models_action.AuditLog(
        id=uuid.uuid4().hex,
        actor="system",
        event_type="ontology.interface.created",
        subject_type="ontology_interface",
        subject_id=iface_id,
        payload={"display_name": body.display_name, "property_count": len(body.properties)},
    ))
    db.commit()
    db.refresh(row)
    return row


@router.get("/interfaces", response_model=List[OntologyInterfaceRead])
def list_interfaces(db: Session = Depends(get_db)):
    return db.query(OntologyInterface).order_by(OntologyInterface.display_name).all()


@router.get("/interfaces/{interface_id}", response_model=OntologyInterfaceRead)
def get_interface(interface_id: str, db: Session = Depends(get_db)):
    row = db.query(OntologyInterface).filter(OntologyInterface.id == interface_id).first()
    if not row:
        raise HTTPException(status_code=404, detail=f"OntologyInterface '{interface_id}' not found")
    return row


@router.get("/interfaces/{interface_id}/implementers")
def list_interface_implementers(
    interface_id: str,
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """Return object_type ids whose 'properties' JSON contains all interface property names."""
    iface = db.query(OntologyInterface).filter(OntologyInterface.id == interface_id).first()
    if not iface:
        raise HTTPException(status_code=404, detail=f"OntologyInterface '{interface_id}' not found")

    required_names = set((iface.properties or {}).keys())

    implementers: List[str] = []
    all_ots = db.query(models.ObjectType).all()
    for ot in all_ots:
        ot_prop_names = set((ot.properties or {}).keys())
        if required_names.issubset(ot_prop_names):
            implementers.append(ot.id)

    return {
        "interface_id": interface_id,
        "required_property_names": sorted(required_names),
        "implementer_object_type_ids": implementers,
    }


@router.post("/interfaces/{interface_id}/check-object-type", response_model=CheckObjectTypeResponse)
def check_object_type_conformance(
    interface_id: str,
    body: CheckObjectTypeRequest,
    db: Session = Depends(get_db),
):
    """Check whether an object type fully satisfies the interface's required properties."""
    iface = db.query(OntologyInterface).filter(OntologyInterface.id == interface_id).first()
    if not iface:
        raise HTTPException(status_code=404, detail=f"OntologyInterface '{interface_id}' not found")

    ot = db.query(models.ObjectType).filter(models.ObjectType.id == body.object_type_id).first()
    if not ot:
        raise HTTPException(status_code=404, detail=f"ObjectType '{body.object_type_id}' not found")

    ot_prop_names = set((ot.properties or {}).keys())
    # Only required properties must be present
    required_names = {
        name
        for name, spec in (iface.properties or {}).items()
        if spec.get("required", False)
    }
    # If no properties are marked required, all property names must be present
    if not required_names:
        required_names = set((iface.properties or {}).keys())

    missing = sorted(required_names - ot_prop_names)
    return CheckObjectTypeResponse(conforms=len(missing) == 0, missing=missing)

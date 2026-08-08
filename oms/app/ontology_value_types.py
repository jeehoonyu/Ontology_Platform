"""
Foundry VALUE TYPES & STRUCTS
Custom typed values with constraint families, validation, and immutable versioning.

Constraint families (validated on apply, per Foundry docs):
    enum / allowed      - static set of allowed values (string/boolean/numeric)
    range (min/max)     - numeric/date/timestamp bounds; for string/array bounds element/char count
    regex               - string pattern match
    length              - string char length / array element count / struct key count
    rid                 - string Resource Identifier format (ri.<service>.<instance>.<type>.<locator>)
    uuid                - string UUID format
    array_uniqueness    - all array elements distinct
    nested              - apply a constraint family to each element of an array
    struct_element      - map a constraint family to a specific struct field by identifier

Versioning (Foundry semantics):
    base_type metadata + constraint definitions are IMMUTABLE within a version.
    Creating a NEW version computes whether the change is BREAKING or NON_BREAKING:
        breaking      = changing base_type, or tightening / adding a constraint
        non_breaking  = loosening / removing a constraint, or metadata-only edits
    Affected consumers are listed so callers can decide to deprecate vs. propagate.

Foundry references:
    https://www.palantir.com/docs/foundry/object-link-types/value-type-constraints
    https://www.palantir.com/docs/foundry/object-link-types/value-types-versions
"""
from .database import Base, get_db
from . import models, models_action
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import String, Integer, JSON, Boolean, Float
from sqlalchemy.orm import Mapped, mapped_column, Session
from pydantic import BaseModel, ConfigDict, Field
from typing import Optional, List, Any, Dict
import time, uuid, re, math

# ---------------------------------------------------------------------------
# SQLAlchemy Model
# ---------------------------------------------------------------------------

class ValueType(Base):
    __tablename__ = "value_types"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    display_name: Mapped[str] = mapped_column(String, nullable=False)
    base_type: Mapped[str] = mapped_column(String, nullable=False)
    # JSON: constraint families, e.g.
    #   {"min": 0, "max": 100, "regex": "...", "allowed": [...], "length": 50,
    #    "rid": true, "uuid": true, "array_uniqueness": true,
    #    "nested": {<constraint family>}, "struct_element": {field: {<family>}}}
    constraints: Mapped[dict] = mapped_column(JSON, default=dict)
    # JSON list of {"name": str, "base_type": str} — populated when base_type == "struct"
    struct_fields: Mapped[list] = mapped_column(JSON, default=list)
    version: Mapped[int] = mapped_column(Integer, default=1)
    description: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    # whether this value type has been deprecated (recommended path for breaking changes)
    deprecated: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[int] = mapped_column(Integer, nullable=False)
    updated_at: Mapped[int] = mapped_column(Integer, nullable=False)


class ValueTypeVersion(Base):
    """
    Immutable, append-only snapshot of a value type at a given version number.
    Each row captures the base_type + constraints + struct_fields at that point
    plus the computed change classification relative to the prior version.
    """
    __tablename__ = "value_type_versions"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    value_type_id: Mapped[str] = mapped_column(String, index=True, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    base_type: Mapped[str] = mapped_column(String, nullable=False)
    constraints: Mapped[dict] = mapped_column(JSON, default=dict)
    struct_fields: Mapped[list] = mapped_column(JSON, default=list)
    description: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    # NON_BREAKING | BREAKING (the very first version is NON_BREAKING)
    change_type: Mapped[str] = mapped_column(String, default="NON_BREAKING")
    # human readable reasons for the classification
    change_reasons: Mapped[list] = mapped_column(JSON, default=list)
    # consumer ids (object types) referencing this value type at creation time
    affected_consumers: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[int] = mapped_column(Integer, nullable=False)


# ---------------------------------------------------------------------------
# Pydantic Schemas
# ---------------------------------------------------------------------------

# Widened accepted base types per Foundry value type docs.
VALID_BASE_TYPES = {
    "string", "integer", "long", "short", "byte",
    "double", "float", "decimal", "boolean",
    "date", "timestamp", "array", "struct", "enum",
}

# Integer-family base types
_INT_TYPES = {"integer", "long", "short", "byte"}
# Floating / decimal numeric base types
_FLOAT_TYPES = {"double", "float", "decimal"}
_NUMERIC_TYPES = _INT_TYPES | _FLOAT_TYPES

# Recognised constraint family keys (used by versioning diff).
CONSTRAINT_FAMILIES = {
    "min", "max", "regex", "length", "allowed",
    "rid", "uuid", "array_uniqueness", "nested", "struct_element",
}

# RID format: ri.<service>.<instance>.<type>.<locator>
_RID_RE = re.compile(r"^ri\.[a-z0-9_-]+\.[a-z0-9_-]*\.[a-z0-9_-]+\.[a-zA-Z0-9_.-]+$")
_UUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)


class StructFieldSchema(BaseModel):
    name: str
    base_type: str


class ValueTypeCreate(BaseModel):
    id: Optional[str] = None
    display_name: str
    base_type: str = Field(..., description="|".join(sorted(VALID_BASE_TYPES)))
    constraints: Optional[Dict[str, Any]] = Field(default_factory=dict)
    struct_fields: Optional[List[StructFieldSchema]] = Field(default_factory=list)
    description: Optional[str] = None
    version: Optional[int] = 1


class ValueTypeRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    display_name: str
    base_type: str
    constraints: Dict[str, Any]
    struct_fields: List[Any]
    version: int
    description: Optional[str] = None
    deprecated: bool = False
    created_at: int
    updated_at: int


class ValidateRequest(BaseModel):
    value: Any


class ValidateResponse(BaseModel):
    valid: bool
    errors: List[str]


class NewVersionRequest(BaseModel):
    """A new version's constraints / base_type / struct definition + optional metadata."""
    base_type: Optional[str] = None  # defaults to current base_type
    constraints: Optional[Dict[str, Any]] = Field(default_factory=dict)
    struct_fields: Optional[List[StructFieldSchema]] = None
    display_name: Optional[str] = None
    description: Optional[str] = None


class ValueTypeVersionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    value_type_id: str
    version: int
    base_type: str
    constraints: Dict[str, Any]
    struct_fields: List[Any]
    description: Optional[str] = None
    change_type: str
    change_reasons: List[str]
    affected_consumers: List[str]
    created_at: int


class VersionDiffRequest(BaseModel):
    from_version: int
    to_version: int


class VersionDiffResponse(BaseModel):
    value_type_id: str
    from_version: int
    to_version: int
    change_type: str          # NON_BREAKING | BREAKING
    breaking: bool
    reasons: List[str]
    added_constraints: List[str]
    removed_constraints: List[str]
    tightened_constraints: List[str]
    loosened_constraints: List[str]
    base_type_changed: bool
    affected_consumers: List[str]


# ---------------------------------------------------------------------------
# Validation Logic
# ---------------------------------------------------------------------------

def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _apply_constraint_family(
    family: dict, value: Any, base_type: str, where: str = "value"
) -> List[str]:
    """
    Apply a constraint-family dict to a single *value* of *base_type*.
    Used both for the top-level value and recursively (nested array elements,
    struct element constraints). Returns a list of error strings.
    """
    errors: List[str] = []
    if not isinstance(family, dict):
        return errors

    # --- range (min / max) ---
    mn = family.get("min")
    mx = family.get("max")
    if base_type in _NUMERIC_TYPES:
        if _is_number(value):
            if mn is not None and float(value) < float(mn):
                errors.append(f"{where} {value} is less than min {mn}")
            if mx is not None and float(value) > float(mx):
                errors.append(f"{where} {value} is greater than max {mx}")
    elif base_type in ("date", "timestamp"):
        # date/timestamp compared as epoch ints or ISO strings (lexicographic ok for ISO)
        if mn is not None and value < mn:
            errors.append(f"{where} {value} is less than min {mn}")
        if mx is not None and value > mx:
            errors.append(f"{where} {value} is greater than max {mx}")

    # --- length (string char length / array element count) ---
    max_len = family.get("length")
    if max_len is not None and hasattr(value, "__len__"):
        try:
            max_len_i = int(max_len)
            if len(value) > max_len_i:
                errors.append(
                    f"{where} length {len(value)} exceeds max length {max_len_i}"
                )
        except (ValueError, TypeError):
            pass

    # --- regex (string) ---
    pattern = family.get("regex")
    if pattern and isinstance(value, str):
        try:
            if not re.fullmatch(pattern, value):
                errors.append(f"{where} does not match regex '{pattern}'")
        except re.error as exc:
            errors.append(f"Invalid regex pattern '{pattern}': {exc}")

    # --- rid (string) ---
    if family.get("rid") and isinstance(value, str):
        if not _RID_RE.match(value):
            errors.append(f"{where} '{value}' is not a valid RID")

    # --- uuid (string) ---
    if family.get("uuid") and isinstance(value, str):
        if not _UUID_RE.match(value):
            errors.append(f"{where} '{value}' is not a valid UUID")

    # --- enum / allowed (static set) ---
    allowed = family.get("allowed")
    if allowed is not None and value not in allowed:
        errors.append(f"{where} '{value}' not in allowed set {allowed}")

    # --- array_uniqueness ---
    if family.get("array_uniqueness") and isinstance(value, list):
        seen = []
        for el in value:
            if el in seen:
                errors.append(f"{where} contains duplicate element {el!r}")
                break
            seen.append(el)

    return errors


def _validate_value(vt: ValueType, value: Any) -> List[str]:
    """
    Run all applicable constraint checks against *value*.
    Returns a list of error strings; empty list means valid.
    """
    errors: List[str] = []
    base = vt.base_type
    constraints: dict = vt.constraints or {}

    # --- type checks per base family ---
    if base == "string":
        if not isinstance(value, str):
            errors.append(f"Expected string, got {type(value).__name__}")
            return errors
        errors.extend(_apply_constraint_family(constraints, value, base))

    elif base in _INT_TYPES:
        if not _is_int(value):
            errors.append(f"Expected {base}, got {type(value).__name__}")
            return errors
        errors.extend(_apply_constraint_family(constraints, value, base))

    elif base in _FLOAT_TYPES:
        if not _is_number(value):
            errors.append(f"Expected {base} (number), got {type(value).__name__}")
            return errors
        errors.extend(_apply_constraint_family(constraints, value, base))

    elif base == "boolean":
        if not isinstance(value, bool):
            errors.append(f"Expected boolean, got {type(value).__name__}")
            return errors
        errors.extend(_apply_constraint_family(constraints, value, base))

    elif base in ("date", "timestamp"):
        # accept epoch ints or ISO strings
        if not (_is_int(value) or isinstance(value, str)):
            errors.append(f"Expected {base} (epoch int or ISO string), got {type(value).__name__}")
            return errors
        errors.extend(_apply_constraint_family(constraints, value, base))

    elif base == "enum":
        allowed = constraints.get("allowed", [])
        if allowed and value not in allowed:
            errors.append(f"Value '{value}' not in allowed set {allowed}")

    elif base == "array":
        if not isinstance(value, list):
            errors.append(f"Expected array/list, got {type(value).__name__}")
            return errors
        # top-level array constraints: length, range (element count), uniqueness
        if constraints.get("min") is not None and len(value) < int(constraints["min"]):
            errors.append(f"Array has {len(value)} elements, fewer than min {constraints['min']}")
        if constraints.get("max") is not None and len(value) > int(constraints["max"]):
            errors.append(f"Array has {len(value)} elements, exceeds max {constraints['max']}")
        errors.extend(_apply_constraint_family(
            {k: v for k, v in constraints.items() if k in ("length", "array_uniqueness", "allowed")},
            value, base,
        ))
        # nested constraint: applied to each element
        nested = constraints.get("nested")
        if isinstance(nested, dict) and nested:
            el_type = nested.get("base_type", "string")
            for i, el in enumerate(value):
                errors.extend(_apply_constraint_family(nested, el, el_type, where=f"element[{i}]"))

    elif base == "struct":
        if not isinstance(value, dict):
            errors.append(f"Expected object/dict for struct, got {type(value).__name__}")
            return errors
        fields: list = vt.struct_fields or []
        struct_element = constraints.get("struct_element") or {}
        for field_def in fields:
            fname = field_def.get("name") if isinstance(field_def, dict) else getattr(field_def, "name", None)
            ftype = field_def.get("base_type") if isinstance(field_def, dict) else getattr(field_def, "base_type", None)
            if fname is None:
                continue
            if fname not in value:
                errors.append(f"Missing required struct field '{fname}'")
                continue
            fval = value[fname]
            # shallow type check per field
            if ftype == "string" and not isinstance(fval, str):
                errors.append(f"Struct field '{fname}' expected string, got {type(fval).__name__}")
            elif ftype in _INT_TYPES and not _is_int(fval):
                errors.append(f"Struct field '{fname}' expected {ftype}, got {type(fval).__name__}")
            elif ftype in _FLOAT_TYPES and not _is_number(fval):
                errors.append(f"Struct field '{fname}' expected {ftype}, got {type(fval).__name__}")
            elif ftype == "boolean" and not isinstance(fval, bool):
                errors.append(f"Struct field '{fname}' expected boolean, got {type(fval).__name__}")
            # struct_element constraint family for this field
            family = struct_element.get(fname)
            if isinstance(family, dict) and family:
                errors.extend(_apply_constraint_family(
                    family, fval, ftype or "string", where=f"struct field '{fname}'"
                ))

        # struct key count length constraint
        max_len = constraints.get("length")
        if max_len is not None:
            try:
                max_len = int(max_len)
                if len(value) > max_len:
                    errors.append(f"Struct has {len(value)} keys, exceeds max {max_len}")
            except (ValueError, TypeError):
                pass

    else:
        errors.append(f"Unknown base_type '{base}'")

    # generic "allowed" check (for primitive scalars not already handled above)
    if base not in ("enum", "struct", "array") and base not in _NUMERIC_TYPES \
            and base not in ("string", "date", "timestamp"):
        allowed = constraints.get("allowed")
        if allowed is not None and value not in allowed:
            errors.append(f"Value '{value}' not in allowed set {allowed}")

    return errors


# ---------------------------------------------------------------------------
# Versioning helpers
# ---------------------------------------------------------------------------

def _find_consumers(db: Session, value_type_id: str) -> List[str]:
    """
    Object types are consumers when any property references this value type.
    Property specs may carry a 'value_type' / 'value_type_id' key.
    """
    consumers: List[str] = []
    for ot in db.query(models.ObjectType).all():
        props = ot.properties or {}
        for _pname, spec in props.items():
            if not isinstance(spec, dict):
                continue
            ref = spec.get("value_type") or spec.get("value_type_id")
            if ref == value_type_id:
                consumers.append(ot.id)
                break
    return sorted(set(consumers))


def _constraint_is_tighter(key: str, old: Any, new: Any) -> bool:
    """
    True when the new constraint value is strictly MORE restrictive than old
    (i.e. some previously-valid value would now be rejected).
    """
    if key == "min":
        # raising a min lower bound tightens
        return float(new) > float(old)
    if key == "max":
        # lowering a max upper bound tightens
        return float(new) < float(old)
    if key == "length":
        # shrinking allowed length tightens
        try:
            return int(new) < int(old)
        except (ValueError, TypeError):
            return new != old
    if key == "allowed":
        old_set, new_set = set(old or []), set(new or [])
        # removing any allowed value tightens (fewer values accepted)
        return not old_set.issubset(new_set)
    if key in ("regex", "rid", "uuid", "array_uniqueness", "nested", "struct_element"):
        # any change to these pattern/format/structural constraints is treated as tightening
        return old != new
    return old != new


def _classify_change(old: dict, new: dict) -> dict:
    """
    Compare two value-type definitions {base_type, constraints} and classify the
    change as BREAKING or NON_BREAKING with structured detail.
    """
    reasons: List[str] = []
    added: List[str] = []
    removed: List[str] = []
    tightened: List[str] = []
    loosened: List[str] = []

    old_bt = old.get("base_type")
    new_bt = new.get("base_type")
    base_type_changed = old_bt != new_bt
    if base_type_changed:
        reasons.append(f"base_type changed from '{old_bt}' to '{new_bt}'")

    old_c = old.get("constraints") or {}
    new_c = new.get("constraints") or {}
    all_keys = set(old_c) | set(new_c)
    for key in sorted(all_keys):
        if key not in CONSTRAINT_FAMILIES:
            continue
        in_old = key in old_c and old_c[key] not in (None, False)
        in_new = key in new_c and new_c[key] not in (None, False)
        if in_new and not in_old:
            added.append(key)
            reasons.append(f"added constraint '{key}'")
        elif in_old and not in_new:
            removed.append(key)
            reasons.append(f"removed constraint '{key}'")
        elif in_old and in_new and old_c[key] != new_c[key]:
            try:
                tighter = _constraint_is_tighter(key, old_c[key], new_c[key])
            except (ValueError, TypeError):
                tighter = True
            if tighter:
                tightened.append(key)
                reasons.append(f"tightened constraint '{key}'")
            else:
                loosened.append(key)
                reasons.append(f"loosened constraint '{key}'")

    # breaking = base type change OR any added/tightened constraint
    breaking = base_type_changed or bool(added) or bool(tightened)
    change_type = "BREAKING" if breaking else "NON_BREAKING"
    if not reasons:
        reasons.append("metadata-only change")

    return {
        "change_type": change_type,
        "breaking": breaking,
        "reasons": reasons,
        "added_constraints": added,
        "removed_constraints": removed,
        "tightened_constraints": tightened,
        "loosened_constraints": loosened,
        "base_type_changed": base_type_changed,
    }


# ---------------------------------------------------------------------------
# Router & Endpoints
# ---------------------------------------------------------------------------

router = APIRouter(tags=["value_types"])


@router.post("/value-types", response_model=ValueTypeRead, status_code=201)
def create_value_type(body: ValueTypeCreate, db: Session = Depends(get_db)):
    """Create a new value type definition (records version 1)."""
    if body.base_type not in VALID_BASE_TYPES:
        raise HTTPException(
            status_code=422,
            detail=f"base_type must be one of {sorted(VALID_BASE_TYPES)}",
        )

    vt_id = body.id or uuid.uuid4().hex
    existing = db.query(ValueType).filter(ValueType.id == vt_id).first()
    if existing:
        raise HTTPException(status_code=400, detail=f"ValueType '{vt_id}' already exists")

    now = int(time.time())
    struct_fields_data = (
        [f.model_dump() for f in body.struct_fields] if body.struct_fields else []
    )
    db_vt = ValueType(
        id=vt_id,
        display_name=body.display_name,
        base_type=body.base_type,
        constraints=body.constraints or {},
        struct_fields=struct_fields_data,
        version=body.version or 1,
        description=body.description,
        deprecated=False,
        created_at=now,
        updated_at=now,
    )
    db.add(db_vt)
    # record immutable version-1 snapshot
    db.add(ValueTypeVersion(
        id=uuid.uuid4().hex,
        value_type_id=vt_id,
        version=db_vt.version,
        base_type=body.base_type,
        constraints=body.constraints or {},
        struct_fields=struct_fields_data,
        description=body.description,
        change_type="NON_BREAKING",
        change_reasons=["initial version"],
        affected_consumers=[],
        created_at=now,
    ))
    db.add(
        models_action.AuditLog(
            id=uuid.uuid4().hex,
            actor="system",
            event_type="value_type.created",
            subject_type="value_type",
            subject_id=vt_id,
            payload={"display_name": body.display_name, "base_type": body.base_type},
        )
    )
    db.commit()
    db.refresh(db_vt)
    return db_vt


@router.get("/value-types", response_model=List[ValueTypeRead])
def list_value_types(db: Session = Depends(get_db)):
    """List all value type definitions."""
    return db.query(ValueType).order_by(ValueType.display_name).all()


@router.get("/value-types/{value_type_id}", response_model=ValueTypeRead)
def get_value_type(value_type_id: str, db: Session = Depends(get_db)):
    """Retrieve a single value type by ID."""
    vt = db.query(ValueType).filter(ValueType.id == value_type_id).first()
    if not vt:
        raise HTTPException(status_code=404, detail=f"ValueType '{value_type_id}' not found")
    return vt


@router.post("/value-types/{value_type_id}/validate", response_model=ValidateResponse)
def validate_value(
    value_type_id: str,
    body: ValidateRequest,
    db: Session = Depends(get_db),
):
    """
    Validate an arbitrary value against a value type's constraint families.
    Returns {valid: bool, errors: [...]}.
    """
    vt = db.query(ValueType).filter(ValueType.id == value_type_id).first()
    if not vt:
        raise HTTPException(status_code=404, detail=f"ValueType '{value_type_id}' not found")

    errors = _validate_value(vt, body.value)
    return ValidateResponse(valid=len(errors) == 0, errors=errors)


# ---------------------------------------------------------------------------
# Immutable versioning endpoints
# ---------------------------------------------------------------------------

@router.post("/value-types/{value_type_id}/versions", response_model=ValueTypeVersionRead, status_code=201)
def create_value_type_version(
    value_type_id: str,
    body: NewVersionRequest,
    db: Session = Depends(get_db),
):
    """
    Create a new IMMUTABLE version of a value type.

    Computes BREAKING vs NON_BREAKING against the current version and lists
    affected consumers. The live ValueType row is updated to point at the new
    version (its base_type metadata + constraints are otherwise immutable per
    Foundry semantics: prior version snapshots are never mutated).
    """
    vt = db.query(ValueType).filter(ValueType.id == value_type_id).first()
    if not vt:
        raise HTTPException(status_code=404, detail=f"ValueType '{value_type_id}' not found")

    new_base = body.base_type or vt.base_type
    if new_base not in VALID_BASE_TYPES:
        raise HTTPException(
            status_code=422,
            detail=f"base_type must be one of {sorted(VALID_BASE_TYPES)}",
        )
    new_constraints = body.constraints if body.constraints is not None else {}
    if body.struct_fields is not None:
        new_struct = [f.model_dump() for f in body.struct_fields]
    else:
        new_struct = vt.struct_fields or []

    old_def = {"base_type": vt.base_type, "constraints": vt.constraints or {}}
    new_def = {"base_type": new_base, "constraints": new_constraints or {}}
    classification = _classify_change(old_def, new_def)

    consumers = _find_consumers(db, value_type_id)
    new_version_num = (vt.version or 1) + 1
    now = int(time.time())

    snapshot = ValueTypeVersion(
        id=uuid.uuid4().hex,
        value_type_id=value_type_id,
        version=new_version_num,
        base_type=new_base,
        constraints=new_constraints or {},
        struct_fields=new_struct,
        description=body.description if body.description is not None else vt.description,
        change_type=classification["change_type"],
        change_reasons=classification["reasons"],
        affected_consumers=consumers,
        created_at=now,
    )
    db.add(snapshot)

    # advance the live row to the new version
    vt.version = new_version_num
    vt.base_type = new_base
    vt.constraints = new_constraints or {}
    vt.struct_fields = new_struct
    if body.display_name is not None:
        vt.display_name = body.display_name
    if body.description is not None:
        vt.description = body.description
    vt.updated_at = now

    db.add(models_action.AuditLog(
        id=uuid.uuid4().hex,
        actor="system",
        event_type="value_type.version_created",
        subject_type="value_type",
        subject_id=value_type_id,
        payload={
            "version": new_version_num,
            "change_type": classification["change_type"],
            "affected_consumers": consumers,
            "reasons": classification["reasons"],
        },
    ))
    db.commit()
    db.refresh(snapshot)
    return snapshot


@router.get("/value-types/{value_type_id}/versions", response_model=List[ValueTypeVersionRead])
def list_value_type_versions(value_type_id: str, db: Session = Depends(get_db)):
    """List all immutable version snapshots of a value type, newest first."""
    vt = db.query(ValueType).filter(ValueType.id == value_type_id).first()
    if not vt:
        raise HTTPException(status_code=404, detail=f"ValueType '{value_type_id}' not found")
    return (
        db.query(ValueTypeVersion)
        .filter(ValueTypeVersion.value_type_id == value_type_id)
        .order_by(ValueTypeVersion.version.desc())
        .all()
    )


@router.post("/value-types/{value_type_id}/version-diff", response_model=VersionDiffResponse)
def diff_value_type_versions(
    value_type_id: str,
    body: VersionDiffRequest,
    db: Session = Depends(get_db),
):
    """
    Diff two stored versions of a value type and classify the change between
    them as BREAKING or NON_BREAKING, listing affected consumers.
    """
    vt = db.query(ValueType).filter(ValueType.id == value_type_id).first()
    if not vt:
        raise HTTPException(status_code=404, detail=f"ValueType '{value_type_id}' not found")

    def _load(v: int) -> ValueTypeVersion:
        row = (
            db.query(ValueTypeVersion)
            .filter(
                ValueTypeVersion.value_type_id == value_type_id,
                ValueTypeVersion.version == v,
            )
            .first()
        )
        if not row:
            raise HTTPException(status_code=404, detail=f"Version {v} not found for '{value_type_id}'")
        return row

    from_v = _load(body.from_version)
    to_v = _load(body.to_version)

    classification = _classify_change(
        {"base_type": from_v.base_type, "constraints": from_v.constraints or {}},
        {"base_type": to_v.base_type, "constraints": to_v.constraints or {}},
    )

    return VersionDiffResponse(
        value_type_id=value_type_id,
        from_version=body.from_version,
        to_version=body.to_version,
        change_type=classification["change_type"],
        breaking=classification["breaking"],
        reasons=classification["reasons"],
        added_constraints=classification["added_constraints"],
        removed_constraints=classification["removed_constraints"],
        tightened_constraints=classification["tightened_constraints"],
        loosened_constraints=classification["loosened_constraints"],
        base_type_changed=classification["base_type_changed"],
        affected_consumers=_find_consumers(db, value_type_id),
    )

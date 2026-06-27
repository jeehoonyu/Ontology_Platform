"""
Faithful, documented Ontology-core semantics (pass 1 of the deep "implement as
written" work). This module adds the documented behaviors that the base platform
did not yet enforce:

  * the Foundry property **base-type catalog** (object-link-types/base-types),
  * **API-name rules** (PascalCase for object types, camelCase for properties),
  * **object-type profiles** — primary key, title key, per-property status and
    base type, and display metadata (action-types & object-types docs), and
  * a faithful **Action engine** — typed parameter validation, **submission
    criteria**, the full **mutation set** (create / modify / delete object,
    add / remove link), and **side effects** (notifications, webhooks).

It is additive: it augments the existing `object_types` / `action_types` tables
via a 1:1 profile table and new endpoints, leaving the working endpoints and
their tests untouched. Link cardinality is already enforced by the core
`/links` endpoint, so it is not duplicated here. Everything is deterministic and
local.
"""
import re
import time
import uuid
from typing import Optional, List, Any, Dict

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import String, Integer, JSON
from sqlalchemy.orm import Mapped, mapped_column, Session
from pydantic import BaseModel, ConfigDict, Field

from .database import Base, get_db
from . import models, models_action
from . import runtime

router = APIRouter(tags=["ontology_core"])


def _now() -> int:
    return int(time.time())


def _audit(db: Session, actor: str, event_type: str, subject_type: str, subject_id: str, payload: dict):
    db.add(models_action.AuditLog(
        id=uuid.uuid4().hex, actor=actor or "system", event_type=event_type,
        subject_type=subject_type, subject_id=subject_id, payload=payload,
    ))


# ---------------------------------------------------------------------------
# Documented Foundry base-type catalog (object-link-types/base-types)
# ---------------------------------------------------------------------------
FOUNDRY_BASE_TYPES: Dict[str, Dict[str, Any]] = {
    "boolean":         {"category": "primitive", "json": "boolean"},
    "byte":            {"category": "numeric",   "json": "integer"},
    "short":           {"category": "numeric",   "json": "integer"},
    "integer":         {"category": "numeric",   "json": "integer"},
    "long":            {"category": "numeric",   "json": "integer"},
    "float":           {"category": "numeric",   "json": "number"},
    "double":          {"category": "numeric",   "json": "number"},
    "decimal":         {"category": "numeric",   "json": "number/string"},
    "string":          {"category": "text",      "json": "string"},
    "date":            {"category": "temporal",  "json": "string (ISO date)"},
    "timestamp":       {"category": "temporal",  "json": "string (ISO datetime)"},
    "geopoint":        {"category": "spatial",   "json": "GeoJSON Point / geohash"},
    "geoshape":        {"category": "spatial",   "json": "GeoJSON geometry"},
    "array":           {"category": "collection","json": "array"},
    "struct":          {"category": "collection","json": "object"},
    "attachment":      {"category": "reference", "json": "attachment ref"},
    "mediaReference":  {"category": "reference", "json": "media reference"},
    "timeSeries":      {"category": "reference", "json": "time series ref"},
    "marking":         {"category": "security",  "json": "marking id"},
    "vector":          {"category": "ml",        "json": "float array"},
    "cipherText":      {"category": "security",  "json": "encrypted string"},
}

# Documented guidance: primary keys must be stable & high-cardinality.
PK_ALLOWED = {"string", "integer", "long", "short", "byte", "decimal", "date", "timestamp", "boolean"}
PROPERTY_STATUSES = {"active", "experimental", "deprecated"}

PASCAL_RE = re.compile(r"^[A-Z][A-Za-z0-9]{0,99}$")   # object type API names
CAMEL_RE = re.compile(r"^[a-z][A-Za-z0-9]{0,99}$")    # property API names


def validate_api_name(name: str, style: str) -> List[str]:
    errors: List[str] = []
    if not name or not (1 <= len(name) <= 100):
        errors.append(f"API name '{name}' must be 1-100 characters")
        return errors
    if style == "pascal" and not PASCAL_RE.match(name):
        errors.append(f"Object-type API name '{name}' must be PascalCase, alphanumeric, 1-100 chars")
    if style == "camel" and not CAMEL_RE.match(name):
        errors.append(f"Property API name '{name}' must be camelCase, alphanumeric, 1-100 chars")
    return errors


# ---------------------------------------------------------------------------
# ORM model — object-type profile (augments object_types 1:1)
# ---------------------------------------------------------------------------
class ObjectTypeProfile(Base):
    __tablename__ = "object_type_profiles"
    object_type_id: Mapped[str] = mapped_column(String, primary_key=True, index=True)
    api_name: Mapped[str] = mapped_column(String)
    primary_key: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    title_key: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    icon: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    color: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    plural_name: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    groups: Mapped[list] = mapped_column(JSON, default=list)
    # name -> {base_type, status, required, shared_property_type_id, render_hint, description}
    properties: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[int] = mapped_column(Integer)
    updated_at: Mapped[int] = mapped_column(Integer)


# ---------------------------------------------------------------------------
# ORM model — queryable action log (Act/act_ prefix) for undo + auditing
# ---------------------------------------------------------------------------
class ActionLog(Base):
    """
    Append-only, queryable record of one action-type execution. Captures who ran
    it, with which parameters, which objects were mutated, and — for property
    modifications — the BEFORE values so the execution can be reversed (undo).
    """
    __tablename__ = "act_action_log"
    id: Mapped[str] = mapped_column(String, primary_key=True, index=True)
    action_type_id: Mapped[str] = mapped_column(String, index=True)
    actor: Mapped[str] = mapped_column(String, default="system", index=True)
    parameters: Mapped[dict] = mapped_column(JSON, default=dict)
    mutated_object_ids: Mapped[list] = mapped_column(JSON, default=list)
    # per-object before/after snapshots: [{object_id, before, after, op}]
    reversal: Mapped[list] = mapped_column(JSON, default=list)
    function_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    undone: Mapped[bool] = mapped_column(Integer, default=0)  # 0/1 flag (sqlite-friendly)
    created_at: Mapped[int] = mapped_column(Integer, index=True)


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------
class PropertySpec(BaseModel):
    base_type: str
    status: str = "active"
    required: bool = False
    shared_property_type_id: Optional[str] = None
    render_hint: Optional[str] = None
    description: Optional[str] = None


class ProfileUpsert(BaseModel):
    api_name: str
    primary_key: Optional[str] = None
    title_key: Optional[str] = None
    icon: Optional[str] = None
    color: Optional[str] = None
    plural_name: Optional[str] = None
    groups: List[str] = Field(default_factory=list)
    properties: Dict[str, PropertySpec] = Field(default_factory=dict)


class ProfileRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    object_type_id: str
    api_name: str
    primary_key: Optional[str] = None
    title_key: Optional[str] = None
    icon: Optional[str] = None
    color: Optional[str] = None
    plural_name: Optional[str] = None
    groups: List[str]
    properties: Dict[str, Any]
    created_at: int
    updated_at: int


class ApiNameRequest(BaseModel):
    name: str
    style: str = "pascal"  # pascal | camel


class ActionExecuteRequest(BaseModel):
    parameters: Dict[str, Any] = Field(default_factory=dict)
    actor: str = "system"
    dry_run: bool = False


class ObjectTypeUpdate(BaseModel):
    display_name: Optional[str] = None
    description: Optional[str] = None
    properties: Optional[Dict[str, Any]] = None


class ActionLogRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    action_type_id: str
    actor: str
    parameters: Dict[str, Any]
    mutated_object_ids: List[str]
    reversal: List[Any]
    function_id: Optional[str] = None
    undone: bool
    created_at: int


class ValidatePrimaryKeyRequest(BaseModel):
    properties: Dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Base-type catalog + API name endpoints
# ---------------------------------------------------------------------------
@router.get("/ontology/base-types")
def list_base_types():
    return {
        "base_types": [{"name": k, **v} for k, v in FOUNDRY_BASE_TYPES.items()],
        "primary_key_allowed": sorted(PK_ALLOWED),
        "property_statuses": sorted(PROPERTY_STATUSES),
        "api_name_rules": {"object_type": "PascalCase 1-100 alnum", "property": "camelCase 1-100 alnum"},
    }


@router.post("/ontology/validate-api-name")
def validate_api_name_endpoint(body: ApiNameRequest):
    style = "camel" if body.style == "camel" else "pascal"
    errors = validate_api_name(body.name, style)
    return {"name": body.name, "style": style, "valid": not errors, "errors": errors}


# ---------------------------------------------------------------------------
# Object-type profiles
# ---------------------------------------------------------------------------
@router.put("/ontology/object-types/{object_type_id}/profile", response_model=ProfileRead)
def upsert_profile(object_type_id: str, body: ProfileUpsert, db: Session = Depends(get_db)):
    obj_type = db.get(models.ObjectType, object_type_id)
    if not obj_type:
        raise HTTPException(status_code=404, detail=f"ObjectType '{object_type_id}' not found")

    errors: List[str] = []
    # API names
    errors += validate_api_name(body.api_name, "pascal")
    for pname, spec in body.properties.items():
        errors += validate_api_name(pname, "camel")
        if spec.base_type not in FOUNDRY_BASE_TYPES:
            errors.append(f"Property '{pname}' has unknown base type '{spec.base_type}'")
        if spec.status not in PROPERTY_STATUSES:
            errors.append(f"Property '{pname}' has invalid status '{spec.status}'")
    # Primary key
    if body.primary_key is not None:
        if body.primary_key not in body.properties:
            errors.append(f"primary_key '{body.primary_key}' is not a declared property")
        else:
            pk_type = body.properties[body.primary_key].base_type
            if pk_type not in PK_ALLOWED:
                errors.append(f"primary_key '{body.primary_key}' base type '{pk_type}' is not allowed for keys")
    # Title key
    if body.title_key is not None and body.title_key not in body.properties:
        errors.append(f"title_key '{body.title_key}' is not a declared property")

    if errors:
        raise HTTPException(status_code=422, detail=errors)

    now = _now()
    profile = db.get(ObjectTypeProfile, object_type_id)
    props = {k: v.model_dump() for k, v in body.properties.items()}
    if profile:
        profile.api_name = body.api_name
        profile.primary_key = body.primary_key
        profile.title_key = body.title_key
        profile.icon = body.icon
        profile.color = body.color
        profile.plural_name = body.plural_name
        profile.groups = body.groups
        profile.properties = props
        profile.updated_at = now
    else:
        profile = ObjectTypeProfile(
            object_type_id=object_type_id, api_name=body.api_name, primary_key=body.primary_key,
            title_key=body.title_key, icon=body.icon, color=body.color, plural_name=body.plural_name,
            groups=body.groups, properties=props, created_at=now, updated_at=now,
        )
        db.add(profile)
    _audit(db, "system", "ontology.object_type.profile_set", "object_type", object_type_id,
           {"api_name": body.api_name, "primary_key": body.primary_key})
    db.commit(); db.refresh(profile)
    return profile


@router.get("/ontology/object-types/{object_type_id}/profile", response_model=ProfileRead)
def get_profile(object_type_id: str, db: Session = Depends(get_db)):
    profile = db.get(ObjectTypeProfile, object_type_id)
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not set for this object type")
    return profile


@router.get("/ontology/object-types/{object_type_id}/full")
def get_full_object_type(object_type_id: str, db: Session = Depends(get_db)):
    obj_type = db.get(models.ObjectType, object_type_id)
    if not obj_type:
        raise HTTPException(status_code=404, detail=f"ObjectType '{object_type_id}' not found")
    profile = db.get(ObjectTypeProfile, object_type_id)
    return {
        "id": obj_type.id,
        "display_name": obj_type.display_name,
        "description": obj_type.description,
        "base_properties": obj_type.properties,
        "profile": ProfileRead.model_validate(profile).model_dump() if profile else None,
    }


# ---------------------------------------------------------------------------
# Faithful Action engine: params + submission criteria + mutations + effects
# ---------------------------------------------------------------------------
def _resolve(expr: Any, parameters: Dict[str, Any]) -> Any:
    """Resolve a mutation expression against action parameters."""
    if isinstance(expr, str) and expr.startswith("$"):
        return parameters.get(expr[1:])
    if isinstance(expr, dict):
        if "from" in expr:
            return parameters.get(expr["from"])
        if "value" in expr:
            return expr["value"]
        if "template" in expr:
            try:
                return str(expr["template"]).format(**parameters)
            except Exception:
                return expr["template"]
    return expr


def _param_type_ok(value: Any, declared: Optional[str]) -> bool:
    if declared in (None, "any", "objectReference", "string"):
        return value is None or isinstance(value, str) if declared == "string" else True
    if declared in ("integer", "long", "short", "byte"):
        return isinstance(value, int) and not isinstance(value, bool)
    if declared in ("double", "float", "decimal"):
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if declared == "boolean":
        return isinstance(value, bool)
    if declared == "array":
        return isinstance(value, list)
    if declared in ("struct", "object"):
        return isinstance(value, dict)
    return True


def _cmp(op: str, left: Any, right: Any) -> bool:
    try:
        if op in ("eq", "=="):
            return left == right
        if op in ("ne", "!="):
            return left != right
        if op == "gt":
            return left > right
        if op == "gte":
            return left >= right
        if op == "lt":
            return left < right
        if op == "lte":
            return left <= right
        if op == "in":
            return left in (right or [])
        if op == "not_null":
            return left is not None
        if op == "truthy":
            return bool(left)
    except TypeError:
        return False
    return False


def _validate_params(action: models.ActionType, parameters: Dict[str, Any], db: Session) -> List[str]:
    errors: List[str] = []
    schema = action.parameters or {}
    for pname, definition in schema.items():
        decl = definition if isinstance(definition, dict) else {"type": definition}
        required = decl.get("required", not isinstance(definition, dict))
        if pname not in parameters or parameters.get(pname) is None:
            if required:
                errors.append(f"Missing required parameter '{pname}'")
            continue
        value = parameters[pname]
        dtype = decl.get("type")
        if not _param_type_ok(value, dtype):
            errors.append(f"Parameter '{pname}' expected {dtype}, got {type(value).__name__}")
        if "allowed_values" in decl and value not in decl["allowed_values"]:
            errors.append(f"Parameter '{pname}' value '{value}' not in allowed_values")
        if "min" in decl and isinstance(value, (int, float)) and value < decl["min"]:
            errors.append(f"Parameter '{pname}' below min {decl['min']}")
        if "max" in decl and isinstance(value, (int, float)) and value > decl["max"]:
            errors.append(f"Parameter '{pname}' above max {decl['max']}")
        # object reference existence
        if dtype == "objectReference" and isinstance(value, str):
            if not db.get(models.ObjectInstance, value):
                errors.append(f"Parameter '{pname}' references missing object '{value}'")
    return errors


def _evaluate_submission_criteria(criteria: List[dict], parameters: Dict[str, Any], db: Session) -> List[str]:
    failures: List[str] = []
    for crit in criteria or []:
        op = crit.get("op", "truthy")
        if "parameter" in crit:
            left = parameters.get(crit["parameter"])
        elif "object_param" in crit:
            obj_id = parameters.get(crit["object_param"])
            obj = db.get(models.ObjectInstance, obj_id) if obj_id else None
            left = (obj.properties or {}).get(crit.get("property")) if obj else None
        else:
            left = None
        if not _cmp(op, left, crit.get("value")):
            failures.append(crit.get("message", f"Submission criterion failed: {crit}"))
    return failures


def _normalize_function_edit(edit: Any, params: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Coerce a function-returned edit (or a proposed_action from a LogicFunction
    block) into a mutation dict understood by the mutation set below. Supported
    shapes:
      * {"op": "modify-object"|"create-object"|"delete-object"|"add-link"|
         "remove-link", ...}  (already-normalized mutation)
      * {"action_type_id": ..., "parameters": {...}}  (a proposed action — the
        referenced ActionType's own mutations are expanded by the caller)
    """
    if not isinstance(edit, dict):
        return None
    if edit.get("op"):
        return edit
    return None


def _run_function_backed(action: models.ActionType, function_id: str,
                         params: Dict[str, Any], db: Session) -> List[Dict[str, Any]]:
    """
    Delegate execution to the referenced ontology function (LogicFunction). The
    function runs via runtime.execute_logic_blocks; its proposed_actions (and any
    explicit 'edits' it sets as an output) are collected and expanded into the
    mutation set so the action applies the function's returned edits.
    """
    fn = db.get(models.LogicFunction, function_id)
    if not fn:
        raise HTTPException(status_code=404,
                            detail=f"function_id '{function_id}' references missing LogicFunction")
    try:
        run = runtime.execute_logic_blocks(db, logic_function=fn, inputs=params)
    except Exception as exc:  # surface logic errors as 422
        raise HTTPException(status_code=422, detail={"function_error": str(exc)})

    collected: List[Dict[str, Any]] = []
    # (a) explicit edits emitted as an output named 'edits'
    edits_out = (run.get("outputs") or {}).get("edits")
    if isinstance(edits_out, list):
        for e in edits_out:
            norm = _normalize_function_edit(e, params)
            if norm:
                collected.append(norm)
    # (b) proposed_actions -> expand each referenced action's own mutations
    for proposal in run.get("proposed_actions") or []:
        ref_id = proposal.get("action_type_id")
        ref = db.get(models.ActionType, ref_id) if ref_id else None
        if not ref:
            continue
        ref_params = proposal.get("parameters") or {}
        ref_rules = ref.rules or {}
        for mut in (ref_rules.get("mutations") or ref_rules.get("object_mutations") or []):
            # resolve the referenced action's mutation against the proposal params
            collected.append({k: (_resolve(v, ref_params) if k in
                              ("object_id", "source_object_id", "target_object_id") else v)
                              for k, v in mut.items()})
    return collected


def _apply_mutation_set(mutations: List[Dict[str, Any]], params: Dict[str, Any],
                        action_type_id: str, now: int, db: Session,
                        mutated_objects: List[str], links_changed: List[str],
                        reversal: List[Dict[str, Any]]) -> None:
    """Apply the documented mutation set, capturing before-values for undo."""
    for m in mutations:
        op = m.get("op", "modify-object")
        if op in ("create-object", "modify-object"):
            otype = m.get("object_type_id")
            oid = _resolve(m.get("object_id"), params) or (m.get("object_id_param") and params.get(m["object_id_param"]))
            existing = db.get(models.ObjectInstance, str(oid)) if oid else None
            sets = {k: _resolve(v, params) for k, v in (m.get("set") or {}).items()}
            if existing is None:
                if op == "modify-object" and not m.get("create_if_missing"):
                    raise HTTPException(status_code=404, detail=f"Object '{oid}' not found for modify")
                if not otype:
                    raise HTTPException(status_code=422, detail="create-object requires object_type_id")
                new_id = str(oid) if oid else uuid.uuid4().hex
                inst = models.ObjectInstance(
                    id=new_id, object_type_id=otype, properties=sets, source_asset_id=None,
                    lineage={"created_by_action": action_type_id}, created_at=now, updated_at=now)
                db.add(inst)
                mutated_objects.append(new_id)
                reversal.append({"op": "create-object", "object_id": new_id})
            else:
                before = dict(existing.properties or {})
                existing.properties = {**before, **sets}
                existing.lineage = {**(existing.lineage or {}), "last_action_id": action_type_id}
                existing.updated_at = now
                mutated_objects.append(existing.id)
                # store the prior values for exactly the keys we changed
                reversal.append({"op": "modify-object", "object_id": existing.id,
                                 "before": {k: before.get(k) for k in sets},
                                 "before_present": {k: (k in before) for k in sets}})
        elif op == "delete-object":
            oid = _resolve(m.get("object_id"), params)
            inst = db.get(models.ObjectInstance, str(oid)) if oid else None
            if inst is None:
                raise HTTPException(status_code=404, detail=f"Object '{oid}' not found for delete")
            reversal.append({"op": "delete-object", "object_id": str(oid),
                             "object_type_id": inst.object_type_id,
                             "before": dict(inst.properties or {})})
            db.delete(inst)
            mutated_objects.append(str(oid))
        elif op in ("add-link", "remove-link"):
            ltype = m.get("link_type_id")
            src = _resolve(m.get("source_object_id"), params)
            tgt = _resolve(m.get("target_object_id"), params)
            link_id = f"{ltype}:{src}:{tgt}"
            if op == "add-link":
                if not db.get(models.LinkInstance, link_id):
                    db.add(models.LinkInstance(
                        id=link_id, link_type_id=ltype, source_object_id=str(src),
                        target_object_id=str(tgt), properties={}, created_at=now))
                    reversal.append({"op": "add-link", "link_id": link_id})
                links_changed.append(link_id)
            else:
                link = db.get(models.LinkInstance, link_id)
                if link:
                    reversal.append({"op": "remove-link", "link_id": link_id, "link_type_id": ltype,
                                     "source_object_id": str(src), "target_object_id": str(tgt),
                                     "properties": dict(link.properties or {})})
                    db.delete(link)
                links_changed.append(link_id)
        else:
            raise HTTPException(status_code=422, detail=f"Unknown mutation op '{op}'")


@router.post("/ontology/action-types/{action_type_id}/execute")
def execute_action_faithful(action_type_id: str, body: ActionExecuteRequest, db: Session = Depends(get_db)):
    action = db.get(models.ActionType, action_type_id)
    if not action:
        raise HTTPException(status_code=404, detail=f"ActionType '{action_type_id}' not found")
    rules = action.rules or {}
    params = body.parameters

    # 1) typed parameter validation
    perrors = _validate_params(action, params, db)
    if perrors:
        raise HTTPException(status_code=422, detail={"parameter_errors": perrors})

    # 2) submission criteria
    failures = _evaluate_submission_criteria(rules.get("submission_criteria", []), params, db)
    if failures:
        raise HTTPException(status_code=422, detail={"submission_criteria_failed": failures})

    mutations = rules.get("mutations") or rules.get("object_mutations") or []
    side_effects = rules.get("side_effects", [])
    function_id = rules.get("function_id")

    if body.dry_run:
        return {"action_type_id": action_type_id, "submittable": True,
                "planned_mutations": len(mutations), "planned_side_effects": len(side_effects),
                "function_backed": bool(function_id)}

    mutated_objects: List[str] = []
    links_changed: List[str] = []
    reversal: List[Dict[str, Any]] = []
    now = _now()

    # 3a) FUNCTION-BACKED rule: delegate to the ontology function and apply its
    #     returned edits (in addition to any inline mutations on the action).
    if function_id:
        fn_mutations = _run_function_backed(action, function_id, params, db)
        _apply_mutation_set(fn_mutations, params, action_type_id, now, db,
                            mutated_objects, links_changed, reversal)

    # 3b) inline mutation set
    _apply_mutation_set(mutations, params, action_type_id, now, db,
                        mutated_objects, links_changed, reversal)

    # 4) side effects
    fired = []
    for eff in side_effects:
        etype = eff.get("type")
        if etype == "notification":
            _audit(db, body.actor, "action.notification", "action_type", action_type_id,
                   {"recipient": eff.get("recipient"), "message": _resolve(eff.get("message"), params)})
            fired.append("notification")
        elif etype == "webhook":
            db.add(models_action.OutboxEvent(
                id=uuid.uuid4().hex, action_type_id=action_type_id,
                payload={"url": eff.get("url"), "payload": eff.get("payload", params)},
                status="PENDING", created_at=now))
            fired.append("webhook")

    # 5) queryable action log (Act/act_) + control-plane audit
    log_id = uuid.uuid4().hex
    db.add(ActionLog(
        id=log_id, action_type_id=action_type_id, actor=body.actor or "system",
        parameters=params, mutated_object_ids=mutated_objects, reversal=reversal,
        function_id=function_id, undone=0, created_at=now))
    _audit(db, body.actor, "ontology.action.executed", "action_type", action_type_id,
           {"mutated_objects": mutated_objects, "links_changed": links_changed,
            "side_effects": fired, "action_log_id": log_id})
    db.commit()
    return {
        "action_type_id": action_type_id, "status": "applied",
        "mutated_object_ids": mutated_objects, "links_changed": links_changed,
        "side_effects_fired": fired, "submission": {"submittable": True},
        "action_log_id": log_id, "function_backed": bool(function_id),
    }


# ---------------------------------------------------------------------------
# Queryable ACTION LOG + UNDO
# ---------------------------------------------------------------------------
@router.get("/ontology/action-log", response_model=List[ActionLogRead])
def list_action_log(
    action_type_id: Optional[str] = None,
    actor: Optional[str] = None,
    limit: int = 100,
    db: Session = Depends(get_db),
):
    q = db.query(ActionLog)
    if action_type_id is not None:
        q = q.filter(ActionLog.action_type_id == action_type_id)
    if actor is not None:
        q = q.filter(ActionLog.actor == actor)
    rows = q.order_by(ActionLog.created_at.desc()).limit(max(1, min(int(limit), 1000))).all()
    return rows


@router.get("/ontology/action-log/{log_id}", response_model=ActionLogRead)
def get_action_log(log_id: str, db: Session = Depends(get_db)):
    row = db.get(ActionLog, log_id)
    if not row:
        raise HTTPException(status_code=404, detail=f"ActionLog '{log_id}' not found")
    return row


@router.post("/ontology/action-log/{log_id}/undo")
def undo_action_log(log_id: str, actor: str = "system", db: Session = Depends(get_db)):
    row = db.get(ActionLog, log_id)
    if not row:
        raise HTTPException(status_code=404, detail=f"ActionLog '{log_id}' not found")
    if row.undone:
        raise HTTPException(status_code=409, detail=f"ActionLog '{log_id}' has already been undone")

    now = _now()
    restored: List[str] = []
    # Reverse in LIFO order so dependent edits unwind cleanly.
    for entry in reversed(row.reversal or []):
        op = entry.get("op")
        if op == "modify-object":
            inst = db.get(models.ObjectInstance, entry.get("object_id"))
            if inst is None:
                continue
            props = dict(inst.properties or {})
            before = entry.get("before") or {}
            present = entry.get("before_present") or {}
            for key in before:
                if present.get(key, True):
                    props[key] = before[key]
                else:
                    props.pop(key, None)
            inst.properties = props
            inst.lineage = {**(inst.lineage or {}), "undo_of_action_log": log_id}
            inst.updated_at = now
            restored.append(inst.id)
        elif op == "create-object":
            inst = db.get(models.ObjectInstance, entry.get("object_id"))
            if inst is not None:
                db.delete(inst)
                restored.append(entry.get("object_id"))
        elif op == "delete-object":
            if db.get(models.ObjectInstance, entry.get("object_id")) is None:
                db.add(models.ObjectInstance(
                    id=entry.get("object_id"), object_type_id=entry.get("object_type_id"),
                    properties=dict(entry.get("before") or {}), source_asset_id=None,
                    lineage={"restored_by_undo": log_id}, created_at=now, updated_at=now))
                restored.append(entry.get("object_id"))
        elif op == "add-link":
            link = db.get(models.LinkInstance, entry.get("link_id"))
            if link is not None:
                db.delete(link)
        elif op == "remove-link":
            if db.get(models.LinkInstance, entry.get("link_id")) is None:
                db.add(models.LinkInstance(
                    id=entry.get("link_id"), link_type_id=entry.get("link_type_id"),
                    source_object_id=entry.get("source_object_id"),
                    target_object_id=entry.get("target_object_id"),
                    properties=dict(entry.get("properties") or {}), created_at=now))

    row.undone = 1
    _audit(db, actor, "ontology.action.undone", "action_type", row.action_type_id,
           {"action_log_id": log_id, "restored_object_ids": restored})
    db.commit()
    return {"action_log_id": log_id, "status": "undone",
            "restored_object_ids": restored, "reversed_operations": len(row.reversal or [])}


# ---------------------------------------------------------------------------
# Object-type EDIT / DELETE
# ---------------------------------------------------------------------------
@router.put("/ontology/object-types/{object_type_id}")
def update_object_type(object_type_id: str, body: ObjectTypeUpdate, db: Session = Depends(get_db)):
    obj_type = db.get(models.ObjectType, object_type_id)
    if not obj_type:
        raise HTTPException(status_code=404, detail=f"ObjectType '{object_type_id}' not found")
    if body.display_name is not None:
        obj_type.display_name = body.display_name
    if body.description is not None:
        obj_type.description = body.description
    if body.properties is not None:
        obj_type.properties = body.properties
    obj_type.updated_at = _now()
    _audit(db, "system", "ontology.object_type.updated", "object_type", object_type_id,
           {"display_name": obj_type.display_name})
    db.commit(); db.refresh(obj_type)
    return {
        "id": obj_type.id, "display_name": obj_type.display_name,
        "description": obj_type.description, "properties": obj_type.properties,
        "updated_at": obj_type.updated_at,
    }


@router.delete("/ontology/object-types/{object_type_id}")
def delete_object_type(object_type_id: str, db: Session = Depends(get_db)):
    obj_type = db.get(models.ObjectType, object_type_id)
    if not obj_type:
        raise HTTPException(status_code=404, detail=f"ObjectType '{object_type_id}' not found")
    instance_count = db.query(models.ObjectInstance).filter(
        models.ObjectInstance.object_type_id == object_type_id).count()
    if instance_count:
        raise HTTPException(status_code=409,
                            detail=f"ObjectType '{object_type_id}' has {instance_count} instances; delete them first")
    profile = db.get(ObjectTypeProfile, object_type_id)
    if profile:
        db.delete(profile)
    db.delete(obj_type)
    _audit(db, "system", "ontology.object_type.deleted", "object_type", object_type_id, {})
    db.commit()
    return {"id": object_type_id, "deleted": True}


# ---------------------------------------------------------------------------
# Primary-key validation against existing ObjectInstances
# ---------------------------------------------------------------------------
@router.post("/ontology/object-types/{object_type_id}/validate-primary-key")
def validate_primary_key(object_type_id: str, body: ValidatePrimaryKeyRequest, db: Session = Depends(get_db)):
    obj_type = db.get(models.ObjectType, object_type_id)
    if not obj_type:
        raise HTTPException(status_code=404, detail=f"ObjectType '{object_type_id}' not found")
    profile = db.get(ObjectTypeProfile, object_type_id)
    if not profile or not profile.primary_key:
        raise HTTPException(status_code=404,
                            detail=f"ObjectType '{object_type_id}' has no profile primary key configured")
    pk = profile.primary_key
    if pk not in body.properties or body.properties.get(pk) is None:
        raise HTTPException(status_code=422,
                            detail={"errors": [f"primary_key '{pk}' is missing from supplied properties"]})
    pk_value = body.properties[pk]

    duplicates: List[str] = []
    for inst in db.query(models.ObjectInstance).filter(
            models.ObjectInstance.object_type_id == object_type_id).all():
        if (inst.properties or {}).get(pk) == pk_value:
            duplicates.append(inst.id)

    return {
        "object_type_id": object_type_id,
        "primary_key": pk,
        "value": pk_value,
        "unique": len(duplicates) == 0,
        "duplicate": len(duplicates) > 0,
        "conflicting_object_ids": duplicates,
    }

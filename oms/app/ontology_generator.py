"""
Ontology Generator.

Local deterministic analogue of the guided Object Type creation flow: infer an
ontology draft from a dataset, validate keys/API names/property mappings, and
apply the reviewed draft into local ontology resources plus an optional Pipeline
Builder graph.
"""
import re
import time
import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import JSON, Integer, String
from sqlalchemy.orm import Mapped, Session, mapped_column

from . import models, models_action, ontology_core, ontology_versioning, pipeline_builder_ops, tenancy
from .database import Base, get_db
from .production_auth import Principal, require_permission

router = APIRouter(tags=["ontology_generator"])


class OntologyGeneratorDraft(Base):
    __tablename__ = "ontology_generator_drafts"

    id: Mapped[str] = mapped_column(String, primary_key=True, index=True)
    asset_id: Mapped[str] = mapped_column(String, index=True)
    object_type_id: Mapped[str] = mapped_column(String, index=True)
    draft: Mapped[dict] = mapped_column(JSON, default=dict)
    validation: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String, default="DRAFT")
    created_at: Mapped[int] = mapped_column(Integer)
    updated_at: Mapped[int] = mapped_column(Integer)


class DraftCreate(BaseModel):
    id: Optional[str] = None
    project_id: str = "default"
    asset_id: str
    object_type_id: Optional[str] = None
    display_name: Optional[str] = None
    description: Optional[str] = None
    include_actions: bool = False
    create_pipeline_graph: bool = True
    draft: Optional[Dict[str, Any]] = None


class DraftRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    asset_id: str
    object_type_id: str
    draft: Dict[str, Any]
    validation: Dict[str, Any]
    status: str
    created_at: int
    updated_at: int


class ApplyRequest(BaseModel):
    actor: str = "ontology_generator"
    create_actions: Optional[bool] = None
    create_pipeline_graph: Optional[bool] = None


def _now() -> int:
    return int(time.time())


def _new_id() -> str:
    return uuid.uuid4().hex


def _slug(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "_", value or "").strip("_").lower()
    return slug or "generated_object"


def _pascal(value: str) -> str:
    words = re.findall(r"[A-Za-z0-9]+", value or "")
    result = "".join(word[:1].upper() + word[1:] for word in words if word)
    if not result or not result[0].isalpha():
        result = f"Generated{result}"
    return result[:100]


def _camel(value: str) -> str:
    pascal = _pascal(value)
    return (pascal[:1].lower() + pascal[1:])[:100]


def _runtime_type(base_type: str) -> str:
    if base_type in {"byte", "short", "integer", "long"}:
        return "integer"
    if base_type in {"float", "double", "decimal"}:
        return "number"
    if base_type == "boolean":
        return "boolean"
    if base_type == "array":
        return "array"
    if base_type in {"geopoint", "geoshape"}:
        return "geojson"
    if base_type == "struct":
        return "object"
    return "string"


def _infer_base_type(values: List[Any]) -> str:
    non_null = [value for value in values if value is not None]
    if not non_null:
        return "string"
    if all(isinstance(value, bool) for value in non_null):
        return "boolean"
    if all(isinstance(value, int) and not isinstance(value, bool) for value in non_null):
        return "integer"
    if all(isinstance(value, (int, float)) and not isinstance(value, bool) for value in non_null):
        return "double"
    if all(isinstance(value, list) for value in non_null):
        return "array"
    if all(isinstance(value, dict) for value in non_null):
        geo_types = {str(value.get("type", "")).lower() for value in non_null}
        if geo_types <= {"point"}:
            return "geopoint"
        if geo_types & {"polygon", "multipolygon", "linestring", "multilinestring", "point"}:
            return "geoshape"
        return "struct"
    text_values = [str(value) for value in non_null]
    if all(re.match(r"^\d{4}-\d{2}-\d{2}$", value) for value in text_values):
        return "date"
    if all(re.match(r"^\d{4}-\d{2}-\d{2}[T\s]\d{2}:\d{2}", value) for value in text_values):
        return "timestamp"
    return "string"


def _asset_fields(asset: models.DataAsset) -> List[str]:
    fields = asset.asset_schema.get("fields") if isinstance(asset.asset_schema, dict) else None
    names = [str(field.get("name")) for field in fields or [] if isinstance(field, dict) and field.get("name")]
    seen = set(names)
    for row in asset.records or []:
        for key in row.keys():
            if key not in seen:
                seen.add(key)
                names.append(str(key))
    return names


def _field_values(asset: models.DataAsset, field: str) -> List[Any]:
    return [(row or {}).get(field) for row in (asset.records or [])]


def _unique_non_null(asset: models.DataAsset, field: str) -> bool:
    rows = asset.records or []
    values = [(row or {}).get(field) for row in rows]
    return bool(rows) and all(value is not None for value in values) and len(set(map(str, values))) == len(values)


def _choose_primary_key(asset: models.DataAsset, fields: List[str]) -> Optional[str]:
    preferred = ["id"] + [field for field in fields if field.lower().endswith("_id") or field.lower().endswith("id")]
    for field in preferred + fields:
        if field in fields and _unique_non_null(asset, field):
            return field
    if "id" in fields:
        return "id"
    for field in preferred:
        if field in fields:
            return field
    return None


def _choose_title_key(fields: List[str], primary_key: Optional[str]) -> Optional[str]:
    lowered = {field.lower(): field for field in fields}
    for candidate in ("name", "title", "display_name", "displayname", "label"):
        if candidate in lowered:
            return lowered[candidate]
    return primary_key or (fields[0] if fields else None)


def _generate_draft(asset: models.DataAsset, body: DraftCreate) -> Dict[str, Any]:
    fields = _asset_fields(asset)
    source_pk = _choose_primary_key(asset, fields)
    title_field = _choose_title_key(fields, source_pk)
    display_name = body.display_name or re.sub(r"[_-]+", " ", body.object_type_id or asset.display_name or asset.id).title()
    api_name = _pascal(display_name)
    object_type_id = body.object_type_id or _slug(api_name)
    properties: List[Dict[str, Any]] = []
    for field in fields:
        values = _field_values(asset, field)
        base_type = _infer_base_type(values)
        missing = sum(1 for value in values if value is None)
        property_name = _camel(field)
        properties.append({
            "source_field": field,
            "property_name": property_name,
            "api_name": property_name,
            "base_type": base_type,
            "status": "active",
            "required": bool(asset.records) and missing == 0,
            "include": True,
            "missing_count": missing,
            "unique_count": len(set(map(str, [value for value in values if value is not None]))),
            "sample_values": [value for value in values[:5] if value is not None],
        })
    needs_generated_id = not source_pk or not _unique_non_null(asset, source_pk)
    primary_key = _camel(source_pk) if source_pk else "generatedObjectId"
    if needs_generated_id and not any(prop["api_name"] == "generatedObjectId" for prop in properties):
        properties.insert(0, {
            "source_field": "generatedObjectId",
            "property_name": "generatedObjectId",
            "api_name": "generatedObjectId",
            "base_type": "string",
            "status": "active",
            "required": True,
            "include": True,
            "generated": True,
            "missing_count": 0,
            "unique_count": len(asset.records or []),
            "sample_values": [],
        })
    draft = {
        "asset_id": asset.id,
        "object_type_id": object_type_id,
        "display_name": display_name,
        "api_name": api_name,
        "description": body.description or f"Generated from dataset {asset.id}.",
        "primary_key": "generatedObjectId" if needs_generated_id else primary_key,
        "title_key": _camel(title_field) if title_field else primary_key,
        "source_primary_key": source_pk,
        "icon": "database",
        "color": "#1d5f8f",
        "plural_name": f"{display_name}s",
        "groups": ["generated", "local"],
        "properties": properties,
        "include_actions": body.include_actions,
        "create_pipeline_graph": body.create_pipeline_graph,
        "requires_unique_id_node": needs_generated_id,
    }
    draft["pipeline_graph"] = _pipeline_graph_draft(draft)
    return draft


def _included_properties(draft: Dict[str, Any]) -> List[Dict[str, Any]]:
    return [prop for prop in draft.get("properties") or [] if prop.get("include", True)]


def _pipeline_graph_draft(draft: Dict[str, Any]) -> Dict[str, Any]:
    nodes = [
        {"id": "input", "type": "input_dataset", "label": "Input dataset", "position": {"x": 80, "y": 150}, "config": {"asset_id": draft["asset_id"]}},
    ]
    edges: List[Dict[str, str]] = []
    previous = "input"
    if draft.get("requires_unique_id_node"):
        source_fields = [prop["source_field"] for prop in _included_properties(draft) if not prop.get("generated")]
        nodes.append({
            "id": "unique_id",
            "type": "unique_id",
            "label": "Stable primary key",
            "position": {"x": 360, "y": 150},
            "config": {"target_field": draft["primary_key"], "source_fields": source_fields[:8]},
        })
        edges.append({"source": previous, "target": "unique_id"})
        previous = "unique_id"
    mapping = {
        prop["source_field"]: prop["api_name"]
        for prop in _included_properties(draft)
        if prop.get("source_field")
    }
    ontology_x = 640 if draft.get("requires_unique_id_node") else 360
    nodes.append({
        "id": "ontology_output",
        "type": "ontology_output",
        "label": "Ontology output",
        "position": {"x": ontology_x, "y": 150},
        "config": {
            "object_type_id": draft["object_type_id"],
            "id_field": draft["primary_key"] if draft.get("requires_unique_id_node") else (draft.get("source_primary_key") or draft["primary_key"]),
            "mapping": mapping,
            "source_asset_id": draft["asset_id"],
        },
    })
    edges.append({"source": previous, "target": "ontology_output"})
    nodes.append({
        "id": "dataset_output",
        "type": "dataset_output",
        "label": "Dataset output",
        "position": {"x": ontology_x + 280, "y": 150},
        "config": {"asset_id": f"{draft['asset_id']}_{draft['object_type_id']}_output"},
    })
    edges.append({"source": "ontology_output", "target": "dataset_output"})
    return {
        "id": f"{draft['object_type_id']}_ontology_graph",
        "display_name": f"{draft['display_name']} Ontology Pipeline",
        "description": f"Generated ontology-output pipeline for {draft['display_name']}.",
        "nodes": nodes,
        "edges": edges,
        "parameters": {},
        "status": "DRAFT",
    }


def _validate_draft(db: Session, draft: Dict[str, Any]) -> Dict[str, Any]:
    errors: List[Dict[str, Any]] = []
    warnings: List[Dict[str, Any]] = []
    asset = db.get(models.DataAsset, draft.get("asset_id"))
    if not asset:
        errors.append({"code": "ASSET_NOT_FOUND", "message": f"DataAsset '{draft.get('asset_id')}' not found"})
        return {"status": "FAIL", "errors": errors, "warnings": warnings, "summary": {"errors": 1, "warnings": 0}}
    included = _included_properties(draft)
    if not included:
        errors.append({"code": "NO_PROPERTIES", "message": "At least one property must be included"})
    for message in ontology_core.validate_api_name(draft.get("api_name") or "", "pascal"):
        errors.append({"code": "INVALID_OBJECT_API_NAME", "message": message})
    seen_props = set()
    for prop in included:
        api_name = prop.get("api_name") or prop.get("property_name") or ""
        if api_name in seen_props:
            errors.append({"code": "DUPLICATE_PROPERTY_API_NAME", "property": api_name, "message": f"Property API name '{api_name}' is duplicated"})
        seen_props.add(api_name)
        for message in ontology_core.validate_api_name(api_name, "camel"):
            errors.append({"code": "INVALID_PROPERTY_API_NAME", "property": api_name, "message": message})
        if prop.get("base_type") not in ontology_core.FOUNDRY_BASE_TYPES:
            errors.append({"code": "INVALID_BASE_TYPE", "property": api_name, "message": f"Unknown base type '{prop.get('base_type')}'"})
        if prop.get("status", "active") not in ontology_core.PROPERTY_STATUSES:
            errors.append({"code": "INVALID_PROPERTY_STATUS", "property": api_name, "message": f"Invalid status '{prop.get('status')}'"})
    primary_key = draft.get("primary_key")
    pk_prop = next((prop for prop in included if prop.get("api_name") == primary_key), None)
    if not pk_prop:
        errors.append({"code": "PRIMARY_KEY_NOT_INCLUDED", "message": f"Primary key '{primary_key}' is not included"})
    elif pk_prop.get("base_type") not in ontology_core.PK_ALLOWED:
        errors.append({"code": "PRIMARY_KEY_TYPE", "message": f"Primary key '{primary_key}' cannot use base type '{pk_prop.get('base_type')}'"})
    else:
        source_field = pk_prop.get("source_field")
        if not pk_prop.get("generated") and not _unique_non_null(asset, source_field):
            if draft.get("requires_unique_id_node"):
                warnings.append({"code": "GENERATED_PRIMARY_KEY", "message": "Generated unique-id node will create a stable local primary key before ontology output"})
            else:
                errors.append({"code": "PRIMARY_KEY_NOT_UNIQUE", "message": f"Primary key source field '{source_field}' is not unique and non-null"})
    if draft.get("title_key") and not any(prop.get("api_name") == draft.get("title_key") for prop in included):
        warnings.append({"code": "TITLE_KEY_NOT_INCLUDED", "message": f"Title key '{draft.get('title_key')}' is not included; primary key will still work"})
    if db.get(models.ObjectType, draft.get("object_type_id")):
        warnings.append({"code": "OBJECT_TYPE_EXISTS", "message": f"Object type '{draft.get('object_type_id')}' will be updated"})
    status = "FAIL" if errors else ("WARN" if warnings else "PASS")
    return {
        "status": status,
        "errors": errors,
        "warnings": warnings,
        "summary": {"errors": len(errors), "warnings": len(warnings), "properties": len(included), "records": len(asset.records or [])},
    }


def _graph_from_draft(draft: Dict[str, Any]) -> Dict[str, Any]:
    graph = draft.get("pipeline_graph") or _pipeline_graph_draft(draft)
    if graph.get("nodes"):
        return graph
    return _pipeline_graph_draft(draft)


def _upsert_action(db: Session, *, project_id: str, action_id: str, display_name: str, description: str, parameters: Dict[str, Any], rules: Dict[str, Any]) -> str:
    row = db.get(models.ActionType, action_id)
    if row:
        if row.project_id != project_id:
            raise HTTPException(status_code=409, detail=f"Action type '{action_id}' belongs to another project")
        row.display_name = display_name
        row.description = description
        row.parameters = parameters
        row.rules = rules
    else:
        db.add(models.ActionType(id=action_id, project_id=project_id, display_name=display_name, description=description, parameters=parameters, rules=rules))
    return action_id


def _apply_draft(db: Session, row: OntologyGeneratorDraft, body: ApplyRequest) -> Dict[str, Any]:
    draft = dict(row.draft or {})
    project_id = str(draft.get("__project_id") or "default")
    validation = _validate_draft(db, draft)
    row.validation = validation
    row.updated_at = _now()
    if validation["errors"]:
        row.status = "INVALID"
        db.commit()
        raise HTTPException(status_code=422, detail=validation)

    now = _now()
    object_type_id = draft["object_type_id"]
    included = _included_properties(draft)
    object_properties = {
        prop["api_name"]: {
            "type": _runtime_type(prop.get("base_type", "string")),
            "base_type": prop.get("base_type", "string"),
            "required": bool(prop.get("required")),
            "source_field": prop.get("source_field"),
        }
        for prop in included
    }
    object_properties["__manager"] = {"project_id": project_id}
    obj_type = db.get(models.ObjectType, object_type_id)
    if obj_type:
        if obj_type.project_id != project_id:
            raise HTTPException(status_code=409, detail="Object type ID is owned by another project")
        obj_type.display_name = draft.get("display_name") or obj_type.display_name
        obj_type.description = draft.get("description")
        obj_type.properties = object_properties
        obj_type.updated_at = now
    else:
        obj_type = models.ObjectType(
            id=object_type_id,
            project_id=project_id,
            display_name=draft.get("display_name") or object_type_id,
            description=draft.get("description"),
            properties=object_properties,
            created_at=now,
            updated_at=now,
        )
        db.add(obj_type)

    profile_props = {
        prop["api_name"]: {
            "base_type": prop.get("base_type", "string"),
            "status": prop.get("status", "active"),
            "required": bool(prop.get("required")),
            "description": f"Mapped from {prop.get('source_field')}",
        }
        for prop in included
    }
    profile = db.get(ontology_core.ObjectTypeProfile, object_type_id)
    if profile:
        profile.api_name = draft["api_name"]
        profile.primary_key = draft.get("primary_key")
        profile.title_key = draft.get("title_key")
        profile.icon = draft.get("icon")
        profile.color = draft.get("color")
        profile.plural_name = draft.get("plural_name")
        profile.groups = draft.get("groups") or []
        profile.properties = profile_props
        profile.updated_at = now
    else:
        db.add(ontology_core.ObjectTypeProfile(
            object_type_id=object_type_id,
            api_name=draft["api_name"],
            primary_key=draft.get("primary_key"),
            title_key=draft.get("title_key"),
            icon=draft.get("icon"),
            color=draft.get("color"),
            plural_name=draft.get("plural_name"),
            groups=draft.get("groups") or [],
            properties=profile_props,
            created_at=now,
            updated_at=now,
        ))

    created_actions: List[str] = []
    if body.create_actions if body.create_actions is not None else draft.get("include_actions"):
        pk = draft.get("primary_key")
        param_schema = {prop["api_name"]: {"type": _runtime_type(prop.get("base_type", "string")), "required": bool(prop.get("required"))} for prop in included}
        set_map = {prop["api_name"]: f"${prop['api_name']}" for prop in included}
        created_actions.append(_upsert_action(
            db,
            project_id=project_id,
            action_id=f"create_{object_type_id}",
            display_name=f"Create {draft.get('display_name')}",
            description=f"Generated create action for {object_type_id}.",
            parameters=param_schema,
            rules={"mutations": [{"op": "create-object", "object_type_id": object_type_id, "object_id": f"${pk}", "set": set_map}]},
        ))
        created_actions.append(_upsert_action(
            db,
            project_id=project_id,
            action_id=f"edit_{object_type_id}",
            display_name=f"Edit {draft.get('display_name')}",
            description=f"Generated edit action for {object_type_id}.",
            parameters={"object_id": {"type": "string", "required": True}, **{k: {**v, "required": False} for k, v in param_schema.items()}},
            rules={"mutations": [{"op": "modify-object", "object_type_id": object_type_id, "object_id_param": "object_id", "set": set_map}]},
        ))
        created_actions.append(_upsert_action(
            db,
            project_id=project_id,
            action_id=f"delete_{object_type_id}",
            display_name=f"Delete {draft.get('display_name')}",
            description=f"Generated delete action for {object_type_id}.",
            parameters={"object_id": {"type": "string", "required": True}},
            rules={"mutations": [{"op": "delete-object", "object_id": "$object_id"}]},
        ))

    graph_id: Optional[str] = None
    if body.create_pipeline_graph if body.create_pipeline_graph is not None else draft.get("create_pipeline_graph", True):
        graph = _graph_from_draft(draft)
        graph_id = graph.get("id") or f"{object_type_id}_ontology_graph"
        existing_graph = db.get(pipeline_builder_ops.PipelineBuilderGraph, graph_id)
        if existing_graph:
            existing_project = existing_graph.project_id
            if existing_project != project_id:
                raise HTTPException(status_code=409, detail="Pipeline graph ID is owned by another project")
            existing_graph.display_name = graph.get("display_name") or existing_graph.display_name
            existing_graph.description = graph.get("description")
            existing_graph.nodes = graph.get("nodes") or []
            existing_graph.edges = graph.get("edges") or []
            existing_graph.parameters = {**(graph.get("parameters") or {}), "project_id": project_id}
            existing_graph.status = graph.get("status") or "DRAFT"
            existing_graph.updated_at = now
        else:
            db.add(pipeline_builder_ops.PipelineBuilderGraph(
                id=graph_id,
                project_id=project_id,
                display_name=graph.get("display_name") or graph_id,
                description=graph.get("description"),
                nodes=graph.get("nodes") or [],
                edges=graph.get("edges") or [],
                parameters={**(graph.get("parameters") or {}), "project_id": project_id},
                status=graph.get("status") or "DRAFT",
                created_at=now,
                updated_at=now,
            ))

    branch_id = f"{object_type_id}_generated_branch"
    if not db.get(ontology_versioning.OntologyBranch, branch_id):
        db.add(ontology_versioning.OntologyBranch(
            id=branch_id,
            display_name=f"Generate {draft.get('display_name')}",
            base_branch="main",
            status="open",
            created_at=now,
        ))
    proposal_id = f"{object_type_id}_generated_proposal"
    proposal = db.get(ontology_versioning.OntologyProposal, proposal_id)
    changes = [
        {"type": "object_type", "id": object_type_id},
        {"type": "object_type_profile", "id": object_type_id},
    ] + [{"type": "action_type", "id": action_id} for action_id in created_actions]
    if graph_id:
        changes.append({"type": "pipeline_builder_graph", "id": graph_id})
    if proposal:
        proposal.changes = changes
        proposal.status = "draft"
    else:
        db.add(ontology_versioning.OntologyProposal(
            id=proposal_id,
            branch_id=branch_id,
            title=f"Generate {draft.get('display_name')} ontology resources",
            description="Local deterministic analogue of an Ontology Manager proposal.",
            changes=changes,
            status="draft",
            reviewer=None,
            decided_at=None,
            created_at=now,
        ))

    db.add(models_action.AuditLog(
        id=_new_id(),
        actor=body.actor,
        event_type="ontology.generator.applied",
        subject_type="object_type",
        subject_id=object_type_id,
        payload={"project_id": project_id, "draft_id": row.id, "graph_id": graph_id, "actions": created_actions},
    ))
    try:
        from . import ops_control
        ops_control.record_ops_event(
            db,
            source="ontology_generator",
            event_type="ontology.generator.applied",
            severity="info",
            title=f"Ontology draft {row.id} applied",
            subject_type="object_type",
            subject_id=object_type_id,
            payload={"project_id": project_id, "draft_id": row.id, "graph_id": graph_id, "actions": created_actions},
        )
    except Exception:
        pass
    row.status = "APPLIED"
    row.validation = validation
    row.updated_at = now
    db.commit()
    return {
        "status": "APPLIED",
        "draft_id": row.id,
        "object_type_id": object_type_id,
        "profile_id": object_type_id,
        "action_type_ids": created_actions,
        "pipeline_graph_id": graph_id,
        "branch_id": branch_id,
        "proposal_id": proposal_id,
        "validation": validation,
    }


def _read(row: OntologyGeneratorDraft) -> DraftRead:
    return DraftRead.model_validate(row)


def _draft_project(row: OntologyGeneratorDraft) -> str:
    return str((row.draft or {}).get("__project_id") or "default")


def _draft_for(db: Session, draft_id: str, principal: Principal, permission: str) -> OntologyGeneratorDraft:
    row = db.get(OntologyGeneratorDraft, draft_id)
    if not row:
        raise HTTPException(status_code=404, detail=f"OntologyGeneratorDraft '{draft_id}' not found")
    tenancy.assert_project_permission(db, principal, _draft_project(row), permission)
    return row


def _create_draft_record(db: Session, body: DraftCreate) -> OntologyGeneratorDraft:
    asset = db.get(models.DataAsset, body.asset_id)
    if not asset:
        raise HTTPException(status_code=404, detail=f"DataAsset '{body.asset_id}' not found")
    if asset.project_id != body.project_id:
        raise HTTPException(status_code=409, detail="DataAsset is owned by another project")
    draft = dict(body.draft or _generate_draft(asset, body))
    draft["__project_id"] = body.project_id
    draft["pipeline_graph"] = draft.get("pipeline_graph") or _pipeline_graph_draft(draft)
    validation = _validate_draft(db, draft)
    draft_id = body.id or _new_id()
    if db.get(OntologyGeneratorDraft, draft_id):
        raise HTTPException(status_code=400, detail="OntologyGeneratorDraft already exists")
    now = _now()
    row = OntologyGeneratorDraft(
        id=draft_id,
        asset_id=asset.id,
        object_type_id=draft["object_type_id"],
        draft=draft,
        validation=validation,
        status="DRAFT" if not validation["errors"] else "INVALID",
        created_at=now,
        updated_at=now,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@router.post("/ontology-generator/drafts", response_model=DraftRead, status_code=201)
def create_draft(body: DraftCreate, principal: Principal = Depends(require_permission("deploy")), db: Session = Depends(get_db)):
    tenancy.assert_project_permission(db, principal, body.project_id, "deploy")
    return _create_draft_record(db, body)


@router.get("/ontology-generator/drafts", response_model=List[DraftRead])
def list_drafts(principal: Principal = Depends(require_permission("view")), db: Session = Depends(get_db)):
    rows = db.query(OntologyGeneratorDraft).order_by(OntologyGeneratorDraft.updated_at.desc()).all()
    accessible = tenancy.accessible_project_ids(db, principal, "view")
    return rows if accessible is None else [row for row in rows if _draft_project(row) in accessible]


@router.get("/ontology-generator/drafts/{draft_id}", response_model=DraftRead)
def get_draft(draft_id: str, principal: Principal = Depends(require_permission("view")), db: Session = Depends(get_db)):
    return _draft_for(db, draft_id, principal, "view")


@router.post("/ontology-generator/drafts/{draft_id}/validate")
def validate_draft(draft_id: str, principal: Principal = Depends(require_permission("edit")), db: Session = Depends(get_db)):
    row = _draft_for(db, draft_id, principal, "edit")
    validation = _validate_draft(db, row.draft or {})
    row.validation = validation
    row.status = "INVALID" if validation["errors"] else "DRAFT"
    row.updated_at = _now()
    db.commit()
    return validation


@router.post("/ontology-generator/drafts/{draft_id}/apply")
def apply_draft(draft_id: str, body: ApplyRequest = ApplyRequest(), principal: Principal = Depends(require_permission("deploy")), db: Session = Depends(get_db)):
    row = _draft_for(db, draft_id, principal, "deploy")
    return _apply_draft(db, row, body.model_copy(update={"actor": principal.id}))

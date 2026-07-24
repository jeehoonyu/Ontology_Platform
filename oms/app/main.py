from fastapi import FastAPI, Depends, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session
from typing import List, Optional
from pathlib import Path
import time
import os

from . import models, schemas, models_action
# New Foundry tool-equivalent modules (self-contained routers + ORM models).
# Importing them here registers their tables on the shared Base before create_all().
from . import (
    ontology_interfaces,
    ontology_value_types,
    ontology_versioning,
    ontology_functions,
    connectivity,
    streaming,
    schedules,
    media_sets,
    lineage,
    analytics,
    apps,
    modeling,
    observability,
    security_access,
    security_data,
    cipher,
    marketplace,
    aip_extras,
    dev_toolchain,
    notepad,
    ontology_core,
    aip_agents,
    aip_evals,
    aip_document,
    datasets_ext,
    workshop_runtime,
    slate_runtime,
    carbon_runtime,
    gis_ops,
    quiver_runtime,
    modeling_metrics,
    observability_checks,
    cipher_ops,
    security_propagation,
    contour_ops,
    object_explorer_ops,
    streaming_ops,
    schedules_ops,
    marketplace_ops,
    osdk_ops,
    compute_ops,
    connectivity_ops,
    media_ops,
    notepad_ops,
    admin_directory,
    admin_auth,
    admin_usage,
    ontology_interfaces_ops,
    lineage_ops,
    webhooks_ops,
    vertex_ops,
    automate_ops,
    aip_content_sources,
    modeling_evaluation_ops,
    fusion_ops,
    object_views_ops,
    pipeline_builder_ops,
    classification_ops,
    autopilot_ops,
    mcp_tools,
    decision_intelligence,
    modelops,
    audit_ops,
    ops_control,
    investigations,
    reliability_ops,
    platform_core,
    asset_reliability_scenario,
    ontology_generator,
    imports_ops,
    system_hardening,
    production_auth,
    tenancy,
    ontology_packages,
    platform_runtime,
)
from .database import engine, get_db
from .domain_maintenance import bootstrap_maintenance_copilot, maintenance_summary
from .domain_sentinel import (
    bootstrap_sentinel_operations_graph,
    case_provenance,
    case_subgraph,
    case_timeline,
    create_case,
    create_case_finding,
    create_case_task,
    draft_case_report,
    graph_neighbors,
    ingest_evidence,
    missing_evidence,
    sentinel_summary,
    shortest_path,
    suggest_next_steps,
    summarize_case,
)
from .runtime import (
    aggregate_object_set,
    apply_action_mutations,
    answer_assist_query,
    build_context_pack,
    build_mcp_context,
    build_object_profile,
    create_audit_log,
    decode_mgrs,
    encode_mgrs,
    evaluate_data_expectations,
    evaluate_automation,
    execute_logic_blocks,
    execute_pipeline_steps,
    extract_document_intelligence,
    generate_cron_from_prompt,
    evaluate_geofence,
    evaluate_saved_object_set,
    list_aip_tool_catalog,
    now_ts,
    object_set_feature_collection,
    plan_agent_session,
    score_eval_case,
    suggest_pipeline_from_prompt,
    stable_object_id,
    query_object_set,
    render_map_layer,
    search_around_objects,
    spatial_query_objects,
    transform_notepad_text,
    validate_action_parameters,
    validate_link_instance_candidate,
    validate_object_properties,
    validate_ontology_integrity,
)
import uuid

if os.getenv("SKIP_CREATE_ALL", "0") != "1":
    models.Base.metadata.create_all(bind=engine)
    models_action.Base.metadata.create_all(bind=engine)

app = FastAPI(title="Ontology Artificial Intelligence Platform")
production_auth.validate_auth_configuration()
app.add_middleware(production_auth.ProductionAuthorizationMiddleware)
UI_DIR = Path(__file__).resolve().parent / "ui"
REPO_ROOT = Path(__file__).resolve().parents[2]
FRONTEND_DIST_DIR = REPO_ROOT / "frontend" / "dist"
app.mount("/ui/assets", StaticFiles(directory=str(UI_DIR)), name="ui-assets")
if FRONTEND_DIST_DIR.exists():
    app.mount("/react", StaticFiles(directory=str(FRONTEND_DIST_DIR)), name="react-assets")

# Mount the new Foundry tool-equivalent routers. Each module exposes `router`.
for _ext_module in (
    ontology_interfaces,
    ontology_value_types,
    ontology_versioning,
    ontology_functions,
    connectivity,
    streaming,
    schedules,
    media_sets,
    lineage,
    analytics,
    apps,
    modeling,
    observability,
    security_access,
    security_data,
    cipher,
    marketplace,
    aip_extras,
    dev_toolchain,
    notepad,
    ontology_core,
    aip_agents,
    aip_evals,
    aip_document,
    datasets_ext,
    workshop_runtime,
    slate_runtime,
    carbon_runtime,
    gis_ops,
    quiver_runtime,
    modeling_metrics,
    observability_checks,
    cipher_ops,
    security_propagation,
    contour_ops,
    object_explorer_ops,
    streaming_ops,
    schedules_ops,
    marketplace_ops,
    osdk_ops,
    compute_ops,
    connectivity_ops,
    media_ops,
    notepad_ops,
    admin_directory,
    admin_auth,
    admin_usage,
    ontology_interfaces_ops,
    lineage_ops,
    webhooks_ops,
    vertex_ops,
    automate_ops,
    aip_content_sources,
    modeling_evaluation_ops,
    fusion_ops,
    object_views_ops,
    pipeline_builder_ops,
    classification_ops,
    autopilot_ops,
    mcp_tools,
    decision_intelligence,
    modelops,
    audit_ops,
    ops_control,
    investigations,
    reliability_ops,
    platform_core,
    asset_reliability_scenario,
    ontology_generator,
    imports_ops,
    system_hardening,
    production_auth,
    tenancy,
    ontology_packages,
    platform_runtime,
):
    app.include_router(_ext_module.router)


def _not_found(resource: str, resource_id: str):
    raise HTTPException(status_code=404, detail=f"{resource} '{resource_id}' not found")


def _workspace_shell(legacy: bool = False):
    react_index = FRONTEND_DIST_DIR / "index.html"
    if react_index.exists() and not legacy:
        return FileResponse(react_index)
    return FileResponse(UI_DIR / "index.html")


@app.get("/workspace", include_in_schema=False)
def serve_workspace(request: Request):
    return _workspace_shell(legacy=request.query_params.get("legacy") == "1")


@app.get("/workspace/{view}", include_in_schema=False)
def serve_workspace_view(view: str, request: Request):
    if view not in {"home", "files", "ontology", "applications", "map", "aip", "workshop", "object-explorer", "pipeline", "decision", "models", "ops", "investigations", "entity-resolution", "search", "graph", "command-center", "imports", "validation", "control-panel", "security", "automate", "data-media", "vertex", "fusion", "analytics", "delivery"}:
        _not_found("Workspace", view)
    return _workspace_shell(legacy=request.query_params.get("legacy") == "1")

@app.get("/")
def read_root():
    return {
        "status": "ok",
        "service": "Ontology Artificial Intelligence Platform",
        "capabilities": [
            "ontology_metadata",
            "ontology_generator",
            "runtime_object_graph",
            "object_sets",
            "saved_object_sets",
            "search_around_graph",
            "ontology_validation",
            "data_assets",
            "data_health_expectations",
            "gis_spatial_intelligence",
            "mgrs_grid_reference",
            "map_layers",
            "geojson_feature_exports",
            "geofence_evaluation",
            "pipeline_builder",
            "decision_intelligence",
            "temporal_object_timeline",
            "entity_resolution",
            "scenario_simulation",
            "modelops_workspace",
            "model_drift_monitoring",
            "model_prediction_logs",
            "ops_control_plane",
            "operational_alerts",
            "incident_runbooks",
            "investigation_graph_workspace",
            "data_quality_contracts",
            "lineage_impact_analysis",
            "deterministic_backfills",
            "unified_event_bus",
            "global_search",
            "policy_simulation",
            "shared_activity_timeline",
            "platform_graph_overview",
            "asset_reliability_command_center",
            "data_imports",
            "file_imports",
            "semantic_import_mapping",
            "import_transforms",
            "mapping_suggestions",
            "hybrid_connector_preview",
            "stream_replay",
            "react_vite_frontend",
            "ui_state_contracts",
            "pipeline_canvas_node_preview",
            "ontology_manager_workspace",
            "asset_reliability_workflow_state",
            "validation_dashboard",
            "project_snapshot",
            "project_validation",
            "schema_health",
            "event_consistency",
            "migration_metadata",
            "scenario_report_export",
            "action_execution_with_hitl",
            "agent_studio",
            "aip_evals",
            "audit_and_lineage",
        ],
    }

# --- Object Type Endpoints ---

@app.post("/object-types", response_model=schemas.ObjectType)
def create_object_type(obj: schemas.ObjectTypeCreate, db: Session = Depends(get_db)):
    db_obj = db.query(models.ObjectType).filter(models.ObjectType.id == obj.id).first()
    if db_obj:
        raise HTTPException(status_code=400, detail="ObjectType already exists")
    
    now = int(time.time())
    db_model = models.ObjectType(**obj.model_dump(), created_at=now, updated_at=now)
    db.add(db_model)
    create_audit_log(
        db,
        actor="system",
        event_type="ontology.object_type.created",
        subject_type="object_type",
        subject_id=obj.id,
        payload=obj.model_dump(),
    )
    db.commit()
    db.refresh(db_model)
    return db_model

@app.get("/object-types", response_model=List[schemas.ObjectType])
def list_object_types(db: Session = Depends(get_db)):
    return db.query(models.ObjectType).all()


# --- Object Instance Endpoints ---

@app.post("/objects", response_model=schemas.ObjectInstance)
def create_object_instance(obj: schemas.ObjectInstanceCreate, db: Session = Depends(get_db)):
    object_type = db.query(models.ObjectType).filter(models.ObjectType.id == obj.object_type_id).first()
    if not object_type:
        _not_found("ObjectType", obj.object_type_id)

    object_id = obj.id or stable_object_id(obj.object_type_id, obj.properties)
    existing = db.query(models.ObjectInstance).filter(models.ObjectInstance.id == object_id).first()
    if existing:
        raise HTTPException(status_code=400, detail="ObjectInstance already exists")

    errors = validate_object_properties(object_type, obj.properties)
    if errors:
        raise HTTPException(status_code=422, detail=errors)

    # Enforce the configured primary-key uniqueness when the object type has a
    # profile that declares one (no profile / no PK => no enforcement, so existing
    # callers without a configured profile are unaffected).
    profile = db.query(ontology_core.ObjectTypeProfile).filter(
        ontology_core.ObjectTypeProfile.object_type_id == obj.object_type_id
    ).first()
    if profile and getattr(profile, "primary_key", None):
        pk = profile.primary_key
        pk_value = (obj.properties or {}).get(pk)
        if pk_value is not None:
            clash = next(
                (
                    inst
                    for inst in db.query(models.ObjectInstance).filter(
                        models.ObjectInstance.object_type_id == obj.object_type_id
                    ).all()
                    if (inst.properties or {}).get(pk) == pk_value
                ),
                None,
            )
            if clash:
                raise HTTPException(
                    status_code=409,
                    detail=f"primary key '{pk}'={pk_value!r} already exists for object type '{obj.object_type_id}'",
                )

    now = now_ts()
    db_model = models.ObjectInstance(
        id=object_id,
        object_type_id=obj.object_type_id,
        properties=obj.properties,
        source_asset_id=obj.source_asset_id,
        lineage=obj.lineage,
        created_at=now,
        updated_at=now,
    )
    db.add(db_model)
    create_audit_log(
        db,
        actor="system",
        event_type="ontology.object.created",
        subject_type="object_instance",
        subject_id=object_id,
        payload={"object_type_id": obj.object_type_id, "lineage": obj.lineage},
    )
    decision_intelligence.record_object_snapshot(
        db,
        db_model,
        event_type="ontology.object.created",
        actor="system",
        source_type="object_api",
        source_id=object_id,
    )
    db.commit()
    db.refresh(db_model)
    return db_model


@app.get("/objects/{object_type_id}", response_model=List[schemas.ObjectInstance])
def list_object_instances(
    object_type_id: str,
    limit: int = 100,
    db: Session = Depends(get_db),
):
    return db.query(models.ObjectInstance).filter(
        models.ObjectInstance.object_type_id == object_type_id
    ).limit(limit).all()


@app.get("/objects/{object_type_id}/{object_id}", response_model=schemas.ObjectInstance)
def get_object_instance(object_type_id: str, object_id: str, db: Session = Depends(get_db)):
    db_obj = db.query(models.ObjectInstance).filter(
        models.ObjectInstance.object_type_id == object_type_id,
        models.ObjectInstance.id == object_id,
    ).first()
    if not db_obj:
        _not_found("ObjectInstance", object_id)
    return db_obj


@app.get("/objects/{object_type_id}/{object_id}/profile", response_model=schemas.ObjectProfileResponse)
def get_object_profile(
    object_type_id: str,
    object_id: str,
    linked_limit: int = 50,
    db: Session = Depends(get_db),
):
    try:
        return build_object_profile(
            db,
            object_type_id=object_type_id,
            object_id=object_id,
            linked_limit=linked_limit,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

# --- Link Type Endpoints ---

@app.post("/link-types", response_model=schemas.LinkType)
def create_link_type(link: schemas.LinkTypeCreate, db: Session = Depends(get_db)):
    db_obj = db.query(models.LinkType).filter(models.LinkType.id == link.id).first()
    if db_obj:
        raise HTTPException(status_code=400, detail="LinkType already exists")

    source = db.query(models.ObjectType).filter(models.ObjectType.id == link.source_object_type_id).first()
    target = db.query(models.ObjectType).filter(models.ObjectType.id == link.target_object_type_id).first()
    if not source:
        _not_found("ObjectType", link.source_object_type_id)
    if not target:
        _not_found("ObjectType", link.target_object_type_id)
    
    db_model = models.LinkType(**link.model_dump())
    db.add(db_model)
    create_audit_log(
        db,
        actor="system",
        event_type="ontology.link_type.created",
        subject_type="link_type",
        subject_id=link.id,
        payload=link.model_dump(),
    )
    db.commit()
    db.refresh(db_model)
    return db_model

@app.get("/link-types", response_model=List[schemas.LinkType])
def list_link_types(db: Session = Depends(get_db)):
    return db.query(models.LinkType).all()


@app.patch("/link-types/{link_type_id}", response_model=schemas.LinkType)
def update_link_type(link_type_id: str, patch: schemas.LinkTypePatch, db: Session = Depends(get_db)):
    row = db.get(models.LinkType, link_type_id)
    if not row:
        _not_found("LinkType", link_type_id)
    changes = patch.model_dump(exclude_unset=True)
    cardinality = changes.get("cardinality")
    if cardinality is not None and cardinality not in {"ONE_TO_ONE", "ONE_TO_MANY", "MANY_TO_MANY"}:
        raise HTTPException(status_code=422, detail="Unsupported link cardinality")
    for field in ("source_object_type_id", "target_object_type_id"):
        if field in changes and not db.get(models.ObjectType, changes[field]):
            raise HTTPException(status_code=422, detail=f"ObjectType '{changes[field]}' not found")
    for field, value in changes.items():
        setattr(row, field, value)
    create_audit_log(db, actor="system", event_type="ontology.link_type.updated", subject_type="link_type", subject_id=link_type_id, payload=changes)
    db.commit()
    db.refresh(row)
    return row


@app.post("/links", response_model=schemas.LinkInstance)
def create_link_instance(link: schemas.LinkInstanceCreate, db: Session = Depends(get_db)):
    link_type = db.query(models.LinkType).filter(models.LinkType.id == link.link_type_id).first()
    if not link_type:
        _not_found("LinkType", link.link_type_id)

    source = db.query(models.ObjectInstance).filter(models.ObjectInstance.id == link.source_object_id).first()
    target = db.query(models.ObjectInstance).filter(models.ObjectInstance.id == link.target_object_id).first()
    if not source:
        _not_found("ObjectInstance", link.source_object_id)
    if not target:
        _not_found("ObjectInstance", link.target_object_id)

    link_id = link.id or f"{link.link_type_id}:{link.source_object_id}:{link.target_object_id}"
    existing = db.query(models.LinkInstance).filter(models.LinkInstance.id == link_id).first()
    if existing:
        raise HTTPException(status_code=400, detail="LinkInstance already exists")

    link_errors = validate_link_instance_candidate(
        db,
        link_type=link_type,
        source=source,
        target=target,
        exclude_link_id=link_id,
    )
    if link_errors:
        raise HTTPException(status_code=422, detail=link_errors)

    db_model = models.LinkInstance(
        id=link_id,
        link_type_id=link.link_type_id,
        source_object_id=link.source_object_id,
        target_object_id=link.target_object_id,
        properties=link.properties,
        created_at=now_ts(),
    )
    db.add(db_model)
    create_audit_log(
        db,
        actor="system",
        event_type="ontology.link.created",
        subject_type="link_instance",
        subject_id=link_id,
        payload=link.model_dump(),
    )
    db.commit()
    db.refresh(db_model)
    return db_model


@app.get("/links", response_model=List[schemas.LinkInstance])
def list_link_instances(link_type_id: Optional[str] = None, db: Session = Depends(get_db)):
    query = db.query(models.LinkInstance)
    if link_type_id:
        query = query.filter(models.LinkInstance.link_type_id == link_type_id)
    return query.all()


# --- Object Set and Graph Exploration Endpoints ---

@app.post("/object-sets/search", response_model=schemas.ObjectSetResponse)
def search_object_sets(request: schemas.ObjectSetQuery, db: Session = Depends(get_db)):
    try:
        return query_object_set(
            db,
            object_type_id=request.object_type_id,
            filters=request.filters,
            limit=request.limit,
            offset=request.offset,
            cursor=request.cursor,
            with_total=request.with_total,
            include_lineage=request.include_lineage,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@app.post("/object-sets/aggregate", response_model=schemas.ObjectSetAggregateResponse)
def aggregate_object_sets(request: schemas.ObjectSetAggregateRequest, db: Session = Depends(get_db)):
    try:
        return aggregate_object_set(
            db,
            object_type_id=request.object_type_id,
            filters=request.filters,
            group_by=request.group_by,
            metrics=request.metrics,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@app.post("/object-sets/search-around", response_model=schemas.ObjectSetSearchAroundResponse)
def search_around_object_set(request: schemas.ObjectSetSearchAroundRequest, db: Session = Depends(get_db)):
    try:
        return search_around_objects(
            db,
            object_ids=request.object_ids,
            link_type_id=request.link_type_id,
            direction=request.direction,
            target_object_type_id=request.target_object_type_id,
            depth=request.depth,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@app.post("/object-sets/saved", response_model=schemas.SavedObjectSet)
def create_saved_object_set(request: schemas.SavedObjectSetCreate, db: Session = Depends(get_db)):
    existing = db.query(models.SavedObjectSet).filter(models.SavedObjectSet.id == request.id).first()
    if existing:
        raise HTTPException(status_code=400, detail="SavedObjectSet already exists")
    object_type = db.query(models.ObjectType).filter(models.ObjectType.id == request.object_type_id).first()
    if not object_type:
        _not_found("ObjectType", request.object_type_id)

    now = now_ts()
    db_model = models.SavedObjectSet(
        **request.model_dump(),
        created_at=now,
        updated_at=now,
    )
    db.add(db_model)
    create_audit_log(
        db,
        actor=request.owner,
        event_type="object_set.saved.created",
        subject_type="saved_object_set",
        subject_id=request.id,
        payload=request.model_dump(),
    )
    db.commit()
    db.refresh(db_model)
    return db_model


@app.get("/object-sets/saved", response_model=List[schemas.SavedObjectSet])
def list_saved_object_sets(db: Session = Depends(get_db)):
    return db.query(models.SavedObjectSet).order_by(models.SavedObjectSet.updated_at.desc()).all()


@app.get("/object-sets/saved/{object_set_id}", response_model=schemas.SavedObjectSet)
def get_saved_object_set(object_set_id: str, db: Session = Depends(get_db)):
    saved = db.query(models.SavedObjectSet).filter(models.SavedObjectSet.id == object_set_id).first()
    if not saved:
        _not_found("SavedObjectSet", object_set_id)
    return saved


@app.get("/object-sets/saved/{object_set_id}/objects", response_model=schemas.ObjectSetResponse)
def evaluate_saved_object_set_endpoint(
    object_set_id: str,
    limit: int = 100,
    include_lineage: bool = True,
    db: Session = Depends(get_db),
):
    saved = db.query(models.SavedObjectSet).filter(models.SavedObjectSet.id == object_set_id).first()
    if not saved:
        _not_found("SavedObjectSet", object_set_id)
    return evaluate_saved_object_set(db, saved_object_set=saved, limit=limit, include_lineage=include_lineage)


@app.get("/ontology/validate", response_model=schemas.OntologyValidationResponse)
def validate_ontology(db: Session = Depends(get_db)):
    return validate_ontology_integrity(db)


# --- GIS and Spatial Intelligence Endpoints ---

@app.post("/gis/spatial-query", response_model=schemas.GISSpatialQueryResponse)
def query_gis_spatial_objects(request: schemas.GISSpatialQuery, db: Session = Depends(get_db)):
    try:
        return spatial_query_objects(
            db,
            object_type_id=request.object_type_id,
            filters=request.filters,
            geometry_field=request.geometry_field,
            near=request.near,
            radius_meters=request.radius_meters,
            bbox=request.bbox,
            polygon=request.polygon,
            limit=request.limit,
            include_lineage=request.include_lineage,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@app.post("/gis/feature-collection", response_model=schemas.GISFeatureCollectionResponse)
def export_gis_feature_collection(request: schemas.GISFeatureCollectionRequest, db: Session = Depends(get_db)):
    try:
        return object_set_feature_collection(
            db,
            object_type_id=request.object_type_id,
            filters=request.filters,
            geometry_field=request.geometry_field,
            limit=request.limit,
            include_properties=request.include_properties,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@app.post("/gis/geofence/evaluate", response_model=schemas.GISGeofenceResponse)
def evaluate_gis_geofence(request: schemas.GISGeofenceRequest, db: Session = Depends(get_db)):
    try:
        result = evaluate_geofence(
            db,
            object_type_id=request.object_type_id,
            geofence=request.geofence,
            bbox=request.bbox,
            filters=request.filters,
            geometry_field=request.geometry_field,
            limit=request.limit,
        )
        summary = result.get("summary", {})
        ops_control.record_ops_event(
            db,
            source="gis",
            event_type="gis.geofence.evaluated",
            severity="high" if summary.get("inside", 0) else "info",
            title=f"Geofence evaluated for {request.object_type_id}",
            subject_type="object_type",
            subject_id=request.object_type_id,
            object_type_id=request.object_type_id,
            payload=summary,
        )
        db.commit()
        return result
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@app.post("/gis/mgrs/encode", response_model=schemas.MGRSCoordinateResponse)
def encode_gis_mgrs(request: schemas.MGRSEncodeRequest):
    try:
        return encode_mgrs(request.latitude, request.longitude, precision=request.precision)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@app.post("/gis/mgrs/decode", response_model=schemas.MGRSCoordinateResponse)
def decode_gis_mgrs(request: schemas.MGRSDecodeRequest):
    try:
        return decode_mgrs(request.mgrs, center=request.center)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@app.post("/gis/map-layers", response_model=schemas.MapLayerDefinition)
def create_map_layer(request: schemas.MapLayerDefinitionCreate, db: Session = Depends(get_db)):
    existing = db.query(models.MapLayerDefinition).filter(models.MapLayerDefinition.id == request.id).first()
    if existing:
        raise HTTPException(status_code=400, detail="MapLayerDefinition already exists")
    object_type = db.query(models.ObjectType).filter(models.ObjectType.id == request.object_type_id).first()
    if not object_type:
        _not_found("ObjectType", request.object_type_id)
    if request.saved_object_set_id:
        saved = db.query(models.SavedObjectSet).filter(models.SavedObjectSet.id == request.saved_object_set_id).first()
        if not saved:
            _not_found("SavedObjectSet", request.saved_object_set_id)

    now = now_ts()
    db_model = models.MapLayerDefinition(
        **request.model_dump(),
        created_at=now,
        updated_at=now,
    )
    db.add(db_model)
    create_audit_log(
        db,
        actor=request.owner,
        event_type="gis.map_layer.created",
        subject_type="map_layer",
        subject_id=request.id,
        payload=request.model_dump(),
    )
    db.commit()
    db.refresh(db_model)
    return db_model


@app.get("/gis/map-layers", response_model=List[schemas.MapLayerDefinition])
def list_map_layers(db: Session = Depends(get_db)):
    return db.query(models.MapLayerDefinition).order_by(models.MapLayerDefinition.updated_at.desc()).all()


@app.get("/gis/map-layers/{layer_id}", response_model=schemas.MapLayerDefinition)
def get_map_layer(layer_id: str, db: Session = Depends(get_db)):
    layer = db.query(models.MapLayerDefinition).filter(models.MapLayerDefinition.id == layer_id).first()
    if not layer:
        _not_found("MapLayerDefinition", layer_id)
    return layer


@app.get("/gis/map-layers/{layer_id}/features", response_model=schemas.MapLayerFeatureCollectionResponse)
def render_gis_map_layer(layer_id: str, limit: int = 1000, db: Session = Depends(get_db)):
    layer = db.query(models.MapLayerDefinition).filter(models.MapLayerDefinition.id == layer_id).first()
    if not layer:
        _not_found("MapLayerDefinition", layer_id)
    try:
        return render_map_layer(db, layer=layer, limit=limit)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

# --- Action Type Endpoints ---

@app.post("/action-types", response_model=schemas.ActionType)
def create_action_type(action: schemas.ActionTypeCreate, db: Session = Depends(get_db)):
    db_obj = db.query(models.ActionType).filter(models.ActionType.id == action.id).first()
    if db_obj:
        raise HTTPException(status_code=400, detail="ActionType already exists")
    
    db_model = models.ActionType(**action.model_dump())
    db.add(db_model)
    create_audit_log(
        db,
        actor="system",
        event_type="ontology.action_type.created",
        subject_type="action_type",
        subject_id=action.id,
        payload=action.model_dump(),
    )
    db.commit()
    db.refresh(db_model)
    return db_model

@app.get("/action-types", response_model=List[schemas.ActionType])
def list_action_types(db: Session = Depends(get_db)):
    return db.query(models.ActionType).all()


@app.patch("/action-types/{action_type_id}", response_model=schemas.ActionType)
def update_action_type(action_type_id: str, patch: schemas.ActionTypePatch, db: Session = Depends(get_db)):
    row = db.get(models.ActionType, action_type_id)
    if not row:
        _not_found("ActionType", action_type_id)
    changes = patch.model_dump(exclude_unset=True)
    for field, value in changes.items():
        setattr(row, field, value)
    create_audit_log(db, actor="system", event_type="ontology.action_type.updated", subject_type="action_type", subject_id=action_type_id, payload=changes)
    db.commit()
    db.refresh(row)
    return row


# --- Data Assets and Pipeline Builder ---

@app.post("/data-assets", response_model=schemas.DataAsset)
def create_data_asset(asset: schemas.DataAssetCreate, db: Session = Depends(get_db)):
    existing = db.query(models.DataAsset).filter(models.DataAsset.id == asset.id).first()
    if existing:
        raise HTTPException(status_code=400, detail="DataAsset already exists")

    now = now_ts()
    db_model = models.DataAsset(**asset.model_dump(), created_at=now, updated_at=now)
    db.add(db_model)
    create_audit_log(
        db,
        actor="system",
        event_type="data.asset.created",
        subject_type="data_asset",
        subject_id=asset.id,
        payload={"kind": asset.kind, "record_count": len(asset.records)},
    )
    db.commit()
    db.refresh(db_model)
    return db_model


@app.get("/data-assets", response_model=List[schemas.DataAsset])
def list_data_assets(db: Session = Depends(get_db)):
    return db.query(models.DataAsset).all()


@app.get("/data-assets/{asset_id}", response_model=schemas.DataAsset)
def get_data_asset(asset_id: str, db: Session = Depends(get_db)):
    db_obj = db.query(models.DataAsset).filter(models.DataAsset.id == asset_id).first()
    if not db_obj:
        _not_found("DataAsset", asset_id)
    return db_obj


@app.post("/data-assets/{asset_id}/expectations/run", response_model=schemas.DataExpectationsResponse)
def run_data_asset_expectations(
    asset_id: str,
    request: schemas.DataExpectationsRequest,
    db: Session = Depends(get_db),
):
    asset = db.query(models.DataAsset).filter(models.DataAsset.id == asset_id).first()
    if not asset:
        _not_found("DataAsset", asset_id)

    result = evaluate_data_expectations(asset.records or [], request.expectations)
    create_audit_log(
        db,
        actor="data_health",
        event_type="data.expectations.evaluated",
        subject_type="data_asset",
        subject_id=asset_id,
        payload={"status": result["status"], "summary": result["summary"]},
    )
    ops_control.record_ops_event(
        db,
        source="data_health",
        event_type="data.expectations.evaluated",
        severity="high" if result["status"] == "FAIL" else "medium" if result["status"] == "WARN" else "info",
        title=f"Data expectations {result['status']} for {asset.display_name}",
        subject_type="data_asset",
        subject_id=asset_id,
        payload={"status": result["status"], "summary": result["summary"]},
    )
    db.commit()
    return result


@app.post("/pipelines", response_model=schemas.PipelineDefinition)
def create_pipeline(pipeline: schemas.PipelineDefinitionCreate, db: Session = Depends(get_db)):
    existing = db.query(models.PipelineDefinition).filter(models.PipelineDefinition.id == pipeline.id).first()
    if existing:
        raise HTTPException(status_code=400, detail="PipelineDefinition already exists")

    input_asset = db.query(models.DataAsset).filter(models.DataAsset.id == pipeline.input_asset_id).first()
    if not input_asset:
        _not_found("DataAsset", pipeline.input_asset_id)
    if pipeline.output_asset_id:
        output_asset = db.query(models.DataAsset).filter(models.DataAsset.id == pipeline.output_asset_id).first()
        if not output_asset:
            _not_found("DataAsset", pipeline.output_asset_id)

    now = now_ts()
    db_model = models.PipelineDefinition(**pipeline.model_dump(), created_at=now, updated_at=now)
    db.add(db_model)
    create_audit_log(
        db,
        actor="system",
        event_type="pipeline.definition.created",
        subject_type="pipeline",
        subject_id=pipeline.id,
        payload={"input_asset_id": pipeline.input_asset_id, "steps": pipeline.steps},
    )
    db.commit()
    db.refresh(db_model)
    return db_model


@app.get("/pipelines", response_model=List[schemas.PipelineDefinition])
def list_pipelines(db: Session = Depends(get_db)):
    return db.query(models.PipelineDefinition).all()


@app.post("/pipelines/{pipeline_id}/run", response_model=schemas.PipelineRun)
def run_pipeline(pipeline_id: str, actor: str = "system", db: Session = Depends(get_db)):
    pipeline = db.query(models.PipelineDefinition).filter(models.PipelineDefinition.id == pipeline_id).first()
    if not pipeline:
        _not_found("PipelineDefinition", pipeline_id)

    input_asset = db.query(models.DataAsset).filter(models.DataAsset.id == pipeline.input_asset_id).first()
    if not input_asset:
        _not_found("DataAsset", pipeline.input_asset_id)

    run_id = str(uuid.uuid4())
    run = models.PipelineRun(
        id=run_id,
        pipeline_id=pipeline.id,
        status="RUNNING",
        input_asset_id=input_asset.id,
        output_asset_id=pipeline.output_asset_id,
        records_in=len(input_asset.records or []),
        records_out=0,
        lineage={},
        metrics={},
        created_at=now_ts(),
    )
    db.add(run)
    create_audit_log(
        db,
        actor=actor,
        event_type="pipeline.run.started",
        subject_type="pipeline_run",
        subject_id=run_id,
        payload={"pipeline_id": pipeline.id},
    )
    ops_control.record_ops_event(
        db,
        source="pipeline",
        event_type="pipeline.run.started",
        severity="info",
        title=f"Pipeline {pipeline.display_name} started",
        subject_type="pipeline_run",
        subject_id=run_id,
        payload={"pipeline_id": pipeline.id, "input_asset_id": input_asset.id},
    )
    db.commit()
    db.refresh(run)

    try:
        output_records, lineage, metrics = execute_pipeline_steps(
            db,
            pipeline=pipeline,
            run_id=run_id,
            input_asset=input_asset,
        )

        output_asset_id = pipeline.output_asset_id or f"{pipeline.id}_output"
        output_asset = db.query(models.DataAsset).filter(models.DataAsset.id == output_asset_id).first()
        if not output_asset:
            output_asset = models.DataAsset(
                id=output_asset_id,
                display_name=f"{pipeline.display_name} Output",
                description=f"Materialized output of pipeline {pipeline.id}",
                kind="dataset",
                asset_schema={},
                records=[],
                created_at=now_ts(),
                updated_at=now_ts(),
            )
            db.add(output_asset)

        output_asset.records = output_records
        output_asset.updated_at = now_ts()

        run.status = "SUCCESS"
        run.output_asset_id = output_asset.id
        run.records_out = len(output_records)
        run.lineage = lineage
        run.metrics = metrics
        run.completed_at = now_ts()
        create_audit_log(
            db,
            actor=actor,
            event_type="pipeline.run.completed",
            subject_type="pipeline_run",
            subject_id=run_id,
            payload={"records_out": len(output_records), "metrics": metrics},
        )
        ops_control.record_ops_event(
            db,
            source="pipeline",
            event_type="pipeline.run.completed",
            severity="info",
            title=f"Pipeline {pipeline.display_name} completed",
            subject_type="pipeline_run",
            subject_id=run_id,
            payload={"pipeline_id": pipeline.id, "records_out": len(output_records), "metrics": metrics},
        )
        db.commit()
        db.refresh(run)
        return run
    except Exception as exc:
        db.rollback()
        failed_run = db.query(models.PipelineRun).filter(models.PipelineRun.id == run_id).first()
        failed_run.status = "FAILED"
        failed_run.error = str(exc)
        failed_run.completed_at = now_ts()
        create_audit_log(
            db,
            actor=actor,
            event_type="pipeline.run.failed",
            subject_type="pipeline_run",
            subject_id=run_id,
            payload={"error": str(exc)},
        )
        ops_control.record_ops_event(
            db,
            source="pipeline",
            event_type="pipeline.run.failed",
            severity="high",
            title=f"Pipeline {pipeline.display_name} failed",
            subject_type="pipeline_run",
            subject_id=run_id,
            payload={"pipeline_id": pipeline.id, "error": str(exc)},
        )
        db.commit()
        db.refresh(failed_run)
        return failed_run


@app.get("/pipeline-runs", response_model=List[schemas.PipelineRun])
def list_pipeline_runs(pipeline_id: Optional[str] = None, db: Session = Depends(get_db)):
    query = db.query(models.PipelineRun)
    if pipeline_id:
        query = query.filter(models.PipelineRun.pipeline_id == pipeline_id)
    return query.order_by(models.PipelineRun.created_at.desc()).all()


# --- Model Endpoint Registry ---

@app.post("/model-endpoints", response_model=schemas.ModelEndpoint)
def create_model_endpoint(model_endpoint: schemas.ModelEndpointCreate, db: Session = Depends(get_db)):
    existing = db.query(models.ModelEndpoint).filter(models.ModelEndpoint.id == model_endpoint.id).first()
    if existing:
        raise HTTPException(status_code=400, detail="ModelEndpoint already exists")
    now = now_ts()
    db_model = models.ModelEndpoint(**model_endpoint.model_dump(), created_at=now, updated_at=now)
    db.add(db_model)
    create_audit_log(
        db,
        actor="system",
        event_type="model.endpoint.created",
        subject_type="model_endpoint",
        subject_id=model_endpoint.id,
        payload={"provider": model_endpoint.provider, "model_name": model_endpoint.model_name},
    )
    db.commit()
    db.refresh(db_model)
    return db_model


@app.get("/model-endpoints", response_model=List[schemas.ModelEndpoint])
def list_model_endpoints(db: Session = Depends(get_db)):
    return db.query(models.ModelEndpoint).all()

# --- Action Execution Engine ---

@app.post("/actions/execute", response_model=schemas.ActionExecutionResponse)
def execute_action(request: schemas.ActionExecutionRequest, db: Session = Depends(get_db)):
    # 1. Idempotency Check
    existing_key = db.query(models_action.IdempotencyKey).filter(
        models_action.IdempotencyKey.key == request.idempotency_key
    ).first()
    
    if existing_key:
        return schemas.ActionExecutionResponse(
            status="SUCCESS_CACHED",
            message="Action previously executed.",
            outbox_event_id=existing_key.response_payload.get("outbox_event_id") if existing_key.response_payload else None,
            mutated_object_ids=existing_key.response_payload.get("mutated_object_ids", []) if existing_key.response_payload else [],
        )
    
    # 2. Validate Action Type and parameters
    action_type = db.query(models.ActionType).filter(models.ActionType.id == request.action_type_id).first()
    if not action_type:
        raise HTTPException(status_code=404, detail="ActionType not found")

    parameter_errors = validate_action_parameters(action_type, request.parameters)
    if parameter_errors:
        raise HTTPException(status_code=422, detail=parameter_errors)

    rules = action_type.rules or {}
    requires_approval = bool(
        rules.get("requires_approval")
        or rules.get("approval_required")
        or str(rules.get("risk_level", "")).lower() in {"high", "critical"}
    )

    if requires_approval:
        approval = None
        if request.approval_request_id:
            approval = db.query(models_action.ApprovalRequest).filter(
                models_action.ApprovalRequest.id == request.approval_request_id
            ).first()
            if not approval:
                _not_found("ApprovalRequest", request.approval_request_id)
            if approval.status != models_action.ApprovalStatus.APPROVED.value:
                raise HTTPException(status_code=403, detail="ApprovalRequest is not approved")
            if approval.action_type_id != request.action_type_id or approval.parameters != request.parameters:
                raise HTTPException(status_code=403, detail="ApprovalRequest does not match this action request")
        else:
            approval_id = str(uuid.uuid4())
            approval = models_action.ApprovalRequest(
                id=approval_id,
                action_type_id=request.action_type_id,
                requester=request.actor,
                parameters=request.parameters,
                status=models_action.ApprovalStatus.PENDING.value,
            )
            db.add(approval)
            create_audit_log(
                db,
                actor=request.actor,
                event_type="action.approval.requested",
                subject_type="approval_request",
                subject_id=approval_id,
                payload={"action_type_id": request.action_type_id, "parameters": request.parameters},
            )
            ops_control.record_ops_event(
                db,
                source="action",
                event_type="action.approval.requested",
                severity="high",
                title=f"Approval requested for {request.action_type_id}",
                subject_type="approval_request",
                subject_id=approval_id,
                payload={"action_type_id": request.action_type_id, "parameters": request.parameters},
            )
            db.commit()
            return schemas.ActionExecutionResponse(
                status="REQUIRES_APPROVAL",
                message="Action staged for human approval.",
                approval_request_id=approval_id,
            )

    # 3. Transactional Outbox Pattern: Save state mutation + external event in single transaction
    outbox_id = str(uuid.uuid4())
    
    try:
        mutated_object_ids = apply_action_mutations(
            db,
            action_type=action_type,
            parameters=request.parameters,
            actor=request.actor,
        )
        
        # Write Outbox Event for CDC to propagate to external systems
        outbox_event = models_action.OutboxEvent(
            id=outbox_id,
            action_type_id=request.action_type_id,
            payload={
                "parameters": request.parameters,
                "actor": request.actor,
                "mutated_object_ids": mutated_object_ids,
                "approval_request_id": request.approval_request_id,
            },
            status=models_action.ActionStatus.PENDING.value
        )
        db.add(outbox_event)
        
        # Save Idempotency Key
        response_data = {"outbox_event_id": outbox_id, "mutated_object_ids": mutated_object_ids}
        idemp_key = models_action.IdempotencyKey(
            key=request.idempotency_key,
            action_type_id=request.action_type_id,
            response_payload=response_data
        )
        db.add(idemp_key)

        create_audit_log(
            db,
            actor=request.actor,
            event_type="action.executed",
            subject_type="action_type",
            subject_id=request.action_type_id,
            payload=response_data,
        )
        ops_control.record_ops_event(
            db,
            source="action",
            event_type="action.executed",
            severity="medium" if mutated_object_ids else "info",
            title=f"Action {request.action_type_id} executed",
            subject_type="action_type",
            subject_id=request.action_type_id,
            payload=response_data,
        )
        
        # Atomic commit
        db.commit()
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Action execution failed: {str(e)}")
        
    return schemas.ActionExecutionResponse(
        status="SUCCESS",
        message="Action processed and outbox event queued.",
        outbox_event_id=outbox_id,
        approval_request_id=request.approval_request_id,
        mutated_object_ids=mutated_object_ids,
    )


@app.get("/approvals", response_model=List[schemas.ApprovalRequest])
def list_approvals(status: Optional[str] = None, db: Session = Depends(get_db)):
    query = db.query(models_action.ApprovalRequest)
    if status:
        query = query.filter(models_action.ApprovalRequest.status == status.upper())
    return query.order_by(models_action.ApprovalRequest.created_at.desc()).all()


@app.post("/approvals/{approval_id}/decision", response_model=schemas.ApprovalRequest)
def decide_approval(
    approval_id: str,
    decision: schemas.ApprovalDecisionRequest,
    db: Session = Depends(get_db),
):
    approval = db.query(models_action.ApprovalRequest).filter(
        models_action.ApprovalRequest.id == approval_id
    ).first()
    if not approval:
        _not_found("ApprovalRequest", approval_id)
    if approval.status != models_action.ApprovalStatus.PENDING.value:
        raise HTTPException(status_code=400, detail="ApprovalRequest is already decided")

    normalized = decision.decision.upper()
    if normalized not in {
        models_action.ApprovalStatus.APPROVED.value,
        models_action.ApprovalStatus.REJECTED.value,
    }:
        raise HTTPException(status_code=422, detail="decision must be APPROVED or REJECTED")

    approval.status = normalized
    approval.reason = decision.reason
    approval.decided_at = now_ts()
    create_audit_log(
        db,
        actor=decision.actor,
        event_type="action.approval.decided",
        subject_type="approval_request",
        subject_id=approval_id,
        payload={"decision": normalized, "reason": decision.reason},
    )
    ops_control.record_ops_event(
        db,
        source="action",
        event_type="action.approval.decided",
        severity="medium",
        title=f"Approval {normalized.lower()} for {approval.action_type_id}",
        subject_type="approval_request",
        subject_id=approval_id,
        payload={"decision": normalized, "reason": decision.reason, "action_type_id": approval.action_type_id},
    )
    db.commit()
    db.refresh(approval)
    return approval


# --- Agent Studio and Evals ---

@app.post("/agents", response_model=schemas.AgentDefinition)
def create_agent(agent: schemas.AgentDefinitionCreate, db: Session = Depends(get_db)):
    existing = db.query(models.AgentDefinition).filter(models.AgentDefinition.id == agent.id).first()
    if existing:
        raise HTTPException(status_code=400, detail="AgentDefinition already exists")
    if agent.model_endpoint_id:
        model_endpoint = db.query(models.ModelEndpoint).filter(
            models.ModelEndpoint.id == agent.model_endpoint_id
        ).first()
        if not model_endpoint:
            _not_found("ModelEndpoint", agent.model_endpoint_id)

    for object_type_id in agent.allowed_object_types:
        if not db.query(models.ObjectType).filter(models.ObjectType.id == object_type_id).first():
            _not_found("ObjectType", object_type_id)
    for action_id in agent.allowed_actions:
        if not db.query(models.ActionType).filter(models.ActionType.id == action_id).first():
            _not_found("ActionType", action_id)

    now = now_ts()
    db_model = models.AgentDefinition(**agent.model_dump(), created_at=now, updated_at=now)
    db.add(db_model)
    create_audit_log(
        db,
        actor="system",
        event_type="agent.definition.created",
        subject_type="agent",
        subject_id=agent.id,
        payload={"allowed_object_types": agent.allowed_object_types, "allowed_actions": agent.allowed_actions},
    )
    db.commit()
    db.refresh(db_model)
    return db_model


@app.get("/agents", response_model=List[schemas.AgentDefinition])
def list_agents(db: Session = Depends(get_db)):
    return db.query(models.AgentDefinition).all()


@app.post("/agents/{agent_id}/sessions", response_model=schemas.AgentSession)
def run_agent_session(
    agent_id: str,
    request: schemas.AgentSessionCreate,
    db: Session = Depends(get_db),
):
    agent = db.query(models.AgentDefinition).filter(models.AgentDefinition.id == agent_id).first()
    if not agent:
        _not_found("AgentDefinition", agent_id)

    context, plan, proposed_actions, status = plan_agent_session(
        db,
        agent=agent,
        user_prompt=request.user_prompt,
        filters=request.filters,
        max_context_objects=request.max_context_objects,
    )
    session_id = str(uuid.uuid4())
    db_model = models.AgentSession(
        id=session_id,
        agent_id=agent.id,
        user_prompt=request.user_prompt,
        status=status,
        context=context,
        plan=plan,
        proposed_actions=proposed_actions,
        created_at=now_ts(),
        completed_at=now_ts(),
    )
    db.add(db_model)
    create_audit_log(
        db,
        actor="agent",
        event_type="agent.session.completed",
        subject_type="agent_session",
        subject_id=session_id,
        payload={"agent_id": agent.id, "status": status, "proposed_actions": proposed_actions},
    )
    ops_control.record_ops_event(
        db,
        source="agent",
        event_type="agent.session.completed",
        severity="medium" if proposed_actions else "info",
        title=f"Agent {agent.display_name} session {status}",
        subject_type="agent_session",
        subject_id=session_id,
        payload={"agent_id": agent.id, "status": status, "proposed_actions": proposed_actions},
    )
    db.commit()
    db.refresh(db_model)
    return db_model


@app.get("/agents/{agent_id}/context")
def get_agent_context(
    agent_id: str,
    limit: int = 5,
    db: Session = Depends(get_db),
):
    agent = db.query(models.AgentDefinition).filter(models.AgentDefinition.id == agent_id).first()
    if not agent:
        _not_found("AgentDefinition", agent_id)
    return build_context_pack(db, allowed_object_types=agent.allowed_object_types or [], limit=limit)


# --- AIP Tooling Surface ---

@app.get("/aip/tools", response_model=List[schemas.AIPTool])
def list_aip_tools():
    return list_aip_tool_catalog()


@app.get("/mcp/context")
def get_mcp_context(db: Session = Depends(get_db)):
    return build_mcp_context(db)


@app.post("/aip/assist/query", response_model=schemas.AssistResponse)
def query_assist(request: schemas.AssistRequest, db: Session = Depends(get_db)):
    result = answer_assist_query(
        db,
        prompt=request.prompt,
        application_context=request.application_context,
        include_mcp_context=request.include_mcp_context,
    )
    create_audit_log(
        db,
        actor="assist",
        event_type="aip.assist.query",
        subject_type="assist",
        subject_id=str(uuid.uuid4()),
        payload={"prompt": request.prompt, "referenced_tools": result["referenced_tools"]},
    )
    db.commit()
    return result


@app.post("/aip/pipeline-builder/generate", response_model=schemas.PipelineAssistResponse)
def generate_pipeline_assist(request: schemas.PipelineAssistRequest, db: Session = Depends(get_db)):
    result = suggest_pipeline_from_prompt(request.prompt, request.sample_fields)
    create_audit_log(
        db,
        actor="pipeline_builder_assist",
        event_type="aip.pipeline_builder.generated",
        subject_type="pipeline_assist",
        subject_id=result["suggested_name"],
        payload={"prompt": request.prompt, "steps": result["steps"]},
    )
    db.commit()
    return result


@app.post("/aip/document-intelligence/extract", response_model=schemas.DocumentExtractionResponse)
def extract_document(request: schemas.DocumentExtractionRequest, db: Session = Depends(get_db)):
    result = extract_document_intelligence(request.text, request.extraction_schema)
    create_audit_log(
        db,
        actor="document_intelligence",
        event_type="aip.document.extracted",
        subject_type="document",
        subject_id=str(uuid.uuid4()),
        payload={"fields": list(result["fields"].keys()), "entities": {k: len(v) for k, v in result["entities"].items()}},
    )
    db.commit()
    return result


@app.post("/aip/notepad/transform", response_model=schemas.NotepadTransformResponse)
def transform_notepad(request: schemas.NotepadTransformRequest, db: Session = Depends(get_db)):
    result = transform_notepad_text(
        text=request.text,
        operation=request.operation,
        instruction=request.instruction,
        target_language=request.target_language,
    )
    create_audit_log(
        db,
        actor="notepad",
        event_type="aip.notepad.transformed",
        subject_type="notepad_text",
        subject_id=str(uuid.uuid4()),
        payload={"operation": request.operation},
    )
    db.commit()
    return result


@app.post("/scheduler/generate-cron", response_model=schemas.SchedulerResponse)
def generate_scheduler_cron(request: schemas.SchedulerRequest):
    return generate_cron_from_prompt(request.prompt)


# --- Maintenance Operations Copilot Domain ---

@app.post("/domains/maintenance/bootstrap", response_model=schemas.DomainBootstrapResponse)
def bootstrap_maintenance_domain(
    request: schemas.DomainBootstrapRequest,
    db: Session = Depends(get_db),
):
    result = bootstrap_maintenance_copilot(db, actor=request.actor)
    pipeline_runs = []
    if request.run_pipelines:
        for pipeline_id in result["recommended_pipeline_order"]:
            run = run_pipeline(pipeline_id, actor=request.actor, db=db)
            pipeline_runs.append({
                "id": run.id,
                "pipeline_id": run.pipeline_id,
                "status": run.status,
                "records_in": run.records_in,
                "records_out": run.records_out,
                "metrics": run.metrics,
            })

    return {**result, "pipeline_runs": pipeline_runs}


@app.get("/domains/maintenance/summary", response_model=schemas.MaintenanceSummary)
def get_maintenance_summary(db: Session = Depends(get_db)):
    return maintenance_summary(db)


# --- Sentinel Operations Graph Domain ---

@app.post("/domains/sentinel/bootstrap", response_model=schemas.SentinelBootstrapResponse)
def bootstrap_sentinel_domain(
    request: schemas.SentinelBootstrapRequest,
    db: Session = Depends(get_db),
):
    return bootstrap_sentinel_operations_graph(db, actor=request.actor)


@app.get("/domains/sentinel/summary", response_model=schemas.SentinelSummary)
def get_sentinel_summary(db: Session = Depends(get_db)):
    return sentinel_summary(db)


@app.post("/cases")
def create_sentinel_case(request: schemas.SentinelCaseCreate, db: Session = Depends(get_db)):
    return create_case(
        db,
        case_id=request.id,
        title=request.title,
        description=request.description,
        owner=request.owner,
        sensitivity=request.sensitivity,
        status=request.status,
        actor=request.actor,
    )


@app.get("/cases", response_model=List[schemas.ObjectInstance])
def list_sentinel_cases(db: Session = Depends(get_db)):
    return db.query(models.ObjectInstance).filter(
        models.ObjectInstance.object_type_id == "sentinel_case"
    ).all()


@app.get("/cases/{case_id}", response_model=schemas.ObjectInstance)
def get_sentinel_case(case_id: str, db: Session = Depends(get_db)):
    case = db.query(models.ObjectInstance).filter(
        models.ObjectInstance.id == case_id,
        models.ObjectInstance.object_type_id == "sentinel_case",
    ).first()
    if not case:
        _not_found("SentinelCase", case_id)
    return case


@app.post("/cases/{case_id}/evidence")
def ingest_sentinel_evidence(
    case_id: str,
    request: schemas.SentinelEvidenceIngestRequest,
    db: Session = Depends(get_db),
):
    try:
        return ingest_evidence(
            db,
            case_id=case_id,
            evidence_id=request.id,
            title=request.title,
            text=request.text,
            source_uri=request.source_uri,
            source_type=request.source_type,
            sensitivity=request.sensitivity,
            extraction_schema=request.extraction_schema,
            actor=request.actor,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@app.post("/cases/{case_id}/tasks")
def create_sentinel_task(
    case_id: str,
    request: schemas.SentinelTaskCreate,
    db: Session = Depends(get_db),
):
    return create_case_task(
        db,
        case_id=case_id,
        task_id=request.id,
        title=request.title,
        description=request.description,
        priority=request.priority,
        status=request.status,
        assignee=request.assignee,
        actor=request.actor,
    )


@app.post("/cases/{case_id}/findings")
def create_sentinel_finding(
    case_id: str,
    request: schemas.SentinelFindingCreate,
    db: Session = Depends(get_db),
):
    return create_case_finding(
        db,
        case_id=case_id,
        finding_id=request.id,
        title=request.title,
        summary=request.summary,
        confidence=request.confidence,
        status=request.status,
        actor=request.actor,
    )


@app.get("/cases/{case_id}/graph")
def get_case_graph(case_id: str, depth: int = 2, db: Session = Depends(get_db)):
    return case_subgraph(db, case_id=case_id, depth=depth)


@app.get("/cases/{case_id}/timeline")
def get_case_timeline(case_id: str, db: Session = Depends(get_db)):
    return case_timeline(db, case_id=case_id)


@app.get("/cases/{case_id}/provenance")
def get_case_provenance(case_id: str, db: Session = Depends(get_db)):
    return case_provenance(db, case_id=case_id)


@app.post("/cases/{case_id}/agent/summarize")
def summarize_sentinel_case(
    case_id: str,
    request: schemas.SentinelCopilotRequest,
    db: Session = Depends(get_db),
):
    try:
        result = summarize_case(db, case_id=case_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    create_audit_log(
        db,
        actor=request.actor,
        event_type="sentinel.agent.summarized",
        subject_type="sentinel_case",
        subject_id=case_id,
        payload={"instruction": request.instruction},
    )
    db.commit()
    return result


@app.post("/cases/{case_id}/agent/missing-evidence")
def get_missing_sentinel_evidence(
    case_id: str,
    request: schemas.SentinelCopilotRequest,
    db: Session = Depends(get_db),
):
    result = missing_evidence(db, case_id=case_id)
    create_audit_log(
        db,
        actor=request.actor,
        event_type="sentinel.agent.missing_evidence",
        subject_type="sentinel_case",
        subject_id=case_id,
        payload=result,
    )
    db.commit()
    return result


@app.post("/cases/{case_id}/agent/suggest-next-steps")
def suggest_sentinel_next_steps(
    case_id: str,
    request: schemas.SentinelCopilotRequest,
    db: Session = Depends(get_db),
):
    result = suggest_next_steps(db, case_id=case_id)
    create_audit_log(
        db,
        actor=request.actor,
        event_type="sentinel.agent.next_steps",
        subject_type="sentinel_case",
        subject_id=case_id,
        payload=result,
    )
    db.commit()
    return result


@app.post("/cases/{case_id}/agent/draft-report")
def draft_sentinel_report(
    case_id: str,
    request: schemas.SentinelCopilotRequest,
    db: Session = Depends(get_db),
):
    try:
        return draft_case_report(db, case_id=case_id, actor=request.actor)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@app.post("/graph/neighbors")
def get_graph_neighbors(request: schemas.SentinelGraphQuery, db: Session = Depends(get_db)):
    return graph_neighbors(db, object_id=request.object_id, depth=request.depth)


@app.post("/graph/shortest-path")
def get_graph_shortest_path(request: schemas.SentinelPathQuery, db: Session = Depends(get_db)):
    return shortest_path(
        db,
        source_id=request.source_id,
        target_id=request.target_id,
        max_depth=request.max_depth,
    )


@app.post("/threads", response_model=schemas.AIPThread)
def create_thread(request: schemas.ThreadCreate, db: Session = Depends(get_db)):
    thread_id = str(uuid.uuid4())
    now = now_ts()
    db_model = models.AIPThread(
        id=thread_id,
        title=request.title,
        owner=request.owner,
        resources=request.resources,
        messages=[],
        created_at=now,
        updated_at=now,
    )
    db.add(db_model)
    create_audit_log(
        db,
        actor=request.owner,
        event_type="aip.thread.created",
        subject_type="thread",
        subject_id=thread_id,
        payload={"title": request.title, "resources": request.resources},
    )
    db.commit()
    db.refresh(db_model)
    return db_model


@app.get("/threads", response_model=List[schemas.AIPThread])
def list_threads(db: Session = Depends(get_db)):
    return db.query(models.AIPThread).order_by(models.AIPThread.updated_at.desc()).all()


@app.get("/threads/{thread_id}", response_model=schemas.AIPThread)
def get_thread(thread_id: str, db: Session = Depends(get_db)):
    thread = db.query(models.AIPThread).filter(models.AIPThread.id == thread_id).first()
    if not thread:
        _not_found("AIPThread", thread_id)
    return thread


@app.post("/threads/{thread_id}/messages", response_model=schemas.AIPThread)
def add_thread_message(
    thread_id: str,
    request: schemas.ThreadMessageCreate,
    db: Session = Depends(get_db),
):
    thread = db.query(models.AIPThread).filter(models.AIPThread.id == thread_id).first()
    if not thread:
        _not_found("AIPThread", thread_id)

    messages = list(thread.messages or [])
    messages.append({
        "id": str(uuid.uuid4()),
        "role": request.role,
        "content": request.content,
        "attachments": request.attachments,
        "created_at": now_ts(),
    })

    if request.role == "user":
        assist_result = answer_assist_query(
            db,
            prompt=request.content,
            application_context=f"thread:{thread.title}",
            include_mcp_context=False,
        )
        messages.append({
            "id": str(uuid.uuid4()),
            "role": "assistant",
            "content": assist_result["answer"],
            "attachments": [{"type": "tool_references", "value": assist_result["referenced_tools"]}],
            "created_at": now_ts(),
        })

    thread.messages = messages
    thread.updated_at = now_ts()
    create_audit_log(
        db,
        actor=request.role,
        event_type="aip.thread.message_added",
        subject_type="thread",
        subject_id=thread_id,
        payload={"role": request.role},
    )
    db.commit()
    db.refresh(thread)
    return thread


@app.post("/logic-functions", response_model=schemas.LogicFunction)
def create_logic_function(logic: schemas.LogicFunctionCreate, db: Session = Depends(get_db)):
    existing = db.query(models.LogicFunction).filter(models.LogicFunction.id == logic.id).first()
    if existing:
        raise HTTPException(status_code=400, detail="LogicFunction already exists")
    now = now_ts()
    db_model = models.LogicFunction(**logic.model_dump(), created_at=now, updated_at=now)
    db.add(db_model)
    create_audit_log(
        db,
        actor="system",
        event_type="aip.logic.created",
        subject_type="logic_function",
        subject_id=logic.id,
        payload={"blocks": logic.blocks},
    )
    db.commit()
    db.refresh(db_model)
    return db_model


@app.get("/logic-functions", response_model=List[schemas.LogicFunction])
def list_logic_functions(db: Session = Depends(get_db)):
    return db.query(models.LogicFunction).all()


@app.post("/logic-functions/{logic_id}/run", response_model=schemas.LogicRun)
def run_logic_function(
    logic_id: str,
    request: schemas.LogicRunRequest,
    db: Session = Depends(get_db),
):
    logic = db.query(models.LogicFunction).filter(models.LogicFunction.id == logic_id).first()
    if not logic:
        _not_found("LogicFunction", logic_id)

    run_id = str(uuid.uuid4())
    try:
        result = execute_logic_blocks(db, logic_function=logic, inputs=request.inputs)
        status = "ACTION_PROPOSED" if result["proposed_actions"] else "SUCCESS"
        db_model = models.LogicRun(
            id=run_id,
            logic_function_id=logic.id,
            status=status,
            inputs=request.inputs,
            outputs=result["outputs"],
            trace=result["trace"],
            proposed_actions=result["proposed_actions"],
            created_at=now_ts(),
            completed_at=now_ts(),
        )
        db.add(db_model)
        create_audit_log(
            db,
            actor=request.actor,
            event_type="aip.logic.run_completed",
            subject_type="logic_run",
            subject_id=run_id,
            payload={"logic_function_id": logic.id, "status": status},
        )
        db.commit()
        db.refresh(db_model)
        return db_model
    except Exception as exc:
        db.rollback()
        db_model = models.LogicRun(
            id=run_id,
            logic_function_id=logic.id,
            status="FAILED",
            inputs=request.inputs,
            outputs={"error": str(exc)},
            trace=[],
            proposed_actions=[],
            created_at=now_ts(),
            completed_at=now_ts(),
        )
        db.add(db_model)
        db.commit()
        db.refresh(db_model)
        return db_model


@app.post("/automations", response_model=schemas.AutomationDefinition)
def create_automation(automation: schemas.AutomationDefinitionCreate, db: Session = Depends(get_db)):
    existing = db.query(models.AutomationDefinition).filter(models.AutomationDefinition.id == automation.id).first()
    if existing:
        raise HTTPException(status_code=400, detail="AutomationDefinition already exists")
    now = now_ts()
    db_model = models.AutomationDefinition(**automation.model_dump(), created_at=now, updated_at=now)
    db.add(db_model)
    create_audit_log(
        db,
        actor="system",
        event_type="automation.created",
        subject_type="automation",
        subject_id=automation.id,
        payload={"trigger": automation.trigger, "condition": automation.condition, "effect": automation.effect},
    )
    db.commit()
    db.refresh(db_model)
    return db_model


@app.get("/automations", response_model=List[schemas.AutomationDefinition])
def list_automations(db: Session = Depends(get_db)):
    return db.query(models.AutomationDefinition).all()


@app.post("/automations/{automation_id}/run", response_model=schemas.AutomationRun)
def run_automation(automation_id: str, actor: str = "automation", db: Session = Depends(get_db)):
    automation = db.query(models.AutomationDefinition).filter(models.AutomationDefinition.id == automation_id).first()
    if not automation:
        _not_found("AutomationDefinition", automation_id)

    result = evaluate_automation(db, automation=automation, actor=actor)
    run_id = str(uuid.uuid4())
    db_model = models.AutomationRun(
        id=run_id,
        automation_id=automation.id,
        status="TRIGGERED" if result["condition_result"] else "SKIPPED",
        condition_result=result["condition_result"],
        effect_result=result["effect_result"],
        created_at=now_ts(),
        completed_at=now_ts(),
    )
    db.add(db_model)
    create_audit_log(
        db,
        actor=actor,
        event_type="automation.run_completed",
        subject_type="automation_run",
        subject_id=run_id,
        payload=result,
    )
    db.commit()
    db.refresh(db_model)
    return db_model


@app.post("/eval-suites", response_model=schemas.EvalSuite)
def create_eval_suite(suite: schemas.EvalSuiteCreate, db: Session = Depends(get_db)):
    existing = db.query(models.EvalSuite).filter(models.EvalSuite.id == suite.id).first()
    if existing:
        raise HTTPException(status_code=400, detail="EvalSuite already exists")
    target_agent = db.query(models.AgentDefinition).filter(models.AgentDefinition.id == suite.target_agent_id).first()
    if not target_agent:
        _not_found("AgentDefinition", suite.target_agent_id)

    now = now_ts()
    db_model = models.EvalSuite(**suite.model_dump(), created_at=now, updated_at=now)
    db.add(db_model)
    create_audit_log(
        db,
        actor="system",
        event_type="eval.suite.created",
        subject_type="eval_suite",
        subject_id=suite.id,
        payload={"target_agent_id": suite.target_agent_id, "case_count": len(suite.cases)},
    )
    db.commit()
    db.refresh(db_model)
    return db_model


@app.get("/eval-suites", response_model=List[schemas.EvalSuite])
def list_eval_suites(db: Session = Depends(get_db)):
    return db.query(models.EvalSuite).all()


@app.post("/eval-suites/{suite_id}/run", response_model=schemas.EvalRun)
def run_eval_suite(suite_id: str, db: Session = Depends(get_db)):
    suite = db.query(models.EvalSuite).filter(models.EvalSuite.id == suite_id).first()
    if not suite:
        _not_found("EvalSuite", suite_id)
    agent = db.query(models.AgentDefinition).filter(models.AgentDefinition.id == suite.target_agent_id).first()
    if not agent:
        _not_found("AgentDefinition", suite.target_agent_id)

    run_id = str(uuid.uuid4())
    results = []
    scores = []
    for case in suite.cases or []:
        context, plan, proposed_actions, status = plan_agent_session(
            db,
            agent=agent,
            user_prompt=case.get("prompt", ""),
            filters=case.get("filters", {}),
            max_context_objects=int(case.get("max_context_objects", 5)),
        )
        session = models.AgentSession(
            id=str(uuid.uuid4()),
            agent_id=agent.id,
            user_prompt=case.get("prompt", ""),
            status=status,
            context=context,
            plan=plan,
            proposed_actions=proposed_actions,
            created_at=now_ts(),
            completed_at=now_ts(),
        )
        db.add(session)
        result = score_eval_case(session, case)
        results.append(result)
        scores.append(result["score"])

    score = int(sum(scores) / len(scores)) if scores else 0
    db_model = models.EvalRun(
        id=run_id,
        suite_id=suite.id,
        status="SUCCESS",
        score=score,
        results=results,
        created_at=now_ts(),
        completed_at=now_ts(),
    )
    db.add(db_model)
    create_audit_log(
        db,
        actor="system",
        event_type="eval.run.completed",
        subject_type="eval_run",
        subject_id=run_id,
        payload={"suite_id": suite.id, "score": score},
    )
    db.commit()
    db.refresh(db_model)
    return db_model


@app.get("/eval-runs", response_model=List[schemas.EvalRun])
def list_eval_runs(suite_id: Optional[str] = None, db: Session = Depends(get_db)):
    query = db.query(models.EvalRun)
    if suite_id:
        query = query.filter(models.EvalRun.suite_id == suite_id)
    return query.order_by(models.EvalRun.created_at.desc()).all()


@app.get("/audit-logs", response_model=List[schemas.AuditLog])
def list_audit_logs(limit: int = 100, db: Session = Depends(get_db)):
    return db.query(models_action.AuditLog).order_by(
        models_action.AuditLog.created_at.desc()
    ).limit(limit).all()

import uuid
from typing import Any, Dict, List

from sqlalchemy.orm import Session

from . import models
from .runtime import create_audit_log, now_ts


def _resource_summary(resource_type: str, resource_id: str, action: str) -> Dict[str, str]:
    return {"resource_type": resource_type, "id": resource_id, "action": action}


def _upsert_object_type(
    db: Session,
    *,
    id: str,
    display_name: str,
    description: str,
    properties: Dict[str, Any],
) -> Dict[str, str]:
    existing = db.query(models.ObjectType).filter(models.ObjectType.id == id).first()
    if existing:
        existing.display_name = display_name
        existing.description = description
        existing.properties = properties
        existing.updated_at = now_ts()
        return _resource_summary("object_type", id, "updated")

    db.add(models.ObjectType(
        id=id,
        display_name=display_name,
        description=description,
        properties=properties,
        created_at=now_ts(),
        updated_at=now_ts(),
    ))
    return _resource_summary("object_type", id, "created")


def _upsert_link_type(
    db: Session,
    *,
    id: str,
    display_name: str,
    source_object_type_id: str,
    target_object_type_id: str,
    cardinality: str,
) -> Dict[str, str]:
    existing = db.query(models.LinkType).filter(models.LinkType.id == id).first()
    payload = {
        "display_name": display_name,
        "source_object_type_id": source_object_type_id,
        "target_object_type_id": target_object_type_id,
        "cardinality": cardinality,
    }
    if existing:
        for key, value in payload.items():
            setattr(existing, key, value)
        return _resource_summary("link_type", id, "updated")

    db.add(models.LinkType(id=id, **payload))
    return _resource_summary("link_type", id, "created")


def _upsert_action_type(
    db: Session,
    *,
    id: str,
    display_name: str,
    description: str,
    parameters: Dict[str, Any],
    rules: Dict[str, Any],
) -> Dict[str, str]:
    existing = db.query(models.ActionType).filter(models.ActionType.id == id).first()
    payload = {
        "display_name": display_name,
        "description": description,
        "parameters": parameters,
        "rules": rules,
    }
    if existing:
        for key, value in payload.items():
            setattr(existing, key, value)
        return _resource_summary("action_type", id, "updated")

    db.add(models.ActionType(id=id, **payload))
    return _resource_summary("action_type", id, "created")


def _upsert_data_asset(
    db: Session,
    *,
    id: str,
    display_name: str,
    description: str,
    records: List[Dict[str, Any]],
    asset_schema: Dict[str, Any] | None = None,
) -> Dict[str, str]:
    existing = db.query(models.DataAsset).filter(models.DataAsset.id == id).first()
    if existing:
        existing.project_id = str((asset_schema or {}).get("project_id") or "default")
        existing.display_name = display_name
        existing.description = description
        existing.records = records
        existing.asset_schema = asset_schema or {}
        existing.updated_at = now_ts()
        return _resource_summary("data_asset", id, "updated")

    db.add(models.DataAsset(
        id=id,
        project_id=str((asset_schema or {}).get("project_id") or "default"),
        display_name=display_name,
        description=description,
        kind="dataset",
        asset_schema=asset_schema or {},
        records=records,
        created_at=now_ts(),
        updated_at=now_ts(),
    ))
    return _resource_summary("data_asset", id, "created")


def _upsert_pipeline(
    db: Session,
    *,
    id: str,
    display_name: str,
    description: str,
    input_asset_id: str,
    steps: List[Dict[str, Any]],
    output_asset_id: str | None = None,
) -> Dict[str, str]:
    existing = db.query(models.PipelineDefinition).filter(models.PipelineDefinition.id == id).first()
    payload = {
        "display_name": display_name,
        "description": description,
        "input_asset_id": input_asset_id,
        "output_asset_id": output_asset_id,
        "mode": "batch",
        "schedule": None,
        "steps": steps,
    }
    if existing:
        for key, value in payload.items():
            setattr(existing, key, value)
        existing.updated_at = now_ts()
        return _resource_summary("pipeline", id, "updated")

    db.add(models.PipelineDefinition(id=id, **payload, created_at=now_ts(), updated_at=now_ts()))
    return _resource_summary("pipeline", id, "created")


def _upsert_agent(
    db: Session,
    *,
    id: str,
    display_name: str,
    description: str,
    allowed_object_types: List[str],
    allowed_actions: List[str],
) -> Dict[str, str]:
    existing = db.query(models.AgentDefinition).filter(models.AgentDefinition.id == id).first()
    payload = {
        "display_name": display_name,
        "description": description,
        "system_prompt": (
            "You are a maintenance operations copilot. Use ontology context to prioritize work, "
            "propose safe operational actions, and require approval for high-risk mutations."
        ),
        "allowed_object_types": allowed_object_types,
        "allowed_actions": allowed_actions,
        "model_endpoint_id": None,
        "approval_required": True,
    }
    if existing:
        for key, value in payload.items():
            setattr(existing, key, value)
        existing.updated_at = now_ts()
        return _resource_summary("agent", id, "updated")

    db.add(models.AgentDefinition(id=id, **payload, created_at=now_ts(), updated_at=now_ts()))
    return _resource_summary("agent", id, "created")


def _upsert_logic_function(
    db: Session,
    *,
    id: str,
    display_name: str,
    description: str,
    blocks: List[Dict[str, Any]],
) -> Dict[str, str]:
    existing = db.query(models.LogicFunction).filter(models.LogicFunction.id == id).first()
    payload = {
        "display_name": display_name,
        "description": description,
        "blocks": blocks,
        "input_schema": {},
        "output_schema": {},
        "approval_required": True,
    }
    if existing:
        for key, value in payload.items():
            setattr(existing, key, value)
        existing.updated_at = now_ts()
        return _resource_summary("logic_function", id, "updated")

    db.add(models.LogicFunction(id=id, **payload, created_at=now_ts(), updated_at=now_ts()))
    return _resource_summary("logic_function", id, "created")


def _upsert_eval_suite(
    db: Session,
    *,
    id: str,
    display_name: str,
    description: str,
    target_agent_id: str,
    cases: List[Dict[str, Any]],
) -> Dict[str, str]:
    existing = db.query(models.EvalSuite).filter(models.EvalSuite.id == id).first()
    payload = {
        "display_name": display_name,
        "description": description,
        "target_agent_id": target_agent_id,
        "cases": cases,
        "criteria": {},
    }
    if existing:
        for key, value in payload.items():
            setattr(existing, key, value)
        existing.updated_at = now_ts()
        return _resource_summary("eval_suite", id, "updated")

    db.add(models.EvalSuite(id=id, **payload, created_at=now_ts(), updated_at=now_ts()))
    return _resource_summary("eval_suite", id, "created")


def _upsert_automation(
    db: Session,
    *,
    id: str,
    display_name: str,
    description: str,
    condition: Dict[str, Any],
    effect: Dict[str, Any],
) -> Dict[str, str]:
    existing = db.query(models.AutomationDefinition).filter(models.AutomationDefinition.id == id).first()
    payload = {
        "display_name": display_name,
        "description": description,
        "trigger": {"type": "manual_or_scheduled", "suggested_cron": "0 * * * *"},
        "condition": condition,
        "effect": effect,
        "enabled": True,
    }
    if existing:
        for key, value in payload.items():
            setattr(existing, key, value)
        existing.updated_at = now_ts()
        return _resource_summary("automation", id, "updated")

    db.add(models.AutomationDefinition(id=id, **payload, created_at=now_ts(), updated_at=now_ts()))
    return _resource_summary("automation", id, "created")


def bootstrap_maintenance_copilot(db: Session, *, actor: str = "system") -> Dict[str, Any]:
    """
    Create a complete, idempotent maintenance/facilities copilot demo domain.
    """
    resources: List[Dict[str, str]] = []

    resources.extend([
        _upsert_object_type(
            db,
            id="facility",
            display_name="Facility",
            description="Plant, warehouse, building, or operating site.",
            properties={
                "name": {"type": "string", "required": True},
                "region": {"type": "string"},
                "criticality": {"type": "string"},
                "geometry": {"type": "geometry"},
                "mgrs": {"type": "string"},
            },
        ),
        _upsert_object_type(
            db,
            id="asset",
            display_name="Asset",
            description="Maintainable equipment or infrastructure asset.",
            properties={
                "name": {"type": "string", "required": True},
                "facility_id": {"type": "string", "required": True},
                "asset_class": {"type": "string"},
                "status": {"type": "string"},
                "criticality": {"type": "string"},
                "geometry": {"type": "geometry"},
                "mgrs": {"type": "string"},
            },
        ),
        _upsert_object_type(
            db,
            id="technician",
            display_name="Technician",
            description="Person or crew that can perform maintenance work.",
            properties={
                "name": {"type": "string", "required": True},
                "skills": {"type": "array"},
                "shift": {"type": "string"},
                "available": {"type": "boolean"},
            },
        ),
        _upsert_object_type(
            db,
            id="part",
            display_name="Part",
            description="Spare part or consumable required for repair.",
            properties={
                "name": {"type": "string", "required": True},
                "sku": {"type": "string"},
                "on_hand": {"type": "integer"},
                "reorder_point": {"type": "integer"},
            },
        ),
        _upsert_object_type(
            db,
            id="purchase_request",
            display_name="Purchase Request",
            description="Request to procure missing maintenance parts.",
            properties={
                "part_id": {"type": "string", "required": True},
                "quantity": {"type": "integer", "required": True},
                "status": {"type": "string", "required": True},
                "reason": {"type": "string"},
            },
        ),
        _upsert_object_type(
            db,
            id="work_order",
            display_name="Work Order",
            description="Operational maintenance order or incident.",
            properties={
                "title": {"type": "string", "required": True},
                "asset_id": {"type": "string", "required": True},
                "status": {"type": "string", "required": True},
                "priority": {"type": "string"},
                "description": {"type": "string"},
                "summary": {"type": "string"},
                "assigned_technician_id": {"type": "string"},
                "escalated": {"type": "boolean"},
            },
        ),
    ])

    resources.extend([
        _upsert_link_type(
            db,
            id="facility_has_asset",
            display_name="Facility Has Asset",
            source_object_type_id="facility",
            target_object_type_id="asset",
            cardinality="ONE_TO_MANY",
        ),
        _upsert_link_type(
            db,
            id="asset_has_work_order",
            display_name="Asset Has Work Order",
            source_object_type_id="asset",
            target_object_type_id="work_order",
            cardinality="ONE_TO_MANY",
        ),
        _upsert_link_type(
            db,
            id="technician_assigned_work_order",
            display_name="Technician Assigned Work Order",
            source_object_type_id="technician",
            target_object_type_id="work_order",
            cardinality="ONE_TO_MANY",
        ),
    ])

    resources.extend([
        _upsert_action_type(
            db,
            id="assign_technician",
            display_name="Assign Technician",
            description="Assign an available technician to a work order.",
            parameters={
                "work_order_id": {"type": "string", "required": True},
                "technician_id": {"type": "string", "required": True},
            },
            rules={
                "requires_approval": False,
                "risk_level": "medium",
                "object_mutations": [
                    {
                        "object_type_id": "work_order",
                        "object_id_param": "work_order_id",
                        "set": {"assigned_technician_id": "$technician_id", "status": {"value": "ASSIGNED"}},
                    }
                ],
            },
        ),
        _upsert_action_type(
            db,
            id="escalate_work_order",
            display_name="Escalate Work Order",
            description="Escalate a high-risk work order for manager review.",
            parameters={
                "work_order_id": {"type": "string", "required": True},
                "reason": {"type": "string", "required": True},
            },
            rules={
                "requires_approval": True,
                "risk_level": "high",
                "object_mutations": [
                    {
                        "object_type_id": "work_order",
                        "object_id_param": "work_order_id",
                        "set": {"escalated": {"value": True}, "priority": {"value": "critical"}, "summary": "$reason"},
                    }
                ],
            },
        ),
        _upsert_action_type(
            db,
            id="create_purchase_request",
            display_name="Create Purchase Request",
            description="Create a purchase request for a missing maintenance part.",
            parameters={
                "purchase_request_id": {"type": "string", "required": True},
                "part_id": {"type": "string", "required": True},
                "quantity": {"type": "integer", "required": True},
                "reason": {"type": "string", "required": True},
            },
            rules={
                "requires_approval": True,
                "risk_level": "high",
                "object_mutations": [
                    {
                        "object_type_id": "purchase_request",
                        "object_id_param": "purchase_request_id",
                        "create_if_missing": True,
                        "set": {
                            "part_id": "$part_id",
                            "quantity": "$quantity",
                            "status": {"value": "PENDING_APPROVAL"},
                            "reason": "$reason",
                        },
                    }
                ],
            },
        ),
        _upsert_action_type(
            db,
            id="close_work_order",
            display_name="Close Work Order",
            description="Close a maintenance work order with resolution notes.",
            parameters={
                "work_order_id": {"type": "string", "required": True},
                "resolution": {"type": "string", "required": True},
            },
            rules={
                "requires_approval": True,
                "risk_level": "high",
                "object_mutations": [
                    {
                        "object_type_id": "work_order",
                        "object_id_param": "work_order_id",
                        "set": {"status": {"value": "CLOSED"}, "summary": "$resolution"},
                    }
                ],
            },
        ),
    ])

    raw_assets = [
        {"id": "facility_1", "kind": "facility", "name": "Line 4 Plant", "region": "West", "criticality": "high", "longitude": -122.4019, "latitude": 37.7921},
        {"id": "asset_pump_4", "kind": "asset", "name": "Line 4 Pump", "facility_id": "facility_1", "asset_class": "pump", "status": "DEGRADED", "criticality": "high", "longitude": -122.4012, "latitude": 37.7924},
        {"id": "asset_chiller_2", "kind": "asset", "name": "Chiller 2", "facility_id": "facility_1", "asset_class": "chiller", "status": "RUNNING", "criticality": "medium", "longitude": -122.4072, "latitude": 37.7893},
        {"id": "tech_amy", "kind": "technician", "name": "Amy Chen", "skills": ["pump", "electrical"], "shift": "day", "available": True},
        {"id": "part_seal_kit", "kind": "part", "name": "Pump Seal Kit", "sku": "SEAL-44", "on_hand": 0, "reorder_point": 2},
    ]
    raw_work_orders = [
        {
            "id": "wo_pump_urgent",
            "asset_id": "asset_pump_4",
            "title": "Line 4 pump vibration",
            "status": "OPEN",
            "description": "Urgent vibration issue affecting production throughput. Pump seal kit likely required.",
        },
        {
            "id": "wo_chiller_inspect",
            "asset_id": "asset_chiller_2",
            "title": "Routine chiller inspection",
            "status": "OPEN",
            "description": "Scheduled inspection, no immediate operating risk.",
        },
    ]

    resources.extend([
        _upsert_data_asset(
            db,
            id="maintenance_raw_assets",
            display_name="Maintenance Raw Assets",
            description="Seed facilities, assets, technicians, and parts.",
            records=raw_assets,
        ),
        _upsert_data_asset(
            db,
            id="maintenance_raw_work_orders",
            display_name="Maintenance Raw Work Orders",
            description="Seed maintenance work order records.",
            records=raw_work_orders,
        ),
    ])

    resources.extend([
        _upsert_pipeline(
            db,
            id="hydrate_maintenance_facilities",
            display_name="Hydrate Maintenance Facilities",
            description="Hydrate facility records into the ontology.",
            input_asset_id="maintenance_raw_assets",
            steps=[
                {"operation": "filter", "field": "kind", "equals": "facility"},
                {"operation": "derive_geo_point", "longitude_field": "longitude", "latitude_field": "latitude", "target_field": "geometry"},
                {"operation": "derive_mgrs", "geometry_field": "geometry", "target_field": "mgrs", "precision": 5},
                {
                    "operation": "map_to_ontology",
                    "object_type_id": "facility",
                    "object_id_field": "id",
                    "property_map": {"name": "$name", "region": "$region", "criticality": "$criticality", "geometry": "$geometry", "mgrs": "$mgrs"},
                },
            ],
        ),
        _upsert_pipeline(
            db,
            id="hydrate_maintenance_assets",
            display_name="Hydrate Maintenance Assets",
            description="Hydrate asset records into the ontology.",
            input_asset_id="maintenance_raw_assets",
            steps=[
                {"operation": "filter", "field": "kind", "equals": "asset"},
                {"operation": "derive_geo_point", "longitude_field": "longitude", "latitude_field": "latitude", "target_field": "geometry"},
                {"operation": "derive_mgrs", "geometry_field": "geometry", "target_field": "mgrs", "precision": 5},
                {
                    "operation": "map_to_ontology",
                    "object_type_id": "asset",
                    "object_id_field": "id",
                    "property_map": {
                        "name": "$name",
                        "facility_id": "$facility_id",
                        "asset_class": "$asset_class",
                        "status": "$status",
                        "criticality": "$criticality",
                        "geometry": "$geometry",
                        "mgrs": "$mgrs",
                    },
                },
            ],
        ),
        _upsert_pipeline(
            db,
            id="hydrate_maintenance_technicians",
            display_name="Hydrate Maintenance Technicians",
            description="Hydrate technician records into the ontology.",
            input_asset_id="maintenance_raw_assets",
            steps=[
                {"operation": "filter", "field": "kind", "equals": "technician"},
                {
                    "operation": "map_to_ontology",
                    "object_type_id": "technician",
                    "object_id_field": "id",
                    "property_map": {"name": "$name", "skills": "$skills", "shift": "$shift", "available": "$available"},
                },
            ],
        ),
        _upsert_pipeline(
            db,
            id="hydrate_maintenance_parts",
            display_name="Hydrate Maintenance Parts",
            description="Hydrate spare parts into the ontology.",
            input_asset_id="maintenance_raw_assets",
            steps=[
                {"operation": "filter", "field": "kind", "equals": "part"},
                {
                    "operation": "map_to_ontology",
                    "object_type_id": "part",
                    "object_id_field": "id",
                    "property_map": {"name": "$name", "sku": "$sku", "on_hand": "$on_hand", "reorder_point": "$reorder_point"},
                },
            ],
        ),
        _upsert_pipeline(
            db,
            id="hydrate_maintenance_work_orders",
            display_name="Hydrate Maintenance Work Orders",
            description="Classify and hydrate maintenance work orders.",
            input_asset_id="maintenance_raw_work_orders",
            steps=[
                {"operation": "normalize", "fields": ["title", "description"]},
                {
                    "operation": "classify",
                    "field": "description",
                    "target_field": "priority",
                    "labels": {"critical": ["urgent", "production"], "normal": ["scheduled", "inspection"]},
                    "default": "normal",
                },
                {"operation": "summarize", "field": "description", "target_field": "summary", "max_chars": 100},
                {
                    "operation": "map_to_ontology",
                    "object_type_id": "work_order",
                    "object_id_field": "id",
                    "property_map": {
                        "title": "$title",
                        "asset_id": "$asset_id",
                        "status": "$status",
                        "priority": "$priority",
                        "description": "$description",
                        "summary": "$summary",
                    },
                },
            ],
        ),
    ])

    resources.extend([
        _upsert_agent(
            db,
            id="maintenance_ops_agent",
            display_name="Maintenance Operations Agent",
            description="Agent for triage, assignment, escalation, and parts procurement.",
            allowed_object_types=["facility", "asset", "technician", "part", "work_order", "purchase_request"],
            allowed_actions=["assign_technician", "escalate_work_order", "create_purchase_request", "close_work_order"],
        ),
        _upsert_logic_function(
            db,
            id="maintenance_triage_logic",
            display_name="Maintenance Triage Logic",
            description="Retrieve maintenance context and propose an escalation when high-risk work appears.",
            blocks=[
                {"type": "retrieve_context", "object_types": ["work_order", "asset", "technician", "part"], "output": "context", "limit": 10},
                {"type": "assist", "prompt": "$prompt", "output": "assist"},
                {
                    "type": "propose_action",
                    "action_type_id": "escalate_work_order",
                    "parameters": {"work_order_id": "$work_order_id", "reason": "$reason"},
                    "output": "escalation",
                },
            ],
        ),
        _upsert_eval_suite(
            db,
            id="maintenance_ops_agent_eval",
            display_name="Maintenance Ops Agent Eval",
            description="Checks that the maintenance agent retrieves work orders and proposes escalation.",
            target_agent_id="maintenance_ops_agent",
            cases=[
                {
                    "id": "urgent_work_order_escalation",
                    "prompt": "Please escalate work order for urgent pump issue",
                    "expected_actions": ["escalate_work_order"],
                    "expected_context_object_types": ["work_order"],
                }
            ],
        ),
        _upsert_automation(
            db,
            id="maintenance_critical_work_order_monitor",
            display_name="Critical Work Order Monitor",
            description="Monitor critical open work orders and stage escalation approval.",
            condition={
                "type": "object_count",
                "object_type_id": "work_order",
                "filters": {"priority": "critical", "status": "OPEN"},
                "operator": ">=",
                "threshold": 1,
            },
            effect={
                "type": "request_approval",
                "action_type_id": "escalate_work_order",
                "parameters": {
                    "work_order_id": "wo_pump_urgent",
                    "reason": "Critical production-impacting maintenance work order detected.",
                },
            },
        ),
    ])

    create_audit_log(
        db,
        actor=actor,
        event_type="domain.maintenance.bootstrapped",
        subject_type="domain",
        subject_id="maintenance_copilot",
        payload={"resources": resources},
    )
    db.commit()

    return {
        "domain": "maintenance_copilot",
        "resources": resources,
        "recommended_pipeline_order": [
            "hydrate_maintenance_facilities",
            "hydrate_maintenance_assets",
            "hydrate_maintenance_technicians",
            "hydrate_maintenance_parts",
            "hydrate_maintenance_work_orders",
        ],
        "agent_id": "maintenance_ops_agent",
        "logic_function_id": "maintenance_triage_logic",
        "eval_suite_id": "maintenance_ops_agent_eval",
        "automation_id": "maintenance_critical_work_order_monitor",
    }


def maintenance_summary(db: Session) -> Dict[str, Any]:
    object_types = ["facility", "asset", "technician", "part", "work_order", "purchase_request"]
    counts = {
        object_type_id: db.query(models.ObjectInstance).filter(
            models.ObjectInstance.object_type_id == object_type_id
        ).count()
        for object_type_id in object_types
    }

    open_work_orders = [
        {
            "id": item.id,
            "title": (item.properties or {}).get("title"),
            "priority": (item.properties or {}).get("priority"),
            "status": (item.properties or {}).get("status"),
            "asset_id": (item.properties or {}).get("asset_id"),
        }
        for item in db.query(models.ObjectInstance).filter(
            models.ObjectInstance.object_type_id == "work_order"
        ).all()
        if (item.properties or {}).get("status") != "CLOSED"
    ]

    return {
        "domain": "maintenance_copilot",
        "object_counts": counts,
        "open_work_orders": open_work_orders,
        "agent_id": "maintenance_ops_agent",
        "logic_function_id": "maintenance_triage_logic",
        "eval_suite_id": "maintenance_ops_agent_eval",
        "automation_id": "maintenance_critical_work_order_monitor",
    }

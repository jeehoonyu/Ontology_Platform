"""
Docs-grounded conformance harness.

This test validates that the local deterministic platform implements the key
public Foundry/AIP ideas as behavior: ontology objects, governed actions,
Workshop, Object Explorer, Pipeline Builder, GIS, ModelOps, Decision, Ops,
Reliability, and Investigations. It does not compare proprietary code or claim
Palantir API compatibility.

Run:
  python test_docs_conformance.py
"""
from __future__ import annotations

import os
from pathlib import Path
import tempfile


tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tmpdir.name, 'docs_conformance.db')}"

from fastapi.testclient import TestClient  # noqa: E402
from app.main import app  # noqa: E402


client = TestClient(app)
passed = 0


def ok(resp, label: str, expect: int = 200):
    global passed
    success = resp.status_code == expect or (expect == 200 and 200 <= resp.status_code < 300)
    assert success, f"{label}: expected {expect}, got {resp.status_code} -> {resp.text[:1000]}"
    passed += 1
    return resp.json() if resp.content else {}


def assert_true(condition, label: str, payload=None):
    global passed
    assert condition, f"{label}: {payload}"
    passed += 1


def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------------------
# Evidence artifacts and workspace routes
# ---------------------------------------------------------------------------
matrix = repo_root() / "foundry-docs" / "VALIDATION_MATRIX.md"
report = repo_root() / "foundry-docs" / "VALIDATION_REPORT.md"
assert_true(matrix.exists(), "validation matrix exists", matrix)
assert_true(report.exists(), "validation report exists", report)
matrix_text = matrix.read_text(encoding="utf-8")
report_text = report.read_text(encoding="utf-8")
for required in ("MATCH", "LOCAL_ANALOG", "INTENTIONAL_DIFFERENCE", "Pipeline Builder", "Object Explorer", "Ontology Generator"):
    assert_true(required in matrix_text, f"matrix includes {required}")
assert_true("does not copy Palantir code" in report_text, "report states non-copying boundary")
assert_true("not Palantir Foundry API compatibility" in report_text, "report states API boundary")

for route in (
    "/workspace/aip",
    "/workspace/map",
    "/workspace/workshop",
    "/workspace/object-explorer",
    "/workspace/pipeline",
    "/workspace/search",
    "/workspace/graph",
    "/workspace/command-center",
    "/workspace/models",
    "/workspace/decision",
    "/workspace/ops",
    "/workspace/investigations",
):
    resp = client.get(route)
    assert_true(resp.status_code == 200, f"workspace route {route} loads", resp.status_code)


# ---------------------------------------------------------------------------
# Ontology, object graph, actions, approvals, and auditability
# ---------------------------------------------------------------------------
ok(client.post("/object-types", json={
    "id": "asset",
    "display_name": "Asset",
    "description": "Operational asset",
    "properties": {
        "name": {"type": "string"},
        "status": {"type": "string"},
        "criticality": {"type": "string"},
        "score": {"type": "number"},
        "geometry": {"type": "geometry"},
        "mgrs": {"type": "string"},
        "flagged": {"type": "boolean"},
    },
}), "create asset object type")
ok(client.post("/object-types", json={
    "id": "work_order",
    "display_name": "Work Order",
    "description": "Maintenance work order",
    "properties": {
        "title": {"type": "string"},
        "status": {"type": "string"},
        "priority": {"type": "string"},
    },
}), "create work order object type")

encoded = ok(client.post("/gis/mgrs/encode", json={
    "latitude": 37.7924,
    "longitude": -122.4012,
    "precision": 5,
}), "encode MGRS")
assert_true(encoded["mgrs"].startswith("10S"), "MGRS is in expected zone", encoded)
decoded = ok(client.post("/gis/mgrs/decode", json={"mgrs": encoded["mgrs"]}), "decode MGRS")
assert_true(abs(decoded["latitude"] - 37.7924) < 0.0002, "MGRS decode latitude round trips", decoded)

for object_id, name, status, criticality, score, lon, lat in [
    ("asset_pump_4", "Line 4 Pump", "DEGRADED", "high", 92, -122.4012, 37.7924),
    ("asset_chiller_2", "Chiller 2", "RUNNING", "medium", 40, -122.3980, 37.7905),
]:
    ok(client.post("/objects", json={
        "id": object_id,
        "object_type_id": "asset",
        "properties": {
            "name": name,
            "status": status,
            "criticality": criticality,
            "score": score,
            "geometry": {"type": "Point", "coordinates": [lon, lat]},
            "mgrs": encoded["mgrs"],
            "flagged": False,
        },
    }), f"create {object_id}")

ok(client.post("/objects", json={
    "id": "wo_pump_urgent",
    "object_type_id": "work_order",
    "properties": {"title": "Inspect pump", "status": "OPEN", "priority": "high"},
}), "create work order")
ok(client.post("/link-types", json={
    "id": "asset_has_work_order",
    "display_name": "Asset has Work Order",
    "description": "Open work linked to an asset",
    "source_object_type_id": "asset",
    "target_object_type_id": "work_order",
    "cardinality": "ONE_TO_MANY",
}), "create link type")
ok(client.post("/links", json={
    "link_type_id": "asset_has_work_order",
    "source_object_id": "asset_pump_4",
    "target_object_id": "wo_pump_urgent",
}), "create link")

ok(client.post("/action-types", json={
    "id": "escalate_asset",
    "display_name": "Escalate Asset",
    "description": "Approval-gated escalation",
    "parameters": {
        "asset_id": {"type": "string", "required": True},
        "reason": {"type": "string", "required": True},
    },
    "rules": {
        "requires_approval": True,
        "object_mutations": [
            {"object_type_id": "asset", "object_id": "$asset_id", "set": {"flagged": True, "status": "ESCALATED"}}
        ],
    },
}), "create governed action")

profile = ok(client.get("/objects/asset/asset_pump_4/profile"), "object profile")
assert_true(profile["metrics"]["outbound_link_count"] == 1, "object profile includes linked work order", profile)
validation = ok(client.get("/ontology/validate"), "ontology validate")
assert_true(validation["status"] == "PASS", "ontology validation passes", validation)

staged = ok(client.post("/actions/execute", json={
    "action_type_id": "escalate_asset",
    "parameters": {"asset_id": "asset_pump_4", "reason": "docs conformance"},
    "idempotency_key": "docs-escalate-stage",
    "actor": "docs",
}), "stage approval-gated action")
assert_true(staged["status"] == "REQUIRES_APPROVAL", "high-risk action requires approval", staged)
approval_id = staged["approval_request_id"]
approved = ok(client.post(f"/approvals/{approval_id}/decision", json={
    "actor": "reviewer",
    "decision": "APPROVED",
    "reason": "docs conformance",
}), "approve staged action")
assert_true(approved["status"] == "APPROVED", "approval decision recorded", approved)
executed = ok(client.post("/actions/execute", json={
    "action_type_id": "escalate_asset",
    "parameters": {"asset_id": "asset_pump_4", "reason": "docs conformance"},
    "idempotency_key": "docs-escalate-execute",
    "actor": "docs",
    "approval_request_id": approval_id,
}), "execute approved action")
assert_true("asset_pump_4" in executed["mutated_object_ids"], "approved action mutates object", executed)
asset_after_action = ok(client.get("/objects/asset/asset_pump_4"), "read escalated asset")
assert_true(asset_after_action["properties"]["flagged"] is True, "action mutation persisted", asset_after_action)

root = ok(client.get("/"), "root capability catalog")
for capability in ("unified_event_bus", "global_search", "policy_simulation", "shared_activity_timeline", "platform_graph_overview"):
    assert_true(capability in root["capabilities"], f"root advertises {capability}", root["capabilities"])
assert_true("asset_reliability_command_center" in root["capabilities"], "root advertises asset reliability MVP", root["capabilities"])
assert_true("ontology_generator" in root["capabilities"], "root advertises ontology generator", root["capabilities"])
scenario = ok(client.post("/scenarios/asset-reliability/bootstrap", json={"actor": "docs", "run_pipelines": True, "run_checks": True}), "asset reliability command-center bootstrap")
assert_true(scenario["data_contract_run"]["status"] == "FAIL", "command-center data contract catches seeded issue", scenario["data_contract_run"])
assert_true(scenario["model_monitor_run"]["status"] in {"WARN", "FAIL"}, "command-center model monitor catches seeded issue", scenario["model_monitor_run"])
scenario_triage = ok(client.post("/scenarios/asset-reliability/run-triage", json={"actor": "docs"}), "asset reliability guided triage")
assert_true(scenario_triage["status"] == "APPROVAL_REQUIRED", "command-center triage stages approval", scenario_triage)
assert_true(scenario_triage["risk"]["band"] == "critical", "command-center triage explains critical risk", scenario_triage["risk"])
scenario_dashboard = ok(client.get("/scenarios/asset-reliability/validation-dashboard"), "asset reliability validation dashboard")
assert_true(scenario_dashboard["row_count"] >= 20, "validation dashboard reads matrix", scenario_dashboard)
platform_event = ok(client.post("/events/publish", json={
    "source": "docs",
    "event_type": "conformance.object.reviewed",
    "severity": "medium",
    "title": "Docs conformance reviewed asset",
    "subject_type": "object",
    "subject_id": "asset_pump_4",
    "object_type_id": "asset",
    "object_id": "asset_pump_4",
    "payload": {"workflow": "docs-conformance"},
}), "publish platform event")
assert_true(platform_event["object_id"] == "asset_pump_4", "event bus records object context", platform_event)
platform_search = ok(client.post("/search/query", json={
    "q": "pump",
    "limit": 20,
    "include_payload": False,
}), "global platform search")
assert_true(any(row["kind"] == "object" and row["id"] == "asset_pump_4" for row in platform_search["results"]), "global search finds ontology object", platform_search)
ok(client.post("/policies", json={
    "id": "docs_asset_mask_policy",
    "display_name": "Docs Asset Mask Policy",
    "effect": "MASK",
    "principal": "docs",
    "action": "read",
    "resource_kind": "object",
    "object_type_id": "asset",
    "mask_properties": ["score"],
}), "create platform policy")
policy_decision = ok(client.post("/policies/evaluate", json={
    "principal": "docs",
    "action": "read",
    "resource_kind": "object",
    "resource_id": "asset_pump_4",
    "object_type_id": "asset",
    "purpose": "validation",
}), "evaluate platform policy")
assert_true(policy_decision["decision"] == "ALLOW_WITH_MASKS" and "score" in policy_decision["masks"], "policy engine returns masking decision", policy_decision)
activity = ok(client.get("/activity/objects/asset/asset_pump_4/timeline"), "shared object activity timeline")
assert_true(activity["timeline"], "shared activity timeline has entries", activity)
platform_graph = ok(client.get("/graph/overview"), "platform graph overview")
assert_true(platform_graph["node_count"] >= 3 and platform_graph["edge_count"] >= 1, "platform graph includes ontology resources", platform_graph)


# ---------------------------------------------------------------------------
# Object Explorer and GIS
# ---------------------------------------------------------------------------
search = ok(client.post("/object-sets/search", json={
    "object_type_id": "asset",
    "filters": {"criticality": "high"},
}), "object-set search")
assert_true(search["count"] == 1, "object-set filter finds high criticality asset", search)
aggregate = ok(client.post("/object-sets/aggregate", json={
    "object_type_id": "asset",
    "group_by": "criticality",
    "metrics": [{"operation": "count", "alias": "n"}],
}), "object-set aggregate")
assert_true(aggregate["groups"], "object-set aggregation returns groups", aggregate)
around = ok(client.post("/object-sets/search-around", json={
    "object_ids": ["asset_pump_4"],
    "link_type_id": "asset_has_work_order",
    "direction": "outgoing",
    "depth": 1,
}), "search around")
assert_true(any(node["id"] == "wo_pump_urgent" for node in around["nodes"]), "search-around traverses links", around)
saved = ok(client.post("/object-sets/saved", json={
    "id": "critical_assets_docs",
    "display_name": "Critical Assets Docs",
    "description": "Docs conformance saved set",
    "object_type_id": "asset",
    "filters": {"criticality": "high"},
    "owner": "docs",
}), "save object set")
assert_true(saved["id"] == "critical_assets_docs", "saved object set created", saved)
explorer = ok(client.post("/object-explorer/query", json={
    "object_type_id": "asset",
    "filters": {"criticality": "high"},
    "columns": ["name", "status", "score"],
    "chart_fields": ["status", "score"],
    "selected_ids": ["asset_pump_4"],
}), "object explorer query")
assert_true(explorer["result_count"] == 1 and explorer["facets"], "explorer returns facets", explorer)
histogram = ok(client.post("/object-explorer/histogram", json={
    "object_type_id": "asset",
    "field": "score",
    "bins": 4,
}), "object explorer histogram")
assert_true(histogram["type"] == "numeric", "histogram is numeric", histogram)
stats = ok(client.post("/object-explorer/property-stats", json={
    "object_type_id": "asset",
    "field": "criticality",
}), "object explorer property stats")
assert_true(stats["distinct"] >= 2, "property stats include distribution", stats)
exploration = ok(client.post("/object-explorer/explorations", json={
    "id": "docs_asset_exploration",
    "display_name": "Docs Asset Exploration",
    "object_type_id": "asset",
    "filters": {"criticality": "high"},
    "columns": ["name", "status", "score"],
    "charts": explorer["facets"],
}), "save exploration", expect=201)
assert_true(exploration["id"] == "docs_asset_exploration", "saved exploration created", exploration)

spatial = ok(client.post("/gis/spatial-query", json={
    "object_type_id": "asset",
    "near": {"type": "Point", "coordinates": [-122.4012, 37.7924]},
    "radius_meters": 500,
}), "GIS radius query")
assert_true(spatial["count"] >= 1, "GIS radius query finds assets", spatial)
feature_collection = ok(client.post("/gis/feature-collection", json={
    "object_type_id": "asset",
}), "GIS feature collection")
assert_true(feature_collection["type"] == "FeatureCollection", "feature collection exported", feature_collection)
geofence = ok(client.post("/gis/geofence/evaluate", json={
    "object_type_id": "asset",
    "bbox": [-122.405, 37.789, -122.397, 37.794],
}), "GIS geofence")
assert_true(geofence["summary"]["inside"] >= 1, "geofence classifies inside objects", geofence)
layer = ok(client.post("/gis/map-layers", json={
    "id": "critical_asset_docs_layer",
    "display_name": "Critical Asset Docs Layer",
    "description": "Docs conformance map layer",
    "object_type_id": "asset",
    "saved_object_set_id": "critical_assets_docs",
    "geometry_field": "geometry",
    "style": {"marker_color": "#d43f3a"},
    "owner": "docs",
}), "create map layer")
layer_features = ok(client.get(f"/gis/map-layers/{layer['id']}/features"), "render map layer")
assert_true(layer_features["metadata"]["feature_count"] == 1, "map layer renders saved set", layer_features)


# ---------------------------------------------------------------------------
# Data health, Pipeline Builder, Workshop, and AIP Logic
# ---------------------------------------------------------------------------
ok(client.post("/data-assets", json={
    "id": "raw_orders_docs",
    "display_name": "Raw Orders Docs",
    "kind": "dataset",
    "asset_schema": {},
    "records": [
        {"order_id": "o1", "asset_id": "asset_pump_4", "amount": 10, "status": "open"},
        {"order_id": "o2", "asset_id": "asset_pump_4", "amount": 20, "status": "open"},
        {"order_id": "o3", "asset_id": "asset_chiller_2", "amount": 5, "status": "closed"},
    ],
}), "create raw orders asset")
health = ok(client.post("/data-assets/raw_orders_docs/expectations/run", json={
    "expectations": {
        "row_count_min": 1,
        "required_fields": ["order_id", "asset_id", "amount", "status"],
        "non_null": ["order_id"],
        "allowed_values": {"status": ["open", "closed"]},
        "min": {"amount": 0},
    }
}), "run data expectations")
assert_true(health["status"] == "PASS", "data expectations pass", health)

graph = ok(client.post("/pipeline-builder/graphs", json={
    "id": "docs_orders_graph",
    "display_name": "Docs Orders Graph",
    "nodes": [
        {"id": "input", "type": "input_dataset", "config": {"asset_id": "raw_orders_docs"}},
        {"id": "filter", "type": "filter", "config": {"filters": {"status": "open"}}},
        {"id": "aggregate", "type": "aggregate", "config": {
            "group_by": ["asset_id"],
            "metrics": [
                {"operation": "sum", "field": "amount", "alias": "total"},
                {"operation": "count", "alias": "n"},
            ],
        }},
        {"id": "output", "type": "dataset_output", "config": {"asset_id": "docs_orders_output"}},
    ],
    "edges": [
        {"source": "input", "target": "filter"},
        {"source": "filter", "target": "aggregate"},
        {"source": "aggregate", "target": "output"},
    ],
}), "create pipeline builder graph", expect=201)
assert_true(graph["id"] == "docs_orders_graph", "pipeline graph created", graph)
graph_validation = ok(client.post("/pipeline-builder/graphs/docs_orders_graph/validate"), "validate pipeline graph")
assert_true(graph_validation["status"] == "VALID", "pipeline graph validates", graph_validation)
preview = ok(client.post("/pipeline-builder/graphs/docs_orders_graph/preview", json={"limit": 10}), "preview pipeline graph")
assert_true(preview["row_count"] == 1 and preview["rows"][0]["total"] == 30, "pipeline preview is deterministic", preview)
delivery = ok(client.post("/pipeline-builder/graphs/docs_orders_graph/deliver", json={"actor": "docs"}), "deliver pipeline graph")
assert_true(delivery["status"] == "DELIVERED", "pipeline graph delivered", delivery)
output_asset = ok(client.get("/data-assets/docs_orders_output"), "read delivered dataset")
assert_true(output_asset["records"][0]["total"] == 30, "delivered dataset contains output", output_asset)
node_types = ok(client.get("/pipeline-builder/node-types"), "pipeline builder node type catalog")
assert_true(any(node["type"] == "ontology_output" for node in node_types["node_types"]), "node catalog includes ontology output", node_types)
generator_draft = ok(client.post("/ontology-generator/drafts", json={
    "id": "docs_order_event_draft",
    "asset_id": "raw_orders_docs",
    "display_name": "Order Event",
    "object_type_id": "order_event",
    "include_actions": True,
    "create_pipeline_graph": True,
}), "create ontology generator draft", expect=201)
assert_true(generator_draft["draft"]["primary_key"] == "orderId", "ontology generator infers primary key", generator_draft["draft"])
generator_validation = ok(client.post("/ontology-generator/drafts/docs_order_event_draft/validate"), "validate ontology generator draft")
assert_true(generator_validation["status"] in {"PASS", "WARN"}, "ontology generator draft validates", generator_validation)
generator_apply = ok(client.post("/ontology-generator/drafts/docs_order_event_draft/apply", json={"actor": "docs", "create_actions": True, "create_pipeline_graph": True}), "apply ontology generator draft")
assert_true(generator_apply["pipeline_graph_id"] == "order_event_ontology_graph", "ontology generator creates pipeline graph", generator_apply)
generator_delivery = ok(client.post("/pipeline-builder/graphs/order_event_ontology_graph/deliver", json={"actor": "docs"}), "deliver generator ontology graph")
assert_true(generator_delivery["metrics"]["materialized_objects"] == 3, "generated ontology graph materializes objects", generator_delivery)
order_events = ok(client.get("/objects/order_event"), "read generated order event objects")
assert_true(any(row["id"] == "o1" and row["properties"]["orderId"] == "o1" for row in order_events), "generated objects use mapped primary key", order_events)
ontology_html = client.get("/workspace/ontology").text
pipeline_html = client.get("/workspace/pipeline").text
assert_true("Ontology Generator" in ontology_html and "d3@7.9.0" in pipeline_html, "workspace HTML includes generator and D3 canvas library")

workshop = ok(client.post("/apps/workshop", json={
    "id": "docs_workshop",
    "display_name": "Docs Workshop",
    "variables": {
        "criticalAssets": {"definition_type": "object_set", "object_type_id": "asset", "filters": {"criticality": "high"}},
        "assetCount": {"definition_type": "object_set_aggregation", "object_type_id": "asset", "op": "count"},
        "selectedAsset": {"definition_type": "state", "key": "selectedAsset", "default": "asset_pump_4"},
        "selectedStatus": {"definition_type": "object_property", "object_id_var": "selectedAsset", "property": "status"},
    },
    "widgets": [
        {"type": "metric", "title": "Assets", "variable": "assetCount"},
        {"type": "object_table", "title": "Critical Assets", "variable": "criticalAssets"},
        {"type": "text", "title": "Selected Status", "variable": "selectedStatus"},
    ],
    "layout": {"columns": 2},
}), "create Workshop module")
render = ok(client.post("/apps/workshop/docs_workshop/render-live", json={"state": {}}), "render Workshop live")
assert_true(render["widgets"][0]["value"] == 2, "Workshop metric resolves variables", render)
event = ok(client.post("/apps/workshop/docs_workshop/event", json={
    "state": {},
    "events": [{"type": "set_variable", "target": "selectedAsset", "value": "asset_chiller_2"}],
}), "run Workshop event")
assert_true(event["state"]["selectedAsset"] == "asset_chiller_2", "Workshop event updates state", event)
version = ok(client.post("/apps/workshop/docs_workshop/publish", json={"actor": "docs", "note": "validation"}), "publish Workshop")
restored = ok(client.post(f"/apps/workshop/docs_workshop/versions/{version['id']}/restore", json={"actor": "docs"}), "restore Workshop")
assert_true(restored["id"] == "docs_workshop", "Workshop version restore works", restored)

logic = ok(client.post("/logic-functions", json={
    "id": "docs_logic",
    "display_name": "Docs Logic",
    "description": "Docs conformance AIP Logic",
    "approval_required": True,
    "input_schema": {"asset_id": {"type": "string"}},
    "blocks": [
        {"type": "object_query", "object_type_id": "asset", "filters": {"criticality": "high"}, "output": "critical_assets"},
        {"type": "object_aggregate", "object_type_id": "asset", "op": "count", "filters": {"criticality": "high"}, "output": "critical_count"},
        {"type": "llm", "mode": "template", "template": "Review {asset_id}", "output": "recommendation"},
        {
            "type": "propose_action",
            "action_type_id": "escalate_asset",
            "parameters": {"asset_id": "$asset_id", "reason": "AIP Logic recommendation"},
            "output": "proposal",
        },
    ],
}), "create AIP Logic function")
logic_run = ok(client.post(f"/logic-functions/{logic['id']}/run", json={
    "inputs": {"asset_id": "asset_pump_4"},
    "actor": "docs",
}), "run AIP Logic function")
assert_true(logic_run["status"] == "ACTION_PROPOSED", "AIP Logic proposes action", logic_run)
assert_true(logic_run["outputs"]["critical_count"]["value"] == 1, "AIP Logic aggregates object set", logic_run["outputs"])


# ---------------------------------------------------------------------------
# Decision, Ops, Reliability, Investigations, and ModelOps local analogs
# ---------------------------------------------------------------------------
ok(client.post("/decision/rules", json={
    "id": "docs_degraded_rule",
    "display_name": "Degraded asset",
    "object_type_id": "asset",
    "expression": {"field": "status", "op": "eq", "value": "ESCALATED"},
    "severity": "high",
    "recommended_actions": ["review_asset"],
}), "create decision rule")
ok(client.post("/decision/scorecards", json={
    "id": "docs_asset_scorecard",
    "display_name": "Docs Asset Scorecard",
    "object_type_id": "asset",
    "features": [
        {"rule_id": "docs_degraded_rule", "weight": 70, "reason": "asset is escalated"},
        {"field": "criticality", "op": "eq", "value": "high", "weight": 20, "reason": "high criticality"},
    ],
    "thresholds": {"medium": 30, "high": 60, "critical": 85},
}), "create decision scorecard")
decision = ok(client.post("/decision/evaluate", json={"object_type_id": "asset", "persist_run": True}), "evaluate decision risk")
assert_true(decision["object_count"] == 2, "decision evaluates asset set", decision)
explain = ok(client.get("/decision/objects/asset/asset_pump_4/explain"), "explain decision object")
assert_true(explain["risk"]["band"] in {"high", "critical"}, "decision explanation includes risk", explain)
timeline = ok(client.get("/temporal/objects/asset/asset_pump_4/timeline"), "object timeline")
assert_true(len(timeline["timeline"]) >= 2, "temporal timeline records mutations", timeline)
scenario = ok(client.post("/decision/scenarios", json={
    "id": "docs_asset_scenario",
    "display_name": "Docs Asset Scenario",
    "seed_object_ids": ["asset_chiller_2"],
    "overrides": {"asset_chiller_2": {"status": "DEGRADED"}},
}), "run decision scenario")
assert_true(scenario["impact"]["changed_object_count"] == 1, "scenario computes impact", scenario)

ok(client.post("/ops/alert-rules", json={
    "id": "docs_decision_high",
    "display_name": "Docs Decision High",
    "source": "decision",
    "min_severity": "high",
}), "create alert rule")
alerts_eval = ok(client.post("/ops/alerts/evaluate", json={"limit": 100}), "evaluate alert rules")
assert_true(alerts_eval["created_alerts"] >= 0, "alert evaluation executes", alerts_eval)
incident = ok(client.post("/ops/incidents", json={
    "id": "docs_asset_incident",
    "display_name": "Docs Asset Incident",
    "severity": "high",
    "linked_objects": [{"object_type_id": "asset", "object_id": "asset_pump_4"}],
}), "create incident")
assert_true(incident["linked_objects"][0]["object_id"] == "asset_pump_4", "incident links object", incident)
runbook = ok(client.post("/ops/runbooks", json={
    "id": "docs_runbook",
    "display_name": "Docs Runbook",
    "steps": [
        {"type": "query_objects", "object_type_id": "asset", "filters": {"criticality": "high"}, "output": "objects"},
        {"type": "create_notification", "title": "Docs runbook complete", "severity": "medium", "output": "notification"},
    ],
}), "create runbook")
runbook_execution = ok(client.post(f"/ops/runbooks/{runbook['id']}/execute", json={
    "incident_id": incident["id"],
    "actor": "docs",
}), "execute runbook")
assert_true(runbook_execution["status"] == "SUCCESS", "runbook executes", runbook_execution)
ops_summary = ok(client.get("/ops/summary"), "ops summary")
assert_true(ops_summary["events"] >= 1, "ops events are recorded", ops_summary)

contract = ok(client.post("/reliability/data-contracts", json={
    "id": "docs_orders_contract",
    "display_name": "Docs Orders Contract",
    "asset_id": "raw_orders_docs",
    "checks": [
        {"type": "row_count_bounds", "min": 1},
        {"type": "required_fields", "fields": ["order_id", "asset_id", "amount"]},
        {"type": "missing_rate", "field": "order_id", "max": 0},
    ],
}), "create data quality contract")
contract_run = ok(client.post(f"/reliability/data-contracts/{contract['id']}/run", json={}), "run data quality contract")
assert_true(contract_run["status"] == "PASS", "data quality contract passes", contract_run)
impact = ok(client.post("/reliability/lineage-impact", json={
    "resource_kind": "dataset",
    "resource_id": "raw_orders_docs",
    "direction": "downstream",
}), "analyze lineage impact")
assert_true(impact["summary"]["node_count"] >= 1, "lineage impact returns graph", impact)

investigation = ok(client.post("/investigations", json={
    "id": "docs_investigation",
    "display_name": "Docs Investigation",
    "object_refs": [{"object_type_id": "asset", "object_id": "asset_pump_4"}],
}), "create investigation")
evidence = ok(client.post(f"/investigations/{investigation['id']}/evidence", json={
    "title": "Docs Evidence",
    "source": "docs",
    "object_refs": [{"object_type_id": "asset", "object_id": "asset_pump_4"}],
    "payload": {"note": "Escalated during conformance test"},
    "tags": ["docs"],
}), "add investigation evidence")
hypothesis = ok(client.post(f"/investigations/{investigation['id']}/hypotheses", json={
    "statement": "Escalated pump requires follow-up",
    "confidence": 80,
    "linked_evidence_ids": [evidence["id"]],
}), "add investigation hypothesis")
assert_true(hypothesis["confidence"] == 80, "hypothesis recorded", hypothesis)
investigation_graph = ok(client.get(f"/investigations/{investigation['id']}/graph"), "investigation graph")
assert_true(investigation_graph["node_count"] >= 3, "investigation graph has evidence and object", investigation_graph)
report_out = ok(client.post(f"/investigations/{investigation['id']}/report", json={}), "generate investigation report")
assert_true("High risk objects" in report_out["body"], "investigation report includes risk section", report_out)

ok(client.post("/data-assets", json={
    "id": "model_baseline_docs",
    "display_name": "Model Baseline Docs",
    "kind": "dataset",
    "asset_schema": {},
    "records": [
        {"temperature": 10, "pressure": 20, "line": "A", "risk_score": 15},
        {"temperature": 12, "pressure": 22, "line": "A", "risk_score": 17},
        {"temperature": 11, "pressure": 19, "line": "A", "risk_score": 15},
    ],
}), "create model baseline")
ok(client.post("/data-assets", json={
    "id": "model_current_docs",
    "display_name": "Model Current Docs",
    "kind": "dataset",
    "asset_schema": {},
    "records": [
        {"temperature": 30, "pressure": 60, "line": "B", "risk_score": 45},
        {"temperature": 32, "pressure": 62, "line": "B", "risk_score": 47},
    ],
}), "create model current")
objective = ok(client.post("/modeling/objectives", json={
    "id": "docs_risk_objective",
    "display_name": "Docs Risk Objective",
    "problem_type": "regression",
    "target_field": "risk_score",
    "feature_fields": ["temperature", "pressure"],
    "input_asset_id": "model_baseline_docs",
}), "create modeling objective")
submission = ok(client.post(f"/modeling/objectives/{objective['id']}/train", json={
    "trainer_type": "regression",
    "training_dataset_id": "model_baseline_docs",
    "target_column": "risk_score",
    "eval_metric": "mae",
}), "train model submission")
ok(client.post(f"/modeling/objectives/{objective['id']}/release", json={
    "submission_id": submission["id"],
}), "release model submission")
deployment = ok(client.post("/modeling/deployments", json={
    "id": "docs_risk_deployment",
    "objective_id": objective["id"],
    "submission_id": submission["id"],
    "mode": "live",
}), "create model deployment")
inference = ok(client.post(f"/modeling/deployments/{deployment['id']}/infer", json={
    "inference_data": [{"temperature": 20, "pressure": 30}],
}), "run model inference")
assert_true(inference["output_data"][0]["prediction"] == 25, "deterministic inference returns prediction", inference)
prediction_logs = ok(client.get(f"/modelops/deployments/{deployment['id']}/prediction-logs"), "read prediction logs")
assert_true(prediction_logs and prediction_logs[0]["output_count"] == 1, "prediction log recorded", prediction_logs)
monitor = ok(client.post("/modelops/monitors", json={
    "id": "docs_risk_monitor",
    "display_name": "Docs Risk Monitor",
    "objective_id": objective["id"],
    "deployment_id": deployment["id"],
    "baseline_asset_id": "model_baseline_docs",
    "feature_fields": ["temperature", "pressure", "line"],
    "prediction_field": "prediction",
    "target_field": "risk_score",
    "thresholds": {
        "numeric_mean_shift_warn": 0.1,
        "numeric_mean_shift_fail": 0.5,
        "unseen_category_rate_warn": 0.1,
        "unseen_category_rate_fail": 0.5,
    },
}), "create model monitor")
monitor_run = ok(client.post(f"/modelops/monitors/{monitor['id']}/run", json={
    "current_asset_id": "model_current_docs",
}), "run model monitor")
assert_true(monitor_run["status"] == "FAIL", "model monitor detects drift", monitor_run)


print(f"\nDocs conformance verified: {passed} assertions passed.")
from app.database import engine as _engine  # noqa: E402

_engine.dispose()
tmpdir.cleanup()

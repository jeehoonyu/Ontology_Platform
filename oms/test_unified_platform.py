"""
Unified Operational Intelligence Platform regression tests.

Run:
  python test_unified_platform.py
"""
import os
import tempfile


tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tmpdir.name, 'unified_platform.db')}"

from fastapi.testclient import TestClient  # noqa: E402
from app.main import app  # noqa: E402


client = TestClient(app)
passed = 0


def ok(resp, label, expect=200):
    global passed
    success = resp.status_code == expect or (expect == 200 and 200 <= resp.status_code < 300)
    assert success, f"{label}: expected {expect}, got {resp.status_code} -> {resp.text[:1000]}"
    passed += 1
    return resp.json() if resp.content else {}


def assert_true(condition, label, payload=None):
    global passed
    assert condition, f"{label}: {payload}"
    passed += 1


for route in ("/workspace/search", "/workspace/graph"):
    resp = client.get(route)
    assert_true(resp.status_code == 200, f"{route} route loads", resp.status_code)

ok(client.post("/object-types", json={
    "id": "asset",
    "display_name": "Asset",
    "description": "Operational asset",
    "properties": {
        "name": {"type": "string"},
        "status": {"type": "string"},
        "criticality": {"type": "string"},
        "ssn": {"type": "string"},
    },
}), "create asset object type")
ok(client.post("/objects", json={
    "id": "asset_1",
    "object_type_id": "asset",
    "properties": {
        "name": "Pump A",
        "status": "DEGRADED",
        "criticality": "high",
        "ssn": "111-22-3333",
    },
}), "create asset object")
ok(client.post("/data-assets", json={
    "id": "raw_assets",
    "display_name": "Raw Assets",
    "description": "Raw asset feed",
    "kind": "dataset",
    "asset_schema": {"fields": ["id", "name"]},
    "records": [{"id": "asset_1", "name": "Pump A"}],
}), "create data asset")
ok(client.post("/pipelines", json={
    "id": "asset_pipeline",
    "display_name": "Asset Pipeline",
    "description": "Hydrates assets",
    "input_asset_id": "raw_assets",
    "steps": [],
}), "create pipeline")
ok(client.post("/action-types", json={
    "id": "escalate_asset",
    "display_name": "Escalate Asset",
    "description": "Escalate an asset",
    "parameters": {"asset_id": {"type": "string"}},
    "rules": {"requires_approval": True},
}), "create action type")

event = ok(client.post("/events/publish", json={
    "source": "decision",
    "event_type": "risk.high",
    "severity": "high",
    "title": "High risk asset",
    "message": "asset_1 is degraded and critical",
    "subject_type": "object",
    "subject_id": "asset_1",
    "object_type_id": "asset",
    "object_id": "asset_1",
    "payload": {"band": "high"},
}), "publish platform event")
assert_true(event["source"] == "decision" and event["severity"] == "high", "event payload returned", event)
events = ok(client.get("/events", params={"object_type_id": "asset", "object_id": "asset_1"}), "list filtered events")
assert_true(events["count"] == 1 and events["events"][0]["id"] == event["id"], "event filter finds object event", events)
summary = ok(client.get("/events/summary"), "event summary")
assert_true(summary["by_source"]["decision"] == 1 and summary["by_severity"]["high"] == 1, "event summary aggregates", summary)

subscription = ok(client.post("/events/subscriptions", json={
    "id": "high_asset_events",
    "display_name": "High Asset Events",
    "filters": {"source": "decision", "object_type_id": "asset", "min_severity": "high"},
    "target": {"type": "inbox", "recipient": "ops"},
}), "create event subscription")
matches = ok(client.post(f"/events/subscriptions/{subscription['id']}/evaluate"), "evaluate event subscription")
assert_true(matches["match_count"] == 1, "event subscription matches high asset event", matches)

search = ok(client.post("/search/query", json={
    "q": "asset",
    "kinds": [],
    "limit": 25,
    "include_payload": True,
}), "global search query")
kinds = {row["kind"] for row in search["results"]}
assert_true({"object", "event"}.issubset(kinds), "global search returns object and event", search)
dataset_search = ok(client.get("/search", params={"q": "Raw", "kind": "dataset"}), "global search get")
assert_true(dataset_search["count"] == 1 and dataset_search["results"][0]["id"] == "raw_assets", "dataset search filters by kind", dataset_search)
commands = ok(client.get("/search/commands"), "search commands")
assert_true(any(command["id"] == "open-graph" for command in commands["commands"]), "commands include graph navigation", commands)

mask_policy = ok(client.post("/policies", json={
    "id": "mask_asset_ssn",
    "display_name": "Mask Asset Sensitive Property",
    "effect": "MASK",
    "principal": "analyst",
    "action": "read",
    "resource_kind": "object",
    "object_type_id": "asset",
    "mask_properties": ["ssn"],
    "priority": 10,
}), "create mask policy")
deny_policy = ok(client.post("/policies", json={
    "id": "deny_asset_delete",
    "display_name": "Deny Asset Delete",
    "effect": "DENY",
    "principal": "analyst",
    "action": "delete",
    "resource_kind": "object",
    "object_type_id": "asset",
    "priority": 1,
}), "create deny policy")
assert_true(mask_policy["effect"] == "MASK" and deny_policy["effect"] == "DENY", "policy effects normalized")
policy_eval = ok(client.post("/policies/evaluate", json={
    "principal": "analyst",
    "action": "read",
    "resource_kind": "object",
    "resource_id": "asset_1",
    "object_type_id": "asset",
    "purpose": "operations",
    "context": {"properties": {"criticality": "high"}},
}), "evaluate mask policy")
assert_true(policy_eval["allowed"] is True and policy_eval["decision"] == "ALLOW_WITH_MASKS", "mask policy allows with masks", policy_eval)
assert_true("ssn" in policy_eval["masks"], "mask policy lists sensitive property", policy_eval)
denied = ok(client.post("/policies/evaluate", json={
    "principal": "analyst",
    "action": "delete",
    "resource_kind": "object",
    "resource_id": "asset_1",
    "object_type_id": "asset",
}), "evaluate deny policy")
assert_true(denied["allowed"] is False and denied["decision"] == "DENY", "deny policy blocks delete", denied)
simulation = ok(client.post("/policies/simulate", json={
    "principal": "operator",
    "action": "escalate",
    "resource_kind": "object",
    "resource_id": "asset_1",
    "object_type_id": "asset",
    "hypothetical_rules": [{
        "display_name": "Require high-risk approval",
        "effect": "REQUIRE_APPROVAL",
        "principal": "operator",
        "action": "escalate",
        "resource_kind": "object",
        "object_type_id": "asset",
        "approval": {"reason": "high risk asset"},
        "priority": 1,
    }],
}), "simulate policy")
assert_true(simulation["persisted"] is False and simulation["decision"]["decision"] == "REQUIRE_APPROVAL", "policy simulation does not persist by default", simulation)
decisions = ok(client.get("/policies/decisions", params={"principal": "analyst"}), "list policy decisions")
assert_true(decisions["count"] == 2, "persisted policy decisions listed", decisions)

timeline = ok(client.get("/activity/objects/asset/asset_1/timeline"), "object activity timeline")
timeline_kinds = {row["kind"] for row in timeline["timeline"]}
assert_true({"object_snapshot", "ops_event"}.issubset(timeline_kinds), "activity timeline combines snapshots and events", timeline)
graph = ok(client.get("/graph/overview"), "platform graph overview")
graph_kinds = {node["kind"] for node in graph["nodes"]}
assert_true({"object_type", "object", "dataset", "pipeline"}.issubset(graph_kinds), "platform graph includes core resources", graph)
assert_true(graph["edge_count"] >= 2, "platform graph has dataset/object/pipeline edges", graph)

print(f"PASS unified platform: {passed} assertions")

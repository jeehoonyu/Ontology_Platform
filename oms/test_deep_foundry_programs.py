"""
Deep Foundry-style local programs:
  * Workshop edit/publish/restore + live render
  * Object Explorer query, facets, saved exploration, selected profile, action availability
  * Pipeline Builder graph validate/preview/deliver with dataset transaction output
Run: python test_deep_foundry_programs.py
"""
import os
import tempfile

tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tmpdir.name, 'deep_foundry.db')}"

from fastapi.testclient import TestClient  # noqa: E402
from app.main import app  # noqa: E402

client = TestClient(app)
passed = 0


def ok(resp, label, expect=200):
    global passed
    success = resp.status_code == expect or (expect == 200 and 200 <= resp.status_code < 300)
    assert success, f"{label}: expected {expect}, got {resp.status_code} -> {resp.text[:500]}"
    passed += 1
    return resp.json() if resp.content else {}


# ---------------- base ontology + action ----------------
ok(client.post("/object-types", json={
    "id": "asset",
    "display_name": "Asset",
    "description": "Operational asset",
    "properties": {"name": {"type": "string"}, "criticality": {"type": "string"}, "status": {"type": "string"}, "score": {"type": "number"}},
}), "asset type")
for asset_id, criticality, status, score in [
    ("asset_1", "high", "RUNNING", 9),
    ("asset_2", "medium", "DEGRADED", 4),
    ("asset_3", "high", "DEGRADED", 7),
]:
    ok(client.post("/objects", json={
        "id": asset_id,
        "object_type_id": "asset",
        "properties": {"name": asset_id, "criticality": criticality, "status": status, "score": score},
    }), f"object {asset_id}")
ok(client.post("/action-types", json={
    "id": "flag_asset",
    "display_name": "Flag Asset",
    "description": "Flag selected asset",
    "parameters": {"object_id": {"type": "string", "required": True}},
    "rules": {"object_mutations": [{"object_type_id": "asset", "object_id": "$object_id", "set": {"flagged": True}}]},
}), "flag action")


# ---------------- Workshop: edit, render, publish, restore ----------------
workshop = ok(client.post("/apps/workshop", json={
    "id": "deep_ops_workshop",
    "display_name": "Deep Ops Workshop",
    "variables": {
        "criticalAssets": {"definition_type": "object_set", "object_type_id": "asset", "filters": {"criticality": "high"}, "limit": 10},
        "assetCount": {"definition_type": "object_set_aggregation", "object_type_id": "asset", "op": "count"},
    },
    "widgets": [
        {"type": "metric", "title": "Assets", "variable": "assetCount"},
        {"type": "object_table", "title": "Critical Assets", "variable": "criticalAssets"},
    ],
    "layout": {"columns": 2, "events": [{"type": "navigate", "page": "detail"}]},
}), "create workshop")
render = ok(client.post(f"/apps/workshop/{workshop['id']}/render-live", json={"state": {}}), "render workshop")
assert render["widgets"][0]["value"] == 3, render
assert render["widgets"][1]["row_count"] == 2, render
v1 = ok(client.post(f"/apps/workshop/{workshop['id']}/publish", json={"actor": "test", "note": "baseline"}), "publish workshop")
ok(client.patch(f"/apps/workshop/{workshop['id']}", json={"display_name": "Changed Workshop", "widgets": [], "actor": "test"}), "patch workshop")
restored = ok(client.post(f"/apps/workshop/{workshop['id']}/versions/{v1['id']}/restore", json={"actor": "test"}), "restore workshop")
assert restored["display_name"] == "Deep Ops Workshop" and len(restored["widgets"]) == 2, restored
versions = ok(client.get(f"/apps/workshop/{workshop['id']}/versions"), "list workshop versions")
assert versions[0]["version_number"] == 1, versions


# ---------------- Object Explorer: deep query + saved exploration ----------------
query = ok(client.post("/object-explorer/query", json={
    "object_type_id": "asset",
    "filters": {"criticality": "high"},
    "columns": ["name", "status", "criticality", "score"],
    "chart_fields": ["status", "score"],
    "selected_ids": ["asset_1"],
    "limit": 50,
}), "object explorer query")
assert query["result_count"] == 2, query
assert len(query["facets"]) == 2 and query["selected_objects"][0]["object"]["id"] == "asset_1", query
assert any(action["id"] == "flag_asset" for action in query["available_actions"]), query["available_actions"]
saved = ok(client.post("/object-explorer/explorations", json={
    "id": "critical_asset_exploration",
    "display_name": "Critical Asset Exploration",
    "object_type_id": "asset",
    "filters": {"criticality": "high"},
    "columns": ["name", "status"],
    "charts": query["facets"],
    "perspective": {"selected_object_id": "asset_1"},
}), "save exploration", expect=201)
loaded = ok(client.get(f"/object-explorer/explorations/{saved['id']}"), "load exploration")
assert loaded["filters"] == {"criticality": "high"}, loaded
patched = ok(client.patch(f"/object-explorer/explorations/{saved['id']}", json={"display_name": "Updated Critical Assets"}), "patch exploration")
assert patched["display_name"] == "Updated Critical Assets", patched
action_result = ok(client.post("/actions/execute", json={
    "action_type_id": "flag_asset",
    "parameters": {"object_id": "asset_1"},
    "idempotency_key": "deep-foundry-flag-asset-1",
    "actor": "object_explorer",
}), "execute explorer action")
assert "asset_1" in action_result["mutated_object_ids"], action_result


# ---------------- Pipeline Builder: validate, preview, deliver ----------------
ok(client.post("/data-assets", json={
    "id": "orders",
    "display_name": "Orders",
    "kind": "dataset",
    "asset_schema": {},
    "records": [
        {"id": "o1", "cust": "A", "amount": 10, "status": "open"},
        {"id": "o2", "cust": "A", "amount": 20, "status": "open"},
        {"id": "o3", "cust": "B", "amount": 5, "status": "closed"},
    ],
}), "orders asset")
ok(client.post("/data-assets", json={
    "id": "customers",
    "display_name": "Customers",
    "kind": "dataset",
    "asset_schema": {},
    "records": [{"cust": "A", "region": "West"}, {"cust": "B", "region": "East"}],
}), "customers asset")
graph = ok(client.post("/pipeline-builder/graphs", json={
    "id": "orders_graph",
    "display_name": "Orders Graph",
    "nodes": [
        {"id": "input", "type": "input_dataset", "config": {"asset_id": "orders"}},
        {"id": "filter", "type": "filter", "config": {"filters": {"status": "open"}}},
        {"id": "join", "type": "join", "config": {"right_asset_id": "customers", "left_key": "cust", "right_key": "cust"}},
        {"id": "aggregate", "type": "aggregate", "config": {"group_by": ["region"], "metrics": [{"operation": "sum", "field": "amount", "alias": "total"}, {"operation": "count", "alias": "n"}]}},
        {"id": "output", "type": "dataset_output", "config": {"asset_id": "orders_graph_output"}},
    ],
    "edges": [
        {"source": "input", "target": "filter"},
        {"source": "filter", "target": "join"},
        {"source": "join", "target": "aggregate"},
        {"source": "aggregate", "target": "output"},
    ],
}), "create pipeline graph", expect=201)
validation = ok(client.post(f"/pipeline-builder/graphs/{graph['id']}/validate"), "validate graph")
assert validation["status"] == "VALID", validation
preview = ok(client.post(f"/pipeline-builder/graphs/{graph['id']}/preview", json={"limit": 10}), "preview graph")
assert preview["row_count"] == 1 and preview["rows"][0]["total"] == 30, preview
delivery = ok(client.post(f"/pipeline-builder/graphs/{graph['id']}/deliver", json={"actor": "test"}), "deliver graph")
assert delivery["status"] == "DELIVERED" and delivery["records_out"] == 1, delivery
output = ok(client.get("/data-assets/orders_graph_output"), "output asset")
assert output["records"] == [{"region": "West", "total": 30, "n": 2}], output["records"]
txns = ok(client.get("/datasets/orders_graph_output/transactions"), "output transactions")
assert txns and txns[-1]["txn_type"] == "SNAPSHOT", txns
runs = ok(client.get("/pipeline-runs", params={"pipeline_id": "orders_graph"}), "pipeline runs")
assert runs and runs[0]["status"] == "SUCCESS", runs


print(f"\nDeep Foundry-style programs verified: {passed} assertions passed.")
from app.database import engine as _engine  # noqa: E402
_engine.dispose()
tmpdir.cleanup()

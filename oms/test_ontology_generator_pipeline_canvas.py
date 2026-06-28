"""
Ontology Generator + Pipeline Builder canvas upgrade.

Run: python test_ontology_generator_pipeline_canvas.py
"""
import os
import tempfile

tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tmpdir.name, 'ontology_generator.db')}"

from fastapi.testclient import TestClient  # noqa: E402
from app.main import app  # noqa: E402

client = TestClient(app)
passed = 0


def ok(resp, label, expect=200):
    global passed
    success = resp.status_code == expect or (expect == 200 and 200 <= resp.status_code < 300)
    assert success, f"{label}: expected {expect}, got {resp.status_code} -> {resp.text[:700]}"
    passed += 1
    return resp.json() if resp.content else {}


root = ok(client.get("/"), "root status")
assert "ontology_generator" in root["capabilities"], root["capabilities"]

node_types = ok(client.get("/pipeline-builder/node-types"), "node type catalog")
assert any(node["type"] == "ontology_output" for node in node_types["node_types"]), node_types

ok(client.post("/data-assets", json={
    "id": "generator_orders_raw",
    "display_name": "Generator Orders Raw",
    "kind": "dataset",
    "asset_schema": {},
    "records": [
        {"order_id": "o1", "asset_id": "asset_pump_4", "amount": 10, "status": "open"},
        {"order_id": "o2", "asset_id": "asset_pump_4", "amount": 20, "status": "open"},
        {"order_id": "o3", "asset_id": "asset_chiller_2", "amount": 5, "status": "closed"},
    ],
}), "create generator source dataset")

draft = ok(client.post("/ontology-generator/drafts", json={
    "id": "generator_orders_draft",
    "asset_id": "generator_orders_raw",
    "display_name": "Service Order",
    "object_type_id": "service_order",
    "include_actions": True,
    "create_pipeline_graph": True,
}), "create ontology generator draft", expect=201)
assert draft["object_type_id"] == "service_order", draft
assert draft["draft"]["primary_key"] == "orderId", draft["draft"]
assert draft["draft"]["title_key"] == "orderId", draft["draft"]
assert any(prop["api_name"] == "amount" and prop["base_type"] == "integer" for prop in draft["draft"]["properties"]), draft["draft"]["properties"]

validation = ok(client.post("/ontology-generator/drafts/generator_orders_draft/validate"), "validate generator draft")
assert validation["status"] in {"PASS", "WARN"}, validation

applied = ok(client.post("/ontology-generator/drafts/generator_orders_draft/apply", json={
    "actor": "test",
    "create_actions": True,
    "create_pipeline_graph": True,
}), "apply generator draft")
assert applied["status"] == "APPLIED", applied
assert applied["pipeline_graph_id"] == "service_order_ontology_graph", applied
assert set(applied["action_type_ids"]) == {"create_service_order", "edit_service_order", "delete_service_order"}, applied

object_type = ok(client.get("/object-types"), "list object types")
assert any(row["id"] == "service_order" for row in object_type), object_type
profile = ok(client.get("/ontology/object-types/service_order/profile"), "read generated profile")
assert profile["primary_key"] == "orderId" and profile["properties"]["orderId"]["base_type"] == "string", profile

graph_validation = ok(client.post("/pipeline-builder/graphs/service_order_ontology_graph/validate"), "validate generated graph")
assert graph_validation["status"] == "VALID", graph_validation
preview = ok(client.post("/pipeline-builder/graphs/service_order_ontology_graph/preview", json={"limit": 10}), "preview generated graph")
assert preview["row_count"] == 3, preview
delivery = ok(client.post("/pipeline-builder/graphs/service_order_ontology_graph/deliver", json={"actor": "test"}), "deliver generated graph")
assert delivery["status"] == "DELIVERED" and delivery["records_out"] == 3, delivery
objects = ok(client.get("/objects/service_order"), "materialized service order objects")
ids = {row["id"] for row in objects}
assert {"o1", "o2", "o3"} <= ids, objects
assert all("orderId" in row["properties"] for row in objects), objects

html_resp = client.get("/workspace/ontology")
assert html_resp.status_code == 200, html_resp.text[:500]
html = html_resp.text
assert "Ontology Generator" in html and "ontologyGeneratorAssetSelect" in html and "d3@7.9.0" in html, html[:500]
passed += 1
js = client.get("/ui/assets/app.js?v=test").text
assert "function renderPipelineCanvas()" in js and "pipeline-svg-node" in js and "createOntologyGeneratorDraft" in js, js[:500]
passed += 1

print(f"\nOntology generator + pipeline canvas verified: {passed} assertions passed.")
from app.database import engine as _engine  # noqa: E402
_engine.dispose()
tmpdir.cleanup()

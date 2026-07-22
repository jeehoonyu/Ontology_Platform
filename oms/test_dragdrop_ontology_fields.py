"""
Backend-connected Pipeline drag/drop and editable Ontology property contracts.

Run: python test_dragdrop_ontology_fields.py
"""
import os
import tempfile

tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tmpdir.name, 'dragdrop_fields.db')}"

from fastapi.testclient import TestClient  # noqa: E402
from app.main import app  # noqa: E402

client = TestClient(app)
passed = 0


def ok(resp, label, expect=200):
    global passed
    success = resp.status_code == expect or (expect == 200 and 200 <= resp.status_code < 300)
    assert success, f"{label}: expected {expect}, got {resp.status_code} -> {resp.text[:900]}"
    passed += 1
    return resp.json() if resp.content else {}


def assert_event(event_type):
    global passed
    audits = ok(client.get("/audit-logs?limit=200"), f"audit lookup for {event_type}")
    assert any(row["event_type"] == event_type for row in audits), event_type
    passed += 1


ok(client.post("/pipeline-builder/graphs", json={
    "id": "drag_create_graph",
    "display_name": "Drag Create Graph",
    "nodes": [
        {"id": "input", "type": "input_dataset", "label": "Input", "position": {"x": 100, "y": 140}, "config": {}},
        {"id": "filter", "type": "filter", "label": "Filter", "position": {"x": 360, "y": 140}, "config": {}},
    ],
    "edges": [{"source": "input", "target": "filter"}],
}), "create drag graph", expect=201)

created_canvas = ok(client.post("/pipeline-builder/graphs/drag_create_graph/nodes", json={
    "node_type": "project",
    "label": "Dropped Project",
    "position": {"x": 333.4, "y": 222.2},
    "connect_from_node_id": "filter",
    "actor": "test",
}), "create node at canvas drop location")
created_node = created_canvas["selected_node"]
assert created_node["type"] == "project", created_node
assert created_node["position"] == {"x": 333.4, "y": 222.2}, created_node
assert any(edge["source"] == "filter" and edge["target"] == created_node["id"] for edge in created_canvas["edges"]), created_canvas["edges"]
passed += 3

layout_canvas = ok(client.patch("/pipeline-builder/graphs/drag_create_graph/layout", json={
    "positions": {created_node["id"]: {"x": 610, "y": 245}}
}), "persist dragged node position")
dragged_node = next(node for node in layout_canvas["nodes"] if node["id"] == created_node["id"])
assert dragged_node["position"] == {"x": 610.0, "y": 245.0}, dragged_node
passed += 1

ok(client.post("/pipeline-builder/graphs", json={
    "id": "drag_delete_graph",
    "display_name": "Drag Delete Graph",
    "nodes": [
        {"id": "input", "type": "input_dataset", "label": "Input", "position": {"x": 100, "y": 120}, "config": {}},
        {"id": "middle", "type": "filter", "label": "Middle", "position": {"x": 360, "y": 120}, "config": {}},
        {"id": "output", "type": "dataset_output", "label": "Output", "position": {"x": 620, "y": 120}, "config": {}},
    ],
    "edges": [{"source": "input", "target": "middle"}, {"source": "middle", "target": "output"}],
}), "create delete graph", expect=201)

delete_canvas = ok(client.delete("/pipeline-builder/graphs/drag_delete_graph/nodes/middle"), "delete node and reconnect path")
assert not any(node["id"] == "middle" for node in delete_canvas["nodes"]), delete_canvas["nodes"]
assert any(edge["source"] == "input" and edge["target"] == "output" for edge in delete_canvas["edges"]), delete_canvas["edges"]
passed += 2

ok(client.post("/object-types", json={
    "id": "editable_asset",
    "display_name": "Editable Asset",
    "description": "Object type for editable-field tests",
    "properties": {
        "assetId": {"type": "string", "base_type": "string", "required": True},
        "status": {"type": "string", "base_type": "string"},
    },
}), "create editable object type")
ok(client.put("/ontology/object-types/editable_asset/profile", json={
    "api_name": "EditableAsset",
    "primary_key": "assetId",
    "title_key": "assetId",
    "plural_name": "Editable Assets",
    "properties": {
        "assetId": {"base_type": "string", "status": "active", "required": True},
        "status": {"base_type": "string", "status": "active", "required": False},
    },
}), "create editable profile")

manager_after_add = ok(client.post("/ontology/object-types/editable_asset/properties", json={
    "name": "inspectionDue",
    "base_type": "date",
    "required": False,
    "description": "Next inspection date",
    "actor": "test",
}), "add ontology property")
assert any(row["name"] == "inspectionDue" and row["base_type"] == "date" for row in manager_after_add["cards"]["properties"]["rows"]), manager_after_add["cards"]["properties"]["rows"]
passed += 1

ok(client.post("/objects", json={
    "id": "asset_a",
    "object_type_id": "editable_asset",
    "properties": {"assetId": "A-1", "status": "RUNNING", "inspectionDue": "2026-07-01"},
}), "create object with soon-to-be-archived value")

manager_after_update = ok(client.patch("/ontology/object-types/editable_asset/properties/inspectionDue", json={
    "required": True,
    "description": "Confirmed inspection deadline",
    "actor": "test",
}), "edit ontology property inline")
updated_row = next(row for row in manager_after_update["cards"]["properties"]["rows"] if row["name"] == "inspectionDue")
assert updated_row["required"] is True and updated_row["description"] == "Confirmed inspection deadline", updated_row
passed += 1

ok(client.post("/ontology/object-types/editable_asset/properties", json={
    "name": "riskScore",
    "base_type": "double",
    "description": "Latest deterministic risk score",
    "actor": "test",
}), "add second property for reorder")
manager_after_reorder = ok(client.patch("/ontology/object-types/editable_asset/properties/order", json={
    "order": ["riskScore", "assetId", "status", "inspectionDue"],
    "actor": "test",
}), "reorder ontology properties")
rows = manager_after_reorder["cards"]["properties"]["rows"]
orders = {row["name"]: row["order"] for row in rows}
assert orders["riskScore"] == 1 and orders["assetId"] == 2 and orders["inspectionDue"] == 4, orders
passed += 1

manager_after_archive = ok(client.delete("/ontology/object-types/editable_asset/properties/inspectionDue"), "archive ontology property")
assert not any(row["name"] == "inspectionDue" for row in manager_after_archive["cards"]["properties"]["rows"]), manager_after_archive["cards"]["properties"]["rows"]
preserved = ok(client.get("/objects/editable_asset/asset_a"), "fetch object after schema archive")
assert preserved["properties"]["inspectionDue"] == "2026-07-01", preserved
passed += 2

primary_key_delete = client.delete("/ontology/object-types/editable_asset/properties/assetId")
assert primary_key_delete.status_code == 422, primary_key_delete.text
passed += 1

full = ok(client.get("/ontology/object-types/editable_asset/full"), "fetch full object type metadata")
archived = full["base_properties"]["__manager"]["archived_properties"]["inspectionDue"]
assert archived["spec"]["description"] == "Confirmed inspection deadline", archived
passed += 1

ok(client.post("/object-types", json={
    "id": "editable_facility",
    "display_name": "Editable Facility",
    "properties": {"facilityId": {"type": "string", "required": True}},
}), "create linked object type")
ok(client.post("/link-types", json={
    "id": "editable_asset_facility",
    "display_name": "Asset at facility",
    "source_object_type_id": "editable_asset",
    "target_object_type_id": "editable_facility",
    "cardinality": "MANY_TO_MANY",
}), "create editable link type")
updated_link = ok(client.patch("/link-types/editable_asset_facility", json={
    "display_name": "Facility contains asset",
    "cardinality": "ONE_TO_MANY",
}), "edit link type")
assert updated_link["display_name"] == "Facility contains asset" and updated_link["cardinality"] == "ONE_TO_MANY", updated_link
passed += 1

ok(client.post("/action-types", json={
    "id": "editable_asset_inspect",
    "display_name": "Inspect asset",
    "description": "Create an inspection recommendation.",
    "parameters": {},
    "rules": {"object_type_id": "editable_asset", "operations": []},
}), "create editable action type")
updated_action = ok(client.patch("/action-types/editable_asset_inspect", json={
    "display_name": "Schedule asset inspection",
    "description": "Schedule a governed inspection.",
}), "edit action type")
assert updated_action["display_name"] == "Schedule asset inspection", updated_action
passed += 1

manager_resources = ok(client.get("/ui-state/ontology/object-types/editable_asset"), "manager includes editable resources")
assert any(row["id"] == "editable_asset_facility" for row in manager_resources["cards"]["link_types"]["rows"]), manager_resources
assert any(row["id"] == "editable_asset_inspect" for row in manager_resources["cards"]["action_types"]["rows"]), manager_resources
passed += 2

for event in [
    "pipeline_builder.node.created",
    "pipeline_builder.graph.layout_updated",
    "pipeline_builder.node.deleted",
    "ontology.object_type.property_created",
    "ontology.object_type.property_updated",
    "ontology.object_type.properties_reordered",
    "ontology.object_type.property_archived",
    "ontology.link_type.updated",
    "ontology.action_type.updated",
]:
    assert_event(event)

print(f"\nDrag/drop and ontology field contracts verified: {passed} assertions passed.")
from app.database import engine as _engine  # noqa: E402
_engine.dispose()
tmpdir.cleanup()

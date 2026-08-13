"""
UI-state contracts for the screenshot-grounded Pipeline Builder and Ontology Manager.

Run: python test_ui_state_pipeline_ontology.py
"""
import os
import tempfile

tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tmpdir.name, 'ui_state.db')}"

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


ok(client.post("/data-assets", json={
    "id": "ui_geo_raw",
    "display_name": "UI Geo Raw",
    "kind": "dataset",
    "asset_schema": {},
    "records": [
        {"track_id": "t1", "object_label": "vehicle", "confidence_score": 0.9, "latitude": 37.1, "longitude": -122.1},
        {"track_id": "t2", "object_label": "aircraft", "confidence_score": 0.7, "latitude": 37.2, "longitude": -122.2},
    ],
}), "create UI source dataset")

draft = ok(client.post("/ontology-generator/drafts", json={
    "id": "ui_geo_draft",
    "asset_id": "ui_geo_raw",
    "display_name": "Correlated Intelligence",
    "object_type_id": "correlated_intelligence",
    "include_actions": True,
    "create_pipeline_graph": True,
}), "create UI ontology draft", expect=201)
assert draft["object_type_id"] == "correlated_intelligence", draft

applied = ok(client.post("/ontology-generator/drafts/ui_geo_draft/apply", json={
    "actor": "test",
    "create_actions": True,
    "create_pipeline_graph": True,
}), "apply UI ontology draft")
graph_id = applied["pipeline_graph_id"]
assert graph_id == "correlated_intelligence_ontology_graph", applied

pipeline_state = ok(client.get("/ui-state/pipeline"), "pipeline UI state")
assert pipeline_state["summary"]["graph_count"] >= 1, pipeline_state
assert pipeline_state["selected_canvas"]["toolbar_groups"], pipeline_state["selected_canvas"]
assert any(group["id"] == "transform" for group in pipeline_state["selected_canvas"]["toolbar_groups"]), pipeline_state["selected_canvas"]["toolbar_groups"]

canvas = ok(client.get(f"/ui-state/pipeline/{graph_id}/canvas?selected_node_id=input"), "pipeline canvas state")
assert canvas["graph"]["id"] == graph_id, canvas
assert any(node["id"] == "input" and node["ports"]["outputs"] for node in canvas["nodes"]), canvas["nodes"]
assert canvas["outputs"]["nodes"], canvas["outputs"]

node_preview = ok(client.post(f"/pipeline-builder/graphs/{graph_id}/nodes/input/preview", json={"limit": 5}), "node preview")
assert node_preview["status"] == "PREVIEW_READY" and node_preview["row_count"] == 2, node_preview
assert any(column["name"] == "track_id" for column in node_preview["columns"]), node_preview["columns"]

node_suggestions = ok(client.post(f"/pipeline-builder/graphs/{graph_id}/nodes/input/suggestions"), "node suggestions")
assert node_suggestions["insertable_node_types"], node_suggestions
assert any(item["node_type"] in {"rename", "project"} for item in node_suggestions["suggestions"]), node_suggestions["suggestions"]

node_details = ok(client.get(f"/ui-state/pipeline/{graph_id}/nodes/input/details"), "node details")
assert node_details["node_id"] == "input", node_details
assert node_details["preview"]["row_count"] == 2, node_details["preview"]
assert any(action["id"] == "use_llm" for action in node_details["context_actions"]), node_details["context_actions"]

output_summary = ok(client.get(f"/ui-state/pipeline/{graph_id}/outputs"), "pipeline output rail")
assert output_summary["summary"]["output_node_count"] >= 1, output_summary["summary"]
assert output_summary["validation"]["status"] in {"READY", "VALID", "ERROR"}, output_summary["validation"]

inserted = ok(client.post(f"/pipeline-builder/graphs/{graph_id}/nodes/input/insert-after", json={
    "node_type": "filter",
    "label": "Filter detections",
    "config": {"field": "confidence_score", "op": "gte", "value": 0.5},
}), "insert filter after input")
inserted_node_id = inserted["selected_node"]["id"]
assert inserted["selected_node"]["type"] == "filter", inserted["selected_node"]
assert any(edge["source"] == "input" and edge["target"] == inserted_node_id for edge in inserted["edges"]), inserted["edges"]

layout = ok(client.patch(f"/pipeline-builder/graphs/{graph_id}/layout", json={
    "positions": {inserted_node_id: {"x": 520, "y": 260}}
}), "save pipeline layout")
saved_node = next(node for node in layout["nodes"] if node["id"] == inserted_node_id)
assert saved_node["position"] == {"x": 520.0, "y": 260.0}, saved_node

ontology_state = ok(client.get("/ui-state/ontology"), "ontology UI state")
assert ontology_state["summary"]["object_type_count"] >= 1, ontology_state
assert any(row["id"] == "correlated_intelligence" for row in ontology_state["object_types"]), ontology_state["object_types"]

manager = ok(client.get("/ui-state/ontology/object-types/correlated_intelligence"), "ontology manager state")
assert manager["object_type"]["display_name"] == "Correlated Intelligence", manager["object_type"]
assert manager["cards"]["properties"]["count"] >= 4, manager["cards"]["properties"]
assert "overview" in manager["navigation"] and "contracts" in manager["navigation"] and "history" in manager["navigation"], manager["navigation"]
assert manager["cards"]["contract_health"]["status"] == "PASS", manager["cards"]["contract_health"]

release = ok(client.post("/ontology/change-sets", json={
    "project_id": "default", "title": "Publish UI ontology baseline", "changes": [],
}), "create UI ontology baseline", expect=201)
ok(client.post(f"/ontology/change-sets/{release['id']}/validate"), "validate UI ontology baseline")
ok(client.post(f"/ontology/change-sets/{release['id']}/decision", json={"approve": True}), "approve UI ontology baseline")
ok(client.post(f"/ontology/change-sets/{release['id']}/publish", json={"environment": "production"}), "publish UI ontology baseline")
ok(client.post("/api/v1/ontology/contracts/bind", json={
    "project_id": "default", "consumer_kind": "test", "consumer_id": "ui_consumer", "consumer_version": "1",
    "payload": {"object_type_id": "correlated_intelligence"},
}), "bind UI ontology consumer")
manager_with_contract = ok(client.get("/ui-state/ontology/object-types/correlated_intelligence"), "ontology manager contract health")
assert manager_with_contract["cards"]["contract_health"]["count"] == 1, manager_with_contract["cards"]["contract_health"]
assert manager_with_contract["cards"]["contract_health"]["rows"][0]["status"] == "CURRENT", manager_with_contract["cards"]["contract_health"]
contracts_section = ok(client.get("/ui-state/ontology/object-types/correlated_intelligence/sections/contracts"), "ontology contracts section")
assert contracts_section["summary"]["status"] == "PASS" and len(contracts_section["rows"]) == 1, contracts_section

walkthrough = ok(client.get("/ui-state/ontology/object-types/correlated_intelligence/walkthrough"), "ontology walkthrough")
assert walkthrough["current_step_id"] == "object_type_overview", walkthrough
assert len(walkthrough["steps"]) >= 4, walkthrough["steps"]

properties_section = ok(client.get("/ui-state/ontology/object-types/correlated_intelligence/sections/properties"), "ontology properties section")
assert properties_section["section_id"] == "properties", properties_section
assert len(properties_section["rows"]) >= 4, properties_section["rows"]

interface_property = properties_section["rows"][0]
ok(client.post("/interfaces", json={
    "id": "ui_identifiable",
    "display_name": "UI Identifiable",
    "description": "Reusable identity capability exposed by Ontology Manager.",
    "properties": {
        "identity": {"base_type": interface_property["base_type"], "required": True},
    },
}), "create ontology interface")
ok(client.post("/object-types/correlated_intelligence/implement-interface", json={
    "interface_id": "ui_identifiable",
    "property_mappings": {"identity": interface_property["name"]},
}), "implement ontology interface")
interfaces_section = ok(client.get("/ui-state/ontology/object-types/correlated_intelligence/sections/interfaces"), "ontology interfaces section")
assert interfaces_section["summary"]["configured"] is True, interfaces_section
assert interfaces_section["summary"]["implementation_count"] == 1, interfaces_section
assert interfaces_section["rows"][0]["interface_id"] == "ui_identifiable", interfaces_section["rows"]
assert interfaces_section["rows"][0]["property_mappings"]["identity"] == interface_property["name"], interfaces_section["rows"][0]

security_section = ok(client.get("/ui-state/ontology/object-types/correlated_intelligence/sections/security"), "ontology security section")
assert security_section["summary"]["visibility"], security_section

metadata = ok(client.patch("/ontology/object-types/correlated_intelligence/metadata", json={
    "plural_name": "Correlated Intelligences",
    "point_of_contact": "tester",
    "visibility": "Normal",
    "groups": ["generated", "geo"],
}), "update ontology manager metadata")
assert metadata["object_type"]["plural_name"] == "Correlated Intelligences", metadata["object_type"]
assert metadata["object_type"]["point_of_contact"] == "tester", metadata["object_type"]

indexed = ok(client.post("/ontology/object-types/correlated_intelligence/index", json={"actor": "test"}), "index object type")
assert indexed["object_type"]["index_status"] == "indexed", indexed["object_type"]

opened = ok(client.post("/ontology/object-types/correlated_intelligence/open-from-pipeline", json={
    "graph_id": graph_id,
    "node_id": inserted_node_id,
    "actor": "test",
}), "open ontology from pipeline")
assert opened["cards"]["dependents"]["count"] >= 1, opened["cards"]["dependents"]

workflow_before = ok(client.get("/scenarios/asset-reliability/workflow-state"), "workflow state before bootstrap")
assert workflow_before["steps"] and workflow_before["next_action"], workflow_before

bootstrap = ok(client.post("/scenarios/asset-reliability/bootstrap", json={"actor": "test", "run_pipelines": True, "run_checks": True}), "bootstrap scenario")
assert bootstrap["scenario_id"] == "asset_reliability", bootstrap

workflow_after = ok(client.get("/scenarios/asset-reliability/workflow-state"), "workflow state after bootstrap")
assert "bootstrap" in workflow_after["completed_steps"], workflow_after
assert any(link["kind"] == "pipeline_graph" for link in workflow_after["evidence_links"]), workflow_after["evidence_links"]

html_pipeline = client.get("/workspace/pipeline").text
assert ("Pipeline Builder" in html_pipeline and "id=\"root\"" in html_pipeline) or "/react/assets/" in html_pipeline, html_pipeline[:400]
passed += 1

print(f"\nUI-state Pipeline/Ontology contracts verified: {passed} assertions passed.")
from app.database import engine as _engine  # noqa: E402
_engine.dispose()
tmpdir.cleanup()

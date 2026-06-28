"""
Productized operational intelligence platform regression test.

Run:
  python test_productized_platform.py
"""
import os
import tempfile


tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tmpdir.name, 'productized_platform.db')}"

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


for route in (
    "/workspace/command-center",
    "/workspace/graph",
    "/workspace/validation",
    "/workspace/ontology",
    "/workspace/pipeline",
):
    resp = client.get(route)
    assert_true(resp.status_code == 200, f"{route} loads", resp.status_code)

html = client.get("/workspace/command-center").text
assert_true("commandCenterImport" in html and "commandCenterProofTrail" in html and "commandCenterStepper" in html, "command center has guided import/proof trail UI")
graph_html = client.get("/workspace/graph").text
assert_true("platformGraphCanvas" in graph_html and "platformGraphFilters" in graph_html and "platformGraphSearchInput" in graph_html, "graph workspace has visual canvas UI")
validation_html = client.get("/workspace/validation").text
assert_true("validationView" in validation_html and "validationMatrix" in validation_html, "validation workspace is present")

root = ok(client.get("/"), "root capability catalog")
for capability in ("data_imports", "validation_dashboard", "project_snapshot", "schema_health", "event_consistency"):
    assert_true(capability in root["capabilities"], f"root advertises {capability}", root["capabilities"])

csv_job = ok(client.post("/imports/csv", json={
    "id": "user_asset_csv_import",
    "filename": "assets.csv",
    "display_name": "User Asset CSV",
    "target_dataset_id": "user_asset_dataset",
    "content": "asset_id,name,status,criticality,vibration_mm_s,temperature_c\nasset_user_1,User Pump,DEGRADED,high,9.7,91.2\nasset_user_2,User Chiller,RUNNING,medium,3.1,70.4\n",
}), "create CSV import", expect=201)
assert_true(csv_job["status"] == "READY" and csv_job["record_count"] == 2, "CSV import is ready", csv_job)
assert_true(any(field["name"] == "vibration_mm_s" and field["type"] == "number" for field in csv_job["schema"]["fields"]), "CSV schema infers numeric field", csv_job["schema"])

json_job = ok(client.post("/imports/json", json={
    "id": "user_asset_json_import",
    "filename": "assets.json",
    "display_name": "User Asset JSON",
    "content": "[{\"asset_id\":\"asset_json_1\",\"name\":\"JSON Pump\",\"status\":\"RUNNING\",\"criticality\":\"low\"}]",
}), "create JSON import", expect=201)
assert_true(json_job["status"] == "READY" and json_job["record_count"] == 1, "JSON import is ready", json_job)

templates = ok(client.get("/imports/templates"), "list import templates")
assert_true(any(template["id"] == "asset" for template in templates["templates"]), "asset import template exists", templates)
sample_csv = client.get("/imports/templates/asset/sample?format=csv")
assert_true(sample_csv.status_code == 200 and "asset_id" in sample_csv.text, "asset sample CSV downloads", sample_csv.text)
file_job = ok(client.post(
    "/imports/files?filename=file-assets.csv&display_name=File%20Asset%20Import&target_dataset_id=file_asset_dataset&template=asset",
    content="asset_id,name,status,criticality\nasset_file_1,File Pump,RUNNING,medium\n",
    headers={"content-type": "text/csv"},
), "create file import", expect=201)
assert_true(file_job["status"] == "READY" and file_job["template"] == "asset", "file import applies template", file_job)
validated_file = ok(client.post(f"/imports/jobs/{file_job['id']}/validate", json={
    "template": "asset",
    "mapping": {"asset_id": "asset_id", "name": "name", "status": "status", "criticality": "criticality"},
}), "validate file import mapping")
assert_true(validated_file["validation"]["status"] == "READY" and validated_file["job"]["semantic_mapping"]["asset_id"] == "asset_id", "mapping validation succeeds", validated_file)
draft_from_file = ok(client.post(f"/imports/jobs/{file_job['id']}/generate-ontology-draft", json={
    "actor": "test",
    "object_type_id": "file_asset",
    "display_name": "File Asset",
}), "generate ontology draft from file import")
assert_true(draft_from_file["status"] == "DRAFT_CREATED" and draft_from_file["draft"]["object_type_id"] == "file_asset", "file import generated ontology draft", draft_from_file)

promoted = ok(client.post("/imports/jobs/user_asset_csv_import/promote-to-dataset", json={
    "dataset_id": "user_asset_dataset",
    "display_name": "User Asset Dataset",
    "actor": "test",
}), "promote import to dataset")
assert_true(promoted["dataset"]["id"] == "user_asset_dataset" and len(promoted["dataset"]["records"]) == 2, "dataset created from import", promoted)
jobs = ok(client.get("/imports/jobs"), "list import jobs")
assert_true(jobs["count"] >= 2 and any(job["status"] == "PROMOTED" for job in jobs["jobs"]), "import jobs list includes promoted job", jobs)
events = ok(client.get("/events", params={"source": "imports"}), "import events")
assert_true(events["count"] >= 2, "import flow emits ops events", events)

draft = ok(client.post("/ontology-generator/drafts", json={
    "id": "user_asset_draft",
    "asset_id": "user_asset_dataset",
    "display_name": "User Asset",
    "object_type_id": "user_asset",
    "include_actions": True,
    "create_pipeline_graph": True,
}), "create ontology draft from imported dataset", expect=201)
assert_true(draft["object_type_id"] == "user_asset" and draft["draft"]["primary_key"] == "assetId", "draft uses imported asset key", draft)
applied = ok(client.post("/ontology-generator/drafts/user_asset_draft/apply", json={
    "actor": "test",
    "create_actions": True,
    "create_pipeline_graph": True,
}), "apply imported ontology draft")
assert_true(applied["pipeline_graph_id"] == "user_asset_ontology_graph", "pipeline graph created for import", applied)
delivery = ok(client.post("/pipeline-builder/graphs/user_asset_ontology_graph/deliver", json={"actor": "test"}), "deliver imported ontology graph")
assert_true(delivery["status"] == "DELIVERED" and delivery["records_out"] == 2, "imported dataset delivered to ontology", delivery)
objects = ok(client.get("/objects/user_asset"), "read generated imported objects")
assert_true({"asset_user_1", "asset_user_2"} <= {row["id"] for row in objects}, "ontology contains imported objects", objects)

bootstrap = ok(client.post("/scenarios/asset-reliability/bootstrap", json={"actor": "test", "run_pipelines": True, "run_checks": True}), "bootstrap command center")
assert_true(bootstrap["summary"]["kpis"]["high_risk_assets"] >= 1, "command center summary has high-risk asset", bootstrap["summary"]["kpis"])
triage = ok(client.post("/scenarios/asset-reliability/run-triage", json={"actor": "test"}), "run command-center triage")
assert_true(triage["status"] == "APPROVAL_REQUIRED" and triage["approval"]["status"] == "PENDING", "triage requires approval", triage)
approval = triage["approval"]
approved = ok(client.post(f"/approvals/{approval['id']}/decision", json={
    "actor": "reviewer",
    "decision": "APPROVED",
    "reason": "productized platform test",
}), "approve triage action")
assert_true(approved["status"] == "APPROVED", "approval decision persisted", approved)
executed = ok(client.post("/actions/execute", json={
    "action_type_id": approval["action_type_id"],
    "parameters": approval["parameters"],
    "idempotency_key": f"productized-{approval['id']}",
    "actor": "reviewer",
    "approval_request_id": approval["id"],
}), "execute approved triage action")
assert_true(executed["status"] == "SUCCESS", "approved command-center action executes", executed)

dashboard = ok(client.get("/scenarios/asset-reliability/validation-dashboard"), "validation dashboard")
assert_true(dashboard["row_count"] >= 20 and not dashboard["priority_gaps"], "validation dashboard has no P0/P1 gaps", dashboard)
migrations = ok(client.get("/system/migrations"), "migration metadata")
assert_true(migrations["status"] == "PASS" and migrations["current_version"] >= 2, "migration metadata passes", migrations)
schema_health = ok(client.get("/system/schema-health"), "schema health")
assert_true(schema_health["status"] == "PASS" and "import_jobs" not in schema_health["missing_tables"], "schema health sees import table", schema_health)
event_health = ok(client.get("/system/event-consistency"), "event consistency")
assert_true(event_health["status"] in {"PASS", "WARN"} and event_health["counts"]["import_jobs"] >= 2, "event consistency includes imports", event_health)
report = client.get("/scenarios/asset-reliability/report?format=markdown")
assert_true(report.status_code == 200 and "Asset Reliability Command Center Report" in report.text, "scenario report exports markdown", report.text[:200])

project_snapshot = ok(client.get("/project/export"), "project export")
assert_true(project_snapshot["snapshot_version"] == 1 and project_snapshot["data_assets"], "project export returns snapshot", project_snapshot)
for key in ("workshop_modules", "object_explorer_explorations", "model_monitors", "incidents", "investigation_reports"):
    assert_true(key in project_snapshot, f"project export includes {key}", project_snapshot.keys())
imported = ok(client.post("/project/import", json={"snapshot": project_snapshot, "mode": "merge", "actor": "test"}), "project import merge")
assert_true(imported["status"] == "IMPORTED", "project import completes", imported)

print(f"PASS productized platform: {passed} assertions")

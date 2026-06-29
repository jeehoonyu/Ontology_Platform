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
    "/workspace/imports",
    "/workspace/ontology",
    "/workspace/pipeline",
):
    resp = client.get(route)
    assert_true(resp.status_code == 200, f"{route} loads", resp.status_code)

html = client.get("/workspace/command-center").text
assert_true(("commandCenterImport" in html and "commandCenterProofTrail" in html) or ("/react/assets/" in html and 'id="root"' in html), "command center has guided UI shell")
graph_html = client.get("/workspace/graph").text
assert_true(("platformGraphCanvas" in graph_html and "platformGraphFilters" in graph_html) or ("/react/assets/" in graph_html and 'id="root"' in graph_html), "graph workspace has visual canvas UI")
validation_html = client.get("/workspace/validation").text
assert_true(("validationView" in validation_html and "validationMatrix" in validation_html) or ("/react/assets/" in validation_html and 'id="root"' in validation_html), "validation workspace is present")

root = ok(client.get("/"), "root capability catalog")
for capability in ("data_imports", "validation_dashboard", "project_snapshot", "schema_health", "event_consistency", "import_transforms", "mapping_suggestions", "hybrid_connector_preview", "stream_replay", "react_vite_frontend", "project_validation"):
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

transform_job = ok(client.post("/imports/csv", json={
    "id": "transform_asset_import",
    "filename": "transform-assets.csv",
    "display_name": "Transform Asset Import",
    "target_dataset_id": "transform_asset_dataset",
    "content": "asset_id,name,status,criticality,vibration_ips,temperature_f,longitude,latitude\nasset_transform_1,Transform Pump,degraded,HIGH,0.5,212,-122.4012,37.7924\nasset_transform_1,Transform Pump,degraded,HIGH,0.5,212,-122.4012,37.7924\n",
}), "create transform import", expect=201)
suggestions = ok(client.get("/imports/jobs/transform_asset_import/mapping-suggestions?template=asset"), "mapping suggestions")
assert_true(suggestions["mapping"]["asset_id"] == "asset_id" and any(row["target"] == "name" for row in suggestions["suggestions"]), "mapping suggestions find asset fields", suggestions)
preview_transform = ok(client.post("/imports/jobs/transform_asset_import/apply-transforms", json={
    "preview_only": True,
    "steps": [{"op": "deduplicate", "keys": ["asset_id"]}],
}), "preview import transforms")
assert_true(preview_transform["summary"]["duplicates_removed"] == 1 and preview_transform["status"] == "PREVIEW", "transform preview detects duplicate", preview_transform)
transformed = ok(client.post("/imports/jobs/transform_asset_import/apply-transforms", json={
    "actor": "test",
    "steps": [
        {"op": "enum_cleanup", "field": "status", "mapping": {"degraded": "DEGRADED"}},
        {"op": "enum_cleanup", "field": "criticality", "mapping": {"high": "high"}},
        {"op": "normalize_unit", "source": "temperature_f", "target": "temperature_c", "from_unit": "fahrenheit", "to_unit": "celsius"},
        {"op": "normalize_unit", "source": "vibration_ips", "target": "vibration_mm_s", "from_unit": "ips", "to_unit": "mm_s"},
        {"op": "derive_point", "latitude_field": "latitude", "longitude_field": "longitude", "target": "geometry"},
        {"op": "deduplicate", "keys": ["asset_id"]}
    ],
}), "apply import transforms")
assert_true(transformed["summary"]["duplicates_removed"] == 1 and transformed["job"]["record_count"] == 1, "transform mutates import job", transformed)
assert_true(transformed["preview_rows"][0]["temperature_c"] == 100.0 and transformed["preview_rows"][0]["geometry"]["type"] == "Point", "unit and geometry transforms apply", transformed["preview_rows"])

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

source = ok(client.post("/connections/sources", json={
    "id": "productized_rest_source",
    "display_name": "Productized REST Source",
    "source_type": "rest",
    "config": {
        "base_url": "http://localhost:9000/assets",
        "sample_records": [{"asset_id": "asset_connector_1", "name": "Connector Pump", "status": "RUNNING", "criticality": "medium"}],
    },
}), "create connector source")
source_preview = ok(client.post("/connections/sources/productized_rest_source/preview", json={"limit": 5}), "preview connector source")
assert_true(source_preview["status"] == "READY" and source_preview["record_count"] == 1, "connector preview returns sample records", source_preview)
connector_import = ok(client.post("/connections/sources/productized_rest_source/generate-import-job", json={
    "id": "productized_connector_import",
    "target_dataset_id": "productized_connector_dataset",
    "template": "asset",
    "actor": "test",
}), "connector generates import job")
assert_true(connector_import["status"] == "IMPORT_JOB_CREATED" and connector_import["job"]["template"] == "asset", "connector import job is template validated", connector_import)
ok(client.post("/data-assets", json={
    "id": "connector_sync_target",
    "display_name": "Connector Sync Target",
    "description": "Target for sync validation",
    "kind": "dataset",
    "asset_schema": {},
    "records": [],
}), "create connector sync target", expect=200)
sync = ok(client.post("/connections/sources/productized_rest_source/syncs", json={
    "id": "productized_connector_sync",
    "target_asset_id": "connector_sync_target",
    "mode": "snapshot",
    "sample_records": [{"asset_id": "asset_sync_1", "name": "Sync Pump"}],
}), "create connector sync")
sync_validation = ok(client.post("/connections/syncs/productized_connector_sync/validate", json={}), "validate connector sync")
assert_true(sync_validation["status"] == "PASS" and sync_validation["schema"], "connector sync validation passes", sync_validation)
sync_run = ok(client.post("/connections/syncs/productized_connector_sync/run"), "run connector sync")
assert_true(sync_run["records_out"] == 1, "connector sync writes target records", sync_run)

stream = ok(client.post("/streams", json={
    "id": "productized_sensor_stream",
    "display_name": "Productized Sensor Stream",
    "schema": {"sample_records": [{"reading_id": "stream_sample", "asset_id": "asset_pump_4", "observed_at": "1782684300"}]},
}), "create replay stream")
stream_replay = ok(client.post("/streams/productized_sensor_stream/replay", json={
    "actor": "test",
    "target_asset_id": "productized_stream_archive",
    "archive_to_dataset": True,
    "timestamp_field": "observed_at",
    "records": [
        {"reading_id": "stream_1", "asset_id": "asset_pump_4", "observed_at": "1782684300"},
        {"reading_id": "stream_2", "asset_id": "asset_pump_4", "observed_at": "1782684310"},
    ],
}), "replay stream to dataset")
assert_true(stream_replay["published"] == 2 and stream_replay["archived"] == 2, "stream replay publishes and archives records", stream_replay)

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
assert_true(migrations["status"] == "PASS" and migrations["current_version"] >= 3 and migrations["migrations"][-1]["applied_at"], "migration metadata passes", migrations)
schema_health = ok(client.get("/system/schema-health"), "schema health")
assert_true(schema_health["status"] == "PASS" and "import_jobs" not in schema_health["missing_tables"], "schema health sees import table", schema_health)
event_health = ok(client.get("/system/event-consistency"), "event consistency")
assert_true(event_health["status"] in {"PASS", "WARN"} and event_health["counts"]["import_jobs"] >= 2 and event_health["counts"]["stream_replays"] >= 1, "event consistency includes imports and streams", event_health)
project_validation = ok(client.get("/project/validate"), "project validate")
assert_true(project_validation["status"] in {"PASS", "WARN"} and project_validation["sections"]["snapshot_coverage"]["status"] == "PASS", "project validation summarizes snapshot coverage", project_validation)
report = client.get("/scenarios/asset-reliability/report?format=markdown")
assert_true(report.status_code == 200 and "Asset Reliability Command Center Report" in report.text, "scenario report exports markdown", report.text[:200])

project_snapshot = ok(client.get("/project/export"), "project export")
assert_true(project_snapshot["snapshot_version"] == 1 and project_snapshot["data_assets"], "project export returns snapshot", project_snapshot)
for key in ("workshop_modules", "object_explorer_explorations", "model_monitors", "model_monitor_runs", "model_prediction_logs", "connection_sources", "connection_syncs", "streams", "stream_records", "schedules", "builds", "webhook_listeners", "incidents", "investigation_evidence", "investigation_reports"):
    assert_true(key in project_snapshot, f"project export includes {key}", project_snapshot.keys())
imported = ok(client.post("/project/import", json={"snapshot": project_snapshot, "mode": "merge", "actor": "test"}), "project import merge")
assert_true(imported["status"] == "IMPORTED", "project import completes", imported)

print(f"PASS productized platform: {passed} assertions")

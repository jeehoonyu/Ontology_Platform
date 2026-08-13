"""Import-to-ontology delivery requires and honors a governed production revision."""
import os
import tempfile


tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tmpdir.name, 'import_governed_delivery.db')}"
os.environ["AUTH_MODE"] = "local"
os.environ["APP_ENV"] = "test"
os.environ["ONTOLOGY_CONTRACT_ENFORCEMENT"] = "strict"

from fastapi.testclient import TestClient  # noqa: E402
from app.main import app  # noqa: E402


client = TestClient(app)
passed = 0


def ok(response, label, expect=200):
    global passed
    assert response.status_code == expect, f"{label}: {response.status_code} {response.text[:1800]}"
    passed += 1
    return response.json() if response.content else {}


# Mirror a long-lived production project: a published environment exists
# before the organization imports and generates a new ontology type.
baseline_change = ok(client.post("/ontology/change-sets", json={
    "project_id": "default",
    "title": "Publish empty organization baseline",
    "changes": [],
}), "create organization baseline", 201)
ok(client.post(f"/ontology/change-sets/{baseline_change['id']}/validate"), "validate organization baseline")
ok(client.post(f"/ontology/change-sets/{baseline_change['id']}/decision", json={"approve": True}), "approve organization baseline")
ok(client.post(f"/ontology/change-sets/{baseline_change['id']}/publish", json={
    "environment": "production",
}), "publish organization baseline")


job = ok(client.post("/imports/csv", json={
    "id": "governed_asset_import",
    "project_id": "default",
    "filename": "assets.csv",
    "display_name": "Governed Assets",
    "content": (
        "asset_id,name,status,latitude,longitude\n"
        "governed-asset-1,Main Pump,DEGRADED,37.79,-122.40\n"
        "governed-asset-2,Backup Pump,RUNNING,37.78,-122.41\n"
    ),
}), "create import", 201)
assert job["status"] == "READY"

validation = ok(client.post("/imports/jobs/governed_asset_import/validate", json={
    "template": "asset",
}), "validate import")
assert validation["validation"]["status"] == "READY"

generated = ok(client.post("/imports/jobs/governed_asset_import/generate-ontology-draft", json={
    "draft_id": "governed_asset_draft",
    "object_type_id": "governed_asset",
    "promote_dataset_id": "governed_assets",
    "include_actions": True,
    "create_pipeline_graph": True,
}), "generate ontology draft")
assert generated["status"] == "DRAFT_CREATED"

draft_validation = ok(client.post("/ontology-generator/drafts/governed_asset_draft/validate"), "validate ontology draft")
assert draft_validation["status"] in {"PASS", "WARN"}
applied = ok(client.post("/ontology-generator/drafts/governed_asset_draft/apply", json={}), "apply ontology draft")
graph_id = applied["pipeline_graph_id"]

ok(client.post("/action-types", json={
    "id": "inspect-governed-asset",
    "project_id": "default",
    "display_name": "Inspect governed asset",
    "parameters": {"object_id": {"type": "string"}},
    "rules": {},
}), "create action with stable hyphenated resource ID")

blocked = ok(client.post(f"/pipeline-builder/graphs/{graph_id}/deliver", json={}), "block unpublished ontology delivery", 422)
assert blocked["detail"]["message"] == "Ontology contract validation failed"
assert {row["code"] for row in blocked["detail"]["issues"]} == {"OBJECT_TYPE_NOT_IN_REVISION"}

change_set = ok(client.post("/ontology/change-sets", json={
    "project_id": "default",
    "title": "Publish governed imported asset ontology",
    "capture_current": True,
    "changes": [],
}), "create ontology release", 201)
assert change_set["diff"]["classification"] == "NON_BREAKING"
assert any(
    row["kind"] == "ADDED" and row["resource_type"] == "object_type" and row["resource_id"] == "governed_asset"
    for row in change_set["diff"]["entries"]
)
ok(client.post(f"/ontology/change-sets/{change_set['id']}/validate"), "validate ontology release")
ok(client.post(f"/ontology/change-sets/{change_set['id']}/decision", json={"approve": True}), "approve ontology release")
published = ok(client.post(f"/ontology/change-sets/{change_set['id']}/publish", json={
    "environment": "production",
}), "publish ontology release")
assert published["revision"]["status"] == "PUBLISHED"

delivery = ok(client.post(f"/pipeline-builder/graphs/{graph_id}/deliver", json={}), "deliver governed pipeline")
assert delivery["status"] == "DELIVERED"
assert delivery["records_out"] == 2
assert delivery["metrics"]["ontology_revision_id"] == published["revision"]["id"]
assert delivery["metrics"]["ontology_binding_count"] == 1

objects = ok(client.get("/objects/governed_asset"), "read materialized ontology objects")
assert len(objects) == 2
assert {row["id"] for row in objects} == {"governed-asset-1", "governed-asset-2"}

print(f"\nGoverned import-to-ontology delivery verified: {passed} assertions passed.")
from app.database import engine as _engine  # noqa: E402
_engine.dispose()
tmpdir.cleanup()

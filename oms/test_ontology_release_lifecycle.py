"""Immutable ontology revision, review, publish, and rollback lifecycle."""
import os
import tempfile

tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tmpdir.name, 'ontology_release.db')}"
os.environ["AUTH_MODE"] = "local"
os.environ["APP_ENV"] = "test"

from fastapi.testclient import TestClient  # noqa: E402
from app.main import app  # noqa: E402

client = TestClient(app)
passed = 0


def ok(response, label, expect=200):
    global passed
    assert response.status_code == expect, f"{label}: {response.status_code} {response.text[:1600]}"
    passed += 1
    return response.json() if response.content else {}


ok(client.post("/object-types", json={
    "id": "release_asset",
    "project_id": "default",
    "display_name": "Release Asset",
    "description": "Asset governed by ontology releases",
    "properties": {
        "assetId": {"type": "string", "required": True},
        "status": {"type": "string"},
    },
}), "create object type")
ok(client.put("/ontology/object-types/release_asset/profile", json={
    "api_name": "ReleaseAsset",
    "primary_key": "assetId",
    "title_key": "assetId",
    "plural_name": "Release Assets",
    "properties": {
        "assetId": {"base_type": "string", "required": True},
        "status": {"base_type": "string"},
    },
}), "create object type profile")
ok(client.post("/objects", json={
    "id": "release_asset_1",
    "project_id": "default",
    "object_type_id": "release_asset",
    "properties": {"assetId": "A-100", "status": "DEGRADED", "legacyEvidence": "preserve-me"},
}), "create live object")

baseline = ok(client.post("/ontology/revisions/capture", json={"project_id": "default"}), "capture baseline", 201)
assert baseline["status"] == "DRAFT"
assert baseline["validation"]["status"] == "PASS"
assert baseline["manifest"]["object_types"][0]["id"] == "release_asset"

add_change = ok(client.post("/ontology/change-sets", json={
    "project_id": "default",
    "title": "Add risk score",
    "base_revision_id": baseline["id"],
    "changes": [{
        "operation": "add_property",
        "object_type_id": "release_asset",
        "property_name": "riskScore",
        "spec": {"base_type": "double", "required": False, "description": "Deterministic operational risk"},
    }],
}), "create additive change set", 201)
assert add_change["diff"]["classification"] == "NON_BREAKING"
assert add_change["migration_plan"]["status"] == "READY"

validated = ok(client.post(f"/ontology/change-sets/{add_change['id']}/validate"), "validate additive change")
assert validated["status"] == "VALIDATED" and validated["validation"]["status"] == "PASS"
approved = ok(client.post(f"/ontology/change-sets/{add_change['id']}/decision", json={"approve": True}), "approve additive change")
assert approved["status"] == "APPROVED"
published = ok(client.post(f"/ontology/change-sets/{add_change['id']}/publish", json={
    "environment": "production",
    "expected_checksum": add_change["checksum"],
}), "publish additive change")
published_revision = published["revision"]
assert published_revision["status"] == "PUBLISHED"
assert published["environment"]["current_revision_id"] == published_revision["id"]

manager = ok(client.get("/ui-state/ontology/object-types/release_asset"), "read published manager")
assert any(row["name"] == "riskScore" for row in manager["cards"]["properties"]["rows"])

archive_change = ok(client.post("/ontology/change-sets", json={
    "project_id": "default",
    "title": "Archive status field",
    "base_revision_id": published_revision["id"],
    "changes": [{"operation": "archive_property", "object_type_id": "release_asset", "property_name": "status"}],
}), "create breaking change set", 201)
assert archive_change["diff"]["classification"] == "BREAKING"
assert archive_change["impact"]["live_objects"] == 1
assert archive_change["migration_plan"]["preserves_existing_values"] is True
ok(client.post(f"/ontology/change-sets/{archive_change['id']}/validate"), "validate breaking change")
ok(client.post(f"/ontology/change-sets/{archive_change['id']}/decision", json={"approve": True}), "approve breaking change")
blocked = client.post(f"/ontology/change-sets/{archive_change['id']}/publish", json={"environment": "production"})
ok(blocked, "require explicit breaking-change acknowledgement", 409)
breaking_publish = ok(client.post(f"/ontology/change-sets/{archive_change['id']}/publish", json={
    "environment": "production",
    "allow_breaking": True,
}), "publish acknowledged breaking change")
assert breaking_publish["applied"]["archived"] == 0

live_object = ok(client.get("/objects/release_asset/release_asset_1"), "read live object after schema archive")
assert live_object["properties"]["status"] == "DEGRADED"
manager_after_archive = ok(client.get("/ui-state/ontology/object-types/release_asset"), "read archived manager")
assert all(row["name"] != "status" for row in manager_after_archive["cards"]["properties"]["rows"])

rollback = ok(client.post("/ontology/environments/production/rollback", json={
    "project_id": "default",
    "revision_id": published_revision["id"],
}), "roll back production ontology")
assert rollback["restored_from_revision_id"] == published_revision["id"]
assert rollback["revision"]["status"] == "PUBLISHED"
manager_after_rollback = ok(client.get("/ui-state/ontology/object-types/release_asset"), "read restored manager")
assert any(row["name"] == "status" for row in manager_after_rollback["cards"]["properties"]["rows"])

revisions = ok(client.get("/ontology/revisions?project_id=default"), "list revisions")
assert len(revisions) >= 4
environments = ok(client.get("/ontology/environments?project_id=default"), "list environments")
assert environments[0]["current_revision_id"] == rollback["revision"]["id"]
audit = ok(client.get("/audit-logs"), "read release audit")
event_types = {row["event_type"] for row in audit}
assert {"ontology.revision.captured", "ontology.change_set.created", "ontology.change_set.validated", "ontology.change_set.decided", "ontology.change_set.published", "ontology.environment.rolled_back"} <= event_types

print(f"\nOntology release lifecycle verified: {passed} assertions passed.")
from app.database import engine as _engine  # noqa: E402
_engine.dispose()
tmpdir.cleanup()

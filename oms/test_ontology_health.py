"""Ontology health, policy simulation, and generated object-view acceptance."""
import os
import tempfile

tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tmpdir.name, 'ontology_health.db')}"
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
    "id": "health_asset", "project_id": "default", "display_name": "Health Asset",
    "description": "Operational asset with governed identity and lineage",
    "properties": {"assetId": {"type": "string"}, "name": {"type": "string"}, "riskScore": {"type": "number"}},
}), "create healthy object type")
ok(client.put("/ontology/object-types/health_asset/profile", json={
    "api_name": "HealthAsset", "primary_key": "assetId", "title_key": "name", "plural_name": "Health Assets",
    "properties": {
        "assetId": {"base_type": "string", "required": True},
        "name": {"base_type": "string", "required": True},
        "riskScore": {"base_type": "double", "required": False},
    },
}), "create healthy profile")
ok(client.post("/data-assets", json={
    "id": "health_asset_dataset", "project_id": "default", "display_name": "Health assets",
    "kind": "dataset", "asset_schema": {}, "records": [{"assetId": "HA-1", "name": "Pump 1", "riskScore": 0.72}],
}), "create healthy source dataset")
ok(client.post("/objects", json={
    "id": "health_asset_1", "project_id": "default", "object_type_id": "health_asset",
    "source_asset_id": "health_asset_dataset", "properties": {"assetId": "HA-1", "name": "Pump 1", "riskScore": 0.72},
}), "create healthy object")

initial = ok(client.post("/ontology/health/run", json={"project_id": "default", "object_type_id": "health_asset"}), "run initial health")
assert initial["status"] == "WARN" and initial["score"] < 100
assert {item["code"] for item in initial["findings"]} == {"MISSING_OBJECT_VIEW", "MISSING_POLICY_COVERAGE"}
assert initial["metrics"]["type_conformance"] == 1.0 and initial["metrics"]["lineage_coverage"] == 1.0

generated = ok(client.post("/ontology/object-types/health_asset/generate-standard-view", json={"publish": True}), "generate standard view")
assert generated["created"] is True and generated["published_version_id"]
rendered = ok(client.get("/object-views/health_asset/health_asset_1/rendered"), "render generated view")
assert rendered["kind"] == "configured"
assert rendered["tabs"][0]["widgets"][0]["resolved"]["properties"]["name"] == "Pump 1"

ok(client.post("/policies", json={
    "id": "health_asset_view_policy", "display_name": "Health asset readers", "effect": "ALLOW",
    "action": "view", "resource_kind": "object_type", "object_type_id": "health_asset", "priority": 10,
}), "create object policy", 201)
healthy = ok(client.post("/ontology/health/run", json={"project_id": "default", "object_type_id": "health_asset"}), "run healthy evaluation")
assert healthy["status"] == "PASS" and healthy["score"] == 100 and not healthy["findings"]

simulation = ok(client.post("/ontology/object-types/health_asset/policies/simulate", json={
    "principal": "contractor", "action": "view", "purpose": "external_review",
    "hypothetical_rules": [{
        "display_name": "Block external review", "effect": "DENY", "principal": "contractor",
        "action": "view", "resource_kind": "object_type", "object_type_id": "health_asset", "priority": 1,
    }],
}), "simulate object policy")
assert simulation["decision"]["decision"] == "DENY" and simulation["persisted"] is False

ok(client.post("/object-types", json={
    "id": "broken_asset", "project_id": "default", "display_name": "Broken Asset", "properties": {},
}), "create broken type")
failed = ok(client.post("/ontology/health/run", json={"project_id": "default", "object_type_id": "broken_asset"}), "run failing health")
assert failed["status"] == "FAIL"
failed_codes = {item["code"] for item in failed["findings"]}
assert {"EMPTY_SCHEMA", "MISSING_PRIMARY_KEY", "MISSING_TITLE_KEY", "NO_RUNTIME_OBJECTS"} <= failed_codes

latest = ok(client.get("/ontology/health/latest?project_id=default&object_type_id=health_asset"), "read latest scoped health")
assert latest["id"] == healthy["id"]
ui_state = ok(client.get("/ui-state/ontology/health?project_id=default&object_type_id=health_asset"), "read health UI state")
assert ui_state["summary"]["status"] == "PASS" and ui_state["primary_actions"] and ui_state["permissions"]
runs = ok(client.get("/ontology/health/runs?project_id=default"), "list health history")
assert runs["count"] == 3
audit = ok(client.get("/audit-logs"), "read ontology health audit")
event_types = {row["event_type"] for row in audit}
assert {"ontology.health.evaluated", "ontology.object_view.generated"} <= event_types

print(f"\nOntology health and generated views verified: {passed} assertions passed.")
from app.database import engine as _engine  # noqa: E402
_engine.dispose()
tmpdir.cleanup()

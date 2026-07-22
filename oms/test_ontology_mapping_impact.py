"""Dataset-to-ontology mapping, hydration preview, and impact guardrails."""
import os
import tempfile

tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tmpdir.name, 'ontology_mapping.db')}"
os.environ["AUTH_MODE"] = "local"
os.environ["APP_ENV"] = "test"

from fastapi.testclient import TestClient  # noqa: E402
from app.main import app  # noqa: E402

client = TestClient(app)
passed = 0


def ok(response, label, expect=200):
    global passed
    assert response.status_code == expect, f"{label}: {response.status_code} {response.text[:1200]}"
    passed += 1
    return response.json() if response.content else {}


ok(client.post("/data-assets", json={
    "id": "mapping_assets", "display_name": "Mapping assets", "kind": "dataset", "asset_schema": {},
    "records": [
        {"asset_id": "A-100", "asset_name": "Pump 100", "risk_score": 0.87, "latitude": 37.79},
        {"asset_id": "A-200", "asset_name": "Pump 200", "risk_score": 0.31, "latitude": 37.78},
    ],
}), "create mapping dataset")
ok(client.post("/object-types", json={
    "id": "mapped_asset", "display_name": "Mapped Asset", "description": "Mapping target", "properties": {
        "assetId": {"type": "string"}, "assetName": {"type": "string"}, "riskScore": {"type": "number"},
    },
}), "create mapping object type")
ok(client.put("/ontology/object-types/mapped_asset/profile", json={
    "api_name": "MappedAsset", "primary_key": "assetId", "title_key": "assetName", "plural_name": "Mapped Assets",
    "properties": {
        "assetId": {"base_type": "string", "required": True},
        "assetName": {"base_type": "string", "required": True},
        "riskScore": {"base_type": "double", "required": False},
    },
}), "create mapping profile")

suggested = ok(client.post("/ontology/mappings/preview", json={
    "asset_id": "mapping_assets", "object_type_id": "mapped_asset", "mappings": [], "limit": 10,
}), "suggest mappings")
assert suggested["status"] == "WARN" and len(suggested["mappings"]) == 3, suggested
assert suggested["hydrated_preview"][0]["assetId"] == "A-100", suggested
assert any(field["name"] == "latitude" and not field["mapped"] for field in suggested["source_fields"]), suggested

saved = ok(client.post("/ontology/object-types/mapped_asset/datasource-mappings", json={
    "asset_id": "mapping_assets", "mappings": suggested["mappings"], "actor": "test",
}), "save datasource mapping")
assert saved["mapping"]["mapped_property_count"] == 3, saved
assert saved["manager"]["cards"]["datasources"]["count"] == 1, saved
assert saved["manager"]["cards"]["datasources"]["rows"][0]["status"] == "mapped", saved

missing_required = client.post("/ontology/object-types/mapped_asset/datasource-mappings", json={
    "asset_id": "mapping_assets",
    "mappings": [{"source_field": "risk_score", "target_property": "riskScore"}],
    "actor": "test",
})
assert missing_required.status_code == 422
codes = {item["code"] for item in missing_required.json()["detail"]["preview"]["errors"]}
assert "REQUIRED_UNMAPPED" in codes, missing_required.text
passed += 1

impact = ok(client.post("/ontology/changes/impact", json={
    "object_type_id": "mapped_asset", "changes": [{"operation": "archive", "property_name": "riskScore"}],
}), "preview schema change impact")
assert impact["destructive_changes"] and impact["recommended_action"], impact

audit = ok(client.get("/audit-logs"), "mapping audit")
assert any(row["event_type"] == "ontology.datasource_mapping.saved" and row["subject_id"] == "mapped_asset" for row in audit), audit

print(f"\nOntology mapping and impact verified: {passed} assertions passed.")
from app.database import engine as _engine  # noqa: E402
_engine.dispose()
tmpdir.cleanup()

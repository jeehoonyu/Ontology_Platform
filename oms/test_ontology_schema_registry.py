"""Published ontology registry, compatibility, JSON Schema, and typed SDK contracts."""
import os
import tempfile
import hashlib
import io
import json
import tarfile
import zipfile

tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tmpdir.name, 'ontology_schema_registry.db')}"
os.environ["AUTH_MODE"] = "local"
os.environ["APP_ENV"] = "test"

from fastapi.testclient import TestClient  # noqa: E402
from app.main import app  # noqa: E402

client = TestClient(app)
passed = 0


def ok(response, label, expect=200):
    global passed
    assert response.status_code == expect, f"{label}: {response.status_code} {response.text[:1800]}"
    passed += 1
    return response.json() if response.content else {}


ok(client.post("/object-types", json={
    "id": "registry_asset", "project_id": "default", "display_name": "Registry Asset",
    "description": "Published client contract target",
    "properties": {"assetId": {"type": "string"}, "name": {"type": "string"}, "risk": {"type": "number"}},
}), "create registry object type")
ok(client.put("/ontology/object-types/registry_asset/profile", json={
    "api_name": "RegistryAsset", "primary_key": "assetId", "title_key": "name", "plural_name": "Registry Assets",
    "properties": {
        "assetId": {"base_type": "string", "required": True, "description": "Stable asset identity"},
        "name": {"base_type": "string", "required": True},
        "risk": {"base_type": "double", "required": False, "minimum": 0, "maximum": 100},
    },
}), "create registry profile")

change = ok(client.post("/ontology/change-sets", json={
    "project_id": "default", "title": "Publish registry baseline", "changes": [],
}), "create baseline change set", 201)
change_id = change["id"]
ok(client.post(f"/ontology/change-sets/{change_id}/validate"), "validate baseline")
ok(client.post(f"/ontology/change-sets/{change_id}/decision", json={"approve": True}), "approve baseline")
published = ok(client.post(f"/ontology/change-sets/{change_id}/publish", json={"environment": "production"}), "publish baseline")
revision_id = published["revision"]["id"]

compatibility = ok(client.post("/ontology/registry/compatibility", json={
    "project_id": "default", "revision_id": revision_id, "channel": "production",
}), "check first registry compatibility")
assert compatibility["classification"] == "NON_BREAKING" and compatibility["against_registry_id"] is None

entry = ok(client.post("/ontology/registry/publish", json={
    "project_id": "default", "revision_id": revision_id, "version": "1.0.0", "channel": "production",
}), "publish registry entry", 201)
entry_id = entry["id"]
assert entry["compatibility"]["classification"] == "NON_BREAKING"
assert len(entry["checksum"]) == 64
assert ok(client.post("/ontology/registry/publish", json={
    "project_id": "default", "revision_id": revision_id, "version": "1.0.0", "channel": "production",
}), "reject duplicate registry version", 409)

listing = ok(client.get("/ontology/registry?project_id=default"), "list registry")
assert listing["count"] == 1 and listing["entries"][0]["id"] == entry_id
current = ok(client.get("/ontology/registry/current?project_id=default&channel=production"), "read current registry")
assert current["version"] == "1.0.0" and current["revision_id"] == revision_id
schema = ok(client.get(f"/ontology/registry/{entry_id}/schema"), "export JSON Schema")
asset_schema = schema["schema"]["$defs"]["registry_asset"]
assert asset_schema["required"] == ["assetId", "name"]
assert asset_schema["properties"]["risk"]["type"] == "number"
assert asset_schema["additionalProperties"] is False

typescript = ok(client.get(f"/ontology/registry/{entry_id}/sdk/typescript"), "generate TypeScript SDK")
ts_source = typescript["files"]["ontology.ts"]
assert "export interface RegistryAsset" in ts_source
assert "assetId: string;" in ts_source and "risk?: number;" in ts_source
assert "class OntologyClient" in ts_source and "/object-sets/search" in ts_source
python_sdk = ok(client.get(f"/ontology/registry/{entry_id}/sdk/python"), "generate Python SDK")
py_source = python_sdk["files"]["ontology_client.py"]
assert "class RegistryAsset" in py_source and "risk: Optional[float] = None" in py_source
assert "class OntologyClient" in py_source
compile(py_source, "ontology_client.py", "exec")

packages = ok(client.get(f"/ontology/registry/{entry_id}/packages"), "list installable SDK packages")
assert {item["ecosystem"] for item in packages["packages"]} == {"npm", "pypi"}
assert all(len(item["sha256"]) == 64 and item["byte_size"] > 0 for item in packages["packages"])

npm_meta = next(item for item in packages["packages"] if item["ecosystem"] == "npm")
npm_download = client.get(npm_meta["download_url"])
assert npm_download.status_code == 200 and npm_download.headers["x-content-sha256"] == npm_meta["sha256"]
assert hashlib.sha256(npm_download.content).hexdigest() == npm_meta["sha256"]
with tarfile.open(fileobj=io.BytesIO(npm_download.content), mode="r:gz") as package:
    names = set(package.getnames())
    assert {"package/package.json", "package/index.js", "package/index.d.ts", "package/ontology.schema.json"} <= names
    package_json = json.loads(package.extractfile("package/package.json").read())
    assert package_json["name"] == "@ontologyos/default-production" and package_json["version"] == "1.0.0"

wheel_meta = next(item for item in packages["packages"] if item["ecosystem"] == "pypi")
wheel_download = client.get(wheel_meta["download_url"])
assert wheel_download.status_code == 200 and wheel_download.headers["x-content-sha256"] == wheel_meta["sha256"]
assert hashlib.sha256(wheel_download.content).hexdigest() == wheel_meta["sha256"]
with zipfile.ZipFile(io.BytesIO(wheel_download.content)) as wheel:
    names = set(wheel.namelist())
    assert "ontologyos_default_production/__init__.py" in names
    assert any(name.endswith(".dist-info/RECORD") for name in names)

# Package bytes are reproducible and therefore safe to address by checksum.
assert client.get(npm_meta["download_url"]).content == npm_download.content
assert client.get(wheel_meta["download_url"]).content == wheel_download.content

breaking = ok(client.post("/ontology/change-sets", json={
    "project_id": "default", "title": "Archive required registry name",
    "base_revision_id": revision_id,
    "changes": [{"operation": "archive_property", "object_type_id": "registry_asset", "property_name": "name"}],
}), "create breaking registry change", 201)
breaking_id = breaking["id"]
assert breaking["diff"]["classification"] == "BREAKING"
ok(client.post(f"/ontology/change-sets/{breaking_id}/validate"), "validate breaking change")
ok(client.post(f"/ontology/change-sets/{breaking_id}/decision", json={"approve": True}), "approve breaking change")
published_breaking = ok(client.post(f"/ontology/change-sets/{breaking_id}/publish", json={
    "environment": "production", "allow_breaking": True,
}), "publish breaking revision")
breaking_revision_id = published_breaking["revision"]["id"]
blocked = ok(client.post("/ontology/registry/publish", json={
    "project_id": "default", "revision_id": breaking_revision_id, "version": "2.0.0", "channel": "production",
}), "block unacknowledged breaking registry release", 409)
assert blocked["detail"]["compatibility"]["classification"] == "BREAKING"
second = ok(client.post("/ontology/registry/publish", json={
    "project_id": "default", "revision_id": breaking_revision_id, "version": "2.0.0",
    "channel": "production", "allow_breaking": True,
}), "publish acknowledged breaking registry release", 201)
assert second["compatibility"]["against_registry_id"] == entry_id

ui = ok(client.get("/ui-state/ontology/registry"), "read registry UI state")
assert ui["summary"]["status"] == "PUBLISHED" and ui["summary"]["current_version"] == "2.0.0"
assert len(ui["sections"]["entries"]) == 2 and ui["evidence_links"]
audit = ok(client.get("/audit-logs"), "read registry audit")
assert sum(1 for row in audit if row["event_type"] == "ontology.registry.published") == 2
snapshot = ok(client.get("/project/export?project_id=default"), "export ontology lifecycle snapshot")
assert len(snapshot["ontology_registry_entries"]) == 2
assert snapshot["ontology_revisions"] and snapshot["ontology_change_sets"] and snapshot["ontology_environments"]
assert snapshot["integrity"]["counts"]["ontology_registry_entries"] == 2
restored = ok(client.post("/project/import", json={"snapshot": snapshot, "mode": "merge"}), "restore ontology lifecycle snapshot")
assert restored["status"] == "IMPORTED"
assert ok(client.get("/ontology/registry?project_id=default"), "verify registry after restore")["count"] == 2

print(f"\nOntology schema registry verified: {passed} assertions passed.")
from app.database import engine as _engine  # noqa: E402
_engine.dispose()
tmpdir.cleanup()

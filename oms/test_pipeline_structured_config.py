"""Structured Pipeline Builder node configuration and field-lineage evidence."""
import os
import tempfile

tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tmpdir.name, 'pipeline_config.db')}"
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
    "id": "structured_assets", "display_name": "Structured assets", "kind": "dataset",
    "asset_schema": {},
    "records": [
        {"asset_id": "A-1", "latitude": 37.791, "longitude": -122.401, "risk": 0.91},
        {"asset_id": "A-2", "latitude": 37.785, "longitude": -122.407, "risk": 0.22},
    ],
}), "create source asset")

catalog = ok(client.get("/pipeline-builder/node-types"), "structured node catalog")
by_type = {item["type"]: item for item in catalog["node_types"]}
assert by_type["derive_mgrs"]["configuration_schema"]["fields"], catalog
assert by_type["window"]["configuration_schema"]["fields"], catalog

ok(client.post("/pipeline-builder/graphs", json={
    "id": "structured_pipeline", "display_name": "Structured pipeline",
    "nodes": [
        {"id": "input", "type": "input_dataset", "label": "Assets", "config": {"asset_id": "structured_assets"}},
        {"id": "mgrs", "type": "derive_mgrs", "label": "Add MGRS", "config": {}},
        {"id": "filter", "type": "filter", "label": "High risk", "config": {}},
        {"id": "output", "type": "dataset_output", "label": "Curated", "config": {"asset_id": "structured_output"}},
    ],
    "edges": [
        {"id": "e1", "source": "input", "target": "mgrs"},
        {"id": "e2", "source": "mgrs", "target": "filter"},
        {"id": "e3", "source": "filter", "target": "output"},
    ],
}), "create configurable graph", 201)

invalid = client.patch("/pipeline-builder/graphs/structured_pipeline/nodes/mgrs", json={
    "label": "MGRS", "config": {"latitude_field": "latitude"},
})
assert invalid.status_code == 422 and invalid.json()["detail"]["validation"]["errors"], invalid.text
passed += 1

mgrs = ok(client.patch("/pipeline-builder/graphs/structured_pipeline/nodes/mgrs", json={
    "label": "Derive MGRS grid",
    "config": {"latitude_field": "latitude", "longitude_field": "longitude", "target_field": "mgrs", "precision": 5},
    "actor": "test",
}), "configure MGRS node")
assert mgrs["metadata"]["configuration_validation"]["status"] == "VALID", mgrs
assert any(field["name"] == "mgrs" for field in mgrs["preview"]["columns"]), mgrs
assert any(row["field"] == "mgrs" for row in mgrs["metadata"]["field_lineage"]), mgrs

filtered = ok(client.patch("/pipeline-builder/graphs/structured_pipeline/nodes/filter", json={
    "label": "Retain high-risk assets",
    "config": {"field": "risk", "operator": "gte", "value": 0.8},
    "actor": "test",
}), "configure typed filter")
assert filtered["preview"]["row_count"] == 1, filtered

preview = ok(client.post("/pipeline-builder/graphs/structured_pipeline/preview", json={"limit": 20}), "preview configured pipeline")
assert preview["row_count"] == 1 and preview["rows"][0]["asset_id"] == "A-1", preview
assert preview["rows"][0]["mgrs"], preview

delivered = ok(client.post("/pipeline-builder/graphs/structured_pipeline/deliver", json={
    "output_asset_id": "structured_output", "actor": "test",
}), "deliver configured pipeline")
assert delivered["status"] == "DELIVERED" and delivered["records_out"] == 1, delivered

print(f"\nStructured pipeline configuration verified: {passed} assertions passed.")
from app.database import engine as _engine  # noqa: E402
_engine.dispose()
tmpdir.cleanup()

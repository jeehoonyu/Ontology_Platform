"""Industrial onboarding consumes registered Parquet without embedded dataset rows."""
import os
import tempfile
from pathlib import Path


temporary = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(temporary.name, 'industrial-snapshot.db')}"
os.environ["DATA_SNAPSHOT_ROOT"] = os.path.join(temporary.name, "snapshots")
os.environ["AUTH_MODE"] = "local"
os.environ["APP_ENV"] = "test"

import pyarrow as pa  # noqa: E402
import pyarrow.parquet as pq  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from app import data_plane, models, pipeline_builder_ops, production_auth  # noqa: E402
from app.database import SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402


client = TestClient(app)
passed = 0


def check(response, label, expected=200):
    global passed
    assert response.status_code == expected, f"{label}: {response.status_code} {response.text[:1600]}"
    passed += 1
    return response.json() if response.content else {}


check(client.post("/tenancy/organizations", json={"id": "snapshot-org", "display_name": "Snapshot Org"}), "organization", 201)
for project_id in ("snapshot-plant", "other-plant"):
    check(client.post("/tenancy/projects", json={
        "id": project_id, "organization_id": "snapshot-org", "display_name": project_id,
    }), project_id, 201)

principal = production_auth.Principal(
    "snapshot-admin", "Snapshot Admin", None, ["administrator"], ["*"],
    organization_id="snapshot-org", project_ids=["snapshot-plant", "other-plant"],
)
app.dependency_overrides[production_auth.current_principal] = lambda: principal

check(client.post("/data-assets", json={
    "id": "registered-assets", "project_id": "snapshot-plant", "display_name": "Registered assets",
    "kind": "dataset", "asset_schema": {}, "records": [],
}), "registered dataset")
check(client.post("/data-assets", json={
    "id": "other-assets", "project_id": "other-plant", "display_name": "Other assets",
    "kind": "dataset", "asset_schema": {}, "records": [],
}), "other dataset")

external_dir = os.path.join(temporary.name, "snapshots", "external")
os.makedirs(external_dir, exist_ok=True)
parquet_path = os.path.join(external_dir, "registered-assets.parquet")
pq.write_table(pa.Table.from_pylist([
    {"asset_key": "compressor-7", "asset_name": "Compressor 7", "condition": "DEGRADED", "priority": "high", "failure_probability": 0.94, "lat": 34.0522, "lon": -118.2437},
    {"asset_key": "pump-2", "asset_name": "Pump 2", "condition": "RUNNING", "priority": "low", "failure_probability": 0.12, "lat": 34.0501, "lon": -118.2471},
]), parquet_path)
snapshot = check(client.post("/api/v1/datasets/registered-assets/snapshots/register", json={
    "storage_uri": Path(parquet_path).resolve().as_uri(), "storage_format": "parquet",
    "lineage": {"connector": "test-parquet"},
}), "register parquet", 201)
assert snapshot["row_count"] == 2 and snapshot["storage_format"] == "parquet", snapshot
passed += 1

request = {
    "project_id": "snapshot-plant", "source_asset_id": "registered-assets",
    "source_snapshot_id": snapshot["id"], "display_name": "Snapshot Asset",
    "mapping": {
        "id_field": "asset_key", "name_field": "asset_name", "status_field": "condition",
        "criticality_field": "priority", "risk_field": "failure_probability",
        "latitude_field": "lat", "longitude_field": "lon", "serial_number_field": None,
    },
    "risk_threshold": 0.7,
}
onboarded = check(client.post("/api/v1/industrial/workflows/asset-reliability/onboard", json=request), "snapshot onboarding")
assert onboarded["summary"] == {
    "source_records": 2, "objects_hydrated": 2, "objects_retired": 0, "high_risk_assets": 1,
}, onboarded
resources = onboarded["resources"]
assert resources["source_snapshot"] == snapshot["id"]
assert resources["output_snapshot"] and resources["pipeline_plan"] and resources["ontology_contract_run"]
passed += 2

plan = check(client.get(f"/api/v1/pipeline-plans/{resources['pipeline_plan']}"), "compiled plan")
assert plan["executor"] == "duckdb" and plan["status"] == "VALID", plan
output_rows = check(client.get(f"/api/v1/dataset-snapshots/{resources['output_snapshot']}/rows?limit=10"), "output snapshot rows")
assert output_rows["total"] == 2 and all(row.get("_geometry") and row.get("_mgrs") for row in output_rows["rows"]), output_rows
contract = check(client.get(f"/pipeline-builder/ontology-contracts/{resources['ontology_contract_run']}"), "ontology hydration evidence")
assert contract["accepted_rows"] == 2 and contract["rejected_rows"] == 0, contract
passed += 2

with SessionLocal() as db:
    source_asset = db.get(models.DataAsset, "registered-assets")
    output_asset = db.get(models.DataAsset, resources["output_asset"])
    objects = db.query(models.ObjectInstance).filter(models.ObjectInstance.project_id == "snapshot-plant").all()
    graph = db.get(pipeline_builder_ops.PipelineBuilderGraph, resources["pipeline_graph"])
    output_snapshot = db.get(data_plane.DataAssetSnapshot, resources["output_snapshot"])
    assert source_asset.records == [] and output_asset.records == [], (source_asset.records, output_asset.records)
    assert output_asset.asset_schema["storage_mode"] == "snapshot"
    assert {row.id for row in objects} == {"snapshot_plant:compressor-7", "snapshot_plant:pump-2"}
    assert graph and output_snapshot.lineage["source_snapshot_id"] == snapshot["id"]
    assert all((row.lineage or {}).get("pipeline_builder_graph_id") == graph.id for row in objects)
    passed += 5

mismatch = client.post("/api/v1/industrial/workflows/asset-reliability/onboard", json={
    **request, "project_id": "other-plant", "source_asset_id": "other-assets",
})
assert mismatch.status_code == 409 and "snapshot belongs" in mismatch.text.lower(), mismatch.text
passed += 1

app.dependency_overrides.clear()
print(f"Industrial snapshot-native workflow verified: {passed} assertions passed.")
engine.dispose()
temporary.cleanup()

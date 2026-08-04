"""Industrial materialization retires and later reactivates source-backed objects."""
import os
import tempfile


temporary = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(temporary.name, 'materialization.db')}"
os.environ["DATA_SNAPSHOT_ROOT"] = os.path.join(temporary.name, "snapshots")
os.environ["AUTH_MODE"] = "local"
os.environ["APP_ENV"] = "test"

from fastapi.testclient import TestClient  # noqa: E402
from app import data_plane, decision_intelligence, event_outbox, models, ontology_runtime_v1  # noqa: E402
from app.database import SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402


client = TestClient(app)
passed = 0


def check(response, label, expected=200):
    global passed
    assert response.status_code == expected, f"{label}: {response.status_code} {response.text[:1800]}"
    passed += 1
    return response.json() if response.content else {}


def source_rows(include_chiller: bool):
    rows = [
        {
            "id": "pump-4", "name": "Line 4 Pump", "status": "DEGRADED",
            "criticality": "high", "predicted_failure_probability": 0.93,
            "latitude": 37.7919, "longitude": -122.4017,
        },
        {
            "id": "compressor-1", "name": "Compressor 1", "status": "RUNNING",
            "criticality": "medium", "predicted_failure_probability": 0.21,
            "latitude": 37.7930, "longitude": -122.3990,
        },
    ]
    if include_chiller:
        rows.append({
            "id": "chiller-2", "name": "Chiller 2", "status": "RUNNING",
            "criticality": "medium", "predicted_failure_probability": 0.18,
            "latitude": 37.7898, "longitude": -122.4031,
        })
    return rows


check(client.post("/data-assets", json={
    "id": "lifecycle-assets", "project_id": "default",
    "display_name": "Lifecycle assets", "kind": "dataset",
    "asset_schema": {
        "id": "string", "name": "string", "status": "string", "criticality": "string",
        "predicted_failure_probability": "number", "latitude": "number", "longitude": "number",
    },
    "records": source_rows(True),
}), "source dataset")


def snapshot_for(rows, actor="lifecycle-test"):
    with SessionLocal() as db:
        asset = db.get(models.DataAsset, "lifecycle-assets")
        asset.records = rows
        snapshot = data_plane.ensure_dataset_snapshot(
            db, asset, actor=actor, lineage={"test": "materialization-lifecycle"},
        )
        snapshot_id = snapshot.id
        db.commit()
        return snapshot_id


def onboard(snapshot_id, key):
    queued = check(client.post("/api/v1/industrial/workflows/asset-reliability/onboard", json={
        "project_id": "default", "source_asset_id": "lifecycle-assets",
        "source_snapshot_id": snapshot_id, "display_name": "Lifecycle Asset",
        "mapping": {"serial_number_field": None}, "risk_threshold": 0.7,
        "execution_mode": "background", "idempotency_key": key,
    }), f"queue {key}", 202)
    completed = check(client.post("/pipeline-builder/workers/run-next", json={
        "worker_id": "lifecycle-worker", "job_id": queued["resources"]["execution_job"],
        "lease_seconds": 30,
    }), f"run {key}")
    assert completed["job"]["status"] == "SUCCEEDED", completed
    return completed["result"]


first_snapshot = snapshot_for(source_rows(True))
first = onboard(first_snapshot, "lifecycle-generation-1")
assert first["summary"]["objects_hydrated"] == 3
assert first["summary"]["objects_retired"] == 0
assert first["summary"]["risk_objects_evaluated"] == 3
object_type_id = first["resources"]["object_type"]
passed += 3

second_snapshot = snapshot_for(source_rows(False))
second = onboard(second_snapshot, "lifecycle-generation-2")
assert second["summary"]["objects_hydrated"] == 2
assert second["summary"]["objects_retired"] == 1
assert second["summary"]["risk_objects_evaluated"] == 2
passed += 3

state = check(client.get(
    "/api/v1/industrial/workflows/asset-reliability/workflow-state?project_id=default"
), "retired workflow state")
assert state["summary"]["object_count"] == 2
assert state["summary"]["retired_object_count"] == 1
assert state["summary"]["risk_objects_evaluated"] == 2
passed += 3

active_query = check(client.post("/api/v1/objects/query", json={
    "project_id": "default", "object_type_id": object_type_id,
    "include_total": True, "limit": 20,
}), "active object query")
assert active_query["total"] == 2
assert all(row["is_active"] for row in active_query["objects"])
passed += 2

all_query = check(client.post("/api/v1/objects/query", json={
    "project_id": "default", "object_type_id": object_type_id,
    "include_inactive": True, "include_total": True, "limit": 20,
}), "all object query")
assert all_query["total"] == 3
retired = next(row for row in all_query["objects"] if not row["is_active"])
assert retired["id"].endswith(":chiller-2")
assert retired["retired_at"] and retired["materialization_id"] == first["resources"]["output_snapshot"]
passed += 3

history = check(client.get(
    f"/api/v1/objects/{object_type_id}/{retired['id']}/history"
), "retired object history")
assert history["events"][0]["event_type"] == "ontology.object.retired", history
passed += 1

with SessionLocal() as db:
    retired_row = db.get(models.ObjectInstance, retired["id"])
    assert retired_row and not retired_row.is_active and retired_row.retired_at
    assert retired_row.properties["name"] == "Chiller 2"
    snapshots = db.query(decision_intelligence.ObjectSnapshot).filter(
        decision_intelligence.ObjectSnapshot.object_id == retired["id"],
    ).all()
    changes = db.query(ontology_runtime_v1.ObjectChangeEvent).filter(
        ontology_runtime_v1.ObjectChangeEvent.object_id == retired["id"],
    ).all()
    retired_delivery = db.query(event_outbox.EventOutbox).filter(
        event_outbox.EventOutbox.topic == "ontologyos.object_change",
        event_outbox.EventOutbox.aggregate_id == retired["id"],
        event_outbox.EventOutbox.event_type == "ontology.object.retired",
    ).one()
    assert any(row.event_type == "ontology.object.retired" for row in snapshots)
    assert any(row.event_type == "ontology.object.retired" for row in changes)
    assert retired_delivery.payload["materialization"] == {
        "id": first["resources"]["output_snapshot"],
        "active": False,
        "retired_at": retired["retired_at"],
    }
    assert retired_delivery.payload["evidence"]["materialization_id"] == second["resources"]["output_snapshot"]
    passed += 7

third_snapshot = snapshot_for(source_rows(True))
third = onboard(third_snapshot, "lifecycle-generation-3")
assert third["summary"]["objects_hydrated"] == 3
assert third["summary"]["objects_retired"] == 0
assert third["summary"]["risk_objects_evaluated"] == 3
passed += 3

restored_query = check(client.post("/api/v1/objects/query", json={
    "project_id": "default", "object_type_id": object_type_id,
    "include_total": True, "limit": 20,
}), "reactivated object query")
assert restored_query["total"] == 3
reactivated = next(row for row in restored_query["objects"] if row["id"] == retired["id"])
assert reactivated["is_active"] and reactivated["retired_at"] is None
assert reactivated["materialization_id"] == third["resources"]["output_snapshot"]
passed += 3

reactivated_history = check(client.get(
    f"/api/v1/objects/{object_type_id}/{retired['id']}/history"
), "reactivated object history")
event_types = [row["event_type"] for row in reactivated_history["events"]]
assert "ontology.object.retired" in event_types
assert "pipeline_builder.object.reactivated" in event_types
assert event_types.index("pipeline_builder.object.reactivated") < event_types.index("ontology.object.retired")
passed += 3

with SessionLocal() as db:
    reactivated_delivery = db.query(event_outbox.EventOutbox).filter(
        event_outbox.EventOutbox.topic == "ontologyos.object_change",
        event_outbox.EventOutbox.aggregate_id == retired["id"],
        event_outbox.EventOutbox.event_type == "pipeline_builder.object.reactivated",
    ).one()
    assert reactivated_delivery.payload["materialization"] == {
        "id": third["resources"]["output_snapshot"], "active": True, "retired_at": None,
    }
    assert reactivated_delivery.payload["object_version"] == 3
    passed += 2

print(f"Industrial materialization lifecycle verified: {passed} assertions passed.")
engine.dispose()
temporary.cleanup()

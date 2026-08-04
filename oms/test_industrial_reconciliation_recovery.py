"""A worker can resume a partitioned materialization retirement scan."""
import os
import tempfile


temporary = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(temporary.name, 'reconciliation-recovery.db')}"
os.environ["DATA_SNAPSHOT_ROOT"] = os.path.join(temporary.name, "snapshots")
os.environ["AUTH_MODE"] = "local"
os.environ["APP_ENV"] = "test"

from fastapi.testclient import TestClient  # noqa: E402
from app import data_plane, models, platform_runtime  # noqa: E402
from app.database import SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402


client = TestClient(app)
passed = 0


def check(response, label, expected=200):
    global passed
    assert response.status_code == expected, f"{label}: {response.status_code} {response.text[:1800]}"
    passed += 1
    return response.json() if response.content else {}


def records(count):
    return [
        {
            "id": f"asset-{index:04d}", "name": f"Asset {index:04d}", "status": "RUNNING",
            "criticality": "medium", "predicted_failure_probability": 0.2,
            "latitude": 37.7 + index / 100000, "longitude": -122.4 - index / 100000,
        }
        for index in range(count)
    ]


check(client.post("/data-assets", json={
    "id": "reconciliation-assets", "project_id": "default",
    "display_name": "Reconciliation assets", "kind": "dataset",
    "asset_schema": {
        "id": "string", "name": "string", "status": "string", "criticality": "string",
        "predicted_failure_probability": "number", "latitude": "number", "longitude": "number",
    },
    "records": records(1002),
}), "source dataset")


def create_snapshot(rows):
    with SessionLocal() as db:
        asset = db.get(models.DataAsset, "reconciliation-assets")
        asset.records = rows
        snapshot = data_plane.ensure_dataset_snapshot(db, asset, actor="reconciliation-test")
        snapshot_id = snapshot.id
        db.commit()
        return snapshot_id


def queue(snapshot_id, key):
    return check(client.post("/api/v1/industrial/workflows/asset-reliability/onboard", json={
        "project_id": "default", "source_asset_id": "reconciliation-assets",
        "source_snapshot_id": snapshot_id, "display_name": "Reconciliation Asset",
        "mapping": {"serial_number_field": None}, "execution_mode": "background",
        "idempotency_key": key,
    }), f"queue {key}", 202)


initial = queue(create_snapshot(records(1002)), "reconciliation-generation-1")
initial_run = check(client.post("/pipeline-builder/workers/run-next", json={
    "worker_id": "reconciliation-worker", "job_id": initial["resources"]["execution_job"],
    "lease_seconds": 30,
}), "initial generation")
assert initial_run["job"]["status"] == "SUCCEEDED"
assert initial_run["result"]["summary"]["objects_hydrated"] == 1002
passed += 2

replacement = queue(create_snapshot(records(1)), "reconciliation-generation-2")
job_id = replacement["resources"]["execution_job"]
original_heartbeat = platform_runtime.heartbeat_job
interrupted = {"value": False}


def interrupt_reconciliation(*args, **kwargs):
    body = args[1] if len(args) > 1 else kwargs.get("body")
    if (
        body is not None
        and str(body.message).startswith("Retired")
        and int((body.metrics or {}).get("retired_objects") or 0) >= 1000
        and not interrupted["value"]
    ):
        interrupted["value"] = True
        original_heartbeat(*args, **kwargs)
        raise RuntimeError("simulated worker loss after retirement checkpoint")
    return original_heartbeat(*args, **kwargs)


platform_runtime.heartbeat_job = interrupt_reconciliation
failed = check(client.post("/pipeline-builder/workers/run-next", json={
    "worker_id": "reconciliation-worker", "job_id": job_id, "lease_seconds": 30,
}), "interrupted reconciliation")
platform_runtime.heartbeat_job = original_heartbeat
assert failed["job"]["status"] == "QUEUED" and failed["job"]["attempt"] == 2, failed
checkpointed = check(client.get(f"/jobs/{job_id}"), "retirement checkpoint")
checkpoint = checkpointed["payload"]["industrial_reconcile_checkpoint"]
assert checkpoint["retired_objects"] == 1000 and checkpoint["cursor"], checkpoint
passed += 2

resumed = check(client.post("/pipeline-builder/workers/run-next", json={
    "worker_id": "reconciliation-worker", "job_id": job_id, "lease_seconds": 30,
}), "resumed reconciliation")
assert resumed["job"]["status"] == "SUCCEEDED", resumed
assert resumed["result"]["summary"]["objects_retired"] == 1001
assert resumed["result"]["summary"]["risk_objects_evaluated"] == 1
passed += 3

with SessionLocal() as db:
    object_type_id = resumed["result"]["resources"]["object_type"]
    query = db.query(models.ObjectInstance).filter(
        models.ObjectInstance.project_id == "default",
        models.ObjectInstance.object_type_id == object_type_id,
    )
    assert query.filter(models.ObjectInstance.is_active.is_(True)).count() == 1
    assert query.filter(models.ObjectInstance.is_active.is_(False)).count() == 1001
    assert all(row.retired_at for row in query.filter(models.ObjectInstance.is_active.is_(False)).all())
    passed += 3

print(f"Industrial reconciliation recovery verified: {passed} assertions passed.")
engine.dispose()
temporary.cleanup()

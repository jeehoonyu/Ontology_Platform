"""Pipeline preview and delivery through durable worker jobs."""
import os
import tempfile

tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tmpdir.name, 'pipeline_async.db')}"
os.environ["AUTH_MODE"] = "local"
os.environ["APP_ENV"] = "test"

from fastapi.testclient import TestClient  # noqa: E402
from app.database import SessionLocal  # noqa: E402
from app.datasets_ext import DatasetTransaction  # noqa: E402
from app.main import app  # noqa: E402

client = TestClient(app)
passed = 0


def ok(response, label, expect=200):
    global passed
    assert response.status_code == expect, f"{label}: {response.status_code} {response.text[:1000]}"
    passed += 1
    return response.json() if response.content else {}


ok(client.post("/data-assets", json={
    "id": "async_assets",
    "display_name": "Async Assets",
    "kind": "dataset",
    "asset_schema": {},
    "records": [
        {"id": "asset-1", "risk": 92, "status": "DEGRADED"},
        {"id": "asset-2", "risk": 41, "status": "RUNNING"},
    ],
}), "create source dataset")

graph = ok(client.post("/pipeline-builder/graphs", json={
    "id": "async_asset_pipeline",
    "display_name": "Async asset pipeline",
    "nodes": [
        {"id": "input", "type": "input_dataset", "config": {"asset_id": "async_assets"}},
        {"id": "filter", "type": "filter", "config": {"field": "risk", "operator": "gte", "value": 80}},
        {"id": "output", "type": "dataset_output", "config": {"asset_id": "async_asset_output"}},
    ],
    "edges": [{"source": "input", "target": "filter"}, {"source": "filter", "target": "output"}],
}), "create pipeline graph", 201)

preview = ok(client.post(f"/pipeline-builder/graphs/{graph['id']}/preview/async", json={
    "limit": 20,
    "priority": 60,
    "idempotency_key": "async-preview-v1",
}), "enqueue preview", 202)
preview_replay = ok(client.post(f"/pipeline-builder/graphs/{graph['id']}/preview/async", json={
    "limit": 20,
    "priority": 60,
    "idempotency_key": "async-preview-v1",
}), "replay preview enqueue", 202)
assert preview_replay["id"] == preview["id"], (preview, preview_replay)

preview_run = ok(client.post("/pipeline-builder/workers/run-next", json={"worker_id": "pipeline-worker-test"}), "execute preview job")
assert preview_run["job"]["id"] == preview["id"] and preview_run["job"]["status"] == "SUCCEEDED", preview_run
assert preview_run["result"]["row_count"] == 1 and preview_run["result"]["rows"][0]["id"] == "asset-1", preview_run
preview_detail = ok(client.get(f"/jobs/{preview['id']}"), "preview job evidence")
assert [event["event_type"] for event in preview_detail["events"]] == ["job.queued", "job.claimed", "job.progress", "job.succeeded"], preview_detail

delivery = ok(client.post(f"/pipeline-builder/graphs/{graph['id']}/deliver/async", json={
    "output_asset_id": "async_asset_output",
    "primary_key": "id",
    "priority": 80,
    "idempotency_key": "async-delivery-v1",
}), "enqueue delivery", 202)
delivery_run = ok(client.post("/pipeline-builder/workers/run-next", json={"worker_id": "pipeline-worker-test"}), "execute delivery job")
assert delivery_run["job"]["status"] == "SUCCEEDED" and delivery_run["result"]["records_out"] == 1, delivery_run
output = ok(client.get("/data-assets/async_asset_output"), "inspect delivered dataset")
assert output["records"] == [{"id": "asset-1", "risk": 92, "status": "DEGRADED"}], output

with SessionLocal() as db:
    transaction_count = db.query(DatasetTransaction).filter(DatasetTransaction.dataset_id == "async_asset_output").count()
idempotent_delivery = ok(client.post(f"/pipeline-builder/graphs/{graph['id']}/deliver", json={
    "output_asset_id": "async_asset_output",
    "primary_key": "id",
    "execution_job_id": delivery["id"],
}), "replay delivery execution")
assert idempotent_delivery["idempotent_replay"] is True, idempotent_delivery
with SessionLocal() as db:
    assert db.query(DatasetTransaction).filter(DatasetTransaction.dataset_id == "async_asset_output").count() == transaction_count
passed += 1

cancelled_job = ok(client.post(f"/pipeline-builder/graphs/{graph['id']}/preview/async", json={
    "idempotency_key": "cancelled-preview-v1",
}), "enqueue cancellable preview", 202)
cancelled = ok(client.post(f"/jobs/{cancelled_job['id']}/cancel"), "cancel queued preview")
assert cancelled["status"] == "CANCELLED", cancelled
empty = ok(client.post("/pipeline-builder/workers/run-next", json={"worker_id": "pipeline-worker-test"}), "skip cancelled work")
assert empty["job"] is None, empty
retried = ok(client.post(f"/jobs/{cancelled_job['id']}/retry"), "retry cancelled preview")
assert retried["status"] == "QUEUED" and retried["attempt"] == 2, retried
retry_run = ok(client.post("/pipeline-builder/workers/run-next", json={"worker_id": "pipeline-worker-test"}), "execute retried preview")
assert retry_run["job"]["status"] == "SUCCEEDED", retry_run

commit_guard_job = ok(client.post(f"/pipeline-builder/graphs/{graph['id']}/deliver/async", json={
    "output_asset_id": "async_asset_output",
    "idempotency_key": "cancelled-delivery-v1",
}), "enqueue guarded delivery", 202)
commit_guard_claim = ok(client.post("/jobs/claim", json={
    "worker_id": "pipeline-worker-guard-test",
    "supported_job_types": ["pipeline.deliver"],
    "job_id": commit_guard_job["id"],
}), "claim guarded delivery")["job"]
ok(client.post(f"/jobs/{commit_guard_job['id']}/cancel"), "cancel delivery before commit")
guarded_delivery = client.post(f"/pipeline-builder/graphs/{graph['id']}/deliver", json={
    "output_asset_id": "async_asset_output",
    "execution_job_id": commit_guard_job["id"],
    "execution_lease_token": commit_guard_claim["lease_token"],
})
assert guarded_delivery.status_code == 409, guarded_delivery.text
with SessionLocal() as db:
    assert db.query(DatasetTransaction).filter(DatasetTransaction.dataset_id == "async_asset_output").count() == transaction_count
passed += 1

bad_graph = ok(client.post("/pipeline-builder/graphs", json={
    "id": "async_bad_pipeline",
    "display_name": "Invalid async pipeline",
    "nodes": [{"id": "input", "type": "input_dataset", "config": {"asset_id": "missing_asset"}}],
    "edges": [],
}), "create invalid pipeline graph", 201)
bad_job = ok(client.post(f"/pipeline-builder/graphs/{bad_graph['id']}/preview/async", json={
    "idempotency_key": "bad-preview-v1",
}), "enqueue invalid preview", 202)
bad_run = ok(client.post("/pipeline-builder/workers/run-next", json={"worker_id": "pipeline-worker-test"}), "fail invalid preview")
assert bad_run["job"]["id"] == bad_job["id"] and bad_run["job"]["status"] == "FAILED", bad_run
assert bad_run["job"]["attempt"] == 1, bad_run

events = client.get(f"/events/stream?job_id={delivery['id']}&once=true")
assert events.status_code == 200 and "event: job.succeeded" in events.text, events.text
passed += 1

print(f"\nAsynchronous Pipeline execution verified: {passed} assertions passed.")
from app.database import engine as _engine  # noqa: E402
_engine.dispose()
tmpdir.cleanup()

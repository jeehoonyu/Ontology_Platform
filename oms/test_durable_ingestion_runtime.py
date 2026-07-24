"""Durable connector/stream ingestion, budgets, recovery, and project isolation."""
import os
import tempfile

tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tmpdir.name, 'ingestion.db')}"
os.environ["AUTH_MODE"] = "local"
os.environ["APP_ENV"] = "test"

from fastapi.testclient import TestClient  # noqa: E402
from app.database import SessionLocal  # noqa: E402
from app.main import app  # noqa: E402
from app import ingestion_runtime, models, production_auth, tenancy  # noqa: E402

client = TestClient(app)
passed = 0


def ok(response, label, expect=200):
    global passed
    assert response.status_code == expect, f"{label}: {response.status_code} {response.text[:1600]}"
    passed += 1
    return response.json() if response.content else {}


for organization in ({"id": "acme", "display_name": "Acme"}, {"id": "other", "display_name": "Other"}):
    ok(client.post("/tenancy/organizations", json=organization), "create organization", 201)
for project in (
    {"id": "operations", "organization_id": "acme", "display_name": "Operations"},
    {"id": "restricted", "organization_id": "other", "display_name": "Restricted"},
):
    ok(client.post("/tenancy/projects", json=project), "create project", 201)

with SessionLocal() as db:
    db.add_all([
        tenancy.ProjectMembership(id="member_alice", project_id="operations", principal_id="alice", role="administrator", permissions=[], created_at=1, updated_at=1),
        tenancy.ProjectMembership(id="member_carol", project_id="restricted", principal_id="carol", role="operator", permissions=[], created_at=1, updated_at=1),
        models.DataAsset(id="ingestion_target", display_name="Ingestion Target", description=None, kind="dataset", asset_schema={"project_id": "operations"}, records=[], file_ref=None, source_format=None, created_at=1, updated_at=1),
        models.DataAsset(id="stream_archive", display_name="Stream Archive", description=None, kind="dataset", asset_schema={"project_id": "operations"}, records=[], file_ref=None, source_format=None, created_at=1, updated_at=1),
    ])
    db.commit()

active_principal = production_auth.Principal("alice", "Alice", "alice@example.test", ["administrator"], ["view", "edit", "execute", "administer"], organization_id="acme", project_ids=[])
app.dependency_overrides[production_auth.current_principal] = lambda: active_principal

catalog = ok(client.get("/ingestion/connectors/catalog"), "connector catalog")
assert {row["id"] for row in catalog["adapters"]} >= {"rest", "jdbc", "s3", "sftp", "kafka"}

source = ok(client.post("/connections/sources", json={
    "id": "maintenance_rest", "project_id": "operations", "display_name": "Maintenance REST", "source_type": "rest",
    "config": {"base_url": "http://fixture", "endpoint": "/assets"},
}), "create project source")
assert source["project_id"] == "operations"
sync = ok(client.post("/connections/sources/maintenance_rest/syncs", json={
    "id": "maintenance_sync", "target_asset_id": "ingestion_target", "sample_records": [{"asset_id": "A-1"}, {"asset_id": "A-2"}],
}), "create project sync")
assert sync["project_id"] == "operations"

queued = ok(client.post("/ingestion/syncs/maintenance_sync/enqueue", json={"idempotency_key": "sync-once"}), "enqueue sync", 202)
assert queued["job"]["project_id"] == "operations" and queued["job"]["status"] == "QUEUED"
repeated = ok(client.post("/ingestion/syncs/maintenance_sync/enqueue", json={"idempotency_key": "sync-once"}), "idempotent enqueue", 202)
assert repeated["idempotent_replay"] is True and repeated["run"]["id"] == queued["run"]["id"]
executed = ok(client.post("/ingestion/workers/run-next", json={"job_id": queued["job"]["id"], "worker_id": "worker-a"}), "execute sync")
assert executed["job"]["status"] == "SUCCEEDED" and executed["run"]["records_out"] == 2

warning = ok(client.post("/ingestion/syncs/maintenance_sync/enqueue", json={
    "idempotency_key": "sync-invalid", "records": [{"asset_id": "A-3"}, {"asset_id": "bad", "__ingestion_error": "invalid asset"}],
}), "enqueue invalid record", 202)
warning_result = ok(client.post("/ingestion/workers/run-next", json={"job_id": warning["job"]["id"]}), "process with dead letter")
assert warning_result["run"]["status"] == "WARN" and warning_result["run"]["metrics"]["rejected"] == 1
dead_letters = ok(client.get("/ingestion/dead-letters?project_id=operations"), "list dead letters")
assert len(dead_letters) == 1 and dead_letters[0]["payload"]["asset_id"] == "bad"

stream = ok(client.post("/streams", json={
    "id": "sensor_stream", "project_id": "operations", "display_name": "Sensor Stream", "schema": {"asset_id": "string"},
}), "create project stream")
assert stream["project_id"] == "operations"
stream_job = ok(client.post("/ingestion/streams/sensor_stream/replay/enqueue", json={
    "records": [{"asset_id": "A-1", "temperature": 72}, {"asset_id": "A-2", "temperature": 75}],
    "archive_to_dataset": True, "target_asset_id": "stream_archive", "idempotency_key": "stream-once",
}), "enqueue stream replay", 202)
stream_result = ok(client.post("/ingestion/workers/run-next", json={"job_id": stream_job["job"]["id"]}), "execute stream replay")
assert stream_result["run"]["records_out"] == 2

retry_job = ok(client.post("/ingestion/streams/sensor_stream/replay/enqueue", json={
    "records": [{"asset_id": "A-4", "temperature": 80}], "idempotency_key": "retry-stream", "max_attempts": 2,
}), "enqueue retryable replay", 202)
failed_once = ok(client.post("/ingestion/workers/run-next", json={"job_id": retry_job["job"]["id"], "inject_failure": True}), "inject worker failure")
assert failed_once["job"]["status"] == "QUEUED" and failed_once["run"]["status"] == "RETRYING"
recovered = ok(client.post("/ingestion/workers/run-next", json={"job_id": retry_job["job"]["id"]}), "recover retried replay")
assert recovered["job"]["status"] == "SUCCEEDED"

budget = ok(client.put("/ingestion/budgets", json={
    "project_id": "operations", "metric": "records", "limit_value": 6, "window_seconds": 86400, "enforcement": "HARD",
}), "set hard budget")
assert budget["limit_value"] == 6
over_budget = ok(client.post("/ingestion/syncs/maintenance_sync/enqueue", json={
    "idempotency_key": "over-budget", "records": [{"asset_id": "A-10"}, {"asset_id": "A-11"}], "max_attempts": 1,
}), "enqueue over-budget sync", 202)
over_result = ok(client.post("/ingestion/workers/run-next", json={"job_id": over_budget["job"]["id"]}), "enforce hard budget")
assert over_result["job"]["status"] == "FAILED" and over_result["run"]["status"] == "FAILED"

summary = ok(client.get("/ingestion/summary?project_id=operations"), "ingestion summary")
assert summary["records_processed"] == 6 and summary["pending_dead_letters"] >= 2 and summary["estimated_cost_usd"] > 0
snapshot = ok(client.get("/project/export"), "snapshot ingestion evidence")
assert snapshot["ingestion_runs"] and snapshot["ingestion_budgets"] and snapshot["ingestion_dead_letters"]
assert all(row["project_id"] == "operations" for row in snapshot["ingestion_runs"])

with SessionLocal() as db:
    assert len(db.get(models.DataAsset, "ingestion_target").records) == 3
    assert len(db.get(models.DataAsset, "stream_archive").records) == 2
    db.query(ingestion_runtime.IngestionDeadLetter).delete()
    db.query(ingestion_runtime.IngestionBudget).delete()
    db.query(ingestion_runtime.IngestionRun).delete()
    db.commit()

restored = ok(client.post("/project/import", json={"snapshot": snapshot, "mode": "merge", "actor": "recovery-test"}), "restore ingestion evidence")
assert restored["status"] == "IMPORTED"
restored_summary = ok(client.get("/ingestion/summary?project_id=operations"), "verify restored ingestion summary")
assert restored_summary["runs"] == len(snapshot["ingestion_runs"])

active_principal = production_auth.Principal("carol", "Carol", "carol@example.test", ["operator"], ["view", "edit", "execute"], organization_id="other", project_ids=[])
assert ok(client.get("/connections/sources"), "cross-project sources filtered") == []
assert ok(client.get("/streams"), "cross-project streams filtered") == []
ok(client.get("/ingestion/summary?project_id=operations"), "cross-project ingestion summary denied", 403)
ok(client.get(f"/jobs/{queued['job']['id']}"), "cross-project job denied", 403)
ok(client.post("/ingestion/syncs/maintenance_sync/enqueue", json={}), "cross-project enqueue denied", 403)

app.dependency_overrides.clear()
print(f"Durable ingestion runtime verified: {passed} assertions passed.")

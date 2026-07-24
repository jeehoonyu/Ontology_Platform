"""Durable worker claims, progress, retries, and stale-job recovery."""
import os
import tempfile
import time

tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tmpdir.name, 'async_jobs.db')}"
os.environ["AUTH_MODE"] = "local"
os.environ["APP_ENV"] = "test"

from fastapi.testclient import TestClient  # noqa: E402
from app.database import SessionLocal  # noqa: E402
from app.main import app  # noqa: E402
from app.platform_runtime import PlatformJobLease  # noqa: E402

client = TestClient(app)
passed = 0


def ok(response, label, expect=200):
    global passed
    assert response.status_code == expect, f"{label}: {response.status_code} {response.text[:800]}"
    passed += 1
    return response.json() if response.content else {}


low = ok(client.post("/jobs", json={
    "job_type": "pipeline.preview",
    "payload": {"graph_id": "low"},
    "priority": 10,
    "max_attempts": 2,
}), "create low-priority job", 201)
high = ok(client.post("/jobs", json={
    "job_type": "pipeline.preview",
    "payload": {"graph_id": "high"},
    "priority": 90,
    "max_attempts": 2,
}), "create high-priority job", 201)

claim = ok(client.post("/jobs/claim", json={
    "worker_id": "pipeline-worker-1",
    "supported_job_types": ["pipeline.preview"],
    "lease_seconds": 30,
}), "claim highest-priority job")
assert claim["job"]["id"] == high["id"] and claim["job"]["status"] == "RUNNING", claim
token = claim["job"]["lease_token"]

ok(client.post(f"/jobs/{high['id']}/heartbeat", json={
    "lease_token": "not-the-owner",
    "progress": 10,
}), "reject invalid lease", 409)
heartbeat = ok(client.post(f"/jobs/{high['id']}/heartbeat", json={
    "lease_token": token,
    "progress": 45,
    "message": "Sampling transformed rows",
    "metrics": {"rows_scanned": 240},
}), "record worker heartbeat")
assert heartbeat["progress"] == 45 and heartbeat["lease"]["worker_id"] == "pipeline-worker-1", heartbeat

completed = ok(client.post(f"/jobs/{high['id']}/complete", json={
    "lease_token": token,
    "result": {"rows": 25, "schema_fields": 8},
}), "complete claimed job")
assert completed["status"] == "SUCCEEDED" and completed["progress"] == 100 and completed["lease"] is None, completed

low_claim = ok(client.post("/jobs/claim", json={"worker_id": "pipeline-worker-2"}), "claim remaining job")["job"]
assert low_claim["id"] == low["id"], low_claim
retried = ok(client.post(f"/jobs/{low['id']}/fail", json={
    "lease_token": low_claim["lease_token"],
    "error": "Temporary connector outage",
    "retriable": True,
}), "schedule retry")
assert retried["status"] == "QUEUED" and retried["attempt"] == 2, retried

retry_claim = ok(client.post("/jobs/claim", json={"worker_id": "pipeline-worker-3"}), "claim retry")["job"]
failed = ok(client.post(f"/jobs/{low['id']}/fail", json={
    "lease_token": retry_claim["lease_token"],
    "error": "Connector remained unavailable",
    "retriable": True,
}), "exhaust retry budget")
assert failed["status"] == "FAILED" and failed["completed_at"], failed

first_idempotent = ok(client.post("/jobs", json={
    "job_type": "report.generate",
    "idempotency_key": "incident-42-report-v1",
}), "create idempotent job", 201)
second_idempotent = ok(client.post("/jobs", json={
    "job_type": "report.generate",
    "idempotency_key": "incident-42-report-v1",
}), "reuse idempotent job", 201)
assert first_idempotent["id"] == second_idempotent["id"], (first_idempotent, second_idempotent)

stale = ok(client.post("/jobs", json={
    "job_type": "model.monitor",
    "max_attempts": 3,
}), "create stale-worker job", 201)
stale_claim = ok(client.post("/jobs/claim", json={
    "worker_id": "model-worker-1",
    "supported_job_types": ["model.monitor"],
}), "claim stale-worker job")["job"]
with SessionLocal() as db:
    lease = db.query(PlatformJobLease).filter(PlatformJobLease.job_id == stale["id"]).one()
    lease.expires_at = int(time.time()) - 1
    db.commit()

summary = ok(client.get("/jobs/summary"), "reap stale worker")
assert summary["reaped_stale_jobs"] == 1 and summary["active_leases"] == 0, summary
recovered = ok(client.get(f"/jobs/{stale['id']}"), "inspect recovered job")
assert recovered["status"] == "QUEUED" and recovered["attempt"] == 2, recovered
assert any(event["event_type"] == "job.requeued" for event in recovered["events"]), recovered

listed = ok(client.get("/jobs?status=SUCCEEDED&job_type=pipeline.preview"), "filter job list")
assert [row["id"] for row in listed] == [high["id"]], listed

empty = ok(client.post("/jobs/claim", json={
    "worker_id": "unsupported-worker",
    "supported_job_types": ["unknown.type"],
}), "return empty compatible queue")
assert empty["job"] is None, empty

print(f"\nAsynchronous job runtime verified: {passed} assertions passed.")
from app.database import engine as _engine  # noqa: E402
_engine.dispose()
tmpdir.cleanup()

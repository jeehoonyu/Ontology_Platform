"""Distributed worker claims, fair queues, draining, and lease-loss recovery."""
import os
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor

tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tmpdir.name, 'worker_fleet.db')}"
os.environ["AUTH_MODE"] = "local"
os.environ["APP_ENV"] = "test"

from fastapi.testclient import TestClient  # noqa: E402
from app.database import SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.models_action import AuditLog  # noqa: E402
from app.platform_runtime import PlatformJobLease  # noqa: E402
from app.worker_control import RuntimeQueuePolicy, RuntimeWorker  # noqa: E402

client = TestClient(app)
passed = 0


def ok(response, label, expect=200):
    global passed
    assert response.status_code == expect, f"{label}: {response.status_code} {response.text[:1000]}"
    passed += 1
    return response.json() if response.content else {}


ok(client.post("/tenancy/bootstrap", json={"project_id": "alpha", "project_name": "Alpha"}), "bootstrap alpha")
ok(client.post("/tenancy/projects", json={"id": "beta", "organization_id": "local", "display_name": "Beta"}), "create beta", 201)
ok(client.post("/tenancy/projects", json={"id": "concurrent", "organization_id": "local", "display_name": "Concurrent"}), "create concurrent", 201)

ok(client.put("/runtime/queues/alpha", json={"weight": 1, "max_concurrency": 20}), "configure alpha queue")
ok(client.put("/runtime/queues/beta", json={"weight": 1, "max_concurrency": 20}), "configure beta queue")
ok(client.put("/runtime/workers/fair-worker", json={
    "supported_job_types": ["pipeline.preview"], "max_concurrency": 1, "labels": {"pool": "general"},
}), "register fair worker")

alpha_high = ok(client.post("/jobs", json={"project_id": "alpha", "job_type": "pipeline.preview", "priority": 95}), "queue alpha high", 201)
ok(client.post("/jobs", json={"project_id": "alpha", "job_type": "pipeline.preview", "priority": 80}), "queue alpha second", 201)
beta_low = ok(client.post("/jobs", json={"project_id": "beta", "job_type": "pipeline.preview", "priority": 5}), "queue beta low", 201)

first = ok(client.post("/jobs/claim", json={"worker_id": "fair-worker"}), "claim first fair job")["job"]
assert first["id"] == alpha_high["id"], first
ok(client.post(f"/jobs/{first['id']}/complete", json={"lease_token": first["lease_token"]}), "complete first fair job")
second = ok(client.post("/jobs/claim", json={"worker_id": "fair-worker"}), "claim second fair job")["job"]
assert second["id"] == beta_low["id"], second
ok(client.post(f"/jobs/{second['id']}/complete", json={"lease_token": second["lease_token"]}), "complete second fair job")

ok(client.put("/runtime/workers/capacity-worker", json={
    "project_id": "alpha", "supported_job_types": ["capacity.test"], "max_concurrency": 1,
}), "register capacity worker")
ok(client.put("/runtime/queues/alpha", json={"weight": 1, "max_concurrency": 1}), "limit alpha concurrency")
for index in range(2):
    ok(client.post("/jobs", json={"project_id": "alpha", "job_type": "capacity.test", "payload": {"index": index}}), f"queue capacity {index}", 201)
capacity_claim = ok(client.post("/jobs/claim", json={"worker_id": "capacity-worker"}), "fill worker capacity")["job"]
at_capacity = ok(client.post("/jobs/claim", json={"worker_id": "capacity-worker"}), "enforce worker capacity")
assert at_capacity == {"job": None, "reason": "WORKER_CAPACITY"}, at_capacity
project_capacity = ok(client.post("/jobs/claim", json={
    "worker_id": "other-capacity-worker", "project_id": "alpha", "supported_job_types": ["capacity.test"],
}), "enforce project capacity")
assert project_capacity == {"job": None, "reason": "NO_COMPATIBLE_WORK"}, project_capacity
draining = ok(client.post("/runtime/workers/capacity-worker/drain"), "drain worker")
assert draining["status"] == "DRAINING" and draining["active_jobs"] == 1, draining
ok(client.post("/jobs/claim", json={"worker_id": "capacity-worker"}), "draining worker rejects claims", 409)
ok(client.post(f"/jobs/{capacity_claim['id']}/complete", json={"lease_token": capacity_claim["lease_token"]}), "complete draining worker job")
ok(client.post("/runtime/workers/capacity-worker/resume"), "resume worker")
resumed_claim = ok(client.post("/jobs/claim", json={"worker_id": "capacity-worker"}), "claim after resume")["job"]
ok(client.post(f"/jobs/{resumed_claim['id']}/complete", json={"lease_token": resumed_claim["lease_token"]}), "complete resumed job")
ok(client.put("/runtime/queues/alpha", json={"weight": 1, "max_concurrency": 20}), "restore alpha concurrency")
ok(client.post("/jobs/claim", json={"worker_id": "capacity-worker", "supported_job_types": ["agent.invoke"]}), "reject capability escalation", 403)

ok(client.put("/runtime/queues/beta", json={"weight": 1, "max_concurrency": 20, "paused": True}), "pause beta queue")
paused_job = ok(client.post("/jobs", json={"project_id": "beta", "job_type": "pause.test"}), "queue paused work", 201)
paused_claim = ok(client.post("/jobs/claim", json={"worker_id": "pause-worker", "project_id": "beta"}), "skip paused queue")
assert paused_claim["job"] is None, paused_claim
ok(client.put("/runtime/queues/beta", json={"weight": 1, "max_concurrency": 20, "paused": False}), "resume beta queue")
unpaused = ok(client.post("/jobs/claim", json={"worker_id": "pause-worker", "project_id": "beta"}), "claim resumed queue")["job"]
assert unpaused["id"] == paused_job["id"], unpaused
ok(client.post(f"/jobs/{unpaused['id']}/complete", json={"lease_token": unpaused["lease_token"]}), "complete resumed queue job")

ok(client.put("/runtime/queues/concurrent", json={"weight": 1, "max_concurrency": 30}), "configure concurrent queue")
chaos_jobs = [
    ok(client.post("/jobs", json={"project_id": "concurrent", "job_type": "chaos.test", "payload": {"index": index}}), f"queue chaos {index}", 201)
    for index in range(12)
]


def concurrent_claim(index):
    return client.post("/jobs/claim", json={
        "worker_id": f"chaos-worker-{index}", "project_id": "concurrent", "supported_job_types": ["chaos.test"],
    })


with ThreadPoolExecutor(max_workers=12) as pool:
    responses = list(pool.map(concurrent_claim, range(12)))
assert all(response.status_code == 200 for response in responses), [(response.status_code, response.text[:200]) for response in responses]
claims = [response.json()["job"] for response in responses]
assert all(claims) and len({row["id"] for row in claims}) == 12, claims
assert {row["id"] for row in claims} == {row["id"] for row in chaos_jobs}, claims
passed += 3

lost = claims[0]
with SessionLocal() as db:
    lease = db.query(PlatformJobLease).filter(PlatformJobLease.job_id == lost["id"]).one()
    lease.expires_at = int(time.time()) - 1
    db.commit()
reaped = ok(client.get("/jobs/summary"), "reap expired chaos lease")
assert reaped["reaped_stale_jobs"] == 1, reaped
ok(client.post(f"/jobs/{lost['id']}/complete", json={"lease_token": lost["lease_token"]}), "fence stale worker completion", 409)
replacement = ok(client.post("/jobs/claim", json={
    "worker_id": "replacement-worker", "project_id": "concurrent", "job_id": lost["id"],
}), "reclaim expired job")["job"]
assert replacement["attempt"] == 2 and replacement["id"] == lost["id"], replacement
ok(client.post(f"/jobs/{replacement['id']}/complete", json={"lease_token": replacement["lease_token"], "result": {"recovered": True}}), "complete recovered job")
detail = ok(client.get(f"/jobs/{lost['id']}"), "inspect recovered job")
assert sum(event["event_type"] == "job.claimed" for event in detail["events"]) == 2, detail
assert sum(event["event_type"] == "job.succeeded" for event in detail["events"]) == 1, detail

for row in claims[1:]:
    ok(client.post(f"/jobs/{row['id']}/complete", json={"lease_token": row["lease_token"]}), f"complete chaos job {row['id']}")

fleet = ok(client.get("/ui-state/worker-fleet?project_id=alpha"), "inspect worker fleet")
assert fleet["summary"]["workers"] >= 2 and fleet["sections"]["queue_policies"], fleet
snapshot = ok(client.get("/project/export"), "export worker fleet snapshot")
assert snapshot["runtime_workers"] and snapshot["runtime_queue_policies"], snapshot.keys()
with SessionLocal() as db:
    db.query(RuntimeWorker).delete()
    db.query(RuntimeQueuePolicy).delete()
    db.commit()
ok(client.post("/project/import", json={"snapshot": snapshot, "mode": "merge", "actor": "worker-recovery"}), "restore worker fleet snapshot")
restored_workers = ok(client.get("/runtime/workers"), "inspect restored workers")
assert restored_workers and all(row["configured_status"] == "OFFLINE" for row in restored_workers), restored_workers
restored_policies = ok(client.get("/runtime/queues"), "inspect restored queue policies")
assert {row["project_id"] for row in restored_policies} >= {"alpha", "beta", "concurrent"}, restored_policies
with SessionLocal() as db:
    audit_types = {row.event_type for row in db.query(AuditLog).filter(AuditLog.event_type.like("runtime.%")).all()}
assert {"runtime.worker.registered", "runtime.worker.draining", "runtime.worker.resumed", "runtime.queue_policy.updated"} <= audit_types, audit_types
passed += 1

print(f"\nWorker fleet control verified: {passed} assertions passed.")
engine.dispose()
tmpdir.cleanup()

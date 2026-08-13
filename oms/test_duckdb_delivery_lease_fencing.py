"""Snapshot publication is fenced from stale and concurrent pipeline workers."""
from __future__ import annotations

import os
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path


tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
root = Path(tmpdir.name)
os.environ["DATABASE_URL"] = os.getenv(
    "DUCKDB_FENCING_DATABASE_URL",
    f"sqlite:///{(root / 'lease_fencing.db').as_posix()}",
)
os.environ["DATA_SNAPSHOT_ROOT"] = str(root / "snapshots")
os.environ["AUTH_MODE"] = "local"
os.environ["APP_ENV"] = "test"

from fastapi import HTTPException  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from app.data_plane import DataAssetSnapshot, execute_duckdb_snapshot_plan  # noqa: E402
from app.database import SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.models import DataAsset  # noqa: E402
from app.models_action import AuditLog  # noqa: E402
from app.platform_runtime import PlatformJob, PlatformJobLease  # noqa: E402


client = TestClient(app)
passed = 0


def checked(response, expected=200):
    global passed
    assert response.status_code == expected, f"{response.status_code}: {response.text[:3000]}"
    passed += 1
    return response.json()


checked(client.post("/data-assets", json={
    "id": "fenced_input",
    "project_id": "default",
    "display_name": "Fenced input",
    "asset_schema": {},
    "records": [{"id": f"asset-{index:04d}", "score": index} for index in range(1000)],
}))
source = checked(client.post(
    "/api/v1/datasets/fenced_input/snapshots",
    json={"storage_format": "parquet"},
), 201)
checked(client.post("/pipeline-builder/graphs", json={
    "id": "fenced_duckdb_graph",
    "project_id": "default",
    "display_name": "Fenced DuckDB graph",
    "nodes": [
        {"id": "input", "type": "input_dataset", "config": {
            "asset_id": "fenced_input", "snapshot_id": source["id"],
        }},
        {"id": "output", "type": "dataset_output", "config": {
            "asset_id": "fenced_output",
        }},
    ],
    "edges": [{"id": "input-output", "source": "input", "target": "output"}],
}), 201)
plan = checked(client.post(
    "/api/v1/pipelines/fenced_duckdb_graph/plans",
    json={"executor": "duckdb"},
), 201)
queued = checked(client.post(
    f"/api/v1/pipeline-plans/{plan['id']}/execute",
    json={
        "mode": "deliver",
        "output_asset_id": "fenced_output",
        "idempotency_key": "fenced-delivery",
    },
), 202)["execution"]
first_claim = checked(client.post("/jobs/claim", json={
    "worker_id": "worker-that-will-expire",
    "supported_job_types": ["pipeline.duckdb.deliver"],
    "job_id": queued["id"],
    "lease_seconds": 10,
}))["job"]

with SessionLocal() as db:
    lease = db.query(PlatformJobLease).filter(PlatformJobLease.job_id == queued["id"]).one()
    lease.expires_at = int(time.time()) - 1
    db.commit()

with SessionLocal() as stale_db:
    try:
        execute_duckdb_snapshot_plan(
            stale_db,
            plan["id"],
            mode="deliver",
            limit=10,
            output_asset_id="fenced_output",
            parameters={},
            actor="local-user",
            execution_job_id=queued["id"],
            execution_fence_job_id=queued["id"],
            execution_lease_token=first_claim["lease_token"],
        )
        raise AssertionError("expired worker published a snapshot")
    except HTTPException as exc:
        assert exc.status_code == 409 and "lost its worker lease" in str(exc.detail), exc.detail
        passed += 1
        stale_db.rollback()

with SessionLocal() as db:
    assert db.query(DataAssetSnapshot).filter(DataAssetSnapshot.asset_id == "fenced_output").count() == 0
    assert db.get(DataAsset, "fenced_output") is None
    passed += 1
output_dir = root / "snapshots" / "default" / "fenced_output"
assert not output_dir.exists() or not list(output_dir.glob(".delivery-*.tmp*"))
passed += 1

# Claiming through the normal worker path reaps the expired lease, increments
# the attempt, and lets exactly one replacement worker publish the result.
replacement = checked(client.post("/pipeline-builder/workers/run-next", json={
    "worker_id": "replacement-worker",
    "job_id": queued["id"],
    "lease_seconds": 60,
}))
if replacement["job"] is None:
    after_replacement = checked(client.get(f"/jobs/{queued['id']}"))
    raise AssertionError({
        "replacement": replacement,
        "after": {key: after_replacement.get(key) for key in ("status", "attempt", "lease", "error")},
    })
assert replacement["job"]["status"] == "SUCCEEDED" and replacement["job"]["attempt"] == 2
assert replacement["result"]["row_count"] == 1000
passed += 1

snapshots = checked(client.get("/api/v1/datasets/fenced_output/snapshots"))["snapshots"]
assert len(snapshots) == 1
assert snapshots[0]["lineage"]["execution_job_id"] == queued["id"]
passed += 1
with SessionLocal() as db:
    assert db.query(DataAssetSnapshot).filter(DataAssetSnapshot.asset_id == "fenced_output").count() == 1
    job = db.get(PlatformJob, queued["id"])
    assert job and job.status == "SUCCEEDED" and job.attempt == 2
    audit = db.query(AuditLog).filter(
        AuditLog.event_type == "pipeline.duckdb.delivered",
        AuditLog.subject_id == snapshots[0]["id"],
    ).one()
    assert audit.payload["execution_job_id"] == queued["id"]
    assert audit.payload["lease_fenced"] is True
    passed += 1

details = checked(client.get(f"/jobs/{queued['id']}"))
event_types = [event["event_type"] for event in details["events"]]
assert event_types.count("job.claimed") == 2
assert "job.requeued" in event_types and event_types[-1] == "job.succeeded"
passed += 1

# A completed job is immutable evidence. A late stale process may read its
# existing snapshot, but cannot create another one.
with SessionLocal() as replay_db:
    replay = execute_duckdb_snapshot_plan(
        replay_db,
        plan["id"],
        mode="deliver",
        limit=10,
        output_asset_id="fenced_output",
        parameters={},
        actor="local-user",
        execution_job_id=queued["id"],
        execution_lease_token=first_claim["lease_token"],
    )
assert replay["idempotent_replay"] is True
assert replay["output_snapshot"]["id"] == snapshots[0]["id"]
passed += 1

if engine.dialect.name == "postgresql":
    concurrent_jobs = []
    for index in range(2):
        concurrent_jobs.append(checked(client.post(
            f"/api/v1/pipeline-plans/{plan['id']}/execute",
            json={
                "mode": "deliver",
                "output_asset_id": "concurrent_fenced_output",
                "idempotency_key": f"concurrent-fenced-delivery-{index}",
            },
        ), 202)["execution"])

    def run_worker(index: int):
        with TestClient(app) as worker_client:
            response = worker_client.post("/pipeline-builder/workers/run-next", json={
                "worker_id": f"concurrent-worker-{index}",
                "job_id": concurrent_jobs[index]["id"],
                "lease_seconds": 60,
            })
            assert response.status_code == 200, response.text
            return response.json()

    with ThreadPoolExecutor(max_workers=2) as executor:
        concurrent_results = list(executor.map(run_worker, range(2)))
    assert all(item["job"]["status"] == "SUCCEEDED" for item in concurrent_results)
    passed += 1
    concurrent_snapshots = checked(client.get(
        "/api/v1/datasets/concurrent_fenced_output/snapshots"
    ))["snapshots"]
    assert len(concurrent_snapshots) == 2
    assert {item["snapshot_number"] for item in concurrent_snapshots} == {1, 2}
    assert len({item["storage_uri"] for item in concurrent_snapshots}) == 2
    assert {item["lineage"]["execution_job_id"] for item in concurrent_snapshots} == {
        item["id"] for item in concurrent_jobs
    }
    passed += 1
    concurrent_dir = root / "snapshots" / "default" / "concurrent_fenced_output"
    assert not list(concurrent_dir.glob(".delivery-*.tmp*"))
    passed += 1

print(f"DuckDB stale-worker publication fencing verified: {passed} assertions passed.")
engine.dispose()
tmpdir.cleanup()

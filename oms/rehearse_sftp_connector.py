"""Rehearse the durable connector path against an external SFTP service."""
import os
import tempfile

required = ["SFTP_REHEARSAL_HOST", "SFTP_REHEARSAL_PORT", "SFTP_REHEARSAL_FINGERPRINT", "SFTP_REHEARSAL_USERNAME", "SFTP_REHEARSAL_PASSWORD"]
missing = [name for name in required if not os.getenv(name)]
if missing:
    raise SystemExit(f"Missing rehearsal environment variables: {', '.join(missing)}")

tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tmpdir.name, 'sftp-rehearsal.db')}"
os.environ["AUTH_MODE"] = "local"
os.environ["APP_ENV"] = "test"
os.environ["CONNECTOR_SECRET_KEY"] = "isolated-sftp-rehearsal-key"
os.environ["CONNECTOR_ALLOW_PRIVATE_NETWORKS"] = "true"

from fastapi.testclient import TestClient  # noqa: E402
from app import models  # noqa: E402
from app.database import SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402

client = TestClient(app)


def expect(response, status=200):
    if response.status_code != status:
        raise RuntimeError(f"Expected HTTP {status}, got {response.status_code}: {response.text[:1200]}")
    return response.json() if response.content else {}


with SessionLocal() as db:
    db.add(models.DataAsset(
        id="sftp_rehearsal_target", display_name="SFTP Rehearsal Target", description=None,
        kind="dataset", asset_schema={}, records=[], file_ref=None, source_format=None, created_at=1, updated_at=1,
    ))
    db.commit()

expect(client.post("/connections/sources", json={
    "id": "sftp_rehearsal", "display_name": "SFTP Rehearsal", "source_type": "sftp",
    "config": {
        "host": os.environ["SFTP_REHEARSAL_HOST"], "port": int(os.environ["SFTP_REHEARSAL_PORT"]),
        "username": os.environ["SFTP_REHEARSAL_USERNAME"], "remote_path": "/upload",
        "host_key_sha256": os.environ["SFTP_REHEARSAL_FINGERPRINT"], "format": "jsonl",
        "execution_mode": "live", "batch_size": 10,
    },
}))
expect(client.post("/connections/sources/sftp_rehearsal/runtime-credentials", json={
    "credential_type": "sftp_password", "secret": os.environ["SFTP_REHEARSAL_PASSWORD"], "metadata": {},
}), 201)
preview = expect(client.post("/connections/sources/sftp_rehearsal/live-preview", json={"limit": 10}))
if preview["record_count"] != 2:
    raise RuntimeError(f"Expected two preview records, got {preview['record_count']}")
expect(client.post("/connections/sources/sftp_rehearsal/syncs", json={
    "id": "sftp_rehearsal_sync", "target_asset_id": "sftp_rehearsal_target",
    "mode": "incremental", "cursor_field": "_source_file_path",
}))
queued = expect(client.post("/ingestion/syncs/sftp_rehearsal_sync/enqueue", json={"idempotency_key": "sftp-rehearsal"}), 202)
executed = expect(client.post("/ingestion/workers/run-next", json={"job_id": queued["job"]["id"], "worker_id": "sftp-rehearsal-worker"}))
if executed["job"]["status"] != "SUCCEEDED" or executed["run"]["records_out"] != 2:
    raise RuntimeError(f"Durable SFTP execution failed: {executed}")
with SessionLocal() as db:
    target = db.get(models.DataAsset, "sftp_rehearsal_target")
    if [row.get("asset_id") for row in target.records] != ["asset_sftp_1", "asset_sftp_2"]:
        raise RuntimeError(f"Unexpected target records: {target.records}")

print("SFTP_DOCKER_REHEARSAL_PASSED: 2 records previewed and durably ingested")
engine.dispose()
tmpdir.cleanup()

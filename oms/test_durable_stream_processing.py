"""Durable stream watermarks, windows, quarantine, pressure, and job recovery."""

import os
import tempfile


tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tmpdir.name, 'stream_processing.db')}"
os.environ["AUTH_MODE"] = "local"
os.environ["APP_ENV"] = "test"

from fastapi.testclient import TestClient  # noqa: E402
from app.database import SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.models import DataAsset  # noqa: E402
from app.stream_processing import (  # noqa: E402
    StreamPartitionState, StreamProcessor, StreamProcessingReceipt,
    StreamProcessingRun, StreamQuarantineRecord, StreamWindowState,
)
from app.streaming import StreamRecord  # noqa: E402


client = TestClient(app, raise_server_exceptions=False)


def checked(response, expected=200):
    assert response.status_code == expected, f"{response.status_code}: {response.text[:2000]}"
    return response.json() if response.content else {}


checked(client.post("/data-assets", json={
    "id": "window_output", "project_id": "default", "display_name": "Window output",
    "kind": "dataset", "asset_schema": {}, "records": [],
}))
checked(client.post("/streams", json={
    "id": "telemetry", "project_id": "default", "display_name": "Telemetry",
    "schema": {"event_ts": "number", "machine": "string", "value": "number"},
}))
processor = checked(client.post("/api/v1/streams/processors", json={
    "id": "telemetry_windows", "project_id": "default", "stream_id": "telemetry",
    "display_name": "Telemetry windows", "timestamp_field": "event_ts",
    "partition_key_field": "machine", "allowed_lateness_seconds": 5,
    "late_policy": "quarantine", "window_size_seconds": 10,
    "value_field": "value", "aggregation": "avg", "target_asset_id": "window_output",
    "max_batch_records": 100, "max_backlog_records": 10, "backpressure_mode": "reject",
}), 201)
assert processor["aggregation"] == "avg" and processor["enabled"] is True

checked(client.post("/streams/telemetry/publish", json={"records": [
    {"event_ts": 100, "machine": "A", "value": 10},
    {"event_ts": 104, "machine": "A", "value": 20},
    {"event_ts": 120, "machine": "A", "value": 30},
]}))
first = checked(client.post("/api/v1/streams/processors/telemetry_windows/process", json={}))
assert first["records_processed"] == 3 and first["records_quarantined"] == 0, first
assert first["windows_emitted"] == 1 and first["backlog_after"] == 0
detail = checked(client.get("/api/v1/streams/processors/telemetry_windows"))
partition_a = next(row for row in detail["partitions"] if row["partition_key"] == "A")
assert partition_a["max_event_time"] == 120 and partition_a["watermark"] == 115
with SessionLocal() as db:
    asset = db.get(DataAsset, "window_output")
    assert len(asset.records) == 1
    assert asset.records[0]["window_start"] == 100 and asset.records[0]["value"] == 15

# Watermarks are partition-local; B's older clock does not inherit A's watermark.
checked(client.post("/streams/telemetry/publish", json={"records": [
    {"event_ts": 10, "machine": "B", "value": 4},
    {"event_ts": 90, "machine": "A", "value": 99},
    {"event_ts": "invalid", "machine": "A", "value": 7},
]}))
second = checked(client.post("/api/v1/streams/processors/telemetry_windows/process", json={}))
assert second["records_processed"] == 3 and second["records_late"] == 1
assert second["records_quarantined"] == 2 and second["status"] == "WARN"
quarantine = checked(client.get("/api/v1/streams/processors/telemetry_windows/quarantine"))
assert {row["reason"] for row in quarantine} == {"event_time_before_watermark", "invalid_event_time"}
assert all(row["status"] == "PENDING" for row in quarantine)

# Every record is handled once; an empty rerun does not duplicate windows or receipts.
empty = checked(client.post("/api/v1/streams/processors/telemetry_windows/process", json={}))
assert empty["records_processed"] == 0 and empty["windows_emitted"] == 0
with SessionLocal() as db:
    assert db.query(StreamProcessingReceipt).count() == db.query(StreamRecord).count() == 6
    assert db.query(StreamQuarantineRecord).count() == 2

# Reject mode applies backpressure before any stream rows are inserted.
checked(client.patch("/api/v1/streams/processors/telemetry_windows", json={
    "max_backlog_records": 2, "backpressure_mode": "reject",
}))
rejected = checked(client.post("/streams/telemetry/publish", json={"records": [
    {"event_ts": 130, "machine": "A", "value": 1},
    {"event_ts": 131, "machine": "A", "value": 2},
    {"event_ts": 132, "machine": "A", "value": 3},
]}), 429)
assert rejected["detail"]["projected_backlog"] == 3
with SessionLocal() as db:
    assert db.query(StreamRecord).count() == 6

# Warn mode admits data and exposes active pressure without losing records.
checked(client.patch("/api/v1/streams/processors/telemetry_windows", json={
    "backpressure_mode": "warn",
}))
checked(client.post("/streams/telemetry/publish", json={"records": [
    {"event_ts": 130, "machine": "A", "value": 1},
    {"event_ts": 131, "machine": "A", "value": 2},
    {"event_ts": 142, "machine": "A", "value": 3},
]}))
summary = checked(client.get("/api/v1/streams/processing/summary?project_id=default"))
assert summary["backlog"] == 3 and summary["backpressure_active"] is True

# A crash in the middle of a batch rolls back run, receipts, state, and output together.
failed = client.post("/api/v1/streams/processors/telemetry_windows/process", json={
    "inject_failure_after_records": 1,
})
assert failed.status_code == 500
with SessionLocal() as db:
    assert db.query(StreamProcessingReceipt).count() == 6
    assert db.query(StreamProcessingRun).count() == 3  # first, second, empty only

# Durable job execution consumes the same backlog and is idempotently recoverable.
job = checked(client.post("/api/v1/streams/processors/telemetry_windows/enqueue", json={
    "idempotency_key": "telemetry-window-batch-1", "max_records": 100,
}), 202)
worked = checked(client.post("/api/v1/streams/processors/workers/run-next", json={
    "worker_id": "stream-worker", "job_id": job["id"],
}))
assert worked["job"]["status"] == "SUCCEEDED" and worked["run"]["records_processed"] == 3
replayed_job = checked(client.post("/api/v1/streams/processors/telemetry_windows/enqueue", json={
    "idempotency_key": "telemetry-window-batch-1", "max_records": 100,
}), 202)
assert replayed_job["id"] == job["id"] and replayed_job["idempotent_replay"] is True
final_summary = checked(client.get("/api/v1/streams/processing/summary?project_id=default"))
assert final_summary["backlog"] == 0 and final_summary["backpressure_active"] is False

# Portable recovery includes processor definitions and every state/evidence table.
snapshot = checked(client.get("/project/export?project_id=default"))
for key in (
    "stream_processors", "stream_partition_states", "stream_window_states",
    "stream_processing_receipts", "stream_quarantine_records", "stream_processing_runs",
):
    assert key in snapshot and snapshot[key], key
assert checked(client.post("/project/import/validate", json={"snapshot": snapshot}))["status"] == "VALID"
with SessionLocal() as db:
    for model in (
        StreamQuarantineRecord, StreamProcessingReceipt, StreamWindowState,
        StreamPartitionState, StreamProcessingRun, StreamProcessor,
    ):
        db.query(model).delete()
    db.commit()
restored = checked(client.post("/project/import", json={"snapshot": snapshot, "mode": "merge"}))
assert restored["status"] == "IMPORTED", restored
with SessionLocal() as db:
    assert db.query(StreamProcessor).count() == len(snapshot["stream_processors"])
    assert db.query(StreamProcessingReceipt).count() == len(snapshot["stream_processing_receipts"])
    assert db.query(StreamQuarantineRecord).count() == len(snapshot["stream_quarantine_records"])

print("Durable event-time stream processing verified.")
engine.dispose()
tmpdir.cleanup()

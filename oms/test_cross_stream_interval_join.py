"""Two-sided interval joins survive late arrival, failure, replay, and snapshot recovery."""

import copy
import os
import tempfile


temporary = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(temporary.name, 'cross-stream-join.db')}"
os.environ["AUTH_MODE"] = "local"
os.environ["APP_ENV"] = "test"

from fastapi.testclient import TestClient  # noqa: E402
from app.database import SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app import system_hardening  # noqa: E402
from app.models import DataAsset  # noqa: E402
from app.stream_processing import (  # noqa: E402
    StreamJoinInput, StreamJoinReceipt, StreamPartitionState, StreamProcessingReceipt,
    StreamProcessingRun, StreamProcessor, StreamQuarantineRecord,
)


client = TestClient(app, raise_server_exceptions=False)
passed = 0


def checked(response, label, expected=200):
    global passed
    assert response.status_code == expected, f"{label}: {response.status_code} {response.text[:2000]}"
    passed += 1
    return response.json() if response.content else {}


checked(client.post("/data-assets", json={
    "id": "correlated_events", "project_id": "default", "display_name": "Correlated events",
    "kind": "dataset", "asset_schema": {}, "records": [],
}), "join output")
for stream_id, name in (("asset_signals", "Asset signals"), ("work_orders", "Work orders")):
    checked(client.post("/streams", json={
        "id": stream_id, "project_id": "default", "display_name": name,
        "schema": {"event_ts": "number", "asset_id": "string"},
    }), f"create {stream_id}")

partial = checked(client.post("/api/v1/streams/processors", json={
    "stream_id": "asset_signals", "display_name": "Invalid partial join",
    "join_stream_id": "work_orders",
}), "reject partial join", 422)
assert "required together" in partial["detail"]
passed += 1

processor = checked(client.post("/api/v1/streams/processors", json={
    "id": "asset_work_order_join", "project_id": "default",
    "stream_id": "asset_signals", "join_stream_id": "work_orders",
    "display_name": "Asset signal to work-order interval join",
    "timestamp_field": "event_ts", "partition_key_field": "asset_id",
    "allowed_lateness_seconds": 5, "late_policy": "quarantine",
    "join_left_key": "asset_id", "join_right_key": "asset_id",
    "join_time_tolerance_seconds": 5, "target_asset_id": "correlated_events",
    "max_batch_records": 100, "max_backlog_records": 1000,
}), "create join processor", 201)
assert processor["join_stream_id"] == "work_orders" and processor["join_time_tolerance_seconds"] == 5
passed += 1


def publish(stream_id, records, label):
    return checked(client.post(f"/streams/{stream_id}/publish", json={"records": records}), label)


publish("asset_signals", [{"event_ts": 100, "asset_id": "A", "temperature": 91}], "left A")
left_first = checked(client.post("/api/v1/streams/processors/asset_work_order_join/process", json={}), "process left first")
assert left_first["records_processed"] == 1 and left_first["joins_emitted"] == 0
passed += 1

publish("work_orders", [{"event_ts": 103, "asset_id": "A", "work_order": "WO-A1"}], "right A")
right_later = checked(client.post("/api/v1/streams/processors/asset_work_order_join/process", json={}), "join right later")
assert right_later["records_processed"] == 1 and right_later["joins_emitted"] == 1
passed += 1

# A second right-side event within tolerance creates a second exact pair.
publish("work_orders", [{"event_ts": 104, "asset_id": "A", "work_order": "WO-A2"}], "second right A")
many = checked(client.post("/api/v1/streams/processors/asset_work_order_join/process", json={}), "many-to-many join")
assert many["joins_emitted"] == 1
passed += 1

# Right-first arrival is retained and matched when the left side appears later.
publish("work_orders", [{"event_ts": 202, "asset_id": "B", "work_order": "WO-B1"}], "right B first")
checked(client.post("/api/v1/streams/processors/asset_work_order_join/process", json={}), "retain right B")
publish("asset_signals", [{"event_ts": 198, "asset_id": "B", "temperature": 84}], "left B later")
left_later = checked(client.post("/api/v1/streams/processors/asset_work_order_join/process", json={}), "join left later")
assert left_later["joins_emitted"] == 1
passed += 1

with SessionLocal() as db:
    asset = db.get(DataAsset, "correlated_events")
    assert len(asset.records) == 3
    assert {row["join_key"] for row in asset.records} == {"A", "B"}
    assert len({row["_stream_join_id"] for row in asset.records}) == 3
    assert db.query(StreamJoinReceipt).count() == 3
    passed += 4

# Watermarks are source-and-partition local. Advance right C, then quarantine an old right C.
publish("work_orders", [{"event_ts": 300, "asset_id": "C", "work_order": "WO-C-new"}], "advance right C")
checked(client.post("/api/v1/streams/processors/asset_work_order_join/process", json={}), "process right C watermark")
publish("work_orders", [
    {"event_ts": 100, "asset_id": "C", "work_order": "WO-C-late"},
    {"event_ts": 310, "work_order": "WO-no-key"},
], "late and invalid right")
warn = checked(client.post("/api/v1/streams/processors/asset_work_order_join/process", json={}), "quarantine invalid join input")
assert warn["records_late"] == 1 and warn["records_quarantined"] == 2 and warn["status"] == "WARN"
quarantine = checked(client.get("/api/v1/streams/processors/asset_work_order_join/quarantine"), "join quarantine")
assert {row["reason"] for row in quarantine} == {"event_time_before_watermark", "invalid_join_key"}
passed += 2

# Pair creation and output mutation are one transaction.
publish("asset_signals", [{"event_ts": 400, "asset_id": "D", "temperature": 99}], "left D")
checked(client.post("/api/v1/streams/processors/asset_work_order_join/process", json={}), "retain left D")
publish("work_orders", [{"event_ts": 401, "asset_id": "D", "work_order": "WO-D1"}], "right D")
failed = client.post("/api/v1/streams/processors/asset_work_order_join/process", json={
    "inject_failure_after_records": 1,
})
assert failed.status_code == 500
with SessionLocal() as db:
    assert db.query(StreamJoinReceipt).count() == 3
    assert db.query(StreamJoinInput).filter(StreamJoinInput.join_key == "D").count() == 1
    assert len(db.get(DataAsset, "correlated_events").records) == 3
    passed += 4
job = checked(client.post("/api/v1/streams/processors/asset_work_order_join/enqueue", json={
    "idempotency_key": "asset-work-order-D", "max_records": 100,
}), "enqueue D recovery", 202)
interrupted = checked(client.post("/api/v1/streams/processors/workers/run-next", json={
    "worker_id": "join-worker", "job_id": job["id"], "inject_failure_after_records": 1,
}), "interrupt D worker")
assert interrupted["job"]["status"] == "QUEUED" and interrupted["run"] is None
with SessionLocal() as db:
    assert db.query(StreamJoinReceipt).count() == 3
    assert len(db.get(DataAsset, "correlated_events").records) == 3
    passed += 3
completed = checked(client.post("/api/v1/streams/processors/workers/run-next", json={
    "worker_id": "join-worker", "job_id": job["id"],
}), "resume D worker")
assert completed["job"]["status"] == "SUCCEEDED" and completed["run"]["joins_emitted"] == 1
empty = checked(client.post("/api/v1/streams/processors/asset_work_order_join/process", json={}), "idempotent join rerun")
assert empty["records_processed"] == 0 and empty["joins_emitted"] == 0
passed += 2

detail = checked(client.get("/api/v1/streams/processors/asset_work_order_join"), "join processor detail")
assert detail["backlog"] == 0
assert {row["partition_key"] for row in detail["partitions"]} >= {"left:A", "right:A", "left:B", "right:B"}
passed += 2

snapshot = checked(client.get("/project/export?project_id=default"), "export join state")
for key in ("stream_join_inputs", "stream_join_receipts"):
    assert key in snapshot and snapshot[key], key
assert checked(client.post("/project/import/validate", json={"snapshot": snapshot}), "validate join snapshot")["status"] == "VALID"
tampered = copy.deepcopy(snapshot)
tampered.pop("integrity", None)
missing_record_id = tampered["stream_join_inputs"][0]["record_id"]
tampered["stream_records"] = [row for row in tampered["stream_records"] if row["id"] != missing_record_id]
tampered = system_hardening._finalize_snapshot(tampered)
invalid_snapshot = checked(client.post("/project/import/validate", json={"snapshot": tampered}), "reject incomplete join snapshot")
assert invalid_snapshot["status"] == "INVALID" and any(missing_record_id in error for error in invalid_snapshot["errors"])
passed += 1
with SessionLocal() as db:
    expected_inputs = len(snapshot["stream_join_inputs"])
    expected_pairs = len(snapshot["stream_join_receipts"])
    db.query(StreamJoinReceipt).delete()
    db.query(StreamJoinInput).delete()
    db.commit()
checked(client.post("/project/import", json={"snapshot": snapshot, "mode": "merge"}), "restore join state")
with SessionLocal() as db:
    assert db.query(StreamJoinInput).count() == expected_inputs
    assert db.query(StreamJoinReceipt).count() == expected_pairs == 4
    assert db.query(StreamProcessingReceipt).count() > 0
    assert db.query(StreamProcessingRun).count() > 0
    assert db.query(StreamPartitionState).count() > 0
    assert db.query(StreamQuarantineRecord).count() == 2
    passed += 6

print(f"Cross-stream interval joins verified: {passed} assertions passed.")
engine.dispose()
temporary.cleanup()

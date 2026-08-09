"""Outer interval joins finalize unmatched records exactly once at safe watermarks."""

import copy
import os
import tempfile
import time


temporary = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(temporary.name, 'cross-stream-outer.db')}"
os.environ["AUTH_MODE"] = "local"
os.environ["APP_ENV"] = "test"

from fastapi.testclient import TestClient  # noqa: E402
from app import system_hardening  # noqa: E402
from app.database import SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.models import DataAsset  # noqa: E402
from app.models_action import AuditLog  # noqa: E402
from app.stream_processing import (  # noqa: E402
    StreamJoinOuterReceipt,
    StreamJoinReceipt,
    StreamPartitionState,
    StreamProcessingRun,
    StreamProcessor,
    _emit_outer_unmatched,
    _materialize_join_outputs,
)


client = TestClient(app, raise_server_exceptions=False)
passed = 0


def checked(response, label, expected=200):
    global passed
    assert response.status_code == expected, f"{label}: {response.status_code} {response.text[:2000]}"
    passed += 1
    return response.json() if response.content else {}


checked(client.post("/data-assets", json={
    "id": "outer_join_output", "project_id": "default", "display_name": "Outer join output",
    "kind": "dataset", "asset_schema": {}, "records": [],
}), "create output")
for stream_id in ("outer_left", "outer_right"):
    checked(client.post("/streams", json={
        "id": stream_id, "project_id": "default", "display_name": stream_id,
        "schema": {"event_ts": "number", "asset_id": "string"},
    }), f"create {stream_id}")

invalid = checked(client.post("/api/v1/streams/processors", json={
    "stream_id": "outer_left", "display_name": "Invalid outer", "join_type": "left",
}), "outer type requires a join", 422)
assert "requires a configured stream join" in invalid["detail"]
passed += 1

unsafe = checked(client.post("/api/v1/streams/processors", json={
    "stream_id": "outer_left", "join_stream_id": "outer_right", "display_name": "Unsafe outer",
    "timestamp_field": "event_ts", "join_left_key": "asset_id", "join_right_key": "asset_id",
    "join_time_tolerance_seconds": 5, "join_type": "full", "late_policy": "accept",
    "target_asset_id": "outer_join_output",
}), "outer join rejects unbounded lateness", 422)
assert "quarantine or drop" in unsafe["detail"]
passed += 1

processor = checked(client.post("/api/v1/streams/processors", json={
    "id": "full_outer_join", "project_id": "default",
    "stream_id": "outer_left", "join_stream_id": "outer_right",
    "display_name": "Full asset interval join", "timestamp_field": "event_ts",
    "allowed_lateness_seconds": 0, "late_policy": "quarantine",
    "join_left_key": "asset_id", "join_right_key": "asset_id",
    "join_time_tolerance_seconds": 5, "join_type": "full",
    "target_asset_id": "outer_join_output", "max_batch_records": 100,
}), "create full outer join", 201)
assert processor["join_type"] == "full"
passed += 1


def publish(stream_id, rows, label):
    return checked(client.post(f"/streams/{stream_id}/publish", json={"records": rows}), label)


def process(label):
    return checked(client.post("/api/v1/streams/processors/full_outer_join/process", json={}), label)


def watermark(side, key, value, label, expected=200):
    return checked(client.post("/api/v1/streams/processors/full_outer_join/watermarks", json={
        "side": side, "join_key": key, "watermark": value,
    }), label, expected)


# A left record is not emitted until the right-side watermark strictly closes its interval.
publish("outer_left", [{"event_ts": 100, "asset_id": "A", "temperature": 91}], "left A")
assert process("retain left A")["outer_joins_emitted"] == 0
closed_left = watermark("right", "A", 106, "close left A")
assert closed_left["outer_joins_emitted"] == 1
assert watermark("right", "A", 106, "idempotent right watermark")["outer_joins_emitted"] == 0
regression = watermark("right", "A", 105, "reject watermark regression", 409)
assert regression["detail"]["code"] == "WATERMARK_REGRESSION"
passed += 4

# The symmetric right-side case is finalized from a left watermark.
publish("outer_right", [{"event_ts": 200, "asset_id": "B", "work_order": "WO-B"}], "right B")
assert process("retain right B")["outer_joins_emitted"] == 0
closed_right = watermark("left", "B", 206, "close right B")
assert closed_right["outer_joins_emitted"] == 1
passed += 2

# Matched records remain ordinary pair outputs and are never also emitted unmatched.
publish("outer_left", [{"event_ts": 300, "asset_id": "C", "temperature": 82}], "left C")
publish("outer_right", [{"event_ts": 303, "asset_id": "C", "work_order": "WO-C"}], "right C")
matched = process("match C")
assert matched["joins_emitted"] == 1 and matched["outer_joins_emitted"] == 0
assert watermark("left", "C", 400, "advance left C")["outer_joins_emitted"] == 0
assert watermark("right", "C", 400, "advance right C")["outer_joins_emitted"] == 0
passed += 3

# An event exactly on the possible-match boundary is still admissible.
publish("outer_left", [{"event_ts": 500, "asset_id": "D", "temperature": 77}], "left D")
process("retain left D")
assert watermark("right", "D", 505, "boundary remains open")["outer_joins_emitted"] == 0
assert watermark("right", "D", 505.1, "strictly close D")["outer_joins_emitted"] == 1
passed += 2

receipts = checked(client.get("/api/v1/streams/processors/full_outer_join/outer-receipts"), "list outer receipts")
assert len(receipts) == 3
assert {(row["side"], row["join_key"]) for row in receipts} == {("left", "A"), ("right", "B"), ("left", "D")}
detail = checked(client.get("/api/v1/streams/processors/full_outer_join"), "outer processor detail")
assert detail["outer_receipt_count"] == 3
passed += 3

with SessionLocal() as db:
    output = db.get(DataAsset, "outer_join_output")
    assert len(output.records) == 4
    assert {row["match_status"] for row in output.records} == {"MATCHED", "LEFT_UNMATCHED", "RIGHT_UNMATCHED"}
    assert db.query(StreamJoinReceipt).count() == 1
    assert db.query(StreamJoinOuterReceipt).count() == 3
    assert db.query(AuditLog).filter(AuditLog.event_type == "stream.join.watermark_advanced").count() >= 7
    passed += 5

# Portable snapshots preserve finalization receipts and remain reference-valid.
snapshot = checked(client.get("/project/export?project_id=default"), "export outer state")
assert snapshot["stream_processors"][0]["join_type"] == "full"
assert len(snapshot["stream_join_outer_receipts"]) == 3
assert all("outer_joins_emitted" in row for row in snapshot["stream_processing_runs"])
assert checked(client.post("/project/import/validate", json={"snapshot": snapshot}), "validate outer snapshot")["status"] == "VALID"
passed += 4

tampered = copy.deepcopy(snapshot)
tampered.pop("integrity", None)
tampered["stream_processing_runs"] = [
    row for row in tampered["stream_processing_runs"]
    if row["id"] != tampered["stream_join_outer_receipts"][0]["run_id"]
]
tampered = system_hardening._finalize_snapshot(tampered)
invalid = checked(client.post("/project/import/validate", json={"snapshot": tampered}), "reject missing finalization run")
assert invalid["status"] == "INVALID"
passed += 1

with SessionLocal() as db:
    db.query(StreamJoinOuterReceipt).delete()
    db.commit()
checked(client.post("/project/import", json={"snapshot": snapshot, "mode": "merge"}), "restore outer state")
with SessionLocal() as db:
    assert db.query(StreamJoinOuterReceipt).count() == 3
    passed += 1

# Matched inputs are excluded in SQL before applying the bounded output limit.
# Otherwise an older matched row can starve a later unmatched row indefinitely.
publish("outer_left", [
    {"event_ts": 600, "asset_id": "E", "temperature": 70},
    {"event_ts": 700, "asset_id": "E", "temperature": 99},
], "left E matched and unmatched")
publish("outer_right", [
    {"event_ts": 600, "asset_id": "E", "work_order": "WO-E"},
], "right E matched")
bounded_match = process("match first E record")
assert bounded_match["joins_emitted"] == 1
passed += 1

with SessionLocal() as db:
    processor_row = db.get(StreamProcessor, "full_outer_join")
    right_state = db.query(StreamPartitionState).filter(
        StreamPartitionState.processor_id == processor_row.id,
        StreamPartitionState.partition_key == "right:E",
    ).one()
    right_state.watermark = 706
    right_state.max_event_time = max(float(right_state.max_event_time or 0), 706)
    now = int(time.time() * 1000)
    bounded_run = StreamProcessingRun(
        id="streamrun_outer_bounded_limit", processor_id=processor_row.id,
        project_id=processor_row.project_id, status="RUNNING", backlog_before=0,
        backlog_after=0, records_processed=0, records_late=0,
        records_quarantined=0, windows_emitted=0, joins_emitted=0,
        outer_joins_emitted=0, metrics={}, created_at=now,
    )
    db.add(bounded_run)
    db.flush()
    bounded_outputs = []
    bounded_run.outer_joins_emitted = _emit_outer_unmatched(
        db, processor_row, bounded_run, bounded_outputs,
        join_keys={"E"}, max_outputs=1,
    )
    _materialize_join_outputs(db, processor_row, bounded_outputs)
    bounded_run.status = "COMPLETED"
    bounded_run.completed_at = now
    db.commit()
    assert bounded_run.outer_joins_emitted == 1
    assert bounded_outputs[0]["left"]["event_ts"] == 700
    assert bounded_outputs[0]["match_status"] == "LEFT_UNMATCHED"
    passed += 3

print(f"Cross-stream outer joins verified: {passed} assertions passed.")
engine.dispose()
temporary.cleanup()

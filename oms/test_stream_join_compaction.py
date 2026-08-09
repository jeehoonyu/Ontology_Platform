"""Bounded interval-join state compacts without losing pair or output evidence."""

import os
import tempfile


temporary = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(temporary.name, 'join-compaction.db')}"
os.environ["AUTH_MODE"] = "local"
os.environ["APP_ENV"] = "test"

from fastapi.testclient import TestClient  # noqa: E402
from app.database import SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.models import DataAsset  # noqa: E402
from app.models_action import AuditLog  # noqa: E402
from app.stream_processing import StreamJoinInput, StreamJoinReceipt  # noqa: E402


client = TestClient(app, raise_server_exceptions=False)
passed = 0


def checked(response, label, expected=200):
    global passed
    assert response.status_code == expected, f"{label}: {response.status_code} {response.text[:2000]}"
    passed += 1
    return response.json() if response.content else {}


checked(client.post("/data-assets", json={
    "id": "join_compaction_output", "project_id": "default", "display_name": "Join output",
    "kind": "dataset", "asset_schema": {}, "records": [],
}), "create output")
for stream_id in ("join_compaction_left", "join_compaction_right"):
    checked(client.post("/streams", json={
        "id": stream_id, "project_id": "default", "display_name": stream_id,
        "schema": {"event_ts": "number", "asset_id": "string"},
    }), f"create {stream_id}")

checked(client.post("/api/v1/streams/processors", json={
    "id": "bounded_join", "project_id": "default",
    "stream_id": "join_compaction_left", "join_stream_id": "join_compaction_right",
    "display_name": "Bounded join", "timestamp_field": "event_ts",
    "allowed_lateness_seconds": 0, "late_policy": "quarantine",
    "join_left_key": "asset_id", "join_right_key": "asset_id",
    "join_time_tolerance_seconds": 5, "target_asset_id": "join_compaction_output",
}), "create bounded join", 201)


def publish_pair(event_time):
    for side in ("left", "right"):
        checked(client.post(f"/streams/join_compaction_{side}/publish", json={"records": [{
            "event_ts": event_time, "asset_id": "A", "side": side,
        }]}), f"publish {side} {event_time}")
    return checked(client.post("/api/v1/streams/processors/bounded_join/process", json={}), f"process {event_time}")


assert publish_pair(100)["joins_emitted"] == 1
assert publish_pair(200)["joins_emitted"] == 1
passed += 2

with SessionLocal() as db:
    assert db.query(StreamJoinInput).count() == 4
    assert db.query(StreamJoinReceipt).count() == 2
    passed += 2

# A dry run proves the safe cutoff without changing durable state.
dry_run = checked(client.post("/api/v1/streams/processors/bounded_join/compact", json={
    "dry_run": True, "retention_seconds": 0, "max_inputs": 100,
}), "dry-run compaction")
assert dry_run["status"] == "DRY_RUN"
assert dry_run["inputs_compacted"] == 2 and dry_run["inputs_after"] == 4
assert dry_run["cutoffs"]["A"] == 195.0
with SessionLocal() as db:
    assert db.query(StreamJoinInput).count() == 4
passed += 4

# Bounded batches can be resumed; exact pair and output evidence are retained.
first = checked(client.post("/api/v1/streams/processors/bounded_join/compact", json={
    "retention_seconds": 0, "max_inputs": 1,
}), "bounded compaction")
assert first["inputs_compacted"] == 1 and first["limit_reached"] is True
second = checked(client.post("/api/v1/streams/processors/bounded_join/compact", json={
    "retention_seconds": 0, "max_inputs": 100,
}), "finish compaction")
assert second["inputs_compacted"] == 1 and second["inputs_after"] == 2
with SessionLocal() as db:
    assert db.query(StreamJoinInput).count() == 2
    assert db.query(StreamJoinReceipt).count() == 2
    assert len(db.get(DataAsset, "join_compaction_output").records) == 2
    event_types = {row.event_type for row in db.query(AuditLog).filter(
        AuditLog.subject_id == "bounded_join",
    ).all()}
    assert {"stream.join.compaction_evaluated", "stream.join.compacted"} <= event_types
    passed += 4

# The default one-day policy compacts state only after both source watermarks advance.
automatic = publish_pair(100000)
assert automatic["metrics"]["join_compaction"]["retention_seconds"] == 86400
assert automatic["metrics"]["join_compaction"]["inputs_compacted"] == 2
with SessionLocal() as db:
    assert db.query(StreamJoinInput).count() == 2
    assert db.query(StreamJoinReceipt).count() == 3
    assert len(db.get(DataAsset, "join_compaction_output").records) == 3
    passed += 3

# Replayed old input is governed by the watermark and cannot recreate compacted state.
checked(client.post("/streams/join_compaction_left/publish", json={"records": [{
    "event_ts": 100, "asset_id": "A", "side": "late-left",
}]}), "publish late input")
late = checked(client.post("/api/v1/streams/processors/bounded_join/process", json={}), "quarantine late input")
assert late["records_late"] == 1 and late["records_quarantined"] == 1
with SessionLocal() as db:
    assert db.query(StreamJoinInput).count() == 2
    assert db.query(StreamJoinReceipt).count() == 3
    passed += 2

# Accepting arbitrary late data explicitly keeps unbounded match state.
checked(client.post("/data-assets", json={
    "id": "accept_output", "project_id": "default", "display_name": "Accept output",
    "kind": "dataset", "asset_schema": {}, "records": [],
}), "create accept output")
checked(client.post("/api/v1/streams/processors", json={
    "id": "unbounded_join", "project_id": "default",
    "stream_id": "join_compaction_left", "join_stream_id": "join_compaction_right",
    "display_name": "Unbounded late join", "timestamp_field": "event_ts",
    "allowed_lateness_seconds": 0, "late_policy": "accept",
    "join_left_key": "asset_id", "join_right_key": "asset_id",
    "join_time_tolerance_seconds": 5, "target_asset_id": "accept_output",
}), "create unbounded join", 201)
skipped = checked(client.post("/api/v1/streams/processors/unbounded_join/compact", json={
    "retention_seconds": 0,
}), "skip unsafe compaction")
assert skipped["status"] == "SKIPPED"
assert skipped["reason"] == "late_accept_requires_unbounded_match_state"
passed += 2

print(f"Stream join compaction verified: {passed} assertions passed.")
engine.dispose()
temporary.cleanup()

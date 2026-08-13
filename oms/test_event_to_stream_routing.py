"""Ontology changes route exactly once into durable event-time processing."""
import os
import tempfile


temporary = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(temporary.name, 'event-to-stream.db')}"
os.environ["AUTH_MODE"] = "local"
os.environ["APP_ENV"] = "test"

from fastapi.testclient import TestClient  # noqa: E402
from app import event_outbox, stream_processing, streaming  # noqa: E402
from app.database import SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402


client = TestClient(app, raise_server_exceptions=False)
passed = 0


def check(response, label, expected=200):
    global passed
    assert response.status_code == expected, f"{label}: {response.status_code} {response.text[:1800]}"
    passed += 1
    return response.json() if response.content else {}


check(client.post("/streams", json={
    "id": "ontology-change-stream", "project_id": "default",
    "display_name": "Ontology change stream",
    "schema": {"event_type": "string", "object_type_id": "string", "occurred_at": "number"},
}), "target stream")
processor = check(client.post("/api/v1/streams/processors", json={
    "id": "ontology-change-counter", "project_id": "default",
    "stream_id": "ontology-change-stream", "display_name": "Ontology change counter",
    "timestamp_field": "occurred_at", "partition_key_field": "event_type",
    "allowed_lateness_seconds": 0, "late_policy": "accept",
    "aggregation": "count", "max_batch_records": 100,
    "max_backlog_records": 1000, "backpressure_mode": "reject",
}), "stream processor", 201)
assert processor["enabled"] is True
passed += 1

for object_type_id in ("routed_asset", "ignored_asset"):
    check(client.post("/object-types", json={
        "id": object_type_id, "project_id": "default", "display_name": object_type_id,
        "properties": {"asset_id": {"type": "string"}},
    }), f"{object_type_id} type")

binding = check(client.post("/api/v1/event-stream-bindings", json={
    "id": "asset-object-cdc", "project_id": "default", "display_name": "Asset object CDC",
    "target_stream_id": "ontology-change-stream", "topics": ["ontologyos.object_change"],
    "event_types": ["ontology.object.*", "pipeline_builder.object.*"],
    "aggregate_types": ["ontology_object"], "object_type_ids": ["routed_asset"],
}), "event stream binding", 201)
assert binding["cursor_sequence"] == 0 and binding["active"] is True
passed += 2


def create_object(object_id, object_type_id):
    return check(client.post("/objects", json={
        "id": object_id, "project_id": "default", "object_type_id": object_type_id,
        "properties": {"asset_id": object_id},
    }), f"create {object_id}")


def publish_object_change(object_id):
    with SessionLocal() as db:
        row = db.query(event_outbox.EventOutbox).filter(
            event_outbox.EventOutbox.topic == "ontologyos.object_change",
            event_outbox.EventOutbox.aggregate_id == object_id,
        ).order_by(event_outbox.EventOutbox.created_at.desc()).first()
        assert row is not None
        outbox_id = row.id
    published = check(client.post("/api/v1/outbox/workers/run-next", json={
        "worker_id": "object-cdc-publisher", "event_id": outbox_id,
    }), f"publish {object_id}")
    assert published["outbox"]["status"] == "PUBLISHED"
    return published["event"]


create_object("routed-1", "routed_asset")
create_object("ignored-1", "ignored_asset")
routed_event = publish_object_change("routed-1")
ignored_event = publish_object_change("ignored-1")

first = check(client.post("/api/v1/event-stream-bindings/asset-object-cdc/route", json={
    "max_events": 100,
}), "route first batch")
assert first["scanned"] == 2 and first["matched"] == first["routed"] == 1
assert first["duplicates"] == 0 and first["cursor_sequence"] == ignored_event["sequence"]
passed += 3

records = check(client.get("/streams/ontology-change-stream/records"), "routed records")
assert len(records) == 1
assert records[0]["payload"]["event_id"] == routed_event["event_id"]
assert records[0]["payload"]["payload"]["object_type_id"] == "routed_asset"
passed += 3

empty = check(client.post("/api/v1/event-stream-bindings/asset-object-cdc/route", json={}), "empty reroute")
assert empty["scanned"] == empty["routed"] == 0
passed += 1

# Injected failure rolls back stream rows, receipts, sequence allocation, and cursor.
create_object("routed-2", "routed_asset")
second_event = publish_object_change("routed-2")
failed = client.post("/api/v1/event-stream-bindings/asset-object-cdc/route", json={
    "inject_failure_after_records": 1,
})
assert failed.status_code == 500, failed.text
with SessionLocal() as db:
    row = db.get(event_outbox.EventStreamBinding, "asset-object-cdc")
    assert row.cursor_sequence == ignored_event["sequence"]
    assert db.query(event_outbox.EventStreamReceipt).count() == 1
    assert db.query(streaming.StreamRecord).count() == 1
    assert db.get(streaming.Stream, "ontology-change-stream").next_sequence == 1
    passed += 5

recovered = check(client.post("/api/v1/event-stream-bindings/asset-object-cdc/route", json={}), "recover route")
assert recovered["routed"] == 1 and recovered["cursor_sequence"] == second_event["sequence"]
passed += 2

# Leased background execution retries from the durable cursor without duplicates.
create_object("routed-3", "routed_asset")
third_event = publish_object_change("routed-3")
job = check(client.post("/api/v1/event-stream-bindings/asset-object-cdc/enqueue", json={
    "idempotency_key": "asset-cdc-generation-3",
}), "enqueue routing", 202)
job_replay = check(client.post("/api/v1/event-stream-bindings/asset-object-cdc/enqueue", json={
    "idempotency_key": "asset-cdc-generation-3",
}), "idempotent enqueue", 202)
assert job_replay["id"] == job["id"] and job_replay["idempotent_replay"] is True
passed += 1

interrupted = check(client.post("/api/v1/event-stream-bindings/workers/run-next", json={
    "worker_id": "event-router", "job_id": job["id"], "lease_seconds": 30,
    "inject_failure_after_records": 1,
}), "interrupted routing worker")
assert interrupted["job"]["status"] == "QUEUED" and interrupted["routing"] is None
with SessionLocal() as db:
    assert db.get(event_outbox.EventStreamBinding, "asset-object-cdc").cursor_sequence == second_event["sequence"]
    assert db.query(event_outbox.EventStreamReceipt).count() == 2
    passed += 3

completed = check(client.post("/api/v1/event-stream-bindings/workers/run-next", json={
    "worker_id": "event-router", "job_id": job["id"], "lease_seconds": 30,
}), "resumed routing worker")
assert completed["job"]["status"] == "SUCCEEDED"
assert completed["routing"]["routed"] == 1
assert completed["routing"]["cursor_sequence"] == third_event["sequence"]
passed += 3

receipts = check(client.get("/api/v1/event-stream-bindings/asset-object-cdc/receipts"), "routing receipts")
assert receipts["count"] == 3
assert len({row["event_id"] for row in receipts["receipts"]}) == 3
passed += 2

processed = check(client.post("/api/v1/streams/processors/ontology-change-counter/process", json={}), "process routed changes")
assert processed["records_processed"] == 3 and processed["records_quarantined"] == 0
processed_again = check(client.post("/api/v1/streams/processors/ontology-change-counter/process", json={}), "idempotent processing")
assert processed_again["records_processed"] == 0
with SessionLocal() as db:
    assert db.query(stream_processing.StreamProcessingReceipt).count() == 3
    assert db.query(streaming.StreamRecord).count() == 3
    passed += 3

detail = check(client.get("/api/v1/event-stream-bindings/asset-object-cdc"), "binding detail")
assert detail["receipt_count"] == 3 and detail["cursor_sequence"] == third_event["sequence"]
passed += 1

print(f"Event-to-stream routing verified: {passed} assertions passed.")
engine.dispose()
temporary.cleanup()

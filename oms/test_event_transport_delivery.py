"""Kafka-compatible outbox delivery receipts, retries, and recovery."""

import os
import tempfile
import uuid


tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tmpdir.name, 'event_transport.db')}"
os.environ["AUTH_MODE"] = "local"
os.environ["APP_ENV"] = "test"

from fastapi.testclient import TestClient  # noqa: E402
from app import event_outbox  # noqa: E402
from app.database import SessionLocal, engine  # noqa: E402
from app.event_outbox import EventOutbox, EventTransportReceipt  # noqa: E402
from app.main import app  # noqa: E402
from app.runtime import create_audit_log  # noqa: E402


client = TestClient(app)
published_calls = []


def checked(response, expected=200):
    assert response.status_code == expected, f"{response.status_code}: {response.text[:2000]}"
    return response.json() if response.content else {}


def create_published(event_type: str) -> EventOutbox:
    with SessionLocal() as db:
        evidence_id = uuid.uuid4().hex
        create_audit_log(
            db, actor="transport-test", event_type=event_type,
            subject_type="transport_probe", subject_id=evidence_id,
            payload={"project_id": "default", "probe": evidence_id},
        )
        db.commit()
        row = db.query(EventOutbox).filter(EventOutbox.event_type == event_type).one()
        event_id = row.id
    checked(client.post("/api/v1/outbox/workers/run-next", json={
        "worker_id": "internal-publisher", "event_id": event_id,
    }))
    with SessionLocal() as db:
        row = db.get(EventOutbox, event_id)
        db.expunge(row)
        return row


def fake_publish(row, destination, settings):
    event_id = event_outbox.hashlib.sha256(
        f"{row.project_id}\x1f{row.idempotency_key}".encode("utf-8")
    ).hexdigest()
    published_calls.append((row.id, destination, event_id, tuple(settings["bootstrap_servers"])))
    return {"topic": destination, "partition": 1, "offset": len(published_calls) - 1, "timestamp": 123, "event_id": event_id}


# A worker cannot silently fall back when the external transport is unconfigured.
os.environ.pop("EVENT_KAFKA_BOOTSTRAP_SERVERS", None)
checked(client.post("/api/v1/outbox/kafka/workers/run-next", json={"worker_id": "kafka-a"}), 503)

os.environ["EVENT_KAFKA_BOOTSTRAP_SERVERS"] = "broker-a:9092,broker-b:9092"
os.environ["EVENT_KAFKA_SECURITY_PROTOCOL"] = "PLAINTEXT"
event_outbox._publish_kafka = fake_publish

# A published internal event receives one durable broker receipt.
source = create_published("transport.kafka.success")
delivered = checked(client.post("/api/v1/outbox/kafka/workers/run-next", json={
    "worker_id": "kafka-a", "event_id": source.id,
}))
assert delivered["delivery"]["status"] == "DELIVERED"
assert delivered["delivery"]["broker_metadata"]["offset"] == 0
assert published_calls[0][0] == source.id and published_calls[0][1] == source.topic
receipt_id = delivered["delivery"]["id"]

# Replay is at-least-once but uses the same deterministic event identity.
checked(client.post(f"/api/v1/outbox/transport-receipts/{receipt_id}/replay", json={"reset_attempts": True}))
ambiguous = checked(client.post("/api/v1/outbox/kafka/workers/run-next", json={
    "worker_id": "kafka-b", "event_id": source.id, "inject_failure": "after_publish",
}))
assert ambiguous["delivery"]["status"] == "RETRY" and ambiguous["delivery"]["attempts"] == 1
assert published_calls[0][2] == published_calls[1][2]
checked(client.post(f"/api/v1/outbox/transport-receipts/{receipt_id}/replay", json={"reset_attempts": False}))
redelivered = checked(client.post("/api/v1/outbox/kafka/workers/run-next", json={
    "worker_id": "kafka-c", "event_id": source.id,
}))
assert redelivered["delivery"]["status"] == "DELIVERED" and redelivered["delivery"]["attempts"] == 2

# Expired leases recover and repeated failures dead-letter independently of the outbox.
expired_source = create_published("transport.kafka.expired")
checked(client.post("/api/v1/outbox/kafka/workers/run-next", json={
    "worker_id": "kafka-expired", "event_id": expired_source.id, "inject_failure": "before_publish",
}))
with SessionLocal() as db:
    expired_receipt = db.query(EventTransportReceipt).filter(
        EventTransportReceipt.outbox_event_id == expired_source.id
    ).one()
    expired_receipt.status = "IN_FLIGHT"
    expired_receipt.lease_owner = "lost-worker"
    expired_receipt.lease_token = uuid.uuid4().hex
    expired_receipt.lease_expires_at = 1
    expired_receipt.available_at = 1
    db.commit()
recovered = checked(client.post("/api/v1/outbox/kafka/workers/run-next", json={
    "worker_id": "kafka-recovery", "event_id": expired_source.id,
}))
assert recovered["delivery"]["status"] == "DELIVERED"

dead_source = create_published("transport.kafka.dead")
latest = None
for attempt in range(5):
    latest = checked(client.post("/api/v1/outbox/kafka/workers/run-next", json={
        "worker_id": "kafka-fail", "event_id": dead_source.id, "inject_failure": "before_publish",
    }))
    if attempt < 4:
        assert latest["delivery"]["status"] == "RETRY"
        checked(client.post(
            f"/api/v1/outbox/transport-receipts/{latest['delivery']['id']}/replay",
            json={"reset_attempts": False},
        ))
assert latest["delivery"]["status"] == "DEAD_LETTER" and latest["delivery"]["attempts"] == 5

listed = checked(client.get("/api/v1/outbox/transport-receipts?project_id=default&transport=kafka"))
assert listed["count"] == 3
summary = checked(client.get("/api/v1/outbox/summary?project_id=default"))
assert summary["transport_deliveries"]["kafka:DELIVERED"] == 2
assert summary["transport_deliveries"]["kafka:DEAD_LETTER"] == 1

# Production refuses accidental plaintext broker delivery.
os.environ["APP_ENV"] = "production"
os.environ.pop("EVENT_KAFKA_ALLOW_PLAINTEXT", None)
checked(client.post("/api/v1/outbox/kafka/workers/run-next", json={"worker_id": "kafka-production"}), 503)

print("Kafka-compatible event transport delivery verified.")
engine.dispose()
tmpdir.cleanup()

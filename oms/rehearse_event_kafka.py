"""Rehearse transactional outbox delivery against a real Kafka-compatible broker.

Start the repository Kafka profile first, then run this script. It intentionally
uses a unique topic prefix and an isolated SQLite database.
"""

import json
import os
import tempfile
import time
import uuid


tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
run_id = uuid.uuid4().hex[:12]
os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tmpdir.name, 'event_kafka.db')}"
os.environ["AUTH_MODE"] = "local"
os.environ["APP_ENV"] = "test"
os.environ["EVENT_KAFKA_BOOTSTRAP_SERVERS"] = os.getenv("EVENT_KAFKA_BOOTSTRAP_SERVERS", "127.0.0.1:9092")
os.environ["EVENT_KAFKA_SECURITY_PROTOCOL"] = os.getenv("EVENT_KAFKA_SECURITY_PROTOCOL", "PLAINTEXT")
os.environ["EVENT_KAFKA_TOPIC_PREFIX"] = f"ontologyos.rehearsal.{run_id}"

from fastapi.testclient import TestClient  # noqa: E402
from kafka import KafkaConsumer  # noqa: E402
from app.database import SessionLocal, engine  # noqa: E402
from app.event_outbox import EventOutbox  # noqa: E402
from app.main import app  # noqa: E402
from app.runtime import create_audit_log  # noqa: E402


client = TestClient(app)
event_type = "rehearsal.kafka.delivery"
with SessionLocal() as db:
    evidence_id = f"kafka-rehearsal-{run_id}"
    create_audit_log(
        db, actor="kafka-rehearsal", event_type=event_type,
        subject_type="rehearsal", subject_id=evidence_id,
        payload={"project_id": "default", "run_id": run_id},
    )
    db.commit()
    outbox = db.query(EventOutbox).filter(EventOutbox.event_type == event_type).one()
    outbox_id = outbox.id
    destination = f"{os.environ['EVENT_KAFKA_TOPIC_PREFIX']}.{outbox.topic}"

internal = client.post("/api/v1/outbox/workers/run-next", json={
    "worker_id": "kafka-rehearsal-internal", "event_id": outbox_id,
})
assert internal.status_code == 200 and internal.json()["outbox"]["status"] == "PUBLISHED", internal.text

external = client.post("/api/v1/outbox/kafka/workers/run-next", json={
    "worker_id": "kafka-rehearsal-external", "event_id": outbox_id,
})
assert external.status_code == 200, external.text
delivery = external.json()["delivery"]
assert delivery["status"] == "DELIVERED" and delivery["destination"] == destination, delivery

consumer = KafkaConsumer(
    destination,
    bootstrap_servers=[value.strip() for value in os.environ["EVENT_KAFKA_BOOTSTRAP_SERVERS"].split(",")],
    security_protocol=os.environ["EVENT_KAFKA_SECURITY_PROTOCOL"],
    group_id=f"ontologyos-rehearsal-{run_id}",
    auto_offset_reset="earliest",
    enable_auto_commit=False,
    consumer_timeout_ms=15000,
    value_deserializer=lambda raw: json.loads(raw.decode("utf-8")),
)
try:
    matched = None
    deadline = time.time() + 15
    while time.time() < deadline and matched is None:
        for message in consumer:
            if message.value.get("outbox_event_id") == outbox_id:
                matched = message
                break
    assert matched is not None, f"No matching event consumed from {destination}"
    envelope = matched.value
    assert envelope["event_type"] == event_type
    assert envelope["project_id"] == "default"
    assert envelope["payload"]["run_id"] == run_id
    assert envelope["event_id"] == delivery["broker_metadata"]["event_id"]
    assert matched.partition == delivery["broker_metadata"]["partition"]
    assert matched.offset == delivery["broker_metadata"]["offset"]
finally:
    consumer.close()

print(
    f"Kafka event delivery rehearsal passed: topic={destination} "
    f"partition={delivery['broker_metadata']['partition']} offset={delivery['broker_metadata']['offset']}"
)
engine.dispose()
tmpdir.cleanup()

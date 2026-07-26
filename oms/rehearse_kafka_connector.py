"""Rehearse durable partition-offset ingestion against an external Kafka broker."""
import json
import os
import tempfile
import time

bootstrap_servers = os.getenv("KAFKA_REHEARSAL_BOOTSTRAP_SERVERS", "127.0.0.1:9092")
topic = os.getenv("KAFKA_REHEARSAL_TOPIC", f"ontology-rehearsal-{int(time.time())}")

tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tmpdir.name, 'kafka-rehearsal.db')}"
os.environ["AUTH_MODE"] = "local"
os.environ["APP_ENV"] = "test"
os.environ["CONNECTOR_SECRET_KEY"] = "isolated-kafka-rehearsal-key"
os.environ["CONNECTOR_ALLOW_PRIVATE_NETWORKS"] = "true"

from fastapi.testclient import TestClient  # noqa: E402
from kafka import KafkaProducer  # noqa: E402
from kafka.admin import KafkaAdminClient, NewTopic  # noqa: E402
from kafka.errors import TopicAlreadyExistsError  # noqa: E402
from app import models  # noqa: E402
from app.database import SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402

admin = KafkaAdminClient(bootstrap_servers=bootstrap_servers, client_id="ontology-rehearsal-admin")
try:
    admin.create_topics([NewTopic(name=topic, num_partitions=1, replication_factor=1)])
except TopicAlreadyExistsError:
    pass
producer = KafkaProducer(bootstrap_servers=bootstrap_servers, value_serializer=lambda value: json.dumps(value).encode())


def publish(records):
    for record in records:
        producer.send(topic, record)
    producer.flush(timeout=10)


publish([{"asset_id": "kafka_rehearsal_1", "status": "DEGRADED"}, {"asset_id": "kafka_rehearsal_2", "status": "RUNNING"}])
client = TestClient(app)


def expect(response, status=200):
    if response.status_code != status:
        raise RuntimeError(f"Expected HTTP {status}, got {response.status_code}: {response.text[:1200]}")
    return response.json() if response.content else {}


with SessionLocal() as db:
    db.add(models.DataAsset(
        id="kafka_rehearsal_target", display_name="Kafka Rehearsal Target", description=None,
        kind="dataset", asset_schema={}, records=[], file_ref=None, source_format=None, created_at=1, updated_at=1,
    ))
    db.commit()

expect(client.post("/connections/sources", json={
    "id": "kafka_rehearsal", "display_name": "Kafka Rehearsal", "source_type": "kafka",
    "config": {
        "bootstrap_servers": bootstrap_servers, "topic": topic, "security_protocol": "PLAINTEXT",
        "execution_mode": "live", "auto_offset_reset": "earliest", "poll_timeout_ms": 3000, "max_records": 100,
    },
}))
expect(client.post("/connections/sources/kafka_rehearsal/syncs", json={
    "id": "kafka_rehearsal_sync", "target_asset_id": "kafka_rehearsal_target", "mode": "incremental",
}))


def run(idempotency_key):
    queued = expect(client.post("/ingestion/syncs/kafka_rehearsal_sync/enqueue", json={"idempotency_key": idempotency_key}), 202)
    return expect(client.post("/ingestion/workers/run-next", json={"job_id": queued["job"]["id"], "worker_id": "kafka-rehearsal-worker"}))


first = run("kafka-rehearsal-1")
if first["job"]["status"] != "SUCCEEDED" or first["run"]["records_out"] != 2:
    raise RuntimeError(f"First Kafka ingestion failed: {first}")
publish([{"asset_id": "kafka_rehearsal_3", "status": "CRITICAL"}])
second = run("kafka-rehearsal-2")
if second["job"]["status"] != "SUCCEEDED" or second["run"]["records_out"] != 1:
    raise RuntimeError(f"Offset resume failed: {second}")
with SessionLocal() as db:
    target = db.get(models.DataAsset, "kafka_rehearsal_target")
    ids = [row.get("asset_id") for row in target.records]
    if ids != ["kafka_rehearsal_1", "kafka_rehearsal_2", "kafka_rehearsal_3"]:
        raise RuntimeError(f"Unexpected Kafka target records: {ids}")
cursor = expect(client.get("/connections/syncs/kafka_rehearsal_sync/cursor"))
if cursor["last_value"] != {"0": 3}:
    raise RuntimeError(f"Unexpected Kafka cursor: {cursor}")

print("KAFKA_DOCKER_REHEARSAL_PASSED: partition 0 resumed at offset 3 without duplicates")
producer.close()
admin.delete_topics([topic])
admin.close()
engine.dispose()
tmpdir.cleanup()

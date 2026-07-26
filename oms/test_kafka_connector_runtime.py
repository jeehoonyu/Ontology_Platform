"""Kafka partition cursors, transport policy, SASL isolation, and retry evidence."""
import json
import os
import tempfile
from types import SimpleNamespace

tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tmpdir.name, 'kafka.db')}"
os.environ["AUTH_MODE"] = "local"
os.environ["APP_ENV"] = "test"
os.environ["CONNECTOR_SECRET_KEY"] = "kafka-connector-test-key"
os.environ["CONNECTOR_ALLOW_PRIVATE_NETWORKS"] = "true"

from fastapi.testclient import TestClient  # noqa: E402
from kafka.errors import KafkaConnectionError  # noqa: E402
from app import connector_runtime, models  # noqa: E402
from app.database import SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402


def message(partition, offset, payload, timestamp):
    return SimpleNamespace(partition=partition, offset=offset, value=None if payload is None else json.dumps(payload).encode(), timestamp=timestamp)


class FixtureKafkaConsumer:
    messages = {
        0: [message(0, 0, {"asset_id": "KAFKA-1"}, 1000), message(0, 1, {"asset_id": "KAFKA-2"}, 1002)],
        1: [message(1, 0, {"asset_id": "KAFKA-3"}, 1001), message(1, 1, None, 1003)],
    }
    options = []

    def __init__(self, **options):
        self.options.append(options)
        if options.get("client_id") == "failing-kafka":
            raise KafkaConnectionError("fixture broker unavailable")
        self.positions = {}
        self.assigned = []

    def partitions_for_topic(self, _topic):
        return set(self.messages)

    def assign(self, partitions):
        self.assigned = list(partitions)

    def seek(self, partition, offset):
        self.positions[partition.partition] = offset

    def seek_to_beginning(self, partition):
        self.positions[partition.partition] = 0

    def seek_to_end(self, partition):
        rows = self.messages.get(partition.partition, [])
        self.positions[partition.partition] = rows[-1].offset + 1 if rows else 0

    def poll(self, timeout_ms, max_records):
        del timeout_ms
        result = {}
        remaining = max_records
        for partition in self.assigned:
            start = self.positions.get(partition.partition, 0)
            rows = [row for row in self.messages.get(partition.partition, []) if row.offset >= start][:remaining]
            if rows:
                result[partition] = rows
                remaining -= len(rows)
            if remaining <= 0:
                break
        return result

    def close(self, autocommit=False):
        assert autocommit is False


connector_runtime.KafkaConsumer = FixtureKafkaConsumer
client = TestClient(app)
passed = 0


def ok(response, label, expect=200):
    global passed
    assert response.status_code == expect, f"{label}: {response.status_code} {response.text[:1600]}"
    passed += 1
    return response.json() if response.content else {}


with SessionLocal() as db:
    db.add(models.DataAsset(
        id="kafka_target", display_name="Kafka Target", description=None, kind="dataset",
        asset_schema={}, records=[], file_ref=None, source_format=None, created_at=1, updated_at=1,
    ))
    db.commit()

catalog = ok(client.get("/connectors/adapters"), "connector catalog")
kafka_catalog = next(row for row in catalog["adapters"] if row["id"] == "kafka")
assert kafka_catalog["available"] is True and kafka_catalog["config_schema"]["incremental_cursor"] == "partition_next_offsets"

source_config = {
    "bootstrap_servers": "127.0.0.1:9092", "topic": "asset-events", "security_protocol": "PLAINTEXT",
    "execution_mode": "live", "max_records": 10, "poll_timeout_ms": 100, "auto_offset_reset": "earliest",
}
ok(client.post("/connections/sources", json={
    "id": "live_kafka", "display_name": "Live Kafka", "source_type": "kafka", "config": source_config,
}), "create Kafka source")
preview = ok(client.post("/connections/sources/live_kafka/live-preview", json={"limit": 10}), "preview Kafka messages")
assert [row["asset_id"] for row in preview["preview_rows"]] == ["KAFKA-1", "KAFKA-3", "KAFKA-2"]
assert preview["next_cursor"] == {"0": 2, "1": 2} and preview["metadata"]["tombstones"] == 1

ok(client.post("/connections/sources/live_kafka/syncs", json={
    "id": "live_kafka_sync", "target_asset_id": "kafka_target", "mode": "incremental",
}), "create connector-managed Kafka sync")
first = ok(client.post("/ingestion/syncs/live_kafka_sync/enqueue", json={"idempotency_key": "kafka-1"}), "enqueue first Kafka sync", 202)
first_run = ok(client.post("/ingestion/workers/run-next", json={"job_id": first["job"]["id"], "worker_id": "kafka-worker"}), "execute first Kafka sync")
assert first_run["run"]["records_out"] == 3 and first_run["run"]["metrics"]["next_cursor"] == {"0": 2, "1": 2}
cursor = ok(client.get("/connections/syncs/live_kafka_sync/cursor"), "inspect partition cursor")
assert cursor["cursor_field"] == "__connector_cursor" and cursor["last_value"] == {"0": 2, "1": 2}

FixtureKafkaConsumer.messages[0].append(message(0, 2, {"asset_id": "KAFKA-4"}, 1004))
FixtureKafkaConsumer.messages[1].append(message(1, 2, {"asset_id": "KAFKA-5"}, 1005))
second = ok(client.post("/ingestion/syncs/live_kafka_sync/enqueue", json={"idempotency_key": "kafka-2"}), "enqueue second Kafka sync", 202)
second_run = ok(client.post("/ingestion/workers/run-next", json={"job_id": second["job"]["id"], "worker_id": "kafka-worker"}), "resume Kafka offsets")
assert second_run["run"]["records_out"] == 2 and second_run["run"]["metrics"]["previous_cursor"] == {"0": 2, "1": 2}
assert second_run["run"]["metrics"]["next_cursor"] == {"0": 3, "1": 3}
with SessionLocal() as db:
    target = db.get(models.DataAsset, "kafka_target")
    assert [row["asset_id"] for row in target.records] == ["KAFKA-1", "KAFKA-3", "KAFKA-2", "KAFKA-4", "KAFKA-5"]
passed += 1

ok(client.post("/connections/sources", json={
    "id": "sasl_kafka", "display_name": "SASL Kafka", "source_type": "kafka",
    "config": {**source_config, "security_protocol": "SASL_SSL", "sasl_mechanism": "PLAIN"},
}), "create SASL Kafka source")
ok(client.post("/connections/sources/sasl_kafka/runtime-credentials", json={
    "credential_type": "kafka_sasl_plain", "secret": "broker-password", "metadata": {},
}), "reject SASL credential without username", 422)
sasl_credential = ok(client.post("/connections/sources/sasl_kafka/runtime-credentials", json={
    "credential_type": "kafka_sasl_plain", "secret": "broker-password", "metadata": {"username": "broker-user"},
}), "store SASL credential", 201)
assert "secret" not in sasl_credential and sasl_credential["metadata"] == {"username": "broker-user"}
ok(client.post("/connections/sources/sasl_kafka/live-preview", json={"limit": 2}), "preview SASL Kafka")
assert FixtureKafkaConsumer.options[-1]["sasl_plain_password"] == "broker-password"

os.environ["APP_ENV"] = "production"
os.environ.pop("CONNECTOR_KAFKA_ALLOW_PLAINTEXT", None)
ok(client.post("/connections/sources/live_kafka/live-preview", json={"limit": 1}), "deny plaintext Kafka in production", 422)
os.environ["APP_ENV"] = "test"

ok(client.post("/connections/sources", json={
    "id": "failing_kafka", "display_name": "Failing Kafka", "source_type": "kafka",
    "config": {**source_config, "client_id": "failing-kafka"},
}), "create failing Kafka source")
ok(client.post("/connections/sources/failing_kafka/syncs", json={
    "id": "failing_kafka_sync", "target_asset_id": "kafka_target", "mode": "incremental",
}), "create failing Kafka sync")
failed = ok(client.post("/ingestion/syncs/failing_kafka_sync/enqueue", json={"idempotency_key": "kafka-fail", "max_attempts": 2}), "enqueue failing Kafka sync", 202)
failed_run = ok(client.post("/ingestion/workers/run-next", json={"job_id": failed["job"]["id"], "worker_id": "kafka-worker"}), "capture retryable Kafka failure")
assert failed_run["job"]["status"] == "QUEUED" and failed_run["run"]["status"] == "RETRYING"

attempts = ok(client.get("/connections/sources/live_kafka/fetch-attempts"), "inspect Kafka fetch evidence")
assert len(attempts) == 4 and [row["status"] for row in attempts].count("FAILED") == 1
assert all("broker-password" not in json.dumps(row) for row in attempts)
snapshot = ok(client.get("/project/export"), "export Kafka snapshot")
assert "connector_credentials" not in snapshot and "broker-password" not in json.dumps(snapshot)

print(f"Kafka connector runtime verified: {passed} assertions passed.")
engine.dispose()
tmpdir.cleanup()

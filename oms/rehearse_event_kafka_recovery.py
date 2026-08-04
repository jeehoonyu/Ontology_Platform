"""Three-stage real-broker interruption and recovery rehearsal.

Run `prepare` while Kafka is healthy, `interrupt` while it is stopped, then
`recover` after restart. State is isolated under a caller-provided directory.
"""

import argparse
import json
import os
from pathlib import Path
import time
import uuid


parser = argparse.ArgumentParser()
parser.add_argument("stage", choices=("prepare", "interrupt", "recover", "cleanup"))
parser.add_argument("--state-dir", default=os.getenv("EVENT_KAFKA_REHEARSAL_STATE", ".event-kafka-recovery"))
args = parser.parse_args()
state_dir = Path(args.state_dir).resolve()
state_file = state_dir / "state.json"
database_file = state_dir / "runtime.db"

if args.stage == "cleanup":
    if state_file.exists():
        state_file.unlink()
    if database_file.exists():
        database_file.unlink()
    if state_dir.exists():
        state_dir.rmdir()
    print("Kafka recovery rehearsal state removed.")
    raise SystemExit(0)

state_dir.mkdir(parents=True, exist_ok=True)
run_id = state_file.stem
if state_file.exists():
    persisted = json.loads(state_file.read_text(encoding="utf-8"))
    run_id = persisted["run_id"]
else:
    persisted = {}
    run_id = uuid.uuid4().hex[:12]

os.environ["DATABASE_URL"] = f"sqlite:///{database_file.as_posix()}"
os.environ["AUTH_MODE"] = "local"
os.environ["APP_ENV"] = "test"
os.environ["EVENT_KAFKA_BOOTSTRAP_SERVERS"] = os.getenv("EVENT_KAFKA_BOOTSTRAP_SERVERS", "127.0.0.1:9092")
os.environ["EVENT_KAFKA_SECURITY_PROTOCOL"] = os.getenv("EVENT_KAFKA_SECURITY_PROTOCOL", "PLAINTEXT")
os.environ["EVENT_KAFKA_TOPIC_PREFIX"] = f"ontologyos.recovery.{run_id}"
os.environ["EVENT_KAFKA_REQUEST_TIMEOUT_MS"] = "3000"
os.environ["EVENT_KAFKA_MAX_BLOCK_MS"] = "3000"

from fastapi.testclient import TestClient  # noqa: E402
from app.database import SessionLocal, engine  # noqa: E402
from app.event_outbox import EventOutbox, EventTransportReceipt  # noqa: E402
from app.main import app  # noqa: E402
from app.runtime import create_audit_log  # noqa: E402


client = TestClient(app)

if args.stage == "prepare":
    assert not persisted, "Recovery state already exists; run cleanup before prepare"
    with SessionLocal() as db:
        create_audit_log(
            db, actor="kafka-recovery", event_type="rehearsal.kafka.interruption",
            subject_type="rehearsal", subject_id=run_id,
            payload={"project_id": "default", "run_id": run_id},
        )
        db.commit()
        outbox = db.query(EventOutbox).filter(EventOutbox.event_type == "rehearsal.kafka.interruption").one()
        outbox_id = outbox.id
    response = client.post("/api/v1/outbox/workers/run-next", json={
        "worker_id": "recovery-internal", "event_id": outbox_id,
    })
    assert response.status_code == 200 and response.json()["outbox"]["status"] == "PUBLISHED", response.text
    state_file.write_text(json.dumps({"run_id": run_id, "outbox_id": outbox_id}, indent=2), encoding="utf-8")
    print(f"Prepared published event {outbox_id}; stop Kafka before the interrupt stage.")

elif args.stage == "interrupt":
    assert persisted.get("outbox_id"), "Run prepare first"
    response = client.post("/api/v1/outbox/kafka/workers/run-next", json={
        "worker_id": "recovery-interrupted", "event_id": persisted["outbox_id"],
    })
    assert response.status_code == 200, response.text
    delivery = response.json()["delivery"]
    assert response.json().get("failed") is True and delivery["status"] == "RETRY", response.text
    persisted["receipt_id"] = delivery["id"]
    persisted["failed_attempts"] = delivery["attempts"]
    state_file.write_text(json.dumps(persisted, indent=2), encoding="utf-8")
    print(f"Broker interruption persisted RETRY receipt {delivery['id']}; restart Kafka before recover.")

else:
    assert persisted.get("receipt_id"), "Run prepare and interrupt first"
    replay = client.post(
        f"/api/v1/outbox/transport-receipts/{persisted['receipt_id']}/replay",
        json={"reset_attempts": False},
    )
    assert replay.status_code == 200, replay.text
    response = client.post("/api/v1/outbox/kafka/workers/run-next", json={
        "worker_id": "recovery-restored", "event_id": persisted["outbox_id"],
    })
    assert response.status_code == 200, response.text
    delivery = response.json()["delivery"]
    assert delivery["status"] == "DELIVERED", response.text
    assert delivery["attempts"] == persisted["failed_attempts"] + 1
    with SessionLocal() as db:
        receipt = db.get(EventTransportReceipt, persisted["receipt_id"])
        assert receipt.status == "DELIVERED" and receipt.broker_metadata.get("event_id")
    print(
        f"Kafka recovery passed: receipt={delivery['id']} attempts={delivery['attempts']} "
        f"partition={delivery['broker_metadata']['partition']} offset={delivery['broker_metadata']['offset']}"
    )

engine.dispose()

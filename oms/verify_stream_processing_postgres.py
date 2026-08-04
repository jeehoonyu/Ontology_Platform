"""Rehearse concurrent stream ordering and processor fencing on PostgreSQL."""

import os
import uuid
from concurrent.futures import ThreadPoolExecutor


if not os.environ.get("DATABASE_URL", "").startswith("postgresql"):
    raise SystemExit("verify_stream_processing_postgres.py requires a PostgreSQL DATABASE_URL")
os.environ["SKIP_CREATE_ALL"] = "1"
os.environ.setdefault("AUTH_MODE", "local")
os.environ.setdefault("APP_ENV", "test")

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import inspect  # noqa: E402
from app.database import SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.stream_processing import StreamProcessingReceipt  # noqa: E402
from app.streaming import Stream, StreamRecord  # noqa: E402


prefix = f"pg_stream_{uuid.uuid4().hex[:8]}"
stream_id = f"{prefix}_input"
processor_id = f"{prefix}_processor"


def checked(response, expected=200):
    assert response.status_code == expected, f"{response.status_code}: {response.text[:2000]}"
    return response.json() if response.content else {}


with TestClient(app) as client:
    checked(client.post("/streams", json={
        "id": stream_id, "project_id": "default", "display_name": "PostgreSQL ordered stream",
        "schema": {"event_ts": "number", "partition": "string"},
    }))


def publish(batch_number):
    with TestClient(app) as thread_client:
        return checked(thread_client.post(f"/streams/{stream_id}/publish", json={"records": [
            {"event_ts": batch_number * 10 + offset, "partition": "A", "batch": batch_number, "offset": offset}
            for offset in range(10)
        ]}))


with ThreadPoolExecutor(max_workers=10) as pool:
    publish_results = list(pool.map(publish, range(10)))
assert sum(row["published"] for row in publish_results) == 100

with SessionLocal() as db:
    stream = db.get(Stream, stream_id)
    sequences = [row.sequence for row in db.query(StreamRecord).filter(
        StreamRecord.stream_id == stream_id
    ).order_by(StreamRecord.sequence).all()]
    assert stream.next_sequence == 100
    assert sequences == list(range(1, 101)), sequences

with TestClient(app) as client:
    checked(client.post("/api/v1/streams/processors", json={
        "id": processor_id, "project_id": "default", "stream_id": stream_id,
        "display_name": "PostgreSQL processor", "timestamp_field": "event_ts",
        "partition_key_field": "partition", "allowed_lateness_seconds": 1000,
        "max_batch_records": 100, "max_backlog_records": 1000,
    }), 201)


def process(worker_number):
    with TestClient(app) as thread_client:
        return checked(thread_client.post(
            f"/api/v1/streams/processors/{processor_id}/process", json={"max_records": 100},
            headers={"X-Actor": f"postgres-stream-worker-{worker_number}"},
        ))


with ThreadPoolExecutor(max_workers=2) as pool:
    processing_results = list(pool.map(process, range(2)))
assert sorted(row["records_processed"] for row in processing_results) == [0, 100], processing_results
with SessionLocal() as db:
    receipts = db.query(StreamProcessingReceipt).filter(
        StreamProcessingReceipt.processor_id == processor_id
    ).all()
    assert len(receipts) == 100
    assert len({row.record_id for row in receipts}) == 100

indexes = {row["name"]: row for row in inspect(engine).get_indexes("stream_records")}
assert indexes["uq_stream_record_sequence"]["unique"] is True

print("PostgreSQL stream sequence allocation and processor fencing rehearsal passed.")
engine.dispose()

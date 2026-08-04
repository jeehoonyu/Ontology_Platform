"""Rehearse concurrent two-stream interval processing on PostgreSQL."""

import os
import uuid
from concurrent.futures import ThreadPoolExecutor


if not os.environ.get("DATABASE_URL", "").startswith("postgresql"):
    raise SystemExit("verify_cross_stream_join_postgres.py requires a PostgreSQL DATABASE_URL")
os.environ["SKIP_CREATE_ALL"] = "1"
os.environ.setdefault("AUTH_MODE", "local")
os.environ.setdefault("APP_ENV", "test")

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import inspect  # noqa: E402
from app.database import SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.models import DataAsset  # noqa: E402
from app.stream_processing import StreamJoinInput, StreamJoinReceipt, StreamProcessingReceipt  # noqa: E402


prefix = f"pg_join_{uuid.uuid4().hex[:8]}"
left_stream = f"{prefix}_left"
right_stream = f"{prefix}_right"
processor_id = f"{prefix}_processor"
output_id = f"{prefix}_output"


def checked(response, expected=200):
    assert response.status_code == expected, f"{response.status_code}: {response.text[:2000]}"
    return response.json() if response.content else {}


with TestClient(app) as client:
    checked(client.post("/data-assets", json={
        "id": output_id, "project_id": "default", "display_name": "PostgreSQL join output",
        "kind": "dataset", "asset_schema": {}, "records": [],
    }))
    for stream_id in (left_stream, right_stream):
        checked(client.post("/streams", json={
            "id": stream_id, "project_id": "default", "display_name": stream_id,
            "schema": {"event_ts": "number", "asset_id": "string"},
        }))
    checked(client.post("/api/v1/streams/processors", json={
        "id": processor_id, "project_id": "default", "stream_id": left_stream,
        "join_stream_id": right_stream, "display_name": "PostgreSQL interval join",
        "timestamp_field": "event_ts", "join_left_key": "asset_id",
        "join_right_key": "asset_id", "join_time_tolerance_seconds": 5,
        "target_asset_id": output_id, "max_batch_records": 100,
        "max_backlog_records": 1000,
    }), 201)
    checked(client.post(f"/streams/{left_stream}/publish", json={"records": [
        {"event_ts": 1000 + offset * 10, "asset_id": f"asset-{offset:03d}", "signal": offset}
        for offset in range(50)
    ]}))
    checked(client.post(f"/streams/{right_stream}/publish", json={"records": [
        {"event_ts": 1002 + offset * 10, "asset_id": f"asset-{offset:03d}", "work_order": offset}
        for offset in range(50)
    ]}))


def process(worker_number):
    with TestClient(app) as thread_client:
        return checked(thread_client.post(
            f"/api/v1/streams/processors/{processor_id}/process",
            json={"max_records": 100},
            headers={"X-Actor": f"postgres-join-worker-{worker_number}"},
        ))


with ThreadPoolExecutor(max_workers=2) as pool:
    results = list(pool.map(process, range(2)))
assert sorted(row["records_processed"] for row in results) == [0, 100], results
assert sorted(row["joins_emitted"] for row in results) == [0, 50], results

with SessionLocal() as db:
    assert db.query(StreamProcessingReceipt).filter(
        StreamProcessingReceipt.processor_id == processor_id,
    ).count() == 100
    assert db.query(StreamJoinInput).filter(StreamJoinInput.processor_id == processor_id).count() == 100
    receipts = db.query(StreamJoinReceipt).filter(StreamJoinReceipt.processor_id == processor_id).all()
    assert len(receipts) == 50
    assert len({(row.left_record_id, row.right_record_id) for row in receipts}) == 50
    output = db.get(DataAsset, output_id)
    assert len(output.records) == 50
    assert len({row["_stream_join_id"] for row in output.records}) == 50

indexes = {row["name"] for row in inspect(engine).get_indexes("stream_join_inputs")}
assert "ix_stream_join_inputs_match" in indexes

print("PostgreSQL concurrent cross-stream interval join rehearsal passed.")
engine.dispose()

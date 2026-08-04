"""Rehearse concurrent durable-event routing into project streams on PostgreSQL."""

import os
import time
import uuid
from concurrent.futures import ThreadPoolExecutor


if not os.environ.get("DATABASE_URL", "").startswith("postgresql"):
    raise SystemExit("verify_event_stream_routing_postgres.py requires a PostgreSQL DATABASE_URL")
os.environ["SKIP_CREATE_ALL"] = "1"
os.environ.setdefault("AUTH_MODE", "local")
os.environ.setdefault("APP_ENV", "test")

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import func  # noqa: E402
from app.database import SessionLocal, engine  # noqa: E402
from app.event_outbox import EventOutbox, EventStreamReceipt, PlatformEventLog  # noqa: E402
from app.main import app  # noqa: E402
from app.streaming import Stream, StreamRecord  # noqa: E402


prefix = f"pg_event_route_{uuid.uuid4().hex[:8]}"
stream_id = f"{prefix}_stream"
binding_id = f"{prefix}_binding"
topic = f"ontologyos.acceptance.{prefix}"
now = int(time.time())


def checked(response, expected=200):
    assert response.status_code == expected, f"{response.status_code}: {response.text[:2000]}"
    return response.json() if response.content else {}


with SessionLocal() as db:
    start_sequence = db.query(func.max(PlatformEventLog.sequence)).scalar() or 0

with TestClient(app) as client:
    checked(client.post("/streams", json={
        "id": stream_id,
        "project_id": "default",
        "display_name": "PostgreSQL event-routing acceptance",
        "schema": {"event_id": "string", "event_type": "string", "payload": "object"},
        "max_backlog_records": 1000,
    }))
    checked(client.post("/api/v1/event-stream-bindings", json={
        "id": binding_id,
        "project_id": "default",
        "display_name": f"PostgreSQL routing {prefix}",
        "target_stream_id": stream_id,
        "topics": [topic],
        "start_sequence": start_sequence,
    }), 201)

with SessionLocal() as db:
    for offset in range(100):
        outbox_id = f"{prefix}_outbox_{offset:03d}"
        event_id = f"{prefix}_event_{offset:03d}"
        payload = {"offset": offset, "object_type_id": "asset"}
        db.add(EventOutbox(
            id=outbox_id, project_id="default", topic=topic,
            event_type="ontology.object.changed", aggregate_type="object",
            aggregate_id=f"asset-{offset:03d}", actor="postgres-acceptance",
            payload=payload, headers={}, idempotency_key=event_id,
            status="PUBLISHED", attempts=1, max_attempts=5,
            available_at=now, created_at=now, updated_at=now, published_at=now,
        ))
        db.add(PlatformEventLog(
            event_id=event_id, outbox_event_id=outbox_id, project_id="default",
            topic=topic, event_type="ontology.object.changed", aggregate_type="object",
            aggregate_id=f"asset-{offset:03d}", actor="postgres-acceptance",
            payload=payload, headers={}, occurred_at=now, published_at=now,
        ))
    db.commit()


def route(worker_number):
    with TestClient(app) as thread_client:
        return checked(thread_client.post(
            f"/api/v1/event-stream-bindings/{binding_id}/route",
            json={"max_events": 1000},
            headers={"X-Actor": f"postgres-event-router-{worker_number}"},
        ))


with ThreadPoolExecutor(max_workers=2) as pool:
    route_results = list(pool.map(route, range(2)))
assert sorted(row["routed"] for row in route_results) == [0, 100], route_results

with SessionLocal() as db:
    stream = db.get(Stream, stream_id)
    records = db.query(StreamRecord).filter(
        StreamRecord.stream_id == stream_id,
    ).order_by(StreamRecord.sequence).all()
    receipts = db.query(EventStreamReceipt).filter(
        EventStreamReceipt.binding_id == binding_id,
    ).order_by(EventStreamReceipt.event_sequence).all()
    assert stream.next_sequence == 100
    assert [row.sequence for row in records] == list(range(1, 101))
    assert len(receipts) == 100
    assert len({row.event_id for row in receipts}) == 100
    assert len({row.stream_record_id for row in receipts}) == 100
    assert {row.id for row in records} == {row.stream_record_id for row in receipts}

print("PostgreSQL concurrent event-to-stream routing rehearsal passed.")
engine.dispose()

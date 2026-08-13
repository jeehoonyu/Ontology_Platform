"""Transactional outbox atomicity, leasing, retry, DLQ, and idempotency."""

import asyncio
import os
import tempfile
import time
import uuid


tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tmpdir.name, 'event_outbox.db')}"
os.environ["AUTH_MODE"] = "local"
os.environ["APP_ENV"] = "test"

from fastapi.testclient import TestClient  # noqa: E402
from app.database import SessionLocal, engine  # noqa: E402
from app.event_outbox import EventOutbox, PlatformEventLog, stream_event_log  # noqa: E402
from app.main import app  # noqa: E402
from app.ops_control import OpsEvent  # noqa: E402
from app.production_auth import Principal  # noqa: E402
from app.runtime import create_audit_log  # noqa: E402


client = TestClient(app)


def checked(response, expected=200):
    assert response.status_code == expected, f"{response.status_code}: {response.text[:2000]}"
    return response.json() if response.content else {}


def create_evidence(event_type: str) -> EventOutbox:
    audit_id = uuid.uuid4().hex
    with SessionLocal() as db:
        create_audit_log(
            db, actor="outbox-test", event_type=event_type,
            subject_type="outbox_probe", subject_id=audit_id,
            payload={"project_id": "default", "probe": audit_id},
        )
        db.commit()
        row = db.query(EventOutbox).filter(EventOutbox.event_type == event_type).one()
        db.expunge(row)
        return row


# Audit evidence and outbox intent share one transaction and both disappear on rollback.
rollback_id = uuid.uuid4().hex
with SessionLocal() as db:
    create_audit_log(
        db, actor="rollback-test", event_type="outbox.rollback.probe",
        subject_type="probe", subject_id=rollback_id,
        payload={"project_id": "default"},
    )
    db.flush()
    assert db.query(EventOutbox).filter(EventOutbox.event_type == "outbox.rollback.probe").count() == 1
    db.rollback()
with SessionLocal() as db:
    assert db.query(EventOutbox).filter(EventOutbox.event_type == "outbox.rollback.probe").count() == 0

# Existing endpoint code emits audit evidence; the session invariant captures it without endpoint changes.
checked(client.post("/object-types", json={
    "id": "outbox_asset", "project_id": "default", "display_name": "Outbox Asset",
    "properties": {"assetId": {"type": "string"}},
}))
events = checked(client.get("/api/v1/outbox/events?project_id=default&status=PENDING"))
assert events["count"] >= 1
captured = next(row for row in events["events"] if row["event_type"] == "ontology.object_type.created")
assert captured["payload"]["evidence_source"] == "audit"

with SessionLocal() as db:
    db.add(OpsEvent(
        id=f"ops_{uuid.uuid4().hex}", project_id="default", source="outbox-test",
        event_type="outbox.ops.probe", severity="info", status="OPEN",
        title="Outbox ops probe", subject_type="probe", subject_id="ops-probe",
        payload={"project_id": "default"}, created_at=int(time.time()),
    ))
    db.commit()
    ops_outbox = db.query(EventOutbox).filter(EventOutbox.event_type == "outbox.ops.probe").one()
    assert ops_outbox.topic == "ontologyos.ops" and ops_outbox.payload["evidence_source"] == "ops"

# A failed dispatch persists its claim attempt, rolls back publication, and becomes retryable.
failure = checked(client.post("/api/v1/outbox/workers/run-next", json={
    "worker_id": "dispatcher-a", "event_id": captured["id"], "inject_failure": "after_publish",
}))
assert failure["failed"] is True and failure["outbox"]["status"] == "RETRY" and failure["outbox"]["attempts"] == 1
with SessionLocal() as db:
    assert db.query(PlatformEventLog).filter(PlatformEventLog.outbox_event_id == captured["id"]).count() == 0

checked(client.post(f"/api/v1/outbox/events/{captured['id']}/replay", json={"reset_attempts": False}))
published = checked(client.post("/api/v1/outbox/workers/run-next", json={
    "worker_id": "dispatcher-a", "event_id": captured["id"],
}))
assert published["outbox"]["status"] == "PUBLISHED" and published["event"]["outbox_event_id"] == captured["id"]

# Replaying an already published event is idempotent: one durable log record remains.
checked(client.post(f"/api/v1/outbox/events/{captured['id']}/replay", json={"reset_attempts": True}))
checked(client.post("/api/v1/outbox/workers/run-next", json={"worker_id": "dispatcher-b", "event_id": captured["id"]}))
with SessionLocal() as db:
    assert db.query(PlatformEventLog).filter(PlatformEventLog.outbox_event_id == captured["id"]).count() == 1

# Expired worker leases are reclaimable.
expired = create_evidence("outbox.expired_lease.probe")
with SessionLocal() as db:
    row = db.get(EventOutbox, expired.id)
    row.status = "IN_FLIGHT"
    row.lease_owner = "dead-worker"
    row.lease_token = uuid.uuid4().hex
    row.lease_expires_at = int(time.time()) - 1
    db.commit()
recovered = checked(client.post("/api/v1/outbox/workers/run-next", json={
    "worker_id": "recovery-worker", "event_id": expired.id,
}))
assert recovered["outbox"]["status"] == "PUBLISHED" and recovered["outbox"]["attempts"] == 1

# Repeated delivery failures enter the dead-letter state and can be explicitly replayed.
dead = create_evidence("outbox.dead_letter.probe")
latest = None
for attempt in range(5):
    latest = checked(client.post("/api/v1/outbox/workers/run-next", json={
        "worker_id": "failing-worker", "event_id": dead.id, "inject_failure": "before_publish",
    }))
    if attempt < 4:
        assert latest["outbox"]["status"] == "RETRY"
        checked(client.post(f"/api/v1/outbox/events/{dead.id}/replay", json={"reset_attempts": False}))
assert latest["outbox"]["status"] == "DEAD_LETTER" and latest["outbox"]["attempts"] == 5
summary = checked(client.get("/api/v1/outbox/summary?project_id=default"))
assert summary["dead_letter"] == 1 and summary["latest_sequence"] >= 2

log = checked(client.get("/api/v1/events/log?project_id=default&after_sequence=0"))
assert log["count"] >= 2 and log["next_sequence"] == log["events"][-1]["sequence"]
sse = stream_event_log(
    project_id="default", after_sequence=0, last_event_id=None,
    principal=Principal(
        id="event-reader", display_name="Event reader", email=None, roles=["viewer"],
        permissions=["view"], project_ids=["default"],
    ),
)
first_chunk = asyncio.run(anext(sse.body_iterator))
assert first_chunk.startswith("id: ") and "\nevent: " in first_chunk and "\ndata: " in first_chunk

print("Transactional event outbox runtime verified.")
engine.dispose()
tmpdir.cleanup()

"""Ontology object changes commit and dispatch as idempotent domain events."""
import os
import tempfile


temporary = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(temporary.name, 'object-change-outbox.db')}"
os.environ["AUTH_MODE"] = "local"
os.environ["APP_ENV"] = "test"

from fastapi.testclient import TestClient  # noqa: E402
from app import event_outbox, models, ontology_runtime_v1  # noqa: E402
from app.database import SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402


client = TestClient(app)
passed = 0


def check(response, label, expected=200):
    global passed
    assert response.status_code == expected, f"{label}: {response.status_code} {response.text[:1800]}"
    passed += 1
    return response.json() if response.content else {}


check(client.post("/object-types", json={
    "id": "streamed_asset", "project_id": "default", "display_name": "Streamed Asset",
    "properties": {"asset_id": {"type": "string"}, "status": {"type": "string"}},
}), "object type")
check(client.post("/objects", json={
    "id": "streamed-asset-1", "project_id": "default", "object_type_id": "streamed_asset",
    "properties": {"asset_id": "streamed-asset-1", "status": "RUNNING"},
}), "object")

with SessionLocal() as db:
    temporal = db.query(ontology_runtime_v1.ObjectChangeEvent).filter(
        ontology_runtime_v1.ObjectChangeEvent.object_id == "streamed-asset-1",
    ).one()
    domain = db.query(event_outbox.EventOutbox).filter(
        event_outbox.EventOutbox.topic == "ontologyos.object_change",
        event_outbox.EventOutbox.aggregate_id == "streamed-asset-1",
    ).one()
    audit = db.query(event_outbox.EventOutbox).filter(
        event_outbox.EventOutbox.topic == "ontologyos.audit",
        event_outbox.EventOutbox.aggregate_id == "streamed-asset-1",
    ).one()
    assert domain.event_type == "ontology.object.created"
    assert domain.idempotency_key == f"object_change:{temporal.id}"
    assert domain.payload["evidence_id"] == temporal.id
    assert domain.payload["object_version"] == 1
    assert domain.payload["after_state"]["status"] == "RUNNING"
    assert domain.payload["materialization"] == {"id": None, "active": True, "retired_at": None}
    assert audit.id != domain.id
    domain_id = domain.id
    passed += 7

# Temporal evidence and delivery intent share the same rollback boundary.
with SessionLocal() as db:
    obj = db.get(models.ObjectInstance, "streamed-asset-1")
    before = dict(obj.properties)
    obj.properties = {**before, "status": "DEGRADED"}
    obj.updated_at += 1
    change = ontology_runtime_v1.record_object_change(
        db, obj, before_state=before, event_type="ontology.object.updated",
        actor="rollback-test", source_type="test", source_id="rollback",
    )
    db.flush()
    assert db.query(event_outbox.EventOutbox).filter(
        event_outbox.EventOutbox.idempotency_key == f"object_change:{change.id}",
    ).count() == 1
    rollback_change_id = change.id
    db.rollback()
with SessionLocal() as db:
    assert db.get(ontology_runtime_v1.ObjectChangeEvent, rollback_change_id) is None
    assert db.query(event_outbox.EventOutbox).filter(
        event_outbox.EventOutbox.idempotency_key == f"object_change:{rollback_change_id}",
    ).count() == 0
    assert db.get(models.ObjectInstance, "streamed-asset-1").properties["status"] == "RUNNING"
    passed += 4

# The public enqueue primitive is idempotent inside and across flushes.
with SessionLocal() as db:
    first = event_outbox.enqueue_domain_event(
        db, project_id="default", topic="ontologyos.object_change",
        event_type="ontology.object.probe", aggregate_type="ontology_object",
        aggregate_id="probe", actor="test", payload={"probe": True},
        idempotency_key="object_change:stable-probe",
    )
    second = event_outbox.enqueue_domain_event(
        db, project_id="default", topic="ontologyos.object_change",
        event_type="ontology.object.probe", aggregate_type="ontology_object",
        aggregate_id="probe", actor="test", payload={"probe": True},
        idempotency_key="object_change:stable-probe",
    )
    assert first.id == second.id
    stable_probe_id = first.id
    db.commit()
with SessionLocal() as db:
    third = event_outbox.enqueue_domain_event(
        db, project_id="default", topic="ontologyos.object_change",
        event_type="ontology.object.probe", aggregate_type="ontology_object",
        aggregate_id="probe", actor="test", payload={"probe": True},
        idempotency_key="object_change:stable-probe",
    )
    assert third.id == stable_probe_id
    assert db.query(event_outbox.EventOutbox).filter(
        event_outbox.EventOutbox.idempotency_key == "object_change:stable-probe",
    ).count() == 1
    db.rollback()
    passed += 3

# Failed publication is retryable; replay remains exactly once in the durable log.
failed = check(client.post("/api/v1/outbox/workers/run-next", json={
    "worker_id": "object-change-dispatcher", "event_id": domain_id,
    "inject_failure": "after_publish",
}), "failed dispatch")
assert failed["outbox"]["status"] == "RETRY"
check(client.post(f"/api/v1/outbox/events/{domain_id}/replay", json={"reset_attempts": False}), "replay")
published = check(client.post("/api/v1/outbox/workers/run-next", json={
    "worker_id": "object-change-dispatcher", "event_id": domain_id,
}), "dispatch")
assert published["event"]["topic"] == "ontologyos.object_change"
assert published["event"]["aggregate_id"] == "streamed-asset-1"
check(client.post(f"/api/v1/outbox/events/{domain_id}/replay", json={"reset_attempts": True}), "published replay")
check(client.post("/api/v1/outbox/workers/run-next", json={
    "worker_id": "object-change-dispatcher-2", "event_id": domain_id,
}), "idempotent redispatch")
with SessionLocal() as db:
    assert db.query(event_outbox.PlatformEventLog).filter(
        event_outbox.PlatformEventLog.outbox_event_id == domain_id,
    ).count() == 1
    passed += 4

print(f"Ontology object-change outbox verified: {passed} assertions passed.")
engine.dispose()
temporary.cleanup()

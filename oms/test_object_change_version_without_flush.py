"""Two changes to one object in one request get versions 1 and 2, unflushed.

`record_object_change` used to call `db.flush()` before asking the database for
`max(object_version)`. The flush was load-bearing -- sessions here are
`autoflush=False`, so a query cannot see rows added earlier in the same request --
and it was the most expensive line in this repository. It runs once per object
written, and a bulk hydrate writes a thousand: `POST /pipeline-builder/workers/run-next`
issued **1,006 separate `INSERT INTO event_outbox` statements**, one per flush,
because the outbox is filled by a `before_flush` hook that fired a thousand times
instead of once, with a transaction held open across all of it.

Flushing was never what the version needed. *Seeing the pending rows* was. So the
pending ones are now counted in the session, and the answer is the greater of that
and the persisted maximum.

This file is the crossed case, and it is the only case where the change could go
wrong. A thousand objects each written once cannot collide -- their maxima are
independent -- so a fixture built from a bulk hydrate would pass against a broken
implementation. Two changes to the *same* object, with no flush between them, is
the thing that has to hold.

The same argument applies to `record_object_snapshot`, which computes `seq` from
a query and never flushed at all. Until now it came out right by accident,
because the change-event flush wrote everything pending, snapshots included.
Removing that flush would have left two snapshots of one object both claiming
seq 1, so it counts pending rows too -- and that is asserted here, because a
latent bug exposed by a performance fix is still a bug the fix caused.
"""
import os
import tempfile

_tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(_tmpdir.name, 'change_version.db')}"
os.environ["AUTH_MODE"] = "local"
os.environ["APP_ENV"] = "test"

from fastapi.testclient import TestClient  # noqa: E402

from app import decision_intelligence, models, ontology_runtime_v1  # noqa: E402
from app.database import SessionLocal  # noqa: E402
from app.main import app  # noqa: E402

client = TestClient(app)
client.get("/health/ready")

passed = 0
PROJECT = "default"

# The object type has to exist: object_instances carries a foreign key to it.
created = client.post("/object-types", json={
    "id": "asset", "api_name": "asset", "display_name": "Asset",
    "primary_key": "id",
    "properties": {"id": {"type": "string"}, "status": {"type": "string"}},
})
assert created.status_code in (200, 201, 409), created.text


def make_object(db, object_id):
    obj = models.ObjectInstance(
        id=object_id, project_id=PROJECT, object_type_id="asset",
        properties={"status": "RUNNING"}, created_at=1, updated_at=1)
    db.add(obj)
    return obj


# --- the crossed case: one object, three changes, no flush between ----------
with SessionLocal() as db:
    obj = make_object(db, "same-object")
    versions = []
    for index, status in enumerate(("DEGRADED", "FAILED", "RUNNING"), start=1):
        before = dict(obj.properties)
        obj.properties = {**before, "status": status}
        obj.updated_at += 1
        change = ontology_runtime_v1.record_object_change(
            db, obj, before_state=before, event_type="ontology.object.updated",
            actor="version-test", source_type="test", source_id=f"step-{index}")
        assert change is not None, "the change event must be recorded"
        versions.append(change.object_version)
    assert versions == [1, 2, 3], (
        f"three changes to one object in one request must be versions 1, 2, 3 -- got "
        f"{versions}. Counting only the persisted maximum gives [1, 1, 1], which is what "
        f"removing the flush would have caused.")
    passed += 2

    # And the numbering survives the flush that ends the request.
    db.flush()
    stored = sorted(
        row.object_version for row in db.query(ontology_runtime_v1.ObjectChangeEvent)
        .filter(ontology_runtime_v1.ObjectChangeEvent.object_id == "same-object").all())
    assert stored == [1, 2, 3], stored
    db.commit()
    passed += 1

# --- and continues correctly in a later request, from the database ----------
with SessionLocal() as db:
    obj = db.get(models.ObjectInstance, "same-object")
    before = dict(obj.properties)
    obj.properties = {**before, "status": "RETIRED"}
    change = ontology_runtime_v1.record_object_change(
        db, obj, before_state=before, event_type="ontology.object.updated",
        actor="version-test", source_type="test", source_id="later")
    assert change.object_version == 4, (
        f"a new request must continue from the persisted maximum, got "
        f"{change.object_version}")
    db.commit()
    passed += 1

# --- distinct objects do not share a counter --------------------------------
with SessionLocal() as db:
    first = make_object(db, "object-a")
    second = make_object(db, "object-b")
    for obj in (first, second):
        before = dict(obj.properties)
        obj.properties = {**before, "status": "DEGRADED"}
        change = ontology_runtime_v1.record_object_change(
            db, obj, before_state=before, event_type="ontology.object.updated",
            actor="version-test", source_type="test", source_id="parallel")
        assert change.object_version == 1, (
            f"{obj.id} is a distinct object and must start at version 1, got "
            f"{change.object_version}")
    db.commit()
    passed += 2

# --- snapshots: the latent bug the flush was hiding -------------------------
with SessionLocal() as db:
    obj = make_object(db, "snapshot-object")
    seqs = []
    for status in ("DEGRADED", "FAILED", "RUNNING"):
        obj.properties = {**obj.properties, "status": status}
        snapshot = decision_intelligence.record_object_snapshot(
            db, obj, event_type="ontology.object.updated", actor="version-test")
        seqs.append(snapshot.seq)
    assert seqs == [1, 2, 3], (
        f"three snapshots of one object in one request must be seq 1, 2, 3 -- got {seqs}. "
        f"This never flushed on its own; it was correct only because the change-event "
        f"recorder flushed everything pending.")
    db.commit()
    passed += 2

with SessionLocal() as db:
    obj = db.get(models.ObjectInstance, "snapshot-object")
    snapshot = decision_intelligence.record_object_snapshot(
        db, obj, event_type="ontology.object.updated", actor="version-test")
    assert snapshot.seq == 4, f"a later request continues from the database, got {snapshot.seq}"
    db.commit()
    passed += 1

client.close()
print(f"Object change versioning without flush verified: {passed} assertions passed "
      f"(three changes to one object number 1, 2, 3; snapshots likewise).")

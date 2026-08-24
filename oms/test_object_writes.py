"""One chokepoint for object writes, and the defect it was built to close.

R3 of GOAL_REPAIR_2026-08-23. Seven modules construct `models.ObjectInstance`
directly. Four validated their properties, five recorded a change event, and the
three that did neither were the same three, which is why one refactor closes three
findings rather than one.

The case that matters most is the third, because nothing could have caught it:

  `validate_object_properties` read `models.ObjectType.properties`. Once an
  `ObjectTypeProfile` exists, property edits are written to the profile and that
  column stops being updated. The two agree at creation and diverge on the first
  edit, so a property added afterwards with `required=true` was never enforced on
  any object -- and a test that added the property and then created a valid object
  would pass, because the schema it was validated against had not moved.

So the assertion below adds a required property the way `ontology_core` does, to
the profile only, and then requires the write to be refused. Against the old
validator it is accepted.

The second assertion is temporal visibility. An object with no change event is not
merely unlogged: `_query_source` in temporal mode resolves from
`object_change_events` and never touches `object_instances`, so as far as every
as-of read is concerned, that object does not exist.

This file is also the suite home for `audit_object_writes`, which is why it
imports and executes it. A check reachable only from a workflow that has never
provisioned a runner is the defect GOAL_2026-08-13 was opened about, and
`audit_check_coverage` fails the build for exactly this.

  python oms/test_object_writes.py
"""
import os
import tempfile

tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
if not os.environ.get("DATABASE_URL"):
    os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tmpdir.name, 'object_writes.db')}"

import io  # noqa: E402
import sys  # noqa: E402
from contextlib import redirect_stdout  # noqa: E402
from pathlib import Path  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))

from fastapi import HTTPException  # noqa: E402

import audit_object_writes  # noqa: E402
from app import models, models_action, object_writes, ontology_core  # noqa: E402
from app.database import SessionLocal, engine  # noqa: E402
from app.ontology_runtime_v1 import ObjectChangeEvent  # noqa: E402
from app.runtime import now_ts, validate_object_properties  # noqa: E402

models.Base.metadata.create_all(bind=engine)
models_action.Base.metadata.create_all(bind=engine)

passed = 0


def check(condition, label, payload=None):
    global passed
    assert condition, f"{label}: {payload}"
    passed += 1


db = SessionLocal()
now = now_ts()

object_type = models.ObjectType(
    id="turbine", display_name="Turbine", description="",
    properties={"serial": {"type": "string", "required": True}},
    project_id="tenant-a", created_at=now, updated_at=now,
)
db.add(object_type)
db.commit()

# --- the chokepoint validates, writes, and records -----------------------------

created = object_writes.create_object(
    db, object_id="turbine-1", object_type_id="turbine", project_id="tenant-a",
    properties={"serial": "A-1"}, actor="tester",
    event_type="ontology.object.created", source_type="test", source_id="turbine-1",
)
db.commit()

check(db.get(models.ObjectInstance, "turbine-1") is not None,
      "the chokepoint writes the row")

events = db.query(ObjectChangeEvent).filter(ObjectChangeEvent.object_id == "turbine-1").all()
check(len(events) == 1, "and records exactly one change event", len(events))
check(events[0].event_type == "ontology.object.created",
      "carrying the event type the caller named", events[0].event_type)
check(events[0].actor == "tester", "and the actor", events[0].actor)
check(events[0].after_state == {"serial": "A-1"},
      "and the state the object landed in", events[0].after_state)

try:
    object_writes.create_object(
        db, object_id="turbine-bad", object_type_id="turbine", project_id="tenant-a",
        properties={}, actor="tester", event_type="ontology.object.created",
        source_type="test",
    )
    refused = False
except HTTPException as error:
    refused = error.status_code == 422
db.rollback()
check(refused, "a write missing a required property is refused with 422")

# --- an update validates, and appends a second event --------------------------

instance = db.get(models.ObjectInstance, "turbine-1")
updated, before = object_writes.update_object(
    db, instance, properties={"serial": "A-2"}, actor="tester",
    event_type="ontology.object.updated", source_type="test",
)
db.commit()
check(before == {"serial": "A-1"}, "an update returns the state it replaced", before)
check(updated.properties == {"serial": "A-2"}, "and applies the change", updated.properties)
events = db.query(ObjectChangeEvent).filter(
    ObjectChangeEvent.object_id == "turbine-1").order_by(ObjectChangeEvent.object_version).all()
check(len(events) == 2, "and appends a second event rather than editing the first", len(events))
check(events[1].before_state == {"serial": "A-1"},
      "which carries the before-state, so the change is reconstructible",
      events[1].before_state)
check("serial" in (events[1].changed_fields or []),
      "and names the field that moved", events[1].changed_fields)

# --- the defect: a property added after creation, to the profile only ---------

profile = ontology_core.ObjectTypeProfile(
    object_type_id="turbine",
    api_name="turbine",
    properties={"serial": {"type": "string", "required": True},
                "site": {"type": "string", "required": True}},
    created_at=now, updated_at=now,
)
db.add(profile)
db.commit()

stale = validate_object_properties(object_type, {"serial": "B-1"})
check(stale == [],
      "reading the object type's own column, the new required property does not exist -- "
      "this is what every write path saw", stale)

live = object_writes.validate(db, object_type, {"serial": "B-1"})
check(live and any("site" in error for error in live),
      "reading the resolved schema, it is missing and named", live)

try:
    object_writes.create_object(
        db, object_id="turbine-2", object_type_id="turbine", project_id="tenant-a",
        properties={"serial": "B-1"}, actor="tester",
        event_type="ontology.object.created", source_type="test",
    )
    refused_after_edit = False
except HTTPException as error:
    refused_after_edit = error.status_code == 422
db.rollback()
check(refused_after_edit,
      "so a write that ignores a property added after creation is now refused; "
      "before this it was accepted")

check(object_writes.resolved_schema(db, object_type).keys() == {"serial", "site"},
      "and the resolved schema is the profile's, with __-prefixed metadata dropped",
      sorted(object_writes.resolved_schema(db, object_type)))

db.close()

# --- the suite home for the ratchet ------------------------------------------

reading = audit_object_writes.read()
check(reading["bypass_sites"] >= 1,
      "the ratchet reads construction sites from the tree", reading["bypass_sites"])
check("object_writes.py" not in reading["modules"],
      "and does not count the chokepoint itself as a bypass", reading["modules"])
check("models.py" not in reading["modules"] and "schemas.py" not in reading["modules"],
      "nor the modules that only declare or name the class", reading["modules"])

argv = sys.argv[:]
sys.argv = ["audit_object_writes"]
try:
    with redirect_stdout(io.StringIO()) as captured:
        code = audit_object_writes.main()
finally:
    sys.argv = argv
check(code == 0, "and the ratchet holds against its recorded ceiling",
      captured.getvalue()[-160:])

print(f"Object write chokepoint verified: {passed} assertions passed "
      f"({reading['bypass_sites']} sites still outside it).")

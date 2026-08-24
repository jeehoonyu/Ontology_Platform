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

# --- null means absent, but only where the type says so ----------------------

null_type = models.ObjectType(
    id="reading", display_name="Reading", description="",
    properties={"sku": {"type": "string"}, "payload": {"type": "json"},
                "count": {"type": "integer"}},
    project_id="tenant-a", created_at=now, updated_at=now)
db2 = SessionLocal()
db2.add(null_type)
db2.commit()
declared = db2.get(models.ObjectType, "reading")
schema = object_writes.resolved_schema(db2, declared)

kept = object_writes.drop_unrepresentable_nulls(
    schema, {"sku": None, "count": None, "payload": None, "other": None})
check("sku" not in kept and "count" not in kept,
      "a None the declared type cannot hold is dropped, because absence is the "
      "ontology's only word for it", kept)
check("payload" in kept and kept["payload"] is None,
      "but a None a `json` property can hold is kept -- the rule is narrow on purpose", kept)
check("other" in kept,
      "and an undeclared property is left exactly as the caller passed it", kept)

written = object_writes.create_object(
    db2, object_id="reading-1", object_type_id="reading", project_id="tenant-a",
    properties={"sku": None, "count": 3}, actor="tester",
    event_type="ontology.object.created", source_type="test")
db2.commit()
check(written.properties == {"count": 3},
      "so a write carrying an unset optional lands without it, rather than as a 422",
      written.properties)

required_type = models.ObjectType(
    id="strict", display_name="Strict", description="",
    properties={"sku": {"type": "string", "required": True}},
    project_id="tenant-a", created_at=now, updated_at=now)
db2.add(required_type)
db2.commit()
try:
    object_writes.create_object(
        db2, object_id="strict-1", object_type_id="strict", project_id="tenant-a",
        properties={"sku": None}, actor="tester",
        event_type="ontology.object.created", source_type="test")
    required_still_enforced = False
except HTTPException as error:
    required_still_enforced = error.status_code == 422
db2.rollback()
check(required_still_enforced,
      "and dropping the null does not weaken `required`: absent is still an error")
db2.close()

# --- a partial schema is not a schema violation -------------------------------

# Compatibility routers and several suite tests build a deliberate subset of the
# tables. Resolving the schema through an unguarded query against
# object_type_profiles raised `no such table` on them, which is the validator
# reporting its own dependency as a defect in the caller. Caught by
# test_automate_action_effect.py, which builds exactly such a subset.
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

partial_path = os.path.join(tmpdir.name, "partial.db")
partial_engine = create_engine(f"sqlite:///{partial_path}")
models.ObjectType.__table__.create(bind=partial_engine)
models.ObjectInstance.__table__.create(bind=partial_engine)
partial_db = sessionmaker(bind=partial_engine)()
partial_db.add(models.ObjectType(
    id="widget", display_name="Widget", description="",
    properties={"sku": {"type": "string", "required": True}, "__manager": {"project_id": "x"}},
    project_id="tenant-a", created_at=now, updated_at=now))
partial_db.commit()

partial_type = partial_db.get(models.ObjectType, "widget")
resolved = object_writes.resolved_schema(partial_db, partial_type)
check(resolved == {"sku": {"type": "string", "required": True}},
      "with no profile table, the object type's own column is the whole schema, "
      "and __-prefixed metadata is still dropped", resolved)
check(object_writes.validate(partial_db, partial_type, {"sku": "W-1"}) == [],
      "so a valid write validates rather than raising `no such table`")
check(object_writes.validate(partial_db, partial_type, {}) != [],
      "and an invalid one is still caught")
partial_db.close()

# --- the suite home for the ratchet ------------------------------------------

reading = audit_object_writes.read()
check(reading["bypass_sites"] == 0,
      "every object write passes the chokepoint -- R3's threshold, 7 of 7",
      reading["sites"])
check("object_writes.py" not in reading["modules"],
      "and the chokepoint itself is not counted as a bypass", reading["modules"])

# A scan that only recognised one spelling could be satisfied by changing the
# import rather than the write, so both forms are asserted directly against the
# detector rather than against whatever the tree currently happens to contain.
import ast  # noqa: E402

for spelling in ("models.ObjectInstance(id='x')", "ObjectInstance(id='x')"):
    node = ast.parse(spelling, mode="eval").body
    check(audit_object_writes._constructs_object_instance(node),
          f"the scan recognises `{spelling}` as a construction")
for benign in ("db.query(models.ObjectInstance)", "isinstance(row, ObjectInstance)",
               "ObjectInstanceCreate(id='x')"):
    node = ast.parse(benign, mode="eval").body
    check(not audit_object_writes._constructs_object_instance(node),
          f"and does not mistake `{benign}` for one")

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

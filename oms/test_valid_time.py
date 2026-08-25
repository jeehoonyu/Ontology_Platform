"""Valid time means something: the two temporal axes can disagree.

R5 of GOAL_REPAIR_2026-08-23. `object_change_events` has carried `valid_from` and
`valid_to` since the table existed, and `_query_source` has filtered on the
half-open interval `valid_from <= t AND (valid_to IS NULL OR valid_to > t)` --
the correct predicate, the whole time. The read side was finished. The write side
was not, in two ways, and together they made bitemporality decorative:

  *No caller ever supplied a business time.* `valid_from=` appeared exactly once
  in the backend, as `record_object_change`'s own default of `now`. So every
  event had `valid_from == transaction_time`, the two axes moved together, and
  `as_of_valid_time` could not answer a question `as_of_transaction_time` did
  not already answer identically.

  *No interval was ever closed.* `valid_to` was written as `None` at the only
  write site and set to a non-NULL value nowhere in the codebase, so the second
  half of the predicate was dead and every version of every object was valid
  forever.

The claim this file makes is the one the README had been making without it: a
correction can say *what was true then*, discovered now, and the two axes then
give different answers about the same object.

  python oms/test_valid_time.py
"""
import os
import tempfile

tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
if not os.environ.get("DATABASE_URL"):
    os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tmpdir.name, 'valid_time.db')}"
os.environ.setdefault("AUTH_MODE", "local")
os.environ.setdefault("APP_ENV", "test")

import sys  # noqa: E402
from pathlib import Path  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))

from app import models, object_writes, ontology_runtime_v1  # noqa: E402
from app.database import SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402,F401  (registers every table on the shared Base)
from app.ontology_runtime_v1 import ObjectChangeEvent  # noqa: E402

models.Base.metadata.create_all(bind=engine)

passed = 0


def check(condition, label, payload=None):
    global passed
    assert condition, f"{label}: {payload}"
    passed += 1


# A controlled clock, so transaction time is a fact this test states rather than
# one it races. Business time is passed explicitly; transaction time is stamped
# by the recorder, and the point of the exercise is that they are independent.
clock = {"now": 0}
_real_now = ontology_runtime_v1._now
ontology_runtime_v1._now = lambda: clock["now"]

db = SessionLocal()
db.add(models.ObjectType(id="account", display_name="Account", description="",
                         properties={"tier": {"type": "string"}}, project_id="p",
                         created_at=0, updated_at=0))
db.commit()

JANUARY, JUNE, DECEMBER = 1_000, 2_000, 3_000

clock["now"] = JANUARY
object_writes.create_object(
    db, object_id="a1", object_type_id="account", project_id="p",
    properties={"tier": "silver"}, actor="t", event_type="ontology.object.created",
    source_type="test", now=JANUARY, valid_from=JANUARY)
db.commit()

clock["now"] = JUNE
object_writes.update_object(
    db, db.get(models.ObjectInstance, "a1"), properties={"tier": "gold"},
    actor="t", event_type="ontology.object.updated", source_type="test",
    now=JUNE, valid_from=JUNE)
db.commit()

events = db.query(ObjectChangeEvent).order_by(ObjectChangeEvent.object_version).all()
check(len(events) == 2, "two versions recorded", len(events))
check(events[0].valid_to == JUNE,
      "the first interval closes where the second begins -- before this it stayed None "
      "and every version was valid forever", events[0].valid_to)
check(events[1].valid_to is None, "and the current one stays open", events[1].valid_to)

# --- the correction: discovered in December, true since January ---------------

clock["now"] = DECEMBER
object_writes.update_object(
    db, db.get(models.ObjectInstance, "a1"), properties={"tier": "bronze"},
    actor="auditor", event_type="ontology.object.updated", source_type="test",
    now=DECEMBER, valid_from=JANUARY)
db.commit()

correction = db.query(ObjectChangeEvent).filter(
    ObjectChangeEvent.object_version == 3).one()
check(correction.valid_from == JANUARY,
      "the correction is effective from January", correction.valid_from)
check(correction.transaction_time == DECEMBER,
      "and was recorded in December", correction.transaction_time)
check(correction.valid_from != correction.transaction_time,
      "so the two axes hold different values on one row -- which no event in this "
      "repository could do before, because no caller ever supplied a business time")

# The ordinary case must not be disturbed by the correction: June's interval
# began after January, so a correction effective from January does not close it.
june_event = db.query(ObjectChangeEvent).filter(ObjectChangeEvent.object_version == 2).one()
check(june_event.valid_to is None,
      "a correction effective before an interval does not close that interval -- "
      "this implements supersession, not interval splitting, and says so",
      june_event.valid_to)

# --- the axes disagree, which is the whole claim ------------------------------

def as_of(*, valid_time=None, transaction_time=None):
    conditions = [ObjectChangeEvent.object_id == "a1"]
    if valid_time is not None:
        conditions.append(ObjectChangeEvent.valid_from <= valid_time)
        conditions.append((ObjectChangeEvent.valid_to.is_(None))
                          | (ObjectChangeEvent.valid_to > valid_time))
    if transaction_time is not None:
        conditions.append(ObjectChangeEvent.transaction_time <= transaction_time)
    row = db.query(ObjectChangeEvent).filter(*conditions).order_by(
        ObjectChangeEvent.transaction_time.desc(),
        ObjectChangeEvent.object_version.desc()).first()
    return row.after_state.get("tier") if row else None


march = 1_500
check(as_of(valid_time=march) == "bronze",
      "what we now believe was true in March: the corrected value", as_of(valid_time=march))
check(as_of(transaction_time=JUNE, valid_time=march) == "silver",
      "what we believed in June about March: the value before the correction was known",
      as_of(transaction_time=JUNE, valid_time=march))
check(as_of(valid_time=march) != as_of(transaction_time=JUNE, valid_time=march),
      "so the same question about the same object gets two answers, one per axis -- "
      "which is the claim README.md makes and could not previously support")

check(as_of(valid_time=2_500) == "bronze", "and the latest belief wins where intervals overlap",
      as_of(valid_time=2_500))

# --- a write with no business time still behaves as it always did -------------

clock["now"] = 9_000
object_writes.create_object(
    db, object_id="a2", object_type_id="account", project_id="p",
    properties={"tier": "silver"}, actor="t", event_type="ontology.object.created",
    source_type="test")
db.commit()
plain = db.query(ObjectChangeEvent).filter(ObjectChangeEvent.object_id == "a2").one()
check(plain.valid_from == plain.transaction_time == 9_000,
      "a caller that names no business time gets the transaction time, exactly as before",
      (plain.valid_from, plain.transaction_time))

ontology_runtime_v1._now = _real_now
db.close()

print(f"Valid time verified: {passed} assertions passed "
      f"(intervals close, and the two axes disagree).")

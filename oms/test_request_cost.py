"""The instrument has to be right before anything it measures can be believed.

Two properties carry the weight. Normalising statements must collapse a shape
executed many times into one shape with a count -- otherwise an N+1 against rows
with distinct ids reads as N distinct queries and hides in plain sight. And the
listener must not outlive its block, or one request's queries are attributed to
the next one and every measurement after the first is wrong.
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
os.environ["DATABASE_URL"] = f"sqlite:///{Path(tmpdir.name, 'request-cost.db').as_posix()}"
os.environ["AUTH_MODE"] = "local"
os.environ["APP_ENV"] = "test"
sys.path.insert(0, str(Path(__file__).resolve().parent))

from sqlalchemy import text  # noqa: E402

from app.database import SessionLocal, engine  # noqa: E402
from request_cost import counting, growth, normalize, summarize  # noqa: E402

passed = 0


def check(condition, label, payload=None):
    global passed
    assert condition, f"{label}: {payload}"
    passed += 1


# --- normalisation ----------------------------------------------------------

one = normalize("SELECT * FROM objects WHERE id = 'abc-123'")
two = normalize("SELECT * FROM objects WHERE id = 'def-456'")
check(one == two, "the same shape with different literals is one shape", (one, two))

check(normalize("SELECT a FROM t WHERE id = 5") == normalize("SELECT a FROM t WHERE id = 900"),
      "numeric literals collapse too", None)
check(normalize("SELECT a  FROM\n  t") == "SELECT a FROM t", "whitespace collapses", None)
check(normalize("SELECT a FROM t WHERE id IN (1, 2, 3)")
      == normalize("SELECT a FROM t WHERE id IN (7)"),
      "IN lists of different lengths are one shape", None)
check(normalize("SELECT a FROM t WHERE id = :ident") == normalize("SELECT a FROM t WHERE id = ?"),
      "bind parameter styles collapse to the same shape", None)

# Shapes that genuinely differ must stay different, or the instrument hides
# variety instead of revealing repetition.
check(normalize("SELECT a FROM t") != normalize("SELECT a FROM u"),
      "different tables are different shapes", None)

# --- summarising ------------------------------------------------------------

empty = summarize([])
check(empty["queries"] == 0 and empty["worst_repeat"] == 0, "no statements is no cost", empty)

# This is the shape of an N+1: one lookup, then one query per row, with a
# different id each time. It must read as 1 shape run 5 times, not 5 queries.
n_plus_one = ["SELECT id FROM parents"] + [
    f"SELECT * FROM children WHERE parent_id = '{index}'" for index in range(5)
]
summary = summarize(n_plus_one)
check(summary["queries"] == 6, "counts every statement", summary)
check(summary["distinct_shapes"] == 2, "five lookups are one shape", summary)
check(summary["worst_repeat"] == 5, "the repeat count is the row count", summary)
check(summary["repeats"][0]["count"] == 5, "the worst repeat is reported first", summary["repeats"])

varied = summarize(["SELECT a FROM t", "SELECT b FROM u", "SELECT c FROM v"])
check(varied["worst_repeat"] == 0, "three different shapes are not a repeat", varied)
check(varied["repeats"] == [], "nothing repeats, so nothing is reported", varied)

# --- counting against a real engine -----------------------------------------

with counting(engine) as collected:
    with SessionLocal() as db:
        db.execute(text("SELECT 1"))
        db.execute(text("SELECT 2"))
check(len(collected) == 2, "the block sees exactly its own statements", collected)

# The listener must be gone afterwards. If it is not, the next measurement
# inherits this one's statements and every number after the first is wrong.
with SessionLocal() as db:
    db.execute(text("SELECT 3"))
check(len(collected) == 2, "statements after the block are not attributed to it", collected)

with counting(engine) as second:
    with SessionLocal() as db:
        db.execute(text("SELECT 4"))
check(len(second) == 1, "a later block starts from zero", second)

# Nesting has to work, because a caller may measure a request that internally
# measures something else.
with counting(engine) as outer:
    with SessionLocal() as db:
        db.execute(text("SELECT 5"))
    with counting(engine) as inner:
        with SessionLocal() as db:
            db.execute(text("SELECT 6"))
    check(len(inner) == 1, "the inner block sees only its own", inner)
check(len(outer) == 2, "the outer block sees both", outer)

# An exception inside the block must still remove the listener.
try:
    with counting(engine):
        raise RuntimeError("boom")
except RuntimeError:
    passed += 1
with counting(engine) as after_error:
    with SessionLocal() as db:
        db.execute(text("SELECT 7"))
check(len(after_error) == 1, "a raising block still detaches its listener", after_error)

# --- growth -----------------------------------------------------------------

flat = growth({"queries": 4}, {"queries": 4}, 8)
check(flat == 0.0, "a route whose cost does not follow the data reports zero", flat)

per_row = growth({"queries": 4}, {"queries": 12}, 8)
check(per_row == 1.0, "one extra query per row reports 1.0", per_row)
check(growth({"queries": 4}, {"queries": 8}, 0) == 0.0, "no rows added is not a division", None)

print(f"Request cost instrument verified: {passed} assertions passed.")

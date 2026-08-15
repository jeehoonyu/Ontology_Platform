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
from request_cost import counting, normalize, shape, summarize  # noqa: E402

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

# --- shape: a step is not a slope -------------------------------------------
#
# These are the real numbers from /ui-state/ontology, which a two-point
# comparison called a one-query-per-row N+1 and which is nothing of the kind.

measured = shape([(0, 1), (8, 9), (16, 9), (32, 9)])
check(measured["verdict"] == "step", "a branch that runs once data exists is a step", measured)
check(measured["slope"] == 0.0, "a step has no slope", measured)

real = shape([(0, 1), (8, 9), (16, 17), (32, 33)])
check(real["verdict"] == "linear", "one query per row is linear", real)
check(real["slope"] == 1.0, "the slope excludes the empty-database point", real)

flat = shape([(0, 4), (8, 4), (16, 4)])
check(flat["verdict"] == "flat", "unchanged cost is flat", flat)

# Two points is the mistake this function exists to prevent, so it refuses.
check(shape([(0, 1), (8, 9)])["verdict"] == "unknown",
      "two points cannot tell a step from a slope, and must not guess",
      shape([(0, 1), (8, 9)]))
check(shape([(0, 1), (8, 9)])["slope"] is None, "an unknown verdict reports no slope", None)
check("three points" in shape([(0, 1), (8, 9)])["why"], "and says why", shape([(0, 1), (8, 9)]))

# All-empty points cannot answer it either.
check(shape([(0, 1), (0, 1), (0, 1)])["verdict"] == "unknown",
      "points with no data are not a measurement of growth", None)

# Unordered input must not change the verdict.
check(shape([(32, 9), (0, 1), (8, 9), (16, 9)])["verdict"] == "step",
      "points are sorted before they are read", None)

print(f"Request cost instrument verified: {passed} assertions passed.")

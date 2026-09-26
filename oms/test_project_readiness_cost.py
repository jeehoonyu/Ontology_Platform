"""`/project/readiness` must not cost more as the project grows.

Not `/health/ready`, whose cost `test_readiness_cost.py` holds down. This is the
project readiness the top bar asks for on every page load. Readiness built the
whole scoped project snapshot to learn which collections it has, and tallied
ops events by loading every one. On the database a full browser run had built
by the time `laptop-1366` reached `shell-widths.spec.ts` (33 MB, 25k snapshot
rows), one call was 1.0 s of Python. Calls overlapped, two dozen at a time, the
slowest taking 56 s, and the Platform Graph test that holds readiness back
waited 40 s for its answer against a 45 s timeout. It had measured 0.04 s
in-process, on a small database.

So the property is not a time. It is that the rows readiness loads do not
depend on how many rows there are: seed a thousand more, and it loads the same
number. Then the two answers readiness gives must still be the answers
validation gives, and the coverage check must still be able to fail.
"""
from __future__ import annotations

import collections
import os
import sys
import tempfile
import uuid
from pathlib import Path

tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
os.environ["DATABASE_URL"] = f"sqlite:///{Path(tmpdir.name, 'readiness-cost.db').as_posix()}"
os.environ["AUTH_MODE"] = "local"
os.environ["APP_ENV"] = "test"
sys.path.insert(0, str(Path(__file__).resolve().parent))

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import event  # noqa: E402

from app import ops_control, system_hardening as hardening  # noqa: E402
from app.database import Base, SessionLocal  # noqa: E402
from app.main import app  # noqa: E402

passed = 0


def check(condition, label, payload=None):
    global passed
    assert condition, f"{label}: {payload}"
    passed += 1


client = TestClient(app)
client.get("/health/ready")
check(client.post("/project/demo/bootstrap", json={}).status_code == 200,
      "the demo scenario bootstraps, so this runs against real rows", None)

loaded = []


@event.listens_for(Base, "load", propagate=True)
def _count_load(target, _context):
    loaded.append(type(target).__name__)


def rows_loaded_by(path):
    loaded.clear()
    response = client.get(path)
    check(response.status_code == 200, f"{path} answers", response.status_code)
    return collections.Counter(loaded), response.json()


def seed_ops_events(count):
    # Ops events are in both halves of what readiness used to pay for: the
    # snapshot's `ops_events` collection, and event consistency's tally by source.
    with SessionLocal() as db:
        db.add_all([
            ops_control.OpsEvent(
                id=f"readiness_cost_{uuid.uuid4().hex}", source=("imports", "streaming", "pipeline")[i % 3],
                event_type="readiness.cost", title="seeded", payload={"i": i, "blob": "x" * 200},
                created_at=1,
            )
            for i in range(count)
        ])
        db.commit()


# --- the cost does not follow the rows --------------------------------------

client.get("/project/readiness")  # the first call reconciles the runtime schema
before, _ = rows_loaded_by("/project/readiness")
validate_before, _ = rows_loaded_by("/project/validate")
seed_ops_events(1000)
after, readiness = rows_loaded_by("/project/readiness")
validate_after, validation = rows_loaded_by("/project/validate")

check(validate_after["OpsEvent"] - validate_before["OpsEvent"] >= 1000,
      "validation, which counts rows, does load the thousand new events",
      (validate_before["OpsEvent"], validate_after["OpsEvent"]))
check(after == before, "readiness loads exactly what it loaded a thousand events ago",
      (sum(before.values()), sum(after.values()), (after - before).most_common(3)))
check(after["OpsEvent"] == 0, "and no ops event at all", after["OpsEvent"])
check(sum(after.values()) < 100, "only a few dozen rows in all, whatever the project holds",
      after.most_common(5))

calls = []
original_snapshot = hardening._snapshot
try:
    def counted(*args, **kwargs):
        calls.append(1)
        return original_snapshot(*args, **kwargs)

    hardening._snapshot = counted
    client.get("/project/readiness")
    check(calls == [], "readiness builds no snapshot", len(calls))
    client.get("/project/validate")
    check(len(calls) == 1, "validation still builds one, to count its rows", len(calls))
finally:
    hardening._snapshot = original_snapshot

# --- the same answers ---------------------------------------------------------

sections = validation["sections"]
by_check = {entry["id"]: entry["status"] for entry in readiness["checks"]}
for check_id, section in (("schema", "schema_health"), ("migrations", "migrations"),
                          ("events", "event_consistency"), ("snapshot", "snapshot_coverage"),
                          ("docs", "docs_conformance"), ("routes", "route_health")):
    check(by_check.get(check_id) == sections[section]["status"],
          f"readiness's {check_id} check says what validation's {section} says",
          (by_check.get(check_id), sections[section]["status"]))
check(readiness["summary"]["project_validation"] == validation["status"],
      "and its overall answer is validation's", (readiness["summary"], validation["status"]))
check(sections["snapshot_coverage"]["counts"]["ops_events"] >= 1000,
      "validation's coverage still counts rows", sections["snapshot_coverage"]["counts"].get("ops_events"))

with SessionLocal() as db:
    names = set(hardening._snapshot_collections(db, "default"))
    scoped = hardening._snapshot(db, "default", "local", finalize=False)
    unscoped = hardening._snapshot(db, None, None, finalize=False)
    tallied = collections.Counter(row.source for row in db.query(ops_control.OpsEvent))
    consistency = hardening.event_consistency(db)
check(names == {key for key, value in scoped.items() if isinstance(value, list)},
      "the names readiness reads are the collections a scoped snapshot carries",
      sorted(names ^ {key for key, value in scoped.items() if isinstance(value, list)}))
check(names == {key for key, value in unscoped.items() if isinstance(value, list)},
      "and an unscoped one", None)
check(consistency["source_counts"] == dict(tallied),
      "ops events tallied by the database match a tally of every row", (consistency["source_counts"], tallied))
check(tallied["imports"] >= 334, "and the tally includes the seeded events", tallied)

# --- the coverage check can still fail ---------------------------------------

original_collections = hardening._snapshot_collections
try:
    def without_object_types(db, project_id=None):
        declared = original_collections(db, project_id)
        declared.pop("object_types")
        return declared

    hardening._snapshot_collections = without_object_types
    _, degraded = rows_loaded_by("/project/readiness")
    snapshot_check = next(entry for entry in degraded["checks"] if entry["id"] == "snapshot")
    check(snapshot_check["status"] == "WARN",
          "a collection missing from the builder turns readiness's snapshot check WARN", snapshot_check)
    check(degraded["status"] == "NEEDS_ATTENTION", "and readiness with it", degraded["status"])
finally:
    hardening._snapshot_collections = original_collections

print(f"Project readiness cost verified: {passed} assertions passed "
      f"({sum(after.values())} rows loaded by readiness, before and after 1000 more events).")

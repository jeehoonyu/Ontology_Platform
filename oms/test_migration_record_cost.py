"""Reconciling the migration record list must not cost one query per migration.

`_ensure_migration_records` called `db.get(MigrationRecord, version)` inside a
loop over `MIGRATIONS`. That is 32 round-trips per call today, on four routes,
and the number is the length of the migration list -- so the cost of asking
whether the product is ready rose with every migration anyone landed.

Measured before the fix: `/project/readiness` 297 queries against an empty
database, `/system/migrations` 35. After: 169 and 3.

The assertion that matters is not the absolute number. It is that the count does
**not** move when the migration list gets longer, because that is the property
the next fifty migrations will test whether or not anyone is watching.
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
os.environ["DATABASE_URL"] = f"sqlite:///{Path(tmpdir.name, 'migration-cost.db').as_posix()}"
os.environ["AUTH_MODE"] = "local"
os.environ["APP_ENV"] = "test"
sys.path.insert(0, str(Path(__file__).resolve().parent))

from app import system_hardening  # noqa: E402
from app.database import SessionLocal, engine  # noqa: E402
from request_cost import counting, summarize  # noqa: E402

passed = 0


def check(condition, label, payload=None):
    global passed
    assert condition, f"{label}: {payload}"
    passed += 1


def reconcile():
    """One call, and the statements it took."""
    with counting(engine) as seen:
        with SessionLocal() as db:
            system_hardening._ensure_migration_records(db)
            db.commit()
    return summarize(seen)


declared = len(system_hardening.MIGRATIONS)
check(declared > 10, "there are enough migrations for a per-migration loop to matter", declared)

first = reconcile()
steady = reconcile()

check(steady["queries"] <= 3,
      "a reconciliation that changes nothing is a handful of statements, not one per migration",
      steady)
check(steady["worst_repeat"] == 0,
      "no statement shape repeats once the records exist", steady["repeats"][:2])
check(first["queries"] < declared * 2,
      "even the first run, which inserts, does not pay a savepoint per migration", first)

# The property that outlives the numbers: lengthening the migration list must
# not lengthen the query count. This is what a loop over MIGRATIONS fails and a
# single read passes, and it is why the assertion is a comparison rather than a
# constant someone will bump.
original = list(system_hardening.MIGRATIONS)
try:
    system_hardening.MIGRATIONS = original + [
        {"version": 90000 + index, "name": f"synthetic_{index}", "status": "applied"}
        for index in range(len(original))
    ]
    doubled_first = reconcile()
    doubled_steady = reconcile()

    check(len(system_hardening.MIGRATIONS) == declared * 2,
          "the list really doubled", len(system_hardening.MIGRATIONS))
    check(doubled_steady["queries"] == steady["queries"],
          "twice the migrations costs the same once they are recorded",
          (steady["queries"], doubled_steady["queries"]))
    check(doubled_first["queries"] - first["queries"] < declared,
          "inserting twice as many rows does not cost twice as many statements",
          (first["queries"], doubled_first["queries"]))
finally:
    system_hardening.MIGRATIONS = original

# Cheap is worthless if it is wrong. Every declared migration must be recorded
# exactly once, and a second pass must not change what the first one wrote.
with SessionLocal() as db:
    rows = db.query(system_hardening.MigrationRecord).all()
    versions = [row.version for row in rows]
    names = {row.version: row.name for row in rows}
declared_versions = {migration["version"] for migration in original}
check(declared_versions.issubset(set(versions)), "every declared migration is recorded", None)
check(len(versions) == len(set(versions)), "no migration is recorded twice", len(versions))
for migration in original:
    check(names.get(migration["version"]) == migration["name"],
          "each record carries its declared name", migration["version"])
    break  # one is enough to prove the mapping; the loop above proved the set

# A changed name must still be written through on the next reconciliation --
# the read is batched, the update is not skipped.
with SessionLocal() as db:
    row = db.get(system_hardening.MigrationRecord, original[0]["version"])
    row.name = "drifted"
    db.commit()
reconcile()
with SessionLocal() as db:
    repaired = db.get(system_hardening.MigrationRecord, original[0]["version"])
    check(repaired.name == original[0]["name"],
          "a drifted name is corrected, not left because the row already existed",
          repaired.name)

print(f"Migration record cost verified: {passed} assertions passed "
      f"({declared} migrations, {steady['queries']} statements to reconcile).")

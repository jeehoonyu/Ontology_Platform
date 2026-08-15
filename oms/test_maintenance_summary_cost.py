"""The maintenance summary must cost one count, and be computed once per request.

Two defects, both invisible in the source and both obvious the moment anyone
counted statements on `/ui-state/command-center`:

  * `maintenance_summary` counted six object types with six `SELECT count(*)`
    statements, one per entry of a list literal.
  * `_summarize` called `maintenance_summary(db)` **twice in the same dict
    literal**, so the route paid for all of it twice.

Thirteen of that route's eighty queries were those two things. The route is now
67 on an empty database.

The assertions here are about shape, not totals. A total is a number someone
will bump when an unrelated query is added; "one grouped count" and "called
once" stay true or are broken outright.
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
os.environ["DATABASE_URL"] = f"sqlite:///{Path(tmpdir.name, 'maintenance-cost.db').as_posix()}"
os.environ["AUTH_MODE"] = "local"
os.environ["APP_ENV"] = "test"
sys.path.insert(0, str(Path(__file__).resolve().parent))

from fastapi.testclient import TestClient  # noqa: E402

from app import asset_reliability_scenario, models  # noqa: E402
from app.database import SessionLocal, engine  # noqa: E402
from app.domain_maintenance import maintenance_summary  # noqa: E402
from app.main import app  # noqa: E402
from request_cost import counting, summarize  # noqa: E402

TYPES = ["facility", "asset", "technician", "part", "work_order", "purchase_request"]
passed = 0


def check(condition, label, payload=None):
    global passed
    assert condition, f"{label}: {payload}"
    passed += 1


def counts_of(statements):
    """Aggregate statements, however they spell the aggregate.

    `count(*)` was the spelling before the fix and `count(object_instances.id)`
    is the spelling after, so matching the old one would have scored the new
    code as issuing no counts at all -- a fix marked correct for having stopped
    doing the thing being measured.
    """
    return sum(1 for statement in statements if "count(" in statement.lower())


client = TestClient(app)
client.get("/health/ready")
check(client.post("/project/demo/bootstrap", json={}).status_code == 200,
      "the demo scenario bootstraps, so these run against real rows", None)

# --- one grouped count, not one per object type -----------------------------

with counting(engine) as collected:
    with SessionLocal() as db:
        summary = maintenance_summary(db)
check(counts_of(collected) == 1,
      "six object types are counted by one grouped statement", collected)
check(summarize(collected)["worst_repeat"] == 0,
      "no statement shape repeats inside the summary", summarize(collected)["repeats"])

# --- and the numbers are the ones the per-type loop produced ----------------

with SessionLocal() as db:
    expected = {
        object_type_id: db.query(models.ObjectInstance).filter(
            models.ObjectInstance.object_type_id == object_type_id).count()
        for object_type_id in TYPES
    }
check(summary["object_counts"] == expected,
      "the grouped count agrees with counting each type separately",
      (summary["object_counts"], expected))
check(any(value > 0 for value in expected.values()),
      "the comparison is against real rows, not six zeros", expected)

# GROUP BY returns no row for a type with no instances, and the caller reads
# every key. A missing key would read as an absent object type, not an empty one.
absent = [name for name, value in expected.items() if value == 0]
check(absent, "at least one declared type has no instances, which is the case that bites", expected)
for name in absent:
    check(summary["object_counts"].get(name) == 0,
          "a type with no rows is zero, not missing", name)

# Counting must not depend on how many *other* object types exist. The old
# comprehension was one statement per entry of its own list, so this would not
# have caught it -- but a later "improvement" that counts every type in the
# database instead would be caught here, and that is the plausible regression.
seeded = 0
for index in range(12):
    created = client.post("/object-types", json={
        "id": f"unrelated_type_{index}", "api_name": f"unrelated_type_{index}",
        "display_name": f"Unrelated {index}", "primary_key": "id",
        "properties": {"id": "string"},
    })
    seeded += 1 if created.status_code in (200, 201) else 0
check(seeded == 12, "twelve unrelated object types were created", seeded)

with counting(engine) as after_noise:
    with SessionLocal() as db:
        maintenance_summary(db)
check(counts_of(after_noise) == 1,
      "twelve unrelated object types do not add a statement", after_noise)

# --- computed once per request, not twice -----------------------------------

original = asset_reliability_scenario.maintenance_summary
calls = []
try:
    def counted(db):
        calls.append(1)
        return original(db)

    asset_reliability_scenario.maintenance_summary = counted
    calls.clear()
    response = client.get("/ui-state/command-center")
    check(response.status_code == 200, "the route still answers", response.status_code)
    check(len(calls) == 1,
          "the maintenance summary is computed once per request, not once per reader",
          len(calls))
finally:
    asset_reliability_scenario.maintenance_summary = original

# The asset count in the KPIs is now read from that same summary rather than
# re-queried, so it must still equal what a direct count returns.
body = client.get("/ui-state/command-center").json()
kpis = body["workflow"]["summary"]["kpis"]
check(kpis["asset_count"] == expected["asset"],
      "asset_count matches a direct count of asset instances",
      (kpis["asset_count"], expected["asset"]))

with counting(engine) as route_statements:
    client.get("/ui-state/command-center")
check(counts_of(route_statements) <= 6,
      "the route no longer pays for thirteen counts", counts_of(route_statements))

print(f"Maintenance summary cost verified: {passed} assertions passed "
      f"({counts_of(route_statements)} count(*) statements on the route, was 13).")

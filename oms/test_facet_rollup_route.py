"""The facet rollup must be reachable through the product, not only in theory.

`object_facet_counts` shipped at migration 0040 and `aggregate_object_set` read
from it whenever it was populated. Nothing populated it: the only caller of
`refresh_facet_counts` in the repository was a test, so no deployment could reach
the stored path and every facet read paid the exact aggregate. The gate recorded
`facet_source: exact` for three days and was telling the truth.

These cases are the ways that could happen again -- a route that vanishes, a
rollup that disagrees with the exact answer, or one served long after it stopped
being true.
"""
import os
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

_root = tempfile.mkdtemp()
os.environ["DATABASE_URL"] = f"sqlite:///{Path(_root).as_posix()}/facet_rollup_route.db"
os.environ.setdefault("AUTH_MODE", "local")
os.environ.setdefault("APP_ENV", "test")

from fastapi.testclient import TestClient  # noqa: E402

from app import models  # noqa: E402
from app.database import SessionLocal  # noqa: E402
from app.main import app  # noqa: E402

client = TestClient(app)
TYPE_ID = "facet_route_asset"
passed = 0


def check(condition, label, payload=None):
    global passed
    assert condition, f"{label}: {payload}"
    passed += 1


def aggregate(**overrides):
    body = {"object_type_id": TYPE_ID, "group_by": "category"}
    body.update(overrides)
    response = client.post("/object-sets/aggregate", json=body)
    assert response.status_code == 200, response.text
    return response.json()


def refresh(field="category"):
    return client.post("/object-sets/facets/refresh",
                       json={"object_type_id": TYPE_ID, "field": field})


assert client.post("/object-types", json={
    "id": TYPE_ID, "project_id": "default", "display_name": "Facet route asset",
    "properties": {"category": {"type": "string"}, "risk": {"type": "number"}},
}).status_code in (200, 201)

for index in range(9):
    assert client.post("/objects", json={
        "id": f"facet_route_{index}", "project_id": "default", "object_type_id": TYPE_ID,
        "properties": {"category": f"c{index % 3}", "risk": index},
    }).status_code in (200, 201)

# The route exists. Its absence is the whole defect, so this is asserted first --
# by inspecting the routing table rather than by calling it, because calling it
# would populate the rollup and destroy the "exact" baseline below.
check(any(getattr(route, "path", "") == "/object-sets/facets/refresh" for route in app.routes),
      "the refresh route is mounted")

exact = aggregate()
check(exact["source"] == "exact", "with no stored counts the aggregate computes exactly", exact)

response = refresh()
check(response.status_code == 200, "and the route answers", response.text[:200])
stored = response.json()
check(stored["field"] == "category", "the refresh reports the field it stored", stored)
check(isinstance(stored["refresh_seconds"], (int, float)),
      "and what it cost, because a fast read is only half the price", stored)

served = aggregate()
check(served["source"] == "rollup", "the next aggregate is served from the rollup", served)
check(served["groups"] == exact["groups"],
      "and agrees with the exact answer it replaced", (served["groups"], exact["groups"]))
check(served["total"] == 9, "over every object in the type", served)

# Staleness. Without a bound a rollup computed once is served forever, which is
# how a stored count outlives the data it described.
database = SessionLocal()
for row in database.query(models.ObjectFacetCount).all():
    row.computed_at = int(time.time()) - 3600
database.commit()
database.close()

check(aggregate(max_rollup_age_seconds=60)["source"] == "exact",
      "an hour-old rollup is refused by a caller that asked for fresher")
check(aggregate()["source"] == "rollup",
      "and still served to a caller that set no bound -- the documented default")

# A filtered aggregate describes a subset; the rollup describes the whole type.
filtered = aggregate(filters={"category": "c0"})
check(filtered["source"] == "exact", "a filtered aggregate never uses the rollup", filtered)

# The stored counts must never contradict the computed ones, including for a
# field the schema does not declare.
ghost_exact = aggregate(group_by="ghost_field")
check(ghost_exact["source"] == "exact", "an undeclared field computes exactly first")
check(refresh("ghost_field").status_code == 200, "and can be rolled up")
ghost_rollup = aggregate(group_by="ghost_field")
check(ghost_rollup["source"] == "rollup", "then serves from the rollup")
check(ghost_rollup["groups"] == ghost_exact["groups"],
      "with the same answer, which is the property the rollup must not break",
      (ghost_rollup["groups"], ghost_exact["groups"]))

# Refreshing writes stored state and pays a full scan of the object type -- tens
# of seconds at ten million objects. A reader must not be able to start one, so
# the permission is asserted from the source rather than inferred from a local
# session where AUTH_MODE bypasses it.
source = (Path(__file__).resolve().parent / "app" / "main.py").read_text(encoding="utf-8")
start = source.index('@app.post("/object-sets/facets/refresh"')
definition = source[start:source.index("\n@app.", start + 1)]
check('require_permission("edit")' in definition,
      "the refresh route is behind 'edit', not 'view'", definition[:400])
check('require_permission("view")' not in definition,
      "and does not also accept a viewer")

route = next(r for r in app.routes if getattr(r, "path", "") == "/object-sets/facets/refresh")
check(route.methods == {"POST"}, "the refresh is a POST", route.methods)

# The aggregate route must actually forward the caller's staleness bound. It did
# not until 2026-08-09: the parameter existed on the request and was dropped.
aggregate_start = source.index('@app.post("/object-sets/aggregate"')
aggregate_definition = source[aggregate_start:source.index("\n@app.", aggregate_start + 1)]
check("max_rollup_age_seconds=request.max_rollup_age_seconds" in aggregate_definition,
      "the aggregate route forwards max_rollup_age_seconds", aggregate_definition[:400])

print(f"Facet rollup route verified: {passed} assertions passed.")

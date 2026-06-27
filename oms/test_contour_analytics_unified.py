"""
Standalone self-test for the unified Contour board engine.

Covers BOTH owned routers:
  - app.contour_ops  (/analytics/contour/apply  -- stateless board pipeline)
  - app.analytics    (/analytics/contour/{id}/run -- persisted boards over a DataAsset)

Verifies:
  (1) unified filter schema (field/equals OR config.field/config.value) in BOTH engines
  (2) data-producing boards: chart_series, histogram, distribution, time_series
  (3) transforms: enrich, join, set_math, unpivot
  (4) preserved ops: derive/aggregate/pivot/sort/top_n/summary

Run from oms/:
    ./venv312/Scripts/python.exe test_contour_analytics_unified.py
"""
import os
import tempfile
import time
import uuid

_t = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(_t.name, 't.db')}"

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.database import Base, engine, SessionLocal
from app import models, models_action  # noqa: F401  (register tables)
from app import contour_ops as CO
from app import analytics as AN

Base.metadata.create_all(bind=engine)

api = FastAPI()
api.include_router(CO.router)
api.include_router(AN.router)
client = TestClient(api)

passed = 0


def check(cond, label):
    global passed
    if cond:
        passed += 1
        print(f"  ok  - {label}")
    else:
        print(f"  FAIL- {label}")
        raise AssertionError(label)


SALES = [
    {"id": "a", "city": "NYC", "region": "east", "amount": 100, "qty": 2, "t": 3},
    {"id": "b", "city": "NYC", "region": "east", "amount": 200, "qty": 4, "t": 1},
    {"id": "c", "city": "LA", "region": "west", "amount": 50, "qty": 1, "t": 2},
    {"id": "d", "city": "LA", "region": "west", "amount": 70, "qty": 3, "t": 4},
    {"id": "e", "city": "SF", "region": "west", "amount": 90, "qty": 5, "t": 5},
]


def apply(boards, records=None):
    r = client.post("/analytics/contour/apply",
                    json={"records": records if records is not None else SALES, "boards": boards})
    assert r.status_code == 200, r.text
    return r.json()


# ---------------------------------------------------------------------------
# (1) UNIFIED FILTER SCHEMA in contour_ops
# ---------------------------------------------------------------------------
out = apply([{"op": "filter", "field": "city", "equals": "NYC"}])
check(out["row_count"] == 2 and all(r["city"] == "NYC" for r in out["records"]),
      "contour_ops filter accepts field/equals form")

out = apply([{"op": "filter", "config": {"field": "city", "value": "NYC"}}])
check(out["row_count"] == 2 and all(r["city"] == "NYC" for r in out["records"]),
      "contour_ops filter accepts config.field/config.value form")

# ---------------------------------------------------------------------------
# (2) DATA-PRODUCING boards (contour_ops)
# ---------------------------------------------------------------------------
out = apply([{"op": "chart_series", "group_by": "region", "metric": "sum", "metric_field": "amount"}])
series = {s["category"]: s["value"] for s in out["records"]}
check(series["east"] == 300 and series["west"] == 210, "chart_series group_by+metric")

out = apply([{"op": "histogram", "field": "amount", "bins": 5}])
total = sum(b["count"] for b in out["records"])
check(len(out["records"]) == 5 and total == 5, "histogram bins numeric field")

out = apply([{"op": "distribution", "field": "amount"}])
dist = out["distribution"]
check(dist["p50"] == 90 and dist["count"] == 5 and "p99" in dist and "p25" in dist,
      "distribution percentiles p25/p50/p75/p90/p99")

out = apply([{"op": "time_series", "time_field": "t", "value_field": "amount"}])
ts = out["records"]
check([p["t"] for p in ts] == [1, 2, 3, 4, 5] and ts[0]["value"] == 200,
      "time_series sorts by time field -> {t,value}")

# ---------------------------------------------------------------------------
# (3) TRANSFORMS (contour_ops)
# ---------------------------------------------------------------------------
side = [{"region": "east", "manager": "Alice"}, {"region": "west", "manager": "Bob"}]
out = apply([{"op": "enrich", "key": "region", "side_table": side, "fields": ["manager"]}])
check(all(r.get("manager") in ("Alice", "Bob") for r in out["records"]),
      "enrich lookup from side-table on key")

right = [{"region": "east", "target": 1000}, {"region": "west", "target": 500}]
out = apply([{"op": "join", "right": right, "on": "region"}])
check(out["row_count"] == 5 and all("target" in r for r in out["records"]),
      "join merges two record lists on key (runtime helper)")

listA = [{"id": "x"}, {"id": "y"}, {"id": "z"}]
listB = [{"id": "y"}, {"id": "z"}, {"id": "w"}]
out = apply([{"op": "set_math", "mode": "intersect", "key": "id", "other": listB}], records=listA)
check(sorted(r["id"] for r in out["records"]) == ["y", "z"], "set_math intersect by key")

out = apply([{"op": "set_math", "mode": "difference", "key": "id", "other": listB}], records=listA)
check([r["id"] for r in out["records"]] == ["x"], "set_math difference by key")

out = apply([{"op": "set_math", "mode": "union", "key": "id", "other": listB}], records=listA)
check(sorted(r["id"] for r in out["records"]) == ["w", "x", "y", "z"], "set_math union by key")

wide = [{"id": "r1", "jan": 1, "feb": 2, "mar": 3}]
out = apply([{"op": "unpivot", "id_fields": ["id"], "value_columns": ["jan", "feb", "mar"]}], records=wide)
check(len(out["records"]) == 3 and {row["variable"] for row in out["records"]} == {"jan", "feb", "mar"}
      and out["records"][0]["id"] == "r1",
      "unpivot wide columns -> long {variable,value}")

# ---------------------------------------------------------------------------
# (4) PRESERVED ops (contour_ops)
# ---------------------------------------------------------------------------
out = apply([{"op": "sort", "field": "amount", "desc": True}, {"op": "top_n", "n": 2}])
check([r["amount"] for r in out["records"]] == [200, 100], "preserved sort+top_n")

out = apply([{"op": "aggregate", "group_by": ["region"],
              "aggregations": [{"op": "sum", "field": "amount", "as": "tot"}]}])
agg = {r["region"]: r["tot"] for r in out["records"]}
check(agg["east"] == 300 and agg["west"] == 210, "preserved aggregate/group_by")

out = apply([{"op": "summary", "fields": ["amount"]}])
check(out["summary"]["amount"]["min"] == 50 and out["summary"]["amount"]["max"] == 200,
      "preserved summary")

# ---------------------------------------------------------------------------
# ANALYTICS router — persisted Contour over a DataAsset
# ---------------------------------------------------------------------------
db = SessionLocal()
asset_id = uuid.uuid4().hex
db.add(models.DataAsset(
    id=asset_id, display_name="sales", description="t", kind="dataset",
    asset_schema={}, records=SALES, created_at=int(time.time()), updated_at=int(time.time()),
))
db.commit()
db.close()


def make_run(boards):
    r = client.post("/analytics/contour", json={
        "display_name": "c", "input_asset_id": asset_id, "boards": boards})
    assert r.status_code == 200, r.text
    cid = r.json()["id"]
    rr = client.post(f"/analytics/contour/{cid}/run")
    assert rr.status_code == 200, rr.text
    return rr.json()


# unified filter — analytics native (config) form
res = make_run([{"op": "filter", "config": {"field": "city", "value": "NYC"}}])
check(res["row_count"] == 2, "analytics filter accepts config.field/config.value form")

# unified filter — contour_ops (field/equals) form, now accepted by analytics too
res = make_run([{"op": "filter", "field": "city", "equals": "LA"}])
check(res["row_count"] == 2 and all(r["city"] == "LA" for r in res["rows"]),
      "analytics filter ALSO accepts field/equals form (unified)")

# analytics shares the extended executor -> data-producing board works
res = make_run([{"op": "chart_series", "config": {"group_by": "region", "metric": "sum", "metric_field": "amount"}}])
amap = {r["category"]: r["value"] for r in res["rows"]}
check(amap["east"] == 300 and amap["west"] == 210, "analytics chart_series via shared executor")

# analytics extended transform: histogram
res = make_run([{"op": "histogram", "config": {"field": "amount", "bins": 5}}])
check(res["row_count"] == 5 and sum(b["count"] for b in res["rows"]) == 5,
      "analytics histogram via shared executor")

# analytics preserved native aggregate still works (config form)
res = make_run([{"op": "aggregate", "config": {"group_by": "region", "agg_field": "amount", "agg_op": "sum"}}])
check(res["row_count"] == 2, "analytics preserved native aggregate (config form)")

# analytics chained: filter (field/equals) -> derive (config) still composes
res = make_run([
    {"op": "filter", "field": "region", "equals": "west"},
    {"op": "derive", "config": {"new_field": "double", "a": "amount", "b": "2", "op": "*"}},
])
check(res["row_count"] == 3 and all(r["double"] == r["amount"] * 2 for r in res["rows"]),
      "analytics chained unified-filter + native derive")

print(f"\n>= 12 assertions passed: {passed} assertions passed")

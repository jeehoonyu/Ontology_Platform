"""
Standalone self-test for the Quiver time-series LIBRARY (oms/app/quiver_runtime.py).

Builds a local FastAPI app from ONLY the quiver_runtime router (does NOT import
app.main, since sibling files are edited concurrently). Verifies the new library
endpoints (resample / rolling / interpolate / detect-events / aggregate-to-chart)
plus a smoke-check of the preserved original 3 endpoints.

Run from oms/:  ./venv312/Scripts/python.exe test_quiver_runtime.py
"""
import os
import tempfile

_t = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(_t.name, 't.db')}"

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.database import Base, engine, SessionLocal  # noqa: E402
from app import models, models_action  # noqa: E402
from app import quiver_runtime as M  # noqa: E402

Base.metadata.create_all(bind=engine)

api = FastAPI()
api.include_router(M.router)
client = TestClient(api)

passed = 0


def check(cond, label):
    global passed
    assert cond, f"FAILED: {label}"
    passed += 1
    print(f"  ok: {label}")


def seed():
    import time
    db = SessionLocal()
    try:
        now = int(time.time())
        db.add(models.ObjectType(
            id="sensor", display_name="Sensor", description="d",
            properties={}, created_at=now, updated_at=now,
        ))
        # region/value pairs for chart aggregation
        rows = [
            ("s1", "north", 10.0),
            ("s2", "north", 30.0),
            ("s3", "south", 5.0),
            ("s4", "south", 15.0),
            ("s5", "south", 25.0),
        ]
        for sid, region, val in rows:
            db.add(models.ObjectInstance(
                id=sid, object_type_id="sensor",
                properties={"region": region, "reading": val},
                source_asset_id=None, lineage={},
                created_at=now, updated_at=now,
            ))
        db.commit()
    finally:
        db.close()


def main():
    seed()

    # --- RESAMPLE -----------------------------------------------------------
    # buckets of 10s; t in [0,5,10,15] -> bucket 0 {1,3 -> mean 2}, bucket 10 {5,7 -> mean 6}
    r = client.post("/quiver/timeseries/resample", json={
        "series": [{"t": 0, "v": 1}, {"t": 5, "v": 3}, {"t": 10, "v": 5}, {"t": 15, "v": 7}],
        "bucket_seconds": 10, "agg": "mean",
    })
    check(r.status_code == 200, "resample 200")
    body = r.json()
    check(body["series"] == [{"t": 0, "v": 2.0}, {"t": 10, "v": 6.0}], "resample mean buckets correct")

    r2 = client.post("/quiver/timeseries/resample", json={
        "series": [{"t": 0, "v": 1}, {"t": 5, "v": 3}, {"t": 10, "v": 5}],
        "bucket_seconds": 10, "agg": "last",
    })
    check(r2.json()["series"] == [{"t": 0, "v": 3.0}, {"t": 10, "v": 5.0}], "resample last picks last per bucket")

    rbad = client.post("/quiver/timeseries/resample", json={
        "series": [], "bucket_seconds": 10, "agg": "bogus"})
    check(rbad.status_code == 422, "resample rejects bad agg")

    # --- ROLLING ------------------------------------------------------------
    roll = client.post("/quiver/timeseries/rolling", json={
        "series": [{"t": 1, "v": 2}, {"t": 2, "v": 4}, {"t": 3, "v": 6}],
        "window": 2, "agg": "mean",
    })
    check(roll.status_code == 200, "rolling 200")
    # i0: [2]->2 ; i1: [2,4]->3 ; i2: [4,6]->5
    check([p["v"] for p in roll.json()["series"]] == [2.0, 3.0, 5.0], "rolling mean window=2 correct")

    rmed = client.post("/quiver/timeseries/rolling", json={
        "series": [{"t": 1, "v": 1}, {"t": 2, "v": 9}, {"t": 3, "v": 2}],
        "window": 3, "agg": "median",
    })
    check(rmed.json()["series"][-1]["v"] == 2.0, "rolling median of {1,9,2} == 2")

    rstd = client.post("/quiver/timeseries/rolling", json={
        "series": [{"t": 1, "v": 2}, {"t": 2, "v": 4}],
        "window": 2, "agg": "stdev",
    })
    # sample stdev of {2,4} = sqrt(2) ~ 1.414214
    check(abs(rstd.json()["series"][-1]["v"] - 1.414214) < 1e-5, "rolling stdev correct")

    # --- INTERPOLATE --------------------------------------------------------
    ff = client.post("/quiver/timeseries/interpolate", json={
        "series": [{"t": 1, "v": 10}, {"t": 2, "v": None}, {"t": 3, "v": None}, {"t": 4, "v": 40}],
        "method": "ffill",
    })
    check(ff.status_code == 200, "interpolate 200")
    check([p["v"] for p in ff.json()["series"]] == [10.0, 10.0, 10.0, 40.0], "ffill carries forward")
    check(ff.json()["filled"] == 2, "ffill reports filled=2")

    bf = client.post("/quiver/timeseries/interpolate", json={
        "series": [{"t": 1, "v": None}, {"t": 2, "v": 20}],
        "method": "bfill",
    })
    check([p["v"] for p in bf.json()["series"]] == [20.0, 20.0], "bfill carries backward")

    lin = client.post("/quiver/timeseries/interpolate", json={
        "series": [{"t": 0, "v": 0}, {"t": 1, "v": None}, {"t": 2, "v": None}, {"t": 3, "v": 30}],
        "method": "linear",
    })
    check([p["v"] for p in lin.json()["series"]] == [0.0, 10.0, 20.0, 30.0], "linear interpolation even spacing")

    # leading gap left null (no anchor before)
    lead = client.post("/quiver/timeseries/interpolate", json={
        "series": [{"t": 1, "v": None}, {"t": 2, "v": 5}],
        "method": "ffill",
    })
    check(lead.json()["series"][0]["v"] is None, "ffill leaves leading gap null")

    # --- DETECT EVENTS ------------------------------------------------------
    tc = client.post("/quiver/timeseries/detect-events", json={
        "series": [{"t": 1, "v": 1}, {"t": 2, "v": 6}, {"t": 3, "v": 2}],
        "mode": "threshold_crossing", "threshold": 5,
    })
    check(tc.status_code == 200, "detect-events 200")
    evs = tc.json()["events"]
    check(len(evs) == 2 and evs[0]["direction"] == "up" and evs[1]["direction"] == "down",
          "threshold_crossing detects up then down")

    pk = client.post("/quiver/timeseries/detect-events", json={
        "series": [{"t": 1, "v": 1}, {"t": 2, "v": 9}, {"t": 3, "v": 1}, {"t": 4, "v": 5}, {"t": 5, "v": 1}],
        "mode": "peak",
    })
    check([e["t"] for e in pk.json()["events"]] == [2, 4], "peak detects local maxima at t=2,4")

    tr = client.post("/quiver/timeseries/detect-events", json={
        "series": [{"t": 1, "v": 5}, {"t": 2, "v": 1}, {"t": 3, "v": 5}],
        "mode": "trough",
    })
    check([e["t"] for e in tr.json()["events"]] == [2], "trough detects local minimum at t=2")

    miss = client.post("/quiver/timeseries/detect-events", json={
        "series": [{"t": 1, "v": 1}], "mode": "threshold_crossing"})
    check(miss.status_code == 422, "threshold_crossing requires threshold")

    # --- AGGREGATE TO CHART -------------------------------------------------
    chart = client.post("/quiver/object-sets/aggregate-to-chart", json={
        "object_type_id": "sensor", "group_by": "region", "agg": "count",
    })
    check(chart.status_code == 200, "aggregate-to-chart 200")
    cb = chart.json()
    check(cb["categories"] == ["north", "south"], "chart categories sorted")
    by_cat = {s["category"]: s["value"] for s in cb["series"]}
    check(by_cat == {"north": 2, "south": 3}, "chart count per region correct")

    csum = client.post("/quiver/object-sets/aggregate-to-chart", json={
        "object_type_id": "sensor", "group_by": "region", "metric": "reading", "agg": "sum",
    })
    sums = {s["category"]: s["value"] for s in csum.json()["series"]}
    check(sums == {"north": 40.0, "south": 45.0}, "chart sum of reading per region correct")

    cmean = client.post("/quiver/object-sets/aggregate-to-chart", json={
        "object_type_id": "sensor", "group_by": "region", "metric": "reading", "agg": "mean",
    })
    means = {s["category"]: s["value"] for s in cmean.json()["series"]}
    check(means == {"north": 20.0, "south": 15.0}, "chart mean of reading per region correct")

    cbad = client.post("/quiver/object-sets/aggregate-to-chart", json={
        "object_type_id": "sensor", "group_by": "region", "agg": "sum"})
    check(cbad.status_code == 422, "non-count agg requires metric")

    cfilter = client.post("/quiver/object-sets/aggregate-to-chart", json={
        "object_type_id": "sensor", "group_by": "region", "agg": "count",
        "filters": {"region": "south"},
    })
    fcats = {s["category"]: s["value"] for s in cfilter.json()["series"]}
    check(fcats == {"south": 3}, "chart respects filters via _logic_object_rows")

    # --- PRESERVED ORIGINAL ENDPOINTS (smoke) -------------------------------
    fo = client.post("/quiver/timeseries/from-objects", json={
        "object_type_id": "sensor", "time_field": "ts", "value_field": "reading",
    })
    check(fo.status_code == 200, "preserved: from-objects still 200")

    tr2 = client.post("/quiver/timeseries/transform", json={
        "series": [{"t": 1, "v": 2}, {"t": 2, "v": 4}], "op": "stats",
    })
    check(tr2.status_code == 200 and tr2.json()["avg"] == 3.0, "preserved: transform stats still works")

    fc = client.post("/quiver/timeseries/forecast", json={
        "series": [{"t": 1, "v": 1}, {"t": 2, "v": 2}, {"t": 3, "v": 3}], "periods": 2,
    })
    check(fc.status_code == 200 and fc.json()["slope"] == 1.0, "preserved: forecast still works")

    print(f"\n{passed} assertions passed")


if __name__ == "__main__":
    main()

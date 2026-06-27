"""
Deep-fidelity pass 7 conformance test (secondary tools):
  GIS geometry ops + network routing, Quiver time-series + forecast,
  Modeling evaluation metrics, Observability real checks.
Run: ./venv312/Scripts/python.exe test_secondary_tools.py
"""
import os
import tempfile

tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tmpdir.name, 'secondary.db')}"

from fastapi.testclient import TestClient  # noqa: E402
from app.main import app  # noqa: E402

client = TestClient(app)
passed = 0


def ok(resp, label, expect=200):
    global passed
    success = resp.status_code == expect or (expect == 200 and 200 <= resp.status_code < 300)
    assert success, f"{label}: expected {expect}, got {resp.status_code} -> {resp.text[:400]}"
    passed += 1
    return resp.json() if resp.content else {}


# ================= GIS geometry ops =================
# SF (-122.4194,37.7749) -> LA (-118.2437,34.0522): ~559 km
d = ok(client.post("/gis/ops/distance", json={"from": [-122.4194, 37.7749], "to": [-118.2437, 34.0522]}), "distance")
assert 550 < d["kilometers"] < 570, d
c = ok(client.post("/gis/ops/centroid", json={"geometry": {"type": "Polygon", "coordinates": [[[0, 0], [2, 0], [2, 2], [0, 2], [0, 0]]]}}), "centroid")
assert abs(c["centroid"][0] - 0.8) < 0.01 and abs(c["centroid"][1] - 0.8) < 0.01, c  # avg incl. repeated closing pt
bb = ok(client.post("/gis/ops/bbox", json={"geometry": {"type": "Polygon", "coordinates": [[[0, 0], [2, 0], [2, 3], [0, 3], [0, 0]]]}}), "bbox")
assert bb["bbox"] == [0, 0, 2, 3], bb
ar = ok(client.post("/gis/ops/area", json={"geometry": {"type": "Polygon", "coordinates": [[[0, 0], [0.01, 0], [0.01, 0.01], [0, 0.01], [0, 0]]]}}), "area")
assert ar["area_m2"] > 1_000_000, ar  # ~1.1km x 1.1km box near equator
buf = ok(client.post("/gis/ops/buffer", json={"point": [10, 50], "radius_m": 1000, "segments": 8}), "buffer")
assert buf["type"] == "Polygon" and len(buf["coordinates"][0]) == 9, buf

# ================= GIS routing =================
ok(client.post("/object-types", json={"id": "stop", "display_name": "Stop", "description": "",
    "properties": {"geometry": {"type": "geometry"}}}), "stop type")
# 4 stops in a line: A(0,0) B(0,0.1) C(0,0.2) D(0,0.3); links A-B, B-C, C-D, and a long shortcut A-D
coords = {"A": [0, 0.0], "B": [0, 0.1], "C": [0, 0.2], "D": [0, 0.3]}
for sid, ll in coords.items():
    ok(client.post("/objects", json={"id": sid, "object_type_id": "stop",
        "properties": {"geometry": {"type": "Point", "coordinates": ll}}}), f"stop {sid}")
ok(client.post("/link-types", json={"id": "road", "display_name": "road", "source_object_type_id": "stop",
    "target_object_type_id": "stop", "cardinality": "MANY_TO_MANY"}), "road link type")
for a, b in [("A", "B"), ("B", "C"), ("C", "D")]:
    ok(client.post("/links", json={"link_type_id": "road", "source_object_id": a, "target_object_id": b}), f"link {a}{b}")
rt = ok(client.post("/gis/route", json={"object_type_id": "stop", "start_object_id": "A", "end_object_id": "D", "link_type_id": "road"}), "route")
assert rt["reachable"] and rt["path"] == ["A", "B", "C", "D"], rt
assert rt["hops"] == 3, rt
assert 32000 < rt["total_distance_m"] < 34000, rt["total_distance_m"]  # ~0.3 deg lat ≈ 33.3 km

# ================= Quiver time-series =================
series = [{"t": 1, "v": 10}, {"t": 2, "v": 20}, {"t": 3, "v": 30}, {"t": 4, "v": 40}]
ma = ok(client.post("/quiver/timeseries/transform", json={"series": series, "op": "moving_average", "window": 2}), "moving avg")
assert ma["series"][1]["v"] == 15 and ma["series"][3]["v"] == 35, ma["series"]
cu = ok(client.post("/quiver/timeseries/transform", json={"series": series, "op": "cumulative"}), "cumulative")
assert [p["v"] for p in cu["series"]] == [10, 30, 60, 100], cu["series"]
de = ok(client.post("/quiver/timeseries/transform", json={"series": series, "op": "delta"}), "delta")
assert [p["v"] for p in de["series"]] == [0, 10, 10, 10], de["series"]
st = ok(client.post("/quiver/timeseries/transform", json={"series": series, "op": "stats"}), "stats")
assert st["avg"] == 25 and st["max"] == 40, st
fc = ok(client.post("/quiver/timeseries/forecast", json={"series": series, "periods": 2}), "forecast")
assert fc["slope"] == 10 and fc["r2"] == 1.0, fc       # perfectly linear
assert fc["predictions"][0]["v"] == 50 and fc["predictions"][1]["v"] == 60, fc["predictions"]

# series from objects
ok(client.post("/object-types", json={"id": "reading", "display_name": "Reading", "description": "",
    "properties": {"ts": {"type": "number"}, "val": {"type": "number"}}}), "reading type")
for i, (ts, val) in enumerate([(3, 9), (1, 3), (2, 6)]):
    ok(client.post("/objects", json={"id": f"r{i}", "object_type_id": "reading", "properties": {"ts": ts, "val": val}}), f"reading {i}")
sfo = ok(client.post("/quiver/timeseries/from-objects", json={"object_type_id": "reading", "time_field": "ts", "value_field": "val"}), "from-objects")
assert [p["v"] for p in sfo["series"]] == [3, 6, 9], sfo["series"]  # sorted by ts

# ================= Modeling metrics =================
reg = ok(client.post("/modeling/metrics/regression", json={"predictions": [2, 4, 6], "actuals": [2, 4, 6]}), "regression perfect")
assert reg["rmse"] == 0 and reg["r2"] == 1.0, reg
reg2 = ok(client.post("/modeling/metrics/regression", json={"predictions": [3, 5], "actuals": [2, 4]}), "regression mae")
assert reg2["mae"] == 1.0, reg2
cls = ok(client.post("/modeling/metrics/classification", json={
    "predictions": ["yes", "yes", "no", "no"], "actuals": ["yes", "no", "no", "no"], "positive_label": "yes"}), "classification")
assert cls["accuracy"] == 0.75, cls
assert cls["binary"]["precision"] == 0.5 and cls["binary"]["recall"] == 1.0, cls["binary"]
assert cls["confusion_matrix"]["no"]["yes"] == 1, cls["confusion_matrix"]

# ================= Observability checks =================
ok(client.post("/data-assets", json={"id": "live_ds", "display_name": "Live", "kind": "dataset", "asset_schema": {}, "records": [{"x": 1}, {"x": 2}]}), "live ds")
fr = ok(client.post("/observability/checks/freshness", json={"dataset_id": "live_ds", "max_age_seconds": 3600}), "freshness")
assert fr["status"] == "ok", fr
rc = ok(client.post("/observability/checks/row-count", json={"dataset_id": "live_ds", "min": 5}), "row-count")
assert rc["status"] == "failed", rc  # only 2 rows, min 5
roll = ok(client.post("/observability/traces/rollup", json={"spans": [
    {"name": "a", "duration_ms": 5, "status": "ok"}, {"name": "b", "duration_ms": 20, "status": "ok"}]}), "trace rollup")
assert roll["total_duration_ms"] == 25 and roll["slowest_span"] == "b" and roll["ok"], roll
agg = ok(client.post("/observability/metrics/aggregate", json={"name": "lat", "values": [10, 20, 30, 40, 50]}), "metric agg")
assert agg["avg"] == 30 and agg["p50"] == 30 and agg["max"] == 50, agg

print(f"\nSecondary tools (GIS/Quiver/Modeling/Observability) verified: {passed} assertions passed.")
from app.database import engine as _engine  # noqa: E402
_engine.dispose()
tmpdir.cleanup()

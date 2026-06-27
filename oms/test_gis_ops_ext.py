"""Standalone self-test for app.gis_ops additions (displays, value styling,
temporal spatial query). Builds a local FastAPI app from ONLY the gis_ops
router; does NOT import app.main."""
import os
import tempfile
import time

_t = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(_t.name, 't.db')}"

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.database import Base, engine, SessionLocal
from app import models, models_action  # noqa: F401
from app import gis_ops as M

Base.metadata.create_all(bind=engine)

api = FastAPI()
api.include_router(M.router)
client = TestClient(api)


def seed():
    db = SessionLocal()
    try:
        now = int(time.time())
        db.add(models.ObjectType(
            id="sensor", display_name="Sensor", description="t",
            properties={}, created_at=now, updated_at=now,
        ))
        # three sensors near SF with a reading + timestamp_ms
        pts = [
            ("s1", [-122.4012, 37.7924], 10, 1000),
            ("s2", [-122.4015, 37.7926], 55, 5000),
            ("s3", [-122.4500, 37.8000], 90, 9000),  # far away
        ]
        for oid, coords, reading, ts_ms in pts:
            db.add(models.ObjectInstance(
                id=oid, object_type_id="sensor",
                properties={
                    "geometry": {"type": "Point", "coordinates": coords},
                    "reading": reading,
                    "ts_ms": ts_ms,
                    "grade": "A" if reading < 50 else "B",
                },
                source_asset_id=None, lineage={},
                created_at=now, updated_at=now,
            ))
        db.commit()
    finally:
        db.close()


def main():
    seed()
    passed = 0

    # --- existing endpoints still work (preservation) ---
    r = client.post("/gis/ops/distance",
                    json={"from": [-122.4012, 37.7924], "to": [-122.4012, 37.7924]})
    assert r.status_code == 200 and r.json()["meters"] == 0.0, r.text
    passed += 1

    r = client.post("/gis/ops/centroid", json={"geometry": {
        "type": "LineString", "coordinates": [[0, 0], [2, 2]]}})
    assert r.status_code == 200 and r.json()["centroid"] == [1.0, 1.0], r.text
    passed += 1

    r = client.post("/gis/route", json={
        "object_type_id": "sensor",
        "start_object_id": "s1", "end_object_id": "s1"})
    assert r.status_code == 200 and r.json()["reachable"] is True, r.text
    passed += 1

    # --- (1) DISPLAYS ---
    r = client.post("/gis/displays", json={
        "layer_id": "layer-a", "name": "Sensors",
        "symbol": "triangle",
        "style_rules": {"by": "reading"}})
    assert r.status_code == 200, r.text
    disp = r.json()
    assert disp["symbol"] == "triangle" and disp["layer_id"] == "layer-a"
    assert "id" in disp and isinstance(disp["created_at"], int)
    passed += 1

    disp_id = disp["id"]
    # second display on a different layer
    r = client.post("/gis/displays", json={
        "id": "fixed-display", "layer_id": "layer-b", "name": "Other"})
    assert r.status_code == 200 and r.json()["symbol"] == "circle", r.text
    passed += 1

    # GET by id
    r = client.get(f"/gis/displays/{disp_id}")
    assert r.status_code == 200 and r.json()["name"] == "Sensors", r.text
    passed += 1

    # list all
    r = client.get("/gis/displays")
    assert r.status_code == 200 and len(r.json()) == 2, r.text
    passed += 1

    # list filtered by layer_id
    r = client.get("/gis/displays", params={"layer_id": "layer-a"})
    assert r.status_code == 200 and len(r.json()) == 1, r.text
    assert r.json()[0]["id"] == disp_id
    passed += 1

    # 404 for missing display
    r = client.get("/gis/displays/nope")
    assert r.status_code == 404, r.text
    passed += 1

    # --- (2) VALUE-BASED STYLING ---
    # explicit features, graduated stops
    r = client.post("/gis/style/evaluate", json={
        "field": "reading",
        "stops": [
            {"max": 25, "color": "#00ff00", "size": 4},
            {"max": 75, "color": "#ffff00", "size": 8},
            {"max": 100, "color": "#ff0000", "size": 12},
        ],
        "features": [
            {"id": "a", "properties": {"reading": 10}},
            {"id": "b", "properties": {"reading": 55}},
            {"id": "c", "properties": {"reading": 95}},
        ],
    })
    assert r.status_code == 200, r.text
    res = {row["id"]: row for row in r.json()["results"]}
    assert res["a"]["color"] == "#00ff00" and res["a"]["size"] == 4, res["a"]
    assert res["b"]["color"] == "#ffff00" and res["b"]["size"] == 8, res["b"]
    assert res["c"]["color"] == "#ff0000" and res["c"]["size"] == 12, res["c"]
    passed += 1

    # categorical (value match) + default fallback
    r = client.post("/gis/style/evaluate", json={
        "field": "grade",
        "default_color": "#cccccc", "default_size": 1,
        "stops": [
            {"value": "A", "color": "#0000ff", "size": 6},
            {"value": "B", "color": "#ff00ff", "size": 9},
        ],
        "features": [
            {"id": "x", "properties": {"grade": "A"}},
            {"id": "y", "properties": {"grade": "Z"}},  # no match -> default
        ],
    })
    assert r.status_code == 200, r.text
    res = {row["id"]: row for row in r.json()["results"]}
    assert res["x"]["color"] == "#0000ff" and res["x"]["size"] == 6
    assert res["y"]["color"] == "#cccccc" and res["y"]["size"] == 1
    passed += 1

    # object_type_id source (reads seeded sensors)
    r = client.post("/gis/style/evaluate", json={
        "object_type_id": "sensor",
        "field": "reading",
        "stops": [
            {"max": 50, "color": "low", "size": 2},
            {"max": 100, "color": "high", "size": 5},
        ],
    })
    assert r.status_code == 200 and r.json()["count"] == 3, r.text
    by_id = {row["id"]: row for row in r.json()["results"]}
    assert by_id["s1"]["color"] == "low", by_id["s1"]
    assert by_id["s3"]["color"] == "high", by_id["s3"]
    passed += 1

    # validation: neither features nor object_type_id
    r = client.post("/gis/style/evaluate", json={"field": "reading", "stops": []})
    assert r.status_code == 422, r.text
    passed += 1

    # --- (3) TEMPORAL SPATIAL QUERY ---
    # near s1 within 1km -> s1,s2 spatially; time window [1000,5000] keeps both
    r = client.post("/gis/spatial-query-temporal", json={
        "object_type_id": "sensor",
        "geometry_field": "geometry",
        "time_field": "ts_ms",
        "start_ms": 1000, "end_ms": 5000,
        "near": {"longitude": -122.4012, "latitude": 37.7924},
        "radius_meters": 1000,
    })
    assert r.status_code == 200, r.text
    body = r.json()
    ids = sorted(o["id"] for o in body["objects"])
    assert ids == ["s1", "s2"], body
    assert body["count"] == 2
    passed += 1

    # tighten the time window to exclude s2 (ts 5000) -> only s1
    r = client.post("/gis/spatial-query-temporal", json={
        "object_type_id": "sensor",
        "time_field": "ts_ms",
        "start_ms": 0, "end_ms": 2000,
        "near": {"longitude": -122.4012, "latitude": 37.7924},
        "radius_meters": 1000,
    })
    assert r.status_code == 200, r.text
    body = r.json()
    assert [o["id"] for o in body["objects"]] == ["s1"], body
    assert body["spatial_total"] == 2 and body["count"] == 1
    passed += 1

    # bbox covering all three, full time window -> all 3
    r = client.post("/gis/spatial-query-temporal", json={
        "object_type_id": "sensor",
        "time_field": "ts_ms",
        "start_ms": 0, "end_ms": 100000,
        "bbox": [-122.5, 37.79, -122.39, 37.81],
    })
    assert r.status_code == 200, r.text
    assert r.json()["count"] == 3, r.json()
    passed += 1

    # invalid window
    r = client.post("/gis/spatial-query-temporal", json={
        "object_type_id": "sensor", "time_field": "ts_ms",
        "start_ms": 100, "end_ms": 10})
    assert r.status_code == 422, r.text
    passed += 1

    print(f">= {passed} assertions passed")
    assert passed >= 12


if __name__ == "__main__":
    main()

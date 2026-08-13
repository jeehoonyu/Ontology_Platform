"""Advanced deterministic transform coverage for the visual Pipeline Builder."""
import os
import tempfile

tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tmpdir.name, 'pipeline_advanced.db')}"

from fastapi.testclient import TestClient  # noqa: E402
from app.main import app  # noqa: E402

client = TestClient(app)
passed = 0


def ok(response, label, expect=200):
    global passed
    assert response.status_code == expect, f"{label}: {response.status_code} {response.text[:1000]}"
    passed += 1
    return response.json()


ok(client.post("/data-assets", json={
    "id": "advanced_assets",
    "display_name": "Advanced assets",
    "kind": "dataset",
    "asset_schema": {},
    "records": [
        {"asset_id": "a1", "facility": " west ", "temperature": "91.5", "latitude": 37.7749, "longitude": -122.4194, "reading": 3},
        {"asset_id": "a1", "facility": " west ", "temperature": "91.5", "latitude": 37.7749, "longitude": -122.4194, "reading": 3},
        {"asset_id": "a2", "facility": None, "temperature": "70", "latitude": 37.7750, "longitude": -122.4195, "reading": 4},
        {"asset_id": "a3", "facility": " east ", "temperature": "75", "latitude": 40.0, "longitude": -100.0, "reading": 8},
    ],
}), "create transform input")

nodes = [
    {"id": "input", "type": "input_dataset", "config": {"asset_id": "advanced_assets"}},
    {"id": "cast", "type": "cast", "config": {"mapping": {"temperature": "number"}}},
    {"id": "fill", "type": "fill_nulls", "config": {"defaults": {"facility": "unknown"}}},
    {"id": "normalize", "type": "normalize", "config": {"fields": ["facility"], "case": "upper"}},
    {"id": "derive", "type": "derive", "config": {"derivations": [{"target": "label", "operation": "concat", "fields": ["asset_id", "facility"], "separator": ":"}]}},
    {"id": "dedupe", "type": "deduplicate", "config": {"keys": ["asset_id"]}},
    {"id": "geo", "type": "derive_geo_point", "config": {}},
    {"id": "mgrs", "type": "derive_mgrs", "config": {"precision": 3}},
    {"id": "geofence", "type": "spatial_filter", "config": {
        "mode": "geofence", "geometry_field": "geometry", "polygon": {
            "type": "Polygon", "coordinates": [[
                [-122.421, 37.774], [-122.418, 37.774], [-122.418, 37.776],
                [-122.421, 37.776], [-122.421, 37.774],
            ]],
        },
    }},
    {"id": "window", "type": "window", "config": {"order_by": "asset_id", "operation": "running_sum", "field": "reading", "target_field": "running_reading"}},
    {"id": "validate", "type": "validate", "config": {"checks": [{"type": "range", "field": "temperature", "min": 60, "max": 100}]}},
    {"id": "output", "type": "dataset_output", "config": {"asset_id": "advanced_output"}},
]
edges = [{"source": nodes[index]["id"], "target": nodes[index + 1]["id"]} for index in range(len(nodes) - 1)]
ok(client.post("/pipeline-builder/graphs", json={"id": "advanced_graph", "display_name": "Advanced graph", "nodes": nodes, "edges": edges}), "create advanced graph", 201)

validation = ok(client.post("/pipeline-builder/graphs/advanced_graph/validate"), "validate advanced graph")
assert validation["status"] == "VALID", validation

preview = ok(client.post("/pipeline-builder/graphs/advanced_graph/preview", json={"limit": 20}), "preview advanced graph")
rows = preview["rows"]
assert len(rows) == 2, rows
assert rows[0]["temperature"] == 91.5 and rows[0]["facility"] == "WEST", rows[0]
assert rows[0]["label"] == "a1:WEST" and rows[1]["label"] == "a2:UNKNOWN", rows
assert rows[0]["geometry"]["type"] == "Point" and isinstance(rows[0]["mgrs"], str), rows[0]
assert [row["running_reading"] for row in rows] == [3.0, 7.0], rows

ok(client.patch("/pipeline-builder/graphs/advanced_graph/nodes/normalize", json={
    "config": {"fields": ["facility"], "mode": "title"},
}), "configure title normalization")
title_preview = ok(client.post("/pipeline-builder/graphs/advanced_graph/preview", json={"limit": 20}), "preview title normalization")
assert [row["facility"] for row in title_preview["rows"]] == ["West", "Unknown"], title_preview

ok(client.post("/data-assets", json={
    "id": "pivot_input",
    "display_name": "Pivot input",
    "kind": "dataset",
    "asset_schema": {},
    "records": [
        {"asset": "a1", "metric": "temperature", "value": 90},
        {"asset": "a1", "metric": "vibration", "value": 8},
    ],
}), "create pivot input")

pivot_nodes = [
    {"id": "input", "type": "input_dataset", "config": {"asset_id": "pivot_input"}},
    {"id": "pivot", "type": "pivot", "config": {"index": ["asset"], "column": "metric", "value": "value"}},
    {"id": "unpivot", "type": "unpivot", "config": {"id_fields": ["asset"], "value_fields": ["temperature", "vibration"], "name_field": "metric_name", "value_field": "metric_value"}},
]
ok(client.post("/pipeline-builder/graphs", json={
    "id": "pivot_graph", "display_name": "Pivot graph", "nodes": pivot_nodes,
    "edges": [{"source": "input", "target": "pivot"}, {"source": "pivot", "target": "unpivot"}],
}), "create pivot graph", 201)
pivot = ok(client.post("/pipeline-builder/graphs/pivot_graph/preview", json={}), "preview pivot graph")
assert {row["metric_name"] for row in pivot["rows"]} == {"temperature", "vibration"}, pivot

ok(client.post("/data-assets", json={
    "id": "nearby_facilities", "display_name": "Nearby facilities", "kind": "dataset", "asset_schema": {},
    "records": [{"facility_id": "f1", "geometry": {"type": "Point", "coordinates": [-122.41945, 37.77495]}}],
}), "create spatial join input")
spatial_nodes = [
    {"id": "input", "type": "input_dataset", "config": {"asset_id": "advanced_assets"}},
    {"id": "geo", "type": "derive_geo_point", "config": {}},
    {"id": "spatial", "type": "spatial_join", "config": {"right_asset_id": "nearby_facilities", "max_distance_meters": 100}},
]
ok(client.post("/pipeline-builder/graphs", json={
    "id": "spatial_graph", "display_name": "Spatial graph", "nodes": spatial_nodes,
    "edges": [{"source": "input", "target": "geo"}, {"source": "geo", "target": "spatial"}],
}), "create spatial graph", 201)
spatial = ok(client.post("/pipeline-builder/graphs/spatial_graph/preview", json={}), "preview spatial join")
assert len(spatial["rows"]) == 3 and all(row["facility_id"] == "f1" for row in spatial["rows"]), spatial
assert all(row["distance_meters"] <= 100 for row in spatial["rows"]), spatial

catalog = ok(client.get("/pipeline-builder/node-types"), "advanced node catalog")
types = {item["type"] for item in catalog["node_types"]}
assert {"cast", "derive", "deduplicate", "pivot", "window", "derive_mgrs", "spatial_join"}.issubset(types), types

print(f"\nAdvanced pipeline transforms verified: {passed} assertions passed.")
from app.database import engine as _engine  # noqa: E402
_engine.dispose()
tmpdir.cleanup()

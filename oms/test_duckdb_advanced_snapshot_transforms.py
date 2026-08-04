"""SQL-native advanced transforms over immutable Parquet snapshots."""

import os
import tempfile


tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tmpdir.name, 'duckdb_advanced.db')}"
os.environ["DATA_SNAPSHOT_ROOT"] = os.path.join(tmpdir.name, "snapshots")
os.environ["AUTH_MODE"] = "local"
os.environ["APP_ENV"] = "test"

from fastapi.testclient import TestClient  # noqa: E402
from app.main import app  # noqa: E402


client = TestClient(app)


def checked(response, expected=200):
    assert response.status_code == expected, f"{response.status_code}: {response.text[:3000]}"
    return response.json()


def snapshot(asset_id, records):
    checked(client.post("/data-assets", json={
        "id": asset_id,
        "project_id": "default",
        "display_name": asset_id.replace("_", " ").title(),
        "asset_schema": {},
        "records": records,
    }))
    return checked(client.post(
        f"/api/v1/datasets/{asset_id}/snapshots",
        json={"storage_format": "parquet"},
    ), 201)


def graph(graph_id, nodes, edges):
    checked(client.post("/pipeline-builder/graphs", json={
        "id": graph_id,
        "project_id": "default",
        "display_name": graph_id.replace("_", " ").title(),
        "nodes": nodes,
        "edges": edges,
    }), 201)
    return checked(client.post(
        f"/api/v1/pipelines/{graph_id}/plans",
        json={"executor": "duckdb"},
    ), 201)


def preview(plan, key, limit=100):
    job = checked(client.post(f"/api/v1/pipeline-plans/{plan['id']}/execute", json={
        "mode": "preview", "limit": limit, "idempotency_key": key,
    }), 202)["execution"]
    return checked(client.post("/pipeline-builder/workers/run-next", json={
        "worker_id": "duckdb-advanced-worker", "job_id": job["id"],
    }))


assets = snapshot("advanced_snapshot_assets", [
    {"asset_id": "a1", "facility": " west ", "temperature": "91.5", "latitude": 37.7749, "longitude": -122.4194, "reading": 3},
    {"asset_id": "a2", "facility": None, "temperature": "70", "latitude": 37.7750, "longitude": -122.4195, "reading": 4},
    {"asset_id": "a3", "facility": "east", "temperature": "120", "latitude": 40.0, "longitude": -100.0, "reading": 5},
    {"asset_id": "a4", "facility": " west ", "temperature": "55", "latitude": 37.7751, "longitude": -122.4196, "reading": 2},
])

advanced_nodes = [
    {"id": "input", "type": "input_dataset", "config": {
        "asset_id": "advanced_snapshot_assets", "snapshot_id": assets["id"],
    }},
    {"id": "cast", "type": "cast", "config": {"mapping": {"temperature": "number"}}},
    {"id": "fill", "type": "fill_nulls", "config": {"defaults": {"facility": "unknown"}}},
    {"id": "normalize", "type": "normalize", "config": {"fields": ["facility"], "mode": "title"}},
    {"id": "identity", "type": "unique_id", "config": {"fields": ["asset_id", "facility"], "target_field": "row_id"}},
    {"id": "geo", "type": "derive_geo_point", "config": {
        "latitude_field": "latitude", "longitude_field": "longitude", "target_field": "geometry",
    }},
    {"id": "radius", "type": "spatial_filter", "config": {
        "mode": "radius", "geometry_field": "geometry",
        "center": {"latitude": 37.7749, "longitude": -122.4194}, "radius_meters": 500,
    }},
    {"id": "window", "type": "window", "config": {
        "order_by": "asset_id", "operation": "running_sum", "field": "reading", "target_field": "running_reading",
    }},
    {"id": "validate", "type": "validate", "config": {
        "checks": [{"type": "range", "field": "temperature", "min": 60, "max": 100}],
        "on_error": "annotate",
    }},
    {"id": "output", "type": "dataset_output", "config": {"asset_id": "advanced_snapshot_output"}},
]
advanced_edges = [
    {"source": advanced_nodes[index]["id"], "target": advanced_nodes[index + 1]["id"]}
    for index in range(len(advanced_nodes) - 1)
]
advanced_plan = graph("advanced_snapshot_graph", advanced_nodes, advanced_edges)
advanced_run = preview(advanced_plan, "advanced-snapshot-preview")
assert advanced_run["job"]["status"] == "SUCCEEDED", advanced_run
advanced_rows = advanced_run["result"]["rows"]
assert [row["asset_id"] for row in advanced_rows] == ["a1", "a2", "a4"]
assert [row["running_reading"] for row in advanced_rows] == [3, 7, 9]
assert advanced_rows[0]["facility"] == "West" and advanced_rows[1]["facility"] == "Unknown", advanced_rows
assert all(len(row["row_id"]) == 16 for row in advanced_rows)
assert advanced_rows[0]["geometry"]["type"] == "Point"
assert advanced_rows[0]["_validation_errors"] == []
assert advanced_rows[2]["_validation_errors"] == ["temperature failed range validation"]

failing_nodes = [
    advanced_nodes[0],
    advanced_nodes[1],
    {"id": "validate", "type": "validate", "config": {
        "checks": [{"type": "range", "field": "temperature", "min": 60, "max": 100}],
        "on_error": "fail",
    }},
]
failing_plan = graph("failing_snapshot_validation", failing_nodes, [
    {"source": "input", "target": "cast"}, {"source": "cast", "target": "validate"},
])
failing_run = preview(failing_plan, "failing-snapshot-preview")
assert failing_run["job"]["status"] == "FAILED", failing_run
assert "temperature failed range validation" in failing_run["job"]["error"]

drop_nodes = [
    advanced_nodes[0],
    advanced_nodes[1],
    {"id": "validate", "type": "validate", "config": {
        "checks": [{"type": "range", "field": "temperature", "min": 60, "max": 100}],
        "on_error": "drop",
    }},
]
drop_plan = graph("dropping_snapshot_validation", drop_nodes, [
    {"source": "input", "target": "cast"}, {"source": "cast", "target": "validate"},
])
drop_rows = preview(drop_plan, "dropping-snapshot-preview")["result"]["rows"]
assert [row["asset_id"] for row in drop_rows] == ["a1", "a2"]

pivot_snapshot = snapshot("advanced_snapshot_metrics", [
    {"asset": "a1", "metric": "temperature", "value": 90},
    {"asset": "a1", "metric": "vibration", "value": 8},
    {"asset": "a2", "metric": "temperature", "value": 70},
    {"asset": "a2", "metric": "vibration", "value": 4},
])
pivot_nodes = [
    {"id": "input", "type": "input_dataset", "config": {
        "asset_id": "advanced_snapshot_metrics", "snapshot_id": pivot_snapshot["id"],
    }},
    {"id": "pivot", "type": "pivot", "config": {
        "index": ["asset"], "column": "metric", "value": "value", "aggregation": "first",
    }},
    {"id": "unpivot", "type": "unpivot", "config": {
        "id_fields": ["asset"], "value_fields": ["temperature", "vibration"],
        "name_field": "metric_name", "value_field": "metric_value",
    }},
]
pivot_plan = graph("advanced_snapshot_pivot", pivot_nodes, [
    {"source": "input", "target": "pivot"}, {"source": "pivot", "target": "unpivot"},
])
pivot_rows = preview(pivot_plan, "advanced-pivot-preview")["result"]["rows"]
assert len(pivot_rows) == 4
assert {row["metric_name"] for row in pivot_rows} == {"temperature", "vibration"}

facilities = snapshot("advanced_snapshot_facilities", [
    {"facility_id": "f1", "latitude": 37.77495, "longitude": -122.41945},
    {"facility_id": "f2", "latitude": 36.0, "longitude": -120.0},
])
spatial_nodes = [
    {"id": "assets", "type": "input_dataset", "config": {
        "asset_id": "advanced_snapshot_assets", "snapshot_id": assets["id"],
    }},
    {"id": "asset_geo", "type": "derive_geo_point", "config": {}},
    {"id": "facilities", "type": "input_dataset", "config": {
        "asset_id": "advanced_snapshot_facilities", "snapshot_id": facilities["id"],
    }},
    {"id": "facility_geo", "type": "derive_geo_point", "config": {}},
    {"id": "spatial", "type": "spatial_join", "config": {
        "left_geometry_field": "geometry", "right_geometry_field": "geometry",
        "max_distance_meters": 200,
    }},
]
spatial_plan = graph("advanced_snapshot_spatial_join", spatial_nodes, [
    {"source": "assets", "target": "asset_geo"},
    {"source": "facilities", "target": "facility_geo"},
    {"source": "asset_geo", "target": "spatial"},
    {"source": "facility_geo", "target": "spatial"},
])
spatial_run = preview(spatial_plan, "advanced-spatial-preview")
assert spatial_run["job"]["status"] == "SUCCEEDED", spatial_run
spatial_rows = spatial_run["result"]["rows"]
assert {row["asset_id"] for row in spatial_rows} == {"a1", "a2", "a4"}
assert all(row["facility_id"] == "f1" for row in spatial_rows)
assert all(row["distance_meters"] <= 200 for row in spatial_rows)
assert set(spatial_run["result"]["source_snapshot_ids"]) == {assets["id"], facilities["id"]}

sf_polygon = {
    "type": "Polygon",
    "coordinates": [[
        [-122.4210, 37.7740], [-122.4180, 37.7740],
        [-122.4180, 37.7760], [-122.4210, 37.7760],
        [-122.4210, 37.7740],
    ]],
}
mgrs_geofence_nodes = [
    {"id": "input", "type": "input_dataset", "config": {
        "asset_id": "advanced_snapshot_assets", "snapshot_id": assets["id"],
    }},
    {"id": "geo", "type": "derive_geo_point", "config": {}},
    {"id": "mgrs", "type": "derive_mgrs", "config": {"precision": 5}},
    {"id": "geofence", "type": "spatial_filter", "config": {
        "mode": "geofence", "geometry_field": "geometry", "polygon": sf_polygon,
    }},
]
mgrs_geofence_plan = graph("advanced_snapshot_mgrs_geofence", mgrs_geofence_nodes, [
    {"source": "input", "target": "geo"},
    {"source": "geo", "target": "mgrs"},
    {"source": "mgrs", "target": "geofence"},
])
mgrs_geofence_run = preview(mgrs_geofence_plan, "advanced-mgrs-geofence-preview")
assert mgrs_geofence_run["job"]["status"] == "SUCCEEDED", mgrs_geofence_run
mgrs_geofence_rows = mgrs_geofence_run["result"]["rows"]
assert {row["asset_id"] for row in mgrs_geofence_rows} == {"a1", "a2", "a4"}, mgrs_geofence_rows
for row in mgrs_geofence_rows:
    expected = checked(client.post("/gis/mgrs/encode", json={
        "latitude": row["latitude"], "longitude": row["longitude"], "precision": 5,
    }))
    assert row["mgrs"] == expected["mgrs"], (row, expected)

polygon_with_hole = {
    **sf_polygon,
    "coordinates": [
        sf_polygon["coordinates"][0],
        [[-122.41946, 37.77484], [-122.41934, 37.77484],
         [-122.41934, 37.77496], [-122.41946, 37.77496],
         [-122.41946, 37.77484]],
    ],
}
hole_nodes = [
    mgrs_geofence_nodes[0], mgrs_geofence_nodes[1],
    {"id": "geofence", "type": "spatial_filter", "config": {
        "mode": "polygon", "geometry_field": "geometry", "polygon": polygon_with_hole,
    }},
]
hole_plan = graph("advanced_snapshot_polygon_hole", hole_nodes, [
    {"source": "input", "target": "geo"}, {"source": "geo", "target": "geofence"},
])
hole_rows = preview(hole_plan, "advanced-polygon-hole-preview")["result"]["rows"]
assert {row["asset_id"] for row in hole_rows} == {"a2", "a4"}, hole_rows

invalid_mgrs_plan = graph("invalid_snapshot_mgrs", [
    mgrs_geofence_nodes[0],
    {"id": "mgrs", "type": "derive_mgrs", "config": {"precision": 6}},
], [{"source": "input", "target": "mgrs"}])
invalid_mgrs_run = preview(invalid_mgrs_plan, "invalid-mgrs-preview")
assert invalid_mgrs_run["job"]["status"] == "FAILED", invalid_mgrs_run
assert "precision must be between 0 and 5" in invalid_mgrs_run["job"]["error"]

print("DuckDB SQL-native advanced snapshot transforms verified.")
from app.database import engine  # noqa: E402
engine.dispose()
tmpdir.cleanup()

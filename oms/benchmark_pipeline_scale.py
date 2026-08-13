"""Benchmark snapshot-native DuckDB pipeline execution through public APIs."""

from __future__ import annotations

import json
import math
import os
import platform
import statistics
import tempfile
import time
from pathlib import Path
from tier_b_evidence import build_evidence_provenance


PROFILE = os.getenv("PIPELINE_SCALE_PROFILE", "smoke").strip().lower()
if PROFILE not in {"smoke", "reference"}:
    raise SystemExit("PIPELINE_SCALE_PROFILE must be 'smoke' or 'reference'")
REFERENCE_ROWS = 10_000_000
default_rows = REFERENCE_ROWS if PROFILE == "reference" else 1_000_000
ROW_COUNT = int(os.getenv("PIPELINE_SCALE_ROWS", str(default_rows)))
SAMPLES = int(os.getenv("PIPELINE_SCALE_SAMPLES", "5"))
WARMUPS = int(os.getenv("PIPELINE_SCALE_WARMUPS", "1"))
PREVIEW_P95_LIMIT_MS = float(os.getenv("PIPELINE_PREVIEW_P95_LIMIT_MS", "30000"))
DELIVER_LIMIT_MS = float(os.getenv("PIPELINE_DELIVER_LIMIT_MS", "60000"))
EVIDENCE_PATH = os.getenv("PIPELINE_SCALE_EVIDENCE_PATH")
GATE_EVIDENCE_DIR = os.getenv("PIPELINE_SCALE_GATE_EVIDENCE_DIR")
PARTITION_COUNT = int(os.getenv("PIPELINE_SCALE_PARTITIONS", "8"))
PIVOT_CARDINALITY = int(os.getenv(
    "PIPELINE_SCALE_PIVOT_CARDINALITY",
    "512" if PROFILE == "reference" else "64",
))
COMPLEX_PREVIEW_LIMIT_MS = float(os.getenv("PIPELINE_COMPLEX_PREVIEW_LIMIT_MS", "60000"))
COMPLEX_DELIVER_LIMIT_MS = float(os.getenv("PIPELINE_COMPLEX_DELIVER_LIMIT_MS", "90000"))
GEOFENCE_OUTER_VERTICES = int(os.getenv(
    "PIPELINE_SCALE_GEOFENCE_VERTICES",
    "8192" if PROFILE == "reference" else "2048",
))
GEOFENCE_HOLE_VERTICES = max(16, GEOFENCE_OUTER_VERTICES // 8)

if ROW_COUNT < 1000 or ROW_COUNT % 100 != 0 or SAMPLES < 3:
    raise SystemExit("Pipeline rows must be >= 1,000 and divisible by 100; samples must be >= 3")
if PARTITION_COUNT < 1 or PARTITION_COUNT > 128 or ROW_COUNT % PARTITION_COUNT != 0:
    raise SystemExit("Pipeline partitions must be 1-128 and divide the row count exactly")
if PIVOT_CARDINALITY < 16 or PIVOT_CARDINALITY > 2048:
    raise SystemExit("Pipeline pivot cardinality must be between 16 and 2,048")
if GEOFENCE_OUTER_VERTICES < 256 or GEOFENCE_OUTER_VERTICES + GEOFENCE_HOLE_VERTICES + 2 > 10_000:
    raise SystemExit("Pipeline geofence must contain 256-9,998 vertices including its hole")
if PROFILE == "reference" and ROW_COUNT < REFERENCE_ROWS:
    raise SystemExit("Reference profile requires at least 10,000,000 rows")

tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
root = Path(tmpdir.name)
snapshot_root = root / "snapshots"
snapshot_root.mkdir(parents=True, exist_ok=True)
os.environ["DATABASE_URL"] = f"sqlite:///{(root / 'pipeline_scale.db').as_posix()}"
os.environ["DATA_SNAPSHOT_ROOT"] = str(snapshot_root)
os.environ["AUTH_MODE"] = "local"
os.environ["APP_ENV"] = "test"

import duckdb  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from app.main import app  # noqa: E402


client = TestClient(app)


def checked(response, expected=200):
    assert response.status_code == expected, f"{response.status_code}: {response.text[:3000]}"
    return response.json()


def percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    return ordered[max(0, min(len(ordered) - 1, math.ceil(len(ordered) * fraction) - 1))]


def ellipse_ring(
    center_lon: float,
    center_lat: float,
    longitude_radius: float,
    latitude_radius: float,
    vertices: int,
) -> list[list[float]]:
    ring = [
        [
            center_lon + longitude_radius * math.cos(2 * math.pi * index / vertices),
            center_lat + latitude_radius * math.sin(2 * math.pi * index / vertices),
        ]
        for index in range(vertices)
    ]
    return [*ring, ring[0]]


high_vertex_geofence = {
    "type": "Polygon",
    "coordinates": [
        # Generated telemetry spans a narrow diagonal. This operational fence
        # selects its center instead of becoming an all-pass decoration, so
        # the pipeline proves predicate selectivity before costly projection.
        ellipse_ring(-122.4199, 37.7754, 0.00036, 0.00036, GEOFENCE_OUTER_VERTICES),
        # A small central exclusion proves exact hole semantics at scale.
        ellipse_ring(-122.4199, 37.7754, 0.00003, 0.00003, GEOFENCE_HOLE_VERTICES),
    ],
}
GEOFENCE_VERTEX_COUNT = sum(len(ring) for ring in high_vertex_geofence["coordinates"])


def in_ellipse(longitude: float, latitude: float, radius: float) -> bool:
    return (
        ((longitude + 122.4199) / radius) ** 2
        + ((latitude - 37.7754) / radius) ** 2
    ) < 1.0


selected_coordinate_buckets = [
    bucket for bucket in range(1000)
    if bucket % 100 >= 50
    and in_ellipse(-122.4194 - bucket * 0.000001, 37.7749 + bucket * 0.000001, 0.00036)
    and not in_ellipse(-122.4194 - bucket * 0.000001, 37.7749 + bucket * 0.000001, 0.00003)
]
EXPECTED_GEOFENCE_ROWS = len(selected_coordinate_buckets) * (ROW_COUNT // 1000)


input_dir = snapshot_root / "default" / "pipeline_scale_input"
input_dir.mkdir(parents=True, exist_ok=True)
right_dir = snapshot_root / "default" / "pipeline_scale_right"
right_dir.mkdir(parents=True, exist_ok=True)
dimension_dir = snapshot_root / "default" / "pipeline_scale_categories"
dimension_dir.mkdir(parents=True, exist_ok=True)
dimension_path = dimension_dir / "categories.parquet"
generate_started = time.perf_counter()
connection = duckdb.connect(database=":memory:")
try:
    connection.execute("SET preserve_insertion_order = false")
    connection.execute("SET threads = 4")
    rows_per_partition = ROW_COUNT // PARTITION_COUNT
    for partition in range(PARTITION_COUNT):
        start = partition * rows_per_partition + 1
        end = start + rows_per_partition
        input_path = input_dir / f"part-{partition:04d}.parquet"
        right_path = right_dir / f"part-{partition:04d}.parquet"
        connection.execute(f"""
            COPY (
                SELECT
                    'asset_' || lpad(CAST(row_number AS VARCHAR), 10, '0') AS asset_id,
                    'category_' || CAST(row_number % 20 AS VARCHAR) AS category,
                    CAST(row_number % 100 AS DOUBLE) AS score,
                    1.5::DOUBLE AS weight,
                    37.7749 + CAST(row_number % 1000 AS DOUBLE) * 0.000001 AS latitude,
                    -122.4194 - CAST(row_number % 1000 AS DOUBLE) * 0.000001 AS longitude,
                    1700000000 + (row_number % 1000000) AS event_time
                FROM range({start}, {end}) AS generated(row_number)
            ) TO '{input_path.as_posix()}' (
                FORMAT PARQUET, COMPRESSION ZSTD, ROW_GROUP_SIZE 122880
            )
        """)
        connection.execute(f"""
            COPY (
                SELECT
                    'asset_' || lpad(CAST(row_number AS VARCHAR), 10, '0') AS asset_id,
                    CASE WHEN row_number % 5 = 0 THEN 'critical' ELSE 'standard' END AS maintenance_tier,
                    'metric_' || lpad(CAST(row_number % {PIVOT_CARDINALITY} AS VARCHAR), 4, '0') AS metric_bucket,
                    CAST((row_number % 100) + 1 AS DOUBLE) AS metric_value
                FROM range({start}, {end}) AS generated(row_number)
            ) TO '{right_path.as_posix()}' (
                FORMAT PARQUET, COMPRESSION ZSTD, ROW_GROUP_SIZE 122880
            )
        """)
    connection.execute(f"""
        COPY (
            SELECT
                'category_' || CAST(category_number AS VARCHAR) AS category,
                CASE WHEN category_number < 5 THEN 'critical' ELSE 'standard' END AS maintenance_tier,
                true AS active
            FROM range(0, 20) AS categories(category_number)
        ) TO '{dimension_path.as_posix()}' (FORMAT PARQUET, COMPRESSION ZSTD)
    """)
finally:
    connection.close()
generate_seconds = time.perf_counter() - generate_started

checked(client.post("/data-assets", json={
    "id": "pipeline_scale_input",
    "project_id": "default",
    "display_name": "Pipeline scale input",
    "asset_schema": {},
    "records": [],
}))
snapshot = checked(client.post(
    "/api/v1/datasets/pipeline_scale_input/snapshots/register",
    json={
        "storage_uri": input_dir.as_uri(),
        "storage_format": "parquet",
        "partition_spec": {"partition_count": PARTITION_COUNT},
        "lineage": {"benchmark_profile": PROFILE, "generator": "duckdb-range"},
    },
), 201)
assert snapshot["row_count"] == ROW_COUNT
assert snapshot["partition_spec"]["_manifest"]["file_count"] == PARTITION_COUNT
assert snapshot["byte_size"] == sum(path.stat().st_size for path in input_dir.glob("*.parquet"))

checked(client.post("/data-assets", json={
    "id": "pipeline_scale_right",
    "project_id": "default",
    "display_name": "Pipeline scale large join input",
    "asset_schema": {},
    "records": [],
}))
right_snapshot = checked(client.post(
    "/api/v1/datasets/pipeline_scale_right/snapshots/register",
    json={
        "storage_uri": right_dir.as_uri(),
        "storage_format": "parquet",
        "partition_spec": {"partition_count": PARTITION_COUNT},
        "lineage": {"benchmark_profile": PROFILE, "generator": "duckdb-range-large-join"},
    },
), 201)
assert right_snapshot["row_count"] == ROW_COUNT
assert right_snapshot["partition_spec"]["_manifest"]["file_count"] == PARTITION_COUNT
assert right_snapshot["byte_size"] == sum(path.stat().st_size for path in right_dir.glob("*.parquet"))

checked(client.post("/data-assets", json={
    "id": "pipeline_scale_categories",
    "project_id": "default",
    "display_name": "Pipeline scale categories",
    "asset_schema": {},
    "records": [],
}))
dimension_snapshot = checked(client.post(
    "/api/v1/datasets/pipeline_scale_categories/snapshots/register",
    json={
        "storage_uri": dimension_path.as_uri(),
        "storage_format": "parquet",
        "lineage": {"benchmark_profile": PROFILE, "generator": "duckdb-range-dimension"},
    },
), 201)
assert dimension_snapshot["row_count"] == 20

nodes = [
    {"id": "input", "type": "input_dataset", "config": {
        "asset_id": "pipeline_scale_input", "snapshot_id": snapshot["id"],
    }},
    {"id": "filter", "type": "filter", "config": {
        "field": "score", "operator": "gte", "value": 50,
    }},
    {"id": "geofence", "type": "spatial_filter", "config": {
        "mode": "geofence", "latitude_field": "latitude",
        "longitude_field": "longitude", "polygon": high_vertex_geofence,
    }},
    {"id": "identity", "type": "unique_id", "config": {
        "fields": ["asset_id", "event_time"], "target_field": "event_id",
    }},
    {"id": "geo", "type": "derive_geo_point", "config": {
        "latitude_field": "latitude", "longitude_field": "longitude", "target_field": "geometry",
    }},
    {"id": "radius", "type": "spatial_filter", "config": {
        "mode": "radius", "geometry_field": "geometry",
        "center": {"latitude": 37.7749, "longitude": -122.4194}, "radius_meters": 500,
    }},
    {"id": "mgrs", "type": "derive_mgrs", "config": {
        "latitude_field": "latitude", "longitude_field": "longitude",
        "target_field": "mgrs", "precision": 5,
    }},
    {"id": "categories", "type": "input_dataset", "config": {
        "asset_id": "pipeline_scale_categories", "snapshot_id": dimension_snapshot["id"],
    }},
    {"id": "join", "type": "join", "config": {
        "left_key": "category", "right_key": "category", "how": "inner",
    }},
    {"id": "window", "type": "window", "config": {
        "partition_by": ["category"], "order_by": "event_time",
        "operation": "row_number", "target_field": "event_sequence",
    }},
    {"id": "derive", "type": "derive", "config": {
        "target_field": "weighted_score", "operation": "multiply",
        "source_fields": ["score", "weight"],
    }},
    {"id": "aggregate", "type": "aggregate", "config": {
        "group_by": ["category"],
        "metrics": [
            {"operation": "count", "alias": "asset_count"},
            {"operation": "avg", "field": "weighted_score", "alias": "average_weighted_score"},
            {"operation": "max", "field": "event_time", "alias": "latest_event_time"},
        ],
    }},
    {"id": "sort", "type": "sort", "config": {
        "field": "asset_count", "direction": "desc",
    }},
    {"id": "output", "type": "dataset_output", "config": {
        "asset_id": "pipeline_scale_output", "partition_by": ["category"],
    }},
]
edges = [
    {"id": "edge_input_filter", "source": "input", "target": "filter"},
    {"id": "edge_filter_geofence", "source": "filter", "target": "geofence"},
    {"id": "edge_geofence_identity", "source": "geofence", "target": "identity"},
    {"id": "edge_identity_geo", "source": "identity", "target": "geo"},
    {"id": "edge_geo_radius", "source": "geo", "target": "radius"},
    {"id": "edge_radius_mgrs", "source": "radius", "target": "mgrs"},
    {"id": "edge_mgrs_join", "source": "mgrs", "target": "join"},
    {"id": "edge_categories_join", "source": "categories", "target": "join"},
    {"id": "edge_join_window", "source": "join", "target": "window"},
    {"id": "edge_window_derive", "source": "window", "target": "derive"},
    {"id": "edge_derive_aggregate", "source": "derive", "target": "aggregate"},
    {"id": "edge_aggregate_sort", "source": "aggregate", "target": "sort"},
    {"id": "edge_sort_output", "source": "sort", "target": "output"},
]
checked(client.post("/pipeline-builder/graphs", json={
    "id": "pipeline_scale_graph",
    "project_id": "default",
    "display_name": "Pipeline scale graph",
    "nodes": nodes,
    "edges": edges,
}), 201)
plan = checked(client.post(
    "/api/v1/pipelines/pipeline_scale_graph/plans", json={"executor": "duckdb"},
), 201)
assert plan["status"] == "VALID" and plan["executor"] == "duckdb"
assert plan["field_lineage"]["score"][0]["snapshot_id"] == snapshot["id"]


def execute_preview(iteration: int) -> tuple[float, dict]:
    queued = checked(client.post(f"/api/v1/pipeline-plans/{plan['id']}/execute", json={
        "mode": "preview",
        "limit": 100,
        "idempotency_key": f"pipeline-scale-preview-{iteration}",
    }), 202)["execution"]
    started = time.perf_counter()
    run = checked(client.post("/pipeline-builder/workers/run-next", json={
        "worker_id": "pipeline-scale-worker", "job_id": queued["id"],
    }))
    elapsed_ms = (time.perf_counter() - started) * 1000
    assert run["job"]["status"] == "SUCCEEDED", run
    result = run["result"]
    assert result["engine"] == "duckdb-snapshot"
    assert result["input_row_count"] == ROW_COUNT + 20
    assert set(result["source_snapshot_ids"]) == {snapshot["id"], dimension_snapshot["id"]}
    assert result["row_count"] == 20
    assert len(result["rows"]) == 20
    assert sum(row["asset_count"] for row in result["rows"]) == EXPECTED_GEOFENCE_ROWS
    assert result["metrics"]["materialized_python_rows"] == 20
    return elapsed_ms, result


for warmup in range(WARMUPS):
    execute_preview(-(warmup + 1))

preview_latencies = []
last_preview = None
for sample in range(SAMPLES):
    latency, last_preview = execute_preview(sample)
    preview_latencies.append(latency)

delivery = checked(client.post(f"/api/v1/pipeline-plans/{plan['id']}/execute", json={
    "mode": "deliver",
    "output_asset_id": "pipeline_scale_output",
    "idempotency_key": "pipeline-scale-deliver",
}), 202)["execution"]
deliver_started = time.perf_counter()
delivery_run = checked(client.post("/pipeline-builder/workers/run-next", json={
    "worker_id": "pipeline-scale-worker", "job_id": delivery["id"],
}))
deliver_ms = (time.perf_counter() - deliver_started) * 1000
assert delivery_run["job"]["status"] == "SUCCEEDED", delivery_run
delivered = delivery_run["result"]
assert delivered["row_count"] == 20 and delivered["rows"] == []
assert delivered["output_snapshot"]["row_count"] == 20
assert delivered["output_snapshot"]["partition_spec"]["fields"] == ["category"]
assert delivered["output_snapshot"]["partition_spec"]["hive_partitioning"] is True
assert delivered["output_snapshot"]["partition_spec"]["_manifest"]["file_count"] == 20
assert delivered["output_snapshot"]["lineage"]["source_snapshot_id"] == snapshot["id"]
assert set(delivered["output_snapshot"]["lineage"]["source_snapshot_ids"]) == {
    snapshot["id"], dimension_snapshot["id"],
}

# A second plan closes the easy-dimension-join blind spot in the baseline. Both
# join sides contain ROW_COUNT rows, the joined result is unioned with a second
# large branch, and the full stream is reshaped into a wide result. The output
# remains bounded, but execution must scan and combine bulk snapshots inside
# DuckDB rather than materializing either branch in Python.
complex_nodes = [
    {"id": "facts", "type": "input_dataset", "config": {
        "asset_id": "pipeline_scale_input", "snapshot_id": snapshot["id"],
    }},
    {"id": "measurements", "type": "input_dataset", "config": {
        "asset_id": "pipeline_scale_right", "snapshot_id": right_snapshot["id"],
    }},
    {"id": "large_join", "type": "join", "config": {
        "left_key": "asset_id", "right_key": "asset_id", "how": "inner",
    }},
    {"id": "large_union", "type": "union", "config": {}},
    {"id": "wide_pivot", "type": "pivot", "config": {
        "index": ["maintenance_tier"], "column": "metric_bucket",
        "value": "metric_value", "operation": "sum",
    }},
    {"id": "complex_output", "type": "dataset_output", "config": {
        "asset_id": "pipeline_complex_scale_output", "partition_by": ["maintenance_tier"],
    }},
]
complex_edges = [
    {"id": "edge_facts_join", "source": "facts", "target": "large_join"},
    {"id": "edge_measurements_join", "source": "measurements", "target": "large_join"},
    # Edge order fixes the joined relation as the union's left branch while the
    # raw measurements relation exercises UNION ALL BY NAME on the right.
    {"id": "edge_join_union", "source": "large_join", "target": "large_union"},
    {"id": "edge_measurements_union", "source": "measurements", "target": "large_union"},
    {"id": "edge_union_pivot", "source": "large_union", "target": "wide_pivot"},
    {"id": "edge_pivot_output", "source": "wide_pivot", "target": "complex_output"},
]
checked(client.post("/pipeline-builder/graphs", json={
    "id": "pipeline_complex_scale_graph",
    "project_id": "default",
    "display_name": "Large join, union, and wide pivot scale graph",
    "nodes": complex_nodes,
    "edges": complex_edges,
}), 201)
complex_plan = checked(client.post(
    "/api/v1/pipelines/pipeline_complex_scale_graph/plans", json={"executor": "duckdb"},
), 201)
assert complex_plan["status"] == "VALID" and complex_plan["executor"] == "duckdb"

complex_preview_job = checked(client.post(
    f"/api/v1/pipeline-plans/{complex_plan['id']}/execute",
    json={
        "mode": "preview", "limit": 10,
        "idempotency_key": "pipeline-complex-scale-preview",
    },
), 202)["execution"]
complex_preview_started = time.perf_counter()
complex_preview_run = checked(client.post("/pipeline-builder/workers/run-next", json={
    "worker_id": "pipeline-complex-scale-worker", "job_id": complex_preview_job["id"],
}))
complex_preview_ms = (time.perf_counter() - complex_preview_started) * 1000
assert complex_preview_run["job"]["status"] == "SUCCEEDED", complex_preview_run
complex_preview = complex_preview_run["result"]
assert complex_preview["input_row_count"] == ROW_COUNT * 2
assert set(complex_preview["source_snapshot_ids"]) == {snapshot["id"], right_snapshot["id"]}
assert complex_preview["row_count"] == 2 and len(complex_preview["rows"]) == 2
assert complex_preview["metrics"]["materialized_python_rows"] == 2
assert len(complex_preview["schema"]["fields"]) == PIVOT_CARDINALITY + 1
assert complex_preview_ms < COMPLEX_PREVIEW_LIMIT_MS, {
    "complex_preview_ms": complex_preview_ms, "limit_ms": COMPLEX_PREVIEW_LIMIT_MS,
}

complex_delivery_job = checked(client.post(
    f"/api/v1/pipeline-plans/{complex_plan['id']}/execute",
    json={
        "mode": "deliver", "output_asset_id": "pipeline_complex_scale_output",
        "idempotency_key": "pipeline-complex-scale-deliver",
    },
), 202)["execution"]
complex_deliver_started = time.perf_counter()
complex_delivery_run = checked(client.post("/pipeline-builder/workers/run-next", json={
    "worker_id": "pipeline-complex-scale-worker", "job_id": complex_delivery_job["id"],
}))
complex_deliver_ms = (time.perf_counter() - complex_deliver_started) * 1000
assert complex_delivery_run["job"]["status"] == "SUCCEEDED", complex_delivery_run
complex_delivered = complex_delivery_run["result"]
assert complex_delivered["row_count"] == 2 and complex_delivered["rows"] == []
assert complex_delivered["output_snapshot"]["partition_spec"]["fields"] == ["maintenance_tier"]
assert complex_delivered["output_snapshot"]["partition_spec"]["_manifest"]["file_count"] == 2
assert set(complex_delivered["output_snapshot"]["lineage"]["source_snapshot_ids"]) == {
    snapshot["id"], right_snapshot["id"],
}
assert complex_deliver_ms < COMPLEX_DELIVER_LIMIT_MS, {
    "complex_deliver_ms": complex_deliver_ms, "limit_ms": COMPLEX_DELIVER_LIMIT_MS,
}

from app.data_plane import execute_duckdb_snapshot_plan  # noqa: E402
from app.database import SessionLocal  # noqa: E402

with SessionLocal() as replay_db:
    complex_replay = execute_duckdb_snapshot_plan(
        replay_db,
        complex_plan["id"],
        mode="deliver",
        limit=10,
        output_asset_id="pipeline_complex_scale_output",
        parameters={},
        actor="local-user",
        execution_job_id=complex_delivery_job["id"],
    )
assert complex_replay["idempotent_replay"] is True
assert complex_replay["output_snapshot"]["id"] == complex_delivered["output_snapshot"]["id"]

preview_p95 = percentile(preview_latencies, 0.95)
assert preview_p95 < PREVIEW_P95_LIMIT_MS, {
    "preview_p95_ms": preview_p95, "limit_ms": PREVIEW_P95_LIMIT_MS,
}
assert deliver_ms < DELIVER_LIMIT_MS, {
    "deliver_ms": deliver_ms, "limit_ms": DELIVER_LIMIT_MS,
}

evidence = {
    "provenance": build_evidence_provenance(
        "oms/benchmark_pipeline_scale.py",
        entry_points=[
            "POST /data-assets",
            "POST /pipeline-builder/graphs",
            "POST /pipeline-builder/workers/run-next",
        ],
        request_shapes=[
            "partitioned dataset registration",
            "compiled pipeline graph preview",
            "worker-driven partitioned delivery",
            "large join/union/pivot execution",
            "parameterized polygon geofence",
        ],
    ),
    "profile": PROFILE,
    "reference_scale_achieved": ROW_COUNT >= REFERENCE_ROWS,
    "input_rows": ROW_COUNT,
    "input_partitions": PARTITION_COUNT,
    "dimension_rows": 20,
    "scanned_rows": ROW_COUNT + 20,
    "filtered_rows": ROW_COUNT // 2,
    "geofence_output_rows": EXPECTED_GEOFENCE_ROWS,
    "output_rows": 20,
    "operations": [node["type"] for node in nodes],
    "samples": SAMPLES,
    "generate_seconds": round(generate_seconds, 3),
    "input_parquet_bytes": snapshot["byte_size"],
    "large_join_right_rows": ROW_COUNT,
    "large_join_right_parquet_bytes": right_snapshot["byte_size"],
    "preview_p50_ms": round(statistics.median(preview_latencies), 3),
    "preview_p95_ms": round(preview_p95, 3),
    "preview_limit_ms": PREVIEW_P95_LIMIT_MS,
    "deliver_ms": round(deliver_ms, 3),
    "deliver_limit_ms": DELIVER_LIMIT_MS,
    "output_parquet_bytes": delivered["output_snapshot"]["byte_size"],
    "output_partitions": delivered["output_snapshot"]["partition_spec"]["_manifest"]["file_count"],
    "materialized_python_rows": last_preview["metrics"]["materialized_python_rows"],
    "complex_operations": [node["type"] for node in complex_nodes],
    "complex_join_left_rows": ROW_COUNT,
    "complex_join_right_rows": ROW_COUNT,
    "complex_union_rows": ROW_COUNT * 2,
    "complex_pivot_cardinality": PIVOT_CARDINALITY,
    "complex_output_rows": complex_delivered["row_count"],
    "complex_output_columns": len(complex_preview["schema"]["fields"]),
    "complex_preview_ms": round(complex_preview_ms, 3),
    "complex_preview_limit_ms": COMPLEX_PREVIEW_LIMIT_MS,
    "complex_deliver_ms": round(complex_deliver_ms, 3),
    "complex_deliver_limit_ms": COMPLEX_DELIVER_LIMIT_MS,
    "complex_materialized_python_rows": complex_preview["metrics"]["materialized_python_rows"],
    "complex_idempotent_replay": complex_replay["idempotent_replay"],
    "complex_plan_id": complex_plan["id"],
    "complex_plan_hash": complex_plan["plan_hash"],
    "complex_output_snapshot_id": complex_delivered["output_snapshot"]["id"],
    "geofence_outer_vertices": GEOFENCE_OUTER_VERTICES,
    "geofence_hole_vertices": GEOFENCE_HOLE_VERTICES,
    "geofence_total_positions": GEOFENCE_VERTEX_COUNT,
    "geofence_parameterized_edges": True,
    "plan_id": plan["id"],
    "plan_hash": plan["plan_hash"],
    "source_snapshot_id": snapshot["id"],
    "source_snapshot_ids": [snapshot["id"], dimension_snapshot["id"]],
    "output_snapshot_id": delivered["output_snapshot"]["id"],
    "host": {
        "platform": platform.platform(),
        "python": platform.python_version(),
        "processor": platform.processor(),
        "duckdb": duckdb.__version__,
    },
}
serialized = json.dumps(evidence, indent=2, sort_keys=True)
if EVIDENCE_PATH:
    Path(EVIDENCE_PATH).write_text(serialized + "\n", encoding="utf-8")
print("Snapshot-native pipeline scale benchmark passed:")
print(serialized)

# Gate evidence only for the reference profile. The smoke profile runs a tenth
# of the rows; letting it emit would overwrite a real reference PASS with a FAIL
# on every CI run.
if PROFILE == "reference":
    from tier_b_evidence import write_evidence

    gate_path, gate_status, gate_breaches = write_evidence(
        "pipeline_scale",
        thresholds={
            "input_rows_min": REFERENCE_ROWS,
            "output_partitions_min": 1,
            "preview_p95_ms_max": PREVIEW_P95_LIMIT_MS,
            "deliver_ms_max": DELIVER_LIMIT_MS,
            "complex_join_left_rows_min": REFERENCE_ROWS,
            "complex_join_right_rows_min": REFERENCE_ROWS,
            "complex_union_rows_min": REFERENCE_ROWS * 2,
            "complex_pivot_cardinality_min": 512,
            "complex_preview_ms_max": COMPLEX_PREVIEW_LIMIT_MS,
            "complex_deliver_ms_max": COMPLEX_DELIVER_LIMIT_MS,
            "complex_materialized_python_rows_max": evidence["complex_output_rows"],
            "complex_idempotent_replay_min": True,
            "geofence_outer_vertices_min": 8192,
            "geofence_total_positions_min": 9000,
            "geofence_parameterized_edges_min": True,
            # Bulk rows must stay in the engine. Hydrating them into Python is
            # the failure this benchmark exists to catch, so it is a gate
            # threshold rather than a note in the output.
            #
            # The bound is the output row count, not zero. This threshold was
            # first written as zero and that was an instrumentation error: the
            # metric is taken from the preview, where returning the aggregated
            # result to the caller is the point, and the benchmark has asserted
            # materialized_python_rows == 20 since before this gate existed.
            # Zero belongs to the delivery path, which test_duckdb_snapshot_
            # pipeline.py pins separately. The property meant here is that
            # materialization does not scale with input: 20 rows returned from
            # 10,000,000 scanned.
            "materialized_python_rows_max": evidence["output_rows"],
        },
        measurements={
            "input_rows": ROW_COUNT,
            "output_partitions": evidence["output_partitions"],
            "preview_p95_ms": evidence["preview_p95_ms"],
            "deliver_ms": evidence["deliver_ms"],
            "materialized_python_rows": evidence["materialized_python_rows"],
            "complex_join_left_rows": evidence["complex_join_left_rows"],
            "complex_join_right_rows": evidence["complex_join_right_rows"],
            "complex_union_rows": evidence["complex_union_rows"],
            "complex_pivot_cardinality": evidence["complex_pivot_cardinality"],
            "complex_preview_ms": evidence["complex_preview_ms"],
            "complex_deliver_ms": evidence["complex_deliver_ms"],
            "complex_materialized_python_rows": evidence["complex_materialized_python_rows"],
            "complex_idempotent_replay": evidence["complex_idempotent_replay"],
            "geofence_outer_vertices": evidence["geofence_outer_vertices"],
            "geofence_total_positions": evidence["geofence_total_positions"],
            "geofence_parameterized_edges": evidence["geofence_parameterized_edges"],
        },
        harness="oms/benchmark_pipeline_scale.py",
        # No observed_head: unlike the other scale gates this one does not
        # measure a migrated database. Line 39 points DATABASE_URL at a
        # throwaway SQLite file built by create_all, because the subject here
        # is DuckDB snapshot execution and the ontology store is incidental.
        # That file has no alembic_version, so any head reported for it would
        # be invented -- exactly the claim this argument exists to prevent.
        entry_points=[
            "POST /data-assets",
            "POST /pipeline-builder/graphs",
            "POST /pipeline-builder/workers/run-next",
        ],
        request_shapes=[
            "partitioned dataset registration",
            "compiled pipeline graph preview",
            "worker-driven partitioned delivery",
            "large-to-large join, schema-aligned union, and high-cardinality pivot",
            "parameterized high-vertex polygon with a hole",
            "idempotent complex-plan delivery replay",
        ],
        notes=(
            f"Reference profile over {ROW_COUNT} rows in {PARTITION_COUNT} immutable "
            f"partitions, delivered to {evidence['output_partitions']} output partitions; "
            f"the complex path joins two {ROW_COUNT}-row snapshots, unions {ROW_COUNT * 2} "
            f"rows, and pivots {PIVOT_CARDINALITY} metric columns without bulk Python materialization."
            f" The geofence evaluates {GEOFENCE_VERTEX_COUNT} positions through bound edge tables "
            "over distinct telemetry coordinates rather than parser-sized generated SQL."
        ),
        output_dir=Path(GATE_EVIDENCE_DIR) if GATE_EVIDENCE_DIR else None,
    )
    print(f"\nTier B evidence {gate_status}: {gate_path.name}")
    for breach in gate_breaches:
        print(f"  breach: {breach}")
else:
    print(f"\nProfile is '{PROFILE}'; no Tier B gate evidence written. "
          "Run with PIPELINE_SCALE_PROFILE=reference to attempt the gate.")

from app.database import engine  # noqa: E402
engine.dispose()
tmpdir.cleanup()

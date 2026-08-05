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
PARTITION_COUNT = int(os.getenv("PIPELINE_SCALE_PARTITIONS", "8"))

if ROW_COUNT < 1000 or ROW_COUNT % 100 != 0 or SAMPLES < 3:
    raise SystemExit("Pipeline rows must be >= 1,000 and divisible by 100; samples must be >= 3")
if PARTITION_COUNT < 1 or PARTITION_COUNT > 128 or ROW_COUNT % PARTITION_COUNT != 0:
    raise SystemExit("Pipeline partitions must be 1-128 and divide the row count exactly")
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


input_dir = snapshot_root / "default" / "pipeline_scale_input"
input_dir.mkdir(parents=True, exist_ok=True)
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
    {"id": "geofence", "type": "spatial_filter", "config": {
        "mode": "geofence", "geometry_field": "geometry", "polygon": {
            "type": "Polygon", "coordinates": [[
                [-122.421, 37.774], [-122.418, 37.774], [-122.418, 37.777],
                [-122.421, 37.777], [-122.421, 37.774],
            ]],
        },
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
    {"id": "edge_filter_identity", "source": "filter", "target": "identity"},
    {"id": "edge_identity_geo", "source": "identity", "target": "geo"},
    {"id": "edge_geo_radius", "source": "geo", "target": "radius"},
    {"id": "edge_radius_mgrs", "source": "radius", "target": "mgrs"},
    {"id": "edge_mgrs_geofence", "source": "mgrs", "target": "geofence"},
    {"id": "edge_geofence_join", "source": "geofence", "target": "join"},
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
    assert sum(row["asset_count"] for row in result["rows"]) == ROW_COUNT // 2
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

preview_p95 = percentile(preview_latencies, 0.95)
assert preview_p95 < PREVIEW_P95_LIMIT_MS, {
    "preview_p95_ms": preview_p95, "limit_ms": PREVIEW_P95_LIMIT_MS,
}
assert deliver_ms < DELIVER_LIMIT_MS, {
    "deliver_ms": deliver_ms, "limit_ms": DELIVER_LIMIT_MS,
}

evidence = {
    "profile": PROFILE,
    "reference_scale_achieved": ROW_COUNT >= REFERENCE_ROWS,
    "input_rows": ROW_COUNT,
    "input_partitions": PARTITION_COUNT,
    "dimension_rows": 20,
    "scanned_rows": ROW_COUNT + 20,
    "filtered_rows": ROW_COUNT // 2,
    "output_rows": 20,
    "operations": [node["type"] for node in nodes],
    "samples": SAMPLES,
    "generate_seconds": round(generate_seconds, 3),
    "input_parquet_bytes": snapshot["byte_size"],
    "preview_p50_ms": round(statistics.median(preview_latencies), 3),
    "preview_p95_ms": round(preview_p95, 3),
    "preview_limit_ms": PREVIEW_P95_LIMIT_MS,
    "deliver_ms": round(deliver_ms, 3),
    "deliver_limit_ms": DELIVER_LIMIT_MS,
    "output_parquet_bytes": delivered["output_snapshot"]["byte_size"],
    "output_partitions": delivered["output_snapshot"]["partition_spec"]["_manifest"]["file_count"],
    "materialized_python_rows": last_preview["metrics"]["materialized_python_rows"],
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
            # Bulk rows must stay in the engine. Hydrating them into Python is
            # the failure this benchmark exists to catch, so it is a gate
            # threshold rather than a note in the output.
            "materialized_python_rows_max": 0,
        },
        measurements={
            "input_rows": ROW_COUNT,
            "output_partitions": evidence["output_partitions"],
            "preview_p95_ms": evidence["preview_p95_ms"],
            "deliver_ms": evidence["deliver_ms"],
            "materialized_python_rows": evidence["materialized_python_rows"],
        },
        harness="oms/benchmark_pipeline_scale.py",
        notes=(
            f"Reference profile over {ROW_COUNT} rows in {PARTITION_COUNT} immutable "
            f"partitions, delivered to {evidence['output_partitions']} output partitions."
        ),
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

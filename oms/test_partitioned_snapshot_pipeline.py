"""Partitioned Parquet manifests execute without Python row hydration."""

import hashlib
import os
import tempfile
from pathlib import Path


tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
root = Path(tmpdir.name)
snapshot_root = root / "snapshots"
os.environ["DATABASE_URL"] = f"sqlite:///{(root / 'partitioned.db').as_posix()}"
os.environ["DATA_SNAPSHOT_ROOT"] = str(snapshot_root)
os.environ["AUTH_MODE"] = "local"
os.environ["APP_ENV"] = "test"
os.environ["DATA_SNAPSHOT_VERIFY_HASH"] = "true"

import pyarrow as pa  # noqa: E402
import pyarrow.parquet as parquet  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from app.main import app  # noqa: E402


client = TestClient(app)


def checked(response, expected=200):
    assert response.status_code == expected, f"{response.status_code}: {response.text[:3000]}"
    return response.json()


def write_part(path: Path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    parquet.write_table(pa.Table.from_pylist(rows), path, compression="zstd")


parts = snapshot_root / "default" / "partitioned_input" / "generation-1"
write_part(parts / "region=west" / "part-000.parquet", [
    {"asset_id": "a1", "region": "west", "score": 91},
    {"asset_id": "a2", "region": "west", "score": 65},
])
write_part(parts / "region=east" / "part-001.parquet", [
    {"asset_id": "a3", "region": "east", "score": 88},
    {"asset_id": "a4", "region": "east", "score": 40},
])

checked(client.post("/data-assets", json={
    "id": "partitioned_input", "project_id": "default",
    "display_name": "Partitioned input", "asset_schema": {}, "records": [],
}))
registered = checked(client.post(
    "/api/v1/datasets/partitioned_input/snapshots/register",
    json={
        "storage_uri": parts.as_uri(), "storage_format": "parquet",
        "partition_spec": {"fields": ["region"]},
        "lineage": {"connector_run_id": "partitioned-fixture-1"},
    },
), 201)
manifest = registered["partition_spec"]["_manifest"]
assert registered["row_count"] == 4 and manifest["file_count"] == 2, registered
assert len(manifest["entries"]) == 2 and all(len(entry["sha256"]) == 64 for entry in manifest["entries"])
assert manifest["files"] == [
    "region=east/part-001.parquet", "region=west/part-000.parquet",
], manifest
assert registered["lineage"]["registration"] == "external-parquet-partitioned"
assert registered["lineage"]["file_count"] == 2

duplicate = checked(client.post(
    "/api/v1/datasets/partitioned_input/snapshots/register",
    json={"storage_uri": parts.as_uri(), "partition_spec": {"fields": ["region"]}},
), 201)
assert duplicate["id"] == registered["id"]

page = checked(client.get(f"/api/v1/dataset-snapshots/{registered['id']}/rows?limit=2&offset=1"))
assert page["total"] == 4 and page["count"] == 2 and page["next_offset"] == 3

query = checked(client.post(f"/api/v1/dataset-snapshots/{registered['id']}/query", json={
    "fields": ["asset_id", "region", "score"],
    "filters": [{"field": "score", "operator": "gte", "value": 60}],
    "order_by": "score", "descending": True, "limit": 10,
}))
assert [row["asset_id"] for row in query["rows"]] == ["a1", "a3", "a2"], query
assert query["execution"]["engine"] == "duckdb-parquet"
assert query["execution"]["file_count"] == 2

nodes = [
    {"id": "input", "type": "input_dataset", "config": {
        "asset_id": "partitioned_input", "snapshot_id": registered["id"],
    }},
    {"id": "filter", "type": "filter", "config": {
        "field": "score", "operator": "gte", "value": 60,
    }},
    {"id": "aggregate", "type": "aggregate", "config": {
        "group_by": ["region"], "metrics": [{"operation": "count", "alias": "asset_count"}],
    }},
    {"id": "output", "type": "dataset_output", "config": {
        "asset_id": "partitioned_output", "partition_by": ["region"],
    }},
]
edges = [
    {"source": "input", "target": "filter"},
    {"source": "filter", "target": "aggregate"},
    {"source": "aggregate", "target": "output"},
]
checked(client.post("/pipeline-builder/graphs", json={
    "id": "partitioned_graph", "project_id": "default",
    "display_name": "Partitioned graph", "nodes": nodes, "edges": edges,
}), 201)
plan = checked(client.post("/api/v1/pipelines/partitioned_graph/plans", json={"executor": "duckdb"}), 201)

preview_job = checked(client.post(f"/api/v1/pipeline-plans/{plan['id']}/execute", json={
    "mode": "preview", "limit": 20, "idempotency_key": "partitioned-preview-1",
}), 202)["execution"]
preview_run = checked(client.post("/pipeline-builder/workers/run-next", json={
    "worker_id": "partitioned-worker", "job_id": preview_job["id"],
}))
assert preview_run["job"]["status"] == "SUCCEEDED", preview_run
assert preview_run["result"]["input_row_count"] == 4
assert sorted(preview_run["result"]["rows"], key=lambda row: row["region"]) == [
    {"region": "east", "asset_count": 1}, {"region": "west", "asset_count": 2},
]

delivery_job = checked(client.post(f"/api/v1/pipeline-plans/{plan['id']}/execute", json={
    "mode": "deliver", "output_asset_id": "partitioned_output",
    "idempotency_key": "partitioned-deliver-1",
}), 202)["execution"]
delivery_run = checked(client.post("/pipeline-builder/workers/run-next", json={
    "worker_id": "partitioned-worker", "job_id": delivery_job["id"],
}))
assert delivery_run["job"]["status"] == "SUCCEEDED", delivery_run
assert delivery_run["result"]["row_count"] == 2
output_snapshot = delivery_run["result"]["output_snapshot"]
assert output_snapshot["lineage"]["source_snapshot_id"] == registered["id"]
assert output_snapshot["partition_spec"]["fields"] == ["region"]
assert output_snapshot["partition_spec"]["hive_partitioning"] is True
assert output_snapshot["partition_spec"]["_manifest"]["file_count"] == 2
assert output_snapshot["lineage"]["file_count"] == 2
assert Path(output_snapshot["storage_uri"].removeprefix("file:///")).is_dir()

output_query = checked(client.post(
    f"/api/v1/dataset-snapshots/{output_snapshot['id']}/query",
    json={"fields": ["region", "asset_count"], "order_by": "region", "limit": 10},
))
assert output_query["rows"] == [
    {"region": "east", "asset_count": 1}, {"region": "west", "asset_count": 2},
], output_query
assert output_query["execution"]["file_count"] == 2

from app.data_plane import execute_duckdb_snapshot_plan  # noqa: E402
from app.database import SessionLocal  # noqa: E402

db = SessionLocal()
try:
    replay = execute_duckdb_snapshot_plan(
        db, plan["id"], mode="deliver", limit=100,
        output_asset_id="partitioned_output", parameters={}, actor="local-user",
        execution_job_id=delivery_job["id"],
    )
finally:
    db.close()
assert replay["idempotent_replay"] is True
assert replay["output_snapshot"]["id"] == delivery_run["result"]["output_snapshot"]["id"]

checked(client.post("/pipeline-builder/graphs", json={
    "id": "invalid_partition_graph", "project_id": "default",
    "display_name": "Invalid partition graph",
    "nodes": [
        {"id": "input", "type": "input_dataset", "config": {
            "asset_id": "partitioned_input", "snapshot_id": registered["id"],
        }},
        {"id": "output", "type": "dataset_output", "config": {
            "asset_id": "invalid_partition_output", "partition_by": ["missing_field"],
        }},
    ],
    "edges": [{"source": "input", "target": "output"}],
}), 201)
invalid_plan = checked(client.post(
    "/api/v1/pipelines/invalid_partition_graph/plans", json={"executor": "duckdb"},
), 201)
invalid_job = checked(client.post(f"/api/v1/pipeline-plans/{invalid_plan['id']}/execute", json={
    "mode": "deliver", "idempotency_key": "invalid-partition-deliver-1",
}), 202)["execution"]
invalid_run = checked(client.post("/pipeline-builder/workers/run-next", json={
    "worker_id": "partitioned-worker", "job_id": invalid_job["id"],
}))
assert invalid_run["job"]["status"] == "FAILED", invalid_run
assert "missing_field" in str(invalid_run["job"].get("error") or invalid_run), invalid_run
assert not (snapshot_root / "default" / "invalid_partition_output").exists()

checked(client.post("/pipeline-builder/graphs", json={
    "id": "empty_partition_graph", "project_id": "default",
    "display_name": "Empty partition graph",
    "nodes": [
        {"id": "input", "type": "input_dataset", "config": {
            "asset_id": "partitioned_input", "snapshot_id": registered["id"],
        }},
        {"id": "filter", "type": "filter", "config": {
            "field": "score", "operator": "gt", "value": 1000,
        }},
        {"id": "output", "type": "dataset_output", "config": {
            "asset_id": "empty_partition_output", "partition_by": ["region"],
        }},
    ],
    "edges": [{"source": "input", "target": "filter"}, {"source": "filter", "target": "output"}],
}), 201)
empty_plan = checked(client.post(
    "/api/v1/pipelines/empty_partition_graph/plans", json={"executor": "duckdb"},
), 201)
empty_job = checked(client.post(f"/api/v1/pipeline-plans/{empty_plan['id']}/execute", json={
    "mode": "deliver", "idempotency_key": "empty-partition-deliver-1",
}), 202)["execution"]
empty_run = checked(client.post("/pipeline-builder/workers/run-next", json={
    "worker_id": "partitioned-worker", "job_id": empty_job["id"],
}))
assert empty_run["job"]["status"] == "SUCCEEDED", empty_run
empty_snapshot = empty_run["result"]["output_snapshot"]
assert empty_snapshot["row_count"] == 0
assert empty_snapshot["partition_spec"]["_manifest"]["file_count"] == 1
empty_query = checked(client.post(f"/api/v1/dataset-snapshots/{empty_snapshot['id']}/query", json={
    "fields": ["asset_id", "region", "score"], "limit": 10,
}))
assert empty_query["rows"] == [] and empty_query["count"] == 0, empty_query

checked(client.post("/pipeline-builder/graphs", json={
    "id": "orphan_recovery_graph", "project_id": "default",
    "display_name": "Orphan recovery graph",
    "nodes": [
        {"id": "input", "type": "input_dataset", "config": {
            "asset_id": "partitioned_input", "snapshot_id": registered["id"],
        }},
        {"id": "output", "type": "dataset_output", "config": {
            "asset_id": "orphan_recovery_output", "partition_by": ["region"],
        }},
    ],
    "edges": [{"source": "input", "target": "output"}],
}), 201)
recovery_plan = checked(client.post(
    "/api/v1/pipelines/orphan_recovery_graph/plans", json={"executor": "duckdb"},
), 201)
recovery_job = checked(client.post(f"/api/v1/pipeline-plans/{recovery_plan['id']}/execute", json={
    "mode": "deliver", "idempotency_key": "orphan-recovery-deliver-1",
}), 202)["execution"]
recovery_suffix = hashlib.sha256(
    f"default:orphan_recovery_output:{recovery_job['id']}".encode("utf-8")
).hexdigest()[:12]
orphan_target = snapshot_root / "default" / "orphan_recovery_output" / f"1-{recovery_suffix}"
orphan_target.mkdir(parents=True)
(orphan_target / "stale.parquet").write_bytes(b"orphaned delivery")
recovery_run = checked(client.post("/pipeline-builder/workers/run-next", json={
    "worker_id": "partitioned-worker", "job_id": recovery_job["id"],
}))
assert recovery_run["job"]["status"] == "SUCCEEDED", recovery_run
assert not (orphan_target / "stale.parquet").exists()
assert recovery_run["result"]["output_snapshot"]["partition_spec"]["_manifest"]["file_count"] == 2

bad_schema = snapshot_root / "default" / "partitioned_bad_schema"
write_part(bad_schema / "part-000.parquet", [{"asset_id": "x", "score": 1}])
write_part(bad_schema / "part-001.parquet", [{"asset_id": "y", "score": "high"}])
bad_response = client.post(
    "/api/v1/datasets/partitioned_input/snapshots/register",
    json={"storage_uri": bad_schema.as_uri()},
)
assert bad_response.status_code == 422 and "schema mismatch" in bad_response.text, bad_response.text

empty = snapshot_root / "default" / "partitioned_empty"
empty.mkdir(parents=True)
empty_response = client.post(
    "/api/v1/datasets/partitioned_input/snapshots/register",
    json={"storage_uri": empty.as_uri()},
)
assert empty_response.status_code == 422 and "contains no Parquet files" in empty_response.text

outside = root / "outside.parquet"
write_part(outside, [{"asset_id": "outside", "region": "west", "score": 1}])
outside_response = client.post(
    "/api/v1/datasets/partitioned_input/snapshots/register",
    json={"storage_uri": outside.as_uri()},
)
assert outside_response.status_code == 422 and "outside DATA_SNAPSHOT_ROOT" in outside_response.text

mutated_path = parts / manifest["files"][0]
mutated = bytearray(mutated_path.read_bytes())
mutated[len(mutated) // 2] ^= 1
mutated_path.write_bytes(mutated)
mutated_response = client.get(f"/api/v1/dataset-snapshots/{registered['id']}/rows?limit=1")
assert mutated_response.status_code == 409 and "content changed after registration" in mutated_response.text

print("Partitioned Parquet snapshot registration, query, delivery, and replay verified.")
from app.database import engine  # noqa: E402

engine.dispose()
tmpdir.cleanup()

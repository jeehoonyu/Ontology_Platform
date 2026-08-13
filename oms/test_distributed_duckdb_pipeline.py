"""Partition jobs execute independently and publish through one fenced finalizer."""

import os
import tempfile
from pathlib import Path


tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
root = Path(tmpdir.name)
snapshot_root = root / "snapshots"
os.environ["DATABASE_URL"] = f"sqlite:///{(root / 'distributed.db').as_posix()}"
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


parts = snapshot_root / "default" / "distributed_input" / "generation-1"
for index in range(4):
    path = parts / f"part-{index:03d}.parquet"
    path.parent.mkdir(parents=True, exist_ok=True)
    parquet.write_table(pa.Table.from_pylist([
        {"asset_id": f"asset-{index}-high", "score": 80 + index},
        {"asset_id": f"asset-{index}-low", "score": 20 + index},
    ]), path, compression="zstd")

checked(client.post("/data-assets", json={
    "id": "distributed_input", "project_id": "default",
    "display_name": "Distributed input", "asset_schema": {}, "records": [],
}))
snapshot = checked(client.post(
    "/api/v1/datasets/distributed_input/snapshots/register",
    json={"storage_uri": parts.as_uri(), "storage_format": "parquet"},
), 201)
assert snapshot["row_count"] == 8
assert snapshot["partition_spec"]["_manifest"]["file_count"] == 4

nodes = [
    {"id": "input", "type": "input_dataset", "config": {
        "asset_id": "distributed_input", "snapshot_id": snapshot["id"],
    }},
    {"id": "filter", "type": "filter", "config": {
        "field": "score", "operator": "gte", "value": 80,
    }},
    {"id": "select", "type": "select", "config": {"fields": ["asset_id", "score"]}},
    {"id": "output", "type": "dataset_output", "config": {"asset_id": "distributed_output"}},
]
edges = [
    {"source": "input", "target": "filter"},
    {"source": "filter", "target": "select"},
    {"source": "select", "target": "output"},
]
checked(client.post("/pipeline-builder/graphs", json={
    "id": "distributed_graph", "project_id": "default",
    "display_name": "Distributed graph", "nodes": nodes, "edges": edges,
}), 201)
plan = checked(client.post(
    "/api/v1/pipelines/distributed_graph/plans", json={"executor": "duckdb"},
), 201)

execution = checked(client.post(f"/api/v1/pipeline-plans/{plan['id']}/execute", json={
    "mode": "deliver", "execution_strategy": "partitioned", "max_partitions": 3,
    "output_asset_id": "distributed_output", "idempotency_key": "distributed-delivery-1",
}), 202)["execution"]
assert execution["status"] == "BLOCKED"
partition_execution = execution["partition_execution"]
assert partition_execution["partition_count"] == 3
assert len(execution["execution"]["depends_on"]) == 3

blocked_claim = checked(client.post("/jobs/claim", json={
    "worker_id": "finalizer-only", "supported_job_types": ["pipeline.duckdb.finalize"],
}))
assert blocked_claim["job"] is None

for _index in range(3):
    run = checked(client.post("/pipeline-builder/workers/run-next", json={
        "worker_id": "distributed-worker", "lease_seconds": 120,
    }))
    assert run["job"]["job_type"] == "pipeline.duckdb.partition", run
    assert run["job"]["status"] == "SUCCEEDED", run
    assert run["result"]["fragment"]["content_hash"]

released = checked(client.get(f"/jobs/{execution['id']}"))
assert released["status"] == "QUEUED", released
finalized = checked(client.post("/pipeline-builder/workers/run-next", json={
    "worker_id": "distributed-finalizer", "job_id": execution["id"], "lease_seconds": 120,
}))
assert finalized["job"]["status"] == "SUCCEEDED", finalized
assert finalized["job"]["execution_strategy"] == "partitioned"
assert finalized["job"]["partition_execution"]["partition_count"] == 3
result = finalized["result"]
assert result["engine"] == "duckdb-distributed-finalizer"
assert result["row_count"] == 4 and result["partition_count"] == 3
output = result["output_snapshot"]
assert output["lineage"]["distributed"] is True
assert output["lineage"]["partition_job_ids"] == partition_execution["partition_job_ids"]
assert output["partition_spec"]["_manifest"]["file_count"] == 3
rows = checked(client.post(f"/api/v1/dataset-snapshots/{output['id']}/query", json={
    "fields": ["asset_id", "score"], "order_by": "asset_id", "limit": 20,
}))["rows"]
assert len(rows) == 4 and all(row["score"] >= 80 for row in rows), rows

replay = checked(client.post(f"/api/v1/pipeline-plans/{plan['id']}/execute", json={
    "mode": "deliver", "execution_strategy": "partitioned", "max_partitions": 3,
    "output_asset_id": "distributed_output", "idempotency_key": "distributed-delivery-1",
}), 202)["execution"]
assert replay["id"] == execution["id"] and replay["status"] == "SUCCEEDED", replay

preview = client.post(f"/api/v1/pipeline-plans/{plan['id']}/execute", json={
    "mode": "preview", "execution_strategy": "partitioned",
})
assert preview.status_code == 422, preview.text

unsafe_nodes = [*nodes[:2], {
    "id": "aggregate", "type": "aggregate",
    "config": {"metrics": [{"operation": "count", "alias": "count"}]},
}, nodes[-1] | {"id": "unsafe_output", "config": {"asset_id": "unsafe_output"}}]
unsafe_edges = [
    {"source": "input", "target": "filter"},
    {"source": "filter", "target": "aggregate"},
    {"source": "aggregate", "target": "unsafe_output"},
]
checked(client.post("/pipeline-builder/graphs", json={
    "id": "unsafe_distributed_graph", "project_id": "default",
    "display_name": "Unsafe distributed graph", "nodes": unsafe_nodes, "edges": unsafe_edges,
}), 201)
unsafe_plan = checked(client.post(
    "/api/v1/pipelines/unsafe_distributed_graph/plans", json={"executor": "duckdb"},
), 201)
unsafe = client.post(f"/api/v1/pipeline-plans/{unsafe_plan['id']}/execute", json={
    "mode": "deliver", "execution_strategy": "partitioned", "max_partitions": 3,
})
assert unsafe.status_code == 422, unsafe.text
assert "aggregate" in unsafe.json()["detail"]["blocking_operations"]

fallback = checked(client.post(f"/api/v1/pipeline-plans/{unsafe_plan['id']}/execute", json={
    "mode": "deliver", "execution_strategy": "auto", "max_partitions": 3,
    "output_asset_id": "unsafe_output", "idempotency_key": "distributed-auto-fallback-1",
}), 202)["execution"]
assert fallback["execution_strategy"] == "single"
assert "aggregate" in fallback["strategy_fallback"]["blocking_operations"]
fallback_run = checked(client.post("/pipeline-builder/workers/run-next", json={
    "worker_id": "fallback-worker", "job_id": fallback["id"], "lease_seconds": 120,
}))
assert fallback_run["job"]["status"] == "SUCCEEDED", fallback_run
assert fallback_run["job"]["execution_strategy"] == "single"
assert "aggregate" in fallback_run["job"]["strategy_fallback"]["blocking_operations"]
assert fallback_run["result"]["row_count"] == 1

print("\nDistributed DuckDB pipeline execution verified: 41 assertions passed.")
tmpdir.cleanup()

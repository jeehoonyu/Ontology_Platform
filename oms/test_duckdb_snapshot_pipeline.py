"""Snapshot-native DuckDB pipeline preview and delivery contract."""

import os
import tempfile


tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tmpdir.name, 'duckdb_pipeline.db')}"
os.environ["DATA_SNAPSHOT_ROOT"] = os.path.join(tmpdir.name, "snapshots")
os.environ["AUTH_MODE"] = "local"
os.environ["APP_ENV"] = "test"

from fastapi.testclient import TestClient  # noqa: E402
from app.main import app  # noqa: E402


client = TestClient(app)


def checked(response, expected=200):
    assert response.status_code == expected, f"{response.status_code}: {response.text[:3000]}"
    return response.json()


records = [
    {
        "asset_id": f"asset_{index:04d}",
        "category": f"category_{index % 5}",
        "score": index % 100,
        "weight": 1.5,
    }
    for index in range(1000)
]
checked(client.post("/data-assets", json={
    "id": "duckdb_input",
    "project_id": "default",
    "display_name": "DuckDB snapshot input",
    "asset_schema": {"fields": [
        {"name": "asset_id", "type": "string"},
        {"name": "category", "type": "string"},
        {"name": "score", "type": "integer"},
        {"name": "weight", "type": "number"},
    ]},
    "records": records,
}))
snapshot = checked(client.post(
    "/api/v1/datasets/duckdb_input/snapshots", json={"storage_format": "parquet"},
), 201)

nodes = [
    {"id": "input", "type": "input_dataset", "config": {
        "asset_id": "duckdb_input", "snapshot_id": snapshot["id"],
    }},
    {"id": "filter", "type": "filter", "config": {
        "field": "score", "operator": "gte", "value": 50,
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
        ],
    }},
    {"id": "sort", "type": "sort", "config": {
        "field": "asset_count", "direction": "desc",
    }},
    {"id": "output", "type": "dataset_output", "config": {
        "asset_id": "duckdb_output",
    }},
]
edges = [
    {"id": f"edge_{index}", "source": nodes[index]["id"], "target": nodes[index + 1]["id"]}
    for index in range(len(nodes) - 1)
]
checked(client.post("/pipeline-builder/graphs", json={
    "id": "duckdb_snapshot_graph",
    "project_id": "default",
    "display_name": "DuckDB snapshot graph",
    "nodes": nodes,
    "edges": edges,
}), 201)
plan = checked(client.post(
    "/api/v1/pipelines/duckdb_snapshot_graph/plans", json={"executor": "duckdb"},
), 201)
assert plan["status"] == "VALID" and plan["executor"] == "duckdb"
assert plan["input_schema"]["input"]["fields"]
assert plan["field_lineage"]["score"][0]["snapshot_id"] == snapshot["id"]

queued_preview = checked(client.post(f"/api/v1/pipeline-plans/{plan['id']}/execute", json={
    "mode": "preview", "limit": 10, "idempotency_key": "duckdb-preview-1",
}), 202)
preview_job = queued_preview["execution"]
assert preview_job["job_type"] == "pipeline.duckdb.preview"
preview_run = checked(client.post("/pipeline-builder/workers/run-next", json={
    "worker_id": "duckdb-test-worker", "job_id": preview_job["id"],
}))
assert preview_run["job"]["status"] == "SUCCEEDED", preview_run
preview = preview_run["result"]
assert preview["engine"] == "duckdb-snapshot"
assert preview["input_row_count"] == 1000
assert preview["row_count"] == 5
assert len(preview["rows"]) == 5
assert sum(row["asset_count"] for row in preview["rows"]) == 500
assert preview["metrics"]["materialized_python_rows"] == 5

queued_delivery = checked(client.post(f"/api/v1/pipeline-plans/{plan['id']}/execute", json={
    "mode": "deliver", "output_asset_id": "duckdb_output",
    "idempotency_key": "duckdb-deliver-1",
}), 202)
delivery_job = queued_delivery["execution"]
assert delivery_job["job_type"] == "pipeline.duckdb.deliver"
delivery_run = checked(client.post("/pipeline-builder/workers/run-next", json={
    "worker_id": "duckdb-test-worker", "job_id": delivery_job["id"],
}))
assert delivery_run["job"]["status"] == "SUCCEEDED", delivery_run
delivery = delivery_run["result"]
assert delivery["row_count"] == 5 and delivery["rows"] == []
assert delivery["metrics"]["materialized_python_rows"] == 0
output_snapshot = delivery["output_snapshot"]
assert output_snapshot["storage_format"] == "parquet"
assert output_snapshot["lineage"]["source_snapshot_id"] == snapshot["id"]
assert output_snapshot["lineage"]["pipeline_plan_id"] == plan["id"]

output_rows = checked(client.post(
    f"/api/v1/dataset-snapshots/{output_snapshot['id']}/query",
    json={"order_by": "category", "limit": 10},
))
assert output_rows["count"] == 5
assert sum(row["asset_count"] for row in output_rows["rows"]) == 500

output_asset = checked(client.get("/data-assets/duckdb_output"))
assert output_asset["records"] == []
assert output_asset["asset_schema"]["storage_mode"] == "snapshot"

from app.data_plane import execute_duckdb_snapshot_plan  # noqa: E402
from app.database import SessionLocal  # noqa: E402

db = SessionLocal()
try:
    replay = execute_duckdb_snapshot_plan(
        db,
        plan["id"],
        mode="deliver",
        limit=100,
        output_asset_id="duckdb_output",
        parameters={},
        actor="local-user",
        execution_job_id=delivery_job["id"],
    )
finally:
    db.close()
assert replay["idempotent_replay"] is True
assert replay["output_snapshot"]["id"] == output_snapshot["id"]
snapshot_list = checked(client.get("/api/v1/datasets/duckdb_output/snapshots"))
assert len(snapshot_list["snapshots"]) == 1

print("DuckDB snapshot-native pipeline preview and delivery verified.")
from app.database import engine  # noqa: E402
engine.dispose()
tmpdir.cleanup()

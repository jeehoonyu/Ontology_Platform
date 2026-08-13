"""Branching snapshot-native DuckDB pipeline execution and lineage contract."""

import os
import tempfile


tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tmpdir.name, 'duckdb_branching.db')}"
os.environ["DATA_SNAPSHOT_ROOT"] = os.path.join(tmpdir.name, "snapshots")
os.environ["AUTH_MODE"] = "local"
os.environ["APP_ENV"] = "test"

from fastapi.testclient import TestClient  # noqa: E402
from app.main import app  # noqa: E402


client = TestClient(app)


def checked(response, expected=200):
    assert response.status_code == expected, f"{response.status_code}: {response.text[:3000]}"
    return response.json()


def create_snapshot(asset_id, records):
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


assets_snapshot = create_snapshot("branch_assets", [{
    "asset_id": f"asset_{index:04d}",
    "category": f"category_{index % 20}",
    "score": index % 100,
} for index in range(1000)])

categories_snapshot = create_snapshot("branch_categories", [{
    "category": f"category_{index}",
    "maintenance_tier": "critical" if index < 5 else "standard",
    "active": True,
} for index in range(20)])

supplemental_snapshot = create_snapshot("branch_supplemental", [{
    "asset_id": "manual_0001",
    "category": "manual",
    "score": 99,
    "maintenance_tier": "supplemental",
}, {
    "asset_id": "manual_0002",
    "category": "manual",
    "score": 98,
    "maintenance_tier": "supplemental",
}])

nodes = [
    {"id": "assets", "type": "input_dataset", "config": {
        "asset_id": "branch_assets", "snapshot_id": assets_snapshot["id"],
    }},
    {"id": "asset_filter", "type": "filter", "config": {
        "field": "score", "operator": "gte", "value": 50,
    }},
    {"id": "categories", "type": "input_dataset", "config": {
        "asset_id": "branch_categories", "snapshot_id": categories_snapshot["id"],
    }},
    {"id": "category_filter", "type": "filter", "config": {
        "field": "active", "operator": "eq", "value": True,
    }},
    {"id": "join", "type": "join", "config": {
        "left_key": "category", "right_key": "category", "how": "inner",
    }},
    {"id": "project", "type": "project", "config": {
        "fields": ["asset_id", "category", "score", "maintenance_tier"],
    }},
    {"id": "supplemental", "type": "input_dataset", "config": {
        "asset_id": "branch_supplemental", "snapshot_id": supplemental_snapshot["id"],
    }},
    {"id": "union", "type": "union", "config": {}},
    {"id": "aggregate", "type": "aggregate", "config": {
        "group_by": ["maintenance_tier"],
        "metrics": [{"operation": "count", "alias": "asset_count"}],
    }},
    {"id": "output", "type": "dataset_output", "config": {
        "asset_id": "branch_output",
    }},
]
edges = [
    {"source": "assets", "target": "asset_filter"},
    {"source": "categories", "target": "category_filter"},
    {"source": "asset_filter", "target": "join"},
    {"source": "category_filter", "target": "join"},
    {"source": "join", "target": "project"},
    {"source": "project", "target": "union"},
    {"source": "supplemental", "target": "union"},
    {"source": "union", "target": "aggregate"},
    {"source": "aggregate", "target": "output"},
]
checked(client.post("/pipeline-builder/graphs", json={
    "id": "duckdb_branching_graph",
    "project_id": "default",
    "display_name": "DuckDB branching graph",
    "nodes": nodes,
    "edges": edges,
}), 201)

plan = checked(client.post(
    "/api/v1/pipelines/duckdb_branching_graph/plans",
    json={"executor": "duckdb"},
), 201)
assert plan["status"] == "VALID", plan

preview_job = checked(client.post(f"/api/v1/pipeline-plans/{plan['id']}/execute", json={
    "mode": "preview",
    "limit": 10,
    "idempotency_key": "duckdb-branch-preview",
}), 202)["execution"]
preview = checked(client.post("/pipeline-builder/workers/run-next", json={
    "worker_id": "duckdb-branch-worker",
    "job_id": preview_job["id"],
}))["result"]
assert preview["engine"] == "duckdb-snapshot"
assert preview["input_row_count"] == 1022
assert set(preview["source_snapshot_ids"]) == {
    assets_snapshot["id"], categories_snapshot["id"], supplemental_snapshot["id"],
}
assert preview["row_count"] == 3
assert sum(row["asset_count"] for row in preview["rows"]) == 502
assert {row["maintenance_tier"] for row in preview["rows"]} == {
    "critical", "standard", "supplemental",
}

delivery_job = checked(client.post(f"/api/v1/pipeline-plans/{plan['id']}/execute", json={
    "mode": "deliver",
    "output_asset_id": "branch_output",
    "idempotency_key": "duckdb-branch-deliver",
}), 202)["execution"]
delivery = checked(client.post("/pipeline-builder/workers/run-next", json={
    "worker_id": "duckdb-branch-worker",
    "job_id": delivery_job["id"],
}))["result"]
assert delivery["row_count"] == 3
assert set(delivery["output_snapshot"]["lineage"]["source_snapshot_ids"]) == set(preview["source_snapshot_ids"])

from app.data_plane import execute_duckdb_snapshot_plan  # noqa: E402
from app.database import SessionLocal, engine  # noqa: E402

db = SessionLocal()
try:
    replay = execute_duckdb_snapshot_plan(
        db,
        plan["id"],
        mode="deliver",
        limit=100,
        output_asset_id="branch_output",
        parameters={},
        actor="local-user",
        execution_job_id=delivery_job["id"],
    )
finally:
    db.close()
assert replay["idempotent_replay"] is True
assert replay["output_snapshot"]["id"] == delivery["output_snapshot"]["id"]

configured_nodes = [
    {"id": "assets", "type": "input_dataset", "config": {
        "asset_id": "branch_assets", "snapshot_id": assets_snapshot["id"],
    }},
    {"id": "join", "type": "join", "config": {
        "left_key": "category", "right_key": "category", "how": "inner",
        "right_asset_id": "branch_categories",
    }},
    {"id": "limit", "type": "limit", "config": {"limit": 3}},
]
checked(client.post("/pipeline-builder/graphs", json={
    "id": "duckdb_configured_join_graph",
    "project_id": "default",
    "display_name": "DuckDB configured dataset join",
    "nodes": configured_nodes,
    "edges": [
        {"source": "assets", "target": "join"},
        {"source": "join", "target": "limit"},
    ],
}), 201)
configured_plan = checked(client.post(
    "/api/v1/pipelines/duckdb_configured_join_graph/plans",
    json={"executor": "duckdb"},
), 201)
configured_job = checked(client.post(
    f"/api/v1/pipeline-plans/{configured_plan['id']}/execute",
    json={"mode": "preview", "limit": 10, "idempotency_key": "configured-join-preview"},
), 202)["execution"]
configured_preview = checked(client.post("/pipeline-builder/workers/run-next", json={
    "worker_id": "duckdb-branch-worker",
    "job_id": configured_job["id"],
}))["result"]
assert configured_preview["row_count"] == 3
assert configured_preview["input_row_count"] == 1020
assert set(configured_preview["source_snapshot_ids"]) == {
    assets_snapshot["id"], categories_snapshot["id"],
}
assert all("maintenance_tier" in row for row in configured_preview["rows"])

print("DuckDB branching join/union pipeline and multi-source lineage verified.")
engine.dispose()
tmpdir.cleanup()

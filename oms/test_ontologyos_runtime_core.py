"""OntologyOS v1 semantic, temporal, data-plane, and model gateway contracts."""

import os
import tempfile


tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tmpdir.name, 'ontologyos.db')}"
os.environ["DATA_SNAPSHOT_ROOT"] = os.path.join(tmpdir.name, "snapshots")
os.environ["AUTH_MODE"] = "local"
os.environ["APP_ENV"] = "test"

from fastapi.testclient import TestClient  # noqa: E402
from app.main import app  # noqa: E402


client = TestClient(app)
passed = 0


def ok(response, label, expected=200):
    global passed
    assert response.status_code == expected, f"{label}: {response.status_code} {response.text[:1800]}"
    passed += 1
    return response.json() if response.content else {}


ok(client.post("/object-types", json={
    "id": "runtime_asset", "project_id": "default", "display_name": "Runtime Asset", "description": "Temporal asset",
    "properties": {
        "assetId": {"type": "string"}, "name": {"type": "string"}, "risk": {"type": "number"},
        "latitude": {"type": "number"}, "longitude": {"type": "number"},
    },
}), "create object type")
ok(client.put("/ontology/object-types/runtime_asset/profile", json={
    "api_name": "RuntimeAsset", "primary_key": "assetId", "title_key": "name", "properties": {
        "assetId": {"base_type": "string", "required": True, "indexed": True},
        "name": {"base_type": "string", "required": True},
        "risk": {"base_type": "double", "minimum": 0, "maximum": 100, "indexed": True, "sensitive": True},
        "latitude": {"base_type": "double"}, "longitude": {"base_type": "double"},
    },
}), "set object type profile")

compiled = ok(client.post("/api/v1/ontology/compile", json={"project_id": "default"}), "compile semantic contract")
assert compiled["status"] == "COMPILED" and compiled["counts"]["properties"] == 5 and len(compiled["checksum"]) == 64
definitions = ok(client.get("/api/v1/ontology/schema/definitions?project_id=default&object_type_id=runtime_asset"), "list semantic definitions")
assert [row["property_name"] for row in definitions["properties"]] == ["assetId", "name", "risk", "latitude", "longitude"]
assert next(row for row in definitions["properties"] if row["property_name"] == "assetId")["primary_key"] is True
index_plans = ok(client.get("/api/v1/ontology/indexes?project_id=default&object_type_id=runtime_asset"), "list automatic index plans")
assert {row["property_name"] for row in index_plans["indexes"]} == {"assetId", "risk"}
risk_index = next(row for row in index_plans["indexes"] if row["property_name"] == "risk")
applied_index = ok(client.post(f"/api/v1/ontology/indexes/{risk_index['id']}/apply"), "apply governed risk index")
assert applied_index["status"] == "ACTIVE" and "CREATE INDEX" in applied_index["ddl"].upper()
assert applied_index["strategy"] == "BTREE_EXPRESSION_V3", applied_index
assert "id" in applied_index["ddl"].lower(), applied_index["ddl"]

for object_id, name, risk, latitude, longitude in (
    ("asset_1", "Pump 1", 88, 37.7900, -122.4010),
    ("asset_2", "Pump 2", 61, 37.7910, -122.4020),
    ("asset_3", "Chiller", 20, 40.7128, -74.0060),
):
    ok(client.post("/objects", json={
        "id": object_id, "project_id": "default", "object_type_id": "runtime_asset",
        "properties": {"assetId": object_id, "name": name, "risk": risk, "latitude": latitude, "longitude": longitude},
    }), f"create {object_id}")

query = ok(client.post("/api/v1/objects/query", json={
    "project_id": "default", "object_type_id": "runtime_asset",
    "filters": [{"field": "risk", "operator": "gte", "value": 60}],
    "aggregates": [{"name": "average_risk", "operation": "avg", "field": "risk"}],
    "order_by": [{"field": "risk", "direction": "desc"}], "limit": 1,
}), "typed query first page")
assert query["total"] == 2 and query["count"] == 1 and query["next_cursor"]
assert query["objects"][0]["id"] == "asset_1" and query["aggregates"]["average_risk"] == 74.5
assert query["query_plan"]["engine"] == "sqlalchemy+typed-sql"
assert query["query_plan"]["filter_pushdown"] == 1 and query["query_plan"]["aggregate_pushdown"] == 1
assert query["query_plan"]["indexed_fields"] == ["risk"] and query["query_plan"]["planned_index_fields"] == ["assetId", "risk"]
second_page = ok(client.post("/api/v1/objects/query", json={
    "project_id": "default", "object_type_id": "runtime_asset",
    "filters": [{"field": "risk", "operator": "gte", "value": 60}],
    "aggregates": [{"name": "average_risk", "operation": "avg", "field": "risk"}],
    "order_by": [{"field": "risk", "direction": "desc"}], "limit": 1, "cursor": query["next_cursor"],
}), "typed query second page")
assert second_page["objects"][0]["id"] == "asset_2" and second_page["next_cursor"] is None
spatial = ok(client.post("/api/v1/objects/query", json={
    "project_id": "default", "object_type_id": "runtime_asset",
    "spatial": {"latitude": 37.79, "longitude": -122.401, "radius_meters": 500},
}), "spatial typed query")
assert spatial["total"] == 2 and spatial["query_plan"]["spatial"] is True

history = ok(client.get("/api/v1/objects/runtime_asset/asset_1/history"), "object create history")
assert history["current_version"] == 1 and history["events"][0]["event_type"] == "ontology.object.created"
ok(client.post("/action-types", json={
    "id": "raise_risk", "project_id": "default", "display_name": "Raise risk", "description": "Test mutation",
    "parameters": {"object_id": {"type": "string"}, "risk": {"type": "number"}},
    "rules": {"object_mutations": [{"object_type_id": "runtime_asset", "object_id_param": "object_id", "set": {"risk": "$risk"}}]},
}), "create governed action")
ok(client.post("/actions/execute", json={
    "action_type_id": "raise_risk", "parameters": {"object_id": "asset_1", "risk": 93}, "idempotency_key": "raise-risk-1",
}), "execute governed action")
history = ok(client.get("/api/v1/objects/runtime_asset/asset_1/history"), "object mutation history")
assert history["current_version"] == 2 and history["events"][0]["before_state"]["risk"] == 88 and history["events"][0]["after_state"]["risk"] == 93

ok(client.post("/link-types", json={
    "id": "related_asset", "project_id": "default", "display_name": "Related asset", "description": "Operational relationship",
    "source_object_type_id": "runtime_asset", "target_object_type_id": "runtime_asset", "cardinality": "MANY_TO_MANY",
}), "create link type")
ok(client.post("/links", json={
    "id": "asset_link_1", "project_id": "default", "link_type_id": "related_asset", "source_object_id": "asset_1", "target_object_id": "asset_2",
}), "create object link")
graph = ok(client.post("/api/v1/graph/query", json={"project_id": "default", "seed_object_ids": ["asset_1"], "depth": 1}), "typed graph query")
assert graph["summary"]["node_count"] == 2 and graph["summary"]["edge_count"] == 1
assert graph["query_plan"]["n_plus_one"] is False and graph["query_plan"]["query_batches"] <= 3

from app.production_auth import Principal, current_principal  # noqa: E402

limited_principal = Principal(
    id="limited-viewer", display_name="Limited viewer", email=None, roles=["viewer"],
    permissions=["view"], project_ids=["default"],
)
app.dependency_overrides[current_principal] = lambda: limited_principal
try:
    masked_graph = ok(client.post("/api/v1/graph/query", json={
        "project_id": "default", "seed_object_ids": ["asset_1"], "depth": 1,
    }), "masked typed graph query")
finally:
    app.dependency_overrides.pop(current_principal, None)
asset_1_graph = next(row for row in masked_graph["nodes"] if row["id"] == "asset_1")
assert asset_1_graph["properties"]["risk"] == "***"
assert masked_graph["query_plan"]["masked_fields"] == ["runtime_asset.risk"]

ok(client.post("/data-assets", json={
    "id": "runtime_assets_raw", "project_id": "default", "display_name": "Runtime assets raw", "description": "Snapshot source",
    "asset_schema": {"fields": [{"name": "assetId", "type": "string"}, {"name": "risk", "type": "number"}]},
    "records": [{"assetId": "asset_1", "risk": 93}, {"assetId": "asset_2", "risk": 61}],
}), "create data asset")
snapshot = ok(client.post("/api/v1/datasets/runtime_assets_raw/snapshots", json={"storage_format": "jsonl"}), "create immutable dataset snapshot", 201)
assert snapshot["row_count"] == 2 and snapshot["storage_format"] == "jsonl" and snapshot["storage_uri"].startswith("file:")
snapshot_rows = ok(client.get(f"/api/v1/dataset-snapshots/{snapshot['id']}/rows?limit=1"), "read immutable dataset snapshot")
assert snapshot_rows["count"] == 1 and snapshot_rows["total"] == 2 and snapshot_rows["next_offset"] == 1
snapshot_query = ok(client.post(f"/api/v1/dataset-snapshots/{snapshot['id']}/query", json={
    "fields": ["assetId", "risk"],
    "filters": [{"field": "risk", "operator": "gte", "value": 70}],
    "order_by": "risk", "descending": True,
}), "query snapshot through DuckDB")
assert snapshot_query["rows"] == [{"assetId": "asset_1", "risk": 93}] and snapshot_query["execution"]["engine"] == "duckdb"

ok(client.post("/data-assets", json={
    "id": "runtime_assets_columnar", "display_name": "Runtime columnar assets",
    "asset_schema": {"fields": [{"name": "assetId", "type": "string"}, {"name": "risk", "type": "number"}]},
    "records": [{"assetId": "asset_3", "risk": 82}],
}), "create columnar data asset")
parquet_snapshot = ok(client.post("/api/v1/datasets/runtime_assets_columnar/snapshots", json={"storage_format": "parquet"}), "create Parquet dataset snapshot", 201)
assert parquet_snapshot["storage_format"] == "parquet" and parquet_snapshot["byte_size"] > 0

graph_definition = ok(client.post("/pipeline-builder/graphs", json={
    "id": "runtime_pipeline", "project_id": "default", "display_name": "Runtime pipeline",
    "nodes": [
        {"id": "input", "type": "input_dataset", "config": {"asset_id": "runtime_assets_raw"}},
        {"id": "output", "type": "dataset_output", "config": {"asset_id": "runtime_assets_output"}},
    ],
    "edges": [{"id": "input-output", "source": "input", "target": "output"}],
}), "create pipeline graph", 201)
assert graph_definition["id"] == "runtime_pipeline"
plan = ok(client.post("/api/v1/pipelines/runtime_pipeline/plans", json={"executor": "local"}), "compile pipeline execution plan", 201)
assert plan["status"] == "VALID" and plan["logical_plan"]["operations"][0]["node_id"] == "input"
execution = ok(client.post(f"/api/v1/pipeline-plans/{plan['id']}/execute", json={"mode": "preview", "idempotency_key": "runtime-plan-preview"}), "enqueue plan execution", 202)
assert execution["execution"]["status"] == "QUEUED"

provider = ok(client.post("/models/gateway/providers", json={
    "id": "local_reasoner", "project_id": "default", "display_name": "Local deterministic reasoner",
    "provider_type": "deterministic", "allowed_models": ["ontology-reasoner-v1"], "policy": {"max_input_chars": 10000},
}), "create model gateway provider", 201)
assert provider["secret_configured"] is False
inference = ok(client.post("/models/gateway/infer", json={
    "project_id": "default", "provider_id": "local_reasoner", "model_name": "ontology-reasoner-v1",
    "messages": [{"role": "user", "content": "Explain the asset risk."}],
    "ontology_objects": [{"object_type_id": "runtime_asset", "object_id": "asset_1", "fields": ["name", "risk"]}],
    "proposed_action_type_id": "raise_risk", "idempotency_key": "inference-1",
}), "run governed deterministic inference")
assert inference["status"] == "SUCCEEDED" and inference["output"]["action_proposal"]["execution_allowed"] is False
cached = ok(client.post("/models/gateway/infer", json={
    "project_id": "default", "provider_id": "local_reasoner", "model_name": "ontology-reasoner-v1",
    "messages": [{"role": "user", "content": "Explain the asset risk."}],
    "ontology_objects": [{"object_type_id": "runtime_asset", "object_id": "asset_1", "fields": ["name", "risk"]}],
    "proposed_action_type_id": "raise_risk", "idempotency_key": "inference-1",
}), "reuse idempotent inference")
assert cached["cached"] is True and cached["id"] == inference["id"]
conflict = client.post("/models/gateway/infer", json={
    "project_id": "default", "provider_id": "local_reasoner", "model_name": "ontology-reasoner-v1",
    "messages": [{"role": "user", "content": "Use the same key for another request."}],
    "idempotency_key": "inference-1",
})
assert conflict.status_code == 409, conflict.text

os.environ["RUNTIME_TEST_MODEL_TOKEN"] = "runtime-test-secret"
blocked_provider = ok(client.post("/models/gateway/providers", json={
    "id": "blocked_local_provider", "project_id": "default", "display_name": "Blocked local provider",
    "provider_type": "local_http", "base_url": "http://127.0.0.1:9/v1", "secret_ref": "RUNTIME_TEST_MODEL_TOKEN",
    "allowed_models": ["local-test"], "configuration": {"external_calls_enabled": True},
}), "create SSRF test provider", 201)
assert blocked_provider["secret_configured"] is True
blocked_inference = client.post("/models/gateway/infer", json={
    "project_id": "default", "provider_id": "blocked_local_provider", "model_name": "local-test",
    "messages": [{"role": "user", "content": "This request must not reach loopback."}],
})
assert blocked_inference.status_code == 502 and "Private or local" in blocked_inference.text, blocked_inference.text

print(f"\nOntologyOS runtime core verified: {passed} API checks passed.")
from app.database import engine as _engine  # noqa: E402
_engine.dispose()
tmpdir.cleanup()

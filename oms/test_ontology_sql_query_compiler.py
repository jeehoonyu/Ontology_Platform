"""Typed SQL ontology query compiler semantics and keyset stability."""

import os
import tempfile
import time


tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tmpdir.name, 'typed_query.db')}"
os.environ["AUTH_MODE"] = "local"
os.environ["APP_ENV"] = "test"

from fastapi.testclient import TestClient  # noqa: E402
from app.main import app  # noqa: E402
from app.database import engine  # noqa: E402
from sqlalchemy import event  # noqa: E402


client = TestClient(app)


def checked(response, expected=200):
    assert response.status_code == expected, f"{response.status_code}: {response.text[:2000]}"
    return response.json()


checked(client.post("/object-types", json={
    "id": "query_asset", "project_id": "default", "display_name": "Query Asset",
    "properties": {"assetId": {"type": "string"}, "name": {"type": "string"}, "score": {"type": "number"}, "category": {"type": "string"}},
}))
checked(client.put("/ontology/object-types/query_asset/profile", json={
    "api_name": "QueryAsset", "primary_key": "assetId", "title_key": "name",
    "properties": {
        "assetId": {"base_type": "string", "required": True, "indexed": True},
        "name": {"base_type": "string", "required": True},
        "score": {"base_type": "double", "indexed": True},
        "category": {"base_type": "string"},
    },
}))
checked(client.post("/api/v1/ontology/compile", json={"project_id": "default"}))

objects = (
    ("asset_a", "Alpha Pump", 10, "pump"),
    ("asset_b", "Beta Pump", 10, "PUMP"),
    ("asset_c", "Chiller", 20, "chiller"),
    ("asset_d", "Delta Pump", None, "pump"),
    ("asset_e", "Echo Turbine", 30, "turbine"),
)
created_times = {}
for object_id, name, score, category in objects:
    properties = {"assetId": object_id, "name": name, "category": category}
    if score is not None:
        properties["score"] = score
    checked(client.post("/objects", json={
        "id": object_id, "project_id": "default", "object_type_id": "query_asset", "properties": properties,
    }))
    created_times[object_id] = checked(client.get(f"/api/v1/objects/query_asset/{object_id}/history"))["events"][0]["transaction_time"]

query_body = {
    "project_id": "default", "object_type_id": "query_asset",
    "order_by": [{"field": "score", "direction": "asc"}], "limit": 2,
    "aggregates": [
        {"name": "score_count", "operation": "count", "field": "score"},
        {"name": "score_sum", "operation": "sum", "field": "score"},
        {"name": "category_count", "operation": "distinct_count", "field": "category"},
    ],
}
seen = []
cursor = None
while True:
    page = checked(client.post("/api/v1/objects/query", json={**query_body, "cursor": cursor}))
    seen.extend(row["id"] for row in page["objects"])
    assert page["total"] == 5
    assert page["aggregates"] == {"score_count": 4, "score_sum": 70.0, "category_count": 4}
    cursor = page["next_cursor"]
    if cursor is None:
        break
assert seen == ["asset_a", "asset_b", "asset_c", "asset_e", "asset_d"], seen
assert len(seen) == len(set(seen))

contains = checked(client.post("/api/v1/objects/query", json={
    "project_id": "default", "object_type_id": "query_asset",
    "filters": [{"field": "name", "operator": "contains", "value": "pump"}],
    "order_by": [{"field": "id", "direction": "asc"}],
}))
assert [row["id"] for row in contains["objects"]] == ["asset_a", "asset_b", "asset_d"]

starts_with = checked(client.post("/api/v1/objects/query", json={
    "project_id": "default", "object_type_id": "query_asset",
    "filters": [{"field": "name", "operator": "starts_with", "value": "be"}],
}))
assert [row["id"] for row in starts_with["objects"]] == ["asset_b"]

null_scores = checked(client.post("/api/v1/objects/query", json={
    "project_id": "default", "object_type_id": "query_asset", "include_total": False,
    "filters": [{"field": "score", "operator": "is_null", "value": True}],
}))
assert null_scores["total"] is None and [row["id"] for row in null_scores["objects"]] == ["asset_d"]

categories = checked(client.post("/api/v1/objects/query", json={
    "project_id": "default", "object_type_id": "query_asset",
    "filters": [{"field": "category", "operator": "in", "value": ["pump", "chiller"]}],
    "order_by": [{"field": "id", "direction": "asc"}],
}))
assert [row["id"] for row in categories["objects"]] == ["asset_a", "asset_c", "asset_d"]

definition_queries = []


def capture_definition_queries(_connection, _cursor, statement, _parameters, _context, _many):
    if statement.lstrip().upper().startswith("SELECT") and "ontology_property_definitions" in statement:
        definition_queries.append(statement)


event.listen(engine, "before_cursor_execute", capture_definition_queries)
try:
    batched_masking = checked(client.post("/api/v1/objects/query", json={
        "project_id": "default", "object_type_id": "query_asset",
        "order_by": [{"field": "id", "direction": "asc"}], "limit": 100,
        "include_total": False, "include_lineage": False,
    }))
finally:
    event.remove(engine, "before_cursor_execute", capture_definition_queries)
assert batched_masking["count"] == len(objects)
assert len(definition_queries) <= 2, f"Masking regressed to per-object definition queries: {len(definition_queries)}"

first_page = checked(client.post("/api/v1/objects/query", json=query_body))
mismatched = client.post("/api/v1/objects/query", json={
    **query_body,
    "filters": [{"field": "score", "operator": "gte", "value": 10}],
    "cursor": first_page["next_cursor"],
})
assert mismatched.status_code == 422 and "query mismatch" in mismatched.text, mismatched.text

time.sleep(1.05)
checked(client.post("/action-types", json={
    "id": "set_query_score", "project_id": "default", "display_name": "Set query score",
    "parameters": {"object_id": {"type": "string"}, "score": {"type": "number"}},
    "rules": {"object_mutations": [{"object_type_id": "query_asset", "object_id_param": "object_id", "set": {"score": "$score"}}]},
}))
checked(client.post("/actions/execute", json={
    "action_type_id": "set_query_score", "parameters": {"object_id": "asset_c", "score": 99}, "idempotency_key": "query-score-1",
}))
historical = checked(client.post("/api/v1/objects/query", json={
    "project_id": "default", "object_type_id": "query_asset",
    "filters": [{"field": "assetId", "operator": "eq", "value": "asset_c"}],
    "as_of_transaction_time": created_times["asset_c"],
}))
assert historical["objects"][0]["properties"]["score"] == 20
assert historical["query_plan"]["temporal"] is True

print("Ontology typed SQL query compiler verified.")
engine.dispose()
tmpdir.cleanup()

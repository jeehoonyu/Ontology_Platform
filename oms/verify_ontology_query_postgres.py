"""Rehearse typed ontology queries and governed indexes on PostgreSQL.

This script intentionally uses DATABASE_URL from the environment and runs after the
Alembic chain in CI. It is not part of the SQLite script sweep.
"""

import os
from concurrent.futures import ThreadPoolExecutor


if not os.environ.get("DATABASE_URL", "").startswith("postgresql"):
    raise SystemExit("verify_ontology_query_postgres.py requires a PostgreSQL DATABASE_URL")
os.environ["SKIP_CREATE_ALL"] = "1"
os.environ.setdefault("AUTH_MODE", "local")
os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("EVENT_KAFKA_BOOTSTRAP_SERVERS", "broker.invalid:9092")
os.environ.setdefault("EVENT_KAFKA_SECURITY_PROTOCOL", "PLAINTEXT")

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import inspect  # noqa: E402
from app import event_outbox  # noqa: E402
from app.database import engine  # noqa: E402
from app.main import app  # noqa: E402


client = TestClient(app)


def checked(response, expected=200):
    assert response.status_code == expected, f"{response.status_code}: {response.text[:2000]}"
    return response.json()


checked(client.post("/object-types", json={
    "id": "pg_query_asset", "project_id": "default", "display_name": "PostgreSQL Query Asset",
    "properties": {"assetId": {"type": "string"}, "risk": {"type": "number"}, "category": {"type": "string"}},
}))
checked(client.put("/ontology/object-types/pg_query_asset/profile", json={
    "api_name": "PostgresQueryAsset", "primary_key": "assetId", "title_key": "assetId",
    "properties": {
        "assetId": {"base_type": "string", "required": True, "indexed": True},
        "risk": {"base_type": "double", "indexed": True},
        "category": {"base_type": "string"},
    },
}))
checked(client.post("/api/v1/ontology/compile", json={"project_id": "default", "object_type_ids": ["pg_query_asset"]}))

for object_id, risk, category in (("pg_a", 85, "pump"), ("pg_b", 70, "pump"), ("pg_c", 20, "chiller")):
    checked(client.post("/objects", json={
        "id": object_id, "project_id": "default", "object_type_id": "pg_query_asset",
        "properties": {"assetId": object_id, "risk": risk, "category": category},
    }))

plans = checked(client.get("/api/v1/ontology/indexes?project_id=default&object_type_id=pg_query_asset"))
risk_plan = next(row for row in plans["indexes"] if row["property_name"] == "risk")
applied = checked(client.post(f"/api/v1/ontology/indexes/{risk_plan['id']}/apply"))
assert applied["status"] == "ACTIVE" and applied["index_name"] in {row["name"] for row in inspect(engine).get_indexes("object_instances")}

query = checked(client.post("/api/v1/objects/query", json={
    "project_id": "default", "object_type_id": "pg_query_asset",
    "filters": [{"field": "risk", "operator": "gte", "value": 60}],
    "order_by": [{"field": "risk", "direction": "desc"}], "limit": 1,
    "aggregates": [{"name": "average_risk", "operation": "avg", "field": "risk"}],
}))
assert query["total"] == 2 and query["objects"][0]["id"] == "pg_a" and query["next_cursor"]
assert float(query["aggregates"]["average_risk"]) == 77.5
assert query["query_plan"]["engine"] == "sqlalchemy+typed-sql" and query["query_plan"]["indexed_fields"] == ["risk"]

second = checked(client.post("/api/v1/objects/query", json={
    "project_id": "default", "object_type_id": "pg_query_asset",
    "filters": [{"field": "risk", "operator": "gte", "value": 60}],
    "order_by": [{"field": "risk", "direction": "desc"}], "limit": 1, "cursor": query["next_cursor"],
    "aggregates": [{"name": "average_risk", "operation": "avg", "field": "risk"}],
}))
assert [row["id"] for row in second["objects"]] == ["pg_b"] and second["next_cursor"] is None

pending_events = checked(client.get("/api/v1/outbox/events?project_id=default&status=PENDING"))
ontology_event = next(row for row in pending_events["events"] if row["event_type"] == "ontology.object_type.created")
dispatched = checked(client.post("/api/v1/outbox/workers/run-next", json={
    "worker_id": "postgres-event-dispatcher", "event_id": ontology_event["id"],
}))
assert dispatched["outbox"]["status"] == "PUBLISHED"
event_log = checked(client.get("/api/v1/events/log?project_id=default&after_sequence=0"))
assert any(row["outbox_event_id"] == ontology_event["id"] for row in event_log["events"])

def dispatch(worker_number):
    return checked(client.post("/api/v1/outbox/workers/run-next", json={
        "worker_id": f"postgres-concurrent-dispatcher-{worker_number}",
    }))

with ThreadPoolExecutor(max_workers=4) as pool:
    concurrent_results = list(pool.map(dispatch, range(4)))
claimed_ids = [result["outbox"]["id"] for result in concurrent_results if result.get("outbox")]
assert len(claimed_ids) == 4 and len(set(claimed_ids)) == 4, claimed_ids

# External transport receipts use an independent SKIP LOCKED claim boundary.
def fake_kafka_publish(row, destination, _settings):
    return {
        "topic": destination, "partition": 0, "offset": int(row.created_at),
        "timestamp": row.created_at, "event_id": row.idempotency_key,
    }

event_outbox._publish_kafka = fake_kafka_publish

def dispatch_kafka(worker_number):
    return checked(client.post("/api/v1/outbox/kafka/workers/run-next", json={
        "worker_id": f"postgres-kafka-dispatcher-{worker_number}",
    }))

with ThreadPoolExecutor(max_workers=4) as pool:
    kafka_results = list(pool.map(dispatch_kafka, range(4)))
delivery_ids = [result["delivery"]["id"] for result in kafka_results if result.get("delivery")]
delivery_outbox_ids = [result["delivery"]["outbox_event_id"] for result in kafka_results if result.get("delivery")]
assert len(delivery_ids) == 4 and len(set(delivery_ids)) == 4, delivery_ids
assert len(set(delivery_outbox_ids)) == 4, delivery_outbox_ids

print("PostgreSQL ontology query, governed index, transactional outbox, and transport receipt rehearsal passed.")
engine.dispose()

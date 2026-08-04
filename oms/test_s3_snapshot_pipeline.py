"""S3-compatible snapshots execute through the verified local DuckDB cache."""

import hashlib
import os
import shutil
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path


tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
root = Path(tmpdir.name)
os.environ["DATABASE_URL"] = f"sqlite:///{(root / 's3-snapshot.db').as_posix()}"
os.environ["DATA_SNAPSHOT_BACKEND"] = "s3"
os.environ["DATA_SNAPSHOT_BUCKET"] = "ontology-test"
os.environ["DATA_SNAPSHOT_ROOT"] = str(root / "delivery-staging")
os.environ["DATA_SNAPSHOT_CACHE_ROOT"] = str(root / "cache")
os.environ["DATA_SNAPSHOT_CACHE_MAX_BYTES"] = str(10 * 1024 * 1024)
os.environ["DATA_SNAPSHOT_CACHE_LEASE_SECONDS"] = "0"
os.environ["AUTH_MODE"] = "local"
os.environ["APP_ENV"] = "test"

from fastapi.testclient import TestClient  # noqa: E402
import pyarrow as pa  # noqa: E402
import pyarrow.parquet as parquet  # noqa: E402
from app.main import app  # noqa: E402
from app import data_plane  # noqa: E402


class MemoryS3:
    def __init__(self):
        self.bucket = "ontology-test"
        self.objects = {}
        self.get_count = 0
        self.lock = threading.Lock()

    def put(self, key, payload, content_type):
        self.objects[key] = bytes(payload)
        return f"s3://ontology-test/{key}"

    def get(self, uri):
        prefix = "s3://ontology-test/"
        if not uri.startswith(prefix):
            raise ValueError("wrong test bucket")
        key = uri.removeprefix(prefix)
        if key not in self.objects:
            raise FileNotFoundError(key)
        with self.lock:
            self.get_count += 1
        return self.objects[key]

    def list_parquet(self, uri, maximum):
        prefix = "s3://ontology-test/"
        if not uri.startswith(prefix):
            raise ValueError("wrong test bucket")
        key = uri.removeprefix(prefix).strip("/")
        if key.lower().endswith((".parquet", ".pq")):
            if key not in self.objects:
                raise FileNotFoundError(key)
            return [{"key": key, "byte_size": len(self.objects[key])}]
        object_prefix = key + "/"
        matches = [
            {"key": item, "byte_size": len(payload)}
            for item, payload in sorted(self.objects.items())
            if item.startswith(object_prefix) and item.lower().endswith((".parquet", ".pq"))
        ]
        if len(matches) > maximum:
            raise ValueError("manifest limit")
        if not matches:
            raise ValueError("no Parquet objects")
        return matches


storage = MemoryS3()
data_plane._storage = lambda: storage
data_plane._storage_for_uri = lambda _uri: storage
client = TestClient(app)


def checked(response, expected=200):
    assert response.status_code == expected, f"{response.status_code}: {response.text[:3000]}"
    return response.json()


checked(client.post("/data-assets", json={
    "id": "s3_input", "project_id": "default", "display_name": "S3 input",
    "asset_schema": {}, "records": [
        {"asset_id": "a1", "region": "west", "score": 91},
        {"asset_id": "a2", "region": "west", "score": 65},
        {"asset_id": "a3", "region": "east", "score": 88},
        {"asset_id": "a4", "region": "east", "score": 40},
    ],
}))
source = checked(client.post("/api/v1/datasets/s3_input/snapshots", json={
    "storage_format": "parquet", "lineage": {"connector_run_id": "memory-s3"},
}), 201)
assert source["storage_uri"].startswith("s3://ontology-test/")
assert source["row_count"] == 4 and len(storage.objects) == 1

for region, rows in {
    "west": [{"asset_id": "a1", "score": 91}, {"asset_id": "a2", "score": 65}],
    "east": [{"asset_id": "a3", "score": 88}, {"asset_id": "a4", "score": 40}],
}.items():
    sink = pa.BufferOutputStream()
    parquet.write_table(pa.Table.from_pylist(rows), sink, compression="zstd")
    storage.put(
        f"external-assets/region={region}/part-000.parquet",
        sink.getvalue().to_pybytes(), "application/vnd.apache.parquet",
    )
checked(client.post("/data-assets", json={
    "id": "s3_registered", "project_id": "default",
    "display_name": "Registered S3 prefix", "asset_schema": {}, "records": [],
}))
registered = checked(client.post("/api/v1/datasets/s3_registered/snapshots/register", json={
    "storage_uri": "s3://ontology-test/external-assets",
    "partition_spec": {"fields": ["region"], "hive_partitioning": True},
    "lineage": {"connector_run_id": "s3-prefix-registration"},
}), 201)
assert registered["row_count"] == 4
assert registered["lineage"]["registration"] == "external-s3-parquet-partitioned"
assert registered["partition_spec"]["_manifest"]["file_count"] == 2
assert {field["name"] for field in registered["schema"]["fields"]} == {"asset_id", "score", "region"}
registered_query = checked(client.post(f"/api/v1/dataset-snapshots/{registered['id']}/query", json={
    "fields": ["asset_id", "region", "score"],
    "filters": [{"field": "region", "operator": "eq", "value": "west"}],
    "order_by": "score", "descending": True, "limit": 10,
}))
assert [row["asset_id"] for row in registered_query["rows"]] == ["a1", "a2"], registered_query

checked(client.post("/data-assets", json={
    "id": "s3_exact_registered", "project_id": "default",
    "display_name": "Registered S3 object", "asset_schema": {}, "records": [],
}))
exact_registered = checked(client.post("/api/v1/datasets/s3_exact_registered/snapshots/register", json={
    "storage_uri": source["storage_uri"], "lineage": {"connector_run_id": "s3-object-registration"},
}), 201)
assert exact_registered["row_count"] == 4
assert exact_registered["lineage"]["registration"] == "external-s3-parquet"
assert "_manifest" not in exact_registered["partition_spec"]

wrong_bucket = client.post("/api/v1/datasets/s3_registered/snapshots/register", json={
    "storage_uri": "s3://another-bucket/external-assets",
})
assert wrong_bucket.status_code == 422 and "bucket" in wrong_bucket.text, wrong_bucket.text
os.environ["DATA_SNAPSHOT_MAX_FILES"] = "1"
over_file_limit = client.post("/api/v1/datasets/s3_registered/snapshots/register", json={
    "storage_uri": "s3://ontology-test/external-assets",
})
assert over_file_limit.status_code == 422 and "limit" in over_file_limit.text, over_file_limit.text
os.environ["DATA_SNAPSHOT_MAX_FILES"] = "10000"

checked(client.post("/pipeline-builder/graphs", json={
    "id": "s3_partition_graph", "project_id": "default", "display_name": "S3 partition graph",
    "nodes": [
        {"id": "input", "type": "input_dataset", "config": {
            "asset_id": "s3_registered", "snapshot_id": registered["id"],
        }},
        {"id": "filter", "type": "filter", "config": {
            "field": "score", "operator": "gte", "value": 60,
        }},
        {"id": "aggregate", "type": "aggregate", "config": {
            "group_by": ["region"], "metrics": [{"operation": "count", "alias": "asset_count"}],
        }},
        {"id": "output", "type": "dataset_output", "config": {
            "asset_id": "s3_output", "partition_by": ["region"],
        }},
    ],
    "edges": [
        {"source": "input", "target": "filter"},
        {"source": "filter", "target": "aggregate"},
        {"source": "aggregate", "target": "output"},
    ],
}), 201)
plan = checked(client.post("/api/v1/pipelines/s3_partition_graph/plans", json={"executor": "duckdb"}), 201)
preview_job = checked(client.post(f"/api/v1/pipeline-plans/{plan['id']}/execute", json={
    "mode": "preview", "limit": 10, "idempotency_key": "s3-preview-1",
}), 202)["execution"]
preview = checked(client.post("/pipeline-builder/workers/run-next", json={
    "worker_id": "s3-worker", "job_id": preview_job["id"],
}))
assert preview["job"]["status"] == "SUCCEEDED", preview
assert sorted(preview["result"]["rows"], key=lambda row: row["region"]) == [
    {"region": "east", "asset_count": 1}, {"region": "west", "asset_count": 2},
]

delivery_job = checked(client.post(f"/api/v1/pipeline-plans/{plan['id']}/execute", json={
    "mode": "deliver", "idempotency_key": "s3-deliver-1",
}), 202)["execution"]
delivery = checked(client.post("/pipeline-builder/workers/run-next", json={
    "worker_id": "s3-worker", "job_id": delivery_job["id"],
}))
assert delivery["job"]["status"] == "SUCCEEDED", delivery
output = delivery["result"]["output_snapshot"]
assert output["storage_uri"].startswith("s3://ontology-test/default/s3_output/")
assert output["partition_spec"]["_manifest"]["file_count"] == 2
assert output["lineage"]["partition_by"] == ["region"]
assert len(storage.objects) == 5

output_cache_key = hashlib.sha256(f"default:s3_output:{output['id']}".encode("utf-8")).hexdigest()
output_cache_dir = root / "cache" / output_cache_key[:2] / output_cache_key
shutil.rmtree(output_cache_dir, ignore_errors=True)
query = checked(client.post(f"/api/v1/dataset-snapshots/{output['id']}/query", json={
    "fields": ["region", "asset_count"], "order_by": "region", "limit": 10,
}))
assert query["rows"] == [
    {"region": "east", "asset_count": 1}, {"region": "west", "asset_count": 2},
]
assert query["execution"]["engine"] == "duckdb-parquet"
summary = checked(client.get("/api/v1/snapshot-cache/summary"))
assert summary["entry_count"] >= 2 and summary["metrics"]["misses"] >= 3, summary
assert summary["metrics"]["hits"] >= 1, summary
pruned = checked(client.post("/api/v1/snapshot-cache/prune", json={"target_bytes": 0}))
assert pruned["cache_bytes"] == 0 and pruned["evictions"] >= 2, pruned
gets_before_concurrency = storage.get_count
with ThreadPoolExecutor(max_workers=8) as pool:
    concurrent_responses = list(pool.map(
        lambda _index: client.post(f"/api/v1/dataset-snapshots/{output['id']}/query", json={
            "fields": ["region", "asset_count"], "order_by": "region", "limit": 10,
        }),
        range(8),
    ))
assert all(response.status_code == 200 for response in concurrent_responses), [response.text for response in concurrent_responses]
assert all(response.json()["rows"] == query["rows"] for response in concurrent_responses)
assert storage.get_count - gets_before_concurrency == 2, storage.get_count - gets_before_concurrency

os.environ["DATA_SNAPSHOT_CACHE_MAX_BYTES"] = "1"
checked(client.post("/api/v1/snapshot-cache/prune", json={"target_bytes": 0}))
over_quota = client.get(f"/api/v1/dataset-snapshots/{output['id']}/rows?limit=1")
assert over_quota.status_code == 507 and "quota" in over_quota.text, over_quota.text
os.environ["DATA_SNAPSHOT_CACHE_MAX_BYTES"] = str(10 * 1024 * 1024)

from app.database import SessionLocal  # noqa: E402

db = SessionLocal()
try:
    replay = data_plane.execute_duckdb_snapshot_plan(
        db, plan["id"], mode="deliver", limit=10, output_asset_id=None,
        parameters={}, actor="local-user", execution_job_id=delivery_job["id"],
    )
finally:
    db.close()
assert replay["idempotent_replay"] is True and replay["output_snapshot"]["id"] == output["id"]
assert len(storage.objects) == 5

first_relative = output["partition_spec"]["_manifest"]["files"][0]
first_key = output["storage_uri"].removeprefix("s3://ontology-test/") + "/" + first_relative
storage.objects[first_key] += b"corruption"
checked(client.post("/api/v1/snapshot-cache/prune", json={"target_bytes": 0}))
corrupted = client.get(f"/api/v1/dataset-snapshots/{output['id']}/rows?limit=1")
assert corrupted.status_code == 409 and "manifest" in corrupted.text, corrupted.text
final_summary = checked(client.get("/api/v1/snapshot-cache/summary"))
assert final_summary["metrics"]["integrity_failures"] >= 1

print("S3-compatible snapshot caching, partitioned delivery, replay, and integrity verification passed.")
from app.database import engine  # noqa: E402

engine.dispose()
tmpdir.cleanup()

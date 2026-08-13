"""Rehearse snapshot-native pipeline delivery against a real S3-compatible endpoint."""

import os
import tempfile
import uuid
from pathlib import Path


tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
root = Path(tmpdir.name)
run_id = uuid.uuid4().hex[:10]
bucket = os.getenv("S3_REHEARSAL_BUCKET", "ontology-rehearsal")
os.environ["DATABASE_URL"] = f"sqlite:///{(root / 'minio-rehearsal.db').as_posix()}"
os.environ["DATA_SNAPSHOT_BACKEND"] = "s3"
os.environ["DATA_SNAPSHOT_BUCKET"] = bucket
os.environ["DATA_SNAPSHOT_S3_ENDPOINT"] = os.getenv("DATA_SNAPSHOT_S3_ENDPOINT", "http://127.0.0.1:9000")
os.environ["DATA_SNAPSHOT_S3_REGION"] = os.getenv("DATA_SNAPSHOT_S3_REGION", "us-east-1")
os.environ["DATA_SNAPSHOT_S3_ADDRESSING_STYLE"] = "path"
os.environ["DATA_SNAPSHOT_S3_AUTO_CREATE_BUCKET"] = "true"
os.environ["DATA_SNAPSHOT_ROOT"] = str(root / "delivery")
os.environ["DATA_SNAPSHOT_CACHE_ROOT"] = str(root / "cache")
os.environ["AWS_ACCESS_KEY_ID"] = os.getenv("AWS_ACCESS_KEY_ID", "ontology")
os.environ["AWS_SECRET_ACCESS_KEY"] = os.getenv("AWS_SECRET_ACCESS_KEY", "ontology-development-secret")
os.environ["AUTH_MODE"] = "local"
os.environ["APP_ENV"] = "test"

import boto3  # noqa: E402
from botocore.config import Config  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
import pyarrow as pa  # noqa: E402
import pyarrow.parquet as parquet  # noqa: E402
from app.main import app  # noqa: E402


client = TestClient(app)


def checked(response, expected=200):
    assert response.status_code == expected, f"{response.status_code}: {response.text[:3000]}"
    return response.json()


input_id = f"minio_input_{run_id}"
output_id = f"minio_output_{run_id}"
graph_id = f"minio_graph_{run_id}"
checked(client.post("/data-assets", json={
    "id": input_id, "project_id": "default", "display_name": "MinIO rehearsal input",
    "asset_schema": {}, "records": [
        {"asset_id": "a1", "region": "west", "score": 91},
        {"asset_id": "a2", "region": "west", "score": 65},
        {"asset_id": "a3", "region": "east", "score": 88},
    ],
}))
source = checked(client.post(f"/api/v1/datasets/{input_id}/snapshots", json={
    "storage_format": "parquet", "lineage": {"rehearsal": run_id},
}), 201)
s3 = boto3.client(
    "s3", endpoint_url=os.environ["DATA_SNAPSHOT_S3_ENDPOINT"],
    region_name=os.environ["DATA_SNAPSHOT_S3_REGION"],
    config=Config(s3={"addressing_style": "path"}),
)
prefix_input_id = f"minio_prefix_input_{run_id}"
prefix = f"connector-output-{run_id}"
for region, rows in {
    "west": [{"asset_id": "a1", "score": 91}, {"asset_id": "a2", "score": 65}],
    "east": [{"asset_id": "a3", "score": 88}],
}.items():
    sink = pa.BufferOutputStream()
    parquet.write_table(pa.Table.from_pylist(rows), sink, compression="zstd")
    s3.put_object(
        Bucket=bucket, Key=f"{prefix}/region={region}/part-000.parquet",
        Body=sink.getvalue().to_pybytes(), ContentType="application/vnd.apache.parquet",
    )
checked(client.post("/data-assets", json={
    "id": prefix_input_id, "project_id": "default", "display_name": "MinIO prefix input",
    "asset_schema": {}, "records": [],
}))
registered = checked(client.post(f"/api/v1/datasets/{prefix_input_id}/snapshots/register", json={
    "storage_uri": f"s3://{bucket}/{prefix}",
    "partition_spec": {"fields": ["region"], "hive_partitioning": True},
    "lineage": {"connector_run_id": f"minio-prefix-{run_id}"},
}), 201)
assert registered["row_count"] == 3 and registered["partition_spec"]["_manifest"]["file_count"] == 2
checked(client.post("/pipeline-builder/graphs", json={
    "id": graph_id, "project_id": "default", "display_name": "MinIO rehearsal graph",
    "nodes": [
        {"id": "input", "type": "input_dataset", "config": {
            "asset_id": prefix_input_id, "snapshot_id": registered["id"],
        }},
        {"id": "aggregate", "type": "aggregate", "config": {
            "group_by": ["region"], "metrics": [{"operation": "count", "alias": "asset_count"}],
        }},
        {"id": "output", "type": "dataset_output", "config": {
            "asset_id": output_id, "partition_by": ["region"],
        }},
    ],
    "edges": [{"source": "input", "target": "aggregate"}, {"source": "aggregate", "target": "output"}],
}), 201)
plan = checked(client.post(f"/api/v1/pipelines/{graph_id}/plans", json={"executor": "duckdb"}), 201)
job = checked(client.post(f"/api/v1/pipeline-plans/{plan['id']}/execute", json={
    "mode": "deliver", "idempotency_key": f"minio-deliver-{run_id}",
}), 202)["execution"]
run = checked(client.post("/pipeline-builder/workers/run-next", json={
    "worker_id": "minio-rehearsal-worker", "job_id": job["id"],
}))
assert run["job"]["status"] == "SUCCEEDED", run
output = run["result"]["output_snapshot"]
assert output["storage_uri"].startswith(f"s3://{bucket}/")
assert output["partition_spec"]["_manifest"]["file_count"] == 2
query = checked(client.post(f"/api/v1/dataset-snapshots/{output['id']}/query", json={
    "fields": ["region", "asset_count"], "order_by": "region", "limit": 10,
}))
assert query["rows"] == [{"region": "east", "asset_count": 1}, {"region": "west", "asset_count": 2}]

objects = s3.list_objects_v2(Bucket=bucket, Prefix="default/").get("Contents") or []
assert len(objects) >= 3, objects
for item in objects:
    if input_id in item["Key"] or output_id in item["Key"]:
        s3.delete_object(Bucket=bucket, Key=item["Key"])
prefix_objects = s3.list_objects_v2(Bucket=bucket, Prefix=prefix + "/").get("Contents") or []
for item in prefix_objects:
    s3.delete_object(Bucket=bucket, Key=item["Key"])

print(f"MinIO rehearsal passed: bucket={bucket}, registered_partitions=2, output_partitions=2, query_rows=2")
from app.database import engine  # noqa: E402

engine.dispose()
tmpdir.cleanup()

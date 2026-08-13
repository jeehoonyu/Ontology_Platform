"""Measure cold and warm snapshot-native execution against S3-compatible storage."""

from __future__ import annotations

import json
import os
import platform
import statistics
import tempfile
import time
import uuid
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlparse
from tier_b_evidence import build_evidence_provenance


PROFILE = os.getenv("OBJECT_STORAGE_BENCHMARK_PROFILE", "smoke").strip().lower()
if PROFILE not in {"smoke", "reference"}:
    raise SystemExit("OBJECT_STORAGE_BENCHMARK_PROFILE must be 'smoke' or 'reference'")
REFERENCE_ROWS = 1_000_000
ROW_COUNT = int(os.getenv(
    "OBJECT_STORAGE_BENCHMARK_ROWS", str(REFERENCE_ROWS if PROFILE == "reference" else 100_000),
))
PARTITIONS = int(os.getenv("OBJECT_STORAGE_BENCHMARK_PARTITIONS", "8"))
SAMPLES = int(os.getenv("OBJECT_STORAGE_BENCHMARK_SAMPLES", "5"))
EVIDENCE_PATH = os.getenv("OBJECT_STORAGE_BENCHMARK_EVIDENCE_PATH")
ENDPOINT = os.getenv("DATA_SNAPSHOT_S3_ENDPOINT", "http://127.0.0.1:9000")
BUCKET = os.getenv("OBJECT_STORAGE_BENCHMARK_BUCKET", "ontology-benchmark")
NETWORK_SCOPE = os.getenv("OBJECT_STORAGE_NETWORK_SCOPE", "local-docker-loopback").strip()
TOXIPROXY_ADMIN_URL = os.getenv("OBJECT_STORAGE_TOXIPROXY_ADMIN_URL", "").rstrip("/")
TOXIPROXY_NAME = os.getenv("OBJECT_STORAGE_TOXIPROXY_NAME", "minio-latency").strip()
TOXIPROXY_ENDPOINT = os.getenv("OBJECT_STORAGE_TOXIPROXY_ENDPOINT", "").rstrip("/")
CONCURRENT_WORKERS = int(os.getenv("OBJECT_STORAGE_BENCHMARK_CONCURRENT_WORKERS", "4"))
REGISTRATION_LIMIT_MS = float(os.getenv("OBJECT_STORAGE_REGISTRATION_LIMIT_MS", "120000"))
COLD_QUERY_LIMIT_MS = float(os.getenv("OBJECT_STORAGE_COLD_QUERY_LIMIT_MS", "30000"))
WARM_QUERY_P95_LIMIT_MS = float(os.getenv("OBJECT_STORAGE_WARM_QUERY_P95_LIMIT_MS", "5000"))
COLD_PIPELINE_LIMIT_MS = float(os.getenv("OBJECT_STORAGE_COLD_PIPELINE_LIMIT_MS", "30000"))
WARM_PIPELINE_P95_LIMIT_MS = float(os.getenv("OBJECT_STORAGE_WARM_PIPELINE_P95_LIMIT_MS", "10000"))
CONCURRENT_COLD_PIPELINE_LIMIT_MS = float(os.getenv(
    "OBJECT_STORAGE_CONCURRENT_COLD_PIPELINE_LIMIT_MS", "30000",
))

if ROW_COUNT < 1_000 or PARTITIONS < 1 or PARTITIONS > 128 or ROW_COUNT % PARTITIONS != 0:
    raise SystemExit("Rows must be >= 1,000 and evenly divisible across 1-128 partitions")
if SAMPLES < 3:
    raise SystemExit("OBJECT_STORAGE_BENCHMARK_SAMPLES must be at least 3")
if CONCURRENT_WORKERS < 2 or CONCURRENT_WORKERS > 32:
    raise SystemExit("Object-storage concurrent workers must be between 2 and 32")
if PROFILE == "reference" and ROW_COUNT < REFERENCE_ROWS:
    raise SystemExit("Reference object-storage profile requires at least 1,000,000 rows")
if PROFILE == "reference" and NETWORK_SCOPE != "local-docker-loopback" and not TOXIPROXY_ADMIN_URL:
    raise SystemExit("A non-loopback reference profile requires a verifiable Toxiproxy admin endpoint")

tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
root = Path(tmpdir.name)
run_id = uuid.uuid4().hex[:12]
prefix = f"object-storage-benchmark/{run_id}"
os.environ["DATABASE_URL"] = f"sqlite:///{(root / 'object-storage.db').as_posix()}"
os.environ["DATA_SNAPSHOT_BACKEND"] = "s3"
os.environ["DATA_SNAPSHOT_BUCKET"] = BUCKET
os.environ["DATA_SNAPSHOT_S3_ENDPOINT"] = ENDPOINT
os.environ["DATA_SNAPSHOT_S3_REGION"] = os.getenv("DATA_SNAPSHOT_S3_REGION", "us-east-1")
os.environ["DATA_SNAPSHOT_S3_ADDRESSING_STYLE"] = "path"
os.environ["DATA_SNAPSHOT_S3_AUTO_CREATE_BUCKET"] = "true"
os.environ["DATA_SNAPSHOT_ROOT"] = str(root / "delivery")
os.environ["DATA_SNAPSHOT_CACHE_ROOT"] = str(root / "cache")
os.environ["DATA_SNAPSHOT_CACHE_MAX_BYTES"] = str(max(256 * 1024 * 1024, ROW_COUNT * 256))
os.environ["DATA_SNAPSHOT_CACHE_LEASE_SECONDS"] = "0"
os.environ["DATA_SNAPSHOT_MAX_FILES"] = str(max(100, PARTITIONS))
os.environ["AWS_ACCESS_KEY_ID"] = os.getenv("AWS_ACCESS_KEY_ID", "ontology")
os.environ["AWS_SECRET_ACCESS_KEY"] = os.getenv("AWS_SECRET_ACCESS_KEY", "ontology-development-secret")
os.environ["AUTH_MODE"] = "local"
os.environ["APP_ENV"] = "test"

import boto3  # noqa: E402
import duckdb  # noqa: E402
from botocore.config import Config  # noqa: E402
from botocore.exceptions import ClientError  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from app.main import app  # noqa: E402


client = TestClient(app)
s3 = boto3.client(
    "s3", endpoint_url=ENDPOINT, region_name=os.environ["DATA_SNAPSHOT_S3_REGION"],
    config=Config(s3={"addressing_style": "path"}),
)
try:
    s3.head_bucket(Bucket=BUCKET)
except ClientError:
    s3.create_bucket(Bucket=BUCKET)


def toxiproxy_profile():
    if not TOXIPROXY_ADMIN_URL:
        return None
    request = urllib.request.Request(
        f"{TOXIPROXY_ADMIN_URL}/proxies/{TOXIPROXY_NAME}",
        headers={"User-Agent": "toxiproxy-cli"},
    )
    with urllib.request.urlopen(request, timeout=5) as response:
        profile = json.loads(response.read().decode("utf-8"))
    toxics = profile.get("toxics") or []
    latency_toxics = [toxic for toxic in toxics if toxic.get("type") == "latency" and toxic.get("enabled", True)]
    if not latency_toxics:
        raise AssertionError("Configured object-storage proxy has no enabled latency toxic")
    if not TOXIPROXY_ENDPOINT or urlparse(TOXIPROXY_ENDPOINT) != urlparse(ENDPOINT):
        raise AssertionError("Benchmark endpoint must equal the declared external Toxiproxy endpoint")
    total_latency_ms = sum(int((toxic.get("attributes") or {}).get("latency") or 0) for toxic in latency_toxics)
    if total_latency_ms <= 0:
        raise AssertionError("Configured object-storage latency toxic must add positive latency")
    return {
        "proxy": TOXIPROXY_NAME,
        "endpoint": ENDPOINT,
        "listen": profile.get("listen"),
        "upstream": profile.get("upstream"),
        "verified_latency_ms": total_latency_ms,
        "toxics": [{
            "name": toxic.get("name"), "stream": toxic.get("stream"),
            "toxicity": toxic.get("toxicity"), "attributes": toxic.get("attributes") or {},
        } for toxic in latency_toxics],
    }


network_fault_profile = toxiproxy_profile()


def checked(response, expected=200):
    assert response.status_code == expected, f"{response.status_code}: {response.text[:3000]}"
    return response.json()


def percentile(values, fraction):
    ordered = sorted(values)
    position = max(0, min(len(ordered) - 1, int(round((len(ordered) - 1) * fraction))))
    return ordered[position]


fixture_dir = root / "fixture"
fixture_dir.mkdir(parents=True)
rows_per_partition = ROW_COUNT // PARTITIONS
generate_started = time.perf_counter()
uploaded_bytes = 0
for partition in range(PARTITIONS):
    start = partition * rows_per_partition
    end = start + rows_per_partition
    region = f"region-{partition:03d}"
    path = fixture_dir / f"part-{partition:04d}.parquet"
    connection = duckdb.connect(database=":memory:")
    try:
        connection.execute(
            f"COPY (SELECT 'asset-' || CAST(i AS VARCHAR) AS asset_id, "
            f"CAST(i % 100 AS DOUBLE) AS score, CAST(i % 20 AS INTEGER) AS category "
            f"FROM range({start}, {end}) AS source(i)) "
            f"TO '{path.as_posix()}' (FORMAT PARQUET, COMPRESSION ZSTD)"
        )
    finally:
        connection.close()
    uploaded_bytes += path.stat().st_size
    s3.upload_file(str(path), BUCKET, f"{prefix}/region={region}/{path.name}")
generate_ms = (time.perf_counter() - generate_started) * 1000

asset_id = f"object_storage_input_{run_id}"
graph_id = f"object_storage_graph_{run_id}"
checked(client.post("/data-assets", json={
    "id": asset_id, "project_id": "default", "display_name": "Object storage benchmark input",
    "asset_schema": {}, "records": [],
}))
registration_started = time.perf_counter()
snapshot = checked(client.post(f"/api/v1/datasets/{asset_id}/snapshots/register", json={
    "storage_uri": f"s3://{BUCKET}/{prefix}",
    "partition_spec": {"fields": ["region"], "hive_partitioning": True},
    "lineage": {"benchmark_run_id": run_id},
}), 201)
registration_ms = (time.perf_counter() - registration_started) * 1000
assert snapshot["row_count"] == ROW_COUNT
assert snapshot["partition_spec"]["_manifest"]["file_count"] == PARTITIONS

query_body = {
    "fields": ["asset_id", "region", "score", "category"],
    "filters": [{"field": "score", "operator": "gte", "value": 90}],
    "order_by": "score", "descending": True, "limit": 100,
}
checked(client.post("/api/v1/snapshot-cache/prune", json={"target_bytes": 0}))
cold_query_started = time.perf_counter()
cold_query = checked(client.post(f"/api/v1/dataset-snapshots/{snapshot['id']}/query", json=query_body))
cold_query_ms = (time.perf_counter() - cold_query_started) * 1000
assert cold_query["count"] == 100 and all(row["score"] >= 90 for row in cold_query["rows"])

warm_query_latencies = []
for _sample in range(SAMPLES):
    started = time.perf_counter()
    checked(client.post(f"/api/v1/dataset-snapshots/{snapshot['id']}/query", json=query_body))
    warm_query_latencies.append((time.perf_counter() - started) * 1000)

checked(client.post("/pipeline-builder/graphs", json={
    "id": graph_id, "project_id": "default", "display_name": "Object storage benchmark graph",
    "nodes": [
        {"id": "input", "type": "input_dataset", "config": {"asset_id": asset_id, "snapshot_id": snapshot["id"]}},
        {"id": "filter", "type": "filter", "config": {"field": "score", "operator": "gte", "value": 90}},
        {"id": "aggregate", "type": "aggregate", "config": {
            "group_by": ["region"], "metrics": [
                {"operation": "count", "alias": "asset_count"},
                {"operation": "avg", "field": "score", "alias": "average_score"},
            ],
        }},
        {"id": "sort", "type": "sort", "config": {"field": "region", "direction": "asc"}},
        {"id": "output", "type": "dataset_output", "config": {"asset_id": f"unused_{run_id}"}},
    ],
    "edges": [
        {"source": "input", "target": "filter"}, {"source": "filter", "target": "aggregate"},
        {"source": "aggregate", "target": "sort"}, {"source": "sort", "target": "output"},
    ],
}), 201)
plan = checked(client.post(f"/api/v1/pipelines/{graph_id}/plans", json={"executor": "duckdb"}), 201)


def preview(sample):
    queued = checked(client.post(f"/api/v1/pipeline-plans/{plan['id']}/execute", json={
        "mode": "preview", "limit": 100, "idempotency_key": f"object-storage-preview-{run_id}-{sample}",
    }), 202)["execution"]
    started = time.perf_counter()
    executed = checked(client.post("/pipeline-builder/workers/run-next", json={
        "worker_id": "object-storage-benchmark-worker", "job_id": queued["id"],
    }))
    elapsed = (time.perf_counter() - started) * 1000
    assert executed["job"]["status"] == "SUCCEEDED", executed
    assert executed["result"]["row_count"] == PARTITIONS, executed
    return elapsed


checked(client.post("/api/v1/snapshot-cache/prune", json={"target_bytes": 0}))
cold_pipeline_ms = preview("cold")
warm_pipeline_latencies = [preview(f"warm-{sample}") for sample in range(SAMPLES)]

# Recreate a cold cache and run independently leased jobs at the same time.
# Per-file locks must coalesce each immutable object download; every waiting
# worker then verifies and reads the same cached manifest without corruption.
concurrent_jobs = [checked(client.post(f"/api/v1/pipeline-plans/{plan['id']}/execute", json={
    "mode": "preview", "limit": 100,
    "idempotency_key": f"object-storage-concurrent-{run_id}-{worker}",
}), 202)["execution"] for worker in range(CONCURRENT_WORKERS)]
checked(client.post("/api/v1/snapshot-cache/prune", json={"target_bytes": 0}))
cache_before_concurrency = checked(client.get("/api/v1/snapshot-cache/summary"))["metrics"]


def run_concurrent_worker(worker_and_job):
    worker, job = worker_and_job
    with TestClient(app) as worker_client:
        response = worker_client.post("/pipeline-builder/workers/run-next", json={
            "worker_id": f"object-storage-concurrent-worker-{worker}", "job_id": job["id"],
        })
        assert response.status_code == 200, response.text[:3000]
        payload = response.json()
        assert payload["job"]["status"] == "SUCCEEDED", payload
        assert payload["result"]["row_count"] == PARTITIONS, payload
        return payload["job"]["id"]


concurrent_started = time.perf_counter()
with ThreadPoolExecutor(max_workers=CONCURRENT_WORKERS) as pool:
    concurrent_job_ids = list(pool.map(run_concurrent_worker, enumerate(concurrent_jobs)))
concurrent_cold_pipeline_ms = (time.perf_counter() - concurrent_started) * 1000
cache_summary = checked(client.get("/api/v1/snapshot-cache/summary"))
concurrent_cache_delta = {
    key: int(cache_summary["metrics"].get(key, 0)) - int(cache_before_concurrency.get(key, 0))
    for key in ("hits", "misses", "downloaded_bytes", "integrity_failures", "evictions")
}

warm_query_p95 = percentile(warm_query_latencies, 0.95)
warm_pipeline_p95 = percentile(warm_pipeline_latencies, 0.95)
assert registration_ms < REGISTRATION_LIMIT_MS, registration_ms
assert cold_query_ms < COLD_QUERY_LIMIT_MS, cold_query_ms
assert warm_query_p95 < WARM_QUERY_P95_LIMIT_MS, warm_query_p95
assert cold_pipeline_ms < COLD_PIPELINE_LIMIT_MS, cold_pipeline_ms
assert warm_pipeline_p95 < WARM_PIPELINE_P95_LIMIT_MS, warm_pipeline_p95
assert concurrent_cold_pipeline_ms < CONCURRENT_COLD_PIPELINE_LIMIT_MS, concurrent_cold_pipeline_ms
assert len(set(concurrent_job_ids)) == CONCURRENT_WORKERS
assert concurrent_cache_delta["misses"] == PARTITIONS, concurrent_cache_delta
assert concurrent_cache_delta["hits"] >= PARTITIONS * (CONCURRENT_WORKERS - 1), concurrent_cache_delta
assert concurrent_cache_delta["integrity_failures"] == 0, concurrent_cache_delta

evidence = {
    "provenance": build_evidence_provenance(
        "oms/benchmark_object_storage_minio.py",
        entry_points=[
            "POST /api/v1/datasets/{asset_id}/snapshots/register",
            "POST /api/v1/datasets/{asset_id}/snapshots/query",
            "POST /api/v1/pipelines/{graph_id}/plans",
            "POST /jobs/{job_id}/execute",
        ],
        request_shapes=[
            "S3-compatible partitioned snapshot registration",
            "cold and warm bounded snapshot query",
            "cold and warm durable pipeline preview",
            "concurrent independently leased preview workers",
        ],
    ),
    "profile": PROFILE,
    "network_scope": NETWORK_SCOPE,
    "network_fault_profile": network_fault_profile,
    "reference_scale_achieved": ROW_COUNT >= REFERENCE_ROWS,
    "rows": ROW_COUNT,
    "partitions": PARTITIONS,
    "uploaded_bytes": uploaded_bytes,
    "generate_and_upload_ms": round(generate_ms, 3),
    "registration_ms": round(registration_ms, 3),
    "registration_limit_ms": REGISTRATION_LIMIT_MS,
    "cold_query_ms": round(cold_query_ms, 3),
    "cold_query_limit_ms": COLD_QUERY_LIMIT_MS,
    "warm_query_p50_ms": round(statistics.median(warm_query_latencies), 3),
    "warm_query_p95_ms": round(warm_query_p95, 3),
    "warm_query_p95_limit_ms": WARM_QUERY_P95_LIMIT_MS,
    "cold_pipeline_ms": round(cold_pipeline_ms, 3),
    "cold_pipeline_limit_ms": COLD_PIPELINE_LIMIT_MS,
    "warm_pipeline_p50_ms": round(statistics.median(warm_pipeline_latencies), 3),
    "warm_pipeline_p95_ms": round(warm_pipeline_p95, 3),
    "warm_pipeline_p95_limit_ms": WARM_PIPELINE_P95_LIMIT_MS,
    "concurrent_workers": CONCURRENT_WORKERS,
    "concurrent_cold_pipeline_ms": round(concurrent_cold_pipeline_ms, 3),
    "concurrent_cold_pipeline_limit_ms": CONCURRENT_COLD_PIPELINE_LIMIT_MS,
    "concurrent_cache_delta": concurrent_cache_delta,
    "concurrent_job_ids": concurrent_job_ids,
    "cache_metrics": cache_summary["metrics"],
    "snapshot_id": snapshot["id"],
    "plan_id": plan["id"],
    "host": {
        "platform": platform.platform(), "python": platform.python_version(),
        "processor": platform.processor(), "duckdb": duckdb.__version__,
        "endpoint": ENDPOINT,
    },
}
serialized = json.dumps(evidence, indent=2, sort_keys=True)
if EVIDENCE_PATH:
    Path(EVIDENCE_PATH).write_text(serialized + "\n", encoding="utf-8")
print("Object-storage benchmark passed:")
print(serialized)

listed = s3.list_objects_v2(Bucket=BUCKET, Prefix=prefix + "/").get("Contents") or []
for item in listed:
    s3.delete_object(Bucket=BUCKET, Key=item["Key"])
from app.database import engine  # noqa: E402

engine.dispose()
tmpdir.cleanup()

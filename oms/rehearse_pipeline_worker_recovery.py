"""Rehearse abrupt worker loss during S3-backed DuckDB delivery.

This is an integration rehearsal, not a unit test. PostgreSQL, MinIO, and an
optional latency proxy must already be running. The script starts an API and
two independent worker processes, kills the first worker after it begins
populating its private cache, and verifies fenced single-publication recovery.
"""
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from typing import Any

import boto3
import duckdb
from botocore.config import Config
from botocore.exceptions import ClientError
from sqlalchemy import create_engine, text

from tier_b_evidence import current_head


ROOT = Path(__file__).resolve().parents[1]
OMS = ROOT / "oms"
ROWS = int(os.getenv("PIPELINE_RECOVERY_ROWS", "100000"))
PARTITIONS = int(os.getenv("PIPELINE_RECOVERY_PARTITIONS", "32"))
LEASE_SECONDS = int(os.getenv("PIPELINE_RECOVERY_LEASE_SECONDS", "10"))
TIMEOUT_SECONDS = int(os.getenv("PIPELINE_RECOVERY_TIMEOUT_SECONDS", "180"))
BUCKET = os.getenv("DATA_SNAPSHOT_BUCKET", "ontology-recovery")
S3_ENDPOINT = os.environ["DATA_SNAPSHOT_S3_ENDPOINT"]
S3_ADMIN_ENDPOINT = os.getenv("PIPELINE_RECOVERY_S3_ADMIN_ENDPOINT", S3_ENDPOINT)
EVIDENCE_PATH = Path(os.getenv(
    "PIPELINE_RECOVERY_EVIDENCE_PATH",
    str(ROOT / "docs/pipeline-worker-recovery-evidence.json"),
))

if ROWS < PARTITIONS or PARTITIONS < 4 or ROWS % PARTITIONS:
    raise SystemExit("PIPELINE_RECOVERY_ROWS must be evenly divisible across at least four partitions")
if LEASE_SECONDS < 10:
    raise SystemExit("PIPELINE_RECOVERY_LEASE_SECONDS must be at least 10 seconds")
if not os.getenv("DATABASE_URL", "").startswith("postgresql"):
    raise SystemExit("Worker-loss recovery requires a migrated PostgreSQL DATABASE_URL")


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def request(api_url: str, method: str, path: str, body: dict[str, Any] | None = None) -> Any:
    payload = None if body is None else json.dumps(body, separators=(",", ":")).encode()
    req = urllib.request.Request(
        f"{api_url}{path}", data=payload, method=method,
        headers={"Accept": "application/json", **({"Content-Type": "application/json"} if payload else {})},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            raw = response.read()
    except urllib.error.HTTPError as exc:
        raise AssertionError(f"{method} {path}: HTTP {exc.code}: {exc.read(3000).decode(errors='replace')}") from exc
    return json.loads(raw) if raw else {}


def wait_for_api(api_url: str, process: subprocess.Popen, deadline: float) -> None:
    while time.time() < deadline:
        if process.poll() is not None:
            raise AssertionError(f"API exited before readiness with code {process.returncode}")
        try:
            request(api_url, "GET", "/health/ready")
            return
        except Exception:
            time.sleep(0.2)
    raise AssertionError("API did not become ready")


def wait_for_job(api_url: str, job_id: str, predicate, deadline: float) -> dict[str, Any]:
    last: dict[str, Any] = {}
    while time.time() < deadline:
        last = request(api_url, "GET", f"/jobs/{job_id}")
        if predicate(last):
            return last
        time.sleep(0.2)
    raise AssertionError(f"Job condition timed out: {last}")


def worker_env(base: dict[str, str], api_url: str, name: str, cache: Path, staging: Path, health_port: int) -> dict[str, str]:
    return {
        **base,
        "PYTHONUNBUFFERED": "1",
        "APP_ENV": "test",
        "AUTH_MODE": "local",
        "WORKER_API_URL": api_url,
        "WORKER_TOKEN": "local-recovery-rehearsal",
        "WORKER_NAME": name,
        "WORKER_PROJECT_ID": "default",
        "WORKER_JOB_TYPES": "pipeline.duckdb.deliver",
        "WORKER_CONCURRENCY": "1",
        "WORKER_LEASE_SECONDS": str(LEASE_SECONDS),
        "WORKER_POLL_SECONDS": "0.1",
        "WORKER_HEARTBEAT_SECONDS": "2",
        "WORKER_REQUEST_TIMEOUT_SECONDS": str(TIMEOUT_SECONDS),
        "WORKER_HEALTH_HOST": "127.0.0.1",
        "WORKER_HEALTH_PORT": str(health_port),
        "DATA_SNAPSHOT_ROOT": str(staging),
        "DATA_SNAPSHOT_CACHE_ROOT": str(cache),
        "DATA_SNAPSHOT_CACHE_LEASE_SECONDS": "0",
        "DATA_SNAPSHOT_CACHE_MAX_BYTES": str(2 * 1024 * 1024 * 1024),
        "DATA_SNAPSHOT_S3_AUTO_CREATE_BUCKET": "false",
    }


def cache_files(path: Path) -> list[Path]:
    return [item for item in path.rglob("*.parquet") if item.is_file()]


def main() -> None:
    run_id = uuid.uuid4().hex[:12]
    prefix = f"pipeline-worker-recovery/{run_id}"
    asset_id = f"recovery-input-{run_id}"
    output_asset_id = f"recovery-output-{run_id}"
    graph_id = f"recovery-graph-{run_id}"
    work = Path(tempfile.mkdtemp(prefix="ontology-worker-recovery-"))
    fixture = work / "fixture"
    fixture.mkdir(parents=True)
    worker1_cache, worker2_cache = work / "worker-1-cache", work / "worker-2-cache"
    worker1_staging, worker2_staging = work / "worker-1-staging", work / "worker-2-staging"
    for path in (worker1_cache, worker2_cache, worker1_staging, worker2_staging):
        path.mkdir(parents=True)

    base_env = {**os.environ, "APP_ENV": "test", "AUTH_MODE": "local"}
    api_port = free_port()
    api_url = f"http://127.0.0.1:{api_port}"
    api_log = (work / "api.log").open("w", encoding="utf-8")
    worker1_log = (work / "worker-1.log").open("w", encoding="utf-8")
    worker2_log = (work / "worker-2.log").open("w", encoding="utf-8")
    api = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(api_port), "--log-level", "warning"],
        cwd=OMS, env=base_env, stdout=api_log, stderr=subprocess.STDOUT,
    )
    worker1 = None
    worker2 = None
    s3 = boto3.client(
        "s3", endpoint_url=S3_ADMIN_ENDPOINT,
        region_name=os.getenv("DATA_SNAPSHOT_S3_REGION", "us-east-1"),
        config=Config(s3={"addressing_style": "path"}),
    )
    try:
        wait_for_api(api_url, api, time.time() + 30)
        migration_head = current_head()
        with create_engine(os.environ["DATABASE_URL"]).connect() as connection:
            observed_migration_head = str(connection.execute(text(
                "SELECT version_num FROM alembic_version"
            )).scalar_one())
        assert observed_migration_head == migration_head, (
            observed_migration_head, migration_head,
        )
        try:
            s3.head_bucket(Bucket=BUCKET)
        except ClientError:
            s3.create_bucket(Bucket=BUCKET)

        rows_per_partition = ROWS // PARTITIONS
        for partition in range(PARTITIONS):
            start = partition * rows_per_partition
            end = start + rows_per_partition
            path = fixture / f"part-{partition:04d}.parquet"
            connection = duckdb.connect(database=":memory:")
            try:
                connection.execute(
                    f"COPY (SELECT 'asset-' || CAST(i AS VARCHAR) AS asset_id, "
                    f"CAST(i % 100 AS DOUBLE) AS risk_score, CAST(i % 20 AS INTEGER) AS category "
                    f"FROM range({start}, {end}) AS source(i)) TO '{path.as_posix()}' "
                    "(FORMAT PARQUET, COMPRESSION ZSTD)"
                )
            finally:
                connection.close()
            s3.upload_file(str(path), BUCKET, f"{prefix}/region=region-{partition:03d}/{path.name}")

        request(api_url, "POST", "/data-assets", {
            "id": asset_id, "project_id": "default", "display_name": "Recovery rehearsal input",
            "asset_schema": {}, "records": [],
        })
        snapshot = request(api_url, "POST", f"/api/v1/datasets/{asset_id}/snapshots/register", {
            "storage_uri": f"s3://{BUCKET}/{prefix}",
            "partition_spec": {"fields": ["region"], "hive_partitioning": True},
            "lineage": {"rehearsal_run_id": run_id},
        })
        assert snapshot["row_count"] == ROWS
        assert snapshot["partition_spec"]["_manifest"]["file_count"] == PARTITIONS
        request(api_url, "POST", "/pipeline-builder/graphs", {
            "id": graph_id, "project_id": "default", "display_name": "Worker loss recovery graph",
            "nodes": [
                {"id": "input", "type": "input_dataset", "config": {"asset_id": asset_id, "snapshot_id": snapshot["id"]}},
                {"id": "filter", "type": "filter", "config": {"field": "risk_score", "operator": "gte", "value": 90}},
                {"id": "output", "type": "dataset_output", "config": {"asset_id": output_asset_id}},
            ],
            "edges": [{"source": "input", "target": "filter"}, {"source": "filter", "target": "output"}],
        })
        plan = request(api_url, "POST", f"/api/v1/pipelines/{graph_id}/plans", {"executor": "duckdb"})
        queued = request(api_url, "POST", f"/api/v1/pipeline-plans/{plan['id']}/execute", {
            "mode": "deliver", "output_asset_id": output_asset_id,
            "idempotency_key": f"worker-loss-{run_id}",
        })["execution"]

        worker1 = subprocess.Popen(
            [sys.executable, "-m", "app.worker_daemon"], cwd=OMS,
            env=worker_env(base_env, api_url, f"recovery-worker-1-{run_id}", worker1_cache, worker1_staging, free_port()),
            stdout=worker1_log, stderr=subprocess.STDOUT,
        )
        wait_for_job(api_url, queued["id"], lambda job: job["status"] == "RUNNING", time.time() + 30)
        cache_deadline = time.time() + 30
        while time.time() < cache_deadline and not cache_files(worker1_cache):
            if worker1.poll() is not None:
                raise AssertionError(f"First worker exited early with code {worker1.returncode}")
            time.sleep(0.05)
        first_cache_count = len(cache_files(worker1_cache))
        assert first_cache_count > 0, "First worker never began filling its private cache"
        worker1.kill()
        worker1.wait(timeout=10)
        assert worker1.returncode != 0

        recovered = wait_for_job(
            api_url, queued["id"],
            lambda job: job["status"] == "QUEUED" and int(job["attempt"]) >= 2,
            time.time() + LEASE_SECONDS + 20,
        )
        assert any(event["event_type"] == "job.requeued" for event in recovered["events"])

        worker2 = subprocess.Popen(
            [sys.executable, "-m", "app.worker_daemon"], cwd=OMS,
            env=worker_env(base_env, api_url, f"recovery-worker-2-{run_id}", worker2_cache, worker2_staging, free_port()),
            stdout=worker2_log, stderr=subprocess.STDOUT,
        )
        completed = wait_for_job(
            api_url, queued["id"], lambda job: job["status"] in {"SUCCEEDED", "FAILED"},
            time.time() + TIMEOUT_SECONDS,
        )
        assert completed["status"] == "SUCCEEDED", completed
        assert completed["attempt"] == 2, completed
        claims = [event for event in completed["events"] if event["event_type"] == "job.claimed"]
        assert len(claims) == 2, completed["events"]
        assert len(cache_files(worker2_cache)) == PARTITIONS

        snapshots = request(api_url, "GET", f"/api/v1/datasets/{output_asset_id}/snapshots")["snapshots"]
        assert len(snapshots) == 1, snapshots
        output = snapshots[0]
        assert output["lineage"]["execution_job_id"] == queued["id"]
        assert output["lineage"]["execution_fence_job_id"] == queued["id"]
        assert output["row_count"] == ROWS // 10
        assert completed["result"]["output_snapshot"]["id"] == output["id"]

        evidence = {
            "status": "PASS",
            "provenance": {
                "migration_head": migration_head,
                "observed_migration_head": observed_migration_head,
                "harness": "oms/rehearse_pipeline_worker_recovery.py",
            },
            "run_id": run_id,
            "database": "postgresql",
            "storage": "s3-compatible",
            "input": {"rows": ROWS, "partitions": PARTITIONS, "snapshot_id": snapshot["id"]},
            "failure": {
                "worker": f"recovery-worker-1-{run_id}", "exit_code": worker1.returncode,
                "cache_files_before_kill": first_cache_count, "lease_seconds": LEASE_SECONDS,
            },
            "recovery": {
                "worker": f"recovery-worker-2-{run_id}", "attempt": completed["attempt"],
                "claim_count": len(claims), "replacement_cache_files": len(cache_files(worker2_cache)),
                "job_id": queued["id"], "output_snapshot_id": output["id"],
                "output_snapshot_count": len(snapshots), "output_rows": output["row_count"],
                "execution_fenced": output["lineage"]["execution_fence_job_id"] == queued["id"],
            },
            "verified_at": int(time.time()),
        }
        EVIDENCE_PATH.parent.mkdir(parents=True, exist_ok=True)
        EVIDENCE_PATH.write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(evidence, indent=2))
    finally:
        for process in (worker1, worker2, api):
            if process and process.poll() is None:
                process.kill()
                process.wait(timeout=10)
        for stream in (worker1_log, worker2_log, api_log):
            stream.close()


if __name__ == "__main__":
    main()

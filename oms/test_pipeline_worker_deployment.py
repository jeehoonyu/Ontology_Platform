"""Protect worker-local snapshot compute and independent cache deployment."""
from pathlib import Path


root = Path(__file__).resolve().parents[1]
compose = (root / "docker-compose.production.yml").read_text(encoding="utf-8")
daemon = (root / "oms/app/worker_daemon.py").read_text(encoding="utf-8")

worker = compose.split("  oms-worker:", 1)[1].split("\n  pilot-observer:", 1)[0]
for required in (
    "DATABASE_URL:",
    "DATA_SNAPSHOT_BACKEND:",
    "DATA_SNAPSHOT_BUCKET:",
    "DATA_SNAPSHOT_S3_ENDPOINT:",
    "DATA_SNAPSHOT_CACHE_ROOT: /var/cache/ontology/snapshots",
    "AWS_ACCESS_KEY_ID:",
    "AWS_SECRET_ACCESS_KEY:",
    "ontology_snapshots:/var/lib/ontology/snapshots",
):
    assert required in worker, required

assert "ontology_snapshot_cache:/var/cache/ontology/snapshots" not in worker
assert '"pipeline-duckdb":' in daemon
assert '"worker-local://pipeline-duckdb"' in daemon
assert 'self.api.request("POST", "/jobs/claim"' in daemon
assert "execute_duckdb_snapshot_plan(" in daemon
assert 'endpoint == "worker-local://pipeline-duckdb"' in daemon

print(
    "Pipeline worker deployment verified: worker-local DuckDB compute, "
    "authoritative API leases, object-store credentials, and independent caches."
)

"""Protect the real worker-loss rehearsal, evidence, and CI gate."""
import json
from pathlib import Path


root = Path(__file__).resolve().parents[1]
rehearsal = (root / "oms/rehearse_pipeline_worker_recovery.py").read_text(encoding="utf-8")
harness = (root / "scripts/run-pipeline-worker-recovery.ps1").read_text(encoding="utf-8")
workflow = (root / ".github/workflows/ci.yml").read_text(encoding="utf-8")
evidence = json.loads((root / "docs/pipeline-worker-recovery-evidence.json").read_text(encoding="utf-8"))

for requirement in (
    "pipeline.duckdb.deliver", "worker1.kill()", 'job["status"] == "QUEUED"',
    'event["event_type"] == "job.requeued"', 'len(claims) == 2',
    'len(snapshots) == 1', 'execution_fence_job_id',
):
    assert requirement in rehearsal, requirement
for requirement in ("postgres:16-alpine", "minio/minio:", "toxiproxy@sha256:", "alembic upgrade head"):
    assert requirement in harness, requirement
assert "Rehearse worker-process loss with independent S3 caches" in workflow
assert "rehearse_pipeline_worker_recovery.py" in workflow

assert evidence["status"] == "PASS"
assert evidence["provenance"]["migration_head"] == "0042_stream_outer_joins"
assert evidence["provenance"]["observed_migration_head"] == evidence["provenance"]["migration_head"]
assert evidence["database"] == "postgresql"
assert evidence["storage"] == "s3-compatible"
assert evidence["failure"]["cache_files_before_kill"] >= 1
assert evidence["recovery"]["attempt"] == 2
assert evidence["recovery"]["claim_count"] == 2
assert evidence["recovery"]["replacement_cache_files"] == evidence["input"]["partitions"]
assert evidence["recovery"]["output_snapshot_count"] == 1
assert evidence["recovery"]["execution_fenced"] is True

print("Pipeline worker recovery contract verified: process loss, lease recovery, private caches, and one fenced output.")

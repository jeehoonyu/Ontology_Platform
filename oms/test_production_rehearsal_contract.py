"""Static contract for the real OIDC, load, restart, and recovery release gate."""
import json
from pathlib import Path
import re

root = Path(__file__).resolve().parents[1]
realm = json.loads((root / "deploy" / "keycloak-realm.json").read_text(encoding="utf-8"))
profile = json.loads((root / "deploy" / "keycloak-user-profile.json").read_text(encoding="utf-8"))
compose = (root / "docker-compose.rehearsal.yml").read_text(encoding="utf-8")
start = (root / "scripts" / "start-production-rehearsal.ps1").read_text(encoding="utf-8")
stop = (root / "scripts" / "stop-production-rehearsal.ps1").read_text(encoding="utf-8")
acceptance = (root / "scripts" / "rehearse-production-acceptance.ps1").read_text(encoding="utf-8")
browser = (root / "frontend" / "tests" / "production" / "oidc-rbac.spec.ts").read_text(encoding="utf-8")
pipeline_browser = (root / "frontend" / "tests" / "production" / "pipeline-worker-recovery.spec.ts").read_text(encoding="utf-8")
pipeline_fixture = (root / "oms" / "build_pipeline_worker_recovery_fixture.py").read_text(encoding="utf-8")
package = json.loads((root / "frontend" / "package.json").read_text(encoding="utf-8"))
pipeline_evidence = json.loads((root / "docs" / "pipeline-worker-container-recovery-evidence.json").read_text(encoding="utf-8"))
pipeline_multidaemon_evidence = json.loads((root / "docs" / "pipeline-worker-multidaemon-recovery-evidence.json").read_text(encoding="utf-8"))
workflow = (root / ".github" / "workflows" / "production-acceptance.yml").read_text(encoding="utf-8")
ci_workflow = (root / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
migration_env = (root / "oms" / "alembic" / "env.py").read_text(encoding="utf-8")
migration_sources = [path.read_text(encoding="utf-8") for path in (root / "oms" / "alembic" / "versions").glob("*.py")]

client = next(row for row in realm["clients"] if row["clientId"] == "ontology-platform")
mapper_claims = {row["config"].get("claim.name") for row in client["protocolMappers"]}
assert {"realm_access.roles", "organization_id", "project_ids"} <= mapper_claims
assert client["publicClient"] is True and client["standardFlowEnabled"] is True
assert client["directAccessGrantsEnabled"] is False

attributes = {row["name"]: row for row in profile["attributes"]}
assert attributes["organization_id"]["permissions"]["edit"] == ["admin"]
assert attributes["organization_id"]["multivalued"] is False
assert attributes["project_ids"]["permissions"]["edit"] == ["admin"]
assert attributes["project_ids"]["multivalued"] is True

assert "keycloak-user-profile.json:/opt/keycloak/conf/ontology-user-profile.json:ro" in compose
assert "@sha256:" in compose and "AUTH_MODE: oidc" in compose
assert "oms-api-peer:" in compose and '"127.0.0.1:18001:8000"' in compose
assert "pipeline-worker-one:" in compose and "pipeline-worker-two:" in compose
assert "pipeline-worker-daemon-one:" in compose and "pipeline-worker-daemon-two:" in compose
assert 'profiles: ["pipeline-workers"]' in compose
assert 'profiles: ["pipeline-multidaemon"]' in compose
assert "DATA_SNAPSHOT_S3_ENDPOINT: http://snapshot-proxy:9000" in compose
assert "/var/cache/ontology/snapshots:rw,noexec,nosuid,nodev" in compose
assert "toxiproxy@sha256:" in compose and "minio/minio@sha256:" in compose
assert "update users/profile" in start
assert "http://127.0.0.1:18001/health/ready" in start
assert "attributes.organization_id=pilot" in start and "attributes.project_ids=default" in start
assert "Tenant attributes were not persisted" in start
for profile_name in ("plugin-execution", "pipeline-workers", "pipeline-multidaemon"):
    assert f'"--profile", "{profile_name}"' in stop

for required in (
    "test:production-oidc",
    "restart oms-api",
    "rehearse-recovery.ps1",
    "Invoke-PipelineWorkerAcceptance",
    "Invoke-PipelineWorkerMultiDaemonAcceptance",
    "OnlyPipelineMultiDaemon",
    "docker -H $firstEndpoint load",
    "docker -H $secondEndpoint load",
    "docker kill",
    "container-isolated and independent-Docker-daemon pipeline worker recovery",
    "PRODUCTION_ACCEPTANCE_PASSED",
):
    assert required in acceptance, required
assert "Array.from({ length: 50 }" in browser
assert 'fetch("/tenancy/organizations"' in browser
assert "APPROVAL_REQUIRED" in browser and 'toBe("SUCCESS")' in browser
assert "crossReplicaEvent" in browser and "http://localhost:18001" in browser
assert "crossReplicaReplay" in browser and "idempotent_replay" in browser
assert "durableJobRequest" in browser and "changedJobRequest" in browser
assert "chaosJob" in browser and "staleCompletion" in browser and "recoveryEvidence" in browser
assert "abandoned-worker chaos recovery" in acceptance
assert package["scripts"]["test:production-pipeline-worker"].endswith("pipeline-worker-recovery.spec.ts")
for required in (
    "build_pipeline_worker_recovery_fixture.py", 'toBe("SUCCEEDED")', "job.attempt).toBe(2)",
    "execution_fence_job_id", "snapshots).toHaveLength(1)", "rehearsal-pipeline-worker-two",
):
    assert required in pipeline_browser, required
assert "FORMAT PARQUET" in pipeline_fixture and "s3.upload_file" in pipeline_fixture
assert "rehearse-production-acceptance.ps1" in workflow
assert "production-pipeline-worker-recovery-evidence" in workflow
assert "production-pipeline-worker-multidaemon-evidence" in workflow
assert pipeline_evidence["status"] == "PASS"
assert pipeline_evidence["provenance"]["migration_head"] == pipeline_evidence["provenance"]["observed_migration_head"]
assert pipeline_evidence["first_worker"]["exit_code"] != 0
assert pipeline_evidence["first_worker"]["private_cache_files_before_kill"] >= 1
assert pipeline_evidence["replacement_worker"]["private_cache_files"] == pipeline_evidence["input_partitions"]
assert pipeline_evidence["replacement_worker"]["attempt"] == 2
assert pipeline_evidence["publication"]["claim_count"] == 2
assert pipeline_evidence["publication"]["requeue_count"] == 1
assert pipeline_evidence["publication"]["success_count"] == 1
assert pipeline_evidence["publication"]["output_snapshot_count"] == 1
assert pipeline_evidence["publication"]["execution_fenced"] is True
assert "token" not in json.dumps(pipeline_evidence).lower()
assert pipeline_multidaemon_evidence["status"] == "PASS"
assert pipeline_multidaemon_evidence["provenance"]["migration_head"] == pipeline_multidaemon_evidence["provenance"]["observed_migration_head"]
assert pipeline_multidaemon_evidence["topology"]["independent_docker_daemons"] == 2
assert pipeline_multidaemon_evidence["topology"]["shared_worker_filesystem"] is False
assert pipeline_multidaemon_evidence["topology"]["shared_image_store"] is False
assert pipeline_multidaemon_evidence["topology"]["shared_cache"] is False
assert pipeline_multidaemon_evidence["topology"]["physical_hosts"] == 1
assert pipeline_multidaemon_evidence["first_worker"]["exit_code"] != 0
assert pipeline_multidaemon_evidence["first_worker"]["private_cache_files_before_kill"] >= 1
assert pipeline_multidaemon_evidence["replacement_worker"]["private_cache_files"] == pipeline_multidaemon_evidence["input_partitions"]
assert pipeline_multidaemon_evidence["replacement_worker"]["attempt"] == 2
assert pipeline_multidaemon_evidence["publication"]["claim_count"] == 2
assert pipeline_multidaemon_evidence["publication"]["requeue_count"] == 1
assert pipeline_multidaemon_evidence["publication"]["success_count"] == 1
assert pipeline_multidaemon_evidence["publication"]["output_snapshot_count"] == 1
assert pipeline_multidaemon_evidence["publication"]["execution_fenced"] is True
assert "token" not in json.dumps(pipeline_multidaemon_evidence).lower()
assert "identity_scale_evidence.py" in acceptance
assert "oidc-identity-scale-evidence.json" in acceptance
assert "playwright install --with-deps chrome" in workflow
for required in (
    "Verify packaged API v1 compatibility inventory",
    "app.state.api_v1_compatibility_summary",
    '"/api/v1/imports/templates" in schema["paths"]',
    '"x-ontologyos-compatibility-source"',
):
    assert required in ci_workflow, required
assert "pg_advisory_xact_lock" in migration_env
assert "connection.dialect.name == \"postgresql\"" in migration_env
revision_ids = [match.group(1) for source in migration_sources if (match := re.search(r'^revision = "([^"]+)"', source, re.MULTILINE))]
assert revision_ids and all(len(revision_id) <= 32 for revision_id in revision_ids), revision_ids

print("Production rehearsal contract verified: OIDC, tenant RBAC, load, cross-replica collaboration, migration serialization, restart, and restore gates are wired.")

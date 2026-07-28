"""Integrity-protected portable recovery, authorization, and rollback tests."""
import copy
import json
import os
import tempfile

tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tmpdir.name, 'recovery.db')}"
os.environ["AUTH_MODE"] = "local"
os.environ["APP_ENV"] = "test"

from fastapi.testclient import TestClient  # noqa: E402

from app import connectivity, models, platform_runtime, system_hardening, webhooks_ops  # noqa: E402
from app.database import SessionLocal  # noqa: E402
from app.main import app  # noqa: E402

client = TestClient(app)
passed = 0


def ok(response, label, status=200):
    global passed
    assert response.status_code == status, f"{label}: {response.status_code} {response.text[:1200]}"
    passed += 1
    return response.json() if response.content else {}


ok(client.post("/object-types", json={
    "id": "recovery_asset", "display_name": "Recovery Asset", "properties": {"name": {"type": "string"}},
}), "create recovery object type")
secret = "portable-snapshots-must-never-export-this"
ok(client.post("/listeners", json={
    "id": "recovery-listener", "display_name": "Recovery Listener", "auth_type": "bearer",
    "auth_secret": secret, "event_schema": {"asset_id": {"required": True}},
}), "create protected listener")
with SessionLocal() as db:
    db.add(connectivity.ConnectionSource(
        id="recovery-source", project_id="default", display_name="Protected source", source_type="rest",
        config={"url": "https://example.invalid/data", "password": secret, "nested": {"token": secret}},
        uses_agent=False, status="ACTIVE", created_at=1,
    ))
    db.commit()

ok(client.post("/artifacts", json={
    "id": "recovery-builder",
    "artifact_type": "pipeline",
    "display_name": "Recovery builder",
    "state": {"nodes": [], "edges": []},
}), "create recovery artifact", 201)
ok(client.post("/artifacts/recovery-builder/commands", json={
    "expected_lock_version": 1,
    "idempotency_key": "recovery-builder-command-v1",
    "commands": [{
        "command_id": "add-source",
        "command": "add_node",
        "payload": {"node": {"id": "source", "position": {"x": 40, "y": 80}, "data": {"label": "Source", "nodeType": "dataset_input"}}},
    }],
}), "create durable command receipt")
recovery_job = ok(client.post("/jobs", json={
    "job_type": "report.generate",
    "subject_type": "report",
    "subject_id": "recovery-report",
    "payload": {"format": "markdown"},
    "idempotency_key": "recovery-report-job-v1",
}), "create durable job idempotency receipt", 201)

snapshot = ok(client.get("/project/export"), "export portable snapshot")
assert snapshot["snapshot_version"] == 3
assert snapshot["project_scope"] == {
    "project_id": "default",
    "organization_id": "local",
    "scope_mode": "single_project",
}
assert snapshot["snapshot_format"] == "ontology-platform-portable"
assert len(snapshot["integrity"]["checksum"]) == 64
assert snapshot["integrity"]["resource_count"] == sum(snapshot["integrity"]["counts"].values())
assert secret not in json.dumps(snapshot)
listener_snapshot = next(row for row in snapshot["webhook_listeners"] if row["id"] == "recovery-listener")
assert listener_snapshot["auth_secret"] is None
assert any(row["resource_id"] == "recovery-listener" for row in snapshot["rebind_required"])
source_snapshot = next(row for row in snapshot["connection_sources"] if row["id"] == "recovery-source")
assert source_snapshot["config"]["password"] == "[REDACTED]" and source_snapshot["config"]["nested"]["token"] == "[REDACTED]"
assert any(row["resource_id"] == "recovery-source" for row in snapshot["rebind_required"])
assert len(snapshot["platform_artifact_command_receipts"]) == 1
assert snapshot["platform_artifact_command_receipts"][0]["request_hash"]
assert len(snapshot["platform_job_idempotency_receipts"]) == 1
assert snapshot["platform_job_idempotency_receipts"][0]["job_id"] == recovery_job["id"]
assert snapshot["platform_job_idempotency_receipts"][0]["request_hash"]
with SessionLocal() as db:
    db.query(platform_runtime.ArtifactCommandReceipt).delete()
    db.query(platform_runtime.PlatformJobIdempotencyReceipt).delete()
    db.commit()
passed += 13

validation = ok(client.post("/project/import/validate", json={"snapshot": snapshot}), "validate clean snapshot")
assert validation["status"] == "VALID" and validation["resource_count"] > 0
passed += 1

dry_run = ok(client.post("/project/import", json={"snapshot": snapshot, "mode": "merge", "dry_run": True}), "dry-run restore")
assert dry_run["status"] == "VALIDATED"
passed += 1

tampered = copy.deepcopy(snapshot)
next(row for row in tampered["object_types"] if row["id"] == "recovery_asset")["display_name"] = "Tampered"
invalid = ok(client.post("/project/import/validate", json={"snapshot": tampered}), "reject tampered checksum")
assert invalid["status"] == "INVALID" and any("checksum" in error.lower() for error in invalid["errors"])
passed += 1
ok(client.post("/project/import", json={"snapshot": tampered}), "tampered import fails before mutation", 400)
with SessionLocal() as db:
    assert db.get(models.ObjectType, "recovery_asset").display_name == "Recovery Asset"
    passed += 1

# A valid manifest with a relational error is rejected before any rows are applied.
relationally_broken = system_hardening._finalize_snapshot({
    "project_scope": {"project_id": "default", "organization_id": "local", "scope_mode": "single_project"},
    "organizations": [{"id": "local"}],
    "projects": [{"id": "default", "organization_id": "local"}],
    "object_types": [{"id": "rollback_asset", "project_id": "default", "display_name": "Must Roll Back", "properties": {}}],
    "link_types": [{
        "id": "broken_link", "project_id": "default", "display_name": "Broken", "source_object_type_id": "rollback_asset",
        "target_object_type_id": "missing_target", "cardinality": "ONE_TO_MANY",
    }],
})
failed_restore = client.post("/project/import", json={"snapshot": relationally_broken, "mode": "merge"})
assert failed_restore.status_code == 400, failed_restore.text
passed += 1
with SessionLocal() as db:
    assert db.get(models.ObjectType, "rollback_asset") is None
    passed += 1

legacy = client.post("/project/import/validate", json={"snapshot": {"snapshot_version": 1}}).json()
assert legacy["status"] == "INVALID" and any("allow_legacy" in error for error in legacy["errors"])
passed += 1

# Re-importing a redacted snapshot into the source environment preserves its separately stored credential.
merged = ok(client.post("/project/import", json={"snapshot": snapshot, "mode": "merge"}), "merge clean snapshot")
assert merged["status"] == "IMPORTED"
with SessionLocal() as db:
    listener = db.get(webhooks_ops.WhListener, "recovery-listener")
    assert listener and listener.auth_secret == secret
    receipt = db.query(platform_runtime.ArtifactCommandReceipt).filter(
        platform_runtime.ArtifactCommandReceipt.artifact_id == "recovery-builder"
    ).one()
    assert receipt.idempotency_key == "recovery-builder-command-v1" and receipt.request_hash
    job_receipt = db.query(platform_runtime.PlatformJobIdempotencyReceipt).filter(
        platform_runtime.PlatformJobIdempotencyReceipt.job_id == recovery_job["id"]
    ).one()
    assert job_receipt.idempotency_key == "recovery-report-job-v1" and job_receipt.request_hash
    passed += 2

same_logical_receipt = copy.deepcopy(snapshot)
same_logical_receipt["platform_artifact_command_receipts"][0]["id"] = "alternate-generated-receipt-id"
same_logical_receipt = system_hardening._finalize_snapshot(same_logical_receipt)
reconciled = ok(client.post("/project/import", json={"snapshot": same_logical_receipt}), "reconcile receipt by natural key")
assert reconciled["counts"]["skipped"] >= 1
with SessionLocal() as db:
    assert db.query(platform_runtime.ArtifactCommandReceipt).count() == 1
    passed += 1

conflicting_receipt = copy.deepcopy(same_logical_receipt)
conflicting_receipt["platform_artifact_command_receipts"][0]["request_hash"] = "f" * 64
conflicting_receipt = system_hardening._finalize_snapshot(conflicting_receipt)
ok(client.post("/project/import", json={"snapshot": conflicting_receipt}), "reject contradictory receipt evidence", 409)
with SessionLocal() as db:
    assert db.query(platform_runtime.ArtifactCommandReceipt).one().request_hash != "f" * 64
    passed += 1

same_job_receipt = copy.deepcopy(snapshot)
same_job_receipt["platform_job_idempotency_receipts"][0]["id"] = "alternate-job-receipt-id"
same_job_receipt = system_hardening._finalize_snapshot(same_job_receipt)
reconciled_job = ok(client.post("/project/import", json={"snapshot": same_job_receipt}), "reconcile job receipt by scope hash")
assert reconciled_job["counts"]["skipped"] >= 1
with SessionLocal() as db:
    assert db.query(platform_runtime.PlatformJobIdempotencyReceipt).count() == 1
    passed += 1

conflicting_job_receipt = copy.deepcopy(same_job_receipt)
conflicting_job_receipt["platform_job_idempotency_receipts"][0]["request_hash"] = "e" * 64
conflicting_job_receipt = system_hardening._finalize_snapshot(conflicting_job_receipt)
ok(client.post("/project/import", json={"snapshot": conflicting_job_receipt}), "reject contradictory job receipt evidence", 409)
with SessionLocal() as db:
    assert db.query(platform_runtime.PlatformJobIdempotencyReceipt).one().request_hash != "e" * 64
    passed += 1

# Portable recovery is an installation-level operation until every legacy resource has project ownership.
ok(client.post("/admin/service-accounts", json={
    "id": "recovery-reader", "display_name": "Recovery Reader", "organization_id": "local",
}), "create restricted service account", 201)
issued = ok(client.post("/admin/tokens", json={
    "principal_type": "service_account", "principal_id": "recovery-reader",
    "scopes": ["view", "project:default:view"], "ttl_seconds": 3600,
}), "issue restricted token", 201)
os.environ["AUTH_MODE"] = "oidc"
restricted = {"Authorization": f"Bearer {issued['token']}"}
ok(client.get("/project/export", headers=restricted), "restricted principal cannot export installation", 403)
ok(client.post("/project/import/validate", headers=restricted, json={"snapshot": snapshot}), "restricted principal cannot validate restore", 403)
os.environ["AUTH_MODE"] = "local"

print(f"Production recovery runtime verified: {passed} assertions passed.")

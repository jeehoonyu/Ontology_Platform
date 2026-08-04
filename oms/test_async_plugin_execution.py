"""Exercise durable, lease-fenced signed plugin execution."""

import base64
import hashlib
import io
import os
import tempfile
import time
import zipfile


tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tmpdir.name, 'async-plugins.db')}"
os.environ["PLUGIN_BUNDLE_ROOT"] = os.path.join(tmpdir.name, "bundles")
os.environ["PLUGIN_EXECUTION_MODE"] = "worker"
os.environ["AUTH_MODE"] = "local"
os.environ["APP_ENV"] = "test"

from cryptography.hazmat.primitives import serialization  # noqa: E402
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.database import SessionLocal  # noqa: E402
from app.main import app  # noqa: E402
from app.platform_runtime import PlatformJobLease  # noqa: E402
from app.plugin_runtime import canonical_manifest  # noqa: E402


client = TestClient(app)
private_key = Ed25519PrivateKey.generate()
public_key = private_key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)


def ok(response, expected=200):
    assert response.status_code == expected, f"{response.status_code}: {response.text[:1500]}"
    return response.json()


stream = io.BytesIO()
with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_DEFLATED) as archive:
    archive.writestr("plugin.py", "def handle(request):\n    return {'value': request['input']['value']}\n")
bundle = stream.getvalue()
manifest = {
    "schema_version": 1,
    "sdk_api_version": 1,
    "plugin_id": "acme.async-transform",
    "version": "1.0.0",
    "kind": "transform",
    "runtime": "python3",
    "entrypoint": "plugin.py",
    "bundle_sha256": hashlib.sha256(bundle).hexdigest(),
    "capabilities": ["scratch_write"],
    "operations": {
        "transform": {
            "input_schema": {"type": "object", "properties": {"value": {"type": "integer"}}, "required": ["value"], "additionalProperties": False},
            "output_schema": {"type": "object", "properties": {"value": {"type": "integer"}}, "required": ["value"], "additionalProperties": False},
        }
    },
    "limits": {"timeout_seconds": 5, "memory_mb": 128, "max_input_bytes": 100000, "max_output_bytes": 100000},
}

ok(client.post("/api/v1/plugins/trust-keys", json={
    "id": "async-vendor", "organization_id": "local", "display_name": "Async vendor",
    "public_key": base64.b64encode(public_key).decode(),
}), 201)
plugin = ok(client.post("/api/v1/plugins/register", json={
    "project_id": "default",
    "manifest": manifest,
    "bundle_base64": base64.b64encode(bundle).decode(),
    "signer_key_id": "async-vendor",
    "signature": base64.b64encode(private_key.sign(canonical_manifest(manifest))).decode(),
}), 201)
ok(client.post(f"/api/v1/plugins/{plugin['id']}/activate"))
ok(client.put("/runtime/workers/plugin-worker", json={
    "project_id": "default", "supported_job_types": ["plugin.execute"], "max_concurrency": 1,
    "labels": {"runtime": "plugin-oci-executor"},
}))

request = {"operation": "transform", "input": {"value": 42}, "idempotency_key": "durable-42", "max_attempts": 2}
execution = ok(client.post(f"/api/v1/plugins/{plugin['id']}/invoke-async", json=request), 202)
assert execution["status"] == "QUEUED" and execution["job_id"]
replay = ok(client.post(f"/api/v1/plugins/{plugin['id']}/invoke-async", json=request), 202)
assert replay["id"] == execution["id"] and replay["job_id"] == execution["job_id"]
ok(client.post(f"/api/v1/plugins/{plugin['id']}/invoke-async", json={**request, "input": {"value": 43}}), 409)

claim = ok(client.post("/jobs/claim", json={"worker_id": "plugin-worker", "supported_job_types": ["plugin.execute"]}))["job"]
assert claim["id"] == execution["job_id"] and claim["status"] == "RUNNING"
ok(client.post("/api/v1/plugins/workers/work", json={"job_id": claim["id"], "lease_token": "wrong"}), 409)
work = ok(client.post("/api/v1/plugins/workers/work", json={"job_id": claim["id"], "lease_token": claim["lease_token"]}))
assert base64.b64decode(work["bundle_base64"]) == bundle
assert work["input"] == {"value": 42} and work["bundle_sha256"] == manifest["bundle_sha256"]
ok(client.post(f"/jobs/{claim['id']}/complete", json={"lease_token": claim["lease_token"]}), 409)
ok(client.post("/api/v1/plugins/workers/complete", json={
    "job_id": claim["id"], "lease_token": claim["lease_token"], "output": {"wrong": True},
    "sandbox": {"mode": "oci"}, "duration_ms": 10,
}), 422)
completed = ok(client.post("/api/v1/plugins/workers/complete", json={
    "job_id": claim["id"], "lease_token": claim["lease_token"], "output": {"value": 42},
    "sandbox": {"mode": "oci", "network": "none"}, "duration_ms": 10,
}))
assert completed["status"] == "SUCCEEDED" and completed["output"] == {"value": 42}
duplicate_completion = ok(client.post("/api/v1/plugins/workers/complete", json={
    "job_id": claim["id"], "lease_token": claim["lease_token"], "output": {"value": 42},
    "sandbox": {"mode": "oci", "network": "none"}, "duration_ms": 10,
}))
assert duplicate_completion["id"] == completed["id"]
ok(client.post("/api/v1/plugins/workers/complete", json={
    "job_id": claim["id"], "lease_token": claim["lease_token"], "output": {"value": 99},
    "sandbox": {"mode": "oci"}, "duration_ms": 10,
}), 409)
job = ok(client.get(f"/jobs/{claim['id']}"))
assert job["status"] == "SUCCEEDED" and job["lease"] is None

failed = ok(client.post(f"/api/v1/plugins/{plugin['id']}/invoke-async", json={
    "operation": "transform", "input": {"value": 7}, "idempotency_key": "retry-7", "max_attempts": 2,
}), 202)
first_claim = ok(client.post("/jobs/claim", json={"worker_id": "plugin-worker"}))["job"]
ok(client.post(f"/jobs/{first_claim['id']}/fail", json={"lease_token": first_claim["lease_token"], "error": "wrong callback"}), 409)
retrying = ok(client.post("/api/v1/plugins/workers/fail", json={
    "job_id": first_claim["id"], "lease_token": first_claim["lease_token"], "error": "runtime unavailable",
    "retriable": True, "retry_delay_seconds": 0,
}))
assert retrying["status"] == "QUEUED"
duplicate_failure = ok(client.post("/api/v1/plugins/workers/fail", json={
    "job_id": first_claim["id"], "lease_token": first_claim["lease_token"], "error": "runtime unavailable",
    "retriable": True, "retry_delay_seconds": 0,
}))
assert duplicate_failure["status"] == "QUEUED"
second_claim = ok(client.post("/jobs/claim", json={"worker_id": "plugin-worker"}))["job"]
assert second_claim["id"] == failed["job_id"] and second_claim["attempt"] == 2
terminal = ok(client.post("/api/v1/plugins/workers/fail", json={
    "job_id": second_claim["id"], "lease_token": second_claim["lease_token"], "error": "plugin rejected input",
    "retriable": True, "retry_delay_seconds": 0,
}))
assert terminal["status"] == "FAILED" and terminal["completed_at"]

cancelled = ok(client.post(f"/api/v1/plugins/{plugin['id']}/invoke", json={
    "operation": "transform", "input": {"value": 9}, "idempotency_key": "cancel-9",
}))
assert cancelled["status"] == "QUEUED"
ok(client.post(f"/jobs/{cancelled['job_id']}/cancel"))
assert ok(client.get(f"/api/v1/plugins/executions/{cancelled['id']}"))["status"] == "CANCELLED"
ok(client.post(f"/jobs/{cancelled['job_id']}/retry"))
assert ok(client.get(f"/api/v1/plugins/executions/{cancelled['id']}"))["status"] == "QUEUED"

stale_claim = ok(client.post("/jobs/claim", json={"worker_id": "plugin-worker"}))["job"]
with SessionLocal() as database:
    lease = database.query(PlatformJobLease).filter(PlatformJobLease.job_id == stale_claim["id"]).one()
    lease.expires_at = int(time.time()) - 1
    database.commit()
ok(client.get("/jobs/summary"))
recovered = ok(client.get(f"/api/v1/plugins/executions/{cancelled['id']}"))
assert recovered["status"] == "QUEUED" and recovered["error"]

snapshot = ok(client.get("/project/export?project_id=default"))
snapshot_execution = next(row for row in snapshot["plugin_executions"] if row["id"] == execution["id"])
assert snapshot_execution["job_id"] == execution["job_id"]

tmpdir.cleanup()
print("Async plugin execution verified: queueing, idempotency, signed work delivery, fenced completion, retry, cancel, stale recovery, and snapshot evidence.")

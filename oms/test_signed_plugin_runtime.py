"""Exercise signed registration, sandbox execution, governance, and revocation."""

import base64
import hashlib
import io
import os
from pathlib import Path
import shutil
import tempfile
import zipfile
from datetime import datetime, timedelta, timezone


tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tmpdir.name, 'plugins.db')}"
os.environ["PLUGIN_BUNDLE_ROOT"] = os.path.join(tmpdir.name, "bundles")
os.environ["PLUGIN_SANDBOX_MODE"] = "process"
os.environ["APP_ENV"] = "development"

from cryptography import x509  # noqa: E402
from cryptography.hazmat.primitives import hashes, serialization  # noqa: E402
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey  # noqa: E402
from cryptography.hazmat.primitives.asymmetric import rsa  # noqa: E402
from cryptography.x509.oid import NameOID  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402
from app.database import SessionLocal  # noqa: E402
from app.plugin_runtime import PluginExecution, PluginTrustKey, PluginVersion, _oci_command, canonical_manifest  # noqa: E402
from app.plugin_oci import is_digest_pinned_image  # noqa: E402


client = TestClient(app)
private_key = Ed25519PrivateKey.generate()
public_bytes = private_key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)


def bundle(source: str) -> bytes:
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("plugin.py", source)
    return stream.getvalue()


def signed_request(plugin_id: str, version: str, source: str, operations: dict, *, limits=None, signature_key=private_key, capabilities=None, network_policy=None):
    raw = bundle(source)
    manifest = {
        "schema_version": 1,
        "plugin_id": plugin_id,
        "version": version,
        "kind": "transform",
        "runtime": "python3",
        "entrypoint": "plugin.py",
        "bundle_sha256": hashlib.sha256(raw).hexdigest(),
        "capabilities": capabilities or ["scratch_write"],
        "operations": operations,
        "limits": limits or {"timeout_seconds": 5, "memory_mb": 128, "max_input_bytes": 100000, "max_output_bytes": 100000},
    }
    if network_policy:
        manifest["network_policy"] = network_policy
    signature = signature_key.sign(canonical_manifest(manifest))
    return {"project_id": "default", "manifest": manifest, "bundle_base64": base64.b64encode(raw).decode(), "signer_key_id": "vendor-key", "signature": base64.b64encode(signature).decode()}


def ca_pem(common_name: str) -> str:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, common_name)])
    now = datetime.now(timezone.utc)
    certificate = (
        x509.CertificateBuilder().subject_name(subject).issuer_name(subject).public_key(key.public_key())
        .serial_number(x509.random_serial_number()).not_valid_before(now - timedelta(minutes=1))
        .not_valid_after(now + timedelta(days=1)).add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .sign(key, hashes.SHA256())
    )
    return certificate.public_bytes(serialization.Encoding.PEM).decode("ascii")


key_response = client.post("/api/v1/plugins/trust-keys", json={"id": "vendor-key", "organization_id": "local", "display_name": "Test vendor", "public_key": base64.b64encode(public_bytes).decode()})
assert key_response.status_code == 201, key_response.text
assert len(key_response.json()["fingerprint"]) == 64

source = """
def handle(request):
    operation = request['operation']
    if operation == 'read_outside':
        # A path that exists on THIS host, so the sandbox is what stops the read.
        # This was hardcoded to 'C:/Windows/System32/drivers/etc/hosts', which
        # exists only on Windows. Everywhere else the open failed with
        # FileNotFoundError before the sandbox was ever consulted -- so the
        # filesystem-escape denial, the thing this case exists to prove, was
        # never exercised off Windows and the failure looked like a host quirk.
        import os as _os
        outside = 'C:/Windows/System32/drivers/etc/hosts' if _os.name == 'nt' else '/etc/hosts'
        open(outside, 'r').read()
    if operation == 'network_probe':
        import socket
        socket.create_connection(('127.0.0.1', 9), timeout=0.1)
    return {'operation': operation, 'value': request['input'].get('value'), 'pid_isolated': True}
"""
payload = signed_request("acme.clean-transform", "1.0.0", source, {
    "transform": {
        "input_schema": {"type": "object", "properties": {"value": {"type": "integer"}}, "required": ["value"], "additionalProperties": False},
        "output_schema": {"type": "object", "properties": {"operation": {"type": "string"}, "value": {"type": "integer"}, "pid_isolated": {"type": "boolean"}}, "required": ["operation", "value", "pid_isolated"], "additionalProperties": False},
    },
    "read_outside": {},
    "network_probe": {},
})

tampered = {**payload, "signature": base64.b64encode(b"0" * 64).decode()}
response = client.post("/api/v1/plugins/register", json=tampered)
assert response.status_code == 422, response.text
assert "signature" in response.text.lower()

wrong_hash = {**payload, "manifest": {**payload["manifest"], "bundle_sha256": "0" * 64}}
wrong_hash["signature"] = base64.b64encode(private_key.sign(canonical_manifest(wrong_hash["manifest"]))).decode()
response = client.post("/api/v1/plugins/register", json=wrong_hash)
assert response.status_code == 422, response.text
assert "bundle_sha256" in response.text

wrong_sdk = {**payload, "manifest": {**payload["manifest"], "sdk_api_version": 999}}
wrong_sdk["signature"] = base64.b64encode(private_key.sign(canonical_manifest(wrong_sdk["manifest"]))).decode()
response = client.post("/api/v1/plugins/register", json=wrong_sdk)
assert response.status_code == 422, response.text
assert "sdk_api_version must be 1" in response.text

network_payload = signed_request(
    "acme.enterprise-connector", "1.0.0", "def handle(request):\n    return {'ok': True}\n", {"fetch": {}},
    capabilities=["network"],
    network_policy={"allowed_hosts": ["api.operations.example"], "allowed_ports": [443], "tls_ca_bundle_pem": ca_pem("Enterprise CA A")},
)
network_registered = client.post("/api/v1/plugins/register", json=network_payload)
assert network_registered.status_code == 201, network_registered.text
tampered_network = {**network_payload, "manifest": {**network_payload["manifest"], "network_policy": {
    **network_payload["manifest"]["network_policy"], "tls_ca_bundle_pem": ca_pem("Enterprise CA B"),
}}}
tampered_response = client.post("/api/v1/plugins/register", json=tampered_network)
assert tampered_response.status_code == 422 and "signature" in tampered_response.text.lower()
with SessionLocal() as database:
    database.query(PluginVersion).filter(PluginVersion.id == network_registered.json()["id"]).delete()
    database.commit()

response = client.post("/api/v1/plugins/register", json=payload)
assert response.status_code == 201, response.text
plugin = response.json()
assert plugin["status"] == "VERIFIED"
assert plugin["manifest_sha256"] == hashlib.sha256(canonical_manifest(payload["manifest"])).hexdigest()

response = client.post("/api/v1/plugins/register", json=payload)
assert response.status_code == 409, response.text

response = client.post(f"/api/v1/plugins/{plugin['id']}/activate")
assert response.status_code == 200, response.text
assert response.json()["status"] == "ACTIVE"

catalog = client.get("/api/v1/plugins/catalog?project_id=default&kind=transform")
assert catalog.status_code == 200, catalog.text
assert [item["plugin_id"] for item in catalog.json()["plugins"]] == ["acme.clean-transform"]
builder_catalog = client.get("/builder/catalogs/pipeline?project_id=default")
assert builder_catalog.status_code == 200, builder_catalog.text
assert [item["plugin_id"] for item in builder_catalog.json()["plugins"]] == ["acme.clean-transform"]

invoke = {"operation": "transform", "input": {"value": 42}, "idempotency_key": "same-request"}
response = client.post(f"/api/v1/plugins/{plugin['id']}/invoke", json=invoke)
assert response.status_code == 200, response.text
execution = response.json()
assert execution["status"] == "SUCCEEDED"
assert execution["output"] == {"operation": "transform", "value": 42, "pid_isolated": True}
assert execution["sandbox"]["mode"] == "process"
assert execution["evidence"]["bundle_sha256"] == payload["manifest"]["bundle_sha256"]

replay = client.post(f"/api/v1/plugins/{plugin['id']}/invoke", json=invoke)
assert replay.status_code == 200, replay.text
assert replay.json()["id"] == execution["id"]
conflict = client.post(f"/api/v1/plugins/{plugin['id']}/invoke", json={**invoke, "input": {"value": 43}})
assert conflict.status_code == 409, conflict.text
invalid_input = client.post(f"/api/v1/plugins/{plugin['id']}/invoke", json={"operation": "transform", "input": {"value": "not-an-integer"}})
assert invalid_input.status_code == 422, invalid_input.text
assert "signed contract" in invalid_input.text

for operation in ("read_outside", "network_probe"):
    denied = client.post(f"/api/v1/plugins/{plugin['id']}/invoke", json={"operation": operation, "input": {}, "idempotency_key": operation})
    assert denied.status_code == 502, denied.text
    assert "PermissionError" in denied.text

snapshot_response = client.get("/project/export?project_id=default")
assert snapshot_response.status_code == 200, snapshot_response.text
snapshot = snapshot_response.json()
assert len(snapshot["plugin_trust_keys"]) == 1
assert len(snapshot["plugin_versions"]) == 1
assert snapshot["plugin_versions"][0]["bundle_base64"] == payload["bundle_base64"]
validated = client.post("/project/import/validate", json={"project_id": "default", "snapshot": snapshot})
assert validated.status_code == 200, validated.text
assert validated.json()["status"] == "VALID", validated.text

with SessionLocal() as database:
    database.query(PluginExecution).delete()
    database.query(PluginVersion).delete()
    database.query(PluginTrustKey).delete()
    database.commit()
shutil.rmtree(os.environ["PLUGIN_BUNDLE_ROOT"])
restored = client.post("/project/import", json={"project_id": "default", "snapshot": snapshot})
assert restored.status_code == 200, restored.text
assert restored.json()["status"] == "IMPORTED"
restored_catalog = client.get("/api/v1/plugins/catalog?project_id=default")
assert restored_catalog.status_code == 200
assert [item["id"] for item in restored_catalog.json()["plugins"]] == [plugin["id"]]
restored_invoke = client.post(f"/api/v1/plugins/{plugin['id']}/invoke", json={"operation": "transform", "input": {"value": 99}, "idempotency_key": "after-restore"})
assert restored_invoke.status_code == 200, restored_invoke.text
assert restored_invoke.json()["output"]["value"] == 99

slow_source = """
def handle(request):
    import time
    time.sleep(3)
    return {'unexpected': True}
"""
slow_payload = signed_request("acme.slow-transform", "1.0.0", slow_source, {"transform": {}}, limits={"timeout_seconds": 1, "memory_mb": 128, "max_input_bytes": 100000, "max_output_bytes": 100000})
slow = client.post("/api/v1/plugins/register", json=slow_payload)
assert slow.status_code == 201, slow.text
slow_id = slow.json()["id"]
assert client.post(f"/api/v1/plugins/{slow_id}/activate").status_code == 200
timed_out = client.post(f"/api/v1/plugins/{slow_id}/invoke", json={"operation": "transform", "input": {}})
assert timed_out.status_code == 502, timed_out.text
assert "execution limit" in timed_out.text

os.environ["APP_ENV"] = "production"
production_denied = client.post(f"/api/v1/plugins/{plugin['id']}/invoke", json={"operation": "transform", "input": {"value": 7}, "idempotency_key": "production-process"})
assert production_denied.status_code == 502, production_denied.text
assert "disabled in production" in production_denied.text
os.environ["PLUGIN_SANDBOX_IMAGE"] = "registry.example/plugin@sha256:" + "a" * 64
with SessionLocal() as database:
    restored_plugin = database.get(PluginVersion, plugin["id"])
    command, _, sandbox = _oci_command(Path(tmpdir.name) / "bundle", Path(tmpdir.name) / "scratch", restored_plugin, {})
assert "--read-only" in command and "--cap-drop" in command and "ALL" in command
assert "--security-opt" in command and "no-new-privileges" in command
assert "--network" in command and command[command.index("--network") + 1] == "none"
assert "--mount" not in command and sandbox["non_root"] is True
assert sandbox["sdk_api_version"] == 1
assert is_digest_pinned_image("sha256:" + "b" * 64)
assert is_digest_pinned_image("registry.example/plugin@sha256:" + "c" * 64)
assert not is_digest_pinned_image("registry.example/plugin:latest")
os.environ.pop("PLUGIN_SANDBOX_IMAGE")
os.environ["APP_ENV"] = "development"

executions = client.get(f"/api/v1/plugins/{plugin['id']}/executions")
assert executions.status_code == 200, executions.text
assert {item["status"] for item in executions.json()["executions"]} == {"SUCCEEDED", "FAILED"}

revoked = client.post("/api/v1/plugins/trust-keys/vendor-key/revoke")
assert revoked.status_code == 200, revoked.text
assert revoked.json()["revoked_plugin_versions"] == 2
catalog = client.get("/api/v1/plugins/catalog?project_id=default")
assert catalog.status_code == 200 and catalog.json()["plugins"] == []
denied = client.post(f"/api/v1/plugins/{plugin['id']}/invoke", json={"operation": "transform", "input": {}})
assert denied.status_code == 409, denied.text

audit = client.get("/audit-logs/search?event_type=plugin.execution.succeeded&limit=20")
assert audit.status_code == 200, audit.text
assert any(item["subject_id"] == execution["id"] for item in audit.json()["results"])

tmpdir.cleanup()
print("Signed plugin runtime verified: signatures, integrity, immutability, sandbox policy, idempotency, audit, timeout, production fail-closed, and revocation.")

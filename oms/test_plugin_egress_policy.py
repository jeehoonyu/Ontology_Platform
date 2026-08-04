"""Verify signed destination policy, credentials, SSRF denial, and OCI wiring."""
import os
import time
import urllib.parse
from types import SimpleNamespace
from datetime import datetime, timedelta, timezone

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from fastapi import HTTPException

from app.plugin_egress import (
    _resolved_ip,
    issue_egress_token,
    normalized_policy,
    validated_ca_bundle,
    verify_egress_token,
)
from app.plugin_oci import build_oci_command
from app.plugin_runtime import _validate_manifest
from app import plugin_executor


secret = "production-egress-secret-with-32-characters"
policy = {"allowed_hosts": ["api.vendor.example"], "allowed_ports": [443], "allow_http": False}


def test_ca_pem() -> str:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "OntologyOS test CA")])
    now = datetime.now(timezone.utc)
    certificate = (
        x509.CertificateBuilder().subject_name(subject).issuer_name(subject).public_key(key.public_key())
        .serial_number(x509.random_serial_number()).not_valid_before(now - timedelta(minutes=1))
        .not_valid_after(now + timedelta(days=1)).add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .sign(key, hashes.SHA256())
    )
    return certificate.public_bytes(serialization.Encoding.PEM).decode("ascii")


ca_pem = test_ca_pem()
ca_bundle, ca_metadata = validated_ca_bundle({"network_policy": {**policy, "tls_ca_bundle_pem": ca_pem}})
assert ca_bundle == ca_pem and ca_metadata["certificate_count"] == 1
assert len(ca_metadata["ca_bundle_sha256"]) == 64 and "BEGIN CERTIFICATE" not in str(ca_metadata)
for invalid_ca in ("not a certificate", ca_pem + "-----BEGIN PRIVATE KEY-----\nabc\n-----END PRIVATE KEY-----\n"):
    try:
        validated_ca_bundle({"network_policy": {**policy, "tls_ca_bundle_pem": invalid_ca}})
        raise AssertionError("invalid custom CA was accepted")
    except ValueError:
        pass
token = issue_egress_token(secret, policy, ttl_seconds=30, now=100)
claims = verify_egress_token(secret, token, "api.vendor.example", 443, scheme="https", now=110)
assert claims["hosts"] == ["api.vendor.example"]
for host, port, scheme in (
    ("evil.example", 443, "https"),
    ("api.vendor.example", 8443, "https"),
    ("api.vendor.example", 443, "http"),
):
    try:
        verify_egress_token(secret, token, host, port, scheme=scheme, now=110)
        raise AssertionError("unauthorized destination was accepted")
    except PermissionError:
        pass
try:
    verify_egress_token(secret, token, "api.vendor.example", 443, scheme="https", now=1000)
    raise AssertionError("expired credential was accepted")
except PermissionError:
    pass

for invalid in (
    {"allowed_hosts": ["*.example.com"], "allowed_ports": [443]},
    {"allowed_hosts": [], "allowed_ports": [443]},
    {"allowed_hosts": ["example.com"], "allowed_ports": [70000]},
    {"allowed_hosts": ["example.com"], "allowed_ports": [80], "allow_http": False},
):
    try:
        normalized_policy({"network_policy": invalid})
        raise AssertionError("invalid policy was accepted")
    except ValueError:
        pass

try:
    _resolved_ip("127.0.0.1", 80, allow_private=False)
    raise AssertionError("loopback destination was accepted")
except PermissionError:
    pass
assert _resolved_ip("127.0.0.1", 80, allow_private=True) == "127.0.0.1"

os.environ.update({
    "PLUGIN_SANDBOX_IMAGE": "registry.example/sandbox@sha256:" + "a" * 64,
    "PLUGIN_SANDBOX_NETWORK": "ontology-plugin-egress",
    "PLUGIN_EGRESS_PROXY_URL": "http://plugin-egress-proxy:8080",
    "PLUGIN_EGRESS_TOKEN_SECRET": secret,
})
manifest = {
    "limits": {"memory_mb": 128, "timeout_seconds": 10},
    "network_policy": {**policy, "tls_ca_bundle_pem": ca_pem},
}
command, _, sandbox = build_oci_command(manifest=manifest, capabilities=["network"], production=True)
assert command[command.index("--network") + 1] == "ontology-plugin-egress"
proxy_value = next(command[index + 1] for index, value in enumerate(command) if value == "--env" and command[index + 1].startswith("HTTPS_PROXY="))
parsed = urllib.parse.urlsplit(proxy_value.split("=", 1)[1])
assert parsed.hostname == "plugin-egress-proxy" and parsed.username == "plugin"
verify_egress_token(secret, parsed.password or "", "api.vendor.example", 443, scheme="https")
assert sandbox["egress_proxy"] is True
assert sandbox["egress_policy"] == policy
assert sandbox["tls_trust"] == ca_metadata
assert ca_pem not in str(sandbox)
assert token not in str(sandbox) and (parsed.password or "") not in str(sandbox)

base_manifest = {
    "schema_version": 1, "sdk_api_version": 1, "plugin_id": "vendor.network-test",
    "version": "1.0.0", "kind": "connector", "runtime": "python3", "entrypoint": "plugin.py",
    "bundle_sha256": "b" * 64, "operations": {"fetch": {}},
    "limits": {"timeout_seconds": 10, "memory_mb": 128, "max_input_bytes": 10000, "max_output_bytes": 10000},
}
for candidate in (
    {**base_manifest, "capabilities": ["network"]},
    {**base_manifest, "capabilities": [], "network_policy": policy},
):
    try:
        _validate_manifest(candidate, "b" * 64)
        raise AssertionError("invalid manifest network contract was accepted")
    except HTTPException as exc:
        assert exc.status_code == 422
valid = {**base_manifest, "capabilities": ["network"], "network_policy": {**policy, "tls_ca_bundle_pem": ca_pem}}
assert _validate_manifest(valid, "b" * 64)["capabilities"] == ["network"]

calls = []
original_oci = plugin_executor._oci


def fake_oci(*arguments, check=True):
    calls.append(arguments)
    if arguments[:2] in {("network", "inspect"), ("inspect", "--format")}:
        return SimpleNamespace(returncode=1, stdout="", stderr="missing")
    return SimpleNamespace(returncode=0, stdout="ok", stderr="")


plugin_executor._oci = fake_oci
os.environ.update({
    "PLUGIN_EGRESS_PROXY_IMAGE": "registry.example/proxy@sha256:" + "c" * 64,
    "PLUGIN_EGRESS_TOKEN_SECRET": secret,
    "PLUGIN_SANDBOX_NETWORK": "ontology-plugin-egress",
})
try:
    assert plugin_executor.ensure_egress_boundary() is True
finally:
    plugin_executor._oci = original_oci
assert any(arguments[:3] == ("network", "create", "--internal") for arguments in calls)
run = next(arguments for arguments in calls if arguments and arguments[0] == "run")
assert "--read-only" in run and "--cap-drop" in run and "no-new-privileges" in run
assert "--label" in run and any(str(value).startswith("ontology.egress.boundary=") for value in run)
assert any(arguments[:3] == ("network", "connect", "bridge") for arguments in calls)

for name in ("PLUGIN_SANDBOX_IMAGE", "PLUGIN_SANDBOX_NETWORK", "PLUGIN_EGRESS_PROXY_URL", "PLUGIN_EGRESS_TOKEN_SECRET", "PLUGIN_EGRESS_PROXY_IMAGE"):
    os.environ.pop(name, None)
print("Plugin egress policy verified: exact destinations, signed custom CA trust, short-lived grants, SSRF denial, internal network, and credential-free evidence.")

"""Protect the governed egress image, release rehearsal, and evidence contract."""
import json
from pathlib import Path


root = Path(__file__).resolve().parents[1]
dockerfile = (root / "oms/plugin-egress-proxy.Dockerfile").read_text(encoding="utf-8")
proxy = (root / "oms/app/plugin_egress.py").read_text(encoding="utf-8")
rehearsal = (root / "oms/rehearse_plugin_egress.py").read_text(encoding="utf-8")
compose = (root / "docker-compose.production.yml").read_text(encoding="utf-8")
evidence = json.loads((root / "docs/plugin-egress-rehearsal-evidence.json").read_text(encoding="utf-8"))

assert "FROM python:3.12-slim@sha256:" in dockerfile
assert "USER 65534:65534" in dockerfile
for requirement in (
    "hmac.compare_digest", "Expired egress credential", "Destination host is not allowed",
    "Private or non-routable destinations are denied", "Proxy-Authorization", "do_CONNECT",
):
    assert requirement in proxy
for requirement in (
    '"--internal"', "undeclared_destination_denied", "direct_socket_bypass_denied",
    "proxy_credentials_redacted", 'PLUGIN_EGRESS_ALLOW_PRIVATE=true', "https_custom_ca",
    "private_ca_rejected_without_signed_bundle", "tls_ca_bundle_pem", "CERTIFICATE_VERIFY_FAILED",
):
    assert requirement in rehearsal
for setting in (
    "PLUGIN_EGRESS_PROXY_IMAGE", "PLUGIN_EGRESS_PROXY_URL", "PLUGIN_EGRESS_TOKEN_SECRET",
    "PLUGIN_SANDBOX_NETWORK:-ontology-plugin-egress",
):
    assert setting in compose

assert evidence["status"] == "PASS"
assert evidence["network_internal"] is True
assert evidence["allowed_destination"]["status"] == 200
assert evidence["https_custom_ca"]["status"] == 200
assert evidence["https_custom_ca"]["mode"] == "custom_ca"
assert evidence["https_custom_ca"]["certificate_count"] == 1
assert len(evidence["https_custom_ca"]["ca_bundle_sha256"]) == 64
assert evidence["private_ca_rejected_without_signed_bundle"] is True
assert evidence["undeclared_destination_denied"] is True
assert evidence["direct_socket_bypass_denied"] is True
assert evidence["proxy_credentials_redacted"] is True
serialized = json.dumps(evidence).lower()
assert "token" not in serialized and "begin certificate" not in serialized and "private key" not in serialized

print("Plugin egress rehearsal verified: pinned proxy, signed grants, custom-CA HTTPS, internal sandbox, destination denial, bypass denial, and redacted evidence.")

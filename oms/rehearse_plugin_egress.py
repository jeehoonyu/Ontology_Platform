"""Exercise allowlisted plugin egress through a real internal Docker network."""
from __future__ import annotations

import argparse
import base64
from datetime import datetime, timedelta, timezone
import hashlib
import io
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import tempfile
import time
import zipfile

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "oms"))
from app.plugin_egress import validated_ca_bundle  # noqa: E402
from app.plugin_oci import build_oci_command, is_digest_pinned_image  # noqa: E402


def docker(*arguments: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(["docker", *arguments], text=True, capture_output=True, timeout=90, check=False)
    if check and result.returncode != 0:
        raise RuntimeError(f"docker {' '.join(arguments)} failed: {result.stderr or result.stdout}")
    return result


def bundle(source: str) -> bytes:
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("plugin.py", source)
    return stream.getvalue()


def execute(image: str, source: str, manifest: dict, capabilities: list[str]) -> tuple[subprocess.CompletedProcess[str], dict, list[str]]:
    raw = bundle(source)
    command, environment, sandbox = build_oci_command(manifest=manifest, capabilities=capabilities, production=True)
    envelope = {
        "bundle_root": "/scratch/bundle", "scratch_root": "/scratch", "entrypoint": "plugin.py",
        "capabilities": capabilities, "operation": "egress", "input": {}, "sdk_api_version": 1,
        "bundle_base64": base64.b64encode(raw).decode("ascii"), "bundle_sha256": hashlib.sha256(raw).hexdigest(),
    }
    ca_bundle, _ = validated_ca_bundle(manifest)
    if ca_bundle:
        envelope["tls_ca_bundle_pem"] = ca_bundle
    completed = subprocess.run(command, input=json.dumps(envelope, separators=(",", ":")), text=True, capture_output=True, timeout=45, env=environment, check=False)
    return completed, sandbox, command


def parsed(completed: subprocess.CompletedProcess[str]) -> dict:
    try:
        return json.loads(completed.stdout or "{}")
    except json.JSONDecodeError as exc:
        raise AssertionError(f"sandbox returned invalid JSON: {completed.stdout!r} {completed.stderr!r}") from exc


def write_tls_fixture(hostname: str, directory: Path) -> str:
    now = datetime.now(timezone.utc)
    ca_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    ca_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "OntologyOS rehearsal CA")])
    ca_certificate = (
        x509.CertificateBuilder().subject_name(ca_name).issuer_name(ca_name).public_key(ca_key.public_key())
        .serial_number(x509.random_serial_number()).not_valid_before(now.replace(microsecond=0) - timedelta(minutes=1))
        .not_valid_after(now.replace(microsecond=0) + timedelta(days=1))
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True).sign(ca_key, hashes.SHA256())
    )
    server_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    server_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, hostname)])
    server_certificate = (
        x509.CertificateBuilder().subject_name(server_name).issuer_name(ca_name).public_key(server_key.public_key())
        .serial_number(x509.random_serial_number()).not_valid_before(now.replace(microsecond=0) - timedelta(minutes=1))
        .not_valid_after(now.replace(microsecond=0) + timedelta(days=1))
        .add_extension(x509.SubjectAlternativeName([x509.DNSName(hostname)]), critical=False)
        .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
        .sign(ca_key, hashes.SHA256())
    )
    directory.joinpath("server.pem").write_bytes(server_certificate.public_bytes(serialization.Encoding.PEM))
    directory.joinpath("server.key").write_bytes(server_key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption(),
    ))
    return ca_certificate.public_bytes(serialization.Encoding.PEM).decode("ascii")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sandbox-image", required=True)
    parser.add_argument("--proxy-image", required=True)
    parser.add_argument("--evidence", type=Path)
    args = parser.parse_args()
    assert is_digest_pinned_image(args.sandbox_image)
    assert is_digest_pinned_image(args.proxy_image)

    suffix = secrets.token_hex(5)
    network = f"ontology-plugin-egress-{suffix}"
    uplink = f"ontology-plugin-uplink-{suffix}"
    proxy = f"plugin-egress-proxy-{suffix}"
    mock = f"plugin-egress-mock-{suffix}"
    tls_mock = f"plugin-egress-tls-{suffix}"
    secret = secrets.token_urlsafe(40)
    os.environ.update({
        "PLUGIN_SANDBOX_IMAGE": args.sandbox_image,
        "PLUGIN_SANDBOX_NETWORK": network,
        "PLUGIN_EGRESS_PROXY_URL": f"http://{proxy}:8080",
        "PLUGIN_EGRESS_TOKEN_SECRET": secret,
    })
    tls_directory = tempfile.TemporaryDirectory(prefix="ontologyos-plugin-tls-")
    try:
        docker("network", "create", "--internal", network)
        docker("network", "create", uplink)
        docker("run", "--detach", "--name", mock, "--network", uplink, args.proxy_image, "python", "-m", "http.server", "8088")
        tls_path = Path(tls_directory.name).resolve()
        ca_pem = write_tls_fixture(tls_mock, tls_path)
        tls_server = (
            "import http.server,ssl;"
            "s=http.server.ThreadingHTTPServer(('0.0.0.0',8443),http.server.SimpleHTTPRequestHandler);"
            "c=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER);c.load_cert_chain('/tls/server.pem','/tls/server.key');"
            "s.socket=c.wrap_socket(s.socket,server_side=True);s.serve_forever()"
        )
        docker(
            "run", "--detach", "--name", tls_mock, "--network", uplink,
            "--mount", f"type=bind,source={tls_path.as_posix()},target=/tls,readonly",
            args.proxy_image, "python", "-c", tls_server,
        )
        docker(
            "run", "--detach", "--name", proxy, "--network", network, "--read-only",
            "--cap-drop", "ALL", "--security-opt", "no-new-privileges", "--user", "65534:65534",
            "--env", f"PLUGIN_EGRESS_TOKEN_SECRET={secret}", "--env", "PLUGIN_EGRESS_ALLOW_PRIVATE=true",
            args.proxy_image,
        )
        docker("network", "connect", uplink, proxy)
        time.sleep(1)

        manifest = {
            "limits": {"memory_mb": 128, "timeout_seconds": 15},
            "network_policy": {"allowed_hosts": [mock], "allowed_ports": [8088], "allow_http": True},
        }
        allowed_source = f"""\
def handle(request):
    import urllib.request
    with urllib.request.urlopen('http://{mock}:8088/', timeout=5) as response:
        return {{'status': response.status, 'proxied': True, 'bytes': len(response.read())}}
"""
        allowed, sandbox, command = execute(args.sandbox_image, allowed_source, manifest, ["network"])
        allowed_result = parsed(allowed)
        assert allowed.returncode == 0 and allowed_result.get("ok") is True, (allowed.stdout, allowed.stderr, docker("logs", proxy, check=False).stdout)
        assert allowed_result["output"]["status"] == 200 and allowed_result["output"]["proxied"] is True

        tls_manifest = {
            "limits": {"memory_mb": 128, "timeout_seconds": 15},
            "network_policy": {
                "allowed_hosts": [tls_mock], "allowed_ports": [8443], "allow_http": False,
                "tls_ca_bundle_pem": ca_pem,
            },
        }
        tls_source = f"""\
def handle(request):
    import urllib.request
    with urllib.request.urlopen('https://{tls_mock}:8443/', timeout=5) as response:
        return {{'status': response.status, 'custom_ca': True, 'bytes': len(response.read())}}
"""
        tls_allowed, tls_sandbox, _ = execute(args.sandbox_image, tls_source, tls_manifest, ["network"])
        tls_result = parsed(tls_allowed)
        # The proxy's logs, the way the HTTP assertion above already carries them.
        # Without them a denial arrives as bare "403 Forbidden" and says nothing
        # about which check produced it -- which is exactly how this failed on a
        # GitHub runner while passing on the author's machine, leaving nothing to
        # diagnose from.
        assert tls_allowed.returncode == 0 and tls_result.get("ok") is True, (
            tls_allowed.stdout, tls_allowed.stderr, docker("logs", proxy, check=False).stdout)
        assert tls_result["output"]["status"] == 200 and tls_result["output"]["custom_ca"] is True
        _, tls_metadata = validated_ca_bundle(tls_manifest)
        assert tls_sandbox["tls_trust"] == tls_metadata and ca_pem not in json.dumps(tls_sandbox)

        no_ca_manifest = {
            "limits": {"memory_mb": 128, "timeout_seconds": 15},
            "network_policy": {"allowed_hosts": [tls_mock], "allowed_ports": [8443], "allow_http": False},
        }
        tls_denied, _, _ = execute(args.sandbox_image, tls_source, no_ca_manifest, ["network"])
        tls_denied_result = parsed(tls_denied)
        assert tls_denied.returncode != 0 and tls_denied_result.get("ok") is False
        assert "CERTIFICATE_VERIFY_FAILED" in tls_denied_result.get("error", "")

        denied_source = """\
def handle(request):
    import urllib.request
    urllib.request.urlopen('http://undeclared.invalid:8088/', timeout=5).read()
    return {'unexpected': True}
"""
        denied, _, _ = execute(args.sandbox_image, denied_source, manifest, ["network"])
        denied_result = parsed(denied)
        assert denied.returncode != 0 and denied_result.get("ok") is False
        assert "403" in denied_result.get("error", "")

        bypass_source = f"""\
def handle(request):
    import socket
    socket.create_connection(('{mock}', 8088), timeout=3)
    return {{'unexpected': True}}
"""
        bypass, _, _ = execute(args.sandbox_image, bypass_source, manifest, ["network"])
        bypass_result = parsed(bypass)
        assert bypass.returncode != 0 and bypass_result.get("ok") is False

        proxy_logs = docker("logs", proxy).stdout
        assert secret not in proxy_logs and "plugin:" not in proxy_logs
        evidence = {
            "status": "PASS",
            "executed_at": datetime.now(timezone.utc).isoformat(),
            "sandbox_image": args.sandbox_image,
            "proxy_image": args.proxy_image,
            "network_internal": True,
            "sandbox": sandbox,
            "allowed_destination": {"host": mock, "port": 8088, "status": 200},
            "https_custom_ca": {"host": tls_mock, "port": 8443, "status": 200, **tls_metadata},
            "private_ca_rejected_without_signed_bundle": True,
            "undeclared_destination_denied": True,
            "direct_socket_bypass_denied": True,
            "proxy_credentials_redacted": True,
            "required_command_flags": sorted(set(command) & {"--network", "--read-only", "--cap-drop", "--security-opt", "--user"}),
        }
        if args.evidence:
            args.evidence.parent.mkdir(parents=True, exist_ok=True)
            args.evidence.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(json.dumps(evidence, separators=(",", ":")))
        return 0
    finally:
        for name in (proxy, mock, tls_mock):
            docker("rm", "--force", name, check=False)
        docker("network", "rm", network, check=False)
        docker("network", "rm", uplink, check=False)
        for name in ("PLUGIN_SANDBOX_IMAGE", "PLUGIN_SANDBOX_NETWORK", "PLUGIN_EGRESS_PROXY_URL", "PLUGIN_EGRESS_TOKEN_SECRET"):
            os.environ.pop(name, None)
        tls_directory.cleanup()


if __name__ == "__main__":
    raise SystemExit(main())

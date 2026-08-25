"""Short-lived egress grants and a default-deny HTTP CONNECT proxy."""
from __future__ import annotations

import argparse
import base64
from dataclasses import dataclass
import hashlib
import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import http.client
import ipaddress
import json
import os
import re
import select
import socket
import ssl
import time
from typing import Any, Dict, Iterable, Optional
import urllib.parse


MAX_REQUEST_BYTES = 10_000_000
MAX_RESPONSE_BYTES = 25_000_000
MAX_TLS_CA_BUNDLE_BYTES = 131_072
MAX_TLS_CA_CERTIFICATES = 32
_CERTIFICATE_BLOCK = re.compile(
    r"-----BEGIN CERTIFICATE-----\s+[A-Za-z0-9+/=\r\n]+?-----END CERTIFICATE-----",
    re.MULTILINE,
)
HOP_HEADERS = {
    "connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
    "te", "trailers", "transfer-encoding", "upgrade",
}


def _b64encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _b64decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def normalize_hosts(values: Iterable[Any]) -> list[str]:
    hosts: list[str] = []
    for value in values:
        host = str(value).strip().lower().rstrip(".")
        if not host or len(host) > 253 or "*" in host:
            raise ValueError("network_policy.allowed_hosts must contain exact DNS names")
        labels = host.split(".")
        if any(not label or len(label) > 63 or not all(character.isalnum() or character == "-" for character in label) or label.startswith("-") or label.endswith("-") for label in labels):
            raise ValueError("network_policy.allowed_hosts contains an invalid DNS name")
        if host not in hosts:
            hosts.append(host)
    if not hosts:
        raise ValueError("network capability requires at least one allowed host")
    return sorted(hosts)


def normalize_ports(values: Iterable[Any]) -> list[int]:
    ports = sorted({int(value) for value in values})
    if not ports or any(port < 1 or port > 65535 for port in ports):
        raise ValueError("network_policy.allowed_ports must contain valid TCP ports")
    return ports


def normalized_policy(manifest: Dict[str, Any]) -> Dict[str, Any]:
    policy = manifest.get("network_policy") or {}
    if not isinstance(policy, dict):
        raise ValueError("network_policy must be an object")
    unknown = sorted(set(policy) - {"allowed_hosts", "allowed_ports", "allow_http", "tls_ca_bundle_pem"})
    if unknown:
        raise ValueError(f"network_policy contains unsupported fields: {', '.join(unknown)}")
    hosts = normalize_hosts(policy.get("allowed_hosts") or [])
    ports = normalize_ports(policy.get("allowed_ports") or [443])
    allow_http = bool(policy.get("allow_http", False))
    if not allow_http and any(port not in {443, 8443} for port in ports):
        raise ValueError("non-TLS ports require network_policy.allow_http")
    return {"allowed_hosts": hosts, "allowed_ports": ports, "allow_http": allow_http}


def validated_ca_bundle(manifest: Dict[str, Any]) -> tuple[Optional[str], Optional[Dict[str, Any]]]:
    """Validate an optional signed public CA bundle without exposing it in evidence."""
    policy = manifest.get("network_policy") or {}
    value = policy.get("tls_ca_bundle_pem") if isinstance(policy, dict) else None
    if value is None:
        return None, None
    if not isinstance(value, str) or not value.strip():
        raise ValueError("network_policy.tls_ca_bundle_pem must be a non-empty PEM string")
    try:
        raw = value.replace("\r\n", "\n").encode("ascii")
    except UnicodeEncodeError as exc:
        raise ValueError("network_policy.tls_ca_bundle_pem must be ASCII PEM") from exc
    if len(raw) > MAX_TLS_CA_BUNDLE_BYTES:
        raise ValueError(f"network_policy.tls_ca_bundle_pem exceeds {MAX_TLS_CA_BUNDLE_BYTES} bytes")
    normalized = raw.decode("ascii").strip() + "\n"
    blocks = _CERTIFICATE_BLOCK.findall(normalized)
    residue = _CERTIFICATE_BLOCK.sub("", normalized).strip()
    if not blocks or residue or len(blocks) > MAX_TLS_CA_CERTIFICATES or "PRIVATE KEY" in normalized:
        raise ValueError("network_policy.tls_ca_bundle_pem must contain only bounded CA certificates")
    try:
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        context.load_verify_locations(cadata=normalized)
    except ssl.SSLError as exc:
        raise ValueError("network_policy.tls_ca_bundle_pem contains an invalid certificate") from exc
    return normalized, {
        "mode": "custom_ca",
        "ca_bundle_sha256": hashlib.sha256(normalized.encode("ascii")).hexdigest(),
        "certificate_count": len(blocks),
    }


def issue_egress_token(secret: str, policy: Dict[str, Any], *, ttl_seconds: int = 120, now: Optional[int] = None) -> str:
    if len(secret) < 32:
        raise ValueError("PLUGIN_EGRESS_TOKEN_SECRET must contain at least 32 characters")
    issued = int(time.time()) if now is None else int(now)
    payload = {
        "v": 1,
        "exp": issued + max(10, min(900, int(ttl_seconds))),
        "hosts": normalize_hosts(policy.get("allowed_hosts") or []),
        "ports": normalize_ports(policy.get("allowed_ports") or []),
        "allow_http": bool(policy.get("allow_http", False)),
        "nonce": _b64encode(os.urandom(12)),
    }
    body = _b64encode(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8"))
    signature = _b64encode(hmac.new(secret.encode("utf-8"), body.encode("ascii"), hashlib.sha256).digest())
    return f"{body}.{signature}"


def verify_egress_token(secret: str, token: str, host: str, port: int, *, scheme: str, now: Optional[int] = None) -> Dict[str, Any]:
    try:
        body, supplied = token.split(".", 1)
        expected = _b64encode(hmac.new(secret.encode("utf-8"), body.encode("ascii"), hashlib.sha256).digest())
        if not hmac.compare_digest(expected, supplied):
            raise ValueError("invalid signature")
        payload = json.loads(_b64decode(body))
    except (ValueError, TypeError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise PermissionError("Invalid egress credential") from exc
    current = int(time.time()) if now is None else int(now)
    if payload.get("v") != 1 or int(payload.get("exp", 0)) < current:
        raise PermissionError("Expired egress credential")
    normalized_host = host.strip().lower().rstrip(".")
    if normalized_host not in payload.get("hosts", []):
        raise PermissionError("Destination host is not allowed")
    if int(port) not in payload.get("ports", []):
        raise PermissionError("Destination port is not allowed")
    if scheme == "http" and not payload.get("allow_http", False):
        raise PermissionError("Plain HTTP is not allowed")
    return payload


def _resolved_ip(host: str, port: int, *, allow_private: bool) -> str:
    try:
        addresses = {item[4][0] for item in socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)}
    except socket.gaierror as exc:
        raise PermissionError("Destination DNS resolution failed") from exc
    if not addresses:
        raise PermissionError("Destination DNS resolution returned no addresses")
    safe: list[str] = []
    for value in addresses:
        address = ipaddress.ip_address(value)
        blocked = address.is_private or address.is_loopback or address.is_link_local or address.is_multicast or address.is_unspecified or address.is_reserved
        if not blocked or allow_private:
            safe.append(value)
    if not safe:
        raise PermissionError("Private or non-routable destinations are denied")
    return sorted(safe)[0]


def _credential(header: Optional[str]) -> str:
    if not header or not header.lower().startswith("basic "):
        raise PermissionError("Proxy authentication is required")
    try:
        raw = base64.b64decode(header.split(" ", 1)[1], validate=True).decode("utf-8")
        username, token = raw.split(":", 1)
    except (ValueError, UnicodeDecodeError) as exc:
        raise PermissionError("Invalid proxy authentication") from exc
    if username != "plugin" or not token:
        raise PermissionError("Invalid proxy authentication")
    return token


@dataclass(frozen=True)
class ProxyConfig:
    secret: str
    allow_private: bool = False
    connect_timeout: float = 10.0
    tunnel_idle_seconds: float = 60.0

    @classmethod
    def from_env(cls) -> "ProxyConfig":
        secret = os.getenv("PLUGIN_EGRESS_TOKEN_SECRET", "")
        if len(secret) < 32:
            raise ValueError("PLUGIN_EGRESS_TOKEN_SECRET must contain at least 32 characters")
        return cls(
            secret=secret,
            allow_private=os.getenv("PLUGIN_EGRESS_ALLOW_PRIVATE", "false").strip().lower() == "true",
            connect_timeout=max(1.0, float(os.getenv("PLUGIN_EGRESS_CONNECT_TIMEOUT_SECONDS", "10"))),
            tunnel_idle_seconds=max(5.0, float(os.getenv("PLUGIN_EGRESS_TUNNEL_IDLE_SECONDS", "60"))),
        )


class EgressProxyHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    config: ProxyConfig

    def _deny(self, status: int, message: str) -> None:
        # Logged as well as returned. On a CONNECT the client sees only the status
        # line -- urllib reports "Tunnel connection failed: 403 Forbidden" and
        # discards the body -- so writing the reason into the response alone puts
        # it exactly where nobody can read it, on the one path where a denial is
        # hardest to diagnose. An egress proxy that refuses without saying why is
        # difficult to operate anywhere, and it cost a CI failure that carried no
        # diagnosis at all.
        print(json.dumps({"event": "plugin.egress.denied", "client": self.client_address[0],
                          "target": self.path, "status": status, "reason": message},
                         separators=(",", ":")), flush=True)
        raw = json.dumps({"error": message}, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(raw)
        self.close_connection = True

    def _authorized_target(self, host: str, port: int, scheme: str) -> str:
        token = _credential(self.headers.get("Proxy-Authorization"))
        verify_egress_token(self.config.secret, token, host, port, scheme=scheme)
        return _resolved_ip(host, port, allow_private=self.config.allow_private)

    def do_CONNECT(self) -> None:
        try:
            host, raw_port = self.path.rsplit(":", 1)
            port = int(raw_port)
            address = self._authorized_target(host, port, "https")
            upstream = socket.create_connection((address, port), timeout=self.config.connect_timeout)
        except (ValueError, OSError, PermissionError) as exc:
            self._deny(403, str(exc))
            return
        self.send_response(200, "Connection Established")
        self.end_headers()
        sockets = [self.connection, upstream]
        try:
            while True:
                readable, _, _ = select.select(sockets, [], [], self.config.tunnel_idle_seconds)
                if not readable:
                    break
                for source in readable:
                    data = source.recv(65536)
                    if not data:
                        return
                    (upstream if source is self.connection else self.connection).sendall(data)
        finally:
            upstream.close()

    def _forward_http(self) -> None:
        try:
            target = urllib.parse.urlsplit(self.path)
            if target.scheme != "http" or not target.hostname:
                raise PermissionError("Only absolute HTTP proxy requests are accepted")
            port = target.port or 80
            address = self._authorized_target(target.hostname, port, "http")
            length = int(self.headers.get("Content-Length", "0"))
            if length < 0 or length > MAX_REQUEST_BYTES:
                raise PermissionError("Request body exceeds proxy limit")
            body = self.rfile.read(length) if length else None
            headers = {name: value for name, value in self.headers.items() if name.lower() not in HOP_HEADERS and name.lower() != "host"}
            headers["Host"] = target.netloc
            path = urllib.parse.urlunsplit(("", "", target.path or "/", target.query, ""))
            connection = http.client.HTTPConnection(address, port, timeout=self.config.connect_timeout)
            connection.request(self.command, path, body=body, headers=headers)
            response = connection.getresponse()
            raw = response.read(MAX_RESPONSE_BYTES + 1)
            if len(raw) > MAX_RESPONSE_BYTES:
                raise PermissionError("Response body exceeds proxy limit")
        except (ValueError, OSError, PermissionError, http.client.HTTPException) as exc:
            self._deny(403, str(exc))
            return
        try:
            self.send_response(response.status, response.reason)
            for name, value in response.getheaders():
                if name.lower() not in HOP_HEADERS and name.lower() != "content-length":
                    self.send_header(name, value)
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)
        finally:
            connection.close()

    do_GET = _forward_http
    do_POST = _forward_http
    do_PUT = _forward_http
    do_PATCH = _forward_http
    do_DELETE = _forward_http
    do_HEAD = _forward_http

    def log_message(self, format: str, *args: Any) -> None:
        print(json.dumps({"event": "plugin.egress.request", "client": self.client_address[0], "message": format % args}, separators=(",", ":")), flush=True)


def serve(config: ProxyConfig, host: str = "0.0.0.0", port: int = 8080) -> None:
    handler = type("ConfiguredEgressProxyHandler", (EgressProxyHandler,), {"config": config})
    server = ThreadingHTTPServer((host, port), handler)
    server.serve_forever()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default=os.getenv("PLUGIN_EGRESS_HOST", "0.0.0.0"))
    parser.add_argument("--port", type=int, default=int(os.getenv("PLUGIN_EGRESS_PORT", "8080")))
    args = parser.parse_args()
    serve(ProxyConfig.from_env(), args.host, args.port)


if __name__ == "__main__":
    main()

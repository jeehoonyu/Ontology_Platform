"""Dependency-free construction of the production plugin OCI boundary."""
from __future__ import annotations

import os
import re
from typing import Any, Dict, Iterable
import urllib.parse

from .plugin_egress import issue_egress_token, normalized_policy, validated_ca_bundle


PLUGIN_SDK_API_VERSION = 1
_IMAGE_ID = re.compile(r"^sha256:[0-9a-f]{64}$")
_REPOSITORY_DIGEST = re.compile(r"^.+@sha256:[0-9a-f]{64}$")


def is_digest_pinned_image(image: str) -> bool:
    """Return whether an image is immutable by repository digest or local image ID."""
    normalized = image.strip().lower()
    return bool(_IMAGE_ID.fullmatch(normalized) or _REPOSITORY_DIGEST.fullmatch(normalized))


def build_oci_command(
    *,
    manifest: Dict[str, Any],
    capabilities: Iterable[str],
    production: bool,
) -> tuple[list[str], Dict[str, str], Dict[str, Any]]:
    executable = os.getenv("PLUGIN_OCI_EXECUTABLE", "docker")
    image = os.getenv("PLUGIN_SANDBOX_IMAGE", "").strip()
    if not image or (production and not is_digest_pinned_image(image)):
        raise RuntimeError("PLUGIN_SANDBOX_IMAGE must be configured and digest-pinned in production")
    runner = os.getenv("PLUGIN_SANDBOX_RUNNER_PATH", "/app/app/plugin_sandbox_runner.py")
    if not runner.startswith("/"):
        raise RuntimeError("PLUGIN_SANDBOX_RUNNER_PATH must be an absolute path in the sandbox image")

    limits = manifest.get("limits") or {}
    memory = int(limits.get("memory_mb", 256))
    declared_capabilities = {str(value) for value in capabilities}
    network = "none"
    egress_policy = None
    tls_trust = None
    proxy_environment: list[str] = []
    if "network" in declared_capabilities:
        network = os.getenv("PLUGIN_SANDBOX_NETWORK", "").strip()
        if not network or network.lower() in {"bridge", "host", "default", "none"}:
            raise RuntimeError("Network-capable plugins require a dedicated restricted PLUGIN_SANDBOX_NETWORK")
        egress_policy = normalized_policy(manifest)
        _, tls_trust = validated_ca_bundle(manifest)
        secret = os.getenv("PLUGIN_EGRESS_TOKEN_SECRET", "")
        proxy_url = os.getenv("PLUGIN_EGRESS_PROXY_URL", "http://plugin-egress-proxy:8080").strip()
        parsed_proxy = urllib.parse.urlsplit(proxy_url)
        if parsed_proxy.scheme != "http" or not parsed_proxy.hostname or parsed_proxy.username or parsed_proxy.password or parsed_proxy.path not in {"", "/"} or parsed_proxy.query or parsed_proxy.fragment:
            raise RuntimeError("PLUGIN_EGRESS_PROXY_URL must be an unauthenticated internal HTTP origin")
        timeout = int((manifest.get("limits") or {}).get("timeout_seconds", 30))
        token = issue_egress_token(secret, egress_policy, ttl_seconds=timeout + 60)
        proxy_host = parsed_proxy.hostname
        if ":" in proxy_host:
            proxy_host = f"[{proxy_host}]"
        authority = f"plugin:{token}@{proxy_host}"
        if parsed_proxy.port:
            authority += f":{parsed_proxy.port}"
        credentialed_proxy = urllib.parse.urlunsplit(("http", authority, "", "", ""))
        proxy_environment = [
            "--env", f"HTTP_PROXY={credentialed_proxy}",
            "--env", f"HTTPS_PROXY={credentialed_proxy}",
            "--env", "NO_PROXY=",
            "--env", "ALL_PROXY=",
        ]

    command = [
        executable,
        "run",
        "--rm",
        "--interactive",
        "--network",
        network,
        "--read-only",
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges",
        "--pids-limit",
        "64",
        "--memory",
        f"{memory}m",
        "--cpus",
        "1",
        "--user",
        "65534:65534",
        "--tmpfs",
        "/scratch:rw,noexec,nosuid,nodev,size=64m,mode=1777",
        *proxy_environment,
        image,
        "python",
        "-I",
        runner,
    ]
    environment = {
        key: value
        for key, value in os.environ.items()
        if key.upper() in {"PATH", "SYSTEMROOT", "WINDIR", "COMSPEC", "DOCKER_HOST", "DOCKER_CONTEXT"}
    }
    sandbox = {
        "mode": "oci",
        "image": image,
        "runner": runner,
        "network": network,
        "read_only": True,
        "capabilities_dropped": True,
        "no_new_privileges": True,
        "non_root": True,
        "memory_mb": memory,
        "cpus": 1,
        "pids": 64,
        "sdk_api_version": PLUGIN_SDK_API_VERSION,
        "egress_policy": egress_policy,
        "egress_proxy": bool(egress_policy),
        "tls_trust": tls_trust or ({"mode": "system"} if egress_policy else None),
    }
    return command, environment, sandbox

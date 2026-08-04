"""Child-process protocol for deterministic development plugin execution.

This runner is deliberately not a production security boundary. Production uses
the OCI runner enforced by plugin_runtime. The audit hook narrows accidental
access during local development and gives tests a deterministic isolation model.
"""
from __future__ import annotations

import importlib.util
import base64
import hashlib
import io
import json
import os
from pathlib import Path
import ssl
import sys
from typing import Any
import zipfile


PLUGIN_SDK_API_VERSION = 1
MAX_TLS_CA_BUNDLE_BYTES = 131_072


def _inside(path: str, roots: list[Path]) -> bool:
    try:
        resolved = Path(path).resolve()
    except (OSError, ValueError):
        return False
    return any(resolved == root or root in resolved.parents for root in roots)


def _install_policy(bundle_root: Path, scratch_root: Path, capabilities: set[str]) -> None:
    read_roots = [bundle_root, scratch_root, Path(sys.base_prefix).resolve()]
    write_roots = [scratch_root]

    def audit(event: str, args: tuple[Any, ...]) -> None:
        if event.startswith("socket.") and "network" not in capabilities:
            raise PermissionError("Plugin network access is not permitted")
        if event in {"subprocess.Popen", "os.system", "os.posix_spawn", "os.spawn"}:
            raise PermissionError("Plugin child processes are not permitted")
        if event == "open" and args:
            path = args[0]
            if not isinstance(path, (str, bytes, os.PathLike)):
                return
            mode = str(args[1] if len(args) > 1 else "r")
            flags = int(args[2]) if len(args) > 2 and isinstance(args[2], int) else 0
            writes = any(marker in mode for marker in ("w", "a", "+", "x")) or bool(
                flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND)
            )
            roots = write_roots if writes else read_roots
            if not _inside(os.fsdecode(path), roots):
                raise PermissionError("Plugin filesystem access is outside the sandbox")

    sys.addaudithook(audit)


def _install_custom_ca(envelope: dict[str, Any], scratch_root: Path, capabilities: set[str]) -> None:
    value = envelope.get("tls_ca_bundle_pem")
    if value is None:
        return
    if "network" not in capabilities or not isinstance(value, str):
        raise RuntimeError("Custom TLS trust requires the network capability")
    raw = value.encode("ascii")
    if not raw or len(raw) > MAX_TLS_CA_BUNDLE_BYTES or b"PRIVATE KEY" in raw:
        raise RuntimeError("Custom TLS CA bundle is invalid or exceeds its limit")
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.load_verify_locations(cadata=value)
    target = scratch_root / "ontologyos-plugin-ca.pem"
    target.write_bytes(raw)
    os.chmod(target, 0o400)
    os.environ["SSL_CERT_FILE"] = str(target)
    os.environ["REQUESTS_CA_BUNDLE"] = str(target)


def main() -> int:
    envelope = json.loads(sys.stdin.read())
    if envelope.get("sdk_api_version") != PLUGIN_SDK_API_VERSION:
        raise RuntimeError(f"Unsupported plugin SDK API version: {envelope.get('sdk_api_version')}")
    scratch_root = Path(envelope["scratch_root"]).resolve()
    bundle_root = Path(envelope["bundle_root"]).resolve()
    if envelope.get("bundle_base64"):
        raw = base64.b64decode(envelope["bundle_base64"], validate=True)
        if hashlib.sha256(raw).hexdigest() != envelope.get("bundle_sha256"):
            raise RuntimeError("Streamed plugin bundle failed integrity verification")
        bundle_root.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            for member in archive.infolist():
                path = Path(member.filename)
                if path.is_absolute() or ".." in path.parts or any(":" in part for part in path.parts):
                    raise RuntimeError("Streamed plugin bundle contains an unsafe path")
                if (member.external_attr >> 16) & 0o170000 == 0o120000:
                    raise RuntimeError("Streamed plugin bundle contains a symbolic link")
            archive.extractall(bundle_root)
    entrypoint = (bundle_root / envelope["entrypoint"]).resolve()
    if not _inside(str(entrypoint), [bundle_root]) or not entrypoint.is_file():
        raise RuntimeError("Plugin entrypoint is missing or outside the bundle")
    capabilities = {str(value) for value in envelope.get("capabilities") or []}
    _install_custom_ca(envelope, scratch_root, capabilities)
    _install_policy(bundle_root, scratch_root, capabilities)
    spec = importlib.util.spec_from_file_location("ontologyos_plugin", entrypoint)
    if spec is None or spec.loader is None:
        raise RuntimeError("Plugin entrypoint cannot be loaded")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    handler = getattr(module, "handle", None)
    if not callable(handler):
        raise RuntimeError("Plugin entrypoint must export handle(request)")
    result = handler({"operation": envelope["operation"], "input": envelope.get("input") or {}})
    if not isinstance(result, dict):
        raise RuntimeError("Plugin handle(request) must return an object")
    sys.stdout.write(json.dumps({"ok": True, "output": result}, separators=(",", ":"), default=str))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        sys.stdout.write(json.dumps({"ok": False, "error": f"{type(exc).__name__}: {exc}"}, separators=(",", ":")))
        raise SystemExit(1)

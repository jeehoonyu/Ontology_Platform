"""Client-side safety and authentication for pilot recovery rehearsals."""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, Optional, Tuple


def recovery_token(env_name: str = "PILOT_RECOVERY_TOKEN") -> str:
    token = os.getenv(env_name, "").strip()
    if not token:
        raise RuntimeError(f"{env_name} must contain the recovery probe bearer token")
    return token


def canonical_target(value: str) -> Tuple[str, str, int, str]:
    parsed = urllib.parse.urlsplit(value.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("Recovery targets must be absolute HTTP(S) URLs")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("Recovery target URLs cannot contain credentials, query, or fragment")
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    path = parsed.path.rstrip("/") or "/"
    return parsed.scheme.lower(), parsed.hostname.lower(), port, path


def require_isolated_target(source_target: str, recovery_target: str) -> None:
    if canonical_target(source_target) == canonical_target(recovery_target):
        raise ValueError(
            "Recovery target resolves to the live source target. Use a separately "
            "restored API/database and a distinct URL."
        )


def json_request(
    target: str,
    path: str,
    *,
    token: str,
    method: str = "GET",
    body: Optional[Dict[str, Any]] = None,
    timeout: float = 15.0,
) -> Tuple[int, Dict[str, Any]]:
    data = None if body is None else json.dumps(body).encode("utf-8")
    request = urllib.request.Request(
        f"{target.rstrip('/')}{path}", data=data, method=method,
        headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
    )
    if data is not None:
        request.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = response.read()
            decoded = json.loads(payload) if payload else {}
            return response.status, decoded if isinstance(decoded, dict) else {}
    except urllib.error.HTTPError as error:
        try:
            payload = json.loads(error.read())
        except Exception:
            payload = {}
        return error.code, payload if isinstance(payload, dict) else {}
    except Exception as error:
        return 0, {"detail": type(error).__name__}


def assert_current_heads(payload: Dict[str, Any], expected_head: str) -> None:
    database_head = payload.get("database_migration_head")
    runtime_head = payload.get("runtime_migration_head")
    if database_head != expected_head or runtime_head != expected_head:
        raise RuntimeError(
            "Recovery target migration mismatch: "
            f"database={database_head!r}, runtime={runtime_head!r}, expected={expected_head!r}"
        )

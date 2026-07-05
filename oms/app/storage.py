"""
Object storage abstraction (local filesystem) for real file uploads.

A tiny, dependency-free store so datasets and media can hold real files instead of
only inline JSON. The root is configurable via the STORAGE_DIR env var (default
./storage). The put/open/delete surface is deliberately backend-agnostic so an
S3/GCS backend can drop in later without touching call sites.
"""
import os
from pathlib import Path
from typing import Optional

_URI_PREFIX = "file://"


def _root() -> Path:
    root = Path(os.getenv("STORAGE_DIR", "./storage"))
    root.mkdir(parents=True, exist_ok=True)
    return root


def _safe_relpath(key: str) -> str:
    # Prevent traversal; normalize separators to a relative POSIX-ish key.
    return key.replace("\\", "/").replace("..", "_").lstrip("/")


def put(key: str, data: bytes) -> str:
    """Store bytes under ``key``; returns a storage URI (``file://<relpath>``)."""
    rel = _safe_relpath(key)
    path = _root() / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return f"{_URI_PREFIX}{rel}"


def open_bytes(uri: Optional[str]) -> Optional[bytes]:
    """Return the stored bytes for a URI produced by :func:`put`, or None."""
    if not uri or not uri.startswith(_URI_PREFIX):
        return None
    path = _root() / _safe_relpath(uri[len(_URI_PREFIX):])
    if not path.exists() or not path.is_file():
        return None
    return path.read_bytes()


def delete(uri: Optional[str]) -> bool:
    if not uri or not uri.startswith(_URI_PREFIX):
        return False
    path = _root() / _safe_relpath(uri[len(_URI_PREFIX):])
    if path.exists() and path.is_file():
        path.unlink()
        return True
    return False

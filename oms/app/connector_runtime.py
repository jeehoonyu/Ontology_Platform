"""Pluggable live connector adapters with encrypted credentials and fetch evidence."""
from __future__ import annotations

import base64
import csv
import datetime
import fnmatch
import hashlib
import hmac
import importlib
import io
import ipaddress
import json
import os
import re
import socket
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Protocol

from cryptography.fernet import Fernet, InvalidToken
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import Integer, JSON, String, Text, create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Mapped, Session, mapped_column

from . import connectivity, models_action, ops_control, tenancy
from .database import Base, SessionLocal, get_db
from .production_auth import Principal, require_permission

router = APIRouter(tags=["connector_runtime"])


def _now() -> int:
    return int(time.time())


class ConnectorCredential(Base):
    __tablename__ = "connector_credentials"

    id: Mapped[str] = mapped_column(String, primary_key=True, index=True)
    project_id: Mapped[str] = mapped_column(String, index=True)
    source_id: Mapped[str] = mapped_column(String, index=True)
    credential_type: Mapped[str] = mapped_column(String, index=True)
    encrypted_secret: Mapped[str] = mapped_column(Text)
    metadata_: Mapped[dict] = mapped_column("metadata", JSON, default=dict)
    key_id: Mapped[str] = mapped_column(String, default="default")
    status: Mapped[str] = mapped_column(String, default="ACTIVE", index=True)
    expires_at: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    created_by: Mapped[str] = mapped_column(String)
    created_at: Mapped[int] = mapped_column(Integer)
    rotated_at: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)


class ConnectorFetchAttempt(Base):
    __tablename__ = "connector_fetch_attempts"

    id: Mapped[str] = mapped_column(String, primary_key=True, index=True)
    project_id: Mapped[str] = mapped_column(String, index=True)
    source_id: Mapped[str] = mapped_column(String, index=True)
    sync_id: Mapped[Optional[str]] = mapped_column(String, nullable=True, index=True)
    ingestion_run_id: Mapped[Optional[str]] = mapped_column(String, nullable=True, index=True)
    adapter_id: Mapped[str] = mapped_column(String, index=True)
    operation: Mapped[str] = mapped_column(String)
    status: Mapped[str] = mapped_column(String, index=True)
    records_read: Mapped[int] = mapped_column(Integer, default=0)
    bytes_read: Mapped[int] = mapped_column(Integer, default=0)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    cursor_in: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    cursor_out: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    metadata_: Mapped[dict] = mapped_column("metadata", JSON, default=dict)
    error: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    created_at: Mapped[int] = mapped_column(Integer)


class CredentialCreate(BaseModel):
    credential_type: str = Field(pattern="^(bearer|api_key|basic|aws)$")
    secret: str = Field(min_length=1, max_length=16000)
    metadata: Dict[str, str] = Field(default_factory=dict)
    expires_at: Optional[int] = None


class LivePreviewRequest(BaseModel):
    limit: int = Field(default=25, ge=1, le=1000)
    cursor: Optional[Any] = None


@dataclass
class AdapterContext:
    source: connectivity.ConnectionSource
    config: Dict[str, Any]
    credential_type: Optional[str] = None
    credential_secret: Optional[str] = None
    credential_metadata: Dict[str, Any] = field(default_factory=dict)
    cursor: Optional[Any] = None
    cursor_field: Optional[str] = None
    limit: int = 500


@dataclass
class AdapterResult:
    records: List[Dict[str, Any]]
    next_cursor: Optional[Any] = None
    bytes_read: int = 0
    metadata: Dict[str, Any] = field(default_factory=dict)


class ConnectorAdapter(Protocol):
    id: str
    source_types: List[str]
    modes: List[str]

    def config_schema(self) -> Dict[str, Any]: ...
    def fetch(self, context: AdapterContext) -> AdapterResult: ...


class ConnectorAdapterRegistry:
    def __init__(self) -> None:
        self._adapters: Dict[str, ConnectorAdapter] = {}

    def register(self, adapter: ConnectorAdapter) -> None:
        if not getattr(adapter, "id", None):
            raise ValueError("Connector adapter must have an id")
        self._adapters[adapter.id] = adapter

    def get(self, adapter_id: str) -> Optional[ConnectorAdapter]:
        return self._adapters.get(adapter_id)

    def catalog(self) -> List[Dict[str, Any]]:
        return [
            {
                "id": adapter.id,
                "source_types": adapter.source_types,
                "modes": adapter.modes,
                "available": True,
                "config_schema": adapter.config_schema(),
            }
            for adapter in sorted(self._adapters.values(), key=lambda row: row.id)
        ]


registry = ConnectorAdapterRegistry()


def register_adapter(adapter: ConnectorAdapter) -> None:
    """Public extension hook for deployment-specific connector packages."""
    registry.register(adapter)


def _load_plugins() -> List[str]:
    loaded: List[str] = []
    for module_name in [value.strip() for value in os.getenv("CONNECTOR_PLUGIN_MODULES", "").split(",") if value.strip()]:
        module = importlib.import_module(module_name)
        register = getattr(module, "register_connectors", None)
        if not callable(register):
            raise RuntimeError(f"Connector plugin '{module_name}' has no register_connectors(registry) function")
        register(registry)
        loaded.append(module_name)
    return loaded


def _secret_key() -> Fernet:
    configured = os.getenv("CONNECTOR_SECRET_KEY", "").strip()
    if not configured:
        if os.getenv("APP_ENV", "development").lower() == "production":
            raise HTTPException(status_code=503, detail="CONNECTOR_SECRET_KEY is required in production")
        configured = os.getenv("CONNECTOR_LOCAL_SECRET_SEED", "ontology-platform-local-connector-seed")
    try:
        raw = configured.encode("ascii")
        if len(raw) == 44:
            return Fernet(raw)
    except UnicodeEncodeError:
        pass
    derived = base64.urlsafe_b64encode(hashlib.sha256(configured.encode("utf-8")).digest())
    return Fernet(derived)


def _encrypt_secret(value: str) -> str:
    return _secret_key().encrypt(value.encode("utf-8")).decode("ascii")


def _decrypt_secret(value: str) -> str:
    try:
        return _secret_key().decrypt(value.encode("ascii")).decode("utf-8")
    except InvalidToken as exc:
        raise HTTPException(status_code=503, detail="Connector credential cannot be decrypted with the configured key") from exc


def _credential_dict(row: ConnectorCredential) -> Dict[str, Any]:
    return {
        "id": row.id,
        "project_id": row.project_id,
        "source_id": row.source_id,
        "credential_type": row.credential_type,
        "metadata": row.metadata_ or {},
        "key_id": row.key_id,
        "status": row.status,
        "expires_at": row.expires_at,
        "expired": bool(row.expires_at and row.expires_at <= _now()),
        "created_by": row.created_by,
        "created_at": row.created_at,
        "rotated_at": row.rotated_at,
    }


def _fetch_attempt_dict(row: ConnectorFetchAttempt) -> Dict[str, Any]:
    return {
        "id": row.id, "project_id": row.project_id, "source_id": row.source_id,
        "sync_id": row.sync_id, "ingestion_run_id": row.ingestion_run_id,
        "adapter_id": row.adapter_id, "operation": row.operation, "status": row.status,
        "records_read": row.records_read, "bytes_read": row.bytes_read,
        "duration_ms": row.duration_ms, "cursor_in": row.cursor_in, "cursor_out": row.cursor_out,
        "metadata": row.metadata_ or {}, "error": row.error, "created_at": row.created_at,
    }


def _active_credential(db: Session, source: connectivity.ConnectionSource) -> Optional[ConnectorCredential]:
    now = _now()
    rows = db.query(ConnectorCredential).filter(
        ConnectorCredential.project_id == source.project_id,
        ConnectorCredential.source_id == source.id,
        ConnectorCredential.status == "ACTIVE",
    ).order_by(ConnectorCredential.created_at.desc()).all()
    return next((row for row in rows if row.expires_at is None or row.expires_at > now), None)


def adapter_id_for_source(source: connectivity.ConnectionSource) -> str:
    return str((source.config or {}).get("adapter_id") or source.source_type)


def _context(db: Session, source: connectivity.ConnectionSource, cursor: Any, cursor_field: Optional[str], limit: int) -> AdapterContext:
    credential = _active_credential(db, source)
    credential_secret = _decrypt_secret(credential.encrypted_secret) if credential else None
    credential_metadata = dict(credential.metadata_ or {}) if credential else {}
    if credential and credential.credential_type == "aws" and credential_secret:
        try:
            envelope = json.loads(credential_secret)
        except json.JSONDecodeError as exc:
            raise HTTPException(status_code=503, detail="AWS connector credential envelope is invalid") from exc
        credential_secret = str(envelope.get("secret_access_key") or "")
        if envelope.get("session_token"):
            credential_metadata["session_token"] = str(envelope["session_token"])
    return AdapterContext(
        source=source,
        config=dict(source.config or {}),
        credential_type=credential.credential_type if credential else None,
        credential_secret=credential_secret,
        credential_metadata=credential_metadata,
        cursor=cursor,
        cursor_field=cursor_field,
        limit=limit,
    )


def _string_cursor(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, (dict, list)):
        return json.dumps(value, sort_keys=True, separators=(",", ":"))
    return str(value)


def fetch_records(
    db: Session,
    source: connectivity.ConnectionSource,
    *,
    cursor: Any = None,
    cursor_field: Optional[str] = None,
    limit: int = 500,
    sync_id: Optional[str] = None,
    ingestion_run_id: Optional[str] = None,
    operation: str = "sync",
) -> AdapterResult:
    adapter_id = adapter_id_for_source(source)
    adapter = registry.get(adapter_id)
    if not adapter:
        raise HTTPException(status_code=422, detail={"message": "Connector adapter is not installed", "adapter_id": adapter_id})
    started = time.perf_counter()
    attempt = ConnectorFetchAttempt(
        id=f"fetch_{uuid.uuid4().hex}", project_id=source.project_id, source_id=source.id,
        sync_id=sync_id, ingestion_run_id=ingestion_run_id, adapter_id=adapter_id, operation=operation,
        status="RUNNING", records_read=0, bytes_read=0, duration_ms=0,
        cursor_in=_string_cursor(cursor), cursor_out=None, metadata_={}, error=None, created_at=_now(),
    )
    try:
        result = adapter.fetch(_context(db, source, cursor, cursor_field, limit))
        attempt.status = "SUCCEEDED"
        attempt.records_read = len(result.records)
        attempt.bytes_read = result.bytes_read
        attempt.cursor_out = _string_cursor(result.next_cursor)
        attempt.metadata_ = {key: value for key, value in result.metadata.items() if "secret" not in key.lower() and "token" not in key.lower()}
    except HTTPException as exc:
        attempt.status = "FAILED"
        upstream = re.search(r"\bHTTP\s+(\d{3})\b", str(exc.detail))
        upstream_status = f", upstream HTTP {upstream.group(1)}" if upstream else ""
        attempt.error = f"Connector adapter rejected request (HTTP {exc.status_code}{upstream_status})"
        attempt.duration_ms = int((time.perf_counter() - started) * 1000)
        with SessionLocal() as evidence_db:
            evidence_db.add(attempt)
            evidence_db.commit()
        raise
    except Exception as exc:
        attempt.status = "FAILED"
        attempt.error = f"Connector adapter failed ({type(exc).__name__})"
        attempt.duration_ms = int((time.perf_counter() - started) * 1000)
        with SessionLocal() as evidence_db:
            evidence_db.add(attempt)
            evidence_db.commit()
        raise HTTPException(status_code=502, detail=f"Connector fetch failed: {type(exc).__name__}") from exc
    attempt.duration_ms = int((time.perf_counter() - started) * 1000)
    with SessionLocal() as evidence_db:
        evidence_db.add(attempt)
        evidence_db.commit()
    return result


def _allowed_host(hostname: str) -> bool:
    allowlist = [value.strip().lower() for value in os.getenv("CONNECTOR_ALLOWED_HOSTS", "").split(",") if value.strip()]
    if allowlist and not any(fnmatch.fnmatch(hostname.lower(), pattern) for pattern in allowlist):
        return False
    return True


def _validate_remote_url(url: str) -> None:
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise HTTPException(status_code=422, detail="REST connector URL must use http or https")
    if parsed.username or parsed.password:
        raise HTTPException(status_code=422, detail="Credentials must not be embedded in connector URLs")
    if not _allowed_host(parsed.hostname):
        raise HTTPException(status_code=403, detail="Connector host is not in CONNECTOR_ALLOWED_HOSTS")
    allow_private = os.getenv("CONNECTOR_ALLOW_PRIVATE_NETWORKS", "false").lower() in {"1", "true", "yes"}
    try:
        addresses = {item[4][0] for item in socket.getaddrinfo(parsed.hostname, parsed.port or (443 if parsed.scheme == "https" else 80), type=socket.SOCK_STREAM)}
    except socket.gaierror as exc:
        raise HTTPException(status_code=502, detail="Connector host could not be resolved") from exc
    for address in addresses:
        ip = ipaddress.ip_address(address)
        unsafe = ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_reserved or ip.is_unspecified
        if unsafe and not allow_private:
            raise HTTPException(status_code=403, detail="Private or local connector addresses are disabled")


class _SafeRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        _validate_remote_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _extract_path(value: Any, path: Optional[str]) -> Any:
    current = value
    if not path:
        return current
    for segment in path.split("."):
        if isinstance(current, dict):
            current = current.get(segment)
        else:
            return None
    return current


class RestPullAdapter:
    id = "rest"
    source_types = ["rest"]
    modes = ["snapshot", "incremental"]

    def config_schema(self) -> Dict[str, Any]:
        return {
            "required": ["base_url"],
            "properties": {
                "base_url": {"type": "string"}, "endpoint": {"type": "string"},
                "records_path": {"type": "string", "default": "records"},
                "next_cursor_path": {"type": "string"}, "cursor_param": {"type": "string"},
                "page_size_param": {"type": "string"}, "timeout_seconds": {"type": "integer"},
            },
        }

    def fetch(self, context: AdapterContext) -> AdapterResult:
        config = context.config
        base = str(config.get("base_url") or "").rstrip("/")
        endpoint = str(config.get("endpoint") or "")
        url = f"{base}/{endpoint.lstrip('/')}" if endpoint else base
        query = {str(key): str(value) for key, value in dict(config.get("query_params") or {}).items()}
        if context.cursor is not None and config.get("cursor_param"):
            query[str(config["cursor_param"])] = str(context.cursor)
        if config.get("page_size_param"):
            query[str(config["page_size_param"])] = str(context.limit)
        if query:
            url = f"{url}{'&' if '?' in url else '?'}{urllib.parse.urlencode(query)}"
        _validate_remote_url(url)
        headers = {str(key): str(value) for key, value in dict(config.get("headers") or {}).items() if key.lower() not in {"host", "content-length", "authorization"}}
        if context.credential_type == "bearer" and context.credential_secret:
            headers["Authorization"] = f"Bearer {context.credential_secret}"
        elif context.credential_type == "api_key" and context.credential_secret:
            headers[str(context.credential_metadata.get("header_name") or "X-API-Key")] = context.credential_secret
        elif context.credential_type == "basic" and context.credential_secret:
            username = str(context.credential_metadata.get("username") or "")
            headers["Authorization"] = "Basic " + base64.b64encode(f"{username}:{context.credential_secret}".encode()).decode()
        request = urllib.request.Request(url, headers=headers, method="GET")
        timeout = max(1, min(60, int(config.get("timeout_seconds", 15))))
        max_bytes = max(1024, min(50_000_000, int(config.get("max_response_bytes", 10_000_000))))
        try:
            with urllib.request.build_opener(_SafeRedirectHandler()).open(request, timeout=timeout) as response:
                final_url = response.geturl()
                _validate_remote_url(final_url)
                raw = response.read(max_bytes + 1)
                if len(raw) > max_bytes:
                    raise HTTPException(status_code=413, detail="Connector response exceeded max_response_bytes")
                content_type = str(response.headers.get("content-type") or "")
        except urllib.error.HTTPError as exc:
            raise HTTPException(status_code=502, detail=f"REST connector returned HTTP {exc.code}") from exc
        except urllib.error.URLError as exc:
            raise HTTPException(status_code=502, detail="REST connector request failed") from exc
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise HTTPException(status_code=502, detail="REST connector response is not valid UTF-8 JSON") from exc
        extracted = _extract_path(payload, str(config.get("records_path") or "records"))
        if extracted is None and isinstance(payload, list):
            extracted = payload
        if not isinstance(extracted, list):
            raise HTTPException(status_code=422, detail="Configured records_path did not resolve to a list")
        records = [dict(row) for row in extracted[:context.limit] if isinstance(row, dict)]
        next_cursor = _extract_path(payload, config.get("next_cursor_path"))
        if next_cursor is None and context.cursor_field:
            values = [row.get(context.cursor_field) for row in records if row.get(context.cursor_field) is not None]
            next_cursor = max(values) if values else context.cursor
        return AdapterResult(records=records, next_cursor=next_cursor, bytes_read=len(raw), metadata={"content_type": content_type, "host": urllib.parse.urlsplit(url).hostname})


_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_.]*$")
_FORBIDDEN_SQL = re.compile(r"\b(insert|update|delete|drop|alter|create|grant|revoke|truncate|copy|attach|detach|pragma)\b", re.IGNORECASE)


def _read_only_query(query: str) -> str:
    stripped = query.strip()
    if not re.match(r"^select\b", stripped, re.IGNORECASE) or ";" in stripped or "--" in stripped or "/*" in stripped or _FORBIDDEN_SQL.search(stripped):
        raise HTTPException(status_code=422, detail="SQL connector query must be one read-only SELECT statement")
    return stripped


class SqlPullAdapter:
    id = "jdbc"
    source_types = ["jdbc"]
    modes = ["snapshot", "incremental"]

    def config_schema(self) -> Dict[str, Any]:
        return {
            "required": ["sqlalchemy_url", "table or query"],
            "properties": {
                "sqlalchemy_url": {"type": "string"}, "table": {"type": "string"},
                "query": {"type": "string"}, "cursor_field": {"type": "string"},
            },
        }

    def fetch(self, context: AdapterContext) -> AdapterResult:
        config = context.config
        raw_url = str(config.get("sqlalchemy_url") or "")
        if not raw_url:
            raise HTTPException(status_code=422, detail="Live JDBC adapter requires sqlalchemy_url")
        try:
            url = make_url(raw_url)
        except Exception as exc:
            raise HTTPException(status_code=422, detail="Invalid sqlalchemy_url") from exc
        if url.get_backend_name() not in {"postgresql", "sqlite"}:
            raise HTTPException(status_code=422, detail="SQL adapter supports PostgreSQL and SQLite")
        if url.get_backend_name() == "sqlite" and os.getenv("APP_ENV", "development").lower() == "production" and os.getenv("CONNECTOR_ALLOW_SQLITE_SOURCE", "false").lower() != "true":
            raise HTTPException(status_code=422, detail="SQLite connector sources are disabled in production")
        if url.password:
            raise HTTPException(status_code=422, detail="Database passwords must use a runtime credential")
        if context.credential_secret:
            url = url.set(username=str(context.credential_metadata.get("username") or url.username or ""), password=context.credential_secret)
        table = str(config.get("table") or "")
        configured_query = str(config.get("query") or "")
        cursor_field = context.cursor_field or config.get("cursor_field")
        params: Dict[str, Any] = {"limit": context.limit}
        if configured_query:
            query = _read_only_query(configured_query)
            if ":limit" not in query:
                raise HTTPException(status_code=422, detail="Custom SQL query must include :limit")
            if context.cursor is not None:
                if ":cursor" not in query:
                    raise HTTPException(status_code=422, detail="Incremental SQL query must include :cursor")
                params["cursor"] = context.cursor
        else:
            if not _IDENTIFIER.fullmatch(table):
                raise HTTPException(status_code=422, detail="SQL connector table is invalid")
            quoted_table = ".".join(f'"{part}"' for part in table.split("."))
            query = f"SELECT * FROM {quoted_table}"
            if context.cursor is not None:
                if not cursor_field or not _IDENTIFIER.fullmatch(str(cursor_field)):
                    raise HTTPException(status_code=422, detail="Incremental SQL connector requires a valid cursor field")
                query += f' WHERE "{cursor_field}" > :cursor'
                params["cursor"] = context.cursor
            if cursor_field:
                if not _IDENTIFIER.fullmatch(str(cursor_field)):
                    raise HTTPException(status_code=422, detail="SQL cursor field is invalid")
                query += f' ORDER BY "{cursor_field}"'
            query += " LIMIT :limit"
        engine = create_engine(url, pool_pre_ping=True)
        started = time.perf_counter()
        try:
            with engine.connect() as connection:
                rows = [dict(row) for row in connection.execute(text(query), params).mappings().all()]
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"SQL connector query failed: {type(exc).__name__}") from exc
        finally:
            engine.dispose()
        next_cursor = context.cursor
        if cursor_field:
            values = [row.get(str(cursor_field)) for row in rows if row.get(str(cursor_field)) is not None]
            next_cursor = max(values) if values else context.cursor
        encoded = json.dumps(rows, default=str, sort_keys=True, separators=(",", ":")).encode()
        return AdapterResult(records=rows, next_cursor=next_cursor, bytes_read=len(encoded), metadata={"backend": url.get_backend_name(), "query_ms": int((time.perf_counter() - started) * 1000)})


def _aws_signing_key(secret: str, date_stamp: str, region: str, service: str = "s3") -> bytes:
    key_date = hmac.new(("AWS4" + secret).encode(), date_stamp.encode(), hashlib.sha256).digest()
    key_region = hmac.new(key_date, region.encode(), hashlib.sha256).digest()
    key_service = hmac.new(key_region, service.encode(), hashlib.sha256).digest()
    return hmac.new(key_service, b"aws4_request", hashlib.sha256).digest()


def _aws_query(params: Dict[str, Any]) -> str:
    pairs = []
    for key, value in params.items():
        if value is None:
            continue
        pairs.append((urllib.parse.quote(str(key), safe="-_.~"), urllib.parse.quote(str(value), safe="-_.~")))
    return "&".join(f"{key}={value}" for key, value in sorted(pairs))


def _s3_records(raw: bytes, object_key: str, configured_format: str) -> List[Dict[str, Any]]:
    data_format = configured_format.lower().strip() if configured_format else "auto"
    if data_format == "auto":
        suffix = object_key.rsplit(".", 1)[-1].lower() if "." in object_key else "json"
        data_format = "jsonl" if suffix in {"jsonl", "ndjson"} else suffix
    try:
        text_value = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise HTTPException(status_code=422, detail=f"S3 object '{object_key}' is not UTF-8") from exc
    try:
        if data_format == "csv":
            return [dict(row) for row in csv.DictReader(io.StringIO(text_value))]
        if data_format == "jsonl":
            rows = [json.loads(line) for line in text_value.splitlines() if line.strip()]
        elif data_format == "json":
            payload = json.loads(text_value)
            rows = payload if isinstance(payload, list) else [payload]
        else:
            raise HTTPException(status_code=422, detail=f"Unsupported S3 object format '{data_format}'")
    except (csv.Error, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=422, detail=f"S3 object '{object_key}' is not valid {data_format}") from exc
    if not all(isinstance(row, dict) for row in rows):
        raise HTTPException(status_code=422, detail=f"S3 object '{object_key}' must contain object records")
    return [dict(row) for row in rows]


class S3PullAdapter:
    """Dependency-light S3-compatible snapshot and object-key incremental reader."""

    id = "s3"
    source_types = ["s3"]
    modes = ["snapshot", "incremental"]

    def config_schema(self) -> Dict[str, Any]:
        return {
            "required": ["bucket", "region"],
            "properties": {
                "bucket": {"type": "string"}, "region": {"type": "string"},
                "endpoint_url": {"type": "string"}, "prefix": {"type": "string"},
                "format": {"type": "string", "enum": ["auto", "csv", "json", "jsonl"]},
                "max_objects": {"type": "integer", "default": 100},
                "max_object_bytes": {"type": "integer", "default": 10000000},
                "max_records": {"type": "integer", "default": 100000},
            },
            "credential": {"type": "aws", "metadata": ["access_key_id", "session_token"]},
            "incremental_cursor_field": "_source_object_key",
        }

    def _request(self, context: AdapterContext, method: str, url: str, query: Dict[str, Any], max_bytes: int) -> tuple[bytes, Dict[str, str]]:
        if context.credential_type != "aws" or not context.credential_secret:
            raise HTTPException(status_code=422, detail="S3 connector requires an active AWS runtime credential")
        access_key = str(context.credential_metadata.get("access_key_id") or "").strip()
        if not access_key:
            raise HTTPException(status_code=422, detail="S3 credential metadata requires access_key_id")
        _validate_remote_url(url)
        parsed = urllib.parse.urlsplit(url)
        canonical_query = _aws_query(query)
        request_url = urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, parsed.path, canonical_query, ""))
        now = datetime.datetime.now(datetime.timezone.utc)
        amz_date = now.strftime("%Y%m%dT%H%M%SZ")
        date_stamp = now.strftime("%Y%m%d")
        payload_hash = hashlib.sha256(b"").hexdigest()
        headers = {
            "host": parsed.netloc,
            "x-amz-content-sha256": payload_hash,
            "x-amz-date": amz_date,
        }
        session_token = str(context.credential_metadata.get("session_token") or "").strip()
        if session_token:
            headers["x-amz-security-token"] = session_token
        signed_headers = ";".join(sorted(headers))
        canonical_headers = "".join(f"{key}:{headers[key].strip()}\n" for key in sorted(headers))
        canonical_request = "\n".join([method, parsed.path or "/", canonical_query, canonical_headers, signed_headers, payload_hash])
        region = str(context.config.get("region") or "us-east-1")
        scope = f"{date_stamp}/{region}/s3/aws4_request"
        string_to_sign = "\n".join(["AWS4-HMAC-SHA256", amz_date, scope, hashlib.sha256(canonical_request.encode()).hexdigest()])
        signature = hmac.new(_aws_signing_key(context.credential_secret, date_stamp, region), string_to_sign.encode(), hashlib.sha256).hexdigest()
        headers["authorization"] = f"AWS4-HMAC-SHA256 Credential={access_key}/{scope}, SignedHeaders={signed_headers}, Signature={signature}"
        request = urllib.request.Request(request_url, headers=headers, method=method)
        timeout = max(1, min(120, int(context.config.get("timeout_seconds", 30))))
        try:
            with urllib.request.build_opener(_SafeRedirectHandler()).open(request, timeout=timeout) as response:
                _validate_remote_url(response.geturl())
                raw = response.read(max_bytes + 1)
                if len(raw) > max_bytes:
                    raise HTTPException(status_code=413, detail="S3 response exceeded configured byte limit")
                return raw, {str(key).lower(): str(value) for key, value in response.headers.items()}
        except urllib.error.HTTPError as exc:
            raise HTTPException(status_code=502, detail=f"S3 endpoint returned HTTP {exc.code}") from exc
        except urllib.error.URLError as exc:
            raise HTTPException(status_code=502, detail="S3 endpoint request failed") from exc

    def fetch(self, context: AdapterContext) -> AdapterResult:
        config = context.config
        bucket = str(config.get("bucket") or "").strip()
        region = str(config.get("region") or "").strip()
        if not bucket or not region or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9.-]{1,62}", bucket):
            raise HTTPException(status_code=422, detail="S3 connector requires a valid bucket and region")
        endpoint = str(config.get("endpoint_url") or f"https://s3.{region}.amazonaws.com").rstrip("/")
        bucket_url = f"{endpoint}/{urllib.parse.quote(bucket, safe='-_.~')}"
        max_objects = max(1, min(1000, int(config.get("max_objects", 100)), context.limit))
        max_object_bytes = max(1024, min(100_000_000, int(config.get("max_object_bytes", 10_000_000))))
        max_records = max(1, min(1_000_000, int(config.get("max_records", 100_000))))
        query = {"list-type": "2", "max-keys": max_objects, "prefix": str(config.get("prefix") or "")}
        if context.cursor is not None:
            query["start-after"] = str(context.cursor)
        listing, _ = self._request(context, "GET", bucket_url, query, min(5_000_000, max_object_bytes))
        try:
            root = ET.fromstring(listing)
        except ET.ParseError as exc:
            raise HTTPException(status_code=502, detail="S3 list response is not valid XML") from exc
        objects = []
        for item in root.findall(".//{*}Contents"):
            key = item.findtext("{*}Key") or ""
            if key:
                objects.append({"key": key, "etag": (item.findtext("{*}ETag") or "").strip('"')})
        records: List[Dict[str, Any]] = []
        bytes_read = len(listing)
        last_key = context.cursor
        for item in objects:
            key = item["key"]
            object_url = f"{bucket_url}/{urllib.parse.quote(key, safe='/-_.~')}"
            raw, _ = self._request(context, "GET", object_url, {}, max_object_bytes)
            object_records = _s3_records(raw, key, str(config.get("format") or "auto"))
            if len(records) + len(object_records) > max_records:
                raise HTTPException(status_code=413, detail="S3 batch exceeded max_records; reduce max_objects or split source objects")
            for row in object_records:
                row.setdefault("_source_object_key", key)
                row.setdefault("_source_object_etag", item["etag"])
            records.extend(object_records)
            bytes_read += len(raw)
            last_key = key
        return AdapterResult(
            records=records,
            next_cursor=last_key,
            bytes_read=bytes_read,
            metadata={"bucket": bucket, "prefix": query["prefix"], "objects_read": len(objects), "endpoint_host": urllib.parse.urlsplit(endpoint).hostname},
        )


register_adapter(RestPullAdapter())
register_adapter(SqlPullAdapter())
register_adapter(S3PullAdapter())
_loaded_plugins = _load_plugins()


@router.get("/connectors/adapters")
def adapter_catalog(principal: Principal = Depends(require_permission("view"))):
    available = registry.catalog()
    installed = {item["id"] for item in available}
    unavailable = [
        {"id": adapter_id, "available": False, "reason": "Install and configure a connector plugin"}
        for adapter_id in ("s3", "sftp", "kafka") if adapter_id not in installed
    ]
    return {"adapters": available + unavailable, "plugin_modules": _loaded_plugins, "runtime": "durable_live_adapter_v1"}


@router.post("/connections/sources/{source_id}/runtime-credentials", status_code=201)
def create_runtime_credential(source_id: str, body: CredentialCreate, principal: Principal = Depends(require_permission("administer")), db: Session = Depends(get_db)):
    source = connectivity._source_or_404(db, source_id, principal, "administer")
    if body.expires_at is not None and body.expires_at <= _now():
        raise HTTPException(status_code=422, detail="Credential expiry must be in the future")
    now = _now()
    for existing in db.query(ConnectorCredential).filter(
        ConnectorCredential.project_id == source.project_id,
        ConnectorCredential.source_id == source.id,
        ConnectorCredential.status == "ACTIVE",
    ).all():
        existing.status = "ROTATED"
        existing.rotated_at = now
    credential_metadata = dict(body.metadata)
    secret_value = body.secret
    if body.credential_type == "aws":
        if not str(credential_metadata.get("access_key_id") or "").strip():
            raise HTTPException(status_code=422, detail="AWS credential metadata requires access_key_id")
        session_token = credential_metadata.pop("session_token", None)
        secret_value = json.dumps({"secret_access_key": body.secret, "session_token": session_token}, separators=(",", ":"))
    row = ConnectorCredential(
        id=f"credential_{uuid.uuid4().hex}", project_id=source.project_id, source_id=source.id,
        credential_type=body.credential_type, encrypted_secret=_encrypt_secret(secret_value),
        metadata_=credential_metadata, key_id=os.getenv("CONNECTOR_SECRET_KEY_ID", "default"), status="ACTIVE",
        expires_at=body.expires_at, created_by=principal.id, created_at=now, rotated_at=None,
    )
    db.add(row)
    db.add(models_action.AuditLog(id=uuid.uuid4().hex, actor=principal.id, event_type="connector.credential.rotated", subject_type="connection_source", subject_id=source.id, payload={"credential_id": row.id, "project_id": source.project_id, "credential_type": row.credential_type}))
    db.commit()
    return _credential_dict(row)


@router.get("/connections/sources/{source_id}/runtime-credentials")
def list_runtime_credentials(source_id: str, principal: Principal = Depends(require_permission("administer")), db: Session = Depends(get_db)):
    source = connectivity._source_or_404(db, source_id, principal, "administer")
    return [_credential_dict(row) for row in db.query(ConnectorCredential).filter(ConnectorCredential.project_id == source.project_id, ConnectorCredential.source_id == source.id).order_by(ConnectorCredential.created_at.desc()).all()]


@router.delete("/connections/sources/{source_id}/runtime-credentials/{credential_id}")
def revoke_runtime_credential(source_id: str, credential_id: str, principal: Principal = Depends(require_permission("administer")), db: Session = Depends(get_db)):
    source = connectivity._source_or_404(db, source_id, principal, "administer")
    row = db.get(ConnectorCredential, credential_id)
    if not row or row.source_id != source.id or row.project_id != source.project_id:
        raise HTTPException(status_code=404, detail="Connector credential not found")
    row.status = "REVOKED"
    row.rotated_at = _now()
    db.add(models_action.AuditLog(id=uuid.uuid4().hex, actor=principal.id, event_type="connector.credential.revoked", subject_type="connection_source", subject_id=source.id, payload={"credential_id": row.id, "project_id": source.project_id}))
    db.commit()
    return _credential_dict(row)


@router.post("/connections/sources/{source_id}/live-preview")
def live_preview(source_id: str, body: LivePreviewRequest = LivePreviewRequest(), principal: Principal = Depends(require_permission("execute")), db: Session = Depends(get_db)):
    source = connectivity._source_or_404(db, source_id, principal, "execute")
    try:
        result = fetch_records(db, source, cursor=body.cursor, cursor_field=(source.config or {}).get("cursor_field"), limit=body.limit, operation="preview")
        db.add(models_action.AuditLog(id=uuid.uuid4().hex, actor=principal.id, event_type="connector.live_preview.completed", subject_type="connection_source", subject_id=source.id, payload={"project_id": source.project_id, "records": len(result.records), "adapter_id": adapter_id_for_source(source)}))
        db.commit()
        return {"source_id": source.id, "adapter_id": adapter_id_for_source(source), "status": "READY", "record_count": len(result.records), "preview_rows": result.records, "next_cursor": result.next_cursor, "bytes_read": result.bytes_read, "metadata": result.metadata}
    except Exception:
        db.commit()
        raise


@router.get("/connections/sources/{source_id}/fetch-attempts")
def list_fetch_attempts(source_id: str, limit: int = Query(50, ge=1, le=500), principal: Principal = Depends(require_permission("view")), db: Session = Depends(get_db)):
    source = connectivity._source_or_404(db, source_id, principal, "view")
    rows = db.query(ConnectorFetchAttempt).filter(ConnectorFetchAttempt.project_id == source.project_id, ConnectorFetchAttempt.source_id == source.id).order_by(ConnectorFetchAttempt.created_at.desc(), ConnectorFetchAttempt.id.desc()).limit(limit).all()
    return [_fetch_attempt_dict(row) for row in rows]

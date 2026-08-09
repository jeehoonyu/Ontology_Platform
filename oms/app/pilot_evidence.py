"""Tamper-evident journals for long-running production-pilot evidence."""
from __future__ import annotations

import hashlib
import json
import os
import re
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional

JOURNAL_SCHEMA_VERSION = 1
GENESIS_HASH = "0" * 64
LOCK_WAIT_SECONDS = 10.0
LOCK_STALE_SECONDS = 120.0


class JournalIntegrityError(ValueError):
    """Raised when persisted pilot evidence is missing, reordered, or altered."""


def current_migration_head() -> str:
    versions = Path(__file__).resolve().parents[1] / "alembic" / "versions"
    revisions, parents = set(), set()
    for path in versions.glob("*.py"):
        source = path.read_text(encoding="utf-8")
        revision = re.search(r'^revision(?::\s*[^=]+)?\s*=\s*"([^"]+)"', source, re.MULTILINE)
        parent = re.search(r'^down_revision(?::\s*[^=]+)?\s*=\s*"([^"]+)"', source, re.MULTILINE)
        if revision:
            revisions.add(revision.group(1))
        if parent:
            parents.add(parent.group(1))
    heads = revisions - parents
    if len(heads) != 1:
        raise RuntimeError(f"expected exactly one migration head, found {sorted(heads)}")
    return heads.pop()


def _canonical(record: Dict[str, Any]) -> bytes:
    payload = {key: value for key, value in record.items() if key != "record_hash"}
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")


def record_hash(record: Dict[str, Any]) -> str:
    return hashlib.sha256(_canonical(record)).hexdigest()


def _read_lines(path: Path) -> List[str]:
    if not path.exists():
        return []
    raw = path.read_bytes()
    if not raw:
        return []
    if not raw.endswith(b"\n"):
        raise JournalIntegrityError(f"torn final journal record in {path}")
    return raw.decode("utf-8").splitlines()


def load_journal(path: Path) -> List[Dict[str, Any]]:
    records: List[Dict[str, Any]] = []
    previous = GENESIS_HASH
    seen_slots = set()
    for line_number, line in enumerate(_read_lines(path), start=1):
        try:
            record = json.loads(line)
        except json.JSONDecodeError as exc:
            raise JournalIntegrityError(f"invalid JSON at {path}:{line_number}") from exc
        if not isinstance(record, dict):
            raise JournalIntegrityError(f"non-object record at {path}:{line_number}")
        if record.get("schema_version") != JOURNAL_SCHEMA_VERSION:
            raise JournalIntegrityError(f"unsupported schema at {path}:{line_number}")
        if record.get("previous_hash") != previous:
            raise JournalIntegrityError(f"hash-chain break at {path}:{line_number}")
        expected = record_hash(record)
        if record.get("record_hash") != expected:
            raise JournalIntegrityError(f"record hash mismatch at {path}:{line_number}")
        slot = (record.get("run_id"), record.get("kind"), record.get("scheduled_at"))
        if slot in seen_slots:
            raise JournalIntegrityError(f"duplicate scheduled observation at {path}:{line_number}")
        seen_slots.add(slot)
        previous = expected
        records.append(record)
    return records


@contextmanager
def _journal_lock(path: Path) -> Iterator[None]:
    lock_path = path.with_suffix(path.suffix + ".lock")
    deadline = time.monotonic() + LOCK_WAIT_SECONDS
    descriptor: Optional[int] = None
    while descriptor is None:
        try:
            descriptor = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            os.write(descriptor, f"{os.getpid()} {int(time.time())}\n".encode("ascii"))
            os.fsync(descriptor)
        except FileExistsError:
            try:
                age = time.time() - lock_path.stat().st_mtime
                if age > LOCK_STALE_SECONDS:
                    lock_path.unlink(missing_ok=True)
                    continue
            except FileNotFoundError:
                continue
            if time.monotonic() >= deadline:
                raise TimeoutError(f"pilot evidence journal is locked: {path}")
            time.sleep(0.05)
    try:
        yield
    finally:
        if descriptor is not None:
            os.close(descriptor)
        lock_path.unlink(missing_ok=True)


def append_observation(
    path: Path,
    *,
    run_id: str,
    kind: str,
    target: str,
    migration_head: str,
    scheduled_at: int,
    observed_at: int,
    payload: Dict[str, Any],
) -> Dict[str, Any]:
    path.parent.mkdir(parents=True, exist_ok=True)
    with _journal_lock(path):
        records = load_journal(path)
        if records and int(scheduled_at) <= int(records[-1]["scheduled_at"]):
            raise JournalIntegrityError("scheduled observations must be globally increasing")
        record: Dict[str, Any] = {
            "schema_version": JOURNAL_SCHEMA_VERSION,
            "run_id": run_id,
            "kind": kind,
            "target": target,
            "migration_head": migration_head,
            "scheduled_at": int(scheduled_at),
            "observed_at": int(observed_at),
            "payload": payload,
            "previous_hash": records[-1]["record_hash"] if records else GENESIS_HASH,
        }
        record["record_hash"] = record_hash(record)
        with path.open("ab") as handle:
            handle.write(json.dumps(record, sort_keys=True, separators=(",", ":")).encode("utf-8") + b"\n")
            handle.flush()
            os.fsync(handle.fileno())
        return record


def load_or_create_run_state(path: Path, *, target: str, migration_head: str, now: int,
                             interval_seconds: int) -> Dict[str, Any]:
    state: Dict[str, Any] = {}
    if path.exists():
        try:
            candidate = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(candidate, dict):
                state = candidate
        except (json.JSONDecodeError, OSError):
            state = {}
    if state.get("target") != target or state.get("migration_head") != migration_head:
        scheduled = int(now) - (int(now) % interval_seconds)
        state = {
            "schema_version": JOURNAL_SCHEMA_VERSION,
            "run_id": f"pilot_{uuid.uuid4().hex}",
            "target": target,
            "migration_head": migration_head,
            "started_at": scheduled,
            "next_scheduled_at": scheduled,
        }
        save_run_state(path, state)
    return state


def save_run_state(path: Path, state: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(state, handle, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def latest_run(records: List[Dict[str, Any]], *, migration_head: Optional[str] = None) -> List[Dict[str, Any]]:
    eligible = [record for record in records if not migration_head or record.get("migration_head") == migration_head]
    if not eligible:
        return []
    run_id = eligible[-1]["run_id"]
    return [record for record in eligible if record.get("run_id") == run_id]


def validate_tail_anchor(records: List[Dict[str, Any]], state_path: Path) -> Dict[str, Any]:
    """Prove the journal has not moved behind the observer's durable lower bound."""
    if not state_path.exists():
        raise JournalIntegrityError(f"pilot evidence state is missing: {state_path}")
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        raise JournalIntegrityError(f"pilot evidence state is invalid: {state_path}") from exc
    if not isinstance(state, dict):
        raise JournalIntegrityError(f"pilot evidence state is not an object: {state_path}")
    anchor = state.get("last_record_hash")
    if not isinstance(anchor, str) or len(anchor) != 64:
        raise JournalIntegrityError(f"pilot evidence tail anchor is missing: {state_path}")
    anchored = next((record for record in records if record.get("record_hash") == anchor), None)
    if not anchored:
        raise JournalIntegrityError("pilot evidence journal was truncated behind its durable tail anchor")
    for field in ("run_id", "target", "migration_head"):
        if state.get(field) != anchored.get(field):
            raise JournalIntegrityError(f"pilot evidence state {field} does not match the anchored record")
    return state

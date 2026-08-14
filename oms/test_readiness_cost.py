"""`/health/ready` must stay cheap, because the availability gate is defined on it.

The contract calls the system available when `/health/live` and `/health/ready`
both answer 200 within 2,000 ms, probed every 30 seconds for seven days. That
makes the cost of answering part of the measurement rather than an
implementation detail: a readiness check slow enough to time out fails the gate
by being slow, with the product perfectly healthy behind it.

It did. Reflecting the whole schema on every call issued one
`information_schema` round-trip per mapped table -- 279 against the pilot
database -- for 220 ms at rest, and crossed 2,000 ms twice in the first two
hours of a real window whenever the disk was busy. Each crossing charges 30
seconds against a 604.8-second budget for the week.

This is the ratchet for the fix. A comment saying the reflection is cached is an
intention; counting the statements is the thing that stays true.
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

root = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
database_path = Path(root.name) / "readiness-cost.db"
os.environ["DATABASE_URL"] = f"sqlite:///{database_path.as_posix()}"
os.environ["APP_ENV"] = "test"
os.environ["AUTH_MODE"] = "local"
sys.path.insert(0, str(Path(__file__).resolve().parent))

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import event, text  # noqa: E402

from app import system_hardening  # noqa: E402
from app.database import SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402

# A reflection touches one catalog per mapped table; a cached answer must not
# come anywhere near that. The bound is deliberately loose -- the claim is a
# change of order, not a specific number.
CACHED_STATEMENT_CEILING = 8

passed = 0
statements: list[str] = []


def check(condition, label, payload=None):
    global passed
    assert condition, f"{label}: {payload}"
    passed += 1


@event.listens_for(engine, "before_cursor_execute")
def _record(conn, cursor, statement, parameters, context, executemany):
    statements.append(statement)


def count_of(call) -> tuple[int, object]:
    """Statements issued while `call` runs, and whatever it returned."""
    statements.clear()
    result = call()
    return len(statements), result


def set_head(value: str) -> None:
    with SessionLocal() as db:
        db.execute(text("DELETE FROM alembic_version"))
        db.execute(text("INSERT INTO alembic_version (version_num) VALUES (:v)"), {"v": value})
        db.commit()


def health() -> tuple[int, object]:
    with SessionLocal() as db:
        return count_of(lambda: system_hardening.schema_health(db))


client = TestClient(app)

# Warm-up: the first call also creates the runtime tables, so it is not a clean
# measurement of anything. What it must do is answer.
response = client.get("/health/ready")
check(response.status_code == 200, "readiness answers 200", response.status_code)
check(response.json()["status"] == "READY", "readiness reports READY", response.json())

with SessionLocal() as db:
    db.execute(text("CREATE TABLE IF NOT EXISTS alembic_version (version_num VARCHAR(32) NOT NULL)"))
    db.commit()
set_head("head_one")

fresh_count, fresh = health()
cached_count, cached = health()

check(fresh_count > CACHED_STATEMENT_CEILING,
      "a cold reflection is expensive, or this test measures nothing", fresh_count)
check(cached_count <= CACHED_STATEMENT_CEILING,
      "a repeat call at the same head must not re-reflect the schema", cached_count)
check(cached_count * 10 < fresh_count,
      "the saving must be a change of order, not a trim", (fresh_count, cached_count))

# Caching is only legitimate if it cannot change the answer.
check(fresh == cached, "the cached answer is the reflected answer", (fresh, cached))

# The head is the cache key, so moving it must force a fresh reflection. If this
# regresses, a migration would land and readiness would keep reporting the
# schema it saw before it.
set_head("head_two")
moved_count, moved = health()
check(moved_count > CACHED_STATEMENT_CEILING,
      "a head change must invalidate the reflection", moved_count)
check(moved == fresh, "same schema at a new head reflects the same result", (moved, fresh))

# Callers mutate what they are given -- `/system/migrations` does. A shared dict
# would let one caller corrupt every later answer.
first = health()[1]
first["missing_tables"].append("poisoned")
first["status"] = "WARN"
second = health()[1]
check(second["missing_tables"] == [], "mutating a result must not poison the cache", second)
check(second["status"] == "PASS", "mutating a result must not poison the status", second)

# The endpoint itself still works after all of that, and reports a head.
response = client.get("/health/ready")
check(response.status_code == 200, "readiness still answers 200", response.status_code)
body = response.json()
check(body["migration"]["database_head"] == "head_two",
      "readiness reports the database's own head", body["migration"])

print(f"Readiness cost verified: {passed} assertions passed "
      f"(cold {fresh_count} statements, cached {cached_count}).")

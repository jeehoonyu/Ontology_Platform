"""Approval consumption and project-scoped, expiring idempotency keys: migration 0047.

From the prior head, with the old shape rebuilt: approvals without consumption columns, and
keys keyed by `key` alone with no expiry. The upgrade must consume every approval an outbox
row names -- by its earliest run -- and no other; date every key a day after it was written,
and a key with no written time at the migration; and key the table by (project_id, key),
keeping its project index. The downgrade refuses while one key is used by two projects.
"""

import os
import subprocess
import sys
import tempfile
import time

from sqlalchemy import create_engine, inspect, text
from tier_b_evidence import current_head

PRIOR = "0046_dataset_txn_seq_unique"
DAY = 24 * 60 * 60

with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temporary:
    database_url = f"sqlite:///{os.path.join(temporary, 'approval-consumption-migration.db')}"
    env = {**os.environ, "DATABASE_URL": database_url, "APP_ENV": "test", "AUTH_MODE": "local"}

    def alembic(*args, expect_ok=True):
        completed = subprocess.run(
            [sys.executable, "-m", "alembic", "-c", "alembic.ini", *args],
            cwd=os.path.dirname(__file__), env=env, capture_output=True, text=True,
        )
        if expect_ok:
            assert completed.returncode == 0, f"{completed.stdout}\n{completed.stderr}"
        return completed

    def columns(connection, table):
        return {row["name"] for row in inspect(connection).get_columns(table)}

    alembic("upgrade", PRIOR)
    engine = create_engine(database_url)
    now = int(time.time())
    with engine.begin() as connection:
        # 0001 builds today's models, so a fresh chain already has the new shape. Rebuild the old one.
        for column in ("consumed_by_outbox_event_id", "consumed_at"):
            if column in columns(connection, "approval_requests"):
                connection.execute(text(f"ALTER TABLE approval_requests DROP COLUMN {column}"))
        connection.execute(text("DROP TABLE idempotency_keys"))
        connection.execute(text(
            "CREATE TABLE idempotency_keys (key VARCHAR NOT NULL PRIMARY KEY, project_id VARCHAR NOT NULL, "
            "action_type_id VARCHAR NOT NULL, response_payload JSON, created_at INTEGER)"))
        connection.execute(text("CREATE INDEX ix_idempotency_keys_project_id ON idempotency_keys (project_id)"))
        assert inspect(connection).get_pk_constraint("idempotency_keys")["constrained_columns"] == ["key"]

        for approval_id, status in (("ran-twice", "APPROVED"), ("never-ran", "APPROVED"), ("pending", "PENDING")):
            connection.execute(text(
                "INSERT INTO approval_requests (id, project_id, action_type_id, requester, parameters, status, created_at) "
                "VALUES (:id, 'default', 'act', 'someone', '{}', :status, 1)"), {"id": approval_id, "status": status})
        # The finding itself: one approval run twice, under two keys. The earlier run consumed it.
        for outbox_id, created, approval in (("out-late", 200, "ran-twice"), ("out-early", 100, "ran-twice"),
                                             ("out-plain", 150, None)):
            payload = '{"approval_request_id": "%s"}' % approval if approval else '{"parameters": {}}'
            connection.execute(text(
                "INSERT INTO action_outbox (id, project_id, action_type_id, payload, status, created_at) "
                "VALUES (:id, 'default', 'act', :payload, 'PENDING', :created)"),
                {"id": outbox_id, "payload": payload, "created": created})
        for key, created in (("old-key", 100), ("recent-key", now - 60), ("undated-key", None)):
            connection.execute(text(
                "INSERT INTO idempotency_keys (key, project_id, action_type_id, response_payload, created_at) "
                "VALUES (:key, 'default', 'act', '{}', :created)"), {"key": key, "created": created})

    alembic("upgrade", "head")
    with engine.begin() as connection:
        consumed = {row.id: (row.consumed_at, row.consumed_by_outbox_event_id) for row in connection.execute(text(
            "SELECT id, consumed_at, consumed_by_outbox_event_id FROM approval_requests"))}
        assert consumed["ran-twice"] == (100, "out-early"), f"not consumed by its earliest run: {consumed['ran-twice']}"
        assert consumed["never-ran"] == (None, None), f"an approval that never ran was consumed: {consumed['never-ran']}"
        assert consumed["pending"] == (None, None), consumed["pending"]

        expires = {row.key: row.expires_at for row in connection.execute(text("SELECT key, expires_at FROM idempotency_keys"))}
        assert expires["old-key"] == 100 + DAY, expires
        assert expires["recent-key"] == now - 60 + DAY, expires
        assert now - 5 <= expires["undated-key"] <= int(time.time()) + 5, f"an undated key did not expire at the migration: {expires}"

        assert inspect(connection).get_pk_constraint("idempotency_keys")["constrained_columns"] == ["project_id", "key"]
        indexes = {index["name"] for index in inspect(connection).get_indexes("idempotency_keys")}
        assert {"ix_idempotency_keys_project_id", "ix_idempotency_keys_expires_at"} <= indexes, indexes
        # A key is its project's now.
        connection.execute(text(
            "INSERT INTO idempotency_keys (key, project_id, action_type_id, response_payload, created_at, expires_at) "
            "VALUES ('recent-key', 'beta', 'act', '{}', 1, 2)"))
        assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == current_head()

    # Applied twice, as CI does.
    alembic("upgrade", "head")

    # The downgrade cannot put a key used by two projects back under a key-only primary key.
    refused = alembic("downgrade", PRIOR, expect_ok=False)
    assert refused.returncode != 0 and "more than one project" in (refused.stdout + refused.stderr), refused.stderr[-600:]
    with engine.begin() as connection:
        connection.execute(text("DELETE FROM idempotency_keys WHERE project_id = 'beta'"))
    alembic("downgrade", PRIOR)
    with engine.connect() as connection:
        assert inspect(connection).get_pk_constraint("idempotency_keys")["constrained_columns"] == ["key"]
        assert not {"consumed_at", "consumed_by_outbox_event_id"} & columns(connection, "approval_requests")
        assert "expires_at" not in columns(connection, "idempotency_keys")
        assert "ix_idempotency_keys_project_id" in {index["name"] for index in inspect(connection).get_indexes("idempotency_keys")}

    alembic("upgrade", "head")
    with engine.connect() as connection:
        assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == current_head()
    engine.dispose()

print("Approval consumption migration verified.")

"""Consume an approval when its action runs, and give idempotency keys a project and a day.

R11 of GOAL_REPAIR_2026-08-23, decision E (2026-09-23). An approved ApprovalRequest was
checked only for being APPROVED, so it ran its action again under every new idempotency key;
and the keys themselves were one global namespace that never expired. Three changes:

- `approval_requests` gains `consumed_at` and `consumed_by_outbox_event_id`. Approvals that
  already ran are backfilled from the only durable link to their run, the
  `approval_request_id` the execute route has written into `action_outbox.payload` since
  approvals existed: the earliest such row consumes the approval.
- `idempotency_keys` gains `expires_at`, a day after `created_at`, old keys included -- the
  owner chose to expire them rather than grandfather them. A key with no `created_at` has no
  age to count from and expires at the migration.
- `idempotency_keys` is keyed by `(project_id, key)` instead of `key`, so one project's key
  neither collides with nor reveals another's. `key` was unique, so no existing row can
  violate the new key.

Revision ID: 0047_approval_consumption
Revises: 0046_dataset_txn_seq_unique
"""
from __future__ import annotations

import json
import time

import sqlalchemy as sa
from alembic import op

revision = "0047_approval_consumption"
down_revision = "0046_dataset_txn_seq_unique"
branch_labels = None
depends_on = None

APPROVALS = "approval_requests"
OUTBOX = "action_outbox"
KEYS = "idempotency_keys"
KEY_TTL_SECONDS = 24 * 60 * 60
EXPIRES_INDEX = "ix_idempotency_keys_expires_at"


def _columns(bind, table: str) -> set:
    inspector = sa.inspect(bind)
    if not inspector.has_table(table):
        return set()
    return {column["name"] for column in inspector.get_columns(table)}


def _backfill_consumption(bind) -> None:
    # Guarded: a partial legacy schema (the 0016 test) has no payload, status or created_at.
    if not {"id", "payload", "created_at"} <= _columns(bind, OUTBOX):
        return
    if not {"id", "status", "consumed_at", "consumed_by_outbox_event_id"} <= _columns(bind, APPROVALS):
        return
    outbox = sa.table(OUTBOX, sa.column("id", sa.String), sa.column("payload", sa.JSON),
                      sa.column("created_at", sa.Integer))
    first: dict = {}
    for row in bind.execute(sa.select(outbox.c.id, outbox.c.payload, outbox.c.created_at)):
        payload = row.payload
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except ValueError:
                continue
        approval_id = (payload or {}).get("approval_request_id") if isinstance(payload, dict) else None
        if not approval_id:
            continue
        candidate = (row.created_at if row.created_at is not None else 0, row.id)
        if approval_id not in first or candidate < first[approval_id]:
            first[approval_id] = candidate
    for approval_id, (created_at, outbox_id) in first.items():
        bind.execute(sa.text(
            f"UPDATE {APPROVALS} SET consumed_at = :at, consumed_by_outbox_event_id = :outbox "
            "WHERE id = :id AND consumed_at IS NULL"
        ), {"at": created_at, "outbox": outbox_id, "id": approval_id})


def _key_is_project_scoped(bind) -> bool:
    return sa.inspect(bind).get_pk_constraint(KEYS).get("constrained_columns") == ["project_id", "key"]


def upgrade() -> None:
    bind = op.get_bind()

    # 1. Approvals remember that they ran.
    present = _columns(bind, APPROVALS)
    if present:
        if "consumed_at" not in present:
            op.add_column(APPROVALS, sa.Column("consumed_at", sa.Integer(), nullable=True))
        if "consumed_by_outbox_event_id" not in present:
            op.add_column(APPROVALS, sa.Column("consumed_by_outbox_event_id", sa.String(), nullable=True))
        _backfill_consumption(bind)

    # 2. Keys expire a day after they were written, old keys included.
    present = _columns(bind, KEYS)
    if not present:
        return
    if "expires_at" not in present:
        op.add_column(KEYS, sa.Column("expires_at", sa.Integer(), nullable=True))
    if "created_at" in _columns(bind, KEYS):
        bind.execute(sa.text(
            f"UPDATE {KEYS} SET expires_at = created_at + :ttl WHERE expires_at IS NULL AND created_at IS NOT NULL"
        ), {"ttl": KEY_TTL_SECONDS})
    bind.execute(sa.text(f"UPDATE {KEYS} SET expires_at = :now WHERE expires_at IS NULL"), {"now": int(time.time())})
    if EXPIRES_INDEX not in {index["name"] for index in sa.inspect(bind).get_indexes(KEYS)}:
        op.create_index(EXPIRES_INDEX, KEYS, ["expires_at"])

    # 3. A key belongs to its project. 0001 builds today's models, so a fresh chain already has it.
    if {"project_id", "key"} <= _columns(bind, KEYS) and not _key_is_project_scoped(bind):
        with op.batch_alter_table(KEYS, recreate="always") as batch:
            if bind.dialect.name == "postgresql":
                batch.drop_constraint(f"{KEYS}_pkey", type_="primary")
            batch.create_primary_key(f"{KEYS}_pkey", ["project_id", "key"])


def downgrade() -> None:
    bind = op.get_bind()
    present = _columns(bind, KEYS)
    if present:
        if _key_is_project_scoped(bind):
            # A key-only primary key cannot hold one key in two projects. Refuse rather than
            # choose which project's receipt to throw away.
            shared = bind.execute(sa.text(
                f"SELECT key FROM {KEYS} GROUP BY key HAVING COUNT(*) > 1 LIMIT 1")).first()
            if shared is not None:
                raise RuntimeError(f"idempotency key '{shared[0]}' is used by more than one project; "
                                   "it cannot return to a key-only primary key")
            with op.batch_alter_table(KEYS, recreate="always") as batch:
                if bind.dialect.name == "postgresql":
                    batch.drop_constraint(f"{KEYS}_pkey", type_="primary")
                batch.create_primary_key(f"{KEYS}_pkey", ["key"])
        if EXPIRES_INDEX in {index["name"] for index in sa.inspect(bind).get_indexes(KEYS)}:
            op.drop_index(EXPIRES_INDEX, table_name=KEYS)
        if "expires_at" in _columns(bind, KEYS):
            with op.batch_alter_table(KEYS) as batch:
                batch.drop_column("expires_at")
    present = _columns(bind, APPROVALS)
    for name in ("consumed_by_outbox_event_id", "consumed_at"):
        if name in present:
            with op.batch_alter_table(APPROVALS) as batch:
                batch.drop_column(name)

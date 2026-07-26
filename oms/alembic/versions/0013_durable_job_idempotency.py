"""Persist asynchronous job idempotency receipts.

Revision ID: 0013_job_idempotency
Revises: 0012_artifact_receipts
"""
import hashlib
import json

import sqlalchemy as sa
from alembic import op

revision = "0013_job_idempotency"
down_revision = "0012_artifact_receipts"
branch_labels = None
depends_on = None


def _payload(value):
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value:
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else {}
        except (TypeError, ValueError):
            return {}
    return {}


def _scope_hash(row, idempotency_key):
    identity = {
        "project_id": row.get("project_id") or "default",
        "actor": row.get("actor") or "workspace",
        "job_type": row.get("job_type") or "unknown",
        "subject_type": row.get("subject_type"),
        "subject_id": row.get("subject_id"),
        "idempotency_key": idempotency_key,
    }
    raw = json.dumps(identity, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def upgrade() -> None:
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())
    if "platform_job_idempotency_receipts" not in tables:
        op.create_table(
            "platform_job_idempotency_receipts",
            sa.Column("id", sa.String(), nullable=False),
            sa.Column("scope_hash", sa.String(length=64), nullable=False),
            sa.Column("job_id", sa.String(), nullable=False),
            sa.Column("project_id", sa.String(), nullable=False),
            sa.Column("actor", sa.String(), nullable=False),
            sa.Column("job_type", sa.String(), nullable=False),
            sa.Column("subject_type", sa.String(), nullable=True),
            sa.Column("subject_id", sa.String(), nullable=True),
            sa.Column("idempotency_key", sa.String(), nullable=False),
            sa.Column("request_hash", sa.String(length=64), nullable=True),
            sa.Column("created_at", sa.Integer(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("scope_hash", name="uq_platform_job_idempotency_scope"),
            sa.UniqueConstraint("job_id", name="uq_platform_job_idempotency_job"),
        )
        for name, columns in (
            ("ix_platform_job_idempotency_receipts_id", ["id"]),
            ("ix_platform_job_idempotency_receipts_scope_hash", ["scope_hash"]),
            ("ix_platform_job_idempotency_receipts_job_id", ["job_id"]),
            ("ix_platform_job_idempotency_receipts_project_id", ["project_id"]),
            ("ix_platform_job_idempotency_receipts_actor", ["actor"]),
            ("ix_platform_job_idempotency_receipts_job_type", ["job_type"]),
            ("ix_platform_job_idempotency_receipts_created_at", ["created_at"]),
        ):
            op.create_index(name, "platform_job_idempotency_receipts", columns)

    if "platform_jobs" not in tables:
        return
    receipt_table = sa.table(
        "platform_job_idempotency_receipts",
        sa.column("id", sa.String()),
        sa.column("scope_hash", sa.String()),
        sa.column("job_id", sa.String()),
        sa.column("project_id", sa.String()),
        sa.column("actor", sa.String()),
        sa.column("job_type", sa.String()),
        sa.column("subject_type", sa.String()),
        sa.column("subject_id", sa.String()),
        sa.column("idempotency_key", sa.String()),
        sa.column("request_hash", sa.String()),
        sa.column("created_at", sa.Integer()),
    )
    seen = {
        str(row["scope_hash"])
        for row in bind.execute(sa.text(
            "SELECT scope_hash FROM platform_job_idempotency_receipts"
        )).mappings().all()
    }
    jobs = bind.execute(sa.text(
        "SELECT id, project_id, job_type, actor, subject_type, subject_id, payload, created_at "
        "FROM platform_jobs ORDER BY created_at, id"
    )).mappings().all()
    for job in jobs:
        execution = _payload(job.get("payload")).get("__execution") or {}
        key = str(execution.get("idempotency_key") or "").strip()
        if not key:
            continue
        scope_hash = _scope_hash(job, key)
        if scope_hash in seen:
            continue
        seen.add(scope_hash)
        digest = hashlib.sha256(f"{scope_hash}|{job['id']}".encode("utf-8")).hexdigest()[:24]
        bind.execute(receipt_table.insert().values(
            id=f"jobreceipt_{digest}",
            scope_hash=scope_hash,
            job_id=job["id"],
            project_id=job.get("project_id") or "default",
            actor=job.get("actor") or "workspace",
            job_type=job.get("job_type") or "unknown",
            subject_type=job.get("subject_type"),
            subject_id=job.get("subject_id"),
            idempotency_key=key,
            request_hash=None,
            created_at=int(job.get("created_at") or 0),
        ))


def downgrade() -> None:
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    if "platform_job_idempotency_receipts" in tables:
        op.drop_table("platform_job_idempotency_receipts")

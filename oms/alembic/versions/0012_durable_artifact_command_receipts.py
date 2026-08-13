"""Persist visual-builder command idempotency receipts.

Revision ID: 0012_artifact_receipts
Revises: 0011_hashed_service_tokens
"""
import hashlib
import json

import sqlalchemy as sa
from alembic import op

revision = "0012_artifact_receipts"
down_revision = "0011_hashed_service_tokens"
branch_labels = None
depends_on = None


def _metadata(value):
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value:
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else {}
        except (TypeError, ValueError):
            return {}
    return {}


def upgrade() -> None:
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())
    if "platform_artifact_command_receipts" not in tables:
        op.create_table(
            "platform_artifact_command_receipts",
            sa.Column("id", sa.String(), nullable=False),
            sa.Column("artifact_id", sa.String(), nullable=False),
            sa.Column("project_id", sa.String(), nullable=False),
            sa.Column("command_scope", sa.String(), nullable=False),
            sa.Column("idempotency_key", sa.String(), nullable=False),
            sa.Column("request_hash", sa.String(length=64), nullable=True),
            sa.Column("revision", sa.Integer(), nullable=False),
            sa.Column("lock_version", sa.Integer(), nullable=True),
            sa.Column("participant_id", sa.String(), nullable=True),
            sa.Column("command_ids", sa.JSON(), nullable=False),
            sa.Column("rebased_from_lock_version", sa.Integer(), nullable=True),
            sa.Column("created_at", sa.Integer(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("artifact_id", "command_scope", "idempotency_key", name="uq_artifact_command_receipt"),
        )
        for name, columns in (
            ("ix_platform_artifact_command_receipts_id", ["id"]),
            ("ix_platform_artifact_command_receipts_artifact_id", ["artifact_id"]),
            ("ix_platform_artifact_command_receipts_project_id", ["project_id"]),
            ("ix_platform_artifact_command_receipts_command_scope", ["command_scope"]),
            ("ix_platform_artifact_command_receipts_participant_id", ["participant_id"]),
            ("ix_platform_artifact_command_receipts_created_at", ["created_at"]),
        ):
            op.create_index(name, "platform_artifact_command_receipts", columns)

    if "platform_artifacts" not in tables:
        return
    receipt_table = sa.table(
        "platform_artifact_command_receipts",
        sa.column("id", sa.String()),
        sa.column("artifact_id", sa.String()),
        sa.column("project_id", sa.String()),
        sa.column("command_scope", sa.String()),
        sa.column("idempotency_key", sa.String()),
        sa.column("request_hash", sa.String()),
        sa.column("revision", sa.Integer()),
        sa.column("lock_version", sa.Integer()),
        sa.column("participant_id", sa.String()),
        sa.column("command_ids", sa.JSON()),
        sa.column("rebased_from_lock_version", sa.Integer()),
        sa.column("created_at", sa.Integer()),
    )
    artifacts = bind.execute(sa.text(
        "SELECT id, project_id, current_revision, updated_at, metadata FROM platform_artifacts"
    )).mappings().all()
    seen = {
        (str(row["artifact_id"]), str(row["command_scope"]), str(row["idempotency_key"]))
        for row in bind.execute(sa.text(
            "SELECT artifact_id, command_scope, idempotency_key FROM platform_artifact_command_receipts"
        )).mappings().all()
    }
    for artifact in artifacts:
        metadata = _metadata(artifact.get("metadata"))
        for scope, legacy_key in (("builder", "command_receipts"), ("collaboration", "collaboration_receipts")):
            for receipt in metadata.get(legacy_key) or []:
                key = str(receipt.get("idempotency_key") or "").strip()
                identity = (str(artifact["id"]), scope, key)
                if not key or identity in seen:
                    continue
                seen.add(identity)
                digest = hashlib.sha256("|".join(identity).encode("utf-8")).hexdigest()[:24]
                bind.execute(receipt_table.insert().values(
                    id=f"receipt_{digest}",
                    artifact_id=artifact["id"],
                    project_id=artifact.get("project_id") or "default",
                    command_scope=scope,
                    idempotency_key=key,
                    request_hash=None,
                    revision=int(receipt.get("revision") or artifact.get("current_revision") or 1),
                    lock_version=receipt.get("lock_version"),
                    participant_id=receipt.get("participant_id"),
                    command_ids=list(receipt.get("command_ids") or []),
                    rebased_from_lock_version=receipt.get("rebased_from_lock_version"),
                    created_at=int(receipt.get("created_at") or artifact.get("updated_at") or 0),
                ))


def downgrade() -> None:
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    if "platform_artifact_command_receipts" in tables:
        op.drop_table("platform_artifact_command_receipts")

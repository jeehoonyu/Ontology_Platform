"""Add signed plugin trust, version, and execution records.

Revision ID: 0032_signed_plugin_runtime
Revises: 0031_artifact_review_workflows
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision = "0032_signed_plugin_runtime"
down_revision = "0031_artifact_review_workflows"
branch_labels = None
depends_on = None


def _tables(bind) -> set[str]:
    return set(sa.inspect(bind).get_table_names())


def _indexes(bind, table: str) -> set[str]:
    inspector = sa.inspect(bind)
    names = {row["name"] for row in inspector.get_indexes(table)}
    names.update(row["name"] for row in inspector.get_unique_constraints(table) if row.get("name"))
    return names


def _index(table: str, name: str, columns: list[str], *, unique: bool = False) -> None:
    if name not in _indexes(op.get_bind(), table):
        op.create_index(name, table, columns, unique=unique)


def upgrade() -> None:
    bind = op.get_bind()
    existing = _tables(bind)
    json_type = postgresql.JSONB() if bind.dialect.name == "postgresql" else sa.JSON()
    if "plugin_trust_keys" not in existing:
        op.create_table(
            "plugin_trust_keys",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("organization_id", sa.String(), nullable=False),
            sa.Column("display_name", sa.String(), nullable=False),
            sa.Column("algorithm", sa.String(), nullable=False, server_default="ed25519"),
            sa.Column("public_key", sa.Text(), nullable=False),
            sa.Column("fingerprint", sa.String(), nullable=False),
            sa.Column("status", sa.String(), nullable=False, server_default="ACTIVE"),
            sa.Column("created_by", sa.String(), nullable=False),
            sa.Column("created_at", sa.Integer(), nullable=False),
            sa.Column("revoked_at", sa.Integer(), nullable=True),
            sa.UniqueConstraint("fingerprint", name="uq_plugin_trust_key_fingerprint"),
        )
    if "plugin_versions" not in existing:
        op.create_table(
            "plugin_versions",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("project_id", sa.String(), nullable=False),
            sa.Column("plugin_id", sa.String(), nullable=False),
            sa.Column("version", sa.String(), nullable=False),
            sa.Column("kind", sa.String(), nullable=False),
            sa.Column("runtime", sa.String(), nullable=False),
            sa.Column("entrypoint", sa.String(), nullable=False),
            sa.Column("manifest", json_type, nullable=False),
            sa.Column("manifest_sha256", sa.String(), nullable=False),
            sa.Column("bundle_sha256", sa.String(), nullable=False),
            sa.Column("bundle_path", sa.Text(), nullable=False),
            sa.Column("signature", sa.Text(), nullable=False),
            sa.Column("signer_key_id", sa.String(), nullable=False),
            sa.Column("capabilities", json_type, nullable=False),
            sa.Column("operations", json_type, nullable=False),
            sa.Column("status", sa.String(), nullable=False, server_default="VERIFIED"),
            sa.Column("created_by", sa.String(), nullable=False),
            sa.Column("created_at", sa.Integer(), nullable=False),
            sa.Column("activated_at", sa.Integer(), nullable=True),
            sa.Column("revoked_at", sa.Integer(), nullable=True),
            sa.UniqueConstraint("project_id", "plugin_id", "version", name="uq_plugin_project_version"),
        )
    if "plugin_executions" not in existing:
        op.create_table(
            "plugin_executions",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("project_id", sa.String(), nullable=False),
            sa.Column("plugin_version_id", sa.String(), nullable=False),
            sa.Column("plugin_id", sa.String(), nullable=False),
            sa.Column("operation", sa.String(), nullable=False),
            sa.Column("status", sa.String(), nullable=False),
            sa.Column("request_hash", sa.String(), nullable=False),
            sa.Column("idempotency_key", sa.String(), nullable=True),
            sa.Column("input_summary", json_type, nullable=False),
            sa.Column("output", json_type, nullable=False),
            sa.Column("evidence", json_type, nullable=False),
            sa.Column("sandbox", json_type, nullable=False),
            sa.Column("exit_code", sa.Integer(), nullable=True),
            sa.Column("duration_ms", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("error", sa.Text(), nullable=True),
            sa.Column("actor", sa.String(), nullable=False),
            sa.Column("created_at", sa.Integer(), nullable=False),
            sa.Column("completed_at", sa.Integer(), nullable=True),
            sa.UniqueConstraint("project_id", "plugin_version_id", "actor", "idempotency_key", name="uq_plugin_execution_idempotency"),
        )
    for table, columns in {
        "plugin_trust_keys": ("organization_id", "fingerprint", "status"),
        "plugin_versions": ("project_id", "plugin_id", "kind", "manifest_sha256", "bundle_sha256", "signer_key_id", "status"),
        "plugin_executions": ("project_id", "plugin_version_id", "plugin_id", "operation", "status", "request_hash", "idempotency_key"),
    }.items():
        for column in columns:
            _index(table, f"ix_{table}_{column}", [column])


def downgrade() -> None:
    existing = _tables(op.get_bind())
    for table in ("plugin_executions", "plugin_versions", "plugin_trust_keys"):
        if table in existing:
            op.drop_table(table)

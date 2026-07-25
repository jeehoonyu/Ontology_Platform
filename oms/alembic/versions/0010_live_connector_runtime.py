"""Add encrypted connector credentials and fetch-attempt evidence.

Revision ID: 0010_live_connector_runtime
Revises: 0009_worker_fleet_control
"""
import sqlalchemy as sa
from alembic import op

revision = "0010_live_connector_runtime"
down_revision = "0009_worker_fleet_control"
branch_labels = None
depends_on = None


def upgrade() -> None:
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    if "connector_credentials" not in tables:
        op.create_table(
            "connector_credentials",
            sa.Column("id", sa.String(), nullable=False), sa.Column("project_id", sa.String(), nullable=False),
            sa.Column("source_id", sa.String(), nullable=False), sa.Column("credential_type", sa.String(), nullable=False),
            sa.Column("encrypted_secret", sa.Text(), nullable=False), sa.Column("metadata", sa.JSON(), nullable=False),
            sa.Column("key_id", sa.String(), nullable=False), sa.Column("status", sa.String(), nullable=False),
            sa.Column("expires_at", sa.Integer(), nullable=True), sa.Column("created_by", sa.String(), nullable=False),
            sa.Column("created_at", sa.Integer(), nullable=False), sa.Column("rotated_at", sa.Integer(), nullable=True),
            sa.PrimaryKeyConstraint("id"),
        )
        for column in ("id", "project_id", "source_id", "credential_type", "status"):
            op.create_index(f"ix_connector_credentials_{column}", "connector_credentials", [column])
    if "connector_fetch_attempts" not in tables:
        op.create_table(
            "connector_fetch_attempts",
            sa.Column("id", sa.String(), nullable=False), sa.Column("project_id", sa.String(), nullable=False),
            sa.Column("source_id", sa.String(), nullable=False), sa.Column("sync_id", sa.String(), nullable=True),
            sa.Column("ingestion_run_id", sa.String(), nullable=True), sa.Column("adapter_id", sa.String(), nullable=False),
            sa.Column("operation", sa.String(), nullable=False), sa.Column("status", sa.String(), nullable=False),
            sa.Column("records_read", sa.Integer(), nullable=False), sa.Column("bytes_read", sa.Integer(), nullable=False),
            sa.Column("duration_ms", sa.Integer(), nullable=False), sa.Column("cursor_in", sa.String(), nullable=True),
            sa.Column("cursor_out", sa.String(), nullable=True), sa.Column("metadata", sa.JSON(), nullable=False),
            sa.Column("error", sa.String(), nullable=True), sa.Column("created_at", sa.Integer(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
        )
        for column in ("id", "project_id", "source_id", "sync_id", "ingestion_run_id", "adapter_id", "status"):
            op.create_index(f"ix_connector_fetch_attempts_{column}", "connector_fetch_attempts", [column])


def downgrade() -> None:
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    for table in ("connector_fetch_attempts", "connector_credentials"):
        if table in tables:
            op.drop_table(table)

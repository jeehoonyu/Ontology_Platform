"""Add worker fleet registration and project queue policies.

Revision ID: 0009_worker_fleet_control
Revises: 0008_runtime_observability
"""
import sqlalchemy as sa
from alembic import op

revision = "0009_worker_fleet_control"
down_revision = "0008_runtime_observability"
branch_labels = None
depends_on = None


def upgrade() -> None:
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    if "runtime_workers" not in tables:
        op.create_table(
            "runtime_workers",
            sa.Column("id", sa.String(), nullable=False),
            sa.Column("organization_id", sa.String(), nullable=False),
            sa.Column("worker_name", sa.String(), nullable=False),
            sa.Column("principal_id", sa.String(), nullable=False),
            sa.Column("project_id", sa.String(), nullable=True),
            sa.Column("status", sa.String(), nullable=False),
            sa.Column("supported_job_types", sa.JSON(), nullable=False),
            sa.Column("max_concurrency", sa.Integer(), nullable=False),
            sa.Column("labels", sa.JSON(), nullable=False),
            sa.Column("started_at", sa.Integer(), nullable=False),
            sa.Column("heartbeat_at", sa.Integer(), nullable=False),
            sa.Column("last_claimed_at", sa.Integer(), nullable=True),
            sa.Column("drain_requested_at", sa.Integer(), nullable=True),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("organization_id", "worker_name", name="uq_runtime_worker_org_name"),
        )
        for column in ("id", "organization_id", "worker_name", "principal_id", "project_id", "status", "heartbeat_at"):
            op.create_index(f"ix_runtime_workers_{column}", "runtime_workers", [column])
    if "runtime_queue_policies" not in tables:
        op.create_table(
            "runtime_queue_policies",
            sa.Column("id", sa.String(), nullable=False),
            sa.Column("project_id", sa.String(), nullable=False),
            sa.Column("weight", sa.Integer(), nullable=False),
            sa.Column("max_concurrency", sa.Integer(), nullable=False),
            sa.Column("paused", sa.Boolean(), nullable=False),
            sa.Column("updated_by", sa.String(), nullable=False),
            sa.Column("created_at", sa.Integer(), nullable=False),
            sa.Column("updated_at", sa.Integer(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_runtime_queue_policies_id", "runtime_queue_policies", ["id"])
        op.create_index("ix_runtime_queue_policies_project_id", "runtime_queue_policies", ["project_id"], unique=True)


def downgrade() -> None:
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    for table in ("runtime_queue_policies", "runtime_workers"):
        if table in tables:
            op.drop_table(table)

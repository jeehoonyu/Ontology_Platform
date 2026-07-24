"""Add durable worker leases for asynchronous platform jobs.

Revision ID: 0003_platform_job_leases
Revises: 0002_legacy_column_compat
"""
import sqlalchemy as sa
from alembic import op

revision = "0003_platform_job_leases"
down_revision = "0002_legacy_column_compat"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Revision 0002 reflects current metadata to support pre-Alembic installs.
    # On a fresh database it may therefore create this table before control
    # reaches this explicit revision; upgrades from an older 0002 database do
    # not have it yet.
    if "platform_job_leases" in sa.inspect(op.get_bind()).get_table_names():
        return
    op.create_table(
        "platform_job_leases",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("job_id", sa.String(), nullable=False),
        sa.Column("worker_id", sa.String(), nullable=False),
        sa.Column("token", sa.String(), nullable=False),
        sa.Column("claimed_at", sa.Integer(), nullable=False),
        sa.Column("heartbeat_at", sa.Integer(), nullable=False),
        sa.Column("expires_at", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("job_id"),
        sa.UniqueConstraint("token"),
    )
    op.create_index("ix_platform_job_leases_id", "platform_job_leases", ["id"])
    op.create_index("ix_platform_job_leases_job_id", "platform_job_leases", ["job_id"])
    op.create_index("ix_platform_job_leases_worker_id", "platform_job_leases", ["worker_id"])
    op.create_index("ix_platform_job_leases_token", "platform_job_leases", ["token"])
    op.create_index("ix_platform_job_leases_expires_at", "platform_job_leases", ["expires_at"])


def downgrade() -> None:
    op.drop_index("ix_platform_job_leases_expires_at", table_name="platform_job_leases")
    op.drop_index("ix_platform_job_leases_token", table_name="platform_job_leases")
    op.drop_index("ix_platform_job_leases_worker_id", table_name="platform_job_leases")
    op.drop_index("ix_platform_job_leases_job_id", table_name="platform_job_leases")
    op.drop_index("ix_platform_job_leases_id", table_name="platform_job_leases")
    op.drop_table("platform_job_leases")

"""Link signed plugin executions to durable platform jobs.

Revision ID: 0033_async_plugin_execution
Revises: 0032_signed_plugin_runtime
"""

import sqlalchemy as sa
from alembic import op


revision = "0033_async_plugin_execution"
down_revision = "0032_signed_plugin_runtime"
branch_labels = None
depends_on = None


def _columns(bind, table_name: str) -> set[str]:
    return {row["name"] for row in sa.inspect(bind).get_columns(table_name)}


def _indexes(bind, table_name: str) -> set[str]:
    inspector = sa.inspect(bind)
    names = {row["name"] for row in inspector.get_indexes(table_name)}
    names.update(row["name"] for row in inspector.get_unique_constraints(table_name) if row.get("name"))
    return names


def upgrade() -> None:
    bind = op.get_bind()
    if "plugin_executions" not in sa.inspect(bind).get_table_names():
        return
    if "job_id" not in _columns(bind, "plugin_executions"):
        op.add_column("plugin_executions", sa.Column("job_id", sa.String(), nullable=True))
    indexes = _indexes(bind, "plugin_executions")
    if "ix_plugin_executions_job_id" not in indexes:
        op.create_index("ix_plugin_executions_job_id", "plugin_executions", ["job_id"], unique=True)


def downgrade() -> None:
    bind = op.get_bind()
    if "plugin_executions" not in sa.inspect(bind).get_table_names():
        return
    indexes = _indexes(bind, "plugin_executions")
    for name in ("ix_plugin_executions_job_id",):
        if name in indexes:
            op.drop_index(name, table_name="plugin_executions")
    if "job_id" in _columns(bind, "plugin_executions"):
        op.drop_column("plugin_executions", "job_id")

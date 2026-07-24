"""Persist durable AIP agent execution evidence.

Revision ID: 0004_agent_execution_evidence
Revises: 0003_platform_job_leases
"""
import sqlalchemy as sa
from alembic import op

revision = "0004_agent_execution_evidence"
down_revision = "0003_platform_job_leases"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "agent_tool_runs" not in inspector.get_table_names():
        return
    columns = {column["name"] for column in inspector.get_columns("agent_tool_runs")}
    if "retrieval" not in columns:
        op.add_column("agent_tool_runs", sa.Column("retrieval", sa.JSON(), nullable=True))
    if "policy_summary" not in columns:
        op.add_column("agent_tool_runs", sa.Column("policy_summary", sa.JSON(), nullable=True))
    if "execution_job_id" not in columns:
        op.add_column("agent_tool_runs", sa.Column("execution_job_id", sa.String(), nullable=True))
    indexes = {index["name"] for index in sa.inspect(bind).get_indexes("agent_tool_runs")}
    if "ix_agent_tool_runs_execution_job_id" not in indexes:
        op.create_index("ix_agent_tool_runs_execution_job_id", "agent_tool_runs", ["execution_job_id"], unique=True)


def downgrade() -> None:
    bind = op.get_bind()
    columns = {column["name"] for column in sa.inspect(bind).get_columns("agent_tool_runs")}
    if "execution_job_id" in columns:
        op.drop_index("ix_agent_tool_runs_execution_job_id", table_name="agent_tool_runs")
        op.drop_column("agent_tool_runs", "execution_job_id")
    if "policy_summary" in columns:
        op.drop_column("agent_tool_runs", "policy_summary")
    if "retrieval" in columns:
        op.drop_column("agent_tool_runs", "retrieval")

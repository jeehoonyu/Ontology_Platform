"""Scope model endpoints and AI evaluation evidence to projects.

Revision ID: 0018_project_scoped_ai_evals
Revises: 0017_governed_automation_scope
"""
import sqlalchemy as sa
from alembic import op

revision = "0018_project_scoped_ai_evals"
down_revision = "0017_governed_automation_scope"
branch_labels = None
depends_on = None


TABLES = ("model_endpoints", "eval_suites", "eval_runs", "aip_eval_runs")


def upgrade() -> None:
    bind = op.get_bind()
    existing_tables = set(sa.inspect(bind).get_table_names())
    for table_name in TABLES:
        if table_name not in existing_tables:
            continue
        columns = {column["name"] for column in sa.inspect(bind).get_columns(table_name)}
        if "project_id" not in columns:
            with op.batch_alter_table(table_name) as batch:
                batch.add_column(sa.Column("project_id", sa.String(), nullable=False, server_default="default"))
        index_name = f"ix_{table_name}_project_id"
        indexes = {index["name"] for index in sa.inspect(bind).get_indexes(table_name)}
        if index_name not in indexes:
            op.create_index(index_name, table_name, ["project_id"])


def downgrade() -> None:
    bind = op.get_bind()
    existing_tables = set(sa.inspect(bind).get_table_names())
    for table_name in reversed(TABLES):
        if table_name not in existing_tables:
            continue
        columns = {column["name"] for column in sa.inspect(bind).get_columns(table_name)}
        if "project_id" in columns:
            # Drop the index first. SQLite rebuilds the table for a column drop
            # and recreates reflected indexes, so an index still referencing
            # project_id fails the rebuild. PostgreSQL drops it by cascade.
            indexes = {index["name"] for index in sa.inspect(bind).get_indexes(table_name)}
            index_name = f"ix_{table_name}_project_id"
            if index_name in indexes:
                op.drop_index(index_name, table_name=table_name)
            with op.batch_alter_table(table_name) as batch:
                batch.drop_column("project_id")

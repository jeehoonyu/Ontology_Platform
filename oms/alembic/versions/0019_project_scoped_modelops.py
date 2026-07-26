"""Scope the complete modeling and ModelOps lifecycle to projects.

Revision ID: 0019_project_scoped_modelops
Revises: 0018_project_scoped_ai_evals
"""
import sqlalchemy as sa
from alembic import op

revision = "0019_project_scoped_modelops"
down_revision = "0018_project_scoped_ai_evals"
branch_labels = None
depends_on = None


TABLES = (
    "modeling_objectives",
    "model_submissions",
    "model_deployments",
    "model_monitors",
    "model_monitor_runs",
    "model_prediction_logs",
    "mev_releases",
    "mev_checks",
    "mev_check_results",
    "mev_eval_datasets",
    "mev_eval_subsets",
    "mev_experiments",
    "mev_adapters",
    "mev_deployment_configs",
)


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
            indexes = {index["name"] for index in sa.inspect(bind).get_indexes(table_name)}
            index_name = f"ix_{table_name}_project_id"
            if index_name in indexes:
                op.drop_index(index_name, table_name=table_name)
            with op.batch_alter_table(table_name) as batch:
                batch.drop_column("project_id")

"""Scope Pipeline Builder graphs to projects.

Revision ID: 0015_pipeline_project_scope
Revises: 0014_import_project_scope
"""
import sqlalchemy as sa
from alembic import op

revision = "0015_pipeline_project_scope"
down_revision = "0014_import_project_scope"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "pipeline_builder_graphs" not in set(inspector.get_table_names()):
        return
    columns = {column["name"] for column in inspector.get_columns("pipeline_builder_graphs")}
    if "project_id" not in columns:
        with op.batch_alter_table("pipeline_builder_graphs") as batch:
            batch.add_column(sa.Column("project_id", sa.String(), nullable=False, server_default="default"))
    indexes = {index["name"] for index in sa.inspect(bind).get_indexes("pipeline_builder_graphs")}
    if "ix_pipeline_builder_graphs_project_id" not in indexes:
        op.create_index("ix_pipeline_builder_graphs_project_id", "pipeline_builder_graphs", ["project_id"])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "pipeline_builder_graphs" not in set(inspector.get_table_names()):
        return
    columns = {column["name"] for column in inspector.get_columns("pipeline_builder_graphs")}
    if "project_id" in columns:
        with op.batch_alter_table("pipeline_builder_graphs") as batch:
            batch.drop_column("project_id")

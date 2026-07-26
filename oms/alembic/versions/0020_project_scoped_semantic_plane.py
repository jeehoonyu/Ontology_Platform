"""Scope core ontology, dataset, and legacy pipeline resources to projects.

Revision ID: 0020_project_semantic_plane
Revises: 0019_project_scoped_modelops
"""
import json

import sqlalchemy as sa
from alembic import op

revision = "0020_project_semantic_plane"
down_revision = "0019_project_scoped_modelops"
branch_labels = None
depends_on = None

TABLES = (
    "object_types", "object_instances", "link_types", "link_instances",
    "data_assets", "pipeline_definitions", "pipeline_runs",
    "saved_object_sets", "map_layer_definitions", "object_explorer_explorations", "act_action_log",
)


def upgrade() -> None:
    bind = op.get_bind()
    existing = set(sa.inspect(bind).get_table_names())
    for table_name in TABLES:
        if table_name not in existing:
            continue
        columns = {column["name"] for column in sa.inspect(bind).get_columns(table_name)}
        if "project_id" not in columns:
            with op.batch_alter_table(table_name) as batch:
                batch.add_column(sa.Column("project_id", sa.String(), nullable=False, server_default="default"))
        index_name = f"ix_{table_name}_project_id"
        indexes = {index["name"] for index in sa.inspect(bind).get_indexes(table_name)}
        if index_name not in indexes:
            op.create_index(index_name, table_name, ["project_id"])

    # Existing import/promoted datasets already carry ownership in asset_schema.
    # Preserve that evidence when promoting project_id to a first-class column.
    if "data_assets" in existing:
        assets = sa.table("data_assets", sa.column("id", sa.String()), sa.column("project_id", sa.String()), sa.column("asset_schema", sa.JSON()))
        for row in bind.execute(sa.select(assets.c.id, assets.c.asset_schema)):
            schema = row.asset_schema
            if isinstance(schema, str):
                try:
                    schema = json.loads(schema)
                except (TypeError, ValueError):
                    schema = {}
            project_id = str((schema or {}).get("project_id") or "default")
            bind.execute(assets.update().where(assets.c.id == row.id).values(project_id=project_id))


def downgrade() -> None:
    bind = op.get_bind()
    existing = set(sa.inspect(bind).get_table_names())
    for table_name in reversed(TABLES):
        if table_name not in existing:
            continue
        columns = {column["name"] for column in sa.inspect(bind).get_columns(table_name)}
        if "project_id" in columns:
            index_name = f"ix_{table_name}_project_id"
            indexes = {index["name"] for index in sa.inspect(bind).get_indexes(table_name)}
            if index_name in indexes:
                op.drop_index(index_name, table_name=table_name)
            with op.batch_alter_table(table_name) as batch:
                batch.drop_column("project_id")

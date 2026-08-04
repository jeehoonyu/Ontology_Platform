"""Add recoverable object materialization lifecycle state.

Revision ID: 0035_object_materialization
Revises: 0034_decision_project_scope
"""

import sqlalchemy as sa
from alembic import op


revision = "0035_object_materialization"
down_revision = "0034_decision_project_scope"
branch_labels = None
depends_on = None


INDEX_NAME = "ix_object_instances_materialized_active"


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "object_instances" not in inspector.get_table_names():
        return
    columns = {column["name"] for column in inspector.get_columns("object_instances")}
    additions = []
    if "materialization_id" not in columns:
        additions.append(sa.Column("materialization_id", sa.String(), nullable=True))
    if "is_active" not in columns:
        additions.append(sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()))
    if "retired_at" not in columns:
        additions.append(sa.Column("retired_at", sa.Integer(), nullable=True))
    if additions:
        with op.batch_alter_table("object_instances") as batch:
            for column in additions:
                batch.add_column(column)
    table = sa.table("object_instances", sa.column("is_active", sa.Boolean()))
    bind.execute(table.update().where(table.c.is_active.is_(None)).values(is_active=True))
    refreshed = sa.inspect(bind)
    columns = {column["name"] for column in refreshed.get_columns("object_instances")}
    indexes = {index["name"] for index in refreshed.get_indexes("object_instances")}
    index_columns = {"project_id", "object_type_id", "source_asset_id", "is_active", "id"}
    if INDEX_NAME not in indexes and index_columns.issubset(columns):
        op.create_index(
            INDEX_NAME,
            "object_instances",
            ["project_id", "object_type_id", "source_asset_id", "is_active", "id"],
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "object_instances" not in inspector.get_table_names():
        return
    indexes = {index["name"] for index in inspector.get_indexes("object_instances")}
    if INDEX_NAME in indexes:
        op.drop_index(INDEX_NAME, table_name="object_instances")
    columns = {column["name"] for column in sa.inspect(bind).get_columns("object_instances")}
    removable = [name for name in ("retired_at", "is_active", "materialization_id") if name in columns]
    if removable:
        with op.batch_alter_table("object_instances") as batch:
            for name in removable:
                batch.drop_column(name)

"""Scope Workshop modules to projects.

Revision ID: 0016_workshop_project_scope
Revises: 0015_pipeline_project_scope
"""
import sqlalchemy as sa
from alembic import op

revision = "0016_workshop_project_scope"
down_revision = "0015_pipeline_project_scope"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "workshop_modules" not in set(inspector.get_table_names()):
        return
    columns = {column["name"] for column in inspector.get_columns("workshop_modules")}
    if "project_id" not in columns:
        with op.batch_alter_table("workshop_modules") as batch:
            batch.add_column(sa.Column("project_id", sa.String(), nullable=False, server_default="default"))
    indexes = {index["name"] for index in sa.inspect(bind).get_indexes("workshop_modules")}
    if "ix_workshop_modules_project_id" not in indexes:
        op.create_index("ix_workshop_modules_project_id", "workshop_modules", ["project_id"])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "workshop_modules" not in set(inspector.get_table_names()):
        return
    columns = {column["name"] for column in inspector.get_columns("workshop_modules")}
    if "project_id" in columns:
        # Drop the index first. SQLite rebuilds the table for a column drop and
        # recreates reflected indexes, so an index still referencing project_id
        # fails the rebuild. PostgreSQL drops it by cascade.
        indexes = {index["name"] for index in inspector.get_indexes("workshop_modules")}
        if "ix_workshop_modules_project_id" in indexes:
            op.drop_index("ix_workshop_modules_project_id", table_name="workshop_modules")
        with op.batch_alter_table("workshop_modules") as batch:
            batch.drop_column("project_id")

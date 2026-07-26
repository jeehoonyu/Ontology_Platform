"""Scope import jobs to projects.

Revision ID: 0014_import_project_scope
Revises: 0013_job_idempotency
"""
import sqlalchemy as sa
from alembic import op

revision = "0014_import_project_scope"
down_revision = "0013_job_idempotency"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "import_jobs" not in set(inspector.get_table_names()):
        return
    columns = {column["name"] for column in inspector.get_columns("import_jobs")}
    if "project_id" not in columns:
        with op.batch_alter_table("import_jobs") as batch:
            batch.add_column(sa.Column("project_id", sa.String(), nullable=False, server_default="default"))
    indexes = {index["name"] for index in sa.inspect(bind).get_indexes("import_jobs")}
    if "ix_import_jobs_project_id" not in indexes:
        op.create_index("ix_import_jobs_project_id", "import_jobs", ["project_id"])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "import_jobs" not in set(inspector.get_table_names()):
        return
    columns = {column["name"] for column in inspector.get_columns("import_jobs")}
    if "project_id" in columns:
        with op.batch_alter_table("import_jobs") as batch:
            batch.drop_column("project_id")

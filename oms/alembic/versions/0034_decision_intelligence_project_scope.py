"""Scope Decision Intelligence resources and temporal evidence to projects.

Revision ID: 0034_decision_project_scope
Revises: 0033_async_plugin_execution
"""

import sqlalchemy as sa
from alembic import op


revision = "0034_decision_project_scope"
down_revision = "0033_async_plugin_execution"
branch_labels = None
depends_on = None

TABLES = (
    "decision_rules",
    "decision_scorecards",
    "decision_runs",
    "object_snapshots",
    "entity_resolution_jobs",
    "entity_candidates",
    "decision_scenarios",
)


def _table(name: str, *columns: str) -> sa.Table:
    return sa.table(name, *(sa.column(column, sa.String()) for column in columns))


def _backfill_from(bind, target_name: str, target_key: str, source_name: str, source_key: str) -> None:
    target = _table(target_name, target_key, "project_id")
    source = _table(source_name, source_key, "project_id")
    project = sa.select(source.c.project_id).where(source.c[source_key] == target.c[target_key]).limit(1).scalar_subquery()
    bind.execute(target.update().values(project_id=sa.func.coalesce(project, "default")))


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = set(inspector.get_table_names())
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

    if {"decision_rules", "object_types"} <= existing:
        _backfill_from(bind, "decision_rules", "object_type_id", "object_types", "id")
    if {"decision_scorecards", "object_types"} <= existing:
        _backfill_from(bind, "decision_scorecards", "object_type_id", "object_types", "id")
    if {"object_snapshots", "object_instances"} <= existing:
        _backfill_from(bind, "object_snapshots", "object_id", "object_instances", "id")
    if {"entity_resolution_jobs", "object_types"} <= existing:
        _backfill_from(bind, "entity_resolution_jobs", "object_type_id", "object_types", "id")
    if {"entity_candidates", "entity_resolution_jobs"} <= existing:
        _backfill_from(bind, "entity_candidates", "job_id", "entity_resolution_jobs", "id")


def downgrade() -> None:
    bind = op.get_bind()
    existing = set(sa.inspect(bind).get_table_names())
    for table_name in reversed(TABLES):
        if table_name not in existing:
            continue
        columns = {column["name"] for column in sa.inspect(bind).get_columns(table_name)}
        if "project_id" not in columns:
            continue
        index_name = f"ix_{table_name}_project_id"
        indexes = {index["name"] for index in sa.inspect(bind).get_indexes(table_name)}
        if index_name in indexes:
            op.drop_index(index_name, table_name=table_name)
        with op.batch_alter_table(table_name) as batch:
            batch.drop_column("project_id")

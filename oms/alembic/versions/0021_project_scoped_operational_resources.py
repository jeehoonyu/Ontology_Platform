"""Scope operational resources, investigations, schedules, and webhooks to projects.

Revision ID: 0021_project_operational_plane
Revises: 0020_project_semantic_plane
"""
import json

import sqlalchemy as sa
from alembic import op

revision = "0021_project_operational_plane"
down_revision = "0020_project_semantic_plane"
branch_labels = None
depends_on = None

TABLES = (
    "ops_events", "ops_alert_rules", "ops_alert_events", "ops_incidents",
    "ops_runbooks", "ops_runbook_executions", "ops_notifications", "ops_sla_policies",
    "investigation_workspaces", "investigation_evidence", "investigation_hypotheses",
    "investigation_findings", "investigation_reports", "schedules", "builds",
    "wh_webhooks", "wh_executions", "wh_credentials", "wh_outbound_apps",
    "wh_listeners", "wh_listener_events",
)


def _json(value):
    if isinstance(value, str):
        try:
            return json.loads(value)
        except (TypeError, ValueError):
            return {}
    return value if isinstance(value, dict) else {}


def _copy_parent_project(bind, child: str, parent: str, child_fk: str) -> None:
    if child not in sa.inspect(bind).get_table_names() or parent not in sa.inspect(bind).get_table_names():
        return
    child_table = sa.table(child, sa.column("id", sa.String()), sa.column("project_id", sa.String()), sa.column(child_fk, sa.String()))
    parent_table = sa.table(parent, sa.column("id", sa.String()), sa.column("project_id", sa.String()))
    parents = {row.id: row.project_id for row in bind.execute(sa.select(parent_table.c.id, parent_table.c.project_id))}
    for row in bind.execute(sa.select(child_table.c.id, getattr(child_table.c, child_fk))):
        parent_id = getattr(row, child_fk)
        if parent_id in parents:
            bind.execute(child_table.update().where(child_table.c.id == row.id).values(project_id=parents[parent_id]))


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

    if "ops_events" in existing:
        events = sa.table("ops_events", sa.column("id", sa.String()), sa.column("project_id", sa.String()), sa.column("payload", sa.JSON()))
        for row in bind.execute(sa.select(events.c.id, events.c.payload)):
            project_id = str(_json(row.payload).get("project_id") or "default")
            bind.execute(events.update().where(events.c.id == row.id).values(project_id=project_id))

    _copy_parent_project(bind, "ops_alert_events", "ops_events", "event_id")
    _copy_parent_project(bind, "ops_runbook_executions", "ops_runbooks", "runbook_id")
    for child in ("investigation_evidence", "investigation_hypotheses", "investigation_findings", "investigation_reports"):
        _copy_parent_project(bind, child, "investigation_workspaces", "investigation_id")
    _copy_parent_project(bind, "builds", "schedules", "schedule_id")
    _copy_parent_project(bind, "wh_executions", "wh_webhooks", "webhook_id")
    _copy_parent_project(bind, "wh_listener_events", "wh_listeners", "listener_id")


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

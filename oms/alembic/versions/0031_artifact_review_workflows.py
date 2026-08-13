"""Add durable artifact comments and reviewed change proposals.

Revision ID: 0031_artifact_review_workflows
Revises: 0030_durable_stream_processing
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision = "0031_artifact_review_workflows"
down_revision = "0030_durable_stream_processing"
branch_labels = None
depends_on = None


def _tables(bind) -> set[str]:
    return set(sa.inspect(bind).get_table_names())


def _indexes(bind, table_name: str) -> set[str]:
    return {row["name"] for row in sa.inspect(bind).get_indexes(table_name)}


def _index(table_name: str, name: str, columns: list[str]) -> None:
    if name not in _indexes(op.get_bind(), table_name):
        op.create_index(name, table_name, columns)


def upgrade() -> None:
    bind = op.get_bind()
    tables = _tables(bind)
    json_type = postgresql.JSONB() if bind.dialect.name == "postgresql" else sa.JSON()
    if "platform_artifact_review_comments" not in tables:
        op.create_table(
            "platform_artifact_review_comments",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("artifact_id", sa.String(), nullable=False),
            sa.Column("project_id", sa.String(), nullable=False),
            sa.Column("revision", sa.Integer(), nullable=False),
            sa.Column("target", sa.String(), nullable=False),
            sa.Column("thread_id", sa.String(), nullable=False),
            sa.Column("parent_id", sa.String(), nullable=True),
            sa.Column("body", sa.String(), nullable=False),
            sa.Column("status", sa.String(), nullable=False, server_default="OPEN"),
            sa.Column("author", sa.String(), nullable=False),
            sa.Column("resolved_by", sa.String(), nullable=True),
            sa.Column("resolved_at", sa.Integer(), nullable=True),
            sa.Column("created_at", sa.Integer(), nullable=False),
            sa.Column("updated_at", sa.Integer(), nullable=False),
        )
    if "platform_artifact_change_proposals" not in tables:
        op.create_table(
            "platform_artifact_change_proposals",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("artifact_id", sa.String(), nullable=False),
            sa.Column("project_id", sa.String(), nullable=False),
            sa.Column("base_revision", sa.Integer(), nullable=False),
            sa.Column("base_lock_version", sa.Integer(), nullable=False),
            sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("title", sa.String(), nullable=False),
            sa.Column("description", sa.String(), nullable=True),
            sa.Column("commands", json_type, nullable=False),
            sa.Column("targets", json_type, nullable=False),
            sa.Column("validation", json_type, nullable=False),
            sa.Column("status", sa.String(), nullable=False, server_default="OPEN"),
            sa.Column("author", sa.String(), nullable=False),
            sa.Column("reviewer", sa.String(), nullable=True),
            sa.Column("review_note", sa.String(), nullable=True),
            sa.Column("applied_revision", sa.Integer(), nullable=True),
            sa.Column("created_at", sa.Integer(), nullable=False),
            sa.Column("updated_at", sa.Integer(), nullable=False),
            sa.Column("reviewed_at", sa.Integer(), nullable=True),
            sa.Column("applied_at", sa.Integer(), nullable=True),
        )
    for table_name, columns in {
        "platform_artifact_review_comments": (
            "artifact_id", "project_id", "revision", "target", "thread_id", "parent_id",
            "status", "author", "created_at",
        ),
        "platform_artifact_change_proposals": (
            "artifact_id", "project_id", "base_lock_version", "status", "author", "reviewer",
            "created_at",
        ),
    }.items():
        for column in columns:
            _index(table_name, f"ix_{table_name}_{column}", [column])
    _index(
        "platform_artifact_review_comments", "ix_artifact_comments_thread_order",
        ["artifact_id", "thread_id", "created_at"],
    )
    _index(
        "platform_artifact_change_proposals", "ix_artifact_proposals_review_queue",
        ["project_id", "status", "updated_at"],
    )


def downgrade() -> None:
    tables = _tables(op.get_bind())
    for table_name in (
        "platform_artifact_change_proposals", "platform_artifact_review_comments",
    ):
        if table_name in tables:
            op.drop_table(table_name)

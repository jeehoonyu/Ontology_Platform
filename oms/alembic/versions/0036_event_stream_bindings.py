"""Add durable event-to-stream bindings and delivery receipts.

Revision ID: 0036_event_stream_bindings
Revises: 0035_object_materialization
"""

import sqlalchemy as sa
from alembic import op


revision = "0036_event_stream_bindings"
down_revision = "0035_object_materialization"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())
    if "event_stream_bindings" not in tables:
        op.create_table(
            "event_stream_bindings",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("project_id", sa.String(), nullable=False),
            sa.Column("display_name", sa.String(), nullable=False),
            sa.Column("target_stream_id", sa.String(), nullable=False),
            sa.Column("topics", sa.JSON(), nullable=False),
            sa.Column("event_types", sa.JSON(), nullable=False),
            sa.Column("aggregate_types", sa.JSON(), nullable=False),
            sa.Column("object_type_ids", sa.JSON(), nullable=False),
            sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("cursor_sequence", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("created_by", sa.String(), nullable=False),
            sa.Column("created_at", sa.Integer(), nullable=False),
            sa.Column("updated_at", sa.Integer(), nullable=False),
            sa.ForeignKeyConstraint(["target_stream_id"], ["streams.id"]),
            sa.UniqueConstraint("project_id", "display_name", name="uq_event_stream_binding_project_name"),
        )
        op.create_index("ix_event_stream_bindings_project_id", "event_stream_bindings", ["project_id"])
        op.create_index("ix_event_stream_bindings_target_stream_id", "event_stream_bindings", ["target_stream_id"])
    tables = set(sa.inspect(bind).get_table_names())
    if "event_stream_receipts" not in tables:
        op.create_table(
            "event_stream_receipts",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("project_id", sa.String(), nullable=False),
            sa.Column("binding_id", sa.String(), nullable=False),
            sa.Column("event_id", sa.String(), nullable=False),
            sa.Column("event_sequence", sa.Integer(), nullable=False),
            sa.Column("stream_record_id", sa.String(), nullable=False),
            sa.Column("created_at", sa.Integer(), nullable=False),
            sa.ForeignKeyConstraint(["binding_id"], ["event_stream_bindings.id"]),
            sa.UniqueConstraint("binding_id", "event_id", name="uq_event_stream_binding_event"),
            sa.UniqueConstraint("stream_record_id", name="uq_event_stream_record_id"),
        )
        op.create_index("ix_event_stream_receipts_project_id", "event_stream_receipts", ["project_id"])
        op.create_index("ix_event_stream_receipts_binding_id", "event_stream_receipts", ["binding_id"])
        op.create_index("ix_event_stream_receipts_event_id", "event_stream_receipts", ["event_id"])
        op.create_index("ix_event_stream_receipts_event_sequence", "event_stream_receipts", ["event_sequence"])


def downgrade() -> None:
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())
    if "event_stream_receipts" in tables:
        op.drop_table("event_stream_receipts")
    tables = set(sa.inspect(bind).get_table_names())
    if "event_stream_bindings" in tables:
        op.drop_table("event_stream_bindings")

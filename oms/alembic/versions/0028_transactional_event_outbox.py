"""Add transactional event outbox and durable platform event log.

Revision ID: 0028_transactional_event_outbox
Revises: 0027_ontology_query_indexes
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision = "0028_transactional_event_outbox"
down_revision = "0027_ontology_query_indexes"
branch_labels = None
depends_on = None


def _tables(bind) -> set[str]:
    return set(sa.inspect(bind).get_table_names())


def _indexes(bind, table_name: str) -> set[str]:
    return {row["name"] for row in sa.inspect(bind).get_indexes(table_name)}


def _json_type(bind):
    return postgresql.JSONB() if bind.dialect.name == "postgresql" else sa.JSON()


def upgrade() -> None:
    bind = op.get_bind()
    existing = _tables(bind)
    json_type = _json_type(bind)

    if "event_outbox" not in existing:
        op.create_table(
            "event_outbox",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("project_id", sa.String(), nullable=False),
            sa.Column("topic", sa.String(), nullable=False),
            sa.Column("event_type", sa.String(), nullable=False),
            sa.Column("aggregate_type", sa.String(), nullable=False),
            sa.Column("aggregate_id", sa.String(), nullable=False),
            sa.Column("actor", sa.String(), nullable=False),
            sa.Column("payload", json_type, nullable=False),
            sa.Column("headers", json_type, nullable=False),
            sa.Column("idempotency_key", sa.String(), nullable=False),
            sa.Column("status", sa.String(), nullable=False, server_default="PENDING"),
            sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="5"),
            sa.Column("available_at", sa.Integer(), nullable=False),
            sa.Column("lease_owner", sa.String(), nullable=True),
            sa.Column("lease_token", sa.String(), nullable=True, unique=True),
            sa.Column("lease_expires_at", sa.Integer(), nullable=True),
            sa.Column("last_error", sa.String(), nullable=True),
            sa.Column("created_at", sa.Integer(), nullable=False),
            sa.Column("updated_at", sa.Integer(), nullable=False),
            sa.Column("published_at", sa.Integer(), nullable=True),
            sa.UniqueConstraint("project_id", "idempotency_key", name="uq_event_outbox_project_idempotency"),
        )
        for column in (
            "project_id", "topic", "event_type", "aggregate_type", "aggregate_id",
            "status", "available_at", "lease_owner", "lease_expires_at", "created_at",
        ):
            op.create_index(f"ix_event_outbox_{column}", "event_outbox", [column])
        bind.exec_driver_sql(
            "CREATE INDEX ix_event_outbox_claim ON event_outbox "
            "(status, available_at, lease_expires_at, created_at, id)"
        )

    if "event_outbox" in _tables(bind):
        indexes = _indexes(bind, "event_outbox")
        for name, columns in (
            ("ix_event_outbox_project_id", ["project_id"]),
            ("ix_event_outbox_topic", ["topic"]),
            ("ix_event_outbox_event_type", ["event_type"]),
            ("ix_event_outbox_aggregate_type", ["aggregate_type"]),
            ("ix_event_outbox_aggregate_id", ["aggregate_id"]),
            ("ix_event_outbox_status", ["status"]),
            ("ix_event_outbox_available_at", ["available_at"]),
            ("ix_event_outbox_lease_owner", ["lease_owner"]),
            ("ix_event_outbox_lease_expires_at", ["lease_expires_at"]),
            ("ix_event_outbox_created_at", ["created_at"]),
            ("ix_event_outbox_claim", ["status", "available_at", "lease_expires_at", "created_at", "id"]),
        ):
            if name not in indexes:
                op.create_index(name, "event_outbox", columns)

    if "platform_event_log" not in existing:
        op.create_table(
            "platform_event_log",
            sa.Column("sequence", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("event_id", sa.String(), nullable=False, unique=True),
            sa.Column("outbox_event_id", sa.String(), nullable=False),
            sa.Column("project_id", sa.String(), nullable=False),
            sa.Column("topic", sa.String(), nullable=False),
            sa.Column("event_type", sa.String(), nullable=False),
            sa.Column("aggregate_type", sa.String(), nullable=False),
            sa.Column("aggregate_id", sa.String(), nullable=False),
            sa.Column("actor", sa.String(), nullable=False),
            sa.Column("payload", json_type, nullable=False),
            sa.Column("headers", json_type, nullable=False),
            sa.Column("occurred_at", sa.Integer(), nullable=False),
            sa.Column("published_at", sa.Integer(), nullable=False),
            sa.UniqueConstraint("outbox_event_id", name="uq_platform_event_log_outbox_event"),
        )
        for column in (
            "project_id", "topic", "event_type", "aggregate_type", "aggregate_id",
            "occurred_at", "published_at",
        ):
            op.create_index(f"ix_platform_event_log_{column}", "platform_event_log", [column])
        bind.exec_driver_sql(
            "CREATE INDEX ix_platform_event_log_project_sequence ON platform_event_log "
            "(project_id, sequence)"
        )

    if "platform_event_log" in _tables(bind):
        indexes = _indexes(bind, "platform_event_log")
        for name, columns in (
            ("ix_platform_event_log_project_id", ["project_id"]),
            ("ix_platform_event_log_topic", ["topic"]),
            ("ix_platform_event_log_event_type", ["event_type"]),
            ("ix_platform_event_log_aggregate_type", ["aggregate_type"]),
            ("ix_platform_event_log_aggregate_id", ["aggregate_id"]),
            ("ix_platform_event_log_occurred_at", ["occurred_at"]),
            ("ix_platform_event_log_published_at", ["published_at"]),
            ("ix_platform_event_log_project_sequence", ["project_id", "sequence"]),
        ):
            if name not in indexes:
                op.create_index(name, "platform_event_log", columns)


def downgrade() -> None:
    existing = _tables(op.get_bind())
    if "platform_event_log" in existing:
        op.drop_table("platform_event_log")
    if "event_outbox" in existing:
        op.drop_table("event_outbox")

"""Add durable cross-transport event delivery receipts.

Revision ID: 0029_event_transport_receipts
Revises: 0028_transactional_event_outbox
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision = "0029_event_transport_receipts"
down_revision = "0028_transactional_event_outbox"
branch_labels = None
depends_on = None


def _tables(bind) -> set[str]:
    return set(sa.inspect(bind).get_table_names())


def _indexes(bind, table_name: str) -> set[str]:
    return {row["name"] for row in sa.inspect(bind).get_indexes(table_name)}


def upgrade() -> None:
    bind = op.get_bind()
    if "event_transport_receipts" not in _tables(bind):
        json_type = postgresql.JSONB() if bind.dialect.name == "postgresql" else sa.JSON()
        op.create_table(
            "event_transport_receipts",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("outbox_event_id", sa.String(), nullable=False),
            sa.Column("project_id", sa.String(), nullable=False),
            sa.Column("transport", sa.String(), nullable=False),
            sa.Column("destination", sa.String(), nullable=False),
            sa.Column("status", sa.String(), nullable=False, server_default="PENDING"),
            sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="5"),
            sa.Column("available_at", sa.Integer(), nullable=False),
            sa.Column("lease_owner", sa.String(), nullable=True),
            sa.Column("lease_token", sa.String(), nullable=True, unique=True),
            sa.Column("lease_expires_at", sa.Integer(), nullable=True),
            sa.Column("broker_metadata", json_type, nullable=False),
            sa.Column("last_error", sa.String(), nullable=True),
            sa.Column("created_at", sa.Integer(), nullable=False),
            sa.Column("updated_at", sa.Integer(), nullable=False),
            sa.Column("delivered_at", sa.Integer(), nullable=True),
            sa.UniqueConstraint(
                "outbox_event_id", "transport", "destination",
                name="uq_event_transport_destination",
            ),
        )

    indexes = _indexes(bind, "event_transport_receipts")
    for name, columns in (
        ("ix_event_transport_receipts_outbox_event_id", ["outbox_event_id"]),
        ("ix_event_transport_receipts_project_id", ["project_id"]),
        ("ix_event_transport_receipts_transport", ["transport"]),
        ("ix_event_transport_receipts_destination", ["destination"]),
        ("ix_event_transport_receipts_status", ["status"]),
        ("ix_event_transport_receipts_available_at", ["available_at"]),
        ("ix_event_transport_receipts_lease_owner", ["lease_owner"]),
        ("ix_event_transport_receipts_lease_expires_at", ["lease_expires_at"]),
        ("ix_event_transport_receipts_created_at", ["created_at"]),
        (
            "ix_event_transport_receipts_claim",
            ["transport", "status", "available_at", "lease_expires_at", "created_at", "id"],
        ),
    ):
        if name not in indexes:
            op.create_index(name, "event_transport_receipts", columns)


def downgrade() -> None:
    if "event_transport_receipts" in _tables(op.get_bind()):
        op.drop_table("event_transport_receipts")

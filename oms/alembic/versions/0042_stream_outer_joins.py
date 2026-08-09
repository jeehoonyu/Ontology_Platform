"""Add watermark-finalized outer interval join evidence.

Revision ID: 0042_stream_outer_joins
Revises: 0041_drop_redundant_pk_indexes
"""

import sqlalchemy as sa
from alembic import op


revision = "0042_stream_outer_joins"
down_revision = "0041_drop_redundant_pk_indexes"
branch_labels = None
depends_on = None


def _tables(bind) -> set[str]:
    return set(sa.inspect(bind).get_table_names())


def _columns(bind, table_name: str) -> set[str]:
    return {row["name"] for row in sa.inspect(bind).get_columns(table_name)}


def _indexes(bind, table_name: str) -> set[str]:
    inspector = sa.inspect(bind)
    names = {row["name"] for row in inspector.get_indexes(table_name)}
    names.update(row["name"] for row in inspector.get_unique_constraints(table_name) if row.get("name"))
    return names


def _index(table_name: str, name: str, columns: list[str], *, unique: bool = False) -> None:
    if name not in _indexes(op.get_bind(), table_name):
        op.create_index(name, table_name, columns, unique=unique)


def upgrade() -> None:
    bind = op.get_bind()
    tables = _tables(bind)
    if "stream_processors" in tables and "join_type" not in _columns(bind, "stream_processors"):
        with op.batch_alter_table("stream_processors") as batch:
            batch.add_column(sa.Column("join_type", sa.String(), nullable=False, server_default="inner"))
    if "stream_processing_runs" in tables and "outer_joins_emitted" not in _columns(bind, "stream_processing_runs"):
        with op.batch_alter_table("stream_processing_runs") as batch:
            batch.add_column(sa.Column("outer_joins_emitted", sa.Integer(), nullable=False, server_default="0"))

    if "stream_join_outer_receipts" not in tables:
        op.create_table(
            "stream_join_outer_receipts",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("processor_id", sa.String(), nullable=False),
            sa.Column("project_id", sa.String(), nullable=False),
            sa.Column("record_id", sa.String(), nullable=False),
            sa.Column("side", sa.String(), nullable=False),
            sa.Column("output_record_id", sa.String(), nullable=False),
            sa.Column("join_key", sa.String(), nullable=False),
            sa.Column("event_time", sa.Float(), nullable=False),
            sa.Column("opposite_watermark", sa.Float(), nullable=False),
            sa.Column("run_id", sa.String(), nullable=False),
            sa.Column("created_at", sa.Integer(), nullable=False),
            sa.UniqueConstraint("processor_id", "record_id", name="uq_stream_join_outer_input"),
            sa.UniqueConstraint("output_record_id", name="uq_stream_join_outer_output"),
        )
    for column in ("processor_id", "project_id", "record_id", "side", "join_key", "run_id"):
        _index("stream_join_outer_receipts", f"ix_stream_join_outer_receipts_{column}", [column])
    _index(
        "stream_join_outer_receipts", "ix_stream_join_outer_receipts_finalized",
        ["processor_id", "side", "join_key", "event_time"],
    )


def downgrade() -> None:
    bind = op.get_bind()
    tables = _tables(bind)
    if "stream_join_outer_receipts" in tables:
        op.drop_table("stream_join_outer_receipts")
    if "stream_processing_runs" in tables and "outer_joins_emitted" in _columns(bind, "stream_processing_runs"):
        with op.batch_alter_table("stream_processing_runs") as batch:
            batch.drop_column("outer_joins_emitted")
    if "stream_processors" in tables and "join_type" in _columns(bind, "stream_processors"):
        with op.batch_alter_table("stream_processors") as batch:
            batch.drop_column("join_type")

"""Add durable two-stream interval join state and exact pair receipts.

Revision ID: 0037_cross_stream_joins
Revises: 0036_event_stream_bindings
"""

import sqlalchemy as sa
from alembic import op


revision = "0037_cross_stream_joins"
down_revision = "0036_event_stream_bindings"
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
    if "stream_processors" in tables:
        columns = _columns(bind, "stream_processors")
        additions = (
            ("join_stream_id", sa.String(), True),
            ("join_left_key", sa.String(), True),
            ("join_right_key", sa.String(), True),
            ("join_time_tolerance_seconds", sa.Integer(), True),
        )
        with op.batch_alter_table("stream_processors") as batch:
            for name, column_type, nullable in additions:
                if name not in columns:
                    batch.add_column(sa.Column(name, column_type, nullable=nullable))
        _index("stream_processors", "ix_stream_processors_join_stream_id", ["join_stream_id"])
    if "stream_processing_runs" in tables and "joins_emitted" not in _columns(bind, "stream_processing_runs"):
        with op.batch_alter_table("stream_processing_runs") as batch:
            batch.add_column(sa.Column("joins_emitted", sa.Integer(), nullable=False, server_default="0"))

    tables = _tables(bind)
    if "stream_join_inputs" not in tables:
        op.create_table(
            "stream_join_inputs",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("processor_id", sa.String(), nullable=False),
            sa.Column("project_id", sa.String(), nullable=False),
            sa.Column("record_id", sa.String(), nullable=False),
            sa.Column("stream_id", sa.String(), nullable=False),
            sa.Column("side", sa.String(), nullable=False),
            sa.Column("join_key", sa.String(), nullable=False),
            sa.Column("event_time", sa.Float(), nullable=False),
            sa.Column("created_at", sa.Integer(), nullable=False),
            sa.UniqueConstraint("processor_id", "record_id", name="uq_stream_join_input_record"),
        )
    if "stream_join_receipts" not in tables:
        op.create_table(
            "stream_join_receipts",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("processor_id", sa.String(), nullable=False),
            sa.Column("project_id", sa.String(), nullable=False),
            sa.Column("left_record_id", sa.String(), nullable=False),
            sa.Column("right_record_id", sa.String(), nullable=False),
            sa.Column("output_record_id", sa.String(), nullable=False),
            sa.Column("join_key", sa.String(), nullable=False),
            sa.Column("left_event_time", sa.Float(), nullable=False),
            sa.Column("right_event_time", sa.Float(), nullable=False),
            sa.Column("run_id", sa.String(), nullable=False),
            sa.Column("created_at", sa.Integer(), nullable=False),
            sa.UniqueConstraint(
                "processor_id", "left_record_id", "right_record_id",
                name="uq_stream_join_pair",
            ),
            sa.UniqueConstraint("output_record_id", name="uq_stream_join_output"),
        )

    for table_name, columns in {
        "stream_join_inputs": (
            "processor_id", "project_id", "record_id", "stream_id", "join_key", "event_time",
        ),
        "stream_join_receipts": (
            "processor_id", "project_id", "left_record_id", "right_record_id", "join_key", "run_id",
        ),
    }.items():
        for column in columns:
            _index(table_name, f"ix_{table_name}_{column}", [column])
    _index(
        "stream_join_inputs", "ix_stream_join_inputs_match",
        ["processor_id", "side", "join_key", "event_time"],
    )


def downgrade() -> None:
    bind = op.get_bind()
    tables = _tables(bind)
    for table_name in ("stream_join_receipts", "stream_join_inputs"):
        if table_name in tables:
            op.drop_table(table_name)
    if "stream_processing_runs" in tables and "joins_emitted" in _columns(bind, "stream_processing_runs"):
        with op.batch_alter_table("stream_processing_runs") as batch:
            batch.drop_column("joins_emitted")
    if "stream_processors" in tables:
        columns = _columns(bind, "stream_processors")
        if "ix_stream_processors_join_stream_id" in _indexes(bind, "stream_processors"):
            op.drop_index("ix_stream_processors_join_stream_id", table_name="stream_processors")
        with op.batch_alter_table("stream_processors") as batch:
            for name in (
                "join_time_tolerance_seconds", "join_right_key", "join_left_key", "join_stream_id",
            ):
                if name in columns:
                    batch.drop_column(name)

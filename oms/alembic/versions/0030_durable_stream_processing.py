"""Add durable event-time stream processing state and evidence.

Revision ID: 0030_durable_stream_processing
Revises: 0029_event_transport_receipts
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision = "0030_durable_stream_processing"
down_revision = "0029_event_transport_receipts"
branch_labels = None
depends_on = None


def _tables(bind) -> set[str]:
    return set(sa.inspect(bind).get_table_names())


def _indexes(bind, table_name: str) -> set[str]:
    inspector = sa.inspect(bind)
    names = {row["name"] for row in inspector.get_indexes(table_name)}
    names.update(row["name"] for row in inspector.get_unique_constraints(table_name) if row.get("name"))
    return names


def _columns(bind, table_name: str) -> set[str]:
    return {row["name"] for row in sa.inspect(bind).get_columns(table_name)}


def _index(table: str, name: str, columns: list[str]) -> None:
    if name not in _indexes(op.get_bind(), table):
        op.create_index(name, table, columns)


def upgrade() -> None:
    bind = op.get_bind()
    existing = _tables(bind)
    json_type = postgresql.JSONB() if bind.dialect.name == "postgresql" else sa.JSON()
    if "streams" in existing and "next_sequence" not in _columns(bind, "streams"):
        op.add_column("streams", sa.Column("next_sequence", sa.Integer(), nullable=False, server_default="0"))
    if "stream_records" in existing and "sequence" not in _columns(bind, "stream_records"):
        op.add_column("stream_records", sa.Column("sequence", sa.Integer(), nullable=True))
    if "stream_records" in existing:
        op.execute(sa.text("""
            WITH ranked AS (
                SELECT id, ROW_NUMBER() OVER (
                    PARTITION BY stream_id ORDER BY created_at, ts, id
                ) AS arrival_sequence
                FROM stream_records
            )
            UPDATE stream_records
            SET sequence = (
                SELECT arrival_sequence FROM ranked WHERE ranked.id = stream_records.id
            )
            WHERE sequence IS NULL
        """))
        op.execute(sa.text("""
            UPDATE streams
            SET next_sequence = COALESCE((
                SELECT MAX(sequence) FROM stream_records
                WHERE stream_records.stream_id = streams.id
            ), 0)
        """))
        with op.batch_alter_table("stream_records") as batch:
            batch.alter_column("sequence", existing_type=sa.Integer(), nullable=False)
        _index("stream_records", "ix_stream_records_sequence", ["sequence"])
        if "uq_stream_record_sequence" not in _indexes(bind, "stream_records"):
            op.create_index(
                "uq_stream_record_sequence", "stream_records", ["stream_id", "sequence"], unique=True,
            )
    if "stream_processors" not in existing:
        op.create_table(
            "stream_processors",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("project_id", sa.String(), nullable=False),
            sa.Column("stream_id", sa.String(), nullable=False),
            sa.Column("display_name", sa.String(), nullable=False),
            sa.Column("timestamp_field", sa.String(), nullable=True),
            sa.Column("partition_key_field", sa.String(), nullable=True),
            sa.Column("allowed_lateness_seconds", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("late_policy", sa.String(), nullable=False, server_default="quarantine"),
            sa.Column("window_size_seconds", sa.Integer(), nullable=True),
            sa.Column("value_field", sa.String(), nullable=True),
            sa.Column("aggregation", sa.String(), nullable=False, server_default="count"),
            sa.Column("target_asset_id", sa.String(), nullable=True),
            sa.Column("max_batch_records", sa.Integer(), nullable=False, server_default="1000"),
            sa.Column("max_backlog_records", sa.Integer(), nullable=False, server_default="10000"),
            sa.Column("backpressure_mode", sa.String(), nullable=False, server_default="reject"),
            sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("created_by", sa.String(), nullable=False),
            sa.Column("created_at", sa.Integer(), nullable=False),
            sa.Column("updated_at", sa.Integer(), nullable=False),
        )
    if "stream_partition_states" not in existing:
        op.create_table(
            "stream_partition_states",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("processor_id", sa.String(), nullable=False),
            sa.Column("project_id", sa.String(), nullable=False),
            sa.Column("partition_key", sa.String(), nullable=False),
            sa.Column("max_event_time", sa.Float(), nullable=True),
            sa.Column("watermark", sa.Float(), nullable=True),
            sa.Column("processed_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("late_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("quarantined_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("updated_at", sa.Integer(), nullable=False),
            sa.UniqueConstraint("processor_id", "partition_key", name="uq_stream_processor_partition"),
        )
    if "stream_window_states" not in existing:
        op.create_table(
            "stream_window_states",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("processor_id", sa.String(), nullable=False),
            sa.Column("project_id", sa.String(), nullable=False),
            sa.Column("partition_key", sa.String(), nullable=False),
            sa.Column("window_start", sa.Float(), nullable=False),
            sa.Column("window_end", sa.Float(), nullable=False),
            sa.Column("count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("numeric_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("value_sum", sa.Float(), nullable=False, server_default="0"),
            sa.Column("value_min", sa.Float(), nullable=True),
            sa.Column("value_max", sa.Float(), nullable=True),
            sa.Column("status", sa.String(), nullable=False, server_default="OPEN"),
            sa.Column("emitted_at", sa.Integer(), nullable=True),
            sa.Column("updated_at", sa.Integer(), nullable=False),
            sa.UniqueConstraint("processor_id", "partition_key", "window_start", name="uq_stream_processor_window"),
        )
    if "stream_processing_receipts" not in existing:
        op.create_table(
            "stream_processing_receipts",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("processor_id", sa.String(), nullable=False),
            sa.Column("project_id", sa.String(), nullable=False),
            sa.Column("record_id", sa.String(), nullable=False),
            sa.Column("partition_key", sa.String(), nullable=False),
            sa.Column("event_time", sa.Float(), nullable=True),
            sa.Column("status", sa.String(), nullable=False),
            sa.Column("reason", sa.String(), nullable=True),
            sa.Column("run_id", sa.String(), nullable=False),
            sa.Column("created_at", sa.Integer(), nullable=False),
            sa.UniqueConstraint("processor_id", "record_id", name="uq_stream_processor_record"),
        )
    if "stream_quarantine_records" not in existing:
        op.create_table(
            "stream_quarantine_records",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("processor_id", sa.String(), nullable=False),
            sa.Column("project_id", sa.String(), nullable=False),
            sa.Column("record_id", sa.String(), nullable=False),
            sa.Column("partition_key", sa.String(), nullable=False),
            sa.Column("event_time", sa.Float(), nullable=True),
            sa.Column("watermark", sa.Float(), nullable=True),
            sa.Column("reason", sa.String(), nullable=False),
            sa.Column("payload", json_type, nullable=False),
            sa.Column("status", sa.String(), nullable=False, server_default="PENDING"),
            sa.Column("created_at", sa.Integer(), nullable=False),
            sa.Column("resolved_at", sa.Integer(), nullable=True),
            sa.UniqueConstraint("processor_id", "record_id", name="uq_stream_quarantine_record"),
        )
    if "stream_processing_runs" not in existing:
        op.create_table(
            "stream_processing_runs",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("processor_id", sa.String(), nullable=False),
            sa.Column("project_id", sa.String(), nullable=False),
            sa.Column("job_id", sa.String(), nullable=True),
            sa.Column("status", sa.String(), nullable=False),
            sa.Column("backlog_before", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("backlog_after", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("records_processed", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("records_late", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("records_quarantined", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("windows_emitted", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("metrics", json_type, nullable=False),
            sa.Column("error", sa.String(), nullable=True),
            sa.Column("created_at", sa.Integer(), nullable=False),
            sa.Column("completed_at", sa.Integer(), nullable=True),
        )

    for table, columns in {
        "stream_processors": ("project_id", "stream_id"),
        "stream_partition_states": ("processor_id", "project_id"),
        "stream_window_states": ("processor_id", "project_id", "status"),
        "stream_processing_receipts": ("processor_id", "project_id", "record_id", "status", "run_id"),
        "stream_quarantine_records": ("processor_id", "project_id", "record_id", "status"),
        "stream_processing_runs": ("processor_id", "project_id", "job_id", "status"),
    }.items():
        for column in columns:
            _index(table, f"ix_{table}_{column}", [column])
    _index(
        "stream_processing_receipts", "ix_stream_processing_receipts_processor_record",
        ["processor_id", "record_id"],
    )
    _index(
        "stream_window_states", "ix_stream_window_states_close",
        ["processor_id", "partition_key", "status", "window_end"],
    )


def downgrade() -> None:
    existing = _tables(op.get_bind())
    for table in (
        "stream_processing_runs", "stream_quarantine_records", "stream_processing_receipts",
        "stream_window_states", "stream_partition_states", "stream_processors",
    ):
        if table in existing:
            op.drop_table(table)
    if "stream_records" in existing and "sequence" in _columns(op.get_bind(), "stream_records"):
        indexes = _indexes(op.get_bind(), "stream_records")
        if "uq_stream_record_sequence" in indexes:
            op.drop_index("uq_stream_record_sequence", table_name="stream_records")
        if "ix_stream_records_sequence" in indexes:
            op.drop_index("ix_stream_records_sequence", table_name="stream_records")
        op.drop_column("stream_records", "sequence")
    if "streams" in existing and "next_sequence" in _columns(op.get_bind(), "streams"):
        op.drop_column("streams", "next_sequence")

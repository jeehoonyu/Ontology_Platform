"""Verify legacy stream rows gain deterministic arrival sequences at revision 0030."""

import os
import tempfile

from sqlalchemy import create_engine, inspect, text


tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
database_path = os.path.join(tmpdir.name, "durable_stream_processing.db")
os.environ["DATABASE_URL"] = f"sqlite:///{database_path}"
os.environ["SKIP_CREATE_ALL"] = "1"

from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402


config = Config(os.path.join(os.path.dirname(__file__), "alembic.ini"))
config.set_main_option("sqlalchemy.url", os.environ["DATABASE_URL"])
command.upgrade(config, "0029_event_transport_receipts")

# The runtime baseline reflects current metadata. Remove the new fields to
# reproduce a database created by the previous release before upgrading it.
engine = create_engine(os.environ["DATABASE_URL"])
with engine.begin() as connection:
    connection.execute(text("DROP INDEX IF EXISTS ix_stream_records_sequence"))
    connection.execute(text("ALTER TABLE stream_records DROP COLUMN sequence"))
    connection.execute(text("ALTER TABLE streams DROP COLUMN next_sequence"))
    connection.execute(text("""
        INSERT INTO streams (
            id, project_id, display_name, schema, retention_seconds,
            archive_policy, created_at
        ) VALUES ('legacy-stream', 'default', 'Legacy', '{}', 86400, '{}', 10)
    """))
    connection.execute(text("""
        INSERT INTO stream_records (
            id, stream_id, payload, ts, archived, archived_at, created_at
        ) VALUES
            ('record-b', 'legacy-stream', '{}', 101, 0, NULL, 10),
            ('record-a', 'legacy-stream', '{}', 100, 0, NULL, 10),
            ('record-c', 'legacy-stream', '{}', 102, 0, NULL, 11)
    """))
engine.dispose()

command.upgrade(config, "0030_durable_stream_processing")
command.upgrade(config, "0030_durable_stream_processing")

engine = create_engine(os.environ["DATABASE_URL"])
with engine.connect() as connection:
    assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == "0030_durable_stream_processing"
    inspector = inspect(connection)
    tables = set(inspector.get_table_names())
    assert {
        "stream_processors", "stream_partition_states", "stream_window_states",
        "stream_processing_receipts", "stream_quarantine_records", "stream_processing_runs",
    } <= tables
    assert "next_sequence" in {row["name"] for row in inspector.get_columns("streams")}
    record_columns = {row["name"]: row for row in inspector.get_columns("stream_records")}
    assert "sequence" in record_columns and record_columns["sequence"]["nullable"] is False
    rows = connection.execute(text("""
        SELECT id, sequence FROM stream_records
        WHERE stream_id = 'legacy-stream' ORDER BY sequence
    """)).all()
    assert rows == [("record-a", 1), ("record-b", 2), ("record-c", 3)], rows
    assert connection.execute(text("SELECT next_sequence FROM streams WHERE id = 'legacy-stream'")).scalar_one() == 3
    indexes = {row["name"]: row for row in inspector.get_indexes("stream_records")}
    assert indexes["uq_stream_record_sequence"]["unique"] == 1

engine.dispose()
tmpdir.cleanup()
print("Durable stream-processing migration verified.")

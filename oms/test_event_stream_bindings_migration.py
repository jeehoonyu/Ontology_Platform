"""Event-to-stream binding migration upgrades and rolls back cleanly."""
import os
import subprocess
import sys
import tempfile

from sqlalchemy import create_engine, inspect, text


with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temporary:
    database_url = f"sqlite:///{os.path.join(temporary, 'event-stream-migration.db')}"
    env = {**os.environ, "DATABASE_URL": database_url, "APP_ENV": "test", "AUTH_MODE": "local"}

    def alembic(*args):
        completed = subprocess.run(
            [sys.executable, "-m", "alembic", "-c", "alembic.ini", *args],
            cwd=os.path.dirname(__file__), env=env, capture_output=True, text=True,
        )
        assert completed.returncode == 0, f"{completed.stdout}\n{completed.stderr}"

    alembic("upgrade", "0035_object_materialization")
    engine = create_engine(database_url)
    # The dynamic baseline uses current metadata for clean installs. Remove the
    # new tables to model an existing deployment that genuinely stopped at 0035.
    with engine.begin() as connection:
        connection.execute(text("DROP TABLE IF EXISTS event_stream_receipts"))
        connection.execute(text("DROP TABLE IF EXISTS event_stream_bindings"))
    with engine.connect() as connection:
        tables = set(inspect(connection).get_table_names())
        assert "event_stream_bindings" not in tables and "event_stream_receipts" not in tables

    alembic("upgrade", "head")
    with engine.connect() as connection:
        inspector = inspect(connection)
        tables = set(inspector.get_table_names())
        assert {"event_stream_bindings", "event_stream_receipts"} <= tables
        binding_columns = {column["name"] for column in inspector.get_columns("event_stream_bindings")}
        receipt_columns = {column["name"] for column in inspector.get_columns("event_stream_receipts")}
        assert {"project_id", "target_stream_id", "topics", "event_types", "cursor_sequence"} <= binding_columns
        assert {"binding_id", "event_id", "event_sequence", "stream_record_id"} <= receipt_columns
        assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == "0037_cross_stream_joins"

    alembic("downgrade", "0035_object_materialization")
    with engine.connect() as connection:
        tables = set(inspect(connection).get_table_names())
        assert "event_stream_bindings" not in tables and "event_stream_receipts" not in tables

    alembic("upgrade", "head")
    with engine.connect() as connection:
        assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == "0037_cross_stream_joins"
    engine.dispose()

print("Event-to-stream binding migration verified.")

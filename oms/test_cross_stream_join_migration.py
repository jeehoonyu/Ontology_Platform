"""Cross-stream join schema upgrades from 0036 and rolls back without ambiguity."""

import os
import subprocess
import sys
import tempfile

from sqlalchemy import create_engine, inspect, text


with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temporary:
    database_url = f"sqlite:///{os.path.join(temporary, 'cross-stream-join-migration.db')}"
    env = {**os.environ, "DATABASE_URL": database_url, "APP_ENV": "test", "AUTH_MODE": "local"}

    def alembic(*args):
        completed = subprocess.run(
            [sys.executable, "-m", "alembic", "-c", "alembic.ini", *args],
            cwd=os.path.dirname(__file__), env=env, capture_output=True, text=True,
        )
        assert completed.returncode == 0, f"{completed.stdout}\n{completed.stderr}"

    alembic("upgrade", "0036_event_stream_bindings")
    engine = create_engine(database_url)
    # Clean installs use current metadata in the baseline. Remove 0037 state to
    # reproduce an existing database that truly stopped at the prior revision.
    with engine.begin() as connection:
        connection.execute(text("DROP TABLE IF EXISTS stream_join_receipts"))
        connection.execute(text("DROP TABLE IF EXISTS stream_join_inputs"))
        indexes = {row["name"] for row in inspect(connection).get_indexes("stream_processors")}
        if "ix_stream_processors_join_stream_id" in indexes:
            connection.execute(text("DROP INDEX ix_stream_processors_join_stream_id"))
        processor_columns = {row["name"] for row in inspect(connection).get_columns("stream_processors")}
        for column in (
            "join_time_tolerance_seconds", "join_right_key", "join_left_key", "join_stream_id",
        ):
            if column in processor_columns:
                connection.execute(text(f"ALTER TABLE stream_processors DROP COLUMN {column}"))
        run_columns = {row["name"] for row in inspect(connection).get_columns("stream_processing_runs")}
        if "joins_emitted" in run_columns:
            connection.execute(text("ALTER TABLE stream_processing_runs DROP COLUMN joins_emitted"))

    alembic("upgrade", "head")
    with engine.connect() as connection:
        inspector = inspect(connection)
        assert {"stream_join_inputs", "stream_join_receipts"} <= set(inspector.get_table_names())
        assert {
            "join_stream_id", "join_left_key", "join_right_key", "join_time_tolerance_seconds",
        } <= {row["name"] for row in inspector.get_columns("stream_processors")}
        assert "joins_emitted" in {row["name"] for row in inspector.get_columns("stream_processing_runs")}
        indexes = {row["name"] for row in inspector.get_indexes("stream_join_inputs")}
        assert "ix_stream_join_inputs_match" in indexes
        assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == "0038_explicit_schema_baseline"

    alembic("downgrade", "0036_event_stream_bindings")
    with engine.connect() as connection:
        inspector = inspect(connection)
        assert "stream_join_inputs" not in inspector.get_table_names()
        assert "stream_join_receipts" not in inspector.get_table_names()
        assert "join_stream_id" not in {row["name"] for row in inspector.get_columns("stream_processors")}
        assert "joins_emitted" not in {row["name"] for row in inspector.get_columns("stream_processing_runs")}

    alembic("upgrade", "head")
    with engine.connect() as connection:
        assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == "0038_explicit_schema_baseline"
    engine.dispose()

print("Cross-stream join migration verified.")

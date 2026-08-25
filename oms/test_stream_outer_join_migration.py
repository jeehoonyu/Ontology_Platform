"""Outer interval join schema upgrades and downgrades from the prior head."""

import os
import subprocess
import sys
import tempfile

from sqlalchemy import create_engine, inspect, text
from tier_b_evidence import current_head


with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temporary:
    database_url = f"sqlite:///{os.path.join(temporary, 'outer-join-migration.db')}"
    env = {**os.environ, "DATABASE_URL": database_url, "APP_ENV": "test", "AUTH_MODE": "local"}

    def alembic(*args):
        completed = subprocess.run(
            [sys.executable, "-m", "alembic", "-c", "alembic.ini", *args],
            cwd=os.path.dirname(__file__), env=env, capture_output=True, text=True,
        )
        assert completed.returncode == 0, f"{completed.stdout}\n{completed.stderr}"

    alembic("upgrade", "0041_drop_redundant_pk_indexes")
    engine = create_engine(database_url)
    with engine.begin() as connection:
        connection.execute(text("DROP TABLE IF EXISTS stream_join_outer_receipts"))
        processor_columns = {row["name"] for row in inspect(connection).get_columns("stream_processors")}
        if "join_type" in processor_columns:
            connection.execute(text("ALTER TABLE stream_processors DROP COLUMN join_type"))
        run_columns = {row["name"] for row in inspect(connection).get_columns("stream_processing_runs")}
        if "outer_joins_emitted" in run_columns:
            connection.execute(text("ALTER TABLE stream_processing_runs DROP COLUMN outer_joins_emitted"))

    alembic("upgrade", "head")
    with engine.connect() as connection:
        inspector = inspect(connection)
        assert "stream_join_outer_receipts" in inspector.get_table_names()
        assert "join_type" in {row["name"] for row in inspector.get_columns("stream_processors")}
        assert "outer_joins_emitted" in {row["name"] for row in inspector.get_columns("stream_processing_runs")}
        indexes = {row["name"] for row in inspector.get_indexes("stream_join_outer_receipts")}
        assert "ix_stream_join_outer_receipts_finalized" in indexes
        assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == current_head()

    alembic("downgrade", "0041_drop_redundant_pk_indexes")
    with engine.connect() as connection:
        inspector = inspect(connection)
        assert "stream_join_outer_receipts" not in inspector.get_table_names()
        assert "join_type" not in {row["name"] for row in inspector.get_columns("stream_processors")}
        assert "outer_joins_emitted" not in {row["name"] for row in inspector.get_columns("stream_processing_runs")}

    alembic("upgrade", "head")
    with engine.connect() as connection:
        assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == current_head()
    engine.dispose()

print("Stream outer join migration verified.")

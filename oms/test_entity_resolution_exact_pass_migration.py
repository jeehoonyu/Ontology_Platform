"""Entity-resolution exact pass columns upgrade and downgrade from the prior head."""

import os
import subprocess
import sys
import tempfile

from sqlalchemy import create_engine, inspect, text
from tier_b_evidence import current_head

COLUMNS = {"exact_objects", "exact_values_skipped"}

with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temporary:
    database_url = f"sqlite:///{os.path.join(temporary, 'entity-exact-pass-migration.db')}"
    env = {**os.environ, "DATABASE_URL": database_url, "APP_ENV": "test", "AUTH_MODE": "local"}

    def alembic(*args):
        completed = subprocess.run(
            [sys.executable, "-m", "alembic", "-c", "alembic.ini", *args],
            cwd=os.path.dirname(__file__), env=env, capture_output=True, text=True,
        )
        assert completed.returncode == 0, f"{completed.stdout}\n{completed.stderr}"

    def job_columns(connection):
        return {row["name"] for row in inspect(connection).get_columns("entity_resolution_jobs")}

    alembic("upgrade", "0044_entity_resolution_coverage")
    engine = create_engine(database_url)
    with engine.begin() as connection:
        # 0001 builds tables from today's models, so a fresh chain already has the columns.
        # Remove them to stand for a database that reached 0044 before they existed.
        for column in sorted(COLUMNS & job_columns(connection)):
            connection.execute(text(f"ALTER TABLE entity_resolution_jobs DROP COLUMN {column}"))
        assert not COLUMNS & job_columns(connection), "the prior head still has exact pass columns"
        connection.execute(text(
            "INSERT INTO entity_resolution_jobs (id, project_id, object_type_id, fields, status, created_at, completed_at, candidate_count) "
            "VALUES ('before-exact-pass', 'default', 'asset', '[]', 'COMPLETED', 1, 2, 0)"
        ))

    alembic("upgrade", "head")
    with engine.connect() as connection:
        assert COLUMNS <= job_columns(connection)
        row = connection.execute(text(
            "SELECT exact_objects, exact_values_skipped FROM entity_resolution_jobs WHERE id = 'before-exact-pass'"
        )).one()
        # A job that ran before the pass existed says nothing it cannot know.
        assert tuple(row) == (None, None), row
        assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == current_head()

    # Applied twice, as CI does.
    alembic("upgrade", "head")

    alembic("downgrade", "0044_entity_resolution_coverage")
    with engine.connect() as connection:
        assert not COLUMNS & job_columns(connection)

    alembic("upgrade", "head")
    with engine.connect() as connection:
        assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == current_head()
    engine.dispose()

print("Entity resolution exact pass migration verified.")

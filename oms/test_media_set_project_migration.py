"""Media sets gain a project; the ones that already exist keep none (migration 0048).

GOAL_FOUNDATIONS A5 and the owner's decision of 2026-09-26: `media_sets` gains a nullable,
indexed `project_id`, and a set created before it stays unassigned (NULL) until someone
assigns it, rather than being filed under a default project. The downgrade drops the
index and the column.
"""

import os
import subprocess
import sys
import tempfile

from sqlalchemy import create_engine, inspect, text
from tier_b_evidence import current_head

PRIOR = "0047_approval_consumption"
INDEX = "ix_media_sets_project_id"

with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temporary:
    database_url = f"sqlite:///{os.path.join(temporary, 'media-set-project-migration.db')}"
    env = {**os.environ, "DATABASE_URL": database_url, "APP_ENV": "test", "AUTH_MODE": "local"}

    def alembic(*args):
        completed = subprocess.run(
            [sys.executable, "-m", "alembic", "-c", "alembic.ini", *args],
            cwd=os.path.dirname(__file__), env=env, capture_output=True, text=True,
        )
        assert completed.returncode == 0, f"{completed.stdout}\n{completed.stderr}"

    def columns(connection):
        return {column["name"] for column in inspect(connection).get_columns("media_sets")}

    def indexes(connection):
        return {row["name"] for row in inspect(connection).get_indexes("media_sets")}

    alembic("upgrade", PRIOR)
    engine = create_engine(database_url)
    with engine.begin() as connection:
        # 0001 builds today's models, so a fresh chain may already have the column. Drop it to
        # stand for a database that reached 0047 before sets had projects.
        if INDEX in indexes(connection):
            connection.execute(text(f"DROP INDEX {INDEX}"))
        if "project_id" in columns(connection):
            connection.execute(text("ALTER TABLE media_sets DROP COLUMN project_id"))
        connection.execute(text(
            "INSERT INTO media_sets (id, display_name, media_type, created_at) VALUES ('old', 'Old set', 'image', 100)"))
        assert "project_id" not in columns(connection), "the prior head still has the column"

    alembic("upgrade", "head")
    with engine.connect() as connection:
        assert "project_id" in columns(connection), "the upgrade did not add project_id"
        assert INDEX in indexes(connection), "the upgrade did not index project_id"
        project = connection.execute(text("SELECT project_id FROM media_sets WHERE id = 'old'")).scalar_one()
        assert project is None, f"an existing set was filed under a project: {project}"
        assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == current_head()

    # Applied twice, as CI does.
    alembic("upgrade", "head")

    alembic("downgrade", PRIOR)
    with engine.connect() as connection:
        assert "project_id" not in columns(connection), "the downgrade left project_id"
        assert INDEX not in indexes(connection), "the downgrade left the index"
        assert connection.execute(text("SELECT display_name FROM media_sets WHERE id = 'old'")).scalar_one() == "Old set"
    engine.dispose()

print("Media set project migration verified: existing sets stay unassigned, and it downgrades.")

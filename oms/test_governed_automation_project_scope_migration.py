"""Alembic backfills project ownership for legacy governed automation records."""
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile


TABLES = (
    "action_types",
    "approval_requests",
    "action_outbox",
    "idempotency_keys",
    "agent_definitions",
    "logic_functions",
)

with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
    database_path = Path(tmpdir) / "legacy_governed_automation.db"
    with sqlite3.connect(database_path) as connection:
        connection.executescript(
            """
            CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL PRIMARY KEY);
            INSERT INTO alembic_version (version_num) VALUES ('0016_workshop_project_scope');
            CREATE TABLE action_types (id VARCHAR NOT NULL PRIMARY KEY);
            CREATE TABLE approval_requests (id VARCHAR NOT NULL PRIMARY KEY);
            CREATE TABLE action_outbox (id VARCHAR NOT NULL PRIMARY KEY);
            CREATE TABLE idempotency_keys (key VARCHAR NOT NULL PRIMARY KEY);
            CREATE TABLE agent_definitions (id VARCHAR NOT NULL PRIMARY KEY);
            CREATE TABLE logic_functions (id VARCHAR NOT NULL PRIMARY KEY);
            INSERT INTO action_types VALUES ('legacy-action');
            INSERT INTO approval_requests VALUES ('legacy-approval');
            INSERT INTO action_outbox VALUES ('legacy-outbox');
            INSERT INTO idempotency_keys VALUES ('legacy-key');
            INSERT INTO agent_definitions VALUES ('legacy-agent');
            INSERT INTO logic_functions VALUES ('legacy-logic');
            """
        )

    env = dict(os.environ)
    env["DATABASE_URL"] = f"sqlite:///{database_path.as_posix()}"
    root = Path(__file__).resolve().parent
    completed = subprocess.run(
        [sys.executable, "-m", "alembic", "-c", str(root / "alembic.ini"), "upgrade", "head"],
        cwd=root,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert completed.returncode == 0, f"{completed.stdout}\n{completed.stderr}"

    with sqlite3.connect(database_path) as connection:
        version = connection.execute("SELECT version_num FROM alembic_version").fetchone()[0]
        for table_name in TABLES:
            key_column = "key" if table_name == "idempotency_keys" else "id"
            project_id = connection.execute(f"SELECT project_id FROM {table_name} WHERE {key_column} LIKE 'legacy-%'").fetchone()[0]
            indexes = {row[1] for row in connection.execute(f"PRAGMA index_list('{table_name}')").fetchall()}
            assert project_id == "default", (table_name, project_id)
            assert f"ix_{table_name}_project_id" in indexes, (table_name, indexes)

    assert version == "0021_project_operational_plane", version

print("\nGoverned automation project-scope migration verified for six legacy tables.")

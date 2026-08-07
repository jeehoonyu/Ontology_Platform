"""Alembic backfills project ownership for legacy model and evaluation records."""
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile


TABLES = ("model_endpoints", "eval_suites", "eval_runs", "aip_eval_runs")

with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
    database_path = Path(tmpdir) / "legacy_ai_evaluations.db"
    with sqlite3.connect(database_path) as connection:
        connection.executescript(
            """
            CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL PRIMARY KEY);
            INSERT INTO alembic_version (version_num) VALUES ('0017_governed_automation_scope');
            CREATE TABLE model_endpoints (id VARCHAR NOT NULL PRIMARY KEY);
            CREATE TABLE eval_suites (id VARCHAR NOT NULL PRIMARY KEY);
            CREATE TABLE eval_runs (id VARCHAR NOT NULL PRIMARY KEY);
            CREATE TABLE aip_eval_runs (id VARCHAR NOT NULL PRIMARY KEY);
            INSERT INTO model_endpoints VALUES ('legacy-endpoint');
            INSERT INTO eval_suites VALUES ('legacy-suite');
            INSERT INTO eval_runs VALUES ('legacy-run');
            INSERT INTO aip_eval_runs VALUES ('legacy-aip-run');
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
            project_id = connection.execute(f"SELECT project_id FROM {table_name}").fetchone()[0]
            indexes = {row[1] for row in connection.execute(f"PRAGMA index_list('{table_name}')").fetchall()}
            assert project_id == "default", (table_name, project_id)
            assert f"ix_{table_name}_project_id" in indexes, (table_name, indexes)

    assert version == "0040_object_facet_counts", version

print("\nAI evaluation project-scope migration verified for four legacy tables.")

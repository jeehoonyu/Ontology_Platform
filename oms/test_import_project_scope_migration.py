"""Alembic backfills project ownership for legacy import jobs."""
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile


with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
    database_path = Path(tmpdir) / "legacy_imports.db"
    with sqlite3.connect(database_path) as connection:
        connection.executescript(
            """
            CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL PRIMARY KEY);
            INSERT INTO alembic_version (version_num) VALUES ('0013_job_idempotency');
            CREATE TABLE import_jobs (
                id VARCHAR NOT NULL PRIMARY KEY,
                source_type VARCHAR NOT NULL,
                filename VARCHAR,
                display_name VARCHAR NOT NULL,
                target_dataset_id VARCHAR,
                status VARCHAR NOT NULL,
                inferred_schema JSON NOT NULL,
                preview_rows JSON NOT NULL,
                validation_errors JSON NOT NULL,
                records JSON NOT NULL,
                created_at INTEGER NOT NULL,
                updated_at INTEGER NOT NULL,
                promoted_at INTEGER
            );
            INSERT INTO import_jobs VALUES (
                'legacy-import', 'csv', 'assets.csv', 'Legacy Assets', NULL, 'READY',
                '{}', '[]', '[]', '[]', 1, 1, NULL
            );
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
        project_id = connection.execute("SELECT project_id FROM import_jobs WHERE id='legacy-import'").fetchone()[0]
        indexes = {row[1] for row in connection.execute("PRAGMA index_list('import_jobs')").fetchall()}

    assert version == "0042_stream_outer_joins", version
    assert project_id == "default", project_id
    assert "ix_import_jobs_project_id" in indexes, indexes

print("\nImport project-scope migration verified: legacy jobs are retained under the default project.")

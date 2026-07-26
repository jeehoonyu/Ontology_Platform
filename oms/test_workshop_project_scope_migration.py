"""Alembic backfills project ownership for legacy Workshop modules."""
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile


with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
    database_path = Path(tmpdir) / "legacy_workshop.db"
    with sqlite3.connect(database_path) as connection:
        connection.executescript(
            """
            CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL PRIMARY KEY);
            INSERT INTO alembic_version (version_num) VALUES ('0015_pipeline_project_scope');
            CREATE TABLE workshop_modules (
                id VARCHAR NOT NULL PRIMARY KEY,
                display_name VARCHAR NOT NULL,
                description VARCHAR,
                variables JSON NOT NULL,
                widgets JSON NOT NULL,
                layout JSON NOT NULL,
                created_at INTEGER NOT NULL,
                updated_at INTEGER NOT NULL
            );
            INSERT INTO workshop_modules VALUES (
                'legacy-workshop', 'Legacy workshop', NULL, '{}', '[]', '{}', 1, 1
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
        project_id = connection.execute("SELECT project_id FROM workshop_modules WHERE id='legacy-workshop'").fetchone()[0]
        indexes = {row[1] for row in connection.execute("PRAGMA index_list('workshop_modules')").fetchall()}

    assert version == "0016_workshop_project_scope", version
    assert project_id == "default", project_id
    assert "ix_workshop_modules_project_id" in indexes, indexes

print("\nWorkshop project-scope migration verified: legacy modules are retained under the default project.")

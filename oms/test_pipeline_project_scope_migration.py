"""Alembic backfills project ownership for legacy Pipeline Builder graphs."""
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile


with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
    database_path = Path(tmpdir) / "legacy_pipeline_graphs.db"
    with sqlite3.connect(database_path) as connection:
        connection.executescript(
            """
            CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL PRIMARY KEY);
            INSERT INTO alembic_version (version_num) VALUES ('0014_import_project_scope');
            CREATE TABLE pipeline_builder_graphs (
                id VARCHAR NOT NULL PRIMARY KEY,
                display_name VARCHAR NOT NULL,
                description VARCHAR,
                nodes JSON NOT NULL,
                edges JSON NOT NULL,
                parameters JSON NOT NULL,
                status VARCHAR NOT NULL,
                created_at INTEGER NOT NULL,
                updated_at INTEGER NOT NULL
            );
            INSERT INTO pipeline_builder_graphs VALUES (
                'legacy-graph', 'Legacy graph', NULL, '[]', '[]', '{}', 'DRAFT', 1, 1
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
        project_id = connection.execute("SELECT project_id FROM pipeline_builder_graphs WHERE id='legacy-graph'").fetchone()[0]
        indexes = {row[1] for row in connection.execute("PRAGMA index_list('pipeline_builder_graphs')").fetchall()}

    assert version == "0020_project_semantic_plane", version
    assert project_id == "default", project_id
    assert "ix_pipeline_builder_graphs_project_id" in indexes, indexes

print("\nPipeline project-scope migration verified: legacy graphs are retained under the default project.")

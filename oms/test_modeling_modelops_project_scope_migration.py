"""Alembic backfills project ownership for the complete modeling lifecycle."""
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile


TABLES = (
    "modeling_objectives", "model_submissions", "model_deployments",
    "model_monitors", "model_monitor_runs", "model_prediction_logs",
    "mev_releases", "mev_checks", "mev_check_results", "mev_eval_datasets",
    "mev_eval_subsets", "mev_experiments", "mev_adapters", "mev_deployment_configs",
)

with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
    database_path = Path(tmpdir) / "legacy_modelops.db"
    with sqlite3.connect(database_path) as connection:
        connection.execute("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL PRIMARY KEY)")
        connection.execute("INSERT INTO alembic_version VALUES ('0018_project_scoped_ai_evals')")
        for table_name in TABLES:
            connection.execute(f"CREATE TABLE {table_name} (id VARCHAR NOT NULL PRIMARY KEY)")
            connection.execute(f"INSERT INTO {table_name} VALUES ('legacy-{table_name}')")

    env = dict(os.environ)
    env["DATABASE_URL"] = f"sqlite:///{database_path.as_posix()}"
    root = Path(__file__).resolve().parent
    completed = subprocess.run(
        [sys.executable, "-m", "alembic", "-c", str(root / "alembic.ini"), "upgrade", "head"],
        cwd=root, env=env, capture_output=True, text=True, timeout=120, check=False,
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

print("\nModeling and ModelOps project-scope migration verified for 14 legacy tables.")

"""Alembic promotes semantic data-plane ownership to first-class project columns."""
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile


TABLES = (
    "object_types", "object_instances", "link_types", "link_instances",
    "data_assets", "pipeline_definitions", "pipeline_runs",
    "saved_object_sets", "map_layer_definitions", "object_explorer_explorations", "act_action_log",
)

with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
    database_path = Path(tmpdir) / "legacy_semantic_plane.db"
    with sqlite3.connect(database_path) as connection:
        connection.execute("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL PRIMARY KEY)")
        connection.execute("INSERT INTO alembic_version VALUES ('0019_project_scoped_modelops')")
        for table_name in TABLES:
            if table_name == "data_assets":
                connection.execute("CREATE TABLE data_assets (id VARCHAR NOT NULL PRIMARY KEY, asset_schema JSON)")
                connection.execute("INSERT INTO data_assets VALUES (?, ?)", ("legacy-data", json.dumps({"project_id": "alpha"})))
            else:
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
            expected = "alpha" if table_name == "data_assets" else "default"
            assert project_id == expected, (table_name, project_id)
            assert f"ix_{table_name}_project_id" in indexes, (table_name, indexes)

    assert version == "0021_project_operational_plane", version

print("\nSemantic data-plane project migration verified for 11 legacy tables.")

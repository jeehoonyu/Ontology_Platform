"""Upgrade a pre-release-lifecycle database from migration 0021 to 0022."""
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from sqlalchemy import create_engine, inspect, text

tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
database = Path(tmpdir.name) / "ontology_release_migration.db"
database_url = f"sqlite:///{database}"
engine = create_engine(database_url)

with engine.begin() as connection:
    connection.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(32) PRIMARY KEY)"))
    connection.execute(text("INSERT INTO alembic_version(version_num) VALUES ('0021_project_operational_plane')"))
    connection.execute(text("CREATE TABLE ontology_branches (id VARCHAR PRIMARY KEY, display_name VARCHAR NOT NULL, base_branch VARCHAR NOT NULL, status VARCHAR NOT NULL, created_at INTEGER NOT NULL)"))
    connection.execute(text("CREATE TABLE ontology_proposals (id VARCHAR PRIMARY KEY, branch_id VARCHAR NOT NULL, title VARCHAR NOT NULL, description VARCHAR, changes JSON, status VARCHAR NOT NULL, reviewer VARCHAR, created_at INTEGER NOT NULL, decided_at INTEGER)"))
    connection.execute(text("INSERT INTO ontology_branches VALUES ('legacy_branch', 'Legacy Branch', 'main', 'open', 1)"))
    connection.execute(text("INSERT INTO ontology_proposals VALUES ('legacy_proposal', 'legacy_branch', 'Legacy Proposal', NULL, '[]', 'draft', NULL, 1, NULL)"))

root = Path(__file__).resolve().parent
environment = os.environ.copy()
environment["DATABASE_URL"] = database_url
environment["AUTH_MODE"] = "local"
environment["APP_ENV"] = "test"
subprocess.run([sys.executable, "-m", "alembic", "-c", str(root / "alembic.ini"), "upgrade", "head"], cwd=root, env=environment, check=True, capture_output=True, text=True)

inspector = inspect(engine)
tables = set(inspector.get_table_names())
assert {"ontology_revisions", "ontology_change_sets", "ontology_environments"} <= tables
assert "project_id" in {column["name"] for column in inspector.get_columns("ontology_branches")}
assert "project_id" in {column["name"] for column in inspector.get_columns("ontology_proposals")}
with engine.connect() as connection:
    assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == "0042_stream_outer_joins"
    assert connection.execute(text("SELECT project_id FROM ontology_branches WHERE id='legacy_branch'")).scalar_one() == "default"
    assert connection.execute(text("SELECT project_id FROM ontology_proposals WHERE id='legacy_proposal'")).scalar_one() == "default"

print("\nOntology release lifecycle migration verified from 0021 to 0022.")
engine.dispose()
tmpdir.cleanup()

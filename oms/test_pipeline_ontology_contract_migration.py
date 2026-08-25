"""Upgrade ontology contract persistence from the prior migration head."""
import os
import tempfile

from sqlalchemy import create_engine, inspect, text

tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
database_path = os.path.join(tmpdir.name, "pipeline_ontology_contract_migration.db")
database_url = f"sqlite:///{database_path}"
engine = create_engine(database_url)
with engine.begin() as connection:
    connection.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL PRIMARY KEY)"))
    connection.execute(text("INSERT INTO alembic_version(version_num) VALUES ('0023_ontology_health_runs')"))
engine.dispose()

os.environ["DATABASE_URL"] = database_url
os.environ["SKIP_CREATE_ALL"] = "1"
from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from tier_b_evidence import current_head

config = Config(os.path.join(os.path.dirname(__file__), "alembic.ini"))
command.upgrade(config, "head")

engine = create_engine(database_url)
with engine.connect() as connection:
    assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == current_head()
    columns = {column["name"] for column in inspect(connection).get_columns("pipeline_ontology_contract_runs")}
    assert {
        "id", "project_id", "graph_id", "build_id", "node_id", "object_type_id", "status",
        "input_rows", "accepted_rows", "rejected_rows", "created_objects", "updated_objects",
        "unchanged_objects", "quarantine_asset_id", "field_lineage", "violations", "created_at",
    } <= columns
engine.dispose()
tmpdir.cleanup()
print("Pipeline ontology contract migration verified.")

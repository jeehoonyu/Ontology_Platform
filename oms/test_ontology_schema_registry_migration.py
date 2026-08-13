"""Upgrade ontology schema registry persistence from the prior migration head."""
import os
import tempfile

from sqlalchemy import create_engine, inspect, text

tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
database_path = os.path.join(tmpdir.name, "ontology_schema_registry_migration.db")
database_url = f"sqlite:///{database_path}"
engine = create_engine(database_url)
with engine.begin() as connection:
    connection.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL PRIMARY KEY)"))
    connection.execute(text("INSERT INTO alembic_version(version_num) VALUES ('0024_pipeline_ontology_contracts')"))
engine.dispose()

os.environ["DATABASE_URL"] = database_url
os.environ["SKIP_CREATE_ALL"] = "1"
from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402

config = Config(os.path.join(os.path.dirname(__file__), "alembic.ini"))
command.upgrade(config, "head")

engine = create_engine(database_url)
with engine.connect() as connection:
    assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == "0042_stream_outer_joins"
    columns = {column["name"] for column in inspect(connection).get_columns("ontology_registry_entries")}
    assert {
        "id", "project_id", "channel", "version", "revision_id", "revision_number", "status",
        "manifest", "contract_schema", "compatibility", "checksum", "published_by", "created_at",
    } <= columns
engine.dispose()
tmpdir.cleanup()
print("Ontology schema registry migration verified.")

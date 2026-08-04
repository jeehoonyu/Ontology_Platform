"""Upgrade governed ontology query indexes from the OntologyOS core revision."""

import os
import tempfile

from sqlalchemy import create_engine, inspect, text


tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
database_path = os.path.join(tmpdir.name, "ontology_query_indexes.db")
os.environ["DATABASE_URL"] = f"sqlite:///{database_path}"
os.environ["SKIP_CREATE_ALL"] = "1"

from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402


config = Config(os.path.join(os.path.dirname(__file__), "alembic.ini"))
config.set_main_option("sqlalchemy.url", os.environ["DATABASE_URL"])
command.upgrade(config, "0026_ontologyos_runtime_core")
command.upgrade(config, "0027_ontology_query_indexes")
command.upgrade(config, "0027_ontology_query_indexes")

engine = create_engine(os.environ["DATABASE_URL"])
with engine.connect() as connection:
    assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == "0027_ontology_query_indexes"
    inspector = inspect(connection)
    tables = set(inspector.get_table_names())
    assert "ontology_index_definitions" in tables
    columns = {column["name"] for column in inspector.get_columns("ontology_index_definitions")}
    assert {"property_name", "base_type", "index_name", "strategy", "status", "ddl", "applied_at"} <= columns
    object_indexes = {row["name"] for row in inspector.get_indexes("object_instances")}
    assert "ix_object_instances_project_type_updated_id" in object_indexes
    event_indexes = {row["name"] for row in inspector.get_indexes("object_change_events")}
    assert "ix_object_change_events_temporal_lookup" in event_indexes
    link_indexes = {row["name"] for row in inspector.get_indexes("link_instances")}
    assert {
        "ix_link_instances_project_source_id", "ix_link_instances_project_target_id",
        "ix_link_instances_project_type_id",
    } <= link_indexes

engine.dispose()
tmpdir.cleanup()
print("Ontology query indexes migration verified.")

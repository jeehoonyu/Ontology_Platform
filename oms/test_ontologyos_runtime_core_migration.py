"""Upgrade the OntologyOS runtime core from the prior migration head."""

import os
import tempfile

from sqlalchemy import create_engine, inspect, text


tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
database_path = os.path.join(tmpdir.name, "ontologyos_migration.db")
os.environ["DATABASE_URL"] = f"sqlite:///{database_path}"
os.environ["SKIP_CREATE_ALL"] = "1"

from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402


config = Config(os.path.join(os.path.dirname(__file__), "alembic.ini"))
config.set_main_option("sqlalchemy.url", os.environ["DATABASE_URL"])
command.upgrade(config, "0025_ontology_schema_registry")
command.upgrade(config, "0026_ontologyos_runtime_core")
command.upgrade(config, "0026_ontologyos_runtime_core")

engine = create_engine(os.environ["DATABASE_URL"])
with engine.connect() as connection:
    assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == "0026_ontologyos_runtime_core"
    tables = set(inspect(connection).get_table_names())
    expected = {
        "ontology_property_definitions", "ontology_resource_definitions", "object_change_events",
        "data_asset_snapshots", "pipeline_execution_plans", "model_gateway_providers", "model_gateway_runs",
    }
    assert expected <= tables, sorted(expected - tables)
    event_columns = {column["name"] for column in inspect(connection).get_columns("object_change_events")}
    assert {"object_version", "before_state", "after_state", "valid_from", "transaction_time"} <= event_columns
    property_columns = {column["name"] for column in inspect(connection).get_columns("ontology_property_definitions")}
    assert {"base_type", "primary_key", "indexed", "ontology_revision_id"} <= property_columns
    gateway_columns = {column["name"] for column in inspect(connection).get_columns("model_gateway_runs")}
    assert {"request_hash", "idempotency_key", "policy_decision", "evidence"} <= gateway_columns

engine.dispose()
tmpdir.cleanup()
print("OntologyOS runtime core migration verified.")

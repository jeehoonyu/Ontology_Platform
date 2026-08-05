"""Object materialization lifecycle migration is additive and recoverable."""
import os
import tempfile

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text


temporary = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
database_url = f"sqlite:///{os.path.join(temporary.name, 'object-materialization.db')}"
config = Config(os.path.join(os.path.dirname(__file__), "alembic.ini"))
config.set_main_option("sqlalchemy.url", database_url)

command.upgrade(config, "0034_decision_project_scope")
engine = create_engine(database_url)
with engine.begin() as connection:
    indexes = {index["name"] for index in inspect(connection).get_indexes("object_instances")}
    if "ix_object_instances_materialized_active" in indexes:
        connection.execute(text("DROP INDEX ix_object_instances_materialized_active"))
    columns = {column["name"] for column in inspect(connection).get_columns("object_instances")}
    for column in ("retired_at", "is_active", "materialization_id"):
        if column in columns:
            connection.execute(text(f"ALTER TABLE object_instances DROP COLUMN {column}"))
    connection.execute(text(
        "INSERT INTO object_types (id, project_id, display_name, description, properties, created_at, updated_at) "
        "VALUES ('asset', 'default', 'Asset', '', '{}', 1, 1)"
    ))
    connection.execute(text(
        "INSERT INTO object_instances "
        "(id, project_id, object_type_id, properties, source_asset_id, lineage, created_at, updated_at) "
        "VALUES ('asset-1', 'default', 'asset', '{}', 'source', '{}', 1, 1)"
    ))

command.upgrade(config, "head")
with engine.connect() as connection:
    assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == "0038_explicit_schema_baseline"
    columns = {column["name"] for column in inspect(connection).get_columns("object_instances")}
    assert {"materialization_id", "is_active", "retired_at"} <= columns
    assert connection.execute(text("SELECT is_active FROM object_instances WHERE id = 'asset-1'")).scalar_one() in (1, True)
    indexes = {index["name"] for index in inspect(connection).get_indexes("object_instances")}
    assert "ix_object_instances_materialized_active" in indexes

command.downgrade(config, "0034_decision_project_scope")
with engine.connect() as connection:
    columns = {column["name"] for column in inspect(connection).get_columns("object_instances")}
    assert "materialization_id" not in columns and "is_active" not in columns and "retired_at" not in columns
    assert connection.execute(text("SELECT COUNT(*) FROM object_instances WHERE id = 'asset-1'")).scalar_one() == 1

command.upgrade(config, "head")
with engine.connect() as connection:
    assert connection.execute(text("SELECT is_active FROM object_instances WHERE id = 'asset-1'")).scalar_one() in (1, True)
    assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == "0038_explicit_schema_baseline"

engine.dispose()
temporary.cleanup()
print("Object materialization lifecycle migration verified.")

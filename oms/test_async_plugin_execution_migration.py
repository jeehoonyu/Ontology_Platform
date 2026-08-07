"""Verify the durable plugin execution job link migration."""

import os
import tempfile

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text


tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
database_url = f"sqlite:///{os.path.join(tmpdir.name, 'async-plugin-migration.db')}"
config = Config(os.path.join(os.path.dirname(__file__), "alembic.ini"))
config.set_main_option("sqlalchemy.url", database_url)

command.upgrade(config, "0032_signed_plugin_runtime")
command.upgrade(config, "0033_async_plugin_execution")
command.upgrade(config, "0033_async_plugin_execution")

engine = create_engine(database_url)
with engine.connect() as connection:
    assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == "0033_async_plugin_execution"
    inspector = inspect(connection)
    columns = {row["name"] for row in inspector.get_columns("plugin_executions")}
    indexes = {row["name"]: row for row in inspector.get_indexes("plugin_executions")}
    assert "job_id" in columns
    assert indexes["ix_plugin_executions_job_id"]["unique"] == 1

command.downgrade(config, "0032_signed_plugin_runtime")
with engine.connect() as connection:
    assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == "0032_signed_plugin_runtime"
    assert "job_id" not in {row["name"] for row in inspect(connection).get_columns("plugin_executions")}

command.upgrade(config, "head")
with engine.connect() as connection:
    assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == "0039_object_geo_bounds"

engine.dispose()
tmpdir.cleanup()
print("Async plugin execution migration verified: repeat upgrade, unique job link, downgrade, and head recovery.")

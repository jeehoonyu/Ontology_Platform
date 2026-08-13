"""Verify revision 0032 installs signed plugin runtime storage."""

import os
import tempfile

from sqlalchemy import create_engine, inspect, text


tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
database_path = os.path.join(tmpdir.name, "signed_plugin_runtime.db")
os.environ["DATABASE_URL"] = f"sqlite:///{database_path}"
os.environ["SKIP_CREATE_ALL"] = "1"

from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402


config = Config(os.path.join(os.path.dirname(__file__), "alembic.ini"))
config.set_main_option("sqlalchemy.url", os.environ["DATABASE_URL"])
command.upgrade(config, "0031_artifact_review_workflows")

engine = create_engine(os.environ["DATABASE_URL"])
with engine.begin() as connection:
    for table in ("plugin_executions", "plugin_versions", "plugin_trust_keys"):
        connection.execute(text(f"DROP TABLE IF EXISTS {table}"))
engine.dispose()

command.upgrade(config, "0032_signed_plugin_runtime")
command.upgrade(config, "0032_signed_plugin_runtime")

engine = create_engine(os.environ["DATABASE_URL"])
with engine.connect() as connection:
    assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == "0032_signed_plugin_runtime"
    inspector = inspect(connection)
    tables = set(inspector.get_table_names())
    assert {"plugin_trust_keys", "plugin_versions", "plugin_executions"} <= tables
    version_columns = {row["name"] for row in inspector.get_columns("plugin_versions")}
    assert {"manifest_sha256", "bundle_sha256", "signature", "signer_key_id", "capabilities", "operations", "status"} <= version_columns
    execution_columns = {row["name"] for row in inspector.get_columns("plugin_executions")}
    assert {"request_hash", "idempotency_key", "sandbox", "exit_code", "duration_ms", "evidence"} <= execution_columns
    assert "uq_plugin_project_version" in {row["name"] for row in inspector.get_unique_constraints("plugin_versions")}
    assert "uq_plugin_execution_idempotency" in {row["name"] for row in inspector.get_unique_constraints("plugin_executions")}

engine.dispose()
tmpdir.cleanup()
print("Signed plugin runtime migration verified.")

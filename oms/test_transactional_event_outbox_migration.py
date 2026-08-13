"""Upgrade the transactional event outbox from the ontology query revision."""

import os
import tempfile

from sqlalchemy import create_engine, inspect, text


tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
database_path = os.path.join(tmpdir.name, "event_outbox_migration.db")
os.environ["DATABASE_URL"] = f"sqlite:///{database_path}"
os.environ["SKIP_CREATE_ALL"] = "1"

from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402


config = Config(os.path.join(os.path.dirname(__file__), "alembic.ini"))
config.set_main_option("sqlalchemy.url", os.environ["DATABASE_URL"])
command.upgrade(config, "0027_ontology_query_indexes")
command.upgrade(config, "0028_transactional_event_outbox")
command.upgrade(config, "0028_transactional_event_outbox")

engine = create_engine(os.environ["DATABASE_URL"])
with engine.connect() as connection:
    assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == "0028_transactional_event_outbox"
    inspector = inspect(connection)
    assert {"event_outbox", "platform_event_log"} <= set(inspector.get_table_names())
    outbox_columns = {column["name"] for column in inspector.get_columns("event_outbox")}
    assert {"idempotency_key", "status", "attempts", "available_at", "lease_token", "published_at"} <= outbox_columns
    outbox_indexes = {row["name"] for row in inspector.get_indexes("event_outbox")}
    assert "ix_event_outbox_claim" in outbox_indexes
    event_indexes = {row["name"] for row in inspector.get_indexes("platform_event_log")}
    assert "ix_platform_event_log_project_sequence" in event_indexes

engine.dispose()
tmpdir.cleanup()
print("Transactional event outbox migration verified.")

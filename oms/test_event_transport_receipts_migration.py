"""Upgrade event delivery from the transactional outbox revision."""

import os
import tempfile

from sqlalchemy import create_engine, inspect, text


tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
database_path = os.path.join(tmpdir.name, "event_transport_receipts.db")
os.environ["DATABASE_URL"] = f"sqlite:///{database_path}"
os.environ["SKIP_CREATE_ALL"] = "1"

from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402


config = Config(os.path.join(os.path.dirname(__file__), "alembic.ini"))
config.set_main_option("sqlalchemy.url", os.environ["DATABASE_URL"])
command.upgrade(config, "0028_transactional_event_outbox")
command.upgrade(config, "0029_event_transport_receipts")
command.upgrade(config, "0029_event_transport_receipts")

engine = create_engine(os.environ["DATABASE_URL"])
with engine.connect() as connection:
    assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == "0029_event_transport_receipts"
    inspector = inspect(connection)
    assert "event_transport_receipts" in inspector.get_table_names()
    columns = {column["name"] for column in inspector.get_columns("event_transport_receipts")}
    assert {
        "outbox_event_id", "transport", "destination", "status", "attempts",
        "available_at", "lease_token", "broker_metadata", "delivered_at",
    } <= columns
    indexes = {row["name"] for row in inspector.get_indexes("event_transport_receipts")}
    assert "ix_event_transport_receipts_claim" in indexes

engine.dispose()
tmpdir.cleanup()
print("Event transport receipt migration verified.")

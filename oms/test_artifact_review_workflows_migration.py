"""Verify revision 0031 installs durable artifact review workflow storage."""

import os
import tempfile

from sqlalchemy import create_engine, inspect, text


tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
database_path = os.path.join(tmpdir.name, "artifact_review_workflows.db")
os.environ["DATABASE_URL"] = f"sqlite:///{database_path}"
os.environ["SKIP_CREATE_ALL"] = "1"

from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402


config = Config(os.path.join(os.path.dirname(__file__), "alembic.ini"))
config.set_main_option("sqlalchemy.url", os.environ["DATABASE_URL"])
command.upgrade(config, "0030_durable_stream_processing")

# Current metadata may create future tables during the dynamic baseline. Drop
# them to reproduce a real database created at the preceding release.
engine = create_engine(os.environ["DATABASE_URL"])
with engine.begin() as connection:
    connection.execute(text("DROP TABLE IF EXISTS platform_artifact_change_proposals"))
    connection.execute(text("DROP TABLE IF EXISTS platform_artifact_review_comments"))
engine.dispose()

command.upgrade(config, "0031_artifact_review_workflows")
command.upgrade(config, "0031_artifact_review_workflows")

engine = create_engine(os.environ["DATABASE_URL"])
with engine.connect() as connection:
    assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == (
        "0031_artifact_review_workflows"
    )
    inspector = inspect(connection)
    tables = set(inspector.get_table_names())
    assert {
        "platform_artifact_review_comments",
        "platform_artifact_change_proposals",
    } <= tables

    comment_columns = {
        row["name"] for row in inspector.get_columns("platform_artifact_review_comments")
    }
    assert {
        "artifact_id", "project_id", "revision", "target", "thread_id",
        "parent_id", "body", "status", "author", "resolved_by", "resolved_at",
    } <= comment_columns

    proposal_columns = {
        row["name"] for row in inspector.get_columns("platform_artifact_change_proposals")
    }
    assert {
        "artifact_id", "project_id", "base_revision", "base_lock_version", "version",
        "commands", "targets", "validation", "status", "author", "reviewer",
        "applied_revision", "reviewed_at", "applied_at",
    } <= proposal_columns

    comment_indexes = {
        row["name"] for row in inspector.get_indexes("platform_artifact_review_comments")
    }
    proposal_indexes = {
        row["name"] for row in inspector.get_indexes("platform_artifact_change_proposals")
    }
    assert "ix_artifact_comments_thread_order" in comment_indexes
    assert "ix_artifact_proposals_review_queue" in proposal_indexes

engine.dispose()
tmpdir.cleanup()
print("Artifact review workflow migration verified.")

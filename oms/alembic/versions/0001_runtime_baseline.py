"""Create the complete production-pilot schema baseline.

Revision ID: 0001_runtime_baseline
Revises: None
"""
import os

from alembic import op

revision = "0001_runtime_baseline"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    os.environ["SKIP_CREATE_ALL"] = "1"
    from app.database import Base
    from app import main  # noqa: F401 - registers every model on Base metadata
    Base.metadata.create_all(bind=op.get_bind(), checkfirst=True)


def downgrade() -> None:
    # The baseline intentionally has no automatic destructive downgrade.
    # Restore a pre-upgrade backup for a complete rollback.
    pass

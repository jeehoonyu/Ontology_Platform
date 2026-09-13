"""Record how much of its object type an entity-resolution job compared.

GOAL_HONEST_UI_2026-09-11, the Decision workspace limits. A job compares every pair
among the objects it reads. It read at most 1,000, in no stated order, while the
Candidate Review Queue read as the type's whole duplicate list and Explain called an
object the job never read "clear". Jobs now read in id order and keep three facts: how
many objects the type held, how many were compared, and the last id read. A reloaded
job list and Explain can then say what was compared, and a job that ran before this
revision says nothing it cannot know: its three columns are NULL.

Revision ID: 0044_entity_resolution_coverage
Revises: 0043_drop_orphaned_value_types
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0044_entity_resolution_coverage"
down_revision = "0043_drop_orphaned_value_types"
branch_labels = None
depends_on = None

TABLE = "entity_resolution_jobs"
COLUMNS = (
    ("objects_in_scope", sa.Integer),
    ("objects_scanned", sa.Integer),
    ("last_scanned_id", sa.String),
)


def _present(bind) -> set:
    inspector = sa.inspect(bind)
    if not inspector.has_table(TABLE):
        return set()
    return {column["name"] for column in inspector.get_columns(TABLE)}


def upgrade() -> None:
    bind = op.get_bind()
    # Guarded, like 0039 and 0043: CI applies the chain twice, and some tests build
    # deliberately partial schemas.
    if not sa.inspect(bind).has_table(TABLE):
        return
    present = _present(bind)
    for name, column_type in COLUMNS:
        if name not in present:
            op.add_column(TABLE, sa.Column(name, column_type(), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    present = _present(bind)
    for name, _column_type in reversed(COLUMNS):
        if name in present:
            op.drop_column(TABLE, name)

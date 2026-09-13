"""Record the exact pass an entity-resolution job makes over its whole object type.

GOAL_HONEST_UI_2026-09-11, entity resolution's reach. A job compares every pair among the
first N objects of its type by id, and objects past them were never compared. It now also
pairs every object of the type that shares a value in one of its fields, ignoring case and
punctuation, and keeps two facts: how many objects that pass read, and how many shared
values it left unpaired because more objects share them than it pairs. A job that ran
before this revision says nothing it cannot know: both columns are NULL.

Revision ID: 0045_entity_exact_pass
Revises: 0044_entity_resolution_coverage
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0045_entity_exact_pass"
down_revision = "0044_entity_resolution_coverage"
branch_labels = None
depends_on = None

TABLE = "entity_resolution_jobs"
COLUMNS = (
    ("exact_objects", sa.Integer),
    ("exact_values_skipped", sa.Integer),
)


def _present(bind) -> set:
    inspector = sa.inspect(bind)
    if not inspector.has_table(TABLE):
        return set()
    return {column["name"] for column in inspector.get_columns(TABLE)}


def upgrade() -> None:
    bind = op.get_bind()
    # Guarded, like 0044: CI applies the chain twice, and some tests build partial schemas.
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

"""Give media sets a project.

GOAL_FOUNDATIONS A5. `media_sets` had no project, so its list, get, items and extraction
served every tenant's sets to any editor. The table gains a nullable, indexed
`project_id`. Existing sets keep none: the owner decided on 2026-09-26 that they stay
unassigned, reachable only by a principal who holds every project, until someone assigns
one (`POST /media-sets/{id}/project`). New sets are created in a project. Media items
reach their project through their set, so they gain no column.

Revision ID: 0048_media_set_project
Revises: 0047_approval_consumption
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0048_media_set_project"
down_revision = "0047_approval_consumption"
branch_labels = None
depends_on = None

TABLE = "media_sets"
INDEX = "ix_media_sets_project_id"


def _columns(bind) -> set:
    inspector = sa.inspect(bind)
    if not inspector.has_table(TABLE):
        return set()
    return {column["name"] for column in inspector.get_columns(TABLE)}


def upgrade() -> None:
    bind = op.get_bind()
    columns = _columns(bind)
    if not columns:
        return  # no media_sets table to alter (0038's baseline creates it)
    if "project_id" not in columns:
        with op.batch_alter_table(TABLE) as batch:
            batch.add_column(sa.Column("project_id", sa.String(), nullable=True))
    if INDEX not in {index["name"] for index in sa.inspect(bind).get_indexes(TABLE)}:
        op.create_index(INDEX, TABLE, ["project_id"])


def downgrade() -> None:
    bind = op.get_bind()
    if "project_id" not in _columns(bind):
        return
    if INDEX in {index["name"] for index in sa.inspect(bind).get_indexes(TABLE)}:
        op.drop_index(INDEX, table_name=TABLE)
    with op.batch_alter_table(TABLE) as batch:
        batch.drop_column("project_id")

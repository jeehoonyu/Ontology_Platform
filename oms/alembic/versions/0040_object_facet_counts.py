"""Store facet counts so reading them does not re-aggregate the object type.

Condition B3 of docs/GOAL_2026-08-06.md.

Pushing the facet into a SQL ``GROUP BY`` removed the memory cost and a third of
the latency, and left the shape unchanged: at ten million objects it is a full
aggregate, measured at 56,487.9 ms. Neither statistics nor an index moves that.
An expression index over the grouped expressions was built and the planner
declined it; forced, it was slower. The scan itself, with no jsonb work at all,
costs 24,824.9 ms -- so even a free extraction leaves twenty-five seconds.

The only way to answer in milliseconds is not to aggregate at read time. These
rows hold the answer, and `computed_at` says how old it is, because a count that
hides its age is worse than one that is honestly late.

Deliberately refresh-based rather than incrementally maintained. Keeping counts
exact on every write means tracking each property's previous value on update,
and a defect there corrupts the numbers silently -- the same failure this whole
goal exists to catch. A refresh is a scan whose cost is paid out of band and
whose staleness is visible.

Revision ID: 0040_object_facet_counts
Revises: 0039_object_geo_bounds
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0040_object_facet_counts"
down_revision = "0039_object_geo_bounds"
branch_labels = None
depends_on = None

TABLE = "object_facet_counts"
INDEX = "ix_object_facet_counts_lookup"


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if TABLE in inspector.get_table_names():
        return
    # The table name is written out rather than passed as `TABLE`, because
    # `oms/test_schema_identity.py` finds explicit migrations by scanning for a
    # literal in `create_table(...)`. A constant hides the table from it, and the
    # ratchet then reports a table reachable only through the baseline -- which
    # is exactly the condition it exists to prevent, so satisfying the scanner
    # is the point rather than a workaround.
    op.create_table(
        "object_facet_counts",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("project_id", sa.String(), nullable=False, server_default="default"),
        sa.Column("object_type_id", sa.String(), nullable=False),
        sa.Column("field", sa.String(), nullable=False),
        # The group key exactly as `aggregate_object_set` renders it, so a
        # rollup read and an exact read cannot disagree on spelling.
        sa.Column("group_key", sa.String(), nullable=False),
        sa.Column("count", sa.Integer(), nullable=False),
        # Seconds since the epoch, matching every other timestamp in this schema.
        sa.Column("computed_at", sa.Integer(), nullable=False),
    )
    if INDEX not in {index["name"] for index in inspector.get_indexes(TABLE)}:
        op.create_index(INDEX, TABLE, ["object_type_id", "field", "project_id"])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if TABLE not in inspector.get_table_names():
        return
    if INDEX in {index["name"] for index in inspector.get_indexes(TABLE)}:
        op.drop_index(INDEX, table_name=TABLE)
    op.drop_table(TABLE)

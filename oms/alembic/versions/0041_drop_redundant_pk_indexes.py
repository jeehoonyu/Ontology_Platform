"""Drop the indexes that duplicate a primary key.

Every model declared its identifier as ``primary_key=True, index=True``. A
primary key already implies a unique index on both dialects, so the second
declaration produced a redundant one -- ``ix_<table>_id`` beside
``<table>_pkey`` -- maintained on every insert, update and delete, for no read
it can serve that the primary key cannot.

Measured on the benchmark database at head 0040: **244 such indexes, 283 MB**,
of which 261 MB sits on ``object_instances`` alone. They are part of why that
table carried 2,761 MB of index against a 966 MB heap while ``shared_buffers``
was 128 MB, and why a bulk load decayed from 10,416 to 2,645 rows per second
across three million rows.

The set is derived from the live schema rather than hardcoded. A list written
today would be wrong the moment a model changed, and would silently do nothing
on a deployment whose tables differ -- the failure mode the schema-identity
ratchet exists to catch. Deriving it also makes this safe to re-run.

Only non-unique, single-column, non-expression indexes on a table's sole
primary-key column are dropped. A unique index may be enforcing a constraint
someone depends on, so uniqueness is left alone even when it looks redundant.

Revision ID: 0041_drop_redundant_pk_indexes
Revises: 0040_object_facet_counts
"""
from __future__ import annotations

from typing import List, Tuple

import sqlalchemy as sa
from alembic import op

revision = "0041_drop_redundant_pk_indexes"
down_revision = "0040_object_facet_counts"
branch_labels = None
depends_on = None


def _redundant(bind) -> List[Tuple[str, str, str]]:
    """(table, index, column) for every index that merely repeats a primary key."""
    inspector = sa.inspect(bind)
    found: List[Tuple[str, str, str]] = []
    for table in inspector.get_table_names():
        try:
            primary = inspector.get_pk_constraint(table).get("constrained_columns") or []
        except Exception:
            continue
        if len(primary) != 1:
            continue
        for index in inspector.get_indexes(table):
            name = index.get("name")
            columns = index.get("column_names") or []
            if not name or index.get("unique"):
                continue
            # `column_names` carries None for an expression member; such an
            # index is not a plain duplicate of the key.
            if len(columns) != 1 or columns[0] != primary[0]:
                continue
            found.append((table, name, primary[0]))
    return found


def upgrade() -> None:
    bind = op.get_bind()
    for table, index, _column in _redundant(bind):
        op.drop_index(index, table_name=table)


def downgrade() -> None:
    """Recreate them, so the chain round-trips.

    They are useless, but a downgrade that does not restore what it removed
    leaves the schema unable to reach its own prior state -- which is the defect
    GOAL2-003 recorded when six migrations could not walk back down.
    """
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    for table in inspector.get_table_names():
        try:
            primary = inspector.get_pk_constraint(table).get("constrained_columns") or []
        except Exception:
            continue
        if len(primary) != 1:
            continue
        column = primary[0]
        name = f"ix_{table}_{column}"
        existing = {index.get("name") for index in inspector.get_indexes(table)}
        if name in existing:
            continue
        op.create_index(name, table, [column], unique=False)

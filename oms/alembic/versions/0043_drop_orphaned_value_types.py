"""Drop the value-type tables, which nothing ever wrote through.

R8 of GOAL_REPAIR_2026-08-23, unblocked by R14.

`ontology_value_types` shipped 765 lines: two tables, seven routes, a constraint
engine covering nine families, and an immutable version-snapshot classifier. Its
one integration point with the rest of the ontology was a `value_type_id` on a
property spec, and **no route, migration, frontend file, script or plugin ever
wrote one**. `_find_consumers` scanned for a key nothing produced, so it could
only ever return an empty list. The subsystem was unwired, not half-wired.

Deleting it was blocked until now for a reason that had nothing to do with value
types: twenty-seven suite scripts asserted the migration head as a literal, so any
revision reddened them all. R14 removed that lock, and this is the first revision
past it.

`ix_value_types_id` and `ix_value_type_versions_id` are not dropped here.
`0041_drop_redundant_pk_indexes` derives redundant single-column primary-key
indexes from the live schema and has already removed them on any database at that
head or later; naming them unconditionally would fail there. The downgrade does
not recreate them either, for the same reason -- restoring an index that 0041
exists to remove would leave the schema inconsistent with the head it claims.

Revision ID: 0043_drop_orphaned_value_types
Revises: 0042_stream_outer_joins
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0043_drop_orphaned_value_types"
down_revision = "0042_stream_outer_joins"
branch_labels = None
depends_on = None


def _has_table(bind, name: str) -> bool:
    return sa.inspect(bind).has_table(name)


def _has_index(bind, table: str, name: str) -> bool:
    if not _has_table(bind, table):
        return False
    return any(index["name"] == name for index in sa.inspect(bind).get_indexes(table))


def upgrade() -> None:
    bind = op.get_bind()
    # Guarded because this chain is applied twice in CI to prove idempotence, and
    # because 0041 may already have taken the primary-key indexes.
    if _has_index(bind, "value_type_versions", "ix_value_type_versions_value_type_id"):
        op.drop_index("ix_value_type_versions_value_type_id", table_name="value_type_versions")
    if _has_table(bind, "value_type_versions"):
        op.drop_table("value_type_versions")
    if _has_table(bind, "value_types"):
        op.drop_table("value_types")


def downgrade() -> None:
    bind = op.get_bind()
    if not _has_table(bind, "value_types"):
        op.create_table(
            "value_types",
            sa.Column("id", sa.String(), nullable=False),
            sa.Column("display_name", sa.String(), nullable=False),
            sa.Column("base_type", sa.String(), nullable=False),
            sa.Column("constraints", sa.JSON(), nullable=False),
            sa.Column("struct_fields", sa.JSON(), nullable=False),
            sa.Column("version", sa.Integer(), nullable=False),
            sa.Column("description", sa.String(), nullable=True),
            sa.Column("deprecated", sa.Boolean(), nullable=False),
            sa.Column("created_at", sa.Integer(), nullable=False),
            sa.Column("updated_at", sa.Integer(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
        )
    if not _has_table(bind, "value_type_versions"):
        op.create_table(
            "value_type_versions",
            sa.Column("id", sa.String(), nullable=False),
            sa.Column("value_type_id", sa.String(), nullable=False),
            sa.Column("version", sa.Integer(), nullable=False),
            sa.Column("base_type", sa.String(), nullable=False),
            sa.Column("constraints", sa.JSON(), nullable=False),
            sa.Column("struct_fields", sa.JSON(), nullable=False),
            sa.Column("description", sa.String(), nullable=True),
            sa.Column("change_type", sa.String(), nullable=False),
            sa.Column("change_reasons", sa.JSON(), nullable=False),
            sa.Column("affected_consumers", sa.JSON(), nullable=False),
            sa.Column("created_at", sa.Integer(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
        )
    if not _has_index(bind, "value_type_versions", "ix_value_type_versions_value_type_id"):
        op.create_index("ix_value_type_versions_value_type_id", "value_type_versions",
                        ["value_type_id"], unique=False)

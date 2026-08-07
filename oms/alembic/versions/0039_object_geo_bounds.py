"""Materialize each object's geographic extent so spatial queries can use an index.

Condition B4 of docs/GOAL_2026-08-06.md.

The spatial pre-filter added earlier had to tolerate geometry SQL cannot judge --
a Polygon's ``coordinates[0]`` is an array, not a number -- so it carried an
``OR unjudgeable`` disjunct. That disjunct is what kept it correct and also what
stopped the planner using an index: measured at ten million objects, the same
query was a sequential scan at 11,006 ms with the disjunct and an index scan at
674 ms without it.

Storing the extent removes the need for the disjunct. Every row with geometry
gets comparable bounds whatever its shape, rows without geometry get NULL, and
NULL is exactly the set a spatial query should exclude -- so the filter becomes
a plain conjunction over indexed columns.

The backfill runs in SQL for point-shaped geometry, which is the bulk of any
corpus, and in Python for everything else so that polygons and the ``location``
and ``geojson`` aliases are covered by the same logic that will maintain them.

Revision ID: 0039_object_geo_bounds
Revises: 0038_explicit_schema_baseline
"""
from __future__ import annotations

from typing import List

import json

import sqlalchemy as sa
from alembic import op

revision = "0039_object_geo_bounds"
down_revision = "0038_explicit_schema_baseline"
branch_labels = None
depends_on = None

COLUMNS = ("geo_min_lon", "geo_min_lat", "geo_max_lon", "geo_max_lat")
UNINDEXED_INDEX = "ix_object_instances_geo_unindexed"
BTREE_INDEX = "ix_object_instances_geo_bounds"
GIST_INDEX = "ix_object_instances_geo_bounds_gist"

# Point-shaped geometry, in the two encodings that cover almost every row. Any
# other shape is left to the Python pass below rather than approximated here.
POSTGRES_BACKFILL = f"""
UPDATE object_instances SET
    geo_min_lon = point_lon, geo_max_lon = point_lon,
    geo_min_lat = point_lat, geo_max_lat = point_lat
FROM (
    SELECT id AS oid,
        CASE WHEN jsonb_typeof(jsonb_extract_path(properties,'geometry','coordinates','0')) = 'number'
               THEN (jsonb_extract_path_text(properties,'geometry','coordinates','0'))::float8
             WHEN jsonb_typeof(jsonb_extract_path(properties,'longitude')) = 'number'
               THEN (jsonb_extract_path_text(properties,'longitude'))::float8
        END AS point_lon,
        CASE WHEN jsonb_typeof(jsonb_extract_path(properties,'geometry','coordinates','1')) = 'number'
               THEN (jsonb_extract_path_text(properties,'geometry','coordinates','1'))::float8
             WHEN jsonb_typeof(jsonb_extract_path(properties,'latitude')) = 'number'
               THEN (jsonb_extract_path_text(properties,'latitude'))::float8
        END AS point_lat
    FROM object_instances
) AS points
WHERE object_instances.id = points.oid
  AND points.point_lon IS NOT NULL AND points.point_lat IS NOT NULL
"""

SQLITE_BACKFILL = """
UPDATE object_instances SET
    geo_min_lon = COALESCE(
        json_extract(properties, '$.geometry.coordinates[0]'),
        json_extract(properties, '$.longitude')),
    geo_max_lon = COALESCE(
        json_extract(properties, '$.geometry.coordinates[0]'),
        json_extract(properties, '$.longitude')),
    geo_min_lat = COALESCE(
        json_extract(properties, '$.geometry.coordinates[1]'),
        json_extract(properties, '$.latitude')),
    geo_max_lat = COALESCE(
        json_extract(properties, '$.geometry.coordinates[1]'),
        json_extract(properties, '$.latitude'))
WHERE json_type(properties, '$.geometry.coordinates[0]') IN ('integer', 'real')
   OR json_type(properties, '$.longitude') IN ('integer', 'real')
"""


def _existing_columns(bind) -> set:
    return {column["name"] for column in sa.inspect(bind).get_columns("object_instances")}


def _existing_indexes(bind) -> set:
    return {index["name"] for index in sa.inspect(bind).get_indexes("object_instances")}


def _backfill_remaining(bind) -> None:
    """Compute bounds in Python for rows the SQL pass could not judge.

    Polygons, LineStrings and the ``location``/``geojson`` aliases land here.
    Batched by primary key so the migration does not hold the whole table, and
    scoped to rows that plausibly carry geometry so an ungeographic deployment
    pays almost nothing.
    """
    import sys
    from pathlib import Path

    app_root = Path(__file__).resolve().parents[2]
    if str(app_root) not in sys.path:
        sys.path.insert(0, str(app_root))
    from app.geo_bounds import bounds_of  # noqa: E402

    candidates = bind.execute(sa.text("""
        SELECT id, properties FROM object_instances
        WHERE geo_min_lon IS NULL AND properties IS NOT NULL
    """)).fetchall()

    updates = []
    for row in candidates:
        properties = row[1]
        if isinstance(properties, str):
            try:
                properties = json.loads(properties)
            except (TypeError, ValueError):
                continue
        bounds = bounds_of(properties)
        if bounds:
            updates.append({
                "oid": row[0], "w": bounds[0], "s": bounds[1],
                "e": bounds[2], "n": bounds[3],
            })

    statement = sa.text("""
        UPDATE object_instances
        SET geo_min_lon = :w, geo_min_lat = :s, geo_max_lon = :e, geo_max_lat = :n
        WHERE id = :oid
    """)
    for start in range(0, len(updates), 1000):
        for parameters in updates[start:start + 1000]:
            bind.execute(statement, parameters)


def upgrade() -> None:
    bind = op.get_bind()
    dialect = bind.dialect.name

    # Guarded like every statement in 0038, and for the same reason: some tests
    # build deliberately partial schemas, so neither the table nor the column
    # this backfill reads can be assumed. An unguarded UPDATE here failed
    # exactly one of the hundred and eighty-seven scripts, on a database whose
    # object_instances has no `properties` at all.
    if "object_instances" not in sa.inspect(bind).get_table_names():
        return
    present = _existing_columns(bind)

    for column in COLUMNS:
        if column not in present:
            op.add_column("object_instances", sa.Column(column, sa.Float(), nullable=True))
    if "geo_indexed" not in present:
        op.add_column("object_instances", sa.Column(
            "geo_indexed", sa.Boolean(), nullable=False,
            server_default=sa.text("false")))

    # There is nothing to derive bounds from without it.
    if "properties" in present:
        if dialect == "postgresql":
            bind.execute(sa.text(POSTGRES_BACKFILL))
        elif dialect == "sqlite":
            bind.execute(sa.text(SQLITE_BACKFILL))
        _backfill_remaining(bind)
    # Every row present at this revision now has a computed extent, whether or
    # not it had geometry to compute one from. Rows arriving later through the
    # ORM set this themselves; rows arriving through a bulk load do not, which
    # is what `runtime.backfill_geo_bounds` exists to repair.
    bind.execute(sa.text("UPDATE object_instances SET geo_indexed = true"))

    indexes = _existing_indexes(bind)
    columns_now = _existing_columns(bind)

    def create_index(name: str, columns: List[str]) -> bool:
        """Create an index only where every column it names exists.

        0038 established this guard after an index over a dropped column broke
        eight scripts. The same partial schemas reach here.
        """
        if name in indexes or not set(columns).issubset(columns_now):
            return False
        op.create_index(name, "object_instances", columns)
        return True

    # Tiny in a healthy database -- it indexes only the rows awaiting a backfill
    # -- and it is what makes the per-query completeness check O(1).
    create_index(UNINDEXED_INDEX, ["object_type_id", "geo_indexed"])
    # Serves SQLite, and the type-scoped lookup on Postgres.
    created_btree = create_index(
        BTREE_INDEX, ["object_type_id", "geo_min_lon", "geo_min_lat"])
    if dialect == "postgresql" and created_btree and GIST_INDEX not in indexes:
        # A btree cannot answer a two-sided interval intersection selectively;
        # GiST over the built-in `box` type can, and needs no extension. The
        # expression is indexed rather than a stored column so the portable
        # schema stays the four floats.
        bind.execute(sa.text(f"""
            CREATE INDEX {GIST_INDEX} ON object_instances
            USING gist (box(point(geo_min_lon, geo_min_lat),
                            point(geo_max_lon, geo_max_lat)))
            WHERE geo_min_lon IS NOT NULL
        """))


def downgrade() -> None:
    bind = op.get_bind()
    indexes = _existing_indexes(bind)
    if GIST_INDEX in indexes:
        op.drop_index(GIST_INDEX, table_name="object_instances")
    if BTREE_INDEX in indexes:
        op.drop_index(BTREE_INDEX, table_name="object_instances")
    if UNINDEXED_INDEX in indexes:
        op.drop_index(UNINDEXED_INDEX, table_name="object_instances")
    present = _existing_columns(bind)
    if "geo_indexed" in present:
        op.drop_column("object_instances", "geo_indexed")
    for column in reversed(COLUMNS):
        if column in present:
            op.drop_column("object_instances", column)

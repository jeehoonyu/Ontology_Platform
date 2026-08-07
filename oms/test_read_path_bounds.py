"""Object-set reads must cost a page, and must return exactly what they did before.

Two independent claims, because the fix for GOAL2-007 could fail either way:

  Boundedness  A filtered read, a facet aggregation and a spatial query must not
               hold the object type in memory. Measured as the high-water mark
               of the session identity map, which is deterministic -- unlike a
               timing or an RSS reading, it does not vary with the host.

  Equivalence  Pushing predicates into SQL changes which engine decides whether
               a row matches, and the two engines disagree in ways that are easy
               to miss. `True == 1` in Python; `'true'::jsonb = '1'::jsonb` is
               false. `1 == "1"` is false in Python; `('{"a":1}'::jsonb->>'a')
               = '1'` is true. Each case below is one of those disagreements.

Both were seen to fail before the fix: the boundedness assertions reported the
full corpus in the identity map, and the equivalence cases are the ones that
would have silently changed which rows came back.

  python oms/test_read_path_bounds.py
"""
import os
import tempfile

# Runs on whatever DATABASE_URL names, defaulting to a throwaway SQLite file so
# the suite stays self-contained. Point it at Postgres to exercise the branches
# SQLite never reaches:
#
#   DATABASE_URL=postgresql+psycopg2://... python oms/test_read_path_bounds.py
#
# That is not optional diligence. Both dialect-specific faults in this code --
# `.contains()` resolving to string LIKE, and `.astext` not existing on a
# with_variant column -- were found only by running it there, after every
# SQLite assertion was green.
tmpdir = tempfile.TemporaryDirectory()
if not os.environ.get("DATABASE_URL"):
    os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tmpdir.name, 'read_path.db')}"

from sqlalchemy import event  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app import models, models_action  # noqa: E402
from app.database import SessionLocal, engine  # noqa: E402
from app import runtime  # noqa: E402

models.Base.metadata.create_all(bind=engine)
models_action.Base.metadata.create_all(bind=engine)

TYPE_ID = "bounds_asset"
CORPUS = 4_000
# A page plus a stream batch plus slack. The point is that the ceiling does not
# move with the corpus, so any constant comfortably below CORPUS proves it.
IDENTITY_MAP_CEILING = 1_500

failures = []


def check(condition, message):
    if condition:
        print(f"  ok   {message}")
    else:
        print(f"  FAIL {message}")
        failures.append(message)


class IdentityMapWatch:
    """High-water mark of instances the session is holding.

    A read that materializes the object type leaves every row in the identity
    map. A read that streams leaves a batch. The difference is the fix.
    """

    def __init__(self):
        self.peak = 0

    def __enter__(self):
        self._listener = lambda session, instance: self._sample(session)
        event.listen(Session, "loaded_as_persistent", self._listener)
        return self

    def _sample(self, session):
        self.peak = max(self.peak, len(session.identity_map))

    def __exit__(self, *exc):
        event.remove(Session, "loaded_as_persistent", self._listener)
        return False


def seed():
    db = SessionLocal()
    try:
        db.add(models.ObjectType(
            id=TYPE_ID, project_id="default", display_name="Bounds Asset",
            properties={"category": {"type": "string"}}, created_at=0, updated_at=0,
        ))
        db.commit()
        rows = []
        for index in range(CORPUS):
            rows.append({
                "id": f"bounds_{index:07d}", "project_id": "default",
                "object_type_id": TYPE_ID,
                "properties": {
                    "category": f"category_{index % 20}",
                    "risk": index % 101,
                    "latitude": 37.0 + (index % 1000) / 10000.0,
                    "longitude": -122.0 - (index % 1000) / 10000.0,
                },
                "source_asset_id": None, "materialization_id": None,
                "is_active": True, "retired_at": None, "lineage": {},
                "created_at": index, "updated_at": index,
            })
        db.execute(models.ObjectInstance.__table__.insert(), rows)
        db.commit()
    finally:
        db.close()


def seed_edge_cases():
    """Rows whose property values sit on a Python/SQL disagreement."""
    db = SessionLocal()
    try:
        db.add(models.ObjectType(
            id="edge_asset", project_id="default", display_name="Edge Asset",
            properties={}, created_at=0, updated_at=0,
        ))
        db.commit()
        rows = [
            ("edge_bool_true", {"flag": True, "code": "x"}),
            ("edge_int_one", {"flag": 1, "code": "x"}),
            ("edge_str_one", {"code": "1"}),
            ("edge_int_num_one", {"code": 1}),
            ("edge_float_one", {"code": 1.0}),
            ("edge_null", {"code": None}),
            ("edge_absent", {"other": "y"}),
            ("edge_numeric_string", {"score": "5"}),
            ("edge_numeric_real", {"score": 5}),
            ("edge_list", {"tags": ["a", "b"]}),
        ]
        db.execute(models.ObjectInstance.__table__.insert(), [
            {"id": row_id, "project_id": "default", "object_type_id": "edge_asset",
             "properties": properties, "source_asset_id": None,
             "materialization_id": None, "is_active": True, "retired_at": None,
             "lineage": {}, "created_at": 0, "updated_at": 0}
            for row_id, properties in rows
        ])
        db.commit()
    finally:
        db.close()


def ids(result):
    return sorted(item["id"] for item in result["objects"])


def matching_ids(filters, limit=100):
    db = SessionLocal()
    try:
        return ids(runtime.query_object_set(
            db, object_type_id="edge_asset", filters=filters, limit=limit))
    finally:
        db.close()


def boundedness():
    print("\nBoundedness -- a read must not hold the object type")

    db = SessionLocal()
    try:
        with IdentityMapWatch() as watch:
            result = runtime.query_object_set(
                db, object_type_id=TYPE_ID, filters={"category": "category_3"},
                limit=50, with_total=True)
        check(result["total"] == CORPUS // 20,
              f"filtered read total is {CORPUS // 20} (got {result['total']})")
        check(result["count"] == 50, f"filtered read returns a page (got {result['count']})")
        check(watch.peak <= IDENTITY_MAP_CEILING,
              f"filtered read held {watch.peak} instances, ceiling {IDENTITY_MAP_CEILING}")
    finally:
        db.close()

    # An equality filter pushes into SQL on SQLite, so the case above would pass
    # on this dialect even unfixed -- and that is precisely the asymmetry that
    # made Postgres the worse dialect while the tests all ran on SQLite. An
    # ordered comparison never pushes down (`_compare_filter` coerces with
    # float()), so this case exercises the Python pass on every dialect.
    db = SessionLocal()
    try:
        with IdentityMapWatch() as watch:
            result = runtime.query_object_set(
                db, object_type_id=TYPE_ID, filters={"risk": {"gt": 50}},
                limit=50, with_total=True)
        check(result["count"] == 50,
              f"unpushable filtered read returns a page (got {result['count']})")
        check(watch.peak <= IDENTITY_MAP_CEILING,
              f"unpushable filtered read held {watch.peak} instances, "
              f"ceiling {IDENTITY_MAP_CEILING}")
    finally:
        db.close()

    db = SessionLocal()
    try:
        with IdentityMapWatch() as watch:
            result = runtime.aggregate_object_set(
                db, object_type_id=TYPE_ID, group_by="category")
        check(result["total"] == CORPUS, f"facet total is {CORPUS} (got {result['total']})")
        check(len(result["groups"]) == 20, f"facet finds 20 groups (got {len(result['groups'])})")
        check(all(group["count"] == CORPUS // 20 for group in result["groups"]),
              "every facet bucket counts correctly")
        check(watch.peak <= IDENTITY_MAP_CEILING,
              f"facet aggregation held {watch.peak} instances, ceiling {IDENTITY_MAP_CEILING}")
    finally:
        db.close()

    db = SessionLocal()
    try:
        with IdentityMapWatch() as watch:
            result = runtime.spatial_query_objects(
                db, object_type_id=TYPE_ID,
                near={"longitude": -122.05, "latitude": 37.05},
                radius_meters=400, limit=25, include_lineage=False)
        check(result["total"] > 0, f"spatial query matches something (got {result['total']})")
        check(result["count"] == 25, f"spatial query returns a page (got {result['count']})")
        distances = [item["spatial"]["distance_meters"] for item in result["objects"]]
        check(distances == sorted(distances), "spatial results stay ordered by distance")
        check(watch.peak <= IDENTITY_MAP_CEILING,
              f"spatial query held {watch.peak} instances, ceiling {IDENTITY_MAP_CEILING}")
    finally:
        db.close()

    db = SessionLocal()
    try:
        with IdentityMapWatch() as watch:
            rows, total = runtime._logic_object_rows(db, TYPE_ID, {"category": "category_7"}, 10)
        check(total == CORPUS // 20, f"logic rows total is {CORPUS // 20} (got {total})")
        check(len(rows) == 10, f"logic rows honours its limit (got {len(rows)})")
        check(watch.peak <= IDENTITY_MAP_CEILING,
              f"a logic query for 10 rows held {watch.peak} instances, "
              f"ceiling {IDENTITY_MAP_CEILING}")
    finally:
        db.close()


def equivalence():
    print("\nEquivalence -- SQL must decide exactly what Python decided")

    # Python: True == 1. jsonb disagrees, so both storage forms must come back
    # for either filter form, or pushing the predicate down loses rows.
    check(matching_ids({"flag": True}) == ["edge_bool_true", "edge_int_one"],
          "filter True matches stored true and stored 1")
    check(matching_ids({"flag": 1}) == ["edge_bool_true", "edge_int_one"],
          "filter 1 matches stored true and stored 1")

    # Python: 1 != "1". `->>` stringifies and would wrongly match.
    check(matching_ids({"code": "1"}) == ["edge_str_one"],
          "filter '1' matches only the stored string")
    check(matching_ids({"code": 1}) == ["edge_float_one", "edge_int_num_one"],
          "filter 1 matches stored 1 and 1.0, not '1'")

    # A missing key and a JSON null are both absent.
    check(matching_ids({"code": {"exists": True}})
          == ["edge_bool_true", "edge_float_one", "edge_int_num_one",
              "edge_int_one", "edge_str_one"],
          "exists ignores JSON null and missing keys alike")
    check(matching_ids({"code": {"exists": False}})
          == ["edge_absent", "edge_list", "edge_null",
              "edge_numeric_real", "edge_numeric_string"],
          "exists False matches absent, null, and rows without the key")

    # `_compare_filter` coerces with float(), so "5" > 3 in Python. No SQL
    # dialect agrees, which is why ordered comparisons stay in the Python pass.
    check(matching_ids({"score": {"gt": 3}}) == ["edge_numeric_real", "edge_numeric_string"],
          "gt still coerces numeric strings, as it always did")

    # Containment on a nested array must not match a scalar member.
    check(matching_ids({"tags": "a"}) == [],
          "a scalar filter does not match a list-valued property")


def seed_geometry_shapes():
    """One row per geometry encoding the product accepts.

    The bounding-box pre-filter recognises point-shaped geometry only. Every
    other encoding has to survive it by being unjudgeable in SQL and therefore
    passed through to Python -- which is the whole safety argument, and the one
    thing worth testing directly.
    """
    db = SessionLocal()
    try:
        db.add(models.ObjectType(
            id="geo_asset", project_id="default", display_name="Geo Asset",
            properties={}, created_at=0, updated_at=0,
        ))
        db.commit()
        rows = [
            ("geo_point_field", {"geometry": {"type": "Point", "coordinates": [-122.05, 37.05]}}),
            ("geo_scalars", {"longitude": -122.0501, "latitude": 37.0501}),
            # A Polygon's coordinates[0] is an array, not a number: SQL cannot
            # judge it, so it must reach Python rather than be filtered out.
            ("geo_polygon", {"geometry": {"type": "Polygon", "coordinates": [[
                [-122.0503, 37.0499], [-122.0499, 37.0499],
                [-122.0499, 37.0503], [-122.0503, 37.0503],
                [-122.0503, 37.0499]]]}}),
            # `extract_geometry` accepts `location` too; the pre-filter does not
            # enumerate it, so this row must pass through unjudged.
            ("geo_location_alias", {"location": {"type": "Point", "coordinates": [-122.0502, 37.0502]}}),
            ("geo_far_away", {"geometry": {"type": "Point", "coordinates": [2.35, 48.85]}}),
            ("geo_none", {"name": "no geometry at all"}),
        ]
        db.execute(models.ObjectInstance.__table__.insert(), [
            {"id": row_id, "project_id": "default", "object_type_id": "geo_asset",
             "properties": properties, "source_asset_id": None,
             "materialization_id": None, "is_active": True, "retired_at": None,
             "lineage": {}, "created_at": 0, "updated_at": 0}
            for row_id, properties in rows
        ])
        db.commit()
    finally:
        db.close()


def spatial_equivalence():
    print("\nSpatial -- the SQL pre-filter must never drop a row Python would keep")

    db = SessionLocal()
    try:
        near = runtime.spatial_query_objects(
            db, object_type_id="geo_asset",
            near={"longitude": -122.05, "latitude": 37.05},
            radius_meters=500, limit=50, include_lineage=False)
        found = sorted(item["id"] for item in near["objects"])
        check(found == ["geo_location_alias", "geo_point_field", "geo_polygon", "geo_scalars"],
              f"radius query finds every geometry encoding (got {found})")
        check(near["total"] == 4, f"radius total counts them once each (got {near['total']})")

        box = runtime.spatial_query_objects(
            db, object_type_id="geo_asset",
            bbox=[-122.06, 37.04, -122.04, 37.06], limit=50, include_lineage=False)
        found = sorted(item["id"] for item in box["objects"])
        check(found == ["geo_location_alias", "geo_point_field", "geo_polygon", "geo_scalars"],
              f"bbox query finds every geometry encoding (got {found})")

        far = runtime.spatial_query_objects(
            db, object_type_id="geo_asset",
            bbox=[2.0, 48.0, 3.0, 49.0], limit=50, include_lineage=False)
        found = sorted(item["id"] for item in far["objects"])
        check(found == ["geo_far_away"], f"a distant box excludes the near rows (got {found})")

        # Near a pole the enclosing box is unreliable, so `_radius_bounds`
        # declines and the query falls back to the scan. It must still answer.
        polar = runtime.spatial_query_objects(
            db, object_type_id="geo_asset",
            near={"longitude": -122.05, "latitude": 89.9},
            radius_meters=500, limit=50, include_lineage=False)
        check(polar["total"] == 0, f"a polar radius query still answers (got {polar['total']})")
    finally:
        db.close()


def materialized_bounds():
    """The stored extent must never disagree with the properties it describes.

    `spatial_query_objects` filters on these columns and treats NULL as "no
    geometry, cannot match". A stale or missing value therefore does not raise
    -- it removes the object from the map. These check the transitions that
    could produce one.
    """
    print("\nMaterialized bounds -- the stored extent must track the properties")

    # The fixtures above were inserted through SQLAlchemy Core, which bypasses
    # the mapper and so the listener -- exactly what a bulk load does. Those
    # rows are marked unindexed, and the query must still answer correctly from
    # them before any backfill runs. This is the case that would otherwise make
    # objects silently disappear from a map, so it is asserted before the happy
    # path rather than after.
    db = SessionLocal()
    try:
        unindexed = db.query(models.ObjectInstance).filter_by(geo_indexed=False).count()
        check(unindexed > 0, f"bulk-inserted rows are marked unindexed (got {unindexed})")
        before = runtime.spatial_query_objects(
            db, object_type_id="geo_asset",
            bbox=[-122.06, 37.04, -122.04, 37.06], limit=50, include_lineage=False)
        found = sorted(item["id"] for item in before["objects"])
        check(found == ["geo_location_alias", "geo_point_field", "geo_polygon", "geo_scalars"],
              f"unindexed rows are still found, via the scan (got {found})")

        repaired = runtime.backfill_geo_bounds(db)
        check(repaired >= unindexed, f"the backfill repaired {repaired} rows")
        check(db.query(models.ObjectInstance).filter_by(geo_indexed=False).count() == 0,
              "nothing is left unindexed after a backfill")

        after = runtime.spatial_query_objects(
            db, object_type_id="geo_asset",
            bbox=[-122.06, 37.04, -122.04, 37.06], limit=50, include_lineage=False)
        check(sorted(item["id"] for item in after["objects"]) == found,
              "the indexed path returns exactly what the scan returned")
    finally:
        db.close()

    db = SessionLocal()
    try:
        point = db.query(models.ObjectInstance).filter_by(id="geo_point_field").one()
        check(point.geo_min_lon == -122.05 and point.geo_max_lon == -122.05
              and point.geo_min_lat == 37.05 and point.geo_max_lat == 37.05,
              "a Point stores a degenerate box at its own position")

        polygon = db.query(models.ObjectInstance).filter_by(id="geo_polygon").one()
        check(polygon.geo_min_lon is not None and polygon.geo_max_lon > polygon.geo_min_lon,
              "a Polygon stores its full extent, not a point")

        nothing = db.query(models.ObjectInstance).filter_by(id="geo_none").one()
        check(nothing.geo_min_lon is None,
              "an object without geometry stores NULL bounds")

        # The failure that matters: geometry moves and the bounds do not follow.
        moved = db.query(models.ObjectInstance).filter_by(id="geo_point_field").one()
        moved.properties = {"geometry": {"type": "Point", "coordinates": [10.0, 20.0]}}
        db.commit()
        moved = db.query(models.ObjectInstance).filter_by(id="geo_point_field").one()
        check(moved.geo_min_lon == 10.0 and moved.geo_min_lat == 20.0,
              f"moving an object updates its bounds (got {moved.geo_min_lon}, {moved.geo_min_lat})")
        found = runtime.spatial_query_objects(
            db, object_type_id="geo_asset", bbox=[9.0, 19.0, 11.0, 21.0],
            limit=10, include_lineage=False)
        check([item["id"] for item in found["objects"]] == ["geo_point_field"],
              "the moved object is found at its new position")

        # And geometry removed entirely must stop matching, not keep its old box.
        moved.properties = {"name": "geometry removed"}
        db.commit()
        emptied = db.query(models.ObjectInstance).filter_by(id="geo_point_field").one()
        check(emptied.geo_min_lon is None, "removing geometry clears the bounds")

        # Restore, so the sections that follow see the fixture they expect.
        emptied.properties = {"geometry": {"type": "Point", "coordinates": [-122.05, 37.05]}}
        db.commit()
    finally:
        db.close()


def aggregation_equivalence():
    """The pushed-down GROUP BY must agree with the streaming pass, field by field.

    Hand-written expectations were tried first and were wrong twice, in both
    directions -- once claiming a bug that was not there. Comparing the two
    implementations against each other tests the property that actually matters
    and cannot be got wrong by miscounting a fixture: requesting a metric forces
    the streaming path, requesting none takes the SQL path, and for a count the
    two owe identical answers.
    """
    print("\nAggregation -- the pushed-down GROUP BY must equal the streaming pass")

    db = SessionLocal()
    try:
        for field in [None, "flag", "code", "tags", "score", "risk"]:
            for type_id in ["edge_asset", TYPE_ID]:
                pushed = runtime.aggregate_object_set(
                    db, object_type_id=type_id, group_by=field)
                streamed = runtime.aggregate_object_set(
                    db, object_type_id=type_id, group_by=field,
                    metrics=[{"operation": "count", "alias": "n"}])
                pushed_groups = {g["group"]: g["count"] for g in pushed["groups"]}
                streamed_groups = {g["group"]: g["count"] for g in streamed["groups"]}
                label = f"group_by={field!r} on {type_id}"
                check(pushed_groups == streamed_groups,
                      f"{label}: group counts agree"
                      + ("" if pushed_groups == streamed_groups
                         else f" (SQL {pushed_groups} vs Python {streamed_groups})"))
                check(pushed["total"] == streamed["total"],
                      f"{label}: totals agree ({pushed['total']} vs {streamed['total']})")
    finally:
        db.close()


FIXTURE_TYPES = (TYPE_ID, "edge_asset", "geo_asset")


def teardown():
    """Leave a shared database as it was found.

    Harmless against the default throwaway SQLite file, and necessary against a
    real Postgres, which this now runs on.
    """
    db = SessionLocal()
    try:
        db.query(models.ObjectInstance).filter(
            models.ObjectInstance.object_type_id.in_(FIXTURE_TYPES)
        ).delete(synchronize_session=False)
        db.query(models.ObjectType).filter(
            models.ObjectType.id.in_(FIXTURE_TYPES)
        ).delete(synchronize_session=False)
        db.commit()
    finally:
        db.close()


def main():
    print(f"dialect: {engine.dialect.name}")
    teardown()  # a prior interrupted run must not change what this one measures
    try:
        seed()
        seed_edge_cases()
        seed_geometry_shapes()
        boundedness()
        equivalence()
        materialized_bounds()
        spatial_equivalence()
        aggregation_equivalence()
    finally:
        teardown()
    print()
    if failures:
        print(f"{len(failures)} failure(s):")
        for message in failures:
            print(f"  - {message}")
        raise SystemExit(1)
    print(f"Read path bounded and equivalent over {CORPUS} objects "
          f"on {engine.dialect.name}.")


main()

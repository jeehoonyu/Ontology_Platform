"""Measure whether object-set reads are bounded by the page or by the object type.

The Tier B ontology-scale gate reads an object set with no residual filter. No
user-facing surface issues that shape: the Object Explorer sends a filter, its
left rail aggregates facets, and the Operational Map sends a spatial predicate.
Each of those takes a path that materializes the whole object type before any
limit applies, so the gate's bounded p95 says nothing about them.

This measures the four shapes side by side at several cardinalities, in latency
and in peak heap, so the growth curve is measured rather than asserted. It is
the harness for condition B1 of ``docs/GOAL_2026-08-06.md``.

Two rules carried over from ``docs/TIER_B_MEASUREMENT_CONTRACT.md``:

  - The worst observation is the measurement, never the mean. An operator
    experiences the worst case.
  - A shape that matches nothing is not a measurement. The scan still runs, but
    the per-row comparison work does not, and reporting that as the cost of a
    real query understates it. Every shape asserts a non-empty result.

Growth is the gate, not the constant. A host twice as fast halves every number
here and changes nothing about whether a read is bounded.

  python oms/measure_read_path_bounds.py
  python oms/measure_read_path_bounds.py --sizes 100000,1000000
  python oms/measure_read_path_bounds.py --database-url postgresql://...
"""
from __future__ import annotations

import argparse
import math
import os
import random
import statistics
import sys
import tempfile
import time
import tracemalloc
from pathlib import Path
from typing import Any, Callable, Dict, List, Tuple

REPO_ROOT = Path(__file__).resolve().parent.parent

# A tight cluster so the radius query has real matches to score and sort, and a
# dispersed remainder so the scan has non-matching rows to reject.
HUB = (-122.4012, 37.7924)
CLUSTER_EVERY = 50
TYPE_ID = "read_path_asset"

DEFAULT_SIZES = (25_000, 100_000, 400_000)

# Ratchet ceilings from docs/GOAL_2026-08-06.md. Growth is per 10x cardinality.
HEAP_CEILING_MB = 64.0
HEAP_GROWTH_MAX = 1.5
LATENCY_GROWTH_MAX = 2.0


def _bootstrap(database_url: str | None) -> Tuple[Any, Any, Any]:
    """Import the app against a chosen database. Must precede any app import."""
    if database_url:
        os.environ["DATABASE_URL"] = database_url
    elif not os.environ.get("DATABASE_URL"):
        tmpdir = tempfile.mkdtemp(prefix="read-path-bounds-")
        os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tmpdir, 'bounds.db')}"

    sys.path.insert(0, str(REPO_ROOT / "oms"))
    from app import models, models_action  # noqa: E402
    from app.database import SessionLocal, engine  # noqa: E402
    from app import runtime  # noqa: E402

    models.Base.metadata.create_all(bind=engine)
    models_action.Base.metadata.create_all(bind=engine)
    return models, SessionLocal, runtime


def seed(models, SessionLocal, size: int, batch: int = 20_000) -> None:
    db = SessionLocal()
    try:
        db.query(models.ObjectInstance).filter(
            models.ObjectInstance.object_type_id == TYPE_ID
        ).delete(synchronize_session=False)
        db.query(models.ObjectType).filter(models.ObjectType.id == TYPE_ID).delete(
            synchronize_session=False
        )
        db.commit()
        db.add(models.ObjectType(
            id=TYPE_ID, project_id="default", display_name="Read Path Asset",
            properties={
                "status": {"type": "string"},
                "risk_score": {"type": "integer"},
                "geometry": {"type": "geometry"},
            },
            created_at=0, updated_at=0,
        ))
        db.commit()

        rng = random.Random(7)
        rows: List[Dict[str, Any]] = []
        for index in range(size):
            clustered = index % CLUSTER_EVERY == 0
            spread = 0.002 if clustered else 0.4
            rows.append({
                "id": f"{TYPE_ID}_{index}",
                "project_id": "default",
                "object_type_id": TYPE_ID,
                "properties": {
                    "status": "degraded" if index % 3 == 0 else "operational",
                    "risk_score": index % 100,
                    "geometry": {
                        "type": "Point",
                        "coordinates": [
                            HUB[0] + rng.uniform(-spread, spread),
                            HUB[1] + rng.uniform(-spread, spread),
                        ],
                    },
                },
                "source_asset_id": None,
                "materialization_id": None,
                "is_active": True,
                "retired_at": None,
                "lineage": {},
                "created_at": index,
                "updated_at": index,
            })
            if len(rows) >= batch:
                db.execute(models.ObjectInstance.__table__.insert(), rows)
                db.commit()
                rows = []
        if rows:
            db.execute(models.ObjectInstance.__table__.insert(), rows)
        db.commit()
    finally:
        db.close()


def shapes(runtime) -> List[Tuple[str, Callable[[Any], int]]]:
    """Each returns a match count, so an empty result can be rejected."""
    return [
        ("typed read, no filter (the shape the 10M gate measures)",
         lambda db: runtime.query_object_set(
             db, object_type_id=TYPE_ID, limit=50, with_total=False)["count"]),
        ("typed read, one equality filter (the Object Explorer)",
         lambda db: runtime.query_object_set(
             db, object_type_id=TYPE_ID, filters={"status": "degraded"},
             limit=50, with_total=False)["count"]),
        ("facet aggregation (the Explorer's left rail)",
         lambda db: sum(group["count"] for group in runtime.aggregate_object_set(
             db, object_type_id=TYPE_ID, group_by="status")["groups"])),
        ("spatial radius query (the Operational Map)",
         lambda db: runtime.spatial_query_objects(
             db, object_type_id=TYPE_ID,
             near={"longitude": HUB[0], "latitude": HUB[1]},
             radius_meters=500, limit=50, include_lineage=False)["total"]),
    ]


def measure(SessionLocal, fn, repeats: int) -> Tuple[float, float, int]:
    """Worst latency, worst peak heap, and the match count.

    Latency and heap are measured in separate passes on purpose. ``tracemalloc``
    hooks every allocation, and these paths allocate per row, so timing under it
    inflates the very shapes being judged -- by roughly 3x on the scanning ones
    and not at all on the bounded one, which is exactly the wrong direction.
    Measuring them together would report an instrument artifact as a defect and
    send someone to optimize it.
    """
    latencies: List[float] = []
    matched = 0
    for _ in range(repeats):
        db = SessionLocal()
        try:
            start = time.perf_counter()
            matched = fn(db)
            latencies.append((time.perf_counter() - start) * 1000)
        finally:
            db.close()

    peaks: List[float] = []
    for _ in range(repeats):
        db = SessionLocal()
        try:
            tracemalloc.start()
            fn(db)
            peaks.append(tracemalloc.get_traced_memory()[1] / 1024 / 1024)
        finally:
            tracemalloc.stop()
            db.close()

    return max(latencies), max(peaks), matched


def growth(readings: Dict[int, float], sizes: List[int]) -> float:
    """Growth normalized to a 10x cardinality step.

    Normalizing lets the harness run at whatever sizes the host can hold while
    still reporting against one threshold. A bounded read gives x1; a read that
    materializes the type gives x10.
    """
    first, last = sizes[0], sizes[-1]
    if readings[first] <= 0:
        return 0.0
    ratio = readings[last] / readings[first]
    decades = math.log10(last / first)
    return ratio if decades <= 0 else ratio ** (1 / decades)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--sizes", default=",".join(str(s) for s in DEFAULT_SIZES),
                        help="comma-separated object counts")
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--database-url", default=None,
                        help="defaults to a throwaway SQLite file. Postgres is the "
                             "production dialect and has no equality pushdown, so a "
                             "SQLite-only reading is the favorable case")
    args = parser.parse_args()

    sizes = sorted(int(value) for value in args.sizes.split(",") if value.strip())
    if len(sizes) < 2:
        print("At least two sizes are required: the gate is a growth curve.")
        return 2

    models, SessionLocal, runtime = _bootstrap(args.database_url)
    dialect = SessionLocal().get_bind().dialect.name

    latency: Dict[str, Dict[int, float]] = {}
    heap: Dict[str, Dict[int, float]] = {}
    counts: Dict[str, int] = {}

    for size in sizes:
        print(f"seeding {size:,} objects...", flush=True)
        seed(models, SessionLocal, size)
        for label, fn in shapes(runtime):
            worst_ms, worst_mb, matched = measure(SessionLocal, fn, args.repeats)
            if not matched:
                print(f"\n{label} matched nothing at {size:,}. The scan still ran, but "
                      f"the comparison work did not, so this timing would understate "
                      f"the cost of a real query. Fix the fixture, not the threshold.")
                return 2
            latency.setdefault(label, {})[size] = worst_ms
            heap.setdefault(label, {})[size] = worst_mb
            counts[label] = matched

    header = " ".join(f"{size:>11,}" for size in sizes)
    print(f"\nRead path bounds on {dialect}, worst of {args.repeats}\n")
    print(f"{'query shape':<54} {header}   per 10x")
    print("-" * (56 + 12 * len(sizes) + 10))
    print("latency")
    for label, readings in latency.items():
        cells = " ".join(f"{readings[size]:>9.1f}ms" for size in sizes)
        print(f"  {label:<52} {cells}   x{growth(readings, sizes):.1f}")
    print("peak heap")
    for label, readings in heap.items():
        cells = " ".join(f"{readings[size]:>9.1f}MB" for size in sizes)
        print(f"  {label:<52} {cells}   x{growth(readings, sizes):.1f}")

    breaches: List[str] = []
    for label in latency:
        latency_growth = growth(latency[label], sizes)
        heap_growth = growth(heap[label], sizes)
        worst_heap = max(heap[label].values())
        if latency_growth > LATENCY_GROWTH_MAX:
            breaches.append(f"{label}: latency grows x{latency_growth:.1f} per 10x, "
                            f"above x{LATENCY_GROWTH_MAX}")
        if heap_growth > HEAP_GROWTH_MAX:
            breaches.append(f"{label}: heap grows x{heap_growth:.1f} per 10x, "
                            f"above x{HEAP_GROWTH_MAX}")
        if worst_heap > HEAP_CEILING_MB:
            breaches.append(f"{label}: peak heap {worst_heap:.1f} MB, "
                            f"above the {HEAP_CEILING_MB:.0f} MB ceiling")

    print()
    if breaches:
        print("B1 FAIL — reads are bounded by the object type, not by the page:")
        for breach in breaches:
            print(f"  {breach}")
        if dialect == "sqlite":
            print("\n  Measured on SQLite, which has an equality pushdown that Postgres "
                  "does not. Production is worse than this reading.")
        return 1
    print("B1 PASS — every shape is bounded by the page.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

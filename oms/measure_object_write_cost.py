"""What it would cost to give bulk hydration the history every other write has.

R3 leaves three constructions outside the chokepoint. Two of them --
`runtime.hydrate_objects` and `pipeline_builder_ops._execute_ontology_contract` --
are held back by one question that reading cannot answer: `record_object_change`
appends a change event *and* enqueues an outbox row, so routing a bulk hydrate
through it multiplies both by the number of records.

That surface has been expensive before. `a6a4218` found
`POST /pipeline-builder/workers/run-next` issuing 1,006 separate
`INSERT INTO event_outbox` statements on one hydrate -- a before_flush hook firing
once per object because the recorder flushed once per object -- and took the route
from 10,202 statements to 3,200.

So this measures rather than argues, and it measures twice, because
`request_cost.summarize` is right that a repeat count means nothing until you know
how it moves with the data. The rule it is measured against is the one
`audit_request_cost` states: gate the repeated shape, report the total. A cost
that is O(1) in records is affordable however large; one that is O(N) is the
defect that file exists to catch.

  python oms/measure_object_write_cost.py
  python oms/measure_object_write_cost.py --sizes 100,1000,5000
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, List

REPO_ROOT = Path(__file__).resolve().parent.parent


def _measure(size: int, record_changes: bool, production_environment: bool = True) -> Dict[str, Any]:
    """One hydrate-shaped run: construct, snapshot, and optionally record history.

    `production_environment` is not a detail. `_active_revision_id` caches the
    environment row per session, but caches only a *found* one, deliberately, so
    a project that acquires an environment mid-request still sees it. A project
    without one therefore re-queries per record, and a measurement taken on a
    bare project charges history for a lookup a real project pays once. Both are
    measured, because which one is realistic depends on the project.
    """
    from app import models, object_writes, ontology_runtime_v1
    from app.database import SessionLocal, engine
    from app import decision_intelligence
    from app.runtime import now_ts, validate_object_properties
    from request_cost import counting, summarize

    db = SessionLocal()
    now = now_ts()
    type_id = f"widget_{size}_{int(record_changes)}_{int(production_environment)}"
    # One project per run: ontology_environments is unique on (project, name), and
    # a shared project would also share the per-session revision cache between
    # variants, which is the thing being measured.
    project = f"tenant_{type_id}"
    db.add(models.ObjectType(
        id=type_id, display_name="Widget", description="",
        properties={"sku": {"type": "string"}}, project_id=project,
        created_at=now, updated_at=now))
    if production_environment:
        from app.ontology_versioning import OntologyEnvironment

        db.add(OntologyEnvironment(
            id=f"env_{type_id}", project_id=project, name="production",
            current_revision_id=f"rev_{type_id}", previous_revision_id=None,
            updated_by="measurement", updated_at=now))
    db.commit()
    object_type = db.get(models.ObjectType, type_id)

    # Resolved once, the way a loop should: the schema is a per-type fact asked
    # from per-record code, and resolving it per record is its own N.
    resolve = object_writes.schema_resolver(db)

    started = time.perf_counter()
    with counting(engine) as statements:
        for index in range(size):
            properties = {"sku": f"{type_id}-{index}"}
            errors = validate_object_properties(object_type, properties,
                                                schema=resolve(object_type))
            if errors:
                raise AssertionError(errors)
            created = models.ObjectInstance(
                id=f"{type_id}-{index}", project_id=project, object_type_id=type_id,
                properties=properties, source_asset_id=None,
                lineage={"operation": "map_to_ontology"},
                created_at=now, updated_at=now)
            db.add(created)
            decision_intelligence.record_object_snapshot(
                db, created, event_type="pipeline.object.created", actor="pipeline",
                source_type="pipeline_run", source_id="run-1")
            if record_changes:
                ontology_runtime_v1.record_object_change(
                    db, created, before_state={},
                    event_type="pipeline.object.created", actor="pipeline",
                    source_type="pipeline_run", source_id="run-1",
                    evidence={"pipeline_run_id": "run-1"})
        db.commit()
    elapsed_ms = (time.perf_counter() - started) * 1000

    summary = summarize(statements)
    from app.event_outbox import EventOutbox

    outbox_rows = db.query(EventOutbox).count()
    change_rows = db.query(ontology_runtime_v1.ObjectChangeEvent).count()
    db.close()

    return {
        "records": size,
        "change_events_recorded": record_changes,
        "production_environment": production_environment,
        "statements": summary["queries"],
        "distinct_shapes": summary["distinct_shapes"],
        "worst_repeat": summary["worst_repeat"],
        "worst_shape": (summary["repeats"][0]["statement"][:70] if summary["repeats"] else None),
        # The whole point of the exercise: a total says how much, the shapes say
        # what, and only the second one tells you whether it is fixable.
        "repeats": [{"statement": entry["statement"][:96], "count": entry["count"]}
                    for entry in summary["repeats"][:6]],
        "outbox_rows": outbox_rows,
        "change_event_rows": change_rows,
        "elapsed_ms": round(elapsed_ms, 1),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sizes", default="100,1000",
                        help="Record counts to measure, smallest first")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--write-evidence", action="store_true",
                        help="Record the run to docs/object-write-cost-evidence.json")
    args = parser.parse_args()
    sizes = [int(part) for part in args.sizes.split(",") if part.strip()]

    scratch = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
    os.environ["DATABASE_URL"] = f"sqlite:///{Path(scratch.name, 'write-cost.db').as_posix()}"
    os.environ["AUTH_MODE"] = "local"
    os.environ["APP_ENV"] = "test"
    sys.path.insert(0, str(REPO_ROOT / "oms"))

    # The whole app, so every table registers on the shared Base before create_all.
    # event_outbox and ontology_runtime_v1 declare the two tables this measurement
    # is about and neither is reachable from models.py, while importing them alone
    # leaves cross-module foreign keys dangling. audit_request_cost boots the app
    # for the same reason.
    from app import models  # noqa: F401
    from app.main import app  # noqa: F401
    from app.database import engine

    models.Base.metadata.create_all(bind=engine)

    rows: List[Dict[str, Any]] = []
    for size in sizes:
        for record_changes in (False, True):
            rows.append(_measure(size, record_changes, production_environment=True))
    bare = _measure(max(sizes), True, production_environment=False)

    if args.json:
        print(json.dumps(rows, indent=2))
        scratch.cleanup()
        return 0

    print(f"Object write cost, hydrate-shaped, at {' and '.join(str(s) for s in sizes)} records\n")
    print("  (project has a production ontology environment, which is the realistic case)\n")
    print(f"  {'records':>8}  {'history':>8}  {'stmts':>7}  {'shapes':>7}  "
          f"{'worst':>6}  {'outbox':>7}  {'events':>7}  {'ms':>8}")
    for row in rows:
        print(f"  {row['records']:>8}  {('yes' if row['change_events_recorded'] else 'no'):>8}  "
              f"{row['statements']:>7}  {row['distinct_shapes']:>7}  {row['worst_repeat']:>6}  "
              f"{row['outbox_rows']:>7}  {row['change_event_rows']:>7}  {row['elapsed_ms']:>8.1f}")

    print(f"\n  {bare['records']:>8}  {'yes':>8}  {bare['statements']:>7}  "
          f"{bare['distinct_shapes']:>7}  {bare['worst_repeat']:>6}  {bare['outbox_rows']:>7}  "
          f"{bare['change_event_rows']:>7}  {bare['elapsed_ms']:>8.1f}   <- no production environment")

    largest = max(sizes)
    print(f"\nWhat repeats, at {largest} records:")
    for record_changes in (False, True):
        row = next(r for r in rows if r["records"] == largest
                   and r["change_events_recorded"] is record_changes)
        print(f"  {'with history' if record_changes else 'without history'}:")
        for entry in row["repeats"]:
            print(f"      x{entry['count']:<6} {entry['statement']}")

    print("\nHow each number moves with the data:")
    for record_changes in (False, True):
        series = [r for r in rows if r["change_events_recorded"] is record_changes]
        if len(series) < 2:
            continue
        first, last = series[0], series[-1]
        factor = last["records"] / first["records"]
        label = "with history" if record_changes else "without"
        for field in ("statements", "worst_repeat"):
            grew = (last[field] / first[field]) if first[field] else float("inf") if last[field] else 1.0
            verdict = "constant" if grew < 1.5 else (f"linear (x{grew:.1f} for x{factor:.0f} data)"
                                                     if grew >= factor * 0.5 else f"x{grew:.1f}")
            print(f"  {label:>13}  {field:<14} {first[field]:>6} -> {last[field]:>6}   {verdict}")

    if args.write_evidence:
        from tier_b_evidence import build_evidence_provenance

        evidence = {
            # observed_head is None on purpose: this harness builds its schema with
            # create_all, not with the migration chain, so claiming the repository
            # head as observed would be a claim it did not check.
            "provenance": build_evidence_provenance(
                "oms/measure_object_write_cost.py",
                observed_head=None,
                entry_points=["runtime.hydrate_objects",
                              "ontology_runtime_v1.record_object_change",
                              "decision_intelligence.record_object_snapshot"],
                request_shapes=["bulk map_to_ontology hydration"]),
            "note": ("What giving bulk hydration the history every other write path has "
                     "would cost. Read against audit_request_cost's rule: gate the "
                     "repeated shape, report the total."),
            "stale_after": "migration head",
            "measurements": rows,
            "without_production_environment": bare,
        }
        target = REPO_ROOT / "docs" / "object-write-cost-evidence.json"
        target.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(f"\nEvidence written to {target.relative_to(REPO_ROOT)}")

    scratch.cleanup()
    return 0


if __name__ == "__main__":
    sys.exit(main())

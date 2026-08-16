"""Ratchet: no route may run one statement shape over and over.

`/health/ready` issued 275 catalog round-trips per call and was found by
accident, because it is the one endpoint an unrelated gate happens to be defined
on. `_ensure_migration_records` ran one `SELECT` per migration on four routes.
`maintenance_summary` counted six object types with six statements, and the
route that called it called it twice. None of those were visible in the source;
all of them were obvious the moment anyone counted statements.

**What is gated and what is only reported.** The gate is the *repeated shape*:
one statement executed many times in a single request is the N+1 signature, and
it is what none of the fixed defects could have hidden from. Totals are reported
and never gated, because a large total is often correct -- `/project/export`
issues 139 queries and 138 of them are distinct, one per exported collection,
which is what exporting everything costs. Gating totals would fail that endpoint
forever and teach everyone to route around this file.

That is the rule this project has now learned three times: gate the thing
ordinary work does not do, report the thing it does.

  python oms/audit_request_cost.py                  # check against the baseline
  python oms/audit_request_cost.py --write-baseline # re-record it deliberately

The baseline is `docs/request-cost-baseline.json`. Rewriting it is a commit with
an author and a diff, which is the point: a number that moves silently is not a
ratchet.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Tuple

REPO_ROOT = Path(__file__).resolve().parent.parent
BASELINE = REPO_ROOT / "docs" / "request-cost-baseline.json"

# No route may execute one statement shape more than this many times. Chosen
# from the measured surface after the loops were removed: the worst remaining is
# 4, so 6 leaves room for an honest change and still catches a ×13 or a ×32 the
# day it lands. This is the ratchet -- the count of routes above it must stay 0.
REPEAT_CEILING = 6

# Routes that reach outside the process block on their own timeouts, and
# streaming routes never return a body at all. Neither says anything about
# database cost. `/events/stream` stalled the first census at route 52 of 154.
OUTBOUND = ("connector", "webhook", "model", "gateway", "egress", "kafka", "s3",
            "minio", "sftp", "plugin", "oidc", "sso", "login", "metrics", "auth")
STREAMING = ("stream", "sse", "watch", "follow", "tail", "subscribe")


def measure_surface() -> Dict[str, Dict[str, int]]:
    """Boot the app on a scratch database and cost every collection route.

    A temporary SQLite file, never the caller's DATABASE_URL: an audit that
    measures whatever database happens to be configured measures the machine it
    runs on rather than the code it is checking.
    """
    scratch = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
    os.environ["DATABASE_URL"] = f"sqlite:///{Path(scratch.name, 'request-cost.db').as_posix()}"
    os.environ["AUTH_MODE"] = "local"
    os.environ["APP_ENV"] = "test"
    sys.path.insert(0, str(REPO_ROOT / "oms"))

    from fastapi.routing import APIRoute
    from fastapi.testclient import TestClient

    from app.database import engine
    from app.main import app
    from request_cost import counting, summarize

    client = TestClient(app)
    # The first call creates the runtime schema and populates one-off records.
    # Measuring it would record setup as the cost of serving.
    client.get("/health/live")
    client.get("/health/ready")

    paths = sorted({
        route.path for route in app.routes
        if isinstance(route, APIRoute) and "GET" in route.methods and "{" not in route.path
        and 1 <= route.path.strip("/").count("/") + 1 <= 2
        and not any(word in route.path.lower() for word in OUTBOUND + STREAMING)
    })

    measured: Dict[str, Dict[str, int]] = {}
    for path in paths:
        try:
            client.get(path)  # warm, so first-call setup is not charged here
            with counting(engine) as collected:
                response = client.get(path)
        except Exception:
            continue
        if response.status_code >= 500:
            continue
        summary = summarize(collected)
        measured[path] = {
            "queries": summary["queries"],
            "distinct_shapes": summary["distinct_shapes"],
            "worst_repeat": summary["worst_repeat"],
        }
    scratch.cleanup()
    return measured


def load_baseline() -> Dict[str, Dict[str, int]]:
    if not BASELINE.exists():
        return {}
    try:
        payload = json.loads(BASELINE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    routes = payload.get("routes")
    return routes if isinstance(routes, dict) else {}


def compare(measured: Dict[str, Dict[str, int]],
            baseline: Dict[str, Dict[str, int]]) -> Tuple[List[str], List[str]]:
    """Return (failures, notes). Only the repeated shape can fail."""
    failures = [
        f"{path} runs one statement shape {row['worst_repeat']} times "
        f"(ceiling {REPEAT_CEILING})"
        for path, row in sorted(measured.items())
        if row["worst_repeat"] > REPEAT_CEILING
    ]

    notes: List[str] = []
    for path, row in sorted(measured.items()):
        recorded = baseline.get(path)
        if recorded is None:
            notes.append(f"new route {path}: {row['queries']} queries, "
                         f"worst repeat {row['worst_repeat']}")
            continue
        delta = row["queries"] - recorded.get("queries", 0)
        if delta:
            notes.append(f"{path}: {recorded.get('queries')} -> {row['queries']} queries "
                         f"({delta:+d})")
        # Shape drift with no query drift is a real signal and used to be
        # invisible here. Pushing a project filter into 26 child collections
        # rewrote their SQL without changing how many statements ran, so
        # `/project/readiness` went from 160 distinct shapes to 163 and this
        # reported nothing. The baseline records the field; it should say when
        # it moves.
        shapes = row["distinct_shapes"] - recorded.get("distinct_shapes", 0)
        if shapes and not delta:
            notes.append(f"{path}: same {row['queries']} queries, "
                         f"{recorded.get('distinct_shapes')} -> {row['distinct_shapes']} "
                         f"distinct shapes ({shapes:+d})")
    for path in sorted(set(baseline) - set(measured)):
        notes.append(f"route no longer measured: {path}")
    return failures, notes


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write-baseline", action="store_true",
                        help="Re-record docs/request-cost-baseline.json from this run")
    args = parser.parse_args()

    measured = measure_surface()
    if not measured:
        print("No route was measurable; the audit cannot pass by measuring nothing.")
        return 1

    if args.write_baseline:
        BASELINE.write_text(json.dumps(
            {"note": "Per-request database round-trips. Written by "
                     "oms/audit_request_cost.py --write-baseline.",
             "repeat_ceiling": REPEAT_CEILING,
             "routes": measured}, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        worst = max(row["worst_repeat"] for row in measured.values())
        print(f"Recorded {len(measured)} routes; worst repeated shape is {worst}.")
        return 0

    baseline = load_baseline()
    failures, notes = compare(measured, baseline)

    ranked = sorted(measured.items(), key=lambda item: -item[1]["queries"])
    print(f"Request cost over {len(measured)} collection routes "
          f"(ceiling: one shape at most {REPEAT_CEILING} times)\n")
    print("  most expensive:")
    for path, row in ranked[:8]:
        print(f"    {row['queries']:5d} queries, {row['distinct_shapes']:4d} shapes, "
              f"worst repeat {row['worst_repeat']:3d}  {path}")

    if notes:
        print(f"\n  drift, reported and not gated ({len(notes)}):")
        for note in notes[:20]:
            print(f"    {note}")
        if len(notes) > 20:
            print(f"    ... and {len(notes) - 20} more")

    if failures:
        print(f"\nRATCHET BROKEN: {len(failures)} route(s) above the repeat ceiling:")
        for failure in failures:
            print(f"  {failure}")
        return 1
    worst = max(row["worst_repeat"] for row in measured.values())
    print(f"\nNo route repeats a statement shape more than {worst} times "
          f"(ceiling {REPEAT_CEILING}).")
    return 0


if __name__ == "__main__":
    from enforcement_runs import recording

    raise SystemExit(recording("audit_request_cost", main))

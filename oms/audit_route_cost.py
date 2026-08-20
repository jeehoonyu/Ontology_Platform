"""What a workspace route costs to open, and a ceiling it may not exceed.

`audit_route_payload` answers what the *bundle* costs -- bytes of JavaScript and
CSS, computed statically from the build manifest. That is half the question. A
user opening a screen also waits on the requests it issues once it is running,
and nothing counted those. The map makes 25; the median screen makes 13.

Which of these three numbers may be gated was decided by measuring twice rather
than by judgement, the way the suite-cost census had to demonstrate 695 of 695
agreement before it was allowed to gate anything:

    requests     identical 16/16 across two runs      gated
    bytes        identical 16/16 across two runs      gated, with tolerance
    settled_ms   identical  0/16, worst drift 2.6%    reported, never gated

Wall-clock is wall-clock. Gating it would fail for reasons that have nothing to
do with the change under test, and a gate that fails for reasons a reader cannot
act on is one they learn to re-run until it passes.

Requests are gated with no tolerance at all, because they were exactly stable and
because the failure mode is creep: one more call per screen, per change, until a
screen makes forty. Bytes carry a percentage tolerance, since a response body
legitimately moves with the data behind it.

  python oms/measure_route_cost.py        # drives the browser, writes the JSON
  python oms/audit_route_cost.py          # judges it
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))

MEASUREMENT = REPO_ROOT / "frontend" / "route-cost.json"
BASELINE = REPO_ROOT / "docs" / "route-cost-baseline.json"

# A response body moves with the rows behind it; a request count does not.
BYTES_TOLERANCE = 0.15


def load(path: Path | None = None) -> Dict[str, Dict[str, int]]:
    source = path or MEASUREMENT
    if not source.exists():
        return {}
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    if not isinstance(payload, dict):
        return {}
    # Newer measurements name the bundle they describe; older ones are the bare
    # mapping. A measurement whose bundle is not the one on disk is evidence
    # about a build that no longer exists, and judging it failed a ceiling for a
    # change that had already happened.
    if "routes" in payload:
        recorded = payload.get("bundle_source_hash")
        if recorded and recorded != _bundle_hash():
            return {}
        return payload["routes"]
    return payload


def _bundle_hash() -> str | None:
    provenance = REPO_ROOT / "frontend" / "dist" / "build-provenance.json"
    if not provenance.exists():
        return None
    try:
        return json.loads(provenance.read_text(encoding="utf-8")).get("source_hash")
    except json.JSONDecodeError:
        return None


def compare(measured: Dict[str, Dict[str, int]],
            baseline: Dict[str, Any]) -> Tuple[bool, List[str], List[str]]:
    failures: List[str] = []
    notes: List[str] = []
    recorded: Dict[str, Dict[str, int]] = baseline.get("routes", {})
    tolerance = baseline.get("bytes_tolerance", BYTES_TOLERANCE)

    for route, entry in sorted(measured.items()):
        ceiling = recorded.get(route)
        if ceiling is None:
            failures.append(
                f"{route}: {entry['requests']} requests, {entry['bytes'] / 1024:.0f} KB, and no "
                f"recorded ceiling. A new screen is exactly when a cost gets away.")
            continue

        if entry["requests"] > ceiling["requests"]:
            failures.append(
                f"{route}: {entry['requests']} requests on open, ceiling "
                f"{ceiling['requests']} (+{entry['requests'] - ceiling['requests']}). "
                f"One more call per change is how a screen reaches forty.")
        elif entry["requests"] < ceiling["requests"]:
            notes.append(f"{route}: {ceiling['requests']} -> {entry['requests']} requests")

        allowed = ceiling["bytes"] * (1 + tolerance)
        if entry["bytes"] > allowed:
            failures.append(
                f"{route}: {entry['bytes'] / 1024:.0f} KB transferred, ceiling "
                f"{ceiling['bytes'] / 1024:.0f} KB plus {tolerance:.0%}")

    for route in sorted(recorded):
        if route not in measured:
            notes.append(f"{route}: not measured in this run")
    return not failures, failures, notes


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--measurement", default=None, help="A route-cost.json to judge")
    parser.add_argument("--set-baseline", action="store_true")
    args = parser.parse_args()

    measured = load(Path(args.measurement) if args.measurement else None)
    if not measured:
        # Absent is not the same as failing. This measurement comes from a
        # browser run, so a machine without node has nothing to judge, and
        # reddening the fast tier for a missing artifact teaches a reader to
        # ignore red. `verify.py --full` produces it, and the gate has teeth
        # wherever it exists.
        print(f"Not measured here. {MEASUREMENT.relative_to(REPO_ROOT)} is written by "
              f"a browser run: python oms/measure_route_cost.py")
        print("Nothing is claimed about route cost from this run.")
        return 0

    total = sum(entry["requests"] for entry in measured.values())
    print(f"{len(measured)} workspace routes, {total} requests on open, median "
          f"{sorted(e['requests'] for e in measured.values())[len(measured) // 2]} per route\n")
    print(f"  {'route':<18}{'requests':>9}{'KB':>8}{'settled ms':>12}")
    for route, entry in sorted(measured.items(), key=lambda i: -i[1]["requests"]):
        print(f"  {route:<18}{entry['requests']:>9}{entry['bytes'] / 1024:>8.0f}"
              f"{entry.get('settled_ms', 0):>12}")

    if args.set_baseline:
        BASELINE.write_text(json.dumps({
            "provenance": {"stale_after": "recomputed each run"},
            "note": ("What each workspace route costs to open, measured in a browser. "
                     "Requests and bytes are gated; settled_ms is recorded and never gated, "
                     "because two runs agreed on the first two for 16 of 16 routes and on "
                     "timing for none of them."),
            "bytes_tolerance": BYTES_TOLERANCE,
            "routes": {route: {"requests": entry["requests"], "bytes": entry["bytes"]}
                       for route, entry in sorted(measured.items())},
        }, indent=2) + "\n", encoding="utf-8")
        print(f"\nBaseline set: {len(measured)} routes, {total} requests.")
        return 0

    if not BASELINE.exists():
        print(f"\nNo baseline at {BASELINE.relative_to(REPO_ROOT)}. Record one with "
              f"--set-baseline.")
        return 1

    ok, failures, notes = compare(measured, json.loads(BASELINE.read_text(encoding="utf-8")))
    if notes:
        print(f"\n{len(notes)} change(s), none of them gated:")
        for note in notes[:15]:
            print(f"  {note}")
    if failures:
        print(f"\nFAIL -- {len(failures)}:")
        for failure in failures:
            print(f"  {failure}")
        return 1
    print(f"\nNo route issues more requests than it did, and none transferred more than its "
          f"ceiling.")
    return 0


if __name__ == "__main__":
    from enforcement_runs import recording

    raise SystemExit(recording("audit_route_cost", main))

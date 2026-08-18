"""Gate the cost of every route the suite touches, writes included.

`audit_request_cost.py` walks 151 collection GET routes against a scratch, empty
database. It is fast, it is deterministic, and 547 write routes are outside it --
including the worst repeated shape in this codebase, a `POST` that repeats one
`INSERT INTO event_outbox` a thousand times in a single request while holding a
transaction open across all of it. A ceiling that every gated route passes, next
to an ungated route at ×1006, is a ceiling measuring the wrong surface.

The obstacle was never the ceiling, it was the payloads: a GET with no path
parameter can be called by a machine walking the route table, and a POST cannot.
The suite already issues those writes with bodies the routes accept, so the
measurement condition here is the suite itself -- `measure_suite_cost.py`
records one line per request, and this reads the aggregate.

**What is gated and what is merely reported** follows the rule this project has
had to learn once per ratchet: gate the thing ordinary work does not do, report
the thing it does.

  - *Gated:* a route repeating a shape more often than its baseline. Adding a
    query is ordinary; turning a fixed cost into one that repeats is not.
  - *Gated:* a route absent from the baseline that arrives above the ceiling.
    New code is held to the standard, never grandfathered into the debt.
  - *Reported:* statement counts, new routes under the ceiling, improvements.

Statement counts are reported rather than gated because they are not
reproducible enough to gate. Two full censuses agreed on the worst repeat for
**695 of 695** route+method pairs and on the statement count for 692 -- the three
that moved are `/runtime/observability/summary` (83 vs 107), `/jobs/claim` (55 vs
58) and `run-next` (10,203 vs 10,202). A gate on a number that moves on its own
teaches people to re-run it until it passes.

The 33 pairs already above the ceiling are recorded as debt, at the value
measured, and may only go down. That is a weaker claim than the GET ratchet
makes -- there, a violation fails even if the baseline recorded it -- and the
difference is deliberate: this surface starts with real debt on it, and a gate
that fails on day one is a gate someone turns off.

  python oms/measure_suite_cost.py --out costs.jsonl     # ~20 minutes
  python oms/audit_suite_cost.py costs.jsonl

Not a pre-push check. The census runs the whole suite in 225 subprocesses; this
is for the periodic enforcement run, and `audit_request_cost.py` remains the
fast one.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Tuple

REPO_ROOT = Path(__file__).resolve().parent.parent
BASELINE = REPO_ROOT / "docs" / "suite-cost-baseline.json"

# The same ceiling the GET ratchet uses. A route may touch many tables; what it
# may not do is run one statement once per row.
REPEAT_CEILING = 6

# A census that reached almost nothing must not pass by having nothing to say.
# The empty-fixture lesson, applied to the fixture that is the whole suite.
MINIMUM_COVERAGE = 0.90


def aggregate(rows: List[dict]) -> Dict[Tuple[str, str], Dict[str, int]]:
    """Worst observation per route+method, never the mean.

    A route called forty times with one expensive call is a route with an
    expensive call, and averaging is how that disappears.
    """
    grouped: Dict[Tuple[str, str], Dict[str, int]] = defaultdict(
        lambda: {"worst_repeat": 0, "queries": 0, "calls": 0, "worst_shape": None})
    for row in rows:
        key = (row.get("method", "?"), row.get("route", "?"))
        entry = grouped[key]
        entry["calls"] += 1
        entry["queries"] = max(entry["queries"], row.get("queries", 0))
        if row.get("worst_repeat", 0) > entry["worst_repeat"]:
            entry["worst_repeat"] = row["worst_repeat"]
            entry["worst_shape"] = row.get("worst_shape")
    return grouped


def load_census(path: Path) -> List[dict]:
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows


def load_baseline(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def key_of(method: str, route: str) -> str:
    return f"{method} {route}"


def compare(measured: Dict[Tuple[str, str], Dict[str, int]],
            baseline: Dict[str, Any]) -> Tuple[bool, List[str], List[str]]:
    """Returns (ok, failures, notes)."""
    recorded = baseline.get("routes", {})
    ceiling = baseline.get("repeat_ceiling", REPEAT_CEILING)
    failures: List[str] = []
    notes: List[str] = []

    seen = {key_of(method, route) for method, route in measured}

    # A census that covered almost nothing proves almost nothing. Without this a
    # crashed run passes every gate by never contradicting one.
    if recorded:
        coverage = len(seen & set(recorded)) / len(recorded)
        if coverage < MINIMUM_COVERAGE:
            failures.append(
                f"census covered {coverage:.0%} of the {len(recorded)} baseline routes "
                f"(minimum {MINIMUM_COVERAGE:.0%}); a census that reached nothing "
                f"cannot clear a route of anything")

    for (method, route), entry in sorted(measured.items()):
        name = key_of(method, route)
        observed = entry["worst_repeat"]
        prior = recorded.get(name)

        if prior is None:
            if observed > ceiling:
                failures.append(
                    f"{name}: new route repeats one statement shape {observed} times "
                    f"(ceiling {ceiling}) -- {entry['calls']} call(s), "
                    f"{entry['queries']} statements\n      {(entry['worst_shape'] or '')[:160]}")
            else:
                notes.append(f"{name}: new route, worst repeat {observed}, "
                             f"{entry['queries']} statements")
            continue

        allowed = prior["worst_repeat"]
        if observed > allowed:
            failures.append(
                f"{name}: repeats one shape {observed} times, baseline {allowed} "
                f"({observed - allowed:+d})\n      {(entry['worst_shape'] or '')[:160]}")
        elif observed < allowed:
            notes.append(f"{name}: worst repeat {allowed} -> {observed} "
                         f"({observed - allowed:+d}) -- baseline should be lowered")

        drift = entry["queries"] - prior.get("queries", 0)
        if drift:
            notes.append(f"{name}: {prior.get('queries')} -> {entry['queries']} "
                         f"statements ({drift:+d})")

    # The debt list is the point of the exercise; losing sight of a route is how
    # debt gets paid off on paper.
    for name, prior in sorted(recorded.items()):
        if prior["worst_repeat"] > ceiling and name not in seen:
            failures.append(
                f"{name}: recorded at {prior['worst_repeat']} repeats and not measured "
                f"by this census -- a watched route may not go dark")

    return not failures, failures, notes


def build_baseline(measured: Dict[Tuple[str, str], Dict[str, int]]) -> Dict[str, Any]:
    from audit_evidence_corpus import current_head

    return {
        # A census measures a schema as much as it measures code: the statements
        # a route runs depend on the tables it has. Recorded so this file can be
        # shown to be stale, which is what `audit_evidence_corpus` ratchets.
        "provenance": {"migration_head": current_head()},
        "repeat_ceiling": REPEAT_CEILING,
        "note": ("Worst observation per route+method from a full suite census. "
                 "worst_repeat is gated; queries is reported only, because two "
                 "censuses agreed on repeats for 695/695 pairs and on statements "
                 "for 692/695."),
        "routes": {key_of(method, route): {"worst_repeat": entry["worst_repeat"],
                                           "queries": entry["queries"],
                                           "calls": entry["calls"]}
                   for (method, route), entry in sorted(measured.items())},
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("census", help="JSONL from measure_suite_cost.py")
    parser.add_argument("--write-baseline", action="store_true",
                        help="Record the measured surface as the new baseline")
    args = parser.parse_args()

    census_path = Path(args.census)
    if not census_path.exists():
        print(f"No census at {census_path}. Run:\n"
              f"  python oms/measure_suite_cost.py --out {census_path}")
        return 1

    rows = load_census(census_path)
    if not rows:
        print(f"{census_path} recorded no requests.")
        return 1
    measured = aggregate(rows)

    writes = sum(1 for method, _ in measured if method in {"POST", "PUT", "PATCH", "DELETE"})
    print(f"{len(rows)} requests over {len(measured)} route+method pairs "
          f"({writes} write pairs, {len(measured) - writes} read pairs)\n")

    if args.write_baseline:
        BASELINE.write_text(json.dumps(build_baseline(measured), indent=2) + "\n",
                            encoding="utf-8")
        above = sum(1 for entry in measured.values() if entry["worst_repeat"] > REPEAT_CEILING)
        print(f"Baseline written to {BASELINE.relative_to(REPO_ROOT)} "
              f"({len(measured)} pairs, {above} above the ceiling of {REPEAT_CEILING}).")
        return 0

    if not BASELINE.exists():
        print(f"No baseline at {BASELINE.relative_to(REPO_ROOT)}. Record one with "
              f"--write-baseline once the census is trusted.")
        return 1

    baseline = load_baseline(BASELINE)
    ok, failures, notes = compare(measured, baseline)

    worst = sorted(measured.items(), key=lambda item: -item[1]["worst_repeat"])[:10]
    print("worst repeated shape per route:")
    for (method, route), entry in worst:
        print(f"  x{entry['worst_repeat']:<5} {entry['queries']:6d} statements  "
              f"{entry['calls']:4d} calls  {method:<6} {route}")

    if notes:
        print(f"\n{len(notes)} change(s) worth reading, none of them gated:")
        for note in notes[:40]:
            print(f"  {note}")
        if len(notes) > 40:
            print(f"  ... and {len(notes) - 40} more")

    if failures:
        print(f"\nFAIL -- {len(failures)} route(s) got worse:")
        for failure in failures:
            print(f"  {failure}")
        return 1

    debt = sum(1 for entry in measured.values()
               if entry["worst_repeat"] > baseline.get("repeat_ceiling", REPEAT_CEILING))
    print(f"\nNo route repeats a shape more than its baseline. "
          f"{debt} route(s) remain above the ceiling of "
          f"{baseline.get('repeat_ceiling', REPEAT_CEILING)}; they may only go down.")
    return 0


if __name__ == "__main__":
    from enforcement_runs import recording

    raise SystemExit(recording("audit_suite_cost", main))

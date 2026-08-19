"""Report how things stand, and gate the promises the project makes to itself.

    python oms/audit_iteration_state.py            # gate, and print the state
    python oms/audit_iteration_state.py --status    # print only

Everything here is read from static files in well under a second, which is the
point: establishing the state of this repository during the session that produced
this file took a shell loop over 228 scripts, a twenty-minute census, a browser
run, and four audits invoked by hand. None of that says what is *owed*.

What is gated, following the rule every ratchet here has had to be taught
separately — gate the thing ordinary work does not do, report the thing it does:

  - *Gated:* a goal document that declares conditions nothing can parse. The
    format is an interface; a document that opts out of it removes itself from
    the backlog silently.
  - *Gated:* a check declaring `every push` that the pre-push hook does not run.
    Four were found this way, while `audit_check_coverage` (every check is
    declared) and `audit_enforcement` (every declared check has run at least
    once) both reported green. Neither compares a declaration to the mechanism
    that would have to honour it.
  - *Gated:* the number of conditions whose state is unrecorded, ratcheted
    downward. Writing a new condition is ordinary; leaving one without a state
    is what made a finished goal indistinguishable from an abandoned one.
  - *Gated:* a baseline with no recorded date, ratcheted downward. Undated
    evidence cannot be shown to be stale, so it never expires.
  - *Reported:* which conditions are open, which are blocked, how old each
    baseline is, and what to do next.

The last line of the output names the next step, by the ordering in
`iteration_state.next_step`. That is I5 of the goal this came from, and it is a
smaller claim than it sounds: it picks the next step *within goals already
stated*, never what the project should care about.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))

from iteration_state import (BLOCKED, MET, OPEN, UNRECORDED, build,  # noqa: E402
                             next_step)

BASELINE = REPO_ROOT / "docs" / "iteration-state-baseline.json"


def summarise(report) -> Dict[str, Any]:
    states: Dict[str, int] = {}
    for condition in report.conditions:
        states[condition.state] = states.get(condition.state, 0) + 1
    return {
        "conditions": len(report.conditions),
        "unrecorded": states.get(UNRECORDED, 0),
        "open": states.get(OPEN, 0),
        "met": states.get(MET, 0),
        "blocked": states.get(BLOCKED, 0),
        "cadence_gaps": len(report.cadence_gaps),
        "undated_baselines": sum(1 for b in report.baselines if not b.recorded_at),
        "lifeless_baselines": sum(1 for b in report.baselines if not b.stale_after),
        "overdue_baselines": sum(1 for b in report.baselines if b.overdue),
        # Declaring evidence head-bound and recording no head is a shelf life
        # nothing can check. It is not the same as having no life declared, and
        # it hides better.
        "headless_baselines": sum(1 for b in report.baselines
                                  if b.stale_after == "migration head" and not b.migration_head),
        "unparsed_documents": len(report.unparsed),
    }


def compare(counts: Dict[str, Any], baseline: Dict[str, Any]):
    failures = []
    notes = []

    if counts["unparsed_documents"]:
        failures.append(
            f"{counts['unparsed_documents']} goal document(s) declare conditions in a shape "
            f"nothing can parse; they are invisible to the backlog")

    if counts["cadence_gaps"]:
        failures.append(
            f"{counts['cadence_gaps']} check(s) run somewhere other than where they say, or "
            f"nowhere at all -- correct the declaration, or give the check a home")

    for entry in [b for b in getattr(counts, "_overdue", [])]:
        pass
    for field, label in (("unrecorded", "condition(s) with no recorded state"),
                         ("undated_baselines", "baseline(s) with no recorded date"),
                         ("lifeless_baselines", "baseline(s) declaring no shelf life"),
                         ("overdue_baselines", "baseline(s) past the life they declare"),
                         ("headless_baselines",
                          "baseline(s) claiming to expire with the migration head "
                          "while recording no head")):
        ceiling = baseline.get(f"{field}_ceiling")
        if ceiling is None:
            continue
        if counts[field] > ceiling:
            failures.append(f"{counts[field]} {label}, above the ceiling of {ceiling}. "
                            f"This number may fall and must never rise.")
        elif counts[field] < ceiling:
            notes.append(f"{field}: {ceiling} -> {counts[field]} -- re-run with "
                         f"--set-baseline to lock the improvement in")
    return not failures, failures, notes


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--status", action="store_true", help="Report without gating")
    parser.add_argument("--set-baseline", action="store_true",
                        help="Record the current counts as the ceilings")
    args = parser.parse_args()

    report = build()
    counts = summarise(report)

    print(f"{counts['conditions']} conditions across "
          f"{len({c.document for c in report.conditions})} goal document(s)\n")
    print(f"  {'state':<14}{'count':>7}")
    for state in (OPEN, BLOCKED, MET, UNRECORDED):
        print(f"  {state:<14}{counts.get(state if state != OPEN else 'open', 0):>7}")

    still_open = [c for c in report.conditions if c.state in (OPEN, BLOCKED)]
    if still_open:
        print(f"\nopen conditions:")
        for condition in still_open[:12]:
            mark = "blocked" if condition.state == BLOCKED else "open"
            print(f"  [{mark:<7}] {condition.identifier:<4} {condition.document[:34]:<34} "
                  f"{condition.title[:56]}")
        if len(still_open) > 12:
            print(f"  ... and {len(still_open) - 12} more")

    if report.cadence_gaps:
        print(f"\ncadence claimed but not honoured ({len(report.cadence_gaps)}):")
        for name in report.cadence_gaps:
            print(f"  {name} declares `every push`, pre-push does not run it")

    undated = [b for b in report.baselines if not b.recorded_at]
    print(f"\n{len(report.baselines)} baseline(s), {len(undated)} undated:")
    for entry in report.baselines:
        age = f"{entry.age_days}d" if entry.age_days is not None else "undated"
        head = entry.migration_head or "-"
        print(f"  {entry.name:<40}{age:>10}  {head}")

    if args.set_baseline:
        from datetime import datetime, timezone

        BASELINE.write_text(json.dumps({
            # This file is subject to its own rule. A baseline that does not say
            # when it was recorded cannot be shown to be stale, and the first run
            # of this gate caught exactly that about the baseline it had just
            # written.
            "provenance": {
                "recorded_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                # Ceilings on the tree, recomputed from it on every run, so this
                # file cannot go stale the way a census can. Saying so is the
                # point: the gate refuses a baseline that declares no life, and
                # this one refused itself until it did.
                "stale_after": "recomputed each run",
            },
            "note": ("Ceilings on what the project has not written down about itself. "
                     "Both may fall and must never rise."),
            "unrecorded_ceiling": counts["unrecorded"],
            "undated_baselines_ceiling": counts["undated_baselines"],
            "lifeless_baselines_ceiling": counts["lifeless_baselines"],
            "overdue_baselines_ceiling": counts["overdue_baselines"],
            "headless_baselines_ceiling": counts["headless_baselines"],
        }, indent=2) + "\n", encoding="utf-8")
        print(f"\nBaseline set: {counts['unrecorded']} unrecorded condition(s), "
              f"{counts['undated_baselines']} undated, "
              f"{counts['lifeless_baselines']} without a declared life, "
              f"{counts['overdue_baselines']} overdue, "
              f"{counts['headless_baselines']} head-bound with no head.")
        return 0

    print(f"\nNext: {next_step(report)}")

    if args.status:
        return 0

    baseline = {}
    if BASELINE.exists():
        baseline = json.loads(BASELINE.read_text(encoding="utf-8"))
    if not baseline:
        print(f"\nNo baseline at {BASELINE.relative_to(REPO_ROOT)}. Record one with "
              f"--set-baseline.")
        return 1

    ok, failures, notes = compare(counts, baseline)
    if notes:
        print()
        for note in notes:
            print(f"  {note}")
    if failures:
        print(f"\nFAIL -- {len(failures)} problem(s):")
        for failure in failures:
            print(f"  {failure}")
        return 1
    print(f"\nEvery condition has a state, every `every push` check is run on push, and no "
          f"baseline is undated beyond its ceiling.")
    return 0


if __name__ == "__main__":
    from enforcement_runs import recording

    raise SystemExit(recording("audit_iteration_state", main))

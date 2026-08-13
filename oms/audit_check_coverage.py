"""Fail when a check is undeclared, or could be automated and is not.

Condition C2 of GOAL_2026-08-13. Two distinct failures, reported separately
because they need different fixes:

  UNDECLARED   a check-shaped script nobody wrote down. Adding a verifier and
               forgetting it is how this surface grew to 34 scripts with 11 of
               them in no workflow at all.

  UNAUTOMATED  a check that needs no infrastructure and still has no home in the
               suite. Not a declaration problem -- a defect. `audit_query_bounds`
               and `audit_route_coverage` are pure static analysis over the tree,
               are named as ratchets by the standing goal, and ran on 2026-08-13
               only because a person typed the command.

Checks that genuinely need PostgreSQL, a broker, an object store or an OCI
sandbox are reported as MANUAL with what they need and how often they should run.
That is a declaration, not a defect: forcing them into a laptop test run would
make the suite slow, flaky, and dishonest about what it covered.

  python oms/audit_check_coverage.py
  python oms/audit_check_coverage.py --set-baseline
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from check_registry import (  # noqa: E402
    DECLARATIONS, discover, requirements_of, suite_executions, workflow_invocations,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
BASELINE = REPO_ROOT / "docs" / "check-coverage-baseline.json"

SUITE, CI, MANUAL, UNAUTOMATED, UNDECLARED = (
    "SUITE", "CI", "MANUAL", "UNAUTOMATED", "UNDECLARED")


def classify() -> dict:
    in_suite, in_ci = suite_executions(), workflow_invocations()
    report = {}
    for name in discover():
        requires = requirements_of(name)
        if name not in DECLARATIONS:
            report[name] = {"state": UNDECLARED, "requires": requires,
                            "detail": "no declaration: say what it gates and how often it runs"}
            continue
        declared = DECLARATIONS[name]
        if name in in_suite:
            state, detail = SUITE, "a test imports and runs it"
        elif requires:
            state, detail = MANUAL, "needs " + ", ".join(requires)
        elif name in in_ci:
            state, detail = CI, "runs only in a workflow, and CI has never provisioned a runner"
        else:
            state, detail = UNAUTOMATED, "needs nothing, and nothing runs it"
        report[name] = {"state": state, "requires": requires, "detail": detail,
                        "gates": declared["gates"], "cadence": declared["cadence"]}
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--set-baseline", action="store_true",
                        help="Record the current undeclared and unautomated counts as ceilings.")
    args = parser.parse_args()

    report = classify()
    width = max(len(name) for name in report)
    print("Check coverage audit\n")
    for state in (UNDECLARED, UNAUTOMATED, CI, SUITE, MANUAL):
        rows = {n: r for n, r in report.items() if r["state"] == state}
        if not rows:
            continue
        print(f"  {state} ({len(rows)})")
        for name, row in rows.items():
            print(f"    {name.ljust(width)}  {row['detail']}")
        print()

    undeclared = sum(1 for r in report.values() if r["state"] == UNDECLARED)
    unautomated = sum(1 for r in report.values() if r["state"] == UNAUTOMATED)
    print(f"{len(report)} check-shaped scripts: " + ", ".join(
        f"{s} {sum(1 for r in report.values() if r['state'] == s)}"
        for s in (SUITE, CI, MANUAL, UNAUTOMATED, UNDECLARED)))

    if args.set_baseline:
        BASELINE.write_text(json.dumps({
            "undeclared_ceiling": undeclared,
            "unautomated_ceiling": unautomated,
            "note": "Ceilings. May be lowered, never raised.",
        }, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(f"\nBaseline set: undeclared {undeclared}, unautomated {unautomated}.")
        return 0

    baseline = {}
    if BASELINE.exists():
        try:
            baseline = json.loads(BASELINE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            baseline = {}
    if not baseline:
        print("\nNo baseline recorded. Run with --set-baseline to start the ratchet.")
        return 0

    failed = False
    for label, count, key in (("undeclared", undeclared, "undeclared_ceiling"),
                              ("unautomated", unautomated, "unautomated_ceiling")):
        ceiling = baseline.get(key)
        if ceiling is None:
            continue
        print(f"{label} ceiling: {ceiling}")
        if count > ceiling:
            names = [n for n, r in report.items()
                     if r["state"] == (UNDECLARED if label == "undeclared" else UNAUTOMATED)]
            print(f"\nRATCHET BROKEN: {count} {label} exceeds the ceiling of {ceiling}: "
                  + ", ".join(names))
            failed = True
        elif count < ceiling:
            print(f"  tightened: {count} < {ceiling}; re-run with --set-baseline to lock it in")
    return 1 if failed else 0


if __name__ == "__main__":
    from enforcement_runs import recording  # noqa: E402
    sys.exit(recording("audit_check_coverage", main))

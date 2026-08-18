"""Report which enforcement checks have run, and fail when one stops having run.

Condition C6 of GOAL_2026-08-13. The corpus audit asks whether the *evidence* is
current; this asks whether the *auditors* are.

  CURRENT  ran at the current migration head
  STALE    ran, but at an older head
  NEVER    no run has ever been recorded

**The ratchet is on NEVER, not on CURRENT**, which corrects the goal as first
written. Ratcheting the CURRENT count would break the build on every migration,
because advancing the head makes every check stale at once until each is re-run.
This repository already learned that lesson from the other direction: the Tier B
gate report is deliberately `continue-on-error`, "because gating on it would
leave the build permanently red and train everyone to ignore it". A ratchet that
fires on ordinary work teaches people to route around it.

So staleness is reported and never gates. What gates is regression to NEVER: once
a check has been shown to run, it must keep having run. That is stable across
migrations and still catches the failure this goal exists for -- a check quietly
dropping out of every automated path.

  python oms/audit_enforcement.py
  python oms/audit_enforcement.py --set-baseline
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from enforcement_runs import (  # noqa: E402
    CURRENT, DECLARED, NEVER, STALE, classify, load,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
BASELINE = REPO_ROOT / "docs" / "enforcement-baseline.json"


def load_baseline() -> dict:
    if not BASELINE.exists():
        return {}
    try:
        payload = json.loads(BASELINE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return payload if isinstance(payload, dict) else {}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--set-baseline", action="store_true",
                        help="Record the current count of checks that have ever run.")
    args = parser.parse_args()

    from tier_b_evidence import current_head

    head = current_head()
    report = classify(load(), head)

    print("Enforcement run audit")
    print(f"Current migration head: {head}\n")
    width = max(len(name) for name in report)
    for name, row in report.items():
        print(f"  {row['state'].ljust(7)}  {name.ljust(width)}  {row['detail']}")
        if row["state"] == NEVER:
            print(f"           {' ' * width}  guards: {row['purpose']}")

    tally = {state: sum(1 for row in report.values() if row["state"] == state)
             for state in (CURRENT, STALE, NEVER)}
    ever_run = tally[CURRENT] + tally[STALE]
    print(f"\n{len(report)} declared checks: " +
          ", ".join(f"{state} {count}" for state, count in tally.items()))
    print(f"{ever_run} have run at least once")

    if args.set_baseline:
        BASELINE.write_text(
            json.dumps({
                "ever_run_floor": ever_run,
                "recorded_at_head": head,
                "note": "Floor. May be raised, never lowered. Staleness is reported, "
                        "not gated: advancing the head makes every check stale at once, "
                        "and a ratchet that fires on ordinary work gets ignored.",
            }, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        print(f"\nBaseline set: {ever_run} checks have run at least once.")
        return 0

    floor = load_baseline().get("ever_run_floor")
    if floor is None:
        print("\nNo baseline recorded. Run with --set-baseline to start the ratchet.")
        return 0

    print(f"Ever-run floor: {floor}")
    if ever_run < floor:
        missing = [name for name, row in report.items() if row["state"] == NEVER]
        print(f"\nRATCHET BROKEN: {ever_run} checks have run, below the floor of {floor}.")
        print("A check that has stopped running cannot fail, and a check that cannot")
        print("fail is not enforcement. Never ran: " + ", ".join(missing))
        return 1
    if ever_run > floor:
        print(f"\nRatchet tightened: {ever_run} > {floor}. "
              "Re-run with --set-baseline to lock in the improvement.")
    if tally[STALE]:
        stale = [name for name, row in report.items() if row["state"] == STALE]
        print(f"\n{tally[STALE]} check(s) last ran at an older head: {', '.join(stale)}.")
        print("Reported, not gated. Re-run them to make this line go away.")
    return 0


if __name__ == "__main__":
    # This is the one audit that does not run through `enforcement_runs.recording`,
    # because it audits the run records and would otherwise be recording itself.
    # It still owes its baseline a date, so it borrows the same two helpers.
    from enforcement_runs import _baseline_mtimes, _stamp_rewritten_baselines

    _seen = _baseline_mtimes()
    try:
        _code = main()
    finally:
        try:
            _stamp_rewritten_baselines(_seen)
        except Exception as _error:
            print(f"[enforcement-runs] could not date a baseline: {_error}")
    sys.exit(_code)

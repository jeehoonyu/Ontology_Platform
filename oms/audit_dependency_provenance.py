"""Report evidence produced against a dependency set that is no longer installed.

Condition D3 of GOAL_REPRODUCIBILITY_2026-08-13.

  CURRENT     the recorded closure digest matches what is installed now
  DRIFTED     it ran against a different set; the packages that moved are named
  UNRECORDED  produced before D2, so the set that made it is unknown

**The ratchet is on UNRECORDED, not on DRIFTED.** Upgrading a dependency is
ordinary work, and a condition that fires on ordinary work teaches people to
route around it -- the lesson `GOAL_2026-08-13.md` paid for when it moved its own
ratchet off CURRENT. Drift is reported so a number that moves after an upgrade
explains itself instead of being attributed to the code. What must never grow is
evidence that cannot say what produced it.

DRIFTED is not a defect. It is the answer to a question this repository could not
previously ask: *did the library change, or did we?*

  python oms/audit_dependency_provenance.py
  python oms/audit_dependency_provenance.py --set-baseline
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict

sys.path.insert(0, str(Path(__file__).resolve().parent))

from dependency_provenance import digest, resolved  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
DOCS = REPO_ROOT / "docs"
BASELINE = DOCS / "dependency-provenance-baseline.json"

CURRENT, DRIFTED, UNRECORDED, UNREADABLE = (
    "CURRENT", "DRIFTED", "UNRECORDED", "UNREADABLE")


def _moved(recorded: Dict[str, str], installed: Dict[str, str]) -> list:
    """Which packages differ, so drift names itself rather than just alarming."""
    names = sorted(set(recorded) | set(installed))
    return [(name, recorded.get(name, "absent"), installed.get(name, "absent"))
            for name in names if recorded.get(name) != installed.get(name)]


def classify(docs: Path | None = None) -> Dict[str, Dict[str, Any]]:
    directory = docs or DOCS
    installed = resolved()
    now = digest(installed)
    report: Dict[str, Dict[str, Any]] = {}
    for path in sorted(directory.glob("*evidence*.json")):
        if path.name == BASELINE.name:
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as error:
            report[path.name] = {"state": UNREADABLE, "detail": str(error)[:70]}
            continue
        if not isinstance(payload, dict):
            report[path.name] = {"state": UNREADABLE, "detail": "top level is not an object"}
            continue
        block = (payload.get("provenance") or {}).get("dependencies")
        if not isinstance(block, dict) or not block.get("digest"):
            report[path.name] = {
                "state": UNRECORDED,
                "detail": "no dependency set recorded; produced before D2",
            }
            continue
        if block["digest"] == now:
            report[path.name] = {"state": CURRENT,
                                 "detail": f"{block.get('closure', '?')} distributions, digest {now}"}
            continue
        moved = _moved(block.get("versions") or {}, installed)
        report[path.name] = {
            "state": DRIFTED,
            "detail": f"{len(moved)} package(s) moved since it was measured",
            "moved": moved,
        }
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--set-baseline", action="store_true",
                        help="Record the current unrecorded count as the ceiling.")
    args = parser.parse_args()

    report = classify()
    if not report:
        print("No evidence files found.")
        return 0
    width = max(len(name) for name in report)
    print("Dependency provenance audit")
    print(f"Installed closure digest: {digest()}\n")
    for state in (UNREADABLE, UNRECORDED, DRIFTED, CURRENT):
        rows = {n: r for n, r in report.items() if r["state"] == state}
        if not rows:
            continue
        print(f"  {state} ({len(rows)})")
        for name, row in rows.items():
            print(f"    {name.ljust(width)}  {row['detail']}")
            for package, was, now_version in row.get("moved", [])[:6]:
                print(f"      {package:<24} {was}  ->  {now_version}")
            if len(row.get("moved", [])) > 6:
                print(f"      ... and {len(row['moved']) - 6} more")
        print()

    unrecorded = sum(1 for r in report.values() if r["state"] == UNRECORDED)
    print(f"{len(report)} evidence files: " + ", ".join(
        f"{s} {sum(1 for r in report.values() if r['state'] == s)}"
        for s in (CURRENT, DRIFTED, UNRECORDED, UNREADABLE)))

    if args.set_baseline:
        BASELINE.write_text(json.dumps({
            "unrecorded_ceiling": unrecorded,
            "note": "Ceiling. May be lowered, never raised. Drift is reported and never "
                    "gated: upgrading a dependency is ordinary work, and a ratchet that "
                    "fires on ordinary work gets routed around.",
        }, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(f"\nBaseline set: {unrecorded} evidence files record no dependency set.")
        return 0

    baseline = {}
    if BASELINE.exists():
        try:
            baseline = json.loads(BASELINE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            baseline = {}
    ceiling = baseline.get("unrecorded_ceiling")
    if ceiling is None:
        print("\nNo baseline recorded. Run with --set-baseline to start the ratchet.")
        return 0

    print(f"Unrecorded ceiling: {ceiling}")
    if unrecorded > ceiling:
        names = [n for n, r in report.items() if r["state"] == UNRECORDED]
        print(f"\nRATCHET BROKEN: {unrecorded} evidence files record no dependency set, "
              f"above the ceiling of {ceiling}: " + ", ".join(names))
        print("Evidence that cannot name the code that produced it cannot be reproduced,")
        print("and a number that moves later cannot be attributed to anything.")
        return 1
    if unrecorded < ceiling:
        print(f"\nRatchet tightened: {unrecorded} < {ceiling}. "
              "Re-run with --set-baseline to lock in the improvement.")
    return 0


if __name__ == "__main__":
    from enforcement_runs import recording  # noqa: E402
    sys.exit(recording("audit_dependency_provenance", main))

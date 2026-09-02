"""Check that every ratchet has actually been lowered at least once.

K6 of `docs/GOAL_CONTINUOUS.md` said it plainly and could not check it: a ceiling that
never falls is a number wearing a goal's clothes. Recording one is cheap and looks like
progress -- the gate goes green, the frontier lists an owner, and nothing about the file
distinguishes a debt being paid down from a debt merely being observed. The only
difference is in the history, so that is where this looks.

**What is measured.** Every `*_ceiling` in every `docs/*baseline*.json`, read at each
commit that touched its file, in order. A ceiling has moved if it ever fell between two
consecutive versions of that file. Cost thresholds are excluded for the same reason
`audit_frontier` excludes them: their ceiling is a limit that should hold, not a debt that
should shrink, and demanding motion from one would be demanding the budget be cut.

**What the number is not.** It says nothing about whether a ceiling fell *enough*, or
recently, or for a good reason -- a one-off drop thirty commits ago still counts as
motion. It catches the specific failure of recording a measurement and then never acting
on it, which is the failure this repository is most prone to, because writing the audit is
the interesting part.

A ceiling that was born at zero has nothing to lower and is not counted against anyone.
Neither is one whose file has only ever been written once: it has not had the chance yet,
and a gate that fired on the first recording would charge the cost of measuring something
to whoever measured it, which is the surest way to stop people measuring. It is counted
from its second recording -- by then the file has been revisited and the ceiling stayed
put, which is the thing worth catching.

  python oms/audit_ratchet_motion.py
  python oms/audit_ratchet_motion.py --verbose
  python oms/audit_ratchet_motion.py --set-baseline
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List

REPO_ROOT = Path(__file__).resolve().parent.parent
DOCS = REPO_ROOT / "docs"
BASELINE = DOCS / "ratchet-motion-baseline.json"
CEILING = re.compile(r"_ceiling$")
THRESHOLDS = {"request-cost-baseline.json", "suite-cost-baseline.json",
              "ratchet-motion-baseline.json"}


def _git(*args: str) -> str:
    result = subprocess.run(("git", *args), cwd=REPO_ROOT,
                            capture_output=True, text=True, check=False)
    return result.stdout if result.returncode == 0 else ""


def _history(relative: str) -> List[Dict[str, Any]]:
    """Each recorded version of a baseline file, oldest first."""
    commits = _git("log", "--follow", "--format=%H", "--", relative).split()
    versions = []
    for commit in reversed(commits):
        blob = _git("show", f"{commit}:{relative}")
        if not blob:
            continue
        try:
            payload = json.loads(blob)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            versions.append(payload)
    return versions


def read() -> Dict[str, Any]:
    moved: List[Dict[str, Any]] = []
    unmoved: List[Dict[str, Any]] = []
    fresh: List[Dict[str, Any]] = []

    for path in sorted(DOCS.glob("*baseline*.json")):
        if path.name in THRESHOLDS:
            continue
        try:
            current = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if not isinstance(current, dict):
            continue

        versions = _history(str(path.relative_to(REPO_ROOT)))
        for key, value in current.items():
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                continue
            if not CEILING.search(key):
                continue

            series = [version[key] for version in versions
                      if isinstance(version.get(key), (int, float))
                      and not isinstance(version.get(key), bool)]
            fell = any(later < earlier for earlier, later in zip(series, series[1:]))
            record = {"baseline": path.name, "measure": key, "now": int(value),
                      "versions": len(series),
                      "high_water": int(max(series)) if series else int(value)}
            # Nothing to lower: a ceiling recorded at zero is already where it is going.
            if fell or value == 0:
                moved.append(record)
            elif len(series) <= 1:
                fresh.append(record)
            else:
                unmoved.append(record)

    return {"moved": moved, "unmoved": unmoved, "fresh": fresh,
            "ratchets": len(moved) + len(unmoved) + len(fresh)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--set-baseline", action="store_true")
    args = parser.parse_args()

    reading = read()
    print(f"{reading['ratchets']} ratchets; {len(reading['moved'])} have been lowered at "
          f"least once, {len(reading['unmoved'])} never have, "
          f"{len(reading['fresh'])} recorded once and not yet revisited")
    for record in reading["unmoved"]:
        print(f"    {record['now']:>6}  {record['measure']:<34} "
              f"{record['versions']} recorded version(s), never fell")
    if args.verbose:
        print()
        for record in reading["moved"]:
            print(f"    moved  {record['measure']:<34} high water {record['high_water']} "
                  f"-> {record['now']}")

    if args.set_baseline:
        BASELINE.write_text(json.dumps({
            "provenance": {
                "recorded_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "stale_after": "recomputed each run",
            },
            "note": ("Ratchet over the other ratchets. A ceiling that has never fallen in "
                     "the history of its own file is a measurement nobody has acted on, and "
                     "recording one is cheap enough to look like progress on its own. Cost "
                     "thresholds are excluded: their ceiling is a limit to hold, not a debt "
                     "to shrink."),
            "unmoved_ceiling": len(reading["unmoved"]),
            "ratchets_reference": reading["ratchets"],
        }, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(f"\nBaseline set: ceiling {len(reading['unmoved'])}.")
        return 0

    if not BASELINE.exists():
        print("\nNo baseline recorded. Run with --set-baseline to start the ratchet.")
        return 0

    ceiling = json.loads(BASELINE.read_text(encoding="utf-8"))["unmoved_ceiling"]
    count = len(reading["unmoved"])
    if count > ceiling:
        print(f"\nRATCHET BROKEN: {count} ratchets have never been lowered, above the "
              f"ceiling of {ceiling}. A measurement that is only ever recorded is a "
              f"backlog item that looks like a gate.")
        return 1
    if count < ceiling:
        print(f"\nRatchet held, and improved: {ceiling} -> {count}. "
              f"Re-run with --set-baseline to lock it in.")
        return 0
    print(f"\nRatchet held: {count} <= {ceiling}.")
    return 0


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from enforcement_runs import recording  # noqa: E402

    sys.exit(recording("audit_ratchet_motion", main))

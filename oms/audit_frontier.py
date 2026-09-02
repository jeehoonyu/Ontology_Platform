"""Every measured gap is owned by a stated condition, and the frontier is readable.

`audit_iteration_state.next_step` picks the next step *within goals already
stated*, and says so plainly: it "never decides what the project should care
about; that judgement stays with a person." When a goal's conditions are all met
it prints *State a new goal* and stops.

Every goal in this repository was opened because somebody noticed something. That
is one person's attention as the single point of failure for the whole
discipline, and it fails silently -- a backlog that has run dry looks exactly like
a project with nothing left to do.

It is also unnecessary, because the backlog already exists and nobody was reading
it. Twenty-odd ratchets each record a number that is not zero: 401 unscoped reads,
75 mutating handlers with no permission, 32 hand-written empty states, 23
dependency records with no provenance. Each is a stated distance from a stated
target, written down by a check that runs on every push. The frontier is the set
of those distances, sorted.

**What is gated.** A non-zero ceiling that no open condition names. A ratchet
recorded and unowned is a measurement nobody is answerable for -- the number goes
into a file, the file is never read, and the gap ages without ever becoming work.
Owning it costs one row in a goal document, which is the cheapest possible
commitment and the whole mechanism this repository runs on.

**What is reported.** The ranked frontier, and which document owns each entry, so
that "what should we do next" has an answer that does not depend on who is
looking.

  python oms/audit_frontier.py
  python oms/audit_frontier.py --verbose
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List

REPO_ROOT = Path(__file__).resolve().parent.parent
DOCS = REPO_ROOT / "docs"
sys.path.insert(0, str(Path(__file__).resolve().parent))

# A ceiling is a distance to close; a floor is a level to hold or raise. Only
# ceilings above zero are gaps. A floor is reported, never gated: raising one is
# an improvement nobody owes.
CEILING = re.compile(r"_ceiling$")
FLOOR = re.compile(r"_floor$")

# Baselines whose ceiling is a threshold rather than a distance. `repeat_ceiling`
# of 6 does not mean "six things left to fix"; it means "no route may repeat one
# statement shape more than six times", and the gap is the count of routes above
# it, which the audit itself reports and gates. Counting 6 as a backlog item
# would be reading a limit as a debt.
THRESHOLDS = {"request-cost-baseline.json", "suite-cost-baseline.json"}


def gaps() -> List[Dict[str, Any]]:
    found: List[Dict[str, Any]] = []
    for path in sorted(DOCS.glob("*baseline*.json")):
        if path.name in THRESHOLDS:
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if not isinstance(payload, dict):
            continue
        for key, value in payload.items():
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                continue
            if CEILING.search(key) and value > 0:
                found.append({"baseline": path.name, "measure": key, "distance": int(value)})
    return sorted(found, key=lambda row: -row["distance"])


def _condition_text() -> Dict[str, str]:
    """Open and blocked conditions, keyed document:id, as searchable text."""
    from iteration_state import BLOCKED, OPEN, read_conditions

    text: Dict[str, str] = {}
    for condition in read_conditions():
        if condition.state in (OPEN, BLOCKED):
            text[f"{condition.document}:{condition.identifier}"] = (
                f"{condition.title} {condition.detail}".lower())
    return text


def _stem_terms(baseline: str, measure: str) -> List[str]:
    """The words an owning condition would plausibly use for this gap.

    Both spellings of the measure, because a condition naming it in code style
    writes `unauthorized_mutating_ceiling` and one naming it in prose writes
    "unauthorized mutating". The first draft of this only tried the prose form
    and reported a condition that named the measure exactly as unowned.
    """
    stem = baseline.replace("-baseline.json", "")
    bare = measure.replace("_ceiling", "")
    return [stem, stem.replace("-", " "), stem.replace("-", "_"),
            measure, bare, bare.replace("_", " ")]


def owners(gap: Dict[str, Any], conditions: Dict[str, str]) -> List[str]:
    terms = _stem_terms(gap["baseline"], gap["measure"])
    return sorted(key for key, body in conditions.items()
                  if any(term and term in body for term in terms))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    conditions = _condition_text()
    rows = gaps()
    unowned: List[Dict[str, Any]] = []

    print(f"Frontier: {len(rows)} measured gap(s) across "
          f"{len({row['baseline'] for row in rows})} ratchet(s), "
          f"{len(conditions)} open or blocked condition(s)\n")
    print(f"  {'distance':>9}  {'measure':<34} owned by")
    for row in rows:
        held = owners(row, conditions)
        if not held:
            unowned.append(row)
        label = ", ".join(held) if held else "-- nothing"
        print(f"  {row['distance']:>9}  {row['measure']:<34} {label}")

    if args.verbose:
        print("\n  open and blocked conditions:")
        for key in sorted(conditions):
            print(f"    {key}")

    if unowned:
        print(f"\nFAIL -- {len(unowned)} measured gap(s) no open condition names:")
        for row in unowned:
            print(f"  {row['measure']} = {row['distance']} ({row['baseline']})")
        print("\nA ratchet recorded and unowned is a number nobody is answerable "
              "for. Open a condition that names it, or lower it to zero.")
        return 1

    if rows:
        largest = rows[0]
        print(f"\nEvery gap is owned. The largest is {largest['measure']} at "
              f"{largest['distance']}, held by {', '.join(owners(largest, conditions))}.")
    else:
        print("\nNo ratchet records a gap. State a new goal, or lower a floor's "
              "target -- a project with no measured distance is measuring too little.")
    return 0


if __name__ == "__main__":
    from enforcement_runs import recording  # noqa: E402

    sys.exit(recording("audit_frontier", main))

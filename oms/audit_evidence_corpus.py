"""Audit every evidence file in docs/ for provenance and freshness.

The tiered goal asks whether particular gates hold. This asks a standing
question instead: how far has the evidence corpus drifted from what is actually
true right now?

Three states matter. CURRENT evidence records the migration head it was produced
at and that head is the current one. STALE evidence records a head that has
since moved, so it describes a system that no longer exists. UNPROVENANCED
evidence records no head at all, which is the worst of the three: it cannot be
shown to be stale, so it reads as valid indefinitely and nothing ever forces it
to be re-earned.

The unprovenanced count is a ratchet. It may fall and must never rise. Adding
evidence without provenance is how a corpus rots quietly, and a baseline that
only tightens makes that failure loud on the commit that causes it rather than
during the audit six months later.

  python oms/audit_evidence_corpus.py            # report and enforce the ratchet
  python oms/audit_evidence_corpus.py --set-baseline
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List

sys.path.insert(0, str(Path(__file__).resolve().parent))

from tier_b_evidence import current_head  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
DOCS = REPO_ROOT / "docs"
BASELINE = DOCS / "evidence-corpus-baseline.json"

CURRENT, STALE, UNPROVENANCED, UNREADABLE = "CURRENT", "STALE", "UNPROVENANCED", "UNREADABLE"


HEAD_KEYS = ("migration_head", "migration", "alembic_head", "schema_head", "revision")
# Alembic revisions in this repo are 0001_name .. 0037_name. Matching the shape
# avoids reading an unrelated "revision: 4" artifact counter as a schema head,
# which would silently classify dated evidence as current.
HEAD_SHAPE = re.compile(r"^\d{4}_[a-z0-9_]+$")


def head_of(payload: Dict[str, Any], depth: int = 3) -> str:
    """Find a recorded migration head wherever a harness happened to put it.

    Pre-contract harnesses buried the head at varying depths under varying
    names; ontology-scale-backup-restore-evidence.json records it three levels
    down as source_state.migration. Searching only the top level reports those
    files as unprovenanced, which is a worse verdict than the truth: they are
    dated, and being able to prove they are dated is the point.
    """
    if depth < 0 or not isinstance(payload, dict):
        return ""
    provenance = payload.get("provenance")
    if isinstance(provenance, dict) and provenance.get("migration_head"):
        return str(provenance["migration_head"])
    for key in HEAD_KEYS:
        value = payload.get(key)
        if isinstance(value, str) and HEAD_SHAPE.match(value):
            return value
    for value in payload.values():
        if isinstance(value, dict):
            found = head_of(value, depth - 1)
            if found:
                return found
    return ""


def classify(path: Path, head: str) -> tuple[str, str]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as error:
        return UNREADABLE, str(error)[:80]
    if not isinstance(payload, dict):
        return UNREADABLE, "top level is not an object"
    recorded = head_of(payload)
    if not recorded:
        return UNPROVENANCED, "records no migration head"
    if recorded != head:
        return STALE, f"produced at {recorded}"
    return CURRENT, f"at {recorded}"


def scan(head: str) -> List[Dict[str, str]]:
    rows = []
    for path in sorted(DOCS.glob("*evidence*.json")):
        # The baseline matches the evidence glob by name. Left in, it counts
        # itself as unprovenanced and breaks the ratchet it exists to hold.
        if path.name == BASELINE.name:
            continue
        state, detail = classify(path, head)
        rows.append({"file": path.name, "state": state, "detail": detail})
    return rows


def verified_database_heads() -> int:
    """Gate files that name the database head their run measured.

    `migration_head` is the repository's declared head -- what the code says.
    `observed_migration_head` is what the measured database reported. A harness
    that stops passing it still produces a well-formed file, so this is counted
    and ratcheted: without a floor, dropping the argument is invisible, which is
    the difference between a ratchet and an intention.

    Not every gate measures a database. The floor therefore protects the number
    that has been earned rather than demanding one from every file.
    """
    total = 0
    for path in sorted(DOCS.glob("*evidence*.json")):
        if path.name == BASELINE.name:
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        provenance = payload.get("provenance")
        if isinstance(provenance, dict) and provenance.get("observed_migration_head"):
            total += 1
    return total


def load_baseline() -> Dict[str, Any]:
    if not BASELINE.exists():
        return {}
    try:
        return json.loads(BASELINE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--set-baseline", action="store_true",
                        help="Record the current unprovenanced count as the ceiling.")
    args = parser.parse_args()

    head = current_head()
    rows = scan(head)
    tally: Dict[str, int] = {}
    for row in rows:
        tally[row["state"]] = tally.get(row["state"], 0) + 1

    print("Evidence corpus audit")
    print(f"Current migration head: {head}\n")
    width = max((len(row["file"]) for row in rows), default=10)
    for row in rows:
        print(f"  {row['file'].ljust(width)}  {row['state'].ljust(14)}  {row['detail']}")

    unprovenanced = tally.get(UNPROVENANCED, 0)
    verified = verified_database_heads()
    print(f"\n{len(rows)} evidence files: " +
          ", ".join(f"{state} {count}" for state, count in sorted(tally.items())))
    print(f"{verified} declare the database head they measured")

    if args.set_baseline:
        BASELINE.write_text(
            json.dumps({
                "unprovenanced_ceiling": unprovenanced,
                "verified_database_head_floor": verified,
                "recorded_at_head": head,
                "note": "Ratchet. The ceiling may be lowered, never raised; "
                        "the floor may be raised, never lowered.",
            }, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        print(f"\nBaseline set: unprovenanced ceiling {unprovenanced}, "
              f"verified-head floor {verified}.")
        return 0

    baseline = load_baseline()
    ceiling = baseline.get("unprovenanced_ceiling")
    if ceiling is None:
        print("\nNo baseline recorded. Run with --set-baseline to start the ratchet.")
        return 0

    print(f"Unprovenanced ceiling: {ceiling}")
    if unprovenanced > ceiling:
        print(f"\nRATCHET BROKEN: {unprovenanced} unprovenanced files exceeds the "
              f"ceiling of {ceiling}.")
        print("Evidence added without a migration head cannot be shown to be stale, so")
        print("it never expires. Record provenance, or lower a different file's debt first.")
        return 1
    floor = baseline.get("verified_database_head_floor")
    if floor is not None:
        print(f"Verified-head floor:   {floor}")
        if verified < floor:
            print(f"\nRATCHET BROKEN: {verified} files declare the database head they "
                  f"measured, below the floor of {floor}.")
            print("A harness that stops reporting observed_migration_head still writes a")
            print("well-formed file, so the loss is otherwise invisible. Pass observed_head")
            print("to write_evidence, or lower the floor deliberately with --set-baseline.")
            return 1
        if verified > floor:
            print(f"\nRatchet tightened: {verified} > {floor} verified heads. "
                  "Re-run with --set-baseline to lock in the improvement.")
    if unprovenanced < ceiling:
        print(f"\nRatchet tightened: {unprovenanced} < {ceiling}. "
              "Re-run with --set-baseline to lock in the improvement.")
        return 0
    print("\nRatchet held.")
    return 0


if __name__ == "__main__":
    from enforcement_runs import recording  # noqa: E402
    sys.exit(recording("audit_evidence_corpus", main))
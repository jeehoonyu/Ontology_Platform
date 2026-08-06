"""Record and aggregate chaos rehearsals for the Tier B chaos gate.

The gate names two subjects: collaboration and cross-stream processing. Each has
its own harness and neither can judge the gate alone, so both record a rehearsal
here and the gate verdict is derived from the union.

This replaces the arrangement where the collaboration harness wrote the gate
evidence and reported the cross-stream count as a hardcoded zero. That was
honest but fragile: the zero had to be remembered and edited by hand the day a
cross-stream harness appeared, and a gate whose scope is maintained by memory
eventually reads as satisfied while covering half of itself.

  python oms/chaos_rehearsals.py aggregate
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_REHEARSALS = REPO_ROOT / "docs" / "chaos-rehearsals.jsonl"

RECONNECT_LIMIT_MS = 5000.0
SUBJECTS = ("collaboration", "cross_stream")


def record(subject: str, measurements: Dict[str, Any], harness: str,
           rehearsals_file: Optional[Path] = None) -> Dict[str, Any]:
    if subject not in SUBJECTS:
        raise ValueError(f"unknown chaos subject {subject!r}; expected one of {SUBJECTS}")
    from tier_b_evidence import current_head

    path = Path(rehearsals_file) if rehearsals_file else DEFAULT_REHEARSALS
    # Each rehearsal records the head it ran at. Without this the aggregate can
    # combine rehearsals from different schemas into one evidence file that
    # claims a single current head, which launders stale work into fresh-looking
    # evidence -- the exact thing the non-completion rule forbids.
    entry = {"subject": subject, "at": int(time.time()), "harness": harness,
             "migration_head": current_head(), "measurements": measurements}
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, sort_keys=True) + "\n")
    return entry


def load(rehearsals_file: Path) -> List[Dict[str, Any]]:
    if not rehearsals_file.exists():
        return []
    rows = []
    for line in rehearsals_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows


def summarize(rehearsals: List[Dict[str, Any]]) -> Dict[str, Any]:
    def metric(rows, key, default=0):
        return [row["measurements"].get(key, default) for row in rows
                if isinstance(row.get("measurements"), dict)]

    collaboration = [row for row in rehearsals if row.get("subject") == "collaboration"]
    cross_stream = [row for row in rehearsals if row.get("subject") == "cross_stream"]
    reconnects = [value for value in metric(collaboration, "reconnect_max_ms") if value]

    return {
        "collaboration_rehearsals": len(collaboration),
        "cross_stream_rehearsals": len(cross_stream),
        # Losses and duplicates are summed across every rehearsal. One clean run
        # must not average away a run that dropped an event.
        "duplicate_events": sum(metric(collaboration, "duplicate_events")),
        "missed_events": sum(metric(collaboration, "missed_events")),
        "duplicate_pairs": sum(metric(cross_stream, "duplicate_pairs")),
        "missed_pairs": sum(metric(cross_stream, "missed_pairs")),
        "reconnect_max_ms": round(max(reconnects), 3) if reconnects else 0,
        "subjects_covered": sorted({row.get("subject") for row in rehearsals if row.get("subject")}),
    }


def at_head(rehearsals: List[Dict[str, Any]], head: str) -> List[Dict[str, Any]]:
    """Keep only rehearsals run at the given head.

    A rehearsal recorded before the head advanced describes a different schema.
    Counting it would let the gate read as satisfied on work that was never
    repeated, which is the non-completion rule violated from the inside.
    Records predating this field carry no head and are dropped.
    """
    return [row for row in rehearsals if row.get("migration_head") == head]


def aggregate(rehearsals_file: Optional[Path] = None,
              output_dir: Optional[Path] = None) -> int:
    from tier_b_evidence import current_head, write_evidence

    path = Path(rehearsals_file) if rehearsals_file else DEFAULT_REHEARSALS
    head = current_head()
    all_rehearsals = load(path)
    current = at_head(all_rehearsals, head)
    dropped = len(all_rehearsals) - len(current)
    if dropped:
        print(f"Ignoring {dropped} rehearsal(s) not run at {head}.")
    summary = summarize(current)
    summary["rehearsals_ignored_at_other_heads"] = dropped
    if not summary["collaboration_rehearsals"]:
        # With no collaboration rehearsal there is no reconnect measurement, and
        # a _max threshold with no data would satisfy itself.
        summary["reconnect_max_ms"] = RECONNECT_LIMIT_MS + 1

    evidence_path, status, breaches = write_evidence(
        "chaos",
        thresholds={
            "collaboration_rehearsals_min": 1,
            "cross_stream_rehearsals_min": 1,
            "duplicate_events_max": 0,
            "missed_events_max": 0,
            "duplicate_pairs_max": 0,
            "missed_pairs_max": 0,
            "reconnect_max_ms_max": RECONNECT_LIMIT_MS,
        },
        measurements=summary,
        harness="oms/chaos_rehearsals.py",
        notes=(
            "The gate names collaboration and cross-stream processing. Both subjects "
            "must have rehearsed, so the gate cannot read as satisfied while covering "
            "one half. Losses and duplicates are summed across rehearsals rather than "
            "averaged."
        ),
        output_dir=output_dir,
    )
    print(json.dumps(summary, indent=2, sort_keys=True))
    print(f"\nTier B evidence {status}: {evidence_path.name}")
    for breach in breaches:
        print(f"  breach: {breach}")
    return 1 if breaches else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("aggregate",))
    parser.add_argument("--rehearsals-file", default=str(DEFAULT_REHEARSALS))
    args = parser.parse_args()
    return aggregate(Path(args.rehearsals_file))


if __name__ == "__main__":
    sys.exit(main())

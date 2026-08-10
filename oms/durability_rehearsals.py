"""Record and aggregate durability rehearsals for the Tier B durability gate.

The gate names two subjects: a fresh-volume backup and restore, and a replica
failover. Each has its own harness and neither can judge the gate alone, so both
record a rehearsal here and the verdict is derived from the union. This is the
arrangement `chaos_rehearsals.py` already uses, reused rather than reinvented.

It replaces no arrangement at all, which is the point. Until 2026-08-08 nothing
in this repository wrote `tier-b-durability-evidence.json`. The file existed,
carried a well-formed envelope, named these two scripts in its `harness` field,
and had been counted as a passing gate since head 0038 -- but no code produced
it. It was written by hand.

That defeats the rule the envelope exists to enforce: a harness cannot record
PASS by asserting it, because the verdict is derived from the numbers. A
hand-written file satisfies every check the auditor performs while proving only
that someone typed numbers that pass. Eight of the ten gates were structurally
incapable of that. This one was not.

  python oms/durability_rehearsals.py aggregate
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_REHEARSALS = REPO_ROOT / "docs" / "durability-rehearsals.jsonl"

SUBJECTS = ("backup_restore", "replica_failover")

# From the Tier B gate: "fresh-volume backup/restore and replica failover with
# zero committed-record loss". The recovery-time bounds are the same ones the
# rehearsal scripts already carry.
RESTORE_READINESS_LIMIT_SECONDS = 1800.0
FAILOVER_PROMOTION_LIMIT_SECONDS = 1800.0


def record(subject: str, measurements: Dict[str, Any], harness: str,
           observed_head: str,
           rehearsals_file: Optional[Path] = None) -> Dict[str, Any]:
    """Append one rehearsal, refusing to misattribute the schema it ran on.

    `observed_head` is `alembic_version` read from the database the rehearsal
    actually touched. It is required, and it must match, because `current_head()`
    derives the head from the *repository's* migration files -- it says what the
    code declares, not what any database contains. A rehearsal against a fixture
    left at an older schema would otherwise be stamped with today's head and
    counted as current evidence.

    That would be a well-formed provenance field asserting something false, in
    the one gate whose subject is whether a schema survives being backed up and
    restored. An optional check is one a future harness forgets, so it is a
    required argument.
    """
    if subject not in SUBJECTS:
        raise ValueError(f"unknown durability subject {subject!r}; expected one of {SUBJECTS}")
    from tier_b_evidence import current_head

    head = current_head()
    if not observed_head:
        raise ValueError(
            f"{harness} did not report the migration head of the database it "
            "rehearsed. Read alembic_version and pass it as observed_head."
        )
    if observed_head != head:
        raise ValueError(
            f"This rehearsal ran against a database at {observed_head!r} while the "
            f"repository declares {head!r}. Recording it would stamp the journal with "
            "a schema the measurement never touched. Migrate the fixture and rehearse "
            "again, or rehearse at the matching checkout."
        )
    path = Path(rehearsals_file) if rehearsals_file else DEFAULT_REHEARSALS
    # Each rehearsal records the head it ran at, so the aggregate cannot combine
    # work from different schemas into one file claiming a single current head.
    entry = {"subject": subject, "at": int(time.time()), "harness": harness,
             "migration_head": head, "observed_migration_head": observed_head,
             "measurements": measurements}
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
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


def summarize(rehearsals: List[Dict[str, Any]]) -> Dict[str, Any]:
    def rows_for(subject: str) -> List[Dict[str, Any]]:
        return [row for row in rehearsals
                if row.get("subject") == subject and isinstance(row.get("measurements"), dict)]

    def worst(rows: List[Dict[str, Any]], key: str, default: float) -> float:
        """The worst observation, never the mean.

        An operator experiences the slowest restore, not the average one, and a
        mean lets one good rehearsal bury one that breached.
        """
        values = [row["measurements"].get(key) for row in rows]
        numeric = [float(v) for v in values if isinstance(v, (int, float))]
        return max(numeric) if numeric else default

    def total(rows: List[Dict[str, Any]], key: str) -> int:
        return sum(int(row["measurements"].get(key) or 0) for row in rows)

    restores = rows_for("backup_restore")
    failovers = rows_for("replica_failover")

    # An empty record is a breach, not a pass. A `_max` threshold with nothing
    # to compare satisfies itself for want of a maximum, so "never rehearsed"
    # would otherwise read exactly like "never exceeded".
    return {
        "backup_restore_rehearsals": len(restores),
        "replica_failover_rehearsals": len(failovers),
        "fresh_volume_restores": total(restores, "fresh_volume_restores"),
        "restore_readiness_seconds": worst(
            restores, "restore_readiness_seconds", RESTORE_READINESS_LIMIT_SECONDS + 1),
        "restore_state_mismatches": total(restores, "restore_state_mismatches"),
        "backup_seconds": worst(restores, "backup_seconds", 0.0),
        "promotions_out_of_recovery": total(failovers, "promotions_out_of_recovery"),
        "failover_promotion_seconds": worst(
            failovers, "failover_promotion_seconds", FAILOVER_PROMOTION_LIMIT_SECONDS + 1),
        "failover_state_mismatches": total(failovers, "failover_state_mismatches"),
        "committed_probe_lost": total(failovers, "committed_probe_lost"),
        "subjects_covered": sorted({row.get("subject") for row in rehearsals if row.get("subject")}),
    }


def at_head(rehearsals: List[Dict[str, Any]], head: str) -> List[Dict[str, Any]]:
    """Rehearsals that ran at `head` *and* verified the database was there too.

    A row must carry `observed_migration_head` matching `migration_head`. Rows
    written before the check are excluded rather than trusted -- not because they
    are known to be wrong, but because nothing in them can show they are right.

    The two rows recorded on 2026-08-08 were in fact correct: their harness
    evidence names `source_container: ontology_postgres` at
    `0041_drop_redundant_pk_indexes`, matching what they claimed. They were
    excluded anyway, and re-run, because "the file happens to be accurate" is not
    a property the gate can check.

    The hole was real even though it had not yet produced a bad file. Both
    harnesses default to the `ontology_scale_reference` container, whose volume
    sits at `0031_artifact_review_workflows` -- eleven migrations back, with no
    geo columns and no facet rollup table. Those runs only avoided it because an
    operator passed environment overrides. Without this check, the default path
    stamps today's repository head onto a measurement of a schema from nine days
    ago, and the file gives no way to tell.
    """
    return [row for row in rehearsals
            if row.get("migration_head") == head
            and row.get("observed_migration_head") == head]


def aggregate(rehearsals_file: Optional[Path] = None,
              output_dir: Optional[Path] = None) -> int:
    """Emit the gate. `output_dir` redirects the file away from docs/.

    Inspection needs somewhere to go. A recorded FAIL at the current head is
    sticky by design -- a gate that passes only after repeated attempts has not
    passed -- so running this merely to see where the journal stands writes a
    failure that then outlives its own reason. That is not hypothetical: it
    happened here on 2026-08-09, replacing a real emitted PASS with a FAIL that
    measured nothing but an empty journal.
    """
    from tier_b_evidence import current_head, write_evidence

    path = Path(rehearsals_file) if rehearsals_file else DEFAULT_REHEARSALS
    head = current_head()
    everything = load(path)
    current = at_head(everything, head)
    summary = summarize(current)
    summary["rehearsals_ignored_at_other_heads"] = len(everything) - len(current)

    print(json.dumps(summary, indent=2, sort_keys=True))

    gate_path, status, breaches = write_evidence(
        "durability",
        thresholds={
            # Both subjects must have been rehearsed. Without these two the gate
            # could pass on one half of its own scope.
            "backup_restore_rehearsals_min": 1,
            "replica_failover_rehearsals_min": 1,
            "fresh_volume_restores_min": 1,
            "promotions_out_of_recovery_min": 1,
            "restore_readiness_seconds_max": RESTORE_READINESS_LIMIT_SECONDS,
            "failover_promotion_seconds_max": FAILOVER_PROMOTION_LIMIT_SECONDS,
            "restore_state_mismatches_max": 0,
            "failover_state_mismatches_max": 0,
            "committed_probe_lost_max": 0,
        },
        measurements={key: value for key, value in summary.items()
                      if key not in {"subjects_covered", "rehearsals_ignored_at_other_heads"}},
        harness="oms/durability_rehearsals.py",
        entry_points=[
            "aggregate of oms/rehearse_ontology_scale_backup_restore.py",
            "aggregate of oms/rehearse_ontology_scale_replica_failover.py",
        ],
        request_shapes=[
            "physical backup and restore onto a fresh volume",
            "streaming replica promotion with a committed probe",
        ],
        notes=(
            f"Derived from {len(current)} rehearsal(s) at {head}; "
            f"{summary['rehearsals_ignored_at_other_heads']} recorded at other heads ignored."
        ),
        output_dir=output_dir,
    )
    print(f"\nTier B evidence {status}: {gate_path.name}")
    for breach in breaches:
        print(f"  breach: {breach}")
    return 0 if status == "PASS" else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("mode", choices=["aggregate"])
    parser.add_argument("--rehearsals-file", default=None)
    parser.add_argument(
        "--output-dir", default=None,
        help="Write the gate here instead of docs/. Use this to inspect the "
             "journal: a FAIL recorded in docs/ at the current head is sticky.")
    args = parser.parse_args()
    return aggregate(
        Path(args.rehearsals_file) if args.rehearsals_file else None,
        Path(args.output_dir) if args.output_dir else None,
    )


if __name__ == "__main__":
    sys.exit(main())

"""Durability gate aggregation across both of its named subjects.

The gate covers a fresh-volume backup/restore and a replica failover. Neither
harness can judge it alone, so the verdict comes from the union -- and the cases
that matter are the ones where the union is incomplete, because that is how a
gate comes to read as satisfied while covering half of itself.

This exists because until 2026-08-08 nothing produced this gate's evidence at
all: the file was written by hand and counted as passing since head 0038.
"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from durability_rehearsals import (  # noqa: E402
    FAILOVER_PROMOTION_LIMIT_SECONDS, RESTORE_READINESS_LIMIT_SECONDS,
    SUBJECTS, at_head, load, record, summarize,
)
from tier_b_evidence import compare, current_head  # noqa: E402

HEAD = current_head()
passed = 0


def check(condition, label, payload=None):
    global passed
    assert condition, f"{label}: {payload}"
    passed += 1


THRESHOLDS = {
    "backup_restore_rehearsals_min": 1,
    "replica_failover_rehearsals_min": 1,
    "fresh_volume_restores_min": 1,
    "promotions_out_of_recovery_min": 1,
    "restore_readiness_seconds_max": RESTORE_READINESS_LIMIT_SECONDS,
    "failover_promotion_seconds_max": FAILOVER_PROMOTION_LIMIT_SECONDS,
    "restore_state_mismatches_max": 0,
    "failover_state_mismatches_max": 0,
    "committed_probe_lost_max": 0,
}


def restore(readiness=12.0, mismatches=0, fresh=1, head=HEAD, observed=None):
    return {"subject": "backup_restore", "at": 1, "harness": "x", "migration_head": head,
            "observed_migration_head": head if observed is None else observed,
            "measurements": {"fresh_volume_restores": fresh,
                             "restore_readiness_seconds": readiness,
                             "backup_seconds": 3.0,
                             "restore_state_mismatches": mismatches}}


def failover(promotion=9.0, mismatches=0, promoted=1, probe_lost=0, head=HEAD, observed=None):
    return {"subject": "replica_failover", "at": 1, "harness": "x", "migration_head": head,
            "observed_migration_head": head if observed is None else observed,
            "measurements": {"promotions_out_of_recovery": promoted,
                             "failover_promotion_seconds": promotion,
                             "failover_state_mismatches": mismatches,
                             "committed_probe_lost": probe_lost}}


def verdict(rows):
    summary = summarize(rows)
    measurements = {k: v for k, v in summary.items()
                    if k not in {"subjects_covered", "rehearsals_ignored_at_other_heads"}}
    return compare(THRESHOLDS, measurements)


# An empty record must breach. A `_max` threshold with no data satisfies itself
# for want of a maximum, so "never rehearsed" would otherwise be indistinguishable
# from "never exceeded" -- the failure this project has already recorded once.
check(verdict([]), "no rehearsals at all is a breach, not a pass", verdict([]))

check(verdict([restore()]), "backup/restore alone does not satisfy the gate")
check(verdict([failover()]), "failover alone does not satisfy the gate")
check(not verdict([restore(), failover()]), "both subjects together satisfy it",
      verdict([restore(), failover()]))

# Zero-tolerance thresholds.
check(verdict([restore(mismatches=1), failover()]), "a restore state mismatch breaches")
check(verdict([restore(), failover(mismatches=1)]), "a failover state mismatch breaches")
check(verdict([restore(), failover(probe_lost=1)]),
      "a lost committed probe breaches -- the gate's whole subject")
check(verdict([restore(), failover(promoted=0)]),
      "a standby that never left recovery breaches")
check(verdict([restore(fresh=0), failover()]), "a restore onto a reused volume breaches")

# The worst observation is the measurement, never the mean: one slow restore
# must not be buried by a fast one.
slow = [restore(readiness=RESTORE_READINESS_LIMIT_SECONDS + 1), restore(), failover()]
check(verdict(slow), "one breaching restore among passing ones still breaches", verdict(slow))

# Head filtering: rehearsals from another schema must not launder into a file
# that claims the current head.
mixed = [restore(head="0001_runtime_baseline"), failover()]
check(len(at_head(mixed, HEAD)) == 1, "rehearsals at other heads are excluded")
check(verdict(at_head(mixed, HEAD)), "and what remains is judged incomplete")

# The row that claims the current head while having measured an older database.
# This is not hypothetical: it is what the 2026-08-08 rehearsals did, stamping
# 0041 from the repository while the fixture sat at 0031.
misattributed = [restore(observed="0031_artifact_review_workflows"), failover()]
check(len(at_head(misattributed, HEAD)) == 1,
      "a rehearsal whose database was at another head is excluded")
check(verdict(at_head(misattributed, HEAD)),
      "so a gate cannot pass on a schema its run never touched")

# Rows written before the check existed cannot be shown to be sound, so they are
# excluded rather than trusted.
legacy = [{k: v for k, v in restore().items() if k != "observed_migration_head"}, failover()]
check(len(at_head(legacy, HEAD)) == 1, "rows with no observed head are excluded")

# Round-trip through the journal, so `record` and `load` agree on the shape.
with tempfile.TemporaryDirectory() as directory:
    journal = Path(directory) / "durability.jsonl"
    record("backup_restore", {"fresh_volume_restores": 1, "restore_readiness_seconds": 5.0,
                              "backup_seconds": 1.0, "restore_state_mismatches": 0},
           harness="test", observed_head=HEAD, rehearsals_file=journal)
    record("replica_failover", {"promotions_out_of_recovery": 1,
                                "failover_promotion_seconds": 4.0,
                                "failover_state_mismatches": 0, "committed_probe_lost": 0},
           harness="test", observed_head=HEAD, rehearsals_file=journal)
    rows = load(journal)
    check(len(rows) == 2, "both rehearsals round-trip through the journal", len(rows))
    check(all(row["migration_head"] == HEAD for row in rows),
          "each records the head it ran at")
    check(all(row["observed_migration_head"] == HEAD for row in rows),
          "and the head of the database it actually touched")
    check(not verdict(rows), "and together they satisfy the gate", verdict(rows))

    # current_head() reads the repository's migration files, not any database.
    # A fixture left at an older schema would otherwise be stamped with today's
    # head -- a true-looking provenance field asserting something false, in the
    # gate whose whole subject is whether a schema survives a restore.
    try:
        record("backup_restore", {"fresh_volume_restores": 1}, harness="test",
               observed_head="0001_runtime_baseline", rehearsals_file=journal)
        raise AssertionError("a rehearsal on a stale fixture was recorded as current")
    except ValueError as error:
        check("never touched" in str(error), "the refusal explains the misattribution", error)

    for absent in ("", None):
        try:
            record("backup_restore", {"fresh_volume_restores": 1}, harness="test",
                   observed_head=absent, rehearsals_file=journal)
            raise AssertionError("a rehearsal that reported no database head was accepted")
        except ValueError:
            passed += 1

    check(len(load(journal)) == 2, "and none of the refusals reached the journal")

try:
    record("not_a_subject", {}, harness="test", observed_head=HEAD)
    raise AssertionError("an unknown subject was accepted")
except ValueError:
    passed += 1

check(set(SUBJECTS) == {"backup_restore", "replica_failover"}, "the gate names two subjects")

print(f"Durability rehearsal aggregation: {passed} assertions passed.")

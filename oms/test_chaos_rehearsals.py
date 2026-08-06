"""Chaos gate aggregation across both of its named subjects."""
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from chaos_rehearsals import (  # noqa: E402
    RECONNECT_LIMIT_MS, aggregate, at_head, load, record, summarize,
)
from tier_b_evidence import current_head  # noqa: E402

HEAD = current_head()

passed = 0


def check(condition, label, payload=None):
    global passed
    assert condition, f"{label}: {payload}"
    passed += 1


def collab(reconnect=120.0, duplicates=0, missed=0):
    return {"subject": "collaboration", "at": 1, "harness": "x", "migration_head": HEAD,
            "measurements": {
        "reconnect_max_ms": reconnect, "duplicate_events": duplicates,
        "missed_events": missed, "replica_terminations": 1, "replica_restarts": 1,
    }}


def cross(duplicate_pairs=0, missed_pairs=0):
    return {"subject": "cross_stream", "at": 2, "harness": "y", "migration_head": HEAD,
            "measurements": {
        "duplicate_pairs": duplicate_pairs, "missed_pairs": missed_pairs,
        "emitted_pairs": 60, "expected_pairs": 60,
    }}


both = summarize([collab(), cross()])
check(both["collaboration_rehearsals"] == 1, "counts collaboration", both)
check(both["cross_stream_rehearsals"] == 1, "counts cross-stream", both)
check(both["subjects_covered"] == ["collaboration", "cross_stream"], "records coverage", both)

# Losses are summed, not averaged. One clean rehearsal must not cancel a run
# that dropped an event.
summed = summarize([collab(missed=1), collab(missed=0), cross()])
check(summed["missed_events"] == 1, "missed events are summed across rehearsals", summed)

# The worst reconnect across rehearsals is the reported figure.
worst = summarize([collab(reconnect=100.0), collab(reconnect=900.0), cross()])
check(worst["reconnect_max_ms"] == 900.0, "the worst reconnect is reported", worst)


def evidence_for(rows):
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        path = Path(tmpdir) / "chaos.jsonl"
        if rows:
            path.write_text("\n".join(json.dumps(r, sort_keys=True) for r in rows) + "\n",
                            encoding="utf-8")
        output_dir = Path(tmpdir) / "evidence"
        code = aggregate(path, output_dir=output_dir)
        payload = json.loads((output_dir / "tier-b-chaos-evidence.json").read_text(encoding="utf-8"))
        return code, payload


# The gate names two subjects. Covering one and reading as satisfied is the
# failure this aggregation exists to prevent.
code, payload = evidence_for([collab()])
check(code == 1, "collaboration alone does not satisfy the gate", code)
check(any("cross_stream" in b for b in payload["breaches"]), "the breach names the missing half",
      payload["breaches"])

code, payload = evidence_for([cross()])
check(code == 1, "cross-stream alone does not satisfy the gate", code)
check(any("collaboration" in b for b in payload["breaches"]), "the breach names the missing half",
      payload["breaches"])

# With no collaboration rehearsal there is no reconnect measurement, and a _max
# threshold with no data would otherwise satisfy itself.
check(any("reconnect_max_ms" in b for b in payload["breaches"]),
      "an absent reconnect measurement breaches rather than passes", payload["breaches"])

code, payload = evidence_for([])
check(code == 1, "an empty record does not satisfy the gate", code)

code, payload = evidence_for([collab(), cross()])
check(code == 0, "both subjects rehearsed satisfies the gate", payload.get("breaches"))
check(payload["status"] == "PASS", "recorded PASS", payload["status"])
check(payload["provenance"]["migration_head"], "carries provenance", payload["provenance"])

code, payload = evidence_for([collab(duplicates=1), cross()])
check(code == 1, "a duplicated event fails the gate", code)
code, payload = evidence_for([collab(), cross(missed_pairs=1)])
check(code == 1, "a lost pair fails the gate", code)

try:
    record("bogus_subject", {}, harness="z")
    check(False, "an unknown subject is rejected")
except ValueError:
    check(True, "an unknown subject is rejected")

with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
    torn = Path(tmpdir) / "torn.jsonl"
    torn.write_text('{"subject": "collaboration", "at": 1, "measurements": {}}\n{"subj',
                    encoding="utf-8")
    check(len(load(torn)) == 1, "a torn final line is skipped", None)

docs_dir = Path(__file__).resolve().parent.parent / "docs"
existing = docs_dir / "tier-b-chaos-evidence.json"
before = existing.read_text(encoding="utf-8") if existing.exists() else None
check(before is None or json.loads(before)["gate_id"] == "chaos", "docs evidence untouched by tests")
check(RECONNECT_LIMIT_MS == 5000.0, "reconnect limit matches the contract")

# A rehearsal run before the head advanced describes a different schema. Counting
# it would let the gate read as satisfied on work that was never repeated, which
# is the non-completion rule violated from the inside rather than from outside.
stale_collab = dict(collab(), migration_head="0001_runtime_baseline")
stale_cross = dict(cross(), migration_head="0001_runtime_baseline")
check(at_head([stale_collab], HEAD) == [], "a rehearsal from an older head is dropped")
check(at_head([collab()], HEAD) != [], "a rehearsal at the current head is kept")
check(at_head([{"subject": "collaboration", "at": 1, "measurements": {}}], HEAD) == [],
      "a record predating the head field is dropped rather than assumed current")

code, payload = evidence_for([stale_collab, stale_cross])
check(code == 1, "both subjects rehearsed at an older head do not satisfy the gate", code)
check(payload["measurements"]["rehearsals_ignored_at_other_heads"] == 2,
      "the evidence records how many rehearsals were ignored", payload["measurements"])
check(payload["measurements"]["subjects_covered"] == [],
      "no subject is covered once stale rehearsals are dropped", payload["measurements"])

print(f"\nChaos rehearsal aggregation verified: {passed} assertions passed.")

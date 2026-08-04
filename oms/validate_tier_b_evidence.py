"""Audit Tier B gate evidence against the measurement contract.

Reports one row per gate in docs/GOAL_2026-08-03.md Tier B, and exits non-zero
unless every gate has a current, passing, provenanced evidence file.

A gate is only counted when its evidence file carries the envelope defined in
docs/TIER_B_MEASUREMENT_CONTRACT.md, states the thresholds it was judged
against, and records the migration head that produced it. Evidence from an
earlier head is reported as STALE rather than passing, which is the goal's
non-completion rule expressed as a check instead of a memory.

Run:
  python oms/validate_tier_b_evidence.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from tier_b_evidence import compare, current_head

REPO_ROOT = Path(__file__).resolve().parent.parent
DOCS = REPO_ROOT / "docs"

# Gate identifier -> the evidence file the harness is expected to emit.
GATES = {
    "ontology_scale": "tier-b-ontology-scale-evidence.json",
    "mixed_workload": "tier-b-mixed-workload-evidence.json",
    "pipeline_scale": "tier-b-pipeline-scale-evidence.json",
    "collaboration": "tier-b-collaboration-evidence.json",
    "identity": "tier-b-identity-evidence.json",
    "availability": "tier-b-availability-evidence.json",
    "rpo": "tier-b-rpo-evidence.json",
    "rto": "tier-b-rto-evidence.json",
    "durability": "tier-b-durability-evidence.json",
    "chaos": "tier-b-chaos-evidence.json",
}

# Pre-contract files kept as prior art. They are never counted as passing: none
# of them records the head that produced it, so staleness cannot be ruled out.
PRIOR_ART = {
    "ontology_scale": "ontology-scale-reference-evidence.json",
    "mixed_workload": "ontology-mixed-workload-reference-evidence.json",
    "pipeline_scale": "pipeline-scale-reference-evidence.json",
    "collaboration": "collaboration-websocket-chaos-evidence.json",
    "identity": "oidc-identity-scale-evidence.json",
    "durability": "ontology-scale-backup-restore-evidence.json",
    "chaos": "ontology-scale-replica-failover-evidence.json",
}

REQUIRED_PROVENANCE = ("migration_head", "git_commit", "captured_at", "harness")


def audit_gate(gate_id: str, filename: str, head: str) -> tuple[str, str]:
    path = DOCS / filename
    if not path.exists():
        prior = PRIOR_ART.get(gate_id)
        if prior and (DOCS / prior).exists():
            return "MISSING", f"no contract evidence; prior art {prior} is unprovenanced"
        return "MISSING", "no evidence file"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        return "INVALID", f"unreadable JSON: {error}"

    provenance = payload.get("provenance") or {}
    absent = [field for field in REQUIRED_PROVENANCE if not provenance.get(field)]
    if absent:
        return "INVALID", f"provenance missing {', '.join(absent)}"
    if provenance["migration_head"] != head:
        return "STALE", f"produced at {provenance['migration_head']}, current head is {head}"

    thresholds = payload.get("thresholds")
    measurements = payload.get("measurements")
    if not isinstance(thresholds, dict) or not thresholds:
        return "INVALID", "no thresholds recorded"
    if not isinstance(measurements, dict) or not measurements:
        return "INVALID", "no measurements recorded"

    breaches = compare(thresholds, measurements)
    if breaches:
        return "FAIL", "; ".join(breaches)
    if payload.get("status") != "PASS":
        return "FAIL", f"status is {payload.get('status')!r} despite satisfied thresholds"
    return "PASS", f"{len(thresholds)} thresholds satisfied"


def main() -> int:
    head = current_head()
    print("Tier B evidence audit")
    print(f"Current migration head: {head}\n")

    tally: dict[str, int] = {}
    width = max(len(name) for name in GATES)
    for gate_id, filename in GATES.items():
        verdict, detail = audit_gate(gate_id, filename, head)
        tally[verdict] = tally.get(verdict, 0) + 1
        print(f"  {gate_id.ljust(width)}  {verdict.ljust(7)}  {detail}")

    passed = tally.get("PASS", 0)
    print(f"\n{passed} of {len(GATES)} gates satisfied.")
    print("  " + ", ".join(f"{verdict}: {count}" for verdict, count in sorted(tally.items())))

    if passed != len(GATES):
        print("\nTier B is not accepted. Gates above that are not PASS have no current,")
        print("provenanced, threshold-checked evidence at this migration head.")
        return 1
    print("\nEvery Tier B gate carries current provenanced evidence.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

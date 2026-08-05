"""Evidence corpus classification and the unprovenanced ratchet."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import audit_evidence_corpus as audit  # noqa: E402
from audit_evidence_corpus import CURRENT, STALE, UNPROVENANCED, head_of  # noqa: E402

passed = 0
HEAD = "0037_cross_stream_joins"


def check(condition, label, payload=None):
    global passed
    assert condition, f"{label}: {payload}"
    passed += 1


check(head_of({"provenance": {"migration_head": HEAD}}) == HEAD, "reads the contract envelope")
check(head_of({"migration": "0031_artifact_review_workflows"}) == "0031_artifact_review_workflows",
      "reads a top-level head")

# The real pre-contract shape: buried three levels down under a different name.
nested = {"source_state": {"migration": "0031_artifact_review_workflows", "objects": 10_000_000}}
check(head_of(nested) == "0031_artifact_review_workflows", "reads a nested head", nested)

check(head_of({"status": "PASS", "reconnect_max_ms": 209.067}) == "", "no head is no head")

# A revision-shaped filter keeps unrelated counters from being read as a schema
# head. Without it, an artifact revision counter would classify dated evidence
# as current, which is the one direction this audit must never get wrong.
check(head_of({"revision": 4}) == "", "an integer revision counter is not a head")
check(head_of({"revision": "final_revision"}) == "", "an unshaped revision string is not a head")
check(head_of({"revision": "0031_artifact_review_workflows"}) == "0031_artifact_review_workflows",
      "a revision-shaped string is a head")

check(head_of({"a": {"b": {"c": {"d": {"migration": HEAD}}}}}) == "",
      "the search is depth-bounded rather than unbounded")

check(head_of({"provenance": {"migration_head": HEAD}, "migration": "0001_runtime_baseline"}) == HEAD,
      "the contract envelope wins over a stray legacy key")


def classify_payload(payload):
    import tempfile
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        path = Path(tmpdir) / "x-evidence.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        return audit.classify(path, HEAD)[0]


check(classify_payload({"provenance": {"migration_head": HEAD}}) == CURRENT, "current head is CURRENT")
check(classify_payload({"provenance": {"migration_head": "0031_x"}}) == STALE, "an older head is STALE")
check(classify_payload({"status": "PASS"}) == UNPROVENANCED, "no head is UNPROVENANCED")

# STALE is a better verdict than UNPROVENANCED: dated evidence can be shown to
# be dated, while unprovenanced evidence reads as valid forever.
check(STALE != UNPROVENANCED, "the two states are distinct")

# The baseline file matches the evidence glob by name. If the scan counts it,
# it reports itself as unprovenanced and breaks the ratchet it exists to hold.
check(audit.BASELINE.name not in {row["file"] for row in audit.scan(audit.current_head())},
      "the audit does not count its own baseline file")

baseline = audit.load_baseline()
check("unprovenanced_ceiling" in baseline, "a baseline is recorded", baseline)
live = audit.scan(audit.current_head())
unprovenanced = sum(1 for row in live if row["state"] == UNPROVENANCED)
check(unprovenanced <= baseline["unprovenanced_ceiling"],
      "the corpus holds its ratchet",
      {"unprovenanced": unprovenanced, "ceiling": baseline["unprovenanced_ceiling"]})

print(f"\nEvidence corpus audit verified: {passed} assertions passed.")

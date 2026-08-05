"""RTO rehearsal accounting and gate evidence."""
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from rto_rehearsal import (  # noqa: E402
    REQUIRED_REHEARSALS,
    REQUIRED_UNATTENDED,
    RTO_LIMIT_SECONDS,
    aggregate,
    load_rehearsals,
    summarize,
)

passed = 0


def check(condition, label, payload=None):
    global passed
    assert condition, f"{label}: {payload}"
    passed += 1


def rehearsal(elapsed, trigger="attended", recovered=True, at=0):
    return {
        "at": 1_700_000_000 + at, "trigger": trigger, "restore_exit": 0,
        "restore_seconds": elapsed / 2, "ready_seconds": elapsed * 0.9,
        "elapsed_seconds": elapsed, "recovered": recovered, "note": "",
    }


empty = summarize([])
check(empty["rehearsals"] == 0, "no rehearsals is zero", empty)
check(empty["max_elapsed_seconds"] == 0, "no rehearsals has no maximum", empty)

four = [rehearsal(600, at=i * 100) for i in range(4)]
summary = summarize(four)
check(summary["rehearsals"] == 4, "counts rehearsals", summary)
check(summary["max_elapsed_seconds"] == 600, "reports the maximum", summary)
check(summary["unattended_rehearsals"] == 0, "attended runs are not unattended", summary)

# The maximum, not the mean, is the reported figure. Three fast rehearsals must
# not conceal one that breached.
mixed = [rehearsal(60, at=0), rehearsal(60, at=100), rehearsal(60, at=200), rehearsal(2000, at=300)]
mixed_summary = summarize(mixed)
check(mixed_summary["max_elapsed_seconds"] == 2000, "one slow rehearsal sets the maximum", mixed_summary)
check(
    sum(mixed_summary["elapsed_distribution_seconds"]) / 4 < RTO_LIMIT_SECONDS,
    "the mean would have passed, which is why the maximum is used",
    mixed_summary["elapsed_distribution_seconds"],
)

failed = summarize([rehearsal(300, recovered=False)])
check(failed["failed_recoveries"] == 1, "a rehearsal that never served is a failed recovery", failed)

unattended = summarize([rehearsal(300, trigger="unattended")])
check(unattended["unattended_rehearsals"] == 1, "counts unattended rehearsals", unattended)


def evidence_for(rehearsals):
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        path = Path(tmpdir) / "rehearsals.jsonl"
        if rehearsals:
            path.write_text(
                "\n".join(json.dumps(item, sort_keys=True) for item in rehearsals) + "\n",
                encoding="utf-8",
            )
        output_dir = Path(tmpdir) / "evidence"
        code = aggregate(path, output_dir=output_dir)
        payload = json.loads((output_dir / "tier-b-rto-evidence.json").read_text(encoding="utf-8"))
        return code, payload


# An empty record must not pass by having no maximum to breach. This is the
# failure mode where "no data" silently satisfies a <= threshold.
code, payload = evidence_for([])
check(code == 1, "no rehearsals does not satisfy the gate", code)
check(payload["status"] == "FAIL", "no rehearsals is recorded FAIL", payload["status"])
check(
    any("max_elapsed_seconds" in breach for breach in payload["breaches"]),
    "an empty record breaches the elapsed threshold rather than passing it",
    payload["breaches"],
)

code, payload = evidence_for([rehearsal(600, at=i * 100) for i in range(REQUIRED_REHEARSALS)])
check(code == 1, "four attended rehearsals still miss the unattended requirement", code)
check(
    any("unattended" in breach for breach in payload["breaches"]),
    "the breach names the missing unattended rehearsal", payload["breaches"],
)

complete = [rehearsal(600, at=i * 100) for i in range(REQUIRED_REHEARSALS - 1)]
complete.append(rehearsal(900, trigger="unattended", at=999))
code, payload = evidence_for(complete)
check(code == 0, "four rehearsals including one unattended satisfy the gate", payload.get("breaches"))
check(payload["status"] == "PASS", "a complete schedule is recorded PASS", payload["status"])
check(payload["measurements"]["max_elapsed_seconds"] == 900, "evidence carries the maximum", payload["measurements"])
check(payload["provenance"]["migration_head"], "evidence carries provenance", payload["provenance"])

breaching = [rehearsal(600, at=0), rehearsal(600, at=100), rehearsal(600, at=200),
             rehearsal(RTO_LIMIT_SECONDS + 1, trigger="unattended", at=300)]
code, payload = evidence_for(breaching)
check(code == 1, "a rehearsal over the limit fails the gate", code)
check(
    any("max_elapsed_seconds" in breach for breach in payload["breaches"]),
    "the breach names the elapsed maximum", payload["breaches"],
)

with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
    torn = Path(tmpdir) / "torn.jsonl"
    torn.write_text('{"at": 1, "elapsed_seconds": 5, "recovered": true}\n{"at": 2, "elap',
                    encoding="utf-8")
    check(len(load_rehearsals(torn)) == 1, "a torn final line is skipped", None)

docs_dir = Path(__file__).resolve().parent.parent / "docs"
check(
    not (docs_dir / "tier-b-rto-evidence.json").exists(),
    "running this test does not leave gate evidence in docs/", None,
)
check(RTO_LIMIT_SECONDS == 1800 and REQUIRED_UNATTENDED >= 1, "thresholds match the contract", None)

print(f"\nRTO rehearsal verified: {passed} assertions passed.")

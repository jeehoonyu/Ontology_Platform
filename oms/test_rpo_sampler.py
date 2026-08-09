"""RPO sampling accounting and gate evidence."""
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from rpo_sampler import (  # noqa: E402
    REQUIRED_PRE_BACKUP_SAMPLES,
    REQUIRED_SAMPLES,
    RPO_LIMIT_SECONDS,
    aggregate,
    load_jsonl,
    summarize,
)
from app.pilot_evidence import (  # noqa: E402
    JournalIntegrityError, append_observation, current_migration_head,
)

passed = 0


def check(condition, label, payload=None):
    global passed
    assert condition, f"{label}: {payload}"
    passed += 1


def sample(rpo, phase="mid_cycle", total_loss=False, at=0):
    return {
        "at": 1_700_000_000 + at, "phase": phase, "note": "",
        "last_written_sequence": 100, "surviving_sequence": None if total_loss else 99,
        "rpo_seconds": rpo, "total_loss": total_loss,
    }


empty = summarize([])
check(empty["samples"] == 0 and empty["max_rpo_seconds"] == 0, "no samples is zero", empty)

ten = [sample(60, at=i) for i in range(10)]
summary = summarize(ten)
check(summary["samples"] == 10, "counts samples", summary)
check(summary["max_rpo_seconds"] == 60, "reports the maximum", summary)
check(summary["pre_backup_samples"] == 0, "mid-cycle samples are not pre-backup", summary)

# The maximum is reported because a mid-cycle sample flatters the system. Nine
# good samples must not bury the one taken at the worst point in the cycle.
skewed = [sample(30, at=i) for i in range(9)] + [sample(600, phase="pre_backup", at=9)]
skewed_summary = summarize(skewed)
check(skewed_summary["max_rpo_seconds"] == 600, "the worst sample sets the maximum", skewed_summary)
check(
    sum(skewed_summary["rpo_distribution_seconds"]) / 10 < RPO_LIMIT_SECONDS,
    "the mean would have passed, which is why the maximum is used",
    skewed_summary["rpo_distribution_seconds"],
)

loss = summarize([sample(0, total_loss=True)])
check(loss["total_loss_samples"] == 1, "a total loss is counted", loss)


def evidence_for(samples):
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        path = Path(tmpdir) / "samples.jsonl"
        for index, item in enumerate(samples):
            append_observation(
                path, run_id="rpo_test", kind="rpo_observation",
                target="http://recovery.test", migration_head=current_migration_head(),
                scheduled_at=1_700_000_000 + index, observed_at=1_700_000_000 + index,
                payload=item,
            )
        output_dir = Path(tmpdir) / "evidence"
        code = aggregate(path, output_dir=output_dir)
        payload = json.loads((output_dir / "tier-b-rpo-evidence.json").read_text(encoding="utf-8"))
        return code, payload


code, payload = evidence_for([])
check(code == 1, "no samples does not satisfy the gate", code)
check(
    any("max_rpo_seconds" in breach for breach in payload["breaches"]),
    "an empty record breaches the maximum rather than passing it", payload["breaches"],
)

code, payload = evidence_for([sample(60, at=i) for i in range(REQUIRED_SAMPLES)])
check(code == 1, "ten mid-cycle samples still miss the pre-backup requirement", code)
check(
    any("pre_backup" in breach for breach in payload["breaches"]),
    "the breach names the missing pre-backup samples", payload["breaches"],
)

complete = [sample(60, at=i) for i in range(REQUIRED_SAMPLES - REQUIRED_PRE_BACKUP_SAMPLES)]
complete += [sample(120, phase="pre_backup", at=90 + i) for i in range(REQUIRED_PRE_BACKUP_SAMPLES)]
code, payload = evidence_for(complete)
check(code == 0, "a complete sampling plan satisfies the gate", payload.get("breaches"))
check(payload["status"] == "PASS", "a complete plan is recorded PASS", payload["status"])
check(payload["measurements"]["max_rpo_seconds"] == 120, "evidence carries the maximum", payload["measurements"])
check("pre_backup" in payload["measurements"]["phases_covered"], "phases are recorded", payload["measurements"])

breaching = complete[:-1] + [sample(RPO_LIMIT_SECONDS + 1, phase="pre_backup", at=99)]
code, payload = evidence_for(breaching)
check(code == 1, "a sample over five minutes fails the gate", code)

# A total loss must fail even when the computed interval looks small.
with_loss = complete[:-1] + [sample(1, phase="pre_backup", total_loss=True, at=99)]
code, payload = evidence_for(with_loss)
check(code == 1, "a total loss fails the gate regardless of the interval", code)
check(
    any("total_loss" in breach for breach in payload["breaches"]),
    "the breach names the total loss", payload["breaches"],
)

with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
    torn = Path(tmpdir) / "torn.jsonl"
    append_observation(
        torn, run_id="rpo_torn", kind="rpo_observation",
        target="http://recovery.test", migration_head=current_migration_head(),
        scheduled_at=1, observed_at=1, payload=sample(1),
    )
    with torn.open("ab") as handle:
        handle.write(b'{"sequ')
    try:
        load_jsonl(torn)
        raise AssertionError("a torn RPO journal was accepted")
    except JournalIntegrityError:
        passed += 1

    tampered = Path(tmpdir) / "tampered.jsonl"
    append_observation(
        tampered, run_id="rpo_tamper", kind="rpo_observation",
        target="http://recovery.test", migration_head=current_migration_head(),
        scheduled_at=1, observed_at=1, payload=sample(1),
    )
    tampered.write_text(tampered.read_text(encoding="utf-8").replace(
        '"rpo_seconds":1', '"rpo_seconds":2', 1,
    ), encoding="utf-8")
    # Point aggregate at the altered journal directly; corruption must be a
    # named breach rather than disappearing as a skipped line.
    output = Path(tmpdir) / "tamper-evidence"
    code = aggregate(tampered, output_dir=output)
    payload = json.loads((output / "tier-b-rpo-evidence.json").read_text(encoding="utf-8"))
    check(code == 1 and payload["measurements"]["integrity_failures"] == 1,
          "tampering fails RPO evidence", payload)

docs_dir = Path(__file__).resolve().parent.parent / "docs"
check(
    not (docs_dir / "tier-b-rpo-evidence.json").exists(),
    "running this test does not leave gate evidence in docs/", None,
)
check(RPO_LIMIT_SECONDS == 300 and REQUIRED_SAMPLES == 10, "thresholds match the contract", None)

print(f"\nRPO sampler verified: {passed} assertions passed.")

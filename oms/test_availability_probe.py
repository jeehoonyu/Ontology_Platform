"""Availability probe accounting, outage opening, and evidence emission."""
import json
import os
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from availability_probe import (  # noqa: E402
    AVAILABILITY_TARGET_PCT,
    CONSECUTIVE_FAILURES_TO_OPEN,
    PROBE_INTERVAL_SECONDS,
    WINDOW_SECONDS,
    aggregate,
    summarize,
)
from app.pilot_evidence import (  # noqa: E402
    JournalIntegrityError, append_observation, current_migration_head, load_journal,
)

passed = 0


def check(condition, label, payload=None):
    global passed
    assert condition, f"{label}: {payload}"
    passed += 1


def samples(pattern):
    """pattern is a string of 'u' (up) and 'd' (down), one char per interval."""
    return [
        {"at": 1_700_000_000 + index * PROBE_INTERVAL_SECONDS, "available": char == "u"}
        for index, char in enumerate(pattern)
    ]


def write_journal(path, rows):
    for row in rows:
        append_observation(
            path, run_id="pilot_test", kind="availability", target="http://pilot",
            migration_head=current_migration_head(), scheduled_at=row["at"],
            observed_at=row["at"], payload={"available": row["available"]},
        )


empty = summarize([])
check(empty["samples"] == 0 and empty["availability_pct"] == 0.0, "empty window is not available", empty)
check(empty["window_seconds_min"] == WINDOW_SECONDS, "window minimum is exposed", empty)

full_up = summarize(samples("u" * 20))
check(full_up["availability_pct"] == 100.0, "all-up window is 100%", full_up)
check(full_up["outages"] == 0 and full_up["unavailable_seconds"] == 0, "all-up has no outage", full_up)
check(full_up["observed_seconds"] == 20 * PROBE_INTERVAL_SECONDS, "observed span covers every interval", full_up)

# A single dropped probe must still cost availability. It must not open an
# outage, which is what keeps one flaky request from reading as downtime.
blip = summarize(samples("uuuuduuuuu"))
check(blip["outages"] == 0, "one failure does not open an outage", blip)
check(blip["unavailable_seconds"] == PROBE_INTERVAL_SECONDS, "one failure still costs its interval", blip)
check(blip["availability_pct"] == 90.0, "one of ten intervals down is 90%", blip)
check(blip["longest_outage_seconds"] == 0, "no outage means no outage length", blip)

opened = summarize(samples("uuuudduuuu"))
check(opened["outages"] == 1, "two consecutive failures open one outage", opened)
check(opened["longest_outage_seconds"] == 2 * PROBE_INTERVAL_SECONDS, "outage spans both intervals", opened)

# Consecutive failures are one outage, not one per failed probe.
sustained = summarize(samples("uudddddu"))
check(sustained["outages"] == 1, "a run of failures is a single outage", sustained)
check(sustained["longest_outage_seconds"] == 5 * PROBE_INTERVAL_SECONDS, "outage length is the whole run", sustained)

two_outages = summarize(samples("uuddu" + "uuddu"))
check(two_outages["outages"] == 2, "separated runs are distinct outages", two_outages)

# An outage still open at the end of the window must be counted, not dropped
# because no recovery sample follows it.
unterminated = summarize(samples("uuuudd"))
check(unterminated["outages"] == 1, "an outage open at the window edge counts", unterminated)
check(
    unterminated["longest_outage_seconds"] == 2 * PROBE_INTERVAL_SECONDS,
    "an unterminated outage keeps its length", unterminated,
)

budget = summarize(samples("u" * 100))
expected_budget = round(WINDOW_SECONDS * (100 - AVAILABILITY_TARGET_PCT) / 100, 1)
check(budget["error_budget_seconds"] == expected_budget, "error budget is derived from the target", budget)
check(expected_budget < 700, "a 99.9% budget over 7 days is under 12 minutes", expected_budget)

# Observer downtime is downtime. Missing a scheduled record cannot shrink the
# denominator and make the platform look healthier.
gapped = summarize([
    {"at": 1_700_000_000, "available": True},
    {"at": 1_700_000_000 + 2 * PROBE_INTERVAL_SECONDS, "available": True},
])
check(gapped["missing_samples"] == 1, "a missing cadence slot is explicit", gapped)
check(gapped["availability_pct"] == 66.6667, "a missing slot costs availability", gapped)

# A short window cannot satisfy the gate however clean it is. This is the check
# that stops a green ten-minute run from being read as a passing week.
with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
    samples_file = Path(tmpdir) / "samples.jsonl"
    recent_start = int(time.time()) - 29 * PROBE_INTERVAL_SECONDS
    recent = [
        {"at": recent_start + index * PROBE_INTERVAL_SECONDS, "available": True}
        for index in range(30)
    ]
    write_journal(samples_file, recent)
    # Emit into the temporary directory. A test must never write a file the
    # Tier B auditor would count as gate evidence.
    evidence_dir = Path(tmpdir) / "evidence"
    exit_code = aggregate(samples_file, output_dir=evidence_dir)
    check(exit_code == 1, "a short all-up window does not satisfy the gate", exit_code)

    evidence_path = evidence_dir / "tier-b-availability-evidence.json"
    check(evidence_path.exists(), "aggregate writes gate evidence", str(evidence_path))
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    check(evidence["gate_id"] == "availability", "evidence names its gate", evidence)
    check(evidence["status"] == "FAIL", "an incomplete window is recorded FAIL", evidence)
    check(
        evidence["provenance"]["migration_head"] and evidence["provenance"]["captured_at"],
        "evidence carries provenance", evidence["provenance"],
    )
    check(
        any("observed_seconds" in breach for breach in evidence["breaches"]),
        "the breach names the short window", evidence.get("breaches"),
    )
    check(evidence["measurements"]["availability_pct"] == 100.0, "a clean short window still reports 100%", evidence)

docs_dir = Path(__file__).resolve().parent.parent / "docs"
check(
    not (docs_dir / "tier-b-availability-evidence.json").exists(),
    "running this test does not leave gate evidence in docs/",
    "test-written evidence would be counted by the auditor",
)

# A torn record is detected. Silently skipping it would let observer loss erase
# an unavailable interval from the denominator.
with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
    from availability_probe import load_samples

    torn = Path(tmpdir) / "torn.jsonl"
    write_journal(torn, samples("u"))
    with torn.open("ab") as handle:
        handle.write(b'{"schema_version":1')
    try:
        load_samples(torn)
        raise AssertionError("torn journal was accepted")
    except JournalIntegrityError:
        passed += 1

with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
    altered = Path(tmpdir) / "altered.jsonl"
    write_journal(altered, samples("uu"))
    text = altered.read_text(encoding="utf-8").replace('"available":true', '"available":false', 1)
    altered.write_text(text, encoding="utf-8")
    try:
        load_journal(altered)
        raise AssertionError("modified evidence was accepted")
    except JournalIntegrityError:
        passed += 1

with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
    rolled_back = Path(tmpdir) / "rolled-back.jsonl"
    write_journal(rolled_back, samples("uu"))
    complete = load_journal(rolled_back)
    state = Path(tmpdir) / "state.json"
    state.write_text(json.dumps({
        "run_id": "pilot_test",
        "target": "http://pilot",
        "migration_head": current_migration_head(),
        "last_record_hash": complete[-1]["record_hash"],
    }) + "\n", encoding="utf-8")
    rolled_back.write_text(rolled_back.read_text(encoding="utf-8").splitlines()[0] + "\n",
                           encoding="utf-8")
    output = Path(tmpdir) / "evidence"
    code = aggregate(rolled_back, output_dir=output, state_file=state)
    evidence = json.loads((output / "tier-b-availability-evidence.json").read_text(encoding="utf-8"))
    check(code == 1 and evidence["measurements"]["integrity_failures"] == 1,
          "aggregate rejects rollback behind the durable anchor", evidence)

check(CONSECUTIVE_FAILURES_TO_OPEN == 2, "outage rule matches the measurement contract", CONSECUTIVE_FAILURES_TO_OPEN)

print(f"\nAvailability probe verified: {passed} assertions passed.")

"""Availability probe accounting, outage opening, and evidence emission."""
import json
import os
import sys
import tempfile
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

# A short window cannot satisfy the gate however clean it is. This is the check
# that stops a green ten-minute run from being read as a passing week.
with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
    samples_file = Path(tmpdir) / "samples.jsonl"
    samples_file.write_text(
        "\n".join(json.dumps(sample, sort_keys=True) for sample in samples("u" * 30)) + "\n",
        encoding="utf-8",
    )
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

# Torn trailing lines are normal for an interrupted append-only probe.
with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
    from availability_probe import load_samples

    torn = Path(tmpdir) / "torn.jsonl"
    torn.write_text('{"at": 1, "available": true}\n{"at": 2, "avail', encoding="utf-8")
    recovered = load_samples(torn)
    check(len(recovered) == 1, "a torn final line is skipped, not fatal", recovered)

check(CONSECUTIVE_FAILURES_TO_OPEN == 2, "outage rule matches the measurement contract", CONSECUTIVE_FAILURES_TO_OPEN)

print(f"\nAvailability probe verified: {passed} assertions passed.")

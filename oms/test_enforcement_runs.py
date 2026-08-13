"""The watcher needs a watcher, and it must be an automated one.

This file exists twice over. It tests `enforcement_runs`, and it is also the
automated home for `audit_enforcement` itself -- applying the live ratchet here,
not only in a CI step, because a check whose sole caller is a CI job that has
never provisioned a runner is the exact defect this whole goal is about. Building
the auditor as another CI-only script would have been funny and useless.
"""
import json
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import audit_enforcement  # noqa: E402
import enforcement_runs  # noqa: E402
from enforcement_runs import (  # noqa: E402
    CURRENT, DECLARED, NEVER, STALE, classify, load, record, recording,
)
from tier_b_evidence import current_head  # noqa: E402

HEAD = current_head()
passed = 0


def check(condition, label, payload=None):
    global passed
    assert condition, f"{label}: {payload}"
    passed += 1


with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as directory:
    runs_file = Path(directory) / "enforcement-runs.json"

    # An absent record is NEVER, not an empty pass. This is the state the whole
    # goal exists to make visible: for nineteen days every check was here.
    report = classify(load(runs_file), HEAD)
    check(len(report) == len(DECLARED), "every declared check is reported", len(report))
    check(all(row["state"] == NEVER for row in report.values()),
          "with nothing recorded, every check reads NEVER")
    check(all(row.get("purpose") for row in report.values()),
          "and each says what it guards, so NEVER is actionable")

    record("audit_query_bounds", verdict="PASS", head=HEAD, runs_file=runs_file)
    report = classify(load(runs_file), HEAD)
    check(report["audit_query_bounds"]["state"] == CURRENT, "a recorded run reads CURRENT")
    check(report["audit_evidence_corpus"]["state"] == NEVER,
          "and says nothing about any other check")

    # Staleness: ran, but against a schema that is no longer the one shipping.
    record("audit_query_bounds", verdict="PASS", head="0001_runtime_baseline",
           runs_file=runs_file)
    check(classify(load(runs_file), HEAD)["audit_query_bounds"]["state"] == STALE,
          "a run at an older head reads STALE, not CURRENT")

    # A failing check has still run. Recording only successes would let a check
    # that fails every time look identical to one that never executes.
    record("audit_extensibility", verdict="FAIL", head=HEAD, runs_file=runs_file)
    row = classify(load(runs_file), HEAD)["audit_extensibility"]
    check(row["state"] == CURRENT, "a failing check is CURRENT -- it ran", row)
    check("FAIL" in row["detail"], "and its verdict is visible", row)

    # Undeclared checks are refused rather than silently tracked, so DECLARED
    # stays the single list of what this repository expects to run.
    try:
        record("not_a_declared_check", verdict="PASS", head=HEAD, runs_file=runs_file)
        raise AssertionError("an undeclared check was recorded")
    except ValueError:
        passed += 1

    # A torn record is not a run.
    runs_file.write_text("{not json", encoding="utf-8")
    check(load(runs_file) == {}, "an unreadable record file yields no runs")
    check(all(row["state"] == NEVER for row in classify(load(runs_file), HEAD).values()),
          "so every check reads NEVER rather than inheriting a stale pass")

# `recording` must record whatever happens, including a raised SystemExit, or the
# checks that fail loudest would be the ones that appear never to run.
with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as directory:
    runs_file = Path(directory) / "runs.json"
    original = enforcement_runs.DEFAULT_RUNS
    enforcement_runs.DEFAULT_RUNS = runs_file
    try:
        check(recording("audit_query_bounds", lambda: 0) == 0, "a passing check returns 0")
        check(load(runs_file)["audit_query_bounds"]["verdict"] == "PASS", "recorded PASS")

        check(recording("audit_extensibility", lambda: 1) == 1, "a failing check returns 1")
        check(load(runs_file)["audit_extensibility"]["verdict"] == "FAIL", "recorded FAIL")

        def explode():
            raise SystemExit(2)

        try:
            recording("audit_route_coverage", explode)
            raise AssertionError("SystemExit was swallowed")
        except SystemExit:
            passed += 1
        check(load(runs_file)["audit_route_coverage"]["verdict"] == "FAIL",
              "a check that exited nonzero is recorded as having run and failed")

        def crash():
            raise RuntimeError("boom")

        try:
            recording("validate_schema_freeze", crash)
            raise AssertionError("the exception was swallowed")
        except RuntimeError:
            passed += 1
        check(load(runs_file)["validate_schema_freeze"]["verdict"] == "ERROR",
              "a check that crashed is recorded as having run and errored")
    finally:
        enforcement_runs.DEFAULT_RUNS = original

# The live ratchet. This is the automated home for audit_enforcement: without it
# the auditor would run only from a CI job, which is the defect under repair.
live = classify(load(), current_head())
ever_run = sum(1 for row in live.values() if row["state"] != NEVER)
floor = audit_enforcement.load_baseline().get("ever_run_floor")
check(floor is not None, "an enforcement baseline is recorded", floor)
check(ever_run >= floor,
      "no declared check has stopped running",
      {"ever_run": ever_run, "floor": floor,
       "never": [n for n, r in live.items() if r["state"] == NEVER]})

# Staleness is reported, never gated. Ratcheting CURRENT would fail the build on
# every migration until each check is re-run, and this repository already refuses
# to gate on the Tier B report for the same reason.
stale_or_current = sum(1 for row in live.values() if row["state"] in (CURRENT, STALE))
check(stale_or_current == ever_run,
      "staleness does not reduce the ever-run count it is ratcheted on")

print(f"Enforcement run recording verified: {passed} assertions passed.")

"""Availability probe and aggregator for the Tier B availability gate.

Implements the definitions fixed in docs/TIER_B_MEASUREMENT_CONTRACT.md:
available means GET /health/live and GET /health/ready both return 200 within
2,000 ms; probes run every 30 seconds; the window is 7 consecutive days; a
failed probe marks its whole interval unavailable; two consecutive failures open
an outage which is then backdated to the first failure; planned restarts count
against the budget.

The probe writes a hash-chained JSONL journal plus a durable tail anchor. On
restart, every missed 30-second schedule slot is recorded as unavailable, so an
observer outage cannot disappear from the availability calculation. Aggregation
validates the complete journal before producing evidence and rejects torn,
altered, duplicated, or out-of-order records.

Probe from the production observer service or an independent host:
  python oms/availability_probe.py probe --target http://127.0.0.1:8000

Aggregate at any point, including mid-window, to see the budget burn:
  python oms/availability_probe.py aggregate
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, List

from app.pilot_evidence import (
    JournalIntegrityError,
    append_observation,
    current_migration_head,
    latest_run,
    load_journal,
    load_or_create_run_state,
    save_run_state,
    validate_tail_anchor,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SAMPLES = REPO_ROOT / "docs" / "availability-samples.jsonl"
DEFAULT_STATE = REPO_ROOT / "docs" / "availability-probe-state.json"

ENDPOINTS = ("/health/live", "/health/ready")
PROBE_INTERVAL_SECONDS = 30
PROBE_TIMEOUT_SECONDS = 2.0
WINDOW_DAYS = 7
WINDOW_SECONDS = WINDOW_DAYS * 24 * 60 * 60
WINDOW_SLOTS = WINDOW_SECONDS // PROBE_INTERVAL_SECONDS
AVAILABILITY_TARGET_PCT = 99.9
# Two consecutive failures are required before an outage opens, so one dropped
# probe does not fabricate downtime.
CONSECUTIVE_FAILURES_TO_OPEN = 2


def probe_once(target: str) -> Dict[str, Any]:
    """One sample. Available only when every endpoint answers 200 in time."""
    started = time.time()
    results, ok = {}, True
    for endpoint in ENDPOINTS:
        url = f"{target.rstrip('/')}{endpoint}"
        began = time.perf_counter()
        try:
            with urllib.request.urlopen(url, timeout=PROBE_TIMEOUT_SECONDS) as response:
                code = response.status
                response.read(2048)
        except urllib.error.HTTPError as error:
            code = error.code
        except Exception as error:  # connection refused, DNS, timeout, TLS
            code = 0
            results[f"{endpoint}_error"] = type(error).__name__
        elapsed_ms = round((time.perf_counter() - began) * 1000, 3)
        results[endpoint] = {"status": code, "elapsed_ms": elapsed_ms}
        if code != 200 or elapsed_ms > PROBE_TIMEOUT_SECONDS * 1000:
            ok = False
    return {"at": int(started), "available": ok, "endpoints": results}


def run_probe(target: str, samples_file: Path, state_file: Path,
              max_samples: int | None) -> int:
    samples_file.parent.mkdir(parents=True, exist_ok=True)
    head = current_migration_head()
    now = int(time.time())
    state = load_or_create_run_state(
        state_file, target=target.rstrip("/"), migration_head=head, now=now,
        interval_seconds=PROBE_INTERVAL_SECONDS,
    )
    existing = load_journal(samples_file)
    if existing:
        anchored_hash = state.get("last_record_hash")
        if anchored_hash and not any(record.get("record_hash") == anchored_hash for record in existing):
            raise JournalIntegrityError(
                "availability journal was truncated behind the persisted observer anchor"
            )
        last = existing[-1]
        state["next_scheduled_at"] = max(
            int(state["next_scheduled_at"]), int(last["scheduled_at"]) + PROBE_INTERVAL_SECONDS,
        )
        matching = [record for record in existing
                    if record.get("target") == target.rstrip("/")
                    and record.get("migration_head") == head]
        if matching:
            state["run_id"] = matching[-1]["run_id"]
            state["started_at"] = min(int(record["scheduled_at"]) for record in matching
                                      if record.get("run_id") == state["run_id"])
        state["last_record_hash"] = last["record_hash"]
        save_run_state(state_file, state)
    print(f"Probing {target} every {PROBE_INTERVAL_SECONDS}s -> {samples_file}")
    print(f"Run {state['run_id']} at migration {head}")
    print("Missed schedule slots are recorded as unavailable after a restart.\n")
    written = 0
    probes_written = 0
    try:
        while max_samples is None or probes_written < max_samples:
            now = int(time.time())
            scheduled = int(state["next_scheduled_at"])
            while scheduled + PROBE_INTERVAL_SECONDS <= now:
                record = append_observation(
                    samples_file, run_id=state["run_id"], kind="availability",
                    target=target.rstrip("/"), migration_head=head,
                    scheduled_at=scheduled, observed_at=now,
                    payload={"available": False, "observer_gap": True,
                             "error": "observer_was_not_running"},
                )
                written += 1
                scheduled += PROBE_INTERVAL_SECONDS
                state["next_scheduled_at"] = scheduled
                state["last_record_hash"] = record["record_hash"]
                save_run_state(state_file, state)
                print(f"  {scheduled - PROBE_INTERVAL_SECONDS}  DOWN (observer gap)")
            delay = scheduled - time.time()
            if delay > 0:
                time.sleep(delay)
            sample = probe_once(target)
            record = append_observation(
                samples_file, run_id=state["run_id"], kind="availability",
                target=target.rstrip("/"), migration_head=head,
                scheduled_at=scheduled, observed_at=int(sample["at"]),
                payload={key: value for key, value in sample.items() if key != "at"},
            )
            written += 1
            probes_written += 1
            state["next_scheduled_at"] = scheduled + PROBE_INTERVAL_SECONDS
            state["last_record_hash"] = record["record_hash"]
            save_run_state(state_file, state)
            display_state = "up" if sample["available"] else "DOWN"
            print(f"  {scheduled}  {display_state}")
            if max_samples is not None and probes_written >= max_samples:
                break
    except KeyboardInterrupt:
        print("\nStopped.")
    print(f"{written} samples written.")
    return 0


def load_samples(samples_file: Path) -> List[Dict[str, Any]]:
    return load_journal(samples_file)


def summarize(samples: List[Dict[str, Any]], now: int | None = None) -> Dict[str, Any]:
    """Uptime over scheduled slots; absent records count as unavailable."""
    if not samples:
        return {
            "samples": 0, "observed_seconds": 0, "window_seconds_min": WINDOW_SECONDS,
            "availability_pct": 0.0, "unavailable_seconds": 0, "outages": 0,
            "longest_outage_seconds": 0, "missing_samples": 0,
            "integrity_failures": 0,
        }

    normalized = []
    for sample in samples:
        payload = sample.get("payload") if isinstance(sample.get("payload"), dict) else sample
        scheduled = int(sample.get("scheduled_at", sample.get("at", 0)))
        normalized.append({"scheduled_at": scheduled, "available": bool(payload.get("available"))})
    normalized.sort(key=lambda item: item["scheduled_at"])
    start = normalized[0]["scheduled_at"]
    effective_now = int(now) if now is not None else normalized[-1]["scheduled_at"]
    elapsed_slots = max(1, ((effective_now - start) // PROBE_INTERVAL_SECONDS) + 1)
    expected_slots = min(WINDOW_SLOTS, elapsed_slots)
    window_end = start + expected_slots * PROBE_INTERVAL_SECONDS
    by_slot = {item["scheduled_at"]: item["available"] for item in normalized
               if start <= item["scheduled_at"] < window_end}
    states = [bool(by_slot.get(start + index * PROBE_INTERVAL_SECONDS, False))
              for index in range(expected_slots)]
    missing = expected_slots - len(by_slot)
    unavailable_intervals = sum(1 for available in states if not available)
    outages, longest, run_length = 0, 0, 0
    for available in states:
        if available:
            if run_length >= CONSECUTIVE_FAILURES_TO_OPEN:
                longest = max(longest, run_length * PROBE_INTERVAL_SECONDS)
            run_length = 0
            continue
        run_length += 1
        if run_length == CONSECUTIVE_FAILURES_TO_OPEN:
            outages += 1
    if run_length >= CONSECUTIVE_FAILURES_TO_OPEN:
        longest = max(longest, run_length * PROBE_INTERVAL_SECONDS)

    observed = expected_slots * PROBE_INTERVAL_SECONDS
    counted = expected_slots * PROBE_INTERVAL_SECONDS
    unavailable_seconds = unavailable_intervals * PROBE_INTERVAL_SECONDS
    availability = 100.0 * (counted - unavailable_seconds) / counted if counted else 0.0
    return {
        "samples": len(by_slot),
        "observed_seconds": observed,
        "window_seconds_min": WINDOW_SECONDS,
        "availability_pct": round(availability, 4),
        "unavailable_seconds": unavailable_seconds,
        "error_budget_seconds": round(WINDOW_SECONDS * (100 - AVAILABILITY_TARGET_PCT) / 100, 1),
        "outages": outages,
        "longest_outage_seconds": longest,
        "missing_samples": missing,
        "integrity_failures": 0,
    }


def aggregate(
    samples_file: Path,
    output_dir: Path | None = None,
    state_file: Path | None = None,
) -> int:
    from tier_b_evidence import write_evidence

    journal_error = None
    try:
        all_records = load_samples(samples_file)
        if state_file is not None:
            validate_tail_anchor(all_records, state_file)
        records = latest_run(all_records, migration_head=current_migration_head())
        summary = summarize(records, now=int(time.time()))
    except JournalIntegrityError as exc:
        records = []
        summary = summarize([])
        summary["integrity_failures"] = 1
        journal_error = str(exc)
    path, status, breaches = write_evidence(
        "availability",
        thresholds={
            "availability_pct_min": AVAILABILITY_TARGET_PCT,
            "observed_seconds_min": WINDOW_SECONDS,
            "samples_min": WINDOW_SLOTS,
            "integrity_failures_max": 0,
        },
        measurements=summary,
        harness="oms/availability_probe.py",
        entry_points=["GET /health/live", "GET /health/ready"],
        request_shapes=["external 30-second liveness and database/schema readiness probe"],
        notes=(
            f"Probe cadence {PROBE_INTERVAL_SECONDS}s against {', '.join(ENDPOINTS)} with a "
            f"{PROBE_TIMEOUT_SECONDS}s timeout. An outage opens after "
            f"{CONSECUTIVE_FAILURES_TO_OPEN} consecutive failures. Planned restarts are "
            "counted against the budget, as the contract requires. Missing observer slots "
            "are unavailable and records are hash chained."
            + (f" Journal integrity error: {journal_error}" if journal_error else "")
        ),
        output_dir=output_dir,
    )
    print(json.dumps(summary, indent=2, sort_keys=True))
    print(f"\nTier B evidence {status}: {path.name}")
    if breaches:
        for breach in breaches:
            print(f"  breach: {breach}")
        remaining = WINDOW_SECONDS - summary["observed_seconds"]
        if remaining > 0:
            print(f"  {remaining // 3600}h {(remaining % 3600) // 60}m of window remaining")
        return 1
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("probe", "aggregate"))
    parser.add_argument("--target", default="http://127.0.0.1:8000")
    parser.add_argument("--samples-file", default=str(DEFAULT_SAMPLES))
    parser.add_argument("--state-file", default=str(DEFAULT_STATE))
    parser.add_argument("--output-dir", default=None,
                        help="Evidence output directory for aggregate mode.")
    parser.add_argument("--max-samples", type=int, default=None,
                        help="Stop after this many samples. For harness self-tests only.")
    args = parser.parse_args()
    samples_file = Path(args.samples_file)
    if args.mode == "probe":
        return run_probe(args.target, samples_file, Path(args.state_file), args.max_samples)
    return aggregate(
        samples_file,
        Path(args.output_dir) if args.output_dir else None,
        state_file=Path(args.state_file),
    )


if __name__ == "__main__":
    sys.exit(main())

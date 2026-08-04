"""Availability probe and aggregator for the Tier B availability gate.

Implements the definitions fixed in docs/TIER_B_MEASUREMENT_CONTRACT.md:
available means GET /health/live and GET /health/ready both return 200 within
2,000 ms; probes run every 30 seconds; the window is 7 consecutive days; a
failed probe marks its whole interval unavailable; two consecutive failures open
an outage which is then backdated to the first failure; planned restarts count
against the budget.

The probe appends one JSON line per sample so a crash loses at most one sample
and an interrupted run can be resumed by appending to the same file.

Probe (run it next to the pilot, not inside its container):
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

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SAMPLES = REPO_ROOT / "docs" / "availability-samples.jsonl"

ENDPOINTS = ("/health/live", "/health/ready")
PROBE_INTERVAL_SECONDS = 30
PROBE_TIMEOUT_SECONDS = 2.0
WINDOW_DAYS = 7
WINDOW_SECONDS = WINDOW_DAYS * 24 * 60 * 60
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


def run_probe(target: str, samples_file: Path, max_samples: int | None) -> int:
    samples_file.parent.mkdir(parents=True, exist_ok=True)
    print(f"Probing {target} every {PROBE_INTERVAL_SECONDS}s -> {samples_file}")
    print("Interrupt to stop; append-only, so the window survives a restart.\n")
    written = 0
    try:
        while max_samples is None or written < max_samples:
            sample = probe_once(target)
            with samples_file.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(sample, sort_keys=True) + "\n")
            written += 1
            state = "up" if sample["available"] else "DOWN"
            print(f"  {sample['at']}  {state}")
            if max_samples is not None and written >= max_samples:
                break
            time.sleep(PROBE_INTERVAL_SECONDS)
    except KeyboardInterrupt:
        print("\nStopped.")
    print(f"{written} samples written.")
    return 0


def load_samples(samples_file: Path) -> List[Dict[str, Any]]:
    if not samples_file.exists():
        return []
    samples = []
    for line in samples_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            try:
                samples.append(json.loads(line))
            except json.JSONDecodeError:
                continue  # a torn final line from an interrupted write
    return sorted(samples, key=lambda item: item["at"])


def summarize(samples: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Uptime over the observed span, plus outages opened by the rule above."""
    if not samples:
        return {
            "samples": 0, "observed_seconds": 0, "window_seconds_min": WINDOW_SECONDS,
            "availability_pct": 0.0, "unavailable_seconds": 0, "outages": 0,
            "longest_outage_seconds": 0,
        }

    unavailable_intervals = 0
    outages, longest, run_length = 0, 0, 0
    for sample in samples:
        if sample.get("available"):
            if run_length >= CONSECUTIVE_FAILURES_TO_OPEN:
                longest = max(longest, run_length * PROBE_INTERVAL_SECONDS)
            run_length = 0
            continue
        run_length += 1
        unavailable_intervals += 1
        if run_length == CONSECUTIVE_FAILURES_TO_OPEN:
            outages += 1
    if run_length >= CONSECUTIVE_FAILURES_TO_OPEN:
        longest = max(longest, run_length * PROBE_INTERVAL_SECONDS)

    observed = samples[-1]["at"] - samples[0]["at"] + PROBE_INTERVAL_SECONDS
    counted = len(samples) * PROBE_INTERVAL_SECONDS
    unavailable_seconds = unavailable_intervals * PROBE_INTERVAL_SECONDS
    availability = 100.0 * (counted - unavailable_seconds) / counted if counted else 0.0
    return {
        "samples": len(samples),
        "observed_seconds": observed,
        "window_seconds_min": WINDOW_SECONDS,
        "availability_pct": round(availability, 4),
        "unavailable_seconds": unavailable_seconds,
        "error_budget_seconds": round(WINDOW_SECONDS * (100 - AVAILABILITY_TARGET_PCT) / 100, 1),
        "outages": outages,
        "longest_outage_seconds": longest,
    }


def aggregate(samples_file: Path, output_dir: Path | None = None) -> int:
    from tier_b_evidence import write_evidence

    summary = summarize(load_samples(samples_file))
    path, status, breaches = write_evidence(
        "availability",
        thresholds={
            "availability_pct_min": AVAILABILITY_TARGET_PCT,
            "observed_seconds_min": WINDOW_SECONDS,
            "samples_min": WINDOW_SECONDS // PROBE_INTERVAL_SECONDS,
        },
        measurements=summary,
        harness="oms/availability_probe.py",
        notes=(
            f"Probe cadence {PROBE_INTERVAL_SECONDS}s against {', '.join(ENDPOINTS)} with a "
            f"{PROBE_TIMEOUT_SECONDS}s timeout. An outage opens after "
            f"{CONSECUTIVE_FAILURES_TO_OPEN} consecutive failures. Planned restarts are "
            "counted against the budget, as the contract requires."
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
    parser.add_argument("--max-samples", type=int, default=None,
                        help="Stop after this many samples. For harness self-tests only.")
    args = parser.parse_args()
    samples_file = Path(args.samples_file)
    if args.mode == "probe":
        return run_probe(args.target, samples_file, args.max_samples)
    return aggregate(samples_file)


if __name__ == "__main__":
    sys.exit(main())

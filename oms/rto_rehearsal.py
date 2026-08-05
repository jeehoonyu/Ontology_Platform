"""Recovery-time rehearsal recorder for the Tier B RTO gate.

Implements the definition fixed in docs/TIER_B_MEASUREMENT_CONTRACT.md: RTO is
the wall clock from the restore command to the first successful authenticated
write at the restored head, including migration and readiness time. At least
four rehearsals are required across the window, at least one of them unattended
and triggered by a timer rather than a person, and every rehearsal must land
within 30 minutes. The maximum is reported and the distribution is retained.

Timing the restore alone would understate the gate. A database that has been
restored but is still migrating, still warming, or not yet accepting writes has
not recovered, so the clock only stops on a write that succeeds.

Record a rehearsal by wrapping whatever restore you actually run:
  python oms/rto_rehearsal.py record \
      --restore-command "pwsh scripts/restore.ps1 -Latest" \
      --target http://127.0.0.1:8000 --trigger attended

Aggregate the recorded rehearsals into gate evidence:
  python oms/rto_rehearsal.py aggregate
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_REHEARSALS = REPO_ROOT / "docs" / "rto-rehearsals.jsonl"

RTO_LIMIT_SECONDS = 30 * 60
REQUIRED_REHEARSALS = 4
REQUIRED_UNATTENDED = 1
READINESS_POLL_SECONDS = 2.0
READINESS_TIMEOUT_SECONDS = RTO_LIMIT_SECONDS


def _request(url: str, method: str = "GET", body: Optional[bytes] = None,
             timeout: float = 10.0) -> int:
    request = urllib.request.Request(url, data=body, method=method)
    if body is not None:
        request.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            response.read(2048)
            return response.status
    except urllib.error.HTTPError as error:
        return error.code
    except Exception:
        return 0


def await_ready(target: str, deadline: float) -> bool:
    while time.time() < deadline:
        if _request(f"{target.rstrip('/')}/health/ready") == 200:
            return True
        time.sleep(READINESS_POLL_SECONDS)
    return False


def perform_write(target: str, deadline: float) -> bool:
    """Recovery is only complete once the system accepts a write."""
    identifier = f"rto_probe_{uuid.uuid4().hex[:12]}"
    payload = json.dumps({
        "id": identifier,
        "display_name": "RTO rehearsal probe",
        "description": "Written to stop the recovery clock.",
        "properties": {"probe": {"type": "string"}},
    }).encode("utf-8")
    while time.time() < deadline:
        status = _request(f"{target.rstrip('/')}/object-types", "POST", payload)
        if status in (200, 201):
            return True
        if status in (401, 403):
            raise SystemExit(
                "Recovery write was rejected as unauthorized. Supply credentials the "
                "rehearsal can write with; an unauthenticated probe does not measure RTO."
            )
        time.sleep(READINESS_POLL_SECONDS)
    return False


def record(args: argparse.Namespace) -> int:
    rehearsals_file = Path(args.rehearsals_file)
    rehearsals_file.parent.mkdir(parents=True, exist_ok=True)

    started = time.time()
    deadline = started + READINESS_TIMEOUT_SECONDS
    restore_status = 0
    if args.restore_command:
        print(f"Restoring: {args.restore_command}")
        completed = subprocess.run(
            args.restore_command, shell=True, cwd=REPO_ROOT,
            capture_output=True, text=True, timeout=READINESS_TIMEOUT_SECONDS,
        )
        restore_status = completed.returncode
        if restore_status != 0:
            print(completed.stderr[-2000:])
    restore_seconds = time.time() - started

    ready = await_ready(args.target, deadline)
    ready_seconds = time.time() - started
    wrote = perform_write(args.target, deadline) if ready else False
    elapsed = time.time() - started

    rehearsal = {
        "at": int(started),
        "trigger": args.trigger,
        "restore_exit": restore_status,
        "restore_seconds": round(restore_seconds, 3),
        "ready_seconds": round(ready_seconds, 3),
        "elapsed_seconds": round(elapsed, 3),
        "recovered": bool(ready and wrote and restore_status == 0),
        "note": args.note,
    }
    with rehearsals_file.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(rehearsal, sort_keys=True) + "\n")

    print(json.dumps(rehearsal, indent=2, sort_keys=True))
    if not rehearsal["recovered"]:
        print("Rehearsal did not reach a serving system; recorded as a failed recovery.")
        return 1
    print(f"Recovered in {rehearsal['elapsed_seconds']}s "
          f"against a {RTO_LIMIT_SECONDS}s limit.")
    return 0


def load_rehearsals(rehearsals_file: Path) -> List[Dict[str, Any]]:
    if not rehearsals_file.exists():
        return []
    rehearsals = []
    for line in rehearsals_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            try:
                rehearsals.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return sorted(rehearsals, key=lambda item: item["at"])


def summarize(rehearsals: List[Dict[str, Any]]) -> Dict[str, Any]:
    elapsed = [item["elapsed_seconds"] for item in rehearsals]
    unattended = [item for item in rehearsals if item.get("trigger") == "unattended"]
    failed = [item for item in rehearsals if not item.get("recovered")]
    return {
        "rehearsals": len(rehearsals),
        "unattended_rehearsals": len(unattended),
        "failed_recoveries": len(failed),
        # The maximum is the reported figure. A mean would let one fast rehearsal
        # conceal one that breached, and an operator experiences the worst case.
        "max_elapsed_seconds": round(max(elapsed), 3) if elapsed else 0,
        "min_elapsed_seconds": round(min(elapsed), 3) if elapsed else 0,
        "elapsed_distribution_seconds": sorted(round(value, 3) for value in elapsed),
    }


def aggregate(rehearsals_file: Path, output_dir: Optional[Path] = None) -> int:
    from tier_b_evidence import write_evidence

    summary = summarize(load_rehearsals(rehearsals_file))
    # An empty record must not satisfy a _max threshold by having no maximum.
    if summary["rehearsals"] == 0:
        summary["max_elapsed_seconds"] = RTO_LIMIT_SECONDS + 1

    path, status, breaches = write_evidence(
        "rto",
        thresholds={
            "rehearsals_min": REQUIRED_REHEARSALS,
            "unattended_rehearsals_min": REQUIRED_UNATTENDED,
            "failed_recoveries_max": 0,
            "max_elapsed_seconds_max": RTO_LIMIT_SECONDS,
        },
        measurements=summary,
        harness="oms/rto_rehearsal.py",
        notes=(
            "Elapsed time runs from the restore command to the first successful "
            "authenticated write, so migration and readiness are inside the measurement. "
            "The maximum across rehearsals is the reported figure."
        ),
        output_dir=output_dir,
    )
    print(json.dumps(summary, indent=2, sort_keys=True))
    print(f"\nTier B evidence {status}: {path.name}")
    for breach in breaches:
        print(f"  breach: {breach}")
    return 1 if breaches else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("record", "aggregate"))
    parser.add_argument("--target", default="http://127.0.0.1:8000")
    parser.add_argument("--restore-command", default="")
    parser.add_argument("--trigger", choices=("attended", "unattended"), default="attended")
    parser.add_argument("--note", default="")
    parser.add_argument("--rehearsals-file", default=str(DEFAULT_REHEARSALS))
    args = parser.parse_args()
    if args.mode == "record":
        return record(args)
    return aggregate(Path(args.rehearsals_file))


if __name__ == "__main__":
    sys.exit(main())

"""Tamper-evident recovery-time rehearsals against an isolated restored API.

RTO starts before the configured restore command and stops only after the
distinct recovered target is ready, accepts a bearer-authenticated database
write, and reports the current database and runtime migration heads. A live
source URL can never be used as the recovery target.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
import uuid
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.pilot_evidence import (
    JournalIntegrityError,
    append_observation,
    current_migration_head,
    load_journal,
)
from recovery_probe_client import (
    assert_current_heads,
    json_request,
    recovery_token,
    require_isolated_target,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_REHEARSALS = REPO_ROOT / "docs" / "rto-rehearsals.jsonl"

RTO_LIMIT_SECONDS = 30 * 60
REQUIRED_REHEARSALS = 4
REQUIRED_UNATTENDED = 1
# "At least 4 rehearsals across the window" -- counting them does not check the
# second half of that sentence, and four back-to-back restores in one afternoon
# satisfied it. See the same constant in `rpo_sampler.py` for why the floor is
# five of seven days rather than the whole window.
REQUIRED_SPAN_SECONDS = 5 * 24 * 60 * 60
READINESS_POLL_SECONDS = 2.0
READINESS_TIMEOUT_SECONDS = RTO_LIMIT_SECONDS


def _request(url: str, timeout: float = 10.0) -> int:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
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


def perform_write(
    target: str,
    deadline: float,
    *,
    token: str,
    run_id: str,
    project_id: str,
    expected_head: str,
) -> bool:
    """Recovery completes only after a credentialed write at the expected head."""
    body = {
        "run_id": run_id,
        "project_id": project_id,
        "migration_head": expected_head,
    }
    while time.time() < deadline:
        status, payload = json_request(
            target, "/health/pilot-recovery/write-probes",
            token=token, method="POST", body=body,
        )
        if status in (200, 201):
            assert_current_heads(payload, expected_head)
            return True
        if status in (401, 403):
            raise RuntimeError("Recovery write credential was rejected")
        if status == 404:
            raise RuntimeError("Recovery probe is disabled on the restored API")
        time.sleep(READINESS_POLL_SECONDS)
    return False


def _scheduled_at(records: List[Dict[str, Any]], now: int) -> int:
    return max(now, int(records[-1]["scheduled_at"]) + 1 if records else now)


def record(args: argparse.Namespace) -> int:
    source_target = str(args.source_target or "").strip()
    recovery_target = str(args.target or "").strip()
    if not source_target:
        raise RuntimeError("--source-target is required")
    require_isolated_target(source_target, recovery_target)
    if not str(args.restore_command or "").strip():
        raise RuntimeError("--restore-command is required; an existing live target is not an RTO rehearsal")

    rehearsals_file = Path(args.rehearsals_file)
    rehearsals_file.parent.mkdir(parents=True, exist_ok=True)
    credential = recovery_token(args.token_env)
    expected_head = current_migration_head()
    started = time.time()
    deadline = started + READINESS_TIMEOUT_SECONDS
    run_id = f"rto_{uuid.uuid4().hex}"
    restore_status = -1
    restore_timed_out = False
    restore_error: Optional[str] = None

    print(f"Restoring isolated target: {args.restore_command}")
    try:
        completed = subprocess.run(
            args.restore_command,
            shell=True,
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=READINESS_TIMEOUT_SECONDS,
        )
        restore_status = completed.returncode
        if restore_status != 0:
            restore_error = (completed.stderr or completed.stdout)[-1000:]
    except subprocess.TimeoutExpired:
        restore_timed_out = True
        restore_error = "restore command exceeded the RTO deadline"
    except Exception as error:  # command launch failure is measured evidence
        restore_error = f"{type(error).__name__}: {error}"
    restore_seconds = time.time() - started

    ready = False
    wrote = False
    head_error: Optional[str] = None
    if restore_status == 0 and not restore_timed_out:
        ready = await_ready(recovery_target, deadline)
        if ready:
            try:
                wrote = perform_write(
                    recovery_target,
                    deadline,
                    token=credential,
                    run_id=run_id,
                    project_id=args.project_id,
                    expected_head=expected_head,
                )
            except RuntimeError as error:
                head_error = str(error)
    ready_seconds = time.time() - started
    elapsed = time.time() - started
    recovered = bool(ready and wrote and restore_status == 0 and not restore_timed_out and not head_error)
    rehearsal = {
        "at": int(started),
        "run_id": run_id,
        "source_target": source_target,
        "recovery_target": recovery_target,
        "project_id": args.project_id,
        "migration_head": expected_head,
        "trigger": args.trigger,
        "restore_exit": restore_status,
        "restore_timed_out": restore_timed_out,
        "restore_seconds": round(restore_seconds, 3),
        "ready_seconds": round(ready_seconds, 3),
        "elapsed_seconds": round(elapsed, 3),
        "recovered": recovered,
        "note": args.note,
        "error": head_error or restore_error,
    }
    records = load_journal(rehearsals_file)
    append_observation(
        rehearsals_file,
        run_id=run_id,
        kind="rto_rehearsal",
        target=recovery_target,
        migration_head=expected_head,
        scheduled_at=_scheduled_at(records, int(started)),
        observed_at=int(time.time()),
        payload=rehearsal,
    )
    print(json.dumps(rehearsal, indent=2, sort_keys=True))
    if not recovered:
        print("Rehearsal did not reach a serving, writable, current-head isolated target.")
        return 1
    print(f"Recovered in {rehearsal['elapsed_seconds']}s against a {RTO_LIMIT_SECONDS}s limit.")
    return 0 if rehearsal["elapsed_seconds"] <= RTO_LIMIT_SECONDS else 1


def load_rehearsals(rehearsals_file: Path) -> List[Dict[str, Any]]:
    rows = [dict(record.get("payload") or {}) for record in load_journal(rehearsals_file)]
    return sorted(rows, key=lambda item: item["at"])


def summarize(rehearsals: List[Dict[str, Any]]) -> Dict[str, Any]:
    elapsed = [item["elapsed_seconds"] for item in rehearsals]
    held_at = [int(item["at"]) for item in rehearsals
               if isinstance(item.get("at"), (int, float))]
    return {
        "rehearsals": len(rehearsals),
        "rehearsal_span_seconds": (max(held_at) - min(held_at)) if len(held_at) > 1 else 0,
        "unattended_rehearsals": sum(1 for item in rehearsals if item.get("trigger") == "unattended"),
        "failed_recoveries": sum(1 for item in rehearsals if not item.get("recovered")),
        "integrity_failures": 0,
        "max_elapsed_seconds": round(max(elapsed), 3) if elapsed else 0,
        "min_elapsed_seconds": round(min(elapsed), 3) if elapsed else 0,
        "elapsed_distribution_seconds": sorted(round(value, 3) for value in elapsed),
    }


def aggregate(rehearsals_file: Path, output_dir: Optional[Path] = None) -> int:
    from tier_b_evidence import write_evidence

    try:
        summary = summarize(load_rehearsals(rehearsals_file))
    except JournalIntegrityError as error:
        summary = summarize([])
        summary["integrity_failures"] = 1
        summary["integrity_error"] = str(error)
    if summary["rehearsals"] == 0:
        summary["max_elapsed_seconds"] = RTO_LIMIT_SECONDS + 1
    path, status, breaches = write_evidence(
        "rto",
        thresholds={
            "rehearsals_min": REQUIRED_REHEARSALS,
            "rehearsal_span_seconds_min": REQUIRED_SPAN_SECONDS,
            "unattended_rehearsals_min": REQUIRED_UNATTENDED,
            "failed_recoveries_max": 0,
            "integrity_failures_max": 0,
            "max_elapsed_seconds_max": RTO_LIMIT_SECONDS,
        },
        measurements=summary,
        harness="oms/rto_rehearsal.py",
        notes=(
            "Elapsed time starts before the isolated restore command and stops only "
            "after readiness plus a bearer-authenticated write at matching database "
            "and runtime migration heads. The evidence journal is hash-chained."
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
    parser.add_argument("--source-target", default="")
    parser.add_argument("--target", default="http://127.0.0.1:8001",
                        help="Distinct isolated recovered API")
    parser.add_argument("--restore-command", default="")
    parser.add_argument("--trigger", choices=("attended", "unattended"), default="attended")
    parser.add_argument("--project-id", default="default")
    parser.add_argument("--token-env", default="PILOT_RECOVERY_TOKEN")
    parser.add_argument("--note", default="")
    parser.add_argument("--rehearsals-file", default=str(DEFAULT_REHEARSALS))
    args = parser.parse_args()
    if args.mode == "record":
        return record(args)
    return aggregate(Path(args.rehearsals_file))


if __name__ == "__main__":
    sys.exit(main())

"""Tamper-evident recovery-point sampling against an isolated restored API.

The live source receives monotonic marks through the dedicated recovery probe.
After an independently restored API is ready, ``observe`` finds the highest mark
that survived and computes the timestamp gap. Source and recovery URLs must be
different, both database/runtime migration heads must match the current build,
and evidence corruption is a hard gate failure.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.parse
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.pilot_evidence import (
    JournalIntegrityError,
    append_observation,
    current_migration_head,
    latest_run,
    load_journal,
    load_or_create_run_state,
    save_run_state,
)
from recovery_probe_client import (
    assert_current_heads,
    json_request,
    recovery_token,
    require_isolated_target,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_MARKS = REPO_ROOT / "docs" / "rpo-marks.jsonl"
DEFAULT_SAMPLES = REPO_ROOT / "docs" / "rpo-samples.jsonl"
DEFAULT_STATE = REPO_ROOT / "docs" / "rpo-sampler-state.json"

RPO_LIMIT_SECONDS = 5 * 60
REQUIRED_SAMPLES = 10
REQUIRED_PRE_BACKUP_SAMPLES = 2
PHASES = ("pre_backup", "mid_cycle", "post_backup")


def _scheduled_at(records: List[Dict[str, Any]], now: int) -> int:
    return max(int(now), int(records[-1]["scheduled_at"]) + 1 if records else int(now))


def _run_records(path: Path, run_id: str) -> List[Dict[str, Any]]:
    return [row for row in load_journal(path) if row.get("run_id") == run_id]


def write_mark(
    target: str,
    marks_file: Path,
    state_file: Path = DEFAULT_STATE,
    *,
    project_id: str = "default",
    token: Optional[str] = None,
    now: Optional[int] = None,
) -> Dict[str, Any]:
    """Persist and submit one source mark without creating a crash window."""
    observed_at = int(time.time() if now is None else now)
    head = current_migration_head()
    state = load_or_create_run_state(
        state_file, target=target, migration_head=head, now=observed_at, interval_seconds=1,
    )
    records = _run_records(marks_file, state["run_id"])
    pending = state.get("pending_mark")
    if not isinstance(pending, dict):
        sequence = max(
            (int(row["payload"]["sequence"]) for row in records), default=0,
        ) + 1
        all_records = load_journal(marks_file)
        pending = {
            "sequence": sequence,
            "written_at": observed_at,
            "scheduled_at": _scheduled_at(all_records, observed_at),
            "project_id": project_id,
        }
        state["pending_mark"] = pending
        save_run_state(state_file, state)

    matching = [
        row for row in records
        if int(row["payload"].get("sequence", -1)) == int(pending["sequence"])
    ]
    if matching:
        payload = matching[-1]["payload"]
        if (
            int(payload.get("written_at", -1)) != int(pending["written_at"])
            or payload.get("project_id") != pending["project_id"]
        ):
            raise JournalIntegrityError("pending RPO mark conflicts with the durable journal")
        state.pop("pending_mark", None)
        save_run_state(state_file, state)
        return {"run_id": state["run_id"], **payload}

    credential = token or recovery_token()
    body = {
        "run_id": state["run_id"],
        "sequence": int(pending["sequence"]),
        "written_at": int(pending["written_at"]),
        "project_id": pending["project_id"],
        "migration_head": head,
    }
    status, response = json_request(
        target, "/health/pilot-recovery/marks", token=credential, method="POST", body=body,
    )
    if status not in (200, 201):
        raise RuntimeError(f"Could not write recovery mark {pending['sequence']}: HTTP {status}")
    assert_current_heads(response, head)
    append_observation(
        marks_file,
        run_id=state["run_id"],
        kind="rpo_mark",
        target=target,
        migration_head=head,
        scheduled_at=int(pending["scheduled_at"]),
        observed_at=observed_at,
        payload={
            "sequence": int(pending["sequence"]),
            "written_at": int(pending["written_at"]),
            "project_id": pending["project_id"],
        },
    )
    state.pop("pending_mark", None)
    save_run_state(state_file, state)
    return {"run_id": state["run_id"], **body}


def highest_surviving_mark(
    target: str, run_id: str, project_id: str, token: str, expected_head: str,
) -> Optional[Dict[str, Any]]:
    run_path = urllib.parse.quote(run_id, safe="")
    project = urllib.parse.quote(project_id, safe="")
    status, payload = json_request(
        target,
        f"/health/pilot-recovery/marks/{run_path}/highest?project_id={project}",
        token=token,
    )
    if status == 404:
        return None
    if status != 200:
        raise RuntimeError(f"Could not inspect restored recovery marks: HTTP {status}")
    assert_current_heads(payload, expected_head)
    return payload


def observe(
    source_target: str,
    recovery_target: str,
    marks_file: Path,
    samples_file: Path,
    phase: str,
    *,
    project_id: str = "default",
    token: Optional[str] = None,
    note: str = "",
    now: Optional[int] = None,
) -> int:
    """Measure one restored target; the live source is never an allowed target."""
    require_isolated_target(source_target, recovery_target)
    observed_at = int(time.time() if now is None else now)
    head = current_migration_head()
    marks = latest_run(load_journal(marks_file), migration_head=head)
    if not marks:
        raise RuntimeError("No current-head marks exist. Run 'mark' against the live source first.")
    last_written = max(marks, key=lambda row: int(row["payload"]["sequence"]))
    run_id = str(last_written["run_id"])
    credential = token or recovery_token()
    survivor = highest_surviving_mark(
        recovery_target, run_id, project_id, credential, head,
    )
    by_sequence = {int(row["payload"]["sequence"]): row for row in marks}

    if survivor is None:
        first_at = min(int(row["payload"]["written_at"]) for row in marks)
        rpo_seconds = max(
            int(last_written["payload"]["written_at"]) - first_at,
            RPO_LIMIT_SECONDS + 1,
        )
        surviving_sequence = None
        total_loss = True
    else:
        surviving_sequence = int(survivor["sequence"])
        surviving_mark = by_sequence.get(surviving_sequence)
        if surviving_mark is None:
            raise RuntimeError(
                f"Restored target reports unrecorded sequence {surviving_sequence}; "
                "the mark journal and target do not describe the same run."
            )
        rpo_seconds = max(
            0,
            int(last_written["payload"]["written_at"])
            - int(surviving_mark["payload"]["written_at"]),
        )
        total_loss = False

    sample = {
        "at": observed_at,
        "phase": phase,
        "note": note,
        "source_target": source_target,
        "recovery_target": recovery_target,
        "project_id": project_id,
        "last_written_sequence": int(last_written["payload"]["sequence"]),
        "surviving_sequence": surviving_sequence,
        "rpo_seconds": rpo_seconds,
        "total_loss": total_loss,
    }
    existing = load_journal(samples_file)
    append_observation(
        samples_file,
        run_id=run_id,
        kind="rpo_observation",
        target=recovery_target,
        migration_head=head,
        scheduled_at=_scheduled_at(existing, observed_at),
        observed_at=observed_at,
        payload=sample,
    )
    print(json.dumps(sample, indent=2, sort_keys=True))
    return 0 if rpo_seconds <= RPO_LIMIT_SECONDS and not total_loss else 1


def load_jsonl(path: Path) -> List[Dict[str, Any]]:
    """Return validated payloads for existing status and aggregation callers."""
    return [dict(row.get("payload") or {}) for row in load_journal(path)]


def summarize(samples: List[Dict[str, Any]]) -> Dict[str, Any]:
    values = [sample["rpo_seconds"] for sample in samples]
    return {
        "samples": len(samples),
        "pre_backup_samples": sum(1 for sample in samples if sample.get("phase") == "pre_backup"),
        "total_loss_samples": sum(1 for sample in samples if sample.get("total_loss")),
        "integrity_failures": 0,
        "max_rpo_seconds": round(max(values), 3) if values else 0,
        "min_rpo_seconds": round(min(values), 3) if values else 0,
        "rpo_distribution_seconds": sorted(round(value, 3) for value in values),
        "phases_covered": sorted({sample.get("phase") for sample in samples if sample.get("phase")}),
    }


def aggregate(samples_file: Path, output_dir: Optional[Path] = None) -> int:
    from tier_b_evidence import write_evidence

    try:
        summary = summarize(load_jsonl(samples_file))
    except JournalIntegrityError as error:
        summary = summarize([])
        summary["integrity_failures"] = 1
        summary["integrity_error"] = str(error)
    if summary["samples"] == 0:
        summary["max_rpo_seconds"] = RPO_LIMIT_SECONDS + 1
    path, status, breaches = write_evidence(
        "rpo",
        thresholds={
            "samples_min": REQUIRED_SAMPLES,
            "pre_backup_samples_min": REQUIRED_PRE_BACKUP_SAMPLES,
            "total_loss_samples_max": 0,
            "integrity_failures_max": 0,
            "max_rpo_seconds_max": RPO_LIMIT_SECONDS,
        },
        measurements=summary,
        harness="oms/rpo_sampler.py",
        notes=(
            "A dedicated bearer-authenticated marker is written to the live source and "
            "queried only through a distinct restored target. Database/runtime migration "
            "heads must match, and the local mark and observation journals are hash-chained."
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
    parser.add_argument("mode", choices=("mark", "observe", "aggregate"))
    parser.add_argument("--target", default="http://127.0.0.1:8000",
                        help="Live source for mark; isolated recovered API for observe")
    parser.add_argument("--source-target", default="",
                        help="Required live source URL for observe isolation validation")
    parser.add_argument("--phase", choices=PHASES, default="mid_cycle")
    parser.add_argument("--project-id", default="default")
    parser.add_argument("--token-env", default="PILOT_RECOVERY_TOKEN")
    parser.add_argument("--note", default="")
    parser.add_argument("--marks-file", default=str(DEFAULT_MARKS))
    parser.add_argument("--samples-file", default=str(DEFAULT_SAMPLES))
    parser.add_argument("--state-file", default=str(DEFAULT_STATE))
    args = parser.parse_args()

    if args.mode == "mark":
        mark = write_mark(
            args.target, Path(args.marks_file), Path(args.state_file),
            project_id=args.project_id, token=recovery_token(args.token_env),
        )
        print(json.dumps(mark, sort_keys=True))
        return 0
    if args.mode == "observe":
        if not args.source_target:
            raise SystemExit("--source-target is required for an isolated recovery observation")
        return observe(
            args.source_target, args.target, Path(args.marks_file), Path(args.samples_file),
            args.phase, project_id=args.project_id, token=recovery_token(args.token_env),
            note=args.note,
        )
    return aggregate(Path(args.samples_file))


if __name__ == "__main__":
    sys.exit(main())

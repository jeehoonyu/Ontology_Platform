"""Recovery-point sampler for the Tier B RPO gate.

Implements the definition fixed in docs/TIER_B_MEASUREMENT_CONTRACT.md: RPO is
the interval between the last write durably committed before an incident and the
latest write present after recovery. A writer appends monotonically increasing
sequenced marks; after a restore the highest surviving mark is located and the
gap is converted to elapsed time from the mark timestamps.

At least ten samples are required across the window, taken at varied points in
the backup cycle, and at least two immediately before a scheduled backup. That
last requirement is the point of the gate: mid-cycle samples flatter the system,
because the worst recovery point is always the moment just before a backup runs.
Every sample must be within 5 minutes and the maximum is reported.

  python oms/rpo_sampler.py mark --target http://127.0.0.1:8000
  python oms/rpo_sampler.py observe --target http://127.0.0.1:8000 --phase pre_backup
  python oms/rpo_sampler.py aggregate
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_MARKS = REPO_ROOT / "docs" / "rpo-marks.jsonl"
DEFAULT_SAMPLES = REPO_ROOT / "docs" / "rpo-samples.jsonl"

RPO_LIMIT_SECONDS = 5 * 60
REQUIRED_SAMPLES = 10
REQUIRED_PRE_BACKUP_SAMPLES = 2
MARK_OBJECT_TYPE = "rpo_mark"
PHASES = ("pre_backup", "mid_cycle", "post_backup")


def _json_request(url: str, method: str = "GET", body: Optional[Dict[str, Any]] = None,
                  timeout: float = 15.0):
    data = None if body is None else json.dumps(body).encode("utf-8")
    request = urllib.request.Request(url, data=data, method=method)
    if data is not None:
        request.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = response.read()
            return response.status, (json.loads(payload) if payload else {})
    except urllib.error.HTTPError as error:
        return error.code, {}
    except Exception:
        return 0, {}


def ensure_mark_type(target: str) -> None:
    base = target.rstrip("/")
    status, _ = _json_request(f"{base}/object-types/{MARK_OBJECT_TYPE}")
    if status == 200:
        return
    _json_request(f"{base}/object-types", "POST", {
        "id": MARK_OBJECT_TYPE,
        "display_name": "RPO mark",
        "description": "Monotonic durability marker for recovery-point sampling.",
        "properties": {"sequence": {"type": "integer"}, "written_at": {"type": "integer"}},
    })


def next_sequence(marks_file: Path) -> int:
    marks = load_jsonl(marks_file)
    return (max((mark["sequence"] for mark in marks), default=0)) + 1


def write_mark(target: str, marks_file: Path) -> Dict[str, Any]:
    ensure_mark_type(target)
    sequence = next_sequence(marks_file)
    written_at = int(time.time())
    status, _ = _json_request(f"{target.rstrip('/')}/objects", "POST", {
        "object_type_id": MARK_OBJECT_TYPE,
        "id": f"{MARK_OBJECT_TYPE}_{sequence:09d}",
        "properties": {"sequence": sequence, "written_at": written_at},
    })
    if status not in (200, 201):
        raise SystemExit(f"Could not write mark {sequence}: HTTP {status}")
    mark = {"sequence": sequence, "written_at": written_at}
    marks_file.parent.mkdir(parents=True, exist_ok=True)
    with marks_file.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(mark, sort_keys=True) + "\n")
    return mark


def highest_surviving_sequence(target: str) -> Optional[int]:
    # Objects of a type are listed at /objects/{type}. The first version of this
    # queried /objects?object_type_id=... which is a 405: that path only accepts
    # POST. The sampler therefore read nothing, reported total_loss on every
    # sample, and would have filled a seven-day RPO window with false total
    # losses while the database held the marks perfectly. A unit test over
    # synthetic samples could not catch this; only a real restore could.
    status, payload = _json_request(
        f"{target.rstrip('/')}/objects/{MARK_OBJECT_TYPE}?limit=1000"
    )
    if status != 200:
        return None
    rows = payload if isinstance(payload, list) else payload.get("objects", payload.get("items", []))
    sequences = [
        (row.get("properties") or {}).get("sequence")
        for row in rows if isinstance(row, dict)
    ]
    sequences = [value for value in sequences if isinstance(value, int)]
    return max(sequences) if sequences else None


def observe(target: str, marks_file: Path, samples_file: Path, phase: str,
            note: str = "") -> int:
    """Compare the restored system against the marks written before the cut."""
    marks = load_jsonl(marks_file)
    if not marks:
        raise SystemExit("No marks recorded. Run 'mark' against the live system first.")
    last_written = max(marks, key=lambda mark: mark["sequence"])
    survivor = highest_surviving_sequence(target)

    if survivor is None:
        # Nothing survived. That is a total loss of the marked window, not a
        # small RPO, and must not be recorded as a good sample.
        lost_seconds = last_written["written_at"] - min(mark["written_at"] for mark in marks)
        sample = {
            "at": int(time.time()), "phase": phase, "note": note,
            "last_written_sequence": last_written["sequence"], "surviving_sequence": None,
            "rpo_seconds": max(lost_seconds, RPO_LIMIT_SECONDS + 1), "total_loss": True,
        }
    else:
        by_sequence = {mark["sequence"]: mark for mark in marks}
        surviving_mark = by_sequence.get(survivor)
        if surviving_mark is None:
            raise SystemExit(
                f"Restored system reports sequence {survivor}, which was never marked. "
                "The marks file does not describe this system."
            )
        sample = {
            "at": int(time.time()), "phase": phase, "note": note,
            "last_written_sequence": last_written["sequence"],
            "surviving_sequence": survivor,
            "rpo_seconds": max(0, last_written["written_at"] - surviving_mark["written_at"]),
            "total_loss": False,
        }

    samples_file.parent.mkdir(parents=True, exist_ok=True)
    with samples_file.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(sample, sort_keys=True) + "\n")
    print(json.dumps(sample, indent=2, sort_keys=True))
    return 0 if sample["rpo_seconds"] <= RPO_LIMIT_SECONDS else 1


def load_jsonl(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows


def summarize(samples: List[Dict[str, Any]]) -> Dict[str, Any]:
    values = [sample["rpo_seconds"] for sample in samples]
    return {
        "samples": len(samples),
        "pre_backup_samples": sum(1 for s in samples if s.get("phase") == "pre_backup"),
        "total_loss_samples": sum(1 for s in samples if s.get("total_loss")),
        "max_rpo_seconds": round(max(values), 3) if values else 0,
        "min_rpo_seconds": round(min(values), 3) if values else 0,
        "rpo_distribution_seconds": sorted(round(value, 3) for value in values),
        "phases_covered": sorted({s.get("phase") for s in samples if s.get("phase")}),
    }


def aggregate(samples_file: Path, output_dir: Optional[Path] = None) -> int:
    from tier_b_evidence import write_evidence

    summary = summarize(load_jsonl(samples_file))
    if summary["samples"] == 0:
        # No samples must breach rather than satisfy the maximum by default.
        summary["max_rpo_seconds"] = RPO_LIMIT_SECONDS + 1

    path, status, breaches = write_evidence(
        "rpo",
        thresholds={
            "samples_min": REQUIRED_SAMPLES,
            "pre_backup_samples_min": REQUIRED_PRE_BACKUP_SAMPLES,
            "total_loss_samples_max": 0,
            "max_rpo_seconds_max": RPO_LIMIT_SECONDS,
        },
        measurements=summary,
        harness="oms/rpo_sampler.py",
        notes=(
            "Marks are monotonic and timestamped; RPO is the gap between the last mark "
            "written before the cut and the highest mark surviving the restore. At least "
            "two samples must be taken immediately before a scheduled backup, which is "
            "the worst point in the cycle and the one a mid-cycle sample hides."
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
    parser.add_argument("--target", default="http://127.0.0.1:8000")
    parser.add_argument("--phase", choices=PHASES, default="mid_cycle")
    parser.add_argument("--note", default="")
    parser.add_argument("--marks-file", default=str(DEFAULT_MARKS))
    parser.add_argument("--samples-file", default=str(DEFAULT_SAMPLES))
    args = parser.parse_args()

    if args.mode == "mark":
        mark = write_mark(args.target, Path(args.marks_file))
        print(json.dumps(mark, sort_keys=True))
        return 0
    if args.mode == "observe":
        return observe(args.target, Path(args.marks_file), Path(args.samples_file),
                       args.phase, args.note)
    return aggregate(Path(args.samples_file))


if __name__ == "__main__":
    sys.exit(main())

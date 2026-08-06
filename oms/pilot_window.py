"""Drive the seven-day pilot window that the availability, RPO and RTO gates need.

Those three gates are not blocked on engineering. They are blocked on a window
of wall clock during which something keeps probing, keeps marking, and keeps
rehearsing recovery on a schedule. Assembling that by hand each time is the real
obstacle, and a seven-day measurement that depends on someone remembering to run
five things is a seven-day measurement that will be wrong.

This is designed for a scheduler rather than a long-lived process. `tick` does
one cycle and exits, so Windows Task Scheduler or cron can call it every thirty
seconds for a week and the window survives reboots, crashes and deploys. Every
action is idempotent and appends; nothing is recomputed from memory.

  python oms/pilot_window.py start --target http://127.0.0.1:8000
  python oms/pilot_window.py tick          # from a scheduler, every 30s
  python oms/pilot_window.py status
  python oms/pilot_window.py aggregate     # emit all three gate evidence files

The window's own definitions live in docs/TIER_B_MEASUREMENT_CONTRACT.md. This
module schedules them; it does not reinterpret them.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))

REPO_ROOT = Path(__file__).resolve().parent.parent
DOCS = REPO_ROOT / "docs"
MANIFEST = DOCS / "pilot-window.json"

WINDOW_DAYS = 7
WINDOW_SECONDS = WINDOW_DAYS * 24 * 60 * 60
PROBE_INTERVAL_SECONDS = 30
# Ten RPO samples across the window, two of them immediately before a scheduled
# backup. Backups every six hours give 28 opportunities across seven days, which
# leaves room for the schedule to slip without starving the sample count.
BACKUP_INTERVAL_SECONDS = 6 * 60 * 60
RPO_SAMPLE_TARGET = 10
PRE_BACKUP_SAMPLE_TARGET = 2
# Four RTO rehearsals across the window, at least one timer-triggered. Spacing
# them at 40 hours puts four inside seven days with margin at both ends.
RTO_INTERVAL_SECONDS = 40 * 60 * 60
RTO_REHEARSAL_TARGET = 4


def load_manifest() -> Optional[Dict[str, Any]]:
    if not MANIFEST.exists():
        return None
    try:
        return json.loads(MANIFEST.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def save_manifest(manifest: Dict[str, Any]) -> None:
    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def start(args: argparse.Namespace) -> int:
    existing = load_manifest()
    if existing and not args.restart:
        started = existing["started_at"]
        raise SystemExit(
            f"A window is already open, started at {started}. Pass --restart to abandon it, "
            "which discards its samples rather than extending them."
        )
    from tier_b_evidence import current_head

    manifest = {
        "started_at": int(time.time()),
        # The head is pinned at the start. If it advances mid-window the samples
        # describe two different systems, and the non-completion rule says that
        # evidence cannot be pooled. status reports the drift rather than hiding it.
        "migration_head_at_start": current_head(),
        "target": args.target,
        "restore_command": args.restore_command,
        "backup_command": args.backup_command,
        "window_seconds": WINDOW_SECONDS,
        "last_backup_at": 0,
        "last_rto_at": 0,
        "rto_rehearsals": 0,
        "unattended_rto_rehearsals": 0,
    }
    save_manifest(manifest)
    print(json.dumps(manifest, indent=2, sort_keys=True))
    print(f"\nWindow open. Schedule `python oms/pilot_window.py tick` every "
          f"{PROBE_INTERVAL_SECONDS}s for {WINDOW_DAYS} days.")
    return 0


def _run(command: str, timeout: int) -> int:
    if not command:
        return 0
    completed = subprocess.run(
        command, shell=True, cwd=REPO_ROOT, capture_output=True, text=True, timeout=timeout,
    )
    return completed.returncode


def tick(args: argparse.Namespace) -> int:
    """One scheduled cycle. Idempotent, append-only, safe to miss."""
    manifest = load_manifest()
    if manifest is None:
        raise SystemExit("No window is open. Run `pilot_window.py start` first.")

    from availability_probe import probe_once
    from rpo_sampler import write_mark

    now = int(time.time())
    elapsed = now - manifest["started_at"]
    actions = []

    # Availability: every tick, unconditionally. A probe that is skipped when the
    # system looks unhealthy would measure only the good moments. probe_once
    # returns a sample without persisting it -- run_probe owns the loop and the
    # file -- so the tick appends it here, which is what makes a scheduler-driven
    # window equivalent to a long-lived probe process.
    samples_file = DOCS / "availability-samples.jsonl"
    try:
        sample = probe_once(manifest["target"])
        samples_file.parent.mkdir(parents=True, exist_ok=True)
        with samples_file.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(sample, sort_keys=True) + "\n")
        actions.append("probe:available" if sample["available"] else "probe:unavailable")
    except Exception as error:  # noqa: BLE001 - a probe failure is data, not a crash
        # An unreachable target is unavailability, not an absent sample. Dropping
        # it would let an outage improve the measured uptime.
        samples_file.parent.mkdir(parents=True, exist_ok=True)
        with samples_file.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(
                {"at": now, "available": False,
                 "endpoints": {"probe_error": type(error).__name__}}, sort_keys=True) + "\n")
        actions.append(f"probe-error:{type(error).__name__}")

    # RPO marks advance continuously so a restore always has a recent recovery
    # point to be measured against.
    #
    # SystemExit is caught explicitly, not by accident. write_mark raises it when
    # the target refuses the write, and SystemExit derives from BaseException, so
    # `except Exception` lets it through and kills the tick. That would abort the
    # cycle during an outage -- precisely when the window most needs to keep
    # sampling -- and every later action in this tick, backups and rehearsals
    # included, would silently stop running for as long as the target was down.
    try:
        write_mark(manifest["target"], DOCS / "rpo-marks.jsonl")
        actions.append("mark")
    except (Exception, SystemExit) as error:  # noqa: BLE001
        actions.append(f"mark-unavailable:{type(error).__name__}")

    if now - manifest["last_backup_at"] >= BACKUP_INTERVAL_SECONDS:
        code = _run(manifest.get("backup_command") or "", timeout=3600)
        manifest["last_backup_at"] = now
        actions.append(f"backup:{code}")

    if (
        now - manifest["last_rto_at"] >= RTO_INTERVAL_SECONDS
        and manifest["rto_rehearsals"] < RTO_REHEARSAL_TARGET
        and manifest.get("restore_command")
    ):
        # Triggered by the scheduler, so it is unattended by construction. That
        # is the contract's requirement and it is satisfied by how this runs,
        # not by someone asserting it afterwards.
        code = subprocess.run(
            [sys.executable, str(Path(__file__).parent / "rto_rehearsal.py"), "record",
             "--restore-command", manifest["restore_command"],
             "--target", manifest["target"], "--trigger", "unattended",
             "--note", f"scheduled rehearsal {manifest['rto_rehearsals'] + 1}"],
            cwd=REPO_ROOT, capture_output=True, text=True, timeout=3600,
        ).returncode
        manifest["last_rto_at"] = now
        manifest["rto_rehearsals"] += 1
        manifest["unattended_rto_rehearsals"] += 1
        actions.append(f"rto:{code}")

    save_manifest(manifest)
    print(json.dumps({"elapsed_seconds": elapsed, "actions": actions}, sort_keys=True))
    return 0


def status(args: argparse.Namespace) -> int:
    manifest = load_manifest()
    if manifest is None:
        print("No window is open.")
        return 1
    from availability_probe import load_samples
    from rpo_sampler import load_jsonl
    from rto_rehearsal import load_rehearsals
    from tier_b_evidence import current_head

    now = int(time.time())
    elapsed = now - manifest["started_at"]
    remaining = max(0, manifest["window_seconds"] - elapsed)
    probes = len(load_samples(DOCS / "availability-samples.jsonl"))
    rpo_samples = load_jsonl(DOCS / "rpo-samples.jsonl")
    pre_backup = sum(1 for row in rpo_samples if row.get("phase") == "pre_backup")
    rehearsals = load_rehearsals(DOCS / "rto-rehearsals.jsonl")
    unattended = sum(1 for row in rehearsals if row.get("trigger") == "unattended")
    head_now = current_head()

    print("Pilot window status\n")
    print(f"  elapsed            {elapsed // 3600}h of {manifest['window_seconds'] // 3600}h")
    print(f"  remaining          {remaining // 3600}h")
    print(f"  availability probes {probes} (expected ~{elapsed // PROBE_INTERVAL_SECONDS})")
    print(f"  rpo samples        {len(rpo_samples)} of {RPO_SAMPLE_TARGET}, "
          f"pre-backup {pre_backup} of {PRE_BACKUP_SAMPLE_TARGET}")
    print(f"  rto rehearsals     {len(rehearsals)} of {RTO_REHEARSAL_TARGET}, "
          f"unattended {unattended} of 1")
    if head_now != manifest["migration_head_at_start"]:
        print(f"\n  MIGRATION HEAD DRIFTED: started at {manifest['migration_head_at_start']}, "
              f"now {head_now}.")
        print("  Samples taken before and after describe different systems and cannot be")
        print("  pooled. Restart the window; the non-completion rule is not negotiable here.")
        return 1
    owed = []
    if remaining > 0:
        owed.append(f"{remaining // 3600}h of wall clock")
    if len(rpo_samples) < RPO_SAMPLE_TARGET:
        owed.append(f"{RPO_SAMPLE_TARGET - len(rpo_samples)} rpo samples")
    if pre_backup < PRE_BACKUP_SAMPLE_TARGET:
        owed.append(f"{PRE_BACKUP_SAMPLE_TARGET - pre_backup} pre-backup samples")
    if len(rehearsals) < RTO_REHEARSAL_TARGET:
        owed.append(f"{RTO_REHEARSAL_TARGET - len(rehearsals)} rto rehearsals")
    if unattended < 1:
        owed.append("1 unattended rehearsal")
    print("\n  " + ("Window complete; run aggregate." if not owed else "Still owed: " + ", ".join(owed)))
    return 0 if not owed else 1


def aggregate(args: argparse.Namespace) -> int:
    """Emit all three gate evidence files from the window's collected samples."""
    from availability_probe import aggregate as availability_aggregate
    from rpo_sampler import aggregate as rpo_aggregate
    from rto_rehearsal import aggregate as rto_aggregate

    codes = [
        availability_aggregate(DOCS / "availability-samples.jsonl"),
        rpo_aggregate(DOCS / "rpo-samples.jsonl"),
        rto_aggregate(DOCS / "rto-rehearsals.jsonl"),
    ]
    return 0 if all(code == 0 for code in codes) else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="mode", required=True)

    started = sub.add_parser("start")
    started.add_argument("--target", required=True)
    started.add_argument("--restore-command", default="")
    started.add_argument("--backup-command", default="")
    started.add_argument("--restart", action="store_true")
    started.set_defaults(func=start)

    sub.add_parser("tick").set_defaults(func=tick)
    sub.add_parser("status").set_defaults(func=status)
    sub.add_parser("aggregate").set_defaults(func=aggregate)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())

"""Schedule a real seven-day availability, RPO, and RTO pilot window.

``run`` is the supervisor: one process, one writer, a tick every 30 seconds for
seven days. Source recovery marks are written every tick. At the configured
recovery cadence an external command restores a *separate* API and database, RTO
is measured through an authenticated write, RPO is measured from the highest
surviving source mark, and an optional cleanup command removes the isolated
target. The live source can never be configured as the recovery URL.

``tick`` performs exactly one of those cycles and exists for tests and for
manual inspection. Do not put it on cron or Task Scheduler. Both bottom out at a
one-minute granularity -- `schtasks /SC MINUTE` accepts 1..1439 *minutes*, and
cron's finest field is a minute -- while the measurement contract fixes the
probe interval at 30 seconds. A one-minute cadence therefore leaves every second
slot unwritten, and an unwritten slot is unavailable by design, so a perfectly
healthy deployment measures ~50% available. Observed against a target that
answered 200 on every real probe: 57.1% over four invocations.

Availability has two possible writers and the journal permits exactly one:

  ``--availability-writer scheduler``  this process probes as part of each tick.
      Simple, but the probe stops for as long as a recovery rehearsal runs, and
      those minutes are backfilled as unavailable. The 99.9% target allows 604.8
      seconds of downtime across the whole window, so roughly ten minutes total
      -- less than a single Postgres restore. Sound only when no rehearsal is
      configured, i.e. an availability-only window.

  ``--availability-writer observer``  the separate `pilot-observability`
      container owns the journal and keeps probing throughout a rehearsal. This
      process then writes no availability sample, and instead fails its tick
      when the observer stops advancing, so a dead observer is a loud failure
      rather than a silent gap.

Collecting all three gates requires the observer.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import stat
import subprocess
import sys
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, Iterator, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))

REPO_ROOT = Path(__file__).resolve().parent.parent
EVIDENCE_ROOT = Path(os.getenv("PILOT_EVIDENCE_ROOT", str(REPO_ROOT / "docs")))
MANIFEST = EVIDENCE_ROOT / "pilot-window.json"
ENVIRONMENT_KEY = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

WINDOW_DAYS = 7
WINDOW_SECONDS = WINDOW_DAYS * 24 * 60 * 60
PROBE_INTERVAL_SECONDS = 30
# The declared recovery objective is five minutes. The scheduler default cannot
# quietly create six-hour recovery points and then pretend the harness failed;
# operators may use WAL archival or another incremental backup command here.
BACKUP_INTERVAL_SECONDS = 5 * 60
RECOVERY_INTERVAL_SECONDS = 14 * 60 * 60
RPO_SAMPLE_TARGET = 10
PRE_BACKUP_SAMPLE_TARGET = 2
RTO_REHEARSAL_TARGET = 4

AVAILABILITY_WRITERS = ("scheduler", "observer")
# Two missed slots is what the contract already treats as an outage, so the
# supervisor refuses to keep collecting past that rather than accumulate a gap
# it would only discover at aggregation.
OBSERVER_MAX_LAG_SECONDS = 2 * PROBE_INTERVAL_SECONDS
SUPERVISOR_LOCK = "pilot-window-supervisor.lock"
SUPERVISOR_LOCK_STALE_SECONDS = 5 * PROBE_INTERVAL_SECONDS


class WindowVoided(RuntimeError):
    """The window can no longer produce evidence, and no later tick repairs it.

    Distinct from an ordinary tick failure so the supervisor cannot mistake a
    transient error for a schema change and quietly stop collecting.
    """


def configure_runtime(
    *,
    evidence_root: Optional[str] = None,
    environment_file: Optional[str] = None,
    token_file: Optional[str] = None,
    token_env: Optional[str] = None,
) -> None:
    """Bind the supervisor to durable paths before reading its manifest.

    Startup managers do not inherit the shell that opened a seven-day window.
    The evidence path is safe to pass as an argument; the recovery credential is
    read from a protected file so it never appears in a process command line or
    scheduled-task definition.
    """
    global EVIDENCE_ROOT, MANIFEST

    if environment_file:
        runtime_path = Path(environment_file).expanduser().resolve()
        if not runtime_path.is_file():
            raise ValueError(f"Pilot runtime environment file does not exist: {runtime_path}")
        metadata = runtime_path.stat()
        if os.name != "nt" and stat.S_IMODE(metadata.st_mode) & 0o077:
            raise ValueError(
                f"Pilot runtime environment file must not be accessible by group or others: {runtime_path}"
            )
        if metadata.st_size > 65536:
            raise ValueError("Pilot runtime environment file is unexpectedly large")
        for line_number, raw_line in enumerate(runtime_path.read_text(encoding="utf-8").splitlines(), 1):
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                raise ValueError(f"Invalid pilot runtime environment entry on line {line_number}")
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip()
            if not ENVIRONMENT_KEY.match(key):
                raise ValueError(f"Invalid pilot runtime environment key on line {line_number}")
            if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
                value = value[1:-1]
            os.environ[key] = value

    if evidence_root:
        EVIDENCE_ROOT = Path(evidence_root).expanduser().resolve()
        MANIFEST = EVIDENCE_ROOT / "pilot-window.json"
    if not token_file:
        return

    secret_path = Path(token_file).expanduser().resolve()
    if not secret_path.is_file():
        raise ValueError(f"Pilot recovery token file does not exist: {secret_path}")
    metadata = secret_path.stat()
    if os.name != "nt" and stat.S_IMODE(metadata.st_mode) & 0o077:
        raise ValueError(
            f"Pilot recovery token file must not be accessible by group or others: {secret_path}"
        )
    if metadata.st_size > 4096:
        raise ValueError("Pilot recovery token file is unexpectedly large")
    token = secret_path.read_text(encoding="utf-8").strip()
    if len(token) < 32 or len(token.splitlines()) != 1:
        raise ValueError("Pilot recovery token file must contain one secret of at least 32 characters")

    environment_name = token_env
    if not environment_name:
        manifest = load_manifest()
        environment_name = str((manifest or {}).get("token_env") or "PILOT_RECOVERY_TOKEN")
    os.environ[environment_name] = token


def _path(name: str) -> Path:
    return EVIDENCE_ROOT / name


def load_manifest() -> Optional[Dict[str, Any]]:
    if not MANIFEST.exists():
        return None
    try:
        payload = json.loads(MANIFEST.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else None
    except (json.JSONDecodeError, OSError):
        return None


def save_manifest(manifest: Dict[str, Any]) -> None:
    from app.pilot_evidence import save_run_state

    save_run_state(MANIFEST, manifest)


def start(args: argparse.Namespace) -> int:
    existing = load_manifest()
    if existing:
        raise RuntimeError(
            f"A window is already open at {EVIDENCE_ROOT}. Use a new "
            "PILOT_EVIDENCE_ROOT for a new migration-scoped pilot."
        )
    from recovery_probe_client import canonical_target, recovery_token, require_isolated_target
    from tier_b_evidence import current_head

    require_isolated_target(args.target, args.recovery_target)
    recovery_token(args.token_env)
    recovery_driver = getattr(args, "recovery_driver", "manual")
    if recovery_driver == "postgres-compose":
        from pilot_postgres_recovery import Config

        driver_config = Config.from_env()
        if canonical_target(driver_config.source_url) != canonical_target(args.target):
            raise ValueError("PILOT_SOURCE_URL must match --target for the postgres-compose driver")
        if canonical_target(driver_config.recovery_url) != canonical_target(args.recovery_target):
            raise ValueError(
                "PILOT_RECOVERY_URL must match --recovery-target for the postgres-compose driver"
            )
        driver = Path(__file__).parent / "pilot_postgres_recovery.py"
        executable = str(Path(sys.executable).resolve())
        prefix = f'"{executable}" "{driver}"'
        args.backup_command = args.backup_command.strip() or f"{prefix} backup"
        args.restore_command = args.restore_command.strip() or f"{prefix} restore"
        args.recovery_cleanup_command = (
            args.recovery_cleanup_command.strip() or f"{prefix} cleanup"
        )
    if not args.restore_command.strip() or not args.backup_command.strip():
        raise RuntimeError("Both --backup-command and --restore-command are required")
    if args.backup_interval_seconds <= 0 or args.recovery_interval_seconds <= 0:
        raise RuntimeError("Pilot intervals must be positive")
    writer = getattr(args, "availability_writer", "observer")
    if writer not in AVAILABILITY_WRITERS:
        raise ValueError(f"--availability-writer must be one of {AVAILABILITY_WRITERS}")
    if writer == "scheduler":
        # A rehearsal blocks this process, and every blocked slot is backfilled
        # as unavailable. Twelve rehearsals over seven days cannot fit in a
        # 604.8-second error budget, so refusing here is cheaper than letting
        # the window run for a week and fail on arithmetic that was fixed at
        # the moment it started.
        raise RuntimeError(
            "A scheduler-written availability journal cannot survive recovery "
            "rehearsals: the probe is blocked for the duration of each restore "
            "and every missed 30s slot counts as unavailable, against a total "
            f"budget of {WINDOW_SECONDS * 0.001:.1f}s for the whole window. Start the "
            "`pilot-observability` container and pass "
            "--availability-writer observer, or collect availability alone."
        )
    now = int(time.time())
    manifest = {
        "schema_version": 3,
        "started_at": now,
        "migration_head_at_start": current_head(),
        "target": args.target,
        "recovery_target": args.recovery_target,
        "project_id": args.project_id,
        "recovery_driver": recovery_driver,
        "availability_writer": writer,
        "token_env": args.token_env,
        "restore_command": args.restore_command,
        "recovery_cleanup_command": args.recovery_cleanup_command,
        "backup_command": args.backup_command,
        "backup_interval_seconds": args.backup_interval_seconds,
        "recovery_interval_seconds": args.recovery_interval_seconds,
        "window_seconds": WINDOW_SECONDS,
        "last_backup_at": 0,
        "last_recovery_at": now,
        "backup_attempts": 0,
        "recovery_attempts": 0,
    }
    save_manifest(manifest)
    print(json.dumps(manifest, indent=2, sort_keys=True))
    print(
        f"\nWindow open. Run `python oms/pilot_window.py run` and keep it running for "
        f"{WINDOW_DAYS} days. Do not schedule `tick`: cron and Task Scheduler both "
        f"round up to a minute and the contract needs {PROBE_INTERVAL_SECONDS}s."
    )
    return 0


def _run(command: str, timeout: int) -> int:
    completed = subprocess.run(
        command, shell=True, cwd=REPO_ROOT,
        capture_output=True, text=True, timeout=timeout,
    )
    return completed.returncode


def _record_recovery(manifest: Dict[str, Any], now: int, phase: str) -> tuple[int, int]:
    """Run one isolated restore, then return (rto_code, rpo_code)."""
    from recovery_probe_client import recovery_token
    from rpo_sampler import observe

    command = [
        sys.executable,
        str(Path(__file__).parent / "rto_rehearsal.py"),
        "record",
        "--source-target", manifest["target"],
        "--target", manifest["recovery_target"],
        "--restore-command", manifest["restore_command"],
        "--trigger", "unattended",
        "--project-id", manifest["project_id"],
        "--token-env", manifest["token_env"],
        "--rehearsals-file", str(_path("rto-rehearsals.jsonl")),
        "--note", f"scheduled isolated recovery at {now}",
    ]
    rto = subprocess.run(
        command, cwd=REPO_ROOT, capture_output=True, text=True,
        timeout=35 * 60,
    )
    rpo_code = 1
    try:
        if rto.returncode == 0:
            rpo_code = observe(
                manifest["target"],
                manifest["recovery_target"],
                _path("rpo-marks.jsonl"),
                _path("rpo-samples.jsonl"),
                phase,
                project_id=manifest["project_id"],
                token=recovery_token(manifest["token_env"]),
                note=f"same isolated recovery as RTO rehearsal at {now}",
                now=now,
            )
    finally:
        cleanup = str(manifest.get("recovery_cleanup_command") or "").strip()
        if cleanup:
            cleanup_code = _run(cleanup, timeout=15 * 60)
            if cleanup_code != 0:
                rpo_code = 1
    return rto.returncode, rpo_code


def observer_lag(now: int) -> Optional[int]:
    """Seconds since the observer last wrote, or None if it never has.

    Read from the observer's own state anchor rather than the journal: this runs
    every 30 seconds for a week, and revalidating a 20,000-record hash chain
    each time to learn one timestamp is work for `status` and `aggregate`.
    """
    state_file = _path("availability-probe-state.json")
    if not state_file.exists():
        return None
    try:
        state = json.loads(state_file.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    scheduled = state.get("next_scheduled_at")
    if not isinstance(scheduled, (int, float)):
        return None
    # next_scheduled_at is one interval past the last write.
    return max(0, now - (int(scheduled) - PROBE_INTERVAL_SECONDS))


def _observe_availability(manifest: Dict[str, Any], now: int) -> tuple[str, bool]:
    """Either write the sample, or verify the writer that does."""
    if manifest.get("availability_writer") == "observer":
        lag = observer_lag(now)
        if lag is None:
            return "availability-observer:absent", True
        if lag > OBSERVER_MAX_LAG_SECONDS:
            return f"availability-observer:stalled:{lag}s", True
        return f"availability-observer:current:{lag}s", False
    from availability_probe import run_probe

    run_probe(
        manifest["target"],
        _path("availability-samples.jsonl"),
        _path("availability-probe-state.json"),
        max_samples=1,
    )
    return "availability:recorded", False


def tick_once(manifest: Dict[str, Any]) -> tuple[int, list[str]]:
    from recovery_probe_client import recovery_token
    from rpo_sampler import write_mark
    from tier_b_evidence import current_head

    head = current_head()
    if head != manifest.get("migration_head_at_start"):
        raise WindowVoided(
            f"Migration head changed from {manifest.get('migration_head_at_start')} to {head}; "
            "start a new evidence root instead of pooling different schemas."
        )
    now = int(time.time())
    actions: list[str] = []

    action, failed = _observe_availability(manifest, now)
    actions.append(action)

    try:
        mark = write_mark(
            manifest["target"],
            _path("rpo-marks.jsonl"),
            _path("rpo-sampler-state.json"),
            project_id=manifest["project_id"],
            token=recovery_token(manifest["token_env"]),
            now=now,
        )
        actions.append(f"rpo-mark:{mark['sequence']}")
    except Exception as error:  # the scheduler continues and exits nonzero
        failed = True
        actions.append(f"rpo-mark-failed:{type(error).__name__}")

    backup_due = now - int(manifest["last_backup_at"]) >= int(manifest["backup_interval_seconds"])
    recovery_due = (
        int(manifest.get("backup_attempts", 0)) > 0
        and now - int(manifest["last_recovery_at"]) >= int(manifest["recovery_interval_seconds"])
    )
    if recovery_due:
        phase = "pre_backup" if backup_due else "mid_cycle"
        rto_code, rpo_code = _record_recovery(manifest, now, phase)
        manifest["last_recovery_at"] = now
        manifest["recovery_attempts"] = int(manifest.get("recovery_attempts", 0)) + 1
        actions.extend((f"rto:{rto_code}", f"rpo-observe:{rpo_code}:{phase}"))
        failed = failed or rto_code != 0 or rpo_code != 0

    # A pre-backup observation must restore the previous recovery point. The new
    # backup therefore runs after the observation, never before it.
    if backup_due:
        try:
            backup_code = _run(manifest["backup_command"], timeout=3600)
        except Exception:
            backup_code = 1
        manifest["last_backup_at"] = now
        manifest["backup_attempts"] = int(manifest.get("backup_attempts", 0)) + 1
        actions.append(f"backup:{backup_code}")
        failed = failed or backup_code != 0

    save_manifest(manifest)
    return (1 if failed else 0), actions


def tick(args: argparse.Namespace) -> int:
    """One cycle. For tests and manual inspection -- see `run` for the window."""
    del args
    manifest = load_manifest()
    if manifest is None:
        raise RuntimeError("No window is open. Run `pilot_window.py start` first.")
    code, actions = tick_once(manifest)
    print(json.dumps(
        {"elapsed_seconds": int(time.time()) - manifest["started_at"], "actions": actions},
        sort_keys=True,
    ))
    return code


@contextmanager
def _supervisor_lock() -> Iterator[Path]:
    """Exactly one supervisor per evidence root.

    Concurrent journal appends are already serialized and duplicate slots are
    rejected at load, so a second supervisor would not corrupt the chain. It
    would corrupt the *window*: both read-modify-write one manifest, so each
    silently discards the other's backup and recovery counters.
    """
    lock_path = _path(SUPERVISOR_LOCK)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    while True:
        try:
            descriptor = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            break
        except FileExistsError:
            try:
                age = time.time() - lock_path.stat().st_mtime
            except FileNotFoundError:
                continue
            if age <= SUPERVISOR_LOCK_STALE_SECONDS:
                raise RuntimeError(
                    f"Another supervisor holds {lock_path} (last heartbeat {int(age)}s ago). "
                    "One evidence root takes one supervisor."
                )
            # Older than several probe intervals: the holder died without
            # releasing. Reclaiming is safe because the manifest it left behind
            # is complete -- every tick saves it before returning.
            lock_path.unlink(missing_ok=True)
    os.write(descriptor, f"{os.getpid()}\n".encode("ascii"))
    os.fsync(descriptor)
    try:
        yield lock_path
    finally:
        os.close(descriptor)
        lock_path.unlink(missing_ok=True)


def run(args: argparse.Namespace) -> int:
    """Supervise the window: one process, one writer, a tick every 30 seconds.

    This exists because neither cron nor Task Scheduler can express the
    contract's 30-second interval; both round up to a minute, and the missing
    slots are scored as downtime.
    """
    manifest = load_manifest()
    if manifest is None:
        raise RuntimeError("No window is open. Run `pilot_window.py start` first.")
    limit = getattr(args, "max_ticks", None)
    deadline = int(manifest["started_at"]) + int(manifest["window_seconds"])
    ticks = failures = 0
    with _supervisor_lock() as lock_path:
        print(
            f"Supervising {manifest['target']} every {PROBE_INTERVAL_SECONDS}s until "
            f"{deadline} (availability writer: {manifest.get('availability_writer')})."
        )
        while limit is None or ticks < limit:
            started = time.monotonic()
            try:
                code, actions = tick_once(manifest)
            except WindowVoided as error:
                # Only this ends collection. Nothing a later tick does repairs a
                # schema change, and continuing would pool two schemas in one file.
                print(f"Supervisor stopping: {error}")
                return 1
            except Exception as error:  # one bad tick must not end seven days
                code, actions = 1, [f"tick-failed:{type(error).__name__}:{error}"]
            ticks += 1
            failures += 1 if code else 0
            print(json.dumps({"tick": ticks, "code": code, "actions": actions}, sort_keys=True),
                  flush=True)
            lock_path.touch()
            if int(time.time()) >= deadline:
                print(f"Window complete after {ticks} ticks ({failures} failed).")
                return 0
            if limit is not None and ticks >= limit:
                break
            # Pace to the next boundary from a fixed origin, so a rehearsal that
            # overran does not then fire a burst of catch-up ticks.
            elapsed = time.monotonic() - started
            remaining = PROBE_INTERVAL_SECONDS - (elapsed % PROBE_INTERVAL_SECONDS)
            time.sleep(remaining)
    print(f"Stopped after {ticks} ticks ({failures} failed).")
    return 1 if failures else 0


def status(args: argparse.Namespace) -> int:
    del args
    manifest = load_manifest()
    if manifest is None:
        print("No window is open.")
        return 1
    from app.pilot_evidence import JournalIntegrityError
    from availability_probe import load_samples
    from rpo_sampler import load_jsonl
    from rto_rehearsal import load_rehearsals
    from tier_b_evidence import current_head

    try:
        probes = len(load_samples(_path("availability-samples.jsonl")))
        rpo_samples = load_jsonl(_path("rpo-samples.jsonl"))
        rehearsals = load_rehearsals(_path("rto-rehearsals.jsonl"))
    except JournalIntegrityError as error:
        print(f"Pilot evidence integrity failure: {error}")
        return 1
    now = int(time.time())
    elapsed = now - manifest["started_at"]
    remaining = max(0, manifest["window_seconds"] - elapsed)
    pre_backup = sum(1 for row in rpo_samples if row.get("phase") == "pre_backup")
    unattended = sum(1 for row in rehearsals if row.get("trigger") == "unattended")
    writer = manifest.get("availability_writer", "scheduler")
    lag = observer_lag(now) if writer == "observer" else None
    print("Pilot window status\n")
    print(f"  availability by     {writer}"
          + ("" if writer != "observer"
             else f" (last wrote {'never' if lag is None else str(lag) + 's ago'})"))
    print(f"  elapsed             {elapsed // 3600}h of {manifest['window_seconds'] // 3600}h")
    print(f"  remaining           {remaining // 3600}h")
    print(f"  availability probes {probes} (expected ~{elapsed // PROBE_INTERVAL_SECONDS})")
    print(f"  rpo samples         {len(rpo_samples)} of {RPO_SAMPLE_TARGET}, pre-backup {pre_backup} of {PRE_BACKUP_SAMPLE_TARGET}")
    print(f"  rto rehearsals      {len(rehearsals)} of {RTO_REHEARSAL_TARGET}, unattended {unattended} of 1")
    if current_head() != manifest["migration_head_at_start"]:
        print("\n  MIGRATION HEAD DRIFTED. This window cannot produce current evidence.")
        return 1
    owed = []
    if remaining:
        owed.append(f"{remaining // 3600}h of wall clock")
    if len(rpo_samples) < RPO_SAMPLE_TARGET:
        owed.append(f"{RPO_SAMPLE_TARGET - len(rpo_samples)} rpo samples")
    if pre_backup < PRE_BACKUP_SAMPLE_TARGET:
        owed.append(f"{PRE_BACKUP_SAMPLE_TARGET - pre_backup} pre-backup samples")
    if len(rehearsals) < RTO_REHEARSAL_TARGET:
        owed.append(f"{RTO_REHEARSAL_TARGET - len(rehearsals)} rto rehearsals")
    if unattended < 1:
        owed.append("1 unattended rehearsal")
    if writer == "observer" and (lag is None or lag > OBSERVER_MAX_LAG_SECONDS):
        owed.append("a live availability observer")
    print("\n  " + ("Window complete; run aggregate." if not owed else "Still owed: " + ", ".join(owed)))
    return 0 if not owed else 1


def verify_runtime(args: argparse.Namespace) -> int:
    """Verify persisted startup inputs against the already-open window."""
    del args
    manifest = load_manifest()
    if manifest is None:
        print("No window is open. Run preflight and start before installing a supervisor.")
        return 1
    checks: list[tuple[str, bool, str]] = []

    def check(name: str, ok: bool, detail: str) -> None:
        checks.append((name, ok, detail))

    from recovery_probe_client import canonical_target, json_request
    from tier_b_evidence import current_head

    head = current_head()
    check("migration-head", head == manifest.get("migration_head_at_start"),
          f"runtime {head}, window {manifest.get('migration_head_at_start')}")
    token_env = str(manifest.get("token_env") or "PILOT_RECOVERY_TOKEN")
    token = os.getenv(token_env, "").strip()
    check("recovery-token", len(token) >= 32,
          f"{token_env} holds {len(token)} characters; production requires 32")
    if token:
        code, _ = json_request(
            str(manifest["target"]),
            "/health/pilot-recovery/marks/_preflight/highest",
            token=token,
            timeout=10.0,
        )
        check("recovery-token-accepted", code == 422,
              f"source recovery protocol returned {code}; expected authenticated validation 422")

    if manifest.get("recovery_driver") == "postgres-compose":
        try:
            from pilot_postgres_recovery import Config

            config = Config.from_env()
            source_matches = canonical_target(config.source_url) == canonical_target(str(manifest["target"]))
            recovery_matches = canonical_target(config.recovery_url) == canonical_target(
                str(manifest["recovery_target"])
            )
            check("source-target", source_matches,
                  f"runtime {config.source_url}, window {manifest['target']}")
            check("recovery-target", recovery_matches,
                  f"runtime {config.recovery_url}, window {manifest['recovery_target']}")
            check("recovery-projects", config.source_project != config.recovery_project,
                  f"{config.source_project} -> {config.recovery_project}")
        except Exception as error:
            check("recovery-driver", False, f"{type(error).__name__}: {error}")

    lag = observer_lag(int(time.time())) if manifest.get("availability_writer") == "observer" else 0
    check("availability-observer", lag is not None and lag <= OBSERVER_MAX_LAG_SECONDS,
          "no observer state" if lag is None else f"last wrote {lag}s ago")

    width = max(len(name) for name, _, _ in checks)
    print("Pilot persisted-runtime verification\n")
    for name, ok, detail in checks:
        print(f"  {'PASS' if ok else 'FAIL'}  {name.ljust(width)}  {detail}")
    failed = [name for name, ok, _ in checks if not ok]
    if failed:
        print(f"\n{len(failed)} runtime check(s) failed: {', '.join(failed)}.")
        return 1
    print(f"\nAll {len(checks)} persisted runtime checks passed.")
    return 0


def preflight(args: argparse.Namespace) -> int:
    """Check everything checkable before committing seven days to it.

    Every failure here is one that would otherwise surface as a failed gate at
    the end of the window, by which time the only remedy is another week.
    """
    checks: list[tuple[str, bool, str]] = []

    def check(name: str, ok: bool, detail: str) -> None:
        checks.append((name, ok, detail))

    try:
        EVIDENCE_ROOT.mkdir(parents=True, exist_ok=True)
        probe = EVIDENCE_ROOT / ".preflight-write-probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        check("evidence-root", True, f"writable: {EVIDENCE_ROOT}")
    except OSError as error:
        check("evidence-root", False, f"{EVIDENCE_ROOT}: {error}")

    check("window-not-open", not MANIFEST.exists(),
          "no manifest present" if not MANIFEST.exists()
          else f"{MANIFEST} exists; use a fresh PILOT_EVIDENCE_ROOT")

    try:
        import shutil

        free_gb = shutil.disk_usage(EVIDENCE_ROOT).free / 1e9
        check("disk-space", free_gb >= 5.0, f"{free_gb:.1f} GB free (journals plus backups)")
    except OSError as error:
        check("disk-space", False, str(error))

    from availability_probe import probe_once

    sample = probe_once(args.target)
    detail = ", ".join(
        f"{endpoint} {value['status']} in {value['elapsed_ms']}ms"
        for endpoint, value in sample["endpoints"].items() if isinstance(value, dict)
    )
    check("source-health", bool(sample["available"]), detail or "unreachable")

    from recovery_probe_client import canonical_target, json_request, require_isolated_target

    try:
        require_isolated_target(args.target, args.recovery_target)
        check("recovery-isolated", True,
              f"{canonical_target(args.target)} != {canonical_target(args.recovery_target)}")
    except ValueError as error:
        check("recovery-isolated", False, str(error))

    token = os.getenv(args.token_env, "").strip()
    check("recovery-token", len(token) >= 32,
          f"{args.token_env} holds {len(token)} characters; production requires 32")

    if token:
        # Read-only, and deliberately malformed. `_run_id` must start
        # alphanumeric, so a live route rejects this with 422 -- but only after
        # the token dependency has already accepted the credential. That
        # separates the three answers a plain lookup cannot:
        #
        #   422  route mounted, token accepted
        #   404  PILOT_RECOVERY_TOKEN is unset *on the API*, so the whole
        #        protocol is disabled -- and a real lookup would also answer 404
        #        for "no such run", which is why this asks with a bad run_id
        #   401  the API has a token and it is not this one
        #
        # The 404 case is the likely mistake: the token exported for this
        # process but never put in the API container's environment. Every RPO
        # mark would then fail for seven days.
        meaning = {
            422: "route mounted and credential accepted",
            404: "the recovery protocol is DISABLED -- set PILOT_RECOVERY_TOKEN "
                 "in the API container, not only in this shell",
            401: "the API has a different recovery token",
            403: "the API refused the recovery credential",
            503: "the API considers its recovery token production-unsafe",
            0: "unreachable",
        }
        code, _ = json_request(
            args.target, "/health/pilot-recovery/marks/_preflight/highest",
            token=token, timeout=10.0,
        )
        check("recovery-token-accepted", code == 422,
              f"GET .../marks/_preflight/highest returned {code}: "
              + meaning.get(code, "unexpected status"))

    if args.recovery_driver == "postgres-compose":
        try:
            from pilot_postgres_recovery import Config

            config = Config.from_env()
            matched = (canonical_target(config.source_url) == canonical_target(args.target)
                       and canonical_target(config.recovery_url) == canonical_target(args.recovery_target))
            check("recovery-driver", matched,
                  f"projects {config.source_project} -> {config.recovery_project}, "
                  f"backups {config.backup_root}"
                  + ("" if matched else "; PILOT_SOURCE_URL/PILOT_RECOVERY_URL do not match the targets"))
        except Exception as error:
            check("recovery-driver", False, f"{type(error).__name__}: {error}")

    if args.availability_writer == "observer":
        lag = observer_lag(int(time.time()))
        check("availability-observer", lag is not None and lag <= OBSERVER_MAX_LAG_SECONDS,
              "no observer journal state; start the pilot-observability profile"
              if lag is None else f"last wrote {lag}s ago (limit {OBSERVER_MAX_LAG_SECONDS}s)")

    from tier_b_evidence import current_head

    head = current_head()
    check("migration-head", True, f"{head} -- must not change for {WINDOW_DAYS} days")

    width = max(len(name) for name, _, _ in checks)
    print("Pilot preflight\n")
    for name, ok, detail in checks:
        print(f"  {'PASS' if ok else 'FAIL'}  {name.ljust(width)}  {detail}")
    failed = [name for name, ok, _ in checks if not ok]
    if failed:
        print(f"\n{len(failed)} check(s) failed: {', '.join(failed)}. The window is not ready.")
        return 1
    print(f"\nAll {len(checks)} checks passed. A window opened now closes in {WINDOW_DAYS} days.")
    return 0


def aggregate(args: argparse.Namespace) -> int:
    del args
    from availability_probe import aggregate as availability_aggregate
    from rpo_sampler import aggregate as rpo_aggregate
    from rto_rehearsal import aggregate as rto_aggregate

    generated = _path("generated")
    codes = [
        availability_aggregate(
            _path("availability-samples.jsonl"), output_dir=generated,
            state_file=_path("availability-probe-state.json"),
        ),
        rpo_aggregate(_path("rpo-samples.jsonl"), output_dir=generated),
        rto_aggregate(_path("rto-rehearsals.jsonl"), output_dir=generated),
    ]
    return 0 if all(code == 0 for code in codes) else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--evidence-root",
        default=None,
        help="Durable pilot evidence directory. Pass before the subcommand.",
    )
    parser.add_argument(
        "--token-file",
        default=None,
        help="Protected file containing PILOT_RECOVERY_TOKEN. Pass before the subcommand.",
    )
    parser.add_argument(
        "--environment-file",
        default=None,
        help="Protected KEY=VALUE runtime configuration. Pass before the subcommand.",
    )
    sub = parser.add_subparsers(dest="mode", required=True)
    started = sub.add_parser("start")
    started.add_argument("--target", required=True, help="Live source API")
    started.add_argument("--recovery-target", required=True, help="Distinct isolated restored API")
    started.add_argument(
        "--recovery-driver", choices=("manual", "postgres-compose"), default="manual",
        help="Use explicit commands or the shipped isolated PostgreSQL Compose driver",
    )
    started.add_argument("--restore-command", default="")
    started.add_argument("--recovery-cleanup-command", default="")
    started.add_argument("--backup-command", default="")
    started.add_argument("--project-id", default="default")
    started.add_argument("--token-env", default="PILOT_RECOVERY_TOKEN")
    started.add_argument("--backup-interval-seconds", type=int, default=BACKUP_INTERVAL_SECONDS)
    started.add_argument("--recovery-interval-seconds", type=int, default=RECOVERY_INTERVAL_SECONDS)
    started.add_argument(
        "--availability-writer", choices=AVAILABILITY_WRITERS, default="observer",
        help="Who owns the availability journal. Collecting RPO and RTO requires "
             "'observer', because a rehearsal blocks this process and every blocked "
             "slot is scored as downtime.",
    )
    started.set_defaults(func=start)

    checked = sub.add_parser("preflight", help="Validate the configuration before opening a window")
    checked.add_argument("--target", required=True)
    checked.add_argument("--recovery-target", required=True)
    checked.add_argument("--recovery-driver", choices=("manual", "postgres-compose"), default="manual")
    checked.add_argument("--availability-writer", choices=AVAILABILITY_WRITERS, default="observer")
    checked.add_argument("--token-env", default="PILOT_RECOVERY_TOKEN")
    checked.set_defaults(func=preflight)

    supervised = sub.add_parser("run", help="Supervise the whole window in one process")
    supervised.add_argument("--max-ticks", type=int, default=None,
                            help="Stop after this many ticks. For harness self-tests only.")
    supervised.set_defaults(func=run)

    sub.add_parser("tick").set_defaults(func=tick)
    sub.add_parser("status").set_defaults(func=status)
    sub.add_parser("verify-runtime", help="Validate persisted startup inputs for an open window").set_defaults(
        func=verify_runtime
    )
    sub.add_parser("aggregate").set_defaults(func=aggregate)
    args = parser.parse_args()
    try:
        configure_runtime(
            evidence_root=args.evidence_root,
            environment_file=args.environment_file,
            token_file=args.token_file,
            token_env=getattr(args, "token_env", None),
        )
    except (OSError, UnicodeError, ValueError) as error:
        parser.error(str(error))
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())

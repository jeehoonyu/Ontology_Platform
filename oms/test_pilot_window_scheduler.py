"""Pilot scheduler safety, ordering, and failure propagation."""
import argparse
import json
import os
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import availability_probe  # noqa: E402
import pilot_window  # noqa: E402
import rpo_sampler  # noqa: E402

os.environ["PILOT_RECOVERY_TOKEN"] = "pilot-window-test-token-abcdefghijklmnopqrstuvwxyz"
passed = 0


def check(condition, label, payload=None):
    global passed
    assert condition, f"{label}: {payload}"
    passed += 1


def arguments(**overrides):
    values = {
        "target": "http://source.test:8000",
        "recovery_target": "http://recovery.test:8001",
        "restore_command": "restore-isolated",
        "recovery_cleanup_command": "cleanup-isolated",
        "backup_command": "backup-source",
        "project_id": "operations",
        "token_env": "PILOT_RECOVERY_TOKEN",
        "backup_interval_seconds": 300,
        "recovery_interval_seconds": 600,
        "availability_writer": "observer",
    }
    values.update(overrides)
    return argparse.Namespace(**values)


def observer_wrote(root, seconds_ago=0):
    """Stand in for the pilot-observability container's state anchor."""
    (root / "availability-probe-state.json").write_text(
        json.dumps({
            "next_scheduled_at":
                int(time.time()) - seconds_ago + pilot_window.PROBE_INTERVAL_SECONDS,
        }),
        encoding="utf-8",
    )


with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as directory:
    root = Path(directory)
    pilot_window.EVIDENCE_ROOT = root
    pilot_window.MANIFEST = root / "pilot-window.json"

    try:
        pilot_window.start(arguments(recovery_target="http://source.test:8000/"))
        raise AssertionError("scheduler accepted the live target as recovery target")
    except ValueError:
        passed += 1
    try:
        pilot_window.start(arguments(restore_command=""))
        raise AssertionError("scheduler accepted an empty restore command")
    except RuntimeError:
        passed += 1

    # A rehearsal blocks this process for as long as a restore takes, and every
    # blocked 30s slot is scored as downtime against a 604.8s budget for the
    # whole week. Refusing at start is cheaper than discovering it on day seven.
    try:
        pilot_window.start(arguments(availability_writer="scheduler"))
        raise AssertionError("scheduler-written availability was accepted alongside rehearsals")
    except RuntimeError as error:
        check("observer" in str(error), "the refusal names the remedy", error)

    check(pilot_window.start(arguments()) == 0, "valid isolated pilot starts")
    manifest = pilot_window.load_manifest()
    check(manifest["schema_version"] == 3, "manifest records the availability writer", manifest)
    check(manifest["availability_writer"] == "observer", "and defaults it to the observer")
    check(manifest["recovery_target"] != manifest["target"], "source and restore targets remain distinct")

    events = []
    original_probe = availability_probe.run_probe
    original_mark = rpo_sampler.write_mark
    original_run = pilot_window._run
    original_recovery = pilot_window._record_recovery
    try:
        availability_probe.run_probe = lambda *_args, **_kwargs: events.append("availability") or 0
        rpo_sampler.write_mark = lambda *_args, **_kwargs: events.append("mark") or {"sequence": 1}
        pilot_window._run = lambda command, timeout: events.append(command) or 0
        pilot_window._record_recovery = (
            lambda _manifest, _now, phase: events.append(f"recovery:{phase}") or (0, 0)
        )

        # An observer that never wrote, or stopped writing, is a failure rather
        # than a gap discovered at aggregation.
        check(pilot_window.tick(argparse.Namespace()) == 1, "a missing observer fails the tick")
        observer_wrote(root, seconds_ago=pilot_window.OBSERVER_MAX_LAG_SECONDS + 30)
        check(pilot_window.tick(argparse.Namespace()) == 1, "a stalled observer fails the tick")

        # Those two ticks each ran a backup; rewind so the ordering assertion
        # below sees a genuinely fresh window.
        events.clear()
        observer_wrote(root)
        manifest = pilot_window.load_manifest()
        manifest.update({"last_backup_at": 0, "backup_attempts": 0})
        pilot_window.save_manifest(manifest)
        check(pilot_window.tick(argparse.Namespace()) == 0, "first tick succeeds")
        check("availability" not in events,
              "the scheduler does not write the journal the observer owns", events)
        check(events == ["mark", "backup-source"],
              "first tick establishes backup before any restore", events)

        events.clear()
        observer_wrote(root)
        manifest = pilot_window.load_manifest()
        manifest["last_backup_at"] = int(time.time()) - 301
        manifest["last_recovery_at"] = int(time.time()) - 601
        manifest["backup_attempts"] = 1
        pilot_window.save_manifest(manifest)
        check(pilot_window.tick(argparse.Namespace()) == 0, "scheduled recovery tick succeeds")
        check(events == ["mark", "recovery:pre_backup", "backup-source"],
              "pre-backup restore is measured before the new backup", events)

        events.clear()
        observer_wrote(root)
        manifest = pilot_window.load_manifest()
        manifest["last_backup_at"] = int(time.time()) - 301
        manifest["last_recovery_at"] = int(time.time()) - 601
        pilot_window.save_manifest(manifest)
        pilot_window._record_recovery = lambda *_args: events.append("recovery:failed") or (1, 1)
        check(pilot_window.tick(argparse.Namespace()) == 1,
              "failed isolated recovery makes the scheduler tick fail", events)

        # The supervisor: one process per evidence root, and a tick that raises
        # must not end the window.
        pilot_window._record_recovery = original_recovery
        observer_wrote(root)
        with pilot_window._supervisor_lock():
            try:
                with pilot_window._supervisor_lock():
                    raise AssertionError("two supervisors held one evidence root")
            except RuntimeError:
                passed += 1
        check(not (root / pilot_window.SUPERVISOR_LOCK).exists(),
              "the lock is released on the way out")

        events.clear()
        observer_wrote(root)
        exploded = {"count": 0}

        def explode_once(*_args, **_kwargs):
            exploded["count"] += 1
            if exploded["count"] == 1:
                raise OSError("transient")
            events.append("mark")
            return {"sequence": exploded["count"]}

        rpo_sampler.write_mark = explode_once
        started = time.monotonic()
        code = pilot_window.run(argparse.Namespace(max_ticks=2))
        check(exploded["count"] == 2, "the supervisor kept going after a failed tick", exploded)
        check(code == 1, "and still reports the failure", code)
        check(time.monotonic() - started >= pilot_window.PROBE_INTERVAL_SECONDS,
              "consecutive ticks are paced one probe interval apart")

        # A transient RuntimeError is a failed tick; only a voided window stops
        # collection. Confusing the two would end seven days on a hiccup.
        original_tick = pilot_window.tick_once
        try:
            attempts = {"count": 0}

            def flaky(_manifest):
                attempts["count"] += 1
                raise RuntimeError("transient")

            pilot_window.tick_once = flaky
            check(pilot_window.run(argparse.Namespace(max_ticks=2)) == 1,
                  "a plain RuntimeError is a failed tick, not a stop")
            check(attempts["count"] == 2,
                  "and the supervisor kept its schedule through it", attempts)

            pilot_window.tick_once = lambda _m: (_ for _ in ()).throw(
                pilot_window.WindowVoided("head moved"))
            stopped = time.monotonic()
            check(pilot_window.run(argparse.Namespace(max_ticks=5)) == 1,
                  "a voided window stops the supervisor")
            check(time.monotonic() - stopped < pilot_window.PROBE_INTERVAL_SECONDS,
                  "on the first tick rather than pacing through five")
        finally:
            pilot_window.tick_once = original_tick
    finally:
        availability_probe.run_probe = original_probe
        rpo_sampler.write_mark = original_mark
        pilot_window._run = original_run
        pilot_window._record_recovery = original_recovery

with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as directory:
    root = Path(directory)
    pilot_window.EVIDENCE_ROOT = root
    pilot_window.MANIFEST = root / "pilot-window.json"
    repo = Path(__file__).resolve().parents[1]
    os.environ.update({
        "PILOT_SOURCE_COMPOSE_FILES": str(repo / "docker-compose.yml"),
        "PILOT_RECOVERY_COMPOSE_FILE": str(repo / "docker-compose.pilot-recovery.yml"),
        "PILOT_SOURCE_PROJECT": "ontology-source",
        "PILOT_RECOVERY_PROJECT": "ontology-recovery",
        "PILOT_BACKUP_ROOT": str(root / "backups"),
        "PILOT_SOURCE_URL": "http://source.test:8000",
        "PILOT_RECOVERY_URL": "http://recovery.test:8001",
        "PILOT_BACKUP_INTEGRITY_KEY": "pilot-backup-integrity-key-abcdefghijklmnopqrstuvwxyz",
    })
    reference_args = arguments(
        recovery_driver="postgres-compose",
        backup_command="",
        restore_command="",
        recovery_cleanup_command="",
    )
    check(pilot_window.start(reference_args) == 0, "reference recovery driver starts")
    reference_manifest = pilot_window.load_manifest()
    check("pilot_postgres_recovery.py\" backup" in reference_manifest["backup_command"],
          "reference driver supplies stable backup command", reference_manifest)
    check("pilot_postgres_recovery.py\" restore" in reference_manifest["restore_command"],
          "reference driver supplies stable restore command", reference_manifest)
    check("pilot_postgres_recovery.py\" cleanup" in reference_manifest["recovery_cleanup_command"],
          "reference driver supplies stable cleanup command", reference_manifest)

print(f"Pilot window scheduler verified: {passed} assertions passed.")

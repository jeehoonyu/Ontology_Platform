"""Reference pilot backup/restore driver safety and integrity contracts."""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import pilot_postgres_recovery as driver  # noqa: E402

HEAD = "0042_stream_outer_joins"
passed = 0


def check(condition, label, payload=None):
    global passed
    assert condition, f"{label}: {payload}"
    passed += 1


class FakeDocker:
    def __init__(self, config):
        self.config = config
        self.source_calls = []
        self.recovery_calls = []

    @staticmethod
    def _result(stdout=""):
        return subprocess.CompletedProcess([], 0, stdout=stdout, stderr="")

    def source(self, args, **_kwargs):
        args = tuple(args)
        self.source_calls.append(args)
        if args[:3] == ("exec", "-T", self.config.database_service) and "SELECT version_num" in args[-1]:
            return self._result(HEAD + "\n")
        if args and args[0] == "cp":
            target = Path(args[-1])
            if target.name.endswith(".snapshots.tar.gz"):
                target.write_bytes(b"snapshot-archive")
            elif target.name.endswith(".plugins.tar.gz"):
                target.write_bytes(b"plugin-archive")
            else:
                target.write_bytes(b"postgres-custom-archive")
        return self._result()

    def recovery(self, args, **_kwargs):
        args = tuple(args)
        self.recovery_calls.append(args)
        if args[:3] == ("exec", "-T", "postgres") and "SELECT version_num" in args[-1]:
            return self._result(HEAD + "\n")
        return self._result()


with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as directory:
    root = Path(directory)
    source_compose = root / "source.yml"
    recovery_compose = root / "recovery.yml"
    source_compose.write_text("services: {}\n", encoding="utf-8")
    recovery_compose.write_text("services: {}\n", encoding="utf-8")
    values = {
        "PILOT_SOURCE_COMPOSE_FILES": str(source_compose),
        "PILOT_SOURCE_PROJECT": "ontology-source",
        "PILOT_RECOVERY_COMPOSE_FILE": str(recovery_compose),
        "PILOT_RECOVERY_PROJECT": "ontology-recovery",
        "PILOT_BACKUP_ROOT": str(root / "backups"),
        "PILOT_SOURCE_URL": "http://source.test:8000",
        "PILOT_RECOVERY_URL": "http://recovery.test:18002",
        "POSTGRES_USER": "ontology",
        "POSTGRES_DB": "ontology",
        "PILOT_BACKUP_RETENTION_COUNT": "2",
        "PILOT_BACKUP_INTEGRITY_KEY": "pilot-backup-integrity-key-abcdefghijklmnopqrstuvwxyz",
    }
    config = driver.Config.from_env(values)
    check(config.source_project != config.recovery_project, "source and recovery projects are isolated")
    check(config.include_snapshots and config.include_plugins, "complete local file backup defaults on")

    bad = {**values, "PILOT_RECOVERY_PROJECT": values["PILOT_SOURCE_PROJECT"]}
    try:
        driver.Config.from_env(bad)
        raise AssertionError("same Compose project was accepted")
    except ValueError:
        passed += 1
    bad = {**values, "PILOT_RECOVERY_URL": values["PILOT_SOURCE_URL"] + "/"}
    try:
        driver.Config.from_env(bad)
        raise AssertionError("same source and recovery URL was accepted")
    except ValueError:
        passed += 1
    bad = {**values, "PILOT_BACKUP_INTEGRITY_KEY": "weak"}
    try:
        driver.Config.from_env(bad)
        raise AssertionError("weak backup integrity key was accepted")
    except ValueError:
        passed += 1

    fake = FakeDocker(config)
    backup = driver.backup(config, fake)
    manifest = json.loads(Path(backup["manifest_path"]).read_text(encoding="utf-8"))
    check(manifest["migration_head"] == HEAD, "backup is current-head bound", manifest)
    check(set(manifest["files"]) == {"database", "snapshots", "plugins"}, "backup covers database and local file volumes")
    check(config.latest_path.is_file(), "backup writes an atomic latest pointer")
    check(all(spec["sha256"] for spec in manifest["files"].values()), "every backup artifact is checksummed")
    check(manifest["integrity"]["algorithm"] == "HMAC-SHA256", "backup manifest is authenticated")
    check(any("pg_restore" in call for call in fake.source_calls), "database archive is validated before publication")

    original_wait = driver._wait_api
    driver._wait_api = lambda _config: None
    try:
        receipt = driver.restore(config, fake)
    finally:
        driver._wait_api = original_wait
    calls = [" ".join(call) for call in fake.recovery_calls]
    check(receipt["fresh_volumes"] is True and receipt["migration_head"] == HEAD, "restore records fresh current-head evidence", receipt)
    check(calls[0].startswith("down -v --remove-orphans"), "restore destroys prior isolated volumes first", calls)
    check(any("cat /proc/1/comm" in call for call in calls), "restore waits past temporary PostGIS initialization")
    check(any("DROP DATABASE" in call for call in calls), "restore replaces only isolated database")
    check(any("pg_restore" in call and "--exit-on-error" in call for call in calls), "restore rejects partial database archives")
    check(any("restore-files run --rm recovery-loader" in call for call in calls), "snapshot and plugin volumes restore before API")
    check(calls[-1] == "up -d oms-api", "recovery API starts only after data validation", calls[-3:])
    check((config.backup_root / "latest-restore.json").is_file(), "restore writes an operator receipt")

    database_path = config.backup_root / manifest["files"]["database"]["name"]
    database_path.write_bytes(database_path.read_bytes() + b"tamper")
    before = len(fake.recovery_calls)
    try:
        driver.restore(config, fake)
        raise AssertionError("tampered archive was restored")
    except RuntimeError as error:
        check("checksum mismatch" in str(error), "tampering is rejected before restore", error)
    check(len(fake.recovery_calls) == before, "tampering cannot mutate recovery infrastructure")

    result = driver.cleanup(config, fake)
    check(result["removed_volumes"] is True, "cleanup reports volume removal")
    check(fake.recovery_calls[-1] == ("down", "-v", "--remove-orphans"), "cleanup removes isolated volumes")

print(f"Pilot PostgreSQL recovery driver verified: {passed} assertions passed.")

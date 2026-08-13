"""Persistent pilot supervisor paths do not depend on an interactive shell."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import pilot_window  # noqa: E402
from tier_b_evidence import current_head  # noqa: E402


ROOT = Path(__file__).resolve().parents[1]
passed = 0


def check(condition, label, payload=None):
    global passed
    assert condition, f"{label}: {payload}"
    passed += 1


original_root = pilot_window.EVIDENCE_ROOT
original_manifest = pilot_window.MANIFEST
original_custom_token = os.environ.get("PILOT_TEST_RECOVERY_TOKEN")
try:
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as directory:
        evidence = Path(directory) / "evidence"
        evidence.mkdir()
        manifest = evidence / "pilot-window.json"
        manifest.write_text(
            json.dumps({
                "token_env": "PILOT_TEST_RECOVERY_TOKEN",
                "target": "http://source.test:8000",
                "recovery_target": "http://recovery.test:8001",
                "migration_head_at_start": current_head(),
                "availability_writer": "observer",
                "recovery_driver": "manual",
            }),
            encoding="utf-8",
        )
        secret = Path(directory) / "pilot-recovery-token"
        expected_token = "pilot-supervisor-secret-abcdefghijklmnopqrstuvwxyz"
        secret.write_text(expected_token + "\n", encoding="utf-8")
        runtime_environment = Path(directory) / "pilot-runtime.env"
        runtime_environment.write_text(
            "# persistent recovery configuration\n"
            "PILOT_SOURCE_PROJECT=ontology-source\n"
            "PILOT_RECOVERY_PROJECT='ontology-recovery'\n",
            encoding="utf-8",
        )
        if os.name != "nt":
            secret.chmod(0o600)
            runtime_environment.chmod(0o600)

        pilot_window.configure_runtime(
            evidence_root=str(evidence),
            environment_file=str(runtime_environment),
            token_file=str(secret),
        )
        check(pilot_window.EVIDENCE_ROOT == evidence.resolve(),
              "explicit evidence root replaces the importing shell")
        check(pilot_window.MANIFEST == manifest.resolve(),
              "manifest follows the durable evidence root")
        check(os.environ["PILOT_TEST_RECOVERY_TOKEN"] == expected_token,
              "manifest-selected token environment is populated from the file")
        check(os.environ["PILOT_SOURCE_PROJECT"] == "ontology-source",
              "runtime environment survives the importing shell")
        check(os.environ["PILOT_RECOVERY_PROJECT"] == "ontology-recovery",
              "quoted runtime values are decoded")

        (evidence / "availability-probe-state.json").write_text(
            json.dumps({"next_scheduled_at": int(time.time()) + pilot_window.PROBE_INTERVAL_SECONDS}),
            encoding="utf-8",
        )
        import recovery_probe_client

        original_request = recovery_probe_client.json_request
        try:
            recovery_probe_client.json_request = lambda *_args, **_kwargs: (422, {})
            check(pilot_window.verify_runtime(object()) == 0,
                  "persisted runtime matches the open window")
            payload = json.loads(manifest.read_text(encoding="utf-8"))
            payload["migration_head_at_start"] = "older-head"
            manifest.write_text(json.dumps(payload), encoding="utf-8")
            check(pilot_window.verify_runtime(object()) == 1,
                  "persisted runtime rejects migration drift")
            payload["migration_head_at_start"] = current_head()
            manifest.write_text(json.dumps(payload), encoding="utf-8")
        finally:
            recovery_probe_client.json_request = original_request

        short = Path(directory) / "short-token"
        short.write_text("too-short", encoding="utf-8")
        if os.name != "nt":
            short.chmod(0o600)
        try:
            pilot_window.configure_runtime(token_file=str(short))
            raise AssertionError("short pilot token was accepted")
        except ValueError as error:
            check("at least 32" in str(error), "short token is rejected without echoing it", error)

        empty_root = Path(directory) / "empty"
        empty_root.mkdir()
        command = [
            sys.executable,
            str(ROOT / "oms" / "pilot_window.py"),
            "--evidence-root",
            str(empty_root),
            "status",
        ]
        result = subprocess.run(command, capture_output=True, text=True, check=False)
        check(result.returncode == 1, "CLI uses explicit empty evidence root", result)
        check("No window is open" in result.stdout, "CLI reports that selected root has no window")
finally:
    pilot_window.EVIDENCE_ROOT = original_root
    pilot_window.MANIFEST = original_manifest
    if original_custom_token is None:
        os.environ.pop("PILOT_TEST_RECOVERY_TOKEN", None)
    else:
        os.environ["PILOT_TEST_RECOVERY_TOKEN"] = original_custom_token


windows = (ROOT / "scripts" / "register-pilot-window.ps1").read_text(encoding="utf-8")
check("[string]$TokenFile" in windows, "Windows registration requires a token file")
check("[string]$EnvironmentFile" in windows, "Windows registration requires persistent runtime configuration")
check("--evidence-root" in windows and "--environment-file" in windows and "--token-file" in windows,
      "Windows startup action binds all durable inputs")
check("$env:PILOT_RECOVERY_TOKEN" not in windows,
      "Windows registration does not trust a temporary shell secret")
check("S-1-1-0" in windows and "S-1-5-11" in windows,
      "Windows registration rejects broadly readable token ACLs")
check("availability-probe-state.json" in windows and "observerAge" in windows,
      "Windows registration refuses a missing or stale observer")
check("verify-runtime" in windows, "Windows registration checks the persisted runtime before install")

systemd = (ROOT / "scripts" / "install-pilot-window-systemd.sh").read_text(encoding="utf-8")
check("EnvironmentFile=" in systemd, "systemd service imports persistent runtime configuration")
check("--evidence-root" in systemd and "--token-file" in systemd,
      "systemd service binds evidence and protected credential paths")
check("Restart=on-failure" in systemd and "RestartSec=180" in systemd,
      "systemd restarts outside the supervisor lock stale window")
check("runuser -u" in systemd, "installer proves the service account can read the token")
check("environment_mode" in systemd, "installer rejects a broadly readable runtime environment")
check("pilot-window.json" in systemd, "installer refuses to supervise an unopened window")
check("availability-probe-state.json" in systemd and "observer_age" in systemd,
      "systemd installer refuses a missing or stale observer")
check("docker info" in systemd, "systemd installer proves recovery-runtime access")
check("verify-runtime" in systemd, "systemd installer checks the persisted runtime before install")

print(f"Pilot supervisor deployment verified: {passed} assertions passed.")

"""Backup manifest and staged Postgres restore orchestration, including rollback chaos."""
import json
import os
import shutil
import subprocess
import tempfile
import uuid
from pathlib import Path

root = Path(__file__).resolve().parents[1]
rehearsal_source = (root / "scripts" / "rehearse-recovery.ps1").read_text(encoding="utf-8")
work = Path(tempfile.mkdtemp(prefix="ontology-recovery-scripts-"))
output_name = f".recovery-test-{uuid.uuid4().hex}"
output_dir = root / output_name
log_path = work / "docker-calls.jsonl"
passed = 0

assert "varchar(32)" in rehearsal_source and "0041_drop_redundant_pk_indexes" in rehearsal_source
passed += 1

fake = work / "fake_docker.py"
fake.write_text(
    """import json, os, pathlib, sys
args = sys.argv[1:]
with open(os.environ['FAKE_DOCKER_LOG'], 'a', encoding='utf-8') as handle:
    handle.write(json.dumps(args) + '\\n')
joined = ' '.join(args)
if 'config --services' in joined:
    print('oms-api\\noms-worker\\npostgres')
if 'pg_restore --list' in joined:
    print('; Archive created by pg_dump')
if ' cp ' in f' {joined} ':
    source, target = args[-2], args[-1]
    if source.startswith('postgres:'):
        pathlib.Path(target).write_bytes(b'portable fake postgres archive')
    if source.startswith('oms-api:'):
        pathlib.Path(target).write_bytes(b'portable fake dataset snapshot archive')
if os.environ.get('FAKE_DOCKER_FAIL_PROMOTE') == '1' and 'ALTER DATABASE' in joined and '_restore_' in joined and 'RENAME TO' in joined:
    sys.exit(71)
sys.exit(0)
""",
    encoding="utf-8",
)
(work / "docker.cmd").write_text(f'@echo off\r\n"{os.sys.executable}" "{fake}" %*\r\n', encoding="ascii")

env = os.environ.copy()
env["PATH"] = f"{work}{os.pathsep}{env['PATH']}"
env["FAKE_DOCKER_LOG"] = str(log_path)


def run_ps(script: str, *args: str, fail: bool = False, extra_env=None):
    global passed
    command = ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(root / "scripts" / script), *args]
    result = subprocess.run(command, cwd=root, env={**env, **(extra_env or {})}, text=True, capture_output=True, timeout=60)
    assert (result.returncode != 0) if fail else (result.returncode == 0), f"{script}: {result.returncode}\n{result.stdout}\n{result.stderr}"
    passed += 1
    return result


try:
    backup = run_ps("backup.ps1", "-OutputDirectory", output_name, "-DatabaseUser", "ontology", "-DatabaseName", "ontology", "-IncludeSnapshots", "-IncludePlugins")
    dumps = list(output_dir.glob("*.dump"))
    assert len(dumps) == 1, (backup.stdout, list(output_dir.iterdir()))
    dump = dumps[0]
    checksum = Path(f"{dump}.sha256")
    manifest_path = Path(f"{dump}.json")
    assert checksum.exists() and manifest_path.exists()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    assert manifest["format"] == "postgres-custom" and manifest["size_bytes"] == dump.stat().st_size
    assert manifest["sha256"] in checksum.read_text(encoding="ascii")
    snapshot_archive = Path(f"{dump}.snapshots.tar.gz")
    assert snapshot_archive.exists() and Path(f"{snapshot_archive}.sha256").exists()
    assert manifest["snapshot_archive"] == snapshot_archive.name and manifest["snapshot_sha256"]
    plugin_archive = Path(f"{dump}.plugins.tar.gz")
    assert plugin_archive.exists() and Path(f"{plugin_archive}.sha256").exists()
    assert manifest["plugin_archive"] == plugin_archive.name and manifest["plugin_sha256"]
    passed += 8

    run_ps(
        "restore.ps1", "-BackupPath", str(dump), "-ConfirmRestore", "-KeepPreviousDatabase",
        "-DatabaseUser", "ontology", "-DatabaseName", "ontology", "-RestoreSnapshots", "-RestorePlugins",
    )
    calls = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()]
    joined = [" ".join(call) for call in calls]
    assert any("pg_restore --list" in call for call in joined)
    assert any("CREATE DATABASE" in call and "_restore_" in call for call in joined)
    assert any("SELECT version_num FROM alembic_version" in call for call in joined)
    assert any("stop oms-api oms-worker" in call for call in joined)
    assert any("ALTER DATABASE" in call and "_previous_" in call for call in joined)
    assert any("start oms-api oms-worker" in call for call in joined)
    assert any("tar -xzf" in call and "/var/lib/ontology/snapshots" in call for call in joined)
    assert any("tar -xzf" in call and "/var/lib/ontology/plugins" in call for call in joined)
    passed += 8

    before_failure = len(calls)
    run_ps(
        "restore.ps1", "-BackupPath", str(dump), "-ConfirmRestore", "-KeepPreviousDatabase",
        "-DatabaseUser", "ontology", "-DatabaseName", "ontology", fail=True,
        extra_env={"FAKE_DOCKER_FAIL_PROMOTE": "1"},
    )
    failed_calls = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()][before_failure:]
    failed_joined = [" ".join(call) for call in failed_calls]
    assert any("_restore_" in call and "RENAME TO" in call for call in failed_joined)
    assert any("_previous_" in call and "RENAME TO" in call and "ontology" in call for call in failed_joined)
    assert any("start oms-api oms-worker" in call for call in failed_joined)
    passed += 3
finally:
    shutil.rmtree(output_dir, ignore_errors=True)
    shutil.rmtree(work, ignore_errors=True)

print(f"Recovery scripts and rollback chaos verified: {passed} assertions passed.")

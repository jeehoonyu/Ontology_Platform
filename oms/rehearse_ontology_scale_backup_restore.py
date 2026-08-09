"""Create and restore a physical PostgreSQL backup of the ontology scale fixture."""

from __future__ import annotations

import json
import os
import platform
import sys
import re
import subprocess
import time
import atexit
from pathlib import Path

from sqlalchemy import create_engine, text


SOURCE_URL = os.environ.get("DATABASE_URL", "")
TARGET_URL = os.environ.get("ONTOLOGY_BACKUP_TARGET_DATABASE_URL", "")
if not SOURCE_URL.startswith("postgresql") or not TARGET_URL.startswith("postgresql"):
    raise SystemExit("Source and target PostgreSQL database URLs are required")

SOURCE_CONTAINER = os.environ.get("ONTOLOGY_BACKUP_SOURCE_CONTAINER", "ontology_scale_reference")
TARGET_CONTAINER = os.environ.get("ONTOLOGY_BACKUP_TARGET_CONTAINER", "ontology_scale_restore_reference")
TARGET_VOLUME = os.environ.get("ONTOLOGY_BACKUP_TARGET_VOLUME", "ontology_scale_restore_pgdata")
TARGET_PORT = int(os.environ.get("ONTOLOGY_BACKUP_TARGET_PORT", "55433"))
POSTGRES_USER = os.environ.get("ONTOLOGY_BACKUP_POSTGRES_USER", "ontology")
POSTGRES_PASSWORD = os.environ.get("ONTOLOGY_BACKUP_POSTGRES_PASSWORD", "")
POSTGRES_DB = os.environ.get("ONTOLOGY_BACKUP_POSTGRES_DB", "ontology")
POSTGRES_IMAGE = os.environ.get("ONTOLOGY_BACKUP_POSTGRES_IMAGE", "").strip()
RESET_TARGET = os.environ.get("ONTOLOGY_BACKUP_RESET_TARGET", "").lower() in {"1", "true", "yes"}
OBJECTS = int(os.environ.get("ONTOLOGY_BACKUP_OBJECTS", "10000000"))
LINKS = int(os.environ.get("ONTOLOGY_BACKUP_LINKS", "50000000"))
RTO_LIMIT_SECONDS = float(os.environ.get("ONTOLOGY_BACKUP_RTO_LIMIT_SECONDS", "1800"))
EVIDENCE_PATH = os.environ.get("ONTOLOGY_BACKUP_EVIDENCE_PATH")

for value in (SOURCE_CONTAINER, TARGET_CONTAINER, TARGET_VOLUME, POSTGRES_USER, POSTGRES_DB):
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", value):
        raise SystemExit(f"Unsafe Docker or PostgreSQL identifier: {value}")
if not TARGET_CONTAINER.startswith("ontology_scale_restore_"):
    raise SystemExit("Target container must use the ontology_scale_restore_ prefix")
if not TARGET_VOLUME.startswith("ontology_scale_restore_"):
    raise SystemExit("Target volume must use the ontology_scale_restore_ prefix")
if not POSTGRES_PASSWORD:
    raise SystemExit("ONTOLOGY_BACKUP_POSTGRES_PASSWORD is required")


def docker(*args: str, timeout: float | None = None, check: bool = True) -> subprocess.CompletedProcess:
    result = subprocess.run(
        ["docker", *args], capture_output=True, text=True, timeout=timeout, check=False,
    )
    if check and result.returncode != 0:
        raise AssertionError({"docker_args": args, "stdout": result.stdout, "stderr": result.stderr})
    return result


if not POSTGRES_IMAGE:
    # A physical backup can only start on the same PostgreSQL major version.
    # Reusing the source image digest also preserves extensions such as PostGIS.
    POSTGRES_IMAGE = docker(
        "inspect", "--format", "{{.Image}}", SOURCE_CONTAINER,
    ).stdout.strip()
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", POSTGRES_IMAGE):
        raise SystemExit("Could not derive a pinned PostgreSQL image from the source container")


def exists(kind: str, name: str) -> bool:
    return docker(kind, "inspect", name, check=False).returncode == 0


def cleanup_target() -> None:
    if exists("container", TARGET_CONTAINER):
        docker("stop", TARGET_CONTAINER, check=False)


atexit.register(cleanup_target)


def state(engine):
    with engine.connect() as connection:
        row = connection.execute(text("""
            SELECT
              (SELECT count(*) FROM object_instances
                WHERE project_id='default' AND object_type_id='scale_benchmark_asset') AS objects,
              (SELECT count(*) FROM link_instances
                WHERE project_id='default' AND link_type_id='scale_benchmark_related') AS links,
              (SELECT count(*) FROM object_change_events
                WHERE source_type='ontology_mixed_workload') AS mixed_events,
              (SELECT version_num FROM alembic_version LIMIT 1) AS migration
        """)).mappings().one()
        plan = connection.execute(text("""
            EXPLAIN (FORMAT JSON)
            SELECT id FROM object_instances
             WHERE project_id='default' AND object_type_id='scale_benchmark_asset'
               AND CASE WHEN jsonb_typeof(properties -> 'risk') = 'number'
                        THEN CAST(properties ->> 'risk' AS double precision) END >= 95
             ORDER BY CASE WHEN jsonb_typeof(properties -> 'risk') = 'number'
                           THEN CAST(properties ->> 'risk' AS double precision) END DESC, id DESC
             LIMIT 100
        """)).scalar_one()
    return {**dict(row), "indexed_plan": "ix_oi_property_" in json.dumps(plan)}


source_engine = create_engine(SOURCE_URL, pool_pre_ping=True)
source_state = state(source_engine)
assert int(source_state["objects"]) == OBJECTS, source_state
assert int(source_state["links"]) == LINKS, source_state
assert source_state["indexed_plan"], source_state

if exists("container", TARGET_CONTAINER):
    if not RESET_TARGET:
        raise SystemExit(f"Target container already exists: {TARGET_CONTAINER}")
    docker("rm", "-f", TARGET_CONTAINER)
if exists("volume", TARGET_VOLUME):
    if not RESET_TARGET:
        raise SystemExit(f"Target volume already exists: {TARGET_VOLUME}")
    docker("volume", "rm", TARGET_VOLUME)
docker("volume", "create", TARGET_VOLUME)
docker(
    "run", "--rm", "--user", "0", "-v", f"{TARGET_VOLUME}:/backup",
    POSTGRES_IMAGE, "sh", "-c", "chown -R postgres:postgres /backup",
)

backup_started = time.perf_counter()
backup = docker(
    "run", "--rm", "--user", "postgres",
    "--network", f"container:{SOURCE_CONTAINER}",
    "-e", f"PGPASSWORD={POSTGRES_PASSWORD}",
    "-v", f"{TARGET_VOLUME}:/backup",
    POSTGRES_IMAGE,
    "pg_basebackup", "-h", "127.0.0.1", "-p", "5432",
    "-U", POSTGRES_USER, "-D", "/backup", "-Fp", "-Xs", "-c", "fast", "-P",
    timeout=RTO_LIMIT_SECONDS * 2,
)
backup_seconds = time.perf_counter() - backup_started
assert "100%" in backup.stderr or "100%" in backup.stdout, {
    "stdout_tail": backup.stdout[-1000:], "stderr_tail": backup.stderr[-1000:]
}

restore_started = time.perf_counter()
docker(
    "run", "-d", "--name", TARGET_CONTAINER,
    "-e", f"POSTGRES_USER={POSTGRES_USER}",
    "-e", f"POSTGRES_PASSWORD={POSTGRES_PASSWORD}",
    "-e", f"POSTGRES_DB={POSTGRES_DB}",
    "-p", f"127.0.0.1:{TARGET_PORT}:5432",
    "-v", f"{TARGET_VOLUME}:/var/lib/postgresql/data",
    "--health-cmd", f"pg_isready -U {POSTGRES_USER} -d {POSTGRES_DB}",
    "--health-interval", "2s", "--health-timeout", "5s", "--health-retries", "300",
    POSTGRES_IMAGE,
    "-c", "shared_buffers=1GB", "-c", "effective_cache_size=3GB",
)

target_engine = create_engine(TARGET_URL, pool_pre_ping=True)
deadline = time.monotonic() + RTO_LIMIT_SECONDS
last_error = None
while time.monotonic() < deadline:
    try:
        with target_engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        break
    except Exception as exc:
        last_error = repr(exc)
        target_engine.dispose()
        time.sleep(0.25)
else:
    raise AssertionError({"restore_readiness_timeout": last_error})
restore_seconds = time.perf_counter() - restore_started

target_state = state(target_engine)
assert target_state == source_state, {"source": source_state, "target": target_state}
assert restore_seconds < RTO_LIMIT_SECONDS, restore_seconds

volume_bytes = int(docker(
    "run", "--rm", "-v", f"{TARGET_VOLUME}:/data", "alpine",
    "sh", "-c", "du -sb /data | cut -f1",
).stdout.strip())

evidence = {
    "status": "PASS",
    "backup_method": "pg_basebackup_physical_stream",
    "postgres_image": POSTGRES_IMAGE,
    "backup_seconds": round(backup_seconds, 3),
    "restore_readiness_seconds": round(restore_seconds, 3),
    "rto_limit_seconds": RTO_LIMIT_SECONDS,
    "source_container": SOURCE_CONTAINER,
    "target_container": TARGET_CONTAINER,
    "target_volume": TARGET_VOLUME,
    "target_volume_bytes": volume_bytes,
    "source_state": source_state,
    "target_state": target_state,
    "fresh_volume": True,
    "rpo_semantics": "consistent physical snapshot at pg_basebackup completion",
    "host": {
        "platform": platform.platform(),
        "python": platform.python_version(),
        "processor": platform.processor(),
    },
}
serialized = json.dumps(evidence, indent=2, sort_keys=True)
if EVIDENCE_PATH:
    Path(EVIDENCE_PATH).write_text(serialized + "\n", encoding="utf-8")
# Record into the durability journal. Until 2026-08-08 this rehearsal printed
# its numbers and the gate evidence was assembled by hand from them, which is
# how a gate came to be counted as passing without any code ever producing it.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from durability_rehearsals import record  # noqa: E402

record("backup_restore", {
    "fresh_volume_restores": 1 if evidence.get("fresh_volume") else 0,
    "restore_readiness_seconds": evidence["restore_readiness_seconds"],
    "backup_seconds": evidence["backup_seconds"],
    "restore_state_mismatches": 0 if evidence["source_state"] == evidence["target_state"] else 1,
}, harness="oms/rehearse_ontology_scale_backup_restore.py")

print("PostgreSQL ontology scale backup/restore rehearsal passed:")
print(serialized)
print("Recorded a backup/restore durability rehearsal.")
source_engine.dispose()
target_engine.dispose()
docker("stop", TARGET_CONTAINER)

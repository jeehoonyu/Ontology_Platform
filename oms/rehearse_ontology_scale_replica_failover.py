"""Measure streaming-replica lag and failover on the strict ontology fixture."""

from __future__ import annotations

import json
import os
import platform
import sys
import re
import subprocess
import time
import uuid
import atexit
from pathlib import Path

from sqlalchemy import create_engine, text


SOURCE_URL = os.environ.get("DATABASE_URL", "")
REPLICA_URL = os.environ.get("ONTOLOGY_REPLICA_DATABASE_URL", "")
if not SOURCE_URL.startswith("postgresql") or not REPLICA_URL.startswith("postgresql"):
    raise SystemExit("Source and replica PostgreSQL database URLs are required")

SOURCE_CONTAINER = os.environ.get("ONTOLOGY_REPLICA_SOURCE_CONTAINER", "ontology_scale_reference")
REPLICA_CONTAINER = os.environ.get("ONTOLOGY_REPLICA_CONTAINER", "ontology_scale_replica_reference")
REPLICA_VOLUME = os.environ.get("ONTOLOGY_REPLICA_VOLUME", "ontology_scale_replica_pgdata")
NETWORK = os.environ.get("ONTOLOGY_REPLICA_NETWORK", "ontology_scale_replication")
REPLICA_PORT = int(os.environ.get("ONTOLOGY_REPLICA_PORT", "55434"))
POSTGRES_USER = os.environ.get("ONTOLOGY_REPLICA_POSTGRES_USER", "ontology")
POSTGRES_PASSWORD = os.environ.get("ONTOLOGY_REPLICA_POSTGRES_PASSWORD", "")
POSTGRES_DB = os.environ.get("ONTOLOGY_REPLICA_POSTGRES_DB", "ontology")
POSTGRES_IMAGE = os.environ.get("ONTOLOGY_REPLICA_POSTGRES_IMAGE", "").strip()
RESET_TARGET = os.environ.get("ONTOLOGY_REPLICA_RESET_TARGET", "").lower() in {"1", "true", "yes"}
OBJECTS = int(os.environ.get("ONTOLOGY_REPLICA_OBJECTS", "10000000"))
LINKS = int(os.environ.get("ONTOLOGY_REPLICA_LINKS", "50000000"))
RPO_LIMIT_SECONDS = float(os.environ.get("ONTOLOGY_REPLICA_RPO_LIMIT_SECONDS", "300"))
RTO_LIMIT_SECONDS = float(os.environ.get("ONTOLOGY_REPLICA_RTO_LIMIT_SECONDS", "1800"))
EVIDENCE_PATH = os.environ.get("ONTOLOGY_REPLICA_EVIDENCE_PATH")

for value in (
    SOURCE_CONTAINER, REPLICA_CONTAINER, REPLICA_VOLUME, NETWORK,
    POSTGRES_USER, POSTGRES_DB,
):
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", value):
        raise SystemExit(f"Unsafe Docker or PostgreSQL identifier: {value}")
if not REPLICA_CONTAINER.startswith("ontology_scale_replica_"):
    raise SystemExit("Replica container must use the ontology_scale_replica_ prefix")
if not REPLICA_VOLUME.startswith("ontology_scale_replica_"):
    raise SystemExit("Replica volume must use the ontology_scale_replica_ prefix")
if not POSTGRES_PASSWORD:
    raise SystemExit("ONTOLOGY_REPLICA_POSTGRES_PASSWORD is required")


def docker(*args: str, timeout: float | None = None, check: bool = True) -> subprocess.CompletedProcess:
    result = subprocess.run(
        ["docker", *args], capture_output=True, text=True, timeout=timeout, check=False,
    )
    if check and result.returncode != 0:
        raise AssertionError({"docker_args": args, "stdout": result.stdout, "stderr": result.stderr})
    return result


if not POSTGRES_IMAGE:
    # Physical streaming replication requires an identical PostgreSQL major.
    # The source digest also carries any required extension binaries.
    POSTGRES_IMAGE = docker(
        "inspect", "--format", "{{.Image}}", SOURCE_CONTAINER,
    ).stdout.strip()
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", POSTGRES_IMAGE):
        raise SystemExit("Could not derive a pinned PostgreSQL image from the source container")


def exists(kind: str, name: str) -> bool:
    return docker(kind, "inspect", name, check=False).returncode == 0


def cleanup_containers() -> None:
    if exists("container", REPLICA_CONTAINER):
        docker("stop", REPLICA_CONTAINER, check=False)
    if exists("container", SOURCE_CONTAINER):
        docker("start", SOURCE_CONTAINER, check=False)


atexit.register(cleanup_containers)


def fixture_state(engine):
    with engine.connect() as connection:
        return dict(connection.execute(text("""
            SELECT
              (SELECT count(*) FROM object_instances
                WHERE project_id='default' AND object_type_id='scale_benchmark_asset') AS objects,
              (SELECT count(*) FROM link_instances
                WHERE project_id='default' AND link_type_id='scale_benchmark_related') AS links,
              (SELECT count(*) FROM object_change_events
                WHERE source_type='ontology_mixed_workload') AS mixed_events,
              (SELECT version_num FROM alembic_version LIMIT 1) AS migration
        """)).mappings().one())


source_engine = create_engine(SOURCE_URL, pool_pre_ping=True)
source_state = fixture_state(source_engine)
assert int(source_state["objects"]) == OBJECTS, source_state
assert int(source_state["links"]) == LINKS, source_state

if not exists("network", NETWORK):
    docker("network", "create", NETWORK)
connected = docker("network", "connect", NETWORK, SOURCE_CONTAINER, check=False)
if connected.returncode != 0 and "already exists" not in connected.stderr.lower():
    raise AssertionError(connected.stderr)
network_cidr = docker(
    "network", "inspect", NETWORK,
    "--format", "{{(index .IPAM.Config 0).Subnet}}",
).stdout.strip()
if not re.fullmatch(r"[0-9a-fA-F:.]+/[0-9]{1,3}", network_cidr):
    raise AssertionError({"invalid_replication_network_cidr": network_cidr})
replication_hba = f"host replication {POSTGRES_USER} {network_cidr} scram-sha-256"
docker(
    "exec", "--user", "postgres", SOURCE_CONTAINER, "sh", "-c",
    f"grep -Fqx '{replication_hba}' \"$PGDATA/pg_hba.conf\" || "
    f"printf '%s\\n' '{replication_hba}' >> \"$PGDATA/pg_hba.conf\"",
)
docker(
    "exec", SOURCE_CONTAINER, "psql", "-v", "ON_ERROR_STOP=1",
    "-U", POSTGRES_USER, "-d", POSTGRES_DB,
    "-c", "SELECT pg_reload_conf();",
)

if exists("container", REPLICA_CONTAINER):
    if not RESET_TARGET:
        raise SystemExit(f"Replica container already exists: {REPLICA_CONTAINER}")
    docker("rm", "-f", REPLICA_CONTAINER)
if exists("volume", REPLICA_VOLUME):
    if not RESET_TARGET:
        raise SystemExit(f"Replica volume already exists: {REPLICA_VOLUME}")
    docker("volume", "rm", REPLICA_VOLUME)
docker("volume", "create", REPLICA_VOLUME)
docker(
    "run", "--rm", "--user", "0", "-v", f"{REPLICA_VOLUME}:/replica",
    POSTGRES_IMAGE, "sh", "-c", "chown -R postgres:postgres /replica",
)

basebackup_started = time.perf_counter()
connection_string = (
    f"host={SOURCE_CONTAINER} port=5432 user={POSTGRES_USER} "
    f"password={POSTGRES_PASSWORD} dbname={POSTGRES_DB}"
)
basebackup = docker(
    "run", "--rm", "--user", "postgres", "--network", NETWORK,
    "-v", f"{REPLICA_VOLUME}:/replica", POSTGRES_IMAGE,
    "pg_basebackup", "-d", connection_string, "-D", "/replica",
    "-Fp", "-Xs", "-c", "fast", "-R", "-P",
    timeout=RTO_LIMIT_SECONDS * 2,
)
basebackup_seconds = time.perf_counter() - basebackup_started
assert "100%" in basebackup.stderr or "100%" in basebackup.stdout

docker(
    "run", "-d", "--name", REPLICA_CONTAINER, "--network", NETWORK,
    "-e", f"POSTGRES_USER={POSTGRES_USER}",
    "-e", f"POSTGRES_PASSWORD={POSTGRES_PASSWORD}",
    "-e", f"POSTGRES_DB={POSTGRES_DB}",
    "-p", f"127.0.0.1:{REPLICA_PORT}:5432",
    "-v", f"{REPLICA_VOLUME}:/var/lib/postgresql/data",
    "--health-cmd", f"pg_isready -U {POSTGRES_USER} -d {POSTGRES_DB}",
    "--health-interval", "1s", "--health-timeout", "5s", "--health-retries", "300",
    POSTGRES_IMAGE, "-c", "hot_standby=on", "-c", "shared_buffers=1GB",
)

replica_engine = create_engine(REPLICA_URL, pool_pre_ping=True)
deadline = time.monotonic() + RTO_LIMIT_SECONDS
last_error = None
while time.monotonic() < deadline:
    try:
        with replica_engine.connect() as connection:
            assert connection.execute(text("SELECT pg_is_in_recovery()" )).scalar_one() is True
        break
    except Exception as exc:
        last_error = repr(exc)
        replica_engine.dispose()
        time.sleep(0.25)
else:
    raise AssertionError({"replica_readiness_timeout": last_error})

probe_id = f"replica_probe_{uuid.uuid4().hex}"
object_id = "scale_object_00000001"
with source_engine.begin() as connection:
    row = connection.execute(text("""
        SELECT properties,
               COALESCE((SELECT max(object_version) FROM object_change_events
                          WHERE project_id='default' AND object_id=:object_id), 0) + 1 AS next_version
          FROM object_instances
         WHERE project_id='default' AND object_type_id='scale_benchmark_asset' AND id=:object_id
         FOR UPDATE
    """), {"object_id": object_id}).mappings().one()
    before = dict(row["properties"] or {})
    after = dict(before)
    after["risk"] = (int(before.get("risk", 0)) + 7) % 101
    now = int(time.time())
    connection.execute(text("""
        UPDATE object_instances SET properties=CAST(:properties AS jsonb), updated_at=:now
         WHERE project_id='default' AND id=:object_id
    """), {"properties": json.dumps(after), "now": now, "object_id": object_id})
    connection.execute(text("""
        INSERT INTO object_change_events (
          id, project_id, object_type_id, object_id, object_version, event_type,
          actor, source_type, source_id, before_state, after_state, changed_fields,
          evidence, ontology_revision_id, valid_from, valid_to, transaction_time
        ) VALUES (
          :id, 'default', 'scale_benchmark_asset', :object_id, :version,
          'ontology.object.replication_probe', 'recovery-rehearsal',
          'ontology_replication_rehearsal', :id, CAST(:before AS jsonb), CAST(:after AS jsonb),
          CAST('["risk"]' AS json), CAST('{}' AS json), NULL, :now, NULL, :now
        )
    """), {
        "id": probe_id, "object_id": object_id, "version": int(row["next_version"]),
        "before": json.dumps(before), "after": json.dumps(after), "now": now,
    })
with source_engine.connect() as connection:
    committed_lsn = connection.execute(text("SELECT pg_current_wal_lsn()::text")).scalar_one()

replay_started = time.perf_counter()
deadline = time.monotonic() + RPO_LIMIT_SECONDS
last_replay_lsn = None
while time.monotonic() < deadline:
    with replica_engine.connect() as connection:
        replay = connection.execute(text("""
            SELECT pg_last_wal_replay_lsn()::text AS replay_lsn,
                   EXISTS(SELECT 1 FROM object_change_events WHERE id=:probe_id) AS event_visible,
                   (SELECT properties ->> 'risk' FROM object_instances WHERE id=:object_id) AS risk
        """), {"probe_id": probe_id, "object_id": object_id}).mappings().one()
    last_replay_lsn = replay["replay_lsn"]
    if replay["event_visible"] and int(replay["risk"]) == int(after["risk"]):
        break
    time.sleep(0.05)
else:
    raise AssertionError({"replication_timeout": RPO_LIMIT_SECONDS, "last_replay_lsn": last_replay_lsn})
replay_seconds = time.perf_counter() - replay_started

source_engine.dispose()
failover_started = time.perf_counter()
docker("stop", "--time", "10", SOURCE_CONTAINER)
with replica_engine.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
    promoted = connection.execute(text("SELECT pg_promote(true, 60)" )).scalar_one()
assert promoted is True

deadline = time.monotonic() + RTO_LIMIT_SECONDS
while time.monotonic() < deadline:
    try:
        replica_engine.dispose()
        replica_engine = create_engine(REPLICA_URL, pool_pre_ping=True)
        with replica_engine.connect() as connection:
            in_recovery = connection.execute(text("SELECT pg_is_in_recovery()" )).scalar_one()
            probe_visible = connection.execute(text(
                "SELECT EXISTS(SELECT 1 FROM object_change_events WHERE id=:probe_id)"
            ), {"probe_id": probe_id}).scalar_one()
        if not in_recovery and probe_visible:
            break
    except Exception:
        pass
    time.sleep(0.1)
else:
    raise AssertionError("Promoted replica did not become writable before the RTO limit")
failover_seconds = time.perf_counter() - failover_started

promoted_state = fixture_state(replica_engine)
assert promoted_state == source_state, {"source": source_state, "promoted": promoted_state}
assert replay_seconds < RPO_LIMIT_SECONDS
assert failover_seconds < RTO_LIMIT_SECONDS

evidence = {
    "status": "PASS",
    "replication_mode": "postgresql_physical_streaming",
    "postgres_image": POSTGRES_IMAGE,
    "replication_network_cidr": network_cidr,
    "basebackup_seconds": round(basebackup_seconds, 3),
    "committed_lsn": committed_lsn,
    "replayed_lsn": last_replay_lsn,
    "committed_probe_id": probe_id,
    "replication_replay_seconds": round(replay_seconds, 3),
    "rpo_limit_seconds": RPO_LIMIT_SECONDS,
    "committed_probe_preserved": True,
    "failover_promotion_seconds": round(failover_seconds, 3),
    "rto_limit_seconds": RTO_LIMIT_SECONDS,
    "promoted_out_of_recovery": True,
    "source_state": source_state,
    "promoted_state": promoted_state,
    "host": {
        "platform": platform.platform(),
        "python": platform.python_version(),
        "processor": platform.processor(),
    },
}
serialized = json.dumps(evidence, indent=2, sort_keys=True)
if EVIDENCE_PATH:
    Path(EVIDENCE_PATH).write_text(serialized + "\n", encoding="utf-8")
sys.path.insert(0, str(Path(__file__).resolve().parent))
from durability_rehearsals import record  # noqa: E402

record("replica_failover", {
    "promotions_out_of_recovery": 1 if evidence.get("promoted_out_of_recovery") else 0,
    "failover_promotion_seconds": evidence["failover_promotion_seconds"],
    "failover_state_mismatches": 0 if evidence["source_state"] == evidence["promoted_state"] else 1,
    # The gate's subject: a record committed before the failover must survive it.
    "committed_probe_lost": 0 if evidence.get("committed_probe_preserved") else 1,
    "committed_lsn": evidence.get("committed_lsn"),
    "replayed_lsn": evidence.get("replayed_lsn"),
}, harness="oms/rehearse_ontology_scale_replica_failover.py",
   observed_head=str(source_state["migration"]))

print("PostgreSQL ontology scale replica failover rehearsal passed:")
print(serialized)
print("Recorded a replica failover durability rehearsal.")
replica_engine.dispose()
docker("stop", REPLICA_CONTAINER)
docker("start", SOURCE_CONTAINER)

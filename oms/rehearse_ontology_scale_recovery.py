"""Rehearse vacuum maintenance and PostgreSQL process restart at ontology scale."""

from __future__ import annotations

import json
import os
import platform
import subprocess
import time
from pathlib import Path

from sqlalchemy import create_engine, text


DATABASE_URL = os.environ.get("DATABASE_URL", "")
if not DATABASE_URL.startswith("postgresql"):
    raise SystemExit("rehearse_ontology_scale_recovery.py requires PostgreSQL")

CONTAINER = os.environ.get("ONTOLOGY_RECOVERY_CONTAINER", "").strip()
if not CONTAINER:
    raise SystemExit("ONTOLOGY_RECOVERY_CONTAINER is required")

OBJECTS = int(os.environ.get("ONTOLOGY_RECOVERY_OBJECTS", "10000000"))
LINKS = int(os.environ.get("ONTOLOGY_RECOVERY_LINKS", "50000000"))
MIN_EVENTS = int(os.environ.get("ONTOLOGY_RECOVERY_MIN_EVENTS", "100000"))
RTO_LIMIT_SECONDS = float(os.environ.get("ONTOLOGY_RECOVERY_RTO_LIMIT_SECONDS", "1800"))
EVIDENCE_PATH = os.environ.get("ONTOLOGY_RECOVERY_EVIDENCE_PATH")

OBJECT_TYPE_ID = "scale_benchmark_asset"
LINK_TYPE_ID = "scale_benchmark_related"
engine = create_engine(DATABASE_URL, pool_pre_ping=True)


def fixture_state(connection):
    return dict(connection.execute(text("""
        SELECT
          (SELECT count(*) FROM object_instances
            WHERE project_id = 'default' AND object_type_id = :object_type_id) AS objects,
          (SELECT count(*) FROM link_instances
            WHERE project_id = 'default' AND link_type_id = :link_type_id) AS links,
          (SELECT count(*) FROM object_change_events
            WHERE source_type = 'ontology_mixed_workload') AS mixed_events
    """), {"object_type_id": OBJECT_TYPE_ID, "link_type_id": LINK_TYPE_ID}).mappings().one())


def maintenance_state(connection):
    return [dict(row) for row in connection.execute(text("""
        SELECT relname, n_live_tup, n_dead_tup, vacuum_count, autovacuum_count,
               analyze_count, autoanalyze_count, last_vacuum, last_autovacuum
          FROM pg_stat_user_tables
         WHERE relname IN ('object_instances', 'object_change_events')
         ORDER BY relname
    """)).mappings().all()]


with engine.connect() as connection:
    before = fixture_state(connection)
    maintenance_before = maintenance_state(connection)
    latest_run = connection.execute(text("""
        SELECT source_id, count(*) AS events
          FROM object_change_events
         WHERE source_type = 'ontology_mixed_workload'
         GROUP BY source_id
         ORDER BY max(transaction_time) DESC, source_id DESC
         LIMIT 1
    """)).mappings().one()

assert int(before["objects"]) == OBJECTS, before
assert int(before["links"]) == LINKS, before
assert int(latest_run["events"]) >= MIN_EVENTS, dict(latest_run)

vacuum_started = time.perf_counter()
with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
    connection.execute(text("SET maintenance_work_mem = '64MB'"))
    connection.execute(text("SET max_parallel_maintenance_workers = 0"))
    connection.execute(text("VACUUM (ANALYZE) object_instances"))
    connection.execute(text("VACUUM (ANALYZE) object_change_events"))
vacuum_seconds = time.perf_counter() - vacuum_started

with engine.connect() as connection:
    maintenance_after = maintenance_state(connection)

engine.dispose()
restart_started = time.perf_counter()
restart = subprocess.run(
    ["docker", "restart", "--time", "30", CONTAINER],
    capture_output=True,
    text=True,
    timeout=int(RTO_LIMIT_SECONDS),
    check=False,
)
assert restart.returncode == 0, {"stdout": restart.stdout, "stderr": restart.stderr}

deadline = time.monotonic() + RTO_LIMIT_SECONDS
last_error = None
while time.monotonic() < deadline:
    try:
        engine = create_engine(DATABASE_URL, pool_pre_ping=True)
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        break
    except Exception as exc:  # database process may still be replaying WAL
        last_error = repr(exc)
        engine.dispose()
        time.sleep(0.25)
else:
    raise AssertionError({"database_restart_timeout": last_error})
recovery_seconds = time.perf_counter() - restart_started

with engine.connect() as connection:
    after = fixture_state(connection)
    recovered_run_events = int(connection.execute(text("""
        SELECT count(*) FROM object_change_events
         WHERE source_type = 'ontology_mixed_workload' AND source_id = :run_id
    """), {"run_id": latest_run["source_id"]}).scalar_one())
    plan = connection.execute(text("""
        EXPLAIN (FORMAT JSON)
        SELECT id FROM object_instances
         WHERE project_id = 'default' AND object_type_id = :object_type_id
           AND CASE WHEN jsonb_typeof(properties -> 'risk') = 'number'
                    THEN CAST(properties ->> 'risk' AS double precision) END >= 95
         ORDER BY CASE WHEN jsonb_typeof(properties -> 'risk') = 'number'
                       THEN CAST(properties ->> 'risk' AS double precision) END DESC, id DESC
         LIMIT 100
    """), {"object_type_id": OBJECT_TYPE_ID}).scalar_one()

assert after == before, {"before": before, "after": after}
assert recovered_run_events == int(latest_run["events"])
assert "ix_oi_property_" in json.dumps(plan), plan
assert recovery_seconds < RTO_LIMIT_SECONDS, recovery_seconds

evidence = {
    "status": "PASS",
    "objects": int(after["objects"]),
    "links": int(after["links"]),
    "mixed_events": int(after["mixed_events"]),
    "verified_run_id": latest_run["source_id"],
    "verified_run_events": recovered_run_events,
    "vacuum_analyze_seconds": round(vacuum_seconds, 3),
    "database_restart_recovery_seconds": round(recovery_seconds, 3),
    "rto_limit_seconds": RTO_LIMIT_SECONDS,
    "indexed_plan_after_restart": True,
    "fixture_state_preserved": True,
    "maintenance_before": maintenance_before,
    "maintenance_after": maintenance_after,
    "host": {
        "platform": platform.platform(),
        "python": platform.python_version(),
        "processor": platform.processor(),
    },
}
serialized = json.dumps(evidence, indent=2, sort_keys=True, default=str)
if EVIDENCE_PATH:
    Path(EVIDENCE_PATH).write_text(serialized + "\n", encoding="utf-8")
print("PostgreSQL ontology scale recovery rehearsal passed:")
print(serialized)
engine.dispose()

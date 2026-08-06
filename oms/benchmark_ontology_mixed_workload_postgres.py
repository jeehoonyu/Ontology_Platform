"""Benchmark concurrent ontology reads, mutations, temporal events, and recovery.

The smoke profile runs after the ontology scale fixture in PostgreSQL CI. The
reference profile intentionally requires the previously seeded 10M object / 50M
link fixture so a small database cannot be reported as production-scale proof.
"""

from __future__ import annotations

import json
import math
import os
import platform
import statistics
import threading
import time
import uuid
from pathlib import Path


if not os.environ.get("DATABASE_URL", "").startswith("postgresql"):
    raise SystemExit("benchmark_ontology_mixed_workload_postgres.py requires PostgreSQL")

PROFILE = os.getenv("ONTOLOGY_MIXED_PROFILE", "smoke").strip().lower()
if PROFILE not in {"smoke", "reference"}:
    raise SystemExit("ONTOLOGY_MIXED_PROFILE must be 'smoke' or 'reference'")

REFERENCE_OBJECTS = 10_000_000
REFERENCE_LINKS = 50_000_000
OBJECT_COUNT = int(os.getenv(
    "ONTOLOGY_MIXED_OBJECTS",
    str(REFERENCE_OBJECTS if PROFILE == "reference" else 100_000),
))
LINK_COUNT = int(os.getenv(
    "ONTOLOGY_MIXED_LINKS",
    str(REFERENCE_LINKS if PROFILE == "reference" else 500_000),
))
WRITE_COUNT = int(os.getenv(
    "ONTOLOGY_MIXED_WRITES",
    "100000" if PROFILE == "reference" else "2000",
))
BATCH_SIZE = int(os.getenv("ONTOLOGY_MIXED_BATCH_SIZE", "200"))
READERS = int(os.getenv("ONTOLOGY_MIXED_READERS", "8" if PROFILE == "reference" else "4"))
MIN_READ_SAMPLES = int(os.getenv("ONTOLOGY_MIXED_MIN_READ_SAMPLES", "40"))
READ_P95_LIMIT_MS = float(os.getenv("ONTOLOGY_MIXED_READ_P95_LIMIT_MS", "300"))
WRITE_P95_LIMIT_MS = float(os.getenv("ONTOLOGY_MIXED_WRITE_P95_LIMIT_MS", "2000"))
MIN_WRITE_THROUGHPUT = float(os.getenv("ONTOLOGY_MIXED_MIN_WRITE_THROUGHPUT", "100"))
EVIDENCE_PATH = os.getenv("ONTOLOGY_MIXED_EVIDENCE_PATH")

if min(OBJECT_COUNT, LINK_COUNT, WRITE_COUNT, BATCH_SIZE, READERS) < 1:
    raise SystemExit("Mixed workload counts must be positive")
if WRITE_COUNT > OBJECT_COUNT:
    raise SystemExit("ONTOLOGY_MIXED_WRITES cannot exceed the fixture object count")
if PROFILE == "reference" and (OBJECT_COUNT < REFERENCE_OBJECTS or LINK_COUNT < REFERENCE_LINKS):
    raise SystemExit("Reference profile requires at least 10,000,000 objects and 50,000,000 links")

os.environ["SKIP_CREATE_ALL"] = "1"
os.environ.setdefault("AUTH_MODE", "local")
os.environ.setdefault("APP_ENV", "test")

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import text  # noqa: E402

from app.database import engine  # noqa: E402
from app.main import app  # noqa: E402


OBJECT_TYPE_ID = "scale_benchmark_asset"
LINK_TYPE_ID = "scale_benchmark_related"
OBJECT_PREFIX = "scale_object_"
RUN_ID = f"mixed_{uuid.uuid4().hex}"


def percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    return ordered[max(0, min(len(ordered) - 1, math.ceil(len(ordered) * fraction) - 1))]


def checked(response, expected: int = 200):
    assert response.status_code == expected, f"{response.status_code}: {response.text[:2000]}"
    return response.json()


object_width = max(8, len(str(OBJECT_COUNT)))
with engine.connect() as connection:
    fixture = connection.execute(text("""
        SELECT
          (SELECT count(*) FROM object_instances
             WHERE project_id = 'default' AND object_type_id = :object_type_id) AS objects,
          (SELECT count(*) FROM link_instances
             WHERE project_id = 'default' AND link_type_id = :link_type_id) AS links
    """), {"object_type_id": OBJECT_TYPE_ID, "link_type_id": LINK_TYPE_ID}).mappings().one()
if int(fixture["objects"]) != OBJECT_COUNT or int(fixture["links"]) != LINK_COUNT:
    raise SystemExit(
        "Mixed workload requires an exact ontology scale fixture: "
        f"expected {OBJECT_COUNT}/{LINK_COUNT}, found {fixture['objects']}/{fixture['links']}"
    )

lookup_id = f"{OBJECT_PREFIX}{max(1, OBJECT_COUNT - WRITE_COUNT - 1):0{object_width}d}"
lookup_body = {
    "project_id": "default",
    "object_type_id": OBJECT_TYPE_ID,
    "filters": [{"field": "assetId", "operator": "eq", "value": lookup_id}],
    "order_by": [{"field": "assetId", "direction": "asc"}],
    "limit": 10,
    "include_total": False,
    "include_lineage": False,
}
range_body = {
    "project_id": "default",
    "object_type_id": OBJECT_TYPE_ID,
    "filters": [{"field": "risk", "operator": "gte", "value": 95}],
    "order_by": [{"field": "risk", "direction": "desc"}],
    "limit": 100,
    "include_total": False,
    "include_lineage": False,
}

stop_readers = threading.Event()
reader_started = threading.Barrier(READERS + 1)
latency_lock = threading.Lock()
read_latencies: list[float] = []
reader_errors: list[str] = []


def reader() -> None:
    local_latencies: list[float] = []
    try:
        with TestClient(app) as client:
            reader_started.wait(timeout=30)
            iteration = 0
            while not stop_readers.is_set() or len(local_latencies) < MIN_READ_SAMPLES:
                body = lookup_body if iteration % 2 == 0 else range_body
                started = time.perf_counter()
                result = checked(client.post("/api/v1/objects/query", json=body))
                local_latencies.append((time.perf_counter() - started) * 1000.0)
                if body is lookup_body:
                    assert [item["id"] for item in result["objects"]] == [lookup_id]
                else:
                    assert result["count"] == 100
                iteration += 1
    except Exception as exc:  # surfaced after all workers join
        with latency_lock:
            reader_errors.append(repr(exc))
    finally:
        with latency_lock:
            read_latencies.extend(local_latencies)


threads = [threading.Thread(target=reader, name=f"ontology-reader-{index}") for index in range(READERS)]
for thread in threads:
    thread.start()
reader_started.wait(timeout=30)

write_ids = [f"{OBJECT_PREFIX}{number:0{object_width}d}" for number in range(1, WRITE_COUNT + 1)]
write_batch_latencies: list[float] = []
write_started = time.perf_counter()
for batch_number, offset in enumerate(range(0, WRITE_COUNT, BATCH_SIZE), start=1):
    batch_ids = write_ids[offset:offset + BATCH_SIZE]
    batch_started = time.perf_counter()
    with engine.begin() as connection:
        current = connection.execute(text("""
            SELECT instance.id, instance.properties,
                   COALESCE((
                     SELECT max(event.object_version)
                       FROM object_change_events AS event
                      WHERE event.project_id = instance.project_id
                        AND event.object_id = instance.id
                   ), 0) + 1 AS object_version
              FROM object_instances AS instance
             WHERE instance.project_id = 'default'
               AND instance.object_type_id = :object_type_id
               AND instance.id = ANY(:object_ids)
             ORDER BY instance.id FOR UPDATE
        """), {"object_type_id": OBJECT_TYPE_ID, "object_ids": batch_ids}).mappings().all()
        assert len(current) == len(batch_ids), (len(current), len(batch_ids))
        now = int(time.time())
        updates = []
        events = []
        for row in current:
            before = dict(row["properties"] or {})
            after = dict(before)
            after["risk"] = (int(before.get("risk", 0)) + 1) % 101
            updates.append({"object_id": row["id"], "properties": json.dumps(after), "updated_at": now})
            events.append({
                "id": f"object_event_{uuid.uuid4().hex}",
                "object_id": row["id"],
                "object_version": int(row["object_version"]),
                "before_state": json.dumps(before),
                "after_state": json.dumps(after),
                "evidence": json.dumps({"benchmark_run_id": RUN_ID, "batch": batch_number}),
                "transaction_time": now,
            })
        connection.execute(text("""
            UPDATE object_instances
               SET properties = CAST(:properties AS jsonb), updated_at = :updated_at
             WHERE project_id = 'default' AND object_type_id = :object_type_id
               AND id = :object_id
        """).bindparams(object_type_id=OBJECT_TYPE_ID), updates)
        connection.execute(text("""
            INSERT INTO object_change_events (
                id, project_id, object_type_id, object_id, object_version,
                event_type, actor, source_type, source_id, before_state,
                after_state, changed_fields, evidence, ontology_revision_id,
                valid_from, valid_to, transaction_time
            ) VALUES (
                :id, 'default', :object_type_id, :object_id, :object_version,
                'ontology.object.benchmark_updated', 'benchmark',
                'ontology_mixed_workload', :run_id,
                CAST(:before_state AS jsonb), CAST(:after_state AS jsonb),
                CAST('["risk"]' AS json), CAST(:evidence AS json), NULL,
                :transaction_time, NULL, :transaction_time
            )
        """).bindparams(object_type_id=OBJECT_TYPE_ID, run_id=RUN_ID), events)
    write_batch_latencies.append((time.perf_counter() - batch_started) * 1000.0)

write_seconds = time.perf_counter() - write_started
stop_readers.set()
for thread in threads:
    thread.join(timeout=120)
assert all(not thread.is_alive() for thread in threads), "Reader threads did not terminate"
assert not reader_errors, reader_errors

# A failed transaction must leave neither object mutation nor temporal evidence.
rollback_id = write_ids[0]
rollback_event_id = f"object_event_{uuid.uuid4().hex}"
with engine.connect() as connection:
    rollback_before = connection.execute(text(
        "SELECT properties FROM object_instances WHERE id = :id"
    ), {"id": rollback_id}).scalar_one()
    rollback_version = int(connection.execute(text("""
        SELECT COALESCE(max(object_version), 0) + 1
          FROM object_change_events
         WHERE project_id = 'default' AND object_id = :id
    """), {"id": rollback_id}).scalar_one())
try:
    with engine.begin() as connection:
        changed = dict(rollback_before)
        changed["risk"] = -999
        connection.execute(text("""
            UPDATE object_instances SET properties = CAST(:properties AS jsonb)
            WHERE id = :id
        """), {"properties": json.dumps(changed), "id": rollback_id})
        connection.execute(text("""
            INSERT INTO object_change_events (
                id, project_id, object_type_id, object_id, object_version,
                event_type, actor, source_type, source_id, before_state,
                after_state, changed_fields, evidence, ontology_revision_id,
                valid_from, valid_to, transaction_time
            ) VALUES (
                :event_id, 'default', :object_type_id, :object_id, :object_version,
                'rollback_probe', 'benchmark', 'ontology_mixed_workload',
                :run_id, CAST(:before_state AS jsonb), CAST(:after_state AS jsonb),
                CAST('["risk"]' AS json), CAST('{}' AS json), NULL,
                :now, NULL, :now
            )
        """), {
            "event_id": rollback_event_id, "object_type_id": OBJECT_TYPE_ID,
            "object_id": rollback_id, "object_version": rollback_version, "run_id": RUN_ID,
            "before_state": json.dumps(rollback_before), "after_state": json.dumps(changed),
            "now": int(time.time()),
        })
        raise RuntimeError("intentional rollback probe")
except RuntimeError as exc:
    assert str(exc) == "intentional rollback probe"

with engine.begin() as connection:
    connection.execute(text("ANALYZE object_instances"))
    connection.execute(text("ANALYZE object_change_events"))

with engine.connect() as connection:
    integrity = connection.execute(text("""
        SELECT count(*) AS event_count,
               count(DISTINCT object_id) AS distinct_objects,
               count(*) FILTER (
                 WHERE CAST(after_state ->> 'risk' AS integer)
                       <> ((CAST(before_state ->> 'risk' AS integer) + 1) % 101)
               ) AS invalid_transitions
          FROM object_change_events
         WHERE source_type = 'ontology_mixed_workload' AND source_id = :run_id
    """), {"run_id": RUN_ID}).mappings().one()
    rollback_after = connection.execute(text(
        "SELECT properties FROM object_instances WHERE id = :id"
    ), {"id": rollback_id}).scalar_one()
    rollback_event_count = connection.execute(text(
        "SELECT count(*) FROM object_change_events WHERE id = :event_id"
    ), {"event_id": rollback_event_id}).scalar_one()
    plan = connection.execute(text("""
        EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)
        SELECT id FROM object_instances
        WHERE project_id = 'default' AND object_type_id = :object_type_id
          AND CASE
                WHEN jsonb_typeof(properties -> 'risk') = 'number'
                THEN CAST(properties ->> 'risk' AS double precision)
              END >= 95
        ORDER BY CASE
                   WHEN jsonb_typeof(properties -> 'risk') = 'number'
                   THEN CAST(properties ->> 'risk' AS double precision)
                 END DESC, id DESC
        LIMIT 100
    """), {"object_type_id": OBJECT_TYPE_ID}).scalar_one()
    index_stats = connection.execute(text("""
        SELECT indexrelname, idx_scan, idx_tup_read, idx_tup_fetch
          FROM pg_stat_user_indexes
         WHERE relname = 'object_instances'
           AND indexrelname LIKE 'ix_oi_property_%'
         ORDER BY indexrelname
    """)).mappings().all()

assert int(integrity["event_count"]) == WRITE_COUNT, integrity
assert int(integrity["distinct_objects"]) == WRITE_COUNT, integrity
assert int(integrity["invalid_transitions"]) == 0, integrity
assert rollback_after == rollback_before
assert int(rollback_event_count) == 0
plan_text = json.dumps(plan)
assert "ix_oi_property_" in plan_text, plan

# Dispose the pool and reconnect to prove committed state survives connection loss.
engine.dispose()
with engine.connect() as connection:
    reconnect = connection.execute(text("""
        SELECT
          (SELECT count(*) FROM object_change_events
            WHERE source_type = 'ontology_mixed_workload' AND source_id = :run_id) AS events,
          (SELECT count(*) FROM object_instances
            WHERE project_id = 'default' AND object_type_id = :object_type_id) AS objects
    """), {"run_id": RUN_ID, "object_type_id": OBJECT_TYPE_ID}).mappings().one()
assert int(reconnect["events"]) == WRITE_COUNT
assert int(reconnect["objects"]) == OBJECT_COUNT

read_p95 = percentile(read_latencies, 0.95)
write_p95 = percentile(write_batch_latencies, 0.95)
throughput = WRITE_COUNT / write_seconds
assert len(read_latencies) >= READERS * MIN_READ_SAMPLES, len(read_latencies)
gate_failures = []
if read_p95 >= READ_P95_LIMIT_MS:
    gate_failures.append({
        "metric": "concurrent_read_p95_ms",
        "actual": round(read_p95, 3),
        "limit": READ_P95_LIMIT_MS,
        "operator": "lt",
    })
if write_p95 >= WRITE_P95_LIMIT_MS:
    gate_failures.append({
        "metric": "write_batch_p95_ms",
        "actual": round(write_p95, 3),
        "limit": WRITE_P95_LIMIT_MS,
        "operator": "lt",
    })
if throughput < MIN_WRITE_THROUGHPUT:
    gate_failures.append({
        "metric": "writes_per_second",
        "actual": round(throughput, 3),
        "limit": MIN_WRITE_THROUGHPUT,
        "operator": "gte",
    })

evidence = {
    "status": "FAIL" if gate_failures else "PASS",
    "gate_failures": gate_failures,
    "run_id": RUN_ID,
    "profile": PROFILE,
    "reference_scale_achieved": OBJECT_COUNT >= REFERENCE_OBJECTS and LINK_COUNT >= REFERENCE_LINKS,
    "objects": OBJECT_COUNT,
    "links": LINK_COUNT,
    "writes": WRITE_COUNT,
    "write_transactions": len(write_batch_latencies),
    "write_seconds": round(write_seconds, 3),
    "batch_size": BATCH_SIZE,
    "reader_workers": READERS,
    "read_samples": len(read_latencies),
    "concurrent_read_p50_ms": round(statistics.median(read_latencies), 3),
    "concurrent_read_p95_ms": round(read_p95, 3),
    "read_p95_limit_ms": READ_P95_LIMIT_MS,
    "write_batch_p50_ms": round(statistics.median(write_batch_latencies), 3),
    "write_batch_p95_ms": round(write_p95, 3),
    "write_p95_limit_ms": WRITE_P95_LIMIT_MS,
    "writes_per_second": round(throughput, 3),
    "minimum_writes_per_second": MIN_WRITE_THROUGHPUT,
    "temporal_events": int(integrity["event_count"]),
    "invalid_transitions": int(integrity["invalid_transitions"]),
    "rollback_probe": "PASS",
    "connection_recovery": "PASS",
    "indexed_plan_after_mutation": True,
    "index_stats": [dict(row) for row in index_stats],
    "host": {
        "platform": platform.platform(),
        "python": platform.python_version(),
        "processor": platform.processor(),
    },
}
serialized = json.dumps(evidence, indent=2, sort_keys=True)
if EVIDENCE_PATH:
    Path(EVIDENCE_PATH).write_text(serialized + "\n", encoding="utf-8")
print(f"PostgreSQL ontology mixed workload benchmark {evidence['status'].lower()}:")
print(serialized)

# The Tier B mixed-workload gate names concurrent reads during bounded writes,
# rollback atomicity and retained index plans. It states no scale, so unlike
# ontology_scale and pipeline_scale this gate is satisfiable below reference
# size and evidence is emitted for either profile. The scale is recorded in the
# measurements so a reader can judge rather than infer.
from tier_b_evidence import write_evidence  # noqa: E402

_gate_path, _gate_status, _gate_breaches = write_evidence(
    "mixed_workload",
    thresholds={
        "concurrent_read_p95_ms_max": READ_P95_LIMIT_MS,
        "write_batch_p95_ms_max": WRITE_P95_LIMIT_MS,
        "writes_per_second_min": MIN_WRITE_THROUGHPUT,
        "invalid_transitions_max": 0,
        "rollback_probes_passed_min": 1,
        "indexed_plans_after_mutation_min": 1,
        "reader_workers_min": 2,
        "performance_gate_failures_max": 0,
    },
    measurements={
        "concurrent_read_p95_ms": evidence["concurrent_read_p95_ms"],
        "write_batch_p95_ms": evidence["write_batch_p95_ms"],
        "writes_per_second": evidence["writes_per_second"],
        "invalid_transitions": evidence["invalid_transitions"],
        "rollback_probes_passed": 1 if evidence["rollback_probe"] == "PASS" else 0,
        "indexed_plans_after_mutation": 1 if evidence["indexed_plan_after_mutation"] else 0,
        "reader_workers": evidence["reader_workers"],
        "performance_gate_failures": len(gate_failures),
        "objects": OBJECT_COUNT,
        "links": LINK_COUNT,
        "writes": WRITE_COUNT,
        "read_samples": evidence["read_samples"],
        "temporal_events": evidence["temporal_events"],
    },
    harness="oms/benchmark_ontology_mixed_workload_postgres.py",
    notes=(
        f"Profile '{PROFILE}' at {OBJECT_COUNT} objects and {LINK_COUNT} links with "
        f"{WRITE_COUNT} writes across {evidence['write_transactions']} bounded transactions "
        f"and {evidence['reader_workers']} concurrent readers. The gate states no scale; "
        "reference-size behaviour belongs to the ontology_scale gate. Rollback atomicity "
        "and the post-mutation index plan are verified in the same run."
    ),
)
print(f"\nTier B evidence {_gate_status}: {_gate_path.name}")
for _breach in _gate_breaches:
    print(f"  breach: {_breach}")

engine.dispose()
if gate_failures:
    raise AssertionError({"performance_gate_failures": gate_failures})

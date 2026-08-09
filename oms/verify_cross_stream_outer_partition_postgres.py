"""Rehearse PostgreSQL connection loss during outer-join finalization.

The finalization transaction is slowed by a processor-scoped test trigger. The
harness observes the receipt INSERT in ``pg_stat_activity`` before terminating
that exact backend, proving the interruption lands after finalization begins and
before commit. Recovery must replay every unmatched row once with no partial
watermark, receipt, or dataset state left by the failed transaction.
"""
import os
import time
import uuid
from concurrent.futures import ThreadPoolExecutor


if not os.environ.get("DATABASE_URL", "").startswith("postgresql"):
    raise SystemExit(
        "verify_cross_stream_outer_partition_postgres.py requires a PostgreSQL DATABASE_URL"
    )
os.environ["SKIP_CREATE_ALL"] = "1"
os.environ.setdefault("AUTH_MODE", "local")
os.environ.setdefault("APP_ENV", "test")

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import text  # noqa: E402
from app.database import SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.models import DataAsset  # noqa: E402
from app.stream_processing import (  # noqa: E402
    StreamJoinOuterReceipt,
    StreamJoinReceipt,
    StreamPartitionState,
)


ROWS = 60
prefix = f"pg_outer_partition_{uuid.uuid4().hex[:8]}"
left_stream = f"{prefix}_left"
right_stream = f"{prefix}_right"
processor_id = f"{prefix}_processor"
output_id = f"{prefix}_output"
trigger_name = f"{prefix}_slow_receipt"
function_name = f"{prefix}_slow_receipt_fn"


def checked(response, expected=200):
    assert response.status_code == expected, f"{response.status_code}: {response.text[:2000]}"
    return response.json() if response.content else {}


def advance_watermark(actor: str) -> dict:
    try:
        with TestClient(app) as client:
            response = client.post(
                f"/api/v1/streams/processors/{processor_id}/watermarks",
                json={"side": "right", "join_key": "shared-key", "watermark": 2000},
                headers={"X-Actor": actor},
            )
            if response.status_code != 200:
                return {"ok": False, "detail": response.text[:300]}
            return {"ok": True, **response.json()}
    except Exception as error:  # noqa: BLE001 - severed connections vary by driver timing
        return {"ok": False, "detail": str(error)[:300]}


def active_finalizer_pid(timeout_seconds: float = 10.0) -> int:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        with engine.connect() as connection:
            pid = connection.execute(text(
                """
                SELECT pid FROM pg_stat_activity
                WHERE datname = current_database()
                  AND pid <> pg_backend_pid()
                  AND state = 'active'
                  AND query LIKE 'INSERT INTO stream_join_outer_receipts%'
                ORDER BY query_start
                LIMIT 1
                """
            )).scalar_one_or_none()
        if pid is not None:
            return int(pid)
        time.sleep(0.01)
    raise AssertionError("outer-receipt INSERT never became active before timeout")


def terminate_backend(pid: int) -> bool:
    with engine.connect() as connection:
        return bool(connection.execute(
            text("SELECT pg_terminate_backend(:pid)"), {"pid": pid},
        ).scalar_one())


def install_slow_trigger() -> None:
    with engine.begin() as connection:
        connection.execute(text(f"""
            CREATE FUNCTION {function_name}() RETURNS trigger
            LANGUAGE plpgsql AS $$
            BEGIN
                PERFORM pg_sleep(0.03);
                RETURN NEW;
            END;
            $$
        """))
        connection.execute(text(f"""
            CREATE TRIGGER {trigger_name}
            BEFORE INSERT ON stream_join_outer_receipts
            FOR EACH ROW
            WHEN (NEW.processor_id = '{processor_id}')
            EXECUTE FUNCTION {function_name}()
        """))


def remove_slow_trigger() -> None:
    engine.dispose()
    with engine.begin() as connection:
        connection.execute(text(
            f"DROP TRIGGER IF EXISTS {trigger_name} ON stream_join_outer_receipts"
        ))
        connection.execute(text(f"DROP FUNCTION IF EXISTS {function_name}()"))


with TestClient(app) as client:
    checked(client.post("/data-assets", json={
        "id": output_id, "project_id": "default",
        "display_name": "Outer partition recovery output",
        "kind": "dataset", "asset_schema": {}, "records": [],
    }))
    for stream_id in (left_stream, right_stream):
        checked(client.post("/streams", json={
            "id": stream_id, "project_id": "default", "display_name": stream_id,
            "schema": {"event_ts": "number", "asset_id": "string"},
        }))
    checked(client.post("/api/v1/streams/processors", json={
        "id": processor_id, "project_id": "default", "stream_id": left_stream,
        "join_stream_id": right_stream,
        "display_name": "Partitioned full outer interval join",
        "timestamp_field": "event_ts", "join_left_key": "asset_id",
        "join_right_key": "asset_id", "join_time_tolerance_seconds": 5,
        "join_type": "full", "late_policy": "quarantine",
        "target_asset_id": output_id, "max_batch_records": 100,
        "max_backlog_records": 1000,
    }), 201)
    checked(client.post(f"/streams/{left_stream}/publish", json={"records": [
        {"event_ts": 1000 + offset, "asset_id": "shared-key", "signal": offset}
        for offset in range(ROWS)
    ]}))
    retained = checked(client.post(
        f"/api/v1/streams/processors/{processor_id}/process", json={},
    ))
    assert retained["records_processed"] == ROWS
    assert retained["outer_joins_emitted"] == 0

install_slow_trigger()
try:
    with ThreadPoolExecutor(max_workers=1) as pool:
        interrupted_future = pool.submit(advance_watermark, "outer-partition-victim")
        finalizer_pid = active_finalizer_pid()
        backend_terminated = terminate_backend(finalizer_pid)
        interrupted = interrupted_future.result(timeout=15)
finally:
    remove_slow_trigger()

assert backend_terminated, "the observed finalizer backend was not terminated"
assert not interrupted["ok"], (
    "outer finalization committed despite terminating its active receipt INSERT", interrupted
)

# The watermark, receipts, and materialized output share one transaction. None
# may survive when the finalization connection is lost before commit.
with SessionLocal() as db:
    receipts_before_retry = db.query(StreamJoinOuterReceipt).filter(
        StreamJoinOuterReceipt.processor_id == processor_id,
    ).count()
    output_before_retry = len(db.get(DataAsset, output_id).records or [])
    right_state_before_retry = db.query(StreamPartitionState).filter(
        StreamPartitionState.processor_id == processor_id,
        StreamPartitionState.partition_key == "right:shared-key",
    ).one_or_none()

assert receipts_before_retry == 0, receipts_before_retry
assert output_before_retry == 0, output_before_retry
assert right_state_before_retry is None, right_state_before_retry

recovered = advance_watermark("outer-partition-recovery")
assert recovered["ok"], recovered
assert recovered["outer_joins_emitted"] == ROWS, recovered

# Concurrent replay after recovery must observe committed receipts and emit zero.
with ThreadPoolExecutor(max_workers=2) as pool:
    replayed = list(pool.map(
        lambda worker: advance_watermark(f"outer-replay-{worker}"), range(2)
    ))
assert all(row["ok"] for row in replayed), replayed
assert sum(row["outer_joins_emitted"] for row in replayed) == 0, replayed

# A counterpart arriving behind the finalized watermark is quarantined and
# cannot retract the deterministic unmatched result.
with TestClient(app) as client:
    checked(client.post(f"/streams/{right_stream}/publish", json={"records": [
        {"event_ts": 1000 + offset, "asset_id": "shared-key", "work_order": offset}
        for offset in range(ROWS)
    ]}))
    late = checked(client.post(
        f"/api/v1/streams/processors/{processor_id}/process", json={},
    ))

with SessionLocal() as db:
    receipts = db.query(StreamJoinOuterReceipt).filter(
        StreamJoinOuterReceipt.processor_id == processor_id,
    ).all()
    pair_count = db.query(StreamJoinReceipt).filter(
        StreamJoinReceipt.processor_id == processor_id,
    ).count()
    output_records = list(db.get(DataAsset, output_id).records or [])

receipt_inputs = [row.record_id for row in receipts]
output_ids = [row.get("_stream_join_id") for row in output_records]
duplicate_outer_rows = (len(receipt_inputs) - len(set(receipt_inputs))) + (
    len(output_ids) - len(set(output_ids))
)
missed_outer_rows = ROWS - len(receipts)

evidence = {
    "join_mode": "outer",
    "expected_outer_rows": ROWS,
    "emitted_outer_rows": len(receipts),
    "duplicate_outer_rows": duplicate_outer_rows,
    "missed_outer_rows": missed_outer_rows,
    "matched_pairs_after_finalization": pair_count,
    "receipts_before_retry": receipts_before_retry,
    "outputs_before_retry": output_before_retry,
    "watermark_rolled_back": right_state_before_retry is None,
    "active_finalizer_observed": finalizer_pid > 0,
    "finalizer_backend_terminated": bool(backend_terminated),
    "interrupted_attempt_failed": not interrupted["ok"],
    "recovery_emitted": recovered["outer_joins_emitted"],
    "replay_emitted": sum(row["outer_joins_emitted"] for row in replayed),
    "late_records_quarantined": late["records_quarantined"],
}

print("Cross-stream outer partition rehearsal measurements:")
for key in sorted(evidence):
    print(f"  {key}: {evidence[key]}")

assert duplicate_outer_rows == 0, evidence
assert missed_outer_rows == 0, evidence
assert pair_count == 0, evidence
assert late["records_quarantined"] == ROWS, evidence

from chaos_rehearsals import record  # noqa: E402

record(
    "cross_stream", evidence,
    harness="oms/verify_cross_stream_outer_partition_postgres.py",
)
print("\nPostgreSQL cross-stream outer partition recovery rehearsal passed.")
engine.dispose()

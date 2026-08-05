"""Rehearse network-partition recovery for cross-stream interval processing.

The Tier B chaos gate names collaboration and cross-stream processing. The
collaboration half rehearses replica process loss; this is the cross-stream
half.

The partition is simulated by terminating the application's PostgreSQL backends
with pg_terminate_backend while a processor is mid-flight. That severs the
connection under an open transaction, which is what a partition between the
application and its database looks like from the application's side, and it
exercises the path that matters: whether an interrupted processor resumes
without emitting a pair twice or dropping one.

Correctness here is exact, not statistical. Every left record must pair with its
right record exactly once across the interruption -- no duplicates, no misses.

Requires a PostgreSQL DATABASE_URL.
"""
import os
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor

if not os.environ.get("DATABASE_URL", "").startswith("postgresql"):
    raise SystemExit("verify_cross_stream_partition_postgres.py requires a PostgreSQL DATABASE_URL")
os.environ["SKIP_CREATE_ALL"] = "1"
os.environ.setdefault("AUTH_MODE", "local")
os.environ.setdefault("APP_ENV", "test")

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import text  # noqa: E402
from app.database import SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.models import DataAsset  # noqa: E402
from app.stream_processing import StreamJoinInput, StreamJoinReceipt  # noqa: E402

PAIRS = 60
BATCH = 25

prefix = f"pg_partition_{uuid.uuid4().hex[:8]}"
left_stream = f"{prefix}_left"
right_stream = f"{prefix}_right"
processor_id = f"{prefix}_processor"
output_id = f"{prefix}_output"


def checked(response, expected=200):
    assert response.status_code == expected, f"{response.status_code}: {response.text[:2000]}"
    return response.json() if response.content else {}


def process_batch(actor: str, max_records: int) -> dict:
    """Run one processing pass, reporting failure instead of raising.

    A severed connection surfaces here as ok=False. That is the partition, not
    a defect; the invariants are checked after recovery.
    """
    try:
        with TestClient(app) as thread_client:
            response = thread_client.post(
                f"/api/v1/streams/processors/{processor_id}/process",
                json={"max_records": max_records},
                headers={"X-Actor": actor},
            )
            if response.status_code != 200:
                return {"ok": False, "detail": response.text[:200]}
            return {"ok": True, **response.json()}
    except Exception as error:  # noqa: BLE001 - the partition arrives as any of several
        return {"ok": False, "detail": str(error)[:200]}


def sever_backends() -> int:
    """Terminate this application's PostgreSQL backends, except our own."""
    with engine.connect() as connection:
        terminated = connection.execute(text(
            """
            SELECT count(pg_terminate_backend(pid)) FROM pg_stat_activity
            WHERE datname = current_database()
              AND pid <> pg_backend_pid()
              AND state IS NOT NULL
            """
        )).scalar_one()
    # The pool now holds sockets to backends that no longer exist. Disposing it
    # is the reconnect an application performs after a partition heals; without
    # it the next checkout returns a dead connection.
    engine.dispose()
    return int(terminated or 0)


with TestClient(app) as client:
    checked(client.post("/data-assets", json={
        "id": output_id, "project_id": "default", "display_name": "Partition join output",
        "kind": "dataset", "asset_schema": {}, "records": [],
    }))
    for stream_id in (left_stream, right_stream):
        checked(client.post("/streams", json={
            "id": stream_id, "project_id": "default", "display_name": stream_id,
            "schema": {"event_ts": "number", "asset_id": "string"},
        }))
    checked(client.post("/api/v1/streams/processors", json={
        "id": processor_id, "project_id": "default", "stream_id": left_stream,
        "join_stream_id": right_stream, "display_name": "Partition interval join",
        "timestamp_field": "event_ts", "join_left_key": "asset_id",
        "join_right_key": "asset_id", "join_time_tolerance_seconds": 5,
        "target_asset_id": output_id, "max_batch_records": BATCH,
        "max_backlog_records": 1000,
    }), 201)
    checked(client.post(f"/streams/{left_stream}/publish", json={"records": [
        {"event_ts": 1000 + offset * 10, "asset_id": f"asset-{offset:03d}", "signal": offset}
        for offset in range(PAIRS)
    ]}))
    checked(client.post(f"/streams/{right_stream}/publish", json={"records": [
        {"event_ts": 1002 + offset * 10, "asset_id": f"asset-{offset:03d}", "work_order": offset}
        for offset in range(PAIRS)
    ]}))

    # Partial progress before the partition, so recovery has committed pair
    # state to resume from rather than starting clean. Records arrive left
    # stream first, so a batch smaller than the left stream consumes only left
    # records and emits no pairs at all -- severing at that point rehearses
    # nothing. The batch must reach into the right stream for pairs to exist.
    # The processor's own max_batch_records caps each pass, so a single large
    # request cannot reach the right stream. Take passes until pairs exist.
    emitted_before = 0
    passes_before = 0
    for _ in range(10):
        first = checked(client.post(
            f"/api/v1/streams/processors/{processor_id}/process",
            json={"max_records": PAIRS + BATCH},
        ))
        passes_before += 1
        emitted_before += first["joins_emitted"]
        if emitted_before > 0:
            break
    assert emitted_before > 0, (
        "No pairs were emitted before the partition, so recovery has no committed "
        "pair state to resume from and the rehearsal proves nothing.", first,
    )
    assert first["backlog_after"] > 0, (
        "The backlog drained before the partition, so there is nothing left for "
        "recovery to process.", first,
    )

# Sever while a processor is genuinely in flight. A single sever races the
# processor and usually loses: the pass finishes, the pool reconnects on the
# next checkout, and nothing is rehearsed. Sever repeatedly for the duration of
# the pass so the interruption actually lands, and require that it did -- a
# partition rehearsal that never partitions is worse than no rehearsal, because
# it reports success.
def sever_until(stop: threading.Event) -> int:
    total = 0
    while not stop.is_set():
        try:
            total += sever_backends()
        except Exception:
            pass
        stop.wait(0.02)
    return total


stop_severing = threading.Event()
with ThreadPoolExecutor(max_workers=2) as pool:
    severed = pool.submit(sever_until, stop_severing)
    outcome = process_batch("victim", PAIRS + BATCH)
    stop_severing.set()
    terminated = severed.result()
partition_interrupted = not outcome["ok"]
print(f"Severed {terminated} PostgreSQL backend(s) during the pass; "
      f"in-flight processor {'was interrupted' if partition_interrupted else 'completed'}.")
assert partition_interrupted, (
    "The in-flight processor completed despite repeated severing, so no partition "
    "was rehearsed and a pass here would report success without measuring recovery.",
    outcome,
)

# One more attempt against the freshly severed pool before healing.
attempts_failed = 1 if partition_interrupted else 0
if not process_batch("post-partition", BATCH)["ok"]:
    attempts_failed += 1

# Heal and drain. Bounded so a stalled processor fails the rehearsal instead of
# spinning until the harness is killed.
emitted_after = 0
with TestClient(app) as client:
    for _ in range(20):
        result = checked(client.post(
            f"/api/v1/streams/processors/{processor_id}/process", json={"max_records": BATCH},
        ))
        emitted_after += result["joins_emitted"]
        if result["records_processed"] == 0:
            break
    else:
        raise SystemExit("Processor did not drain its backlog within 20 attempts after recovery.")

# Two processors racing after recovery must not double-emit either.
def process(worker_number):
    with TestClient(app) as thread_client:
        return checked(thread_client.post(
            f"/api/v1/streams/processors/{processor_id}/process",
            json={"max_records": BATCH},
            headers={"X-Actor": f"partition-worker-{worker_number}"},
        ))


with ThreadPoolExecutor(max_workers=2) as pool:
    raced = list(pool.map(process, range(2)))
assert sum(row["joins_emitted"] for row in raced) == 0, raced

with SessionLocal() as db:
    receipts = db.query(StreamJoinReceipt).filter(
        StreamJoinReceipt.processor_id == processor_id,
    ).all()
    pairs = {(row.left_record_id, row.right_record_id) for row in receipts}
    inputs = db.query(StreamJoinInput).filter(
        StreamJoinInput.processor_id == processor_id,
    ).count()
    output = db.get(DataAsset, output_id)
    output_ids = [row["_stream_join_id"] for row in output.records]

duplicate_pairs = len(receipts) - len(pairs)
missed_pairs = PAIRS - len(pairs)
duplicate_outputs = len(output_ids) - len(set(output_ids))

evidence = {
    "expected_pairs": PAIRS,
    "emitted_pairs": len(pairs),
    "duplicate_pairs": duplicate_pairs,
    "missed_pairs": missed_pairs,
    "duplicate_output_records": duplicate_outputs,
    "join_inputs": inputs,
    "backends_severed": terminated,
    "failed_attempts_during_partition": attempts_failed,
    "partition_interrupted_in_flight_processor": bool(partition_interrupted),
    "pairs_before_partition": emitted_before,
    "pairs_after_recovery": emitted_after,
}
print("Cross-stream partition rehearsal measurements:")
for key in sorted(evidence):
    print(f"  {key}: {evidence[key]}")

assert duplicate_pairs == 0, f"partition produced {duplicate_pairs} duplicate pair(s)"
assert missed_pairs == 0, f"partition lost {missed_pairs} pair(s)"
assert duplicate_outputs == 0, f"partition wrote {duplicate_outputs} duplicate output record(s)"
assert terminated > 0, "no backend was severed, so no partition was rehearsed"

from chaos_rehearsals import record  # noqa: E402

record("cross_stream", evidence, harness="oms/verify_cross_stream_partition_postgres.py")
print("\nPostgreSQL cross-stream partition recovery rehearsal passed.")
engine.dispose()

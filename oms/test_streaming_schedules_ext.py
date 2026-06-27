"""
Standalone self-test for the streaming/schedules extensions.

Covers:
  (1) STREAM auto-archive policy   — set policy, deterministic apply, count returned
  (2) STREAM metrics               — record_count, records_per_second, first/last ts
  (3) SCHEDULE 'ignored' outcome   — trigger FALSE => Build status 'IGNORED'
  (4) SCHEDULE metrics             — counts by status + last_run

Does NOT import app.main. Builds a local app from ONLY the owned routers.
Run from oms/:  ./venv312/Scripts/python.exe test_streaming_schedules_ext.py
"""
import os
import tempfile

_t = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(_t.name, 't.db')}"

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.database import Base, engine, SessionLocal  # noqa: E402
from app import models, models_action  # noqa: E402  (ensure tables registered)
from app import streaming as STREAM  # noqa: E402
from app import streaming_ops as STREAM_OPS  # noqa: E402
from app import schedules as SCHED  # noqa: E402
from app import schedules_ops as SCHED_OPS  # noqa: E402

Base.metadata.create_all(bind=engine)

api = FastAPI()
api.include_router(STREAM.router)
api.include_router(STREAM_OPS.router)
api.include_router(SCHED.router)
api.include_router(SCHED_OPS.router)
client = TestClient(api)

passed = 0


def ok(resp, label, expect=200):
    global passed
    success = resp.status_code == expect or (expect == 200 and 200 <= resp.status_code < 300)
    assert success, f"{label}: expected {expect}, got {resp.status_code} -> {resp.text[:400]}"
    passed += 1
    return resp.json() if resp.content else {}


def check(cond, label):
    global passed
    assert cond, f"CHECK FAILED: {label}"
    passed += 1


# =====================================================================
# (1) STREAM auto-archive policy
# =====================================================================
ok(client.post("/streams", json={"id": "s1", "display_name": "S1"}), "create stream s1")

# publish records with explicit (deterministic) timestamps via the ORM so we
# control ts precisely (publish stamps server time). Use a session.
db = SessionLocal()
import uuid as _uuid
for i, ts in enumerate([100, 200, 300, 400, 500]):
    db.add(STREAM.StreamRecord(
        id=_uuid.uuid4().hex, stream_id="s1", payload={"v": i}, ts=ts, archived=False, created_at=ts,
    ))
db.commit()
db.close()

# Set an age-based policy: archive records older than (now - 150).
pol = ok(client.post("/streams/s1/archive-policy", json={"max_age_seconds": 150}), "set archive policy")
check(pol["max_age_seconds"] == 150, "policy max_age echoed")

# Read policy back.
gpol = ok(client.get("/streams/s1/archive-policy"), "get archive policy")
check(gpol["max_age_seconds"] == 150 and gpol["max_records"] is None, "policy persisted")

# Apply deterministically with now=500 => cutoff=350 => ts 100,200,300 archived (3).
ap = ok(client.post("/streams/s1/apply-archive-policy", json={"now": 500}), "apply archive policy age")
check(ap["archived"] == 3, f"age archive count == 3 (got {ap['archived']})")
check(ap["remaining"] == 2, f"remaining == 2 (got {ap['remaining']})")
check(ap["now"] == 500, "deterministic now echoed")

# Idempotent: re-applying archives nothing new.
ap2 = ok(client.post("/streams/s1/apply-archive-policy", json={"now": 500}), "apply archive policy idempotent")
check(ap2["archived"] == 0, f"idempotent re-apply archives 0 (got {ap2['archived']})")

# Count-based policy on a fresh stream: keep newest 2, archive the rest.
ok(client.post("/streams", json={"id": "s2", "display_name": "S2"}), "create stream s2")
db = SessionLocal()
for i, ts in enumerate([10, 20, 30, 40]):
    db.add(STREAM.StreamRecord(
        id=_uuid.uuid4().hex, stream_id="s2", payload={"v": i}, ts=ts, archived=False, created_at=ts,
    ))
db.commit()
db.close()
ok(client.post("/streams/s2/archive-policy", json={"max_records": 2}), "set count policy")
apc = ok(client.post("/streams/s2/apply-archive-policy", json={"now": 1000}), "apply count policy")
check(apc["archived"] == 2 and apc["remaining"] == 2, f"count archive keeps newest 2 (got {apc})")

# =====================================================================
# (2) STREAM metrics
# =====================================================================
m = ok(client.get("/streams/s1/metrics"), "stream metrics s1")
check(m["record_count"] == 5, f"record_count == 5 (got {m['record_count']})")
check(m["first_ts"] == 100 and m["last_ts"] == 500, f"first/last ts (got {m['first_ts']},{m['last_ts']})")
# span = 400, 5 records => 5/400 = 0.0125
check(abs(m["records_per_second"] - (5 / 400)) < 1e-9, f"rps (got {m['records_per_second']})")

# Empty stream metrics.
ok(client.post("/streams", json={"id": "empty", "display_name": "E"}), "create empty stream")
me = ok(client.get("/streams/empty/metrics"), "empty stream metrics")
check(me["record_count"] == 0 and me["records_per_second"] == 0.0, "empty stream metrics zeros")

# 404 path preserved.
check(client.get("/streams/nope/metrics").status_code == 404, "metrics 404 for missing stream")

# =====================================================================
# Preserve existing streaming endpoints (publish/records/window)
# =====================================================================
ok(client.post("/streams", json={"id": "win", "display_name": "W"}), "create win")
ok(client.post("/streams/win/publish", json={"records": [{"ts": 0, "k": "a", "v": 10}, {"ts": 1, "k": "a", "v": 20}]}), "publish preserved")
recs = ok(client.get("/streams/win/records"), "records preserved")
check(len(recs) == 2, "records endpoint still returns published records")

# =====================================================================
# (3) SCHEDULE 'ignored' outcome
# =====================================================================
ok(client.post("/schedules", json={
    "id": "sch1", "display_name": "Nightly", "target_type": "pipeline",
    "target_id": "p1", "trigger_type": "cron", "cron": "0 9 * * *", "enabled": True,
}), "create schedule sch1", expect=201)

# Run with a timestamp where the cron is NOT due => IGNORED.
T_0900 = 1609491600  # 2021-01-01 09:00:00 UTC
b_ign = ok(client.post("/schedules/sch1/run", json={"context": {"timestamp": T_0900 + 60}}), "run ignored", expect=201)
check(b_ign["status"] == "IGNORED", f"trigger false -> IGNORED (got {b_ign['status']})")

# Run with a timestamp where the cron IS due => success.
b_ok = ok(client.post("/schedules/sch1/run", json={"context": {"timestamp": T_0900}}), "run success", expect=201)
check(b_ok["status"] == "success", f"trigger true -> success (got {b_ok['status']})")

# Existing /trigger endpoint still records 'success' unconditionally (preserved).
b_trig = ok(client.post("/schedules/sch1/trigger"), "trigger preserved", expect=201)
check(b_trig["status"] == "success", "legacy /trigger still success")

# =====================================================================
# (4) SCHEDULE metrics
# =====================================================================
sm = ok(client.get("/schedules/sch1/metrics"), "schedule metrics")
check(sm["total"] == 3, f"total builds == 3 (got {sm['total']})")
check(sm["success"] == 2, f"success == 2 (got {sm['success']})")
check(sm["ignored"] == 1, f"ignored == 1 (got {sm['ignored']})")
check(sm["failed"] == 0, f"failed == 0 (got {sm['failed']})")
check(sm["last_run"] is not None, "last_run present")

# Metrics 404 for missing schedule.
check(client.get("/schedules/missing/metrics").status_code == 404, "schedule metrics 404")

# =====================================================================
# Preserve existing schedules_ops endpoints (cron-due / evaluate-trigger)
# =====================================================================
cd = ok(client.post("/schedules/cron-due", json={"cron": "0 9 * * *", "timestamp": T_0900}), "cron-due preserved")
check(cd["due"] is True, "cron-due still works")
et = ok(client.post("/schedules/evaluate-trigger", json={
    "trigger": {"type": "or", "triggers": [{"type": "event", "event": "x"}]},
    "context": {"events": ["x"]}}), "evaluate-trigger preserved")
check(et["result"]["satisfied"] is True, "evaluate-trigger still works")

print(f"\nStreaming/Schedules extensions verified: {passed} assertions passed.")

engine.dispose()
_t.cleanup()

import os, tempfile, uuid
_t = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(_t.name, 't.db')}"
from fastapi import FastAPI                         # noqa: E402
from fastapi.testclient import TestClient           # noqa: E402
from app.database import Base, engine, SessionLocal  # noqa: E402
from app import models, models_action               # noqa: E402  (registers core + audit tables)
from app import audit_ops as M                       # noqa: E402  (owned module)
Base.metadata.create_all(bind=engine)
api = FastAPI(); api.include_router(M.router)
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


# ---------------------------------------------------------------------------
# Seed AuditLog rows directly via SessionLocal with varied event_types /
# actors / timestamps so we can exercise every filter and the derivations.
# ---------------------------------------------------------------------------
def _row(event_type, subject_type, subject_id, actor, ts, payload=None):
    return models_action.AuditLog(
        id=uuid.uuid4().hex,
        actor=actor,
        event_type=event_type,
        subject_type=subject_type,
        subject_id=subject_id,
        payload=payload,
        created_at=ts,
    )


db = SessionLocal()
rows = [
    # event_type, subject_type, subject_id, actor, ts, payload
    _row("security.role.granted", "role", "r1", "alice", 100),
    _row("security.login.failed", "session", "s1", "bob", 110, {"reason": "bad password"}),
    _row("ontology.interface.created", "ontology_interface", "i1", "alice", 200),
    _row("ontology.object_type.updated", "object_type", "ot1", "carol", 210),
    _row("data.dataset.built", "dataset", "d1", "system", 300),
    _row("pipeline.run.completed", "pipeline", "p1", "system", 310),
    _row("pipeline.run.completed", "pipeline", "p2", "system", 320, {"error": "boom"}),
    _row("admin.user.disabled", "user", "u1", "root", 400),
    _row("aip.agent.invoked", "agent", "a1", "alice", 500),
    _row("action.executed", "action_type", "act1", "bob", 600),
    _row("action.approval.requested", "action_type", "act2", "carol", 610),
    _row("widget.frobnicated", "widget", "w1", "alice", 700, {"success": False}),
]
for r in rows:
    db.add(r)
db.commit()
db.close()

# ---------------------------------------------------------------------------
# 1. No filters: returns everything newest-first
# ---------------------------------------------------------------------------
r = ok(client.get("/audit-logs/search"), "search no filters")
check(r["count"] == 12, "all 12 rows returned")
ts_seq = [row["created_at"] for row in r["results"]]
check(ts_seq == sorted(ts_seq, reverse=True), "results are newest-first")
check(r["results"][0]["created_at"] == 700, "first row is the newest (ts=700)")

# ---------------------------------------------------------------------------
# 2. actor filter
# ---------------------------------------------------------------------------
r = ok(client.get("/audit-logs/search?actor=alice"), "search actor=alice")
check(r["count"] == 4, "alice has 4 events")
check(all(x["actor"] == "alice" for x in r["results"]), "all rows are alice")

# ---------------------------------------------------------------------------
# 3. event_type filter (exact)
# ---------------------------------------------------------------------------
r = ok(client.get("/audit-logs/search?event_type=pipeline.run.completed"), "search event_type")
check(r["count"] == 2, "two pipeline.run.completed rows")
check(all(x["event_type"] == "pipeline.run.completed" for x in r["results"]), "exact event_type match")

# ---------------------------------------------------------------------------
# 4. subject_type filter
# ---------------------------------------------------------------------------
r = ok(client.get("/audit-logs/search?subject_type=pipeline"), "search subject_type=pipeline")
check(r["count"] == 2, "two pipeline-subject rows")
check(all(x["subject_type"] == "pipeline" for x in r["results"]), "all subject_type pipeline")

# ---------------------------------------------------------------------------
# 5. time-range filter (start_ts / end_ts inclusive)
# ---------------------------------------------------------------------------
r = ok(client.get("/audit-logs/search?start_ts=200&end_ts=320"), "search time range")
check(r["count"] == 5, "5 rows in [200,320]")
check(all(200 <= x["created_at"] <= 320 for x in r["results"]), "all rows within range")

r = ok(client.get("/audit-logs/search?start_ts=600"), "search start_ts only")
check(r["count"] == 3, "3 rows at ts >= 600")

# ---------------------------------------------------------------------------
# 6. category derivation + filter
# ---------------------------------------------------------------------------
r = ok(client.get("/audit-logs/search?category=security"), "search category=security")
check(r["count"] == 2, "2 security rows")
check(all(x["category"] == "security" for x in r["results"]), "all category security")

r = ok(client.get("/audit-logs/search?category=ontology"), "search category=ontology")
check(r["count"] == 2, "2 ontology rows")

r = ok(client.get("/audit-logs/search?category=data"), "search category=data")
# data.* (1) + pipeline.* (2) all bucket to 'data'
check(r["count"] == 3, "3 data rows (data.* + pipeline.*)")
check(all(x["category"] == "data" for x in r["results"]), "all category data")

r = ok(client.get("/audit-logs/search?category=admin"), "search category=admin")
check(r["count"] == 1, "1 admin row")

r = ok(client.get("/audit-logs/search?category=aip"), "search category=aip")
check(r["count"] == 1, "1 aip row")

r = ok(client.get("/audit-logs/search?category=other"), "search category=other")
# action.* (2) + widget.* (1) bucket to 'other'
check(r["count"] == 3, "3 other rows (action.* + widget.*)")
check(all(x["category"] == "other" for x in r["results"]), "all category other")

# ---------------------------------------------------------------------------
# 7. result derivation + filter
#    failures: security.login.failed (.failed suffix),
#              pipeline.run.completed w/ payload.error,
#              widget.frobnicated w/ success:false  -> 3 failures
# ---------------------------------------------------------------------------
r = ok(client.get("/audit-logs/search?result=failure"), "search result=failure")
check(r["count"] == 3, "3 failure rows")
check(all(x["result"] == "failure" for x in r["results"]), "all result failure")
fail_events = {x["event_type"] for x in r["results"]}
check("security.login.failed" in fail_events, "failed suffix derives failure")
check("widget.frobnicated" in fail_events, "payload success:false derives failure")

r = ok(client.get("/audit-logs/search?result=success"), "search result=success")
check(r["count"] == 9, "9 success rows")
check(all(x["result"] == "success" for x in r["results"]), "all result success")

# one of the two pipeline.run.completed rows is failure (payload.error), one success
r = ok(client.get("/audit-logs/search?event_type=pipeline.run.completed&result=failure"),
       "pipeline failure subset")
check(r["count"] == 1, "only the pipeline row with payload.error is a failure")
check(r["results"][0]["payload"]["error"] == "boom", "failure row carries error payload")

# ---------------------------------------------------------------------------
# 8. combined filters narrow correctly
# ---------------------------------------------------------------------------
r = ok(client.get("/audit-logs/search?actor=alice&category=ontology"), "combined actor+category")
check(r["count"] == 1, "alice + ontology -> 1 row")
check(r["results"][0]["event_type"] == "ontology.interface.created", "correct combined row")

# ---------------------------------------------------------------------------
# 9. limit caps the result set (still newest-first)
# ---------------------------------------------------------------------------
r = ok(client.get("/audit-logs/search?limit=3"), "search limit=3")
check(r["count"] == 3, "limit=3 returns 3 rows")
check([x["created_at"] for x in r["results"]] == [700, 610, 600], "limit keeps newest-first")

# ---------------------------------------------------------------------------
# 10. action-log view: only event_type startswith 'action', newest-first
# ---------------------------------------------------------------------------
r = ok(client.get("/audit-logs/action-log"), "action-log")
check(r["count"] == 2, "2 action.* rows")
check(all(x["event_type"].startswith("action") for x in r["results"]), "all action-prefixed")
check([x["created_at"] for x in r["results"]] == [610, 600], "action-log newest-first")

# ---------------------------------------------------------------------------
# 11. unknown category yields no rows (forgiving, not an error)
# ---------------------------------------------------------------------------
r = ok(client.get("/audit-logs/search?category=nonsense"), "unknown category")
check(r["count"] == 0, "unknown category narrows to nothing")

print(f"\nAUDIT_OPS verified: {passed} assertions passed.")
engine.dispose(); _t.cleanup()

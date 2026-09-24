"""An approval runs its action once, and an idempotency key is a project's for a day.

R11 of GOAL_REPAIR_2026-08-23, decision E. The execute route checked an approval only for being
APPROVED, so one approval ran its action again under every new idempotency key -- a probe ran
one approval three times and wrote three outbox events naming it. And the keys were one global
namespace that never expired: a key another project had used was refused with a message saying
so, and a key used once was held forever.

Now an approval is consumed by the run it authorizes, a key belongs to (project, key), and a key
answers with its first result for a day and is new again after.

Run:
  python oms/test_approval_consumption.py
"""
import os
import tempfile

tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tmpdir.name, 'approval_consumption.db')}"
os.environ["AUTH_MODE"] = "local"
os.environ["APP_ENV"] = "test"

from fastapi.testclient import TestClient  # noqa: E402
from app import models, models_action, production_auth  # noqa: E402
from app.database import SessionLocal  # noqa: E402
from app.main import app  # noqa: E402

client = TestClient(app)
passed = 0


def ok(response, label, expect=200):
    global passed
    success = response.status_code == expect or (expect == 200 and 200 <= response.status_code < 300)
    assert success, f"{label}: expected {expect}, got {response.status_code} -> {response.text[:500]}"
    passed += 1
    return response.json() if response.content else {}


def check(condition, label, payload=None):
    global passed
    assert condition, f"{label}: {payload}"
    passed += 1


def outbox_naming(approval_id):
    with SessionLocal() as db:
        return [row.id for row in db.query(models_action.OutboxEvent).all()
                if (row.payload or {}).get("approval_request_id") == approval_id]


ok(client.post("/object-types", json={"id": "case", "display_name": "Case", "properties": {"state": {"type": "string"}}}), "type")
ok(client.post("/objects", json={"id": "case-1", "object_type_id": "case", "properties": {"state": "open"}}), "object")
ok(client.post("/action-types", json={
    "id": "close_case", "display_name": "Close case", "parameters": {"case_id": {"type": "string", "required": True}},
    "rules": {"requires_approval": True,
              "object_mutations": [{"object_type_id": "case", "object_id": "$case_id", "set": {"state": "closed"}}]},
}), "gated action")
ok(client.post("/action-types", json={
    "id": "note_case", "display_name": "Note case", "parameters": {},
    "rules": {"object_mutations": []},
}), "ungated action")

# --- 1. one approval, one run ------------------------------------------------------------
staged = ok(client.post("/actions/execute", json={
    "action_type_id": "close_case", "parameters": {"case_id": "case-1"}, "idempotency_key": "stage-1",
}), "stage")
approval_id = staged["approval_request_id"]
ok(client.post(f"/approvals/{approval_id}/decision", json={"actor": "approver", "decision": "APPROVED", "reason": "ok"}), "approve")

run = ok(client.post("/actions/execute", json={
    "action_type_id": "close_case", "parameters": {"case_id": "case-1"}, "idempotency_key": "run-1",
    "approval_request_id": approval_id,
}), "run the approved action")
check(run["status"] == "SUCCESS", "the approved action did not run", run)
listed = next(row for row in ok(client.get("/approvals"), "approvals") if row["id"] == approval_id)
check(listed["consumed_at"] and listed["consumed_by_outbox_event_id"] == run["outbox_event_id"],
      "the approval does not say which run consumed it", listed)
check(listed["status"] == "APPROVED", "consumption changed the approval's decision", listed)

again = client.post("/actions/execute", json={
    "action_type_id": "close_case", "parameters": {"case_id": "case-1"}, "idempotency_key": "run-2",
    "approval_request_id": approval_id,
})
check(again.status_code == 409, f"one approval ran its action again under a new key: {again.status_code}", again.text[:300])
check(outbox_naming(approval_id) == [run["outbox_event_id"]], "a second run wrote an outbox event", outbox_naming(approval_id))

retry = ok(client.post("/actions/execute", json={
    "action_type_id": "close_case", "parameters": {"case_id": "case-1"}, "idempotency_key": "run-1",
    "approval_request_id": approval_id,
}), "retry with the first key")
check(retry["status"] == "SUCCESS_CACHED" and retry["outbox_event_id"] == run["outbox_event_id"],
      "a retry within the day did not get the first result back", retry)

# --- 2. a key is its project's --------------------------------------------------------------
alpha = production_auth.Principal("alpha-user", "Alpha", None, ["operator"], ["view", "edit", "execute"], project_ids=["alpha-r11"])
beta = production_auth.Principal("beta-user", "Beta", None, ["operator"], ["view", "edit", "execute"], project_ids=["beta-r11"])
with SessionLocal() as db:
    for project in ("alpha-r11", "beta-r11"):
        db.add(models.ActionType(id=f"note_{project}", project_id=project, display_name="Note", description="",
                                 parameters={}, rules={"object_mutations": []}))
    db.commit()
app.dependency_overrides[production_auth.current_principal] = lambda: alpha
first = ok(client.post("/actions/execute", json={"action_type_id": "note_alpha-r11", "parameters": {}, "idempotency_key": "shared-key"}), "alpha's key")
app.dependency_overrides[production_auth.current_principal] = lambda: beta
second = client.post("/actions/execute", json={"action_type_id": "note_beta-r11", "parameters": {}, "idempotency_key": "shared-key"})
check(second.status_code == 200 and second.json()["status"] == "SUCCESS",
      f"another project's key refused this one's: {second.status_code}", second.text[:300])
check("another project" not in second.text, "the response told one project about another's key", second.text[:300])
app.dependency_overrides[production_auth.current_principal] = lambda: alpha
replay = ok(client.post("/actions/execute", json={"action_type_id": "note_alpha-r11", "parameters": {}, "idempotency_key": "shared-key"}), "alpha replays")
check(replay["status"] == "SUCCESS_CACHED" and replay["outbox_event_id"] == first["outbox_event_id"],
      "beta's use of the same key disturbed alpha's receipt", replay)
app.dependency_overrides.clear()

# --- 3. a key lasts a day --------------------------------------------------------------------
first = ok(client.post("/actions/execute", json={"action_type_id": "note_case", "parameters": {}, "idempotency_key": "day-key"}), "ungated run")
with SessionLocal() as db:
    receipt = db.get(models_action.IdempotencyKey, ("default", "day-key"))
    check(receipt.expires_at == receipt.created_at + 24 * 60 * 60, "a key does not expire a day after it was written",
          (receipt.created_at, receipt.expires_at))
    receipt.expires_at = receipt.created_at - 1  # a day has passed
    db.commit()
fresh = ok(client.post("/actions/execute", json={"action_type_id": "note_case", "parameters": {}, "idempotency_key": "day-key"}), "after a day")
check(fresh["status"] == "SUCCESS" and fresh["outbox_event_id"] != first["outbox_event_id"],
      "an expired key still answered with its old result", fresh)
with SessionLocal() as db:
    rows = db.query(models_action.IdempotencyKey).filter(models_action.IdempotencyKey.key == "day-key").all()
    check(len(rows) == 1 and rows[0].response_payload["outbox_event_id"] == fresh["outbox_event_id"],
          "reusing an expired key left two rows or the old result", [(r.project_id, r.response_payload) for r in rows])

# --- 4. an expired key does not revive a consumed approval ------------------------------------
with SessionLocal() as db:
    db.get(models_action.IdempotencyKey, ("default", "run-1")).expires_at = 0
    db.commit()
late = client.post("/actions/execute", json={
    "action_type_id": "close_case", "parameters": {"case_id": "case-1"}, "idempotency_key": "run-1",
    "approval_request_id": approval_id,
})
check(late.status_code == 409, f"a consumed approval ran again once its key expired: {late.status_code}", late.text[:300])
check(outbox_naming(approval_id) == [run["outbox_event_id"]], "the late retry wrote an outbox event", outbox_naming(approval_id))

print(f"Approvals consumed once, keys per project for a day: {passed} assertions passed.")
from app.database import engine as _engine  # noqa: E402
_engine.dispose()
tmpdir.cleanup()

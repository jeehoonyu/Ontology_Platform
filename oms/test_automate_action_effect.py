"""
STANDALONE self-test for the ACTION effect of oms/app/automate_ops.py.

Does NOT import app.main (siblings edit other files concurrently). Builds a local
FastAPI app from ONLY the automate_ops router and seeds core rows directly.

Proves the fix: an automation whose ACTION effect targets a real ActionType
ACTUALLY mutates the object's property and records the REAL mutated_object_ids
returned by runtime.apply_action_mutations -- while the deterministic
simulate_fail path (used by the existing suite) still produces a FAILED effect
with empty mutated_object_ids.

Run from oms/:  ./venv312/Scripts/python.exe test_automate_action_effect.py
"""

import os, tempfile, time

_t = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(_t.name, 't.db')}"

from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.database import Base, engine, SessionLocal
from app import models, models_action
from app import automate_ops as M

Base.metadata.create_all(bind=engine)
api = FastAPI()
api.include_router(M.router)
client = TestClient(api)

PASSED = 0


def check(cond, msg):
    global PASSED
    if not cond:
        raise AssertionError("FAIL: " + msg)
    PASSED += 1
    print("  ok:", msg)


def ok(resp, msg):
    check(resp.status_code == 200, f"{msg} (HTTP {resp.status_code}: {resp.text[:200]})")
    return resp.json()


def mk_automation(name):
    return ok(client.post("/automations", json={"display_name": name}), f"create automation {name}")["id"]


# ---------------------------------------------------------------------------
# Seed core rows directly (no main.py routes available)
# ---------------------------------------------------------------------------
NOW = int(time.time())
db = SessionLocal()
db.add(models.ObjectType(
    id="ticket", display_name="Ticket", description="",
    properties={"priority": {"type": "string"}, "points": {"type": "number"}},
    created_at=NOW, updated_at=NOW,
))
db.add(models.ObjectInstance(
    id="t1", object_type_id="ticket",
    properties={"priority": "low", "points": 3},
    source_asset_id=None, lineage={}, created_at=NOW, updated_at=NOW,
))
db.add(models.ObjectInstance(
    id="t2", object_type_id="ticket",
    properties={"priority": "low", "points": 1},
    source_asset_id=None, lineage={}, created_at=NOW, updated_at=NOW,
))
# Real ActionType whose rule modifies the 'priority' property of a ticket.
# object_id is resolved from parameters via "$ticket_id".
db.add(models.ActionType(
    id="escalate", display_name="Escalate", description="",
    parameters={"ticket_id": {"type": "string", "required": True}},
    rules={"object_mutations": [
        {"object_type_id": "ticket", "object_id": "$ticket_id",
         "set": {"priority": "critical"}}
    ]},
))
db.commit()
db.close()


# ===========================================================================
# 1. ACTION effect ACTUALLY mutates an object (explicit parameters path)
# ===========================================================================
a1 = mk_automation("escalate-auto")
ok(client.post(f"/automations/{a1}/conditions",
               json={"condition_type": "run_on_all", "config": {"object_type_id": "ticket"}}),
   "add run_on_all condition")
ok(client.post(f"/automations/{a1}/effects",
               json={"effect_type": "action", "execution_order": 0,
                     "config": {"action_type_id": "escalate",
                                "parameters": {"ticket_id": "t1"}}}),
   "add action effect targeting escalate(ticket_id=t1)")

r = ok(client.post(f"/automations/{a1}/run", json={"manual": True}), "run escalate-auto")
check(r["condition_result"] is True, "run_on_all condition triggered")
check(r["status"] == "SUCCEEDED", "action-effect run SUCCEEDED")

eff_res = r["effect_results"][0]
check(eff_res["effect_type"] == "action", "effect_results[0] is an action effect")
check(eff_res["status"] == "SUCCEEDED", "action effect status SUCCEEDED")
result = eff_res["result"]
check(result["type"] == "action", "result.type == action")
check(result["action_type_id"] == "escalate", "result.action_type_id echoes escalate")
# THE CORE ASSERTION: mutated_object_ids is REAL and non-empty
check(isinstance(result.get("mutated_object_ids"), list), "result has mutated_object_ids list")
check("t1" in result["mutated_object_ids"], "mutated_object_ids contains the real mutated id t1")
check(len(result["mutated_object_ids"]) >= 1, "mutated_object_ids is NON-EMPTY")

# Verify the object's property ACTUALLY changed in the DB.
db = SessionLocal()
t1 = db.query(models.ObjectInstance).filter(models.ObjectInstance.id == "t1").first()
check(t1.properties.get("priority") == "critical",
      "object t1 priority ACTUALLY mutated low -> critical")
check((t1.lineage or {}).get("last_action_id") == "escalate",
      "object t1 lineage records the action that mutated it")
# t2 was NOT targeted -> unchanged
t2 = db.query(models.ObjectInstance).filter(models.ObjectInstance.id == "t2").first()
check(t2.properties.get("priority") == "low", "untargeted object t2 unchanged")
db.close()


# ===========================================================================
# 2. ACTION effect via the triggered-object convenience param (_object_id)
# ===========================================================================
db = SessionLocal()
db.add(models.ObjectInstance(
    id="t3", object_type_id="ticket",
    properties={"priority": "low", "points": 2},
    source_asset_id=None, lineage={}, created_at=NOW, updated_at=NOW,
))
# Action whose mutation pulls the object id from the automation's triggered ids.
db.add(models.ActionType(
    id="escalate_first", display_name="Escalate First", description="",
    parameters={},
    rules={"object_mutations": [
        {"object_type_id": "ticket", "object_id_param": "_object_id",
         "set": {"priority": "urgent"}}
    ]},
))
db.commit()
db.close()

a2 = mk_automation("escalate-first-auto")
ok(client.post(f"/automations/{a2}/conditions",
               json={"condition_type": "run_on_all",
                     "config": {"object_type_id": "ticket", "filters": {"points": 2}}}),
   "add run_on_all condition filtered to t3")
ok(client.post(f"/automations/{a2}/effects",
               json={"effect_type": "action", "execution_order": 0,
                     "config": {"action_type_id": "escalate_first"}}),
   "add action effect using triggered _object_id")
r = ok(client.post(f"/automations/{a2}/run", json={"manual": True}), "run escalate-first-auto")
check(r["status"] == "SUCCEEDED", "triggered-id action run SUCCEEDED")
check("t3" in r["effect_results"][0]["result"]["mutated_object_ids"],
      "triggered _object_id resolved -> t3 mutated")

db = SessionLocal()
t3 = db.query(models.ObjectInstance).filter(models.ObjectInstance.id == "t3").first()
check(t3.properties.get("priority") == "urgent", "object t3 ACTUALLY mutated via triggered id")
db.close()


# ===========================================================================
# 3. PRESERVED: deterministic simulate_fail path still FAILS, no mutation,
#    fallback still fires with context (existing contract unchanged).
# ===========================================================================
a3 = mk_automation("simfail-auto")
ok(client.post(f"/automations/{a3}/conditions",
               json={"condition_type": "run_on_all", "config": {"object_type_id": "ticket"}}),
   "add condition")
e_fail = ok(client.post(f"/automations/{a3}/effects",
                        json={"effect_type": "action", "execution_order": 0,
                              "config": {"action_type_id": "AT_X", "simulate_fail": True}}),
            "add simulate_fail action effect (bogus action_type_id, like existing suite)")["id"]
ok(client.post(f"/automations/{a3}/effects",
               json={"effect_type": "fallback", "parent_effect_id": e_fail,
                     "config": {"error_message": "rolled back"}}), "add fallback")
r = ok(client.post(f"/automations/{a3}/run", json={"manual": True}), "run simfail-auto")
by_id = {x["effect_id"]: x for x in r["effect_results"]}
check(by_id[e_fail]["status"] == "FAILED", "simulate_fail action effect FAILED (path preserved)")
check(by_id[e_fail]["result"]["mutated_object_ids"] == [],
      "failed action effect mutated_object_ids is empty (no real mutation on fail)")
fb = [x for x in r["effect_results"] if x["effect_type"] == "fallback"]
check(len(fb) == 1 and fb[0]["result"]["error_message"] == "rolled back",
      "fallback still fires with error context (contract preserved)")

# bogus action_type_id must NOT have created any ticket rows or mutated anything
db = SessionLocal()
count = db.query(models.ObjectInstance).count()
check(count == 3, "simulate_fail created/mutated nothing (still exactly t1,t2,t3)")
db.close()


# ===========================================================================
# 4. Missing-but-non-simulated action type => effect FAILS gracefully (no crash)
# ===========================================================================
a4 = mk_automation("missing-action-auto")
ok(client.post(f"/automations/{a4}/conditions",
               json={"condition_type": "run_on_all", "config": {"object_type_id": "ticket"}}),
   "add condition")
ef = ok(client.post(f"/automations/{a4}/effects",
                    json={"effect_type": "action", "execution_order": 0,
                          "config": {"action_type_id": "DOES_NOT_EXIST"}}),
        "add action effect with unknown action_type_id (no simulate_fail)")["id"]
r = ok(client.post(f"/automations/{a4}/run", json={"manual": True}), "run missing-action-auto")
mby = {x["effect_id"]: x for x in r["effect_results"]}
check(mby[ef]["status"] == "FAILED", "unknown action type effect FAILED gracefully")
check("error" in mby[ef]["result"], "unknown action type result carries an error message")


# ===========================================================================
# 5. A high-risk action staged for approval instead of mutating (T5)
# ===========================================================================
#
# _run_action_effect called apply_action_mutations unconditionally, so an
# automation was a route to run a high-risk action without the approval an
# interactive caller needs. `approve` is a permission the role model withholds
# from operators, so gating this router at `execute` would have handed it to
# them anyway.
db = SessionLocal()
db.add(models.ObjectInstance(
    id="t9", project_id="default", object_type_id="ticket",
    properties={"priority": "low"}, source_asset_id=None, lineage={},
    created_at=NOW, updated_at=NOW))
db.add(models.ActionType(
    id="escalate_risky", display_name="Escalate (high risk)", description="",
    parameters={},
    rules={"risk_level": "high",
           "object_mutations": [
               {"object_type_id": "ticket", "object_id": "t9",
                "set": {"priority": "critical"}}]},
))
db.commit()
db.close()

a9 = mk_automation("risky-auto")
ok(client.post(f"/automations/{a9}/conditions",
               json={"condition_type": "run_on_all", "config": {"object_type_id": "ticket"}}),
   "add run_on_all condition")
ok(client.post(f"/automations/{a9}/effects",
               json={"effect_type": "action", "execution_order": 0,
                     "config": {"action_type_id": "escalate_risky"}}),
   "add high-risk action effect")

r = ok(client.post(f"/automations/{a9}/run", json={"manual": True}), "run risky-auto")
res = r["effect_results"][0]["result"]
check(res.get("status") == "pending_approval",
      "a high-risk action effect stages an approval instead of running")
check(res.get("approval_request_id"), "and returns the approval request id")
check(res.get("mutated_object_ids") == [], "and mutates nothing")

db = SessionLocal()
t9 = db.query(models.ObjectInstance).filter(models.ObjectInstance.id == "t9").first()
check(t9.properties.get("priority") == "low", "the object is untouched until someone approves")
pending = db.query(models_action.ApprovalRequest).filter(
    models_action.ApprovalRequest.action_type_id == "escalate_risky").first()
check(pending is not None, "an ApprovalRequest exists")
# The caller who ran the automation asked for it; the automation is named beside them (R15).
check(pending.requester == os.getenv("LOCAL_AUTH_USER", "local-admin"),
      f"and names the caller who ran the automation as requester, not {pending.requester!r}")
check(res.get("automation_id") == a9, "and the result names the automation")
staged = db.query(models_action.AuditLog).filter(
    models_action.AuditLog.event_type == "automate.action.approval_requested").one()
check(staged.actor == pending.requester and staged.payload.get("automation_id") == a9,
      "and an audit row records both who asked and which automation")
check(pending.status == models_action.ApprovalStatus.PENDING.value, "and is PENDING")
db.close()


# ===========================================================================
# 6. An automation runs an action only in a project its caller may execute in (R15)
# ===========================================================================
#
# The lookup read any project's ActionType by id, so a caller who could execute in
# `default` ran another project's action on that project's objects: 200 SUCCEEDED,
# and the object changed.
from app import production_auth  # noqa: E402

db = SessionLocal()
db.add(models.ObjectType(id="beta_ticket", project_id="beta-automate", display_name="Beta ticket",
                         description="", properties={"priority": {"type": "string"}},
                         created_at=NOW, updated_at=NOW))
db.add(models.ObjectInstance(
    id="b1", project_id="beta-automate", object_type_id="beta_ticket",
    properties={"priority": "low"}, source_asset_id=None, lineage={},
    created_at=NOW, updated_at=NOW))
db.add(models.ActionType(
    id="beta_escalate", project_id="beta-automate", display_name="Beta escalate", description="",
    parameters={},
    rules={"object_mutations": [{"object_type_id": "beta_ticket", "object_id": "b1", "set": {"priority": "hit"}}]},
))
db.commit()
db.close()

a10 = mk_automation("cross-project-auto")
ok(client.post(f"/automations/{a10}/conditions",
               json={"condition_type": "run_on_all", "config": {"object_type_id": "beta_ticket"}}),
   "add a condition on another project's type")
e10 = ok(client.post(f"/automations/{a10}/effects",
                     json={"effect_type": "action", "execution_order": 0,
                           "config": {"action_type_id": "beta_escalate"}}),
         "add an effect naming another project's action")["id"]

default_only = production_auth.Principal("default-operator", "Default operator", None, ["operator"],
                                         ["view", "edit", "execute"], project_ids=["default"])
api.dependency_overrides[production_auth.current_principal] = lambda: default_only
r = ok(client.post(f"/automations/{a10}/run", json={"manual": True}), "run it as a caller of default only")
effect = {x["effect_id"]: x for x in r["effect_results"]}[e10]
check(effect["status"] == "FAILED", f"another project's action ran for a caller of default only: {effect['status']}")
check("may not execute" in effect["result"].get("error", ""), f"the failure says why: {effect['result']}")
db = SessionLocal()
check(db.get(models.ObjectInstance, "b1").properties.get("priority") == "low",
      "another project's object changed under a caller who may not execute there")
db.close()
api.dependency_overrides.pop(production_auth.current_principal, None)

# The same automation, retried by a caller who may execute there, runs -- and the retry's
# work is kept: the route used to return without committing it.
r = ok(client.post(f"/automations/{a10}/run/retry-failed-batches"), "retry as an administrator")
check(r["retried_batches"] == [0], f"the failed batch is retried: {r['retried_batches']}")
check(r["results"][0]["results"][0]["status"] == "SUCCEEDED", "and succeeds for a caller who may execute there")
db = SessionLocal()
b1 = db.get(models.ObjectInstance, "b1")
check(b1.properties.get("priority") == "hit", "the retry's mutation was not kept once the request ended")
check((b1.lineage or {}).get("last_action_actor") == os.getenv("LOCAL_AUTH_USER", "local-admin"),
      f"the mutation records the caller who ran it, not {(b1.lineage or {}).get('last_action_actor')!r}")
db.close()


print(f"\n>= 12 assertions passed: {PASSED} assertions passed")

import os, tempfile, time, uuid
_tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(_tmp.name, 't.db')}"
from fastapi import FastAPI                       # noqa: E402
from fastapi.testclient import TestClient         # noqa: E402
from app.database import Base, engine, SessionLocal  # noqa: E402
from app import models, models_action            # noqa: E402  (core + audit tables)
from app import automate_ops as M                # noqa: E402  (this module's tables)
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
# Seed core ObjectType + ObjectInstances directly via a Session.
# ---------------------------------------------------------------------------
def seed_object_type(ot_id):
    db = SessionLocal()
    db.add(models.ObjectType(id=ot_id, display_name=ot_id, description="t",
                             properties={"status": {"base_type": "string"}},
                             created_at=int(time.time()), updated_at=int(time.time())))
    db.commit(); db.close()


def add_object(ot_id, props, oid=None):
    oid = oid or uuid.uuid4().hex
    db = SessionLocal()
    db.add(models.ObjectInstance(id=oid, object_type_id=ot_id, properties=props,
                                 lineage={}, created_at=int(time.time()), updated_at=int(time.time())))
    db.commit(); db.close()
    return oid


def update_object(oid, props):
    db = SessionLocal()
    inst = db.query(models.ObjectInstance).filter(models.ObjectInstance.id == oid).first()
    inst.properties = props
    inst.updated_at = int(time.time())
    db.commit(); db.close()


seed_object_type("OT_ALERT")


def mk_automation(name="auto", scope="user_scoped"):
    return ok(client.post("/automations", json={"display_name": name, "scope_mode": scope}),
              "create automation")["id"]


# ===========================================================================
# 1. object_count condition triggers / skips per threshold
# ===========================================================================
add_object("OT_ALERT", {"status": "open"})
add_object("OT_ALERT", {"status": "open"})
add_object("OT_ALERT", {"status": "closed"})

a1 = mk_automation("count-auto")
ok(client.post(f"/automations/{a1}/conditions",
               json={"condition_type": "object_count",
                     "config": {"object_type_id": "OT_ALERT", "operator": ">=", "threshold": 3}}),
   "add object_count condition")
# add a notification effect so a triggered run has effects
ok(client.post(f"/automations/{a1}/effects",
               json={"effect_type": "notification", "execution_order": 0,
                     "config": {"heading": "Count alert", "message": "There are {count} objects"}}),
   "add notification effect")
r = ok(client.post(f"/automations/{a1}/run", json={"manual": True}), "run count-auto (>=3, have 3)")
check(r["condition_result"] is True, "object_count >=3 triggers (3 objects)")
check(r["status"] == "SUCCEEDED", "count run succeeded")
check(r["effect_results"][0]["result"]["message"] == "There are 3 objects",
      "{count} substitution in notification")

# Now require >=10 -> skip
a1b = mk_automation("count-auto-high")
ok(client.post(f"/automations/{a1b}/conditions",
               json={"condition_type": "object_count",
                     "config": {"object_type_id": "OT_ALERT", "operator": ">=", "threshold": 10}}),
   "add high threshold condition")
r = ok(client.post(f"/automations/{a1b}/run", json={"manual": True}), "run count-auto-high")
check(r["condition_result"] is False, "object_count >=10 does NOT trigger")
check(r["status"] == "SKIPPED", "untriggered run is SKIPPED")


# ===========================================================================
# 2. object_added diff triggers only on new objects; rerun no-trigger
# ===========================================================================
seed_object_type("OT_ADD")
a2 = mk_automation("added-auto")
ok(client.post(f"/automations/{a2}/conditions",
               json={"condition_type": "object_added", "config": {"object_type_id": "OT_ADD"}}),
   "add object_added condition")
ok(client.post(f"/automations/{a2}/effects",
               json={"effect_type": "notification", "config": {"heading": "h", "message": "m"}}),
   "add effect")
add_object("OT_ADD", {"status": "x"}, oid="add1")
# First run: seeds snapshot. Empty previous snapshot -> add1 is new -> triggers.
r = ok(client.post(f"/automations/{a2}/run", json={"manual": True}), "added first run")
check(r["condition_result"] is True, "object_added triggers on first new object")
check("add1" in r["triggered_object_ids"], "added exposes triggered id add1")
# Rerun with no new objects -> snapshot updated -> no trigger
r = ok(client.post(f"/automations/{a2}/run", json={"manual": True}), "added rerun")
check(r["condition_result"] is False, "object_added no-trigger on rerun (snapshot updated)")
# Add another -> triggers only the new one
add_object("OT_ADD", {"status": "y"}, oid="add2")
r = ok(client.post(f"/automations/{a2}/run", json={"manual": True}), "added third run")
check(r["triggered_object_ids"] == ["add2"], "object_added triggers only newly added id")


# ===========================================================================
# 3. object_modified triggers on property change
# ===========================================================================
seed_object_type("OT_MOD")
a3 = mk_automation("mod-auto")
ok(client.post(f"/automations/{a3}/conditions",
               json={"condition_type": "object_modified", "config": {"object_type_id": "OT_MOD"}}),
   "add object_modified condition")
ok(client.post(f"/automations/{a3}/effects",
               json={"effect_type": "notification", "config": {"heading": "h", "message": "m"}}), "eff")
add_object("OT_MOD", {"status": "a"}, oid="mod1")
ok(client.post(f"/automations/{a3}/run", json={"manual": True}), "mod first run seeds snapshot")
r = ok(client.post(f"/automations/{a3}/run", json={"manual": True}), "mod no-change run")
check(r["condition_result"] is False, "object_modified no-trigger when unchanged")
update_object("mod1", {"status": "b"})
r = ok(client.post(f"/automations/{a3}/run", json={"manual": True}), "mod after change")
check(r["triggered_object_ids"] == ["mod1"], "object_modified triggers on property change")


# ===========================================================================
# 4. threshold_crossed: triggers once false->true, no re-trigger while true,
#    re-records on true->false. Crossing activity recorded.
# ===========================================================================
seed_object_type("OT_TC")
a4 = mk_automation("tc-auto")
cresp = ok(client.post(f"/automations/{a4}/conditions",
                       json={"condition_type": "threshold_crossed",
                             "config": {"object_type_id": "OT_TC", "aggregate": "count",
                                        "operator": ">=", "value": 2}}),
           "add threshold_crossed condition")
ok(client.post(f"/automations/{a4}/effects",
               json={"effect_type": "notification", "config": {"heading": "h", "message": "m"}}), "eff")
# Start with 1 object -> predicate false -> first run seeds state, no crossing
add_object("OT_TC", {"status": "x"}, oid="tc1")
r = ok(client.post(f"/automations/{a4}/run", json={"manual": True}), "tc run1 (count=1, predicate false)")
check(r["condition_result"] is False, "threshold_crossed no trigger while predicate false")
# Add second -> count=2 -> predicate true -> false->true crossing -> trigger
add_object("OT_TC", {"status": "y"}, oid="tc2")
r = ok(client.post(f"/automations/{a4}/run", json={"manual": True}), "tc run2 (count=2 crossing)")
check(r["condition_result"] is True, "threshold_crossed triggers once on false->true")
# Rerun still true -> no re-trigger
r = ok(client.post(f"/automations/{a4}/run", json={"manual": True}), "tc run3 (still true)")
check(r["condition_result"] is False, "threshold_crossed no re-trigger while still true")
# Remove objects so count<2 -> predicate false -> true->false crossing -> trigger
dbx = SessionLocal()
dbx.query(models.ObjectInstance).filter(models.ObjectInstance.id == "tc2").delete()
dbx.commit(); dbx.close()
r = ok(client.post(f"/automations/{a4}/run", json={"manual": True}), "tc run4 (true->false)")
check(r["condition_result"] is True, "threshold_crossed re-records on true->false crossing")
acts = ok(client.get(f"/automations/{a4}/activities"), "tc activities")
trig_acts = [a for a in acts if a["event_type"] == "triggered"]
check(len(trig_acts) >= 2, "threshold_crossed recorded multiple triggered activities (crossings)")


# ===========================================================================
# 5. cron matcher: '15 8 * * 1-5' matches Mon 08:15, not Mon 09:00
# ===========================================================================
MON_0815 = 1704096900  # 2024-01-01 (Monday) 08:15 UTC
MON_0900 = 1704099600  # 2024-01-01 (Monday) 09:00 UTC
SUN_0815 = 1704615300  # 2024-01-07 (Sunday) 08:15 UTC
prev = ok(client.post("/automations/cron/preview", json={"cron": "15 8 * * 1-5", "now": MON_0815}),
          "cron preview Mon 08:15")
check(prev["matches"] is True, "cron '15 8 * * 1-5' matches Monday 08:15")
prev = ok(client.post("/automations/cron/preview", json={"cron": "15 8 * * 1-5", "now": MON_0900}),
          "cron preview Mon 09:00")
check(prev["matches"] is False, "cron '15 8 * * 1-5' does NOT match Monday 09:00")
prev = ok(client.post("/automations/cron/preview", json={"cron": "15 8 * * 1-5", "now": SUN_0815}),
          "cron preview Sun 08:15")
check(prev["matches"] is False, "cron '15 8 * * 1-5' does NOT match Sunday (weekend)")
# time-condition automation run honoring 'now'
seed_object_type("OT_NONE")
a5 = mk_automation("time-auto")
ok(client.post(f"/automations/{a5}/conditions",
               json={"condition_type": "time", "config": {"cron": "15 8 * * 1-5"}}), "add time cond")
ok(client.post(f"/automations/{a5}/effects",
               json={"effect_type": "notification", "config": {"heading": "h", "message": "m"}}), "eff")
r = ok(client.post(f"/automations/{a5}/run", json={"manual": True, "now": MON_0815}), "time run match")
check(r["condition_result"] is True, "time condition triggers at matching epoch")
r = ok(client.post(f"/automations/{a5}/run", json={"manual": True, "now": MON_0900}), "time run no-match")
check(r["condition_result"] is False, "time condition skips at non-matching epoch")


# ===========================================================================
# 6. sequential effects: effect2 fails -> effect3 SKIPPED; fallback runs w/ context
# ===========================================================================
add_object("OT_NONE", {"status": "z"})  # not used; run_on_all needs matches but empty is fine
a6 = mk_automation("effects-auto")
ok(client.post(f"/automations/{a6}/conditions",
               json={"condition_type": "run_on_all", "config": {"object_type_id": "OT_NONE"}}), "cond")
e1 = ok(client.post(f"/automations/{a6}/effects",
                    json={"effect_type": "notification", "execution_order": 0,
                          "config": {"heading": "first", "message": "ok"}}), "effect1")["id"]
e2 = ok(client.post(f"/automations/{a6}/effects",
                    json={"effect_type": "action", "execution_order": 1,
                          "config": {"action_type_id": "AT_X", "simulate_fail": True}}), "effect2 (fails)")["id"]
e3 = ok(client.post(f"/automations/{a6}/effects",
                    json={"effect_type": "notification", "execution_order": 2,
                          "config": {"heading": "third", "message": "should skip"}}), "effect3")["id"]
# fallback attached to effect2
ok(client.post(f"/automations/{a6}/effects",
               json={"effect_type": "fallback", "parent_effect_id": e2,
                     "config": {"error_message": "action failed; rolling back"}}), "fallback")
r = ok(client.post(f"/automations/{a6}/run", json={"manual": True}), "run effects-auto")
res_by_id = {x["effect_id"]: x for x in r["effect_results"]}
check(res_by_id[e1]["status"] == "SUCCEEDED", "effect1 succeeded")
check(res_by_id[e2]["status"] == "FAILED", "effect2 (simulate_fail) FAILED")
check(res_by_id[e3]["status"] == "SKIPPED", "effect3 SKIPPED after prior failure")
fb = [x for x in r["effect_results"] if x["effect_type"] == "fallback"]
check(len(fb) == 1 and fb[0]["result"]["error_message"] == "action failed; rolling back",
      "fallback runs with error context")
check(fb[0]["result"]["for_effect_id"] == e2 and "automation_rid" in fb[0]["result"],
      "fallback carries automation_rid + parent effect id")
check(r["status"] == "PARTIALLY_FAILED", "run with a failed + a succeeded effect is PARTIALLY_FAILED")


# ===========================================================================
# 7. exponential retry attempts recorded
# ===========================================================================
a7 = mk_automation("retry-auto")
ok(client.post(f"/automations/{a7}/conditions",
               json={"condition_type": "run_on_all", "config": {"object_type_id": "OT_NONE"}}), "cond")
ok(client.post(f"/automations/{a7}/effects",
               json={"effect_type": "action", "execution_order": 0,
                     "config": {"action_type_id": "AT_R", "simulate_fail": True}}), "always-fail effect")
ok(client.put(f"/automations/{a7}/retry-config",
              json={"max_attempts": 3, "interval_seconds": 5, "backoff": "exponential"}), "retry config")
r = ok(client.post(f"/automations/{a7}/run", json={"manual": True}), "run retry-auto")
attempts = r["effect_results"][0]["attempts"]
check(len(attempts) == 3, "exponential retry recorded 3 attempts")
check(all(a["ok"] is False for a in attempts), "all retry attempts failed (simulate_fail)")
# exponential intervals before attempt2 and attempt3: 5*2^0=5, 5*2^1=10
check(attempts[1]["wait_before_seconds"] == 5, "exponential wait before attempt2 = 5")
check(attempts[2]["wait_before_seconds"] == 10, "exponential wait before attempt3 = 10")


# ===========================================================================
# 8. pause -> run SKIPPED; resume -> runs
# ===========================================================================
a8 = mk_automation("lifecycle-auto")
ok(client.post(f"/automations/{a8}/conditions",
               json={"condition_type": "run_on_all", "config": {"object_type_id": "OT_NONE"}}), "cond")
ok(client.post(f"/automations/{a8}/effects",
               json={"effect_type": "notification", "config": {"heading": "h", "message": "m"}}), "eff")
ok(client.post(f"/automations/{a8}/pause"), "pause")
r = ok(client.post(f"/automations/{a8}/run", json={"manual": True}), "run while paused")
check(r["status"] == "SKIPPED", "paused automation run is SKIPPED")
ok(client.post(f"/automations/{a8}/resume"), "resume")
r = ok(client.post(f"/automations/{a8}/run", json={"manual": True}), "run after resume")
check(r["status"] == "SUCCEEDED", "resumed automation runs")
acts = ok(client.get(f"/automations/{a8}/activities"), "lifecycle activities")
ev = {a["event_type"] for a in acts}
check("paused" in ev and "resumed" in ev, "pause/resume recorded as activities")
# mute/unmute
au = ok(client.post(f"/automations/{a8}/mute"), "mute")
check(au["muted"] is True, "mute flips muted flag")
au = ok(client.post(f"/automations/{a8}/unmute"), "unmute")
check(au["muted"] is False, "unmute clears muted flag")


# ===========================================================================
# 9. manual batch splits 50 ids by batch_size=20 into 3 batches
# ===========================================================================
seed_object_type("OT_BATCH")
for i in range(50):
    add_object("OT_BATCH", {"status": "open", "n": i})
a9 = mk_automation("batch-auto")
ok(client.post(f"/automations/{a9}/conditions",
               json={"condition_type": "run_on_all", "config": {"object_type_id": "OT_BATCH"}}), "cond")
ok(client.post(f"/automations/{a9}/effects",
               json={"effect_type": "notification", "config": {"heading": "h", "message": "m"}}), "eff")
ok(client.put(f"/automations/{a9}/execution-settings",
              json={"execution_mode": "sequential", "batch_size": 20, "parallelism": 1}), "exec settings")
r = ok(client.post(f"/automations/{a9}/run", json={"manual": True}), "run batch-auto")
check(len(r["triggered_object_ids"]) == 50, "run_on_all triggered all 50 objects")
check(r["batch_count"] == 3, "50 ids / batch_size 20 -> 3 batches")
batch_indices = {x["batch_index"] for x in r["effect_results"]}
check(batch_indices == {0, 1, 2}, "effect results span 3 distinct batches")


# ===========================================================================
# 10. dependency triggers dependent
# ===========================================================================
seed_object_type("OT_DEP")
add_object("OT_DEP", {"status": "open"})
parent = mk_automation("parent-auto")
childauto = mk_automation("child-auto")
ok(client.post(f"/automations/{parent}/conditions",
               json={"condition_type": "run_on_all", "config": {"object_type_id": "OT_DEP"}}), "parent cond")
ok(client.post(f"/automations/{parent}/effects",
               json={"effect_type": "notification", "config": {"heading": "h", "message": "m"}}), "parent eff")
ok(client.post(f"/automations/{childauto}/effects",
               json={"effect_type": "notification", "config": {"heading": "child", "message": "m"}}), "child eff")
ok(client.post(f"/automations/{parent}/dependencies",
               json={"dependent_id": childauto,
                     "additional_condition": {"condition_type": "run_on_all",
                                              "config": {"object_type_id": "OT_DEP"}}}), "add dependency")
r = ok(client.post(f"/automations/{parent}/run", json={"manual": True}), "run parent")
check(r["condition_result"] is True, "parent triggered")
check(len(r["dependent_run_ids"]) == 1, "one dependent run fired")
child_runs = ok(client.get(f"/automations/{childauto}/runs"), "child runs")
check(any(cr["id"] == r["dependent_run_ids"][0] for cr in child_runs), "dependent run recorded in child history")
check(child_runs[0]["status"] == "SUCCEEDED", "dependent run succeeded (additional condition met)")


# ===========================================================================
# 11. validation endpoints + retry-failed-batches + history
# ===========================================================================
v = ok(client.post("/automations/conditions/validate",
                   json={"condition_type": "object_count", "config": {}}), "validate bad condition")
check(v["valid"] is False, "object_count without threshold is invalid")
v = ok(client.post("/automations/conditions/validate",
                   json={"condition_type": "object_count",
                         "config": {"threshold": 1, "operator": ">="}}), "validate good condition")
check(v["valid"] is True, "object_count with threshold is valid")
v = ok(client.post("/automations/effects/validate",
                   json={"effect_type": "fallback"}), "validate fallback without parent")
check(v["valid"] is False, "fallback without parent is invalid")
# error path: unknown condition_type at create -> 422
ok(client.post(f"/automations/{a9}/conditions",
               json={"condition_type": "bogus", "config": {}}), "bad condition_type -> 422", expect=422)
# 404 on unknown automation
ok(client.post("/automations/does-not-exist/run", json={"manual": True}), "run missing automation", expect=404)
# history endpoint
h = ok(client.get(f"/automations/{a9}/history"), "history")
check(h["run_count"] >= 1 and "activities" in h, "history returns runs + activities")
# retry-failed-batches on the partially-failed effects-auto
rf = ok(client.post(f"/automations/{a6}/run/retry-failed-batches"), "retry failed batches")
check("retried_batches" in rf, "retry-failed-batches returns retried batches")


print(f"\nAUTOMATE verified: {passed} assertions passed.")
engine.dispose(); _tmp.cleanup()

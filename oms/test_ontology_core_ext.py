"""
Standalone self-test for the ontology_core extensions (owned file:
app/ontology_core.py). Does NOT import app.main; it builds a local FastAPI app
from ONLY the ontology_core router and seeds core rows directly via SessionLocal.

Covers:
  * function-backed action rule (delegates to a LogicFunction and applies edits)
  * queryable action-log (list/filter + get)
  * undo (reverses recorded property mutations, restores prior values)
  * object-type edit / delete
  * primary-key validation (duplicate vs unique, 404 when no PK)
  * preservation of the existing execute + profile endpoints

Run from oms/: ./venv312/Scripts/python.exe test_ontology_core_ext.py
"""
import os
import tempfile
import time
import uuid

_t = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(_t.name, 't.db')}"

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.database import Base, engine, SessionLocal  # noqa: E402
from app import models, models_action  # noqa: E402
from app import ontology_core as M  # noqa: E402

Base.metadata.create_all(bind=engine)
api = FastAPI()
api.include_router(M.router)
client = TestClient(api)

passed = 0


def ok(resp, label, expect=200):
    global passed
    success = resp.status_code == expect or (expect == 200 and 200 <= resp.status_code < 300)
    assert success, f"{label}: expected {expect}, got {resp.status_code} -> {resp.text[:400]}"
    passed += 1
    return resp.json() if resp.content else {}


def _now():
    return int(time.time())


# ---------------------------------------------------------------------------
# Seed core rows directly (we don't mount the base /object-types router).
# ---------------------------------------------------------------------------
db = SessionLocal()
db.add(models.ObjectType(id="account", display_name="Account", description="",
                         properties={"balance": {"type": "number"}, "status": {"type": "string"}},
                         created_at=_now(), updated_at=_now()))
db.add(models.ObjectType(id="person", display_name="Person", description="",
                         properties={"name": {"type": "string"}, "email": {"type": "string"}},
                         created_at=_now(), updated_at=_now()))
db.add(models.ObjectInstance(id="acct1", object_type_id="account",
                             properties={"balance": 10, "status": "OPEN"},
                             lineage={}, created_at=_now(), updated_at=_now()))
db.add(models.ObjectInstance(id="acct2", object_type_id="account",
                             properties={"balance": 50, "status": "OPEN"},
                             lineage={}, created_at=_now(), updated_at=_now()))
db.add(models.ObjectInstance(id="p1", object_type_id="person",
                             properties={"name": "Ada", "email": "ada@x.io"},
                             lineage={}, created_at=_now(), updated_at=_now()))

# Inline-mutation action (existing behavior must still work).
db.add(models.ActionType(id="adjust_account", display_name="Adjust", description="",
                         parameters={"account_id": {"type": "objectReference", "required": True},
                                     "amount": {"type": "double", "required": True, "min": 0}},
                         rules={"mutations": [
                             {"op": "modify-object", "object_id": "$account_id", "set": {"balance": "$amount"}}]}))

# A referenced inner action used by the function (function emits a proposed_action).
db.add(models.ActionType(id="set_status", display_name="Set Status", description="",
                         parameters={"account_id": {"type": "objectReference", "required": True}},
                         rules={"mutations": [
                             {"op": "modify-object", "object_id": "$account_id", "set": {"status": "FROZEN"}}]}))

# LogicFunction that proposes the inner action for the supplied account.
db.add(models.LogicFunction(id="freeze_fn", display_name="Freeze", description="",
                            blocks=[{"type": "propose_action", "action_type_id": "set_status",
                                     "parameters": {"account_id": "$account_id"}}],
                            input_schema={}, output_schema={}, approval_required=False,
                            created_at=_now(), updated_at=_now()))

# Function-backed action: rules carry a function_id; execution delegates to it.
db.add(models.ActionType(id="freeze_account", display_name="Freeze Account", description="",
                         parameters={"account_id": {"type": "objectReference", "required": True}},
                         rules={"function_id": "freeze_fn"}))
db.commit()
db.close()


# ---------------------------------------------------------------------------
# (1) PRESERVE existing execute behavior on inline-mutation action
# ---------------------------------------------------------------------------
res = ok(client.post("/ontology/action-types/adjust_account/execute",
                     json={"parameters": {"account_id": "acct1", "amount": 100}, "actor": "alice"}),
         "execute inline")
assert res["status"] == "applied" and "acct1" in res["mutated_object_ids"], res
assert "action_log_id" in res, res
adjust_log_id = res["action_log_id"]

# verify the mutation took effect
db = SessionLocal()
assert db.get(models.ObjectInstance, "acct1").properties["balance"] == 100
db.close()

# missing required param still 422 (preserved)
ok(client.post("/ontology/action-types/adjust_account/execute",
               json={"parameters": {"account_id": "acct1"}}), "missing param", expect=422)


# ---------------------------------------------------------------------------
# (2) FUNCTION-BACKED action: delegates to LogicFunction, applies its edits
# ---------------------------------------------------------------------------
fb = ok(client.post("/ontology/action-types/freeze_account/execute",
                    json={"parameters": {"account_id": "acct2"}, "actor": "bob"}),
        "execute function-backed")
assert fb["function_backed"] is True, fb
assert "acct2" in fb["mutated_object_ids"], fb
freeze_log_id = fb["action_log_id"]

db = SessionLocal()
assert db.get(models.ObjectInstance, "acct2").properties["status"] == "FROZEN", "function edit applied"
db.close()


# ---------------------------------------------------------------------------
# (3) ACTION LOG: list (filter by action_type_id / actor) + get by id
# ---------------------------------------------------------------------------
all_logs = ok(client.get("/ontology/action-log"), "list action-log")
assert len(all_logs) >= 2, all_logs

by_type = ok(client.get("/ontology/action-log", params={"action_type_id": "adjust_account"}), "filter by type")
assert all(r["action_type_id"] == "adjust_account" for r in by_type) and by_type, by_type

by_actor = ok(client.get("/ontology/action-log", params={"actor": "bob"}), "filter by actor")
assert by_actor and all(r["actor"] == "bob" for r in by_actor), by_actor

one = ok(client.get(f"/ontology/action-log/{adjust_log_id}"), "get action-log by id")
assert one["id"] == adjust_log_id and one["undone"] is False, one
assert one["reversal"], "reversal before-values recorded"

ok(client.get("/ontology/action-log/does-not-exist"), "missing action-log", expect=404)


# ---------------------------------------------------------------------------
# (4) UNDO: reverses recorded property mutations (restore prior value)
# ---------------------------------------------------------------------------
und = ok(client.post(f"/ontology/action-log/{adjust_log_id}/undo"), "undo adjust")
assert und["status"] == "undone" and "acct1" in und["restored_object_ids"], und

db = SessionLocal()
# balance was 10 before the action set it to 100 -> restored to 10
assert db.get(models.ObjectInstance, "acct1").properties["balance"] == 10, "prior value restored"
db.close()

# undoing again -> 409
ok(client.post(f"/ontology/action-log/{adjust_log_id}/undo"), "double undo", expect=409)

# undo the function-backed action (restores status to OPEN)
ok(client.post(f"/ontology/action-log/{freeze_log_id}/undo"), "undo freeze")
db = SessionLocal()
assert db.get(models.ObjectInstance, "acct2").properties["status"] == "OPEN", "function edit reversed"
db.close()


# ---------------------------------------------------------------------------
# (5) OBJECT-TYPE EDIT / DELETE
# ---------------------------------------------------------------------------
upd = ok(client.put("/ontology/object-types/person",
                    json={"display_name": "Human", "description": "a person"}), "edit object-type")
assert upd["display_name"] == "Human" and upd["description"] == "a person", upd

# delete is blocked while instances exist (p1 still present) -> 409
ok(client.delete("/ontology/object-types/person"), "delete blocked", expect=409)

# create a clean object type with no instances, then delete it
db = SessionLocal()
db.add(models.ObjectType(id="widget", display_name="Widget", description="",
                         properties={"sku": {"type": "string"}}, created_at=_now(), updated_at=_now()))
db.commit()
db.close()
dele = ok(client.delete("/ontology/object-types/widget"), "delete object-type")
assert dele["deleted"] is True, dele
ok(client.get("/ontology/object-types/widget/full"), "deleted gone", expect=404)
ok(client.put("/ontology/object-types/widget", json={"display_name": "x"}), "edit missing", expect=404)


# ---------------------------------------------------------------------------
# (6) PRIMARY-KEY VALIDATION (needs a profile with primary_key)
# ---------------------------------------------------------------------------
# no profile yet -> 404
ok(client.post("/ontology/object-types/account/validate-primary-key",
               json={"properties": {"balance": 1}}), "pk no profile", expect=404)

# set a profile with a primary key + a title key on account
ok(client.put("/ontology/object-types/account/profile", json={
    "api_name": "Account", "primary_key": "acctNo", "title_key": "acctNo",
    "properties": {"acctNo": {"base_type": "string", "status": "active"}}}), "set profile")

# seed two account instances carrying acctNo property values
db = SessionLocal()
db.add(models.ObjectInstance(id="acctX", object_type_id="account",
                             properties={"acctNo": "A-100"}, lineage={},
                             created_at=_now(), updated_at=_now()))
db.commit()
db.close()

# duplicate value -> not unique
dup = ok(client.post("/ontology/object-types/account/validate-primary-key",
                     json={"properties": {"acctNo": "A-100"}}), "pk duplicate")
assert dup["duplicate"] is True and dup["unique"] is False and "acctX" in dup["conflicting_object_ids"], dup

# new unique value -> unique
uni = ok(client.post("/ontology/object-types/account/validate-primary-key",
                     json={"properties": {"acctNo": "A-200"}}), "pk unique")
assert uni["unique"] is True and uni["duplicate"] is False, uni

# missing PK in supplied properties -> 422
ok(client.post("/ontology/object-types/account/validate-primary-key",
               json={"properties": {"balance": 5}}), "pk missing", expect=422)


# ---------------------------------------------------------------------------
# (7) PRESERVE base-types / profile endpoints
# ---------------------------------------------------------------------------
bt = ok(client.get("/ontology/base-types"), "base-types preserved")
assert "string" in bt["primary_key_allowed"], bt
prof = ok(client.get("/ontology/object-types/account/profile"), "profile preserved")
assert prof["primary_key"] == "acctNo", prof


# ---------------------------------------------------------------------------
# (8) UNDO STAYS INSIDE THE LOG'S PROJECT
#
# The reversal payload names bare object ids, and the caller is authorized against
# the log, not against the rows the payload happens to name. Undo resolved them with
# `db.get`, so a log in one project whose reversal named another project's object
# rewrote that object's properties under a permission that looked entirely correct.
# T2 of GOAL_TENANCY_2026-08-27.
# ---------------------------------------------------------------------------
db = SessionLocal()
db.add(models.ObjectInstance(id="victim1", object_type_id="account", project_id="tenant-b",
                             properties={"balance": 999, "status": "OPEN"},
                             lineage={}, created_at=_now(), updated_at=_now()))
db.add(M.ActionLog(id="cross-log", project_id="default", action_type_id="adjust_account",
                   actor="mallory", parameters={}, mutated_object_ids=["victim1"],
                   reversal=[{"op": "modify-object", "object_id": "victim1",
                              "before": {"balance": 0, "status": "DRAINED"},
                              "before_present": {"balance": True, "status": True}}],
                   undone=0, created_at=_now()))
db.commit()
db.close()

crossed = ok(client.post("/ontology/action-log/cross-log/undo"), "undo across projects")
assert "victim1" not in crossed["restored_object_ids"], crossed

db = SessionLocal()
victim = db.get(models.ObjectInstance, "victim1")
assert victim.properties["balance"] == 999, victim.properties
assert victim.properties["status"] == "OPEN", victim.properties
db.close()
passed += 2

# The same undo still reverses rows that *are* in its project.
db = SessionLocal()
db.add(models.ObjectInstance(id="mine1", object_type_id="account", project_id="default",
                             properties={"balance": 7, "status": "OPEN"},
                             lineage={}, created_at=_now(), updated_at=_now()))
db.add(M.ActionLog(id="own-log", project_id="default", action_type_id="adjust_account",
                   actor="ada", parameters={}, mutated_object_ids=["mine1"],
                   reversal=[{"op": "modify-object", "object_id": "mine1",
                              "before": {"balance": 3},
                              "before_present": {"balance": True}}],
                   undone=0, created_at=_now()))
db.commit()
db.close()

mine = ok(client.post("/ontology/action-log/own-log/undo"), "undo within project")
assert "mine1" in mine["restored_object_ids"], mine
db = SessionLocal()
assert db.get(models.ObjectInstance, "mine1").properties["balance"] == 3
db.close()
passed += 1


print(f"\nontology_core extensions verified: {passed} assertions passed.")
engine.dispose()
_t.cleanup()

"""
Deep-fidelity pass 6 (Applications: Slate + Carbon) conformance test.
Slate: query resolution, function DSL, widget render, event engine (incl. apply_action).
Carbon: module resolution across the platform, navigation render, and open-by-delegation.
Run: ./venv312/Scripts/python.exe test_slate_carbon.py
"""
import os
import tempfile

tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tmpdir.name, 'slate_carbon.db')}"

from fastapi.testclient import TestClient  # noqa: E402
from app.main import app  # noqa: E402

client = TestClient(app)
passed = 0


def ok(resp, label, expect=200):
    global passed
    success = resp.status_code == expect or (expect == 200 and 200 <= resp.status_code < 300)
    assert success, f"{label}: expected {expect}, got {resp.status_code} -> {resp.text[:400]}"
    passed += 1
    return resp.json() if resp.content else {}


# ---------------- setup ontology ----------------
ok(client.post("/object-types", json={"id": "deal", "display_name": "Deal", "description": "",
    "properties": {"stage": {"type": "string"}, "value": {"type": "number"}, "owner": {"type": "string"}}}), "deal type")
for did, stage, val, owner in [("d1", "won", 100, "u1"), ("d2", "won", 50, "u2"), ("d3", "lost", 30, "u1")]:
    ok(client.post("/objects", json={"id": did, "object_type_id": "deal", "properties": {"stage": stage, "value": val, "owner": owner}}), f"obj {did}")
ok(client.post("/action-types", json={"id": "win_deal", "display_name": "Win", "description": "",
    "parameters": {"deal_id": {"type": "string", "required": True}},
    "rules": {"object_mutations": [{"object_type_id": "deal", "object_id": "$deal_id", "set": {"stage": "won"}}]}}), "win action")

# ================= SLATE =================
ok(client.post("/apps/slate", json={
    "id": "sales_app", "display_name": "Sales App",
    "queries": {
        "wonDeals": {"type": "object_set", "object_type_id": "deal", "filters": {"stage": "won"}},
        "allDeals": {"type": "object_set", "object_type_id": "deal"},
        "wonTotal": {"type": "object_aggregation", "object_type_id": "deal", "op": "sum", "field": "value", "filters": {"stage": "won"}},
        "region": {"type": "static", "value": "EMEA"},
        "ext": {"type": "http", "url": "https://api.example/x", "mock_response": {"ok": True}},
    },
    "functions": {
        "wonValues": {"op": "pluck", "source": "wonDeals", "field": "value"},
        "wonCount": {"op": "aggregate", "source": "wonDeals", "agg": "count"},
        "headline": {"op": "format", "template": "{region}: {n} won worth {total}",
                     "inputs": {"region": "region", "n": "wonCount", "total": "wonTotal"}},
    },
    "widgets": {
        "tbl": {"type": "object_table", "title": "Won", "query": "wonDeals"},
        "kpi": {"type": "metric", "title": "Won Total", "query": "wonTotal"},
        "msg": {"type": "text", "title": "Headline", "function": "headline"},
    },
}), "create slate app")

r = ok(client.post("/apps/slate/sales_app/resolve", json={"state": {}}), "slate resolve")
assert r["queries"]["wonDeals"]["count"] == 2, r["queries"]["wonDeals"]
assert r["queries"]["wonTotal"] == 150, r["queries"]
assert r["queries"]["ext"]["status"] == "mocked", r["queries"]["ext"]
assert r["functions"]["wonValues"] == [100, 50], r["functions"]
assert r["functions"]["wonCount"] == 2, r["functions"]
assert r["functions"]["headline"] == "EMEA: 2 won worth 150", r["functions"]["headline"]

rq = ok(client.post("/apps/slate/sales_app/run-query/wonDeals", json={"state": {}}), "run-query")
assert rq["result"]["count"] == 2, rq

rend = ok(client.post("/apps/slate/sales_app/render", json={"state": {}}), "slate render")
wmap = {w["name"]: w for w in rend["widgets"]}
assert wmap["tbl"]["row_count"] == 2, wmap["tbl"]
assert wmap["kpi"]["value"] == 150, wmap["kpi"]
assert wmap["msg"]["value"] == "EMEA: 2 won worth 150", wmap["msg"]

# event: apply_action wins d3, then wonDeals recomputes to 3
ev = ok(client.post("/apps/slate/sales_app/event", json={"state": {"sel": "d3"}, "events": [
    {"type": "apply_action", "action_type_id": "win_deal", "parameters": {"deal_id": "$sel"}},
]}), "slate event apply_action")
assert ev["effects"][0]["status"] == "applied" and "d3" in ev["effects"][0]["mutated_object_ids"], ev["effects"]
assert ev["queries"]["wonDeals"]["count"] == 3, ev["queries"]["wonDeals"]  # reactive recompute

# ================= CARBON =================
# a Workshop module to embed
ok(client.post("/apps/workshop", json={"id": "wk1", "display_name": "Deals Board",
    "variables": {"cnt": {"definition_type": "object_set_aggregation", "object_type_id": "deal", "op": "count"}},
    "widgets": [{"type": "metric", "title": "Deals", "variable": "cnt"}]}), "workshop wk1")

ok(client.post("/apps/carbon", json={"id": "hub", "display_name": "Sales Hub",
    "module_ids": ["wk1", "sales_app", "ghost"],
    "navigation": {"home": "wk1", "sections": [{"title": "Apps", "items": ["wk1", "sales_app"]}]}}), "carbon create")

res = ok(client.get("/apps/carbon/hub/resolve"), "carbon resolve")
kinds = {m["module_id"]: m["kind"] for m in res["modules"]}
assert kinds["wk1"] == "workshop" and kinds["sales_app"] == "slate" and kinds["ghost"] == "unknown", kinds
assert res["missing"] == ["ghost"], res["missing"]

ren = ok(client.get("/apps/carbon/hub/render"), "carbon render")
assert ren["home"]["display_name"] == "Deals Board", ren["home"]
labels = {it["display_name"] for s in ren["sections"] for it in s["items"]}
assert {"Deals Board", "Sales App"} <= labels, labels

# open the Workshop module via Carbon (delegates to Workshop runtime)
ow = ok(client.post("/apps/carbon/hub/open/wk1", json={"state": {}}), "carbon open workshop")
assert ow["kind"] == "workshop", ow
metric = next(w for w in ow["rendered"]["widgets"] if w["title"] == "Deals")
assert metric["value"] == 3, metric                          # 3 deals total

# open the Slate app via Carbon (delegates to Slate runtime)
osl = ok(client.post("/apps/carbon/hub/open/sales_app", json={"state": {}}), "carbon open slate")
assert osl["kind"] == "slate", osl
assert any(w["name"] == "tbl" for w in osl["rendered"]["widgets"]), osl["rendered"]["widgets"]

# opening a module not in the workspace -> 404
ok(client.post("/apps/carbon/hub/open/not_a_module", json={"state": {}}), "carbon open invalid", expect=404)

# --- T5: a slate apply_action stages a high-risk action, and names who asked ---
#
# fire_events loaded any ActionType by id, mutated immediately, and wrote
# actor="slate". Its sibling workshop_runtime has always performed the project
# check, staged an ApprovalRequest for a high-risk action, and recorded
# principal.id. The gap meant a slate app was a way around the approval gate
# POST /actions/execute enforces for the identical call.
from app import models, models_action  # noqa: E402
from app.database import SessionLocal  # noqa: E402

with SessionLocal() as _db:
    _db.add(models.ObjectInstance(
        id="slate_t1", project_id="default", object_type_id="slate_ticket",
        properties={"priority": "low"}, source_asset_id=None, lineage={},
        created_at=0, updated_at=0))
    _db.add(models.ObjectType(
        id="slate_ticket", display_name="Slate Ticket", description="",
        properties={"priority": {"type": "string"}}, project_id="default",
        created_at=0, updated_at=0))
    _db.add(models.ActionType(
        id="slate_risky", display_name="Risky", description="", parameters={},
        project_id="default",
        rules={"risk_level": "critical",
               "object_mutations": [{"object_type_id": "slate_ticket",
                                     "object_id": "slate_t1",
                                     "set": {"priority": "critical"}}]}))
    _db.commit()

risky = ok(client.post("/apps/slate/sales_app/event", json={
    "state": {}, "events": [{"type": "apply_action", "action_type_id": "slate_risky"}],
}), "slate high-risk apply_action")
effect = risky["effects"][0]
assert effect["status"] == "pending_approval", effect
passed += 1
assert effect["mutated_object_ids"] == [], effect
passed += 1
print("  ok: a high-risk slate action stages an approval instead of mutating")

with SessionLocal() as _db:
    row = _db.query(models.ObjectInstance).filter(
        models.ObjectInstance.id == "slate_t1").first()
    assert row.properties.get("priority") == "low", row.properties
    pending = _db.query(models_action.ApprovalRequest).filter(
        models_action.ApprovalRequest.action_type_id == "slate_risky").first()
    assert pending is not None and pending.status == models_action.ApprovalStatus.PENDING.value
    assert pending.requester != "slate", "the requester must name the caller, not the runtime"
passed += 2
print("  ok: the object is untouched and the request names the caller, not \"slate\"")


# ---------------------------------------------------------------------------
# Carbon resolves module ids only within the caller's reach
#
# A workspace's `module_ids` decide what gets looked up, and they are as trustworthy as
# whoever last edited the workspace -- not as the caller. The workshop branch authorized;
# the saved-object-set and map-layer branches did not, and answered with another project's
# display name for anyone who could open the workspace. `CarbonWorkspace` records no
# project of its own (T10 of GOAL_TENANCY_2026-08-27), so the bound is what the principal
# can see, not what the workspace claims. T2 of the same document.
# ---------------------------------------------------------------------------
from app import carbon_runtime as _carbon  # noqa: E402
from app import models as _m, production_auth as _auth  # noqa: E402
from app.database import SessionLocal as _SL  # noqa: E402

ok(client.post("/tenancy/organizations", json={"id": "carbon-org", "display_name": "Carbon Org"}),
   "organization for the foreign project", 201)
ok(client.post("/tenancy/projects", json={"id": "tenant-b", "organization_id": "carbon-org",
                                          "display_name": "Tenant B"}), "foreign project", 201)

with _SL() as _db:
    _db.add(_m.SavedObjectSet(id="foreign-set", project_id="tenant-b",
                              display_name="Another tenant's set", object_type_id="deal",
                              filters={}, owner="someone-else", created_at=1, updated_at=1))
    _db.add(_m.SavedObjectSet(id="own-set", project_id="default",
                              display_name="Our own set", object_type_id="deal",
                              filters={}, owner="us", created_at=1, updated_at=1))
    _db.commit()

    _outsider = _auth.Principal("outsider", "Outsider", None, ["viewer"], ["view"],
                                organization_id="org", project_ids=["default"])
    hidden = _carbon._resolve_module(_db, "foreign-set", _outsider)
    assert hidden["exists"] is False, hidden
    assert hidden["display_name"] is None, hidden

    # The same principal still resolves a set it can reach, so the filter is scoping the
    # lookup rather than emptying it -- a fix that hid everything would pass the check above.
    shown = _carbon._resolve_module(_db, "own-set", _outsider)
    assert shown["exists"] is True and shown["kind"] == "object_set", shown
passed += 3


print(f"\nSlate + Carbon faithful runtimes verified: {passed} assertions passed.")
from app.database import engine as _engine  # noqa: E402
_engine.dispose()
tmpdir.cleanup()

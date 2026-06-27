"""
Deep-fidelity pass 5 (Applications) conformance test: Workshop reactive runtime.
Variable definition types resolved against live ontology, dependency-ordered
resolution, live widget rendering, and the event engine (set_variable, navigate,
apply_action). Run: ./venv312/Scripts/python.exe test_workshop.py
"""
import os
import tempfile

tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tmpdir.name, 'workshop.db')}"

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
ok(client.post("/object-types", json={"id": "alert", "display_name": "Alert", "description": "",
    "properties": {"severity": {"type": "string"}, "score": {"type": "number"}, "owner": {"type": "string"}}}), "alert type")
for aid, sev, sc, owner in [("a1", "high", 5, "u1"), ("a2", "high", 3, "u2"), ("a3", "low", 1, "u1")]:
    ok(client.post("/objects", json={"id": aid, "object_type_id": "alert", "properties": {"severity": sev, "score": sc, "owner": owner}}), f"obj {aid}")
ok(client.post("/action-types", json={"id": "ack_alert", "display_name": "Ack", "description": "",
    "parameters": {"alert_id": {"type": "string", "required": True}},
    "rules": {"object_mutations": [{"object_type_id": "alert", "object_id": "$alert_id", "set": {"status": "ack"}}]}}), "ack action")
ok(client.post("/ontology-functions", json={"id": "alert_count", "display_name": "Count", "kind": "compute",
    "object_type_id": "alert", "expression": {"type": "aggregate", "op": "count"}}), "count fn")

# ---------------- create Workshop module with all variable definition types ----------------
ok(client.post("/apps/workshop", json={
    "id": "ops_console", "display_name": "Ops Console",
    "variables": {
        "allAlerts": {"definition_type": "object_set", "object_type_id": "alert"},
        "highCount": {"definition_type": "object_set_aggregation", "object_type_id": "alert", "op": "count", "filters": {"severity": "high"}},
        "totalScore": {"definition_type": "object_set_aggregation", "object_type_id": "alert", "op": "sum", "field": "score"},
        "selectedAlertId": {"definition_type": "state", "key": "selectedAlertId", "default": "a1"},
        "selectedOwner": {"definition_type": "object_property", "object_id_var": "selectedAlertId", "property": "owner"},
        "fnCount": {"definition_type": "function", "function_id": "alert_count"},
        "headline": {"definition_type": "variable_transformation", "op": "concat", "inputs": ["highCount", "selectedOwner"], "separator": " high; owner="},
    },
    "widgets": [
        {"type": "object_table", "title": "All Alerts", "variable": "allAlerts"},
        {"type": "metric", "title": "High", "variable": "highCount"},
        {"type": "button", "title": "Ack", "action_type_id": "ack_alert"},
    ],
}), "create module")

# ---------------- resolve with default state ----------------
r = ok(client.post("/apps/workshop/ops_console/resolve", json={"state": {}}), "resolve default")["variables"]
assert r["allAlerts"]["count"] == 3, r["allAlerts"]
assert r["highCount"] == 2, r
assert r["totalScore"] == 9, r           # 5+3+1
assert r["fnCount"] == 3, r              # ontology function count
assert r["selectedAlertId"] == "a1", r  # state default
assert r["selectedOwner"] == "u1", r    # a1.owner via object_property -> depends on selectedAlertId
assert r["headline"] == "2 high; owner=u1", r  # variable_transformation chaining two resolved vars

# ---------------- resolve with overridden state (reactivity) ----------------
r2 = ok(client.post("/apps/workshop/ops_console/resolve", json={"state": {"selectedAlertId": "a2"}}), "resolve a2")["variables"]
assert r2["selectedOwner"] == "u2", r2
assert r2["headline"] == "2 high; owner=u2", r2

# ---------------- live render of widgets ----------------
render = ok(client.post("/apps/workshop/ops_console/render-live", json={"state": {}}), "render-live")
wmap = {w["title"]: w for w in render["widgets"]}
assert wmap["All Alerts"]["row_count"] == 3, wmap["All Alerts"]
assert wmap["High"]["value"] == 2, wmap["High"]
assert wmap["Ack"]["action_type_id"] == "ack_alert", wmap["Ack"]

# ---------------- event engine: set_variable + navigate ----------------
ev = ok(client.post("/apps/workshop/ops_console/event", json={"state": {}, "events": [
    {"type": "set_variable", "target": "selectedAlertId", "value": "a3"},
    {"type": "navigate", "page": "detail"},
]}), "events nav")
assert ev["state"]["selectedAlertId"] == "a3" and ev["state"]["_page"] == "detail", ev["state"]
assert ev["variables"]["selectedOwner"] == "u1", ev["variables"]  # a3.owner, recomputed after event

# ---------------- event engine: apply_action actually mutates ----------------
ev2 = ok(client.post("/apps/workshop/ops_console/event", json={"state": {"selectedAlertId": "a1"}, "events": [
    {"type": "apply_action", "action_type_id": "ack_alert", "parameters": {"alert_id": "$selectedAlertId"}},
]}), "event apply_action")
assert ev2["applied_actions"] and "a1" in ev2["applied_actions"][0]["mutated_object_ids"], ev2["applied_actions"]
a1 = ok(client.get("/objects/alert/a1"), "get a1")
assert a1["properties"].get("status") == "ack", a1["properties"]

print(f"\nWorkshop reactive runtime verified: {passed} assertions passed.")
from app.database import engine as _engine  # noqa: E402
_engine.dispose()
tmpdir.cleanup()

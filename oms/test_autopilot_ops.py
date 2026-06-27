"""
Autopilot — conformance test. Kanban state inference (direct property + computed rules)
and workflow dependency graph (topological order + cycle detection).
Run: ./venv312/Scripts/python.exe test_autopilot_ops.py
"""
import os
import tempfile

_tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(_tmp.name, 'ap.db')}"

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from app.database import Base, engine, SessionLocal  # noqa: E402
from app import models, models_action  # noqa: E402
from app import autopilot_ops as M  # noqa: E402

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


# ---- seed an object type + tickets directly (no main.py in the isolated harness) ----
db = SessionLocal()
db.add(models.ObjectType(id="ticket", display_name="Ticket", description="", properties={}, created_at=1, updated_at=1))
tickets = [
    ("t1", {"status": "Open", "priority": 5}),
    ("t2", {"status": "In Progress", "priority": 9}),
    ("t3", {"status": "Resolved", "priority": 1}),
    ("t4", {"status": "Open", "priority": 2}),
    ("t5", {"status": "Archived", "priority": 0}),   # value not in board columns -> unassigned
]
for tid, props in tickets:
    db.add(models.ObjectInstance(id=tid, object_type_id="ticket", properties=props, lineage={}, created_at=1, updated_at=1))
db.commit()
db.close()

# board over a missing object type -> 404
ok(client.post("/autopilot/boards", json={"display_name": "x", "object_type_id": "ghost", "columns": ["A"]}), "bad ot", expect=404)

# ---- direct state_property board ----
b = ok(client.post("/autopilot/boards", json={
    "display_name": "Tickets", "object_type_id": "ticket",
    "state_property": "status", "columns": ["Open", "In Progress", "Resolved"]}), "board")
kb = ok(client.get(f"/autopilot/boards/{b['id']}/kanban"), "kanban")
counts = {c["state"]: c["count"] for c in kb["columns"]}
assert counts == {"Open": 2, "In Progress": 1, "Resolved": 1}, counts
assert kb["unassigned"]["count"] == 1, kb            # the Archived ticket
assert kb["total"] == 5, kb
# the right cards landed in the right column
open_ids = {o["id"] for col in kb["columns"] if col["state"] == "Open" for o in col["objects"]}
assert open_ids == {"t1", "t4"}, open_ids

# ---- computed (inferred) state via predicate rules ----
b2 = ok(client.post("/autopilot/boards", json={
    "display_name": "By Priority", "object_type_id": "ticket", "columns": ["Critical", "Normal", "Low"]}), "board2")
# rules evaluated in order; first match wins
ok(client.post(f"/autopilot/boards/{b2['id']}/state-rules", json={"state": "Critical", "prop": "priority", "op": ">=", "value": 8, "rule_order": 0}), "rule crit")
ok(client.post(f"/autopilot/boards/{b2['id']}/state-rules", json={"state": "Low", "prop": "priority", "op": "<=", "value": 2, "rule_order": 2}), "rule low")
ok(client.post(f"/autopilot/boards/{b2['id']}/state-rules", json={"state": "Normal", "prop": "priority", "op": ">", "value": 2, "rule_order": 1}), "rule normal")
rules = ok(client.get(f"/autopilot/boards/{b2['id']}/state-rules"), "list rules")
assert len(rules) == 3, rules
kb2 = ok(client.get(f"/autopilot/boards/{b2['id']}/kanban"), "kanban2")
c2 = {c["state"]: c["count"] for c in kb2["columns"]}
# priorities: t1=5 Normal, t2=9 Critical, t3=1 Low, t4=2 Low, t5=0 Low
assert c2 == {"Critical": 1, "Normal": 1, "Low": 3}, c2

# ---- workflow dependency graph ----
wf = ok(client.post("/autopilot/workflows", json={"display_name": "Onboarding"}), "wf")
ok(client.post(f"/autopilot/workflows/{wf['id']}/steps", json={"id": "s1", "name": "ingest", "step_type": "automation", "depends_on": []}), "s1")
ok(client.post(f"/autopilot/workflows/{wf['id']}/steps", json={"id": "s2", "name": "enrich", "step_type": "function", "depends_on": ["s1"]}), "s2")
ok(client.post(f"/autopilot/workflows/{wf['id']}/steps", json={"id": "s3", "name": "notify", "step_type": "action", "depends_on": ["s2"]}), "s3")
g = ok(client.get(f"/autopilot/workflows/{wf['id']}/dependency-graph"), "graph")
assert g["has_cycle"] is False, g
assert g["topological_order"] == ["s1", "s2", "s3"], g
assert {"from": "s1", "to": "s2"} in g["edges"], g

# cycle detection
wf2 = ok(client.post("/autopilot/workflows", json={"display_name": "Cyclic"}), "wf2")
ok(client.post(f"/autopilot/workflows/{wf2['id']}/steps", json={"id": "a", "name": "a", "depends_on": ["b"]}), "a")
ok(client.post(f"/autopilot/workflows/{wf2['id']}/steps", json={"id": "b", "name": "b", "depends_on": ["a"]}), "b")
g2 = ok(client.get(f"/autopilot/workflows/{wf2['id']}/dependency-graph"), "graph2")
assert g2["has_cycle"] is True and g2["topological_order"] == [], g2

print(f"\nAutopilot verified: {passed} assertions passed.")
engine.dispose()
_tmp.cleanup()

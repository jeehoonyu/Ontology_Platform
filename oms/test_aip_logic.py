"""
Faithful AIP Logic engine conformance test (deep-fidelity pass 2 — AIP).
Verifies the documented block-execution model: variable chaining across blocks,
the 'Use LLM' block (template/summarize/classify), Query Objects + aggregate,
conditional then/else branching, for_each loops, and apply-action.
Run: ./venv312/Scripts/python.exe test_aip_logic.py
"""
import os
import tempfile

tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tmpdir.name, 'aip_logic.db')}"

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


def run_logic(logic_id, inputs):
    return ok(client.post(f"/logic-functions/{logic_id}/run", json={"inputs": inputs}), f"run {logic_id}")


def trace_entry(run, block_type):
    return next((t for t in run["trace"] if t["type"] == block_type), None)


# ---- setup ontology ----
ok(client.post("/object-types", json={"id": "ticket", "display_name": "Ticket", "description": "",
    "properties": {"priority": {"type": "string"}, "points": {"type": "number"}}}), "ticket type")
for tid, pr, pts in [("t1", "high", 5), ("t2", "high", 3), ("t3", "low", 1)]:
    ok(client.post("/objects", json={"id": tid, "object_type_id": "ticket", "properties": {"priority": pr, "points": pts}}), f"obj {tid}")
ok(client.post("/action-types", json={"id": "escalate", "display_name": "Escalate", "description": "",
    "parameters": {"ticket_id": {"type": "string", "required": True}},
    "rules": {"object_mutations": [{"object_type_id": "ticket", "object_id": "$ticket_id", "set": {"priority": "critical"}}]}}), "escalate action")

# ---- 1. variable chaining + llm (template reads a prior block's output) ----
ok(client.post("/logic-functions", json={"id": "lf_chain", "display_name": "Chain", "blocks": [
    {"type": "set_variable", "key": "greeting", "value": "hello"},
    {"type": "llm", "mode": "template", "template": "{greeting} world", "output": "msg"},
]}), "create lf_chain")
r = run_logic("lf_chain", {})
assert r["outputs"]["msg"]["response"] == "hello world", r["outputs"]

# ---- 2. llm classify ----
ok(client.post("/logic-functions", json={"id": "lf_llm", "display_name": "LLM", "blocks": [
    {"type": "llm", "mode": "classify", "prompt": "$text", "labels": ["billing", "outage", "feature"], "output": "label"},
]}), "create lf_llm")
r = run_logic("lf_llm", {"text": "we have a major outage in prod"})
assert r["outputs"]["label"]["response"] == "outage", r["outputs"]["label"]

# ---- 3. object_query + object_aggregate ----
ok(client.post("/logic-functions", json={"id": "lf_query", "display_name": "Query", "blocks": [
    {"type": "object_query", "object_type_id": "ticket", "filters": {"priority": "high"}, "output": "q"},
    {"type": "object_aggregate", "object_type_id": "ticket", "op": "sum", "field": "points", "filters": {"priority": "high"}, "output": "agg"},
]}), "create lf_query")
r = run_logic("lf_query", {})
assert r["outputs"]["q"]["count"] == 2, r["outputs"]["q"]
assert r["outputs"]["agg"]["value"] == 8, r["outputs"]["agg"]

# ---- 4. conditional: then branch ----
ok(client.post("/logic-functions", json={"id": "lf_cond_then", "display_name": "CondThen", "blocks": [
    {"type": "conditional",
     "condition": {"object_count": {"object_type_id": "ticket", "filters": {"priority": "high"}}, "op": "gte", "value": 2},
     "then": [{"type": "set_variable", "key": "branch", "value": "many"}],
     "else": [{"type": "set_variable", "key": "branch", "value": "few"}]},
]}), "create lf_cond_then")
r = run_logic("lf_cond_then", {})
assert r["outputs"]["branch"] == "many", r["outputs"]

# ---- 5. conditional: else branch ----
ok(client.post("/logic-functions", json={"id": "lf_cond_else", "display_name": "CondElse", "blocks": [
    {"type": "conditional",
     "condition": {"object_count": {"object_type_id": "ticket", "filters": {"priority": "high"}}, "op": "gte", "value": 5},
     "then": [{"type": "set_variable", "key": "branch", "value": "many"}],
     "else": [{"type": "set_variable", "key": "branch", "value": "few"}]},
]}), "create lf_cond_else")
r = run_logic("lf_cond_else", {})
assert r["outputs"]["branch"] == "few", r["outputs"]

# ---- 6. for_each over an input list ----
ok(client.post("/logic-functions", json={"id": "lf_loop", "display_name": "Loop", "blocks": [
    {"type": "for_each", "items": "$nums", "item_var": "x", "blocks": [
        {"type": "set_variable", "key": "last", "value": "$x"}]},
]}), "create lf_loop")
r = run_logic("lf_loop", {"nums": [1, 2, 3]})
assert r["outputs"]["last"] == 3, r["outputs"]
fe = trace_entry(r, "for_each")
assert fe and fe["result"]["iterations"] == 3, fe

# ---- 7. for_each over an object set (object_type_id form) ----
ok(client.post("/logic-functions", json={"id": "lf_loop_obj", "display_name": "LoopObj", "blocks": [
    {"type": "for_each", "object_type_id": "ticket", "filters": {"priority": "high"}, "item_var": "t", "blocks": [
        {"type": "set_variable", "key": "last_id", "value": "$t"}]},
]}), "create lf_loop_obj")
r = run_logic("lf_loop_obj", {})
fe = trace_entry(r, "for_each")
assert fe and fe["result"]["iterations"] == 2, fe

# ---- 8. apply_action (real mutation through the action engine) ----
ok(client.post("/logic-functions", json={"id": "lf_apply", "display_name": "Apply", "blocks": [
    {"type": "apply_action", "action_type_id": "escalate", "parameters": {"ticket_id": "$ticket_id"}, "output": "applied"},
]}), "create lf_apply")
r = run_logic("lf_apply", {"ticket_id": "t3"})
assert "t3" in r["outputs"]["applied"]["mutated_object_ids"], r["outputs"]
t3 = ok(client.get("/objects/ticket/t3"), "get t3")
assert t3["properties"]["priority"] == "critical", t3

print(f"\nAIP Logic faithful engine verified: {passed} assertions passed.")
from app.database import engine as _engine  # noqa: E402
_engine.dispose()
tmpdir.cleanup()

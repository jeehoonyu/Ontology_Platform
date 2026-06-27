"""
Deep-fidelity pass 3 (rest of AIP) conformance test: Agent Studio tool-calling +
retrieval, Evals graders + metrics, and Document Intelligence strategies.
Run: ./venv312/Scripts/python.exe test_aip_extended.py
"""
import os
import tempfile

tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tmpdir.name, 'aip_ext.db')}"

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


# ---------------- setup ----------------
ok(client.post("/object-types", json={"id": "incident", "display_name": "Incident", "description": "",
    "properties": {"severity": {"type": "string"}, "points": {"type": "number"}}}), "incident type")
for iid, sev, pts in [("i1", "high", 5), ("i2", "high", 3), ("i3", "low", 1)]:
    ok(client.post("/objects", json={"id": iid, "object_type_id": "incident", "properties": {"severity": sev, "points": pts}}), f"obj {iid}")
ok(client.post("/action-types", json={"id": "escalate_incident", "display_name": "Escalate", "description": "",
    "parameters": {"incident_id": {"type": "string", "required": True}}, "rules": {"requires_approval": True}}), "escalate action")
ok(client.post("/ontology-functions", json={"id": "incident_count", "display_name": "Count", "kind": "compute",
    "object_type_id": "incident", "expression": {"type": "aggregate", "op": "count"}}), "count fn")
ok(client.post("/agents", json={"id": "ops_agent", "display_name": "Ops Agent", "description": "",
    "allowed_object_types": ["incident"], "allowed_actions": ["escalate_incident"]}), "agent")

# ============ Agent Studio tool-calling ============
ok(client.put("/aip/agents/ops_agent/tools", json={
    "tools": [
        {"name": "find_incidents", "type": "object_query", "object_type_id": "incident", "filters": {"severity": "high"}, "trigger": "incident"},
        {"name": "escalate", "type": "action", "action_type_id": "escalate_incident", "trigger": "escalate"},
        {"name": "count_fn", "type": "function", "function_id": "incident_count", "trigger": "count"},
        {"name": "help", "type": "command", "command": "help", "response": "I query and escalate incidents.", "trigger": "help"},
    ],
    "retrieval": {"ontology": ["incident"]},
}), "configure tools")

inv = ok(client.post("/aip/agents/ops_agent/invoke", json={"prompt": "please escalate the incident now", "parameters": {"incident_id": "i1"}}), "invoke agent")
tools_used = {tc["tool"] for tc in inv["tool_calls"]}
assert {"find_incidents", "escalate"} <= tools_used, tools_used        # both triggers present in prompt
assert inv["retrieval"]["retrieved_object_count"] == 3, inv["retrieval"]
fi = next(tc for tc in inv["tool_calls"] if tc["tool"] == "find_incidents")
assert fi["output"]["count"] == 2, fi                                  # 2 high-severity
assert inv["proposed_actions"] and inv["proposed_actions"][0]["action_type_id"] == "escalate_incident", inv["proposed_actions"]
assert inv["proposed_actions"][0]["parameters"]["incident_id"] == "i1", inv["proposed_actions"]

# forced tool selection -> function tool only
inv2 = ok(client.post("/aip/agents/ops_agent/invoke", json={"prompt": "anything", "select": ["count_fn"]}), "invoke select")
assert len(inv2["tool_calls"]) == 1 and inv2["tool_calls"][0]["output"]["output"] == 3, inv2["tool_calls"]

# ============ Evals graders ============
assert "regex" in ok(client.get("/aip/evals/grader-types"), "grader types")["grader_types"]
g = ok(client.post("/aip/evals/grade", json={
    "actual": {"answer": "outage detected", "score": 0.9, "items": [1, 2, 3]},
    "graders": [
        {"id": "g1", "type": "contains", "path": "answer", "expected": "outage"},
        {"id": "g2", "type": "numeric", "path": "score", "op": "gte", "value": 0.8},
        {"id": "g3", "type": "length", "path": "items", "op": "eq", "value": 3},
        {"id": "g4", "type": "exact_match", "path": "answer", "expected": "nope"},
    ]}), "grade")
assert g["metrics"]["total"] == 4 and g["metrics"]["passed"] == 3, g["metrics"]
assert g["metrics"]["pass_rate"] == 0.75, g["metrics"]

# grade-logic: run an AIP Logic function per case and grade its outputs
ok(client.post("/logic-functions", json={"id": "lf_eval", "display_name": "EvalLogic",
    "blocks": [{"type": "object_aggregate", "object_type_id": "incident", "op": "count", "output": "agg"}]}), "lf_eval")
gl = ok(client.post("/aip/evals/grade-logic", json={
    "logic_function_id": "lf_eval",
    "cases": [{"id": "c1", "inputs": {}, "graders": [{"type": "numeric", "path": "outputs.agg.value", "op": "eq", "value": 3}]}]}), "grade-logic")
assert gl["metrics"]["passed"] == 1 and gl["metrics"]["pass_rate"] == 1.0, gl["metrics"]

# ============ Document Intelligence strategies ============
assert "chunk" in ok(client.get("/aip/document-intelligence/strategies"), "strategies")["strategies"]
raw = ok(client.post("/aip/document-intelligence/process", json={"text": "Hello   world\nfoo", "strategy": "raw_text"}), "raw_text")
assert raw["word_count"] == 3 and raw["text"] == "Hello world foo", raw
lay = ok(client.post("/aip/document-intelligence/process", json={"text": "Title\nbody line\n\nSection Two\nmore detail", "strategy": "layout"}), "layout")
assert lay["section_count"] == 2, lay
cls = ok(client.post("/aip/document-intelligence/process", json={"text": "the prod server had an outage", "strategy": "classify", "labels": ["billing", "outage", "feature"]}), "classify")
assert cls["label"] == "outage", cls
ent = ok(client.post("/aip/document-intelligence/process", json={"text": "mail a@b.com on 2024-01-02", "strategy": "entities"}), "entities")
assert "a@b.com" in ent["entities"]["emails"], ent

long_text = " ".join(f"word{i}" for i in range(100))
ch = ok(client.post("/aip/document-intelligence/chunk", json={"text": long_text, "chunk_size": 30, "overlap": 5}), "chunk")
assert ch["chunk_count"] == 4, ch["chunk_count"]
assert all(len(c["embedding"]) == 16 for c in ch["chunks"]), "embedding dim"

print(f"\nAIP (Agent Studio + Evals + Document Intelligence) verified: {passed} assertions passed.")
from app.database import engine as _engine  # noqa: E402
_engine.dispose()
tmpdir.cleanup()

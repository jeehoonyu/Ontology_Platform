"""Durable agent context/tool/synthesis graphs recover without unsafe mutations."""

import os
import tempfile


tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tmpdir.name, 'agent_graph.db')}"
os.environ["AUTH_MODE"] = "local"
os.environ["APP_ENV"] = "test"

from fastapi.testclient import TestClient  # noqa: E402
from app.aip_agents import AgentToolRun  # noqa: E402
from app.database import SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.models_action import ApprovalRequest  # noqa: E402
from app.platform_runtime import PlatformJob  # noqa: E402


client = TestClient(app)
passed = 0


def ok(response, label, expected=200):
    global passed
    assert response.status_code == expected, f"{label}: {response.status_code} {response.text[:2000]}"
    passed += 1
    return response.json() if response.content else {}


ok(client.post("/object-types", json={
    "id": "graph_incident", "display_name": "Graph Incident",
    "properties": {"severity": {"type": "string"}},
}), "create object type")
ok(client.post("/objects", json={
    "id": "graph-incident-1", "object_type_id": "graph_incident",
    "properties": {"severity": "critical"},
}), "create object")
ok(client.post("/action-types", json={
    "id": "graph_escalate", "display_name": "Escalate graph incident",
    "parameters": {"incident_id": {"type": "string", "required": True}},
    "rules": {"requires_approval": True, "risk_level": "high"},
}), "create governed action")
ok(client.post("/agents", json={
    "id": "graph_agent", "display_name": "Durable Graph Agent",
    "allowed_object_types": ["graph_incident"], "allowed_actions": ["graph_escalate"],
}), "create agent")
ok(client.put("/aip/agents/graph_agent/tools", json={
    "tools": [
        {"name": "find incidents", "type": "object_query", "object_type_id": "graph_incident", "trigger": "incident"},
        {"name": "escalate", "type": "action", "action_type_id": "graph_escalate", "trigger": "escalate"},
    ],
    "retrieval": {"ontology": ["graph_incident"], "documents": ["operations-handbook-v1"]},
}), "configure tools")

body = {
    "prompt": "escalate the critical incident",
    "parameters": {"incident_id": "graph-incident-1"},
    "idempotency_key": "durable-agent-graph-1",
}
coordinator = ok(client.post("/api/v1/agents/graph_agent/task-graphs", json=body), "enqueue graph", 202)
replay = ok(client.post("/api/v1/agents/graph_agent/task-graphs", json=body), "replay graph", 202)
assert coordinator["id"] == replay["id"]
assert coordinator["status"] == "BLOCKED" and coordinator["job_type"] == "aip.agent.synthesize"
graph = coordinator["agent_task_graph"]
assert graph["tool_count"] == 2 and len(graph["tool_job_ids"]) == 2
assert replay["agent_task_graph"] == graph

context = ok(client.get(f"/jobs/{graph['context_job_id']}"), "inspect context")
assert context["status"] == "QUEUED" and context["job_type"] == "aip.agent.context"
for tool_id in graph["tool_job_ids"]:
    tool = ok(client.get(f"/jobs/{tool_id}"), "inspect blocked tool")
    assert tool["status"] == "BLOCKED" and tool["dependencies"][0]["id"] == context["id"]

context_run = ok(client.post("/aip/agents/workers/run-next", json={
    "worker_id": "agent-graph-worker", "job_id": context["id"],
}), "execute context")
assert context_run["job"]["status"] == "SUCCEEDED"
assert context_run["result"]["retrieval"]["retrieved_object_count"] == 1

for tool_id in graph["tool_job_ids"]:
    tool_run = ok(client.post("/aip/agents/workers/run-next", json={
        "worker_id": "agent-graph-worker", "job_id": tool_id,
    }), "execute tool")
    assert tool_run["job"]["status"] == "SUCCEEDED", tool_run
    assert tool_run["result"]["tool_call"]["citations"]

with SessionLocal() as db:
    assert db.query(ApprovalRequest).count() == 0
    assert db.query(AgentToolRun).count() == 0
passed += 1

ready = ok(client.get(f"/api/v1/agents/tasks/{coordinator['id']}"), "inspect ready coordinator")
assert ready["status"] == "QUEUED" and ready["agent_task_graph"]["tool_count"] == 2
synthesized = ok(client.post("/aip/agents/workers/run-next", json={
    "worker_id": "agent-graph-synthesizer", "job_id": coordinator["id"],
}), "synthesize graph")
assert synthesized["job"]["status"] == "SUCCEEDED", synthesized
result = synthesized["result"]
assert result["task_graph_id"] == graph["group_id"]
assert result["policy_summary"]["decision"] == "APPROVAL_REQUIRED"
assert result["policy_summary"]["direct_mutations"] == 0
assert len(result["tool_calls"]) == 2 and len(result["proposed_actions"]) == 1
approval_id = result["proposed_actions"][0]["approval_request_id"]
assert approval_id and result["proposed_actions"][0]["executed"] is False
with SessionLocal() as db:
    assert db.query(ApprovalRequest).count() == 1
    assert db.query(AgentToolRun).count() == 1
passed += 1

# A failed tool deterministically fails the synthesis dependency. Repairing and
# graph-aware retry resumes only failed/cancelled stages and commits once.
failed_body = {**body, "idempotency_key": "durable-agent-graph-recovery"}
failed_graph_job = ok(client.post(
    "/api/v1/agents/graph_agent/task-graphs", json=failed_body,
), "enqueue recoverable graph", 202)
failed_graph = failed_graph_job["agent_task_graph"]
ok(client.post("/aip/agents/workers/run-next", json={
    "worker_id": "agent-graph-worker", "job_id": failed_graph["context_job_id"],
}), "execute recovery context")
broken_tool_id = failed_graph["tool_job_ids"][1]
with SessionLocal() as db:
    broken = db.get(PlatformJob, broken_tool_id)
    payload = dict(broken.payload or {})
    tool = dict(payload["tool"])
    tool["action_type_id"] = "missing-action"
    payload["tool"] = tool
    broken.payload = payload
    db.commit()
passed += 1
ok(client.post("/aip/agents/workers/run-next", json={
    "worker_id": "agent-graph-worker", "job_id": failed_graph["tool_job_ids"][0],
}), "execute healthy recovery tool")
broken_run = ok(client.post("/aip/agents/workers/run-next", json={
    "worker_id": "agent-graph-worker", "job_id": broken_tool_id,
}), "fail broken tool")
assert broken_run["job"]["status"] == "FAILED"
failed_finalizer = ok(client.get(f"/jobs/{failed_graph_job['id']}"), "inspect dependency failure")
assert failed_finalizer["status"] == "FAILED" and "dependency" in failed_finalizer["error"].lower()
with SessionLocal() as db:
    assert db.query(ApprovalRequest).count() == 1
    assert db.query(AgentToolRun).count() == 1
    broken = db.get(PlatformJob, broken_tool_id)
    payload = dict(broken.payload or {})
    tool = dict(payload["tool"])
    tool["action_type_id"] = "graph_escalate"
    payload["tool"] = tool
    broken.payload = payload
    db.commit()
passed += 1
retried = ok(client.post(f"/api/v1/agents/tasks/{failed_graph_job['id']}/retry"), "retry graph")
assert retried["status"] == "BLOCKED" and retried["attempt"] == 2
repaired_tool = ok(client.post("/aip/agents/workers/run-next", json={
    "worker_id": "agent-graph-worker", "job_id": broken_tool_id,
}), "execute repaired tool")
assert repaired_tool["job"]["status"] == "SUCCEEDED" and repaired_tool["job"]["attempt"] == 2
recovered = ok(client.post("/aip/agents/workers/run-next", json={
    "worker_id": "agent-graph-synthesizer", "job_id": failed_graph_job["id"],
}), "synthesize recovered graph")
assert recovered["job"]["status"] == "SUCCEEDED" and recovered["job"]["attempt"] == 2
with SessionLocal() as db:
    assert db.query(ApprovalRequest).count() == 2
    assert db.query(AgentToolRun).count() == 2
passed += 1

cancelled = ok(client.post("/api/v1/agents/graph_agent/task-graphs", json={
    **body, "idempotency_key": "durable-agent-graph-cancel",
}), "enqueue cancellable graph", 202)
cancelled_graph = cancelled["agent_task_graph"]
cancelled_result = ok(client.post(f"/api/v1/agents/tasks/{cancelled['id']}/cancel"), "cancel graph")
assert cancelled_result["status"] == "CANCELLED"
for child_id in [cancelled_graph["context_job_id"], *cancelled_graph["tool_job_ids"]]:
    child = ok(client.get(f"/jobs/{child_id}"), "inspect cancelled graph stage")
    assert child["status"] == "CANCELLED", child

# A prompt that selects no tool still has a useful context -> synthesis path.
context_only = ok(client.post("/api/v1/agents/graph_agent/task-graphs", json={
    "prompt": "summarize available context",
    "select": [],
    "idempotency_key": "durable-agent-context-only",
}), "enqueue context-only graph", 202)
context_only_graph = context_only["agent_task_graph"]
assert context_only_graph["tool_count"] == 0 and context_only_graph["tool_job_ids"] == []
ok(client.post("/aip/agents/workers/run-next", json={
    "worker_id": "agent-context-worker", "job_id": context_only_graph["context_job_id"],
}), "execute context-only retrieval")
context_only_result = ok(client.post("/aip/agents/workers/run-next", json={
    "worker_id": "agent-context-synthesizer", "job_id": context_only["id"],
}), "synthesize context-only graph")
assert context_only_result["job"]["status"] == "SUCCEEDED"
assert context_only_result["result"]["tool_calls"] == []
assert context_only_result["result"]["policy_summary"]["decision"] == "ALLOWED"

# Parallelism is an explicit per-request safety and cost boundary.
limited = client.post("/api/v1/agents/graph_agent/task-graphs", json={
    **body,
    "idempotency_key": "durable-agent-graph-limited",
    "max_parallel_tools": 1,
})
assert limited.status_code == 422, limited.text
limited_detail = limited.json()["detail"]
assert limited_detail["selected_tools"] == 2 and limited_detail["max_parallel_tools"] == 1
passed += 1

print(f"\nDurable governed agent task graphs verified: {passed} assertions passed.")
engine.dispose()
tmpdir.cleanup()

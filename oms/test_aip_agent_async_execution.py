"""AIP Agent Studio invocation through durable worker jobs and approval gates."""
import os
import tempfile

tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tmpdir.name, 'aip_agent_async.db')}"
os.environ["AUTH_MODE"] = "local"
os.environ["APP_ENV"] = "test"

from fastapi import HTTPException  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from app.aip_agents import AgentToolRun, InvokeRequest, _invoke_agent  # noqa: E402
from app.database import SessionLocal  # noqa: E402
from app.main import app  # noqa: E402
from app.models_action import ApprovalRequest  # noqa: E402

client = TestClient(app)
passed = 0


def ok(response, label, expect=200):
    global passed
    assert response.status_code == expect, f"{label}: {response.status_code} {response.text[:1000]}"
    passed += 1
    return response.json() if response.content else {}


ok(client.post("/object-types", json={
    "id": "async_incident",
    "display_name": "Async Incident",
    "properties": {"severity": {"type": "string"}},
}), "create incident type")
ok(client.post("/objects", json={
    "id": "incident-1",
    "object_type_id": "async_incident",
    "properties": {"severity": "critical"},
}), "create incident")
ok(client.post("/action-types", json={
    "id": "async_escalate",
    "display_name": "Escalate incident",
    "parameters": {"incident_id": {"type": "string", "required": True}},
    "rules": {"requires_approval": True},
}), "create governed action")
ok(client.post("/agents", json={
    "id": "async_ops_agent",
    "display_name": "Async Operations Agent",
    "allowed_object_types": ["async_incident"],
    "allowed_actions": ["async_escalate"],
}), "create agent")
ok(client.put("/aip/agents/async_ops_agent/tools", json={
    "tools": [
        {"name": "find incidents", "type": "object_query", "object_type_id": "async_incident", "trigger": "incident"},
        {"name": "escalate", "type": "action", "action_type_id": "async_escalate", "trigger": "escalate"},
    ],
    "retrieval": {"ontology": ["async_incident"]},
}), "configure agent tools")

queued = ok(client.post("/api/v1/agents/async_ops_agent/tasks", json={
    "prompt": "escalate the critical incident",
    "parameters": {"incident_id": "incident-1"},
    "idempotency_key": "agent-invocation-v1",
}), "enqueue agent invocation", 202)
replayed = ok(client.post("/aip/agents/async_ops_agent/invoke/async", json={
    "prompt": "escalate the critical incident",
    "parameters": {"incident_id": "incident-1"},
    "idempotency_key": "agent-invocation-v1",
}), "replay agent enqueue", 202)
assert replayed["id"] == queued["id"], (queued, replayed)

executed = ok(client.post("/aip/agents/workers/run-next", json={
    "worker_id": "agent-worker-test",
    "job_id": queued["id"],
}), "execute agent invocation")
assert executed["job"]["status"] == "SUCCEEDED", executed
result = executed["result"]
assert result["policy_summary"] == {
    "decision": "APPROVAL_REQUIRED",
    "approval_requests": 1,
    "proposed_actions": 1,
    "denied_tools": 0,
    "direct_mutations": 0,
}, result
assert result["retrieval"]["retrieved_object_count"] == 1, result
assert all(call["citations"] and call["duration_ms"] >= 1 for call in result["tool_calls"]), result
proposal = result["proposed_actions"][0]
assert proposal["executed"] is False and proposal["approval_request_id"], proposal

approval = ok(client.get("/approvals?status=PENDING"), "inspect staged approval")
assert any(row["id"] == proposal["approval_request_id"] for row in approval), approval
runs = ok(client.get("/aip/agents/async_ops_agent/runs"), "inspect persisted agent runs")
assert len(runs) == 1 and runs[0]["execution_job_id"] == queued["id"], runs
detail = ok(client.get(f"/jobs/{queued['id']}"), "inspect job trace")
assert [event["event_type"] for event in detail["events"]] == ["job.queued", "job.claimed", "job.progress", "job.succeeded"], detail
task_detail = ok(client.get(f"/api/v1/agents/tasks/{queued['id']}"), "inspect versioned agent task")
assert task_detail["id"] == queued["id"] and task_detail["job_type"] == "aip.agent.invoke", task_detail

denied = ok(client.post("/aip/agents/async_ops_agent/invoke", json={
    "prompt": "escalate",
    "parameters": {},
}), "deny invalid action proposal")
assert denied["policy_summary"]["decision"] == "DENIED", denied
assert denied["policy_summary"]["denied_tools"] == 1 and not denied["proposed_actions"], denied
assert denied["tool_calls"][0]["output"]["validation_errors"], denied

cancelled_job = ok(client.post("/aip/agents/async_ops_agent/invoke/async", json={
    "prompt": "incident",
    "idempotency_key": "agent-cancel-v1",
}), "enqueue cancellable invocation", 202)
ok(client.post(f"/jobs/{cancelled_job['id']}/cancel"), "cancel queued invocation")
empty = ok(client.post("/aip/agents/workers/run-next", json={"worker_id": "agent-worker-test"}), "skip cancelled invocation")
assert empty["job"] is None, empty
ok(client.post(f"/jobs/{cancelled_job['id']}/retry"), "retry cancelled invocation")
retried_run = ok(client.post("/aip/agents/workers/run-next", json={
    "worker_id": "agent-worker-test",
    "job_id": cancelled_job["id"],
}), "execute retried invocation")
assert retried_run["job"]["status"] == "SUCCEEDED" and retried_run["job"]["attempt"] == 2, retried_run

guard_job = ok(client.post("/aip/agents/async_ops_agent/invoke/async", json={
    "prompt": "escalate incident",
    "parameters": {"incident_id": "incident-1"},
    "idempotency_key": "agent-guard-v1",
}), "enqueue guarded invocation", 202)
claim = ok(client.post("/jobs/claim", json={
    "worker_id": "agent-worker-guard-test",
    "supported_job_types": ["aip.agent.invoke"],
    "job_id": guard_job["id"],
}), "claim guarded invocation")["job"]
ok(client.post(f"/jobs/{guard_job['id']}/cancel"), "cancel invocation before commit")
with SessionLocal() as db:
    run_count = db.query(AgentToolRun).count()
    approval_count = db.query(ApprovalRequest).count()
    try:
        _invoke_agent(
            "async_ops_agent",
            InvokeRequest(prompt="escalate incident", parameters={"incident_id": "incident-1"}),
            db,
            execution_job_id=guard_job["id"],
            execution_lease_token=claim["lease_token"],
        )
        raise AssertionError("Cancelled agent invocation committed")
    except HTTPException as exc:
        assert exc.status_code == 409, exc
    assert db.query(AgentToolRun).count() == run_count
    assert db.query(ApprovalRequest).count() == approval_count
passed += 1

bad_job = ok(client.post("/jobs", json={
    "job_type": "aip.agent.invoke",
    "subject_type": "agent",
    "subject_id": "missing-agent",
    "payload": {"agent_id": "missing-agent", "prompt": "run"},
    "max_attempts": 3,
}), "enqueue missing-agent invocation", 201)
bad_run = ok(client.post("/aip/agents/workers/run-next", json={
    "worker_id": "agent-worker-test",
    "job_id": bad_job["id"],
}), "fail missing-agent invocation")
assert bad_run["job"]["status"] == "FAILED" and bad_run["job"]["attempt"] == 1, bad_run

print(f"\nAsynchronous AIP agent execution verified: {passed} assertions passed.")
from app.database import engine as _engine  # noqa: E402
_engine.dispose()
tmpdir.cleanup()

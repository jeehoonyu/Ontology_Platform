"""Actions, approvals, AIP Logic, and agents enforce one project boundary."""
import os
import tempfile


tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tmpdir.name, 'governed_automation_tenancy.db')}"
os.environ["AUTH_MODE"] = "local"
os.environ["APP_ENV"] = "test"

from fastapi.testclient import TestClient  # noqa: E402
from app import models, models_action, production_auth  # noqa: E402
from app.database import SessionLocal  # noqa: E402
from app.main import app  # noqa: E402

client = TestClient(app)
passed = 0


def ok(response, label, expect=200):
    global passed
    assert response.status_code == expect, f"{label}: {response.status_code} {response.text[:1600]}"
    passed += 1
    return response.json() if response.content else {}


ok(client.post("/tenancy/organizations", json={"id": "automation-org", "display_name": "Automation Org"}), "create organization", 201)
for project_id in ("alpha-automation", "beta-automation"):
    ok(client.post("/tenancy/projects", json={
        "id": project_id, "organization_id": "automation-org", "display_name": project_id,
    }), f"create {project_id}", 201)

with SessionLocal() as db:
    db.add_all([
        models.ObjectType(
            id="alpha-case", display_name="Alpha case", description=None,
            properties={"id": {"type": "string"}, "state": {"type": "string"}, "__manager": {"project_id": "alpha-automation"}},
            created_at=1, updated_at=1,
        ),
        models.ObjectType(
            id="beta-case", display_name="Beta case", description=None,
            properties={"id": {"type": "string"}, "state": {"type": "string"}, "__manager": {"project_id": "beta-automation"}},
            created_at=1, updated_at=1,
        ),
        models.ObjectInstance(id="alpha-case-1", object_type_id="alpha-case", properties={"id": "alpha-case-1", "state": "open"}, source_asset_id=None, lineage={}, created_at=1, updated_at=1),
        models.ObjectInstance(id="beta-case-1", object_type_id="beta-case", properties={"id": "beta-case-1", "state": "open"}, source_asset_id=None, lineage={}, created_at=1, updated_at=1),
    ])
    db.commit()

all_permissions = ["view", "edit", "execute", "approve", "publish", "restore", "export", "administer"]
alpha = production_auth.Principal("alpha-automation-user", "Alpha", None, ["administrator"], all_permissions, organization_id="automation-org", project_ids=["alpha-automation"])
beta = production_auth.Principal("beta-automation-user", "Beta", None, ["administrator"], all_permissions, organization_id="automation-org", project_ids=["beta-automation"])
viewer = production_auth.Principal("alpha-automation-viewer", "Viewer", None, ["viewer"], ["view"], organization_id="automation-org", project_ids=["alpha-automation"])
approver = production_auth.Principal("alpha-automation-approver", "Approver", None, ["approver"], ["view", "approve"], organization_id="automation-org", project_ids=["alpha-automation"])

app.dependency_overrides[production_auth.current_principal] = lambda: alpha
alpha_action = ok(client.post("/action-types", json={
    "id": "alpha-close-case", "project_id": "alpha-automation", "display_name": "Close alpha case", "description": "Critical close",
    "parameters": {"case_id": {"type": "string", "required": True}},
    "rules": {
        "risk_level": "critical",
        "object_mutations": [{"object_type_id": "alpha-case", "object_id": "$case_id", "set": {"state": "closed"}}],
    },
}), "create alpha action")
assert alpha_action["project_id"] == "alpha-automation"
ok(client.post("/ontology/action-types/alpha-close-case/execute", json={
    "parameters": {"case_id": "alpha-case-1"},
}), "legacy route cannot bypass approval", 409)
ok(client.post("/action-types", json={
    "id": "foreign-action", "project_id": "alpha-automation", "display_name": "Foreign", "description": None,
    "parameters": {}, "rules": {"mutations": [{"object_type_id": "beta-case", "op": "modify-object"}]},
}), "reject foreign object mutation", 403)

with SessionLocal() as db:
    db.add(models.ActionType(
        id="legacy-cross-project", project_id="alpha-automation", display_name="Legacy cross-project",
        description=None, parameters={}, rules={
            "mutations": [{"op": "modify-object", "object_type_id": "beta-case", "object_id": "beta-case-1"}],
        },
    ))
    db.commit()
ok(client.post("/ontology/action-types/legacy-cross-project/execute", json={
    "parameters": {},
}), "legacy route cannot mutate another project", 409)

staged = ok(client.post("/actions/execute", json={
    "action_type_id": "alpha-close-case", "parameters": {"case_id": "alpha-case-1"},
    "idempotency_key": "alpha-close-once", "actor": "spoofed",
}), "stage critical action")
assert staged["status"] == "REQUIRES_APPROVAL"
approval_id = staged["approval_request_id"]
alpha_approvals = ok(client.get("/approvals"), "list alpha approvals")
assert [row["id"] for row in alpha_approvals] == [approval_id]
assert alpha_approvals[0]["project_id"] == "alpha-automation"

logic = ok(client.post("/logic-functions", json={
    "id": "alpha-triage", "project_id": "alpha-automation", "display_name": "Alpha triage", "description": None,
    "blocks": [
        {"type": "object_query", "object_type_id": "alpha-case", "output": "cases"},
        {"type": "propose_action", "action_type_id": "alpha-close-case", "parameters": {"case_id": "alpha-case-1"}},
    ],
}), "create alpha logic")
assert logic["project_id"] == "alpha-automation"
logic_run = ok(client.post("/logic-functions/alpha-triage/run", json={"inputs": {}, "actor": "spoofed"}), "run alpha logic")
assert logic_run["status"] == "ACTION_PROPOSED"
ok(client.post("/logic-functions", json={
    "id": "foreign-logic", "project_id": "alpha-automation", "display_name": "Foreign logic", "description": None,
    "blocks": [{"type": "object_query", "object_type_id": "beta-case"}],
}), "reject foreign logic reference", 403)

agent = ok(client.post("/agents", json={
    "id": "alpha-agent", "project_id": "alpha-automation", "display_name": "Alpha agent", "description": None,
    "allowed_object_types": ["alpha-case"], "allowed_actions": ["alpha-close-case"], "approval_required": True,
}), "create alpha agent")
assert agent["project_id"] == "alpha-automation"
ok(client.put("/aip/agents/alpha-agent/tools", json={
    "retrieval": {"ontology": ["alpha-case"]},
    "tools": [
        {"name": "cases", "type": "object_query", "object_type_id": "alpha-case", "always": True},
        {"name": "close", "type": "action", "action_type_id": "alpha-close-case", "always": True},
    ],
}), "configure alpha agent")
invoked = ok(client.post("/aip/agents/alpha-agent/invoke", json={
    "prompt": "close case", "parameters": {"case_id": "alpha-case-1"},
}), "invoke alpha agent")
assert invoked["policy_summary"]["decision"] == "APPROVAL_REQUIRED"
agent_approval_id = invoked["proposed_actions"][0]["approval_request_id"]
async_job = ok(client.post("/aip/agents/alpha-agent/invoke/async", json={
    "prompt": "inspect case", "parameters": {}, "select": ["cases"], "idempotency_key": "alpha-agent-job",
}), "enqueue alpha agent", 202)
assert async_job["project_id"] == "alpha-automation"
task_graph = ok(client.post("/api/v1/agents/alpha-agent/task-graphs", json={
    "prompt": "inspect case", "parameters": {}, "select": ["cases"],
    "idempotency_key": "alpha-agent-task-graph",
}), "enqueue project-owned agent task graph", 202)
assert task_graph["project_id"] == "alpha-automation"
assert task_graph["agent_task_graph"]["tool_count"] == 1

app.dependency_overrides[production_auth.current_principal] = lambda: beta
assert ok(client.get("/action-types"), "filter beta actions") == []
assert ok(client.get("/approvals"), "filter beta approvals") == []
assert ok(client.get("/logic-functions"), "filter beta logic") == []
assert ok(client.get("/agents"), "filter beta agents") == []
for method, path, body in (
    (client.patch, "/action-types/alpha-close-case", {"display_name": "stolen"}),
    (client.post, "/actions/execute", {"action_type_id": "alpha-close-case", "parameters": {"case_id": "alpha-case-1"}, "idempotency_key": "stolen", "actor": "beta"}),
    (client.post, f"/approvals/{approval_id}/decision", {"actor": "beta", "decision": "APPROVED"}),
    (client.post, "/logic-functions/alpha-triage/run", {"inputs": {}}),
    (client.get, "/aip/agents/alpha-agent/tools", None),
    (client.post, "/aip/agents/alpha-agent/invoke", {"prompt": "steal", "parameters": {}}),
    (client.get, f"/jobs/{async_job['id']}", None),
    (client.get, f"/api/v1/agents/tasks/{task_graph['id']}", None),
    (client.post, "/api/v1/agents/alpha-agent/task-graphs", {"prompt": "steal", "parameters": {}}),
):
    response = method(path, json=body) if body is not None and method is not client.get else method(path)
    ok(response, f"deny cross-project {path}", 403)

beta_action = ok(client.post("/action-types", json={
    "id": "beta-note-case", "project_id": "beta-automation", "display_name": "Note beta case", "description": None,
    "parameters": {}, "rules": {"object_mutations": []},
}), "create beta action")
assert beta_action["project_id"] == "beta-automation"

app.dependency_overrides[production_auth.current_principal] = lambda: viewer
assert {row["id"] for row in ok(client.get("/action-types"), "viewer reads actions")} == {
    "alpha-close-case", "legacy-cross-project",
}
assert {row["id"] for row in ok(client.get("/approvals"), "viewer reads approvals")} == {approval_id, agent_approval_id}
ok(client.post("/actions/execute", json={
    "action_type_id": "alpha-close-case", "parameters": {"case_id": "alpha-case-1"}, "idempotency_key": "viewer", "actor": "viewer",
}), "viewer cannot execute action", 403)
ok(client.post(f"/approvals/{approval_id}/decision", json={"actor": "viewer", "decision": "APPROVED"}), "viewer cannot approve", 403)
ok(client.post("/logic-functions/alpha-triage/run", json={"inputs": {}}), "viewer cannot run logic", 403)
ok(client.get("/aip/agents/alpha-agent/tools"), "viewer reads agent config")
ok(client.post("/aip/agents/alpha-agent/invoke", json={"prompt": "run", "parameters": {}}), "viewer cannot invoke agent", 403)

app.dependency_overrides[production_auth.current_principal] = lambda: approver
approved = ok(client.post(f"/approvals/{approval_id}/decision", json={
    "actor": "spoofed", "decision": "APPROVED", "reason": "Reviewed",
}), "approve alpha action")
assert approved["status"] == "APPROVED"

app.dependency_overrides[production_auth.current_principal] = lambda: alpha
executed = ok(client.post("/actions/execute", json={
    "action_type_id": "alpha-close-case", "parameters": {"case_id": "alpha-case-1"},
    "idempotency_key": "alpha-close-once", "actor": "spoofed", "approval_request_id": approval_id,
}), "execute approved action")
assert executed["status"] == "SUCCESS"
cached = ok(client.post("/actions/execute", json={
    "action_type_id": "alpha-close-case", "parameters": {"case_id": "alpha-case-1"},
    "idempotency_key": "alpha-close-once", "actor": "spoofed", "approval_request_id": approval_id,
}), "replay approved action")
assert cached["status"] == "SUCCESS_CACHED"

app.dependency_overrides[production_auth.current_principal] = lambda: beta
ok(client.post("/actions/execute", json={
    "action_type_id": "beta-note-case", "parameters": {}, "idempotency_key": "alpha-close-once", "actor": "beta",
}), "reject cross-project idempotency collision", 409)

app.dependency_overrides[production_auth.current_principal] = lambda: alpha
snapshot = ok(client.get("/project/export"), "export governed automation")
for key in ("action_types", "approval_requests", "action_outbox", "action_idempotency_keys", "agent_definitions", "agent_sessions", "logic_functions", "logic_runs"):
    assert key in snapshot, key
assert next(row for row in snapshot["agent_definitions"] if row["id"] == "alpha-agent")["project_id"] == "alpha-automation"
assert next(row for row in snapshot["logic_functions"] if row["id"] == "alpha-triage")["project_id"] == "alpha-automation"

with SessionLocal() as db:
    obj = db.get(models.ObjectInstance, "alpha-case-1")
    assert obj.properties["state"] == "closed"
    approval = db.get(models_action.ApprovalRequest, approval_id)
    assert approval.project_id == "alpha-automation" and approval.requester == "alpha-automation-user"
    outbox = db.get(models_action.OutboxEvent, executed["outbox_event_id"])
    receipt = db.get(models_action.IdempotencyKey, "alpha-close-once")
    assert outbox.project_id == receipt.project_id == "alpha-automation"
    decision_audit = db.query(models_action.AuditLog).filter(models_action.AuditLog.event_type == "action.approval.decided").one()
    assert decision_audit.actor == "alpha-automation-approver"
    passed += 1

app.dependency_overrides.clear()
print(f"\nProject-scoped governed automation verified: {passed} assertions passed.")

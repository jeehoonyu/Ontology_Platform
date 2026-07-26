"""Model endpoints and AI evaluation evidence enforce one project boundary."""
import os
import tempfile


tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tmpdir.name, 'ai_evaluation_tenancy.db')}"
os.environ["AUTH_MODE"] = "local"
os.environ["APP_ENV"] = "test"

from fastapi.testclient import TestClient  # noqa: E402
from app import aip_evals, models, models_action, production_auth  # noqa: E402
from app.database import SessionLocal  # noqa: E402
from app.main import app  # noqa: E402

client = TestClient(app)
passed = 0


def ok(response, label, expect=200):
    global passed
    assert response.status_code == expect, f"{label}: {response.status_code} {response.text[:1600]}"
    passed += 1
    return response.json() if response.content else {}


ok(client.post("/tenancy/organizations", json={"id": "ai-org", "display_name": "AI Org"}), "create organization", 201)
for project_id in ("alpha-ai", "beta-ai"):
    ok(client.post("/tenancy/projects", json={
        "id": project_id, "organization_id": "ai-org", "display_name": project_id,
    }), f"create {project_id}", 201)

permissions = ["view", "edit", "execute", "approve", "publish", "restore", "export", "administer"]
alpha = production_auth.Principal("alpha-ai-user", "Alpha", None, ["administrator"], permissions, organization_id="ai-org", project_ids=["alpha-ai"])
beta = production_auth.Principal("beta-ai-user", "Beta", None, ["administrator"], permissions, organization_id="ai-org", project_ids=["beta-ai"])
viewer = production_auth.Principal("alpha-ai-viewer", "Viewer", None, ["viewer"], ["view"], organization_id="ai-org", project_ids=["alpha-ai"])

app.dependency_overrides[production_auth.current_principal] = lambda: alpha
alpha_endpoint = ok(client.post("/model-endpoints", json={
    "id": "alpha-model", "project_id": "alpha-ai", "display_name": "Alpha model", "description": None,
    "provider": "local", "model_name": "deterministic-alpha",
}), "create alpha model endpoint")
assert alpha_endpoint["project_id"] == "alpha-ai"
ok(client.post("/aip/model-catalog/byom", json={
    "id": "alpha-byom", "project_id": "alpha-ai", "display_name": "Alpha BYOM",
    "provider": "private", "endpoint_url": "https://model.alpha.invalid", "model_name": "alpha-private",
}), "register alpha BYOM")
ok(client.post("/model-endpoints", json={
    "id": "outside-model", "project_id": "beta-ai", "display_name": "Outside", "description": None,
    "provider": "local", "model_name": "forbidden",
}), "reject model creation outside membership", 403)

alpha_agent = ok(client.post("/agents", json={
    "id": "alpha-eval-agent", "project_id": "alpha-ai", "display_name": "Alpha eval agent",
    "description": None, "model_endpoint_id": "alpha-model",
}), "create alpha eval agent")
assert alpha_agent["project_id"] == "alpha-ai"
ok(client.post("/logic-functions", json={
    "id": "alpha-eval-logic", "project_id": "alpha-ai", "display_name": "Alpha eval logic",
    "description": None, "blocks": [{"type": "set_variable", "key": "result", "value": "ready"}],
}), "create alpha eval logic")

suite = ok(client.post("/eval-suites", json={
    "id": "alpha-suite", "project_id": "alpha-ai", "display_name": "Alpha suite", "description": None,
    "target_agent_id": "alpha-eval-agent", "cases": [{"prompt": "inspect"}], "criteria": {},
}), "create alpha suite")
assert suite["project_id"] == "alpha-ai"
suite_run = ok(client.post("/eval-suites/alpha-suite/run"), "run alpha suite")
assert suite_run["project_id"] == "alpha-ai"
grade = ok(client.post("/aip/evals/grade", json={
    "project_id": "alpha-ai", "actual": {"state": "ready"},
    "graders": [{"type": "exact_match", "path": "state", "expected": "ready"}],
}), "run alpha direct grade")
logic_grade = ok(client.post("/aip/evals/grade-logic", json={
    "logic_function_id": "alpha-eval-logic",
    "cases": [{"id": "case-1", "inputs": {}, "graders": [{"type": "not_null", "path": "outputs"}]}],
}), "grade alpha logic")
assert grade["metrics"]["passed"] == 1 and logic_grade["metrics"]["passed"] == 1

app.dependency_overrides[production_auth.current_principal] = lambda: beta
assert ok(client.get("/model-endpoints"), "filter beta endpoints") == []
assert ok(client.get("/eval-suites"), "filter beta suites") == []
assert ok(client.get("/eval-runs"), "filter beta suite runs") == []
assert ok(client.get("/aip/evals/runs"), "filter beta AIP eval runs") == []
ok(client.post("/agents", json={
    "id": "beta-cross-model-agent", "project_id": "beta-ai", "display_name": "Cross model", "description": None,
    "model_endpoint_id": "alpha-model",
}), "reject agent model from another project", 403)
with SessionLocal() as db:
    db.add(models.AgentDefinition(
        id="legacy-cross-model-agent", project_id="beta-ai", display_name="Legacy cross model",
        description=None, system_prompt=None, allowed_object_types=[], allowed_actions=[],
        model_endpoint_id="alpha-model", approval_required=True, created_at=1, updated_at=1,
    ))
    db.commit()
ok(client.post("/aip/agents/legacy-cross-model-agent/invoke", json={
    "prompt": "run", "parameters": {},
}), "reject malformed legacy agent model reference at runtime", 409)
ok(client.post("/eval-suites", json={
    "id": "beta-cross-suite", "project_id": "beta-ai", "display_name": "Cross suite", "description": None,
    "target_agent_id": "alpha-eval-agent",
}), "reject suite agent from another project", 403)
ok(client.post("/eval-suites/alpha-suite/run"), "reject cross-project suite run", 403)
ok(client.post("/aip/evals/grade-logic", json={
    "logic_function_id": "alpha-eval-logic", "cases": [],
}), "reject cross-project logic grade", 403)
ok(client.post("/aip/evals/grade", json={
    "project_id": "alpha-ai", "actual": {}, "graders": [],
}), "reject cross-project direct grade", 403)

app.dependency_overrides[production_auth.current_principal] = lambda: viewer
assert {row["id"] for row in ok(client.get("/model-endpoints"), "viewer reads alpha endpoints")} == {"alpha-model", "alpha-byom"}
assert [row["id"] for row in ok(client.get("/eval-suites"), "viewer reads alpha suite")] == ["alpha-suite"]
assert [row["id"] for row in ok(client.get("/eval-runs"), "viewer reads alpha run")] == [suite_run["id"]]
assert {row["id"] for row in ok(client.get("/aip/evals/runs"), "viewer reads alpha AIP evals")} == {grade["run_id"], logic_grade["run_id"]}
ok(client.post("/eval-suites/alpha-suite/run"), "viewer cannot run suite", 403)
ok(client.post("/aip/evals/grade-one", json={
    "project_id": "alpha-ai", "grader": "not_null", "actual": "value",
}), "viewer cannot grade", 403)

app.dependency_overrides[production_auth.current_principal] = lambda: alpha
snapshot = ok(client.get("/project/export"), "export AI evaluation evidence")
for key in ("model_endpoints", "eval_suites", "eval_runs", "aip_eval_runs"):
    assert key in snapshot, key
assert next(row for row in snapshot["model_endpoints"] if row["id"] == "alpha-model")["project_id"] == "alpha-ai"
assert next(row for row in snapshot["eval_suites"] if row["id"] == "alpha-suite")["project_id"] == "alpha-ai"

with SessionLocal() as db:
    assert db.get(models.EvalRun, suite_run["id"]).project_id == "alpha-ai"
    assert db.get(aip_evals.AipEvalRun, grade["run_id"]).project_id == "alpha-ai"
    audit = db.query(models_action.AuditLog).filter(models_action.AuditLog.event_type == "eval.run.completed").one()
    assert audit.actor == "alpha-ai-user" and audit.payload["project_id"] == "alpha-ai"
    passed += 1

app.dependency_overrides.clear()
print(f"\nProject-scoped AI evaluation verified: {passed} assertions passed.")

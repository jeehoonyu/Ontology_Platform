"""Project runtime telemetry, budgets, SLOs, recovery, and isolation."""
import os
import tempfile
from concurrent.futures import ThreadPoolExecutor

tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tmpdir.name, 'runtime-observability.db')}"
os.environ["AUTH_MODE"] = "local"
os.environ["APP_ENV"] = "test"

from fastapi.testclient import TestClient  # noqa: E402
from app.database import SessionLocal  # noqa: E402
from app.main import app  # noqa: E402
from app import models_action, platform_runtime, production_auth, runtime_observability, tenancy  # noqa: E402

client = TestClient(app)
passed = 0


def ok(response, label, expect=200):
    global passed
    assert response.status_code == expect, f"{label}: {response.status_code} {response.text[:1600]}"
    passed += 1
    return response.json() if response.content else {}


for organization in ({"id": "acme", "display_name": "Acme"}, {"id": "other", "display_name": "Other"}):
    ok(client.post("/tenancy/organizations", json=organization), "create organization", 201)
for project in (
    {"id": "operations", "organization_id": "acme", "display_name": "Operations"},
    {"id": "private", "organization_id": "other", "display_name": "Private"},
):
    ok(client.post("/tenancy/projects", json=project), "create project", 201)

with SessionLocal() as db:
    db.add_all([
        tenancy.ProjectMembership(id="ops-admin", project_id="operations", principal_id="alice", role="administrator", permissions=[], created_at=1, updated_at=1),
        tenancy.ProjectMembership(id="private-operator", project_id="private", principal_id="carol", role="operator", permissions=[], created_at=1, updated_at=1),
    ])
    db.commit()

active_principal = production_auth.Principal("alice", "Alice", "alice@example.test", ["administrator"], ["view", "edit", "execute", "administer"], organization_id="acme", project_ids=[])
app.dependency_overrides[production_auth.current_principal] = lambda: active_principal

budget = ok(client.put("/runtime/observability/budgets", json={
    "project_id": "operations", "metric": "executions", "limit_value": 2, "window_seconds": 86400,
    "enforcement": "HARD", "enabled": True,
}), "create execution budget")
assert budget["metric"] == "executions" and budget["limit_value"] == 2

job1 = ok(client.post("/jobs", json={
    "project_id": "operations", "job_type": "pipeline.preview", "subject_type": "pipeline", "subject_id": "p1",
    "estimated_compute_seconds": 2, "estimated_cost_usd": 0.2, "estimated_tokens": 100, "estimated_records": 10,
}), "queue observed job", 201)
claimed1 = ok(client.post("/jobs/claim", json={"worker_id": "worker-a", "job_id": job1["id"], "lease_seconds": 60}), "claim observed job")["job"]
ok(client.post(f"/jobs/{job1['id']}/heartbeat", json={
    "lease_token": claimed1["lease_token"], "progress": 60, "message": "Processing preview",
    "metrics": {"compute_seconds": 3, "tokens": 150, "records_out": 12, "cost_usd": 0.25},
}), "record job progress")
job1_done = ok(client.post(f"/jobs/{job1['id']}/complete", json={
    "lease_token": claimed1["lease_token"], "result": {"compute_seconds": 4, "token_units": 180, "records_out": 14, "estimated_cost_usd": 0.3},
}), "complete observed job")
assert job1_done["status"] == "SUCCEEDED"

job2 = ok(client.post("/jobs", json={
    "project_id": "operations", "job_type": "aip.agent.invoke", "subject_type": "agent", "subject_id": "agent-1",
    "estimated_compute_seconds": 1, "estimated_cost_usd": 0.1, "estimated_tokens": 50,
}), "queue failed job", 201)
claimed2 = ok(client.post("/jobs/claim", json={"worker_id": "worker-b", "job_id": job2["id"]}), "claim failed job")["job"]
job2_failed = ok(client.post(f"/jobs/{job2['id']}/fail", json={
    "lease_token": claimed2["lease_token"], "error": "Model endpoint unavailable", "retriable": False,
    "details": {"compute_seconds": 1.5, "token_units": 25, "estimated_cost_usd": 0.12},
}), "fail observed job")
assert job2_failed["status"] == "FAILED"

blocked = client.post("/jobs", json={"project_id": "operations", "job_type": "report.generate"})
ok(blocked, "enforce execution budget", 429)
assert blocked.json()["detail"]["check"]["metric"] == "executions"

observation = ok(client.get(f"/runtime/observability/jobs/{job1['id']}"), "get correlated trace")
assert observation["status"] == "SUCCEEDED" and observation["compute_seconds"] >= 4
assert observation["token_units"] == 180 and observation["record_units"] == 14
assert [span["name"] for span in observation["spans"]] == ["queue", "progress", "progress", "terminal"]

slo = ok(client.post("/runtime/observability/slo-policies", json={
    "id": "availability-slo", "project_id": "operations", "display_name": "Runtime availability",
    "metric": "availability", "operator": "gte", "threshold": 0.75, "window_seconds": 86400, "severity": "critical",
}), "create availability SLO", 201)
evaluation = ok(client.post(f"/runtime/observability/slo-policies/{slo['id']}/evaluate"), "evaluate breached SLO")
assert evaluation["status"] == "FAIL" and evaluation["observed_value"] == 0.5 and evaluation["sample_count"] == 2

summary = ok(client.get("/runtime/observability/summary?project_id=operations"), "runtime summary")
assert summary["total_jobs"] == 2 and summary["availability"] == 0.5
assert summary["estimated_cost_usd"] >= 0.42 and summary["warnings"] == ["Runtime availability is breaching"]
assert summary["active_workers"] == 2
ui_state = ok(client.get("/ui-state/runtime-operations?project_id=operations"), "runtime UI state")
assert {section["id"] for section in ui_state["sections"]} == {"jobs", "budgets", "slos"}
assert "administer" in ui_state["permissions"]

with SessionLocal() as db:
    breach_events = db.query(models_action.AuditLog).filter(models_action.AuditLog.event_type == "runtime.budget.updated").count()
    assert breach_events == 1

snapshot = ok(client.get("/project/export"), "export runtime evidence")
assert len(snapshot["runtime_job_observations"]) == 2 and snapshot["runtime_slo_evaluations"]
with SessionLocal() as db:
    db.query(runtime_observability.RuntimeSloEvaluation).delete()
    db.query(runtime_observability.RuntimeSloPolicy).delete()
    db.query(runtime_observability.RuntimeBudgetPolicy).delete()
    db.query(runtime_observability.RuntimeJobObservation).delete()
    db.commit()
ok(client.post("/project/import", json={"snapshot": snapshot, "mode": "merge", "actor": "recovery-test"}), "restore runtime evidence")
restored = ok(client.get("/runtime/observability/summary?project_id=operations"), "verify runtime recovery")
assert restored["total_jobs"] == 2 and restored["slo_evaluations"][0]["status"] == "FAIL"

with SessionLocal() as db:
    for index in range(20):
        db.add(platform_runtime.PlatformJob(
            id=f"legacy-job-{index}", project_id="operations", job_type="legacy.backfill", status="SUCCEEDED",
            actor="legacy", subject_type=None, subject_id=None, payload={}, result={}, error=None, attempt=1,
            progress=100, created_at=2, updated_at=3, started_at=2, completed_at=3,
        ))
    db.commit()
with ThreadPoolExecutor(max_workers=6) as pool:
    responses = list(pool.map(lambda _: client.get("/runtime/observability/summary?project_id=operations"), range(12)))
assert all(response.status_code == 200 for response in responses), [response.text[:300] for response in responses if response.status_code != 200]
with SessionLocal() as db:
    job_ids = [row.job_id for row in db.query(runtime_observability.RuntimeJobObservation).filter(runtime_observability.RuntimeJobObservation.job_id.like("legacy-job-%")).all()]
    assert len(job_ids) == len(set(job_ids)) == 20
passed += 1

active_principal = production_auth.Principal("carol", "Carol", "carol@example.test", ["operator"], ["view", "edit", "execute"], organization_id="other", project_ids=[])
ok(client.get("/runtime/observability/summary?project_id=operations"), "deny cross-project summary", 403)
ok(client.get(f"/runtime/observability/jobs/{job1['id']}"), "deny cross-project trace", 403)
ok(client.get("/runtime/observability/budgets?project_id=operations"), "deny cross-project budgets", 403)

app.dependency_overrides.clear()
print(f"Runtime observability verified: {passed} assertions passed.")

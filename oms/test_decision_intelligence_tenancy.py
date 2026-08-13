"""Decision, temporal, entity-resolution, and scenario resources remain project isolated."""
import os
import tempfile


temporary = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(temporary.name, 'decision-tenancy.db')}"
os.environ["AUTH_MODE"] = "local"
os.environ["APP_ENV"] = "test"

from fastapi.testclient import TestClient  # noqa: E402
from app import decision_intelligence, models_action, production_auth, runtime  # noqa: E402
from app.database import SessionLocal  # noqa: E402
from app.main import app  # noqa: E402


client = TestClient(app)
passed = 0


def check(response, label, expected=200):
    global passed
    assert response.status_code == expected, f"{label}: {response.status_code} {response.text[:1000]}"
    passed += 1
    return response.json() if response.content else {}


check(client.post("/tenancy/organizations", json={"id": "decision-org", "display_name": "Decision Org"}), "organization", 201)
for project_id in ("alpha", "beta"):
    check(client.post("/tenancy/projects", json={"id": project_id, "organization_id": "decision-org", "display_name": project_id.title()}), project_id, 201)

alpha = production_auth.Principal("alpha-admin", "Alpha", None, ["administrator"], ["*"], organization_id="decision-org", project_ids=["alpha"])
beta = production_auth.Principal("beta-admin", "Beta", None, ["administrator"], ["*"], organization_id="decision-org", project_ids=["beta"])
viewer = production_auth.Principal("alpha-viewer", "Viewer", None, ["viewer"], ["view"], organization_id="decision-org", project_ids=["alpha"])


def use(principal):
    app.dependency_overrides[production_auth.current_principal] = lambda: principal


def seed(project_id: str):
    object_type_id = f"{project_id}-asset"
    check(client.post("/object-types", json={
        "id": object_type_id, "project_id": project_id, "display_name": f"{project_id} asset",
        "properties": {"name": {"type": "string"}, "status": {"type": "string"}},
    }), f"{project_id} object type")
    for suffix, name in (("1", "Pump One"), ("2", "pump one")):
        check(client.post("/objects", json={
            "id": f"{project_id}-object-{suffix}", "project_id": project_id, "object_type_id": object_type_id,
            "properties": {"name": name, "status": "DEGRADED"},
        }), f"{project_id} object {suffix}")
    check(client.post("/decision/rules", json={
        "id": f"{project_id}-rule", "project_id": project_id, "display_name": "Degraded",
        "object_type_id": object_type_id, "expression": {"field": "status", "op": "eq", "value": "DEGRADED"},
        "severity": "high",
    }), f"{project_id} rule")
    check(client.post("/decision/scorecards", json={
        "id": f"{project_id}-scorecard", "project_id": project_id, "display_name": "Risk",
        "object_type_id": object_type_id, "features": [{"rule_id": f"{project_id}-rule", "weight": 90}],
        "thresholds": {"critical": 85},
    }), f"{project_id} scorecard")
    evaluation = check(client.post("/decision/evaluate", json={
        "project_id": project_id, "object_type_id": object_type_id, "persist_run": True,
    }), f"{project_id} evaluation")
    assert evaluation["project_id"] == project_id and evaluation["object_count"] == 2, evaluation
    job = check(client.post("/entity-resolution/jobs", json={
        "project_id": project_id, "object_type_id": object_type_id, "fields": ["name"], "threshold": 85,
    }), f"{project_id} resolution job")
    assert job["project_id"] == project_id and job["candidates"], job
    scenario = check(client.post("/decision/scenarios", json={
        "id": f"{project_id}-scenario", "project_id": project_id, "display_name": "Outage",
        "seed_object_ids": [f"{project_id}-object-1"],
        "overrides": {f"{project_id}-object-1": {"status": "OUTAGE"}},
    }), f"{project_id} scenario")
    assert scenario["project_id"] == project_id, scenario
    return job


use(alpha)
alpha_job = seed("alpha")
alpha_candidate_id = alpha_job["candidates"][0]["id"]
use(beta)
beta_job = seed("beta")

assert [row["id"] for row in check(client.get("/decision/rules"), "beta rule list")] == ["beta-rule"]
assert [row["id"] for row in check(client.get("/decision/scorecards"), "beta scorecard list")] == ["beta-scorecard"]
assert [row["id"] for row in check(client.get("/entity-resolution/jobs"), "beta job list")] == [beta_job["id"]]
check(client.get("/decision/objects/alpha-asset/alpha-object-1/explain"), "deny alpha explanation", 403)
check(client.get("/temporal/objects/alpha-asset/alpha-object-1/timeline"), "deny alpha timeline", 403)
check(client.get("/decision/scenarios/alpha-scenario"), "deny alpha scenario", 403)
check(client.get(f"/entity-resolution/jobs/{alpha_job['id']}/candidates"), "deny alpha resolution job", 403)
check(client.post(f"/entity-resolution/candidates/{alpha_candidate_id}/reject", json={"actor": "spoofed"}), "deny alpha candidate mutation", 403)
check(client.post("/decision/evaluate", json={"project_id": "alpha", "object_type_id": "alpha-asset"}), "deny alpha evaluation", 403)
check(client.post("/decision/scorecards", json={
    "id": "cross-scorecard", "project_id": "beta", "display_name": "Cross", "object_type_id": "alpha-asset",
}), "reject cross-project scorecard", 422)
check(client.post("/decision/scenarios", json={
    "id": "cross-scenario", "project_id": "beta", "display_name": "Cross", "seed_object_ids": ["alpha-object-1"],
}), "reject cross-project scenario object", 422)

use(viewer)
assert [row["id"] for row in check(client.get("/decision/rules"), "viewer alpha rules")] == ["alpha-rule"]
check(client.get("/decision/objects/alpha-asset/alpha-object-1/explain"), "viewer explanation")
check(client.post("/decision/evaluate", json={"project_id": "alpha", "object_type_id": "alpha-asset"}), "viewer cannot evaluate", 403)
check(client.post("/decision/rules", json={
    "id": "viewer-rule", "project_id": "alpha", "display_name": "Viewer", "object_type_id": "alpha-asset",
}), "viewer cannot create rule", 403)

use(alpha)
rejected = check(client.post(f"/entity-resolution/candidates/{alpha_candidate_id}/reject", json={"actor": "spoofed", "reason": "reviewed"}), "alpha rejects candidate")
assert rejected["status"] == "REJECTED"
with SessionLocal() as db:
    audit = db.query(models_action.AuditLog).filter(
        models_action.AuditLog.event_type == "entity_resolution.candidate.rejected",
        models_action.AuditLog.subject_id == alpha_candidate_id,
    ).one()
    assert audit.actor == "alpha-admin" and audit.payload["project_id"] == "alpha", (audit.actor, audit.payload)
    passed += 1
    alpha_context = runtime.build_context_pack(db, allowed_object_types=[], project_id="alpha", limit=10)
    assert {pack["object_type_id"] for pack in alpha_context["packs"]} == {"alpha-asset"}, alpha_context
    assert {obj["id"] for pack in alpha_context["packs"] for obj in pack["objects"]} == {"alpha-object-1", "alpha-object-2"}, alpha_context
    passed += 1
    decision_context = decision_intelligence.build_decision_context(db, alpha_context, project_id="alpha")
    assert {row["object_id"] for row in decision_context["object_risk"]} == {"alpha-object-1", "alpha-object-2"}, decision_context
    passed += 1

app.dependency_overrides.clear()
print(f"Decision Intelligence tenancy verified: {passed} assertions passed.")

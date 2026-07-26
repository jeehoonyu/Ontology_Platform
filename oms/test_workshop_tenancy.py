"""Workshop authoring and runtime enforce project ownership and action safeguards."""
import os
import tempfile


tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tmpdir.name, 'workshop_tenancy.db')}"
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
    assert response.status_code == expect, f"{label}: {response.status_code} {response.text[:1200]}"
    passed += 1
    return response.json() if response.content else {}


ok(client.post("/tenancy/organizations", json={"id": "workshop-org", "display_name": "Workshop Org"}), "create organization", 201)
for project_id in ("alpha-workshop", "beta-workshop"):
    ok(client.post("/tenancy/projects", json={
        "id": project_id, "organization_id": "workshop-org", "display_name": project_id,
    }), f"create {project_id}", 201)

with SessionLocal() as db:
    db.add_all([
        models.ObjectType(
            id="alpha-alert", display_name="Alpha alert", description=None,
            properties={"id": {"type": "string"}, "status": {"type": "string"}, "__manager": {"project_id": "alpha-workshop"}},
            created_at=1, updated_at=1,
        ),
        models.ObjectType(
            id="beta-alert", display_name="Beta alert", description=None,
            properties={"id": {"type": "string"}, "__manager": {"project_id": "beta-workshop"}},
            created_at=1, updated_at=1,
        ),
        models.ObjectInstance(
            id="alpha-alert-1", object_type_id="alpha-alert", properties={"id": "alpha-alert-1", "status": "open"},
            source_asset_id=None, lineage={}, created_at=1, updated_at=1,
        ),
        models.ActionType(
            id="critical-ack", display_name="Critical acknowledge", description=None,
            parameters={"alert_id": {"type": "string", "required": True}},
            rules={
                "risk_level": "critical",
                "object_mutations": [{"object_type_id": "alpha-alert", "object_id": "$alert_id", "set": {"status": "acknowledged"}}],
            },
        ),
    ])
    db.commit()

permissions = ["view", "edit", "execute", "publish", "restore", "administer"]
alpha = production_auth.Principal("alpha-workshop-user", "Alpha", None, ["administrator"], permissions, organization_id="workshop-org", project_ids=["alpha-workshop"])
beta = production_auth.Principal("beta-workshop-user", "Beta", None, ["administrator"], permissions, organization_id="workshop-org", project_ids=["beta-workshop"])
viewer = production_auth.Principal("alpha-workshop-viewer", "Viewer", None, ["viewer"], ["view"], organization_id="workshop-org", project_ids=["alpha-workshop"])

app.dependency_overrides[production_auth.current_principal] = lambda: alpha
module = ok(client.post("/apps/workshop", json={
    "id": "alpha-console",
    "project_id": "alpha-workshop",
    "display_name": "Alpha Console",
    "variables": {"alerts": {"definition_type": "object_set", "object_type_id": "alpha-alert"}},
    "widgets": [
        {"type": "object_table", "title": "Alerts", "variable": "alerts", "object_type_id": "alpha-alert"},
        {"type": "button", "title": "Acknowledge", "action_type_id": "critical-ack"},
    ],
}), "create owned Workshop")
assert module["project_id"] == "alpha-workshop"
ok(client.get("/apps/workshop/alpha-console"), "read owned Workshop")
rendered = ok(client.post("/apps/workshop/alpha-console/render-live", json={"state": {}}), "render owned Workshop")
assert rendered["widgets"][0]["row_count"] == 1
version = ok(client.post("/apps/workshop/alpha-console/publish", json={"actor": "spoofed", "note": "baseline"}), "publish owned Workshop")
ok(client.patch("/apps/workshop/alpha-console", json={"description": "changed", "actor": "spoofed"}), "edit owned Workshop")
ok(client.post(f"/apps/workshop/alpha-console/versions/{version['id']}/restore", json={"actor": "spoofed"}), "restore owned Workshop")

approval_event = ok(client.post("/apps/workshop/alpha-console/event", json={
    "state": {},
    "events": [{"id": "critical-event", "type": "apply_action", "action_type_id": "critical-ack", "parameters": {"alert_id": "alpha-alert-1"}}],
}), "high-risk action is staged")
assert approval_event["effects"][0]["status"] == "approval_required"
approval_id = approval_event["effects"][0]["approval_request_id"]

foreign = ok(client.post("/apps/workshop", json={
    "id": "foreign-reference", "project_id": "alpha-workshop", "display_name": "Foreign",
    "variables": {"alerts": {"definition_type": "object_set", "object_type_id": "beta-alert"}},
}), "reject foreign ontology reference", 403)
assert foreign["detail"]["object_type_id"] == "beta-alert"

ok(client.post("/apps/carbon", json={"id": "alpha-hub", "display_name": "Alpha Hub", "module_ids": ["alpha-console"]}), "create Carbon wrapper")

app.dependency_overrides[production_auth.current_principal] = lambda: beta
for method, path, body in (
    (client.get, "/apps/workshop/alpha-console", None),
    (client.get, "/apps/workshop/alpha-console/dependencies", None),
    (client.post, "/apps/workshop/alpha-console/resolve", {"state": {}}),
    (client.post, "/apps/workshop/alpha-console/render-live", {"state": {}}),
    (client.patch, "/apps/workshop/alpha-console", {"display_name": "stolen"}),
    (client.post, "/apps/workshop/alpha-console/publish", {}),
    (client.post, "/apps/workshop/alpha-console/event", {"state": {}, "events": []}),
    (client.get, "/apps/carbon/alpha-hub/resolve", None),
):
    response = method(path, json=body) if body is not None and method is not client.get else method(path)
    ok(response, f"deny cross-project {path}", 403)
assert ok(client.get("/apps/workshop"), "filter Workshop list") == []

app.dependency_overrides[production_auth.current_principal] = lambda: viewer
visible = ok(client.get("/apps/workshop"), "viewer lists owned Workshop")
assert [row["id"] for row in visible] == ["alpha-console"]
ok(client.post("/apps/workshop/alpha-console/render-live", json={"state": {}}), "viewer renders owned Workshop")
ok(client.post("/apps/workshop/alpha-console/event", json={"state": {}, "events": []}), "viewer cannot execute events", 403)
ok(client.patch("/apps/workshop/alpha-console", json={"display_name": "forbidden"}), "viewer cannot edit", 403)

app.dependency_overrides[production_auth.current_principal] = lambda: alpha
snapshot = ok(client.get("/project/export"), "export project-owned Workshop")
exported_module = next(row for row in snapshot["workshop_modules"] if row["id"] == "alpha-console")
assert exported_module["project_id"] == "alpha-workshop"

with SessionLocal() as db:
    obj = db.get(models.ObjectInstance, "alpha-alert-1")
    assert obj.properties["status"] == "open", obj.properties
    approval = db.get(models_action.ApprovalRequest, approval_id)
    assert approval and approval.status == models_action.ApprovalStatus.PENDING.value
    audits = db.query(models_action.AuditLog).filter(models_action.AuditLog.subject_id == "alpha-console").all()
    assert audits and all(row.actor == "alpha-workshop-user" for row in audits)
    assert all((row.payload or {}).get("project_id") == "alpha-workshop" for row in audits)
    passed += 1

app.dependency_overrides.clear()
print(f"\nProject-scoped Workshop verified: {passed} assertions passed.")

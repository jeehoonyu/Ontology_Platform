"""Import and generated-ontology onboarding enforce project ownership."""
import os
import tempfile


tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tmpdir.name, 'import_tenancy.db')}"
os.environ["AUTH_MODE"] = "local"
os.environ["APP_ENV"] = "test"

from fastapi.testclient import TestClient  # noqa: E402
from app import models_action, production_auth  # noqa: E402
from app.database import SessionLocal  # noqa: E402
from app.main import app  # noqa: E402

client = TestClient(app)
passed = 0


def ok(response, label, expect=200):
    global passed
    assert response.status_code == expect, f"{label}: {response.status_code} {response.text[:1200]}"
    passed += 1
    return response.json() if response.content else {}


ok(client.post("/tenancy/organizations", json={"id": "tenant-org", "display_name": "Tenant Org"}), "create organization", 201)
for project_id in ("alpha", "beta"):
    ok(client.post("/tenancy/projects", json={
        "id": project_id, "organization_id": "tenant-org", "display_name": project_id.title(),
    }), f"create {project_id} project", 201)

alpha = production_auth.Principal(
    "alpha-user", "Alpha User", "alpha@example.test", ["administrator"],
    ["view", "edit", "deploy", "administer"], organization_id="tenant-org", project_ids=["alpha"],
)
beta = production_auth.Principal(
    "beta-user", "Beta User", "beta@example.test", ["administrator"],
    ["view", "edit", "deploy", "administer"], organization_id="tenant-org", project_ids=["beta"],
)
viewer = production_auth.Principal(
    "alpha-viewer", "Alpha Viewer", "viewer@example.test", ["viewer"],
    ["view"], organization_id="tenant-org", project_ids=["alpha"],
)

app.dependency_overrides[production_auth.current_principal] = lambda: alpha
created = ok(client.post("/imports/csv", json={
    "id": "alpha-assets-import", "project_id": "alpha", "filename": "assets.csv",
    "display_name": "Alpha Assets", "content": "asset_id,name,status\na-1,Pump 1,DEGRADED\na-2,Chiller 2,RUNNING\n",
}), "create project-owned import", 201)
assert created["project_id"] == "alpha"
ok(client.post("/imports/jobs/alpha-assets-import/validate", json={"template": "asset"}), "validate import")

app.dependency_overrides[production_auth.current_principal] = lambda: beta
for method, path, body in (
    (client.get, "/imports/jobs/alpha-assets-import", None),
    (client.patch, "/imports/jobs/alpha-assets-import", {"display_name": "stolen"}),
    (client.post, "/imports/jobs/alpha-assets-import/validate", {"template": "asset"}),
    (client.post, "/imports/jobs/alpha-assets-import/promote-to-dataset", {"dataset_id": "stolen-assets"}),
    (client.post, "/imports/jobs/alpha-assets-import/generate-ontology-draft", {"draft_id": "stolen-draft"}),
):
    response = method(path, json=body) if body is not None else method(path)
    ok(response, f"deny cross-project {path}", 403)
listed = ok(client.get("/imports/jobs"), "filter import list")
assert listed["count"] == 0 and listed["jobs"] == [], listed

app.dependency_overrides[production_auth.current_principal] = lambda: viewer
ok(client.post("/imports/csv", json={"project_id": "alpha", "content": "id\n1\n"}), "deny viewer mutation", 403)

app.dependency_overrides[production_auth.current_principal] = lambda: alpha
generated = ok(client.post("/imports/jobs/alpha-assets-import/generate-ontology-draft", json={
    "draft_id": "alpha-assets-draft", "object_type_id": "alpha_asset", "promote_dataset_id": "alpha-assets",
}), "promote and generate ontology draft")
assert generated["draft"]["draft"]["__project_id"] == "alpha"
ok(client.post("/ontology-generator/drafts/alpha-assets-draft/validate"), "validate owned ontology draft")
applied = ok(client.post("/ontology-generator/drafts/alpha-assets-draft/apply", json={}), "apply owned ontology draft")
assert applied["object_type_id"] == "alpha_asset"

app.dependency_overrides[production_auth.current_principal] = lambda: beta
ok(client.get("/ontology-generator/drafts/alpha-assets-draft"), "deny cross-project draft read", 403)
ok(client.post("/ontology-generator/drafts/alpha-assets-draft/apply", json={}), "deny cross-project draft apply", 403)

with SessionLocal() as db:
    audit = db.query(models_action.AuditLog).filter(
        models_action.AuditLog.event_type == "ontology.generator.applied",
        models_action.AuditLog.subject_id == "alpha_asset",
    ).one()
    assert audit.actor == "alpha-user" and audit.payload["project_id"] == "alpha", audit.payload
    passed += 1

app.dependency_overrides.clear()
print(f"\nProject-scoped import and ontology onboarding verified: {passed} assertions passed.")

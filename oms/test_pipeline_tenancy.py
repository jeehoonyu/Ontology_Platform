"""Pipeline Builder graph lifecycle enforces project ownership."""
import os
import tempfile


tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tmpdir.name, 'pipeline_tenancy.db')}"
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


ok(client.post("/tenancy/organizations", json={"id": "pipeline-org", "display_name": "Pipeline Org"}), "create organization", 201)
for project_id in ("alpha-pipeline", "beta-pipeline"):
    ok(client.post("/tenancy/projects", json={
        "id": project_id, "organization_id": "pipeline-org", "display_name": project_id,
    }), f"create {project_id}", 201)

with SessionLocal() as db:
    db.add_all([
        models.DataAsset(id="alpha-input", project_id="alpha-pipeline", display_name="Alpha input", description=None, kind="dataset", asset_schema={"project_id": "alpha-pipeline"}, records=[{"id": "a1", "value": 4}], created_at=1, updated_at=1),
        models.DataAsset(id="beta-input", project_id="beta-pipeline", display_name="Beta input", description=None, kind="dataset", asset_schema={"project_id": "beta-pipeline"}, records=[{"id": "b1", "value": 8}], created_at=1, updated_at=1),
    ])
    db.commit()

permissions = ["view", "edit", "execute", "deploy", "administer"]
alpha = production_auth.Principal("alpha-pipeline-user", "Alpha", None, ["administrator"], permissions, organization_id="pipeline-org", project_ids=["alpha-pipeline"])
beta = production_auth.Principal("beta-pipeline-user", "Beta", None, ["administrator"], permissions, organization_id="pipeline-org", project_ids=["beta-pipeline"])
viewer = production_auth.Principal("alpha-pipeline-viewer", "Viewer", None, ["viewer"], ["view"], organization_id="pipeline-org", project_ids=["alpha-pipeline"])

app.dependency_overrides[production_auth.current_principal] = lambda: alpha
graph = ok(client.post("/pipeline-builder/graphs", json={
    "id": "alpha-graph", "project_id": "alpha-pipeline", "display_name": "Alpha graph",
    "nodes": [
        {"id": "input", "type": "input_dataset", "config": {"asset_id": "alpha-input"}},
        {"id": "output", "type": "dataset_output", "config": {"asset_id": "alpha-output"}},
    ],
    "edges": [{"source": "input", "target": "output"}],
}), "create owned graph", 201)
assert graph["project_id"] == "alpha-pipeline"
ok(client.patch("/pipeline-builder/graphs/alpha-graph/nodes/output", json={"label": "Owned output", "actor": "spoofed"}), "edit owned node")
job = ok(client.post("/pipeline-builder/graphs/alpha-graph/preview/async", json={"idempotency_key": "alpha-preview"}), "enqueue project job", 202)
assert job["project_id"] == "alpha-pipeline"
delivery = ok(client.post("/pipeline-builder/graphs/alpha-graph/deliver", json={"actor": "spoofed"}), "deliver owned graph")
assert delivery["records_out"] == 1

app.dependency_overrides[production_auth.current_principal] = lambda: beta
for method, path, body in (
    (client.get, "/pipeline-builder/graphs/alpha-graph", None),
    (client.get, "/ui-state/pipeline/alpha-graph/canvas", None),
    (client.patch, "/pipeline-builder/graphs/alpha-graph", {"display_name": "stolen"}),
    (client.post, "/pipeline-builder/graphs/alpha-graph/validate", {}),
    (client.post, "/pipeline-builder/graphs/alpha-graph/preview", {}),
    (client.post, "/pipeline-builder/graphs/alpha-graph/deliver", {}),
):
    response = method(path, json=body) if body is not None and method is not client.get else method(path)
    ok(response, f"deny cross-project {path}", 403)
listed = ok(client.get("/pipeline-builder/graphs"), "filter graph list")
assert listed == [], listed

mismatch = ok(client.post("/pipeline-builder/graphs", json={
    "id": "beta-mismatch", "project_id": "beta-pipeline", "display_name": "Mismatched graph",
    "nodes": [{"id": "input", "type": "input_dataset", "config": {"asset_id": "alpha-input"}}],
}), "create graph with foreign input", 201)
validation = ok(client.post(f"/pipeline-builder/graphs/{mismatch['id']}/validate"), "validate foreign input")
assert any(error["code"] == "INPUT_ASSET_PROJECT_MISMATCH" for error in validation["errors"]), validation

collision = ok(client.post("/pipeline-builder/graphs", json={
    "id": "beta-collision", "project_id": "beta-pipeline", "display_name": "Collision graph",
    "nodes": [
        {"id": "input", "type": "input_dataset", "config": {"asset_id": "beta-input"}},
        {"id": "output", "type": "dataset_output", "config": {"asset_id": "alpha-output"}},
    ],
    "edges": [{"source": "input", "target": "output"}],
}), "create collision graph", 201)
ok(client.post(f"/pipeline-builder/graphs/{collision['id']}/deliver", json={}), "deny output asset collision", 409)

app.dependency_overrides[production_auth.current_principal] = lambda: viewer
visible = ok(client.get("/pipeline-builder/graphs"), "viewer sees owned graph")
assert [row["id"] for row in visible] == ["alpha-graph"]
ok(client.post("/pipeline-builder/graphs/alpha-graph/preview", json={}), "viewer cannot execute", 403)

with SessionLocal() as db:
    output = db.get(models.DataAsset, "alpha-output")
    assert output and output.asset_schema["project_id"] == "alpha-pipeline"
    audit = db.query(models_action.AuditLog).filter(models_action.AuditLog.event_type == "pipeline_builder.graph.delivered").one()
    assert audit.actor == "alpha-pipeline-user" and audit.payload["project_id"] == "alpha-pipeline"
    passed += 1

app.dependency_overrides.clear()
print(f"\nProject-scoped Pipeline Builder verified: {passed} assertions passed.")

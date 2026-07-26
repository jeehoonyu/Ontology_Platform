"""Modeling and ModelOps resources remain isolated across project boundaries."""
import os
import tempfile

tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tmpdir.name, 'model_tenancy.db')}"
os.environ["AUTH_MODE"] = "local"
os.environ["APP_ENV"] = "test"

from fastapi.testclient import TestClient  # noqa: E402
from app import modeling, modelops, models, production_auth  # noqa: E402
from app.database import SessionLocal  # noqa: E402
from app.main import app  # noqa: E402

client = TestClient(app)
passed = 0


def ok(response, label, expect=200):
    global passed
    assert response.status_code == expect, f"{label}: {response.status_code} {response.text[:1200]}"
    passed += 1
    return response.json() if response.content else {}


ok(client.post("/tenancy/organizations", json={"id": "model-org", "display_name": "Model Org"}), "organization", 201)
for project_id in ("alpha-model", "beta-model"):
    ok(client.post("/tenancy/projects", json={"id": project_id, "organization_id": "model-org", "display_name": project_id}), project_id, 201)

alpha = production_auth.Principal("alpha-user", "Alpha", None, ["administrator"], ["*"], organization_id="model-org", project_ids=["alpha-model"])
beta = production_auth.Principal("beta-user", "Beta", None, ["administrator"], ["*"], organization_id="model-org", project_ids=["beta-model"])
viewer = production_auth.Principal("alpha-viewer", "Viewer", None, ["viewer"], ["view"], organization_id="model-org", project_ids=["alpha-model"])

with SessionLocal() as db:
    db.add_all([
        models.DataAsset(id="alpha-baseline", display_name="Alpha baseline", description=None, kind="dataset", asset_schema={"project_id": "alpha-model"}, records=[{"temperature": 10, "risk": 5}, {"temperature": 12, "risk": 6}], created_at=1, updated_at=1),
        models.DataAsset(id="alpha-current", display_name="Alpha current", description=None, kind="dataset", asset_schema={"project_id": "alpha-model"}, records=[{"temperature": 30, "risk": 15}], created_at=1, updated_at=1),
        models.DataAsset(id="beta-data", display_name="Beta data", description=None, kind="dataset", asset_schema={"project_id": "beta-model"}, records=[], created_at=1, updated_at=1),
    ])
    db.commit()

app.dependency_overrides[production_auth.current_principal] = lambda: alpha
objective = ok(client.post("/modeling/objectives", json={
    "id": "alpha-objective", "project_id": "alpha-model", "display_name": "Alpha risk",
    "problem_type": "regression", "target_field": "risk", "feature_fields": ["temperature"],
    "input_asset_id": "alpha-baseline",
}), "create objective")
ok(client.post("/modeling/objectives", json={
    "id": "bad-objective", "project_id": "alpha-model", "display_name": "Bad",
    "problem_type": "regression", "target_field": "risk", "feature_fields": [], "input_asset_id": "beta-data",
}), "reject cross-project objective dataset", 403)
submission = ok(client.post("/modeling/objectives/alpha-objective/train", json={"trainer_type": "regression", "training_dataset_id": "alpha-baseline"}), "train")
check = ok(client.post("/modeling/objectives/alpha-objective/checks", json={"name": "quality", "check_type": "automatic", "metric": "mae", "operator": "<=", "threshold": 10}), "check")
ok(client.post(f"/modeling/submissions/{submission['id']}/evaluate-checks"), "evaluate checks")
release = ok(client.post("/modeling/objectives/alpha-objective/releases", json={"submission_id": submission["id"], "version": "v1", "environment": "staging"}), "release")
deployment = ok(client.post("/modeling/deployments", json={"id": "alpha-deployment", "objective_id": objective["id"], "submission_id": submission["id"], "mode": "live"}), "deploy")
ok(client.post(f"/modeling/deployments/{deployment['id']}/infer", json={"records": [{"temperature": 20}]}), "infer")
monitor = ok(client.post("/modelops/monitors", json={
    "id": "alpha-monitor", "project_id": "alpha-model", "display_name": "Alpha monitor",
    "objective_id": objective["id"], "deployment_id": deployment["id"], "baseline_asset_id": "alpha-baseline",
    "feature_fields": ["temperature"], "target_field": "risk",
}), "monitor")
run = ok(client.post(f"/modelops/monitors/{monitor['id']}/run", json={"current_asset_id": "alpha-current"}), "monitor run")
assert release["project_id"] == run["project_id"] == "alpha-model" and check["project_id"] == "alpha-model"

app.dependency_overrides[production_auth.current_principal] = lambda: beta
assert ok(client.get("/modeling/objectives"), "beta objectives") == []
assert ok(client.get("/modelops/monitors"), "beta monitors") == []
assert ok(client.get("/modeling/deployment-configs"), "beta configs") == []
for method, path, body in (
    (client.get, "/modeling/objectives/alpha-objective", None),
    (client.post, f"/modeling/submissions/{submission['id']}/adapter/infer", {"inputs": {}}),
    (client.post, "/modeling/deployment-configs", {"release_id": release["id"], "kind": "batch"}),
    (client.post, f"/modelops/monitors/{monitor['id']}/run", {"current_asset_id": "beta-data"}),
):
    response = method(path, json=body) if body is not None else method(path)
    ok(response, f"reject beta access {path}", 403)

app.dependency_overrides[production_auth.current_principal] = lambda: viewer
assert ok(client.get("/modeling/objectives"), "viewer objective list")[0]["id"] == objective["id"]
assert ok(client.get("/modelops/monitors"), "viewer monitor list")[0]["id"] == monitor["id"]
ok(client.post("/modeling/objectives/alpha-objective/train", json={"trainer_type": "regression"}), "viewer cannot train", 403)
ok(client.post(f"/modeling/deployments/{deployment['id']}/infer", json={"records": []}), "viewer cannot infer", 403)

app.dependency_overrides[production_auth.current_principal] = lambda: alpha
snapshot = ok(client.get("/project/export"), "snapshot")
for key in ("modeling_objectives", "model_submissions", "model_deployments", "mev_releases", "mev_checks", "model_monitors", "model_monitor_runs", "model_prediction_logs"):
    assert key in snapshot, key
assert next(row for row in snapshot["modeling_objectives"] if row["id"] == objective["id"])["project_id"] == "alpha-model"

with SessionLocal() as db:
    db.add(modeling.ModelDeployment(id="malformed-deployment", project_id="beta-model", objective_id=objective["id"], submission_id=submission["id"], mode="live", status="running", created_at=1))
    db.commit()
app.dependency_overrides[production_auth.current_principal] = lambda: beta
ok(client.post("/modeling/deployments/malformed-deployment/infer", json={"records": []}), "malformed cross-project deployment fails closed", 409)

app.dependency_overrides.clear()
print(f"\nProject-scoped modeling and ModelOps verified: {passed} assertions passed.")

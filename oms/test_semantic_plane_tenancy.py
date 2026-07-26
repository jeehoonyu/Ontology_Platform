"""Core semantic resources and their primary consumers remain project isolated."""
import os
import tempfile

tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tmpdir.name, 'semantic_tenancy.db')}"
os.environ["AUTH_MODE"] = "local"
os.environ["APP_ENV"] = "test"

from fastapi.testclient import TestClient  # noqa: E402
from app import production_auth  # noqa: E402
from app.main import app  # noqa: E402

client = TestClient(app)
passed = 0


def check(response, label, expected=200):
    global passed
    assert response.status_code == expected, f"{label}: {response.status_code} {response.text[:1000]}"
    passed += 1
    return response.json() if response.content else {}


check(client.post("/tenancy/organizations", json={"id": "semantic-org", "display_name": "Semantic Org"}), "organization", 201)
for project_id in ("alpha", "beta"):
    check(client.post("/tenancy/projects", json={"id": project_id, "organization_id": "semantic-org", "display_name": project_id}), project_id, 201)

alpha = production_auth.Principal("alpha-admin", "Alpha", None, ["administrator"], ["*"], organization_id="semantic-org", project_ids=["alpha"])
beta = production_auth.Principal("beta-admin", "Beta", None, ["administrator"], ["*"], organization_id="semantic-org", project_ids=["beta"])
viewer = production_auth.Principal("alpha-viewer", "Viewer", None, ["viewer"], ["view"], organization_id="semantic-org", project_ids=["alpha"])


def use(principal):
    app.dependency_overrides[production_auth.current_principal] = lambda: principal


def seed(project_id):
    check(client.post("/data-assets", json={
        "id": f"{project_id}-data", "project_id": project_id, "display_name": f"{project_id} data",
        "kind": "dataset", "asset_schema": {}, "records": [{"id": f"{project_id}-1", "name": project_id}],
    }), f"{project_id} dataset")
    check(client.post("/object-types", json={
        "id": f"{project_id}-asset", "project_id": project_id, "display_name": f"{project_id} asset",
        "properties": {"id": {"type": "string"}, "name": {"type": "string"}},
    }), f"{project_id} object type")
    check(client.post("/objects", json={
        "id": f"{project_id}-object", "project_id": project_id, "object_type_id": f"{project_id}-asset",
        "properties": {"id": f"{project_id}-1", "name": project_id}, "source_asset_id": f"{project_id}-data",
    }), f"{project_id} object")
    check(client.post("/object-sets/saved", json={
        "id": f"{project_id}-set", "project_id": project_id, "display_name": f"{project_id} set",
        "object_type_id": f"{project_id}-asset", "filters": {},
    }), f"{project_id} saved set")
    check(client.post("/gis/map-layers", json={
        "id": f"{project_id}-layer", "project_id": project_id, "display_name": f"{project_id} layer",
        "object_type_id": f"{project_id}-asset", "saved_object_set_id": f"{project_id}-set", "filters": {}, "style": {},
    }), f"{project_id} map layer")
    check(client.post("/pipelines", json={
        "id": f"{project_id}-pipeline", "project_id": project_id, "display_name": f"{project_id} pipeline",
        "input_asset_id": f"{project_id}-data", "steps": [{"operation": "select", "fields": ["id", "name"]}],
    }), f"{project_id} pipeline")


use(alpha)
seed("alpha")
use(beta)
seed("beta")

assert [row["id"] for row in check(client.get("/object-types"), "beta object types")] == ["beta-asset"]
assert [row["id"] for row in check(client.get("/data-assets"), "beta datasets")] == ["beta-data"]
assert [row["id"] for row in check(client.get("/pipelines"), "beta pipelines")] == ["beta-pipeline"]
check(client.get("/objects/alpha-asset/alpha-object"), "beta cannot read alpha object", 403)
check(client.get("/gis/map-layers/alpha-layer"), "beta cannot read alpha layer", 403)
check(client.post("/object-explorer/query", json={"object_type_id": "alpha-asset"}), "beta cannot query alpha", 403)
graph = check(client.get("/graph/overview"), "beta graph")
assert "alpha-object" not in str(graph) and "alpha-data" not in str(graph)
search = check(client.get("/search?q=alpha"), "beta search")
assert search["count"] == 0, search

check(client.post("/objects", json={
    "id": "cross-object", "project_id": "beta", "object_type_id": "alpha-asset", "properties": {"id": "x"},
}), "cross-project object type rejected", 403)
check(client.post("/pipelines", json={
    "id": "cross-pipeline", "project_id": "beta", "display_name": "cross", "input_asset_id": "alpha-data", "steps": [],
}), "cross-project pipeline input rejected", 403)

use(viewer)
assert check(client.get("/object-types"), "viewer reads alpha")[0]["id"] == "alpha-asset"
check(client.post("/objects", json={
    "id": "viewer-write", "project_id": "alpha", "object_type_id": "alpha-asset", "properties": {"id": "viewer"},
}), "viewer cannot create object", 403)
check(client.post("/pipelines/alpha-pipeline/run"), "viewer cannot run pipeline", 403)

use(alpha)
run = check(client.post("/pipelines/alpha-pipeline/run"), "alpha pipeline run")
assert run["project_id"] == "alpha"
snapshot = check(client.get("/project/export"), "snapshot")
for resource in ("object_types", "object_instances", "data_assets", "pipeline_definitions", "pipeline_runs", "saved_object_sets", "map_layer_definitions"):
    row = next(item for item in snapshot[resource] if item.get("project_id") == "alpha")
    assert row["project_id"] == "alpha", (resource, row)

app.dependency_overrides.clear()
print(f"\nSemantic data-plane tenancy verified: {passed} assertions passed.")

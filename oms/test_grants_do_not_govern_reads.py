"""Grants that govern no data read say so (GOAL_FOUNDATIONS A4); this pins what they say.

Security's project grants (`POST /projects/{id}/grants`) and Control Panel's role
grants (`POST /admin/roles/grant`) return 201, but reads are scoped by tenancy
memberships alone (`semantic_scope` -> `tenancy.project_permissions`). A principal
granted a role on a project by either, with no membership, reads none of that
project's data. Until decision O retires the grants or wires them into scoping, both
screens say they do not govern data access. This fails the day that stops being
true, so the notes can be revisited.
"""
import os
import tempfile

tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tmpdir.name, 'grants.db')}"
os.environ["AUTH_MODE"] = "local"
os.environ["APP_ENV"] = "test"

from fastapi.testclient import TestClient  # noqa: E402

from app import production_auth  # noqa: E402
from app.main import app  # noqa: E402

client = TestClient(app)
passed = 0


def check(response, label, expected=200):
    global passed
    assert response.status_code == expected, f"{label}: {response.status_code} {response.text[:600]}"
    passed += 1
    return response.json() if response.content else {}


def use(principal):
    app.dependency_overrides[production_auth.current_principal] = lambda: principal


admin = production_auth.Principal("platform-admin", "Admin", None, ["administrator"], ["*"],
                                  organization_id="grants-org", project_ids=["*"])
alpha = production_auth.Principal("alpha-admin", "Alpha", None, ["administrator"], ["*"],
                                  organization_id="grants-org", project_ids=["alpha"])
granted = production_auth.Principal("granted-user", "Granted", None, ["viewer"], ["view"],
                                    organization_id="grants-org", project_ids=[])

use(admin)
check(client.post("/tenancy/organizations", json={"id": "grants-org", "display_name": "Grants Org"}), "organization", 201)
check(client.post("/tenancy/projects", json={"id": "alpha", "organization_id": "grants-org", "display_name": "alpha"}),
      "tenancy project", 201)

use(alpha)
check(client.post("/data-assets", json={
    "id": "alpha-data", "project_id": "alpha", "display_name": "alpha data", "kind": "dataset",
    "asset_schema": {}, "records": [{"id": "alpha-1", "name": "alpha"}],
}), "alpha dataset")
check(client.post("/object-types", json={
    "id": "alpha-asset", "project_id": "alpha", "display_name": "alpha asset",
    "properties": {"id": {"type": "string"}, "name": {"type": "string"}},
}), "alpha object type")
check(client.post("/objects", json={
    "id": "alpha-object", "project_id": "alpha", "object_type_id": "alpha-asset",
    "properties": {"id": "alpha-1", "name": "alpha"}, "source_asset_id": "alpha-data",
}), "alpha object")

# Both grant forms, as an administrator: each returns 201.
use(admin)
check(client.post("/projects", json={"id": "alpha", "display_name": "alpha"}), "Security's project record", 201)
check(client.post("/roles", json={"id": "alpha-reader", "display_name": "Alpha reader", "permissions": ["view"]}),
      "Security role", 201)
check(client.post("/projects/alpha/grants", json={"principal": "granted-user", "role_id": "alpha-reader"}),
      "Security project grant", 201)
check(client.post("/admin/roles/grant", json={
    "scope_type": "project", "scope_id": "alpha", "principal_type": "user",
    "principal_id": "granted-user", "role": "viewer",
}), "Control Panel role grant", 201)

# The granted principal has no membership, and reads nothing of alpha's.
use(granted)
assets = check(client.get("/data-assets"), "granted user's datasets")
assert "alpha-data" not in {row["id"] for row in assets}, assets
passed += 1
types = check(client.get("/object-types"), "granted user's object types")
assert "alpha-asset" not in {row["id"] for row in types}, types
passed += 1
check(client.get("/objects/alpha-asset/alpha-object"), "granted user cannot read alpha's object", 403)

app.dependency_overrides.clear()
print(f"Grants govern no read, as the screens say: {passed} assertions passed.")

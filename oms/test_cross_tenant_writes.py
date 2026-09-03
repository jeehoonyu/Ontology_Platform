"""Three writes that crossed a tenant boundary, each closed and each proved by failing first.

Found by a fan-out audit of all ninety routed modules for one shape: **an id that arrived
inside something already authorized is not itself authorized**. These three are the writes
among the confirmed findings, and they fail differently from one another, which is why they
are worth keeping together.

  * `preview_artifact` took no id at all. It built its `PlatformJob` without naming a
    project, and the column's `default="default"` did the rest, filing a project's artifact
    internals where every job route -- which all scope on that stored column -- would serve
    them to the default project.
  * `apply_shared_property_type` and `detach_shared_property_type` took `object_type_id`
    from the request body. Their router carries `require_permission("edit")`, and that is a
    *tier* check: `production_auth.require_permission` calls `principal.allows(permission)`
    with no project argument at all. Holding `edit` somewhere is not holding it here.

  python oms/test_cross_tenant_writes.py
"""
import os
import tempfile

_t = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(_t.name, 'cross_tenant.db')}"
os.environ["AUTH_MODE"] = "local"
os.environ["APP_ENV"] = "test"

from fastapi.testclient import TestClient  # noqa: E402
from app import models, platform_runtime, production_auth  # noqa: E402
from app.database import SessionLocal  # noqa: E402
from app.main import app  # noqa: E402
from app.ontology_interfaces import SharedPropertyType, SptApplication  # noqa: E402

client = TestClient(app)
passed = 0


def ok(response, label, expect=200):
    global passed
    assert response.status_code == expect, f"{label}: {response.status_code} {response.text[:600]}"
    passed += 1
    return response.json() if response.content else {}


ok(client.post("/tenancy/organizations", json={"id": "xt-org", "display_name": "XT"}),
   "organization", 201)
for pid in ("alpha", "beta"):
    ok(client.post("/tenancy/projects",
                   json={"id": pid, "organization_id": "xt-org", "display_name": pid}),
       f"project {pid}", 201)

PERMS = ["view", "edit", "execute", "publish", "export", "restore"]
alpha_user = production_auth.Principal("alpha-user", "Alpha", None, ["administrator"], PERMS,
                                       organization_id="xt-org", project_ids=["alpha"])
app.dependency_overrides[production_auth.current_principal] = lambda: alpha_user

with SessionLocal() as db:
    db.add(models.ObjectType(id="beta_type", project_id="beta", display_name="Beta type",
                             description=None, properties={"code": {"type": "string"}},
                             created_at=1, updated_at=1))
    db.add(SharedPropertyType(id="spt1", display_name="Code", description="governed",
                              base_type="string", constraints={}, created_at=1))
    # detach refuses a missing application before it ever looks at the object type, so the
    # binding has to exist for the test to reach the write the fix guards.
    db.add(SptApplication(id="spt_app_beta", shared_property_type_id="spt1",
                          object_type_id="beta_type", property_name="code", locked=True,
                          inherited_metadata={}, created_at=1))
    db.commit()


# ---------------------------------------------------------------------------
# (1) A preview files its job in the artifact's project, not "default"
# ---------------------------------------------------------------------------
artifact = ok(client.post("/artifacts", json={
    "id": "xt-artifact", "project_id": "alpha", "artifact_type": "pipeline",
    "display_name": "Alpha pipeline",
    "state": {"nodes": [{"id": "n1", "node_type": "source", "label": "Source"}], "edges": []},
}), "create artifact in alpha", 201)
assert artifact["project_id"] == "alpha", artifact

preview = ok(client.post("/artifacts/xt-artifact/preview", json={"sample_limit": 2, "inputs": {}}),
             "preview the artifact", 202)
with SessionLocal() as db:
    job = db.get(platform_runtime.PlatformJob, preview["job_id"])
    assert job is not None, preview
    assert job.project_id == "alpha", (
        f"preview job filed under {job.project_id!r}; the artifact lives in 'alpha' and every "
        f"job route scopes on this column")
passed += 1


# ---------------------------------------------------------------------------
# (2) and (3) A body-supplied object_type_id cannot reach another project
# ---------------------------------------------------------------------------
ok(client.post("/shared-property-types/spt1/apply",
               json={"object_type_id": "beta_type", "property_name": "code"}),
   "apply cannot govern another project's object type", 403)

ok(client.post("/shared-property-types/spt1/detach",
               json={"object_type_id": "beta_type", "property_name": "code"}),
   "detach cannot unlock another project's property", 403)

with SessionLocal() as db:
    untouched = db.get(models.ObjectType, "beta_type")
    assert untouched.properties == {"code": {"type": "string"}}, untouched.properties
passed += 1

# The same routes still work inside the caller's own project.
ok(client.post("/object-types", json={
    "id": "alpha_type", "project_id": "alpha", "display_name": "Alpha type",
    "properties": {"code": {"type": "string"}},
}), "create an object type in alpha")
applied = ok(client.post("/shared-property-types/spt1/apply",
                         json={"object_type_id": "alpha_type", "property_name": "code"}),
             "apply still governs the caller's own object type")
assert applied["object_type_id"] == "alpha_type", applied

print(f"\nCross-tenant writes verified: {passed} assertions passed.")
from app.database import engine as _engine  # noqa: E402
_engine.dispose()
_t.cleanup()

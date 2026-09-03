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
from app import models, platform_runtime, production_auth, reliability_ops  # noqa: E402
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



# ---------------------------------------------------------------------------
# (4) A backfill plan cannot run another project's pipeline
#
# `BackfillPlan.pipeline_ids` is a caller-authored JSON list, `reliability_ops` held no
# principal anywhere, and `_run_pipeline_backfill` compares a pipeline only to its own
# assets -- so the checks passed and the run overwrote `output_asset.records` in whatever
# project the pipeline belonged to. T7 of GOAL_TENANCY_2026-08-27.
# ---------------------------------------------------------------------------
with SessionLocal() as db:
    db.add(models.DataAsset(id="beta_in", project_id="beta", display_name="in", description=None,
                            kind="dataset", asset_schema={}, records=[{"v": 1}],
                            created_at=1, updated_at=1))
    db.add(models.DataAsset(id="beta_out", project_id="beta", display_name="out", description=None,
                            kind="dataset", asset_schema={}, records=[{"keep": "me"}],
                            created_at=1, updated_at=1))
    db.add(models.PipelineDefinition(id="beta_pipe", project_id="beta", display_name="Beta pipe",
                                     description=None, input_asset_id="beta_in",
                                     output_asset_id="beta_out", mode="batch", schedule=None,
                                     steps=[], created_at=1, updated_at=1))
    db.commit()

# Creating a plan over it reads as "not found" rather than 403, so the route cannot be used
# to probe which pipeline ids exist elsewhere.
ok(client.post("/reliability/backfills",
               json={"id": "xt_plan", "display_name": "Crossing", "pipeline_ids": ["beta_pipe"]}),
   "a plan cannot name another project's pipeline", 404)

# A plan seeded directly, as an already-stored one would be, still must not run it.
with SessionLocal() as db:
    db.add(reliability_ops.BackfillPlan(id="seeded_plan", display_name="Seeded", description=None,
                                        pipeline_ids=["beta_pipe"], asset_ids=[], parameters={},
                                        status="PENDING", run_results=[], created_at=1, updated_at=1))
    db.commit()

run = ok(client.post("/reliability/backfills/seeded_plan/run", json={"actor": "alpha-user"}),
         "running it does not reach the foreign pipeline")
assert all(r.get("status") == "FAILED" for r in run["run_results"]), run
with SessionLocal() as db:
    assert db.get(models.DataAsset, "beta_out").records == [{"keep": "me"}], "beta's output was rewritten"
passed += 2



# ---------------------------------------------------------------------------
# (5) A snapshot import cannot adopt a row owned by another project
#
# `_validate_snapshot_project_scope` checks each row's *claimed* project against the import
# target; `_upsert_model` then found the row to overwrite by id alone, across every project.
# A row claiming "alpha" whose id belongs to "beta" passed validation and was then
# setattr-ed field by field onto beta's row -- project_id included, moving it into alpha.
# T7 of GOAL_TENANCY_2026-08-27.
# ---------------------------------------------------------------------------
snapshot = ok(client.get("/project/export?project_id=alpha"), "export alpha")
assert snapshot.get("object_types") is not None, sorted(snapshot)[:12]

# One row, claiming alpha, carrying beta's id.
snapshot["object_types"] = [dict(row) for row in snapshot["object_types"]] + [{
    "id": "beta_type", "project_id": "alpha", "display_name": "Hijacked",
    "description": None, "properties": {"stolen": {"type": "string"}},
    "created_at": 1, "updated_at": 1,
}]

# The manifest is self-computed, not signed, so an attacker recomputes it and so does this
# test -- otherwise the checksum refuses the request and the tenancy hole is never reached.
from app import system_hardening as _sh  # noqa: E402

counts = {k: len(v) for k, v in snapshot.items() if isinstance(v, list) and k != "rebind_required"}
snapshot["integrity"] = {"algorithm": "sha256", "checksum": _sh._snapshot_checksum(snapshot),
                         "counts": counts, "resource_count": sum(counts.values())}
assert client.post("/project/import/validate", json={"snapshot": snapshot}).json()["status"] == "VALID", \
    "the doctored snapshot must pass validation, or the test is proving the checksum instead"
passed += 1

ok(client.post("/project/import", json={"snapshot": snapshot}),
   "import refuses a row owned by another project", 409)

with SessionLocal() as db:
    victim = db.get(models.ObjectType, "beta_type")
    assert victim.project_id == "beta", f"row was moved into {victim.project_id!r}"
    assert victim.display_name == "Beta type", victim.display_name
    assert victim.properties == {"code": {"type": "string"}}, victim.properties
passed += 3

print(f"\nCross-tenant writes verified: {passed} assertions passed.")
from app.database import engine as _engine  # noqa: E402
_engine.dispose()
_t.cleanup()

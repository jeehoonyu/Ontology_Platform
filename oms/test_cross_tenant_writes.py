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

A convention this file learned the hard way, twice: assert on a **named** field and assert
the field exists. Two checks here were first written as `response.get("last_job") or {}` and
`seen.get("implementers", [])`, and both fields are called something else -- so both passed
whatever the code did, and only reverting the fix and watching the test stay green revealed
it. A security assertion that cannot fail is worse than no assertion, because it reports
coverage that does not exist.

  python oms/test_cross_tenant_writes.py
"""
import json
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



# ---------------------------------------------------------------------------
# (6) A sync cannot be pointed at another project's dataset
#
# `target_asset_id` is a pointer out of the sync row, so `_sync_or_404` proves nothing about
# it. Unscoped, `run_sync` and `run_incremental` appended records into whatever it named.
# T2 of GOAL_TENANCY_2026-08-27.
# ---------------------------------------------------------------------------
source = ok(client.post("/connections/sources", json={
    "id": "alpha_src", "project_id": "alpha", "display_name": "Alpha source",
    "source_type": "jdbc", "config": {"url": "jdbc:postgresql://db/x"},
}), "create a source in alpha")

# 403 when the caller cannot see the target at all, 409 when they can see it but it belongs
# elsewhere. Either is a refusal; which one fires depends on the caller's reach.
crossing = client.post("/connections/sources/alpha_src/syncs", json={
    "id": "crossing_sync", "target_asset_id": "beta_out", "mode": "incremental",
    "cursor_field": "v", "sample_records": [{"v": 99}],
})
assert crossing.status_code in (403, 409), \
    f"a sync cannot target another project's dataset: {crossing.status_code} {crossing.text[:300]}"
passed += 1

with SessionLocal() as db:
    assert db.get(models.DataAsset, "beta_out").records == [{"keep": "me"}], "beta's dataset was written"
passed += 1



# ---------------------------------------------------------------------------
# (7) The interface routes stay inside the caller's projects
#
# Three shapes in one module family: a path id (`implement_interface`), a body id
# (`check_object_type_conformance`), and an unfiltered enumeration
# (`list_interface_implementers`, which returned every matching object type in the
# installation). T2 of GOAL_TENANCY_2026-08-27.
# ---------------------------------------------------------------------------
iface = ok(client.post("/interfaces", json={
    "id": "iface1", "api_name": "Coded", "display_name": "Coded",
    "properties": {"code": {"base_type": "string"}},
}), "create an interface")

ok(client.post("/object-types/beta_type/implement-interface",
               json={"interface_id": "iface1", "property_mappings": {"code": "code"}}),
   "cannot bind another project's object type to an interface", 403)

ok(client.post("/interfaces/iface1/check-object-type", json={"object_type_id": "beta_type"}),
   "cannot ask what another project's object type declares", 403)

seen = ok(client.get("/interfaces/iface1/implementers"), "implementers stay in reach")
# Name the key rather than .get(...) with a default -- a renamed field would otherwise make
# this assertion vacuous, which is exactly how it read the first time.
assert "implementer_object_type_ids" in seen, seen
assert "beta_type" not in seen["implementer_object_type_ids"], seen
assert "alpha_type" in seen["implementer_object_type_ids"], (
    "the caller's own matching type must still be listed, or this is passing by emptiness")
passed += 2



# ---------------------------------------------------------------------------
# (8) Marking propagation stops at the edge of what the caller administers
#
# The route applied ResourceMarking rows -- mandatory controls -- to every dataset reachable
# through *any* project's pipeline definitions, and returned each one's id and effective
# markings. T2 of GOAL_TENANCY_2026-08-27.
# ---------------------------------------------------------------------------
with SessionLocal() as db:
    db.add(models.PipelineDefinition(id="beta_lineage", project_id="beta",
                                     display_name="Beta lineage", description=None,
                                     input_asset_id="alpha_src_asset", output_asset_id="beta_out",
                                     mode="batch", schedule=None, steps=[],
                                     created_at=1, updated_at=1))
    db.add(models.DataAsset(id="alpha_src_asset", project_id="alpha", display_name="src",
                            description=None, kind="dataset", asset_schema={}, records=[],
                            created_at=1, updated_at=1))
    db.commit()

admin_alpha = production_auth.Principal("alpha-admin", "AlphaAdmin", None, ["administrator"],
                                        PERMS + ["administer"], organization_id="xt-org",
                                        project_ids=["alpha"])
app.dependency_overrides[production_auth.current_principal] = lambda: admin_alpha
spread = ok(client.post("/security/markings/propagate?dataset_id=alpha_src_asset"),
            "propagation does not walk into another project")
reached = [row["dataset_id"] for row in spread["downstream"]]
assert "beta_out" not in reached, spread
app.dependency_overrides[production_auth.current_principal] = lambda: alpha_user
passed += 1



# ---------------------------------------------------------------------------
# (9) Another project's job cannot pose as an artifact's latest job
#
# `_artifact_dict` matched jobs on `subject_id`, and `create_job` accepts `subject_id` from
# the request body within the caller's own project -- so a job raised elsewhere naming this
# artifact's id appeared as its latest job in every artifact response.
# T2 of GOAL_TENANCY_2026-08-27.
# ---------------------------------------------------------------------------
_ts3 = int(__import__("time").time())
with SessionLocal() as db:
    db.add(platform_runtime.PlatformJob(
        id="impostor_job", project_id="beta", job_type="pipeline.run", status="FAILED",
        actor="someone-else", subject_type="artifact", subject_id="xt-artifact",
        payload={}, result={"leaked": "beta"}, attempt=1, progress=100,
        created_at=_ts3 + 999, updated_at=_ts3 + 999,
    ))
    db.commit()

view = ok(client.get("/artifacts/xt-artifact"), "read the alpha artifact")
# The field is "execution", not "last_job". Naming it wrongly made the first version of this
# assertion pass whatever the code did -- the same way the implementers check did.
assert "execution" in view, sorted(view)
assert (view["execution"] or {}).get("id") != "impostor_job", view["execution"]
assert (view["execution"] or {}).get("project_id") in (None, "alpha"), view["execution"]
passed += 1



# ---------------------------------------------------------------------------
# (10) Adopting an object type does not drag another project's schema in with it
#
# `adopt_resource` checks the object type against `body.project_id`, then followed link types
# naming it without the same filter -- so another project's linked object types were resolved
# and their property names and declared types rendered into the artifact's node fields.
# T2 of GOAL_TENANCY_2026-08-27.
# ---------------------------------------------------------------------------
with SessionLocal() as db:
    db.add(models.ObjectType(id="beta_secret_type", project_id="beta", display_name="Beta secret",
                             description=None, properties={"ssn": {"type": "string"}},
                             created_at=1, updated_at=1))
    db.add(models.LinkType(id="beta_link", project_id="beta", display_name="Crosses",
                           description=None, source_object_type_id="alpha_type",
                           target_object_type_id="beta_secret_type", cardinality="MANY_TO_ONE"))
    db.commit()

adopted = ok(client.post("/artifacts/adopt", json={
    "project_id": "alpha", "resource_type": "object_type", "resource_id": "alpha_type",
    "display_name": "Adopted alpha type",
}), "adopt the caller's own object type", 201)

rendered = json.dumps(adopted)
assert "beta_secret_type" not in rendered, "another project's object type was rendered in"
assert "ssn" not in rendered, "another project's property names were rendered in"
passed += 2

print(f"\nCross-tenant writes verified: {passed} assertions passed.")
from app.database import engine as _engine  # noqa: E402
_engine.dispose()
_t.cleanup()

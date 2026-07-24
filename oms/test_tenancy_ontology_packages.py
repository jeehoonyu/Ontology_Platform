"""Project isolation and governed ontology package lifecycle."""
import os
import tempfile

tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tmpdir.name, 'packages.db')}"
os.environ["AUTH_MODE"] = "local"
os.environ["APP_ENV"] = "test"

from fastapi.testclient import TestClient  # noqa: E402
from app.database import SessionLocal  # noqa: E402
from app.main import app  # noqa: E402
from app import models, models_action, ontology_core, production_auth, tenancy  # noqa: E402

client = TestClient(app)
passed = 0


def ok(response, label, expect=200):
    global passed
    assert response.status_code == expect, f"{label}: {response.status_code} {response.text[:1600]}"
    passed += 1
    return response.json() if response.content else {}


for organization in (
    {"id": "acme", "display_name": "Acme Operations"},
    {"id": "other_org", "display_name": "Other Organization"},
):
    ok(client.post("/tenancy/organizations", json=organization), "create organization", 201)
for project in (
    {"id": "ontology_source", "organization_id": "acme", "display_name": "Ontology Source"},
    {"id": "operations_target", "organization_id": "acme", "display_name": "Operations Target"},
    {"id": "private_project", "organization_id": "other_org", "display_name": "Private Project"},
):
    ok(client.post("/tenancy/projects", json=project), "create project", 201)

with SessionLocal() as db:
    now = 1
    for project_id, principal_id, role in (
        ("ontology_source", "alice", "publisher"),
        ("operations_target", "alice", "publisher"),
        ("ontology_source", "bob", "viewer"),
        ("private_project", "carol", "editor"),
    ):
        db.add(tenancy.ProjectMembership(id=f"member_{project_id}_{principal_id}", project_id=project_id, principal_id=principal_id, role=role, permissions=["restore"] if principal_id == "alice" else [], created_at=now, updated_at=now))
    db.add_all([
        models.ObjectType(id="asset", display_name="Asset", description="Operational asset", properties={"asset_id": {"type": "string", "required": True}, "status": {"type": "string"}, "__manager": {"primary_key": "asset_id"}}, created_at=now, updated_at=now),
        models.ObjectType(id="facility", display_name="Facility", description="Operating facility", properties={"facility_id": {"type": "string", "required": True}}, created_at=now, updated_at=now),
        models.LinkType(id="located_at", display_name="Located at", description=None, source_object_type_id="asset", target_object_type_id="facility", cardinality="MANY_TO_ONE"),
        models.ActionType(id="inspect_asset", display_name="Inspect asset", description="Request inspection", parameters={"asset_id": {"type": "string"}}, rules={"requires_approval": True}),
        ontology_core.ObjectTypeProfile(object_type_id="asset", api_name="Asset", primary_key="asset_id", title_key="asset_id", icon="wrench", color="#176b8f", plural_name="Assets", groups=["Reliability"], properties={"asset_id": {"base_type": "string", "required": True}}, created_at=now, updated_at=now),
    ])
    db.commit()

active_principal = production_auth.Principal("alice", "Alice", "alice@example.test", ["publisher"], ["view", "edit", "publish", "restore", "export"], organization_id="acme", project_ids=[])
app.dependency_overrides[production_auth.current_principal] = lambda: active_principal

package = ok(client.post("/ontology-packages", json={
    "id": "asset_reliability", "organization_id": "acme", "owning_project_id": "ontology_source",
    "display_name": "Asset Reliability", "description": "Reusable reliability ontology",
}), "create governed package", 201)
assert package["status"] == "DRAFT"

version1 = ok(client.post("/ontology-packages/asset_reliability/versions/capture", json={
    "version": "1.0.0", "object_type_ids": ["asset", "facility"], "action_type_ids": ["inspect_asset"],
}), "capture package resources", 201)
assert version1["validation"]["status"] == "PASS" and len(version1["checksum"]) == 64
ok(client.post("/ontology-packages/asset_reliability/versions/1.0.0/publish", json={"expected_checksum": version1["checksum"]}), "publish package")

bad_checksum = client.post("/ontology-packages/asset_reliability/versions/1.0.0/install", json={"target_project_id": "operations_target", "namespace": "reliability", "expected_checksum": "0" * 64})
ok(bad_checksum, "reject altered package checksum", 409)
install1 = ok(client.post("/ontology-packages/asset_reliability/versions/1.0.0/install", json={"target_project_id": "operations_target", "namespace": "reliability", "expected_checksum": version1["checksum"]}), "install package", 201)
assert {row["resource_id"] for row in install1["installed_resources"]} >= {"reliability__asset", "reliability__facility", "reliability__located_at", "reliability__inspect_asset"}
replayed_install = ok(client.post("/ontology-packages/asset_reliability/versions/1.0.0/install", json={"target_project_id": "operations_target", "namespace": "reliability"}), "replay package install", 201)
assert replayed_install["id"] == install1["id"] and replayed_install["idempotent_replay"] is True

with SessionLocal() as db:
    installed_asset = db.get(models.ObjectType, "reliability__asset")
    assert installed_asset and installed_asset.properties["__package"]["version"] == "1.0.0"
    installed_profile = db.get(ontology_core.ObjectTypeProfile, "reliability__asset")
    assert installed_profile and installed_profile.primary_key == "asset_id" and installed_profile.groups == ["Reliability"]
    assert db.get(models.LinkType, "reliability__located_at").target_object_type_id == "reliability__facility"

manifest2 = dict(version1["manifest"])
manifest2["object_types"] = [dict(item) for item in manifest2["object_types"]]
asset2 = next(item for item in manifest2["object_types"] if item["id"] == "asset")
asset2["properties"] = {**asset2["properties"], "risk_score": {"type": "number"}}
version2 = ok(client.post("/ontology-packages/asset_reliability/versions", json={"version": "1.1.0", "manifest": manifest2}), "create upgrade version", 201)
ok(client.post("/ontology-packages/asset_reliability/versions/1.1.0/publish", json={"expected_checksum": version2["checksum"]}), "publish upgrade")
install2 = ok(client.post("/ontology-packages/asset_reliability/versions/1.1.0/install", json={"target_project_id": "operations_target", "namespace": "reliability"}), "upgrade package", 201)
assert install2["previous_installation_id"] == install1["id"]
with SessionLocal() as db:
    assert "risk_score" in db.get(models.ObjectType, "reliability__asset").properties

rollback = ok(client.post(f"/ontology-package-installations/{install2['id']}/rollback", json={}), "rollback package upgrade")
assert rollback["restored_installation_id"] == install1["id"]
with SessionLocal() as db:
    assert "risk_score" not in db.get(models.ObjectType, "reliability__asset").properties

install3 = ok(client.post("/ontology-packages/asset_reliability/versions/1.1.0/install", json={"target_project_id": "operations_target", "namespace": "reliability_v2"}), "install independent namespace", 201)
with SessionLocal() as db:
    db.add(models.ObjectInstance(id="live_packaged_asset", object_type_id="reliability_v2__asset", properties={"asset_id": "A-1"}, source_asset_id=None, lineage={}, created_at=2, updated_at=2))
    db.commit()
blocked_rollback = client.post(f"/ontology-package-installations/{install3['id']}/rollback", json={})
ok(blocked_rollback, "protect live objects during rollback", 409)

artifact = ok(client.post("/artifacts", json={"id": "source_workshop", "project_id": "ontology_source", "artifact_type": "workshop", "display_name": "Source workshop", "state": {"nodes": [], "edges": []}}), "create project artifact", 201)
assert artifact["project_id"] == "ontology_source"

active_principal = production_auth.Principal("bob", "Bob", "bob@example.test", ["editor"], ["view", "edit"], organization_id="acme", project_ids=[])
ok(client.get("/artifacts/source_workshop"), "viewer reads project artifact")
ok(client.post("/artifacts", json={"project_id": "ontology_source", "artifact_type": "workshop", "display_name": "Forbidden"}), "viewer cannot create project artifact", 403)
ok(client.get("/ontology-packages"), "viewer lists accessible package")
ok(client.post("/ontology-packages/asset_reliability/versions/1.0.0/install", json={"target_project_id": "operations_target", "namespace": "forbidden"}), "viewer cannot install into inaccessible project", 403)

active_principal = production_auth.Principal("carol", "Carol", "carol@example.test", ["editor"], ["view", "edit"], organization_id="other_org", project_ids=[])
ok(client.get("/artifacts/source_workshop"), "cross-organization artifact read denied", 403)
ok(client.post("/artifacts/source_workshop/collaboration/join", json={"client_id": "carol-browser"}), "cross-organization collaboration denied", 403)
assert ok(client.get("/ontology-packages"), "cross-organization package list filtered") == []

active_principal = production_auth.Principal("alice", "Alice", "alice@example.test", ["publisher"], ["view", "edit", "publish", "restore", "export"], organization_id="acme", project_ids=[])
exported = ok(client.get("/ontology-packages/asset_reliability/versions/1.0.0/export"), "export package")
assert exported["integrity"]["verified"] is True
snapshot = ok(client.get("/project/export"), "export project recovery snapshot")
assert snapshot["ontology_packages"] and snapshot["ontology_package_versions"] and snapshot["ontology_package_installations"]
assert snapshot["projects"] and snapshot["project_memberships"]

with SessionLocal() as db:
    event_types = {row.event_type for row in db.query(models_action.AuditLog).filter(models_action.AuditLog.subject_type == "ontology_package").all()}
    assert {"ontology.package.created", "ontology.package.published", "ontology.package.installed", "ontology.package.rolled_back"} <= event_types

app.dependency_overrides.clear()
print(f"Tenancy and ontology packages verified: {passed} assertions passed.")

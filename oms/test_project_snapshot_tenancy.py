"""Project snapshots are isolated, dependency-complete, and cleanly restorable."""
import copy
import os
import tempfile

tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tmpdir.name, 'snapshot_source.db')}"
os.environ["AUTH_MODE"] = "local"
os.environ["APP_ENV"] = "test"

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402
from app import ops_control, platform_runtime, production_auth, system_hardening, tenancy  # noqa: E402
from app.database import Base  # noqa: E402
from app.main import app  # noqa: E402
from app.models import DataAsset  # noqa: E402

client = TestClient(app)
passed = 0


def check(response, label, expected=200):
    global passed
    assert response.status_code == expected, f"{label}: {response.status_code} {response.text[:1200]}"
    passed += 1
    return response.json() if response.content else {}


check(client.post("/tenancy/organizations", json={"id": "snapshot-org", "display_name": "Snapshot Org"}), "organization", 201)
for project_id in ("alpha", "beta"):
    check(client.post("/tenancy/projects", json={"id": project_id, "organization_id": "snapshot-org", "display_name": project_id}), project_id, 201)

alpha = production_auth.Principal("alpha-admin", "Alpha", None, ["administrator"], ["*"], organization_id="snapshot-org", project_ids=["alpha"])
beta = production_auth.Principal("beta-admin", "Beta", None, ["administrator"], ["*"], organization_id="snapshot-org", project_ids=["beta"])


def use(principal):
    app.dependency_overrides[production_auth.current_principal] = lambda: principal


def seed(project_id):
    check(client.post("/data-assets", json={
        "id": f"{project_id}-asset", "project_id": project_id, "display_name": project_id,
        "kind": "dataset", "asset_schema": {}, "records": [{"id": project_id}],
    }), f"{project_id} dataset")
    artifact = check(client.post("/artifacts", json={
        "id": f"{project_id}-artifact", "project_id": project_id,
        "artifact_type": "pipeline", "display_name": project_id,
        "state": {"nodes": [], "edges": []},
    }), f"{project_id} artifact", 201)
    assert artifact["project_id"] == project_id
    check(client.post("/ops/events/ingest", json={
        "project_id": project_id, "source": "snapshot", "event_type": "snapshot.seeded",
        "severity": "info", "title": project_id,
    }), f"{project_id} event")
    check(client.post("/ops/incidents", json={
        "id": f"{project_id}-incident", "project_id": project_id,
        "display_name": f"{project_id} incident",
    }), f"{project_id} incident")
    check(client.post("/connections/webhooks", json={
        "id": f"{project_id}-webhook", "project_id": project_id,
        "display_name": project_id, "mode": "writeback",
    }), f"{project_id} webhook")


use(alpha)
seed("alpha")
use(beta)
seed("beta")

use(alpha)
snapshot = check(client.get("/project/export"), "alpha export")
assert snapshot["snapshot_version"] == 3
assert snapshot["project_scope"]["project_id"] == "alpha"
assert {row["id"] for row in snapshot["projects"]} == {"alpha"}
assert {row["project_id"] for row in snapshot["data_assets"]} == {"alpha"}
assert {row["project_id"] for row in snapshot["ops_events"]} == {"alpha"}
assert {row["project_id"] for row in snapshot["incidents"]} == {"alpha"}
assert {row["project_id"] for row in snapshot["webhooks"]} == {"alpha"}
assert {row["artifact_id"] for row in snapshot["platform_artifact_revisions"]} == {"alpha-artifact"}
assert "beta-" not in str(snapshot), "snapshot leaked beta resources"
passed += 8

check(client.get("/project/export", params={"project_id": "beta"}), "alpha cannot export beta", 403)
use(beta)
check(client.post("/project/import/validate", json={"snapshot": snapshot}), "beta cannot validate alpha restore", 403)

use(alpha)
tampered = copy.deepcopy(snapshot)
tampered.pop("integrity", None)
tampered["data_assets"].append({
    "id": "beta-injected", "project_id": "beta", "display_name": "injected",
    "kind": "dataset", "asset_schema": {}, "records": [],
})
tampered = system_hardening._finalize_snapshot(tampered)
invalid = check(client.post("/project/import/validate", json={"snapshot": tampered}), "foreign row rejected")
assert invalid["status"] == "INVALID" and any("beta" in error for error in invalid["errors"]), invalid
passed += 1
legacy = check(client.post("/project/import/validate", json={
    "snapshot": {"snapshot_version": 1}, "project_id": "alpha", "allow_legacy": True,
}), "project admin cannot restore global legacy snapshot")
assert legacy["status"] == "INVALID" and any("system-wide" in error for error in legacy["errors"]), legacy
passed += 1

# Restore into a clean database and prove both ownership and child dependency closure.
restore_path = os.path.join(tmpdir.name, "snapshot_restore.db")
restore_engine = create_engine(f"sqlite:///{restore_path}")
Base.metadata.create_all(bind=restore_engine)
restore_principal = production_auth.Principal(
    "restore-admin", "Restore", None, ["administrator"], ["*"],
    organization_id="snapshot-org", project_ids=["*"],
)
with Session(restore_engine) as db:
    result = system_hardening.import_project(
        system_hardening.ProjectImportRequest(snapshot=snapshot),
        db=db,
        principal=restore_principal,
    )
    assert result["status"] == "IMPORTED" and result["project_id"] == "alpha", result
    assert db.get(tenancy.PlatformProject, "alpha") is not None
    assert db.get(tenancy.PlatformProject, "beta") is None
    assert db.get(DataAsset, "alpha-asset").project_id == "alpha"
    assert db.get(DataAsset, "beta-asset") is None
    assert db.get(platform_runtime.PlatformArtifact, "alpha-artifact").project_id == "alpha"
    revisions = db.query(platform_runtime.ArtifactRevision).filter(
        platform_runtime.ArtifactRevision.artifact_id == "alpha-artifact"
    ).count()
    assert revisions == 1
    assert db.get(ops_control.Incident, "alpha-incident").project_id == "alpha"
    assert db.get(ops_control.Incident, "beta-incident") is None
    passed += 9

restore_engine.dispose()
app.dependency_overrides.clear()
print(f"\nProject snapshot tenancy and clean restore verified: {passed} assertions passed.")

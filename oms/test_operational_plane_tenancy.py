"""Operational control resources remain isolated across projects."""
import os
import tempfile

tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tmpdir.name, 'operational_tenancy.db')}"
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


check(client.post("/tenancy/organizations", json={"id": "ops-org", "display_name": "Ops Org"}), "organization", 201)
for project_id in ("alpha", "beta"):
    check(client.post("/tenancy/projects", json={"id": project_id, "organization_id": "ops-org", "display_name": project_id}), project_id, 201)

alpha = production_auth.Principal("alpha-admin", "Alpha", None, ["administrator"], ["*"], organization_id="ops-org", project_ids=["alpha"])
beta = production_auth.Principal("beta-admin", "Beta", None, ["administrator"], ["*"], organization_id="ops-org", project_ids=["beta"])
viewer = production_auth.Principal("alpha-viewer", "Viewer", None, ["viewer"], ["view"], organization_id="ops-org", project_ids=["alpha"])


def use(principal):
    app.dependency_overrides[production_auth.current_principal] = lambda: principal


def seed(project_id):
    check(client.post("/data-assets", json={
        "id": f"{project_id}-asset", "project_id": project_id, "display_name": project_id,
        "kind": "dataset", "asset_schema": {}, "records": [],
    }), f"{project_id} asset")
    check(client.post("/ops/alert-rules", json={
        "id": f"{project_id}-rule", "project_id": project_id, "display_name": project_id,
        "min_severity": "low", "expression": {},
    }), f"{project_id} rule")
    event = check(client.post("/ops/events/ingest", json={
        "project_id": project_id, "source": "test", "event_type": "test.event",
        "severity": "high", "title": f"{project_id} event",
    }), f"{project_id} event")
    check(client.post("/ops/incidents", json={
        "id": f"{project_id}-incident", "project_id": project_id,
        "display_name": f"{project_id} incident", "alert_ids": [],
    }), f"{project_id} incident")
    check(client.post("/investigations", json={
        "id": f"{project_id}-investigation", "project_id": project_id,
        "display_name": f"{project_id} investigation", "incident_ids": [f"{project_id}-incident"],
    }), f"{project_id} investigation")
    check(client.post("/schedules", json={
        "id": f"{project_id}-schedule", "project_id": project_id, "display_name": project_id,
        "target_type": "pipeline", "target_id": f"{project_id}-future-pipeline",
        "trigger_type": "cron", "cron": "0 * * * *",
    }), f"{project_id} schedule", 201)
    check(client.post("/connections/webhooks", json={
        "id": f"{project_id}-webhook", "project_id": project_id,
        "display_name": project_id, "mode": "writeback",
    }), f"{project_id} webhook")
    check(client.post("/listeners", json={
        "id": f"{project_id}-listener", "project_id": project_id, "display_name": project_id,
        "auth_type": "bearer", "auth_secret": f"{project_id}-secret",
        "target_asset_id": f"{project_id}-asset", "event_schema": {"required": ["id"]},
    }), f"{project_id} listener")
    return event


use(alpha)
seed("alpha")
use(beta)
seed("beta")

assert [row["id"] for row in check(client.get("/ops/alert-rules"), "beta rules")] == ["beta-rule"]
assert all(row["project_id"] == "beta" for row in check(client.get("/ops/events"), "beta events"))
assert [row["id"] for row in check(client.get("/ops/incidents"), "beta incidents")] == ["beta-incident"]
assert [row["id"] for row in check(client.get("/investigations"), "beta investigations")] == ["beta-investigation"]
assert [row["id"] for row in check(client.get("/schedules"), "beta schedules")] == ["beta-schedule"]
assert [row["id"] for row in check(client.get("/connections/webhooks"), "beta webhooks")] == ["beta-webhook"]
assert [row["id"] for row in check(client.get("/listeners"), "beta listeners")] == ["beta-listener"]

check(client.get("/ops/incidents/alpha-incident"), "beta cannot read alpha incident", 403)
check(client.get("/investigations/alpha-investigation"), "beta cannot read alpha investigation", 403)
check(client.get("/schedules/alpha-schedule"), "beta cannot read alpha schedule", 403)
check(client.get("/connections/webhooks/alpha-webhook"), "beta cannot read alpha webhook", 403)
check(client.get("/listeners/alpha-listener"), "beta cannot read alpha listener", 403)
check(client.post("/investigations", json={
    "id": "cross-investigation", "project_id": "beta", "display_name": "cross",
    "incident_ids": ["alpha-incident"],
}), "cross-project incident rejected", 422)
check(client.post("/listeners", json={
    "id": "cross-listener", "project_id": "beta", "display_name": "cross",
    "target_asset_id": "alpha-asset",
}), "cross-project listener asset rejected", 403)

use(viewer)
check(client.get("/ops/incidents/alpha-incident"), "viewer reads own incident")
check(client.post("/ops/incidents", json={
    "id": "viewer-incident", "project_id": "alpha", "display_name": "denied",
}), "viewer cannot create incident", 403)
check(client.post("/schedules/alpha-schedule/trigger"), "viewer cannot trigger schedule", 403)

# Inbound delivery is authenticated by the listener secret and remains bound to its project.
app.dependency_overrides.clear()
check(client.post("/listeners/beta-listener/events", headers={"Authorization": "Bearer beta-secret"}, json={"id": "evt-1"}), "listener delivery")
use(beta)
asset = check(client.get("/data-assets/beta-asset"), "beta asset after listener")
assert asset["records"] == [{"id": "evt-1"}], asset
use(alpha)
asset = check(client.get("/data-assets/alpha-asset"), "alpha asset unchanged")
assert asset["records"] == [], asset

app.dependency_overrides.clear()
print(f"\nOperational plane tenancy verified: {passed} assertions passed.")

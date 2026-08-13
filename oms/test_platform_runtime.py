"""Versioned artifacts, leases, job evidence, and local auth boundary."""
import os
import tempfile
import time

tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tmpdir.name, 'platform_runtime.db')}"
os.environ["AUTH_MODE"] = "local"
os.environ["APP_ENV"] = "test"

from fastapi.testclient import TestClient  # noqa: E402
from app.main import app  # noqa: E402

client = TestClient(app)
passed = 0


def ok(response, label, expect=200):
    global passed
    assert response.status_code == expect, f"{label}: {response.status_code} {response.text[:800]}"
    passed += 1
    return response.json() if response.content else {}


session = ok(client.get("/auth/session"), "local auth session")
assert session["authenticated"] and "*" in session["permissions"], session

artifact = ok(client.post("/artifacts", json={
    "id": "pipeline_asset_reliability",
    "artifact_type": "pipeline",
    "display_name": "Asset reliability pipeline",
    "state": {
        "nodes": [
            {"id": "input", "type": "dataset_input"},
            {"id": "output", "type": "dataset_output"},
        ],
        "edges": [{"source": "input", "target": "output"}],
    },
    "layout": {"input": {"x": 40, "y": 100}, "output": {"x": 420, "y": 100}},
}), "create artifact", 201)
assert artifact["current_revision"] == 1 and artifact["validation"]["status"] == "PASS", artifact

lease = ok(client.post("/artifacts/pipeline_asset_reliability/leases", json={"ttl_seconds": 120}), "acquire lease")
assert lease["token"], lease

updated = ok(client.patch("/artifacts/pipeline_asset_reliability", json={
    "expected_lock_version": artifact["lock_version"],
    "lease_token": lease["token"],
    "state": {
        "nodes": [
            {"id": "input", "type": "dataset_input"},
            {"id": "filter", "type": "filter"},
            {"id": "output", "type": "dataset_output"},
        ],
        "edges": [
            {"source": "input", "target": "filter"},
            {"source": "filter", "target": "output"},
        ],
    },
    "message": "Add risk filter",
}), "update artifact")
assert updated["current_revision"] == 2 and updated["lock_version"] == 2, updated

conflict = client.patch("/artifacts/pipeline_asset_reliability", json={
    "expected_lock_version": 1,
    "lease_token": lease["token"],
    "message": "stale update",
})
assert conflict.status_code == 409, conflict.text
passed += 1

published = ok(client.post("/artifacts/pipeline_asset_reliability/publish", json={
    "expected_lock_version": updated["lock_version"],
}), "publish artifact")
assert published["status"] == "PUBLISHED" and published["published_revision"] == 2, published

versions = ok(client.get("/artifacts/pipeline_asset_reliability/versions"), "list versions")
assert [row["revision"] for row in versions] == [2, 1], versions

diff = ok(client.get("/artifacts/pipeline_asset_reliability/diff?from_revision=1&to_revision=2"), "diff versions")
assert any(change["path"] == "/nodes" for change in diff["changed"]), diff

restored = ok(client.post("/artifacts/pipeline_asset_reliability/versions/1/restore"), "restore version")
assert restored["current_revision"] == 3 and restored["status"] == "DRAFT", restored

job = ok(client.post("/jobs", json={"job_type": "pipeline.preview", "subject_type": "artifact", "subject_id": artifact["id"]}), "create job", 201)
assert job["status"] == "QUEUED", job
cancelled = ok(client.post(f"/jobs/{job['id']}/cancel"), "cancel job")
assert cancelled["status"] == "CANCELLED", cancelled
retried = ok(client.post(f"/jobs/{job['id']}/retry"), "retry job")
assert retried["status"] == "QUEUED" and retried["attempt"] == 2, retried
detail = ok(client.get(f"/jobs/{job['id']}"), "job detail")
assert [event["event_type"] for event in detail["events"]] == ["job.queued", "job.cancelled", "job.retried"], detail

events = client.get(f"/events/stream?job_id={job['id']}&once=true")
assert events.status_code == 200 and "event: job.queued" in events.text and "text/event-stream" in events.headers["content-type"], events.text
passed += 1

migrations = ok(client.get("/system/migrations"), "migration history")
assert migrations["current_version"] >= 4, migrations

ok(client.post("/data-assets", json={
    "id": "adopt_input", "display_name": "Adopt input", "kind": "dataset", "asset_schema": {}, "records": [{"id": "1"}],
}), "create adoption input")
ok(client.post("/pipeline-builder/graphs", json={
    "id": "adopt_graph", "display_name": "Adopt graph",
    "nodes": [{"id": "input", "type": "input_dataset", "config": {"asset_id": "adopt_input"}}], "edges": [],
}), "create adoption graph", 201)
adopted = ok(client.post("/artifacts/adopt", json={"resource_type": "pipeline_builder_graph", "resource_id": "adopt_graph"}), "adopt pipeline graph", 201)
assert adopted["artifact_type"] == "pipeline" and adopted["state"]["nodes"][0]["data"]["nodeType"] == "input_dataset", adopted

# Production boundary: OIDC mode rejects anonymous requests and enforces the
# role-derived permission set for an authenticated viewer session.
from app.database import SessionLocal  # noqa: E402
from app.production_auth import AuthSession, SESSION_COOKIE  # noqa: E402

os.environ["APP_ENV"] = "production"
os.environ["AUTH_MODE"] = "oidc"
os.environ["OIDC_ISSUER"] = "https://id.example.test/realms/ontology"
os.environ["OIDC_CLIENT_ID"] = "ontology-platform"
client.cookies.clear()
ok(client.get("/artifacts"), "production anonymous denied", expect=401)
with SessionLocal() as db:
    now = int(time.time())
    db.add(AuthSession(
        id="viewer_session",
        principal_id="viewer@example.test",
        email="viewer@example.test",
        display_name="Pilot Viewer",
        roles=["viewer"],
        claims={},
        created_at=now,
        expires_at=now + 300,
        last_seen_at=now,
    ))
    db.commit()
client.cookies.set(SESSION_COOKIE, "viewer_session")
ok(client.get("/artifacts"), "production viewer read")
ok(client.post("/artifacts", json={
    "artifact_type": "workshop",
    "display_name": "Forbidden edit",
    "state": {"widgets": []},
}), "production viewer edit denied", expect=403)
ok(client.post("/jobs", json={
    "job_type": "pipeline.preview",
}), "production viewer execution denied", expect=403)
os.environ["APP_ENV"] = "test"
os.environ["AUTH_MODE"] = "local"
client.cookies.clear()

print(f"\nPlatform runtime verified: {passed} assertions passed.")
from app.database import engine as _engine  # noqa: E402
_engine.dispose()
tmpdir.cleanup()

"""Cross-stream processors cannot correlate or expose resources across projects."""

import os
import tempfile


temporary = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(temporary.name, 'cross-stream-tenancy.db')}"
os.environ["AUTH_MODE"] = "local"
os.environ["APP_ENV"] = "test"

from fastapi.testclient import TestClient  # noqa: E402
from app.main import app  # noqa: E402
from app import production_auth  # noqa: E402
from app.database import engine  # noqa: E402


client = TestClient(app)
passed = 0


def checked(response, label, expected=200):
    global passed
    assert response.status_code == expected, f"{label}: {response.status_code} {response.text[:1600]}"
    passed += 1
    return response.json() if response.content else {}


checked(client.post("/tenancy/organizations", json={
    "id": "join-org", "display_name": "Join Organization",
}), "organization", 201)
for project_id in ("alpha", "beta"):
    checked(client.post("/tenancy/projects", json={
        "id": project_id, "organization_id": "join-org", "display_name": project_id.title(),
    }), f"{project_id} project", 201)
    checked(client.post("/data-assets", json={
        "id": f"{project_id}-join-output", "project_id": project_id,
        "display_name": f"{project_id} join output", "kind": "dataset",
        "asset_schema": {}, "records": [],
    }), f"{project_id} output")
    for side in ("left", "right"):
        checked(client.post("/streams", json={
            "id": f"{project_id}-{side}", "project_id": project_id,
            "display_name": f"{project_id} {side}",
            "schema": {"event_ts": "number", "asset_id": "string"},
        }), f"{project_id} {side} stream")


def principal(project_id):
    return production_auth.Principal(
        f"{project_id}-operator", project_id.title(), None,
        ["administrator"], ["*"], organization_id="join-org", project_ids=[project_id],
    )


def use(project_id):
    scoped = principal(project_id)
    app.dependency_overrides[production_auth.current_principal] = lambda: scoped


def processor_payload(project_id, processor_id=None):
    return {
        "id": processor_id or f"{project_id}-join", "project_id": project_id,
        "stream_id": f"{project_id}-left", "join_stream_id": f"{project_id}-right",
        "display_name": f"{project_id} join", "timestamp_field": "event_ts",
        "join_left_key": "asset_id", "join_right_key": "asset_id",
        "join_time_tolerance_seconds": 10,
        "target_asset_id": f"{project_id}-join-output",
    }


use("alpha")
checked(client.post("/api/v1/streams/processors", json=processor_payload("alpha")), "alpha processor", 201)
cross_stream = processor_payload("alpha", "alpha-cross-stream")
cross_stream["join_stream_id"] = "beta-right"
checked(client.post("/api/v1/streams/processors", json=cross_stream), "deny beta join stream", 403)
cross_output = processor_payload("alpha", "alpha-cross-output")
cross_output["target_asset_id"] = "beta-join-output"
checked(client.post("/api/v1/streams/processors", json=cross_output), "deny beta output", 409)

use("beta")
checked(client.post("/api/v1/streams/processors", json=processor_payload("beta")), "beta processor", 201)

use("alpha")
checked(client.get("/api/v1/streams/processors/beta-join"), "deny beta processor read", 403)
checked(client.post("/api/v1/streams/processors/beta-join/process", json={}), "deny beta processor execute", 403)
checked(client.post("/api/v1/streams/processors/beta-join/enqueue", json={}), "deny beta processor enqueue", 403)
alpha_rows = checked(client.get("/api/v1/streams/processors?project_id=alpha"), "list alpha processors")
assert [row["id"] for row in alpha_rows] == ["alpha-join"]
passed += 1
checked(client.get("/api/v1/streams/processors?project_id=beta"), "deny beta processor list", 403)

app.dependency_overrides.clear()
print(f"Cross-stream join tenancy verified: {passed} assertions passed.")
engine.dispose()
temporary.cleanup()

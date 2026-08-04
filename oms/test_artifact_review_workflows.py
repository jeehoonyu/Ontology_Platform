"""Durable target-anchored comments and governed artifact proposals."""

import os
import tempfile


tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tmpdir.name, 'artifact_reviews.db')}"
os.environ["AUTH_MODE"] = "local"
os.environ["APP_ENV"] = "test"

from fastapi.testclient import TestClient  # noqa: E402
from app.database import SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.models_action import AuditLog  # noqa: E402
from app.platform_runtime import (  # noqa: E402
    ArtifactChangeProposal, ArtifactCommandReceipt, ArtifactReviewComment,
)


client = TestClient(app, raise_server_exceptions=False)


def checked(response, expected=200):
    assert response.status_code == expected, f"{response.status_code}: {response.text[:2000]}"
    return response.json() if response.content else {}


artifact = checked(client.post("/artifacts", json={
    "id": "reviewed_pipeline", "project_id": "default", "artifact_type": "pipeline",
    "display_name": "Reviewed pipeline", "state": {"nodes": [
        {"id": "source", "position": {"x": 0, "y": 0}, "data": {"label": "Source", "nodeType": "dataset_input"}},
        {"id": "output", "position": {"x": 300, "y": 0}, "data": {"label": "Output", "nodeType": "dataset_output"}},
    ], "edges": []},
}), 201)

comment = checked(client.post("/api/v1/artifacts/reviewed_pipeline/comments", json={
    "target": "node:source", "body": "Confirm the source contract.",
}), 201)
reply = checked(client.post("/api/v1/artifacts/reviewed_pipeline/comments", json={
    "target": "node:source", "parent_id": comment["id"], "body": "Contract verified.",
}), 201)
assert reply["thread_id"] == comment["thread_id"] and reply["parent_id"] == comment["id"]
resolved = checked(client.patch(
    f"/api/v1/artifacts/reviewed_pipeline/comments/{comment['id']}", json={"status": "RESOLVED"},
))
assert resolved["resolved_by"] == resolved["author"], resolved
assert checked(client.get(
    "/api/v1/artifacts/reviewed_pipeline/comments?target=node%3Asource",
))["count"] == 2
assert client.post("/api/v1/artifacts/reviewed_pipeline/comments", json={
    "target": "node:missing", "body": "Invalid target",
}).status_code == 422

# A proposal can rebase over a non-overlapping direct edit.
proposal = checked(client.post("/api/v1/artifacts/reviewed_pipeline/proposals", json={
    "title": "Clarify source", "expected_lock_version": artifact["lock_version"],
    "commands": [{"command_id": "proposal-source", "command": "update_node", "payload": {
        "node_id": "source", "changes": {"data": {"label": "Governed source", "nodeType": "dataset_input"}},
    }}],
}), 201)
direct = checked(client.post("/artifacts/reviewed_pipeline/commands", json={
    "expected_lock_version": artifact["lock_version"], "idempotency_key": "direct-output-label-v1",
    "commands": [{"command_id": "direct-output", "command": "update_node", "payload": {
        "node_id": "output", "changes": {"data": {"label": "Curated output", "nodeType": "dataset_output"}},
    }}],
}))
approved = checked(client.post(
    f"/api/v1/artifacts/reviewed_pipeline/proposals/{proposal['id']}/review",
    json={"expected_version": proposal["version"], "decision": "APPROVE", "note": "Reviewed"},
))
applied = checked(client.post(
    f"/api/v1/artifacts/reviewed_pipeline/proposals/{proposal['id']}/apply",
    json={"expected_version": approved["version"]},
))
assert applied["status"] == "APPLIED" and applied["applied_revision"] == 3
assert applied["artifact"]["state"]["nodes"][0]["data"]["label"] == "Governed source"
assert applied["artifact"]["state"]["nodes"][1]["data"]["label"] == "Curated output"
assert applied["command_receipt"]["command_scope"] == "proposal"
replayed = checked(client.post(
    f"/api/v1/artifacts/reviewed_pipeline/proposals/{proposal['id']}/apply",
    json={"expected_version": approved["version"]},
))
assert replayed["idempotent_replay"] is True and replayed["applied_revision"] == 3

# Overlapping edits produce durable conflict evidence and can be rebased/re-reviewed.
conflicting = checked(client.post("/api/v1/artifacts/reviewed_pipeline/proposals", json={
    "title": "Change source again", "expected_lock_version": applied["artifact"]["lock_version"],
    "commands": [{"command_id": "conflicting-source", "command": "update_node", "payload": {
        "node_id": "source", "changes": {"data": {"label": "Proposed source", "nodeType": "dataset_input"}},
    }}],
}), 201)
newer = checked(client.post("/artifacts/reviewed_pipeline/commands", json={
    "expected_lock_version": applied["artifact"]["lock_version"],
    "idempotency_key": "direct-source-label-v2",
    "commands": [{"command_id": "newer-source", "command": "update_node", "payload": {
        "node_id": "source", "changes": {"data": {"label": "Newer source", "nodeType": "dataset_input"}},
    }}],
}))
conflict_approved = checked(client.post(
    f"/api/v1/artifacts/reviewed_pipeline/proposals/{conflicting['id']}/review",
    json={"expected_version": conflicting["version"], "decision": "APPROVE"},
))
conflict_response = client.post(
    f"/api/v1/artifacts/reviewed_pipeline/proposals/{conflicting['id']}/apply",
    json={"expected_version": conflict_approved["version"]},
)
assert conflict_response.status_code == 409 and "node:source" in conflict_response.json()["detail"]["concurrent_targets"]
conflict_state = checked(client.get(
    f"/api/v1/artifacts/reviewed_pipeline/proposals/{conflicting['id']}"
))
assert conflict_state["status"] == "CONFLICT"
rebased = checked(client.patch(
    f"/api/v1/artifacts/reviewed_pipeline/proposals/{conflicting['id']}", json={
        "expected_version": conflict_state["version"], "title": "Rebased source change",
    },
))
assert rebased["status"] == "OPEN" and rebased["base_lock_version"] == newer["lock_version"]
reapproved = checked(client.post(
    f"/api/v1/artifacts/reviewed_pipeline/proposals/{conflicting['id']}/review",
    json={"expected_version": rebased["version"], "decision": "APPROVE"},
))
reapplied = checked(client.post(
    f"/api/v1/artifacts/reviewed_pipeline/proposals/{conflicting['id']}/apply",
    json={"expected_version": reapproved["version"]},
))
assert reapplied["status"] == "APPLIED" and reapplied["artifact"]["state"]["nodes"][0]["data"]["label"] == "Proposed source"

# Production defaults forbid self-review unless explicitly enabled.
self_review = checked(client.post("/api/v1/artifacts/reviewed_pipeline/proposals", json={
    "title": "Independent review required", "expected_lock_version": reapplied["artifact"]["lock_version"],
    "commands": [{"command_id": "move-output", "command": "move_nodes", "payload": {
        "positions": {"output": {"x": 450, "y": 100}},
    }}],
}), 201)
os.environ["APP_ENV"] = "production"
assert client.post(
    f"/api/v1/artifacts/reviewed_pipeline/proposals/{self_review['id']}/review",
    json={"expected_version": self_review["version"], "decision": "APPROVE"},
).status_code == 409
os.environ["APP_ENV"] = "test"

room = checked(client.get("/artifacts/reviewed_pipeline/collaboration/events?after=0"))
event_types = {row["event_type"] for row in room["events"]}
assert {"comment.created", "comment.resolved", "proposal.created", "proposal.approved", "proposal.conflicted", "proposal.applied"} <= event_types
with SessionLocal() as db:
    assert db.query(ArtifactReviewComment).count() == 2
    assert db.query(ArtifactChangeProposal).count() == 3
    assert db.query(ArtifactCommandReceipt).filter(ArtifactCommandReceipt.command_scope == "proposal").count() == 2
    evidence = db.query(AuditLog).filter(AuditLog.subject_id == "reviewed_pipeline").all()
    assert any(row.event_type == "artifact.proposal.applied" for row in evidence)

snapshot = checked(client.get("/project/export?project_id=default"))
assert len(snapshot["platform_artifact_review_comments"]) == 2
assert len(snapshot["platform_artifact_change_proposals"]) == 3
assert checked(client.post("/project/import/validate", json={"snapshot": snapshot}))["status"] == "VALID"
with SessionLocal() as db:
    db.query(ArtifactReviewComment).delete()
    db.query(ArtifactChangeProposal).delete()
    db.commit()
assert checked(client.post("/project/import", json={"snapshot": snapshot}))["status"] == "IMPORTED"
with SessionLocal() as db:
    assert db.query(ArtifactReviewComment).count() == 2
    assert db.query(ArtifactChangeProposal).count() == 3

print("Artifact review comments and governed proposals verified.")
engine.dispose()
tmpdir.cleanup()

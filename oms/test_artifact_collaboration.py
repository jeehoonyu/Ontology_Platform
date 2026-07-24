"""Real-time artifact presence, optimistic rebasing, and conflict evidence."""
import os
import tempfile

tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tmpdir.name, 'artifact_collaboration.db')}"
os.environ["AUTH_MODE"] = "local"
os.environ["APP_ENV"] = "test"

from fastapi.testclient import TestClient  # noqa: E402
from app.database import SessionLocal  # noqa: E402
from app.main import app  # noqa: E402
from app.models_action import AuditLog  # noqa: E402
from app.platform_runtime import ArtifactCollaborationParticipant  # noqa: E402

client = TestClient(app)
passed = 0


def ok(response, label, expect=200):
    global passed
    assert response.status_code == expect, f"{label}: {response.status_code} {response.text[:1200]}"
    passed += 1
    return response.json() if response.content else {}


artifact = ok(client.post("/artifacts", json={
    "id": "collaborative_pipeline",
    "artifact_type": "pipeline",
    "display_name": "Collaborative pipeline",
    "state": {
        "nodes": [
            {"id": "node-a", "position": {"x": 100, "y": 100}, "data": {"label": "Node A", "nodeType": "filter"}},
            {"id": "node-b", "position": {"x": 360, "y": 100}, "data": {"label": "Node B", "nodeType": "select"}},
        ],
        "edges": [],
    },
}), "create collaborative artifact", 201)
assert artifact["lock_version"] == 1, artifact

joined_a = ok(client.post("/artifacts/collaborative_pipeline/collaboration/join", json={
    "client_id": "browser-client-a",
}), "join first collaborator")
joined_b = ok(client.post("/artifacts/collaborative_pipeline/collaboration/join", json={
    "client_id": "browser-client-b",
}), "join second collaborator")
token_a = joined_a["participant_token"]
token_b = joined_b["participant_token"]
assert token_a == joined_a["participant"]["token"]
assert joined_a["participant"]["id"] != joined_b["participant"]["id"]

room = ok(client.get("/artifacts/collaborative_pipeline/collaboration"), "inspect active room")
assert len(room["participants"]) == 2, room
assert all("token" not in participant for participant in room["participants"]), room

edit_a = ok(client.post("/artifacts/collaborative_pipeline/collaboration/commands", json={
    "participant_token": token_a,
    "expected_lock_version": 1,
    "idempotency_key": "client-a-edit-001",
    "commands": [{
        "command_id": "cmd-a",
        "command": "update_node",
        "payload": {"node_id": "node-a", "changes": {"data": {"label": "Node A by client A", "nodeType": "filter"}}},
    }],
}), "apply first edit")
assert edit_a["lock_version"] == 2 and edit_a["current_revision"] == 2, edit_a

edit_b = ok(client.post("/artifacts/collaborative_pipeline/collaboration/commands", json={
    "participant_token": token_b,
    "expected_lock_version": 1,
    "idempotency_key": "client-b-edit-001",
    "commands": [{
        "command_id": "cmd-b",
        "command": "move_nodes",
        "payload": {"positions": {"node-b": {"x": 420, "y": 220}}},
    }],
}), "rebase non-overlapping stale edit")
assert edit_b["lock_version"] == 3 and edit_b["collaboration_receipt"]["rebased_from_lock_version"] == 1, edit_b
assert edit_b["state"]["nodes"][0]["data"]["label"] == "Node A by client A", edit_b
assert edit_b["state"]["nodes"][1]["position"] == {"x": 420, "y": 220}, edit_b

replay_b = ok(client.post("/artifacts/collaborative_pipeline/collaboration/commands", json={
    "participant_token": token_b,
    "expected_lock_version": 1,
    "idempotency_key": "client-b-edit-001",
    "commands": [{
        "command_id": "cmd-b",
        "command": "move_nodes",
        "payload": {"positions": {"node-b": {"x": 420, "y": 220}}},
    }],
}), "replay collaborative command")
assert replay_b["idempotent_replay"] is True and replay_b["lock_version"] == 3, replay_b

conflict = client.post("/artifacts/collaborative_pipeline/collaboration/commands", json={
    "participant_token": token_b,
    "expected_lock_version": 1,
    "idempotency_key": "client-b-conflict-001",
    "commands": [{
        "command_id": "cmd-conflict",
        "command": "update_node",
        "payload": {"node_id": "node-a", "changes": {"data": {"label": "Conflicting label", "nodeType": "filter"}}},
    }],
})
assert conflict.status_code == 409, conflict.text
conflict_detail = conflict.json()["detail"]
assert "node:node-a" in conflict_detail["incoming_targets"], conflict_detail
assert "node:node-a" in conflict_detail["concurrent_targets"], conflict_detail
passed += 1

heartbeat = ok(client.post("/artifacts/collaborative_pipeline/collaboration/heartbeat", json={
    "participant_token": token_b,
    "cursor": {"x": 320, "y": 180},
    "selection": ["node-b"],
}), "update collaborator presence")
assert heartbeat["cursor"] == {"x": 320, "y": 180} and heartbeat["selection"] == ["node-b"], heartbeat

events = ok(client.get("/artifacts/collaborative_pipeline/collaboration/events?after=0"), "read collaboration events")
event_types = [event["event_type"] for event in events["events"]]
assert "presence.joined" in event_types and "artifact.commands" in event_types and "artifact.conflict" in event_types, event_types
sse = client.get("/artifacts/collaborative_pipeline/collaboration/stream?after=0&once=true")
assert sse.status_code == 200 and "event: artifact.commands" in sse.text and "event: artifact.conflict" in sse.text, sse.text
passed += 1

ok(client.post("/artifacts/collaborative_pipeline/collaboration/leave", json={
    "participant_token": token_a,
}), "leave collaboration room")
with SessionLocal() as db:
    participant_b = db.query(ArtifactCollaborationParticipant).filter(ArtifactCollaborationParticipant.token == token_b).one()
    participant_b.expires_at = 0
    db.commit()
expired_room = ok(client.get("/artifacts/collaborative_pipeline/collaboration"), "prune expired collaborator")
assert expired_room["participants"] == [], expired_room

with SessionLocal() as db:
    audits = db.query(AuditLog).filter(AuditLog.event_type == "artifact.collaboration.commands_applied").all()
    assert len(audits) == 2 and all((audit.payload or {}).get("participant_id") for audit in audits), audits
passed += 1

print(f"\nArtifact collaboration verified: {passed} assertions passed.")
from app.database import engine as _engine  # noqa: E402
_engine.dispose()
tmpdir.cleanup()

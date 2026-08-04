"""Real-time artifact presence, optimistic rebasing, and conflict evidence."""
import os
import tempfile
from concurrent.futures import ThreadPoolExecutor

tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tmpdir.name, 'artifact_collaboration.db')}"
os.environ["AUTH_MODE"] = "local"
os.environ["APP_ENV"] = "test"

from fastapi.testclient import TestClient  # noqa: E402
from app.database import SessionLocal  # noqa: E402
from app.main import app  # noqa: E402
from app.models_action import AuditLog  # noqa: E402
from app.platform_runtime import ArtifactCollaborationParticipant, ArtifactCommandReceipt, ArtifactRevision, PlatformArtifact  # noqa: E402

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

changed_reuse = client.post("/artifacts/collaborative_pipeline/collaboration/commands", json={
    "participant_token": token_b,
    "expected_lock_version": 1,
    "idempotency_key": "client-b-edit-001",
    "commands": [{
        "command_id": "cmd-b-different",
        "command": "remove_nodes",
        "payload": {"node_ids": ["node-b"]},
    }],
})
assert changed_reuse.status_code == 409 and "different command batch" in changed_reuse.json()["detail"]["message"], changed_reuse.text
passed += 1

# Receipts must remain replayable after exceeding the old 100-entry metadata window.
current_lock_version = edit_b["lock_version"]
for index in range(105):
    response = client.post("/artifacts/collaborative_pipeline/collaboration/commands", json={
        "participant_token": token_b,
        "expected_lock_version": current_lock_version,
        "idempotency_key": f"durable-collaboration-edit-{index:03d}",
        "commands": [{
            "command_id": f"durable-cmd-{index:03d}",
            "command": "update_node",
            "payload": {"node_id": "node-b", "changes": {"data": {"label": f"Node B revision {index}", "nodeType": "select"}}},
        }],
    })
    assert response.status_code == 200, response.text
    current_lock_version = response.json()["lock_version"]
old_replay = client.post("/artifacts/collaborative_pipeline/collaboration/commands", json={
    "participant_token": token_b,
    "expected_lock_version": 1,
    "idempotency_key": "client-b-edit-001",
    "commands": [{
        "command_id": "cmd-b",
        "command": "move_nodes",
        "payload": {"positions": {"node-b": {"x": 420, "y": 220}}},
    }],
})
assert old_replay.status_code == 200 and old_replay.json()["idempotent_replay"] is True
assert old_replay.json()["lock_version"] == current_lock_version
with SessionLocal() as db:
    receipts = db.query(ArtifactCommandReceipt).filter(
        ArtifactCommandReceipt.artifact_id == "collaborative_pipeline",
        ArtifactCommandReceipt.command_scope == "collaboration",
    ).all()
    stored = db.get(PlatformArtifact, "collaborative_pipeline")
    assert len(receipts) == 107 and all(receipt.request_hash for receipt in receipts), len(receipts)
    assert "collaboration_receipts" not in (stored.metadata_ or {}), stored.metadata_
passed += 2

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

# SQLite must serialize simultaneous revision allocation just as Postgres does
# with SELECT FOR UPDATE. Non-overlapping edits may rebase, but revision IDs
# must remain unique.
def concurrent_move(index):
    node_id = "node-a" if index == 0 else "node-b"
    return client.post("/artifacts/collaborative_pipeline/collaboration/commands", json={
        "participant_token": token_a if index == 0 else token_b,
        "expected_lock_version": current_lock_version,
        "idempotency_key": f"concurrent-edit-{index}",
        "commands": [{
            "command_id": f"concurrent-command-{index}",
            "command": "move_nodes",
            "payload": {"positions": {node_id: {"x": 500 + index * 100, "y": 300}}},
        }],
    })


with ThreadPoolExecutor(max_workers=2) as pool:
    concurrent_results = list(pool.map(concurrent_move, range(2)))
assert all(response.status_code == 200 for response in concurrent_results), [response.text for response in concurrent_results]
concurrent_payloads = [response.json() for response in concurrent_results]
assert sorted(item["current_revision"] for item in concurrent_payloads) == [current_lock_version + 1, current_lock_version + 2]
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
assert sse.status_code == 200 and "event: artifact.commands" in sse.text, sse.text
conflict_event_id = next(event["id"] for event in events["events"] if event["event_type"] == "artifact.conflict")
conflict_sse = client.get(
    f"/artifacts/collaborative_pipeline/collaboration/stream?after={conflict_event_id - 1}&once=true"
)
assert conflict_sse.status_code == 200 and "event: artifact.conflict" in conflict_sse.text, conflict_sse.text
passed += 1
latest_event_id = events["next_cursor"]
resumed = client.get(
    "/artifacts/collaborative_pipeline/collaboration/stream?after=0&once=true",
    headers={"Last-Event-ID": str(latest_event_id)},
)
assert resumed.status_code == 200 and resumed.text == "", resumed.text
invalid_resume = client.get(
    "/artifacts/collaborative_pipeline/collaboration/stream?once=true",
    headers={"Last-Event-ID": "not-an-event-id"},
)
assert invalid_resume.status_code == 400, invalid_resume.text
passed += 1

with client.websocket_connect(
    f"/artifacts/collaborative_pipeline/collaboration/ws?after={latest_event_id}"
) as websocket:
    ready = websocket.receive_json()
    assert ready["type"] == "connection.ready" and ready["cursor"] == latest_event_id, ready
    heartbeat_response = client.post("/artifacts/collaborative_pipeline/collaboration/heartbeat", json={
        "participant_token": token_b,
        "cursor": {"x": 360, "y": 220},
        "selection": ["node-b"],
    })
    assert heartbeat_response.status_code == 200, heartbeat_response.text
    websocket_event = websocket.receive_json()
    assert websocket_event["type"] == "event", websocket_event
    assert websocket_event["cursor"] > latest_event_id, websocket_event
    assert websocket_event["event"]["event_type"] == "presence.updated", websocket_event
    websocket.send_json({"type": "ping"})
    pong = websocket.receive_json()
    assert pong["type"] == "pong" and pong["cursor"] == websocket_event["cursor"], pong
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
    assert len(audits) == 109 and all((audit.payload or {}).get("participant_id") for audit in audits), len(audits)
passed += 1

# Repeated race on an isolated artifact. Committing expires the artifact row, so
# a response built from a post-commit re-read reports whichever writer committed
# last: both concurrent writers can then be told they produced the same revision
# and the same state. Each writer must describe the revision it allocated, which
# its own receipt records. A single round observes the interleaving only
# occasionally, and this artifact is separate so repeated edits do not perturb
# the event-cursor and receipt expectations above.
race_artifact = ok(client.post("/artifacts", json={
    "id": "collaborative_race",
    "artifact_type": "pipeline",
    "display_name": "Collaborative race",
    "state": {
        "nodes": [
            {"id": "node-a", "position": {"x": 100, "y": 100}, "data": {"label": "Node A", "nodeType": "filter"}},
            {"id": "node-b", "position": {"x": 360, "y": 100}, "data": {"label": "Node B", "nodeType": "select"}},
        ],
        "edges": [],
    },
}), "create race artifact", 201)
race_token_a = ok(client.post("/artifacts/collaborative_race/collaboration/join", json={
    "client_id": "race-client-a",
}), "join first race collaborator")["participant_token"]
race_token_b = ok(client.post("/artifacts/collaborative_race/collaboration/join", json={
    "client_id": "race-client-b",
}), "join second race collaborator")["participant_token"]
race_lock_version = race_artifact["lock_version"]


def race_move(index, base, round_id):
    node_id = "node-a" if index == 0 else "node-b"
    return client.post("/artifacts/collaborative_race/collaboration/commands", json={
        "participant_token": race_token_a if index == 0 else race_token_b,
        "expected_lock_version": base,
        "idempotency_key": f"race-edit-{round_id}-{index}",
        "commands": [{
            "command_id": f"race-command-{round_id}-{index}",
            "command": "move_nodes",
            "payload": {"positions": {node_id: {"x": 500 + index * 100, "y": 300 + round_id}}},
        }],
    })


for race_round in range(120):
    with ThreadPoolExecutor(max_workers=2) as pool:
        race_results = list(pool.map(
            lambda index: race_move(index, race_lock_version, race_round), range(2),
        ))
    assert all(response.status_code == 200 for response in race_results), [response.text for response in race_results]
    race_payloads = [response.json() for response in race_results]
    assert sorted(item["current_revision"] for item in race_payloads) == [
        race_lock_version + 1, race_lock_version + 2,
    ], (race_round, race_lock_version, race_payloads)
    for item in race_payloads:
        assert item["current_revision"] == item["collaboration_receipt"]["revision"], (race_round, item)
        assert item["lock_version"] == item["collaboration_receipt"]["lock_version"], (race_round, item)
    race_lock_version = max(item["lock_version"] for item in race_payloads)
with SessionLocal() as db:
    race_revisions = [
        row.revision for row in db.query(ArtifactRevision).filter(
            ArtifactRevision.artifact_id == "collaborative_race",
        ).all()
    ]
assert len(race_revisions) == len(set(race_revisions)) == 241, sorted(race_revisions)
passed += 1

print(f"\nArtifact collaboration verified: {passed} assertions passed.")
from app.database import engine as _engine  # noqa: E402
_engine.dispose()
tmpdir.cleanup()

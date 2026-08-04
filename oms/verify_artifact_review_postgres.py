"""Rehearse proposal serialization, rebasing, and conflicts on PostgreSQL."""

import os
import uuid
from concurrent.futures import ThreadPoolExecutor


if not os.environ.get("DATABASE_URL", "").startswith("postgresql"):
    raise SystemExit("verify_artifact_review_postgres.py requires a PostgreSQL DATABASE_URL")
os.environ["SKIP_CREATE_ALL"] = "1"
os.environ.setdefault("AUTH_MODE", "local")
os.environ.setdefault("APP_ENV", "test")

from fastapi.testclient import TestClient  # noqa: E402
from app.database import SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.platform_runtime import ArtifactChangeProposal, ArtifactCommandReceipt  # noqa: E402


artifact_id = f"pg_review_{uuid.uuid4().hex[:10]}"


def checked(response, expected=200):
    assert response.status_code == expected, f"{response.status_code}: {response.text[:2000]}"
    return response.json() if response.content else {}


with TestClient(app) as client:
    artifact = checked(client.post("/artifacts", json={
        "id": artifact_id,
        "project_id": "default",
        "artifact_type": "pipeline",
        "display_name": "PostgreSQL reviewed pipeline",
        "state": {
            "nodes": [
                {"id": "left", "position": {"x": 0, "y": 0}, "data": {"label": "Left"}},
                {"id": "right", "position": {"x": 300, "y": 0}, "data": {"label": "Right"}},
            ],
            "edges": [],
        },
    }), 201)

    proposals = []
    for node_id in ("left", "right"):
        proposal = checked(client.post(f"/api/v1/artifacts/{artifact_id}/proposals", json={
            "title": f"Update {node_id}",
            "expected_lock_version": artifact["lock_version"],
            "commands": [{
                "command_id": f"update-{node_id}",
                "command": "update_node",
                "payload": {"node_id": node_id, "changes": {"data": {"label": node_id.title() + " v2"}}},
            }],
        }), 201)
        proposals.append(checked(client.post(
            f"/api/v1/artifacts/{artifact_id}/proposals/{proposal['id']}/review",
            json={"expected_version": proposal["version"], "decision": "APPROVE"},
        )))


def apply_proposal(proposal):
    with TestClient(app) as thread_client:
        response = thread_client.post(
            f"/api/v1/artifacts/{artifact_id}/proposals/{proposal['id']}/apply",
            json={"expected_version": proposal["version"]},
        )
        return response.status_code, response.json()


with ThreadPoolExecutor(max_workers=2) as pool:
    nonoverlap_results = list(pool.map(apply_proposal, proposals))
assert [status for status, _ in nonoverlap_results] == [200, 200], nonoverlap_results
assert sorted(result["applied_revision"] for _, result in nonoverlap_results) == [2, 3]

with TestClient(app) as client:
    current = checked(client.get(f"/artifacts/{artifact_id}"))
    overlapping = []
    for suffix in ("a", "b"):
        proposal = checked(client.post(f"/api/v1/artifacts/{artifact_id}/proposals", json={
            "title": f"Competing left change {suffix}",
            "expected_lock_version": current["lock_version"],
            "commands": [{
                "command_id": f"competing-left-{suffix}",
                "command": "update_node",
                "payload": {"node_id": "left", "changes": {"data": {"label": f"Left {suffix}"}}},
            }],
        }), 201)
        overlapping.append(checked(client.post(
            f"/api/v1/artifacts/{artifact_id}/proposals/{proposal['id']}/review",
            json={"expected_version": proposal["version"], "decision": "APPROVE"},
        )))

with ThreadPoolExecutor(max_workers=2) as pool:
    overlap_results = list(pool.map(apply_proposal, overlapping))
assert sorted(status for status, _ in overlap_results) == [200, 409], overlap_results
conflict = next(body for status, body in overlap_results if status == 409)
assert "node:left" in conflict["detail"]["concurrent_targets"], conflict

with SessionLocal() as db:
    statuses = [row.status for row in db.query(ArtifactChangeProposal).filter(
        ArtifactChangeProposal.artifact_id == artifact_id
    ).all()]
    assert statuses.count("APPLIED") == 3 and statuses.count("CONFLICT") == 1, statuses
    receipts = db.query(ArtifactCommandReceipt).filter(
        ArtifactCommandReceipt.artifact_id == artifact_id,
        ArtifactCommandReceipt.command_scope == "proposal",
    ).all()
    assert len(receipts) == 3
    assert len({row.revision for row in receipts}) == 3

print("PostgreSQL artifact proposal serialization and conflict rehearsal passed.")
engine.dispose()

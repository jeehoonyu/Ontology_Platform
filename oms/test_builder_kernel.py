"""Shared visual-builder catalog, command, preview, and impact contracts."""
import os
import tempfile

tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tmpdir.name, 'builder_kernel.db')}"
os.environ["AUTH_MODE"] = "local"
os.environ["APP_ENV"] = "test"

from fastapi.testclient import TestClient  # noqa: E402
from app.main import app  # noqa: E402

client = TestClient(app)
passed = 0


def ok(response, label, expect=200):
    global passed
    assert response.status_code == expect, f"{label}: {response.status_code} {response.text[:1000]}"
    passed += 1
    return response.json() if response.content else {}


catalog = ok(client.get("/builder/catalogs/pipeline"), "pipeline catalog")
assert len(catalog["nodes"]) >= 30 and "replace_state" in catalog["commands"], catalog
assert all("inputs" in node and "outputs" in node and "configuration_schema" in node for node in catalog["nodes"])
workshop_catalog = ok(client.get("/builder/catalogs/workshop"), "workshop catalog")
assert workshop_catalog["nodes"][0]["configuration_schema"]["properties"], workshop_catalog
aip_catalog = ok(client.get("/builder/catalogs/aip_logic"), "AIP Logic catalog")
approval_schema = next(node for node in aip_catalog["nodes"] if node["type"] == "approval")["configuration_schema"]
assert approval_schema["properties"]["proposal_variable"]["required"] is True, approval_schema

artifact = ok(client.post("/artifacts", json={
    "id": "kernel_pipeline",
    "artifact_type": "pipeline",
    "display_name": "Kernel pipeline",
    "state": {"nodes": [], "edges": []},
    "layout": {},
}), "create builder artifact", 201)
assert artifact["dirty_revision"] == 1 and artifact["validation_targets"], artifact
assert {"edit", "execute", "publish", "restore"}.issubset(set(artifact["permissions"])), artifact

lease = ok(client.post("/artifacts/kernel_pipeline/leases", json={"ttl_seconds": 180}), "lease artifact")
batch = {
    "expected_lock_version": artifact["lock_version"],
    "lease_token": lease["token"],
    "idempotency_key": "kernel-add-input-output-v1",
    "message": "Create executable pipeline",
    "commands": [
        {"command_id": "add-input", "command": "add_node", "payload": {"node": {
            "id": "input", "position": {"x": 50, "y": 80},
            "data": {"label": "Assets", "nodeType": "dataset_input", "fields": []},
        }}},
        {"command_id": "add-output", "command": "add_node", "payload": {"node": {
            "id": "output", "position": {"x": 500, "y": 80},
            "data": {"label": "Curated assets", "nodeType": "dataset_output", "fields": []},
        }}},
        {"command_id": "connect", "command": "add_edge", "payload": {
            "edge": {"id": "input-output", "source": "input", "target": "output"},
        }},
    ],
}
updated = ok(client.post("/artifacts/kernel_pipeline/commands", json=batch), "atomic builder commands")
assert updated["current_revision"] == 2 and updated["validation"]["status"] == "PASS", updated
assert len(updated["state"]["nodes"]) == 2 and len(updated["state"]["edges"]) == 1, updated
assert updated["command_receipt"]["command_ids"] == ["add-input", "add-output", "connect"], updated

replayed = ok(client.post("/artifacts/kernel_pipeline/commands", json=batch), "idempotent command replay")
assert replayed["idempotent_replay"] is True and replayed["current_revision"] == 2, replayed

stale = dict(batch)
stale["idempotency_key"] = "kernel-stale-command-v1"
assert client.post("/artifacts/kernel_pipeline/commands", json=stale).status_code == 409
passed += 1

moved = ok(client.post("/artifacts/kernel_pipeline/commands", json={
    "expected_lock_version": updated["lock_version"],
    "lease_token": lease["token"],
    "idempotency_key": "kernel-move-duplicate-v1",
    "commands": [
        {"command": "move_nodes", "payload": {"positions": {"output": {"x": 620, "y": 160}}}},
        {"command": "duplicate_nodes", "payload": {"node_ids": ["input"], "id_map": {"input": "input_copy"}}},
        {"command": "auto_layout", "payload": {"columns": 2}},
    ],
}), "move duplicate and layout")
assert len(moved["state"]["nodes"]) == 3 and moved["layout"]["input_copy"], moved

preview = ok(client.post("/artifacts/kernel_pipeline/preview", json={"sample_limit": 10}), "preview artifact", 202)
assert preview["status"] == "SUCCEEDED" and preview["metrics"]["node_count"] == 3, preview
job = ok(client.get(f"/jobs/{preview['job_id']}"), "preview job evidence")
assert [event["event_type"] for event in job["events"]] == ["job.queued", "job.started", "job.succeeded"], job

aip_artifact = ok(client.post("/artifacts", json={
    "id": "kernel_aip", "artifact_type": "aip_logic", "display_name": "Governed AIP plan",
    "state": {"nodes": [{
        "id": "approval", "position": {"x": 100, "y": 100},
        "data": {"label": "Approve", "nodeType": "approval", "configurationSchemaVersion": 1, "fields": [
            {"id": "proposal", "name": "proposal_variable", "value": "proposed_action"},
        ]},
    }], "edges": []},
}), "create typed AIP artifact", 201)
assert aip_artifact["validation"]["status"] == "PASS", aip_artifact
aip_preview = ok(client.post("/artifacts/kernel_aip/preview", json={"sample_limit": 10}), "preview governed AIP trace", 202)
assert aip_preview["trace"][0]["policy_decision"] == "APPROVAL_REQUIRED" and aip_preview["trace"][0]["approval_gate"], aip_preview

ok(client.post("/object-types", json={
    "id": "impact_asset", "display_name": "Impact Asset", "description": "Impact test",
    "properties": {"asset_id": {"type": "string"}, "risk": {"type": "number"}},
}), "create impact object type")
ok(client.post("/objects", json={
    "id": "impact_asset_1", "object_type_id": "impact_asset",
    "properties": {"asset_id": "A-1", "risk": 0.91},
}), "create populated object")
impact = ok(client.post("/ontology/changes/impact", json={
    "object_type_id": "impact_asset",
    "changes": [{"operation": "delete", "property_name": "risk"}],
}), "ontology impact analysis")
assert impact["severity"] == "HIGH" and impact["safe_to_publish"] is False, impact
assert impact["summary"]["objects"] == 1 and impact["summary"]["populated_values"] == 1, impact

print(f"\nBuilder kernel verified: {passed} assertions passed.")
from app.database import engine as _engine  # noqa: E402
_engine.dispose()
tmpdir.cleanup()

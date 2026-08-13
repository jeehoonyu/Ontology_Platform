"""
Human-facing evaluator UI readiness contracts.

Run: python test_human_ui_readiness.py
"""
import os
import tempfile

tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tmpdir.name, 'human_ui.db')}"

from fastapi.testclient import TestClient  # noqa: E402
from app.main import app  # noqa: E402

client = TestClient(app)
passed = 0


def ok(resp, label, expect=200):
    global passed
    success = resp.status_code == expect or (expect == 200 and 200 <= resp.status_code < 300)
    assert success, f"{label}: expected {expect}, got {resp.status_code} -> {resp.text[:900]}"
    passed += 1
    return resp.json() if resp.content else {}


def assert_ui_state(payload, label):
    global passed
    for key in ("summary", "primary_actions", "sections", "evidence_links", "warnings", "last_updated"):
        assert key in payload, f"{label}: missing {key}"
    assert isinstance(payload["sections"], list), payload
    assert isinstance(payload["primary_actions"], list), payload
    passed += 1


bootstrap = ok(client.post("/project/demo/bootstrap", json={"actor": "test", "run_pipelines": True, "run_checks": True}), "bootstrap human demo")
assert bootstrap["status"] == "READY", bootstrap
assert bootstrap["workflow_state"]["steps"], bootstrap["workflow_state"]

reset = ok(client.post("/project/demo/reset", json={"actor": "test", "run_pipelines": True, "run_checks": True}), "reset human demo")
assert reset["mode"] == "idempotent_reset", reset

command = ok(client.get("/ui-state/command-center"), "command center ui state")
assert_ui_state(command, "command center")
assert command["evaluator_summary"]["decision"], command["evaluator_summary"]
assert any(section["id"] == "risk" for section in command["sections"]), command["sections"]
assert any(action["id"] == "triage" for action in command["primary_actions"]), command["primary_actions"]

ok(client.post("/imports/csv", json={
    "id": "human_assets_import",
    "filename": "human-assets.csv",
    "display_name": "Human Assets",
    "target_dataset_id": "human_assets_dataset",
    "content": "asset_id,name,status,criticality\nasset_human_1,Human Pump,RUNNING,high\n",
}), "create human import", expect=201)

imports = ok(client.get("/ui-state/imports"), "imports ui state")
assert_ui_state(imports, "imports")
assert imports["summary"]["job_count"] >= 1, imports["summary"]
assert any(template["id"] == "asset" for template in imports["templates"]), imports["templates"]

validation = ok(client.get("/ui-state/validation"), "validation ui state")
assert_ui_state(validation, "validation")
assert validation["summary"]["docs_row_count"] >= 1, validation["summary"]
assert any(section["id"] == "docs" for section in validation["sections"]), validation["sections"]

readiness = ok(client.get("/project/readiness"), "project readiness")
assert readiness["status"] in {"READY", "NEEDS_ATTENTION"}, readiness
assert readiness["checks"], readiness

for route in ["/workspace/command-center", "/workspace/imports", "/workspace/ontology", "/workspace/pipeline", "/workspace/object-explorer", "/workspace/map", "/workspace/models", "/workspace/decision", "/workspace/ops", "/workspace/graph", "/workspace/validation"]:
    html = client.get(route).text
    assert "id=\"root\"" in html or "/react/assets/" in html, html[:300]
    passed += 1

print(f"\nHuman UI readiness verified: {passed} assertions passed.")
from app.database import engine as _engine  # noqa: E402
_engine.dispose()
tmpdir.cleanup()

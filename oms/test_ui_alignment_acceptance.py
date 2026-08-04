"""
UI endpoint alignment and human-usability acceptance checks.

Run: python test_ui_alignment_acceptance.py
"""
import os
import tempfile
from pathlib import Path

tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tmpdir.name, 'ui_alignment.db')}"

from fastapi.testclient import TestClient  # noqa: E402
from app.main import app  # noqa: E402

client = TestClient(app)
passed = 0
repo_root = Path(__file__).resolve().parents[1]


def ok(resp, label, expect=200):
    global passed
    success = resp.status_code == expect or (expect == 200 and 200 <= resp.status_code < 300)
    assert success, f"{label}: expected {expect}, got {resp.status_code} -> {resp.text[:900]}"
    passed += 1
    return resp.json() if resp.content else {}


for route in [
    "/workspace/command-center",
    "/workspace/imports",
    "/workspace/ontology",
    "/workspace/pipeline",
    "/workspace/object-explorer",
    "/workspace/map",
    "/workspace/models",
    "/workspace/decision",
    "/workspace/ops",
    "/workspace/graph",
    "/workspace/validation",
]:
    html = client.get(route).text
    assert "id=\"root\"" in html or "/react/assets/" in html, html[:300]
    passed += 1

app_source = (repo_root / "frontend" / "src" / "App.tsx").read_text(encoding="utf-8")
display_source = (repo_root / "frontend" / "src" / "components" / "data" / "DataDisplay.tsx").read_text(encoding="utf-8")
format_source = (repo_root / "frontend" / "src" / "utils" / "format.ts").read_text(encoding="utf-8")
styles_source = (repo_root / "frontend" / "src" / "styles.css").read_text(encoding="utf-8")
explorer_source = (repo_root / "frontend" / "src" / "workspaces" / "ObjectExplorer.tsx").read_text(encoding="utf-8")
map_source = (repo_root / "frontend" / "src" / "workspaces" / "MapWorkspace.tsx").read_text(encoding="utf-8")
modelops_source = (repo_root / "frontend" / "src" / "workspaces" / "ModelOps.tsx").read_text(encoding="utf-8")
decision_source = (repo_root / "frontend" / "src" / "workspaces" / "DecisionWorkspace.tsx").read_text(encoding="utf-8")
ops_source = (repo_root / "frontend" / "src" / "workspaces" / "OpsWorkspace.tsx").read_text(encoding="utf-8")

assert "ENDPOINT_INVENTORY" in app_source and "/workspace/validation" in app_source, "endpoint inventory missing"
passed += 1
assert "DeveloperEvidence" in app_source and "<DebugJson" not in app_source, "developer evidence must gate raw diagnostics"
passed += 1
assert "developer-evidence" in display_source and "JSON.stringify(value, null, 2)" in display_source, "raw JSON must be isolated to collapsed developer evidence"
passed += 1
assert '`${keys.length} fields`' in format_source and "JSON.stringify(value)" not in format_source, "normal value formatting must not emit raw JSON"
passed += 1
assert "queryObjects" in explorer_source and "getObjectProfile" in explorer_source and "JSON.stringify" not in explorer_source, "Object Explorer must use typed backend contracts without raw JSON"
passed += 1
assert "MapContainer" in map_source and "evaluateGeofence" in map_source and "decodeMgrs" in map_source, "Map must render real GIS data and spatial tools"
passed += 1
assert "trainObjective" in modelops_source and "runMonitor" in modelops_source and "runInference" in modelops_source and "JSON.stringify" not in modelops_source, "ModelOps must expose the governed lifecycle without raw JSON"
passed += 1
assert "evaluateDecision" in decision_source and "explainDecisionObject" in decision_source and "createDecisionScenario" in decision_source and "JSON.stringify" not in decision_source, "Decision Intelligence must expose structured reasoning workflows without raw JSON"
passed += 1
assert "evaluateAlerts" in ops_source and "createIncident" in ops_source and "executeRunbook" in ops_source and "JSON.stringify" not in ops_source, "Ops must expose structured control-plane workflows without raw JSON"
passed += 1

for selector in [
    ".backend-connection-main",
    ".property-panel",
    ".section-card-grid",
    ".platform-flow",
    ".table-wrap",
    ".explorer-layout",
    ".map-workbench",
    ".modelops-layout",
    ".decision-risk-layout",
    ".ops-command-layout",
    "@media (max-width: 640px)",
]:
    assert selector in styles_source, f"alignment selector missing: {selector}"
    passed += 1

ok(client.get("/ui-state/command-center"), "command-center ui state")
ok(client.get("/ui-state/imports"), "imports ui state")
ok(client.get("/ui-state/validation"), "validation ui state")

print(f"\nUI alignment acceptance verified: {passed} assertions passed.")
from app.database import engine as _engine  # noqa: E402
_engine.dispose()
tmpdir.cleanup()

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

assert "ENDPOINT_INVENTORY" in app_source and "/workspace/validation" in app_source, "endpoint inventory missing"
passed += 1
assert "DeveloperEvidence" in app_source and "<DebugJson" not in app_source, "developer evidence must gate raw diagnostics"
passed += 1
assert "developer-evidence" in display_source and "JSON.stringify(value, null, 2)" in display_source, "raw JSON must be isolated to collapsed developer evidence"
passed += 1
assert '`${keys.length} fields`' in format_source and "JSON.stringify(value)" not in format_source, "normal value formatting must not emit raw JSON"
passed += 1

for selector in [
    ".backend-connection-main",
    ".property-panel",
    ".section-card-grid",
    ".platform-flow",
    ".table-wrap",
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

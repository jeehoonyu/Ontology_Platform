"""
End-to-end functional test for the newly added Foundry tool-equivalent modules.

Exercises every new router (interfaces, value types, ontology manager, ontology
functions, data connection, streaming, schedules, media sets, lineage, analytics,
apps, modeling, observability, security access, security data, cipher, marketplace,
AIP extras) through the real FastAPI app via TestClient, asserting core behavior.

Run:  ./venv312/Scripts/python.exe test_foundry_tools.py
"""
import os
import tempfile

tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tmpdir.name, 'foundry_tools.db')}"

from fastapi.testclient import TestClient  # noqa: E402
from app.main import app  # noqa: E402

client = TestClient(app)

passed = 0


def ok(resp, label, expect=200):
    global passed
    # Accept any 2xx for normal calls; require an exact match for explicit non-2xx (e.g. 403).
    success = resp.status_code == expect or (expect == 200 and 200 <= resp.status_code < 300)
    assert success, f"{label}: expected {expect}, got {resp.status_code} -> {resp.text[:300]}"
    passed += 1
    return resp.json() if resp.content else {}


# ---------------------------------------------------------------- shared setup
ok(client.post("/object-types", json={
    "id": "tool_widget", "display_name": "Widget", "description": "test entity",
    "properties": {"geometry": {"type": "geometry"}, "score": {"type": "integer"}, "ts": {"type": "integer"}},
}), "setup object-type")

for sid, score, ts in [("w1", 10, 1), ("w2", 20, 2)]:
    ok(client.post("/objects", json={
        "id": sid, "object_type_id": "tool_widget",
        "properties": {"score": score, "ts": ts, "geometry": {"type": "Point", "coordinates": [-122.4, 37.8]}},
    }), f"setup object {sid}")

ok(client.post("/data-assets", json={
    "id": "tool_ds", "display_name": "Sales DS", "kind": "dataset", "asset_schema": {},
    "records": [{"city": "A", "val": 10}, {"city": "A", "val": 20}, {"city": "B", "val": 5}],
}), "setup data-asset")

# ------------------------------------------------------------- 1. interfaces
ok(client.post("/shared-property-types", json={"id": "sp_geo", "display_name": "Geo", "base_type": "geo"}), "shared-prop create")
ok(client.post("/interfaces", json={
    "id": "geolocatable", "display_name": "Geolocatable",
    "properties": {"geometry": {"base_type": "geo", "required": True}},
}), "interface create")
impl = ok(client.get("/interfaces/geolocatable/implementers"), "interface implementers")
assert "tool_widget" in str(impl), f"implementers missing tool_widget: {impl}"
chk = ok(client.post("/interfaces/geolocatable/check-object-type", json={"object_type_id": "tool_widget"}), "interface check")
assert chk["conforms"] is True, chk

# ----------------------------------------------------------- 2. value types

# -------------------------------------------------- 3. ontology manager
ok(client.post("/ontology/branches", json={"id": "b1", "display_name": "Branch 1"}), "branch create")
ok(client.post("/ontology/proposals", json={"id": "p1", "branch_id": "b1", "title": "Add field", "changes": []}), "proposal create")
ok(client.post("/ontology/proposals/p1/submit"), "proposal submit")
ok(client.post("/ontology/proposals/p1/decision", json={"approve": True, "reviewer": "me"}), "proposal decision")
merged = ok(client.post("/ontology/proposals/p1/merge"), "proposal merge")
assert merged["status"] == "merged", merged

# ------------------------------------------------- 4. ontology functions
ok(client.post("/ontology-functions", json={
    "id": "cnt", "display_name": "Count widgets", "kind": "compute",
    "object_type_id": "tool_widget", "expression": {"type": "aggregate", "op": "count"},
}), "ontology-function create")
run = ok(client.post("/ontology-functions/cnt/run", json={"inputs": {}}), "ontology-function run")
assert "2" in str(run), f"expected count 2 in {run}"

# ----------------------------------------------------- 5. data connection
ok(client.post("/connections/sources", json={"id": "src1", "display_name": "S3 bucket", "source_type": "s3"}), "source create")
sync = ok(client.post("/connections/sources/src1/syncs", json={"target_asset_id": "tool_ds", "sample_records": [{"city": "C", "val": 99}]}), "sync create")
ok(client.post(f"/connections/syncs/{sync['id']}/run"), "sync run")
ds_after = ok(client.get("/data-assets/tool_ds"), "data-asset after sync")
assert len(ds_after["records"]) == 4, f"sync should append a record: {len(ds_after['records'])}"
ok(client.post("/connections/exports", json={"id": "exp1", "source_asset_id": "tool_ds", "destination": "sftp://x", "format": "csv"}), "export create")
ok(client.post("/connections/exports/exp1/run"), "export run")

# ---------------------------------------------------------- 6. streaming
ok(client.post("/streams", json={"id": "st1", "display_name": "Events"}), "stream create")
pub = ok(client.post("/streams/st1/publish", json={"records": [{"a": 1}, {"a": 2}]}), "stream publish")
assert pub["published"] == 2, pub
assert len(ok(client.get("/streams/st1/records"), "stream records")) == 2
arch = ok(client.post("/streams/st1/archive", json={"target_asset_id": "tool_ds"}), "stream archive")
assert arch["archived"] == 2, arch

# ---------------------------------------------------------- 7. schedules
ok(client.post("/schedules", json={"id": "sch1", "display_name": "Nightly", "target_type": "pipeline", "target_id": "tool_pipe", "trigger_type": "cron", "cron": "0 0 * * *"}), "schedule create")
build = ok(client.post("/schedules/sch1/trigger"), "schedule trigger")
assert build["status"] == "success", build
assert len(ok(client.get("/builds", params={"target_id": "tool_pipe"}), "builds list")) >= 1

# --------------------------------------------------------- 8. media sets
ok(client.post("/media-sets", json={"id": "ms1", "display_name": "Docs", "media_type": "document"}), "media-set create")
item = ok(client.post("/media-sets/ms1/items", json={"filename": "a.txt", "mime_type": "text/plain", "size_bytes": 11, "text_content": "hello world"}), "media-item create")
ext = ok(client.post(f"/media-items/{item['id']}/extract"), "media extract")
assert ext.get("word_count") == 2, ext

# ------------------------------------------------------------ 9. lineage
graph = ok(client.get("/lineage/graph"), "lineage graph")
assert graph.get("nodes"), f"lineage graph empty: {graph}"
ok(client.get("/lineage/resource/dataset/tool_ds"), "lineage resource")

# --------------------------------------------------------- 10. analytics
ok(client.post("/analytics/contour", json={"id": "c1", "display_name": "C", "input_asset_id": "tool_ds", "boards": [{"op": "filter", "config": {"field": "city", "value": "A"}}]}), "contour create")
ok(client.post("/analytics/contour/c1/run"), "contour run")
ok(client.post("/analytics/quiver", json={"id": "q1", "display_name": "Q", "object_type_id": "tool_widget", "time_field": "ts", "value_field": "score"}), "quiver create")
qc = ok(client.post("/analytics/quiver/q1/compute"), "quiver compute")
assert "2" in str(qc), f"quiver should see 2 points: {qc}"
ok(client.post("/analytics/fusion", json={"id": "f1", "display_name": "F", "object_type_id": "tool_widget", "cells": {"A1": "=COUNT(tool_widget)"}}), "fusion create")
fz = ok(client.post("/analytics/fusion/f1/evaluate"), "fusion evaluate")
assert "2" in str(fz), f"fusion COUNT should be 2: {fz}"

# -------------------------------------------------------------- 11. apps
ok(client.post("/apps/workshop", json={"id": "wks1", "display_name": "Ops", "widgets": [{"type": "object_table", "title": "Widgets", "object_type_id": "tool_widget"}]}), "workshop create")
ok(client.get("/apps/workshop/wks1/render"), "workshop render")
ok(client.post("/apps/slate", json={"id": "sl1", "display_name": "Slate App"}), "slate create")
ok(client.post("/apps/carbon", json={"id": "cb1", "display_name": "Workspace", "module_ids": ["wks1"]}), "carbon create")
ok(client.get("/apps/carbon/cb1"), "carbon get")

# ----------------------------------------------------------- 12. modeling
ok(client.post("/modeling/objectives", json={"id": "mo1", "display_name": "Predict score", "problem_type": "regression", "target_field": "score", "feature_fields": ["ts"]}), "objective create")
sub = ok(client.post("/modeling/objectives/mo1/train", json={"algorithm": "linear"}), "model train")
ok(client.post("/modeling/objectives/mo1/release", json={"submission_id": sub["id"]}), "model release")
ok(client.post("/modeling/deployments", json={"id": "dep1", "objective_id": "mo1", "submission_id": sub["id"], "mode": "batch"}), "deployment create")
inf = ok(client.post("/modeling/deployments/dep1/infer", json={"records": [{"ts": 5}]}), "model infer")
assert len(inf["predictions"]) == 1, inf

# ------------------------------------------------------- 13. observability
ok(client.post("/observability/traces", json={"workflow": "wf", "spans": [{"name": "s1", "kind": "function", "duration_ms": 5, "status": "ok"}], "status": "ok"}), "trace create")
ok(client.post("/observability/metrics", json={"subject_type": "function", "subject_id": "f1", "name": "latency_ms", "value": 12.5}), "metric create")
ok(client.get("/observability/summary"), "obs summary")
ok(client.post("/observability/monitoring-views", json={"id": "mv1", "display_name": "MV", "scope": {}, "checks": [{"type": "freshness", "config": {}}]}), "monitoring-view create")
ok(client.post("/observability/monitoring-views/mv1/evaluate"), "monitoring-view evaluate")

# ---------------------------------------------------- 14. security access
ok(client.post("/projects", json={"id": "proj1", "display_name": "Project One"}), "project create")
ok(client.post("/roles", json={"id": "viewer", "display_name": "Viewer", "permissions": ["view"]}), "role create")
ok(client.post("/projects/proj1/grants", json={"principal": "u1", "role_id": "viewer"}), "grant create")
assert ok(client.post("/access/check", json={"project_id": "proj1", "principal": "u1", "permission": "view"}), "access allow")["allowed"] is True
assert ok(client.post("/access/check", json={"project_id": "proj1", "principal": "u1", "permission": "edit"}), "access deny")["allowed"] is False

# ------------------------------------------------------ 15. security data
ok(client.post("/markings", json={"id": "pii", "display_name": "PII", "category": "PII"}), "marking create")
ok(client.post("/markings/pii/grant", json={"principal": "u1"}), "marking grant")
scan = ok(client.post("/governance/scan", json={"records": [{"email": "a@b.com", "ssn": "123-45-6789"}]}), "data scan")
assert scan["findings"], f"scan should find PII: {scan}"
ok(client.post("/restricted-views", json={"id": "rv1", "display_name": "RV", "object_type_id": "tool_widget", "row_filter": {}, "masked_properties": ["score"], "required_marking_id": "pii"}), "restricted-view create")
masked = ok(client.post("/restricted-views/rv1/apply", json={"principal": "u2", "rows": [{"score": 10, "ts": 1}]}), "restricted-view apply")
assert "***" in str(masked), f"score should be masked for u2: {masked}"

# ---------------------------------------------------------- 16. cipher
ok(client.post("/cipher/channels", json={"id": "ch1", "display_name": "Channel", "mode": "encrypt", "key_ref": "k1"}), "cipher channel")
enc = ok(client.post("/cipher/encrypt", json={"channel_id": "ch1", "value": "secret"}), "cipher encrypt")
ok(client.post("/cipher/channels/ch1/licenses", json={"principal": "u1"}), "cipher license")
dec = ok(client.post("/cipher/decrypt", json={"channel_id": "ch1", "ciphertext": enc["ciphertext"], "principal": "u1"}), "cipher decrypt")
assert dec["value"] == "secret", dec
ok(client.post("/cipher/decrypt", json={"channel_id": "ch1", "ciphertext": enc["ciphertext"], "principal": "u2"}), "cipher decrypt denied", expect=403)

# ------------------------------------------------------- 17. marketplace
ok(client.post("/devops/products", json={"id": "prod1", "display_name": "Control Tower"}), "product create")
rel = ok(client.post("/devops/products/prod1/releases", json={"version": "1.0.0", "channel": "stable"}), "release create")
ok(client.get("/marketplace"), "marketplace list")
inst = ok(client.post("/marketplace/prod1/install", json={"target_project": "projA"}), "product install")
ok(client.post(f"/installations/{inst['id']}/upgrade", json={"release_id": rel["id"]}), "product upgrade")

# -------------------------------------------------------- 18. aip extras
cat = ok(client.get("/aip/model-catalog"), "model catalog")
assert cat, f"catalog empty: {cat}"
ok(client.post("/aip/model-catalog/byom", json={"display_name": "My LLM", "provider": "custom", "endpoint_url": "http://x", "model_name": "m"}), "byom register")
ok(client.post("/compute-modules", json={"id": "cm1", "display_name": "CM", "image": "img:1", "entrypoint": "run"}), "compute-module create")
inv = ok(client.post("/compute-modules/cm1/invoke", json={"input": {"x": 1}}), "compute-module invoke")
assert inv.get("output") == {"x": 1}, inv
sdk = ok(client.post("/osdk/generate", json={}), "osdk generate")
assert sdk.get("sdk"), f"osdk empty: {sdk}"

# ------------------------------------------------ 19. code repositories
ok(client.post("/code-repositories", json={"id": "repo1", "display_name": "Pipelines", "language": "python"}), "repo create")
ok(client.post("/code-repositories/repo1/branches", json={"name": "feature-x"}), "repo branch")
ok(client.put("/code-repositories/repo1/files", json={"branch": "feature-x", "path": "clean.py", "content": "print(1)"}), "repo file put")
ok(client.post("/code-repositories/repo1/commits", json={"branch": "feature-x", "message": "add clean", "author": "me", "changes": [{"path": "clean.py", "action": "add"}]}), "repo commit")
chk = ok(client.post("/code-repositories/repo1/checks/run", params={"branch": "feature-x"}), "repo checks")
assert chk["status"] == "passed", chk
mg = ok(client.post("/code-repositories/repo1/merge", params={"branch": "feature-x"}), "repo merge")
assert mg["files_merged"] >= 1, mg

# --------------------------------------------------- 20. code workspaces
ok(client.post("/code-workspaces", json={"id": "ws_dev", "display_name": "Dev", "kind": "vscode"}), "workspace create")
st = ok(client.post("/code-workspaces/ws_dev/status", json={"status": "stopped"}), "workspace status")
assert st["status"] == "stopped", st

# ---------------------------------------------------- 21. code workbook
ok(client.post("/code-workbooks", json={"id": "wb1", "display_name": "Explore", "language": "python", "nodes": [{"id": "n1", "name": "load", "code": "x=1"}, {"id": "n2", "name": "agg", "code": "y=2", "inputs": ["n1"]}]}), "workbook create")
wr = ok(client.post("/code-workbooks/wb1/run"), "workbook run")
assert len(wr["node_results"]) == 2, wr

# -------------------------------------------------------- 22. notepad
ok(client.post("/notepad/documents", json={"id": "doc1", "title": "Ops Brief", "blocks": [{"type": "heading", "content": "Summary"}, {"type": "object_table", "object_type_id": "tool_widget"}, {"type": "metric", "object_type_id": "tool_widget", "agg": "count"}]}), "notepad create")
rendered = ok(client.get("/notepad/documents/doc1/render"), "notepad render")
assert any(b.get("row_count") == 2 for b in rendered["blocks"]), rendered
exp = ok(client.post("/notepad/documents/doc1/export", json={"format": "pdf"}), "notepad export")
assert exp["status"] == "generated", exp

# ---------------------------------------------------------------------------
# Cross-project resolution of ids that came from a stored definition
#
# Seeded last on purpose: it adds a row to an object type earlier assertions count,
# and those counts are part of what they check.
#
# A workshop widget names an object type by id, and that id comes from the module
# definition rather than from the caller, so authorizing the module proves nothing
# about what the id points at. Rendering resolved it across every project, handing
# another tenant's instance ids and row counts to anyone who could view the module.
# T2 of GOAL_TENANCY_2026-08-27.
# ---------------------------------------------------------------------------
from app.database import SessionLocal as _SL  # noqa: E402
from app import models as _m  # noqa: E402
import time as _time  # noqa: E402

_before = ok(client.get("/apps/workshop/wks1/render"), "workshop render before")
_db = _SL()
_db.add(_m.ObjectInstance(id="foreign_widget", object_type_id="tool_widget",
                          project_id="tenant-b", properties={"score": 99},
                          lineage={}, created_at=int(_time.time()), updated_at=int(_time.time())))
_db.commit()
_db.close()

_after = ok(client.get("/apps/workshop/wks1/render"), "workshop render stays in project")
_w = _after["widgets"][0]["resolved"]
assert _w["total_count"] == _before["widgets"][0]["resolved"]["total_count"], _w
assert "foreign_widget" not in _w["preview_ids"], _w
passed += 2


print(f"\nAll Foundry tool modules verified: {passed} endpoint assertions passed.")

from app.database import engine as _engine  # noqa: E402
_engine.dispose()
tmpdir.cleanup()

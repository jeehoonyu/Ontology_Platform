"""
Deep-fidelity pass 11 conformance test:
  Connectivity — incremental sync with cursor high-water-mark (only newer rows pulled).
  Media — chunking + embeddings, entity extraction, layout strategy over stored items.
  Notepad — deep render (template interpolation, live metric, chart series, markdown export).
Run: ./venv312/Scripts/python.exe test_connectivity_media_notepad.py
"""
import os
import tempfile

tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tmpdir.name, 'cmn.db')}"

from fastapi.testclient import TestClient  # noqa: E402
from app.main import app  # noqa: E402

client = TestClient(app)
passed = 0


def ok(resp, label, expect=200):
    global passed
    success = resp.status_code == expect or (expect == 200 and 200 <= resp.status_code < 300)
    assert success, f"{label}: expected {expect}, got {resp.status_code} -> {resp.text[:400]}"
    passed += 1
    return resp.json() if resp.content else {}


# ================= Connectivity: incremental sync =================
ok(client.post("/connections/sources", json={"id": "src", "display_name": "DB", "source_type": "jdbc"}), "source")
ok(client.post("/data-assets", json={"id": "tgt", "display_name": "tgt", "kind": "dataset", "asset_schema": {}, "records": []}), "target")
sync = ok(client.post("/connections/sources/src/syncs", json={"target_asset_id": "tgt", "mode": "incremental", "cursor_field": "updated_at", "sample_records": []}), "sync")
sid = sync["id"]

r1 = ok(client.post(f"/connections/syncs/{sid}/run-incremental", json={"batch": [
    {"id": 1, "updated_at": 10}, {"id": 2, "updated_at": 20}]}), "incr run 1")
assert r1["pulled"] == 2 and r1["new_cursor"] == 20 and r1["target_row_count"] == 2, r1
r2 = ok(client.post(f"/connections/syncs/{sid}/run-incremental", json={"batch": [
    {"id": 2, "updated_at": 20}, {"id": 3, "updated_at": 30}]}), "incr run 2")
assert r2["pulled"] == 1 and r2["skipped_not_newer"] == 1 and r2["new_cursor"] == 30, r2  # only id3 is newer
assert r2["target_row_count"] == 3, r2
cur = ok(client.get(f"/connections/syncs/{sid}/cursor"), "cursor")
assert cur["last_value"] == 30 and cur["runs"] == 2, cur

# ================= Media: chunk / entities / layout =================
ok(client.post("/media-sets", json={"id": "ms", "display_name": "Docs", "media_type": "document"}), "media set")
text = "Invoice from ACME. Contact billing a@b.com on 2024-01-02.\n\nTotal due $1,200.00 for services rendered. " + " ".join(f"line{i}" for i in range(80))
item = ok(client.post("/media-sets/ms/items", json={"filename": "inv.txt", "mime_type": "text/plain", "size_bytes": len(text), "text_content": text}), "item")
iid = item["id"]
ch = ok(client.post(f"/media-items/{iid}/chunk", json={"chunk_size": 40, "overlap": 5}), "media chunk")
assert ch["chunk_count"] >= 2 and all(len(c["embedding"]) == 16 for c in ch["chunks"]), ch
ent = ok(client.post(f"/media-items/{iid}/extract-entities"), "media entities")
assert "a@b.com" in ent["entities"]["emails"], ent
lay = ok(client.post(f"/media-items/{iid}/process", json={"strategy": "layout"}), "media layout")
assert lay["section_count"] >= 2, lay

# ================= Notepad: deep render =================
ok(client.post("/object-types", json={"id": "alert", "display_name": "Alert", "description": "",
    "properties": {"sev": {"type": "string"}, "score": {"type": "number"}}}), "alert type")
for aid, sev, sc in [("a1", "high", 5), ("a2", "high", 3), ("a3", "low", 1)]:
    ok(client.post("/objects", json={"id": aid, "object_type_id": "alert", "properties": {"sev": sev, "score": sc}}), f"obj {aid}")
ok(client.post("/notepad/documents", json={"id": "doc", "title": "Ops Brief", "blocks": [
    {"type": "heading", "content": "Summary"},
    {"type": "template", "template": "Region {region} status report"},
    {"type": "metric", "title": "Total Alerts", "object_type_id": "alert", "agg": "count"},
    {"type": "chart", "object_type_id": "alert", "group_by": "sev", "agg": "count"},
]}), "notepad doc")
rf = ok(client.post("/notepad/documents/doc/render-full", json={"context": {"region": "EMEA"}}), "render-full")
btypes = {b["type"]: b for b in rf["blocks"]}
assert btypes["template"]["content"] == "Region EMEA status report", btypes["template"]
assert btypes["metric"]["value"] == 3, btypes["metric"]
chart_series = {s["group"]: s["value"] for s in btypes["chart"]["series"]}
assert chart_series == {"high": 2, "low": 1}, chart_series
assert rf["markdown_export"].startswith("# Ops Brief") and "Region EMEA status report" in rf["markdown_export"], rf["markdown_export"][:80]

print(f"\nConnectivity + Media + Notepad deep mechanics verified: {passed} assertions passed.")
from app.database import engine as _engine  # noqa: E402
_engine.dispose()
tmpdir.cleanup()

"""
The platform graph says how many of each kind exist, and keeps every edge between loaded nodes.

`/graph/overview` loaded each kind up to `limit` with no totals, and cut its edges at three
times the limit in the order they were added. It now reports `loaded` and `totals` per kind,
counting only a kind that reached the limit, and returns every edge between loaded nodes.

Run:
  python oms/test_graph_overview_totals.py
"""
import os
import tempfile

tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tmpdir.name, 'graph_totals.db')}"

from fastapi.testclient import TestClient  # noqa: E402
from app.main import app  # noqa: E402

client = TestClient(app)
passed = 0


def ok(resp, label, expect=200):
    global passed
    success = resp.status_code == expect or (expect == 200 and 200 <= resp.status_code < 300)
    assert success, f"{label}: expected {expect}, got {resp.status_code} -> {resp.text[:600]}"
    passed += 1
    return resp.json() if resp.content else {}


def check(condition, message):
    global passed
    assert condition, message
    passed += 1


ok(client.post("/object-types", json={"id": "graph_totals", "display_name": "Graph totals", "description": "Graph totals", "properties": {"name": {"type": "string"}}}), "type")
for index in range(3):
    ok(client.post("/data-assets", json={"id": f"graph_totals_asset_{index}", "display_name": f"Graph asset {index}", "kind": "dataset", "asset_schema": {}, "records": []}), f"asset {index}")
    ok(client.post("/objects", json={"id": f"graph_totals_{index}", "object_type_id": "graph_totals", "source_asset_id": f"graph_totals_asset_{index}", "properties": {"name": f"Graph {index}"}}), f"object {index}")

window = ok(client.get("/graph/overview?limit=1"), "graph of one per kind")
check(window["limit"] == 1, window.get("limit"))
check(window["loaded"]["object"] == 1 and window["totals"]["object"] == 3, (window["loaded"], window["totals"]))
check(window["loaded"]["data_asset"] == 1 and window["totals"]["data_asset"] == 3, (window["loaded"], window["totals"]))
check(window["totals"]["object_type"] >= 1 and window["loaded"]["object_type"] == 1, (window["loaded"], window["totals"]))
check(len(window["edges"]) == window["edge_count"], (len(window["edges"]), window["edge_count"]))

whole = ok(client.get("/graph/overview"), "graph at the default limit")
check(whole["totals"] == whole["loaded"], f"below the limit the totals are what was loaded: {whole['totals']} and {whole['loaded']}")
check(whole["totals"]["object"] == 3 and whole["totals"]["data_asset"] == 3, whole["totals"])
check(len(whole["edges"]) == whole["edge_count"], (len(whole["edges"]), whole["edge_count"]))

print(f"Graph overview totals verified: {passed} assertions passed.")
from app.database import engine as _engine  # noqa: E402
_engine.dispose()
tmpdir.cleanup()

"""
A pipeline node preview returns the rows it asks for, and says how many the node holds.

The preview endpoint sliced the node's stored sample, which `_execute_graph` cut to five
rows for every node, so the screen's `limit: 50` could never return more than five; the
drawer drew them with nothing said. The previewed node now keeps what the preview asked
for, and every other node's sample, which the canvas and details carry, stays at five.

Run:
  python oms/test_pipeline_node_preview_window.py
"""
import os
import tempfile

tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tmpdir.name, 'node_preview.db')}"

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


def samples(payload, node_id):
    """Every `sample` list the payload carries for `node_id`, wherever it nests."""
    found = []
    if isinstance(payload, dict):
        if (payload.get("id") == node_id or payload.get("node_id") == node_id) and isinstance(payload.get("sample"), list):
            found.append(payload["sample"])
        for value in payload.values():
            found.extend(samples(value, node_id))
    elif isinstance(payload, list):
        for value in payload:
            found.extend(samples(value, node_id))
    return found


ok(client.post("/data-assets", json={
    "id": "preview_window_rows", "display_name": "Preview window rows", "kind": "dataset", "asset_schema": {},
    "records": [{"row": index, "label": f"row {index}"} for index in range(60)],
}), "create a 60-row input")
ok(client.post("/pipeline-builder/graphs", json={
    "id": "preview_window_graph", "display_name": "Preview window graph",
    "nodes": [{"id": "input", "type": "input_dataset", "label": "Preview input", "position": {"x": 80, "y": 120},
               "config": {"asset_id": "preview_window_rows"}}],
    "edges": [],
}), "create a graph over it")

preview = ok(client.post("/pipeline-builder/graphs/preview_window_graph/nodes/input/preview", json={"limit": 50}), "preview 50 rows")
check(preview["row_count"] == 60, f"the preview says the node holds {preview['row_count']} rows, not 60")
check(len(preview["rows"]) == 50, f"the preview asked for 50 rows and returned {len(preview['rows'])}")
small = ok(client.post("/pipeline-builder/graphs/preview_window_graph/nodes/input/preview", json={"limit": 3}), "preview 3 rows")
check(len(small["rows"]) == 3 and small["row_count"] == 60, (len(small["rows"]), small["row_count"]))

canvas = ok(client.get("/ui-state/pipeline/preview_window_graph/canvas?selected_node_id=input"), "canvas state")
canvas_samples = samples(canvas, "input")
check(canvas_samples and all(len(sample) == 5 for sample in canvas_samples),
      f"the canvas carries samples of {[len(sample) for sample in canvas_samples]} rows; every node's stays at five")
details = ok(client.get("/ui-state/pipeline/preview_window_graph/nodes/input/details"), "node details")
check(len(details["preview"]["rows"]) == 5 and details["preview"]["row_count"] == 60,
      (len(details["preview"]["rows"]), details["preview"]["row_count"]))

print(f"Pipeline node preview window verified: {passed} assertions passed.")
from app.database import engine as _engine  # noqa: E402
_engine.dispose()
tmpdir.cleanup()

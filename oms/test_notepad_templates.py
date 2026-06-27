"""
Standalone self-test for the Notepad TEMPLATE resource (owned: app.notepad +
app.notepad_ops). Builds a local FastAPI app from ONLY the owned routers (does
NOT import app.main, since sibling tasks edit other files concurrently).

Covers:
  - existing notepad document + render-full endpoints still work (both routers)
  - template create / list / get
  - validate: 422 on missing-required and type-mismatch (string/number/object), ok otherwise
  - blocks/from-template: validate then instantiate body blocks with bound-input substitution

Run from oms/:  ./venv312/Scripts/python.exe test_notepad_templates.py
"""
import os
import tempfile

_t = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(_t.name, 't.db')}"

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.database import Base, engine, SessionLocal  # noqa: E402
from app import models, models_action  # noqa: E402  (ensure tables registered)
from app import notepad as NP  # noqa: E402
from app import notepad_ops as NPO  # noqa: E402

Base.metadata.create_all(bind=engine)

api = FastAPI()
api.include_router(NP.router)
api.include_router(NPO.router)
client = TestClient(api)

passed = 0


def ok(resp, label, expect=200):
    global passed
    success = resp.status_code == expect or (expect == 200 and 200 <= resp.status_code < 300)
    assert success, f"{label}: expected {expect}, got {resp.status_code} -> {resp.text[:400]}"
    passed += 1
    return resp.json() if resp.content else {}


# --- seed core rows directly (object type + instances) for live render checks ---
db = SessionLocal()
db.add(models.ObjectType(id="alert", display_name="Alert", description="",
                         properties={"sev": {"type": "string"}},
                         created_at=0, updated_at=0))
for aid, sev in [("a1", "high"), ("a2", "high"), ("a3", "low")]:
    db.add(models.ObjectInstance(id=aid, object_type_id="alert", properties={"sev": sev},
                                 source_asset_id=None, lineage={}, created_at=0, updated_at=0))
db.commit()
db.close()

# ============ existing notepad endpoints still work (router 1) ============
doc = ok(client.post("/notepad/documents", json={
    "id": "doc1", "title": "Ops Brief",
    "blocks": [{"type": "heading", "content": "Summary"}],
}), "create document", expect=201)
assert doc["id"] == "doc1" and doc["blocks"][0]["type"] == "heading", doc

got = ok(client.get("/notepad/documents/doc1"), "get document")
assert got["title"] == "Ops Brief", got

# ============ existing notepad_ops render-full still works (router 2) ============
rf = ok(client.post("/notepad/documents/doc1/render-full", json={"context": {}}), "render-full")
assert rf["markdown_export"].startswith("# Ops Brief"), rf["markdown_export"][:40]

# ============ template create ============
tpl = ok(client.post("/notepad/templates", json={
    "id": "tpl1",
    "name": "Region Brief",
    "inputs": [
        {"name": "region", "type": "string", "required": True},
        {"name": "threshold", "type": "number", "default": 5},
        {"name": "meta", "type": "object", "required": False},
    ],
    "widget_bindings": [
        {"block_ref": "hdr", "input_name": "region"},
        {"block_ref": "metric1", "input_name": "threshold"},
    ],
    "body": [
        {"ref": "hdr", "type": "heading", "content": "Status for {region}"},
        {"ref": "metric1", "type": "metric", "title": "Alerts", "object_type_id": "alert", "agg": "count"},
        {"type": "text", "content": "Static footer note"},
    ],
}), "create template", expect=201)
assert tpl["id"] == "tpl1" and len(tpl["body"]) == 3, tpl

# invalid input type -> 422 at create
ok(client.post("/notepad/templates", json={
    "id": "bad", "name": "Bad", "inputs": [{"name": "x", "type": "boolean"}],
}), "create template invalid type", expect=422)

# ============ template list / get ============
lst = ok(client.get("/notepad/templates"), "list templates")
assert any(t["id"] == "tpl1" for t in lst), lst
g = ok(client.get("/notepad/templates/tpl1"), "get template")
assert g["name"] == "Region Brief", g
ok(client.get("/notepad/templates/nope"), "get missing template", expect=404)

# ============ validate ============
# valid (region supplied, threshold omitted -> uses default, meta optional)
ok(client.post("/notepad/templates/tpl1/validate", json={"inputs": {"region": "EMEA"}}), "validate ok")
# missing required -> 422
ok(client.post("/notepad/templates/tpl1/validate", json={"inputs": {}}), "validate missing required", expect=422)
# type mismatch: region must be string
ok(client.post("/notepad/templates/tpl1/validate", json={"inputs": {"region": 123}}), "validate string mismatch", expect=422)
# type mismatch: threshold must be number (bool is NOT a number)
ok(client.post("/notepad/templates/tpl1/validate", json={"inputs": {"region": "EMEA", "threshold": True}}), "validate number mismatch (bool)", expect=422)
# type mismatch: meta must be object
ok(client.post("/notepad/templates/tpl1/validate", json={"inputs": {"region": "EMEA", "meta": "nope"}}), "validate object mismatch", expect=422)
# number accepts float
ok(client.post("/notepad/templates/tpl1/validate", json={"inputs": {"region": "EMEA", "threshold": 2.5}}), "validate number float ok")

# ============ blocks/from-template ============
# validation gate: missing required -> 422, document unchanged
ok(client.post("/notepad/documents/doc1/blocks/from-template",
               json={"template_id": "tpl1", "inputs": {}}), "from-template missing required", expect=422)
doc_after_fail = ok(client.get("/notepad/documents/doc1"), "doc unchanged after failed instantiate")
assert len(doc_after_fail["blocks"]) == 1, doc_after_fail

# happy path: instantiate body, substituting bound 'region' into heading
res = ok(client.post("/notepad/documents/doc1/blocks/from-template",
                     json={"template_id": "tpl1", "inputs": {"region": "EMEA"}}), "from-template ok")
# doc started with 1 heading block, template adds 3 -> 4 total
assert len(res["blocks"]) == 4, res
new_blocks = res["blocks"][1:]
hdr = new_blocks[0]
assert hdr["type"] == "heading" and hdr["content"] == "Status for EMEA", hdr
assert "ref" not in hdr, hdr  # template-only 'ref' stripped from instantiated block
assert hdr["inputs"]["region"] == "EMEA", hdr  # bound input attached for live resolution
metric_block = new_blocks[1]
assert metric_block["type"] == "metric" and metric_block["inputs"]["threshold"] == 5, metric_block  # default applied
footer = new_blocks[2]
assert footer["type"] == "text" and footer["content"] == "Static footer note", footer  # unbound static block untouched

# render the augmented document end-to-end through notepad_ops (cross-router check)
rf2 = ok(client.post("/notepad/documents/doc1/render-full", json={"context": {}}), "render-full after template")
btypes = {b["type"] for b in rf2["blocks"]}
assert "metric" in btypes and "heading" in btypes, rf2["blocks"]
metric_rendered = next(b for b in rf2["blocks"] if b["type"] == "metric")
assert metric_rendered["value"] == 3, metric_rendered  # live count of seeded alert instances

# from-template on missing document / template -> 404
ok(client.post("/notepad/documents/nope/blocks/from-template",
               json={"template_id": "tpl1", "inputs": {"region": "X"}}), "from-template missing doc", expect=404)
ok(client.post("/notepad/documents/doc1/blocks/from-template",
               json={"template_id": "nope", "inputs": {"region": "X"}}), "from-template missing template", expect=404)

print(f"\nNotepad template resource verified: {passed} assertions passed.")
engine.dispose()
_t.cleanup()

"""
Faithful Ontology-core conformance test: documented base-type catalog, API-name
rules, object-type profiles (primary/title key + property status + base types),
and the Action engine (typed params, submission criteria, full mutation set,
side effects). Run: ./venv312/Scripts/python.exe test_ontology_core.py
"""
import os
import tempfile

tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tmpdir.name, 'onto_core.db')}"

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


# ---- base-type catalog ----
bt = ok(client.get("/ontology/base-types"), "base-types")
names = {b["name"] for b in bt["base_types"]}
assert {"string", "integer", "double", "geopoint", "geoshape", "struct", "mediaReference"} <= names, names
assert "string" in bt["primary_key_allowed"] and "double" not in bt["primary_key_allowed"], bt["primary_key_allowed"]
assert "active" in bt["property_statuses"]

# ---- API-name validation ----
assert ok(client.post("/ontology/validate-api-name", json={"name": "AssetItem", "style": "pascal"}), "apiname ok")["valid"] is True
assert ok(client.post("/ontology/validate-api-name", json={"name": "asset_item", "style": "pascal"}), "apiname bad")["valid"] is False
assert ok(client.post("/ontology/validate-api-name", json={"name": "assetId", "style": "camel"}), "apiname camel ok")["valid"] is True

# ---- object type + profile ----
ok(client.post("/object-types", json={"id": "asset", "display_name": "Asset", "description": "",
    "properties": {"assetId": {"type": "string"}, "name": {"type": "string"}, "score": {"type": "number"}}}), "create asset type")

prof = ok(client.put("/ontology/object-types/asset/profile", json={
    "api_name": "Asset", "primary_key": "assetId", "title_key": "name",
    "icon": "cube", "color": "#2D72D2", "plural_name": "Assets",
    "properties": {
        "assetId": {"base_type": "string", "status": "active"},
        "name": {"base_type": "string", "status": "active"},
        "score": {"base_type": "double", "status": "experimental"},
    }}), "profile upsert")
assert prof["primary_key"] == "assetId" and prof["title_key"] == "name", prof

# invalid primary key type (double not allowed)
ok(client.put("/ontology/object-types/asset/profile", json={
    "api_name": "Asset", "primary_key": "score",
    "properties": {"score": {"base_type": "double"}}}), "profile bad PK", expect=422)
# invalid object-type API name (not PascalCase)
ok(client.put("/ontology/object-types/asset/profile", json={
    "api_name": "asset", "properties": {"assetId": {"base_type": "string"}}}), "profile bad apiname", expect=422)
# unknown base type
ok(client.put("/ontology/object-types/asset/profile", json={
    "api_name": "Asset", "properties": {"x": {"base_type": "supernumber"}}}), "profile bad basetype", expect=422)

full = ok(client.get("/ontology/object-types/asset/full"), "full object type")
assert full["profile"]["primary_key"] == "assetId", full

# ---- Action engine ----
ok(client.post("/object-types", json={"id": "account", "display_name": "Account", "description": "",
    "properties": {"balance": {"type": "number"}, "status": {"type": "string"}}}), "create account type")
ok(client.post("/object-types", json={"id": "person", "display_name": "Person", "description": "",
    "properties": {"name": {"type": "string"}}}), "create person type")
ok(client.post("/link-types", json={"id": "owns", "display_name": "owns", "source_object_type_id": "person",
    "target_object_type_id": "account", "cardinality": "MANY_TO_MANY"}), "create link type")

for aid, status in [("acct1", "OPEN"), ("acct2", "CLOSED")]:
    ok(client.post("/objects", json={"id": aid, "object_type_id": "account", "properties": {"balance": 0, "status": status}}), f"create {aid}")
ok(client.post("/objects", json={"id": "p1", "object_type_id": "person", "properties": {"name": "Ada"}}), "create p1")

# action type with typed params, submission criteria, mutations, side effects
ok(client.post("/action-types", json={
    "id": "adjust_account", "display_name": "Adjust Account", "description": "",
    "parameters": {
        "account_id": {"type": "objectReference", "required": True},
        "amount": {"type": "double", "required": True, "min": 0},
    },
    "rules": {
        "submission_criteria": [{"object_param": "account_id", "property": "status", "op": "eq", "value": "OPEN", "message": "account must be OPEN"}],
        "mutations": [{"op": "modify-object", "object_id": "$account_id", "set": {"balance": "$amount"}}],
        "side_effects": [{"type": "notification", "message": "adjusted", "recipient": "ops"},
                          {"type": "webhook", "url": "http://hook", "payload": {"k": 1}}],
    }}), "create adjust action")

# happy path: applies mutation + fires both side effects
res = ok(client.post("/ontology/action-types/adjust_account/execute", json={"parameters": {"account_id": "acct1", "amount": 100}}), "execute adjust")
assert res["status"] == "applied" and "acct1" in res["mutated_object_ids"], res
assert set(res["side_effects_fired"]) == {"notification", "webhook"}, res
acct1 = ok(client.get("/objects/account/acct1"), "get acct1")
assert acct1["properties"]["balance"] == 100, acct1

# param validation: amount below min -> 422
ok(client.post("/ontology/action-types/adjust_account/execute", json={"parameters": {"account_id": "acct1", "amount": -5}}), "execute bad amount", expect=422)
# missing required param -> 422
ok(client.post("/ontology/action-types/adjust_account/execute", json={"parameters": {"account_id": "acct1"}}), "execute missing param", expect=422)
# object reference to missing object -> 422
ok(client.post("/ontology/action-types/adjust_account/execute", json={"parameters": {"account_id": "ghost", "amount": 5}}), "execute bad ref", expect=422)
# submission criteria fail (acct2 is CLOSED) -> 422
ok(client.post("/ontology/action-types/adjust_account/execute", json={"parameters": {"account_id": "acct2", "amount": 5}}), "execute criteria fail", expect=422)

# dry run
dry = ok(client.post("/ontology/action-types/adjust_account/execute", json={"parameters": {"account_id": "acct1", "amount": 10}, "dry_run": True}), "execute dry run")
assert dry["submittable"] is True and dry["planned_mutations"] == 1, dry

# add-link mutation
ok(client.post("/action-types", json={
    "id": "link_owner", "display_name": "Link Owner", "description": "",
    "parameters": {"person_id": {"type": "objectReference", "required": True}, "account_id": {"type": "objectReference", "required": True}},
    "rules": {"mutations": [{"op": "add-link", "link_type_id": "owns", "source_object_id": "$person_id", "target_object_id": "$account_id"}]}}), "create link action")
lr = ok(client.post("/ontology/action-types/link_owner/execute", json={"parameters": {"person_id": "p1", "account_id": "acct1"}}), "execute add-link")
assert lr["links_changed"], lr
assert len(ok(client.get("/links", params={"link_type_id": "owns"}), "list links")) == 1

# delete-object mutation
ok(client.post("/action-types", json={
    "id": "purge_account", "display_name": "Purge", "description": "",
    "parameters": {"account_id": {"type": "objectReference", "required": True}},
    "rules": {"mutations": [{"op": "delete-object", "object_id": "$account_id"}]}}), "create purge action")
ok(client.post("/ontology/action-types/purge_account/execute", json={"parameters": {"account_id": "acct2"}}), "execute delete")
ok(client.get("/objects/account/acct2"), "acct2 gone", expect=404)

# --- T6: an object type's owning project is not editable through its properties ---
#
# PUT replaces `properties` wholesale, and `properties["__manager"]["project_id"]`
# is what aip_agents, apps and main all read to decide which project owns this
# type -- main uses it to refuse cross-project automation references. So the
# wholesale replace could re-home a type and defeat a check in another module.
# Scoping the read does not prevent that; this does.

from app.database import SessionLocal as _SL  # noqa: E402
from app import models as _m  # noqa: E402

with _SL() as _db:
    _props = dict((_db.get(_m.ObjectType, "asset").properties) or {})

rehome = client.put("/ontology/object-types/asset", json={
    "properties": {**_props, "__manager": {"project_id": "somebody-else"}},
})
assert rehome.status_code == 403, (rehome.status_code, rehome.text[:200])
assert "owning project" in rehome.text, rehome.text[:200]
passed += 1
print("  ok: re-homing an object type through its properties is refused (403)")

same = client.put("/ontology/object-types/asset", json={
    "properties": {**_props, "note": {"type": "string"}},
})
assert same.status_code == 200, (same.status_code, same.text[:200])
passed += 1
print("  ok: an ordinary property edit still works")

# The audit names the caller, not "system".
from app import models_action  # noqa: E402

with _SL() as _db:
    entry = _db.query(models_action.AuditLog).filter(
        models_action.AuditLog.event_type == "ontology.object_type.updated"
    ).order_by(models_action.AuditLog.id.desc()).first()
    assert entry is not None, "the update wrote no audit entry"
    assert entry.actor != "system", f"the trail still says {entry.actor!r}"
passed += 1
print("  ok: the audit entry names the caller rather than \"system\"")

print(f"\nOntology-core faithful behaviors verified: {passed} assertions passed.")
from app.database import engine as _engine  # noqa: E402
_engine.dispose()
tmpdir.cleanup()

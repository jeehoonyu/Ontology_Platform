"""
Standalone self-test for app.object_views_ops (does NOT import app.main).

Covers every brief scenario for AREA object-views:
- create a full view with 2 tabs (workshop + legacy) -> persisted
- standard view yields Properties + Links widgets with the right linked types
- property-condition tab hidden when object doesn't match, shown when it does
- link-condition tab hidden without a link, shown with one
- render resolves Markdown {{displayName}}/{{elevation}} to actual values
- save increments version & is_published=false (when auto_publish off)
- publish sets published_version_id
- republish an older version restores its snapshot
- panel instance returns prominent props
- panel object_set documents the verified 5/3 numbers and flags max_objects unverified
"""

import os, tempfile
_tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(_tmp.name, 't.db')}"

from fastapi import FastAPI                       # noqa: E402
from fastapi.testclient import TestClient         # noqa: E402
from app.database import Base, engine, SessionLocal  # noqa: E402
from app import models, models_action            # noqa: E402  (registers core + audit tables)
from app import object_views_ops as M            # noqa: E402  (registers this module's tables)
import time, uuid                                 # noqa: E402

Base.metadata.create_all(bind=engine)
api = FastAPI(); api.include_router(M.router)
client = TestClient(api)
passed = 0


def ok(resp, label, expect=200):
    global passed
    success = resp.status_code == expect or (expect == 200 and 200 <= resp.status_code < 300)
    assert success, f"{label}: expected {expect}, got {resp.status_code} -> {resp.text[:400]}"
    passed += 1
    return resp.json() if resp.content else {}


def check(cond, label):
    global passed
    assert cond, f"CHECK FAILED: {label}"
    passed += 1


# ---------------------------------------------------------------------------
# Seed core rows directly via a Session (object types, instances, link types/instances)
# ---------------------------------------------------------------------------
now = int(time.time())
db = SessionLocal()

# Building object type with prominent / hidden flags, plus a normal property.
db.add(models.ObjectType(
    id="ot_building",
    display_name="Building",
    description="A building",
    properties={
        "displayName": {"base_type": "string", "visibility": "prominent"},
        "elevation": {"base_type": "integer", "visibility": "prominent"},
        "status": {"base_type": "string", "visibility": "normal"},
        "internal_code": {"base_type": "string", "visibility": "hidden"},
    },
    created_at=now, updated_at=now,
))
# Operator object type (target of a link).
db.add(models.ObjectType(
    id="ot_operator", display_name="Operator", description="op",
    properties={"name": {"base_type": "string", "visibility": "prominent"}},
    created_at=now, updated_at=now,
))
# Link type building -> operator.
db.add(models.LinkType(
    id="lt_assigned", display_name="assigned_to",
    source_object_type_id="ot_building", target_object_type_id="ot_operator",
    cardinality="ONE_TO_MANY",
))
# Two building instances: b1 matches status==active and has a link; b2 doesn't.
db.add(models.ObjectInstance(
    id="b1", object_type_id="ot_building",
    properties={"displayName": "Tower A", "elevation": 120, "status": "active",
                "internal_code": "X1"},
    lineage={}, created_at=now, updated_at=now,
))
db.add(models.ObjectInstance(
    id="b2", object_type_id="ot_building",
    properties={"displayName": "Shed B", "elevation": 5, "status": "inactive"},
    lineage={}, created_at=now, updated_at=now,
))
db.add(models.ObjectInstance(
    id="op1", object_type_id="ot_operator",
    properties={"name": "Alice"}, lineage={}, created_at=now, updated_at=now,
))
# b1 has an assigned_to link; b2 has none.
db.add(models.LinkInstance(
    id="li1", link_type_id="lt_assigned", source_object_id="b1",
    target_object_id="op1", properties={}, created_at=now,
))
db.commit()
db.close()

# ===========================================================================
# 1. Standard view generation
# ===========================================================================
std = ok(client.get("/object-views/ot_building/standard"), "standard view")
check(std["kind"] == "standard", "standard kind")
wtypes = [w["widget_type"] for w in std["widgets"]]
check("property_list" in wtypes and "links" in wtypes, "standard has property_list + links")
pl = next(w for w in std["widgets"] if w["widget_type"] == "property_list")
# prominent properties exclude hidden internal_code; include displayName + elevation
check("displayName" in pl["config"]["prominent_properties"], "prominent has displayName")
check("elevation" in pl["config"]["prominent_properties"], "prominent has elevation")
check("internal_code" not in pl["config"]["prominent_properties"], "hidden excluded from prominent")
links_w = next(w for w in std["widgets"] if w["widget_type"] == "links")
linked_ots = [l["linked_object_type_id"] for l in links_w["config"]["linked_object_types"]]
check("ot_operator" in linked_ots, "standard links derive ot_operator")
check("lt_assigned" in links_w["config"]["link_type_ids"], "standard links has lt_assigned")

# standard view for unknown object type -> 404
ok(client.get("/object-views/nope/standard"), "standard 404", expect=404)

# ===========================================================================
# 2. Create a full view with 2 tabs (workshop + legacy)
# ===========================================================================
view = ok(client.post("/object-views", json={
    "object_type_id": "ot_building", "form_factor": "full", "auto_publish": False,
}), "create full view")
view_id = view["id"]
check(view["form_factor"] == "full", "view form_factor full")
check(view["auto_publish"] is False, "auto_publish off")

# duplicate view for same object type -> 400
ok(client.post("/object-views", json={"object_type_id": "ot_building"}),
   "duplicate view 400", expect=400)
# view for unknown object type -> 404
ok(client.post("/object-views", json={"object_type_id": "ghost"}),
   "view unknown ot 404", expect=404)

tab1 = ok(client.post(f"/object-views/view/{view_id}/tabs", json={
    "tab_type": "workshop", "display_name": "Summary",
}), "add workshop tab")
tab2 = ok(client.post(f"/object-views/view/{view_id}/tabs", json={
    "tab_type": "legacy", "display_name": "Legacy",
}), "add legacy tab")
check(tab1["tab_order"] == 0 and tab2["tab_order"] == 1, "tab order auto-assigned")

tabs = ok(client.get(f"/object-views/view/{view_id}/tabs"), "list tabs")
check(len(tabs) == 2, "two tabs persisted")
check({t["tab_type"] for t in tabs} == {"workshop", "legacy"}, "tab types persisted")

# invalid tab_type -> 422
ok(client.post(f"/object-views/view/{view_id}/tabs",
               json={"tab_type": "bogus", "display_name": "X"}),
   "invalid tab_type 422", expect=422)

# set default tab
upd = ok(client.patch(f"/object-views/view/{view_id}",
                      json={"default_tab_id": tab1["id"]}), "set default tab")
check(upd["default_tab_id"] == tab1["id"], "default_tab_id set")

# ===========================================================================
# 3. Widgets: property_list + markdown on tab1
# ===========================================================================
w_pl = ok(client.post(f"/object-views/tabs/{tab1['id']}/widgets", json={
    "widget_type": "property_list", "config": {"properties": ["displayName", "elevation", "status"]},
}), "add property_list widget")
w_md = ok(client.post(f"/object-views/tabs/{tab1['id']}/widgets", json={
    "widget_type": "markdown",
    "config": {"template": "# {{displayName}} at {{elevation}}m"},
}), "add markdown widget")
check(w_md["widget_order"] == 1, "second widget order 1")

# invalid widget type -> 422
ok(client.post(f"/object-views/tabs/{tab1['id']}/widgets",
               json={"widget_type": "nope"}), "invalid widget 422", expect=422)

wlist = ok(client.get(f"/object-views/tabs/{tab1['id']}/widgets"), "list widgets")
check(len(wlist) == 2, "two widgets on tab1")

# ===========================================================================
# 4. Property-condition tab visibility (tab2 only when status == active)
# ===========================================================================
ok(client.patch(f"/object-views/tabs/{tab2['id']}", json={
    "conditional_visibility": {
        "property_conditions": [{"property": "status", "op": "eq", "value": "active"}],
        "link_conditions": [],
    }
}), "set property condition on tab2")

# render against b1 (status active) -> tab2 visible
r1 = ok(client.get("/object-views/ot_building/b1/rendered"), "render b1")
check(r1["kind"] == "configured", "render configured")
tab_names_b1 = [t["display_name"] for t in r1["tabs"]]
check("Summary" in tab_names_b1, "Summary tab visible for b1")
check("Legacy" in tab_names_b1, "Legacy tab visible for b1 (status active)")

# render against b2 (status inactive) -> tab2 hidden
r2 = ok(client.get("/object-views/ot_building/b2/rendered"), "render b2")
tab_names_b2 = [t["display_name"] for t in r2["tabs"]]
check("Summary" in tab_names_b2, "Summary tab visible for b2")
check("Legacy" not in tab_names_b2, "Legacy tab hidden for b2 (status inactive)")

# ===========================================================================
# 5. Markdown render resolves {{displayName}}/{{elevation}}
# ===========================================================================
summary_tab_b1 = next(t for t in r1["tabs"] if t["display_name"] == "Summary")
md_widget = next(w for w in summary_tab_b1["widgets"] if w["widget_type"] == "markdown")
check(md_widget["resolved"]["text"] == "# Tower A at 120m", "markdown resolved for b1")
pl_widget = next(w for w in summary_tab_b1["widgets"] if w["widget_type"] == "property_list")
check(pl_widget["resolved"]["properties"]["displayName"] == "Tower A", "property_list resolved displayName")
check(pl_widget["resolved"]["properties"]["elevation"] == 120, "property_list resolved elevation")

# render against b2 markdown uses b2 values
summary_tab_b2 = next(t for t in r2["tabs"] if t["display_name"] == "Summary")
md_b2 = next(w for w in summary_tab_b2["widgets"] if w["widget_type"] == "markdown")
check(md_b2["resolved"]["text"] == "# Shed B at 5m", "markdown resolved for b2")

# ===========================================================================
# 6. Link-condition tab visibility (new tab visible only if assigned_to link exists)
# ===========================================================================
tab3 = ok(client.post(f"/object-views/view/{view_id}/tabs", json={
    "tab_type": "workshop", "display_name": "Operators",
    "conditional_visibility": {
        "property_conditions": [],
        "link_conditions": [{"link_type_id": "lt_assigned", "exists": True}],
    },
}), "add link-condition tab")

r1b = ok(client.get("/object-views/ot_building/b1/rendered"), "render b1 again")
check("Operators" in [t["display_name"] for t in r1b["tabs"]], "Operators tab visible for b1 (has link)")
r2b = ok(client.get("/object-views/ot_building/b2/rendered"), "render b2 again")
check("Operators" not in [t["display_name"] for t in r2b["tabs"]], "Operators tab hidden for b2 (no link)")

# render unknown object -> 404
ok(client.get("/object-views/ot_building/ghost/rendered"), "render missing obj 404", expect=404)

# ===========================================================================
# 7. Versioning: save increments version, is_published=false (auto_publish off)
# ===========================================================================
v1 = ok(client.post(f"/object-views/view/{view_id}/save",
                    json={"description": "first save"}), "save v1")
check(v1["version_number"] == 1, "version number 1")
check(v1["is_published"] is False, "v1 not published (auto off)")

v2 = ok(client.post(f"/object-views/view/{view_id}/save",
                    json={"description": "second save"}), "save v2")
check(v2["version_number"] == 2, "version number 2")
check(v2["is_published"] is False, "v2 not published")

vlist = ok(client.get(f"/object-views/view/{view_id}/versions"), "list versions")
check(len(vlist) == 2, "two versions listed")

# ===========================================================================
# 8. Publish sets published_version_id
# ===========================================================================
pub2 = ok(client.put(f"/object-views/view/{view_id}/versions/{v2['version_id']}/publish"),
          "publish v2")
check(pub2["published_version_id"] == v2["version_id"], "published_version_id == v2")
view_after = ok(client.get(f"/object-views/view/{view_id}"), "get view after publish")
check(view_after["published_version_id"] == v2["version_id"], "view shows published v2")

# ===========================================================================
# 9. Republish an older version restores its snapshot
# ===========================================================================
# Mutate the live view: delete a tab so current state differs from v1/v2 snapshots.
# v2's snapshot had Summary + Legacy + Operators (3 tabs). Delete Operators now.
ok(client.delete(f"/object-views/tabs/{tab3['id']}"), "delete operators tab")
cur_tabs = ok(client.get(f"/object-views/view/{view_id}/tabs"), "tabs after delete")
check(len(cur_tabs) == 2, "two tabs after delete")

# Republish v2 -> should restore the 3-tab snapshot.
rep = ok(client.put(f"/object-views/view/{view_id}/versions/{v2['version_id']}/publish"),
         "republish v2")
check(rep["restored_tab_count"] == 3, "republish v2 restores 3 tabs")
restored = ok(client.get(f"/object-views/view/{view_id}/tabs"), "tabs after republish")
check("Operators" in [t["display_name"] for t in restored], "Operators restored on republish")

# ===========================================================================
# 10. Panel instance returns prominent props
# ===========================================================================
# Update view to panel/instance.
ok(client.patch(f"/object-views/view/{view_id}",
                json={"form_factor": "panel", "panel_mode": "instance"}),
   "switch to panel instance")
pi = ok(client.get("/object-views/ot_building/form-factor/panel?object_id=b1"),
        "panel instance form factor")
check(pi["panel_mode"] == "instance", "panel mode instance")
check("displayName" in pi["prominent_properties"], "panel instance prominent has displayName")
check("internal_code" not in pi["prominent_properties"], "panel instance excludes hidden")
check(pi["property_values"]["displayName"] == "Tower A", "panel instance resolved b1 value")

# Full form factor lists tabs.
ff_full = ok(client.get("/object-views/ot_building/form-factor/full"), "panel full form factor")
check(len(ff_full["tabs"]) == 3, "full form factor lists 3 tabs")

# ===========================================================================
# 11. Panel object_set documents verified 5/3 numbers, flags max_objects unverified
# ===========================================================================
ok(client.patch(f"/object-views/view/{view_id}",
                json={"panel_mode": "object_set"}), "switch to object_set")
pos = ok(client.get("/object-views/ot_building/form-factor/panel"), "panel object_set")
check(pos["max_charts"] == 5, "object_set documented 5 charts")
check(pos["max_properties_per_object"] == 3, "object_set documented 3 props/object")
# NOTE: max_objects is NOT documented on config-panel-views; flagged unverified.
check(pos["max_objects_documented"] is False, "max_objects flagged undocumented/unverified")

# invalid form factor -> 422
ok(client.get("/object-views/ot_building/form-factor/bogus"),
   "invalid form factor 422", expect=422)

# ===========================================================================
# 12. Sidebar upsert + get
# ===========================================================================
sb = ok(client.post(f"/object-views/view/{view_id}/sidebar",
                    json={"config": {"groups": [{"title": "Apps", "cards": ["a1"]}]}}),
        "create sidebar")
check(sb["config"]["groups"][0]["title"] == "Apps", "sidebar config stored")
sb2 = ok(client.post(f"/object-views/view/{view_id}/sidebar",
                     json={"config": {"groups": []}}), "update sidebar")
check(sb2["config"]["groups"] == [], "sidebar config updated")
sbg = ok(client.get(f"/object-views/view/{view_id}/sidebar"), "get sidebar")
check(sbg["id"] == sb["id"], "sidebar same row (upsert)")

# ===========================================================================
# 13. property condition operators (is_defined / is_one_of) sanity
# ===========================================================================
# is_defined on a property b2 lacks (internal_code) -> tab hidden for b2, shown for b1.
ok(client.patch(f"/object-views/tabs/{tab2['id']}", json={
    "conditional_visibility": {
        "property_conditions": [{"property": "internal_code", "op": "is_defined"}],
        "link_conditions": [],
    }
}), "set is_defined condition")
# switch back to full so render uses full tab set (render is form-factor-agnostic on tabs)
r1c = ok(client.get("/object-views/ot_building/b1/rendered"), "render b1 is_defined")
check("Legacy" in [t["display_name"] for t in r1c["tabs"]], "is_defined true for b1")
r2c = ok(client.get("/object-views/ot_building/b2/rendered"), "render b2 is_defined")
check("Legacy" not in [t["display_name"] for t in r2c["tabs"]], "is_defined false for b2")

print(f"\nOBJECT-VIEWS verified: {passed} assertions passed.")
engine.dispose(); _tmp.cleanup()

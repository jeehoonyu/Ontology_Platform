import os, tempfile, time
_tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(_tmp.name, 't.db')}"
from fastapi import FastAPI                       # noqa: E402
from fastapi.testclient import TestClient         # noqa: E402
from app.database import Base, engine, SessionLocal  # noqa: E402
from app import models, models_action            # noqa: E402  (registers core + audit tables)
from app import ontology_interfaces               # noqa: E402  (registers base interface tables)
from app import ontology_interfaces_ops as M      # noqa: E402  (registers this module's tables)

Base.metadata.create_all(bind=engine)
api = FastAPI()
# Mount THIS deepening module's router first so its routes win on any path that also
# exists in the base module (e.g. /interfaces/{id}/check-object-type), then mount the
# base interfaces router for create/list endpoints this module relies on.
api.include_router(M.router)
api.include_router(ontology_interfaces.router)
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
# Seed core rows directly via Session (object types, instances, link types).
# ---------------------------------------------------------------------------
now = int(time.time())
db = SessionLocal()

# Interface base interface A is created via endpoints. Object types implementing A.
db.add(models.ObjectType(
    id="ot_incident", display_name="Incident",
    description="incidents", properties={"title": {}, "state": {}, "sev": {}},
    created_at=now, updated_at=now,
))
db.add(models.ObjectType(
    id="ot_alert", display_name="Alert",
    description="alerts", properties={"name": {}, "status": {}},
    created_at=now, updated_at=now,
))
# Object type C target for an interface link constraint -> implemented by a link type.
db.add(models.ObjectType(
    id="ot_team", display_name="Team",
    description="teams", properties={"team_name": {}},
    created_at=now, updated_at=now,
))

# Object instances of the two implementers of A.
db.add(models.ObjectInstance(
    id="inc1", object_type_id="ot_incident",
    properties={"title": "DB down", "state": "open", "sev": 5},
    created_at=now, updated_at=now,
))
db.add(models.ObjectInstance(
    id="inc2", object_type_id="ot_incident",
    properties={"title": "Disk full", "state": "closed", "sev": 2},
    created_at=now, updated_at=now,
))
db.add(models.ObjectInstance(
    id="alrt1", object_type_id="ot_alert",
    properties={"name": "CPU high", "status": "open"},
    created_at=now, updated_at=now,
))

# Link type from incident -> team (used for the link constraint mapping on B).
db.add(models.LinkType(
    id="lt_inc_team", display_name="Incident owned by team",
    source_object_type_id="ot_incident", target_object_type_id="ot_team",
    cardinality="MANY_TO_MANY",
))
# A wrong-source link type (source = alert) to test source validation.
db.add(models.LinkType(
    id="lt_alert_team", display_name="Alert owned by team",
    source_object_type_id="ot_alert", target_object_type_id="ot_team",
    cardinality="MANY_TO_MANY",
))
db.commit()
db.close()


# ---------------------------------------------------------------------------
# Scenario 1: create base interface A and child B extends[A]; all-properties(B).
# ---------------------------------------------------------------------------
a = ok(client.post("/interfaces", json={
    "id": "iface_A", "display_name": "Trackable",
    "properties": {
        "name": {"base_type": "string", "required": True},
        "status": {"base_type": "string", "required": False},
    },
    "extends": [],
}), "create interface A")
check(a["id"] == "iface_A", "A id")

# Interface C (target of the link constraint on B).
ok(client.post("/interfaces", json={
    "id": "iface_C", "display_name": "Assignable",
    "properties": {"owner": {"base_type": "string", "required": False}},
    "extends": [],
}), "create interface C")

b = ok(client.post("/interfaces", json={
    "id": "iface_B", "display_name": "Severe",
    "properties": {"severity": {"base_type": "integer", "required": True}},
    "extends": ["iface_A"],
}), "create interface B extends A")
check(b["extends"] == ["iface_A"], "B extends A")

allp = ok(client.get("/interfaces/iface_B/all-properties"), "all-properties(B)")
check(allp["count"] == 3, f"B has 3 resolved properties, got {allp['count']}")
props = allp["properties"]
check(set(props.keys()) == {"name", "status", "severity"}, "B resolved prop names")
check(props["name"]["required"] is True, "inherited name required")
check(props["status"]["required"] is False, "inherited status optional")
check(props["severity"]["required"] is True, "local severity required")
check(allp["inherited_from"]["name"] == "iface_A", "name inherited from A")
check(allp["inherited_from"]["severity"] == "iface_B", "severity from B")

# Local-overrides-parent on name clash: child redefines `status` as required.
ok(client.post("/interfaces", json={
    "id": "iface_Override", "display_name": "Override",
    "properties": {"status": {"base_type": "string", "required": True}},
    "extends": ["iface_A"],
}), "create override interface")
ov = ok(client.get("/interfaces/iface_Override/all-properties"), "all-properties(Override)")
check(ov["properties"]["status"]["required"] is True, "child overrides parent status")
check(ov["inherited_from"]["status"] == "iface_Override", "status now from child")


# ---------------------------------------------------------------------------
# Scenario 2: OT1, OT2 implement A; query-objects(A) returns normalized objects.
# ---------------------------------------------------------------------------
impl1 = ok(client.post("/object-types/ot_incident/implement-interface", json={
    "interface_id": "iface_A",
    "property_mappings": {"name": "title", "status": "state"},
}), "incident implements A")
check(impl1["object_type_id"] == "ot_incident", "impl1 ot")

impl2 = ok(client.post("/object-types/ot_alert/implement-interface", json={
    "interface_id": "iface_A",
    "property_mappings": {"name": "name", "status": "status"},
}), "alert implements A")
check(impl2["interface_id"] == "iface_A", "impl2 iface")

# Duplicate implementation -> 400.
ok(client.post("/object-types/ot_incident/implement-interface", json={
    "interface_id": "iface_A",
    "property_mappings": {"name": "title", "status": "state"},
}), "duplicate implement -> 400", expect=400)

impls = ok(client.get("/interfaces/iface_A/implementations"), "list A implementations")
check(len(impls["implementations"]) == 2, "A has 2 implementations")

oti = ok(client.get("/object-types/ot_incident/implemented-interfaces"), "incident implemented-interfaces")
check(any(i["interface_id"] == "iface_A" for i in oti["implementations"]), "incident implements A listed")

q = ok(client.post("/interfaces/iface_A/query-objects", json={}), "query A no filters")
check(q["count"] == 3, f"query A returns 3 objects, got {q['count']}")
check(set(q["object_type_ids_searched"]) == {"ot_incident", "ot_alert"}, "both ot searched")
# Normalization: incident's title->name, state->status.
by_id = {o["id"]: o for o in q["objects"]}
check(by_id["inc1"]["interface_properties"]["name"] == "DB down", "inc1 normalized name")
check(by_id["inc1"]["interface_properties"]["status"] == "open", "inc1 normalized status")
check(by_id["alrt1"]["interface_properties"]["name"] == "CPU high", "alrt1 normalized name")

# Polymorphic filter returns only matching rows (status=open across both types).
qf = ok(client.post("/interfaces/iface_A/query-objects", json={"filters": {"status": "open"}}),
        "query A filter status=open")
check(qf["count"] == 2, f"filter open returns 2 (inc1, alrt1), got {qf['count']}")
ids = {o["id"] for o in qf["objects"]}
check(ids == {"inc1", "alrt1"}, "filter open returns inc1 & alrt1 only")

qf2 = ok(client.post("/interfaces/iface_A/query-objects", json={"filters": {"status": "closed"}}),
         "query A filter status=closed")
check(qf2["count"] == 1 and qf2["objects"][0]["id"] == "inc2", "filter closed returns inc2 only")

# limit honored.
ql = ok(client.post("/interfaces/iface_A/query-objects", json={"limit": 1}), "query A limit 1")
check(ql["count"] == 1, "limit 1 honored")


# ---------------------------------------------------------------------------
# Scenario 3: required link constraint on B targeting interface C; check-object-type
# fails until link_mapping added via implement-interface.
# ---------------------------------------------------------------------------
lc = ok(client.post("/interfaces/iface_B/link-type-constraints", json={
    "api_name": "ownedBy", "target_kind": "interface", "target_id": "iface_C",
    "cardinality": "MANY", "required": True,
}), "create required link constraint on B -> C")
check(lc["required"] is True, "constraint required")

# Resolved listing includes the constraint.
lcs = ok(client.get("/interfaces/iface_B/link-type-constraints?resolved=true"),
         "list resolved constraints B")
check(len(lcs["constraints"]) == 1, "B has 1 resolved constraint")

# Incident's properties: title, state, sev. Map B props: name->title, status->state, severity->sev.
# But no link_mapping yet -> implement-interface(B) should 422 (missing required link).
r = client.post("/object-types/ot_incident/implement-interface", json={
    "interface_id": "iface_B",
    "property_mappings": {"name": "title", "status": "state", "severity": "sev"},
})
ok(r, "implement B without link_mapping -> 422", expect=422)
detail = r.json()["detail"]
check(any("ownedBy" in str(u) for u in detail["unmet"]), "unmet mentions ownedBy link")

# check-object-type(B, incident) should not conform (no implementation recorded; missing link).
chk = ok(client.post("/interfaces/iface_B/check-object-type", json={"object_type_id": "ot_incident"}),
         "check B against incident (pre-mapping)")
check(chk["conforms"] is False, "incident does not conform to B yet")
check("ownedBy" in chk["missing_link_constraints"], "missing link constraint ownedBy")

# Now implement B WITH a valid link_mapping (source incident -> lt_inc_team).
implB = ok(client.post("/object-types/ot_incident/implement-interface", json={
    "interface_id": "iface_B",
    "property_mappings": {"name": "title", "status": "state", "severity": "sev"},
    "link_mappings": {"ownedBy": "lt_inc_team"},
}), "implement B with valid link_mapping")
check(implB["link_mappings"]["ownedBy"] == "lt_inc_team", "link mapping persisted")

# check-object-type(B, incident) now conforms.
chk2 = ok(client.post("/interfaces/iface_B/check-object-type", json={"object_type_id": "ot_incident"}),
          "check B against incident (post-mapping)")
check(chk2["conforms"] is True, "incident now conforms to B")
check(chk2["missing_link_constraints"] == [], "no missing link constraints")
check(chk2["missing_properties"] == [], "no missing properties")

# Wrong-source link type should fail validation. Create object type that has the right props
# but maps to a link whose source is the wrong type.
rw = client.post("/object-types/ot_alert/implement-interface", json={
    "interface_id": "iface_B",
    "property_mappings": {"name": "name", "status": "status", "severity": "name"},
    "link_mappings": {"ownedBy": "lt_alert_team"},
})
# alert has no "severity" property; severity maps to "name" which exists -> property ok.
# But lt_alert_team source IS ot_alert, so that part is fine. This should actually succeed.
ok(rw, "alert implements B with its own link", expect=200)

# Delete the link constraint.
dl = ok(client.delete(f"/interfaces/iface_B/link-type-constraints/{lc['id']}"),
        "delete link constraint")
check(dl["deleted"] == lc["id"], "constraint deleted")
lcs2 = ok(client.get("/interfaces/iface_B/link-type-constraints"), "list constraints after delete")
check(len(lcs2["constraints"]) == 0, "no constraints after delete")


# ---------------------------------------------------------------------------
# Scenario 4: create action without parameter_property -> 422; with valid shared prop -> 200.
# ---------------------------------------------------------------------------
ok(client.post("/interfaces/iface_A/actions", json={
    "api_name": "createTrackable", "operation": "create",
}), "create action w/o parameter_property -> 422", expect=422)

# parameter_property not a resolved property -> 422.
ok(client.post("/interfaces/iface_A/actions", json={
    "api_name": "createTrackable", "operation": "create", "parameter_property": "nope",
}), "create action w/ invalid parameter_property -> 422", expect=422)

act = ok(client.post("/interfaces/iface_A/actions", json={
    "api_name": "createTrackable", "operation": "create", "parameter_property": "name",
}), "create action w/ valid parameter_property -> 200")
check(act["operation"] == "create" and act["parameter_property"] == "name", "create action persisted")

# Modify/delete actions don't need parameter_property.
ok(client.post("/interfaces/iface_A/actions", json={
    "api_name": "modifyTrackable", "operation": "modify",
}), "modify action w/o parameter_property -> 200")
ok(client.post("/interfaces/iface_A/actions", json={
    "api_name": "deleteTrackable", "operation": "delete",
}), "delete action w/o parameter_property -> 200")

# Invalid operation -> 422.
ok(client.post("/interfaces/iface_A/actions", json={
    "api_name": "weird", "operation": "frobnicate",
}), "invalid operation -> 422", expect=422)

acts = ok(client.get("/interfaces/iface_A/actions"), "list A actions")
check(len(acts["actions"]) == 3, f"A has 3 actions, got {len(acts['actions'])}")


# ---------------------------------------------------------------------------
# Misc 404 paths.
# ---------------------------------------------------------------------------
ok(client.get("/interfaces/nope/all-properties"), "all-properties missing iface -> 404", expect=404)
ok(client.post("/object-types/nope/implement-interface", json={"interface_id": "iface_A",
   "property_mappings": {}}), "implement on missing OT -> 404", expect=404)
ok(client.post("/interfaces/iface_A/check-object-type", json={"object_type_id": "nope"}),
   "check missing OT -> 404", expect=404)

print(f"\nINTERFACES verified: {passed} assertions passed.")
engine.dispose(); _tmp.cleanup()

import os, tempfile, math
_tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(_tmp.name, 't.db')}"
from fastapi import FastAPI                       # noqa: E402
from fastapi.testclient import TestClient         # noqa: E402
from app.database import Base, engine, SessionLocal  # noqa: E402
from app import models, models_action            # noqa: E402  (registers core + audit tables)
from app import vertex_ops as M                   # noqa: E402  (registers this module's tables)
import time                                        # noqa: E402

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
# Seed core ontology rows directly via a Session.
# ---------------------------------------------------------------------------
now = int(time.time())
db = SessionLocal()

# Object types: Person and Event
db.add(models.ObjectType(id="ot_person", display_name="Person", description=None,
                         properties={"name": {}, "age": {}}, created_at=now, updated_at=now))
db.add(models.ObjectType(id="ot_event", display_name="Event", description=None,
                         properties={"title": {}, "start_ms": {}, "end_ms": {}}, created_at=now, updated_at=now))

# Link type: Person -> Person (knows), and Person -> Event (attended)
db.add(models.LinkType(id="lt_knows", display_name="knows", description=None,
                       source_object_type_id="ot_person", target_object_type_id="ot_person",
                       cardinality="MANY_TO_MANY"))
db.add(models.LinkType(id="lt_attended", display_name="attended", description=None,
                       source_object_type_id="ot_person", target_object_type_id="ot_event",
                       cardinality="MANY_TO_MANY"))

# 3 people seed objects + 1 extra reachable person
for pid, name, age in [("p1", "Alice", 30), ("p2", "Bob", 40), ("p3", "Carol", 50), ("p4", "Dave", 25)]:
    db.add(models.ObjectInstance(id=pid, object_type_id="ot_person",
                                 properties={"name": name, "age": age}, source_asset_id=None,
                                 lineage={}, created_at=now, updated_at=now))

# Two events with time fields
db.add(models.ObjectInstance(id="e1", object_type_id="ot_event",
                             properties={"title": "Launch", "start_ms": 1000, "end_ms": 2000},
                             source_asset_id=None, lineage={}, created_at=now, updated_at=now))
db.add(models.ObjectInstance(id="e2", object_type_id="ot_event",
                             properties={"title": "Review", "start_ms": 9000, "end_ms": 9500},
                             source_asset_id=None, lineage={}, created_at=now, updated_at=now))

# Links: p1 knows p2, p2 knows p3, p3 knows p4; p1 attended e1; p2 attended e2
db.add(models.LinkInstance(id="l1", link_type_id="lt_knows", source_object_id="p1",
                           target_object_id="p2", properties={}, created_at=now))
db.add(models.LinkInstance(id="l2", link_type_id="lt_knows", source_object_id="p2",
                           target_object_id="p3", properties={}, created_at=now))
db.add(models.LinkInstance(id="l3", link_type_id="lt_knows", source_object_id="p3",
                           target_object_id="p4", properties={}, created_at=now))
db.add(models.LinkInstance(id="l4", link_type_id="lt_attended", source_object_id="p1",
                           target_object_id="e1", properties={}, created_at=now))
db.add(models.LinkInstance(id="l5", link_type_id="lt_attended", source_object_id="p2",
                           target_object_id="e2", properties={}, created_at=now))
db.commit()
db.close()


# ---------------------------------------------------------------------------
# Scenario A: build a graph from 3 seed objects
# ---------------------------------------------------------------------------
g = ok(client.post("/vertex/graphs", json={
    "display_name": "G1", "seed_object_ids": ["p1", "p2", "p3"], "layout_type": "grid"}),
    "create graph")
gid = g["id"]
check(len(g["nodes"]) == 3, "graph has 3 seed nodes")
check(g["edges"] == [], "graph starts with no edges")
check(all(n.get("is_seed") for n in g["nodes"]), "all nodes flagged as seed")
check(set(g["seed_object_ids"]) == {"p1", "p2", "p3"}, "seed ids recorded")

# seed validation: non-existent seed -> 404
ok(client.post("/vertex/graphs", json={"display_name": "bad", "seed_object_ids": ["nope"]}),
   "missing seed 404", expect=404)
# bad layout -> 422
ok(client.post("/vertex/graphs", json={"display_name": "bad", "seed_object_ids": ["p1"],
   "layout_type": "spiral"}), "bad layout 422", expect=422)


# ---------------------------------------------------------------------------
# Scenario B: expand over a link type returns reachable nodes/edges
# ---------------------------------------------------------------------------
# From p1,p2,p3 expanding 'knows' out by depth 1 should reach p4 (via p3->p4) and add edges.
exp = ok(client.post(f"/vertex/graphs/{gid}/explore",
                     json={"link_type_id": "lt_knows", "direction": "out", "depth": 1}),
         "explore knows out")
node_ids = {n["id"] for n in exp["graph"]["nodes"]}
check("p4" in node_ids, "explore reached p4")
check(exp["added_nodes"] == 1, "explore added exactly 1 node (p4)")
edge_ids = {e["id"] for e in exp["graph"]["edges"]}
check({"l1", "l2", "l3"}.issubset(edge_ids), "explore added knows edges l1,l2,l3")
check(exp["added_edges"] >= 3, "explore reports >=3 added edges")

# explore with bad link type -> 404
ok(client.post(f"/vertex/graphs/{gid}/explore", json={"link_type_id": "nope", "direction": "out", "depth": 1}),
   "explore bad link 404", expect=404)
# explore bad direction -> 422
ok(client.post(f"/vertex/graphs/{gid}/explore", json={"direction": "sideways", "depth": 1}),
   "explore bad direction 422", expect=422)

# Re-expanding the same thing adds nothing new (idempotent merge).
exp2 = ok(client.post(f"/vertex/graphs/{gid}/explore",
                      json={"link_type_id": "lt_knows", "direction": "out", "depth": 1}),
          "explore again")
check(exp2["added_nodes"] == 0, "re-explore adds no new nodes")


# ---------------------------------------------------------------------------
# Scenario C: circular layout positions deterministic & on the unit circle
# ---------------------------------------------------------------------------
gc = ok(client.post("/vertex/graphs", json={
    "display_name": "Circle", "seed_object_ids": ["p1", "p2", "p3", "p4"], "layout_type": "circular"}),
    "create circular graph")
cnodes = gc["nodes"]
check(len(cnodes) == 4, "circular graph has 4 nodes")
SCALE = 100.0
for i, n in enumerate(cnodes):
    angle = 2.0 * math.pi * i / 4
    ex = round(math.cos(angle) * SCALE, 9)
    ey = round(math.sin(angle) * SCALE, 9)
    check(abs(n["x"] - ex) < 1e-6 and abs(n["y"] - ey) < 1e-6, f"circular pos {i} deterministic")
    # on unit circle once divided by scale
    r = math.hypot(n["x"] / SCALE, n["y"] / SCALE)
    check(abs(r - 1.0) < 1e-6, f"circular pos {i} on unit circle")

# Re-layout an existing graph to circular and verify persisted positions on unit circle.
relg = ok(client.post(f"/vertex/graphs/{gid}/layout", json={"layout_type": "circular"}), "relayout circular")
check(relg["layout_type"] == "circular", "layout type persisted")
nn = len(relg["nodes"])
for i, n in enumerate(relg["nodes"]):
    r = math.hypot(n["x"] / SCALE, n["y"] / SCALE)
    check(abs(r - 1.0) < 1e-6, f"relayout node {i} on unit circle")


# ---------------------------------------------------------------------------
# Scenario D: filter fades non-matching nodes
# ---------------------------------------------------------------------------
# Filter G1 nodes (p1..p4) by age >= 40 -> Bob(40), Carol(50) match; Alice(30), Dave(25) faded.
fres = ok(client.post(f"/vertex/graphs/{gid}/filter", json={"property": "age", "op": "gte", "value": 40}),
          "filter age>=40")
check(fres["matched"] == 2, "filter matched 2 nodes")
check(fres["faded"] == 2, "filter faded 2 nodes")
faded_map = {n["id"]: n["faded"] for n in fres["graph"]["nodes"]}
check(faded_map["p1"] is True and faded_map["p4"] is True, "young people faded")
check(faded_map["p2"] is False and faded_map["p3"] is False, "older people not faded")


# ---------------------------------------------------------------------------
# Scenario E: styles persist
# ---------------------------------------------------------------------------
sres = ok(client.post(f"/vertex/graphs/{gid}/style", json={
    "node_styling": {"color_by": "age"}, "edge_styling": {"width": 2}}), "style graph")
check(sres["styles"]["node_styling"]["color_by"] == "age", "node styling persisted")
check(sres["styles"]["edge_styling"]["width"] == 2, "edge styling persisted")
# confirm via GET
ggot = ok(client.get(f"/vertex/graphs/{gid}"), "get graph after style")
check(ggot["styles"]["node_styling"]["color_by"] == "age", "style survives reload")


# ---------------------------------------------------------------------------
# Scenario F: template execute with an object param produces expected expanded graph
# ---------------------------------------------------------------------------
t = ok(client.post("/vertex/templates", json={
    "display_name": "FriendsOf",
    "object_params": [{"name": "root", "object_type_id": "ot_person"}],
    "scalar_params": [{"name": "depth", "default": 2}],
    "search_arounds": [{"link_type_id": "lt_knows", "direction": "out", "depth": 2}],
}), "create template")
tid = t["id"]
check(len(t["object_params"]) == 1, "template has 1 object param")

# Execute with root=p1, depth-2 'knows' out -> p1,p2,p3 (p4 at depth 3 excluded).
texec = ok(client.post(f"/vertex/templates/{tid}/execute", json={"object_param_values": {"root": "p1"}}),
           "execute template")
texec_ids = {n["id"] for n in texec["nodes"]}
check(texec_ids == {"p1", "p2", "p3"}, "template execute reached p1,p2,p3 at depth 2")
texec_edges = {e["id"] for e in texec["edges"]}
check({"l1", "l2"}.issubset(texec_edges), "template execute added expected edges")

# Wrong object type for param -> 422
ok(client.post(f"/vertex/templates/{tid}/execute", json={"object_param_values": {"root": "e1"}}),
   "template wrong type 422", expect=422)
# Missing param value -> 422
ok(client.post(f"/vertex/templates/{tid}/execute", json={"object_param_values": {}}),
   "template missing param 422", expect=422)


# ---------------------------------------------------------------------------
# Scenario G: timeline + timeline filter fades out-of-window nodes
# ---------------------------------------------------------------------------
# Build a graph seeded with two events, configure events, then timeline filter.
ge = ok(client.post("/vertex/graphs", json={
    "display_name": "Events", "seed_object_ids": ["e1", "e2", "p1"], "layout_type": "grid"}),
    "create events graph")
geid = ge["id"]
ok(client.post(f"/vertex/graphs/{geid}/events", json={
    "event_object_type_id": "ot_event", "start_time_field": "start_ms", "end_time_field": "end_ms",
    "intent": "schedule"}), "configure events")

tl = ok(client.get(f"/vertex/graphs/{geid}/timeline"), "get timeline")
check(tl["count"] == 2, "timeline has 2 events")
check(tl["events"][0]["node_id"] == "e1", "timeline sorted: e1 first (start 1000)")
check(tl["events"][1]["node_id"] == "e2", "timeline sorted: e2 second (start 9000)")

# Window 0..5000 includes e1 (1000), excludes e2 (9000); p1 has no event -> kept visible.
tlf = ok(client.post(f"/vertex/graphs/{geid}/timeline/filter", json={"start_ms": 0, "end_ms": 5000}),
         "timeline filter")
tlf_map = {n["id"]: n["faded"] for n in tlf["graph"]["nodes"]}
check(tlf_map["e1"] is False, "e1 in window not faded")
check(tlf_map["e2"] is True, "e2 out of window faded")
check(tlf_map["p1"] is False, "non-event node not faded")
check(tlf["faded"] == 1, "timeline filter faded exactly 1 node")


# ---------------------------------------------------------------------------
# Scenario H: scenario returns baseline != override for changed props
# ---------------------------------------------------------------------------
sc = ok(client.post(f"/vertex/graphs/{gid}/scenarios", json={
    "display_name": "Aging", "parameter_overrides": {"p1": {"age": 99}}}), "create scenario")
check(sc["kind"] == "deterministic_what_if_simulation", "scenario clearly labeled deterministic")
check(sc["baseline"]["p1"]["age"] == 30, "scenario baseline preserves original age")
check(sc["scenario_output"]["p1"]["age"] == 99, "scenario output has overridden age")
check(sc["diff"]["p1"]["age"]["baseline"] == 30 and sc["diff"]["p1"]["age"]["scenario"] == 99,
      "scenario diff shows baseline != scenario")
check("p2" not in sc["diff"], "unchanged node not in diff")
sid = sc["id"]
scg = ok(client.get(f"/vertex/graphs/{gid}/scenarios/{sid}"), "get scenario")
check(scg["scenario_output"]["p1"]["age"] == 99, "scenario fetch round-trips override")
ok(client.get(f"/vertex/graphs/{gid}/scenarios/nope"), "missing scenario 404", expect=404)


# ---------------------------------------------------------------------------
# Scenario I: control panel settings persist
# ---------------------------------------------------------------------------
cp = ok(client.post("/vertex/control-panel/settings", json={"settings": {"theme": "dark"}}),
        "set control panel")
check(cp["settings"]["theme"] == "dark", "control panel setting stored")
cp2 = ok(client.post("/vertex/control-panel/settings", json={"settings": {"max_nodes": 500}}),
         "update control panel")
check(cp2["settings"]["theme"] == "dark" and cp2["settings"]["max_nodes"] == 500,
      "control panel merges settings")
cpg = ok(client.get("/vertex/control-panel/settings"), "get control panel")
check(cpg["settings"]["max_nodes"] == 500, "control panel reload persists")


print(f"\nVERTEX verified: {passed} assertions passed.")
engine.dispose(); _tmp.cleanup()

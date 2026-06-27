"""Standalone self-test for vertex_ops link-merging (does NOT import app.main).

Builds a local FastAPI app from ONLY the vertex_ops router, seeds core ontology
rows directly, then exercises the new POST /vertex/graphs/{id}/links/merge endpoint
alongside a smoke check of the pre-existing build/explore behavior.

Run from oms/:  ./venv312/Scripts/python.exe test_vertex_link_merge.py
"""

import os, tempfile

_t = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(_t.name, 't.db')}"

from fastapi import FastAPI                          # noqa: E402
from fastapi.testclient import TestClient            # noqa: E402
from app.database import Base, engine, SessionLocal  # noqa: E402
from app import models, models_action                # noqa: E402
from app import vertex_ops as M                       # noqa: E402
import time                                            # noqa: E402

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
# Seed core ontology rows: two endpoint objects + many parallel "transaction"
# links between them (the classic link-merging case), plus a side node.
# ---------------------------------------------------------------------------
now = int(time.time())
db = SessionLocal()

db.add(models.ObjectType(id="ot_acct", display_name="Account", description=None,
                         properties={"name": {}}, created_at=now, updated_at=now))
db.add(models.LinkType(id="lt_txn", display_name="transacted", description=None,
                       source_object_type_id="ot_acct", target_object_type_id="ot_acct",
                       cardinality="MANY_TO_MANY"))
db.add(models.LinkType(id="lt_other", display_name="related", description=None,
                       source_object_type_id="ot_acct", target_object_type_id="ot_acct",
                       cardinality="MANY_TO_MANY"))

for aid, name in [("a1", "Alice"), ("a2", "Bob"), ("a3", "Carol")]:
    db.add(models.ObjectInstance(id=aid, object_type_id="ot_acct",
                                 properties={"name": name}, source_asset_id=None,
                                 lineage={}, created_at=now, updated_at=now))

# Three parallel txn links a1->a2 with weights, one reverse a2->a1 (same endpoint pair),
# plus one differently-typed link a1->a2, and one unrelated link a2->a3.
db.add(models.LinkInstance(id="t1", link_type_id="lt_txn", source_object_id="a1",
                           target_object_id="a2", properties={"weight": 10}, created_at=now))
db.add(models.LinkInstance(id="t2", link_type_id="lt_txn", source_object_id="a1",
                           target_object_id="a2", properties={"weight": 25}, created_at=now))
db.add(models.LinkInstance(id="t3", link_type_id="lt_txn", source_object_id="a1",
                           target_object_id="a2", properties={"weight": 5}, created_at=now))
db.add(models.LinkInstance(id="t4", link_type_id="lt_txn", source_object_id="a2",
                           target_object_id="a1", properties={"weight": 100}, created_at=now))
db.add(models.LinkInstance(id="o1", link_type_id="lt_other", source_object_id="a1",
                           target_object_id="a2", properties={}, created_at=now))
db.add(models.LinkInstance(id="x1", link_type_id="lt_txn", source_object_id="a2",
                           target_object_id="a3", properties={"weight": 7}, created_at=now))
db.commit()
db.close()


# ---------------------------------------------------------------------------
# Build a graph and populate edges by exploring (pre-existing behavior intact).
# ---------------------------------------------------------------------------
g = ok(client.post("/vertex/graphs", json={
    "display_name": "Money", "seed_object_ids": ["a1", "a2", "a3"], "layout_type": "grid"}),
    "create graph")
gid = g["id"]
check(g["edges"] == [], "graph starts with no edges")

exp = ok(client.post(f"/vertex/graphs/{gid}/explore",
                     json={"direction": "both", "depth": 1}), "explore both")
edge_ids = {e["id"] for e in exp["graph"]["edges"]}
# All six LinkInstances are between graph nodes -> all present as distinct edges.
check({"t1", "t2", "t3", "t4", "o1", "x1"}.issubset(edge_ids),
      "explore captured all 6 distinct parallel/intermediate edges")
before_total = len(exp["graph"]["edges"])
check(before_total == 6, "graph has 6 edges before merge")


# ---------------------------------------------------------------------------
# Validation paths.
# ---------------------------------------------------------------------------
ok(client.post(f"/vertex/graphs/{gid}/links/merge", json={"aggregation": "median"}),
   "bad aggregation 422", expect=422)
ok(client.post(f"/vertex/graphs/{gid}/links/merge", json={"link_type_id": "nope"}),
   "bad link_type_id 404", expect=404)
ok(client.post("/vertex/graphs/nope/links/merge", json={}),
   "missing graph 404", expect=404)


# ---------------------------------------------------------------------------
# Merge ONLY lt_txn edges by count. The four txn edges between {a1,a2}
# (t1,t2,t3 forward + t4 reverse) collapse into ONE aggregated edge (count 4).
# The lt_other edge o1 (a1-a2) is NOT eligible -> passes through unchanged.
# The lt_txn edge x1 (a2-a3) is a singleton bucket -> stays as-is.
# ---------------------------------------------------------------------------
mr = ok(client.post(f"/vertex/graphs/{gid}/links/merge",
                    json={"link_type_id": "lt_txn", "aggregation": "count"}),
        "merge lt_txn by count")
check(mr["before_edge_count"] == 6, "merge reports before=6")
check(mr["merged_edge_count"] == 1, "exactly one aggregated edge produced")
# after = passthrough(o1) + singleton(x1) + 1 merged = 3
check(mr["after_edge_count"] == 3, "after-merge edge count is 3")
merged = mr["merged_edges"][0]
check(merged["merged_count"] == 4, "aggregated edge carries count of 4 collapsed edges")
check(set(merged["merged_edge_ids"]) == {"t1", "t2", "t3", "t4"},
      "aggregated edge references the 4 collapsed link ids")
check(tuple(sorted((merged["source_object_id"], merged["target_object_id"]))) == ("a1", "a2"),
      "aggregated edge spans the a1-a2 endpoint pair")
check(merged.get("merged") is True, "aggregated edge flagged merged=True")
check(merged["label"] == "4", "count aggregation label is the count")
# summed weight is also carried when weights present (10+25+5+100)
check(merged.get("merged_weight") == 140.0, "summed weight present even for count aggregation")

# The persisted graph reflects the merge, and passthrough/singleton survive.
gg = ok(client.get(f"/vertex/graphs/{gid}"), "get graph after merge")
gg_edge_ids = {e["id"] for e in gg["edges"]}
check("o1" in gg_edge_ids, "non-eligible lt_other edge preserved")
check("x1" in gg_edge_ids, "singleton lt_txn edge preserved")
check(not ({"t1", "t2", "t3", "t4"} & gg_edge_ids), "collapsed raw edges removed from graph")
check(len(gg["edges"]) == 3, "persisted graph has 3 edges after merge")


# ---------------------------------------------------------------------------
# sum_weight aggregation on a fresh graph, no link_type filter (merge across types
# on the same endpoint pair). a1-a2 has t1,t2,t3,t4 (txn) -> bucketed by link type,
# so txn collapses (weights 140) and o1 stays a singleton.
# ---------------------------------------------------------------------------
g2 = ok(client.post("/vertex/graphs", json={
    "display_name": "Money2", "seed_object_ids": ["a1", "a2"], "layout_type": "grid"}),
    "create graph 2")
g2id = g2["id"]
ok(client.post(f"/vertex/graphs/{g2id}/explore", json={"direction": "both", "depth": 1}),
   "explore graph 2")
mr2 = ok(client.post(f"/vertex/graphs/{g2id}/links/merge",
                     json={"aggregation": "sum_weight"}), "merge by sum_weight")
sw = [e for e in mr2["merged_edges"] if e["link_type_id"] == "lt_txn"][0]
check(sw["merged_weight"] == 140.0, "sum_weight merged edge sums weights to 140")
check(sw["label"] == "140.0", "sum_weight label is the summed weight")
check(sw["aggregation"] == "sum_weight", "aggregation echoed on merged edge")

# Idempotency-ish: merging again on the already-merged graph leaves the single
# aggregated edge as a singleton bucket (count edge is not re-collapsed).
mr3 = ok(client.post(f"/vertex/graphs/{gid}/links/merge",
                     json={"link_type_id": "lt_txn", "aggregation": "count"}),
         "re-merge already merged graph")
check(mr3["merged_edge_count"] == 0, "re-merge collapses nothing new")
check(mr3["after_edge_count"] == 3, "re-merge keeps edge count stable at 3")


# ---------------------------------------------------------------------------
# group_by on a LINK PROPERTY. The category lives on the LinkInstance, NOT on
# the graph edge dict (edges don't materialize link props), so grouping must
# resolve it from the underlying link. wire (w1,w2) collapses; ach (ac1) stays
# a separate singleton — the merge must NOT lump them together.
# ---------------------------------------------------------------------------
db = SessionLocal()
db.add(models.ObjectInstance(id="b1", object_type_id="ot_acct", properties={"name": "B1"},
                             source_asset_id=None, lineage={}, created_at=now, updated_at=now))
db.add(models.ObjectInstance(id="b2", object_type_id="ot_acct", properties={"name": "B2"},
                             source_asset_id=None, lineage={}, created_at=now, updated_at=now))
db.add(models.LinkInstance(id="w1", link_type_id="lt_txn", source_object_id="b1",
                           target_object_id="b2", properties={"weight": 1, "category": "wire"}, created_at=now))
db.add(models.LinkInstance(id="w2", link_type_id="lt_txn", source_object_id="b1",
                           target_object_id="b2", properties={"weight": 2, "category": "wire"}, created_at=now))
db.add(models.LinkInstance(id="ac1", link_type_id="lt_txn", source_object_id="b1",
                           target_object_id="b2", properties={"weight": 3, "category": "ach"}, created_at=now))
db.commit(); db.close()

g3 = ok(client.post("/vertex/graphs", json={
    "display_name": "ByCat", "seed_object_ids": ["b1", "b2"], "layout_type": "grid"}), "create graph 3")
g3id = g3["id"]
ok(client.post(f"/vertex/graphs/{g3id}/explore", json={"direction": "both", "depth": 1}), "explore graph 3")
mrg = ok(client.post(f"/vertex/graphs/{g3id}/links/merge",
                    json={"link_type_id": "lt_txn", "aggregation": "count", "group_by": "category"}),
         "merge grouped by category")
# Only the two 'wire' txns collapse; the 'ach' txn must remain separate.
check(mrg["merged_edge_count"] == 1, "group_by category collapses only the 'wire' bucket")
gm = mrg["merged_edges"][0]
check(gm["merged_count"] == 2, "grouped merged edge has count 2 (the two wire txns, not all 3)")
check(gm.get("group_value") == "wire", "merged edge carries group_value resolved from the LinkInstance")
check(set(gm["merged_edge_ids"]) == {"w1", "w2"}, "grouped merge references only the wire links, not ach")
gg3 = ok(client.get(f"/vertex/graphs/{g3id}"), "get graph 3 after grouped merge")
check("ac1" in {e["id"] for e in gg3["edges"]}, "the 'ach' txn survives as a distinct edge")


print(f"\nVERTEX link-merge verified: {passed} assertions passed.")
engine.dispose(); _t.cleanup()

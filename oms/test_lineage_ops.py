import os, tempfile, time
_tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(_tmp.name, 't.db')}"
from fastapi import FastAPI                       # noqa: E402
from fastapi.testclient import TestClient         # noqa: E402
from app.database import Base, engine, SessionLocal  # noqa: E402
from app import models, models_action            # noqa: E402  (registers core + audit tables)
from app import lineage_ops as M                   # noqa: E402  (registers this module's tables)
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
# Seed core rows directly via a Session:
#   chain A -> p1 -> B -> p2 -> C
# ---------------------------------------------------------------------------
now = int(time.time())
db = SessionLocal()
for did, name in [("A", "Asset A"), ("B", "Asset B"), ("C", "Asset C")]:
    db.add(models.DataAsset(id=did, display_name=name, description=None, kind="dataset",
                            asset_schema={}, records=[], created_at=now, updated_at=now))
db.add(models.PipelineDefinition(id="p1", display_name="P1", description=None,
                                 input_asset_id="A", output_asset_id="B", mode="batch",
                                 schedule=None, steps=[], created_at=now, updated_at=now))
db.add(models.PipelineDefinition(id="p2", display_name="P2", description=None,
                                 input_asset_id="B", output_asset_id="C", mode="batch",
                                 schedule=None, steps=[], created_at=now, updated_at=now))
db.commit()
db.close()

# ---------------------------------------------------------------------------
# 1. Recursive traversal: downstream(A) -> B@depth1, C@depth2 (p1@1, p2@2 too)
# ---------------------------------------------------------------------------
d = ok(client.get("/lineage/resource/dataset/A/downstream?depth=5"), "downstream(A)")
down_nodes = {n["id"]: n["depth"] for n in d["nodes"]}
check("B" in down_nodes and "C" in down_nodes, "downstream(A) contains B and C")
check(down_nodes["B"] == 1, "B is at depth 1 downstream of A")
check(down_nodes["C"] == 2, "C is at depth 2 downstream of A")
check(down_nodes.get("p1") == 1 and down_nodes.get("p2") == 2, "pipelines at expected depths")

# depth bound: depth=1 returns only B (and p1), not C
d1 = ok(client.get("/lineage/resource/dataset/A/downstream?depth=1"), "downstream(A) depth=1")
d1_ids = {n["id"] for n in d1["nodes"]}
check("B" in d1_ids and "C" not in d1_ids, "depth=1 stops before C")

# upstream(C) -> B@depth1 (via p2), A@depth2 (via p1)
u = ok(client.get("/lineage/resource/dataset/C/upstream?depth=5"), "upstream(C)")
up_nodes = {n["id"]: n["depth"] for n in u["nodes"]}
check("A" in up_nodes and "B" in up_nodes, "upstream(C) contains A and B")
check(up_nodes["B"] == 1 and up_nodes["A"] == 2, "upstream depths correct")

# bad kind -> 422 ; missing node -> 404
ok(client.get("/lineage/resource/bogus/A/downstream"), "bad kind -> 422", expect=422)
ok(client.get("/lineage/resource/dataset/ZZZ/downstream"), "missing node -> 404", expect=404)

# ---------------------------------------------------------------------------
# 2. Column discovery
# ---------------------------------------------------------------------------
ok(client.put("/lineage/dataset/A/schema", json={"columns": [
    {"name": "customer_id", "type": "string"},
    {"name": "customer_name", "type": "string"},
]}), "register schema A")
ok(client.put("/lineage/dataset/B/schema", json={"columns": [
    {"name": "customer_id", "type": "string"},
    {"name": "order_total", "type": "double"},
]}), "register schema B")
ok(client.put("/lineage/dataset/C/schema", json={"columns": [
    {"name": "region", "type": "string"},
]}), "register schema C")

sc = ok(client.get("/lineage/dataset/A/schema"), "get schema A")
check(len(sc["columns"]) == 2, "schema A has 2 columns")

# exact search 'customer_id' finds A and B, not C
r = ok(client.get("/lineage/columns/search?column=customer_id"), "search customer_id")
found = {m["dataset_id"] for m in r["datasets"]}
check(found == {"A", "B"}, "customer_id found in A and B only")
check(r["count"] == 2, "customer_id count == 2")

# exact search must not match a prefix
r2 = ok(client.get("/lineage/columns/search?column=customer"), "search exact 'customer' (no match)")
check(r2["count"] == 0, "exact 'customer' matches nothing")

# prefix search 'customer' finds A (customer_id, customer_name) and B (customer_id)
rp = ok(client.get("/lineage/columns/search?column=customer&prefix=true"), "prefix search customer")
pfound = {m["dataset_id"] for m in rp["datasets"]}
check(pfound == {"A", "B"}, "prefix 'customer' finds A and B")
a_match = next(m for m in rp["datasets"] if m["dataset_id"] == "A")
check(len(a_match["matched_columns"]) == 2, "A has 2 prefix-matched columns")

# schema on unknown dataset -> 404; duplicate columns -> 422
ok(client.put("/lineage/dataset/NOPE/schema", json={"columns": []}), "schema unknown ds -> 404", expect=404)
ok(client.put("/lineage/dataset/C/schema", json={"columns": [
    {"name": "dup"}, {"name": "dup"}]}), "duplicate cols -> 422", expect=422)

# ---------------------------------------------------------------------------
# 5. Build timeline (record builds with timestamps; B stale vs A)
#    Use started_at/completed_at so B's latest build predates A's rebuild.
# ---------------------------------------------------------------------------
# Initial builds: A@100, B@200, C@300
ok(client.post("/lineage/dataset/A/builds", json={"id": "bA1", "status": "SUCCEEDED",
   "records_in": 10, "records_out": 10, "started_at": 100, "completed_at": 110}), "build A1")
ok(client.post("/lineage/dataset/B/builds", json={"id": "bB1", "status": "SUCCEEDED",
   "records_in": 10, "records_out": 8, "started_at": 200, "completed_at": 210}), "build B1")
ok(client.post("/lineage/dataset/C/builds", json={"id": "bC1", "status": "SUCCEEDED",
   "records_in": 8, "records_out": 8, "started_at": 300, "completed_at": 310}), "build C1")

# Build timeline metrics for A: add a failed build, check success_rate / avg_duration
ok(client.post("/lineage/dataset/A/builds", json={"id": "bA2", "status": "FAILED",
   "records_in": 0, "records_out": 0, "started_at": 120, "completed_at": 130}), "build A2 failed")
tl = ok(client.get("/lineage/dataset/A/builds"), "timeline A")
m = tl["metrics"]
check(m["count"] == 2, "A has 2 builds")
check(abs(m["success_rate"] - 0.5) < 1e-9, "A success_rate 0.5")
# durations: bA1 = 10*1000=10000, bA2 = 10*1000=10000 -> avg 10000
check(abs(m["avg_duration_ms"] - 10000) < 1e-9, "A avg_duration_ms 10000")
check(m["total_records_out"] == 10, "A total_records_out 10")
# history ordered by started_at: bA1 (100) before bA2 (120)
check([h["id"] for h in tl["history"]] == ["bA1", "bA2"], "A history ordered by started_at")

# build on unknown dataset -> 404
ok(client.post("/lineage/dataset/NOPE/builds", json={"status": "SUCCEEDED"}), "build unknown ds -> 404", expect=404)

# ---------------------------------------------------------------------------
# 4. Staleness: rebuild A LATER than B's latest build -> B stale UPSTREAM_CHANGED
# ---------------------------------------------------------------------------
# B latest build completed at 210. Rebuild A completing at 500 (> 210).
ok(client.post("/lineage/dataset/A/builds", json={"id": "bA3", "status": "SUCCEEDED",
   "records_in": 12, "records_out": 12, "started_at": 500, "completed_at": 510}), "build A3 (late)")
stB = ok(client.get("/lineage/dataset/B/staleness"), "staleness B")
check(stB["is_stale"] is True, "B is stale")
check(stB["reason"] == "UPSTREAM_CHANGED", "B stale reason UPSTREAM_CHANGED")
check(any(x["dataset_id"] == "A" for x in stB["newer_upstream"]), "B newer_upstream includes A")

# A itself has no upstream dataset -> not stale
stA = ok(client.get("/lineage/dataset/A/staleness"), "staleness A")
check(stA["is_stale"] is False, "A not stale (no upstream)")

# Dataset with no build -> NO_BUILD. Seed a fresh isolated dataset D.
dbx = SessionLocal()
dbx.add(models.DataAsset(id="D", display_name="Asset D", description=None, kind="dataset",
                         asset_schema={}, records=[], created_at=now, updated_at=now))
dbx.commit(); dbx.close()
stD = ok(client.get("/lineage/dataset/D/staleness"), "staleness D")
check(stD["is_stale"] is True and stD["reason"] == "NO_BUILD", "D NO_BUILD")

# ---------------------------------------------------------------------------
# 3. Impact analysis
# ---------------------------------------------------------------------------
imp = ok(client.get("/lineage/impact/dataset/A"), "impact(A)")
imp_ids = {x["id"]: x["impact_type"] for x in imp["impacted"]}
check("B" in imp_ids and "C" in imp_ids, "impact(A) includes B and C")
check(imp_ids["B"] == "STALE" and imp_ids["C"] == "STALE", "downstream datasets STALE")
check(imp_ids.get("p1") == "NEEDS_REBUILD", "pipeline impact NEEDS_REBUILD")

# Marking impact: must set a marking first; before that -> 422
ok(client.get("/lineage/impact/marking/A"), "marking impact before set -> 422", expect=422)
ok(client.post("/lineage/dataset/A/markings", json={"marking": "PII"}), "set marking on A")
mimp = ok(client.get("/lineage/impact/marking/A"), "marking impact(A)")
mids = {x["id"]: x["impact_type"] for x in mimp["impacted"]}
check("B" in mids and "C" in mids, "marking impact includes B,C")
check(all(v == "PERMISSION_CHANGE" for v in mids.values()), "all PERMISSION_CHANGE")
ml = ok(client.get("/lineage/dataset/A/markings"), "list markings A")
check(ml["count"] == 1 and ml["markings"][0]["marking"] == "PII", "marking listed")
ok(client.post("/lineage/dataset/NOPE/markings", json={"marking": "X"}), "marking unknown ds -> 404", expect=404)

# ---------------------------------------------------------------------------
# 6. Rollback
# ---------------------------------------------------------------------------
rb = ok(client.post("/lineage/dataset/A/rollback", json={"to_build_id": "bA1", "reason": "bad data"}), "rollback A -> bA1")
check(rb["to_build_id"] == "bA1", "rollback target is bA1")
check(rb["restored_build"]["status"] == "SUCCEEDED", "restored build succeeded")
check(rb["from_build_id"] == "bA3", "from_build_id is latest (bA3)")

rbl = ok(client.get("/lineage/dataset/A/rollbacks"), "list rollbacks A")
check(rbl["count"] == 1, "one rollback recorded")

# rollback to a FAILED build -> 422
ok(client.post("/lineage/dataset/A/rollback", json={"to_build_id": "bA2"}), "rollback to failed -> 422", expect=422)
# rollback to absent build -> 404
ok(client.post("/lineage/dataset/A/rollback", json={"to_build_id": "ZZZ"}), "rollback to absent -> 404", expect=404)
# rollback on unknown dataset -> 404
ok(client.post("/lineage/dataset/NOPE/rollback", json={"to_build_id": "bA1"}), "rollback unknown ds -> 404", expect=404)

print(f"\nLINEAGE verified: {passed} assertions passed.")
engine.dispose(); _tmp.cleanup()

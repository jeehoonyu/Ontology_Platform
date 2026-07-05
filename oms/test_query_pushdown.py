"""
Track A — object-set query pushdown + pagination.
Proves the SQL equality pre-filter + Python confirm returns results IDENTICAL to a
pure-Python filter (by comparing against the full set filtered client-side), and
exercises offset/cursor pagination and opt-in total.
Run: ./venv312/Scripts/python.exe test_query_pushdown.py
"""
import os
import tempfile

_tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(_tmp.name, 'pd.db')}"

from fastapi.testclient import TestClient  # noqa: E402
from app.main import app  # noqa: E402
from app.database import engine  # noqa: E402

client = TestClient(app)
passed = 0


def ok(resp, label, expect=200):
    global passed
    success = resp.status_code == expect or (expect == 200 and 200 <= resp.status_code < 300)
    assert success, f"{label}: expected {expect}, got {resp.status_code} -> {resp.text[:300]}"
    passed += 1
    return resp.json() if resp.content else {}


def check(cond, label):
    global passed
    assert cond, f"CHECK FAILED: {label}"
    passed += 1


# ---- seed an object type + 12 objects with mixed-type properties ----
ok(client.post("/object-types", json={"id": "dev", "display_name": "Device", "description": "",
    "properties": {"status": {"type": "string"}, "score": {"type": "number"}, "region": {"type": "string"}}}), "dev type")
seed = [
    ("d0", "active", 5, "EMEA"), ("d1", "active", 10, "APAC"), ("d2", "inactive", 5, "EMEA"),
    ("d3", "active", 3, "AMER"), ("d4", "inactive", 8, "APAC"), ("d5", "active", 5, "EMEA"),
    ("d6", "pending", 1, "AMER"), ("d7", "active", 7, "APAC"), ("d8", "inactive", 5, "EMEA"),
    ("d9", "active", 9, "AMER"), ("d10", "pending", 5, "APAC"), ("d11", "active", 2, "EMEA"),
]
for did, status, score, region in seed:
    ok(client.post("/objects", json={"id": did, "object_type_id": "dev",
        "properties": {"status": status, "score": score, "region": region}}), f"obj {did}")


def search(filters=None, **kw):
    body = {"object_type_id": "dev", "limit": 1000}
    if filters is not None:
        body["filters"] = filters
    body.update(kw)
    return ok(client.post("/object-sets/search", json=body), f"search {filters} {kw}")


# full unfiltered set = source of truth to compare against
full = search()
all_objs = {o["id"]: o["properties"] for o in full["objects"]}
check(full["total"] == 12 and full["count"] == 12, "full set has 12")


def expected_ids(pred):
    return sorted(oid for oid, p in all_objs.items() if pred(p))


# 1. string equality (pushed to SQL) == pure-Python filter
r = search({"status": "active"})
check(sorted(o["id"] for o in r["objects"]) == expected_ids(lambda p: p["status"] == "active"), "status==active identical")
check(r["total"] == 7, "7 active")

# 2. numeric equality (pushed) == pure-Python (int value)
r = search({"score": 5})
check(sorted(o["id"] for o in r["objects"]) == expected_ids(lambda p: p["score"] == 5), "score==5 identical")

# 3. combined equality predicates (both pushed) — AND semantics preserved
r = search({"status": "active", "region": "EMEA"})
check(sorted(o["id"] for o in r["objects"]) == expected_ids(lambda p: p["status"] == "active" and p["region"] == "EMEA"),
      "active+EMEA identical")

# 4. comparison op (NOT pushed — Python path) still correct
r = search({"score": {"gt": 5}})
check(sorted(o["id"] for o in r["objects"]) == expected_ids(lambda p: p["score"] > 5), "score>5 identical")

# 5. contains op (Python path) correct
r = search({"region": {"contains": "ME"}})  # EMEA / AMER contain 'me' (case-insensitive)
check(sorted(o["id"] for o in r["objects"]) == expected_ids(lambda p: "me" in p["region"].lower()), "region contains ME identical")

# 6. equality with no matches -> empty, no over-restriction weirdness
r = search({"status": "ghost"})
check(r["objects"] == [] and r["total"] == 0, "no-match equality returns empty")

# ---- pagination: offset + cursor + opt-in total ----
p1 = search(limit=5, offset=0)
check(p1["count"] == 5 and p1["total"] == 12 and p1["next_cursor"], "page1: 5 of 12 + cursor")
p2 = ok(client.post("/object-sets/search", json={"object_type_id": "dev", "limit": 5, "cursor": p1["next_cursor"]}), "page2 by cursor")
check(p2["count"] == 5, "page2: 5")
p3 = ok(client.post("/object-sets/search", json={"object_type_id": "dev", "limit": 5, "cursor": p2["next_cursor"]}), "page3 by cursor")
check(p3["count"] == 2 and p3["next_cursor"] is None, "page3: final 2, no next cursor")
# pages are disjoint and cover the whole set
paged_ids = [o["id"] for o in p1["objects"]] + [o["id"] for o in p2["objects"]] + [o["id"] for o in p3["objects"]]
check(sorted(paged_ids) == sorted(all_objs.keys()) and len(paged_ids) == len(set(paged_ids)),
      "cursor pages tile the full set with no overlap")

# with_total=false omits the count (skips the full-scan count)
nt = ok(client.post("/object-sets/search", json={"object_type_id": "dev", "limit": 3, "with_total": False}), "no total")
check(nt.get("total") is None and nt["count"] == 3, "with_total=false omits total")

# offset pagination over a FILTERED set (Python path) still paginates correctly
fp = ok(client.post("/object-sets/search", json={"object_type_id": "dev", "filters": {"status": "active"}, "limit": 3, "offset": 3}), "filtered offset")
check(fp["total"] == 7 and fp["count"] == 3, "filtered page: 7 active, offset 3 limit 3 -> 3 rows")
check(fp["next_cursor"], "filtered page has a next cursor (1 active remains)")

print(f"\nQuery pushdown + pagination verified: {passed} assertions passed.")
engine.dispose()
_tmp.cleanup()

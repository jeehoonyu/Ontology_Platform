"""
An entity-resolution job says how much of its object type it compared, and reaches past its scan.

GOAL_HONEST_UI_2026-09-11, the Decision workspace limits and entity resolution's reach. A job
compares every pair among the first objects of its type by id, keeps how many objects the type
held, how many it compared and the last id it read, and Explain says whether an object was
compared. The exact pass then pairs every object of the type that shares a value in one of the
job's fields, ignoring case and punctuation, scores those pairs as the scan does, and counts the
shared values it left unpaired because more objects share them than it pairs.

Run:
  python oms/test_entity_resolution_coverage.py
"""
import os
import tempfile
import time

tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tmpdir.name, 'entity_coverage.db')}"

from fastapi.testclient import TestClient  # noqa: E402
from app.main import app  # noqa: E402

client = TestClient(app)
passed = 0


def ok(resp, label, expect=200):
    global passed
    success = resp.status_code == expect or (expect == 200 and 200 <= resp.status_code < 300)
    assert success, f"{label}: expected {expect}, got {resp.status_code} -> {resp.text[:800]}"
    passed += 1
    return resp.json() if resp.content else {}


def check(condition, label, detail=""):
    global passed
    assert condition, f"{label}: {detail}"
    passed += 1


def pairs_of(job):
    return sorted(sorted(candidate["object_ids"]) for candidate in job["candidates"])


TYPE = "er_cut"
ok(client.post("/object-types", json={
    "id": TYPE, "display_name": "Entity coverage", "description": "Past the 1,000 a job compares",
    "properties": {"name": {"type": "string"}, "code": {"type": "string"}},
}), "object type")

# The named objects have the highest ids but are hydrated first, from a source asset whose id sorts
# before the fillers'. With no ORDER BY, SQLite reads this scope through
# ix_object_instances_materialized_active (project, type, source asset, active, id), so an unordered
# scan reads them first; only a scan in id order leaves them out of the first 1,000.
#   z1, z2  an exact pair past the scan: only the exact pass can reach it.
#   z3, z4  a near pair past the scan, no value shared: nothing compares it at limit 1,000, and an
#           unordered scan would.
#   z5      shares an exact name with filler 0, which the scan reads: the pass pairs across the scan's edge.
# The other fillers carry no name, so their pairs score 0 and write no candidate.
def hydrate(name, records):
    ok(client.post("/data-assets", json={
        "id": f"{TYPE}_{name}", "display_name": f"Entity coverage {name}", "kind": "dataset", "asset_schema": {}, "records": records,
    }), f"{name} feed")
    ok(client.post("/pipelines", json={
        "id": f"{TYPE}_{name}_hydrate", "display_name": f"Entity coverage {name} hydrate", "input_asset_id": f"{TYPE}_{name}",
        "steps": [{"operation": "map_to_ontology", "object_type_id": TYPE, "object_id_field": "id",
                   "property_map": {"name": "$name", "code": "$code"}, "omit_nulls": True}],
    }), f"{name} pipeline")
    run = ok(client.post(f"/pipelines/{TYPE}_{name}_hydrate/run", params={"actor": "test"}), f"{name} hydrate")
    check(run.get("status") == "SUCCESS", f"{name} hydrate succeeded", run)


hydrate("a_pair", [
    {"id": f"{TYPE}_z1", "name": "Duplicate Pump Omega", "code": "D1"},
    {"id": f"{TYPE}_z2", "name": "duplicate pump omega", "code": "D2"},
    {"id": f"{TYPE}_z3", "name": "Fuzzy Valve Kappa", "code": "N3"},
    {"id": f"{TYPE}_z4", "name": "Fuzzy Valve Kappas", "code": "N4"},
    {"id": f"{TYPE}_z5", "name": "mixed pair sigma", "code": "M5"},
])
time.sleep(1.1)
hydrate("b_fillers", [{"id": f"{TYPE}_a{index:04d}", "code": f"F{index}", **({"name": "Mixed Pair, Sigma"} if index == 0 else {})}
                      for index in range(1000)])

# 1. The scan is ordered, counted and kept on the job; the exact pass reads every object.
job = ok(client.post("/entity-resolution/jobs", json={"object_type_id": TYPE, "fields": ["name"], "threshold": 85, "limit": 1000}), "job past the scan")
coverage = {key: job.get(key) for key in ("objects_in_scope", "objects_scanned", "last_scanned_id", "scan_order", "scan_limit",
                                          "candidate_count", "exact_objects", "exact_values_skipped", "exact_group_ceiling")}
check(job.get("objects_in_scope") == 1005 and job.get("objects_scanned") == 1000, "the job counts the type and what it compared", coverage)
check(job.get("last_scanned_id") == f"{TYPE}_a0999" and job.get("scan_order") == "id", "the job reads in id order", coverage)
check(job.get("exact_objects") == 1005 and job.get("exact_values_skipped") == 0 and job.get("exact_group_ceiling") == 50,
      "the exact pass reads the whole type and skips no value", coverage)
check(pairs_of(job) == [[f"{TYPE}_a0000", f"{TYPE}_z5"], [f"{TYPE}_z1", f"{TYPE}_z2"]],
      "the exact pass pairs past the scan and across its edge, and the near pair past it is not compared", pairs_of(job))
exact = next(candidate for candidate in job["candidates"] if set(candidate["object_ids"]) == {f"{TYPE}_z1", f"{TYPE}_z2"})
check(exact["score"] == 100 and exact["reasons"][0]["field"] == "name", "an exact pair is scored as the scan scores it", exact)
listed = next(item for item in ok(client.get("/entity-resolution/jobs"), "job list") if item["id"] == job["id"])
check({key: listed.get(key) for key in ("objects_in_scope", "objects_scanned", "last_scanned_id", "exact_objects", "exact_values_skipped")}
      == {"objects_in_scope": 1005, "objects_scanned": 1000, "last_scanned_id": f"{TYPE}_a0999", "exact_objects": 1005, "exact_values_skipped": 0},
      "a reloaded job list keeps the coverage", listed)

# 2. Explain says whether an object was compared, and whether the exact pass read it.
far = ok(client.get(f"/decision/objects/{TYPE}/{TYPE}_z1/explain"), "explain an object past the scan")
far_coverage = far.get("duplicate_coverage") or {}
check(far_coverage.get("compared") is False and far_coverage.get("exact_checked") is True, "an object past the scan was checked, not compared", far_coverage)
check(far_coverage.get("objects_scanned") == 1000 and far_coverage.get("exact_objects") == 1005 and far.get("duplicate_warning_count") == 1,
      "Explain states the job's coverage and carries the exact pair's warning", {key: far.get(key) for key in ("duplicate_coverage", "duplicate_warning_count")})
near = ok(client.get(f"/decision/objects/{TYPE}/{TYPE}_a0001/explain"), "explain a scanned object")
check((near.get("duplicate_coverage") or {}).get("compared") is True, "a scanned object was compared", near.get("duplicate_coverage"))

# An object made after the job, with an id inside the scanned range, was neither compared nor checked.
time.sleep(1.1)
ok(client.post("/objects", json={"id": f"{TYPE}_a0500_late", "object_type_id": TYPE, "properties": {"code": "late"}}), "late object")
late = ok(client.get(f"/decision/objects/{TYPE}/{TYPE}_a0500_late/explain"), "explain a later object")
check((late.get("duplicate_coverage") or {}).get("compared") is False and (late.get("duplicate_coverage") or {}).get("exact_checked") is False,
      "an object created after the job was not read", late.get("duplicate_coverage"))

# 3. With room for every object, the same job finds the near pair too.
time.sleep(1.1)
wide = ok(client.post("/entity-resolution/jobs", json={"object_type_id": TYPE, "fields": ["name"], "threshold": 85, "limit": 5000}), "job over the whole type")
check([f"{TYPE}_z3", f"{TYPE}_z4"] in pairs_of(wide) and [f"{TYPE}_z1", f"{TYPE}_z2"] in pairs_of(wide) and wide.get("objects_scanned") == 1006,
      "a scan of every object finds the near pair", {"pairs": pairs_of(wide), "objects_scanned": wide.get("objects_scanned")})
found = ok(client.get(f"/decision/objects/{TYPE}/{TYPE}_z3/explain"), "explain after the wide job")
check((found.get("duplicate_coverage") or {}).get("compared") is True and found.get("duplicate_warning_count") == 1,
      "after a scan that compared it, the near pair carries its warning", {key: found.get(key) for key in ("duplicate_coverage", "duplicate_warning_count")})

# 4. A value more objects share than the ceiling is not paired past the scan, and the job counts it.
CROWD = "er_crowd"
ok(client.post("/object-types", json={"id": CROWD, "display_name": "Crowd", "description": "A shared value", "properties": {"name": {"type": "string"}}}), "crowd type")
for index in range(51):
    ok(client.post("/objects", json={"id": f"{CROWD}_c{index:02d}", "object_type_id": CROWD, "properties": {"name": "Crowded Name"}}), f"crowd {index}")
for twin in ("t1", "t2"):
    ok(client.post("/objects", json={"id": f"{CROWD}_{twin}", "object_type_id": CROWD, "properties": {"name": "Twin Tank"}}), twin)
crowd = ok(client.post("/entity-resolution/jobs", json={"object_type_id": CROWD, "fields": ["name"], "threshold": 85, "limit": 2}), "crowd job")
check(crowd.get("objects_scanned") == 2 and crowd.get("exact_objects") == 53 and crowd.get("exact_values_skipped") == 1,
      "the job counts the value it left unpaired", {key: crowd.get(key) for key in ("objects_scanned", "exact_objects", "exact_values_skipped")})
check(pairs_of(crowd) == [[f"{CROWD}_c00", f"{CROWD}_c01"], [f"{CROWD}_t1", f"{CROWD}_t2"]],
      "the scan's pair and the twins are found, and the crowd is not paired past the scan", pairs_of(crowd))
crowded = ok(client.get(f"/decision/objects/{CROWD}/{CROWD}_c10/explain"), "explain a crowded object")
check((crowded.get("duplicate_coverage") or {}).get("exact_values_skipped") == 1, "Explain says a value was left unpaired", crowded.get("duplicate_coverage"))

# 5. A type no job has run over reports no coverage rather than "clear".
ok(client.post("/object-types", json={"id": "er_untouched", "display_name": "Untouched", "description": "No job", "properties": {"name": {"type": "string"}}}), "untouched type")
ok(client.post("/objects", json={"id": "er_untouched_1", "object_type_id": "er_untouched", "properties": {"name": "Alone"}}), "untouched object")
untouched = ok(client.get("/decision/objects/er_untouched/er_untouched_1/explain"), "explain with no job")
check(untouched.get("duplicate_coverage") is None, "no job means no coverage to claim", untouched.get("duplicate_coverage"))

print(f"\nEntity resolution coverage verified: {passed} assertions passed.")
from app.database import engine as _engine  # noqa: E402
_engine.dispose()
tmpdir.cleanup()

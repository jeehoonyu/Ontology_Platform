"""
An entity-resolution job says how much of its object type it compared.

GOAL_HONEST_UI_2026-09-11, the Decision workspace limits. A job compares every pair
among the objects it reads, and it read at most 1,000 in no stated order, while the
Candidate Review Queue read as the type's whole duplicate list and Explain called an
object the job never read "clear". These hold the fix: the scan is in id order, the job
keeps how many objects the type held, how many it compared and the last id it read,
the job list returns them after a reload, and Explain says whether an object was
compared at all.

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


TYPE = "er_cut"
ok(client.post("/object-types", json={
    "id": TYPE, "display_name": "Entity coverage", "description": "Past the 1,000 a job compares",
    "properties": {"name": {"type": "string"}, "code": {"type": "string"}},
}), "object type")

# The duplicate pair has the highest ids but is hydrated first, from a source asset whose
# id sorts before the fillers'. With no ORDER BY, SQLite reads this scope through
# ix_object_instances_materialized_active (project, type, source asset, active, id), so
# an unordered scan reads the pair first and compares it; only a scan in id order leaves
# it out of the first 1,000. The 1,000 fillers carry no name, so every filler pair scores
# 0 at once and writes no candidate.
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
])
time.sleep(1.1)
hydrate("b_fillers", [{"id": f"{TYPE}_a{index:04d}", "code": f"F{index}"} for index in range(1000)])

# 1. The scan is ordered, counted and kept on the job.
job = ok(client.post("/entity-resolution/jobs", json={"object_type_id": TYPE, "fields": ["name"], "threshold": 85, "limit": 1000}), "job past the scan")
coverage = {key: job.get(key) for key in ("objects_in_scope", "objects_scanned", "last_scanned_id", "scan_order", "scan_limit", "candidate_count")}
check(job.get("objects_in_scope") == 1002 and job.get("objects_scanned") == 1000, "the job counts the type and what it compared", coverage)
check(job.get("last_scanned_id") == f"{TYPE}_a0999" and job.get("scan_order") == "id", "the job reads in id order", coverage)
check(job.get("candidate_count") == 0, "the pair past the scan was not compared", coverage)
listed = next(item for item in ok(client.get("/entity-resolution/jobs"), "job list") if item["id"] == job["id"])
check({key: listed.get(key) for key in ("objects_in_scope", "objects_scanned", "last_scanned_id")} == {"objects_in_scope": 1002, "objects_scanned": 1000, "last_scanned_id": f"{TYPE}_a0999"},
      "a reloaded job list keeps the coverage", listed)

# 2. Explain says whether an object was compared, from the latest completed job.
far = ok(client.get(f"/decision/objects/{TYPE}/{TYPE}_z1/explain"), "explain an object past the scan")
check((far.get("duplicate_coverage") or {}).get("compared") is False, "an object past the scan is not called clear", far.get("duplicate_coverage"))
check((far.get("duplicate_coverage") or {}).get("objects_scanned") == 1000 and far["duplicate_coverage"].get("objects_in_scope") == 1002,
      "Explain states the job's coverage", far.get("duplicate_coverage"))
near = ok(client.get(f"/decision/objects/{TYPE}/{TYPE}_a0001/explain"), "explain a scanned object")
check((near.get("duplicate_coverage") or {}).get("compared") is True, "a scanned object was compared", near.get("duplicate_coverage"))

# An object made after the job, with an id inside the scanned range, was not compared.
time.sleep(1.1)
ok(client.post("/objects", json={"id": f"{TYPE}_a0500_late", "object_type_id": TYPE, "properties": {"code": "late"}}), "late object")
late = ok(client.get(f"/decision/objects/{TYPE}/{TYPE}_a0500_late/explain"), "explain a later object")
check((late.get("duplicate_coverage") or {}).get("compared") is False, "an object created after the job was not compared", late.get("duplicate_coverage"))

# 3. With room for every object, the same job finds the pair, and Explain counts it.
time.sleep(1.1)
wide = ok(client.post("/entity-resolution/jobs", json={"object_type_id": TYPE, "fields": ["name"], "threshold": 85, "limit": 5000}), "job over the whole type")
pairs = [set(candidate["object_ids"]) for candidate in wide["candidates"]]
check({f"{TYPE}_z1", f"{TYPE}_z2"} in pairs and wide.get("objects_scanned") == 1003, "a scan of every object finds the pair",
      {"pairs": [sorted(pair) for pair in pairs][:3], "objects_scanned": wide.get("objects_scanned")})
found = ok(client.get(f"/decision/objects/{TYPE}/{TYPE}_z1/explain"), "explain after the wide job")
check((found.get("duplicate_coverage") or {}).get("compared") is True and found.get("duplicate_warning_count") == 1,
      "after a scan that compared it, the object carries its warning", {key: found.get(key) for key in ("duplicate_coverage", "duplicate_warning_count")})

# 4. A type no job has run over reports no coverage rather than "clear".
ok(client.post("/object-types", json={"id": "er_untouched", "display_name": "Untouched", "description": "No job", "properties": {"name": {"type": "string"}}}), "untouched type")
ok(client.post("/objects", json={"id": "er_untouched_1", "object_type_id": "er_untouched", "properties": {"name": "Alone"}}), "untouched object")
untouched = ok(client.get("/decision/objects/er_untouched/er_untouched_1/explain"), "explain with no job")
check(untouched.get("duplicate_coverage") is None, "no job means no coverage to claim", untouched.get("duplicate_coverage"))

print(f"\nEntity resolution coverage verified: {passed} assertions passed.")
from app.database import engine as _engine  # noqa: E402
_engine.dispose()
tmpdir.cleanup()

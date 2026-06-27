import os, tempfile
_t = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(_t.name, 't.db')}"
from fastapi import FastAPI                         # noqa: E402
from fastapi.testclient import TestClient           # noqa: E402
from app.database import Base, engine, SessionLocal  # noqa: E402
from app import models, models_action              # noqa: E402
from app import fusion_ops as M                      # noqa: E402
import time                                          # noqa: E402

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
# Seed: a DataAsset (employees) + ObjectType/ObjectInstance for write-back
# ---------------------------------------------------------------------------
now = int(time.time())
db = SessionLocal()
db.add(models.DataAsset(
    id="ds_emp", display_name="Employees", description=None, kind="dataset",
    asset_schema={}, records=[
        {"id": 1, "name": "Alice", "dept": "eng", "salary": 120},
        {"id": 2, "name": "Bob", "dept": "eng", "salary": 110},
        {"id": 3, "name": "Cara", "dept": "sales", "salary": 90},
        {"id": 4, "name": "Dan", "dept": "sales", "salary": 90},
    ], created_at=now, updated_at=now))

db.add(models.ObjectType(id="ot_emp", display_name="Employee", description="emps",
                         properties={"salary": {"base_type": "double"},
                                     "band": {"base_type": "string"}},
                         created_at=now, updated_at=now))
db.add_all([
    models.ObjectInstance(id="e1", object_type_id="ot_emp",
                          properties={"salary": 0, "band": "?"},
                          lineage={}, created_at=now, updated_at=now),
    models.ObjectInstance(id="e2", object_type_id="ot_emp",
                          properties={"salary": 0, "band": "?"},
                          lineage={}, created_at=now, updated_at=now),
])
db.commit()
db.close()


# ---------------------------------------------------------------------------
# LOOKUP (first match)
# ---------------------------------------------------------------------------
r = ok(client.post("/fusion/lookup", json={
    "dataset_id": "ds_emp", "key_field": "id", "key_value": 2, "value_field": "name"}),
    "lookup by id")
check(r["found"] is True and r["value"] == "Bob", f"lookup id=2 -> Bob (got {r.get('value')})")

# key coercion: string "1" should match numeric id 1
r = ok(client.post("/fusion/lookup", json={
    "dataset_id": "ds_emp", "key_field": "id", "key_value": "1", "value_field": "name"}),
    "lookup coerced key")
check(r["value"] == "Alice", f"lookup '1' coerces -> Alice (got {r.get('value')})")

# no match -> #N/A, found False
r = ok(client.post("/fusion/lookup", json={
    "dataset_id": "ds_emp", "key_field": "id", "key_value": 999, "value_field": "name"}),
    "lookup miss")
check(r["found"] is False and r["value"] == "#N/A", "lookup miss -> #N/A")

# missing dataset -> 404
ok(client.post("/fusion/lookup", json={
    "dataset_id": "nope", "key_field": "id", "key_value": 1, "value_field": "name"}),
   "lookup missing dataset", expect=404)

# inline table (no dataset)
r = ok(client.post("/fusion/lookup", json={
    "table": [{"k": "x", "v": 7}, {"k": "y", "v": 8}],
    "key_field": "k", "key_value": "y", "value_field": "v"}), "lookup inline table")
check(r["value"] == 8, f"inline table lookup -> 8 (got {r.get('value')})")


# ---------------------------------------------------------------------------
# LOOKUP-ARRAY (all matches)
# ---------------------------------------------------------------------------
r = ok(client.post("/fusion/lookup-array", json={
    "dataset_id": "ds_emp", "key_field": "dept", "key_value": "eng", "value_field": "name"}),
    "lookup-array")
check(r["values"] == ["Alice", "Bob"] and r["count"] == 2,
      f"array eng -> [Alice,Bob] (got {r.get('values')})")


# ---------------------------------------------------------------------------
# LOOKUP-DISTINCT (deduped)
# ---------------------------------------------------------------------------
r = ok(client.post("/fusion/lookup-distinct", json={
    "dataset_id": "ds_emp", "value_field": "dept"}), "lookup-distinct")
check(r["values"] == ["eng", "sales"] and r["count"] == 2,
      f"distinct dept -> [eng,sales] (got {r.get('values')})")

# distinct salary (90 appears twice) -> deduped
r = ok(client.post("/fusion/lookup-distinct", json={
    "dataset_id": "ds_emp", "value_field": "salary"}), "lookup-distinct salary")
check(r["count"] == 3, f"distinct salary count==3 (got {r.get('count')})")


# ---------------------------------------------------------------------------
# LOOKUP-DROPDOWN (distinct choice list, sorted)
# ---------------------------------------------------------------------------
r = ok(client.post("/fusion/lookup-dropdown", json={
    "dataset_id": "ds_emp", "field": "dept"}), "lookup-dropdown")
check(r["choices"] == ["eng", "sales"], f"dropdown sorted choices (got {r.get('choices')})")


# ---------------------------------------------------------------------------
# LOOKUP-SORTED (sorted by field, asc + desc)
# ---------------------------------------------------------------------------
r = ok(client.post("/fusion/lookup-sorted", json={
    "dataset_id": "ds_emp", "value_field": "name", "sort_field": "salary"}),
    "lookup-sorted asc")
# salaries: Alice120,Bob110,Cara90,Dan90 -> asc by salary -> [Cara/Dan(90), Bob(110), Alice(120)]
check(r["values"][-1] == "Alice", f"sorted asc last==Alice (got {r.get('values')})")

r = ok(client.post("/fusion/lookup-sorted", json={
    "dataset_id": "ds_emp", "value_field": "name", "sort_field": "salary", "desc": True}),
    "lookup-sorted desc")
check(r["values"][0] == "Alice", f"sorted desc first==Alice (got {r.get('values')})")


# ---------------------------------------------------------------------------
# LOOKUP-SCHEMA (inferred column names/types)
# ---------------------------------------------------------------------------
r = ok(client.post("/fusion/lookup-schema", json={"dataset_id": "ds_emp"}), "lookup-schema")
check(r["columns"] == ["id", "name", "dept", "salary"], f"schema cols (got {r.get('columns')})")
types = {c["name"]: c["type"] for c in r["schema"]}
check(types["id"] == "integer" and types["name"] == "string" and types["salary"] == "integer",
      f"schema types inferred (got {types})")
check(r["record_count"] == 4, "schema record_count==4")


# ---------------------------------------------------------------------------
# LOOKUP() inside the formula evaluator (sheet eval)
# ---------------------------------------------------------------------------
wb = ok(client.post("/fusion/workbooks", json={"display_name": "WB"}), "wb")
sh = ok(client.post("/fusion/sheets", json={"workbook_id": wb["id"], "name": "S1"}), "sheet")
sid = sh["id"]
ok(client.put(f"/fusion/sheets/{sid}/cells", json={"cells": [
    {"ref": "A1", "raw": "=LOOKUP('ds_emp','salary','name','Alice')"},
    {"ref": "A2", "raw": "=LOOKUP('ds_emp','salary','name','Bob') + 5"},
]}), "set lookup formula cells")
ev = ok(client.post(f"/fusion/sheets/{sid}/evaluate"), "evaluate with LOOKUP()")
check(ev["values"]["A1"] == 120, f"LOOKUP() Alice salary==120 (got {ev['values'].get('A1')})")
check(ev["values"]["A2"] == 115, f"LOOKUP()+5 Bob==115 (got {ev['values'].get('A2')})")


# ---------------------------------------------------------------------------
# WRITE-BACK: stage (commit=false) then commit (commit=true)
# ---------------------------------------------------------------------------
# Seed cells that compute target values for the two employees.
ok(client.put(f"/fusion/sheets/{sid}/cells", json={"cells": [
    {"ref": "C1", "raw": "=LOOKUP('ds_emp','salary','name','Alice')"},  # 120
    {"ref": "D1", "raw": "high"},
    {"ref": "C2", "raw": "=LOOKUP('ds_emp','salary','name','Bob')"},   # 110
    {"ref": "D2", "raw": "mid"},
]}), "set write-back source cells")

stage = ok(client.post(f"/fusion/sheets/{sid}/write-back", json={
    "target_object_type_id": "ot_emp",
    "row_mappings": [
        {"object_id": "e1", "cells": {"salary": "C1", "band": "D1"}},
        {"object_id": "e2", "cells": {"salary": "C2", "band": "D2"}},
    ],
    "commit": False,
}), "write-back stage")
check(stage["committed"] is False, "stage not committed")
check(stage["objects_applied"] == 0, "stage applies nothing")
e1c = next(s for s in stage["staged_changes"] if s["object_id"] == "e1")
check(e1c["changes"]["salary"]["new"] == 120 and e1c["changes"]["salary"]["old"] == 0,
      f"stage shows old/new salary (got {e1c['changes'].get('salary')})")

# Verify nothing was persisted during staging.
verify = SessionLocal()
inst_before = verify.query(models.ObjectInstance).filter_by(id="e1").first()
check(inst_before.properties["salary"] == 0, "staging did not persist")
verify.close()

# Now commit.
commit = ok(client.post(f"/fusion/sheets/{sid}/write-back", json={
    "target_object_type_id": "ot_emp",
    "row_mappings": [
        {"object_id": "e1", "cells": {"salary": "C1", "band": "D1"}},
        {"object_id": "e2", "cells": {"salary": "C2", "band": "D2"}},
    ],
    "commit": True,
}), "write-back commit")
check(commit["committed"] is True and commit["objects_applied"] == 2, "commit applied 2")

verify = SessionLocal()
i1 = verify.query(models.ObjectInstance).filter_by(id="e1").first()
i2 = verify.query(models.ObjectInstance).filter_by(id="e2").first()
check(i1.properties["salary"] == 120 and i1.properties["band"] == "high",
      f"e1 persisted (got {i1.properties})")
check(i2.properties["salary"] == 110 and i2.properties["band"] == "mid",
      f"e2 persisted (got {i2.properties})")
verify.close()

# write-back to missing object type -> 404
ok(client.post(f"/fusion/sheets/{sid}/write-back", json={
    "target_object_type_id": "nope", "row_mappings": []}),
   "write-back missing OT", expect=404)

# write-back referencing a missing object -> staged with found=False, no crash
miss = ok(client.post(f"/fusion/sheets/{sid}/write-back", json={
    "target_object_type_id": "ot_emp",
    "row_mappings": [{"object_id": "ghost", "cells": {"salary": "C1"}}],
    "commit": True,
}), "write-back missing object")
check(miss["staged_changes"][0]["found"] is False, "missing object reported found=False")


print(f"\nFUSION LOOKUP verified: {passed} assertions passed.")
engine.dispose(); _t.cleanup()

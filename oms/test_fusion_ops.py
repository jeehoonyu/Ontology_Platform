import os, tempfile
_tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(_tmp.name, 't.db')}"
from fastapi import FastAPI                       # noqa: E402
from fastapi.testclient import TestClient         # noqa: E402
from app.database import Base, engine, SessionLocal  # noqa: E402
from app import models, models_action            # noqa: E402  (registers core + audit tables)
from app import fusion_ops as M                   # noqa: E402  (registers this module's tables)
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
# Seed core ontology rows directly via a Session (object type + instances)
# ---------------------------------------------------------------------------
now = int(time.time())
db = SessionLocal()
db.add(models.ObjectType(id="ot_order", display_name="Order", description="orders",
                         properties={"amount": {"base_type": "double"},
                                     "status": {"base_type": "string"}},
                         created_at=now, updated_at=now))
db.add_all([
    models.ObjectInstance(id="o1", object_type_id="ot_order",
                          properties={"amount": 100, "status": "open"},
                          lineage={}, created_at=now, updated_at=now),
    models.ObjectInstance(id="o2", object_type_id="ot_order",
                          properties={"amount": 250, "status": "open"},
                          lineage={}, created_at=now, updated_at=now),
    models.ObjectInstance(id="o3", object_type_id="ot_order",
                          properties={"amount": 50, "status": "closed"},
                          lineage={}, created_at=now, updated_at=now),
])
db.commit()
db.close()


# ---------------------------------------------------------------------------
# Workbook / sheet CRUD
# ---------------------------------------------------------------------------
wb = ok(client.post("/fusion/workbooks", json={"display_name": "Q3 Plan", "owner": "alice"}),
        "create workbook")
check(wb["display_name"] == "Q3 Plan", "workbook name persisted")
wbs = ok(client.get("/fusion/workbooks"), "list workbooks")
check(len(wbs) == 1, "one workbook listed")

sh = ok(client.post("/fusion/sheets", json={"workbook_id": wb["id"], "name": "Sheet1"}),
        "create sheet")
sid = sh["id"]
sheets = ok(client.get(f"/fusion/workbooks/{wb['id']}/sheets"), "list sheets")
check(len(sheets) == 1 and sheets[0]["name"] == "Sheet1", "sheet listed")

# sheet under missing workbook -> 404
ok(client.post("/fusion/sheets", json={"workbook_id": "nope", "name": "X"}),
   "sheet missing workbook", expect=404)


# ---------------------------------------------------------------------------
# Scenario: A1=10, A2=20, A3==SUM(A1:A2) -> A3=30
# ---------------------------------------------------------------------------
ok(client.put(f"/fusion/sheets/{sid}/cells", json={"cells": [
    {"ref": "A1", "raw": "10"},
    {"ref": "A2", "raw": "20"},
    {"ref": "A3", "raw": "=SUM(A1:A2)"},
    {"ref": "B1", "raw": '=IF(A3>25,"hi","lo")'},
]}), "bulk set cells")

ev = ok(client.post(f"/fusion/sheets/{sid}/evaluate"), "evaluate sheet")
vals = ev["values"]
check(vals["A3"] == 30, f"SUM(A1:A2)==30 (got {vals.get('A3')})")
check(vals["B1"] == "hi", f"IF >25 -> hi (got {vals.get('B1')})")

# get cells back
got = ok(client.get(f"/fusion/sheets/{sid}"), "get sheet cells")
check(any(c["ref"] == "A3" and c["raw"] == "=SUM(A1:A2)" for c in got["cells"]), "raw persisted")


# ---------------------------------------------------------------------------
# Stateless eval: errors, cycles, nested, concat
# ---------------------------------------------------------------------------
# DIV/0
r = ok(client.post("/fusion/formula/evaluate", json={"cells": {"A1": "=A2/0", "A2": "5"}}),
       "stateless div0")
check(r["values"]["A1"] == "#DIV/0!", f"#DIV/0! (got {r['values'].get('A1')})")

# cycle A1==A2, A2==A1
r = ok(client.post("/fusion/formula/evaluate", json={"cells": {"A1": "=A2", "A2": "=A1"}}),
       "stateless cycle")
check(r["values"]["A1"] == "#CYCLE!", f"#CYCLE! A1 (got {r['values'].get('A1')})")
check(r["values"]["A2"] == "#CYCLE!", f"#CYCLE! A2 (got {r['values'].get('A2')})")

# nested ROUND(AVG(A1:A2),0) = 15  (avg of 10,20 = 15)
r = ok(client.post("/fusion/formula/evaluate", json={"cells": {
    "A1": "10", "A2": "20", "A3": "=ROUND(AVG(A1:A2),0)"}}), "stateless nested round/avg")
check(r["values"]["A3"] == 15, f"ROUND(AVG,0)==15 (got {r['values'].get('A3')})")

# AVERAGE alias
r = ok(client.post("/fusion/formula/evaluate", json={"cells": {
    "A1": "10", "A2": "20", "A3": "30", "A4": "=AVERAGE(A1:A3)"}}), "AVERAGE alias")
check(r["values"]["A4"] == 20, f"AVERAGE==20 (got {r['values'].get('A4')})")

# MIN / MAX / COUNT
r = ok(client.post("/fusion/formula/evaluate", json={"cells": {
    "A1": "10", "A2": "20", "A3": "5",
    "B1": "=MIN(A1:A3)", "B2": "=MAX(A1:A3)", "B3": "=COUNT(A1:A3)"}}), "min max count")
check(r["values"]["B1"] == 5, "MIN==5")
check(r["values"]["B2"] == 20, "MAX==20")
check(r["values"]["B3"] == 3, "COUNT==3")

# ABS, ROUND with digits, arithmetic + parentheses
r = ok(client.post("/fusion/formula/evaluate", json={"cells": {
    "A1": "=ABS(-7)", "A2": "=ROUND(3.14159,2)", "A3": "=(2+3)*4"}}), "abs round arith")
check(r["values"]["A1"] == 7, "ABS(-7)==7")
check(r["values"]["A2"] == 3.14, f"ROUND(3.14159,2)==3.14 (got {r['values'].get('A2')})")
check(r["values"]["A3"] == 20, "(2+3)*4==20")

# CONCAT
r = ok(client.post("/fusion/formula/evaluate", json={"cells": {
    "A1": "foo", "A2": "bar", "A3": "=CONCAT(A1,A2)"}}), "concat")
check(r["values"]["A3"] == "foobar", f"CONCAT==foobar (got {r['values'].get('A3')})")

# CONCAT with single-quote string literal (Fusion uses single quotes)
r = ok(client.post("/fusion/formula/evaluate", json={"cells": {
    "A1": "x", "A2": "=CONCAT(A1,'-y')"}}), "concat single quote")
check(r["values"]["A2"] == "x-y", f"CONCAT single-quote (got {r['values'].get('A2')})")

# AND / OR / NOT
r = ok(client.post("/fusion/formula/evaluate", json={"cells": {
    "A1": "=AND(1>0, 2>1)", "A2": "=OR(1>2, 3>2)", "A3": "=NOT(1>2)"}}), "and or not")
check(r["values"]["A1"] == "TRUE", f"AND -> TRUE (got {r['values'].get('A1')})")
check(r["values"]["A2"] == "TRUE", "OR -> TRUE")
check(r["values"]["A3"] == "TRUE", "NOT(1>2) -> TRUE")

# IFERROR catches DIV/0
r = ok(client.post("/fusion/formula/evaluate", json={"cells": {
    "A1": "=IFERROR(1/0, 99)"}}), "iferror")
check(r["values"]["A1"] == 99, f"IFERROR -> 99 (got {r['values'].get('A1')})")

# #REF! when range can't be referenced / bad ref propagation via #NAME?
r = ok(client.post("/fusion/formula/evaluate", json={"cells": {
    "A1": "=BOGUSFN(1)"}}), "unknown function")
check(r["values"]["A1"] == "#NAME?", f"unknown fn -> #NAME? (got {r['values'].get('A1')})")

# error propagation: A1 is #DIV/0!, A2 references it
r = ok(client.post("/fusion/formula/evaluate", json={"cells": {
    "A1": "=1/0", "A2": "=A1+1"}}), "error propagation")
check(r["values"]["A2"] == "#DIV/0!", f"error propagates (got {r['values'].get('A2')})")


# ---------------------------------------------------------------------------
# Ontology reference: materialize seeded objects into a range, SUM over it
# ---------------------------------------------------------------------------
ref = ok(client.post(f"/fusion/sheets/{sid}/references", json={
    "anchor_ref": "D1",
    "object_type_id": "ot_order",
    "property_columns": ["amount"],
}), "materialize reference")
check(ref["rows_materialized"] == 3, f"3 rows materialized (got {ref['rows_materialized']})")

# Now D1,D2,D3 = 100,250,50 ; add a SUM in F1 and re-evaluate the sheet.
ok(client.put(f"/fusion/sheets/{sid}/cells", json={"cells": [
    {"ref": "F1", "raw": "=SUM(D1:D3)"}]}), "set sum over reference range")
ev = ok(client.post(f"/fusion/sheets/{sid}/evaluate"), "evaluate after reference")
check(ev["values"]["D1"] == 100, f"D1==100 (got {ev['values'].get('D1')})")
check(ev["values"]["D2"] == 250, "D2==250")
check(ev["values"]["D3"] == 50, "D3==50")
check(ev["values"]["F1"] == 400, f"SUM over materialized range == 400 (got {ev['values'].get('F1')})")

# filtered reference: only status==open (o1,o2) -> 2 rows
ref2 = ok(client.post(f"/fusion/sheets/{sid}/references", json={
    "anchor_ref": "H1",
    "object_type_id": "ot_order",
    "property_columns": ["amount", "status"],
    "filters": {"status": "open"},
}), "materialize filtered reference")
check(ref2["rows_materialized"] == 2, f"filtered -> 2 rows (got {ref2['rows_materialized']})")

refs = ok(client.get(f"/fusion/sheets/{sid}/references"), "list references")
check(len(refs) == 2, f"two references listed (got {len(refs)})")

# reference to missing object type -> 404
ok(client.post(f"/fusion/sheets/{sid}/references", json={
    "anchor_ref": "Z1", "object_type_id": "nope", "property_columns": ["amount"]}),
   "reference missing OT", expect=404)

# reference with empty property_columns -> 422
ok(client.post(f"/fusion/sheets/{sid}/references", json={
    "anchor_ref": "Z1", "object_type_id": "ot_order", "property_columns": []}),
   "reference empty cols", expect=422)


# ---------------------------------------------------------------------------
# A1 helper sanity (col<->index round trip via materialized far column)
# ---------------------------------------------------------------------------
check(M.index_to_col(M.col_to_index("AA")) == "AA", "col round trip AA")
check(M.col_to_index("A") == 0 and M.col_to_index("Z") == 25, "col index A/Z")
check(M.normalize_ref("a1") == "A1", "normalize lowercased ref")

# evaluate sheet on a missing sheet -> 404
ok(client.post("/fusion/sheets/nope/evaluate"), "evaluate missing sheet", expect=404)


print(f"\nFUSION verified: {passed} assertions passed.")
engine.dispose(); _tmp.cleanup()

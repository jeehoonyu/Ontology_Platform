"""
Validation pass — Tier-0 correctness fixes (Wave 1, main-loop implemented).
Covers: OSDK duplicate-id bug, Object Explorer 404 + chart aggregations,
admin usage organization-scoped quota, observability monitoring-view real evaluator.
Run: ./venv312/Scripts/python.exe test_validation_fixes.py
"""
import os
import tempfile

_tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(_tmp.name, 'vfix.db')}"

from fastapi.testclient import TestClient  # noqa: E402
from app.main import app  # noqa: E402
from app.database import SessionLocal, engine  # noqa: E402
from app import models  # noqa: E402

client = TestClient(app)
passed = 0


def ok(resp, label, expect=200):
    global passed
    success = resp.status_code == expect or (expect == 200 and 200 <= resp.status_code < 300)
    assert success, f"{label}: expected {expect}, got {resp.status_code} -> {resp.text[:400]}"
    passed += 1
    return resp.json() if resp.content else {}


# ============ FIX #1 — OSDK must not emit a duplicate `id` field ============
# Object type that ALREADY declares an `id` property.
ok(client.post("/object-types", json={"id": "acct", "display_name": "Account", "description": "",
    "properties": {"id": {"type": "string"}, "name": {"type": "string"}, "balance": {"type": "number"}}}), "acct type")
# Object type WITHOUT an id property (should get a synthetic one).
ok(client.post("/object-types", json={"id": "note", "display_name": "Note", "description": "",
    "properties": {"body": {"type": "string"}}}), "note type")

gen = ok(client.post("/osdk/generate", json={"object_type_ids": ["acct"]}), "osdk acct")
acct_sdk = gen["sdk"][0]
ts, py = acct_sdk["typescript_interface"], acct_sdk["python_dataclass"]
# exactly one id line in each — the bug emitted two
assert sum(1 for ln in ts.splitlines() if ln.strip().startswith("id:")) == 1, ts
assert sum(1 for ln in py.splitlines() if ln.strip().startswith("id:")) == 1, py
passed += 2

gen2 = ok(client.post("/osdk/generate", json={"object_type_ids": ["note"]}), "osdk note")
note_ts = gen2["sdk"][0]["typescript_interface"]
# note has no id property -> synthetic id present exactly once
assert sum(1 for ln in note_ts.splitlines() if ln.strip().startswith("id:")) == 1, note_ts
assert "body:" in note_ts, note_ts
passed += 2


# ============ FIX #2 — Object Explorer 404 + chart aggregations ============
ok(client.post("/object-types", json={"id": "tx", "display_name": "Tx", "description": "",
    "properties": {"amount": {"type": "number"}, "kind": {"type": "string"}, "region": {"type": "string"}}}), "tx type")
seed = [(10, "food", "EMEA"), (20, "food", "APAC"), (30, "toys", "EMEA"), (40, "toys", "APAC"), (50, "food", "EMEA")]
for i, (amt, kind, region) in enumerate(seed):
    ok(client.post("/objects", json={"id": f"t{i}", "object_type_id": "tx",
        "properties": {"amount": amt, "kind": kind, "region": region}}), f"tx {i}")

# bad object type now 404 (was 200 + empty)
r = client.post("/object-explorer/histogram", json={"object_type_id": "ghost", "field": "amount"})
assert r.status_code == 404, f"bad-type histogram: expected 404 got {r.status_code}"
passed += 1
r = client.post("/object-explorer/property-stats", json={"object_type_id": "ghost", "field": "amount"})
assert r.status_code == 404, f"bad-type property-stats: expected 404 got {r.status_code}"
passed += 1

# listogram keep/exclude
lg = ok(client.post("/object-explorer/listogram", json={"object_type_id": "tx", "field": "kind"}), "listogram")
assert {c["value"]: c["count"] for c in lg["categories"]} == {"food": 3, "toys": 2}, lg
lg_keep = ok(client.post("/object-explorer/listogram", json={"object_type_id": "tx", "field": "kind", "keep": ["toys"]}), "listogram keep")
assert {c["value"] for c in lg_keep["categories"]} == {"toys"}, lg_keep
lg_excl = ok(client.post("/object-explorer/listogram", json={"object_type_id": "tx", "field": "kind", "exclude": ["food"]}), "listogram exclude")
assert {c["value"] for c in lg_excl["categories"]} == {"toys"}, lg_excl

# statistics-table
st = ok(client.post("/object-explorer/statistics-table", json={"object_type_id": "tx", "fields": ["amount"]}), "stats table")
amt_row = next(r for r in st["rows"] if r["field"] == "amount")
assert amt_row["count"] == 5 and amt_row["min"] == 10 and amt_row["max"] == 50 and amt_row["sum"] == 150, amt_row

# single-statistic
ss = ok(client.post("/object-explorer/single-statistic", json={"object_type_id": "tx", "field": "amount", "statistic": "avg"}), "single stat")
assert ss["value"] == 30.0, ss

# grid-plot (kind x region)
gp = ok(client.post("/object-explorer/grid-plot", json={"object_type_id": "tx", "row_field": "kind", "col_field": "region"}), "grid plot")
cells = {(c["row"], c["col"]): c["count"] for c in gp["cells"]}
assert cells[("food", "EMEA")] == 2 and cells[("toys", "APAC")] == 1, cells


# ============ FIX #3 — admin usage organization-scoped quota ============
for v in (60.0, 50.0):
    ok(client.post("/admin/usage/record", json={"principal": "u1", "project": "p1", "organization": "orgA",
        "metric": "compute_seconds", "value": v}), "org usage")
# different org should NOT count toward orgA
ok(client.post("/admin/usage/record", json={"principal": "u2", "project": "p2", "organization": "orgB",
    "metric": "compute_seconds", "value": 500.0}), "orgB usage")
ok(client.post("/admin/usage/quotas", json={"scope_type": "organization", "scope_id": "orgA",
    "metric": "compute_seconds", "limit_value": 100.0}), "org quota")
qo = ok(client.post("/admin/usage/check-quota", json={"scope_type": "organization", "scope_id": "orgA",
    "metric": "compute_seconds"}), "org quota check")
assert qo["usage"] == 110.0 and qo["within_limit"] is False, qo  # 60+50 only; orgB excluded
summ = ok(client.get("/admin/usage/summary", params={"metric": "compute_seconds", "group_by": "organization"}), "org summary")
org_tot = {b["key"]: b["value"] for b in summ["breakdown"]}
assert org_tot["orgA"] == 110.0 and org_tot["orgB"] == 500.0, org_tot


# ============ FIX #4 — observability monitoring view real evaluator ============
ok(client.post("/data-assets", json={"id": "ds1", "display_name": "DS1", "description": "",
    "kind": "dataset", "asset_schema": {"a": "string"}, "records": [{"a": 1}, {"a": 2}]}), "ds1")
# make ds1 stale by backdating updated_at directly
db = SessionLocal()
ds = db.query(models.DataAsset).filter(models.DataAsset.id == "ds1").first()
ds.updated_at = 1
db.commit()
db.close()

view = ok(client.post("/observability/monitoring-views", json={"display_name": "MV", "scope": {},
    "checks": [
        {"type": "freshness", "dataset_id": "ds1", "max_age_seconds": 3600},   # stale (backdated)
        {"type": "row_count", "dataset_id": "ds1", "min": 100},                # failed (only 2 rows)
        {"type": "always_ok"},                                                  # ok
    ]}), "create view")
ev = ok(client.post(f"/observability/monitoring-views/{view['id']}/evaluate"), "evaluate view")
by_type = {r["type"]: r["status"] for r in ev["results"]}
assert by_type["freshness"] == "stale", by_type
assert by_type["row_count"] == "failed", by_type
assert by_type["always_ok"] == "ok", by_type
assert ev["overall"] == "failed", ev  # worst-of
# a healthy freshness check returns ok (proves it's not always-stale)
view2 = ok(client.post("/observability/monitoring-views", json={"display_name": "MV2", "scope": {},
    "checks": [{"type": "freshness", "dataset_id": "ds1", "max_age_seconds": 10 ** 12}]}), "create view2")
ev2 = ok(client.post(f"/observability/monitoring-views/{view2['id']}/evaluate"), "evaluate view2")
assert ev2["overall"] == "ok", ev2

# ============ Object primary-key uniqueness (enforced from the profile PK) ============
ok(client.post("/object-types", json={"id": "emp", "display_name": "Employee", "description": "",
    "properties": {"badge": {"type": "string"}, "name": {"type": "string"}}}), "emp type")
ok(client.put("/ontology/object-types/emp/profile", json={
    "api_name": "Employee", "primary_key": "badge",
    "properties": {"badge": {"base_type": "string"}, "name": {"base_type": "string"}}}), "emp profile pk=badge")
ok(client.post("/objects", json={"id": "e1", "object_type_id": "emp",
    "properties": {"badge": "B100", "name": "Ann"}}), "emp e1")
# duplicate primary-key value -> 409 (enforced because the profile declares badge as PK)
rdup = client.post("/objects", json={"id": "e2", "object_type_id": "emp",
    "properties": {"badge": "B100", "name": "Bob"}})
assert rdup.status_code == 409, f"dup PK: expected 409 got {rdup.status_code} -> {rdup.text[:200]}"
passed += 1
# distinct primary-key value -> allowed
ok(client.post("/objects", json={"id": "e3", "object_type_id": "emp",
    "properties": {"badge": "B200", "name": "Cy"}}), "emp e3 distinct pk")
# object types WITHOUT a profile PK are unaffected (backward compatible)
ok(client.post("/object-types", json={"id": "freeform", "display_name": "Free", "description": "",
    "properties": {"k": {"type": "string"}}}), "freeform type")
ok(client.post("/objects", json={"id": "f1", "object_type_id": "freeform", "properties": {"k": "x"}}), "freeform f1")
ok(client.post("/objects", json={"id": "f2", "object_type_id": "freeform", "properties": {"k": "x"}}), "freeform f2 (no PK -> allowed)")

print(f"\nValidation Tier-0 fixes verified: {passed} assertions passed.")
engine.dispose()
_tmp.cleanup()

"""
CBAC / Classification-Based Access Control — conformance test.
Hierarchical clearance, disjunctive-OR category groups, strictest-upstream-union derivation.
Run: ./venv312/Scripts/python.exe test_classification_ops.py
"""
import os
import tempfile

_tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(_tmp.name, 'cls.db')}"

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from app.database import Base, engine  # noqa: E402
from app import models, models_action  # noqa: E402
from app import classification_ops as M  # noqa: E402

Base.metadata.create_all(bind=engine)
api = FastAPI()
api.include_router(M.router)
client = TestClient(api)
passed = 0


def ok(resp, label, expect=200):
    global passed
    success = resp.status_code == expect or (expect == 200 and 200 <= resp.status_code < 300)
    assert success, f"{label}: expected {expect}, got {resp.status_code} -> {resp.text[:400]}"
    passed += 1
    return resp.json() if resp.content else {}


# Scheme: 4 hierarchical levels + two disjunctive category groups.
ok(client.post("/classification/schemes", json={
    "id": "us", "display_name": "US Gov",
    "levels": ["unclassified", "confidential", "secret", "top_secret"],
    "category_groups": [["NOFORN", "FVEY"], ["NUCLEAR", "CYBER"]],
}), "scheme")
ok(client.post("/classification/schemes", json={"display_name": "bad", "levels": []}), "empty levels", expect=422)

# A Secret dataset requiring FVEY (group1) and CYBER (group2).
ok(client.post("/classification/classifications", json={
    "id": "ds_secret", "scheme_id": "us", "kind": "data", "level": "secret",
    "categories": ["FVEY", "CYBER"]}), "secret data")
# A Top-Secret dataset, no categories.
ok(client.post("/classification/classifications", json={
    "id": "ds_ts", "scheme_id": "us", "kind": "data", "level": "top_secret", "categories": []}), "ts data")
# invalid level rejected
ok(client.post("/classification/classifications", json={
    "scheme_id": "us", "kind": "data", "level": "cosmic", "categories": []}), "bad level", expect=422)

# Clearances.
ok(client.post("/classification/clearances", json={
    "principal_id": "alice", "scheme_id": "us", "max_level": "secret",
    "categories": ["FVEY", "CYBER"]}), "alice clearance")
ok(client.post("/classification/clearances", json={
    "principal_id": "bob", "scheme_id": "us", "max_level": "confidential",
    "categories": ["FVEY", "CYBER"]}), "bob clearance")
ok(client.post("/classification/clearances", json={
    "principal_id": "carol", "scheme_id": "us", "max_level": "top_secret",
    "categories": ["NOFORN"]}), "carol clearance")  # holds NOFORN (group1) but NOT group2

# --- HIERARCHICAL level checks ---
# alice (secret + right categories) -> secret data ALLOWED
a = ok(client.post("/classification/check-access", json={"principal_id": "alice", "classification_id": "ds_secret"}), "alice->secret")
assert a["allowed"] is True, a
# alice (secret clearance) -> top_secret data DENIED (insufficient level)
a2 = ok(client.post("/classification/check-access", json={"principal_id": "alice", "classification_id": "ds_ts"}), "alice->ts")
assert a2["allowed"] is False and a2["level_ok"] is False, a2
# carol (top_secret) -> top_secret data ALLOWED (no categories required)
c = ok(client.post("/classification/check-access", json={"principal_id": "carol", "classification_id": "ds_ts"}), "carol->ts")
assert c["allowed"] is True, c
# bob (confidential) -> secret data DENIED (level too low) even though he has the categories
b = ok(client.post("/classification/check-access", json={"principal_id": "bob", "classification_id": "ds_secret"}), "bob->secret")
assert b["allowed"] is False and b["level_ok"] is False, b

# --- DISJUNCTIVE-OR category groups ---
# carol has the level (top_secret>=secret) but holds NOFORN only -> group2 (NUCLEAR/CYBER) unmet
cc = ok(client.post("/classification/check-access", json={"principal_id": "carol", "classification_id": "ds_secret"}), "carol->secret")
assert cc["allowed"] is False and cc["level_ok"] is True and cc["category_failures"], cc

# OR within a group: a dataset requiring FVEY; a principal holding NOFORN (same group) should NOT pass
# (must hold one of the REQUIRED categories), but holding FVEY should.
ok(client.post("/classification/classifications", json={
    "id": "ds_fvey", "scheme_id": "us", "kind": "data", "level": "confidential", "categories": ["FVEY"]}), "fvey data")
ok(client.post("/classification/clearances", json={
    "principal_id": "dave", "scheme_id": "us", "max_level": "secret", "categories": ["NOFORN"]}), "dave clearance")
d = ok(client.post("/classification/check-access", json={"principal_id": "dave", "classification_id": "ds_fvey"}), "dave->fvey")
assert d["allowed"] is False, d  # holds NOFORN (same group) but not the required FVEY
ok(client.post("/classification/clearances", json={
    "principal_id": "erin", "scheme_id": "us", "max_level": "secret", "categories": ["FVEY"]}), "erin clearance")
e = ok(client.post("/classification/check-access", json={"principal_id": "erin", "classification_id": "ds_fvey"}), "erin->fvey")
assert e["allowed"] is True, e

# no clearance in scheme -> denied
nc = ok(client.post("/classification/check-access", json={"principal_id": "nobody", "classification_id": "ds_fvey"}), "nobody")
assert nc["allowed"] is False and nc["reason"] == "no clearance in scheme", nc

# --- STRICTEST UNION derivation ---
derived = ok(client.post("/classification/compute-data", json={
    "scheme_id": "us", "upstream_classification_ids": ["ds_secret", "ds_ts", "ds_fvey"], "persist": True}), "derive")
assert derived["level"] == "top_secret", derived          # max level wins
assert set(derived["categories"]) == {"FVEY", "CYBER"}, derived  # union of all categories
assert derived["derived"] is True, derived
# empty upstream list rejected
ok(client.post("/classification/compute-data", json={"scheme_id": "us", "upstream_classification_ids": []}), "empty derive", expect=422)

print(f"\nCBAC / Classification verified: {passed} assertions passed.")
engine.dispose()
_tmp.cleanup()

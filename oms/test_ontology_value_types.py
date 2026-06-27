"""
Standalone self-test for app.ontology_value_types.
Builds a local FastAPI app from ONLY the owned router (does NOT import app.main).
Run from oms/:  ./venv312/Scripts/python.exe test_ontology_value_types.py
"""
import os, tempfile

_t = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(_t.name, 't.db')}"

from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.database import Base, engine, SessionLocal
from app import models, models_action
from app import ontology_value_types as M

Base.metadata.create_all(bind=engine)
api = FastAPI()
api.include_router(M.router)
client = TestClient(api)

passed = 0


def check(cond, label):
    global passed
    if cond:
        passed += 1
        print(f"  PASS: {label}")
    else:
        print(f"  FAIL: {label}")
        raise AssertionError(label)


# -------------------------------------------------------------------------
# 1. Widened base types: create string + decimal + array + struct value types
# -------------------------------------------------------------------------
r = client.post("/value-types", json={
    "id": "vt_email", "display_name": "Email", "base_type": "string",
    "constraints": {"regex": r"[^@]+@[^@]+\.[^@]+", "length": 50},
})
check(r.status_code == 201, "create string value type -> 201")

r = client.post("/value-types", json={
    "id": "vt_dec", "display_name": "Score", "base_type": "decimal",
    "constraints": {"min": 0, "max": 100},
})
check(r.status_code == 201, "create decimal (widened) base type -> 201")

r = client.post("/value-types", json={
    "id": "vt_long", "display_name": "BigId", "base_type": "long",
    "constraints": {"min": 1},
})
check(r.status_code == 201, "create long (widened) base type -> 201")

r = client.post("/value-types", json={
    "id": "vt_arr", "display_name": "Tags", "base_type": "array",
    "constraints": {"array_uniqueness": True, "length": 3,
                    "nested": {"base_type": "string", "regex": r"[a-z]+"}},
})
check(r.status_code == 201, "create array value type with nested+uniqueness -> 201")

r = client.post("/value-types", json={
    "id": "vt_rid", "display_name": "RidField", "base_type": "string",
    "constraints": {"rid": True},
})
check(r.status_code == 201, "create string value type with rid constraint -> 201")

r = client.post("/value-types", json={
    "id": "vt_uuid", "display_name": "UuidField", "base_type": "string",
    "constraints": {"uuid": True},
})
check(r.status_code == 201, "create string value type with uuid constraint -> 201")

r = client.post("/value-types", json={
    "id": "vt_struct", "display_name": "Person", "base_type": "struct",
    "struct_fields": [{"name": "age", "base_type": "integer"},
                      {"name": "code", "base_type": "string"}],
    "constraints": {"struct_element": {"age": {"min": 0, "max": 130},
                                        "code": {"regex": r"[A-Z]{3}"}}},
})
check(r.status_code == 201, "create struct value type with struct_element constraints -> 201")

# invalid base type still rejected
r = client.post("/value-types", json={"display_name": "X", "base_type": "blob"})
check(r.status_code == 422, "invalid base_type rejected -> 422")


# -------------------------------------------------------------------------
# 2. Constraint family validation on apply
# -------------------------------------------------------------------------
r = client.post("/value-types/vt_email/validate", json={"value": "a@b.com"})
check(r.status_code == 200 and r.json()["valid"] is True, "valid email passes regex")

r = client.post("/value-types/vt_email/validate", json={"value": "not-an-email"})
check(r.json()["valid"] is False, "bad email fails regex")

r = client.post("/value-types/vt_rid/validate",
                json={"value": "ri.ontology.main.object-type.abc"})
check(r.json()["valid"] is True, "valid RID passes rid constraint")

r = client.post("/value-types/vt_rid/validate", json={"value": "not-a-rid"})
check(r.json()["valid"] is False, "bad RID fails rid constraint")

r = client.post("/value-types/vt_uuid/validate",
                json={"value": "12345678-1234-1234-1234-123456789abc"})
check(r.json()["valid"] is True, "valid UUID passes uuid constraint")

r = client.post("/value-types/vt_uuid/validate", json={"value": "xyz"})
check(r.json()["valid"] is False, "bad UUID fails uuid constraint")

# array uniqueness + nested element regex
r = client.post("/value-types/vt_arr/validate", json={"value": ["aa", "bb"]})
check(r.json()["valid"] is True, "unique lowercase array passes")

r = client.post("/value-types/vt_arr/validate", json={"value": ["aa", "aa"]})
check(r.json()["valid"] is False, "duplicate array fails array_uniqueness")

r = client.post("/value-types/vt_arr/validate", json={"value": ["aa", "B9"]})
check(r.json()["valid"] is False, "array element failing nested regex fails")

# struct element constraints
r = client.post("/value-types/vt_struct/validate",
                json={"value": {"age": 30, "code": "ABC"}})
check(r.json()["valid"] is True, "valid struct passes struct_element constraints")

r = client.post("/value-types/vt_struct/validate",
                json={"value": {"age": 200, "code": "ABC"}})
check(r.json()["valid"] is False, "struct field violating range fails")

r = client.post("/value-types/vt_struct/validate",
                json={"value": {"age": 30, "code": "abc"}})
check(r.json()["valid"] is False, "struct field violating regex fails")


# -------------------------------------------------------------------------
# 3. Seed a consumer object type referencing vt_dec
# -------------------------------------------------------------------------
db = SessionLocal()
db.add(models.ObjectType(
    id="ot_emp", display_name="Employee",
    description="emp",
    properties={"score": {"base_type": "decimal", "value_type": "vt_dec"}},
    created_at=int(__import__("time").time()),
    updated_at=int(__import__("time").time()),
))
db.commit()
db.close()


# -------------------------------------------------------------------------
# 4. Versioning: breaking (tightening max) and non-breaking (loosening)
# -------------------------------------------------------------------------
# tighten max from 100 -> 50 = BREAKING; consumer ot_emp affected
r = client.post("/value-types/vt_dec/versions", json={"constraints": {"min": 0, "max": 50}})
check(r.status_code == 201, "create new version -> 201")
body = r.json()
check(body["version"] == 2, "new version number is 2")
check(body["change_type"] == "BREAKING", "tightening max is BREAKING")
check("ot_emp" in body["affected_consumers"], "consumer ot_emp listed as affected")

# loosen max from 50 -> 200 = NON_BREAKING
r = client.post("/value-types/vt_dec/versions", json={"constraints": {"min": 0, "max": 200}})
check(r.status_code == 201, "create v3 -> 201")
check(r.json()["change_type"] == "NON_BREAKING", "loosening max is NON_BREAKING")
check(r.json()["version"] == 3, "version is 3")

# changing base_type = BREAKING
r = client.post("/value-types/vt_dec/versions", json={"base_type": "integer", "constraints": {"min": 0, "max": 200}})
check(r.json()["change_type"] == "BREAKING", "base_type change is BREAKING")

# list versions
r = client.get("/value-types/vt_dec/versions")
check(r.status_code == 200 and len(r.json()) == 4, "list versions returns all 4 (v1..v4)")
check(r.json()[0]["version"] == 4, "versions listed newest-first")

# adding a constraint = BREAKING (compare v1 -> v2 via diff)
r = client.post("/value-types/vt_dec/version-diff", json={"from_version": 1, "to_version": 2})
check(r.status_code == 200, "version-diff -> 200")
d = r.json()
check(d["breaking"] is True and d["change_type"] == "BREAKING", "diff v1->v2 breaking")
check("max" in d["tightened_constraints"], "diff reports tightened max")

# diff v2 -> v3 is non-breaking (loosened)
r = client.post("/value-types/vt_dec/version-diff", json={"from_version": 2, "to_version": 3})
check(r.json()["breaking"] is False, "diff v2->v3 non-breaking")
check("max" in r.json()["loosened_constraints"], "diff reports loosened max")

# diff to a missing version 404s
r = client.post("/value-types/vt_dec/version-diff", json={"from_version": 1, "to_version": 99})
check(r.status_code == 404, "diff missing version -> 404")

# versions for unknown value type 404
r = client.get("/value-types/nope/versions")
check(r.status_code == 404, "versions for unknown value type -> 404")


# -------------------------------------------------------------------------
# 5. Preserved existing endpoints still behave
# -------------------------------------------------------------------------
r = client.get("/value-types")
check(r.status_code == 200 and len(r.json()) >= 7, "list value types preserved")

r = client.get("/value-types/vt_email")
check(r.status_code == 200 and r.json()["id"] == "vt_email", "get single value type preserved")

r = client.get("/value-types/missing")
check(r.status_code == 404, "get missing value type -> 404 preserved")


print(f"\n{passed} assertions passed")
assert passed >= 12, f"expected >= 12 assertions, got {passed}"
print("ALL GOOD")

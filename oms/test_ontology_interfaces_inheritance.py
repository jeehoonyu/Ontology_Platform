"""
Standalone self-test for shared-property-type INHERITANCE in
app.ontology_interfaces. Does NOT import app.main (siblings edit other files
concurrently); builds a local FastAPI app from only the owned router.

Run from oms/:
    ./venv312/Scripts/python.exe test_ontology_interfaces_inheritance.py
"""

import os
import tempfile
import time
import uuid

_t = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(_t.name, 't.db')}"

from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.database import Base, engine, SessionLocal
from app import models, models_action  # noqa: F401  (ensure tables registered)
from app import ontology_interfaces as M

Base.metadata.create_all(bind=engine)
api = FastAPI()
api.include_router(M.router)
client = TestClient(api)

passed = 0


def check(cond, msg):
    global passed
    if not cond:
        raise AssertionError("FAILED: " + msg)
    passed += 1
    print(f"  ok: {msg}")


# --- Seed a core ObjectType directly (no main.py routes available) ----------
def seed_object_type(ot_id, props):
    db = SessionLocal()
    try:
        now = int(time.time())
        ot = models.ObjectType(
            id=ot_id,
            display_name=ot_id,
            description="seed",
            properties=props,
            created_at=now,
            updated_at=now,
        )
        db.add(ot)
        db.commit()
    finally:
        db.close()


def get_object_type(ot_id):
    db = SessionLocal()
    try:
        ot = db.query(models.ObjectType).filter(models.ObjectType.id == ot_id).first()
        return dict(ot.properties or {}) if ot else None
    finally:
        db.close()


print("== shared property type inheritance ==")

seed_object_type("ot_building", {"address": {"base_type": "string"}})

# Create a shared property type
r = client.post("/shared-property-types", json={
    "id": "spt_email",
    "display_name": "Email Address",
    "base_type": "string",
    "description": "RFC5322 email",
    "constraints": {"format": "email"},
})
check(r.status_code == 200, "create shared property type returns 200")
check(r.json()["id"] == "spt_email", "spt id echoed")

# --- Existing endpoint preserved: list ---
r = client.get("/shared-property-types")
check(r.status_code == 200 and any(s["id"] == "spt_email" for s in r.json()),
      "existing list endpoint still works")

# --- consumers empty before any apply ---
r = client.get("/shared-property-types/spt_email/consumers")
check(r.status_code == 200 and r.json() == [], "consumers empty before apply")

# --- APPLY ---
r = client.post("/shared-property-types/spt_email/apply", json={
    "object_type_id": "ot_building",
    "property_name": "contact_email",
})
check(r.status_code == 200, "apply returns 200")
body = r.json()
check(body["locked"] is True, "application locked=true")
check(body["inherited_metadata"]["base_type"] == "string", "inherited base_type")
check(body["inherited_metadata"]["display_name"] == "Email Address",
      "inherited display_name")

# Verify metadata propagated + LOCKED into the ObjectType.properties
props = get_object_type("ot_building")
check("contact_email" in props, "property written into object type")
prop = props["contact_email"]
check(prop["base_type"] == "string", "propagated base_type into object type")
check(prop["display_name"] == "Email Address", "propagated display_name")
check(prop["description"] == "RFC5322 email", "propagated description")
check(prop["locked"] is True, "property metadata is locked")
check(prop["shared_property_type_id"] == "spt_email", "property links back to spt")
# pre-existing property untouched
check(props["address"] == {"base_type": "string"}, "unrelated property untouched")

# --- CONSUMERS now lists the application ---
r = client.get("/shared-property-types/spt_email/consumers")
check(r.status_code == 200 and len(r.json()) == 1, "consumers lists one application")
check(r.json()[0]["object_type_id"] == "ot_building"
      and r.json()[0]["property_name"] == "contact_email",
      "consumer entry has object type + property")

# --- Conflict: applying a different SPT to a locked property is rejected ---
client.post("/shared-property-types", json={
    "id": "spt_other", "display_name": "Other", "base_type": "integer",
})
r = client.post("/shared-property-types/spt_other/apply", json={
    "object_type_id": "ot_building",
    "property_name": "contact_email",
})
check(r.status_code == 409, "applying second SPT to locked property -> 409")

# --- Re-apply same SPT is idempotent (still one consumer) ---
r = client.post("/shared-property-types/spt_email/apply", json={
    "object_type_id": "ot_building",
    "property_name": "contact_email",
})
check(r.status_code == 200, "re-apply same SPT returns 200")
r = client.get("/shared-property-types/spt_email/consumers")
check(len(r.json()) == 1, "re-apply does not duplicate consumer")

# --- 404 paths ---
r = client.post("/shared-property-types/nope/apply", json={
    "object_type_id": "ot_building", "property_name": "x"})
check(r.status_code == 404, "apply unknown spt -> 404")
r = client.post("/shared-property-types/spt_email/apply", json={
    "object_type_id": "nope_ot", "property_name": "x"})
check(r.status_code == 404, "apply unknown object type -> 404")

# --- DETACH ---
r = client.post("/shared-property-types/spt_email/detach", json={
    "object_type_id": "ot_building",
    "property_name": "contact_email",
})
check(r.status_code == 200 and r.json()["detached"] is True, "detach returns 200")

props = get_object_type("ot_building")
check(props["contact_email"]["locked"] is False, "property unlocked after detach")
check("shared_property_type_id" not in props["contact_email"],
      "shared linkage removed after detach")
# metadata is retained (not lost)
check(props["contact_email"]["base_type"] == "string",
      "materialized metadata retained after detach")

r = client.get("/shared-property-types/spt_email/consumers")
check(r.json() == [], "consumers empty after detach")

# --- detach when no application -> 404 ---
r = client.post("/shared-property-types/spt_email/detach", json={
    "object_type_id": "ot_building", "property_name": "contact_email"})
check(r.status_code == 404, "detach with no application -> 404")

# --- Existing interface endpoints still function (regression) ---
r = client.post("/interfaces", json={
    "id": "if_geo", "display_name": "Geo",
    "properties": {"lat": {"base_type": "double"}},
})
check(r.status_code == 200, "existing create interface endpoint preserved")
r = client.get("/interfaces/if_geo")
check(r.status_code == 200 and r.json()["id"] == "if_geo",
      "existing get interface endpoint preserved")

print(f"\n{passed} assertions passed")
assert passed >= 12, f"expected >= 12 assertions, got {passed}"

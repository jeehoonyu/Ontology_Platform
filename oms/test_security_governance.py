"""Standalone self-test for the owned security governance files:
    app.security_data           (marking categories + granular permissions)
    app.security_propagation    (resource-marking assign/strip enforcement)

Builds a local FastAPI app from ONLY the owned routers (does NOT import
app.main) so it runs concurrently with siblings editing other modules.

Run from oms/:
    ./venv312/Scripts/python.exe test_security_governance.py
"""

import os
import tempfile

_t = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(_t.name, 't.db')}"

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.database import Base, engine, SessionLocal
from app import models, models_action
from app import security_data as SD
from app import security_propagation as SP

Base.metadata.create_all(bind=engine)

api = FastAPI()
api.include_router(SD.router)
api.include_router(SP.router)
client = TestClient(api)

passed = 0


def check(cond, label):
    global passed
    assert cond, f"FAILED: {label}"
    passed += 1
    print(f"  ok: {label}")


def audit_count(event_type, subject_id=None):
    db = SessionLocal()
    try:
        q = db.query(models_action.AuditLog).filter(
            models_action.AuditLog.event_type == event_type
        )
        if subject_id is not None:
            q = q.filter(models_action.AuditLog.subject_id == subject_id)
        return q.count()
    finally:
        db.close()


print("== Backward compat: legacy /markings/{id}/grant is a FULL/permissive grant ==")

r = client.post("/markings", json={"id": "m-pii", "display_name": "PII", "category": "PII"})
check(r.status_code == 200, "create marking -> 200")

r = client.post("/markings/m-pii/grant", json={"principal": "legacy"})
check(r.status_code == 200, "legacy grant -> 200")
g = r.json()
check(g["permission"] == "*", "legacy grant is full/permissive (permission == '*')")

# A full grant satisfies every granular permission check.
db = SessionLocal()
try:
    check(SD.principal_has_marking_permission(db, "legacy", "m-pii", "apply"),
          "full grant satisfies APPLY")
    check(SD.principal_has_marking_permission(db, "legacy", "m-pii", "remove"),
          "full grant satisfies REMOVE")
    check(not SD.principal_has_marking_permission(db, "nobody", "m-pii", "apply"),
          "ungranted principal lacks APPLY")
finally:
    db.close()


print("== Marking CATEGORY governance: visibility + org_restriction + roles ==")

r = client.post("/marking-categories", json={
    "id": "cat-secret", "name": "Secret", "visibility": "hidden", "org_restriction": "org-acme",
})
check(r.status_code == 200, "create hidden category -> 200")
cat = r.json()
check(cat["visibility"] == "hidden", "category visibility hidden persisted")
check(cat["org_restriction"] == "org-acme", "org_restriction persisted")
check(audit_count("security.marking_category.created", "cat-secret") == 1,
      "category creation audited")

# Invalid visibility rejected
r = client.post("/marking-categories", json={"name": "Bad", "visibility": "public"})
check(r.status_code == 422, "invalid visibility -> 422")

# Default visibility is 'visible'
r = client.post("/marking-categories", json={"id": "cat-open", "name": "Open"})
check(r.status_code == 200 and r.json()["visibility"] == "visible",
      "default category visibility is 'visible'")

# Category role grants: Admin + Viewer
r = client.post("/marking-categories/cat-secret/roles", json={"principal": "admin1", "role": "admin"})
check(r.status_code == 200 and r.json()["role"] == "admin", "grant category Admin role -> 200")

r = client.post("/marking-categories/cat-secret/roles", json={"principal": "viewer1", "role": "viewer"})
check(r.status_code == 200 and r.json()["role"] == "viewer", "grant category Viewer role -> 200")

# Idempotent role grant
r = client.post("/marking-categories/cat-secret/roles", json={"principal": "admin1", "role": "admin"})
check(r.status_code == 200, "re-grant same role -> 200 (idempotent)")
r = client.get("/marking-categories/cat-secret/roles")
check(r.status_code == 200 and len(r.json()) == 2, "exactly 2 role grants after idempotent re-grant")

# Invalid role rejected
r = client.post("/marking-categories/cat-secret/roles", json={"principal": "x", "role": "owner"})
check(r.status_code == 422, "invalid category role -> 422")

# Role grant on missing category -> 404
r = client.post("/marking-categories/nope/roles", json={"principal": "x", "role": "admin"})
check(r.status_code == 404, "role grant on missing category -> 404")


print("== Granular permission grants: manage|apply|remove|members ==")

r = client.post("/markings/m-pii/grant-permission", json={"principal": "applier", "permission": "apply"})
check(r.status_code == 200 and r.json()["permission"] == "apply", "grant APPLY permission -> 200")

r = client.post("/markings/m-pii/grant-permission", json={"principal": "remover", "permission": "remove"})
check(r.status_code == 200 and r.json()["permission"] == "remove", "grant REMOVE permission -> 200")

# Invalid permission rejected
r = client.post("/markings/m-pii/grant-permission", json={"principal": "x", "permission": "destroy"})
check(r.status_code == 422, "invalid permission -> 422")

# Granular APPLY does NOT confer REMOVE (permissions don't overlap)
db = SessionLocal()
try:
    check(SD.principal_has_marking_permission(db, "applier", "m-pii", "apply"),
          "applier has APPLY")
    check(not SD.principal_has_marking_permission(db, "applier", "m-pii", "remove"),
          "applier does NOT have REMOVE (no overlap)")
finally:
    db.close()

# Grant on missing marking -> 404
r = client.post("/markings/nope/grant-permission", json={"principal": "x", "permission": "apply"})
check(r.status_code == 404, "grant-permission on missing marking -> 404")


print("== Assign enforcement: APPLY required only when actor supplied ==")

# No actor -> no enforcement (historical behavior preserved)
r = client.post("/security/resource-markings", json={"resource_id": "ds-1", "marking_id": "m-pii"})
check(r.status_code == 201, "assign without actor -> 201 (no enforcement)")

# Actor WITHOUT apply -> 403
r = client.post("/security/resource-markings",
                json={"resource_id": "ds-2", "marking_id": "m-pii", "actor": "remover"})
check(r.status_code == 403, "assign with actor lacking APPLY -> 403")

# Actor WITH apply -> 201
r = client.post("/security/resource-markings",
                json={"resource_id": "ds-2", "marking_id": "m-pii", "actor": "applier"})
check(r.status_code == 201, "assign with actor holding APPLY -> 201")
applied_rm_id = r.json()["id"]

# Full/permissive (legacy) actor can also assign
r = client.post("/security/resource-markings",
                json={"resource_id": "ds-3", "marking_id": "m-pii", "actor": "legacy"})
check(r.status_code == 201, "assign with full-grant actor -> 201")
legacy_rm_id = r.json()["id"]

# Assign to a missing marking still -> 404
r = client.post("/security/resource-markings", json={"resource_id": "ds-4", "marking_id": "nope"})
check(r.status_code == 404, "assign unknown marking -> 404")


print("== Strip (DELETE) enforcement: REMOVE required only when actor supplied ==")

# Actor WITHOUT remove -> 403 (and the marking stays)
r = client.delete(f"/security/resource-markings/{applied_rm_id}?actor=applier")
check(r.status_code == 403, "strip with actor lacking REMOVE -> 403")
r = client.get("/security/resource-markings/ds-2")
check("m-pii" in r.json()["marking_ids"], "marking still present after denied strip")

# Actor WITH remove -> 200
r = client.delete(f"/security/resource-markings/{applied_rm_id}?actor=remover")
check(r.status_code == 200 and r.json()["stripped"] is True, "strip with REMOVE permission -> 200")
r = client.get("/security/resource-markings/ds-2")
check("m-pii" not in r.json()["marking_ids"], "marking gone after authorized strip")
check(audit_count("security.marking.stripped", "ds-2") == 1, "strip audited")

# No actor -> no enforcement
r = client.delete(f"/security/resource-markings/{legacy_rm_id}")
check(r.status_code == 200, "strip without actor -> 200 (no enforcement)")

# Strip missing resource-marking -> 404
r = client.delete("/security/resource-markings/does-not-exist")
check(r.status_code == 404, "strip unknown resource-marking -> 404")


print(f"\n{passed} assertions passed")

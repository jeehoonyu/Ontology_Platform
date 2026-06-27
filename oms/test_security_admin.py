"""
Standalone self-test for owned files:
  app/security_access.py, app/admin_directory.py, app/admin_auth.py

Builds a local FastAPI app from ONLY the owned routers (does NOT import app.main).
Run from oms/:  ./venv312/Scripts/python.exe test_security_admin.py
"""
import os
import tempfile

_t = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(_t.name, 't.db')}"

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.database import Base, engine, SessionLocal  # noqa: E402
from app import models, models_action  # noqa: E402
from app import security_access as SA  # noqa: E402
from app import admin_directory as AD  # noqa: E402
from app import admin_auth as AA  # noqa: E402

Base.metadata.create_all(bind=engine)

api = FastAPI()
api.include_router(SA.router)
api.include_router(AD.router)
api.include_router(AA.router)
client = TestClient(api)

passed = 0


def ok(resp, label, expect=200):
    global passed
    success = resp.status_code == expect or (expect == 200 and 200 <= resp.status_code < 300)
    assert success, f"{label}: expected {expect}, got {resp.status_code} -> {resp.text[:400]}"
    passed += 1
    return resp.json() if resp.content else {}


# ============ admin_directory: hierarchy enrollment->org->space->project ============
ok(client.post("/admin/enrollments", json={"id": "enr", "display_name": "Acme"}), "enrollment")
ok(client.post("/admin/organizations", json={"id": "org", "enrollment_id": "enr", "display_name": "Acme Org"}), "org")
ok(client.post("/admin/spaces", json={"id": "sp", "organization_id": "org", "display_name": "Space"}), "space")
# (4) GET /admin/spaces
spaces = ok(client.get("/admin/spaces"), "list spaces")
assert any(s["id"] == "sp" for s in spaces), spaces

# new project entity inside the space
ok(client.post("/admin/projects", json={"id": "proj", "space_id": "sp", "display_name": "Proj"}), "project")
projs = ok(client.get("/admin/projects", params={"space_id": "sp"}), "list projects")
assert any(p["id"] == "proj" for p in projs), projs
# project under unknown space -> 404
ok(client.post("/admin/projects", json={"space_id": "ghost", "display_name": "x"}), "project bad space", expect=404)

# users + group
ok(client.post("/admin/users", json={"id": "u1", "username": "alice", "display_name": "Alice"}), "user u1")
ok(client.post("/admin/users", json={"id": "mgr", "username": "mgr", "display_name": "Manager"}), "user mgr")
ok(client.post("/admin/groups", json={"id": "eng", "organization_id": "org", "display_name": "Eng"}), "group")
# (4) GET /admin/groups
groups = ok(client.get("/admin/groups"), "list groups")
assert any(g["id"] == "eng" for g in groups), groups

# add member (no actor -> unchanged behavior)
ok(client.post("/admin/groups/eng/members", json={"user_id": "u1"}), "member u1 (no actor)")

# ============ (1) PROJECT branch inheritance ============
# grant editor to eng group at ENROLLMENT scope; u1 (member) checks edit at PROJECT scope
ok(client.post("/admin/roles/grant", json={"scope_type": "enrollment", "scope_id": "enr",
   "principal_type": "group", "principal_id": "eng", "role": "editor"}), "grant editor@enrollment")
chk = ok(client.post("/admin/access-check", json={"user_id": "u1", "scope_type": "project",
   "scope_id": "proj", "capability": "edit"}), "u1 edit @project")
assert chk["allowed"] is True, chk
# scopes considered must walk project->space->organization->enrollment
sc = chk["scopes_considered"]
assert "project:proj" in sc and "space:sp" in sc and "organization:org" in sc and "enrollment:enr" in sc, sc

# ============ (2) manage_membership enforcement (OPT-IN) ============
# mgr has no manage_membership -> supplying actor=mgr is rejected with 403
ok(client.post("/admin/groups/eng/members", json={"user_id": "mgr", "actor": "mgr"}),
   "add member with unauthorized actor", expect=403)
# give mgr manage_membership via a direct membership (no actor -> permissive)
ok(client.post("/admin/groups/eng/members", json={"user_id": "mgr", "manage_membership": True}),
   "seed mgr as manager")
# now mgr (actor) CAN add another user
ok(client.post("/admin/users", json={"id": "u3", "username": "carol", "display_name": "Carol"}), "user u3")
ok(client.post("/admin/groups/eng/members", json={"user_id": "u3", "actor": "mgr"}),
   "authorized actor adds member")
mem = ok(client.get("/admin/groups/eng/members"), "members list")
assert any(m["user_id"] == "u3" for m in mem), mem

# administrator at org scope can also manage membership
ok(client.post("/admin/users", json={"id": "boss", "username": "boss", "display_name": "Boss"}), "user boss")
ok(client.post("/admin/roles/grant", json={"scope_type": "organization", "scope_id": "org",
   "principal_type": "user", "principal_id": "boss", "role": "administrator"}), "grant admin@org boss")
ok(client.post("/admin/users", json={"id": "u4", "username": "dave", "display_name": "Dave"}), "user u4")
ok(client.post("/admin/groups/eng/members", json={"user_id": "u4", "actor": "boss"}),
   "org administrator adds member")

# ============ (3) admin_auth: enable/disable providers ============
prov = ok(client.post("/admin/auth-providers", json={"name": "Okta", "protocol": "saml",
   "attribute_mapping": {"NameID": "username"}}), "provider")
pid = prov["id"]
dis = ok(client.post(f"/admin/auth-providers/{pid}/disable"), "disable provider")
assert dis["enabled"] is False, dis
# disabled provider rejects map-assertion (existing behavior preserved)
ok(client.post(f"/admin/auth-providers/{pid}/map-assertion", json={"assertion": {"NameID": "x"}}),
   "map on disabled", expect=403)
en = ok(client.post(f"/admin/auth-providers/{pid}/enable"), "enable provider")
assert en["enabled"] is True, en
provs = ok(client.get("/admin/auth-providers"), "list providers")
assert any(p["id"] == pid and p["enabled"] is True for p in provs), provs
ok(client.post(f"/admin/auth-providers/{pid}/disable", json=None), "disable missing provider id?", expect=200)
ok(client.post("/admin/auth-providers/ghost/enable"), "enable unknown provider", expect=404)

# ============ (4) service-accounts + oauth-clients list/get/delete ============
ok(client.post("/admin/service-accounts", json={"id": "svc", "display_name": "ETL"}), "service account")
sas = ok(client.get("/admin/service-accounts"), "list service accounts")
assert any(s["id"] == "svc" for s in sas), sas

oc = ok(client.post("/admin/oauth-clients", json={"display_name": "App", "scopes": ["ontology:read"],
   "redirect_uris": ["https://app/cb"]}), "oauth client")
ocid = oc["id"]
ocs = ok(client.get("/admin/oauth-clients"), "list oauth clients")
assert any(c["id"] == ocid for c in ocs), ocs
got = ok(client.get(f"/admin/oauth-clients/{ocid}"), "get oauth client")
assert got["client_id"].startswith("client_"), got
ok(client.get("/admin/oauth-clients/ghost"), "get unknown oauth client", expect=404)
deld = ok(client.delete(f"/admin/oauth-clients/{ocid}"), "delete oauth client")
assert deld["deleted"] is True, deld
ok(client.get(f"/admin/oauth-clients/{ocid}"), "get deleted oauth client", expect=404)

# ============ security_access router smoke (preserved behavior) ============
pr = ok(client.post("/projects", json={"id": "p1", "display_name": "P1"}), "create project (security_access)", expect=201)
role = ok(client.post("/roles", json={"id": "r1", "display_name": "Editor", "permissions": ["edit"]}), "create role", expect=201)
ok(client.post("/projects/p1/grants", json={"principal": "u1", "role_id": "r1"}), "create grant", expect=201)
ac = ok(client.post("/access/check", json={"project_id": "p1", "principal": "u1", "permission": "edit"}), "access check")
assert ac["allowed"] is True, ac

print(f"\nSecurity/Admin self-test verified: {passed} assertions passed.")

from app.database import engine as _engine  # noqa: E402
_engine.dispose()
_t.cleanup()

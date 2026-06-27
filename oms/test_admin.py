"""
Deep-fidelity pass 12 conformance test: Management & Enablement (Control Panel).
Directory (enrollment->org->space, users, groups, memberships, scope-level roles with
hierarchical inheritance + group resolution + membership expiry), Authentication
(providers + attribute mapping, tokens gated by user active status), Usage (quotas).
Run: ./venv312/Scripts/python.exe test_admin.py
"""
import os
import tempfile

tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tmpdir.name, 'admin.db')}"

from fastapi.testclient import TestClient  # noqa: E402
from app.main import app  # noqa: E402

client = TestClient(app)
passed = 0


def ok(resp, label, expect=200):
    global passed
    success = resp.status_code == expect or (expect == 200 and 200 <= resp.status_code < 300)
    assert success, f"{label}: expected {expect}, got {resp.status_code} -> {resp.text[:400]}"
    passed += 1
    return resp.json() if resp.content else {}


# ================= Directory: enrollment -> org -> space =================
enr = ok(client.post("/admin/enrollments", json={"id": "enr", "display_name": "Acme Foundry"}), "enrollment")
org = ok(client.post("/admin/organizations", json={"id": "org", "enrollment_id": "enr", "display_name": "Acme"}), "org")
sp = ok(client.post("/admin/spaces", json={"id": "sp", "organization_id": "org", "display_name": "Ops Space"}), "space")
# org must reference a real enrollment
ok(client.post("/admin/organizations", json={"enrollment_id": "ghost", "display_name": "x"}), "org bad enr", expect=404)

# users + groups + membership
u1 = ok(client.post("/admin/users", json={"id": "u1", "username": "alice", "display_name": "Alice", "organization_ids": ["org"]}), "user u1")
u2 = ok(client.post("/admin/users", json={"id": "u2", "username": "bob", "display_name": "Bob"}), "user u2")
grp = ok(client.post("/admin/groups", json={"id": "eng", "organization_id": "org", "display_name": "Engineers"}), "group")
ok(client.post("/admin/groups/eng/members", json={"user_id": "u1"}), "member u1")
ok(client.post("/admin/groups/eng/members", json={"user_id": "u2", "expiration": 1}), "member u2 expired")  # expiration in the past
members = ok(client.get("/admin/groups/eng/members"), "members")
assert {m["user_id"]: m["expired"] for m in members} == {"u1": False, "u2": True}, members

# ================= Roles: hierarchical inheritance + group resolution =================
# grant 'editor' to the Engineers group at the ENROLLMENT scope -> should inherit down to the space
ok(client.post("/admin/roles/grant", json={"scope_type": "enrollment", "scope_id": "enr",
    "principal_type": "group", "principal_id": "eng", "role": "editor"}), "grant editor@enrollment")

# u1 (active member of eng) checking 'edit' at the SPACE scope -> allowed via inheritance
chk_u1 = ok(client.post("/admin/access-check", json={"user_id": "u1", "scope_type": "space", "scope_id": "sp", "capability": "edit"}), "u1 edit space")
assert chk_u1["allowed"] is True, chk_u1
assert "enrollment:enr" in chk_u1["scopes_considered"], chk_u1
# u1 cannot 'administer' (editor lacks it)
chk_admin = ok(client.post("/admin/access-check", json={"user_id": "u1", "scope_type": "space", "scope_id": "sp", "capability": "administer"}), "u1 administer")
assert chk_admin["allowed"] is False, chk_admin
# u2 membership is expired -> not in group -> denied
chk_u2 = ok(client.post("/admin/access-check", json={"user_id": "u2", "scope_type": "space", "scope_id": "sp", "capability": "edit"}), "u2 edit (expired)")
assert chk_u2["allowed"] is False and "eng" not in chk_u2["via_groups"], chk_u2
# direct user grant of administrator at org scope
ok(client.post("/admin/roles/grant", json={"scope_type": "organization", "scope_id": "org",
    "principal_type": "user", "principal_id": "u2", "role": "administrator"}), "grant admin@org to u2")
chk_u2b = ok(client.post("/admin/access-check", json={"user_id": "u2", "scope_type": "space", "scope_id": "sp", "capability": "administer"}), "u2 administer")
assert chk_u2b["allowed"] is True, chk_u2b  # org grant inherits down to space

# inactive user -> denied regardless of roles
ok(client.post("/admin/users/u1/status", json={"status": "inactive"}), "deactivate u1")
chk_inactive = ok(client.post("/admin/access-check", json={"user_id": "u1", "scope_type": "space", "scope_id": "sp", "capability": "view"}), "u1 inactive")
assert chk_inactive["allowed"] is False and chk_inactive["reason"] == "user inactive", chk_inactive
ok(client.post("/admin/users/u1/status", json={"status": "active"}), "reactivate u1")

# ================= Authentication: providers + attribute mapping + tokens =================
prov = ok(client.post("/admin/auth-providers", json={"name": "Okta", "protocol": "saml",
    "attribute_mapping": {"NameID": "username", "mail": "email", "memberOf": "groups"}}), "provider")
mapped = ok(client.post(f"/admin/auth-providers/{prov['id']}/map-assertion", json={
    "assertion": {"NameID": "alice@acme.com", "mail": "alice@acme.com", "memberOf": ["Engineers"], "ignored": "x"}}), "map assertion")
assert mapped["mapped_attributes"] == {"username": "alice@acme.com", "email": "alice@acme.com", "groups": ["Engineers"]}, mapped

# token tied to u2; valid while active, invalid while inactive
tok = ok(client.post("/admin/tokens", json={"principal_type": "user", "principal_id": "u2", "scopes": ["api:read"]}), "issue token")
v1 = ok(client.post("/admin/tokens/validate", json={"token": tok["token"], "required_scope": "api:read"}), "validate active")
assert v1["valid"] is True, v1
v_scope = ok(client.post("/admin/tokens/validate", json={"token": tok["token"], "required_scope": "api:write"}), "validate missing scope")
assert v_scope["valid"] is False and v_scope["reason"] == "missing scope", v_scope
ok(client.post("/admin/users/u2/status", json={"status": "inactive"}), "deactivate u2")
v2 = ok(client.post("/admin/tokens/validate", json={"token": tok["token"]}), "validate inactive")
assert v2["valid"] is False and v2["reason"] == "principal inactive", v2  # tokens invalid while account inactive
ok(client.post("/admin/users/u2/status", json={"status": "active"}), "reactivate u2")
ok(client.post(f"/admin/tokens/{tok['id']}/revoke"), "revoke")
v3 = ok(client.post("/admin/tokens/validate", json={"token": tok["token"]}), "validate revoked")
assert v3["valid"] is False and v3["reason"] == "revoked", v3

# oauth client + service account
oc = ok(client.post("/admin/oauth-clients", json={"display_name": "My App", "scopes": ["ontology:read"], "redirect_uris": ["https://app/cb"]}), "oauth client")
assert oc["client_id"].startswith("client_") and oc["client_secret"].startswith("secret_"), oc
ok(client.post("/admin/service-accounts", json={"id": "svc", "display_name": "ETL bot"}), "service account")
stok = ok(client.post("/admin/tokens", json={"principal_type": "service_account", "principal_id": "svc", "scopes": ["api:write"]}), "svc token")
assert ok(client.post("/admin/tokens/validate", json={"token": stok["token"]}), "validate svc token")["valid"] is True

# ================= Usage & quotas =================
for v in [30.0, 50.0]:
    ok(client.post("/admin/usage/record", json={"principal": "u1", "project": "proj", "metric": "compute_seconds", "value": v}), "usage rec")
summ = ok(client.get("/admin/usage/summary", params={"project": "proj", "metric": "compute_seconds"}), "usage summary")
assert summ["total"] == 80.0, summ
ok(client.post("/admin/usage/quotas", json={"scope_type": "project", "scope_id": "proj", "metric": "compute_seconds", "limit_value": 100}), "quota")
qok = ok(client.post("/admin/usage/check-quota", json={"scope_type": "project", "scope_id": "proj", "metric": "compute_seconds"}), "quota ok")
assert qok["within_limit"] is True and qok["remaining"] == 20.0, qok
ok(client.post("/admin/usage/record", json={"principal": "u1", "project": "proj", "metric": "compute_seconds", "value": 40.0}), "usage over")
qover = ok(client.post("/admin/usage/check-quota", json={"scope_type": "project", "scope_id": "proj", "metric": "compute_seconds"}), "quota over")
assert qover["within_limit"] is False and qover["usage"] == 120.0, qover

print(f"\nManagement & Enablement (Control Panel) verified: {passed} assertions passed.")
from app.database import engine as _engine  # noqa: E402
_engine.dispose()
tmpdir.cleanup()

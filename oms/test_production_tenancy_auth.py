"""OIDC session and service-token project context extraction."""
import os
import tempfile

tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tmpdir.name, 'tenancy_auth.db')}"
os.environ["AUTH_MODE"] = "local"
os.environ["APP_ENV"] = "test"

from app import admin_auth, production_auth  # noqa: E402
from app.database import SessionLocal  # noqa: E402
from app.main import app  # noqa: E402,F401

passed = 0


def check(condition, label):
    global passed
    assert condition, label
    passed += 1


with SessionLocal() as db:
    db.add(production_auth.AuthSession(
        id="session-1", principal_id="oidc-user", email="user@example.test", display_name="OIDC User",
        roles=["publisher"], claims={"organization_id": "acme", "project_ids": ["operations", "models"]},
        created_at=1, expires_at=4_000_000_000, last_seen_at=1,
    ))
    db.add(admin_auth.ServiceAccount(id="worker", display_name="Worker", organization_id="acme", created_at=1))
    db.add(admin_auth.ApiToken(
        id="token-1", token="secret-project-token", principal_type="service_account", principal_id="worker",
        scopes=["view", "project:operations:execute", "project:operations:edit"], expires_at=None, revoked=False, created_at=1,
    ))
    db.commit()

    session_principal = production_auth._session_principal(db, "session-1")
    check(session_principal is not None, "OIDC session resolves")
    check(session_principal.organization_id == "acme", "organization claim resolves")
    check(session_principal.project_ids == ["models", "operations"], "project claims resolve deterministically")
    check(session_principal.allows("publish"), "role permissions remain available")

    token_principal = production_auth._bearer_principal(db, "Bearer secret-project-token")
    check(token_principal is not None, "service token resolves")
    check(token_principal.organization_id == "acme", "service account organization resolves")
    check(token_principal.project_ids == ["operations"], "project-scoped token resolves")
    check(token_principal.allows("execute") and token_principal.allows("edit") and token_principal.allows("view"), "token permissions resolve")

local = production_auth._local_principal()
check(local.project_ids == ["*"] and local.allows("anything"), "local development bypass is explicit")
print(f"Production tenancy authentication verified: {passed} assertions passed.")

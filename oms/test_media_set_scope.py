"""Media sets belong to a project, and only that project's principals reach them (GOAL_FOUNDATIONS A5).

`MediaSet` had no project: any editor listed, read, filled and extracted every tenant's
sets and items. A set now carries `project_id`; its list, get, items, upload, content
and extraction routes are scoped by it. A set created before sets had projects has none,
and only a principal who holds every project reaches it until one is assigned (the
owner's decision, 2026-09-26).
"""
import os
import tempfile

tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tmpdir.name, 'media_scope.db')}"
os.environ["AUTH_MODE"] = "local"
os.environ["APP_ENV"] = "test"

from fastapi.testclient import TestClient  # noqa: E402

from app import media_sets, production_auth  # noqa: E402
from app.database import SessionLocal  # noqa: E402
from app.main import app  # noqa: E402

client = TestClient(app)
passed = 0


def check(response, label, expected=200):
    global passed
    assert response.status_code == expected, f"{label}: {response.status_code} {response.text[:600]}"
    passed += 1
    return response.json() if response.content else {}


def use(principal):
    app.dependency_overrides[production_auth.current_principal] = lambda: principal


admin = production_auth.Principal("platform-admin", "Admin", None, ["administrator"], ["*"],
                                  organization_id="media-org", project_ids=["*"])
alpha = production_auth.Principal("alpha-editor", "Alpha", None, ["editor"], ["view", "edit"],
                                  organization_id="media-org", project_ids=["alpha"])
beta = production_auth.Principal("beta-editor", "Beta", None, ["editor"], ["view", "edit"],
                                 organization_id="media-org", project_ids=["beta"])

use(admin)
check(client.post("/tenancy/organizations", json={"id": "media-org", "display_name": "Media Org"}), "organization", 201)
for project in ("alpha", "beta"):
    check(client.post("/tenancy/projects", json={"id": project, "organization_id": "media-org", "display_name": project}),
          f"{project} project", 201)

use(alpha)
created = check(client.post("/media-sets", json={"id": "alpha-docs", "project_id": "alpha", "display_name": "Alpha docs",
                                                 "media_type": "document"}), "alpha creates a set", 201)
assert created["project_id"] == "alpha", created
item = check(client.post("/media-sets/alpha-docs/items", json={"id": "alpha-memo", "filename": "memo.txt",
                                                               "mime_type": "text/plain", "text_content": "alpha only"}),
             "alpha registers an item", 201)
check(client.post("/media-sets", json={"id": "stray", "project_id": "beta", "display_name": "Stray",
                                       "media_type": "document"}), "alpha cannot create a set in beta", 403)

# Beta reaches none of alpha's set or its item, by any route.
use(beta)
listed = check(client.get("/media-sets"), "beta lists sets")
assert "alpha-docs" not in {row["id"] for row in listed}, listed
passed += 1
check(client.get("/media-sets/alpha-docs"), "beta cannot read alpha's set", 403)
check(client.get("/media-sets/alpha-docs/items"), "beta cannot list alpha's items", 403)
check(client.post("/media-sets/alpha-docs/items", json={"filename": "x.txt", "mime_type": "text/plain"}),
      "beta cannot add to alpha's set", 403)
check(client.get(f"/media-items/{item['id']}"), "beta cannot read alpha's item", 403)
check(client.post(f"/media-items/{item['id']}/extract"), "beta cannot extract alpha's item", 403)
check(client.get(f"/media-items/{item['id']}/content"), "beta cannot read alpha's item content", 403)
check(client.post(f"/media-items/{item['id']}/chunk", json={}), "beta cannot chunk alpha's item", 403)

# Alpha reaches its own.
use(alpha)
assert "alpha-docs" in {row["id"] for row in check(client.get("/media-sets"), "alpha lists its sets")}
passed += 1
check(client.post(f"/media-items/{item['id']}/extract"), "alpha extracts its own item")

# A set from before sets had projects: unassigned, reached only by a principal who holds
# every project, until it is assigned.
with SessionLocal() as db:
    db.add(media_sets.MediaSet(id="legacy", project_id=None, display_name="Legacy", media_type="image"))
    db.commit()
for principal, label in ((alpha, "alpha"), (beta, "beta")):
    use(principal)
    assert "legacy" not in {row["id"] for row in check(client.get("/media-sets"), f"{label} lists sets")}
    passed += 1
    check(client.get("/media-sets/legacy"), f"{label} cannot read the unassigned set", 403)
    check(client.post("/media-sets/legacy/project", json={"project_id": principal.project_ids[0]}),
          f"{label} cannot claim the unassigned set", 403)
use(admin)
assert "legacy" in {row["id"] for row in check(client.get("/media-sets"), "admin lists sets")}
passed += 1
assigned = check(client.post("/media-sets/legacy/project", json={"project_id": "beta"}), "admin assigns it to beta")
assert assigned["project_id"] == "beta", assigned
use(beta)
check(client.get("/media-sets/legacy"), "beta reaches the set once it is beta's")

app.dependency_overrides.clear()
print(f"Media sets stay inside their projects: {passed} assertions passed.")

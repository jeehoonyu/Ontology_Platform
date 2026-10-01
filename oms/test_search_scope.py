"""Global search returns only the caller's projects' events and incidents (GOAL_FOUNDATIONS A5).

Search filtered events by the project in their payload and did not filter incidents at
all, though `Incident` carries `project_id` and `/ops/incidents` is scoped: a principal
of project beta found alpha's incidents by name. Both now go through the same project
scope as every other kind search returns, by the column the row is filed under.
"""
import os
import tempfile

tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tmpdir.name, 'search_scope.db')}"
os.environ["AUTH_MODE"] = "local"
os.environ["APP_ENV"] = "test"

from fastapi.testclient import TestClient  # noqa: E402

from app import ops_control, production_auth  # noqa: E402
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
                                  organization_id="search-org", project_ids=["*"])
alpha = production_auth.Principal("alpha-admin", "Alpha", None, ["administrator"], ["*"],
                                  organization_id="search-org", project_ids=["alpha"])
beta = production_auth.Principal("beta-admin", "Beta", None, ["administrator"], ["*"],
                                 organization_id="search-org", project_ids=["beta"])

use(admin)
check(client.post("/tenancy/organizations", json={"id": "search-org", "display_name": "Search Org"}), "organization", 201)
for project in ("alpha", "beta"):
    check(client.post("/tenancy/projects", json={"id": project, "organization_id": "search-org", "display_name": project}),
          f"{project} project", 201)

# An incident and an event filed under alpha. The event's payload names beta, which the
# column does not: the column is what the row is filed under.
with SessionLocal() as db:
    ops_control._ensure_tables(db)
    ops_control.record_ops_event(db, source="alpha-sensor", event_type="reliability.threshold", severity="high",
                             title="Zephyrine event", project_id="alpha", payload={"project_id": "beta"})
    db.commit()
use(alpha)
check(client.post("/ops/incidents", json={"display_name": "Zephyrine incident", "severity": "high", "project_id": "alpha"}),
      "alpha incident")

use(beta)
found = check(client.get("/search?q=Zephyrine"), "beta searches for alpha's names")
kinds = sorted(item["kind"] for item in found.get("results", []))
assert kinds == [], f"beta found alpha's rows: {kinds}"
passed += 1

use(alpha)
found = check(client.get("/search?q=Zephyrine"), "alpha searches for its own names")
titles = {(item["kind"], item["title"]) for item in found.get("results", [])}
# Opening the incident also records an event of its own in alpha.
assert {("event", "Zephyrine event"), ("incident", "Zephyrine incident")} <= titles, f"alpha should find its rows: {titles}"
passed += 1

app.dependency_overrides.clear()
print(f"Search stays inside the caller's projects: {passed} assertions passed.")

"""Interface-scoped queries must not cross project boundaries.

An interface names a capability, not a tenancy scope. Querying objects through
one walks every object type that implements it, and those types can belong to
different projects. Without a project filter the query returns instance data
from projects the caller cannot otherwise read, which is a tenant isolation
failure on committed data rather than on metadata.

This is the regression test for GOAL2-006.
"""
import os
import tempfile

tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tmpdir.name, 'iface_tenancy.db')}"
os.environ["AUTH_MODE"] = "local"
os.environ["APP_ENV"] = "test"

from fastapi.testclient import TestClient  # noqa: E402
from app.main import app  # noqa: E402

client = TestClient(app)
passed = 0


def check(condition, label, payload=None):
    global passed
    assert condition, f"{label}: {payload}"
    passed += 1


def ok(response, label, expect=200):
    assert response.status_code == expect, f"{label}: {response.status_code} {response.text[:500]}"
    return response.json() if response.content else {}


for project in ("alpha", "beta"):
    client.post("/projects", json={"id": project, "display_name": project})

ok(client.post("/interfaces", json={
    "id": "trackable", "display_name": "Trackable",
    "properties": {"code": {"base_type": "string", "required": True}},
}), "create interface")

for project, object_type in (("alpha", "alpha_asset"), ("beta", "beta_asset")):
    ok(client.post("/object-types", json={
        "id": object_type, "project_id": project, "display_name": object_type,
        "properties": {"code": {"type": "string"}},
    }), f"create {object_type}")
    ok(client.post(f"/object-types/{object_type}/implement-interface", json={
        "interface_id": "trackable", "property_mappings": {"code": "code"},
    }), f"{object_type} implements trackable")
    ok(client.post("/objects", json={
        "id": f"{object_type}_1", "project_id": project, "object_type_id": object_type,
        "properties": {"code": f"SECRET-{project.upper()}"},
    }), f"create {object_type} instance")

# A query scoped to one project must not return the other project's objects.
scoped = ok(client.post("/interfaces/trackable/query-objects", json={"project_id": "alpha"}),
            "query scoped to alpha")
returned_types = {row["object_type_id"] for row in scoped["objects"]}
leaked_values = [
    value for row in scoped["objects"]
    for value in (row.get("interface_properties") or {}).values()
    if isinstance(value, str) and "BETA" in value
]
check("beta_asset" not in returned_types,
      "a query scoped to alpha does not walk beta's object type", sorted(returned_types))
check(not leaked_values, "no beta property value appears in an alpha-scoped query", leaked_values)
check(scoped["object_type_ids_searched"] == ["alpha_asset"],
      "only the scoped project's implementers are searched", scoped["object_type_ids_searched"])

# The unscoped query is the one that leaked. It must now return only what the
# caller can read rather than every implementer in the deployment.
unscoped = ok(client.post("/interfaces/trackable/query-objects", json={}), "unscoped query")
check(isinstance(unscoped.get("objects"), list), "unscoped query still answers", unscoped)

alpha_only = ok(client.post("/interfaces/trackable/query-objects",
                            json={"project_id": "alpha", "filters": {"code": "SECRET-ALPHA"}}),
                "filtered scoped query")
check(all(row["object_type_id"] == "alpha_asset" for row in alpha_only["objects"]),
      "filters do not widen the project scope", alpha_only["objects"])

# Listing interfaces is metadata, but it is still ontology metadata and every
# other ontology resource requires a principal to read it.
listed = client.get("/interfaces")
check(listed.status_code == 200, "listing interfaces answers for a permitted principal",
      listed.status_code)

# The property that actually matters. Everything above runs as an unrestricted
# local principal, which legitimately reads every project; a scoped request
# proves the filter is wired but not that it protects anyone. A principal
# confined to one project must not be able to reach the other's instances by
# any route: not by asking for them, not by omitting the scope.
from app import production_auth  # noqa: E402

alpha_only = production_auth.Principal(
    "alpha-user", "Alpha User", "alpha@example.test", ["administrator"],
    ["view", "edit", "administer"], project_ids=["alpha"],
)
app.dependency_overrides[production_auth.current_principal] = lambda: alpha_only
try:
    confined = ok(client.post("/interfaces/trackable/query-objects", json={}),
                  "confined principal queries without a scope")
    reached = {row["object_type_id"] for row in confined["objects"]}
    values = [
        value for row in confined["objects"]
        for value in (row.get("interface_properties") or {}).values()
        if isinstance(value, str)
    ]
    check("beta_asset" not in reached,
          "omitting the scope does not widen past what the principal may read", sorted(reached))
    check(not any("BETA" in value for value in values),
          "no beta instance value reaches a principal confined to alpha", values)

    denied = client.post("/interfaces/trackable/query-objects", json={"project_id": "beta"})
    check(denied.status_code in (403, 404),
          "asking for another project outright is refused", denied.status_code)
finally:
    app.dependency_overrides.pop(production_auth.current_principal, None)

print(f"\nInterface query tenancy verified: {passed} assertions passed.")
from app.database import engine as _engine  # noqa: E402
_engine.dispose()
tmpdir.cleanup()

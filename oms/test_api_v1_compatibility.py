"""Compatibility-preserving API v1 aliases remain typed and behaviorally identical."""
import os
import tempfile
import time
from types import SimpleNamespace


tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tmpdir.name, 'api_v1_compat.db')}"
os.environ["AUTH_MODE"] = "local"
os.environ["APP_ENV"] = "test"

from fastapi.routing import APIRoute  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from app import api_v1_compat, production_auth  # noqa: E402
from app.database import SessionLocal  # noqa: E402
from app.main import app  # noqa: E402


client = TestClient(app)
passed = 0


def check(condition, label, payload=None):
    global passed
    assert condition, f"{label}: {payload}"
    passed += 1


def ok(response, label, status=200):
    check(response.status_code == status, label, f"{response.status_code} {response.text[:1000]}")
    return response.json() if response.content else {}


manifest = ok(client.get("/api/v1/compatibility/manifest"), "manifest is available")
check(manifest["version"] == "v1", "manifest identifies v1", manifest)
check(manifest["strategy"] == "same-handler-typed-alias", "manifest identifies alias strategy", manifest)
check(manifest["summary"]["aliases"] >= 850, "broad legacy API is covered", manifest["summary"])
check(manifest["summary"]["schema_visible"] >= 800, "typed aliases are OpenAPI-visible", manifest["summary"])
check(manifest["summary"]["authoritative_v1_collisions"] > 0,
      "explicit v1 implementations remain authoritative", manifest["summary"])

sample_route = next(route for route in app.routes if isinstance(route, APIRoute) and route.path == "/imports/jobs")
fake_context = SimpleNamespace(original_route=sample_route, path="/nested/imports/jobs")
fake_branch = SimpleNamespace(effective_route_contexts=lambda: iter([fake_context]))
discovered = list(api_v1_compat.iter_assembled_api_routes([fake_branch]))
check(discovered == [fake_context], "nested FastAPI effective route contexts are discovered")

aliases = {(row["source_path"], row["v1_path"], tuple(row["methods"])) for row in manifest["aliases"]}
for source, alias, method in (
    ("/imports/jobs", "/api/v1/imports/jobs", "GET"),
    ("/imports/csv", "/api/v1/imports/csv", "POST"),
    ("/pipeline-builder/graphs", "/api/v1/pipeline-builder/graphs", "GET"),
    ("/ontology-generator/drafts", "/api/v1/ontology-generator/drafts", "GET"),
    ("/object-explorer/query", "/api/v1/object-explorer/query", "POST"),
):
    check((source, alias, (method,)) in aliases, f"{source} has a v1 alias", aliases)

alias_paths = {row["v1_path"] for row in manifest["aliases"]}
for excluded in ("/api/v1/workspace/command-center", "/api/v1/auth/login", "/api/v1/health/live"):
    check(excluded not in alias_paths, f"deployment surface {excluded} is not aliased", alias_paths)

routes = [route for route in app.routes if isinstance(route, APIRoute)]
legacy_imports = next(route for route in routes if route.path == "/imports/jobs" and "GET" in route.methods)
v1_imports = next(route for route in routes if route.path == "/api/v1/imports/jobs" and "GET" in route.methods)
check(v1_imports.endpoint is legacy_imports.endpoint, "legacy and v1 paths share one endpoint implementation")
check(v1_imports.response_model is legacy_imports.response_model, "response model is preserved")
check(v1_imports.status_code == legacy_imports.status_code, "status code contract is preserved")

for method, source_path, expected in (
    ("POST", "/runtime/workers/worker-1/heartbeat", "execute"),
    ("POST", "/jobs/claim", "execute"),
    ("POST", "/approvals/a-1/decision", "approve"),
    ("POST", "/model/deploy", "deploy"),
    ("POST", "/ontology/publish", "publish"),
    ("POST", "/logic/run", "execute"),
    ("POST", "/reports/export", "export"),
    ("POST", "/artifacts/a-1/restore", "restore"),
    ("POST", "/admin/service-accounts", "administer"),
):
    source_permission = production_auth._permission_for_request(method, source_path)
    alias_permission = production_auth._permission_for_request(method, "/api/v1" + source_path)
    check(source_permission == expected and alias_permission == expected,
          f"v1 permission inference matches {source_path}", (source_permission, alias_permission))

legacy_templates = ok(client.get("/imports/templates"), "legacy templates load")
v1_templates = ok(client.get("/api/v1/imports/templates"), "v1 templates load")
check(v1_templates == legacy_templates, "read responses are identical")

ok(client.post("/api/v1/tenancy/organizations", json={
    "id": "compat-org", "display_name": "Compatibility Org",
}), "create organization through v1 alias", 201)
ok(client.post("/api/v1/tenancy/projects", json={
    "id": "compat-project", "organization_id": "compat-org", "display_name": "Compatibility Project",
}), "create project through v1 alias", 201)

editor = production_auth.Principal(
    "compat-editor", "Compatibility Editor", None, ["editor"], ["view", "edit"],
    organization_id="compat-org", project_ids=["compat-project"],
)
viewer = production_auth.Principal(
    "compat-viewer", "Compatibility Viewer", None, ["viewer"], ["view"],
    organization_id="compat-org", project_ids=["compat-project"],
)
app.dependency_overrides[production_auth.current_principal] = lambda: editor
created = ok(client.post("/api/v1/imports/csv", json={
    "id": "compat-import",
    "project_id": "compat-project",
    "filename": "assets.csv",
    "content": "asset_id,name,status\na-1,Pump 1,RUNNING\n",
}), "create import through v1 alias", 201)
check(created["project_id"] == "compat-project", "v1 write retains project scope", created)
legacy_list = ok(client.get("/imports/jobs?project_id=compat-project"), "legacy path sees v1 write")
check(any(row["id"] == "compat-import" for row in legacy_list["jobs"]),
      "state is shared between compatibility paths", legacy_list)

app.dependency_overrides[production_auth.current_principal] = lambda: viewer
ok(client.post("/api/v1/imports/csv", json={
    "project_id": "compat-project", "content": "asset_id\na-2\n",
}), "v1 alias preserves edit authorization", 403)
app.dependency_overrides.clear()

with SessionLocal() as db:
    db.add(production_auth.AuthSession(
        id="compat-viewer-session",
        principal_id="compat-viewer",
        email=None,
        display_name="Compatibility Viewer",
        roles=["viewer"],
        claims={"organization_id": "compat-org", "project_ids": ["compat-project"]},
        created_at=int(time.time()),
        expires_at=int(time.time()) + 3600,
        last_seen_at=int(time.time()),
    ))
    db.commit()
os.environ["AUTH_MODE"] = "oidc"
os.environ["OIDC_ISSUER"] = "https://identity.example.test/realms/ontology"
os.environ["OIDC_CLIENT_ID"] = "ontology-platform"
client.cookies.set(production_auth.SESSION_COOKIE, "compat-viewer-session")
ok(client.post("/api/v1/admin/service-accounts", json={}),
   "OIDC middleware protects aliased administrator route", 403)
ok(client.post("/admin/service-accounts", json={}),
   "OIDC middleware applies the same source-route protection", 403)
client.cookies.clear()
os.environ["AUTH_MODE"] = "local"

schema = app.openapi()
operation = schema["paths"]["/api/v1/imports/csv"]["post"]
check(operation["x-ontologyos-compatibility-source"] == "/imports/csv",
      "OpenAPI identifies compatibility source", operation)
check(operation["x-ontologyos-version"] == "v1", "OpenAPI identifies API version", operation)
check("requestBody" in operation and "responses" in operation, "OpenAPI retains typed request and response contracts")
operation_ids = [
    path_item[method]["operationId"]
    for path_item in schema["paths"].values()
    for method, method_spec in path_item.items()
    if method in {"get", "post", "put", "patch", "delete"} and "operationId" in method_spec
]
check(len(operation_ids) == len(set(operation_ids)), "OpenAPI operation IDs are unique")

route_count = len(app.routes)
second_summary = api_v1_compat.install_api_v1_compatibility(app)
check(len(app.routes) == route_count, "compatibility installation is idempotent")
check(second_summary == app.state.api_v1_compatibility_summary, "idempotent summary is stable")

print(f"API v1 compatibility verified: {passed} assertions passed, "
      f"{manifest['summary']['aliases']} aliases active.")

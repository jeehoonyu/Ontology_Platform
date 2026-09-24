"""Materializing an ontology's definitions reads each table once, however many rows it holds.

`ontology_runtime_v1.materialize_semantic_definitions` runs whenever an action type is created,
and re-materializes every definition in the project. Each lookup inside it was its own query:
one property definition per property, one profile and one resource definition per object
type. The suite-cost census found it on 2026-09-23 -- after the demo bootstrap, one
`POST /action-types` read property definitions 32 times -- through a test that happened to
create an action type in a project with many types. The cost grew with the ontology, not with
the request.

This builds twelve object types of five properties each, creates an action type, and requires
the request to repeat no statement more than twice. It then checks the materialization is
still right: every property defined once, and a second action type changing none of them.

Run:
  python oms/test_semantic_materialize_cost.py
"""
import os
import sys
import tempfile
from pathlib import Path

tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
os.environ["DATABASE_URL"] = f"sqlite:///{Path(tmpdir.name, 'materialize-cost.db').as_posix()}"
os.environ["AUTH_MODE"] = "local"
os.environ["APP_ENV"] = "test"
sys.path.insert(0, str(Path(__file__).resolve().parent))

from fastapi.testclient import TestClient  # noqa: E402

from app import ontology_runtime_v1  # noqa: E402
from app.database import SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from request_cost import counting, summarize  # noqa: E402

client = TestClient(app)
passed = 0
TYPES, PROPERTIES = 12, 5


def ok(response, label, expect=200):
    global passed
    success = response.status_code == expect or (expect == 200 and 200 <= response.status_code < 300)
    assert success, f"{label}: {response.status_code} {response.text[:400]}"
    passed += 1
    return response.json() if response.content else {}


def check(condition, label, payload=None):
    global passed
    assert condition, f"{label}: {payload}"
    passed += 1


for index in range(TYPES):
    ok(client.post("/object-types", json={
        "id": f"cost_type_{index}", "display_name": f"Cost type {index}",
        "properties": {f"field_{p}": {"type": "string"} for p in range(PROPERTIES)},
    }), f"object type {index}")


def create_action(action_id):
    with counting(engine) as statements:
        ok(client.post("/action-types", json={
            "id": action_id, "display_name": action_id, "parameters": {},
            "rules": {"object_mutations": [{"object_type_id": "cost_type_0", "object_id": "$id", "set": {"field_0": "x"}}]},
        }), f"create {action_id}")
    return summarize(statements)


first = create_action("cost_action_one")
check(first["worst_repeat"] <= 2,
      f"creating an action type repeated one statement {first['worst_repeat']} times over "
      f"{TYPES} types of {PROPERTIES} properties", first.get("repeats"))

with SessionLocal() as db:
    definitions = db.query(ontology_runtime_v1.OntologyPropertyDefinition).filter(
        ontology_runtime_v1.OntologyPropertyDefinition.object_type_id.like("cost_type_%")).all()
    check(len(definitions) == TYPES * PROPERTIES,
          f"{len(definitions)} property definitions for {TYPES * PROPERTIES} properties", None)
    check(len({row.id for row in definitions}) == len(definitions), "a property was defined twice", None)
    versions = {row.id: row.updated_at for row in definitions}
    resources = db.query(ontology_runtime_v1.OntologyResourceDefinition).filter(
        ontology_runtime_v1.OntologyResourceDefinition.resource_kind == "object_type",
        ontology_runtime_v1.OntologyResourceDefinition.resource_id.like("cost_type_%")).all()
    check(len(resources) == TYPES, f"{len(resources)} object type resources for {TYPES} types", None)
    resource_versions = {row.id: row.version for row in resources}

second = create_action("cost_action_two")
check(second["worst_repeat"] <= 2, f"a second action type repeated a statement {second['worst_repeat']} times", None)
with SessionLocal() as db:
    again = db.query(ontology_runtime_v1.OntologyPropertyDefinition).filter(
        ontology_runtime_v1.OntologyPropertyDefinition.object_type_id.like("cost_type_%")).count()
    check(again == TYPES * PROPERTIES, f"a second materialization left {again} property definitions", None)
    unchanged = {row.id: row.version for row in db.query(ontology_runtime_v1.OntologyResourceDefinition).filter(
        ontology_runtime_v1.OntologyResourceDefinition.id.in_(list(resource_versions))).all()}
    check(unchanged == resource_versions, "re-materializing unchanged types bumped their versions", (unchanged, resource_versions))

print(f"Semantic materialization cost verified: {passed} assertions passed "
      f"(worst repeat {first['worst_repeat']} over {TYPES} types of {PROPERTIES} properties).")
engine.dispose()
tmpdir.cleanup()

"""A batch of pipeline edits applies whole or not at all, and only for an editor of the graph.

X5 of `GOAL_GRAPH_2026-09-23.md`. A paste is several nodes and the edges between
them; sent a node at a time it could stop halfway and leave a graph nobody made.
`POST /pipeline-builder/graphs/{id}/commands` takes the whole paste as one batch.
These assertions hold the three things the canvas relies on: a ref names a node
added earlier in the same batch, one bad command leaves the graph untouched, and
the batch is scoped to the graph's project like every other edit.
"""
import os
import tempfile

tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tmpdir.name, 'pipeline_commands.db')}"
os.environ["AUTH_MODE"] = "local"
os.environ["APP_ENV"] = "test"

from fastapi.testclient import TestClient  # noqa: E402
from app import production_auth  # noqa: E402
from app.main import app  # noqa: E402

client = TestClient(app)
passed = 0


def ok(response, label, expect=200):
    global passed
    assert response.status_code == expect, f"{label}: {response.status_code} {response.text[:1200]}"
    passed += 1
    return response.json() if response.content else {}


def check(condition, label, payload=None):
    global passed
    assert condition, f"{label}: {payload}"
    passed += 1


ok(client.post("/tenancy/organizations", json={"id": "commands-org", "display_name": "Commands Org"}), "create organization", 201)
for project_id in ("alpha-commands", "beta-commands"):
    ok(client.post("/tenancy/projects", json={
        "id": project_id, "organization_id": "commands-org", "display_name": project_id,
    }), f"create {project_id}", 201)

permissions = ["view", "edit", "execute", "deploy", "administer"]
alpha = production_auth.Principal("alpha-commands-user", "Alpha", None, ["administrator"], permissions,
                                  organization_id="commands-org", project_ids=["alpha-commands"])
beta = production_auth.Principal("beta-commands-user", "Beta", None, ["administrator"], permissions,
                                 organization_id="commands-org", project_ids=["beta-commands"])
viewer = production_auth.Principal("alpha-commands-viewer", "Viewer", None, ["viewer"], ["view"],
                                   organization_id="commands-org", project_ids=["alpha-commands"])

app.dependency_overrides[production_auth.current_principal] = lambda: alpha
ok(client.post("/pipeline-builder/graphs", json={
    "id": "commands-graph", "project_id": "alpha-commands", "display_name": "Commands graph",
    "nodes": [{"id": "source", "type": "filter", "config": {}, "position": {"x": 40, "y": 60}}],
    "edges": [],
}), "create graph", 201)
PATH = "/pipeline-builder/graphs/commands-graph/commands"


def graph():
    return ok(client.get("/pipeline-builder/graphs/commands-graph"), "read graph")


def edges_of(body):
    return sorted((edge["source"], edge["target"]) for edge in body["edges"])


# --- a paste: three nodes and the edges between them, in one request -----------------
pasted = ok(client.post(PATH, json={"commands": [
    {"op": "add_node", "ref": "a", "node_type": "filter", "label": "A copy", "position": {"x": 80, "y": 100}},
    {"op": "add_node", "ref": "b", "node_type": "filter", "label": "B copy", "position": {"x": 340, "y": 100}},
    {"op": "add_node", "ref": "c", "node_type": "rename", "label": "C copy", "position": {"x": 600, "y": 100}},
    {"op": "add_edge", "source": "a", "target": "b"},
    {"op": "add_edge", "source": "b", "target": "c"},
]}), "apply a paste")
created = pasted["created"]
check(sorted(created) == ["a", "b", "c"], "every ref comes back with the id it was given", created)
check(len(set(created.values())) == 3, "three nodes, three different ids", created)
check("nodes" in pasted and "validation" in pasted, "the response is the canvas", sorted(pasted))
after = graph()
check(len(after["nodes"]) == 4, "the graph holds the three pasted nodes and the one it had", after["nodes"])
check(edges_of(after) == sorted([(created["a"], created["b"]), (created["b"], created["c"])]),
      "the edges between the pasted nodes came with them", after["edges"])
positions = {node["id"]: node["position"] for node in after["nodes"]}
check(positions[created["c"]] == {"x": 600.0, "y": 100.0}, "a pasted node lands where the batch put it", positions)

# --- an edge between a node already there and one added in the batch -----------------
ok(client.post(PATH, json={"commands": [
    {"op": "add_node", "ref": "tail", "node_type": "filter"},
    {"op": "add_edge", "source": created["c"], "target": "tail"},
]}), "connect an existing node to a new one")
check(len(graph()["nodes"]) == 5, "the batch added its node", None)

# --- one bad command, and nothing applies -------------------------------------------
before = graph()
ok(client.post(PATH, json={"commands": [
    {"op": "add_node", "ref": "x", "node_type": "filter"},
    {"op": "add_edge", "source": "x", "target": "nobody"},
]}), "a batch naming a node that is not there", 422)
check(graph()["nodes"] == before["nodes"] and graph()["edges"] == before["edges"],
      "a refused batch left no node behind", graph()["nodes"])
ok(client.post(PATH, json={"commands": [
    {"op": "add_node", "ref": "x", "node_type": "no_such_type"},
]}), "a batch adding a type that does not exist", 422)
ok(client.post(PATH, json={"commands": [
    {"op": "add_node", "ref": "x", "node_type": "filter"}, {"op": "add_node", "ref": "x", "node_type": "filter"},
]}), "a batch using one ref twice", 422)
ok(client.post(PATH, json={"commands": [{"op": "add_edge", "source": "source", "target": "source"}]}),
   "a node fed by itself", 422)
ok(client.post(PATH, json={"commands": []}), "an empty batch", 422)
check(graph()["nodes"] == before["nodes"], "four refused batches changed nothing", None)

# --- the undo of a paste: its nodes, and their edges, go in one request ----------------
ok(client.post(PATH, json={"commands": [{"op": "delete_node", "node_id": node_id} for node_id in created.values()]}),
   "take back the paste")
left = graph()
check(sorted(node["id"] for node in left["nodes"]) == sorted(node["id"] for node in before["nodes"]
                                                                if node["id"] not in created.values()),
      "the pasted nodes are gone and nothing else is", left["nodes"])
check(not any(edge["source"] in created.values() or edge["target"] in created.values() for edge in left["edges"]),
      "and no edge still names one", left["edges"])

# --- an edge taken back by itself ----------------------------------------------------
tail = next(node["id"] for node in left["nodes"] if node["id"] != "source")
ok(client.post(PATH, json={"commands": [{"op": "add_edge", "source": "source", "target": tail}]}), "connect two nodes")
ok(client.post(PATH, json={"commands": [{"op": "delete_edge", "source": "source", "target": tail}]}), "take the edge back")
check(("source", tail) not in edges_of(graph()), "the edge is gone", graph()["edges"])
ok(client.post(PATH, json={"commands": [{"op": "delete_edge", "source": "source", "target": tail}]}),
   "taking back an edge that is not there", 422)

# --- scoped like every other edit ----------------------------------------------------
app.dependency_overrides[production_auth.current_principal] = lambda: beta
ok(client.post(PATH, json={"commands": [{"op": "add_node", "node_type": "filter"}]}),
   "another project's editor may not edit this graph", 403)
app.dependency_overrides[production_auth.current_principal] = lambda: viewer
ok(client.post(PATH, json={"commands": [{"op": "add_node", "node_type": "filter"}]}),
   "a viewer may not edit it", 403)
app.dependency_overrides[production_auth.current_principal] = lambda: alpha
check(len(graph()["nodes"]) == len(left["nodes"]), "neither refused edit landed", graph()["nodes"])

app.dependency_overrides.clear()
print(f"Pipeline commands verified: {passed} assertions passed.")

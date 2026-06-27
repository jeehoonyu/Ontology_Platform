"""
Standalone self-test for app.dev_toolchain (owned file).

Builds a local FastAPI app from ONLY the dev_toolchain router — does NOT import
app.main (sibling files are edited concurrently). Covers the three deepenings:
  (1) Code Workbook /run honors the node DAG (topological order via depends_on /
      inputs), returns per-node preview + row_count, and a 'failed' path that
      marks the erroring node failed and downstream nodes skipped.
  (2) Code Repositories pull-request + branch protection: /merge enforces
      required approvals (reject merge if PR unapproved); default (no protection)
      merge still works.
  (3) Compute Modules: register/list typed functions and start/stop/status
      lifecycle.

Run from oms/:  ./venv312/Scripts/python.exe test_dev_toolchain.py
"""
import os
import tempfile

_t = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(_t.name, 't.db')}"

from fastapi import FastAPI                       # noqa: E402
from fastapi.testclient import TestClient         # noqa: E402
from app.database import Base, engine             # noqa: E402
from app import models, models_action             # noqa: E402  (registers core + audit tables)
from app import dev_toolchain as M                # noqa: E402  (registers this module's tables)

Base.metadata.create_all(bind=engine)
api = FastAPI()
api.include_router(M.router)
client = TestClient(api)

passed = 0


def ok(resp, label, expect=200):
    global passed
    success = resp.status_code == expect or (expect == 200 and 200 <= resp.status_code < 300)
    assert success, f"{label}: expected {expect}, got {resp.status_code} -> {resp.text[:400]}"
    passed += 1
    return resp.json() if resp.content else {}


def check(cond, label):
    global passed
    assert cond, f"CHECK FAILED: {label}"
    passed += 1


# ===========================================================================
# (1) CODE WORKBOOK — DAG-aware run
# ===========================================================================
# Nodes declared deliberately OUT of dependency order to prove topo sorting:
#   n3 depends_on n2 ; n2 depends_on n1 (via legacy 'inputs') ; n1 is a root.
ok(client.post("/code-workbooks", json={
    "id": "wb_dag", "display_name": "DAG", "language": "python",
    "nodes": [
        {"id": "n3", "name": "final", "code": "z=3", "depends_on": ["n2"]},
        {"id": "n1", "name": "load", "code": "x=1", "row_count": 7},
        {"id": "n2", "name": "agg", "code": "y=2", "inputs": ["n1"]},
    ],
}), "workbook DAG create", expect=201)

run = ok(client.post("/code-workbooks/wb_dag/run"), "workbook DAG run")
check(run["status"] == "COMPLETED", "DAG run completed")
# Topological order must respect dependencies: n1 before n2 before n3.
order = run["execution_order"]
check(order.index("n1") < order.index("n2") < order.index("n3"), "topological order honored")
# Per-node preview + row_count surfaced.
by_node = {r["node_id"]: r for r in run["node_results"]}
check(by_node["n1"]["row_count"] == 7, "node n1 row_count from spec")
check(isinstance(by_node["n1"]["preview"], list) and len(by_node["n1"]["preview"]) > 0,
      "node n1 has preview rows")
check(all(r["status"] == "success" for r in run["node_results"]), "all nodes success on clean DAG")

# ---- legacy shape preserved: 'inputs'-only nodes still all reported -------
ok(client.post("/code-workbooks", json={
    "id": "wb1", "display_name": "Explore", "language": "python",
    "nodes": [{"id": "n1", "name": "load", "code": "x=1"},
              {"id": "n2", "name": "agg", "code": "y=2", "inputs": ["n1"]}],
}), "legacy workbook create", expect=201)
wr = ok(client.post("/code-workbooks/wb1/run"), "legacy workbook run")
check(len(wr["node_results"]) == 2, "legacy run reports both nodes (preserved)")

# ---- FAILED path: a node that errors marks itself failed + downstream skipped
ok(client.post("/code-workbooks", json={
    "id": "wb_fail", "display_name": "Fail", "language": "python",
    "nodes": [
        {"id": "a", "name": "root", "code": "x=1"},
        {"id": "b", "name": "boom", "fail": True, "depends_on": ["a"]},
        {"id": "c", "name": "downstream", "code": "y=1", "depends_on": ["b"]},
    ],
}), "failing workbook create", expect=201)
fr = ok(client.post("/code-workbooks/wb_fail/run"), "failing workbook run")
check(fr["status"] == "FAILED", "run overall status FAILED when a node errors")
fmap = {r["node_id"]: r for r in fr["node_results"]}
check(fmap["a"]["status"] == "success", "root node still success")
check(fmap["b"]["status"] == "failed", "erroring node marked failed")
check(fmap["c"]["status"] == "skipped", "downstream of failure marked skipped (not success)")

# A node whose code contains a raise statement is also detected as failed.
ok(client.post("/code-workbooks", json={
    "id": "wb_raise", "display_name": "Raise", "language": "python",
    "nodes": [{"id": "r", "name": "r", "code": "raise ValueError('x')"}],
}), "raise workbook create", expect=201)
rr = ok(client.post("/code-workbooks/wb_raise/run"), "raise workbook run")
check(rr["node_results"][0]["status"] == "failed", "raise-in-code detected as failed")

# 404 path preserved.
ok(client.post("/code-workbooks/nope/run"), "missing workbook run 404", expect=404)


# ===========================================================================
# (2) CODE REPOSITORIES — pull requests + branch protection
# ===========================================================================
ok(client.post("/code-repositories", json={"id": "repo1", "display_name": "Pipelines", "language": "python"}),
   "repo create", expect=201)
ok(client.post("/code-repositories/repo1/branches", json={"name": "feature-x"}), "repo branch", expect=201)
ok(client.put("/code-repositories/repo1/files",
              json={"branch": "feature-x", "path": "clean.py", "content": "print(1)"}), "repo file put")
ok(client.post("/code-repositories/repo1/commits",
               json={"branch": "feature-x", "message": "add clean", "author": "me",
                     "changes": [{"path": "clean.py", "action": "add"}]}), "repo commit", expect=201)
chk = ok(client.post("/code-repositories/repo1/checks/run", params={"branch": "feature-x"}), "repo checks")
check(chk["status"] == "passed", "checks pass with files (preserved)")

# ---- DEFAULT (unprotected) merge still works without any PR (preserved) ----
mg = ok(client.post("/code-repositories/repo1/merge", params={"branch": "feature-x"}), "unprotected merge")
check(mg["files_merged"] >= 1, "unprotected merge moved files (legacy behavior preserved)")

# ---- Now PROTECT master and prove merge is gated on approvals --------------
ok(client.post("/code-repositories", json={"id": "repo2", "display_name": "Gated", "language": "python"}),
   "repo2 create", expect=201)
ok(client.post("/code-repositories/repo2/branches", json={"name": "feat"}), "repo2 branch", expect=201)
ok(client.put("/code-repositories/repo2/files",
              json={"branch": "feat", "path": "f.py", "content": "1"}), "repo2 file put")
ok(client.put("/code-repositories/repo2/branch-protection",
              json={"branch": "master", "required_approvals": 1}), "set branch protection")
prot = ok(client.get("/code-repositories/repo2/branch-protection"), "list branch protection")
check(len(prot) == 1 and prot[0]["required_approvals"] == 1, "protection persisted")

# Merge with NO open PR on a protected branch is rejected.
ok(client.post("/code-repositories/repo2/merge", params={"branch": "feat"}),
   "protected merge without PR rejected", expect=409)

# Open a PR, then merge while UNAPPROVED -> rejected.
pr = ok(client.post("/code-repositories/repo2/pull-requests",
                    json={"id": "pr1", "title": "Add f", "source_branch": "feat", "author": "me"}),
        "create pull request", expect=201)
check(pr["status"] == "open" and pr["target_branch"] == "master", "PR opened against default branch")
ok(client.post("/code-repositories/repo2/merge", params={"branch": "feat"}),
   "protected merge unapproved rejected", expect=409)

# Approve, then merge succeeds and PR flips to merged.
appr = ok(client.post("/code-repositories/repo2/pull-requests/pr1/approve", json={"reviewer": "lead"}),
          "approve PR")
check(len(appr["approvals"]) == 1, "approval recorded")
mg2 = ok(client.post("/code-repositories/repo2/merge", params={"branch": "feat"}), "approved merge succeeds")
check(mg2["files_merged"] >= 1 and mg2["pull_request_id"] == "pr1", "approved merge moved files + linked PR")
pr_after = ok(client.get("/code-repositories/repo2/pull-requests/pr1"), "get PR after merge")
check(pr_after["status"] == "merged", "PR marked merged after merge")

# require_passing_checks gate.
ok(client.post("/code-repositories", json={"id": "repo3", "display_name": "Checks", "language": "python"}),
   "repo3 create", expect=201)
ok(client.post("/code-repositories/repo3/branches", json={"name": "wip"}), "repo3 branch", expect=201)
ok(client.put("/code-repositories/repo3/files", json={"branch": "wip", "path": "g.py", "content": "1"}),
   "repo3 file put")
ok(client.put("/code-repositories/repo3/branch-protection",
              json={"branch": "master", "required_approvals": 0, "require_passing_checks": True}),
   "set check-required protection")
pr3 = ok(client.post("/code-repositories/repo3/pull-requests",
                     json={"id": "pr3", "title": "wip", "source_branch": "wip"}), "create PR3", expect=201)
check(pr3["checks_status"] == "pending", "PR3 checks pending (no commit yet)")
ok(client.post("/code-repositories/repo3/merge", params={"branch": "wip"}),
   "merge blocked on failing/pending checks", expect=409)


# ===========================================================================
# (3) COMPUTE MODULES — typed functions + start/stop/status lifecycle
# ===========================================================================
cm = ok(client.post("/devtools/compute-modules",
                    json={"id": "cm1", "display_name": "Anomaly", "namespace": "acme", "language": "python"}),
        "compute module create", expect=201)
check(cm["status"] == "Stopped" and cm["replicas"] == 0, "module starts Stopped with 0 replicas")

fn = ok(client.post("/devtools/compute-modules/cm1/functions",
                    json={"name": "detect_anomalies",
                          "inputs": [{"name": "records", "type": "array", "required": True},
                                     {"name": "threshold", "type": "float", "required": False}],
                          "output": {"type": "struct"}}),
        "register typed function", expect=201)
check(fn["api_name"] == "com.acme.computemodules.DetectAnomalies", "api_name derived per Foundry convention")
check(len(fn["inputs"]) == 2 and fn["output"]["type"] == "struct", "typed inputs + output stored")

fns = ok(client.get("/devtools/compute-modules/cm1/functions"), "list functions")
check(len(fns) == 1, "function listed")

# Lifecycle: start -> Running with >=1 replica.
started = ok(client.post("/devtools/compute-modules/cm1/lifecycle", json={"action": "start"}), "start module")
check(started["status"] == "Running" and started["replicas"] >= 1, "module Running after start")
st = ok(client.get("/devtools/compute-modules/cm1/status"), "module status")
check(st["status"] == "Running" and st["function_count"] == 1, "status reports Running + function count")

# Lifecycle: stop -> Stopped, 0 replicas.
stopped = ok(client.post("/devtools/compute-modules/cm1/lifecycle", json={"action": "stop"}), "stop module")
check(stopped["status"] == "Stopped" and stopped["replicas"] == 0, "module Stopped after stop")

# Invalid action rejected.
ok(client.post("/devtools/compute-modules/cm1/lifecycle", json={"action": "frobnicate"}),
   "invalid lifecycle action rejected", expect=422)
# Missing module 404.
ok(client.get("/devtools/compute-modules/missing/status"), "missing module status 404", expect=404)


# ===========================================================================
# Audit log persisted (cross-cutting sanity).
# ===========================================================================
from app.database import SessionLocal  # noqa: E402
_db = SessionLocal()
n_audit = _db.query(models_action.AuditLog).count()
_db.close()
check(n_audit > 0, "audit logs written")

print(f"\n{passed} assertions passed")

"""A dataset's transactions, branches, schema and file belong to the dataset's project.

`app/datasets_ext.py` served ten routes behind one router guard: the caller may edit
somewhere. Seven handlers loaded the dataset by id and three never loaded it, so an
editor in one project could read and write another project's transaction log,
branches, declared schema and uploaded file. Each route now resolves the dataset
through `semantic_scope.asset_for`, `edit` for the four writes and `view` for the
six reads. This holds every route both ways -- the owner's editor can, another
project's editor cannot -- and checks that a refused write left nothing behind.
"""
import os
import tempfile

tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tmpdir.name, 'datasets_ext_tenancy.db')}"
os.environ["AUTH_MODE"] = "local"
os.environ["APP_ENV"] = "test"
os.environ.setdefault("OBJECT_STORE_ROOT", os.path.join(tmpdir.name, "objects"))

from fastapi.testclient import TestClient  # noqa: E402
from app import models, models_action, production_auth  # noqa: E402
from app.database import SessionLocal  # noqa: E402
from app.datasets_ext import DatasetBranch, DatasetSchemaDef, DatasetTransaction  # noqa: E402
from app.main import app  # noqa: E402

client = TestClient(app)
passed = 0


def ok(response, label, expect=200):
    global passed
    assert response.status_code == expect, f"{label}: {response.status_code} {response.text[:600]}"
    passed += 1
    return response.json() if response.content and "json" in response.headers.get("content-type", "") else response


def check(condition, label, payload=None):
    global passed
    assert condition, f"{label}: {payload}"
    passed += 1


ok(client.post("/tenancy/organizations", json={"id": "datasets-org", "display_name": "Datasets Org"}), "create organization", 201)
for project_id in ("alpha-datasets", "beta-datasets"):
    ok(client.post("/tenancy/projects", json={
        "id": project_id, "organization_id": "datasets-org", "display_name": project_id,
    }), f"create {project_id}", 201)

with SessionLocal() as db:
    for dataset_id, project_id in (("alpha-data", "alpha-datasets"), ("beta-data", "beta-datasets")):
        db.add(models.DataAsset(id=dataset_id, project_id=project_id, display_name=dataset_id, description=None,
                                kind="dataset", asset_schema={"project_id": project_id},
                                records=[{"id": "r1", "value": 1}], created_at=1, updated_at=1))
    db.commit()

permissions = ["view", "edit", "execute", "deploy", "administer"]
alpha = production_auth.Principal("alpha-datasets-user", "Alpha", None, ["administrator"], permissions,
                                  organization_id="datasets-org", project_ids=["alpha-datasets"])


def every_route(dataset_id):
    """Each of the ten routes, as (label, call, status an owner gets)."""
    base = f"/datasets/{dataset_id}"
    return [
        ("POST transactions", lambda: client.post(f"{base}/transactions", json={
            "txn_type": "APPEND", "branch": "master", "primary_key": "id", "records": [{"id": "r2", "value": 2}]}), 201),
        ("GET transactions", lambda: client.get(f"{base}/transactions"), 200),
        ("GET view", lambda: client.get(f"{base}/view"), 200),
        ("GET changes", lambda: client.get(f"{base}/changes"), 200),
        ("POST branches", lambda: client.post(f"{base}/branches", json={"name": f"work-{dataset_id}", "base_branch": "master"}), 201),
        ("GET branches", lambda: client.get(f"{base}/branches"), 200),
        ("PUT schema", lambda: client.put(f"{base}/schema", json={"columns": [{"name": "id", "type": "string"}]}), 200),
        ("GET schema", lambda: client.get(f"{base}/schema"), 200),
        ("POST upload", lambda: client.post(f"/data-assets/{dataset_id}/upload",
                                            files={"file": ("rows.csv", b"id,value\nr3,3\n", "text/csv")},
                                            data={"mode": "append"}), 200),
        ("GET download", lambda: client.get(f"/data-assets/{dataset_id}/download"), 200),
    ]


app.dependency_overrides[production_auth.current_principal] = lambda: alpha

# --- the owner's editor reaches every route on their own dataset -------------------
for label, call, status in every_route("alpha-data"):
    ok(call(), f"{label} on the caller's own dataset", status)
# The caller's own writes name the caller. A baseline the system records of rows the
# log never saw (`dataset.transaction.baseline_recorded`) is the system's, and says so.
WRITES = ("dataset.transaction.committed", "dataset.branch.created", "dataset.schema.upserted", "data.asset.uploaded")
with SessionLocal() as db:
    actors = {row.event_type: row.actor for row in db.query(models_action.AuditLog)
              .filter(models_action.AuditLog.subject_id == "alpha-data").all()}
check(all(actors.get(event) == "alpha-datasets-user" for event in WRITES),
      "the audit rows for a dataset's writes do not name the caller", actors)

# --- and none on another project's -------------------------------------------------
for label, call, _ in every_route("beta-data"):
    ok(call(), f"{label} on another project's dataset is refused", 403)
with SessionLocal() as db:
    beta = db.get(models.DataAsset, "beta-data")
    check(beta.records == [{"id": "r1", "value": 1}], "a refused write changed another project's rows", beta.records)
    check(beta.file_ref is None, "a refused upload stored a file on another project's dataset", beta.file_ref)
    check(not db.query(DatasetTransaction).filter(DatasetTransaction.dataset_id == "beta-data").count(),
          "a refused transaction or branch wrote to another project's log", None)
    check(not db.query(DatasetBranch).filter(DatasetBranch.dataset_id == "beta-data").count(),
          "a refused branch was created on another project's dataset", None)
    check(db.get(DatasetSchemaDef, "beta-data") is None,
          "a refused schema was declared on another project's dataset", None)

# --- a dataset that does not exist is not found, on every route ---------------------
for label, call, _ in every_route("no-such-data"):
    ok(call(), f"{label} on a dataset that does not exist", 404)

app.dependency_overrides.clear()
print(f"Dataset routes scoped to their project: {passed} assertions passed.")

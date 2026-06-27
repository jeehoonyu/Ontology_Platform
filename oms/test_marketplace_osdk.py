"""
Deep-fidelity pass 10 conformance test:
  Marketplace — declared requirements, install validation, dependency-resolved install
                with prefix, release snapshots + upgrade diff.
  OSDK — richer typed client generation (objects+properties, link traversal, actions, functions).
  Compute Modules — deterministic transform run (filter -> aggregate).
Run: ./venv312/Scripts/python.exe test_marketplace_osdk.py
"""
import os
import tempfile

tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tmpdir.name, 'mkt_osdk.db')}"

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


# ================= Marketplace dependency-resolved install =================
ok(client.post("/devops/products", json={"id": "prod", "display_name": "CRM",
    "resources": [{"kind": "object_type", "id": "customer"}, {"kind": "dataset", "id": "sales"}]}), "product")
ok(client.post("/devops/products/prod/requirements", json={"key": "raw_input", "kind": "dataset", "required": True}), "requirement")
rel1 = ok(client.post("/devops/products/prod/releases", json={"version": "1.0.0", "channel": "stable"}), "release1")

v_missing = ok(client.post("/marketplace/prod/validate-install", json={"input_mappings": {}}), "validate missing")
assert v_missing["valid"] is False and v_missing["missing_inputs"] == ["raw_input"], v_missing
v_bad = ok(client.post("/marketplace/prod/validate-install", json={"input_mappings": {"raw_input": "nope"}}), "validate unresolved")
assert v_bad["valid"] is False and v_bad["unresolved_inputs"][0]["exists"] is False, v_bad
ok(client.post("/data-assets", json={"id": "my_raw", "display_name": "raw", "kind": "dataset", "asset_schema": {}, "records": []}), "raw asset")
v_ok = ok(client.post("/marketplace/prod/validate-install", json={"input_mappings": {"raw_input": "my_raw"}}), "validate ok")
assert v_ok["valid"] is True, v_ok

# install blocked when required input missing
ok(client.post("/marketplace/prod/install-resolved", json={"target_project": "p", "input_mappings": {}}), "install blocked", expect=422)
inst = ok(client.post("/marketplace/prod/install-resolved", json={
    "target_project": "proj", "input_mappings": {"raw_input": "my_raw"}, "prefix": "[DEV]", "suffix": "_v1"}), "install ok")
created = {c["kind"]: c["installed_as"] for c in inst["created_content"]}
assert created["object_type"] == "[DEV]customer", created      # prefix applied to ontology entities
assert created["dataset"] == "sales", created                  # not to datasets
assert inst["target_project"] == "proj_v1", inst               # suffix applied to project

# upgrade diff between two snapshots (different products to force a real diff)
ok(client.post("/devops/products", json={"id": "prod2", "display_name": "CRM v2",
    "resources": [{"kind": "object_type", "id": "customer"}, {"kind": "object_type", "id": "orders"}]}), "product2")
rel2 = ok(client.post("/devops/products/prod2/releases", json={"version": "2.0.0", "channel": "stable"}), "release2")
ok(client.post(f"/devops/products/prod/releases/{rel1['id']}/snapshot"), "snap1")
ok(client.post(f"/devops/products/prod2/releases/{rel2['id']}/snapshot"), "snap2")
diff = ok(client.post("/marketplace/upgrade-diff", json={"from_release_id": rel1["id"], "to_release_id": rel2["id"]}), "upgrade diff")
assert diff["added"] == ["orders"] and diff["removed"] == ["sales"] and diff["unchanged"] == ["customer"], diff

# ================= OSDK richer generation =================
ok(client.post("/object-types", json={"id": "customer", "display_name": "Customer", "description": "",
    "properties": {"id": {"type": "string"}, "name": {"type": "string"}, "score": {"type": "number"}}}), "customer type")
ok(client.post("/object-types", json={"id": "order", "display_name": "Order", "description": "",
    "properties": {"id": {"type": "string"}, "total": {"type": "number"}}}), "order type")
ok(client.post("/link-types", json={"id": "placed", "display_name": "placed", "source_object_type_id": "customer",
    "target_object_type_id": "order", "cardinality": "ONE_TO_MANY"}), "link type")
ok(client.post("/action-types", json={"id": "promote", "display_name": "Promote", "description": "",
    "parameters": {"customer_id": {"type": "string", "required": True}}, "rules": {}}), "action type")
ok(client.post("/ontology-functions", json={"id": "cust_count", "display_name": "Count", "kind": "compute",
    "object_type_id": "customer", "expression": {"type": "aggregate", "op": "count"}}), "ont function")

gen = ok(client.post("/osdk/generate-client", json={}), "osdk generate")
assert gen["object_type_count"] == 2 and gen["action_count"] >= 1 and gen["function_count"] >= 1, gen
cust = next(s for s in gen["sdk"] if s["object_type_id"] == "customer")
assert cust["properties"] == ["id", "name", "score"], cust
assert any(l["target"] == "order" for l in cust["links"]), cust["links"]
assert "export interface Customer" in cust["typescript"] and "@dataclass" in cust["python"], cust
assert any(a["action_type_id"] == "promote" and a["parameters"] == ["customer_id"] for a in gen["actions"]), gen["actions"]

# ================= Compute Module transform =================
ok(client.post("/compute-modules", json={"id": "cm", "display_name": "CM", "image": "img:1", "entrypoint": "run"}), "compute module")
run = ok(client.post("/compute-modules/cm/run", json={
    "records": [{"a": 1, "k": "x"}, {"a": 2, "k": "x"}, {"a": 3, "k": "y"}],
    "spec": [{"op": "filter", "field": "k", "equals": "x"}, {"op": "aggregate", "field": "a", "agg": "sum"}]}), "compute run")
assert run["result"] == 3, run  # filter k==x (a=1,2) then sum a = 3

print(f"\nMarketplace + OSDK + Compute deep mechanics verified: {passed} assertions passed.")
from app.database import engine as _engine  # noqa: E402
_engine.dispose()
tmpdir.cleanup()

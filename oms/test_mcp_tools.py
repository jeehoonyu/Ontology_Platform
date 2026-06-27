"""
Palantir MCP callable tools — conformance test.
Tool catalog + dispatch (search/query/aggregate/sql) + mutation proposal gate.
Run: ./venv312/Scripts/python.exe test_mcp_tools.py
"""
import os
import tempfile

_tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(_tmp.name, 'mcp.db')}"

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from app.database import Base, engine, SessionLocal  # noqa: E402
from app import models, models_action  # noqa: E402
from app import mcp_tools as M  # noqa: E402

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


# ---- seed ontology + dataset directly ----
db = SessionLocal()
db.add(models.ObjectType(id="customer", display_name="Customer", description="", properties={}, created_at=1, updated_at=1))
for i, (tier, spend) in enumerate([("gold", 100), ("gold", 300), ("silver", 50)]):
    db.add(models.ObjectInstance(id=f"c{i}", object_type_id="customer",
                                 properties={"tier": tier, "spend": spend}, lineage={}, created_at=1, updated_at=1))
db.add(models.DataAsset(id="sales", display_name="Sales", description="", kind="dataset", asset_schema={},
                        records=[{"region": "EMEA", "amt": 10}, {"region": "EMEA", "amt": 30}, {"region": "APAC", "amt": 20}],
                        created_at=1, updated_at=1))
db.commit()
db.close()

# ---- catalog ----
cat = ok(client.get("/mcp/tools"), "catalog")
names = {t["name"] for t in cat["tools"]}
assert "search_foundry_ontology" in names and "create_or_update_foundry_object_type" in names, names
assert len(cat["tools"]) >= 5, cat
ok(client.post("/mcp/tools/nope/call", json={"arguments": {}}), "unknown tool", expect=404)

# ---- search ----
s = ok(client.post("/mcp/tools/search_foundry_ontology/call", json={"arguments": {"keyword": "cust"}}), "search")
assert any(o["id"] == "customer" for o in s["result"]["object_types"]), s

# ---- query ----
q = ok(client.post("/mcp/tools/query_foundry_objects/call",
                   json={"arguments": {"object_type_id": "customer", "filters": {"tier": "gold"}}}), "query")
assert q["result"]["count"] == 2, q

# ---- aggregate (sum spend by tier) ----
a = ok(client.post("/mcp/tools/aggregate_foundry_objects/call",
                   json={"arguments": {"object_type_id": "customer", "group_by": "tier", "metric": "spend", "agg": "sum"}}), "agg")
by_tier = {g["group"]: g for g in a["result"]["groups"]}
assert by_tier["gold"]["value"] == 400 and by_tier["gold"]["count"] == 2, a
assert by_tier["silver"]["value"] == 50, a

# ---- sql over a dataset (group + sum) ----
sql = ok(client.post("/mcp/tools/run_sql_query_on_foundry_dataset/call",
                     json={"arguments": {"dataset_id": "sales", "group_by": "region",
                                         "aggregate": {"field": "amt", "func": "sum"}}}), "sql group")
rows = {r["region"]: r for r in sql["result"]["rows"]}
assert rows["EMEA"]["sum_amt"] == 40 and rows["EMEA"]["count"] == 2 and rows["APAC"]["sum_amt"] == 20, sql
# sql with where + select
sql2 = ok(client.post("/mcp/tools/run_sql_query_on_foundry_dataset/call",
                      json={"arguments": {"dataset_id": "sales", "where": {"region": "APAC"}, "select": ["amt"]}}), "sql where")
assert sql2["result"]["row_count"] == 1 and sql2["result"]["rows"] == [{"amt": 20}], sql2

# ---- proposal gate on a mutating tool ----
staged = ok(client.post("/mcp/tools/create_or_update_foundry_object_type/call",
                        json={"arguments": {"id": "vendor", "display_name": "Vendor", "properties": {}}}), "staged upsert")
assert staged["staged"] is True and "proposal_id" in staged, staged
# not yet applied
chk = ok(client.post("/mcp/tools/search_foundry_ontology/call", json={"arguments": {"keyword": "vendor"}}), "search vendor pre")
assert not chk["result"]["object_types"], chk
# commit the proposal -> now it exists
ok(client.post(f"/mcp/proposals/{staged['proposal_id']}/commit"), "commit proposal")
chk2 = ok(client.post("/mcp/tools/search_foundry_ontology/call", json={"arguments": {"keyword": "vendor"}}), "search vendor post")
assert any(o["id"] == "vendor" for o in chk2["result"]["object_types"]), chk2
# committing twice fails
ok(client.post(f"/mcp/proposals/{staged['proposal_id']}/commit"), "double commit", expect=400)

# ---- direct commit=true bypasses staging ----
direct = ok(client.post("/mcp/tools/create_or_update_foundry_object_type/call",
                        json={"arguments": {"id": "partner", "display_name": "Partner", "properties": {}}, "commit": True}), "direct upsert")
assert direct["staged"] is False and direct["result"]["action"] == "created", direct

print(f"\nPalantir MCP tools verified: {passed} assertions passed.")
engine.dispose()
_tmp.cleanup()

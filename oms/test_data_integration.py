"""
Deep-fidelity pass 4 (Data integration) conformance test:
  * Pipeline Builder transform DSL: join, aggregate, union, dedupe, cast, rename, sort, limit
  * Dataset transactions (SNAPSHOT/APPEND/UPDATE/DELETE), branches, time-travel, incremental changes
Run: ./venv312/Scripts/python.exe test_data_integration.py
"""
import os
import tempfile

tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tmpdir.name, 'data_int.db')}"

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


def mk_asset(aid, records):
    ok(client.post("/data-assets", json={"id": aid, "display_name": aid, "kind": "dataset",
        "asset_schema": {}, "records": records}), f"asset {aid}")


# ============ Pipeline DSL: dedupe -> join -> aggregate -> sort ============
mk_asset("orders", [{"id": 1, "cust": "A", "amt": 10}, {"id": 2, "cust": "A", "amt": 20},
                     {"id": 3, "cust": "B", "amt": 5}, {"id": 3, "cust": "B", "amt": 5}])
mk_asset("customers", [{"cust": "A", "region": "West"}, {"cust": "B", "region": "East"}])
mk_asset("orders_out", [])

ok(client.post("/pipelines", json={"id": "p_agg", "display_name": "Agg", "input_asset_id": "orders",
    "output_asset_id": "orders_out", "steps": [
        {"operation": "dedupe", "keys": ["id"]},
        {"operation": "join", "right_asset_id": "customers", "on": "cust"},
        {"operation": "aggregate", "group_by": ["region"], "aggregations": [
            {"op": "sum", "field": "amt", "as": "total"}, {"op": "count", "as": "n"}]},
        {"operation": "sort", "field": "total", "desc": True},
    ]}), "create p_agg")
run = ok(client.post("/pipelines/p_agg/run"), "run p_agg")
out = ok(client.get(f"/data-assets/{run['output_asset_id']}"), "agg output")["records"]
assert out == [{"region": "West", "total": 30, "n": 2}, {"region": "East", "total": 5, "n": 1}], out

# ============ Pipeline DSL: union -> cast -> rename -> limit ============
mk_asset("more_orders", [{"id": 5, "cust": "C", "amt": "7"}])
mk_asset("orders_out2", [])
ok(client.post("/pipelines", json={"id": "p_uc", "display_name": "UnionCast", "input_asset_id": "orders",
    "output_asset_id": "orders_out2", "steps": [
        {"operation": "union", "asset_id": "more_orders"},
        {"operation": "cast", "field": "amt", "to": "integer"},
        {"operation": "rename", "mapping": {"amt": "amount"}},
        {"operation": "limit", "count": 2},
    ]}), "create p_uc")
run2 = ok(client.post("/pipelines/p_uc/run"), "run p_uc")
out2 = ok(client.get(f"/data-assets/{run2['output_asset_id']}"), "uc output")["records"]
assert len(out2) == 2, out2
assert "amount" in out2[0] and "amt" not in out2[0], out2[0]
assert out2[0]["amount"] == 10 and isinstance(out2[0]["amount"], int), out2[0]

# ============ Dataset transactions / branches / time-travel / incremental ============
mk_asset("ledger", [])
ok(client.post("/datasets/ledger/transactions", json={"txn_type": "SNAPSHOT", "primary_key": "id",
    "records": [{"id": 1, "v": 10}, {"id": 2, "v": 20}]}), "snapshot")
assert ok(client.get("/datasets/ledger/view"), "view1")["row_count"] == 2
ok(client.post("/datasets/ledger/transactions", json={"txn_type": "APPEND", "primary_key": "id", "records": [{"id": 3, "v": 30}]}), "append")
assert ok(client.get("/datasets/ledger/view"), "view2")["row_count"] == 3
ok(client.post("/datasets/ledger/transactions", json={"txn_type": "UPDATE", "primary_key": "id", "records": [{"id": 1, "v": 99}]}), "update")
view3 = ok(client.get("/datasets/ledger/view"), "view3")
assert next(r for r in view3["rows"] if r["id"] == 1)["v"] == 99, view3["rows"]
ok(client.post("/datasets/ledger/transactions", json={"txn_type": "DELETE", "primary_key": "id", "records": [{"id": 2}]}), "delete")
view4 = ok(client.get("/datasets/ledger/view"), "view4")
assert view4["row_count"] == 2 and all(r["id"] != 2 for r in view4["rows"]), view4

# time-travel back to the initial snapshot (seq 0)
past = ok(client.get("/datasets/ledger/view", params={"as_of_seq": 0}), "time-travel")
assert past["row_count"] == 2 and next(r for r in past["rows"] if r["id"] == 1)["v"] == 10, past

# incremental delta after seq 1 (UPDATE seq2 counts; DELETE seq3 excluded)
chg = ok(client.get("/datasets/ledger/changes", params={"since_seq": 1}), "changes")
assert chg["change_count"] == 1 and chg["changes"][0]["v"] == 99, chg

# the DataAsset.records mirror tracks the master view
assert len(ok(client.get("/data-assets/ledger"), "mirror")["records"]) == 2

# branch isolation
br = ok(client.post("/datasets/ledger/branches", json={"name": "dev"}), "branch")
assert br["seeded_rows"] == 2, br
ok(client.post("/datasets/ledger/transactions", json={"branch": "dev", "txn_type": "APPEND", "primary_key": "id", "records": [{"id": 4, "v": 40}]}), "dev append")
assert ok(client.get("/datasets/ledger/view", params={"branch": "dev"}), "dev view")["row_count"] == 3
assert ok(client.get("/datasets/ledger/view"), "master view")["row_count"] == 2  # master unaffected

print(f"\nData integration faithful behaviors verified: {passed} assertions passed.")
from app.database import engine as _engine  # noqa: E402
_engine.dispose()
tmpdir.cleanup()

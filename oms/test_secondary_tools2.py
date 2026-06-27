"""
Deep-fidelity pass 8 conformance test:
  Cipher (key rotation, bulk column encrypt/tokenize/decrypt with license gate),
  Security (resource markings, lineage propagation, access decision),
  Contour (pivot/sort/top_n/summary boards), Object Explorer (histogram/property-stats).
Run: ./venv312/Scripts/python.exe test_secondary_tools2.py
"""
import os
import tempfile

tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tmpdir.name, 'secondary2.db')}"

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


# ================= Cipher: rotation + bulk transform + license gate =================
ok(client.post("/cipher/channels", json={"id": "ch", "display_name": "PII", "mode": "encrypt", "key_ref": "k0"}), "channel")
rot = ok(client.post("/cipher/channels/ch/rotate"), "rotate1")
assert rot["active_version"] == 1, rot
rot2 = ok(client.post("/cipher/channels/ch/rotate"), "rotate2")
assert rot2["active_version"] == 2, rot2
keys = ok(client.get("/cipher/channels/ch/keys"), "keys")
assert len(keys) == 2 and sum(1 for k in keys if k["active"]) == 1, keys

rows = [{"id": 1, "ssn": "111-22-3333"}, {"id": 2, "ssn": "444-55-6666"}]
enc = ok(client.post("/cipher/bulk-transform", json={"channel_id": "ch", "records": rows, "field": "ssn", "mode": "encrypt"}), "bulk encrypt")
assert all(r["ssn"].startswith("enc:") for r in enc["records"]), enc["records"]
dec = ok(client.post("/cipher/bulk-transform", json={"channel_id": "ch", "records": enc["records"], "field": "ssn", "mode": "decrypt", "principal": "u1"}), "bulk decrypt (no license)", expect=403)
# grant license then decrypt
ok(client.post("/cipher/channels/ch/licenses", json={"principal": "u1"}), "license")
dec2 = ok(client.post("/cipher/bulk-transform", json={"channel_id": "ch", "records": enc["records"], "field": "ssn", "mode": "decrypt", "principal": "u1"}), "bulk decrypt")
assert dec2["records"][0]["ssn"] == "111-22-3333", dec2["records"]
# tokenize is consistent + reversible via vault
tok = ok(client.post("/cipher/bulk-transform", json={"channel_id": "ch", "records": rows, "field": "ssn", "mode": "tokenize"}), "tokenize")
assert tok["records"][0]["ssn"].startswith("tok_"), tok
tok_again = ok(client.post("/cipher/bulk-transform", json={"channel_id": "ch", "records": [rows[0]], "field": "ssn", "mode": "tokenize"}), "tokenize again")
assert tok_again["records"][0]["ssn"] == tok["records"][0]["ssn"], "token must be consistent"
detok = ok(client.post("/cipher/bulk-transform", json={"channel_id": "ch", "records": tok["records"], "field": "ssn", "mode": "decrypt", "principal": "u1"}), "detokenize")
assert detok["records"][0]["ssn"] == "111-22-3333", detok

# ================= Security: markings propagation + access decision =================
ok(client.post("/markings", json={"id": "pii", "display_name": "PII", "category": "PII"}), "marking pii")
ok(client.post("/data-assets", json={"id": "raw", "display_name": "raw", "kind": "dataset", "asset_schema": {}, "records": []}), "raw ds")
ok(client.post("/data-assets", json={"id": "clean", "display_name": "clean", "kind": "dataset", "asset_schema": {}, "records": []}), "clean ds")
ok(client.post("/data-assets", json={"id": "mart", "display_name": "mart", "kind": "dataset", "asset_schema": {}, "records": []}), "mart ds")
ok(client.post("/pipelines", json={"id": "p1", "display_name": "p1", "input_asset_id": "raw", "output_asset_id": "clean", "steps": []}), "pipe1")
ok(client.post("/pipelines", json={"id": "p2", "display_name": "p2", "input_asset_id": "clean", "output_asset_id": "mart", "steps": []}), "pipe2")
ok(client.post("/security/resource-markings", json={"resource_type": "dataset", "resource_id": "raw", "marking_id": "pii"}), "assign pii to raw")
prop = ok(client.post("/security/markings/propagate", params={"dataset_id": "raw"}), "propagate")
assert prop["downstream_count"] == 2, prop                       # clean + mart
downstream_ids = {d["dataset_id"] for d in prop["downstream"]}
assert downstream_ids == {"clean", "mart"}, downstream_ids
# mart now carries pii via propagation
assert "pii" in ok(client.get("/security/resource-markings/mart"), "mart markings")["marking_ids"], "mart should inherit pii"
# access: u1 lacks pii -> denied on mart; grant -> allowed
deny = ok(client.post("/security/access-decision", json={"principal": "u1", "resource_id": "mart"}), "deny")
assert deny["allowed"] is False and "pii" in deny["missing_markings"], deny
ok(client.post("/markings/pii/grant", json={"principal": "u1"}), "grant pii")
allow = ok(client.post("/security/access-decision", json={"principal": "u1", "resource_id": "mart"}), "allow")
assert allow["allowed"] is True, allow

# ================= Contour: pivot / sort / top_n / summary =================
sales = [{"region": "W", "q": "Q1", "amt": 10}, {"region": "W", "q": "Q2", "amt": 20},
         {"region": "E", "q": "Q1", "amt": 5}, {"region": "E", "q": "Q2", "amt": 7}]
piv = ok(client.post("/analytics/contour/apply", json={"records": sales, "boards": [
    {"op": "pivot", "index": "region", "column": "q", "value": "amt", "agg": "sum"}]}), "pivot")
wrow = next(r for r in piv["records"] if r["region"] == "W")
assert wrow["Q1"] == 10 and wrow["Q2"] == 20, wrow
agg_sort = ok(client.post("/analytics/contour/apply", json={"records": sales, "boards": [
    {"op": "aggregate", "group_by": ["region"], "aggregations": [{"op": "sum", "field": "amt", "as": "total"}]},
    {"op": "sort", "field": "total", "desc": True},
    {"op": "top_n", "n": 1}]}), "agg+sort+top")
assert agg_sort["records"] == [{"region": "W", "total": 30}], agg_sort["records"]
summ = ok(client.post("/analytics/contour/apply", json={"records": sales, "boards": [{"op": "summary", "fields": ["amt"]}]}), "summary")
assert summ["summary"]["amt"]["max"] == 20 and summ["summary"]["amt"]["count"] == 4, summ

# ================= Object Explorer: histogram + property-stats =================
ok(client.post("/object-types", json={"id": "tx", "display_name": "Tx", "description": "",
    "properties": {"amount": {"type": "number"}, "kind": {"type": "string"}}}), "tx type")
for i, (amt, kind) in enumerate([(1, "a"), (2, "a"), (3, "b"), (10, "b")]):
    ok(client.post("/objects", json={"id": f"t{i}", "object_type_id": "tx", "properties": {"amount": amt, "kind": kind}}), f"tx {i}")
hist = ok(client.post("/object-explorer/histogram", json={"object_type_id": "tx", "field": "amount", "bins": 3}), "histogram numeric")
assert hist["type"] == "numeric" and sum(b["count"] for b in hist["buckets"]) == 4, hist
chist = ok(client.post("/object-explorer/histogram", json={"object_type_id": "tx", "field": "kind"}), "histogram categorical")
assert chist["type"] == "categorical" and {b["value"]: b["count"] for b in chist["buckets"]} == {"a": 2, "b": 2}, chist
ps = ok(client.post("/object-explorer/property-stats", json={"object_type_id": "tx", "field": "amount"}), "property stats")
assert ps["count"] == 4 and ps["numeric"]["max"] == 10 and ps["distinct"] == 4, ps

print(f"\nPass 8 tools (Cipher/Security/Contour/Object Explorer) verified: {passed} assertions passed.")
from app.database import engine as _engine  # noqa: E402
_engine.dispose()
tmpdir.cleanup()

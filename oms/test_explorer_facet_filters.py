"""
An Object Explorer facet filters to the objects it counts.

A histogram bucket carried rounded edges and no value, so a click sent its label, which no
number equals; a value list keyed its values by their text, so a True bucket sent "True",
which no stored true equals. Every bucket's filter must now return exactly its count.

Run:
  python oms/test_explorer_facet_filters.py
"""
import os
import tempfile

tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tmpdir.name, 'facet_filters.db')}"

from fastapi.testclient import TestClient  # noqa: E402
from app.main import app  # noqa: E402

client = TestClient(app)
passed = 0
TYPE = "facet_filters"


def ok(resp, label, expect=200):
    global passed
    success = resp.status_code == expect or (expect == 200 and 200 <= resp.status_code < 300)
    assert success, f"{label}: expected {expect}, got {resp.status_code} -> {resp.text[:600]}"
    passed += 1
    return resp.json() if resp.content else {}


def check(condition, message):
    global passed
    assert condition, message
    passed += 1


def query(filters):
    return ok(client.post("/object-explorer/query", json={"object_type_id": TYPE, "filters": filters, "limit": 500}), f"query {filters}")


ok(client.post("/object-types", json={"id": TYPE, "display_name": "Facet filters", "description": "Facet filters",
                                      "properties": {"name": {"type": "string"}, "score": {"type": "number"}, "active": {"type": "boolean"}}}), "type")
# The highest score makes the bin width 13.7500001, so a rounded edge reads 13.75, and 13.75
# itself belongs to the first bin by the edges the counts used and to the second by the rounded ones.
scores = [0, 13.75, 110.0000008] + [index * 5 for index in range(1, 21)]
records = [{"id": f"{TYPE}_{index:02d}", "name": f"n{index:02d}", "score": score, "active": index % 2 == 0}
           for index, score in enumerate(scores)]
ok(client.post("/data-assets", json={"id": f"{TYPE}_feed", "display_name": "Facet filters feed", "kind": "dataset", "asset_schema": {}, "records": records}), "feed")
ok(client.post("/pipelines", json={"id": f"{TYPE}_hydrate", "display_name": "Facet filters hydrate", "input_asset_id": f"{TYPE}_feed",
                                   "steps": [{"operation": "map_to_ontology", "object_type_id": TYPE, "object_id_field": "id",
                                              "property_map": {"name": "$name", "score": "$score", "active": "$active"}, "omit_nulls": True}]}), "pipeline")
run = ok(client.post(f"/pipelines/{TYPE}_hydrate/run", params={"actor": "test"}), "hydrate")
check(run.get("status") == "SUCCESS", run)

everything = query({})
facets = {facet["field"]: facet for facet in everything["facets"]}
score = facets["score"]
check(score["type"] == "histogram" and len(score["buckets"]) == 8, score)
for index, bucket in enumerate(score["buckets"]):
    low, high = bucket["range"]
    edge = {"gte": low, "lte": high} if index == len(score["buckets"]) - 1 else {"gte": low, "lt": high}
    matched = query({"score": edge})["result_count"]
    check(matched == bucket["count"], f"score bin {index} ({bucket['label']}) counts {bucket['count']} and its filter {edge} returns {matched}")

active = facets["active"]
check(active["type"] == "listogram", active)
check({type(bucket["value"]) for bucket in active["buckets"]} == {bool}, f"the active facet sends {[bucket['value'] for bucket in active['buckets']]!r}, not booleans")
for bucket in active["buckets"]:
    matched = query({"active": bucket["value"]})["result_count"]
    check(matched == bucket["count"], f"active {bucket['value']!r} counts {bucket['count']} and its filter returns {matched}")

print(f"Explorer facet filters verified: {passed} assertions passed.")
from app.database import engine as _engine  # noqa: E402
_engine.dispose()
tmpdir.cleanup()

"""
Standalone self-test for the apps router family (does NOT import app.main):
  * apps.py            — Slate versioning (publish / versions / restore / PATCH / DELETE)
  * workshop_runtime.py — Workshop dependency graph
  * slate_runtime.py    — Slate dependency graph
  * carbon_runtime.py   — typed navigation between modules

Builds a local FastAPI app from ONLY the four owned routers. Seeds core ontology
rows directly via SessionLocal. Run from oms/:
  ./venv312/Scripts/python.exe test_apps_versioning.py
"""
import os
import tempfile

_t = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(_t.name, 't.db')}"

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.database import Base, engine, SessionLocal  # noqa: E402
from app import models, models_action  # noqa: E402
from app import apps as APPS  # noqa: E402
from app import workshop_runtime as WR  # noqa: E402
from app import slate_runtime as SR  # noqa: E402
from app import carbon_runtime as CR  # noqa: E402

Base.metadata.create_all(bind=engine)

api = FastAPI()
api.include_router(APPS.router)
api.include_router(WR.router)
api.include_router(SR.router)
api.include_router(CR.router)
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


# ---------------- seed core ontology directly via SessionLocal ----------------
import time as _time

with SessionLocal() as s:
    s.add(models.ObjectType(
        id="deal", display_name="Deal", description="",
        properties={"stage": {"type": "string"}, "value": {"type": "number"}, "owner": {"type": "string"}},
        created_at=int(_time.time()), updated_at=int(_time.time()),
    ))
    for did, stage, val, owner in [("d1", "won", 100, "u1"), ("d2", "won", 50, "u2"), ("d3", "lost", 30, "u1")]:
        s.add(models.ObjectInstance(
            id=did, object_type_id="deal",
            properties={"stage": stage, "value": val, "owner": owner},
            created_at=int(_time.time()), updated_at=int(_time.time()),
        ))
    s.commit()

# ================= SLATE: create + PATCH + versioning =================
ok(client.post("/apps/slate", json={
    "id": "sales_app", "display_name": "Sales App",
    "queries": {
        "wonDeals": {"type": "object_set", "object_type_id": "deal", "filters": {"stage": "won"}},
        "wonTotal": {"type": "object_aggregation", "object_type_id": "deal", "op": "sum", "field": "value", "filters": {"stage": "won"}},
        "region": {"type": "static", "value": "EMEA"},
    },
    "functions": {
        "wonCount": {"op": "aggregate", "source": "wonDeals", "agg": "count"},
        "headline": {"op": "format", "template": "{region}: {n}", "inputs": {"region": "region", "n": "wonCount"}},
    },
    "widgets": {
        "tbl": {"type": "object_table", "title": "Won", "query": "wonDeals"},
        "msg": {"type": "text", "title": "Headline", "function": "headline"},
    },
}), "create slate app")

# publish v1 (captures the original display_name + queries)
v1 = ok(client.post("/apps/slate/sales_app/publish", json={"note": "initial"}), "slate publish v1")
check(v1["version_number"] == 1, "slate v1 version_number == 1")
check(v1["snapshot"]["display_name"] == "Sales App", "slate v1 snapshot display_name")

# PATCH the app (edit display_name + add a query)
patched = ok(client.patch("/apps/slate/sales_app", json={
    "display_name": "Sales App v2",
    "queries": {
        "wonDeals": {"type": "object_set", "object_type_id": "deal", "filters": {"stage": "won"}},
        "wonTotal": {"type": "object_aggregation", "object_type_id": "deal", "op": "sum", "field": "value", "filters": {"stage": "won"}},
        "region": {"type": "static", "value": "APAC"},
    },
}), "slate patch")
check(patched["display_name"] == "Sales App v2", "slate patch display_name updated")
check(patched["queries"]["region"]["value"] == "APAC", "slate patch region updated")

# publish v2
v2 = ok(client.post("/apps/slate/sales_app/publish", json={"note": "v2"}), "slate publish v2")
check(v2["version_number"] == 2, "slate v2 version_number == 2")

# list versions -> 2, newest first
versions = ok(client.get("/apps/slate/sales_app/versions"), "slate list versions")
check(len(versions) == 2 and versions[0]["version_number"] == 2, "slate two versions newest-first")

# restore v1 by version_number -> display_name reverts to original
restored = ok(client.post("/apps/slate/sales_app/versions/1/restore", json={}), "slate restore v1")
check(restored["display_name"] == "Sales App", "slate restore reverted display_name")
check(restored["queries"]["region"]["value"] == "EMEA", "slate restore reverted region")

# ================= SLATE dependency graph =================
dep = ok(client.get("/apps/slate/sales_app/dependencies"), "slate dependencies")
node_ids = {n["id"] for n in dep["nodes"]}
check({"wonDeals", "wonCount", "headline"} <= node_ids, "slate graph has query+function nodes")
edge_pairs = {(e["from"], e["to"]) for e in dep["edges"]}
check(("wonDeals", "wonCount") in edge_pairs, "slate edge wonDeals->wonCount")
check(("wonCount", "headline") in edge_pairs, "slate edge wonCount->headline")
check(dep["has_cycle"] is False, "slate graph acyclic")
# topo order: query before the functions that depend on it
order = dep["topological_order"]
check(order.index("wonDeals") < order.index("wonCount") < order.index("headline"), "slate topo order valid")

# ================= WORKSHOP: create + dependency graph =================
ok(client.post("/apps/workshop", json={
    "id": "ops", "display_name": "Ops",
    "variables": {
        "allDeals": {"definition_type": "object_set", "object_type_id": "deal"},
        "selDeal": {"definition_type": "state", "key": "selDeal", "default": "d1"},
        "selOwner": {"definition_type": "object_property", "object_id_var": "selDeal", "property": "owner"},
        "headline": {"definition_type": "variable_transformation", "op": "concat", "inputs": ["selOwner"], "separator": ""},
    },
    "widgets": [
        {"type": "object_table", "title": "All", "variable": "allDeals"},
        {"type": "text", "title": "Owner", "variable": "selOwner"},
    ],
}), "create workshop module")

wdep = ok(client.get("/apps/workshop/ops/dependencies"), "workshop dependencies")
wedges = {(e["from"], e["to"]) for e in wdep["edges"]}
check(("selDeal", "selOwner") in wedges, "workshop edge selDeal->selOwner")
check(("selOwner", "headline") in wedges, "workshop edge selOwner->headline")
worder = wdep["topological_order"]
check(worder.index("selDeal") < worder.index("selOwner") < worder.index("headline"), "workshop topo order")
# widget binding edge exists
wbind = {(e["from"], e["to"]) for e in wdep["edges"] if e["kind"] == "widget_binding"}
check(any(src == "allDeals" for src, _ in wbind), "workshop widget binding edge")

# ================= CARBON: typed navigation =================
ok(client.post("/apps/carbon", json={
    "id": "hub", "display_name": "Hub",
    "module_ids": ["ops", "sales_app"],
    "navigation": {"home": "ops", "sections": [{"title": "Apps", "items": ["ops", "sales_app"]}]},
}), "create carbon workspace")

# navigate from the Workshop module (source) to the Slate app (target),
# binding the resolved 'selOwner' output -> target input 'ownerFilter'
nav = ok(client.post("/apps/carbon/hub/navigate", json={
    "from_module_id": "ops",
    "to_module_id": "sales_app",
    "state": {"selDeal": "d2"},
    "output_bindings": [
        {"source_output": "selOwner", "target_input": "ownerFilter"},
        {"source_output": "headline", "target_input": "title"},
    ],
}), "carbon navigate")
check(nav["from_kind"] == "workshop" and nav["to_kind"] == "slate", "carbon navigate kinds")
# d2.owner == u2 resolved via the workshop runtime object_property
check(nav["typed_inputs"]["ownerFilter"] == "u2", "carbon navigate resolved typed input value")
check(nav["unresolved"] == [], "carbon navigate all bindings resolved")
bmap = {b["target_input"]: b for b in nav["bindings"]}
check(bmap["ownerFilter"]["type"] == "string" and bmap["ownerFilter"]["resolved"] is True, "carbon binding typed string")

# navigate from the Slate app (source) -> Workshop, binding a query (object_set output)
nav2 = ok(client.post("/apps/carbon/hub/navigate", json={
    "from_module_id": "sales_app",
    "to_module_id": "ops",
    "output_bindings": [
        {"source_output": "wonTotal", "target_input": "budget"},
        {"source_output": "doesNotExist", "target_input": "x"},
    ],
}), "carbon navigate slate->workshop")
check(nav2["typed_inputs"]["budget"] == 150, "carbon slate output wonTotal == 150")
check(nav2["unresolved"] == ["doesNotExist"], "carbon navigate reports unresolved binding")

# navigate with a module not in the workspace -> 404
ok(client.post("/apps/carbon/hub/navigate", json={
    "from_module_id": "ghost", "to_module_id": "ops", "output_bindings": [],
}), "carbon navigate invalid source", expect=404)

# ================= SLATE DELETE =================
ok(client.delete("/apps/slate/sales_app"), "slate delete")
ok(client.get("/apps/slate/sales_app"), "slate get after delete -> 404", expect=404)
# versions are gone too
ok(client.get("/apps/slate/sales_app/versions"), "slate versions after delete -> 404", expect=404)

print(f"\napps versioning + dependency graph + carbon navigation verified: {passed} assertions passed.")

from app.database import engine as _engine  # noqa: E402
_engine.dispose()
_t.cleanup()

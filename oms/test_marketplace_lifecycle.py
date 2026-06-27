"""
Standalone self-test for the Marketplace owned files:
  - app.marketplace        (DevOps products + consolidated install + lifecycle)
  - app.marketplace_ops    (declared requirements + install-resolved + INPUTS/OUTPUTS)

Builds a local FastAPI app from ONLY the owned routers (does NOT import app.main,
because sibling files are edited concurrently). Seeds core rows directly via
SessionLocal.

Run from oms/:  ./venv312/Scripts/python.exe test_marketplace_lifecycle.py
"""
import os
import tempfile

_t = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(_t.name, 't.db')}"

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.database import Base, engine, SessionLocal  # noqa: E402
from app import models, models_action  # noqa: E402  (ensure tables register)
from app import marketplace as MKT  # noqa: E402
from app import marketplace_ops as OPS  # noqa: E402

Base.metadata.create_all(bind=engine)

api = FastAPI()
api.include_router(MKT.router)
api.include_router(OPS.router)
client = TestClient(api)

passed = 0


def ok(resp, label, expect=200):
    global passed
    success = resp.status_code == expect or (expect == 200 and 200 <= resp.status_code < 300)
    assert success, f"{label}: expected {expect}, got {resp.status_code} -> {resp.text[:400]}"
    passed += 1
    return resp.json() if resp.content else {}


def _now():
    import time
    return int(time.time())


# --- seed core rows directly (no main.py routes available) ------------------
def seed():
    db = SessionLocal()
    try:
        # a raw input dataset that installers can map to
        if not db.get(models.DataAsset, "my_raw"):
            db.add(models.DataAsset(id="my_raw", display_name="raw", description=None,
                                    kind="dataset", asset_schema={}, records=[],
                                    created_at=_now(), updated_at=_now()))
        # upstream + output datasets for input-derivation
        for did in ("raw_src", "curated_out"):
            if not db.get(models.DataAsset, did):
                db.add(models.DataAsset(id=did, display_name=did, description=None,
                                        kind="dataset", asset_schema={}, records=[],
                                        created_at=_now(), updated_at=_now()))
        # a pipeline declaring curated_out <- raw_src lineage
        if not db.get(models.PipelineDefinition, "pipe1"):
            db.add(models.PipelineDefinition(id="pipe1", display_name="pipe1", description=None,
                                             input_asset_id="raw_src", output_asset_id="curated_out",
                                             mode="batch", schedule=None, steps=[],
                                             created_at=_now(), updated_at=_now()))
        db.commit()
    finally:
        db.close()


seed()

# ============================================================================
# 1. Product + release + requirement, then CONSOLIDATED install
# ============================================================================
ok(client.post("/devops/products", json={
    "id": "prod", "display_name": "CRM", "mode": "production",
    "resources": [{"kind": "object_type", "id": "customer"}, {"kind": "dataset", "id": "sales"}]}),
   "create product", expect=200)

prod = ok(client.get("/devops/products/prod"), "get product")
assert prod["mode"] == "production", prod  # (a1) mode persisted

ok(client.post("/devops/products/prod/requirements",
               json={"key": "raw_input", "kind": "dataset", "required": True}), "add requirement", expect=201)
rel1 = ok(client.post("/devops/products/prod/releases", json={"version": "1.0.0", "channel": "stable"}), "release1")

# consolidated /install must now REJECT a missing required input (same as install-resolved)
ok(client.post("/marketplace/prod/install", json={"target_project": "p", "input_mappings": {}}),
   "consolidated install blocked", expect=422)  # (a2)

# consolidated /install applies prefix (ontology) + suffix (project) + lifecycle
inst = ok(client.post("/marketplace/prod/install", json={
    "target_project": "proj", "input_mappings": {"raw_input": "my_raw"},
    "prefix": "[DEV]", "suffix": "_v1"}), "consolidated install ok")
assert inst["target_project"] == "proj_v1", inst                       # (a3) suffix on project
assert inst["mode"] == "production", inst                              # (a4) mode recorded
assert inst["release_channel"] == "stable", inst                       # (a5) channel default
assert inst["auto_upgrade"] is True and inst["locked"] is True, inst   # (a6) production defaults

install_id = inst["id"]

# ============================================================================
# 2. Installation lifecycle: lock/unlock, auto-upgrade, release-channel, upgrade
# ============================================================================
# locked install cannot be upgraded
rel2 = ok(client.post("/devops/products/prod/releases", json={"version": "1.1.0", "channel": "stable"}), "release2")
ok(client.post(f"/installations/{install_id}/upgrade", json={"release_id": rel2["id"]}),
   "upgrade blocked while locked", expect=409)  # (a7)

unlocked = ok(client.post(f"/installations/{install_id}/unlock"), "unlock")
assert unlocked["locked"] is False, unlocked                            # (a8)

upgraded = ok(client.post(f"/installations/{install_id}/upgrade", json={"release_id": rel2["id"]}), "upgrade")
assert upgraded["release_id"] == rel2["id"], upgraded                   # (a9)

au = ok(client.post(f"/installations/{install_id}/auto-upgrade", json={"auto_upgrade": False}), "auto-upgrade off")
assert au["auto_upgrade"] is False, au                                  # (a10)

ch = ok(client.post(f"/installations/{install_id}/release-channel", json={"release_channel": "test"}), "set channel")
assert ch["release_channel"] == "test", ch                              # (a11)
ok(client.post(f"/installations/{install_id}/release-channel", json={"release_channel": "bogus"}),
   "bad channel rejected", expect=400)                                  # (a12)

locked = ok(client.post(f"/installations/{install_id}/lock"), "lock")
assert locked["locked"] is True, locked                                 # (a13)

# list + get installation
lst = ok(client.get("/installations?product_id=prod"), "list installs")
assert any(i["id"] == install_id for i in lst), lst                     # (a14)

# ============================================================================
# 3. DELETE installation requires confirmation
# ============================================================================
ok(client.request("DELETE", f"/installations/{install_id}", json={"confirm": False}),
   "delete without confirm rejected", expect=400)                       # (a15)
deleted = ok(client.request("DELETE", f"/installations/{install_id}",
                            json={"confirm_text": "delete installation"}), "delete with confirm")
assert deleted["deleted"] is True, deleted                              # (a16)
ok(client.get(f"/installations/{install_id}"), "gone after delete", expect=404)  # (a17)

# ============================================================================
# 4. Singleton mode prevents a second install into the same target
# ============================================================================
ok(client.post("/devops/products", json={"id": "single", "display_name": "S", "mode": "singleton",
                                          "resources": []}), "singleton product")
ok(client.post("/devops/products/single/releases", json={"version": "1.0.0"}), "single release")
s1 = ok(client.post("/marketplace/single/install", json={"target_project": "spc"}), "singleton install 1")
assert s1["mode"] == "singleton" and s1["locked"] is True, s1          # (a18)
ok(client.post("/marketplace/single/install", json={"target_project": "spc"}),
   "singleton install 2 blocked", expect=409)                          # (a19)

# ============================================================================
# 5. INPUTS vs OUTPUTS: explicit ports, upstream derivation, promotion
# ============================================================================
ok(client.post("/devops/products", json={"id": "dp", "display_name": "DataProduct",
                                          "resources": []}), "data product")
# OUTPUT = curated_out (produced by pipe1 from raw_src)
ok(client.post("/devops/products/dp/outputs", json={"kind": "dataset", "resource_id": "curated_out"}),
   "add output", expect=201)
ports0 = ok(client.get("/devops/products/dp/ports"), "ports before derive")
assert len(ports0["outputs"]) == 1 and ports0["inputs"] == [], ports0  # (a20)

derived = ok(client.post("/devops/products/dp/derive-inputs"), "derive inputs", expect=201)
# raw_src is upstream of curated_out and is NOT itself an output -> surfaced as input
assert any(p["resource_id"] == "raw_src" and p["derived"] for p in derived["derived_inputs"]), derived  # (a21)

ports1 = ok(client.get("/devops/products/dp/ports"), "ports after derive")
assert any(p["resource_id"] == "raw_src" for p in ports1["inputs"]), ports1  # (a22)

# promote the derived input raw_src to an output
promoted = ok(client.post("/devops/products/dp/inputs/raw_src/promote"), "promote input")
assert promoted["port_type"] == "output", promoted                      # (a23)
ports2 = ok(client.get("/devops/products/dp/ports"), "ports after promote")
assert any(p["resource_id"] == "raw_src" for p in ports2["outputs"]), ports2  # (a24)
assert not any(p["resource_id"] == "raw_src" for p in ports2["inputs"]), ports2  # (a25)

# re-derive: now raw_src is an output, so it must NOT be re-added as an input
re_derived = ok(client.post("/devops/products/dp/derive-inputs"), "re-derive after promote", expect=201)
assert not any(p["resource_id"] == "raw_src" for p in re_derived["derived_inputs"]), re_derived  # (a26)

# ============================================================================
# 6. Existing endpoints preserved: validate-install + install-resolved + snapshots
# ============================================================================
v_ok = ok(client.post("/marketplace/prod/validate-install",
                      json={"input_mappings": {"raw_input": "my_raw"}}), "validate ok")
assert v_ok["valid"] is True, v_ok                                      # (a27)
ir = ok(client.post("/marketplace/prod/install-resolved", json={
    "target_project": "rp", "input_mappings": {"raw_input": "my_raw"}, "prefix": "[X]"}),
   "install-resolved preserved", expect=201)
created = {c["kind"]: c["installed_as"] for c in ir["created_content"]}
assert created["object_type"] == "[X]customer", created                # (a28)

print(f"\nMarketplace lifecycle + inputs/outputs verified: {passed} assertions passed.")

from app.database import engine as _engine  # noqa: E402
_engine.dispose()
_t.cleanup()

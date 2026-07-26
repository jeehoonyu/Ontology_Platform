"""
Standalone self-test for owned modules:
  * app.datasets_ext  -> GET/PUT /datasets/{id}/schema
  * app.connectivity  -> POST /connections/sources/{id}/test
                         GET  /connections/sources/{id}/schema
                         DELTA export checkpoint on /connections/exports/{id}/run

Builds a local FastAPI app from ONLY the owned routers (does NOT import app.main).
Run from oms/: ./venv312/Scripts/python.exe test_datasets_connectivity_ext.py
"""
import os
import tempfile

_t = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(_t.name, 't.db')}"

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.database import Base, engine, SessionLocal  # noqa: E402
from app import models, models_action  # noqa: E402
from app import datasets_ext as DX  # noqa: E402
from app import connectivity as CN  # noqa: E402

Base.metadata.create_all(bind=engine)

api = FastAPI()
api.include_router(DX.router)
api.include_router(CN.router)
client = TestClient(api)

passed = 0


def ok(resp, label, expect=200):
    global passed
    success = resp.status_code == expect or (expect == 200 and 200 <= resp.status_code < 300)
    assert success, f"{label}: expected {expect}, got {resp.status_code} -> {resp.text[:400]}"
    passed += 1
    return resp.json() if resp.content else {}


def seed_asset(aid, records):
    """Seed a DataAsset row directly (no data-assets router in this local app)."""
    now = int(__import__("time").time())
    db = SessionLocal()
    try:
        db.add(models.DataAsset(id=aid, display_name=aid, description=None, kind="dataset",
                                asset_schema={}, records=records, created_at=now, updated_at=now))
        db.commit()
    finally:
        db.close()


# =====================================================================
# (1) Dataset schema: PUT upserts, GET returns it, GET 404 if unset
# =====================================================================
seed_asset("ds1", [{"id": 1, "v": 10}])

# GET before any schema -> 404
ok(client.get("/datasets/ds1/schema"), "schema unset -> 404", expect=404)

# PUT to a non-existent dataset -> 404
ok(client.put("/datasets/nope/schema", json={"columns": [{"name": "x", "type": "integer"}]}),
   "schema put missing dataset -> 404", expect=404)

# PUT a schema -> stored
put1 = ok(client.put("/datasets/ds1/schema", json={"columns": [
    {"name": "id", "type": "integer"}, {"name": "v", "type": "integer"}]}), "schema put 1")
assert put1["dataset_id"] == "ds1", put1
assert [c["name"] for c in put1["columns"]] == ["id", "v"], put1
assert put1["columns"][0]["type"] == "integer", put1

# GET returns the stored schema
got = ok(client.get("/datasets/ds1/schema"), "schema get")
assert [c["name"] for c in got["columns"]] == ["id", "v"], got
assert got["created_at"] == put1["created_at"], got

# PUT again upserts (replaces columns, keeps created_at)
put2 = ok(client.put("/datasets/ds1/schema", json={"columns": [
    {"name": "id", "type": "integer"}, {"name": "name", "type": "string"},
    {"name": "score", "type": "double"}]}), "schema put 2 (upsert)")
assert len(put2["columns"]) == 3, put2
assert put2["created_at"] == put1["created_at"], "created_at must be preserved on upsert"
got2 = ok(client.get("/datasets/ds1/schema"), "schema get 2")
assert [c["name"] for c in got2["columns"]] == ["id", "name", "score"], got2

# =====================================================================
# (2) Source connection test — deterministic required-key validation
# =====================================================================
# jdbc missing required keys -> not ok
ok(client.post("/connections/sources", json={"id": "s_bad", "display_name": "Bad JDBC",
    "source_type": "jdbc", "config": {}}), "create s_bad")
t_bad = ok(client.post("/connections/sources/s_bad/test"), "test s_bad")
assert t_bad["ok"] is False, t_bad
assert "jdbc_url" in t_bad["missing"] and "driver_class" in t_bad["missing"], t_bad
assert all(c["required"] for c in t_bad["checks"]) and len(t_bad["checks"]) == 2, t_bad

# jdbc with required keys -> ok
ok(client.post("/connections/sources", json={"id": "s_good", "display_name": "Good JDBC",
    "source_type": "jdbc", "config": {"jdbc_url": "jdbc:postgresql://h/db", "driver_class": "org.postgresql.Driver"}}),
   "create s_good")
t_good = ok(client.post("/connections/sources/s_good/test"), "test s_good")
assert t_good["ok"] is True and t_good["missing"] == [], t_good

# SFTP validation requires a remote path and pinned host key; credentials are write-only runtime resources.
ok(client.post("/connections/sources", json={"id": "s_sftp", "display_name": "SFTP",
    "source_type": "sftp", "config": {"host": "h", "username": "u", "remote_path": "/incoming", "host_key_sha256": "SHA256:fixture"}}), "create s_sftp")
t_sftp = ok(client.post("/connections/sources/s_sftp/test"), "test s_sftp")
assert t_sftp["ok"] is True, t_sftp

# missing source -> 404
ok(client.post("/connections/sources/ghost/test"), "test missing source -> 404", expect=404)

# =====================================================================
# (3) Source schema inference from sync sample_records / config
# =====================================================================
ok(client.post("/connections/sources/s_good/syncs", json={"target_asset_id": "ds1",
    "mode": "snapshot", "sample_records": [
        {"id": 1, "name": "a", "active": True, "ratio": 1.5, "tags": ["x"]},
        {"id": 2, "name": "b", "active": False, "ratio": 2.0}]}), "sync for schema")
sch = ok(client.get("/connections/sources/s_good/schema"), "source schema")
by = {c["name"]: c["type"] for c in sch["schema"]}
assert by["id"] == "integer", by
assert by["name"] == "string", by
assert by["active"] == "boolean", by  # bool not mis-inferred as integer
assert by["ratio"] == "double", by
assert by["tags"] == "json", by
assert sch["sample_count"] == 2, sch

# schema inference from config samples when no sync samples
ok(client.post("/connections/sources", json={"id": "s_cfg", "display_name": "RestCfg",
    "source_type": "rest", "config": {"base_url": "https://api", "sample_records": [{"k": 5}]}}), "create s_cfg")
sch2 = ok(client.get("/connections/sources/s_cfg/schema"), "source schema from config")
assert {c["name"]: c["type"] for c in sch2["schema"]} == {"k": "integer"}, sch2

# =====================================================================
# (4) Export DELTA checkpoint — delta=true exports only new rows
# =====================================================================
seed_asset("exp_src", [{"id": 1}, {"id": 2}])
exp = ok(client.post("/connections/exports", json={"id": "ex1", "source_asset_id": "exp_src",
    "destination": "s3://bucket/out", "format": "json"}), "create export")

# default run (no delta) preserves existing behavior: returns full row count, no checkpoint touched
full = ok(client.post("/connections/exports/ex1/run"), "full export run")
assert full["rows"] == 2 and "delta" not in full, full
cp0 = ok(client.get("/connections/exports/ex1/checkpoint"), "checkpoint after full run")
assert cp0["runs"] == 0 and cp0["last_exported_count"] == 0, cp0  # full run does NOT checkpoint

# first delta run exports all current rows and records checkpoint at 2
d1 = ok(client.post("/connections/exports/ex1/run", params={"delta": True}), "delta run 1")
assert d1["delta"] is True and d1["rows"] == 2, d1
assert d1["previous_checkpoint"] == 0 and d1["new_checkpoint"] == 2, d1
assert [r["id"] for r in d1["delta_records"]] == [1, 2], d1

# append 3 new rows to the source asset, then delta run exports only those 3
def _append(aid, recs):
    db = SessionLocal()
    try:
        a = db.get(models.DataAsset, aid)
        a.records = list(a.records) + recs
        db.commit()
    finally:
        db.close()


_append("exp_src", [{"id": 3}, {"id": 4}, {"id": 5}])
d2 = ok(client.post("/connections/exports/ex1/run", params={"delta": True}), "delta run 2")
assert d2["rows"] == 3, d2  # only the 3 newly-appended rows
assert d2["previous_checkpoint"] == 2 and d2["new_checkpoint"] == 5, d2
assert [r["id"] for r in d2["delta_records"]] == [3, 4, 5], d2

# a subsequent delta run with no new rows exports nothing
d3 = ok(client.post("/connections/exports/ex1/run", params={"delta": True}), "delta run 3 (empty)")
assert d3["rows"] == 0 and d3["delta_records"] == [], d3

cp = ok(client.get("/connections/exports/ex1/checkpoint"), "checkpoint final")
assert cp["last_exported_count"] == 5 and cp["runs"] == 3, cp

print(f"\nDatasets + Connectivity extension behaviors verified: {passed} assertions passed.")

from app.database import engine as _engine  # noqa: E402
_engine.dispose()
_t.cleanup()

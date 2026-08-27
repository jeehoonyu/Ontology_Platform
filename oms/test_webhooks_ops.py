"""Standalone self-test for app/webhooks_ops.py (does NOT import app.main)."""
import os, tempfile, hashlib, json, time

_tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(_tmp.name, 't.db')}"

from fastapi import FastAPI                       # noqa: E402
from fastapi.testclient import TestClient         # noqa: E402
from app.database import Base, engine, SessionLocal  # noqa: E402
from app import models, models_action            # noqa: E402  (core + audit tables)
from app import webhooks_ops as M                # noqa: E402  (this module's tables)

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


# ---------------------------------------------------------------------------
# Seed a DataAsset directly (target for the inbound listener)
# ---------------------------------------------------------------------------
_db = SessionLocal()
_db.add(models.DataAsset(
    id="asset1", display_name="Inbound Events", description="seed",
    kind="dataset", asset_schema={}, records=[],
    created_at=int(time.time()), updated_at=int(time.time()),
))
_db.commit()
_db.close()


# ---------------------------------------------------------------------------
# 1. Create a writeback webhook with required params + output extraction
# ---------------------------------------------------------------------------
wb = ok(client.post("/connections/webhooks", json={
    "id": "wb1",
    "source_id": "src1",
    "display_name": "Create Ticket",
    "mode": "writeback",
    "request_config": {
        "method": "POST",
        "path": "/tickets/{ticket_id}",
        "headers": {"X-Title": "{title}"},
        "query": {"priority": "{priority}"},
        "body_template": {"title": "{title}", "ticket_id": "{ticket_id}", "fixed": "static"},
    },
    "input_parameters": [
        {"name": "title", "required": True},
        {"name": "ticket_id", "required": True},
        {"name": "priority", "required": False},
    ],
    "output_parameters": ["external_id", "url"],
    "mock_response": {"status": 201, "body": {"external_id": "EXT-9", "url": "http://x/9", "extra": "ignored"}},
}), "create writeback webhook", 200)
check(wb["mode"] == "writeback", "webhook mode writeback")

# get + list
ok(client.get("/connections/webhooks/wb1"), "get webhook")
lst = ok(client.get("/connections/webhooks"), "list webhooks")
check(len(lst) == 1, "one webhook listed")

# duplicate id -> 400
ok(client.post("/connections/webhooks", json={"id": "wb1", "display_name": "dup"}), "dup webhook 400", 400)
# invalid mode -> 422
ok(client.post("/connections/webhooks", json={"display_name": "bad", "mode": "nope"}), "bad mode 422", 422)


# ---------------------------------------------------------------------------
# 2. Parameter substitution correctness (dry-run, stores nothing)
# ---------------------------------------------------------------------------
dry = ok(client.post("/connections/webhooks/wb1/test", json={
    "parameters": {"title": "Bug", "ticket_id": "T-42", "priority": 5},
}), "dry-run", 200)
prev = dry["request_preview"]
check(prev["path"] == "/tickets/T-42", "path substitution")
check(prev["body"]["title"] == "Bug", "body title substitution")
check(prev["body"]["ticket_id"] == "T-42", "body ticket_id substitution")
check(prev["body"]["fixed"] == "static", "static body field untouched")
check(prev["headers"]["X-Title"] == "Bug", "header substitution")
# numeric stays numeric when template value is exactly {name}
check(prev["query"]["priority"] == 5 and isinstance(prev["query"]["priority"], int),
      "numeric param stays numeric")
check(dry["extracted_outputs"]["external_id"] == "EXT-9", "dry-run extracts outputs")
# dry-run stored nothing
ex = ok(client.get("/connections/webhooks/wb1/executions"), "executions after dry-run")
check(len(ex) == 0, "dry-run stored no execution")


# ---------------------------------------------------------------------------
# 3. Missing required param -> 422
# ---------------------------------------------------------------------------
ok(client.post("/connections/webhooks/wb1/invoke", json={"parameters": {"title": "Bug"}}),
   "missing required param 422", 422)


# ---------------------------------------------------------------------------
# 4. Writeback success: extracts outputs + stores execution
# ---------------------------------------------------------------------------
inv = ok(client.post("/connections/webhooks/wb1/invoke", json={
    "parameters": {"title": "Bug", "ticket_id": "T-42", "priority": 5},
    "idempotency_key": "idem-1", "actor": "alice",
}), "writeback invoke success", 200)
check(inv["status"] == "success", "invoke success status")
check(inv["extracted_outputs"]["external_id"] == "EXT-9", "invoke extracts external_id")
check(inv["extracted_outputs"]["url"] == "http://x/9", "invoke extracts url")
check("extra" not in inv["extracted_outputs"], "non-output keys not extracted")
check(inv["response_status"] == 201, "invoke response_status 201")
ex = ok(client.get("/connections/webhooks/wb1/executions"), "executions after invoke")
check(len(ex) == 1 and ex[0]["status"] == "success", "one success execution stored")


# ---------------------------------------------------------------------------
# 5. Idempotency returns cached execution (no new row)
# ---------------------------------------------------------------------------
inv2 = ok(client.post("/connections/webhooks/wb1/invoke", json={
    "parameters": {"title": "Bug", "ticket_id": "T-42", "priority": 5},
    "idempotency_key": "idem-1", "actor": "alice",
}), "idempotent re-invoke", 200)
check(inv2["cached"] is True, "second invoke is cached")
check(inv2["execution_id"] == inv["execution_id"], "cached returns same execution id")
ex = ok(client.get("/connections/webhooks/wb1/executions"), "executions after idempotent")
check(len(ex) == 1, "idempotency added no new execution")


# ---------------------------------------------------------------------------
# 6. Writeback FAIL -> 422 + stored failed execution
# ---------------------------------------------------------------------------
fb = ok(client.post("/connections/webhooks", json={
    "id": "wb_fail", "source_id": "src1", "display_name": "Fails",
    "mode": "writeback",
    "request_config": {"method": "POST", "path": "/x", "body_template": {"a": "{a}"}},
    "input_parameters": [{"name": "a", "required": True}],
    "output_parameters": ["ok"],
    "mock_response": {"status": 500, "fail": True, "body": {}},
}), "create failing webhook", 200)
r = client.post("/connections/webhooks/wb_fail/invoke", json={"parameters": {"a": "1"}})
ok(r, "writeback fail -> 422", 422)
exf = ok(client.get("/connections/webhooks/wb_fail/executions"), "failed executions")
check(len(exf) == 1 and exf[0]["status"] == "failed", "failed execution stored")


# ---------------------------------------------------------------------------
# 7. Side-effect: one failing + one ok -> 200, both logged (non-blocking)
# ---------------------------------------------------------------------------
# A side-effect webhook whose mock fails: we invoke a batch; failures non-blocking.
se = ok(client.post("/connections/webhooks", json={
    "id": "wb_se", "source_id": "src1", "display_name": "SideEffect",
    "mode": "side_effect",
    "request_config": {"method": "POST", "path": "/notify", "body_template": {"msg": "{msg}"}},
    "input_parameters": [{"name": "msg", "required": True}],
    "output_parameters": ["ack"],
    "mock_response": {"status": 200, "body": {"ack": "yes"}},
}), "create side-effect webhook", 200)
# batch: first set OK, second set MISSING required -> failed, both logged, still 200
batch = ok(client.post("/connections/webhooks/wb_se/invoke-side-effect", json={
    "parameter_sets": [{"msg": "hello"}, {}],
    "actor": "bob",
}), "side-effect batch", 200)
check(batch["count"] == 2, "side-effect processed 2 sets")
check(batch["succeeded"] == 1, "side-effect 1 succeeded")
check(batch["failed"] == 1, "side-effect 1 failed")
check(batch["results"][0]["status"] == "success", "first side-effect ok")
check(batch["results"][0]["extracted_outputs"]["ack"] == "yes", "side-effect extracts output")
check(batch["results"][1]["status"] == "failed", "second side-effect failed")
exse = ok(client.get("/connections/webhooks/wb_se/executions"), "side-effect executions")
check(len(exse) == 2, "both side-effect executions logged")


# ---------------------------------------------------------------------------
# 8. Outbound app + OAuth authorize + credential expiry flagged
# ---------------------------------------------------------------------------
app = ok(client.post("/outbound-applications", json={
    "id": "app1", "display_name": "Ext", "client_id": "cid",
    "client_secret": "secret", "token_endpoint": "http://t/token", "scopes": ["write"],
}), "create outbound app", 200)
apps = ok(client.get("/outbound-applications"), "list outbound apps")
check(len(apps) == 1, "one outbound app")

auth = ok(client.post("/connections/webhooks/wb1/authorize", json={
    "outbound_app_id": "app1", "code": "auth-code-1", "ttl_seconds": 3600,
}), "authorize webhook", 200)
expected_tok = hashlib.sha256(("secret" + "auth-code-1").encode()).hexdigest()
check(auth["token"] == expected_tok, "deterministic oauth token")
check(auth["needs_refresh"] is False, "fresh token does not need refresh")

# Create an already-expired credential on a fresh source bound to a new webhook,
# then invoke and confirm needs_refresh flagged.
wexp = ok(client.post("/connections/webhooks", json={
    "id": "wb_exp", "source_id": "src_exp", "display_name": "Expired",
    "mode": "writeback",
    "request_config": {"method": "POST", "path": "/x", "body_template": {}},
    "input_parameters": [], "output_parameters": [],
    "mock_response": {"status": 200, "body": {}},
}), "create expiring webhook", 200)
cred = ok(client.post("/connections/sources/src_exp/credentials", json={
    "credential_type": "oauth2", "token": "old", "expires_at": int(time.time()) - 10,
}), "create expired credential", 200)
check(cred["expired"] is True, "credential reports expired")
invx = ok(client.post("/connections/webhooks/wb_exp/invoke", json={"parameters": {}}),
          "invoke with expired cred", 200)
check(invx["needs_refresh"] is True, "expired credential flags needs_refresh on invoke")


# ---------------------------------------------------------------------------
# 9. Inbound HMAC listener
# ---------------------------------------------------------------------------
ln = ok(client.post("/listeners", json={
    "id": "ln1", "display_name": "HMAC In", "auth_type": "hmac",
    "auth_secret": "shh", "target_asset_id": "asset1",
    "event_schema": ["event_id", "value"],
}), "create hmac listener", 200)
check(ln["auth_type"] == "hmac", "listener auth_type hmac")
ok(client.get("/listeners/ln1"), "get listener")
lns = ok(client.get("/listeners"), "list listeners")
check(len(lns) == 1, "one listener")

# missing auth_secret for non-none auth -> 422
ok(client.post("/listeners", json={"display_name": "bad", "auth_type": "bearer"}),
   "listener missing secret 422", 422)

# correctly-signed payload -> 200 + appended
good_body = {"event_id": "e1", "value": 42}
raw = json.dumps(good_body).encode("utf-8")
sig = hashlib.sha256(b"shh" + raw).hexdigest()
r = client.post("/listeners/ln1/events", content=raw,
                headers={"x-signature": sig, "content-type": "application/json"})
res = ok(r, "hmac valid event", 200)
check(res["processing_status"] == "persisted", "valid event persisted")
check(res["appended"] is True, "valid event appended to asset")

# confirm the DataAsset got the record appended
_db = SessionLocal()
asset = _db.query(models.DataAsset).filter(models.DataAsset.id == "asset1").first()
check(len(asset.records) == 1 and asset.records[0]["event_id"] == "e1", "asset record appended")
_db.close()

# bad signature -> 401 + auth_error, no append
r = client.post("/listeners/ln1/events", content=raw,
                headers={"x-signature": "deadbeef", "content-type": "application/json"})
ok(r, "hmac bad signature 401", 401)

# schema-invalid (valid sig, missing 'value') -> 202 + validation_error, no append
bad_schema_body = {"event_id": "e2"}
raw2 = json.dumps(bad_schema_body).encode("utf-8")
sig2 = hashlib.sha256(b"shh" + raw2).hexdigest()
r = client.post("/listeners/ln1/events", content=raw2,
                headers={"x-signature": sig2, "content-type": "application/json"})
res2 = ok(r, "schema-invalid -> 202", 202)
check(res2["processing_status"] == "validation_error", "schema-invalid validation_error")

# Confirm asset still has exactly 1 record (bad sig + schema-fail did NOT append)
_db = SessionLocal()
asset = _db.query(models.DataAsset).filter(models.DataAsset.id == "asset1").first()
check(len(asset.records) == 1, "no append on auth/schema failure")
_db.close()

# events log records all three (persisted, auth_error, validation_error)
events = ok(client.get("/listeners/ln1/events"), "listener events")
statuses = sorted(e["processing_status"] for e in events)
check(statuses == ["auth_error", "persisted", "validation_error"], "all event statuses logged")


# ---------------------------------------------------------------------------
# 10. Bearer + none listeners (extra coverage)
# ---------------------------------------------------------------------------
lb = ok(client.post("/listeners", json={
    "id": "ln_b", "display_name": "Bearer In", "auth_type": "bearer",
    "auth_secret": "tok123", "target_asset_id": None, "event_schema": ["k"],
}), "create bearer listener", 200)
r = client.post("/listeners/ln_b/events", json={"k": "v"},
                headers={"authorization": "Bearer tok123"})
ok(r, "bearer valid", 200)
r = client.post("/listeners/ln_b/events", json={"k": "v"},
                headers={"authorization": "Bearer wrong"})
ok(r, "bearer invalid 401", 401)

# 404s
ok(client.get("/connections/webhooks/nope"), "missing webhook 404", 404)
ok(client.get("/listeners/nope"), "missing listener 404", 404)
ok(client.post("/listeners/nope/events", json={}), "missing listener event 404", 404)


# --- T4: silence must not create an open write endpoint ----------------------
#
# ListenerCreate.auth_type defaulted to "none", create_listener permitted it, and
# _check_listener_auth returns True unconditionally for that value -- so a caller
# who said nothing about authentication got a listener accepting anything from
# anyone, appending it to a project's DataAsset. Two things now stand in the way:
# saying nothing is an error, and saying "none" costs `administer`.

ok(client.post("/listeners", json={"id": "ln_silent", "display_name": "Silent"}),
   "a listener with no auth_type is refused rather than opened", 422)
passed += 1

from fastapi import HTTPException                     # noqa: E402
from app import production_auth                       # noqa: E402

editor = production_auth.Principal(
    id="editor-1", display_name="Editor", email=None, roles=["editor"],
    permissions=["view", "edit"], project_ids=["default"],
)
assert not editor.allows("administer"), "fixture principal must not hold administer"
with SessionLocal() as _db:
    try:
        M.create_listener(
            M.ListenerCreate(id="ln_open", display_name="Open", auth_type="none"),
            _db, editor,
        )
        raise AssertionError("an editor created an unauthenticated listener")
    except HTTPException as exc:
        assert exc.status_code == 403, exc.status_code
        assert "administer" in str(exc.detail), exc.detail
passed += 1
print("  ok: an editor cannot stand up an unauthenticated listener (403)")

admin = production_auth.Principal(
    id="admin-1", display_name="Admin", email=None, roles=["administrator"],
    permissions=["*"], project_ids=["*"],
)
with SessionLocal() as _db:
    created = M.create_listener(
        M.ListenerCreate(id="ln_open_admin", display_name="Open", auth_type="none"),
        _db, admin,
    )
    _db.commit()
    assert created.auth_type == "none"
passed += 1
print("  ok: an administrator still can, deliberately")

print(f"\nWEBHOOKS verified: {passed} assertions passed.")
engine.dispose()
_tmp.cleanup()

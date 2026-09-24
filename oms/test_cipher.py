"""Cipher channels, licences and operations, authorized as the calling principal.

R15 of GOAL_REPAIR_2026-08-23. Every operation used to take its principal from the request
body: encrypt and hash checked no licence when the body named nobody, decrypt let an
administrator name anyone, a licence id matched whoever held it, and granting a licence
answered to `edit`, so an editor could issue themselves an `admin` licence. Now grants and
channels need `administer`, operations need `execute` and a licence of the caller's own,
and a body may name the caller and no one else. Each section acts as a real caller.
"""
import os, tempfile, hashlib

_t = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(_t.name, 't.db')}"

from fastapi import FastAPI                          # noqa: E402
from fastapi.testclient import TestClient            # noqa: E402
from app.database import Base, engine, SessionLocal  # noqa: E402
from app import models, models_action, production_auth  # noqa: E402  (registers core + audit tables)
from app import cipher as M                          # noqa: E402  (owned module)

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


OPERATOR = ["view", "edit", "execute"]


def as_caller(principal_id, permissions=OPERATOR):
    """Every request after this runs as `principal_id`; None goes back to the local administrator."""
    if principal_id is None:
        api.dependency_overrides.pop(production_auth.current_principal, None)
        return
    caller = production_auth.Principal(principal_id, principal_id, None, ["operator"], permissions,
                                       project_ids=["default"])
    api.dependency_overrides[production_auth.current_principal] = lambda: caller


def audits(event_type):
    with SessionLocal() as db:
        return db.query(models_action.AuditLog).filter(models_action.AuditLog.event_type == event_type).all()


# ---------------------------------------------------------------------------
# 1) Channels: created by an administrator, refused to anyone else.
# ---------------------------------------------------------------------------
ch = ok(client.post("/cipher/channels", json={
    "id": "ch_enc", "display_name": "PII", "mode": "encrypt",
    "key_ref": "kms://k1", "algorithm": "AES-GCM", "require_justification": True,
}), "create encrypt channel")
check(ch["algorithm"] == "AES-GCM", "channel stores algorithm")
check(ch["require_justification"] is True, "channel requires justification")
check(any(row.actor == "local-admin" for row in audits("cipher.channel.created")), "channel creation audited as its caller")

lst = ok(client.get("/cipher/channels"), "list channels")
check(any(c["id"] == "ch_enc" for c in lst), "channel appears in list")

as_caller("mallory")
ok(client.post("/cipher/channels", json={
    "id": "ch_mallory", "display_name": "M", "mode": "encrypt", "key_ref": "kms://m",
}), "an operator cannot create a channel", expect=403)
as_caller(None)

# ---------------------------------------------------------------------------
# 2) Licences: granted by an administrator. An operator cannot grant one -- least of
#    all an `admin` licence to themselves, which used to pass every check after it.
# ---------------------------------------------------------------------------
op_lic = ok(client.post("/cipher/channels/ch_enc/licenses", json={
    "principal": "alice", "license_type": "operational_user",
}), "create operational_user license")
check(op_lic["license_type"] == "operational_user", "operational license type stored")
ok(client.post("/cipher/channels/ch_enc/licenses", json={
    "principal": "bob", "license_type": "data_manager",
}), "create data_manager license")
ok(client.post("/cipher/channels/ch_enc/licenses", json={
    "principal": "carol", "license_type": "admin",
}), "create admin license")
ok(client.post("/cipher/channels/ch_enc/licenses", json={
    "principal": "dan", "license_type": "bogus",
}), "reject unknown license type", expect=422)
granted = audits("cipher.license.granted")
check(len(granted) == 3 and all(row.actor == "local-admin" for row in granted),
      "every grant is audited, naming who granted it")
check({row.payload["principal"] for row in granted} == {"alice", "bob", "carol"}, "the audit names each grantee")

as_caller("mallory")
ok(client.post("/cipher/channels/ch_enc/licenses", json={
    "principal": "mallory", "license_type": "admin",
}), "an operator cannot grant themselves an admin licence", expect=403)
ok(client.post("/cipher/encrypt", json={"channel_id": "ch_enc", "value": "x"}),
   "and so holds none to encrypt with", expect=403)
as_caller(None)

# ---------------------------------------------------------------------------
# 3) encrypt: the caller's own licence, whatever the body says.
# ---------------------------------------------------------------------------
as_caller("bob")  # data_manager
enc = ok(client.post("/cipher/encrypt", json={"channel_id": "ch_enc", "value": "secret"}),
         "data_manager can encrypt")
ct = enc["ciphertext"]
check(ct.startswith("CIPHER::ch_enc::") and ct.endswith("::CIPHER"), "canonical wrapper emitted")
ok(client.post("/cipher/encrypt", json={"channel_id": "ch_enc", "value": "s", "principal": "bob"}),
   "a body may name its own caller")
ok(client.post("/cipher/encrypt", json={"channel_id": "ch_enc", "value": "s", "principal": "carol"}),
   "a body may not name another principal", expect=403)
with SessionLocal() as db:
    carols = db.query(M.CipherLicense).filter(M.CipherLicense.principal == "carol").one().id
ok(client.post("/cipher/encrypt", json={"channel_id": "ch_enc", "value": "s", "license_id": carols}),
   "another principal's licence id authorizes nothing", expect=403)

as_caller("alice")  # operational_user
ok(client.post("/cipher/encrypt", json={"channel_id": "ch_enc", "value": "secret"}),
   "operational_user denied encrypt", expect=403)
ok(client.post("/cipher/encrypt", json={"channel_id": "ch_enc", "value": "secret", "principal": "bob"}),
   "operational_user cannot encrypt by naming a data_manager", expect=403)

as_caller(None)  # the local administrator holds no licence on this channel
ok(client.post("/cipher/encrypt", json={"channel_id": "ch_enc", "value": "legacy"}),
   "an encrypt that names nobody is authorized as its caller, who holds no licence", expect=403)

as_caller("bob", ["view", "edit"])
ok(client.post("/cipher/encrypt", json={"channel_id": "ch_enc", "value": "secret"}),
   "a licence without the execute permission does not run the operation", expect=403)

# ---------------------------------------------------------------------------
# 4) decrypt: justification, the caller's licence, and the caller in the audit.
# ---------------------------------------------------------------------------
as_caller("alice")
ok(client.post("/cipher/decrypt", json={"channel_id": "ch_enc", "ciphertext": ct}),
   "decrypt missing justification -> 422", expect=422)
ok(client.post("/cipher/decrypt", json={"channel_id": "ch_enc", "ciphertext": ct, "justification": "   "}),
   "decrypt blank justification -> 422", expect=422)
dec = ok(client.post("/cipher/decrypt", json={
    "channel_id": "ch_enc", "ciphertext": ct, "justification": "investigating fraud case 42",
}), "operational_user decrypt with justification")
check(dec["value"] == "secret", "decrypt round-trips canonical wrapper")

as_caller("nobody")
ok(client.post("/cipher/decrypt", json={"channel_id": "ch_enc", "ciphertext": ct, "justification": "x"}),
   "unlicensed principal denied decrypt", expect=403)
ok(client.post("/cipher/decrypt", json={
    "channel_id": "ch_enc", "ciphertext": ct, "principal": "alice", "justification": "x",
}), "an unlicensed principal cannot decrypt by naming a licensed one", expect=403)

as_caller(None)
ok(client.post("/cipher/decrypt", json={
    "channel_id": "ch_enc", "ciphertext": ct, "principal": "alice", "justification": "recovery",
}), "an administrator no longer decrypts on another principal's licence", expect=403)

decrypts = audits("cipher.decrypt")
check(len(decrypts) == 1, "only the authorized decrypt is audited")
check(decrypts[0].actor == "alice" and decrypts[0].payload.get("principal") == "alice",
      "the decrypt audit names the caller")
check(decrypts[0].payload.get("justification") == "investigating fraud case 42",
      "justification recorded in audit payload")
check(decrypts[0].payload.get("license_type") == "operational_user", "license_type recorded in audit")

# ---------------------------------------------------------------------------
# 5) hash: deterministic sha256/sha512 digests, with a licence of the caller's own.
# ---------------------------------------------------------------------------
as_caller("alice")
h256_a = ok(client.post("/cipher/hash", json={"channel_id": "ch_enc", "value": "ssn-123", "algorithm": "sha256"}),
            "hash sha256")
h256_b = ok(client.post("/cipher/hash", json={"channel_id": "ch_enc", "value": "ssn-123", "algorithm": "sha256"}),
            "hash sha256 again")
check(h256_a["digest"] == h256_b["digest"], "sha256 hash is deterministic")
check(len(h256_a["digest"]) == 64, "sha256 digest is 64 hex chars")
expected = hashlib.sha256(("ssn-123" + "::" + "kms://k1").encode()).hexdigest()
check(h256_a["digest"] == expected, "sha256 digest matches peppered scheme")
h512 = ok(client.post("/cipher/hash", json={"channel_id": "ch_enc", "value": "ssn-123", "algorithm": "sha512"}),
          "hash sha512")
check(len(h512["digest"]) == 128, "sha512 digest is 128 hex chars")
ok(client.post("/cipher/hash", json={"channel_id": "ch_enc", "value": "x", "algorithm": "md5"}),
   "reject unknown hash algorithm", expect=422)
as_caller("nobody")
ok(client.post("/cipher/hash", json={"channel_id": "ch_enc", "value": "x", "algorithm": "sha256"}),
   "a hash that names nobody is authorized as its caller, who holds no licence", expect=403)

# ---------------------------------------------------------------------------
# 6) tokenize: an encrypt-class operation, since a token is reversible.
# ---------------------------------------------------------------------------
as_caller(None)
ok(client.post("/cipher/channels", json={
    "id": "ch_tok", "display_name": "Tok", "mode": "tokenize", "key_ref": "kms://k2",
}), "create tokenize channel")
ok(client.post("/cipher/channels/ch_tok/licenses", json={"principal": "bob", "license_type": "data_manager"}),
   "grant a tokenize licence")
as_caller("bob")
tok = ok(client.post("/cipher/tokenize", json={"channel_id": "ch_tok", "value": "hello"}), "tokenize value")
check(tok["token"].startswith("tok_"), "token format preserved")
ok(client.post("/cipher/encrypt", json={"channel_id": "ch_tok", "value": "x"}),
   "encrypt wrong mode -> 422", expect=422)
as_caller("alice")
ok(client.post("/cipher/tokenize", json={"channel_id": "ch_tok", "value": "hello"}),
   "tokenize without a licence on the channel", expect=403)

as_caller(None)
print(f"{passed} assertions passed")

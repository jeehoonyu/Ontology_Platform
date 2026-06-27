import os, tempfile, hashlib

_t = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(_t.name, 't.db')}"

from fastapi import FastAPI                          # noqa: E402
from fastapi.testclient import TestClient            # noqa: E402
from app.database import Base, engine, SessionLocal  # noqa: E402
from app import models, models_action               # noqa: E402  (registers core + audit tables)
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


# ---------------------------------------------------------------------------
# 1) Create an encrypt channel with a stored algorithm.
# ---------------------------------------------------------------------------
ch = ok(client.post("/cipher/channels", json={
    "id": "ch_enc", "display_name": "PII", "mode": "encrypt",
    "key_ref": "kms://k1", "algorithm": "AES-GCM", "require_justification": True,
}), "create encrypt channel")
check(ch["algorithm"] == "AES-GCM", "channel stores algorithm")
check(ch["require_justification"] is True, "channel requires justification")

# list reflects channel
lst = ok(client.get("/cipher/channels"), "list channels")
check(any(c["id"] == "ch_enc" for c in lst), "channel appears in list")

# ---------------------------------------------------------------------------
# 2) License types: create one of each and validate rejection of unknown type.
# ---------------------------------------------------------------------------
op_lic = ok(client.post("/cipher/channels/ch_enc/licenses", json={
    "principal": "alice", "license_type": "operational_user",
}), "create operational_user license")
check(op_lic["license_type"] == "operational_user", "operational license type stored")

dm_lic = ok(client.post("/cipher/channels/ch_enc/licenses", json={
    "principal": "bob", "license_type": "data_manager",
}), "create data_manager license")

admin_lic = ok(client.post("/cipher/channels/ch_enc/licenses", json={
    "principal": "carol", "license_type": "admin",
}), "create admin license")

ok(client.post("/cipher/channels/ch_enc/licenses", json={
    "principal": "dan", "license_type": "bogus",
}), "reject unknown license type", expect=422)

# ---------------------------------------------------------------------------
# 3) encrypt emits canonical wrapper CIPHER::<rid>::<ct>::CIPHER and enforces
#    license type (operational_user may NOT encrypt -> 403).
# ---------------------------------------------------------------------------
enc = ok(client.post("/cipher/encrypt", json={
    "channel_id": "ch_enc", "value": "secret", "principal": "bob",  # data_manager
}), "data_manager can encrypt")
ct = enc["ciphertext"]
check(ct.startswith("CIPHER::ch_enc::") and ct.endswith("::CIPHER"), "canonical wrapper emitted")

# operational_user denied encrypt
ok(client.post("/cipher/encrypt", json={
    "channel_id": "ch_enc", "value": "secret", "principal": "alice",  # operational_user
}), "operational_user denied encrypt", expect=403)

# legacy caller (no identity) still works
enc_legacy = ok(client.post("/cipher/encrypt", json={
    "channel_id": "ch_enc", "value": "legacy",
}), "legacy encrypt without identity")
check(enc_legacy["ciphertext"].startswith("CIPHER::ch_enc::"), "legacy encrypt wrapped")

# ---------------------------------------------------------------------------
# 4) decrypt requires justification (422 if absent) and records it in AuditLog.
# ---------------------------------------------------------------------------
# missing justification -> 422 (Pydantic required field)
ok(client.post("/cipher/decrypt", json={
    "channel_id": "ch_enc", "ciphertext": ct, "principal": "alice",
}), "decrypt missing justification -> 422", expect=422)

# empty/whitespace justification -> 422
ok(client.post("/cipher/decrypt", json={
    "channel_id": "ch_enc", "ciphertext": ct, "principal": "alice", "justification": "   ",
}), "decrypt blank justification -> 422", expect=422)

# valid decrypt by operational_user with justification (round-trips wrapper)
dec = ok(client.post("/cipher/decrypt", json={
    "channel_id": "ch_enc", "ciphertext": ct, "principal": "alice",
    "justification": "investigating fraud case 42",
}), "operational_user decrypt with justification")
check(dec["value"] == "secret", "decrypt round-trips canonical wrapper")

# principal without a license -> 403
ok(client.post("/cipher/decrypt", json={
    "channel_id": "ch_enc", "ciphertext": ct, "principal": "nobody",
    "justification": "x",
}), "unlicensed principal denied decrypt", expect=403)

# audit log recorded the justification
db = SessionLocal()
audit = (
    db.query(models_action.AuditLog)
    .filter(models_action.AuditLog.event_type == "cipher.decrypt")
    .first()
)
check(audit is not None, "decrypt audit row written")
check(audit.payload.get("justification") == "investigating fraud case 42",
      "justification recorded in audit payload")
check(audit.payload.get("license_type") == "operational_user", "license_type recorded in audit")
db.close()

# ---------------------------------------------------------------------------
# 5) hash endpoint — deterministic sha256/sha512 digests + algorithm validation.
# ---------------------------------------------------------------------------
h256_a = ok(client.post("/cipher/hash", json={
    "channel_id": "ch_enc", "value": "ssn-123", "algorithm": "sha256", "principal": "alice",
}), "hash sha256")
h256_b = ok(client.post("/cipher/hash", json={
    "channel_id": "ch_enc", "value": "ssn-123", "algorithm": "sha256", "principal": "alice",
}), "hash sha256 again")
check(h256_a["digest"] == h256_b["digest"], "sha256 hash is deterministic")
check(len(h256_a["digest"]) == 64, "sha256 digest is 64 hex chars")

# verify the digest matches the documented peppering scheme
expected = hashlib.sha256(("ssn-123" + "::" + "kms://k1").encode()).hexdigest()
check(h256_a["digest"] == expected, "sha256 digest matches peppered scheme")

h512 = ok(client.post("/cipher/hash", json={
    "channel_id": "ch_enc", "value": "ssn-123", "algorithm": "sha512", "principal": "alice",
}), "hash sha512")
check(len(h512["digest"]) == 128, "sha512 digest is 128 hex chars")

# unknown algorithm -> 422
ok(client.post("/cipher/hash", json={
    "channel_id": "ch_enc", "value": "x", "algorithm": "md5", "principal": "alice",
}), "reject unknown hash algorithm", expect=422)

# ---------------------------------------------------------------------------
# 6) tokenize preserved.
# ---------------------------------------------------------------------------
ok(client.post("/cipher/channels", json={
    "id": "ch_tok", "display_name": "Tok", "mode": "tokenize", "key_ref": "kms://k2",
}), "create tokenize channel")
tok = ok(client.post("/cipher/tokenize", json={"channel_id": "ch_tok", "value": "hello"}),
         "tokenize value")
check(tok["token"].startswith("tok_"), "token format preserved")

# wrong mode preserved behavior: encrypt on tokenize channel -> 422
ok(client.post("/cipher/encrypt", json={"channel_id": "ch_tok", "value": "x"}),
   "encrypt wrong mode -> 422", expect=422)

print(f"{passed} assertions passed")

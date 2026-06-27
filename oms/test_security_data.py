"""Standalone self-test for app.security_data (owned file).

Builds a local FastAPI app from ONLY the security_data router so it can run
concurrently with siblings editing other modules. Does NOT import app.main.

Run from oms/:
    ./venv312/Scripts/python.exe test_security_data.py
"""

import os
import tempfile

_t = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(_t.name, 't.db')}"

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.database import Base, engine, SessionLocal
from app import models, models_action
from app import security_data as M

Base.metadata.create_all(bind=engine)

api = FastAPI()
api.include_router(M.router)
client = TestClient(api)

passed = 0


def check(cond, label):
    global passed
    assert cond, f"FAILED: {label}"
    passed += 1
    print(f"  ok: {label}")


def audit_count(event_type, subject_id=None):
    db = SessionLocal()
    try:
        q = db.query(models_action.AuditLog).filter(
            models_action.AuditLog.event_type == event_type
        )
        if subject_id is not None:
            q = q.filter(models_action.AuditLog.subject_id == subject_id)
        return q.count()
    finally:
        db.close()


print("== Checkpoints: pass requires justification ==")

# Create a checkpoint
r = client.post("/checkpoints", json={"action_label": "delete-dataset", "requires_approval": True})
check(r.status_code == 200, "create checkpoint -> 200")
cp = r.json()
cp_id = cp["id"]
check(cp["status"] == "open", "new checkpoint status is open")

# Pass without a body -> 422 (justification required)
r = client.post(f"/checkpoints/{cp_id}/pass")
check(r.status_code == 422, "pass with no body -> 422")

# Pass with empty justification -> 422
r = client.post(f"/checkpoints/{cp_id}/pass", json={"justification": "   "})
check(r.status_code == 422, "pass with whitespace justification -> 422")

# Pass with empty-string justification -> 422 (pydantic min_length)
r = client.post(f"/checkpoints/{cp_id}/pass", json={"justification": ""})
check(r.status_code == 422, "pass with empty-string justification -> 422")

# No audit log should have been written by the failed attempts
check(audit_count("security.checkpoint.passed", cp_id) == 0, "no audit row before successful pass")

# Pass with a valid justification + bound trigger/resource
r = client.post(
    f"/checkpoints/{cp_id}/pass",
    json={
        "justification": "Quarterly compliance purge approved by legal",
        "actor": "alice",
        "trigger": "dataset-export",
        "resource_type": "dataset",
        "resource_id": "ds-123",
    },
)
check(r.status_code == 200, "pass with justification -> 200")
out = r.json()
check(out["status"] == "passed", "checkpoint now passed")
check(out["justification"] == "Quarterly compliance purge approved by legal", "justification persisted")
check(out["trigger"] == "dataset-export", "trigger bound")
check(out["resource_type"] == "dataset" and out["resource_id"] == "ds-123", "resource bound")
check(out["passed_by"] == "alice", "passed_by recorded")
check(out["passed_at"] is not None, "passed_at recorded")

# An AuditLog row was written on pass
check(audit_count("security.checkpoint.passed", cp_id) == 1, "audit row written on pass")

# Passing again is idempotent (returns passed checkpoint, no second audit row)
r = client.post(f"/checkpoints/{cp_id}/pass", json={"justification": "again"})
check(r.status_code == 200, "re-pass -> 200 (idempotent)")
check(audit_count("security.checkpoint.passed", cp_id) == 1, "no duplicate audit row on re-pass")

# Passing a missing checkpoint -> 404
r = client.post("/checkpoints/does-not-exist/pass", json={"justification": "x"})
check(r.status_code == 404, "pass unknown checkpoint -> 404")


print("== Retention: deterministic sweep expires/archives elapsed policies ==")

# Create policies with explicit ids and known TTLs. created_at is wall-clock,
# so we drive the sweep with an explicit 'now' far in the future.
r = client.post(
    "/retention-policies",
    json={"id": "pol-del", "resource_type": "dataset", "resource_id": "ds-A", "ttl_seconds": 100, "action": "delete"},
)
check(r.status_code == 200, "create delete policy -> 200")
del_created = r.json()["created_at"]
check(r.json()["status"] == "active", "new policy status active")

r = client.post(
    "/retention-policies",
    json={"id": "pol-arch", "resource_type": "media_set", "resource_id": "ms-B", "ttl_seconds": 100, "action": "archive"},
)
check(r.status_code == 200, "create archive policy -> 200")

r = client.post(
    "/retention-policies",
    json={"id": "pol-fresh", "resource_type": "dataset", "resource_id": "ds-C", "ttl_seconds": 10_000_000, "action": "delete"},
)
check(r.status_code == 200, "create long-ttl policy -> 200")

# Sweep with now BEFORE any TTL elapses -> nothing expired
r = client.post("/retention-policies/enforce", json={"now": del_created + 1})
check(r.status_code == 200, "enforce (early now) -> 200")
check(r.json()["expired_count"] == 0, "nothing expired before TTL elapses")

# Sweep with now AFTER the 100s TTLs (but before the huge one) elapses
sweep_now = del_created + 1000
r = client.post("/retention-policies/enforce", json={"now": sweep_now})
check(r.status_code == 200, "enforce (late now) -> 200")
body = r.json()
ids = {item["policy_id"]: item for item in body["expired"]}
check(body["expired_count"] == 2, "two policies expired")
check("pol-del" in ids and ids["pol-del"]["status"] == "expired", "delete policy -> expired")
check("pol-arch" in ids and ids["pol-arch"]["status"] == "archived", "archive policy -> archived")
check("pol-fresh" not in ids, "long-ttl policy not expired")
check(ids["pol-del"]["enforced_at"] == sweep_now, "enforced_at uses provided now")

# Audit rows written for both expirations
check(audit_count("security.retention.expired", "ds-A") == 1, "audit row for expired dataset")
check(audit_count("security.retention.archived", "ms-B") == 1, "audit row for archived media_set")

# Sweep is idempotent: re-running does not re-expire already-terminal policies
r = client.post("/retention-policies/enforce", json={"now": sweep_now})
check(r.json()["expired_count"] == 0, "re-sweep expires nothing (idempotent)")
check(audit_count("security.retention.expired", "ds-A") == 1, "no duplicate audit on re-sweep")

# resource_type filter scopes the sweep
r = client.post("/retention-policies/enforce", json={"now": sweep_now + 20_000_000, "resource_type": "media_set"})
check(r.json()["expired_count"] == 0, "filtered sweep (media_set) finds nothing new")

# Now sweep datasets far in the future -> the long-ttl one expires
r = client.post("/retention-policies/enforce", json={"now": sweep_now + 20_000_000, "resource_type": "dataset"})
check(r.json()["expired_count"] == 1 and r.json()["expired"][0]["policy_id"] == "pol-fresh",
      "filtered dataset sweep expires the long-ttl policy")

# Listing reflects updated statuses
r = client.get("/retention-policies")
check(r.status_code == 200, "list retention policies -> 200")
statuses = {p["id"]: p["status"] for p in r.json()}
check(statuses.get("pol-del") == "expired", "list shows pol-del expired")
check(statuses.get("pol-arch") == "archived", "list shows pol-arch archived")
check(statuses.get("pol-fresh") == "expired", "list shows pol-fresh expired")


print("== Preserved behavior: markings / restricted views / scan still work ==")

# Marking + grant (audit on grant preserved)
r = client.post("/markings", json={"display_name": "PII", "category": "PII"})
check(r.status_code == 200, "create marking -> 200")
m_id = r.json()["id"]
r = client.post(f"/markings/{m_id}/grant", json={"principal": "bob"})
check(r.status_code == 200, "grant marking -> 200")

# Restricted view masks for an uncleared principal
r = client.post(
    "/restricted-views",
    json={
        "display_name": "ssn-view",
        "object_type_id": "person",
        "masked_properties": ["ssn"],
        "required_marking_id": m_id,
    },
)
check(r.status_code == 200, "create restricted view -> 200")
v_id = r.json()["id"]
r = client.post(
    f"/restricted-views/{v_id}/apply",
    json={"principal": "carol", "rows": [{"name": "x", "ssn": "111-22-3333"}]},
)
check(r.status_code == 200, "apply restricted view -> 200")
check(r.json()["rows"][0]["ssn"] == "***", "uncleared principal sees masked ssn")

# Cleared principal (bob holds the marking) sees raw
r = client.post(
    f"/restricted-views/{v_id}/apply",
    json={"principal": "bob", "rows": [{"name": "x", "ssn": "111-22-3333"}]},
)
check(r.json()["rows"][0]["ssn"] == "111-22-3333", "cleared principal sees raw ssn")

# Governance scan still detects patterns
r = client.post("/governance/scan", json={"records": [{"email": "a@b.com"}]})
check(r.status_code == 200 and any(f["pattern"] == "email" for f in r.json()["findings"]),
      "governance scan detects email")

print(f"\n{passed} assertions passed")

"""
A decision evaluation scores its whole scope, and says how much of it that was.

GOAL_HONEST_UI_2026-09-11. The Decision workspace asked for `limit: 250`, the server
scored the first 250 objects by id, and the Risk Board and its metrics read as the
whole type: a critical object at id 251 changed no number and never appeared. These
hold the fix: totals counted over the scan's own filters, bands and averages over every
scored object, findings kept by score, and the ops event's severity from all of them.

Run:
  python oms/test_decision_scope_totals.py
"""
import os
import tempfile

tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tmpdir.name, 'decision_scope.db')}"

from fastapi.testclient import TestClient  # noqa: E402
from app import decision_intelligence, models  # noqa: E402
from app.database import SessionLocal  # noqa: E402
from app.main import app  # noqa: E402

client = TestClient(app)
passed = 0


def ok(resp, label, expect=200):
    global passed
    success = resp.status_code == expect or (expect == 200 and 200 <= resp.status_code < 300)
    assert success, f"{label}: expected {expect}, got {resp.status_code} -> {resp.text[:800]}"
    passed += 1
    return resp.json() if resp.content else {}


def check(condition, label, detail=""):
    global passed
    assert condition, f"{label}: {detail}"
    passed += 1


def hydrate(type_id, risky):
    """300 objects of a fresh type, critical at the indexes in `risky`, low elsewhere."""
    ok(client.post("/object-types", json={
        "id": type_id, "display_name": type_id, "description": "Decision scope totals",
        "properties": {"name": {"type": "string"}, "status": {"type": "string"}, "criticality": {"type": "string"}},
    }), f"{type_id} type")
    records = [{
        "id": f"{type_id}_{index:04d}",
        "name": f"Object {index}",
        "status": "DEGRADED" if index in risky else "RUNNING",
        "criticality": "high" if index in risky else "low",
    } for index in range(1, 301)]
    ok(client.post("/data-assets", json={
        "id": f"{type_id}_feed", "display_name": f"{type_id} feed", "kind": "dataset", "asset_schema": {}, "records": records,
    }), f"{type_id} feed")
    ok(client.post("/pipelines", json={
        "id": f"{type_id}_hydrate", "display_name": f"{type_id} hydrate", "input_asset_id": f"{type_id}_feed",
        "steps": [{
            "operation": "map_to_ontology", "object_type_id": type_id, "object_id_field": "id",
            "property_map": {"name": "$name", "status": "$status", "criticality": "$criticality"}, "omit_nulls": True,
        }],
    }), f"{type_id} pipeline")
    run = ok(client.post(f"/pipelines/{type_id}_hydrate/run", params={"actor": "test"}), f"{type_id} hydrate")
    check(run.get("status") == "SUCCESS", f"{type_id} hydrate succeeded", run)
    # 60 + 30 = 90, critical, for a degraded high-criticality object; 0, low, otherwise.
    ok(client.post("/decision/rules", json={
        "id": f"{type_id}_degraded", "display_name": "Degraded", "object_type_id": type_id,
        "expression": {"field": "status", "op": "eq", "value": "DEGRADED"}, "severity": "high",
    }), f"{type_id} rule")
    ok(client.post("/decision/scorecards", json={
        "id": f"{type_id}_scorecard", "display_name": "Scope totals scorecard", "object_type_id": type_id,
        "features": [
            {"rule_id": f"{type_id}_degraded", "weight": 60, "reason": "degraded"},
            {"field": "criticality", "op": "eq", "value": "high", "weight": 30, "reason": "high criticality"},
        ],
        "thresholds": {"medium": 35, "high": 65, "critical": 85},
    }), f"{type_id} scorecard")


def evaluate(type_id, **overrides):
    body = {"object_type_id": type_id, "filters": {}, "limit": 10000, "finding_limit": 250, "persist_run": True, **overrides}
    return ok(client.post("/decision/evaluate", json=body), f"evaluate {type_id}")


# 1. Totals, bands and ranking over the whole scope. Index 2 is risky inside the old
# 250; 251 to 300 are risky past it.
RISKY = "risk_cut"
hydrate(RISKY, {2, *range(251, 301)})
result = evaluate(RISKY)
check(result["objects_in_scope"] == 300 and result["object_count"] == 300, "every object in scope is scored",
      {key: result.get(key) for key in ("objects_in_scope", "object_count", "scan_limit")})
check(result["band_counts"] == {"low": 249, "medium": 0, "high": 0, "critical": 51}, "bands count every scored object", result["band_counts"])
check(result["high_risk_count"] == 51, "high-risk count covers every scored object", result["high_risk_count"])
check(abs(result["average_score"] - 15.3) < 1e-9, "average covers every scored object", result["average_score"])
findings = result["findings"]
check(len(findings) == 250 and result["findings_retained"] == 250, "findings are kept to the limit", len(findings))
check(findings[0]["object_id"] == f"{RISKY}_0002", "the first finding is the riskiest, lowest id on a tie", findings[0]["object_id"])
kept_ids = {finding["object_id"] for finding in findings}
missing = [f"{RISKY}_{index:04d}" for index in range(251, 301) if f"{RISKY}_{index:04d}" not in kept_ids]
check(not missing, "every critical object past id 250 is kept", missing[:5])
scores = [finding["risk"]["score"] for finding in findings]
check(scores == sorted(scores, reverse=True), "findings are ordered by score", scores[:5])
check(result["unlisted_max_score"] == 0 and result["finding_order"] == "score_desc", "what was left out is stated",
      {key: result.get(key) for key in ("unlisted_max_score", "finding_order")})

# The Object Explorer's call names its objects and sends no finding limit: it keeps
# every finding, in id order, and its total is the ids it named.
named = ok(client.post("/decision/evaluate", json={
    "object_type_id": RISKY, "object_ids": [f"{RISKY}_0002", f"{RISKY}_0001"], "persist_run": False,
}), "evaluate named objects")
check(named["object_count"] == 2 and named["objects_in_scope"] == 2, "a named scope counts only its ids",
      {key: named.get(key) for key in ("object_count", "objects_in_scope")})
check([finding["object_id"] for finding in named["findings"]] == [f"{RISKY}_0001", f"{RISKY}_0002"] and named["finding_order"] == "id_asc",
      "with no finding limit every finding is kept in id order", [finding["object_id"] for finding in named["findings"]])

# 2. The scan ceiling is stated from a true total, and retired objects leave the scope.
decision_intelligence.EVALUATE_SCAN_CEILING = 100
try:
    capped = evaluate(RISKY)
finally:
    decision_intelligence.EVALUATE_SCAN_CEILING = 10000
check(capped["object_count"] == 100 and capped["objects_in_scope"] == 300 and capped["scan_limit"] == 100,
      "past the ceiling the total still counts the whole scope",
      {key: capped.get(key) for key in ("object_count", "objects_in_scope", "scan_limit")})

db = SessionLocal()
try:
    retired_ids = [f"{RISKY}_{index:04d}" for index in range(296, 301)]
    for obj in db.query(models.ObjectInstance).filter(models.ObjectInstance.id.in_(retired_ids)).all():
        obj.is_active = False
    db.commit()
finally:
    db.close()
retired = evaluate(RISKY)
check(retired["objects_in_scope"] == 295 and retired["object_count"] == 295, "the total leaves out retired objects, as the scan does",
      {key: retired.get(key) for key in ("objects_in_scope", "object_count")})

# 3. The ops event takes its severity from every scored object. On this type nothing in
# the first 250 by id is risky, so the old event said "info".
TAIL = "risk_tail"
hydrate(TAIL, set(range(251, 301)))
tail = evaluate(TAIL)
events = ok(client.get("/ops/events", params={"source": "decision", "limit": 500}), "decision ops events")
event = next((item for item in events if item.get("subject_id") == tail["id"]), None)
check(event is not None, "the evaluation recorded an ops event", [item.get("subject_id") for item in events][:5])
check(event["severity"] == "critical", "the event's severity covers objects past id 250", event)
payload = event.get("payload") or {}
check(payload.get("band_counts", {}).get("critical") == 50 and payload.get("objects_in_scope") == 300 and "bands" not in payload,
      "the event carries band counts and the total, not one band per object", payload)

db = SessionLocal()
try:
    stored = db.get(decision_intelligence.DecisionRun, tail["id"])
    check(stored is not None and stored.object_count == 300 and len(stored.findings or []) == 250
          and (stored.scope or {}).get("band_counts", {}).get("critical") == 50,
          "the saved run holds the scored count, the kept findings and the bands",
          None if stored is None else {"object_count": stored.object_count, "findings": len(stored.findings or []), "scope_bands": (stored.scope or {}).get("band_counts")})
finally:
    db.close()

print(f"\nDecision scope totals verified: {passed} assertions passed.")
from app.database import engine as _engine  # noqa: E402
_engine.dispose()
tmpdir.cleanup()

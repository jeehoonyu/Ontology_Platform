"""
Decision Intelligence layer regression tests.

Run:
  python test_decision_intelligence.py
"""
import os
import tempfile

tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tmpdir.name, 'decision.db')}"

from fastapi.testclient import TestClient  # noqa: E402
from app.main import app  # noqa: E402

client = TestClient(app)
passed = 0


def ok(resp, label, expect=200):
    global passed
    success = resp.status_code == expect or (expect == 200 and 200 <= resp.status_code < 300)
    assert success, f"{label}: expected {expect}, got {resp.status_code} -> {resp.text[:800]}"
    passed += 1
    return resp.json() if resp.content else {}


ok(client.post("/object-types", json={
    "id": "asset",
    "display_name": "Asset",
    "description": "Operational asset",
    "properties": {
        "name": {"type": "string"},
        "status": {"type": "string"},
        "criticality": {"type": "string"},
        "serial": {"type": "string"},
        "flagged": {"type": "boolean"},
    },
}), "asset object type")

for object_id, name, status, criticality, serial in [
    ("asset_1", "Pump A", "DEGRADED", "high", "P-100"),
    ("asset_2", "pump a", "DEGRADED", "high", "P-100-copy"),
    ("asset_3", "Chiller B", "DEGRADED", "high", "C-200"),
]:
    ok(client.post("/objects", json={
        "id": object_id,
        "object_type_id": "asset",
        "properties": {"name": name, "status": status, "criticality": criticality, "serial": serial, "flagged": False},
    }), f"create {object_id}")

timeline = ok(client.get("/temporal/objects/asset/asset_1/timeline"), "creation timeline")
assert len(timeline["timeline"]) == 1 and timeline["timeline"][0]["event_type"] == "ontology.object.created", timeline

ok(client.post("/decision/rules", json={
    "id": "degraded_asset_rule",
    "display_name": "Asset is degraded",
    "object_type_id": "asset",
    "expression": {"field": "status", "op": "eq", "value": "DEGRADED"},
    "severity": "high",
    "recommended_actions": ["inspect_asset", "stage_escalation"],
}), "create decision rule")
ok(client.post("/decision/scorecards", json={
    "id": "asset_risk_scorecard",
    "display_name": "Asset Risk Scorecard",
    "object_type_id": "asset",
    "features": [
        {"rule_id": "degraded_asset_rule", "weight": 60, "reason": "asset is degraded"},
        {"field": "criticality", "op": "eq", "value": "high", "weight": 30, "reason": "high criticality"},
    ],
    "thresholds": {"medium": 35, "high": 65, "critical": 85},
    "recommended_actions": ["review_timeline"],
}), "create scorecard")

evaluation = ok(client.post("/decision/evaluate", json={
    "object_type_id": "asset",
    "object_ids": ["asset_1", "asset_3"],
    "persist_run": True,
}), "evaluate decision scope")
assert evaluation["status"] == "SUCCESS" and evaluation["object_count"] == 2, evaluation
asset_1_risk = next(item["risk"] for item in evaluation["findings"] if item["object_id"] == "asset_1")
assert asset_1_risk["score"] == 90 and asset_1_risk["band"] == "critical", asset_1_risk

explanation = ok(client.get("/decision/objects/asset/asset_1/explain"), "explain object")
assert explanation["risk"]["band"] == "critical" and explanation["temporal_summary"]["snapshot_count"] == 1, explanation

ok(client.post("/action-types", json={
    "id": "escalate_asset",
    "display_name": "Escalate Asset",
    "description": "Escalate an asset for review",
    "parameters": {"object_id": {"type": "string"}, "reason": {"type": "string"}},
    "rules": {
        "object_mutations": [
            {"object_type_id": "asset", "object_id": "$object_id", "set": {"status": "ESCALATED", "flagged": True}}
        ]
    },
}), "create action")
action_result = ok(client.post("/actions/execute", json={
    "action_type_id": "escalate_asset",
    "parameters": {"object_id": "asset_1", "reason": "test"},
    "idempotency_key": "decision-action-asset-1",
    "actor": "test",
}), "execute action")
assert action_result["status"] == "SUCCESS" and "asset_1" in action_result["mutated_object_ids"], action_result

timeline = ok(client.get("/temporal/objects/asset/asset_1/timeline"), "action timeline")
assert len(timeline["timeline"]) == 2 and timeline["timeline"][-1]["event_type"] == "action.object.mutated", timeline
diff = ok(client.get("/temporal/objects/asset/asset_1/diff", params={"from_seq": 1, "to_seq": 2}), "object diff")
assert diff["changed"]["properties"]["status"]["after"] == "ESCALATED", diff

job = ok(client.post("/entity-resolution/jobs", json={
    "object_type_id": "asset",
    "fields": ["name"],
    "threshold": 85,
}), "entity resolution job")
assert job["candidate_count"] >= 1, job
candidate = next(item for item in job["candidates"] if set(item["object_ids"]) == {"asset_1", "asset_2"})
accepted = ok(client.post(f"/entity-resolution/candidates/{candidate['id']}/accept", json={"actor": "test"}), "accept entity candidate")
assert accepted["status"] == "ACCEPTED" and accepted["merged_object_id"] in {"asset_1", "asset_2"}, accepted
split_id = next(item for item in candidate["object_ids"] if item != accepted["merged_object_id"])
split = ok(client.post(f"/entity-resolution/objects/{split_id}/split", json={"actor": "test", "reason": "test split"}), "split entity")
assert split["lineage"]["resolution_status"] == "SPLIT", split

scenario = ok(client.post("/decision/scenarios", json={
    "id": "asset_outage_scenario",
    "display_name": "Asset Outage Scenario",
    "seed_object_ids": ["asset_3"],
    "overrides": {"asset_3": {"status": "OUTAGE"}},
}), "create scenario")
assert scenario["impact"]["changed_object_count"] == 1, scenario
rerun = ok(client.post("/decision/scenarios/asset_outage_scenario/run"), "rerun scenario")
assert rerun["impact"]["by_object"]["asset_3"]["properties"]["status"]["after"] == "OUTAGE", rerun

ok(client.post("/data-assets", json={
    "id": "asset_feed",
    "display_name": "Asset Feed",
    "kind": "dataset",
    "asset_schema": {},
    "records": [
        {"id": "asset_4", "name": "Compressor C", "status": "RUNNING", "criticality": "medium", "serial": "K-300", "flagged": False}
    ],
}), "create asset feed")
ok(client.post("/pipelines", json={
    "id": "hydrate_assets",
    "display_name": "Hydrate Assets",
    "input_asset_id": "asset_feed",
    "steps": [
        {
            "operation": "map_to_ontology",
            "object_type_id": "asset",
            "object_id_field": "id",
            "property_map": {
                "name": "$name",
                "status": "$status",
                "criticality": "$criticality",
                "serial": "$serial",
                "flagged": "$flagged",
            },
        }
    ],
}), "create hydration pipeline")
pipeline_run = ok(client.post("/pipelines/hydrate_assets/run", params={"actor": "test"}), "run hydration pipeline")
assert pipeline_run["status"] == "SUCCESS", pipeline_run
pipeline_timeline = ok(client.get("/temporal/objects/asset/asset_4/timeline"), "pipeline object timeline")
assert pipeline_timeline["timeline"][0]["event_type"] == "pipeline.object.created", pipeline_timeline

ok(client.post("/agents", json={
    "id": "decision_agent",
    "display_name": "Decision Agent",
    "description": "Decision-aware local agent",
    "allowed_object_types": ["asset"],
    "allowed_actions": ["escalate_asset"],
    "approval_required": False,
}), "create agent")
session = ok(client.post("/agents/decision_agent/sessions", json={
    "user_prompt": "Please escalate asset after checking risk",
    "max_context_objects": 5,
}), "run decision-aware agent")
assert "decision_intelligence" in session["context"], session["context"]
assert session["proposed_actions"] and session["proposed_actions"][0]["requires_approval"] is True, session["proposed_actions"]

logic = ok(client.post("/logic-functions", json={
    "id": "decision_logic",
    "display_name": "Decision Logic",
    "description": "Decision block coverage",
    "input_schema": {"object_id": {"type": "string"}},
    "output_schema": {"type": "json"},
    "blocks": [
        {"type": "score_risk", "object_type_id": "asset", "object_id": "$object_id", "output": "risk"},
        {"type": "explain_object", "object_type_id": "asset", "object_id": "$object_id", "output": "explanation"},
        {"type": "run_scenario", "seed_object_ids": ["asset_3"], "overrides": {"asset_3": {"status": "OUTAGE"}}, "output": "scenario"},
    ],
}), "create decision logic")
logic_run = ok(client.post(f"/logic-functions/{logic['id']}/run", json={"inputs": {"object_id": "asset_3"}, "actor": "test"}), "run decision logic")
assert logic_run["status"] == "SUCCESS", logic_run
assert logic_run["outputs"]["risk"]["band"] == "critical", logic_run["outputs"]
assert logic_run["outputs"]["scenario"]["impact"]["changed_object_count"] == 1, logic_run["outputs"]["scenario"]

print(f"\nDecision Intelligence verified: {passed} assertions passed.")
from app.database import engine as _engine  # noqa: E402
_engine.dispose()
tmpdir.cleanup()

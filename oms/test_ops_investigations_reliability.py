"""
Ops Control, Investigations, and Reliability integration tests.

Run:
  python test_ops_investigations_reliability.py
"""
import os
import tempfile

tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tmpdir.name, 'ops.db')}"

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
    "properties": {"name": {"type": "string"}, "criticality": {"type": "string"}, "status": {"type": "string"}},
}), "asset type")
ok(client.post("/objects", json={
    "id": "asset_high",
    "object_type_id": "asset",
    "properties": {"name": "Pump 9", "criticality": "high", "status": "DEGRADED"},
}), "high asset")
ok(client.post("/objects", json={
    "id": "asset_low",
    "object_type_id": "asset",
    "properties": {"name": "Pump 10", "criticality": "low", "status": "RUNNING"},
}), "low asset")
ok(client.post("/decision/rules", json={
    "id": "degraded_rule",
    "display_name": "Degraded asset",
    "object_type_id": "asset",
    "expression": {"field": "status", "op": "eq", "value": "DEGRADED"},
    "severity": "high",
}), "decision rule")
ok(client.post("/decision/scorecards", json={
    "id": "asset_score",
    "display_name": "Asset Score",
    "object_type_id": "asset",
    "features": [
        {"rule_id": "degraded_rule", "weight": 70, "reason": "degraded"},
        {"field": "criticality", "op": "eq", "value": "high", "weight": 20, "reason": "high criticality"},
    ],
    "thresholds": {"medium": 30, "high": 60, "critical": 85},
}), "scorecard")

ok(client.post("/ops/alert-rules", json={
    "id": "decision_high_alert",
    "display_name": "Decision high risk",
    "source": "decision",
    "min_severity": "high",
}), "alert rule")
evaluation = ok(client.post("/decision/evaluate", json={"object_type_id": "asset", "persist_run": True}), "decision evaluate")
assert evaluation["object_count"] == 2, evaluation
alerts_eval = ok(client.post("/ops/alerts/evaluate", json={"limit": 100}), "evaluate alerts")
assert alerts_eval["created_alerts"] >= 0, alerts_eval
alerts = ok(client.get("/ops/alerts"), "list alerts")
assert alerts and alerts[0]["source"] == "decision", alerts
summary = ok(client.get("/ops/summary"), "ops summary")
assert summary["events"] >= 1 and summary["open_alerts"] >= 1, summary

ok(client.post("/action-types", json={
    "id": "escalate_asset",
    "display_name": "Escalate Asset",
    "description": "Requires approval",
    "parameters": {"object_id": {"type": "string"}},
    "rules": {"requires_approval": True},
}), "approval action")
incident = ok(client.post("/ops/incidents", json={
    "id": "incident_asset_high",
    "display_name": "Asset high risk incident",
    "severity": "high",
    "linked_objects": [{"object_type_id": "asset", "object_id": "asset_high"}],
}), "create incident")
assert incident["linked_objects"][0]["object_id"] == "asset_high", incident
runbook = ok(client.post("/ops/runbooks", json={
    "id": "triage_runbook",
    "display_name": "Triage Runbook",
    "steps": [
        {"type": "query_objects", "object_type_id": "asset", "filters": {"criticality": "high"}, "output": "objects"},
        {"type": "request_approval", "action_type_id": "escalate_asset", "parameters": {"object_id": "asset_high"}, "output": "approval"},
        {"type": "create_notification", "title": "Triage complete", "severity": "medium", "output": "notification"},
    ],
}), "create runbook")
execution = ok(client.post(f"/ops/runbooks/{runbook['id']}/execute", json={"incident_id": incident["id"], "actor": "test"}), "execute runbook")
assert execution["status"] == "SUCCESS", execution
approvals = ok(client.get("/approvals"), "approval queue")
assert approvals and approvals[0]["action_type_id"] == "escalate_asset", approvals
inbox = ok(client.get("/ops/inbox"), "ops inbox")
assert inbox, inbox
acked = ok(client.post(f"/ops/inbox/{inbox[0]['id']}/ack"), "ack notification")
assert acked["status"] == "ACKED", acked

ok(client.post("/data-assets", json={
    "id": "raw_assets",
    "display_name": "Raw Assets",
    "kind": "dataset",
    "asset_schema": {},
    "records": [{"id": "r1", "status": "ok"}, {"id": None, "status": "bad"}],
}), "raw asset dataset")
ok(client.post("/data-assets", json={
    "id": "clean_assets",
    "display_name": "Clean Assets",
    "kind": "dataset",
    "asset_schema": {},
    "records": [],
}), "clean asset dataset")
contract = ok(client.post("/reliability/data-contracts", json={
    "id": "raw_asset_contract",
    "display_name": "Raw Asset Contract",
    "asset_id": "raw_assets",
    "checks": [
        {"type": "row_count_bounds", "min": 1},
        {"type": "missing_rate", "field": "id", "max": 0},
    ],
}), "create data contract")
dq_run = ok(client.post(f"/reliability/data-contracts/{contract['id']}/run", json={}), "run data contract")
assert dq_run["status"] == "FAIL", dq_run
ok(client.post("/pipelines", json={
    "id": "asset_cleanup",
    "display_name": "Asset Cleanup",
    "input_asset_id": "raw_assets",
    "output_asset_id": "clean_assets",
    "steps": [],
}), "create classic pipeline")
impact = ok(client.post("/reliability/lineage-impact", json={
    "resource_kind": "dataset",
    "resource_id": "raw_assets",
    "direction": "downstream",
}), "lineage impact")
assert impact["summary"]["node_count"] >= 1, impact
backfill = ok(client.post("/reliability/backfills", json={
    "id": "asset_cleanup_backfill",
    "display_name": "Asset Cleanup Backfill",
    "pipeline_ids": ["asset_cleanup"],
}), "create backfill")
backfill_run = ok(client.post(f"/reliability/backfills/{backfill['id']}/run", json={"actor": "test"}), "run backfill")
assert backfill_run["status"] == "SUCCESS", backfill_run
reliability = ok(client.get("/reliability/summary"), "reliability summary")
assert reliability["data_contracts"] == 1 and reliability["backfills"] == 1, reliability

investigation = ok(client.post("/investigations", json={
    "id": "asset_case",
    "display_name": "Asset Case",
    "object_refs": [{"object_type_id": "asset", "object_id": "asset_high"}],
}), "create investigation")
evidence = ok(client.post(f"/investigations/{investigation['id']}/evidence", json={
    "title": "Sensor evidence",
    "source": "test",
    "object_refs": [{"object_type_id": "asset", "object_id": "asset_high"}],
    "payload": {"temperature": "high"},
    "tags": ["sensor"],
}), "add evidence")
hypothesis = ok(client.post(f"/investigations/{investigation['id']}/hypotheses", json={
    "statement": "Degraded asset is operationally significant",
    "confidence": 75,
    "linked_evidence_ids": [evidence["id"]],
}), "add hypothesis")
assert hypothesis["confidence"] == 75, hypothesis
graph = ok(client.get(f"/investigations/{investigation['id']}/graph"), "investigation graph")
assert graph["node_count"] >= 3 and graph["edge_count"] >= 2, graph
timeline = ok(client.get(f"/investigations/{investigation['id']}/timeline"), "investigation timeline")
assert timeline["timeline"], timeline
report = ok(client.post(f"/investigations/{investigation['id']}/report", json={}), "investigation report")
assert "High risk objects" in report["body"], report
detail = ok(client.get(f"/investigations/{investigation['id']}"), "investigation detail")
assert detail["evidence"][0]["id"] == evidence["id"], detail

logic = ok(client.post("/logic-functions", json={
    "id": "ops_logic",
    "display_name": "Ops Logic",
    "input_schema": {},
    "blocks": [
        {"type": "evaluate_alert_rules", "output": "alerts"},
        {"type": "run_data_contract", "contract_id": "raw_asset_contract", "output": "contract"},
        {"type": "analyze_lineage_impact", "resource_kind": "dataset", "resource_id": "raw_assets", "output": "impact"},
        {"type": "create_incident", "display_name": "Logic Created Incident", "severity": "medium", "output": "incident"},
        {"type": "run_runbook", "runbook_id": "triage_runbook", "incident_id": "$incident.id", "output": "runbook"},
    ],
}), "create ops logic")
logic_run = ok(client.post(f"/logic-functions/{logic['id']}/run", json={"inputs": {}}), "run ops logic")
assert logic_run["status"] == "SUCCESS", logic_run
assert logic_run["outputs"]["contract"]["status"] == "FAIL", logic_run["outputs"]
assert logic_run["outputs"]["runbook"]["status"] == "SUCCESS", logic_run["outputs"]

assert client.get("/workspace/ops").status_code == 200
passed += 1
assert client.get("/workspace/investigations").status_code == 200
passed += 1

print(f"\nOps/Investigations/Reliability verified: {passed} assertions passed.")
from app.database import engine as _engine  # noqa: E402
_engine.dispose()
tmpdir.cleanup()

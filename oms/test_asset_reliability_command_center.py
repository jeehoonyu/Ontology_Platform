"""
Asset Reliability Command Center end-to-end regression test.

Run:
  python test_asset_reliability_command_center.py
"""
import os
import tempfile


tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tmpdir.name, 'asset_reliability.db')}"

from fastapi.testclient import TestClient  # noqa: E402
from app.main import app  # noqa: E402


client = TestClient(app)
passed = 0


def ok(resp, label, expect=200):
    global passed
    success = resp.status_code == expect or (expect == 200 and 200 <= resp.status_code < 300)
    assert success, f"{label}: expected {expect}, got {resp.status_code} -> {resp.text[:1000]}"
    passed += 1
    return resp.json() if resp.content else {}


def assert_true(condition, label, payload=None):
    global passed
    assert condition, f"{label}: {payload}"
    passed += 1


for route in ("/workspace/command-center", "/workspace/search", "/workspace/graph"):
    resp = client.get(route)
    assert_true(resp.status_code == 200, f"{route} loads", resp.status_code)

root = ok(client.get("/"), "root capabilities")
assert_true("asset_reliability_command_center" in root["capabilities"], "root advertises command center", root["capabilities"])

bootstrap = ok(client.post("/scenarios/asset-reliability/bootstrap", json={"actor": "test", "run_pipelines": True, "run_checks": True}), "bootstrap scenario")
assert_true(len(bootstrap["pipeline_runs"]) >= 6, "bootstrap ran pipeline sequence", bootstrap["pipeline_runs"])
assert_true(bootstrap["data_contract_run"]["status"] == "FAIL", "sensor contract surfaces quality issue", bootstrap["data_contract_run"])
assert_true(bootstrap["model_monitor_run"]["status"] in {"WARN", "FAIL"}, "model monitor surfaces drift/quality issue", bootstrap["model_monitor_run"])
assert_true(bootstrap["incident"]["id"] == "asset_reliability_incident", "bootstrap creates incident", bootstrap["incident"])
assert_true(bootstrap["report"]["body"], "bootstrap creates report", bootstrap["report"])

summary = ok(client.get("/scenarios/asset-reliability/summary"), "scenario summary")
assert_true(summary["kpis"]["high_risk_assets"] >= 1, "summary has high-risk asset", summary["kpis"])
asset = summary["selected_asset"]
assert_true(asset["id"] == "asset_pump_4" and asset["properties"]["vibration_mm_s"] >= 8, "selected asset carries reliability signals", asset)
assert_true(summary["graph"]["node_count"] >= 4 and summary["timeline"], "summary includes graph and timeline evidence", summary)

triage = ok(client.post("/scenarios/asset-reliability/run-triage", json={"actor": "test"}), "run guided triage")
assert_true(triage["status"] == "APPROVAL_REQUIRED", "triage stages approval", triage)
assert_true(triage["risk"]["band"] == "critical", "triage explains critical risk", triage["risk"])
assert_true(triage["policy_decision"]["decision"] == "REQUIRE_APPROVAL", "policy gates high-risk action", triage["policy_decision"])
assert_true(triage["agent_session"]["proposed_actions"], "agent proposes action", triage["agent_session"])
assert_true(triage["approval"]["status"] == "PENDING", "approval pending", triage["approval"])

approval = triage["approval"]
approved = ok(client.post(f"/approvals/{approval['id']}/decision", json={
    "actor": "reviewer",
    "decision": "APPROVED",
    "reason": "test approval",
}), "approve staged action")
assert_true(approved["status"] == "APPROVED", "approval is approved", approved)

executed = ok(client.post("/actions/execute", json={
    "action_type_id": approval["action_type_id"],
    "parameters": approval["parameters"],
    "idempotency_key": f"asset-reliability-{approval['id']}",
    "actor": "reviewer",
    "approval_request_id": approval["id"],
}), "execute approved action")
assert_true(executed["status"] == "SUCCESS", "approved action executes", executed)
assert_true("wo_pump_urgent" in executed["mutated_object_ids"], "work order mutated", executed)

governed_state = ok(client.get("/ui-state/command-center"), "command center governed state")
assert_true(governed_state["workflow"]["summary"]["latest_approval"]["status"] == "APPROVED", "ui state exposes durable approval decision", governed_state["workflow"]["summary"])
assert_true(governed_state["workflow"]["summary"]["latest_action"]["approval_request_id"] == approval["id"], "ui state links action to approval", governed_state["workflow"]["summary"])
action_step = next(step for step in governed_state["workflow"]["steps"] if step["id"] == "action")
assert_true(action_step["status"] == "complete" and action_step["evidence_id"], "workflow exposes completed governed action step", action_step)
report_step_before_export = next(step for step in governed_state["workflow"]["steps"] if step["id"] == "report")
assert_true(report_step_before_export["status"] == "available", "report remains available until evidence is exported", report_step_before_export)

work_order = ok(client.get("/objects/work_order/wo_pump_urgent"), "read escalated work order")
assert_true(work_order["properties"]["escalated"] is True and work_order["properties"]["priority"] == "critical", "work order escalation persisted", work_order)

activity = ok(client.get("/activity/objects/work_order/wo_pump_urgent/timeline"), "work order activity timeline")
assert_true(any(row["kind"] == "object_snapshot" for row in activity["timeline"]), "timeline includes object snapshots", activity)
events = ok(client.get("/events", params={"object_id": "asset_pump_4"}), "asset event stream")
assert_true(events["count"] >= 1, "event bus has asset event", events)

dashboard = ok(client.get("/scenarios/asset-reliability/validation-dashboard"), "validation dashboard")
assert_true(dashboard["row_count"] >= 20 and not dashboard["priority_gaps"], "validation dashboard summarizes matrix", dashboard)

report = client.get("/scenarios/asset-reliability/report?format=markdown")
assert_true(report.status_code == 200 and "Action execution" in report.text, "report exports governed action evidence", report.text[:500])
workflow_after_export = ok(client.get("/scenarios/asset-reliability/workflow-state"), "workflow after report export")
report_step_after_export = next(step for step in workflow_after_export["steps"] if step["id"] == "report")
assert_true(report_step_after_export["status"] == "complete", "report step completes after evidence export", report_step_after_export)

print(f"PASS asset reliability command center: {passed} assertions")

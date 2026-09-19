"""
The Command Center counts every open alert, open approval and incident, not the 20 it loads.

GOAL_HONEST_UI_2026-09-11, window `command-center-counts`. The scenario loads the 20 newest open
alerts, the 20 newest pending approvals and the 20 most recently updated incidents, and its KPIs
were the lengths of those lists, so Open alerts, Open approvals and the section cards' incident
counts never read past 20. A list shorter than 20 is every matching row and is still counted where
it lies; one that reaches 20 is counted in SQL on the query that loaded it. The lists stay the 20
newest. Each count is compared with the route that lists every such row: `/ops/alerts`,
`/approvals` and `/ops/incidents`.

Run:
  python oms/test_command_center_counts.py
"""
import os
import tempfile

tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tmpdir.name, 'command_center_counts.db')}"

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


def check(condition, label, detail=""):
    global passed
    assert condition, f"{label}: {detail}"
    passed += 1


def truth():
    """Every open alert, pending approval and incident, from the routes that list them all."""
    alerts = ok(client.get("/ops/alerts", params={"status": "OPEN"}), "every open alert")
    approvals = ok(client.get("/approvals", params={"status": "PENDING"}), "every pending approval")
    incidents = ok(client.get("/ops/incidents"), "every incident")
    return {
        "open_alerts": len(alerts),
        "open_approvals": len(approvals),
        "open_incidents": sum(1 for row in incidents if row["status"] != "CLOSED"),
        "incident_count": len(incidents),
    }


def shown(state):
    """What the Command Center draws: its two metrics and the section cards' counts."""
    kpis = state["summary"]["kpis"]
    sections = {section["id"]: section for section in state["sections"]}
    approval = sections["approval"]["metrics"]
    check(approval == {"open_approvals": kpis["open_approvals"], "open_incidents": kpis["open_incidents"]},
          "the approval card reads the same counts as the metrics", (approval, kpis))
    return {
        "open_alerts": kpis["open_alerts"],
        "open_approvals": kpis["open_approvals"],
        "open_incidents": kpis["open_incidents"],
        "incident_count": sections["report"]["metrics"]["incident_count"],
    }


# 1. Below the window each list is every row, and its length is the count. One closed incident
#    beside the scenario's open one gives the open count something to leave out.
ok(client.post("/scenarios/asset-reliability/bootstrap", json={"actor": "test"}), "bootstrap")
ok(client.post("/ops/incidents", json={"display_name": "Counts closed incident", "severity": "medium", "status": "CLOSED"}), "closed incident")
below = truth()
check(all(value < 20 for value in below.values()), "the bootstrap alone stays below the 20 the scenario loads", below)
check(below["open_incidents"] < below["incident_count"], "a closed incident is among them", below)
counted = shown(ok(client.get("/ui-state/command-center"), "command center below the window"))
for key, value in below.items():
    check(counted[key] == value, f"{key} counts every row below the window", (counted[key], value))

# 2. Past the window: 25 more open alerts, 25 more pending approvals, and 22 more open and 2 more
#    closed incidents. Triage runs after them, so its own read of the alerts meets the new return shape.
ok(client.post("/ops/alert-rules", json={
    "id": "cc_counts_rule", "display_name": "Command Center counts", "source": "cc-counts", "min_severity": "high",
}), "alert rule")
for index in range(25):
    ok(client.post("/ops/events/ingest", json={
        "source": "cc-counts", "event_type": "fixture.alert", "severity": "high", "title": f"Counts alert {index}",
    }), f"alert {index}")
ok(client.post("/action-types", json={
    "id": "cc_counts_escalate", "display_name": "Command Center counts", "parameters": {}, "rules": {"requires_approval": True},
}), "approval action")
for index in range(25):
    staged = ok(client.post("/actions/execute", json={
        "action_type_id": "cc_counts_escalate", "parameters": {}, "idempotency_key": f"cc-counts-{index}",
    }), f"approval {index}")
    check(staged.get("status") == "REQUIRES_APPROVAL", f"approval {index} is staged", staged)
for index in range(24):
    ok(client.post("/ops/incidents", json={
        "display_name": f"Counts incident {index}", "severity": "medium", "status": "CLOSED" if index < 2 else "OPEN",
    }), f"incident {index}")
triage = ok(client.post("/scenarios/asset-reliability/run-triage", json={"actor": "test"}), "triage past the window")
check(triage.get("status") == "APPROVAL_REQUIRED", "triage still stages its approval", triage.get("status"))

past = truth()
check(all(value > 20 for value in past.values()), "the fixture reaches past the 20 the scenario loads", past)
check(past["open_incidents"] < past["incident_count"], "closed incidents are among them", past)
state = ok(client.get("/ui-state/command-center"), "command center past the window")
counted = shown(state)
for key, value in past.items():
    check(counted[key] == value, f"{key} counts every row past the window", (counted[key], value))
summary = state["workflow"]["summary"]
for key in ("alerts", "approvals", "incidents"):
    check(len(summary[key]) == 20, f"the {key} list is still the 20 newest", len(summary[key]))

# 3. The legacy shell reads the scenario summary, and the exported report prints two of the counts.
legacy = ok(client.get("/scenarios/asset-reliability/summary"), "scenario summary")
for key in ("open_alerts", "open_approvals", "open_incidents", "incident_count"):
    check(legacy["kpis"].get(key) == past[key], f"the scenario summary's {key} counts every row", (legacy["kpis"].get(key), past[key]))
report = client.get("/scenarios/asset-reliability/report", params={"format": "markdown"})
lines = report.text.splitlines()
check(report.status_code == 200 and f"- Open approvals: {past['open_approvals']}" in lines, "the report counts every open approval", lines[:8])
check(f"- Open incidents: {past['open_incidents']}" in lines, "the report counts every open incident", lines[:8])

print(f"\nCommand Center counts verified: {passed} assertions passed.")
from app.database import engine as _engine  # noqa: E402
_engine.dispose()
tmpdir.cleanup()

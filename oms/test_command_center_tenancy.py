"""The Command Center lists and counts the viewer's alerts, approvals and incidents.

`asset_reliability_scenario` loaded the 20 newest open alerts, pending approvals and incidents
with `db.query` and no project, and every Command Center route draws from those loaders: the
summary, the workflow state, the UI state, the validation dashboard, the exported report and the
demo bootstrap. A viewer of `default` saw, and counted, every project's rows. The loaders now
read through `semantic_scope.accessible_query`, as `/ops/summary` does.

The same loader chose the alerts the demo incident links. With another project's alert among
the 20 newest, the bootstrap failed with 422 (`create_incident_inline` refuses a foreign alert),
and once the incident existed, triage linked the foreign alert without a check. The demo incident
now links only `default`'s open alerts.

Run:
  python oms/test_command_center_tenancy.py
"""
import json
import os
import tempfile
import time

tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tmpdir.name, 'command_center_tenancy.db')}"
os.environ["AUTH_MODE"] = "local"
os.environ["APP_ENV"] = "test"

from fastapi.testclient import TestClient  # noqa: E402
from app import decision_intelligence, models, models_action, ops_control, production_auth  # noqa: E402
from app.database import SessionLocal  # noqa: E402
from app.main import app  # noqa: E402

client = TestClient(app)
passed = 0
FOREIGN = "beta-command-center"
LATER = int(time.time()) + 10_000  # newer than anything the scenario writes, so inside its window of 20


def ok(response, label, expect=200):
    global passed
    assert response.status_code == expect, f"{label}: {response.status_code} {response.text[:600]}"
    passed += 1
    return response.json() if response.content else {}


def check(condition, label, payload=None):
    global passed
    assert condition, f"{label}: {payload}"
    passed += 1


def foreign_alert(alert_id):
    with SessionLocal() as db:
        ops_control._ensure_tables(db)
        db.add(ops_control.AlertEvent(id=alert_id, project_id=FOREIGN, rule_id="beta-rule", event_id=f"{alert_id}-event",
                                      source="beta", severity="critical", status="OPEN", title=f"Beta alert {alert_id}",
                                      payload={}, created_at=LATER, updated_at=LATER))
        db.commit()


def demo_incident_alerts():
    with SessionLocal() as db:
        return list(db.get(ops_control.Incident, "asset_reliability_incident").alert_ids or [])


# --- 1. another project's newest alert does not break the demo, or join its incident -----
foreign_alert("beta-alert-1")
ok(client.post("/scenarios/asset-reliability/bootstrap", json={"actor": "test"}),
   "the bootstrap with another project's alert among the 20 newest")
linked = demo_incident_alerts()
check(linked, "the demo incident links the scenario's own open alerts", linked)
check("beta-alert-1" not in linked, "the demo incident linked another project's alert", linked)

foreign_alert("beta-alert-2")
triage = ok(client.post("/scenarios/asset-reliability/run-triage", json={"actor": "test"}),
            "triage with another project's alerts among the 20 newest")
check(triage.get("status") == "APPROVAL_REQUIRED", "triage still stages its approval", triage.get("status"))
linked = demo_incident_alerts()
check(not {"beta-alert-1", "beta-alert-2"} & set(linked),
      "triage added another project's alerts to the existing demo incident", linked)

# --- 2. another project's approvals, incidents, asset and work order, beside its two alerts ----
with SessionLocal() as db:
    for object_id, object_type_id in (("beta-asset", "asset"), ("beta-work-order", "work_order")):
        db.add(models.ObjectInstance(id=object_id, project_id=FOREIGN, object_type_id=object_type_id,
                                     properties={"name": f"Beta {object_type_id}", "status": "degraded"},
                                     lineage={}, created_at=LATER, updated_at=LATER))
    for index in range(2):
        db.add(models_action.ApprovalRequest(id=f"beta-approval-{index}", project_id=FOREIGN, action_type_id="escalate_work_order",
                                             requester="beta", parameters={}, status=models_action.ApprovalStatus.PENDING.value,
                                             created_at=LATER + index))
    for index, status in enumerate(("OPEN", "CLOSED")):
        db.add(ops_control.Incident(id=f"beta-incident-{index}", project_id=FOREIGN, display_name=f"Beta incident {index}",
                                    severity="high", status=status, linked_objects=[], alert_ids=[], approval_ids=[],
                                    runbook_execution_ids=[], timeline=[], created_at=LATER, updated_at=LATER + index))
    db.commit()
FOREIGN_IDS = ["beta-alert-1", "beta-alert-2", "beta-approval-0", "beta-approval-1", "beta-incident-0", "beta-incident-1",
               "beta-asset"]


def counts(project_ids):
    """Open alerts, pending approvals, open incidents and incidents, in these projects, from the tables."""
    with SessionLocal() as db:
        alerts = db.query(ops_control.AlertEvent).filter(ops_control.AlertEvent.project_id.in_(project_ids),
                                                         ops_control.AlertEvent.status == "OPEN").count()
        approvals = db.query(models_action.ApprovalRequest).filter(
            models_action.ApprovalRequest.project_id.in_(project_ids),
            models_action.ApprovalRequest.status == models_action.ApprovalStatus.PENDING.value).count()
        incidents = db.query(ops_control.Incident).filter(ops_control.Incident.project_id.in_(project_ids))
        return {"open_alerts": alerts, "open_approvals": approvals,
                "open_incidents": incidents.filter(ops_control.Incident.status != "CLOSED").count(),
                "incident_count": incidents.count()}


own = counts(["default"])
every = counts(["default", FOREIGN])
check(all(own[key] < every[key] for key in own), "the fixture gives each count another project's rows to leave out", (own, every))
check(all(value < 20 for value in every.values()), "every count stays below the window of 20, so the lists hold every row", every)


def pick(kpis):
    """The four counts this test holds, out of a summary's KPIs."""
    return {key: kpis.get(key) for key in ("open_alerts", "open_approvals", "open_incidents", "incident_count")}


# The local administrator may view every project, and still sees every row.
admin = ok(client.get("/ui-state/command-center"), "the Command Center for every project")
check(pick(admin["summary"]["kpis"]) == every, "an administrator of every project no longer counts them all",
      (admin["summary"]["kpis"], every))
admin_text = client.get("/ui-state/command-center").text
check(all(row_id in admin_text for row_id in FOREIGN_IDS), "an administrator of every project no longer lists them all",
      [row_id for row_id in FOREIGN_IDS if row_id not in admin_text])

# --- 3. a viewer of `default` alone sees only `default`'s, on every route --------------------
viewer = production_auth.Principal("default-viewer", "Default viewer", None, ["operator"],
                                   ["view", "edit", "execute", "export"], project_ids=["default"])
app.dependency_overrides[production_auth.current_principal] = lambda: viewer

ROUTES = [
    ("summary", lambda: client.get("/scenarios/asset-reliability/summary"), lambda body: body["kpis"]),
    ("workflow state", lambda: client.get("/scenarios/asset-reliability/workflow-state"), lambda body: body["summary"]["kpis"]),
    ("Command Center", lambda: client.get("/ui-state/command-center"), lambda body: body["summary"]["kpis"]),
    ("validation dashboard", lambda: client.get("/scenarios/asset-reliability/validation-dashboard"),
     lambda body: body["scenario_summary"]["kpis"]),
    ("exported report", lambda: client.get("/scenarios/asset-reliability/report"), lambda body: body["summary"]["kpis"]),
    ("demo bootstrap", lambda: client.post("/project/demo/bootstrap", json={"actor": "test"}),
     lambda body: body["ui_state"]["summary"]["kpis"]),
]
for label, call, kpis in ROUTES:
    response = call()
    body = ok(response, f"the {label} for a viewer of default")
    shown = pick(kpis(body))
    own = counts(["default"])  # the demo bootstrap may add `default` rows; another project's never change
    check(shown == own, f"the {label} counts another project's rows", (shown, own))
    leaked = [row_id for row_id in FOREIGN_IDS + ["beta-work-order"] if row_id in response.text]
    check(not leaked, f"the {label} lists another project's rows", leaked)

report = client.get("/scenarios/asset-reliability/report", params={"format": "markdown"})
check(report.status_code == 200 and f"- Open approvals: {counts(['default'])['open_approvals']}" in report.text.splitlines(),
      "the markdown report counts another project's approvals", report.text[:400])

# --- 4. naming another project's objects -----------------------------------------------------
# The summary takes the asset as a query parameter. Another project's reads as none selected,
# the way an asset the bootstrap has not written yet does.
named = client.get("/scenarios/asset-reliability/summary", params={"asset_id": "beta-asset"})
check(ok(named, "a summary naming another project's asset")["selected_asset"] is None,
      "the summary showed another project's asset by id", named.json()["selected_asset"])
# The response echoes the `asset_id` it was asked for; nothing else in it may name the asset.
check("beta-asset" not in json.dumps({key: value for key, value in named.json().items() if key != "asset_id"}),
      "a summary naming another project's asset lists it", None)


def decision_runs():
    with SessionLocal() as db:
        return db.query(decision_intelligence.DecisionRun).count()


def pending_approvals():
    return counts(["default", FOREIGN])["open_approvals"]


# Triage scores the asset, persists a decision run and stages an escalation of the work order.
for label, body in (("asset", {"asset_id": "beta-asset"}), ("work order", {"work_order_id": "beta-work-order"})):
    runs, approvals = decision_runs(), pending_approvals()
    ok(client.post("/scenarios/asset-reliability/run-triage", json={"actor": "test", **body}),
       f"triage of another project's {label} is refused", 403)
    check(decision_runs() == runs, f"a refused triage of another project's {label} persisted a decision run", (runs, decision_runs()))
    check(pending_approvals() == approvals, f"a refused triage of another project's {label} staged an approval",
          (approvals, pending_approvals()))

app.dependency_overrides.clear()
# ...and the parameter still selects an asset for a caller who may view it.
admin_named = ok(client.get("/scenarios/asset-reliability/summary", params={"asset_id": "beta-asset"}),
                 "a summary naming another project's asset, for an administrator of every project")
check((admin_named["selected_asset"] or {}).get("id") == "beta-asset",
      "the summary no longer selects an asset its caller may view", admin_named["selected_asset"])
print(f"Command Center scoped to the viewer's projects: {passed} assertions passed.")
from app.database import engine as _engine  # noqa: E402
_engine.dispose()
tmpdir.cleanup()

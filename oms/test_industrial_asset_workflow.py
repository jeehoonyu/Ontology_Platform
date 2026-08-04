"""A promoted project dataset becomes an isolated ontology, pipeline, and risk workflow."""
import os
import tempfile


temporary = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(temporary.name, 'industrial-workflow.db')}"
os.environ["AUTH_MODE"] = "local"
os.environ["APP_ENV"] = "test"

from fastapi.testclient import TestClient  # noqa: E402
from app import (  # noqa: E402
    decision_intelligence,
    investigations,
    models,
    models_action,
    ontology_registry,
    ontology_runtime_v1,
    ontology_versioning,
    ops_control,
    production_auth,
)
from app.database import SessionLocal  # noqa: E402
from app.main import app  # noqa: E402


client = TestClient(app)
passed = 0


def check(response, label, expected=200):
    global passed
    assert response.status_code == expected, f"{label}: {response.status_code} {response.text[:1200]}"
    passed += 1
    return response.json() if response.content else {}


check(client.post("/tenancy/organizations", json={"id": "industrial-org", "display_name": "Industrial Org"}), "organization", 201)
for project_id in ("plant-alpha", "plant-beta"):
    check(client.post("/tenancy/projects", json={"id": project_id, "organization_id": "industrial-org", "display_name": project_id}), project_id, 201)

alpha = production_auth.Principal("alpha-engineer", "Alpha", None, ["administrator"], ["*"], organization_id="industrial-org", project_ids=["plant-alpha"])
beta = production_auth.Principal("beta-engineer", "Beta", None, ["administrator"], ["*"], organization_id="industrial-org", project_ids=["plant-beta"])
viewer = production_auth.Principal("alpha-viewer", "Viewer", None, ["viewer"], ["view"], organization_id="industrial-org", project_ids=["plant-alpha"])
editor = production_auth.Principal("alpha-editor", "Editor", None, ["editor"], ["view", "edit", "execute"], organization_id="industrial-org", project_ids=["plant-alpha"])


def use(principal):
    app.dependency_overrides[production_auth.current_principal] = lambda: principal


use(alpha)
check(client.post("/data-assets", json={
    "id": "alpha-promoted-assets", "project_id": "plant-alpha", "display_name": "Alpha promoted assets",
    "kind": "dataset", "asset_schema": {
        "asset_key": "string", "asset_name": "string", "condition": "string", "priority": "string",
        "failure_probability": "number", "lat": "number", "lon": "number", "serial": "string",
    },
    "records": [
        {"asset_key": "pump-4", "asset_name": "Line 4 Pump", "condition": "DEGRADED", "priority": "high", "failure_probability": 0.91, "lat": 37.7924, "lon": -122.4012, "serial": "P-004"},
        {"asset_key": "chiller-2", "asset_name": "Chiller 2", "condition": "RUNNING", "priority": "medium", "failure_probability": 0.22, "lat": 37.7893, "lon": -122.4072, "serial": "C-002"},
        {"asset_key": "facility-1", "asset_name": "Plant Facility", "priority": "high", "lat": 37.7900, "lon": -122.4050, "serial": "F-001"},
    ],
}), "alpha dataset")

request = {
    "project_id": "plant-alpha", "source_asset_id": "alpha-promoted-assets", "display_name": "Plant Asset",
    "mapping": {
        "id_field": "asset_key", "name_field": "asset_name", "status_field": "condition",
        "criticality_field": "priority", "risk_field": "failure_probability", "latitude_field": "lat",
        "longitude_field": "lon", "serial_number_field": "serial",
    },
    "risk_threshold": 0.7,
}
onboarded = check(client.post("/api/v1/industrial/workflows/asset-reliability/onboard", json=request), "onboard alpha")
assert onboarded["project_id"] == "plant-alpha" and onboarded["status"] == "READY", onboarded
assert onboarded["summary"] == {
    "source_records": 3, "objects_hydrated": 3, "objects_retired": 0, "high_risk_assets": 1,
}, onboarded
assert onboarded["resources"]["pipeline_run"] and onboarded["resources"]["decision_run"], onboarded
contract = onboarded["ontology_contract"]
assert contract["created"] and contract["revision"]["status"] == "PUBLISHED", contract
assert contract["registry"]["revision_id"] == contract["revision"]["id"] and contract["registry"]["version"], contract
assert contract["semantic_contract"]["status"] == "COMPILED" and contract["semantic_contract"]["revision_id"] == contract["revision"]["id"], contract
passed += 6

state = check(client.get("/api/v1/industrial/workflows/asset-reliability/state?project_id=plant-alpha"), "alpha state")
assert state["status"] == "READY" and state["summary"]["object_count"] == 3, state
assert state["summary"]["ontology_published"] and state["summary"]["registry_version"] == contract["registry"]["version"], state
passed += 1

triage = check(client.post("/api/v1/industrial/workflows/asset-reliability/triage", json={"project_id": "plant-alpha"}), "triage imported assets")
assert triage["status"] == "APPROVAL_REQUIRED" and triage["object"]["id"] == "plant_alpha:pump-4", triage
assert triage["risk"]["band"] in {"high", "critical"} and triage["agent_session"]["proposed_actions"][0]["requires_approval"], triage
assert triage["incident"]["project_id"] == "plant-alpha" and triage["investigation"]["project_id"] == "plant-alpha", triage
passed += 3

workflow = check(client.get("/api/v1/industrial/workflows/asset-reliability/workflow-state?project_id=plant-alpha"), "workflow awaits approval")
assert workflow["current_step"] == "approve" and workflow["summary"]["latest_approval"]["status"] == "PENDING", workflow
passed += 1

approval = triage["approval"]
check(client.post(f"/approvals/{approval['id']}/decision", json={"actor": "ignored", "decision": "APPROVED", "reason": "Evidence reviewed"}), "approve inspection")
execution = check(client.post("/actions/execute", json={
    "action_type_id": approval["action_type_id"], "parameters": approval["parameters"],
    "idempotency_key": f"industrial-{approval['id']}", "approval_request_id": approval["id"],
}), "execute inspection")
assert execution["status"] == "SUCCESS" and execution["mutated_object_ids"] == ["plant_alpha:pump-4"], execution
passed += 1
cached = check(client.post("/actions/execute", json={
    "action_type_id": approval["action_type_id"], "parameters": approval["parameters"],
    "idempotency_key": f"industrial-{approval['id']}", "approval_request_id": approval["id"],
}), "idempotent inspection execution")
assert cached["status"] == "SUCCESS_CACHED", cached
passed += 1
refreshed = check(client.post("/api/v1/industrial/workflows/asset-reliability/onboard", json=request), "refresh source after governed action")
assert refreshed["summary"]["objects_hydrated"] == 3, refreshed
passed += 1

completed = check(client.get("/api/v1/industrial/workflows/asset-reliability/workflow-state?project_id=plant-alpha"), "workflow action complete")
assert {"connect", "transform", "model", "analyze", "approve", "act"}.issubset(set(completed["completed_steps"])), completed
passed += 1
report_json = check(client.get("/api/v1/industrial/workflows/asset-reliability/report?project_id=plant-alpha"), "project report")
assert report_json["approval"]["status"] == "APPROVED" and report_json["action"]["payload"]["mutated_object_ids"] == ["plant_alpha:pump-4"], report_json
passed += 1
report_markdown = client.get("/api/v1/industrial/workflows/asset-reliability/report?project_id=plant-alpha&format=markdown")
assert report_markdown.status_code == 200 and "Industrial Asset Reliability Report" in report_markdown.text and "plant_alpha:pump-4" in report_markdown.text, report_markdown.text
passed += 1

rerun = check(client.post("/api/v1/industrial/workflows/asset-reliability/onboard", json=request), "idempotent rerun")
assert rerun["summary"]["objects_hydrated"] == 3 and rerun["resources"]["pipeline_run"] != onboarded["resources"]["pipeline_run"], rerun
assert not rerun["ontology_contract"]["created"] and rerun["resources"]["ontology_revision"] == onboarded["resources"]["ontology_revision"], rerun
assert rerun["resources"]["ontology_registry"] == onboarded["resources"]["ontology_registry"], rerun
passed += 3

breaking = client.post("/api/v1/industrial/workflows/asset-reliability/onboard", json={
    **request,
    "mapping": {**request["mapping"], "name_field": None},
})
assert breaking.status_code == 409 and "breaking" in breaking.text.lower(), breaking.text
passed += 1

with SessionLocal() as db:
    objects = db.query(models.ObjectInstance).filter(models.ObjectInstance.project_id == "plant-alpha").all()
    assert {row.id for row in objects} == {"plant_alpha:pump-4", "plant_alpha:chiller-2", "plant_alpha:facility-1"}, [row.id for row in objects]
    assert all((row.properties or {}).get("geometry", {}).get("type") == "Point" for row in objects), [row.properties for row in objects]
    assert all((row.properties or {}).get("mgrs") for row in objects), [row.properties for row in objects]
    passed += 3
    revisions = db.query(ontology_versioning.OntologyRevision).filter(ontology_versioning.OntologyRevision.project_id == "plant-alpha").all()
    registry_entries = db.query(ontology_registry.OntologyRegistryEntry).filter(ontology_registry.OntologyRegistryEntry.project_id == "plant-alpha").all()
    normalized = db.query(ontology_runtime_v1.OntologyPropertyDefinition).filter(
        ontology_runtime_v1.OntologyPropertyDefinition.project_id == "plant-alpha",
        ontology_runtime_v1.OntologyPropertyDefinition.object_type_id == onboarded["resources"]["object_type"],
    ).all()
    assert len(revisions) == 1 and len(registry_entries) == 1, (revisions, registry_entries)
    assert {row.property_name for row in normalized} >= {"source_id", "name", "risk_score", "geometry", "mgrs", "maintenance_state"}, normalized
    assert all(row.ontology_revision_id == revisions[0].id and row.status == "ACTIVE" for row in normalized), normalized
    changes = db.query(ontology_runtime_v1.ObjectChangeEvent).filter(
        ontology_runtime_v1.ObjectChangeEvent.project_id == "plant-alpha",
        ontology_runtime_v1.ObjectChangeEvent.object_type_id == onboarded["resources"]["object_type"],
    ).all()
    assert changes and all(row.ontology_revision_id == revisions[0].id for row in changes), changes
    passed += 4
    pump = db.get(models.ObjectInstance, "plant_alpha:pump-4")
    assert pump.properties["maintenance_state"] == "INSPECTION_REQUIRED" and pump.properties["maintenance_reason"], pump.properties
    passed += 1
    snapshots = db.query(decision_intelligence.ObjectSnapshot).filter(
        decision_intelligence.ObjectSnapshot.project_id == "plant-alpha",
        decision_intelligence.ObjectSnapshot.object_id == "plant_alpha:pump-4",
        decision_intelligence.ObjectSnapshot.event_type == "action.object.mutated",
    ).all()
    assert len(snapshots) == 1 and snapshots[0].actor == "alpha-engineer", snapshots
    outbox = db.query(models_action.OutboxEvent).filter(models_action.OutboxEvent.project_id == "plant-alpha").all()
    assert len(outbox) == 1 and outbox[0].payload["approval_request_id"] == approval["id"], outbox
    incident = db.get(ops_control.Incident, triage["incident"]["id"])
    investigation = db.get(investigations.InvestigationWorkspace, triage["investigation"]["id"])
    assert incident and investigation and incident.project_id == investigation.project_id == "plant-alpha", (incident, investigation)
    export_audit = db.query(models_action.AuditLog).filter(models_action.AuditLog.event_type == "industrial.workflow.report.exported").first()
    assert export_audit and export_audit.actor == "alpha-engineer" and export_audit.payload["project_id"] == "plant-alpha", export_audit
    passed += 4
    audit = db.query(models_action.AuditLog).filter(models_action.AuditLog.event_type == "industrial.workflow.contract.compiled").order_by(models_action.AuditLog.id.desc()).first()
    assert audit and audit.actor == "alpha-engineer" and audit.payload["project_id"] == "plant-alpha", audit
    passed += 1

use(beta)
check(client.get("/api/v1/industrial/workflows/asset-reliability/state?project_id=plant-alpha"), "beta cannot view alpha", 403)
check(client.get("/api/v1/industrial/workflows/asset-reliability/workflow-state?project_id=plant-alpha"), "beta cannot view alpha workflow", 403)
check(client.get("/api/v1/industrial/workflows/asset-reliability/report?project_id=plant-alpha"), "beta cannot export alpha report", 403)
check(client.post("/api/v1/industrial/workflows/asset-reliability/onboard", json={**request, "project_id": "plant-beta"}), "beta cannot use alpha dataset", 404)
check(client.post("/api/v1/industrial/workflows/asset-reliability/triage", json={"project_id": "plant-alpha"}), "beta cannot triage alpha", 403)

use(viewer)
check(client.get("/api/v1/industrial/workflows/asset-reliability/state?project_id=plant-alpha"), "viewer reads state")
check(client.post("/api/v1/industrial/workflows/asset-reliability/onboard", json=request), "viewer cannot onboard", 403)

use(editor)
check(client.post("/api/v1/industrial/workflows/asset-reliability/onboard", json=request), "editor cannot publish ontology", 403)
check(client.post("/api/v1/industrial/workflows/asset-reliability/onboard", json={**request, "publish_ontology": False}), "unpublished ontology cannot hydrate", 422)

app.dependency_overrides.clear()
print(f"Industrial asset onboarding workflow verified: {passed} assertions passed.")

"""Project snapshots are isolated, dependency-complete, and cleanly restorable."""
import copy
import os
import tempfile
import time

tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tmpdir.name, 'snapshot_source.db')}"
os.environ["AUTH_MODE"] = "local"
os.environ["APP_ENV"] = "test"

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402
from app import decision_intelligence, event_outbox, ops_control, platform_runtime, production_auth, system_hardening, tenancy  # noqa: E402
from app.database import Base, SessionLocal  # noqa: E402
from app.main import app  # noqa: E402
from app.models import DataAsset  # noqa: E402

client = TestClient(app)
passed = 0


def check(response, label, expected=200):
    global passed
    assert response.status_code == expected, f"{label}: {response.status_code} {response.text[:1200]}"
    passed += 1
    return response.json() if response.content else {}


check(client.post("/tenancy/organizations", json={"id": "snapshot-org", "display_name": "Snapshot Org"}), "organization", 201)
for project_id in ("alpha", "beta"):
    check(client.post("/tenancy/projects", json={"id": project_id, "organization_id": "snapshot-org", "display_name": project_id}), project_id, 201)

alpha = production_auth.Principal("alpha-admin", "Alpha", None, ["administrator"], ["*"], organization_id="snapshot-org", project_ids=["alpha"])
beta = production_auth.Principal("beta-admin", "Beta", None, ["administrator"], ["*"], organization_id="snapshot-org", project_ids=["beta"])


def use(principal):
    app.dependency_overrides[production_auth.current_principal] = lambda: principal


def seed(project_id):
    check(client.post("/data-assets", json={
        "id": f"{project_id}-asset", "project_id": project_id, "display_name": project_id,
        "kind": "dataset", "asset_schema": {}, "records": [{"id": project_id}],
    }), f"{project_id} dataset")
    check(client.post("/object-types", json={
        "id": f"{project_id}-object-type", "project_id": project_id, "display_name": f"{project_id} object type",
        "properties": {"name": {"type": "string"}, "status": {"type": "string"}},
    }), f"{project_id} object type")
    for suffix, name in (("1", "Pump"), ("2", "pump")):
        check(client.post("/objects", json={
            "id": f"{project_id}-object-{suffix}", "project_id": project_id,
            "object_type_id": f"{project_id}-object-type", "properties": {"name": name, "status": "DEGRADED"},
        }), f"{project_id} object {suffix}")
    check(client.post("/decision/rules", json={
        "id": f"{project_id}-decision-rule", "project_id": project_id, "display_name": "Degraded",
        "object_type_id": f"{project_id}-object-type", "expression": {"field": "status", "op": "eq", "value": "DEGRADED"},
    }), f"{project_id} decision rule")
    check(client.post("/decision/scorecards", json={
        "id": f"{project_id}-scorecard", "project_id": project_id, "display_name": "Risk",
        "object_type_id": f"{project_id}-object-type", "features": [{"rule_id": f"{project_id}-decision-rule", "weight": 90}],
    }), f"{project_id} scorecard")
    check(client.post("/decision/evaluate", json={
        "project_id": project_id, "object_type_id": f"{project_id}-object-type",
    }), f"{project_id} decision run")
    check(client.post("/entity-resolution/jobs", json={
        "project_id": project_id, "object_type_id": f"{project_id}-object-type", "fields": ["name"], "threshold": 85,
    }), f"{project_id} entity job")
    check(client.post("/decision/scenarios", json={
        "id": f"{project_id}-scenario", "project_id": project_id, "display_name": "Outage",
        "seed_object_ids": [f"{project_id}-object-1"],
        "overrides": {f"{project_id}-object-1": {"status": "OUTAGE"}},
    }), f"{project_id} scenario")
    artifact = check(client.post("/artifacts", json={
        "id": f"{project_id}-artifact", "project_id": project_id,
        "artifact_type": "pipeline", "display_name": project_id,
        "state": {"nodes": [], "edges": []},
    }), f"{project_id} artifact", 201)
    assert artifact["project_id"] == project_id
    check(client.post("/ops/events/ingest", json={
        "project_id": project_id, "source": "snapshot", "event_type": "snapshot.seeded",
        "severity": "info", "title": project_id,
    }), f"{project_id} event")
    check(client.post("/ops/incidents", json={
        "id": f"{project_id}-incident", "project_id": project_id,
        "display_name": f"{project_id} incident",
    }), f"{project_id} incident")
    check(client.post("/connections/webhooks", json={
        "id": f"{project_id}-webhook", "project_id": project_id,
        "display_name": project_id, "mode": "writeback",
    }), f"{project_id} webhook")
    check(client.post("/streams", json={
        "id": f"{project_id}-event-stream", "project_id": project_id,
        "display_name": f"{project_id} event stream", "schema": {"event_type": "string"},
    }), f"{project_id} event stream")
    check(client.post("/api/v1/event-stream-bindings", json={
        "id": f"{project_id}-event-binding", "project_id": project_id,
        "display_name": f"{project_id} object changes",
        "target_stream_id": f"{project_id}-event-stream",
        "topics": ["ontologyos.object_change"],
        "object_type_ids": [f"{project_id}-object-type"],
    }), f"{project_id} event binding", 201)


use(alpha)
seed("alpha")
use(beta)
seed("beta")

use(alpha)
alpha_outbox = check(client.get("/api/v1/outbox/events", params={"project_id": "alpha"}), "alpha outbox")
assert alpha_outbox["count"] > 0
alpha_object_change = next(row for row in alpha_outbox["events"] if row["topic"] == "ontologyos.object_change")
check(client.post("/api/v1/outbox/workers/run-next", json={
    "worker_id": "snapshot-test", "event_id": alpha_object_change["id"],
}), "publish alpha event")
alpha_routing = check(client.post("/api/v1/event-stream-bindings/alpha-event-binding/route", json={}), "route alpha event")
assert alpha_routing["routed"] == 1
with SessionLocal() as db:
    now = int(time.time())
    db.add(event_outbox.EventTransportReceipt(
        id="alpha-delivery", outbox_event_id=alpha_object_change["id"], project_id="alpha",
        transport="kafka", destination="snapshot.alpha", status="DELIVERED", attempts=1,
        max_attempts=5, available_at=now, broker_metadata={"partition": 0, "offset": 7},
        created_at=now, updated_at=now, delivered_at=now,
    ))
    db.commit()
snapshot = check(client.get("/project/export"), "alpha export")
assert snapshot["snapshot_version"] == 3
assert snapshot["project_scope"]["project_id"] == "alpha"
assert {row["id"] for row in snapshot["projects"]} == {"alpha"}
assert {row["project_id"] for row in snapshot["data_assets"]} == {"alpha"}
assert {row["project_id"] for row in snapshot["ops_events"]} == {"alpha"}
assert {row["project_id"] for row in snapshot["event_outbox"]} == {"alpha"}
assert {row["project_id"] for row in snapshot["platform_event_log"]} == {"alpha"}
assert {row["project_id"] for row in snapshot["event_transport_receipts"]} == {"alpha"}
assert {row["project_id"] for row in snapshot["event_stream_bindings"]} == {"alpha"}
assert {row["project_id"] for row in snapshot["event_stream_receipts"]} == {"alpha"}
assert {row["project_id"] for row in snapshot["incidents"]} == {"alpha"}
for resource in ("decision_rules", "decision_scorecards", "decision_runs", "object_snapshots", "entity_resolution_jobs", "entity_candidates", "decision_scenarios"):
    assert snapshot[resource] and {row["project_id"] for row in snapshot[resource]} == {"alpha"}, resource
assert {row["project_id"] for row in snapshot["webhooks"]} == {"alpha"}
assert {row["artifact_id"] for row in snapshot["platform_artifact_revisions"]} == {"alpha-artifact"}
assert "beta-" not in str(snapshot), "snapshot leaked beta resources"
passed += 8

check(client.get("/project/export", params={"project_id": "beta"}), "alpha cannot export beta", 403)
use(beta)
check(client.post("/project/import/validate", json={"snapshot": snapshot}), "beta cannot validate alpha restore", 403)

use(alpha)
tampered = copy.deepcopy(snapshot)
tampered.pop("integrity", None)
tampered["data_assets"].append({
    "id": "beta-injected", "project_id": "beta", "display_name": "injected",
    "kind": "dataset", "asset_schema": {}, "records": [],
})
tampered = system_hardening._finalize_snapshot(tampered)
invalid = check(client.post("/project/import/validate", json={"snapshot": tampered}), "foreign row rejected")
assert invalid["status"] == "INVALID" and any("beta" in error for error in invalid["errors"]), invalid
passed += 1
missing_stream = copy.deepcopy(snapshot)
missing_stream.pop("integrity", None)
missing_stream["streams"] = [row for row in missing_stream["streams"] if row["id"] != "alpha-event-stream"]
missing_stream = system_hardening._finalize_snapshot(missing_stream)
invalid_binding = check(client.post("/project/import/validate", json={"snapshot": missing_stream}), "binding target stream required")
assert invalid_binding["status"] == "INVALID" and any("alpha-event-stream" in error for error in invalid_binding["errors"]), invalid_binding
passed += 1
legacy = check(client.post("/project/import/validate", json={
    "snapshot": {"snapshot_version": 1}, "project_id": "alpha", "allow_legacy": True,
}), "project admin cannot restore global legacy snapshot")
assert legacy["status"] == "INVALID" and any("system-wide" in error for error in legacy["errors"]), legacy
passed += 1

# Restore into a clean database and prove both ownership and child dependency closure.
restore_path = os.path.join(tmpdir.name, "snapshot_restore.db")
restore_engine = create_engine(f"sqlite:///{restore_path}")
Base.metadata.create_all(bind=restore_engine)
restore_principal = production_auth.Principal(
    "restore-admin", "Restore", None, ["administrator"], ["*"],
    organization_id="snapshot-org", project_ids=["*"],
)
with Session(restore_engine) as db:
    result = system_hardening.import_project(
        system_hardening.ProjectImportRequest(snapshot=snapshot),
        db=db,
        principal=restore_principal,
    )
    assert result["status"] == "IMPORTED" and result["project_id"] == "alpha", result
    assert db.get(tenancy.PlatformProject, "alpha") is not None
    assert db.get(tenancy.PlatformProject, "beta") is None
    assert db.get(DataAsset, "alpha-asset").project_id == "alpha"
    assert db.get(DataAsset, "beta-asset") is None
    assert db.get(platform_runtime.PlatformArtifact, "alpha-artifact").project_id == "alpha"
    revisions = db.query(platform_runtime.ArtifactRevision).filter(
        platform_runtime.ArtifactRevision.artifact_id == "alpha-artifact"
    ).count()
    assert revisions == 1
    assert db.get(ops_control.Incident, "alpha-incident").project_id == "alpha"
    assert db.get(ops_control.Incident, "beta-incident") is None
    assert db.get(decision_intelligence.DecisionRule, "alpha-decision-rule").project_id == "alpha"
    assert db.get(decision_intelligence.DecisionRule, "beta-decision-rule") is None
    assert db.get(decision_intelligence.DecisionScenario, "alpha-scenario").project_id == "alpha"
    assert db.query(decision_intelligence.ObjectSnapshot).filter(decision_intelligence.ObjectSnapshot.project_id == "alpha").count() == len(snapshot["object_snapshots"])
    assert db.query(decision_intelligence.EntityCandidate).filter(decision_intelligence.EntityCandidate.project_id == "alpha").count() == len(snapshot["entity_candidates"])
    restored_outbox_ids = {
        row.id for row in db.query(event_outbox.EventOutbox).filter(event_outbox.EventOutbox.project_id == "alpha").all()
    }
    assert {row["id"] for row in snapshot["event_outbox"]}.issubset(restored_outbox_ids)
    assert db.query(event_outbox.PlatformEventLog).filter(event_outbox.PlatformEventLog.project_id == "alpha").count() == len(snapshot["platform_event_log"])
    assert db.get(event_outbox.EventTransportReceipt, "alpha-delivery").broker_metadata["offset"] == 7
    binding = db.get(event_outbox.EventStreamBinding, "alpha-event-binding")
    assert binding and binding.project_id == "alpha" and binding.cursor_sequence == alpha_routing["cursor_sequence"]
    assert db.query(event_outbox.EventStreamReceipt).filter(
        event_outbox.EventStreamReceipt.binding_id == "alpha-event-binding",
    ).count() == 1
    passed += 19

restore_engine.dispose()
app.dependency_overrides.clear()
print(f"\nProject snapshot tenancy and clean restore verified: {passed} assertions passed.")

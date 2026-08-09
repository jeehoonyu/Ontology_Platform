"""Version-bound ontology contracts for published downstream consumers."""
import os
import tempfile

tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tmpdir.name, 'ontology_contracts.db')}"
os.environ["AUTH_MODE"] = "local"
os.environ["APP_ENV"] = "test"
os.environ["ONTOLOGY_CONTRACT_ENFORCEMENT"] = "strict"

from fastapi.testclient import TestClient  # noqa: E402
from app.main import app  # noqa: E402

client = TestClient(app)
passed = 0


def ok(response, label, expect=200):
    global passed
    assert response.status_code == expect, f"{label}: {response.status_code} {response.text[:1800]}"
    passed += 1
    return response.json() if response.content else {}


def publish_change(title, changes, *, allow_breaking=False):
    change_set = ok(client.post("/ontology/change-sets", json={
        "project_id": "default", "title": title, "changes": changes,
    }), f"create {title}", 201)
    validated_change = ok(
        client.post(f"/ontology/change-sets/{change_set['id']}/validate"),
        f"validate {title}",
    )
    ok(
        client.post(f"/ontology/change-sets/{change_set['id']}/decision", json={"approve": True}),
        f"approve {title}",
    )
    publish_body = {"environment": "production", "allow_breaking": allow_breaking}
    breaking_binding_ids = sorted(
        str(item["binding_id"])
        for item in validated_change.get("impact", {}).get("affected_consumers", [])
        if item.get("breaking")
    )
    if breaking_binding_ids:
        missing_ack = ok(client.post(
            f"/ontology/change-sets/{change_set['id']}/publish", json=publish_body,
        ), f"reject missing downstream acknowledgement for {title}", 409)
        assert missing_ack["detail"]["code"] == "DOWNSTREAM_CONSUMER_ACKNOWLEDGEMENT_REQUIRED"
        assert missing_ack["detail"]["missing_consumer_binding_ids"] == breaking_binding_ids
        stale_ack = ok(client.post(
            f"/ontology/change-sets/{change_set['id']}/publish",
            json={**publish_body, "acknowledged_consumer_binding_ids": [*breaking_binding_ids, "stale-binding"]},
        ), f"reject stale downstream acknowledgement for {title}", 409)
        assert stale_ack["detail"]["stale_consumer_binding_ids"] == ["stale-binding"]
        publish_body["acknowledged_consumer_binding_ids"] = breaking_binding_ids
    published_change = ok(client.post(
        f"/ontology/change-sets/{change_set['id']}/publish",
        json=publish_body,
    ), f"publish {title}")
    return validated_change, published_change


ok(client.post("/object-types", json={
    "id": "contract_asset", "project_id": "default", "display_name": "Contract Asset",
    "properties": {"assetId": {"type": "string"}, "name": {"type": "string"}, "risk": {"type": "number"}},
}), "create contract object type")
ok(client.put("/ontology/object-types/contract_asset/profile", json={
    "api_name": "ContractAsset", "primary_key": "assetId", "title_key": "name",
    "properties": {
        "assetId": {"base_type": "string", "required": True},
        "name": {"base_type": "string", "required": True},
        "risk": {"base_type": "double"},
    },
}), "profile contract object type")
ok(client.post("/action-types", json={
    "id": "inspect_contract_asset", "project_id": "default", "display_name": "Inspect Contract Asset",
    "parameters": {"object_id": {"type": "string"}}, "rules": {},
}), "create contract action")

request = {
    "project_id": "default", "consumer_kind": "test", "consumer_id": "strict_consumer", "consumer_version": "1",
    "payload": {"object_type_id": "contract_asset", "properties": ["assetId", "risk"]},
}
unversioned = ok(client.post("/api/v1/ontology/contracts/validate", json=request), "strict validation before revision")
assert unversioned["status"] == "FAIL" and unversioned["issues"][0]["code"] == "ACTIVE_ONTOLOGY_REVISION_REQUIRED"
ok(client.post("/api/v1/ontology/contracts/bind", json=request), "strict bind before revision rejected", 422)

change = ok(client.post("/ontology/change-sets", json={
    "project_id": "default", "title": "Publish contract baseline", "changes": [],
}), "create contract baseline", 201)
ok(client.post(f"/ontology/change-sets/{change['id']}/validate"), "validate contract baseline")
ok(client.post(f"/ontology/change-sets/{change['id']}/decision", json={"approve": True}), "approve contract baseline")
published = ok(client.post(f"/ontology/change-sets/{change['id']}/publish", json={"environment": "production"}), "publish contract baseline")
revision_id = published["revision"]["id"]

validated = ok(client.post("/api/v1/ontology/contracts/validate", json=request), "validate versioned contract")
assert validated["status"] == "PASS" and validated["ontology_revision_id"] == revision_id and len(validated["ontology_checksum"]) == 64
bound = ok(client.post("/api/v1/ontology/contracts/bind", json=request), "bind versioned contract")
assert bound["binding_count"] == 1 and bound["ontology_revision_id"] == revision_id
idempotent = ok(client.post("/api/v1/ontology/contracts/bind", json=request), "repeat immutable contract idempotently")
assert idempotent["ontology_revision_id"] == revision_id
ok(client.post("/api/v1/ontology/contracts/bind", json={
    **request, "payload": {"object_type_id": "contract_asset", "properties": ["assetId", "name"]},
}), "reject changed immutable consumer version", 409)
bindings = ok(client.get("/api/v1/ontology/contracts/bindings?project_id=default&consumer_kind=test&consumer_id=strict_consumer"), "list exact binding")
assert bindings["count"] == 1
definition = bindings["bindings"][0]["definition"]
assert definition["properties"] == ["assetId", "risk"] and definition["ontology_checksum"] == validated["ontology_checksum"]
assert bindings["bindings"][0]["health"]["status"] == "CURRENT"
initial_health = ok(client.get("/api/v1/ontology/contracts/health?project_id=default"), "current contract health")
assert initial_health["status"] == "PASS" and initial_health["counts"]["CURRENT"] == 1

missing_property = {**request, "consumer_id": "bad_property", "payload": {"object_type_id": "contract_asset", "properties": ["removed_field"]}}
invalid = ok(client.post("/api/v1/ontology/contracts/validate", json=missing_property), "reject property absent from revision")
assert invalid["status"] == "FAIL" and any(item["code"] == "PROPERTIES_NOT_IN_REVISION" for item in invalid["issues"])

ok(client.post("/object-types", json={
    "id": "foreign_asset", "project_id": "foreign", "display_name": "Foreign Asset", "properties": {"id": {"type": "string"}},
}), "create foreign object type")
foreign = {**request, "consumer_id": "foreign_consumer", "payload": {"object_type_id": "foreign_asset"}}
rejected = ok(client.post("/api/v1/ontology/contracts/validate", json=foreign), "reject cross-project contract")
assert rejected["status"] == "FAIL" and any(item["code"] == "CROSS_PROJECT_OBJECT_TYPE" for item in rejected["issues"])

workshop = ok(client.post("/apps/workshop", json={
    "id": "contract_workshop", "project_id": "default", "display_name": "Contract Workshop",
    "variables": {"assets": {"definition_type": "object_set", "object_type_id": "contract_asset"}},
    "widgets": [{"type": "object_table", "title": "Assets", "variable": "assets", "object_type_id": "contract_asset"}],
}), "create bound workshop")
ok(client.post(f"/apps/workshop/{workshop['id']}/publish", json={"note": "version-bound"}), "publish bound workshop")
workshop_bindings = ok(client.get("/api/v1/ontology/contracts/bindings?project_id=default&consumer_kind=workshop&consumer_id=contract_workshop"), "workshop contract binding")
assert workshop_bindings["count"] == 1 and workshop_bindings["bindings"][0]["ontology_revision_id"] == revision_id

artifact = ok(client.post("/artifacts", json={
    "id": "contract_visual_app", "project_id": "default", "artifact_type": "workshop", "display_name": "Contract Visual App",
    "state": {"widgets": [{"id": "asset_table", "object_type_id": "contract_asset", "properties": ["name", "risk"]}]},
}), "create bound visual artifact", 201)
ok(client.post(f"/artifacts/{artifact['id']}/publish", json={"expected_lock_version": artifact["lock_version"]}), "publish bound visual artifact")
artifact_bindings = ok(client.get("/api/v1/ontology/contracts/bindings?project_id=default&consumer_kind=artifact.workshop&consumer_id=contract_visual_app"), "artifact contract binding")
assert artifact_bindings["count"] == 1 and artifact_bindings["bindings"][0]["definition"]["properties"] == ["name", "risk"]

ok(client.post("/data-assets", json={
    "id": "contract_input", "project_id": "default", "display_name": "Contract Input", "kind": "dataset",
    "schema": {}, "records": [{"asset_id": "asset-1", "name": "Pump 1", "risk": 88}],
}), "create pipeline input")
graph = ok(client.post("/pipeline-builder/graphs", json={
    "id": "contract_pipeline", "project_id": "default", "display_name": "Contract Pipeline",
    "nodes": [
        {"id": "input", "type": "input_dataset", "config": {"asset_id": "contract_input"}},
        {"id": "ontology", "type": "ontology_output", "config": {
            "object_type_id": "contract_asset", "primary_key": "asset_id",
            "property_mapping": {"asset_id": "assetId", "name": "name", "risk": "risk"},
        }},
    ],
    "edges": [{"source": "input", "target": "ontology"}],
}), "create bound pipeline", 201)
delivery = ok(client.post(f"/pipeline-builder/graphs/{graph['id']}/deliver", json={}), "deliver bound pipeline")
assert delivery["metrics"]["ontology_revision_id"] == revision_id and delivery["metrics"]["ontology_binding_count"] == 1

impact = ok(client.post("/ontology/changes/impact", json={
    "object_type_id": "contract_asset", "changes": [{"operation": "archive", "property_name": "risk"}],
}), "exact contract impact")
assert impact["summary"]["contract_bindings"] >= 3
assert {row["id"] for row in impact["affected"]["pipelines"]} == {"contract_pipeline"}
assert {row["id"] for row in impact["affected"]["workshops"]} == {"contract_workshop"}
assert {row["id"] for row in impact["affected"]["artifacts"]} == {"contract_visual_app"}

unrelated_impact = ok(client.post("/ontology/changes/impact", json={
    "object_type_id": "contract_asset", "changes": [{"operation": "archive_property", "property_name": "unrelated"}],
}), "property-aware unrelated impact")
assert unrelated_impact["summary"]["contract_bindings"] == 1
assert unrelated_impact["affected"]["pipelines"] == []
assert unrelated_impact["affected"]["artifacts"] == []
assert {row["id"] for row in unrelated_impact["affected"]["workshops"]} == {"contract_workshop"}

_, additive = publish_change("Add compatible contract property", [{
    "operation": "add_property", "object_type_id": "contract_asset", "property_name": "zone",
    "spec": {"base_type": "string"},
}])
assert additive["downstream_contracts"]["status"] == "WARN"
assert additive["downstream_contracts"]["counts"]["COMPATIBLE_STALE"] >= 4
additive_health = ok(client.get("/api/v1/ontology/contracts/health?project_id=default"), "compatible stale contract health")
assert additive_health["counts"]["BROKEN"] == 0 and additive_health["counts"]["COMPATIBLE_STALE"] >= 4
ok(client.post("/api/v1/ontology/contracts/bind", json=request), "reject immutable rebind on a newer compatible revision", 409)

breaking_validation, breaking = publish_change("Archive contracted risk property", [{
    "operation": "archive_property", "object_type_id": "contract_asset", "property_name": "risk",
}], allow_breaking=True)
affected_versions = {
    (row["consumer_kind"], row["consumer_id"], str(row["consumer_version"]))
    for row in breaking_validation["impact"]["affected_consumers"]
}
assert any(kind == "pipeline" and consumer_id == "contract_pipeline" for kind, consumer_id, _ in affected_versions), affected_versions
assert any(kind == "artifact.workshop" and consumer_id == "contract_visual_app" for kind, consumer_id, _ in affected_versions), affected_versions
assert breaking["downstream_contracts"]["status"] == "FAIL"
assert breaking["downstream_contracts"]["counts"]["BROKEN"] == 3
broken_health = ok(client.get("/api/v1/ontology/contracts/health?project_id=default&object_type_id=contract_asset"), "broken contract health")
assert broken_health["counts"]["BROKEN"] == 3
assert any(row["health"]["missing_properties"] == ["risk"] for row in broken_health["bindings"])
broken_manager = ok(client.get("/ui-state/ontology/object-types/contract_asset"), "broken manager contract state")
assert broken_manager["cards"]["contract_health"]["status"] == "FAIL"
assert broken_manager["cards"]["contract_health"]["counts"]["BROKEN"] == 3

rollback = ok(client.post("/ontology/environments/production/rollback", json={
    "project_id": "default", "revision_id": revision_id,
}), "rollback ontology contract")
assert rollback["downstream_contracts"]["counts"]["BROKEN"] == 0
assert rollback["downstream_contracts"]["counts"]["COMPATIBLE_STALE"] >= 4
assert all(row["health"]["same_checksum"] for row in rollback["downstream_contracts"]["bindings"])
restored_manager = ok(client.get("/ui-state/ontology/object-types/contract_asset"), "restored manager contract state")
assert restored_manager["cards"]["contract_health"]["status"] == "WARN"
assert restored_manager["cards"]["contract_health"]["counts"]["BROKEN"] == 0

ok(client.post("/api/v1/ontology/contracts/bind", json={
    **request, "consumer_version": "2", "payload": {},
}), "archive stale binding with a new consumer version")
active = ok(client.get("/api/v1/ontology/contracts/bindings?project_id=default&consumer_kind=test&consumer_id=strict_consumer"), "stale binding removed from active list")
assert active["count"] == 0
archived = ok(client.get("/api/v1/ontology/contracts/bindings?project_id=default&consumer_kind=test&consumer_id=strict_consumer&include_archived=true"), "stale binding retained for audit")
assert archived["count"] == 1 and archived["bindings"][0]["status"] == "ARCHIVED"

os.environ["ONTOLOGY_CONTRACT_ENFORCEMENT"] = "warn"
foreign_unversioned = {
    "project_id": "foreign", "consumer_kind": "test", "consumer_id": "development_consumer",
    "consumer_version": "draft", "payload": {"object_type_id": "foreign_asset"},
}
ok(client.post("/api/v1/ontology/contracts/bind", json=foreign_unversioned), "bind development contract without revision")
before_foreign_publish = ok(client.get("/api/v1/ontology/contracts/health?project_id=foreign"), "unversioned health before publication")
assert before_foreign_publish["counts"]["UNVERSIONED"] == 1
foreign_change = ok(client.post("/ontology/change-sets", json={
    "project_id": "foreign", "title": "Publish foreign contract baseline", "changes": [],
}), "create foreign contract baseline", 201)
ok(client.post(f"/ontology/change-sets/{foreign_change['id']}/validate"), "validate foreign contract baseline")
ok(client.post(f"/ontology/change-sets/{foreign_change['id']}/decision", json={"approve": True}), "approve foreign contract baseline")
foreign_published = ok(client.post(
    f"/ontology/change-sets/{foreign_change['id']}/publish", json={"environment": "production"},
), "publish foreign contract baseline")
assert foreign_published["downstream_contracts"]["counts"]["UNVERSIONED"] == 1
os.environ["ONTOLOGY_CONTRACT_ENFORCEMENT"] = "strict"

audit = ok(client.get("/audit-logs"), "contract audit evidence")
assert sum(1 for row in audit if row["event_type"] == "ontology.contract.bound") >= 5

print(f"\nOntology contract bindings verified: {passed} assertions passed.")
from app.database import engine as _engine  # noqa: E402
_engine.dispose()
tmpdir.cleanup()

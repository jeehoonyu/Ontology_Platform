"""Pipeline-to-ontology contracts, lineage, quarantine, and reconciliation."""
import os
import tempfile

tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tmpdir.name, 'pipeline_ontology_contracts.db')}"
os.environ["AUTH_MODE"] = "local"
os.environ["APP_ENV"] = "test"

from fastapi.testclient import TestClient  # noqa: E402
from app.main import app  # noqa: E402

client = TestClient(app)
passed = 0


def ok(response, label, expect=200):
    global passed
    assert response.status_code == expect, f"{label}: {response.status_code} {response.text[:1800]}"
    passed += 1
    return response.json() if response.content else {}


ok(client.post("/data-assets", json={
    "id": "contract_assets", "project_id": "default", "display_name": "Contract assets", "kind": "dataset", "asset_schema": {},
    "records": [
        {"asset_id": "CA-1", "asset_name": "Pump 1", "risk_score": 0.82},
        {"asset_id": "CA-2", "asset_name": None, "risk_score": 0.31},
        {"asset_id": "CA-3", "asset_name": "Pump 3", "risk_score": "high"},
    ],
}), "create contract input")
ok(client.post("/object-types", json={
    "id": "contract_asset", "project_id": "default", "display_name": "Contract Asset", "description": "Contract output",
    "properties": {"assetId": {"type": "string"}, "name": {"type": "string"}, "riskScore": {"type": "number"}},
}), "create contract object type")
ok(client.put("/ontology/object-types/contract_asset/profile", json={
    "api_name": "ContractAsset", "primary_key": "assetId", "title_key": "name", "plural_name": "Contract Assets",
    "properties": {
        "assetId": {"base_type": "string", "required": True},
        "name": {"base_type": "string", "required": True},
        "riskScore": {"base_type": "double", "required": False},
    },
}), "create contract profile")
graph = ok(client.post("/pipeline-builder/graphs", json={
    "id": "contract_graph", "project_id": "default", "display_name": "Contract graph", "nodes": [
        {"id": "input", "type": "input_dataset", "position": {"x": 80, "y": 100}, "config": {"asset_id": "contract_assets"}},
        {"id": "ontology", "type": "ontology_output", "position": {"x": 360, "y": 100}, "config": {
            "object_type_id": "contract_asset", "primary_key": "asset_id",
            "property_mapping": {"asset_id": "assetId", "asset_name": "name", "risk_score": "riskScore"},
            "write_mode": "upsert", "on_error": "quarantine", "quarantine_asset_id": "contract_asset_quarantine",
            "source_asset_id": "contract_assets",
        }},
    ], "edges": [{"source": "input", "target": "ontology"}], "parameters": {}, "status": "DRAFT",
}), "create contract graph", 201)
assert graph["id"] == "contract_graph"

legacy_edit = ok(client.patch("/pipeline-builder/graphs/contract_graph/nodes/ontology", json={
    "label": "Contract ontology output",
    "config": {
        "object_type_id": "contract_asset", "id_field": "asset_id",
        "mapping": {"asset_id": "assetId", "asset_name": "name", "risk_score": "riskScore"},
        "quarantine_asset_id": "contract_asset_quarantine", "source_asset_id": "contract_assets",
    },
}), "normalize legacy ontology output config")
normalized_config = legacy_edit["metadata"]["config"]
assert normalized_config["primary_key"] == "asset_id" and normalized_config["property_mapping"]["asset_name"] == "name"
assert normalized_config["write_mode"] == "upsert" and normalized_config["on_error"] == "quarantine"

validation = ok(client.post("/pipeline-builder/graphs/contract_graph/validate"), "validate contract graph")
assert validation["status"] == "VALID", validation
preview = ok(client.post("/pipeline-builder/graphs/contract_graph/preview", json={"limit": 10}), "preview ontology contract")
contract_preview = preview["ontology_contracts"][0]
assert contract_preview["status"] == "PARTIAL"
assert contract_preview["accepted_rows"] == 1 and contract_preview["rejected_rows"] == 2
assert contract_preview["created_objects"] == 1
assert {entry["target_property"] for entry in contract_preview["field_lineage"]} == {"assetId", "name", "riskScore"}
assert contract_preview["field_lineage"][0]["origins"][0]["asset_id"] == "contract_assets"

delivered = ok(client.post("/pipeline-builder/graphs/contract_graph/deliver", json={"actor": "test"}), "deliver ontology contract")
assert delivered["metrics"]["materialized_objects"] == 1
assert delivered["metrics"]["rejected_ontology_rows"] == 2
assert len(delivered["metrics"]["ontology_contract_run_ids"]) == 1
obj = ok(client.get("/objects/contract_asset/CA-1"), "read accepted object")
assert obj["properties"] == {"assetId": "CA-1", "name": "Pump 1", "riskScore": 0.82}
assert obj["lineage"]["pipeline_builder_graph_id"] == "contract_graph"
assert any(item["target_property"] == "riskScore" for item in obj["lineage"]["field_lineage"])
assert client.get("/objects/contract_asset/CA-2").status_code == 404

contracts = ok(client.get("/pipeline-builder/graphs/contract_graph/ontology-contracts"), "list contract evidence")
assert contracts["count"] == 1 and contracts["contracts"][0]["status"] == "PARTIAL"
contract = contracts["contracts"][0]
assert contract["accepted_rows"] == 1 and contract["rejected_rows"] == 2
quarantine = ok(client.get(f"/pipeline-builder/ontology-contracts/{contract['id']}/quarantine"), "read quarantine evidence")
assert quarantine["status"] == "AVAILABLE" and quarantine["asset"]["row_count"] == 2
assert {record["_errors"][0]["code"] for record in quarantine["records"]} == {"REQUIRED_PROPERTY_MISSING", "PROPERTY_TYPE_MISMATCH"}
ui_state = ok(client.get("/ui-state/pipeline/contract_graph/ontology-contracts"), "read contract UI state")
assert ui_state["summary"]["status"] == "WARN" and ui_state["summary"]["rejected_rows"] == 2
assert ui_state["evidence_links"] and ui_state["warnings"]

second = ok(client.post("/pipeline-builder/graphs/contract_graph/deliver", json={"actor": "test"}), "redeliver idempotent object state")
assert second["metrics"]["materialized_objects"] == 1
latest = ok(client.get("/pipeline-builder/graphs/contract_graph/ontology-contracts"), "read reconciliation history")
assert latest["count"] == 2 and latest["contracts"][0]["unchanged_objects"] == 1

audit = ok(client.get("/audit-logs"), "read contract audit")
assert sum(1 for row in audit if row["event_type"] == "pipeline_builder.ontology_contract.evaluated") == 2

print(f"\nPipeline ontology contracts verified: {passed} assertions passed.")
from app.database import engine as _engine  # noqa: E402
_engine.dispose()
tmpdir.cleanup()

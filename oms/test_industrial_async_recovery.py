"""Background industrial onboarding resumes a leased ontology checkpoint exactly once."""
import os
import tempfile
import time


temporary = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(temporary.name, 'industrial-async.db')}"
os.environ["DATA_SNAPSHOT_ROOT"] = os.path.join(temporary.name, "snapshots")
os.environ["AUTH_MODE"] = "local"
os.environ["APP_ENV"] = "test"

from fastapi.testclient import TestClient  # noqa: E402
from app import (  # noqa: E402
    data_plane, decision_intelligence, industrial_workflow, models,
    pipeline_builder_ops, platform_runtime, production_auth,
)
from app.database import SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402


client = TestClient(app)
passed = 0


def check(response, label, expected=200):
    global passed
    assert response.status_code == expected, f"{label}: {response.status_code} {response.text[:2000]}"
    passed += 1
    return response.json() if response.content else {}


records = [
    {
        "id": f"asset-{index:04d}", "name": f"Asset {index:04d}",
        "status": "DEGRADED" if index % 100 == 0 else "RUNNING",
        "criticality": "high" if index % 100 == 0 else "medium",
        "predicted_failure_probability": 0.91 if index % 100 == 0 else 0.2,
        "latitude": 37.7 + (index % 50) / 10000,
        "longitude": -122.4 - (index % 50) / 10000,
    }
    for index in range(1500)
]
check(client.post("/data-assets", json={
    "id": "async-industrial-assets", "project_id": "default",
    "display_name": "Async industrial assets", "kind": "dataset",
    "asset_schema": {
        "id": "string", "name": "string", "status": "string", "criticality": "string",
        "predicted_failure_probability": "number", "latitude": "number", "longitude": "number",
    },
    "records": records,
}), "source dataset")

request = {
    "project_id": "default", "source_asset_id": "async-industrial-assets",
    "display_name": "Async Industrial Asset", "risk_threshold": 0.7,
    "execution_mode": "background", "idempotency_key": "async-industrial-onboarding-v1",
    "mapping": {"serial_number_field": None},
}
queued = check(
    client.post("/api/v1/industrial/workflows/asset-reliability/onboard", json=request),
    "queue onboarding", 202,
)
assert queued["status"] == "QUEUED" and queued["execution"]["job_type"] == "industrial.ontology_hydrate", queued
job_id = queued["resources"]["execution_job"]
source_snapshot_id = queued["resources"]["source_snapshot"]
plan_id = queued["resources"]["pipeline_plan"]
passed += 2

processing_state = check(
    client.get("/api/v1/industrial/workflows/asset-reliability/workflow-state?project_id=default"),
    "refresh-safe processing state",
)
assert processing_state["status"] == "PROCESSING", processing_state
assert processing_state["current_step"] == "transform", processing_state
assert processing_state["summary"]["latest_execution_job"]["id"] == job_id, processing_state
assert processing_state["summary"]["latest_execution_job"]["status"] == "QUEUED", processing_state
assert any(link["kind"] == "execution_job" and link["id"] == job_id for link in processing_state["evidence_links"])
passed += 5

replayed = check(
    client.post("/api/v1/industrial/workflows/asset-reliability/onboard", json=request),
    "idempotent queue replay", 202,
)
assert replayed["resources"]["execution_job"] == job_id and replayed["execution"]["idempotent_replay"], replayed
passed += 1

conflict = client.post("/api/v1/industrial/workflows/asset-reliability/onboard", json={
    **request, "risk_threshold": 0.8,
})
assert conflict.status_code == 409 and "idempotency" in conflict.text.lower(), conflict.text
passed += 1

original_query = data_plane._query_local_parquet_snapshot
failed_once = {"value": False}


def interrupt_second_batch(snapshot, body):
    if body.offset >= 1000 and not failed_once["value"]:
        failed_once["value"] = True
        raise RuntimeError("simulated worker loss after durable checkpoint")
    return original_query(snapshot, body)


data_plane._query_local_parquet_snapshot = interrupt_second_batch
first_attempt = check(client.post("/pipeline-builder/workers/run-next", json={
    "worker_id": "industrial-worker", "job_id": job_id, "lease_seconds": 30,
}), "interrupted worker attempt")
data_plane._query_local_parquet_snapshot = original_query
assert first_attempt["job"]["status"] == "QUEUED" and first_attempt["job"]["attempt"] == 2, first_attempt
checkpointed = check(client.get(f"/jobs/{job_id}"), "checkpointed job")
checkpoint = checkpointed["payload"]["industrial_checkpoint"]
assert checkpoint["next_offset"] == 1000 and checkpoint["totals"]["accepted_rows"] == 1000, checkpoint
passed += 2

original_evaluate_rows = decision_intelligence.evaluate_object_rows_inline
decision_batches = {"count": 0}


def interrupt_second_decision_batch(*args, **kwargs):
    decision_batches["count"] += 1
    if decision_batches["count"] == 2:
        raise RuntimeError("simulated worker loss after durable decision checkpoint")
    return original_evaluate_rows(*args, **kwargs)


decision_intelligence.evaluate_object_rows_inline = interrupt_second_decision_batch
decision_interrupted = check(client.post("/pipeline-builder/workers/run-next", json={
    "worker_id": "industrial-worker", "job_id": job_id, "lease_seconds": 30,
}), "decision-interrupted worker attempt")
decision_intelligence.evaluate_object_rows_inline = original_evaluate_rows
assert decision_interrupted["job"]["status"] == "QUEUED" and decision_interrupted["job"]["attempt"] == 3, decision_interrupted
decision_checkpointed = check(client.get(f"/jobs/{job_id}"), "decision checkpointed job")
decision_checkpoint = decision_checkpointed["payload"]["industrial_decision_checkpoint"]
assert decision_checkpoint["evaluated"] == 1000 and sum(decision_checkpoint["band_counts"].values()) == 1000, decision_checkpoint
passed += 2

completed = check(client.post("/pipeline-builder/workers/run-next", json={
    "worker_id": "industrial-worker", "job_id": job_id, "lease_seconds": 30,
}), "resumed decision worker attempt")
assert completed["job"]["status"] == "SUCCEEDED", completed
result = completed["result"]
assert result["summary"]["source_records"] == 1500
assert result["summary"]["objects_hydrated"] == 1500
assert result["summary"]["high_risk_assets"] == 15
assert result["summary"]["risk_objects_evaluated"] == 1500
assert result["summary"]["risk_evaluation_truncated"] is False
assert result["summary"]["risk_band_counts"] == {"low": 1485, "medium": 0, "high": 0, "critical": 15}
assert result["summary"]["risk_findings_retained"] == 15
assert result["resources"]["source_snapshot"] == source_snapshot_id
assert result["resources"]["pipeline_plan"] == plan_id
passed += 8

duplicate_worker = check(client.post("/pipeline-builder/workers/run-next", json={
    "worker_id": "industrial-worker", "job_id": job_id, "lease_seconds": 30,
}), "duplicate terminal delivery")
assert duplicate_worker == {"job": None, "result": None}, duplicate_worker
passed += 1

ready_state = check(
    client.get("/api/v1/industrial/workflows/asset-reliability/workflow-state?project_id=default"),
    "refresh-safe completed state",
)
assert ready_state["status"] == "READY", ready_state
assert ready_state["summary"]["object_count"] == 1500, ready_state
assert ready_state["summary"]["latest_execution_job"]["id"] == job_id, ready_state
assert ready_state["summary"]["latest_execution_job"]["status"] == "SUCCEEDED", ready_state
assert ready_state["summary"]["risk_objects_evaluated"] == 1500, ready_state
assert ready_state["summary"]["risk_band_counts"] == {"low": 1485, "medium": 0, "high": 0, "critical": 15}, ready_state
assert any(link["kind"] == "decision_run" for link in ready_state["evidence_links"])
passed += 7

with SessionLocal() as db:
    objects = db.query(models.ObjectInstance).filter(
        models.ObjectInstance.project_id == "default",
        models.ObjectInstance.object_type_id == result["resources"]["object_type"],
    ).all()
    runs = db.query(models.PipelineRun).filter(models.PipelineRun.pipeline_id == result["resources"]["pipeline"]).all()
    contracts = db.query(pipeline_builder_ops.PipelineOntologyContractRun).filter(
        pipeline_builder_ops.PipelineOntologyContractRun.graph_id == result["resources"]["pipeline_graph"],
    ).all()
    output_snapshots = db.query(data_plane.DataAssetSnapshot).filter(
        data_plane.DataAssetSnapshot.asset_id == result["resources"]["output_asset"],
    ).all()
    job = db.get(platform_runtime.PlatformJob, job_id)
    assert len(objects) == 1500 and len({row.id for row in objects}) == 1500
    assert len(runs) == 1 and runs[0].records_out == 1500 and runs[0].status == "SUCCESS"
    assert len(contracts) == 1 and contracts[0].accepted_rows == 1500
    assert len(output_snapshots) == 1 and output_snapshots[0].row_count == 1500
    assert job.status == "SUCCEEDED" and job.progress == 100
    assert job.result["resources"]["ontology_contract_run"] == contracts[0].id
    passed += 6

with SessionLocal() as db:
    now = int(time.time())
    db.bulk_save_objects([
        models.ObjectInstance(
            id=f"default:scale-{index:05d}", project_id="default",
            object_type_id=result["resources"]["object_type"],
            properties={
                "name": f"Scale Asset {index:05d}", "status": "RUNNING",
                "criticality": "high" if index % 100 == 0 else "medium",
                "risk_score": 0.91 if index % 100 == 0 else 0.2,
            },
            lineage={"source": "decision-scale-contract"}, created_at=now, updated_at=now,
        )
        for index in range(9001)
    ])
    db.commit()

scale_job = check(client.post("/jobs", json={
    "project_id": "default", "job_type": "industrial.ontology_hydrate",
    "subject_type": "decision_scale_contract", "subject_id": "10501-objects",
    "payload": {}, "max_attempts": 3, "timeout_seconds": 900,
}), "create full-scope decision job", 201)
scale_claim = check(client.post("/jobs/claim", json={
    "worker_id": "decision-scale-worker", "job_id": scale_job["id"],
    "supported_job_types": ["industrial.ontology_hydrate"], "lease_seconds": 120,
}), "claim full-scope decision job")
lease_token = scale_claim["job"]["lease_token"]
with SessionLocal() as db:
    scale_evaluation = industrial_workflow._evaluate_partitioned_decision(
        db, project_id="default", object_type_id=result["resources"]["object_type"],
        job_id=scale_job["id"], lease_token=lease_token, lease_seconds=120,
        principal=production_auth._local_principal(),
    )
    db.commit()
assert scale_evaluation["object_count"] == 10501, scale_evaluation
assert sum(scale_evaluation["band_counts"].values()) == 10501, scale_evaluation
assert scale_evaluation["band_counts"]["critical"] == 106, scale_evaluation
assert scale_evaluation["findings_retained"] == 100 and len(scale_evaluation["findings"]) == 100, scale_evaluation
passed += 4
check(client.post(f"/jobs/{scale_job['id']}/complete", json={
    "lease_token": lease_token, "result": scale_evaluation,
}), "complete full-scope decision job")
with SessionLocal() as db:
    scale_run = db.get(decision_intelligence.DecisionRun, scale_evaluation["id"])
    assert scale_run.object_count == 10501
    assert len(scale_run.findings) == 100
    assert scale_run.scope["partitioned"] is True
    assert scale_run.scope["band_counts"] == scale_evaluation["band_counts"]
    passed += 4

print(f"Industrial asynchronous checkpoint recovery verified: {passed} assertions passed.")
engine.dispose()
temporary.cleanup()

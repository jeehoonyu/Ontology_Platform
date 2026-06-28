"""
ModelOps workspace and monitoring regression tests.

Run:
  python test_modelops.py
"""
import os
import tempfile
import time

tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tmpdir.name, 'modelops.db')}"

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


ok(client.post("/data-assets", json={
    "id": "model_baseline",
    "display_name": "Model Baseline",
    "kind": "dataset",
    "asset_schema": {},
    "records": [
        {"temperature": 10, "pressure": 20, "line": "A", "risk_score": 15},
        {"temperature": 12, "pressure": 22, "line": "A", "risk_score": 17},
        {"temperature": 11, "pressure": 19, "line": "A", "risk_score": 15},
    ],
}), "baseline asset")
ok(client.post("/data-assets", json={
    "id": "model_current",
    "display_name": "Model Current",
    "kind": "dataset",
    "asset_schema": {},
    "records": [
        {"temperature": 30, "pressure": 60, "line": "B", "risk_score": 45},
        {"temperature": 32, "pressure": 62, "line": "B", "risk_score": 47},
        {"temperature": 34, "pressure": 64, "line": "C", "risk_score": 49},
    ],
}), "current asset")
ok(client.post("/data-assets", json={
    "id": "model_current_2",
    "display_name": "Model Current 2",
    "kind": "dataset",
    "asset_schema": {},
    "records": [
        {"temperature": 13, "pressure": 23, "line": "A", "risk_score": 18},
        {"temperature": 14, "pressure": 24, "line": "A", "risk_score": 19},
    ],
}), "second current asset")

objective = ok(client.post("/modeling/objectives", json={
    "id": "asset_risk_objective",
    "display_name": "Asset Risk Objective",
    "problem_type": "regression",
    "target_field": "risk_score",
    "feature_fields": ["temperature", "pressure"],
    "input_asset_id": "model_baseline",
}), "create objective")
submission = ok(client.post(f"/modeling/objectives/{objective['id']}/train", json={
    "trainer_type": "regression",
    "training_dataset_id": "model_baseline",
    "target_column": "risk_score",
    "eval_metric": "mae",
    "quality_preset": "balanced",
}), "train submission")
submissions = ok(client.get(f"/modeling/objectives/{objective['id']}/submissions"), "list submissions")
assert submissions and submissions[0]["id"] == submission["id"], submissions

check = ok(client.post(f"/modeling/objectives/{objective['id']}/checks", json={
    "name": "mae_gate",
    "check_type": "automatic",
    "metric": "mae",
    "operator": "<=",
    "threshold": 10,
}), "create check")
results = ok(client.post(f"/modeling/submissions/{submission['id']}/evaluate-checks"), "evaluate checks")
assert results and results[0]["check_id"] == check["id"] and results[0]["status"] == "approved", results
eligibility = ok(client.get(f"/modeling/submissions/{submission['id']}/release-eligibility"), "release eligibility")
assert eligibility["eligible"] is True, eligibility

release = ok(client.post(f"/modeling/objectives/{objective['id']}/releases", json={
    "submission_id": submission["id"],
    "version": "v1.0",
    "environment": "staging",
}), "create mev release")
assert release["environment"] == "staging", release
deployment = ok(client.post("/modeling/deployments", json={
    "id": "asset_risk_live",
    "objective_id": objective["id"],
    "submission_id": submission["id"],
    "mode": "live",
}), "create deployment")
assert deployment["status"] == "running", deployment

inference = ok(client.post(f"/modeling/deployments/{deployment['id']}/infer", json={
    "inference_data": [{"temperature": 20, "pressure": 30}]
}), "run inference")
assert inference["output_data"][0]["prediction"] == 25, inference
logs = ok(client.get(f"/modelops/deployments/{deployment['id']}/prediction-logs"), "prediction logs")
assert logs and logs[0]["output_count"] == 1 and logs[0]["request_shape"] == "multi_io", logs

monitor = ok(client.post("/modelops/monitors", json={
    "id": "asset_risk_monitor",
    "display_name": "Asset Risk Monitor",
    "objective_id": objective["id"],
    "deployment_id": deployment["id"],
    "baseline_asset_id": "model_baseline",
    "feature_fields": ["temperature", "pressure", "line"],
    "prediction_field": "prediction",
    "target_field": "risk_score",
    "thresholds": {
        "numeric_mean_shift_warn": 0.1,
        "numeric_mean_shift_fail": 0.5,
        "unseen_category_rate_warn": 0.1,
        "unseen_category_rate_fail": 0.5
    },
}), "create monitor")
run = ok(client.post(f"/modelops/monitors/{monitor['id']}/run", json={
    "current_asset_id": "model_current",
}), "run monitor")
assert run["status"] == "FAIL", run
assert run["drift_metrics"]["temperature"]["status"] == "FAIL", run["drift_metrics"]
assert run["drift_metrics"]["line"]["unseen_category_rate"] == 1.0, run["drift_metrics"]["line"]
assert run["quality_metrics"]["available"] is True and run["quality_metrics"]["rmse"] == 0.0, run["quality_metrics"]

time.sleep(1)
run2 = ok(client.post(f"/modelops/monitors/{monitor['id']}/run", json={
    "current_asset_id": "model_current_2",
}), "run second monitor")
runs = ok(client.get(f"/modelops/monitors/{monitor['id']}/runs"), "monitor run history")
assert runs[0]["id"] == run2["id"] and len(runs) == 2, runs

summary = ok(client.get("/modelops/summary"), "modelops summary")
assert summary["objectives"] == 1 and summary["deployments"] == 1 and summary["prediction_logs"] == 1, summary
monitors = ok(client.get("/modelops/monitors"), "list monitors")
assert monitors[0]["latest_run"]["id"] == run2["id"], monitors
route = client.get("/workspace/models")
assert route.status_code == 200, route.status_code
passed += 1

print(f"\nModelOps verified: {passed} assertions passed.")
from app.database import engine as _engine  # noqa: E402
_engine.dispose()
tmpdir.cleanup()

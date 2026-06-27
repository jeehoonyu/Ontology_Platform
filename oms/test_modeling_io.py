"""
Standalone self-test for app.modeling (owned file).

Builds a local FastAPI app from ONLY the modeling router (does NOT import
app.main, since sibling files are edited concurrently). Verifies:

  * Multi-I/O REST envelope on /modeling/deployments/{id}/infer
    (input_name -> [{field:value}] => output_name -> [{field:result}]).
  * Backward-compat legacy {"records": [...]} shape => {"predictions": [...]}.
  * Enriched /modeling/objectives/{id}/train accepting trainer_type,
    training_dataset_id, target_column, eval_metric, quality_preset and a
    status lifecycle field on submissions.
  * Legacy {"algorithm": ...} train contract still works.

Run from oms/:
    ./venv312/Scripts/python.exe test_modeling_io.py
"""

import os
import sys
import tempfile

_t = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(_t.name, 't.db')}"

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.database import Base, engine, SessionLocal  # noqa: E402
from app import models, models_action  # noqa: E402  (ensure tables registered)
from app import modeling as M  # noqa: E402

Base.metadata.create_all(bind=engine)

api = FastAPI()
api.include_router(M.router)
client = TestClient(api)


_passed = 0


def check(cond, msg):
    global _passed
    if not cond:
        print(f"FAIL: {msg}")
        sys.exit(1)
    _passed += 1
    print(f"ok: {msg}")


def ok(resp, msg):
    check(resp.status_code in (200, 201), f"{msg} -> {resp.status_code} {resp.text[:300]}")
    return resp.json()


# ---------------------------------------------------------------------------
# 1. Create a regression objective
# ---------------------------------------------------------------------------
obj = ok(
    client.post(
        "/modeling/objectives",
        json={
            "id": "mo1",
            "display_name": "Predict score",
            "problem_type": "regression",
            "target_field": "score",
            "feature_fields": ["a", "b"],
        },
    ),
    "create regression objective",
)
check(obj["id"] == "mo1", "objective id echoed")

# ---------------------------------------------------------------------------
# 2. Legacy train contract: {"algorithm": "linear"} still works
# ---------------------------------------------------------------------------
sub_legacy = ok(
    client.post("/modeling/objectives/mo1/train", json={"algorithm": "linear"}),
    "legacy train with algorithm",
)
check(sub_legacy["algorithm"] == "linear", "legacy algorithm preserved")
check(sub_legacy["status"] == "success", "submission has status lifecycle field")
check(sub_legacy["released"] is False, "new submission not released")

# ---------------------------------------------------------------------------
# 3. Enriched train contract with trainer_type + training config
# ---------------------------------------------------------------------------
sub = ok(
    client.post(
        "/modeling/objectives/mo1/train",
        json={
            "trainer_type": "regression",
            "training_dataset_id": "ds_train_1",
            "target_column": "score",
            "eval_metric": "rmse",
            "quality_preset": "balanced",
        },
    ),
    "enriched train with trainer_type",
)
check(sub["trainer_type"] == "regression", "trainer_type stored")
check(sub["training_dataset_id"] == "ds_train_1", "training_dataset_id stored")
check(sub["target_column"] == "score", "target_column stored")
check(sub["eval_metric"] == "rmse", "eval_metric stored")
check(sub["quality_preset"] == "balanced", "quality_preset stored")
check(sub["status"] == "success", "enriched submission has status")
check("rmse" in sub["metrics"] or "mae" in sub["metrics"], "regression metrics present")

# forecasting trainer family is accepted
sub_fc = ok(
    client.post(
        "/modeling/objectives/mo1/train",
        json={"trainer_type": "forecasting", "eval_metric": "smape"},
    ),
    "enriched train forecasting",
)
check(sub_fc["trainer_type"] == "forecasting", "forecasting trainer_type stored")

# invalid trainer_type rejected
bad = client.post("/modeling/objectives/mo1/train", json={"trainer_type": "bogus"})
check(bad.status_code == 422, f"invalid trainer_type rejected -> {bad.status_code}")

# ---------------------------------------------------------------------------
# 4. Release + deploy the enriched submission
# ---------------------------------------------------------------------------
ok(
    client.post("/modeling/objectives/mo1/release", json={"submission_id": sub["id"]}),
    "release submission",
)
dep = ok(
    client.post(
        "/modeling/deployments",
        json={"id": "dep1", "objective_id": "mo1", "submission_id": sub["id"], "mode": "live"},
    ),
    "create live deployment",
)
check(dep["status"] == "running", "deployment running")

# ---------------------------------------------------------------------------
# 5. Backward-compat legacy infer shape: {"records": [...]}
# ---------------------------------------------------------------------------
legacy_inf = ok(
    client.post("/modeling/deployments/dep1/infer", json={"records": [{"a": 2, "b": 4}]}),
    "legacy infer records shape",
)
check("predictions" in legacy_inf, "legacy infer returns predictions key")
check(len(legacy_inf["predictions"]) == 1, "legacy infer one prediction")
check(abs(legacy_inf["predictions"][0] - 3.0) < 1e-6, "regression mean of [2,4] == 3.0")

# ---------------------------------------------------------------------------
# 6. Multi-I/O envelope, single input -> default output name
# ---------------------------------------------------------------------------
mio = ok(
    client.post(
        "/modeling/deployments/dep1/infer",
        json={"inference_data": [{"a": 10, "b": 20}, {"a": 0, "b": 0}]},
    ),
    "multi-io default input name",
)
check("output_data" in mio, "default output name 'output_data' present")
check(isinstance(mio["output_data"], list), "output is a list")
check(len(mio["output_data"]) == 2, "two output records for two inputs")
check("prediction" in mio["output_data"][0], "output record has 'prediction' field")
check(abs(mio["output_data"][0]["prediction"] - 15.0) < 1e-6, "mean of [10,20] == 15.0")
check(abs(mio["output_data"][1]["prediction"] - 0.0) < 1e-6, "mean of [0,0] == 0.0")

# ---------------------------------------------------------------------------
# 7. Multi-I/O envelope, custom single input name -> "<name>_out"
# ---------------------------------------------------------------------------
mio2 = ok(
    client.post(
        "/modeling/deployments/dep1/infer",
        json={"table_1": [{"a": 6, "b": 8}]},
    ),
    "multi-io custom input name",
)
check("table_1_out" in mio2, "custom input maps to 'table_1_out'")
check(abs(mio2["table_1_out"][0]["prediction"] - 7.0) < 1e-6, "mean of [6,8] == 7.0")

# ---------------------------------------------------------------------------
# 8. Multi-I/O envelope, multiple inputs -> multiple namespaced outputs
# ---------------------------------------------------------------------------
mio3 = ok(
    client.post(
        "/modeling/deployments/dep1/infer",
        json={
            "table_1": [{"a": 2, "b": 2}],
            "table_2": [{"a": 4, "b": 4}, {"a": 6, "b": 6}],
        },
    ),
    "multi-io multiple inputs",
)
check("table_1_out" in mio3 and "table_2_out" in mio3, "both outputs present")
check(len(mio3["table_1_out"]) == 1, "table_1_out has 1 record")
check(len(mio3["table_2_out"]) == 2, "table_2_out has 2 records")

# ---------------------------------------------------------------------------
# 9. Empty / invalid Multi-I/O envelope is rejected
# ---------------------------------------------------------------------------
empty = client.post("/modeling/deployments/dep1/infer", json={"meta": "no lists here"})
check(empty.status_code == 422, f"envelope without input lists rejected -> {empty.status_code}")

# unknown deployment -> 404
missing = client.post("/modeling/deployments/nope/infer", json={"records": []})
check(missing.status_code == 404, f"unknown deployment 404 -> {missing.status_code}")

# ---------------------------------------------------------------------------
# 10. Classification objective: Multi-I/O returns string labels
# ---------------------------------------------------------------------------
ok(
    client.post(
        "/modeling/objectives",
        json={
            "id": "mo2",
            "display_name": "Classify",
            "problem_type": "classification",
            "target_field": "label",
            "feature_fields": ["x"],
        },
    ),
    "create classification objective",
)
csub = ok(
    client.post("/modeling/objectives/mo2/train", json={"trainer_type": "classification"}),
    "train classification",
)
ok(client.post("/modeling/objectives/mo2/release", json={"submission_id": csub["id"]}), "release cls")
ok(
    client.post(
        "/modeling/deployments",
        json={"id": "dep2", "objective_id": "mo2", "submission_id": csub["id"], "mode": "live"},
    ),
    "deploy cls",
)
cls_inf = ok(
    client.post("/modeling/deployments/dep2/infer", json={"inference_data": [{"x": "foo"}]}),
    "classification multi-io infer",
)
check(
    isinstance(cls_inf["output_data"][0]["prediction"], str)
    and cls_inf["output_data"][0]["prediction"].startswith("class_"),
    "classification returns class_* label",
)

print(f"\n{_passed} assertions passed")
sys.exit(0)

import os, tempfile
_tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(_tmp.name, 't.db')}"
from fastapi import FastAPI                       # noqa: E402
from fastapi.testclient import TestClient         # noqa: E402
from app.database import Base, engine, SessionLocal  # noqa: E402
from app import models, models_action            # noqa: E402  (registers core + audit tables)
from app import modeling                          # noqa: E402  (registers base modeling tables)
from app import modeling_evaluation_ops as M      # noqa: E402  (registers this module's tables)
import time                                        # noqa: E402

Base.metadata.create_all(bind=engine)
api = FastAPI(); api.include_router(M.router)
client = TestClient(api)
passed = 0


def ok(resp, label, expect=200):
    global passed
    success = resp.status_code == expect or (expect == 200 and 200 <= resp.status_code < 300)
    assert success, f"{label}: expected {expect}, got {resp.status_code} -> {resp.text[:400]}"
    passed += 1
    return resp.json() if resp.content else {}


def check(cond, label):
    global passed
    assert cond, f"CHECK FAILED: {label}"
    passed += 1


# ---------------------------------------------------------------------------
# Seed core modeling rows directly via a Session.
# ---------------------------------------------------------------------------
def seed():
    db = SessionLocal()
    now = int(time.time())
    # classification objective
    db.add(modeling.ModelingObjective(
        id="obj_clf", display_name="Churn", description=None, problem_type="classification",
        target_field="churn", feature_fields=["age", "tenure"], input_asset_id=None,
        created_at=now, updated_at=now,
    ))
    # regression objective
    db.add(modeling.ModelingObjective(
        id="obj_reg", display_name="Price", description=None, problem_type="regression",
        target_field="price", feature_fields=["sqft"], input_asset_id=None,
        created_at=now, updated_at=now,
    ))
    # submissions with stored metrics
    db.add(modeling.ModelSubmission(
        id="sub_good", objective_id="obj_clf", algorithm="xgb",
        metrics={"accuracy": 0.90, "auc": 0.93}, released=False, created_at=now,
    ))
    db.add(modeling.ModelSubmission(
        id="sub_bad", objective_id="obj_clf", algorithm="logreg",
        metrics={"accuracy": 0.82, "auc": 0.80}, released=False, created_at=now,
    ))
    db.add(modeling.ModelSubmission(
        id="sub_manual", objective_id="obj_clf", algorithm="rf",
        metrics={"accuracy": 0.91, "auc": 0.94}, released=False, created_at=now,
    ))
    db.add(modeling.ModelSubmission(
        id="sub_reg", objective_id="obj_reg", algorithm="linreg",
        metrics={"r2": 0.95}, released=False, created_at=now,
    ))
    db.commit()
    db.close()


seed()

# ---------------------------------------------------------------------------
# 1. Automatic check: accuracy >= 0.85 rejects 0.82 and approves 0.90
# ---------------------------------------------------------------------------
chk = ok(client.post("/modeling/objectives/obj_clf/checks", json={
    "name": "acc_gate", "check_type": "automatic",
    "metric": "accuracy", "operator": ">=", "threshold": 0.85,
}), "create automatic check")
check(chk["check_type"] == "automatic", "check type automatic")
auto_check_id = chk["id"]

# automatic check missing fields -> 422
ok(client.post("/modeling/objectives/obj_clf/checks", json={
    "name": "bad", "check_type": "automatic", "metric": "accuracy",
}), "automatic check missing threshold -> 422", expect=422)

# evaluate good submission -> approved
res_good = ok(client.post("/modeling/submissions/sub_good/evaluate-checks", json={}),
              "evaluate checks good submission")
statuses_good = {r["check_id"]: r["status"] for r in res_good}
check(statuses_good[auto_check_id] == "approved", "0.90 accuracy approved")

# evaluate bad submission -> rejected
res_bad = ok(client.post("/modeling/submissions/sub_bad/evaluate-checks", json={}),
             "evaluate checks bad submission")
statuses_bad = {r["check_id"]: r["status"] for r in res_bad}
check(statuses_bad[auto_check_id] == "rejected", "0.82 accuracy rejected")

# good submission is release-eligible; bad is not
elig_good = ok(client.get("/modeling/submissions/sub_good/release-eligibility"),
               "eligibility good")
check(elig_good["eligible"] is True, "good submission eligible")
elig_bad = ok(client.get("/modeling/submissions/sub_bad/release-eligibility"),
              "eligibility bad")
check(elig_bad["eligible"] is False, "bad submission not eligible")
check(auto_check_id in elig_bad["rejected_checks"], "bad lists rejected check")

# ---------------------------------------------------------------------------
# 2. Manual check blocks release until approved
# ---------------------------------------------------------------------------
mchk = ok(client.post("/modeling/objectives/obj_clf/checks", json={
    "name": "human_review", "check_type": "manual",
}), "create manual check")
manual_check_id = mchk["id"]

# sub_manual now has a pending manual check -> not eligible
elig_m = ok(client.get("/modeling/submissions/sub_manual/release-eligibility"),
            "eligibility manual pending")
check(elig_m["eligible"] is False, "manual pending blocks eligibility")
check(manual_check_id in elig_m["pending_manual_checks"], "manual pending listed")

# release rejected because not eligible
ok(client.post("/modeling/objectives/obj_clf/releases", json={
    "submission_id": "sub_manual", "version": "v1", "environment": "staging",
}), "release blocked by pending manual -> 422", expect=422)

# approve the manual check
dec = ok(client.post("/modeling/submissions/sub_manual/check-results", json={
    "check_id": manual_check_id, "status": "approved", "reviewer": "alice",
}), "approve manual check")
check(dec["status"] == "approved", "manual check approved")

# now eligible
elig_m2 = ok(client.get("/modeling/submissions/sub_manual/release-eligibility"),
             "eligibility after manual approve")
check(elig_m2["eligible"] is True, "eligible after manual approve")

# ---------------------------------------------------------------------------
# 3. Release succeeds when eligible; promote sets production
# ---------------------------------------------------------------------------
# sub_good also carries the pending manual check (checks are per-objective); approve it first.
ok(client.post("/modeling/submissions/sub_good/check-results", json={
    "check_id": manual_check_id, "status": "approved", "reviewer": "bob",
}), "approve manual check for sub_good")
elig_good2 = ok(client.get("/modeling/submissions/sub_good/release-eligibility"),
                "eligibility good after manual approve")
check(elig_good2["eligible"] is True, "sub_good eligible after manual approve")

rel = ok(client.post("/modeling/objectives/obj_clf/releases", json={
    "submission_id": "sub_good", "version": "v1.0", "environment": "staging", "notes": "first",
}), "create release for eligible submission")
check(rel["environment"] == "staging", "release env staging")
release_id = rel["id"]

# bad submission release rejected
ok(client.post("/modeling/objectives/obj_clf/releases", json={
    "submission_id": "sub_bad", "version": "v0", "environment": "staging",
}), "release rejected ineligible -> 422", expect=422)

rels = ok(client.get("/modeling/objectives/obj_clf/releases"), "list releases")
check(any(r["id"] == release_id for r in rels), "release listed")

prom = ok(client.post(f"/modeling/releases/{release_id}/promote", json={}), "promote release")
check(prom["environment"] == "production", "promote sets production")

# ---------------------------------------------------------------------------
# 4. Evaluation datasets + subsets; regression and classification metrics
# ---------------------------------------------------------------------------
# regression eval dataset
rds = ok(client.post("/modeling/objectives/obj_reg/eval-datasets", json={
    "display_name": "reg eval", "asset_id": "asset1",
}), "create regression eval dataset")
reg_ds_id = rds["id"]

# regression metrics on a tiny known set: preds=[2,4,6], actuals=[1,4,9]
# errors: 1,0,-3 -> MAE=(1+0+3)/3=4/3; RMSE=sqrt((1+0+9)/3)=sqrt(10/3)
reg = ok(client.post("/modeling/objectives/obj_reg/evaluate", json={
    "submission_id": "sub_reg", "eval_dataset_id": reg_ds_id,
    "predictions": [2, 4, 6], "actuals": [1, 4, 9],
}), "evaluate regression")
mae = reg["metrics"]["mae"]
rmse = reg["metrics"]["rmse"]
r2 = reg["metrics"]["r2"]
import math as _m
check(abs(mae - (4 / 3)) < 1e-6, f"regression MAE correct got {mae}")
check(abs(rmse - _m.sqrt(10 / 3)) < 1e-6, f"regression RMSE correct got {rmse}")
# mean actual=14/3; ss_tot=(1-14/3)^2+(4-14/3)^2+(9-14/3)^2 ; ss_res=10 ; r2=1-10/ss_tot
mean_a = 14 / 3
ss_tot = (1 - mean_a) ** 2 + (4 - mean_a) ** 2 + (9 - mean_a) ** 2
expected_r2 = 1 - 10 / ss_tot
check(abs(r2 - expected_r2) < 1e-6, f"regression R2 correct got {r2}")
check("mape" in reg["metrics"], "MAPE present (no zero actuals)")

# regression with a zero actual -> no MAPE
reg_zero = ok(client.post("/modeling/objectives/obj_reg/evaluate", json={
    "submission_id": "sub_reg", "eval_dataset_id": reg_ds_id,
    "predictions": [1, 2], "actuals": [0, 2],
}), "evaluate regression with zero actual")
check("mape" not in reg_zero["metrics"], "MAPE absent when zero actual present")

# classification eval dataset + subsets
cds = ok(client.post("/modeling/objectives/obj_clf/eval-datasets", json={
    "display_name": "clf eval",
}), "create classification eval dataset")
clf_ds_id = cds["id"]

# Two subsets across a 'region' attribute (fairness slices)
ss_a = ok(client.post(f"/modeling/eval-datasets/{clf_ds_id}/subsets", json={
    "name": "region_A", "filter_column": "region", "filter_values": ["A"],
}), "create subset A")
ss_b = ok(client.post(f"/modeling/eval-datasets/{clf_ds_id}/subsets", json={
    "name": "region_B", "filter_column": "region", "filter_values": ["B"],
}), "create subset B")
subs_list = ok(client.get(f"/modeling/eval-datasets/{clf_ds_id}/subsets"), "list subsets")
check(len(subs_list) == 2, "two subsets listed")

# classification metrics: preds vs actuals (1=positive)
# rows tagged with region so subsets differ
clf = ok(client.post("/modeling/objectives/obj_clf/evaluate", json={
    "submission_id": "sub_good", "eval_dataset_id": clf_ds_id,
    "predictions": [1, 0, 1, 1, 0, 0],
    "actuals":     [1, 0, 0, 1, 0, 1],
    "probability": [0.9, 0.2, 0.7, 0.8, 0.1, 0.6],
    "rows": [
        {"region": "A"}, {"region": "A"}, {"region": "A"},
        {"region": "B"}, {"region": "B"}, {"region": "B"},
    ],
}), "evaluate classification")
cm = clf["metrics"]["confusion_matrix"]
# tp: idx0(1,1),idx3(1,1)=2 ; fp: idx2(1,0)=1 ; tn: idx1(0,0),idx4(0,0)=2 ; fn: idx5(0,1)=1
check(cm["tp"] == 2 and cm["fp"] == 1 and cm["tn"] == 2 and cm["fn"] == 1, f"confusion matrix correct {cm}")
acc = clf["metrics"]["accuracy"]
check(abs(acc - (4 / 6)) < 1e-6, f"classification accuracy correct got {acc}")
prec = clf["metrics"]["precision"]
check(abs(prec - (2 / 3)) < 1e-6, f"precision correct got {prec}")
rec = clf["metrics"]["recall"]
check(abs(rec - (2 / 3)) < 1e-6, f"recall correct got {rec}")
check("roc_auc" in clf["metrics"], "roc_auc present with probabilities")

# subset metrics differ across slices
sm = clf["subset_metrics"]
check("region_A" in sm and "region_B" in sm, "both subset metrics present")
# region A rows: preds[1,0,1] actuals[1,0,0] -> acc=2/3
check(abs(sm["region_A"]["accuracy"] - (2 / 3)) < 1e-6, f"region A accuracy {sm['region_A']}")
# region B rows: preds[1,0,0] actuals[1,0,1] -> acc=2/3 but confusion differs
check(sm["region_A"]["confusion_matrix"] != sm["region_B"]["confusion_matrix"],
      "subset confusion matrices differ across slices")

# predictions/actuals length mismatch -> 422
ok(client.post("/modeling/objectives/obj_clf/evaluate", json={
    "submission_id": "sub_good", "eval_dataset_id": clf_ds_id,
    "predictions": [1, 0], "actuals": [1],
}), "length mismatch -> 422", expect=422)

# ---------------------------------------------------------------------------
# 5. Experiments logged & listed
# ---------------------------------------------------------------------------
exp = ok(client.post("/modeling/submissions/sub_good/experiments", json={
    "hyperparameters": {"lr": 0.1, "depth": 5},
    "metrics": {"accuracy": 0.90},
    "artifacts": {"model_uri": "mem://m1"},
}), "log experiment")
check(exp["hyperparameters"]["depth"] == 5, "experiment hyperparams stored")
exps = ok(client.get("/modeling/submissions/sub_good/experiments"), "list experiments")
check(len(exps) == 1, "one experiment listed")

# ---------------------------------------------------------------------------
# 6. Adapter define + infer validates schema
# ---------------------------------------------------------------------------
adp = ok(client.post("/modeling/submissions/sub_good/adapter", json={
    "input_schema": {"age": "integer", "tenure": "double"},
    "output_schema": {"score": "double"},
}), "create adapter")
check("score" in adp["output_schema"], "adapter output schema stored")

# infer missing input -> 422
ok(client.post("/modeling/submissions/sub_good/adapter/infer", json={
    "inputs": {"age": 30},
}), "adapter infer missing input -> 422", expect=422)

# infer wrong type -> 422
ok(client.post("/modeling/submissions/sub_good/adapter/infer", json={
    "inputs": {"age": "notanint", "tenure": 1.5},
}), "adapter infer wrong type -> 422", expect=422)

# infer valid -> outputs match output schema
inf = ok(client.post("/modeling/submissions/sub_good/adapter/infer", json={
    "inputs": {"age": 30, "tenure": 2.5},
}), "adapter infer valid")
check("score" in inf["outputs"], "infer produced output matching schema")

# ---------------------------------------------------------------------------
# 7. Deployment config binds to a specific release; query validates input
# ---------------------------------------------------------------------------
# live config requires replicas
ok(client.post("/modeling/deployment-configs", json={
    "release_id": release_id, "kind": "live",
}), "live config without replicas -> 422", expect=422)

dcfg = ok(client.post("/modeling/deployment-configs", json={
    "release_id": release_id, "kind": "live", "replicas": 2, "cpu": 1.0, "gpu": 0.0,
    "deployment_id": "dep1",
}), "create live deployment config")
check(dcfg["release_id"] == release_id, "deployment config bound to specific release")
cfg_id = dcfg["id"]

# config bound to nonexistent release -> 404
ok(client.post("/modeling/deployment-configs", json={
    "release_id": "nope", "kind": "batch", "spark_profile": {"executors": 4},
}), "config bad release -> 404", expect=404)

# batch config
bcfg = ok(client.post("/modeling/deployment-configs", json={
    "release_id": release_id, "kind": "batch", "spark_profile": {"executors": 4},
}), "create batch deployment config")
check(bcfg["spark_profile"]["executors"] == 4, "batch spark profile stored")

cfgs = ok(client.get("/modeling/deployment-configs"), "list deployment configs")
check(len(cfgs) >= 2, "deployment configs listed")

# query validates input against the bound release's adapter schema
# release_id is bound to sub_good which has an adapter (age:int, tenure:double)
q = ok(client.post(f"/modeling/deployment-configs/{cfg_id}/query", json={
    "inputs": {"age": 40, "tenure": 3.0},
}), "deployment config query valid")
check(q["validated"] is True and q["submission_id"] == "sub_good", "query validated against release adapter")

# query missing input -> 422
ok(client.post(f"/modeling/deployment-configs/{cfg_id}/query", json={
    "inputs": {"age": 40},
}), "deployment query missing input -> 422", expect=422)

# ---------------------------------------------------------------------------
# 8. 404s for unknown parents
# ---------------------------------------------------------------------------
ok(client.post("/modeling/objectives/ghost/checks", json={
    "name": "x", "check_type": "manual",
}), "check on unknown objective -> 404", expect=404)
ok(client.get("/modeling/submissions/ghost/check-results"),
   "check-results unknown submission -> 404", expect=404)

print(f"\nMODELING verified: {passed} assertions passed.")
engine.dispose(); _tmp.cleanup()

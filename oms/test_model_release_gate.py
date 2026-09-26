"""A gate-blocked submission cannot be marked released (GOAL_FOUNDATIONS A3c).

`POST /modeling/objectives/{id}/release` set `released = True` without asking the
release gate, and ModelOps called it before `POST .../releases`, which does ask and
refused with 422. One click on a submission its Gates tab showed as blocked left it
marked released, with "Start deployment" enabled. The endpoint now refuses first,
with the same detail as the gated release, and changes nothing.
"""
import os
import tempfile

_tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(_tmp.name, 't.db')}"

import time  # noqa: E402

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.database import Base, SessionLocal, engine  # noqa: E402
from app import models, models_action  # noqa: E402,F401  (core and audit tables)
from app import modeling  # noqa: E402
from app import modeling_evaluation_ops as evaluation  # noqa: E402  (the gate's tables)

Base.metadata.create_all(bind=engine)
api = FastAPI()
api.include_router(modeling.router)
api.include_router(evaluation.router)
client = TestClient(api)
checks = 0


def check(condition, message):
    global checks
    assert condition, message
    checks += 1


now = int(time.time())
with SessionLocal() as db:
    db.add(modeling.ModelingObjective(
        id="obj", display_name="Churn", description=None, problem_type="classification",
        target_field="churn", feature_fields=["age"], input_asset_id=None, created_at=now, updated_at=now))
    db.add(modeling.ModelSubmission(id="sub_good", objective_id="obj", algorithm="xgb",
                                    metrics={"accuracy": 0.90}, released=False, created_at=now))
    db.add(modeling.ModelSubmission(id="sub_bad", objective_id="obj", algorithm="logreg",
                                    metrics={"accuracy": 0.82}, released=False, created_at=now))
    db.commit()


def released(submission_id):
    with SessionLocal() as db:
        return db.get(modeling.ModelSubmission, submission_id).released


# With no gate, a submission releases as it always did.
free = client.post("/modeling/objectives/obj/release", json={"submission_id": "sub_bad"})
check(free.status_code == 200, f"with no check defined, release is not gated: {free.status_code} {free.text[:200]}")
check(released("sub_bad") is True, "an ungated release marks the submission released")
with SessionLocal() as db:
    db.get(modeling.ModelSubmission, "sub_bad").released = False
    db.commit()

# An automatic gate: accuracy >= 0.85 rejects sub_bad.
gate = client.post("/modeling/objectives/obj/checks", json={
    "name": "acc_gate", "check_type": "automatic", "metric": "accuracy", "operator": ">=", "threshold": 0.85})
check(gate.status_code in (200, 201), f"the gate is created: {gate.status_code} {gate.text[:200]}")
eligibility = client.get("/modeling/submissions/sub_bad/release-eligibility").json()
check(eligibility["eligible"] is False, f"the Gates tab's answer for sub_bad is blocked: {eligibility}")

refused = client.post("/modeling/objectives/obj/release", json={"submission_id": "sub_bad"})
check(refused.status_code == 422, f"a gate-blocked submission is refused: {refused.status_code} {refused.text[:200]}")
detail = refused.json().get("detail", {})
check(detail.get("error") == "submission not release-eligible", f"the refusal says why: {detail}")
check(gate.json()["id"] in detail.get("rejected_checks", []), f"the refusal names the rejected check: {detail}")
check(released("sub_bad") is False, "a refused release marks nothing released")

# The eligible submission still releases.
allowed = client.post("/modeling/objectives/obj/release", json={"submission_id": "sub_good"})
check(allowed.status_code == 200, f"an eligible submission releases: {allowed.status_code} {allowed.text[:200]}")
check(released("sub_good") is True and released("sub_bad") is False, "only the eligible submission is released")

print(f"Release gate verified: {checks} assertions passed.")

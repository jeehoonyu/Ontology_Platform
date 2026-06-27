"""
Modeling Objectives lifecycle deepening: releases (environment tags), checks (manual +
automatic), evaluation datasets / subsets (fairness slices), experiments, model adapters,
and deployment configuration.

Docs (Foundry): manage-models/{create-a-modeling-objective, release-model, set-up-batch,
set-up-live, configure-objective-metadata, set-up-checks, live-deployment-reference};
evaluate-models/{model-evaluation-automatic, evaluator-binary-classification,
evaluator-regression}.

Scope (per critic): Objectives / Checks / Releases / Evaluation / Adapters / Deployment.
Model Studio AutoML trainers are intentionally OUT of scope (separate pass).

Release -> deployment binding (per critic): NOT automatic. A deployment config binds to a
SPECIFIC release (deployment_config.release_id). "promote" explicitly re-points a release's
environment to "production"; it does not silently rebind any deployment. We use the
explicit specific-release binding model throughout.

All ORM classes / tables are prefixed Mev / mev_ to avoid collisions on the shared Base.
The base modeling tables (ModelingObjective, ModelSubmission, ModelDeployment) are imported
read-only from app.modeling.
"""

from .database import Base, get_db
from . import models, models_action
from .modeling import ModelingObjective, ModelSubmission, ModelDeployment
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import String, Integer, JSON, Boolean, Float, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, Session
from pydantic import BaseModel, ConfigDict, Field
from typing import Optional, List, Any, Dict
import time, uuid, math

# ---------------------------------------------------------------------------
# SQLAlchemy ORM models  (prefix Mev / mev_)
# ---------------------------------------------------------------------------

VALID_ENVIRONMENTS = {"staging", "production"}
VALID_CHECK_TYPES = {"manual", "automatic"}
VALID_CHECK_STATUS = {"pending", "approved", "rejected"}
VALID_OPERATORS = {">", ">=", "<", "<=", "==", "!="}
VALID_DEPLOY_KINDS = {"batch", "live"}


class MevRelease(Base):
    """A released model version pinned to an environment tag (staging / production)."""
    __tablename__ = "mev_releases"

    id: Mapped[str] = mapped_column(String, primary_key=True, index=True)
    objective_id: Mapped[str] = mapped_column(String, ForeignKey("modeling_objectives.id"), index=True)
    submission_id: Mapped[str] = mapped_column(String, ForeignKey("model_submissions.id"), index=True)
    version: Mapped[str] = mapped_column(String)
    environment: Mapped[str] = mapped_column(String)  # staging | production
    notes: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    created_at: Mapped[int] = mapped_column(Integer)


class MevCheck(Base):
    """A manual or automatic release-gate check defined on an objective."""
    __tablename__ = "mev_checks"

    id: Mapped[str] = mapped_column(String, primary_key=True, index=True)
    objective_id: Mapped[str] = mapped_column(String, ForeignKey("modeling_objectives.id"), index=True)
    name: Mapped[str] = mapped_column(String)
    check_type: Mapped[str] = mapped_column(String)  # manual | automatic
    metric: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    operator: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    threshold: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    created_at: Mapped[int] = mapped_column(Integer)


class MevCheckResult(Base):
    """The decision (pending/approved/rejected) for a check against a submission."""
    __tablename__ = "mev_check_results"

    id: Mapped[str] = mapped_column(String, primary_key=True, index=True)
    submission_id: Mapped[str] = mapped_column(String, ForeignKey("model_submissions.id"), index=True)
    check_id: Mapped[str] = mapped_column(String, ForeignKey("mev_checks.id"), index=True)
    status: Mapped[str] = mapped_column(String)  # pending | approved | rejected
    reviewer: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    comment: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    decided_at: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)


class MevEvalDataset(Base):
    """An evaluation dataset registered for an objective."""
    __tablename__ = "mev_eval_datasets"

    id: Mapped[str] = mapped_column(String, primary_key=True, index=True)
    objective_id: Mapped[str] = mapped_column(String, ForeignKey("modeling_objectives.id"), index=True)
    asset_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    display_name: Mapped[str] = mapped_column(String)
    created_at: Mapped[int] = mapped_column(Integer)


class MevEvalSubset(Base):
    """A fairness/analysis slice over an evaluation dataset (filter_column in filter_values)."""
    __tablename__ = "mev_eval_subsets"

    id: Mapped[str] = mapped_column(String, primary_key=True, index=True)
    eval_dataset_id: Mapped[str] = mapped_column(String, ForeignKey("mev_eval_datasets.id"), index=True)
    name: Mapped[str] = mapped_column(String)
    filter_column: Mapped[str] = mapped_column(String)
    filter_values: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[int] = mapped_column(Integer)


class MevExperiment(Base):
    """A logged experiment: hyperparameters, metrics, artifacts for a submission."""
    __tablename__ = "mev_experiments"

    id: Mapped[str] = mapped_column(String, primary_key=True, index=True)
    submission_id: Mapped[str] = mapped_column(String, ForeignKey("model_submissions.id"), index=True)
    hyperparameters: Mapped[dict] = mapped_column(JSON, default=dict)
    metrics: Mapped[dict] = mapped_column(JSON, default=dict)
    artifacts: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[int] = mapped_column(Integer)


class MevAdapter(Base):
    """A model adapter defining the input/output schema of a submission."""
    __tablename__ = "mev_adapters"

    id: Mapped[str] = mapped_column(String, primary_key=True, index=True)
    submission_id: Mapped[str] = mapped_column(String, ForeignKey("model_submissions.id"), index=True)
    input_schema: Mapped[dict] = mapped_column(JSON, default=dict)
    output_schema: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[int] = mapped_column(Integer)


class MevDeploymentConfig(Base):
    """Deployment configuration bound to a SPECIFIC release (batch or live)."""
    __tablename__ = "mev_deployment_configs"

    id: Mapped[str] = mapped_column(String, primary_key=True, index=True)
    deployment_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    release_id: Mapped[str] = mapped_column(String, ForeignKey("mev_releases.id"), index=True)
    kind: Mapped[str] = mapped_column(String)  # batch | live
    spark_profile: Mapped[dict] = mapped_column(JSON, default=dict)
    replicas: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    cpu: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    gpu: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    created_at: Mapped[int] = mapped_column(Integer)


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------

class MevCheckCreate(BaseModel):
    id: Optional[str] = None
    name: str
    check_type: str
    metric: Optional[str] = None
    operator: Optional[str] = None
    threshold: Optional[float] = None


class MevCheckRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    objective_id: str
    name: str
    check_type: str
    metric: Optional[str] = None
    operator: Optional[str] = None
    threshold: Optional[float] = None
    created_at: int


class MevCheckResultRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    submission_id: str
    check_id: str
    status: str
    reviewer: Optional[str] = None
    comment: Optional[str] = None
    decided_at: Optional[int] = None


class MevCheckDecision(BaseModel):
    check_id: str
    status: str  # approved | rejected
    reviewer: Optional[str] = None
    comment: Optional[str] = None


class MevReleaseCreate(BaseModel):
    id: Optional[str] = None
    submission_id: str
    version: str
    environment: str = "staging"
    notes: Optional[str] = None


class MevReleaseRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    objective_id: str
    submission_id: str
    version: str
    environment: str
    notes: Optional[str] = None
    created_at: int


class MevEvalDatasetCreate(BaseModel):
    id: Optional[str] = None
    asset_id: Optional[str] = None
    display_name: str


class MevEvalDatasetRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    objective_id: str
    asset_id: Optional[str] = None
    display_name: str
    created_at: int


class MevEvalSubsetCreate(BaseModel):
    id: Optional[str] = None
    name: str
    filter_column: str
    filter_values: List[Any] = Field(default_factory=list)


class MevEvalSubsetRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    eval_dataset_id: str
    name: str
    filter_column: str
    filter_values: List[Any]
    created_at: int


class MevEvaluateRequest(BaseModel):
    submission_id: str
    eval_dataset_id: str
    predictions: List[Any]
    actuals: List[Any]
    probability: Optional[List[float]] = None
    rows: Optional[List[Dict[str, Any]]] = None  # optional per-row attributes for subset slicing


class MevExperimentCreate(BaseModel):
    id: Optional[str] = None
    hyperparameters: Dict[str, Any] = Field(default_factory=dict)
    metrics: Dict[str, Any] = Field(default_factory=dict)
    artifacts: Dict[str, Any] = Field(default_factory=dict)


class MevExperimentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    submission_id: str
    hyperparameters: Dict[str, Any]
    metrics: Dict[str, Any]
    artifacts: Dict[str, Any]
    created_at: int


class MevAdapterCreate(BaseModel):
    id: Optional[str] = None
    input_schema: Dict[str, Any] = Field(default_factory=dict)
    output_schema: Dict[str, Any] = Field(default_factory=dict)


class MevAdapterRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    submission_id: str
    input_schema: Dict[str, Any]
    output_schema: Dict[str, Any]
    created_at: int


class MevInferRequest(BaseModel):
    inputs: Dict[str, Any]


class MevDeploymentConfigCreate(BaseModel):
    id: Optional[str] = None
    deployment_id: Optional[str] = None
    release_id: str
    kind: str  # batch | live
    spark_profile: Dict[str, Any] = Field(default_factory=dict)
    replicas: Optional[int] = None
    cpu: Optional[float] = None
    gpu: Optional[float] = None


class MevDeploymentConfigRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    deployment_id: Optional[str] = None
    release_id: str
    kind: str
    spark_profile: Dict[str, Any]
    replicas: Optional[int] = None
    cpu: Optional[float] = None
    gpu: Optional[float] = None
    created_at: int


# ---------------------------------------------------------------------------
# Router + helpers
# ---------------------------------------------------------------------------

router = APIRouter(tags=["modeling-evaluation"])


def _now() -> int:
    return int(time.time())


def _audit(db: Session, event_type: str, subject_type: str, subject_id: str,
           payload: Dict[str, Any], actor: str = "system") -> None:
    db.add(models_action.AuditLog(
        id=uuid.uuid4().hex, actor=actor, event_type=event_type,
        subject_type=subject_type, subject_id=subject_id, payload=payload,
    ))


def _get_objective(db: Session, objective_id: str) -> ModelingObjective:
    obj = db.query(ModelingObjective).filter(ModelingObjective.id == objective_id).first()
    if not obj:
        raise HTTPException(status_code=404, detail=f"ModelingObjective '{objective_id}' not found")
    return obj


def _get_submission(db: Session, submission_id: str) -> ModelSubmission:
    sub = db.query(ModelSubmission).filter(ModelSubmission.id == submission_id).first()
    if not sub:
        raise HTTPException(status_code=404, detail=f"ModelSubmission '{submission_id}' not found")
    return sub


def _compare(value: float, operator: str, threshold: float) -> bool:
    if operator == ">":
        return value > threshold
    if operator == ">=":
        return value >= threshold
    if operator == "<":
        return value < threshold
    if operator == "<=":
        return value <= threshold
    if operator == "==":
        return value == threshold
    if operator == "!=":
        return value != threshold
    raise HTTPException(status_code=422, detail=f"Unknown operator '{operator}'")


# ---------------------------------------------------------------------------
# Checks
# ---------------------------------------------------------------------------

@router.post("/modeling/objectives/{objective_id}/checks", response_model=MevCheckRead)
def create_check(objective_id: str, body: MevCheckCreate, db: Session = Depends(get_db)):
    _get_objective(db, objective_id)
    if body.check_type not in VALID_CHECK_TYPES:
        raise HTTPException(status_code=422, detail=f"check_type must be one of {sorted(VALID_CHECK_TYPES)}")
    if body.check_type == "automatic":
        if not body.metric or not body.operator or body.threshold is None:
            raise HTTPException(status_code=422,
                                detail="automatic check requires metric, operator, and threshold")
        if body.operator not in VALID_OPERATORS:
            raise HTTPException(status_code=422, detail=f"operator must be one of {sorted(VALID_OPERATORS)}")
    cid = body.id or uuid.uuid4().hex
    if db.query(MevCheck).filter(MevCheck.id == cid).first():
        raise HTTPException(status_code=400, detail="MevCheck already exists")
    row = MevCheck(
        id=cid, objective_id=objective_id, name=body.name, check_type=body.check_type,
        metric=body.metric, operator=body.operator, threshold=body.threshold, created_at=_now(),
    )
    db.add(row)
    _audit(db, "modeling.check.created", "mev_check", cid,
           {"objective_id": objective_id, "check_type": body.check_type})
    db.commit()
    db.refresh(row)
    return row


@router.get("/modeling/objectives/{objective_id}/checks", response_model=List[MevCheckRead])
def list_checks(objective_id: str, db: Session = Depends(get_db)):
    _get_objective(db, objective_id)
    return db.query(MevCheck).filter(MevCheck.objective_id == objective_id).all()


def _evaluate_submission_checks(db: Session, submission: ModelSubmission) -> List[MevCheckResult]:
    """
    Materialize check results for a submission. Automatic checks evaluate the submission's stored
    metric vs threshold/operator -> approved/rejected automatically. Manual checks start pending.
    Idempotent per (submission, check): existing results are reused.
    """
    checks = db.query(MevCheck).filter(MevCheck.objective_id == submission.objective_id).all()
    results: List[MevCheckResult] = []
    metrics = submission.metrics or {}
    for chk in checks:
        existing = db.query(MevCheckResult).filter(
            MevCheckResult.submission_id == submission.id,
            MevCheckResult.check_id == chk.id,
        ).first()
        if existing:
            results.append(existing)
            continue
        if chk.check_type == "automatic":
            metric_val = metrics.get(chk.metric)
            if metric_val is None:
                status = "rejected"  # missing metric cannot satisfy the gate
            else:
                status = "approved" if _compare(float(metric_val), chk.operator, float(chk.threshold)) else "rejected"
            res = MevCheckResult(
                id=uuid.uuid4().hex, submission_id=submission.id, check_id=chk.id,
                status=status, reviewer="system",
                comment=f"auto: {chk.metric}={metric_val} {chk.operator} {chk.threshold}",
                decided_at=_now(),
            )
        else:
            res = MevCheckResult(
                id=uuid.uuid4().hex, submission_id=submission.id, check_id=chk.id,
                status="pending", reviewer=None, comment=None, decided_at=None,
            )
        db.add(res)
        results.append(res)
    db.commit()
    for r in results:
        db.refresh(r)
    return results


@router.post("/modeling/submissions/{submission_id}/evaluate-checks",
             response_model=List[MevCheckResultRead])
def evaluate_checks(submission_id: str, db: Session = Depends(get_db)):
    sub = _get_submission(db, submission_id)
    return _evaluate_submission_checks(db, sub)


@router.get("/modeling/submissions/{submission_id}/check-results",
            response_model=List[MevCheckResultRead])
def list_check_results(submission_id: str, db: Session = Depends(get_db)):
    _get_submission(db, submission_id)
    return db.query(MevCheckResult).filter(MevCheckResult.submission_id == submission_id).all()


@router.post("/modeling/submissions/{submission_id}/check-results",
             response_model=MevCheckResultRead)
def decide_check_result(submission_id: str, body: MevCheckDecision, db: Session = Depends(get_db)):
    _get_submission(db, submission_id)
    if body.status not in {"approved", "rejected"}:
        raise HTTPException(status_code=422, detail="status must be 'approved' or 'rejected'")
    chk = db.query(MevCheck).filter(MevCheck.id == body.check_id).first()
    if not chk:
        raise HTTPException(status_code=404, detail=f"MevCheck '{body.check_id}' not found")
    res = db.query(MevCheckResult).filter(
        MevCheckResult.submission_id == submission_id,
        MevCheckResult.check_id == body.check_id,
    ).first()
    if not res:
        res = MevCheckResult(
            id=uuid.uuid4().hex, submission_id=submission_id, check_id=body.check_id,
            status=body.status,
        )
        db.add(res)
    res.status = body.status
    res.reviewer = body.reviewer or "system"
    res.comment = body.comment
    res.decided_at = _now()
    _audit(db, "modeling.check_result.decided", "mev_check_result", res.id,
           {"submission_id": submission_id, "check_id": body.check_id, "status": body.status})
    db.commit()
    db.refresh(res)
    return res


def _release_eligibility(db: Session, submission: ModelSubmission) -> Dict[str, Any]:
    """
    A submission is release-eligible iff no check is rejected AND all manual checks are approved.
    Ensures check results exist (materializes automatic ones) before judging.
    """
    _evaluate_submission_checks(db, submission)
    checks = {c.id: c for c in db.query(MevCheck).filter(
        MevCheck.objective_id == submission.objective_id).all()}
    results = db.query(MevCheckResult).filter(
        MevCheckResult.submission_id == submission.id).all()
    rejected = [r.check_id for r in results if r.status == "rejected"]
    pending_manual = [
        r.check_id for r in results
        if r.status == "pending" and checks.get(r.check_id) and checks[r.check_id].check_type == "manual"
    ]
    eligible = (len(rejected) == 0) and (len(pending_manual) == 0)
    return {"eligible": eligible, "rejected_checks": rejected, "pending_manual_checks": pending_manual}


@router.get("/modeling/submissions/{submission_id}/release-eligibility")
def get_release_eligibility(submission_id: str, db: Session = Depends(get_db)) -> Dict[str, Any]:
    sub = _get_submission(db, submission_id)
    return _release_eligibility(db, sub)


# ---------------------------------------------------------------------------
# Releases
# ---------------------------------------------------------------------------

@router.post("/modeling/objectives/{objective_id}/releases", response_model=MevReleaseRead)
def create_release(objective_id: str, body: MevReleaseCreate, db: Session = Depends(get_db)):
    _get_objective(db, objective_id)
    if body.environment not in VALID_ENVIRONMENTS:
        raise HTTPException(status_code=422, detail=f"environment must be one of {sorted(VALID_ENVIRONMENTS)}")
    sub = db.query(ModelSubmission).filter(
        ModelSubmission.id == body.submission_id,
        ModelSubmission.objective_id == objective_id,
    ).first()
    if not sub:
        raise HTTPException(status_code=404,
                            detail=f"ModelSubmission '{body.submission_id}' not found for objective")
    elig = _release_eligibility(db, sub)
    if not elig["eligible"]:
        raise HTTPException(status_code=422, detail={
            "error": "submission not release-eligible",
            "rejected_checks": elig["rejected_checks"],
            "pending_manual_checks": elig["pending_manual_checks"],
        })
    rid = body.id or uuid.uuid4().hex
    if db.query(MevRelease).filter(MevRelease.id == rid).first():
        raise HTTPException(status_code=400, detail="MevRelease already exists")
    row = MevRelease(
        id=rid, objective_id=objective_id, submission_id=body.submission_id,
        version=body.version, environment=body.environment, notes=body.notes, created_at=_now(),
    )
    db.add(row)
    # Reconcile with the base modeling lifecycle: a versioned release marks the
    # underlying submission as released, so the base /modeling/deployments gate
    # (which checks ModelSubmission.released) agrees with the release record.
    if hasattr(sub, "released"):
        sub.released = True
    _audit(db, "modeling.release.created", "mev_release", rid,
           {"objective_id": objective_id, "submission_id": body.submission_id,
            "environment": body.environment})
    db.commit()
    db.refresh(row)
    return row


@router.get("/modeling/objectives/{objective_id}/releases", response_model=List[MevReleaseRead])
def list_releases(objective_id: str, db: Session = Depends(get_db)):
    _get_objective(db, objective_id)
    return db.query(MevRelease).filter(
        MevRelease.objective_id == objective_id).order_by(MevRelease.created_at.desc()).all()


@router.post("/modeling/releases/{release_id}/promote", response_model=MevReleaseRead)
def promote_release(release_id: str, db: Session = Depends(get_db)):
    """
    Promote explicitly re-points a release's environment to 'production'. It does NOT silently
    rebind any deployment config; deployment configs bind to a specific release_id (re-point
    those explicitly via a new deployment config if desired).
    """
    row = db.query(MevRelease).filter(MevRelease.id == release_id).first()
    if not row:
        raise HTTPException(status_code=404, detail=f"MevRelease '{release_id}' not found")
    row.environment = "production"
    _audit(db, "modeling.release.promoted", "mev_release", release_id,
           {"environment": "production"})
    db.commit()
    db.refresh(row)
    return row


# ---------------------------------------------------------------------------
# Evaluation datasets / subsets
# ---------------------------------------------------------------------------

@router.post("/modeling/objectives/{objective_id}/eval-datasets", response_model=MevEvalDatasetRead)
def create_eval_dataset(objective_id: str, body: MevEvalDatasetCreate, db: Session = Depends(get_db)):
    _get_objective(db, objective_id)
    did = body.id or uuid.uuid4().hex
    if db.query(MevEvalDataset).filter(MevEvalDataset.id == did).first():
        raise HTTPException(status_code=400, detail="MevEvalDataset already exists")
    row = MevEvalDataset(
        id=did, objective_id=objective_id, asset_id=body.asset_id,
        display_name=body.display_name, created_at=_now(),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@router.get("/modeling/objectives/{objective_id}/eval-datasets",
            response_model=List[MevEvalDatasetRead])
def list_eval_datasets(objective_id: str, db: Session = Depends(get_db)):
    _get_objective(db, objective_id)
    return db.query(MevEvalDataset).filter(MevEvalDataset.objective_id == objective_id).all()


@router.post("/modeling/eval-datasets/{eval_dataset_id}/subsets", response_model=MevEvalSubsetRead)
def create_eval_subset(eval_dataset_id: str, body: MevEvalSubsetCreate, db: Session = Depends(get_db)):
    ds = db.query(MevEvalDataset).filter(MevEvalDataset.id == eval_dataset_id).first()
    if not ds:
        raise HTTPException(status_code=404, detail=f"MevEvalDataset '{eval_dataset_id}' not found")
    sid = body.id or uuid.uuid4().hex
    if db.query(MevEvalSubset).filter(MevEvalSubset.id == sid).first():
        raise HTTPException(status_code=400, detail="MevEvalSubset already exists")
    row = MevEvalSubset(
        id=sid, eval_dataset_id=eval_dataset_id, name=body.name,
        filter_column=body.filter_column, filter_values=body.filter_values, created_at=_now(),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@router.get("/modeling/eval-datasets/{eval_dataset_id}/subsets",
            response_model=List[MevEvalSubsetRead])
def list_eval_subsets(eval_dataset_id: str, db: Session = Depends(get_db)):
    ds = db.query(MevEvalDataset).filter(MevEvalDataset.id == eval_dataset_id).first()
    if not ds:
        raise HTTPException(status_code=404, detail=f"MevEvalDataset '{eval_dataset_id}' not found")
    return db.query(MevEvalSubset).filter(MevEvalSubset.eval_dataset_id == eval_dataset_id).all()


# ---------------------------------------------------------------------------
# Deterministic evaluation metric helpers
# ---------------------------------------------------------------------------

def _regression_metrics(preds: List[float], actuals: List[float]) -> Dict[str, Any]:
    n = len(actuals)
    if n == 0:
        raise HTTPException(status_code=422, detail="no rows to evaluate")
    abs_err = [abs(p - a) for p, a in zip(preds, actuals)]
    sq_err = [(p - a) ** 2 for p, a in zip(preds, actuals)]
    mae = sum(abs_err) / n
    rmse = math.sqrt(sum(sq_err) / n)
    mean_actual = sum(actuals) / n
    ss_tot = sum((a - mean_actual) ** 2 for a in actuals)
    ss_res = sum(sq_err)
    r2 = 1.0 - (ss_res / ss_tot) if ss_tot != 0 else 0.0
    out: Dict[str, Any] = {
        "count": n,
        "mae": round(mae, 6),
        "rmse": round(rmse, 6),
        "r2": round(r2, 6),
    }
    # MAPE only if no zero actuals (per brief)
    if all(a != 0 for a in actuals):
        mape = sum(abs((a - p) / a) for p, a in zip(preds, actuals)) / n
        out["mape"] = round(mape, 6)
    return out


def _binary_classification_metrics(preds: List[Any], actuals: List[Any],
                                   probability: Optional[List[float]] = None) -> Dict[str, Any]:
    n = len(actuals)
    if n == 0:
        raise HTTPException(status_code=422, detail="no rows to evaluate")
    # Treat 1/"1"/True as the positive class deterministically.
    def _pos(v: Any) -> int:
        return 1 if v in (1, "1", True, 1.0) else 0
    p = [_pos(x) for x in preds]
    a = [_pos(x) for x in actuals]
    tp = sum(1 for pi, ai in zip(p, a) if pi == 1 and ai == 1)
    tn = sum(1 for pi, ai in zip(p, a) if pi == 0 and ai == 0)
    fp = sum(1 for pi, ai in zip(p, a) if pi == 1 and ai == 0)
    fn = sum(1 for pi, ai in zip(p, a) if pi == 0 and ai == 1)
    accuracy = (tp + tn) / n
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) else 0.0
    out: Dict[str, Any] = {
        "count": n,
        "accuracy": round(accuracy, 6),
        "precision": round(precision, 6),
        "recall": round(recall, 6),
        "f1": round(f1, 6),
        "confusion_matrix": {"tp": tp, "tn": tn, "fp": fp, "fn": fn},
    }
    if probability is not None and len(probability) == n:
        out["roc_auc"] = round(_roc_auc(a, probability), 6)
    return out


def _roc_auc(actual: List[int], scores: List[float]) -> float:
    """
    Deterministic ROC AUC via the Mann-Whitney U statistic (rank-based), with tie handling.
    """
    pos = [s for s, y in zip(scores, actual) if y == 1]
    neg = [s for s, y in zip(scores, actual) if y == 0]
    if not pos or not neg:
        return 0.0
    # Average ranks (1-based) over all scores, ties share the mean rank.
    paired = sorted(zip(scores, range(len(scores))), key=lambda t: t[0])
    ranks = [0.0] * len(scores)
    i = 0
    while i < len(paired):
        j = i
        while j + 1 < len(paired) and paired[j + 1][0] == paired[i][0]:
            j += 1
        avg_rank = (i + 1 + j + 1) / 2.0  # mean of 1-based ranks in the tie block
        for k in range(i, j + 1):
            ranks[paired[k][1]] = avg_rank
        i = j + 1
    sum_ranks_pos = sum(r for r, y in zip(ranks, actual) if y == 1)
    n_pos, n_neg = len(pos), len(neg)
    auc = (sum_ranks_pos - n_pos * (n_pos + 1) / 2.0) / (n_pos * n_neg)
    return auc


def _compute_metrics(problem_type: str, preds: List[Any], actuals: List[Any],
                     probability: Optional[List[float]]) -> Dict[str, Any]:
    if problem_type == "regression":
        return _regression_metrics([float(x) for x in preds], [float(x) for x in actuals])
    return _binary_classification_metrics(preds, actuals, probability)


@router.post("/modeling/objectives/{objective_id}/evaluate")
def evaluate(objective_id: str, body: MevEvaluateRequest, db: Session = Depends(get_db)) -> Dict[str, Any]:
    objective = _get_objective(db, objective_id)
    sub = db.query(ModelSubmission).filter(
        ModelSubmission.id == body.submission_id,
        ModelSubmission.objective_id == objective_id,
    ).first()
    if not sub:
        raise HTTPException(status_code=404,
                            detail=f"ModelSubmission '{body.submission_id}' not found for objective")
    ds = db.query(MevEvalDataset).filter(
        MevEvalDataset.id == body.eval_dataset_id,
        MevEvalDataset.objective_id == objective_id,
    ).first()
    if not ds:
        raise HTTPException(status_code=404,
                            detail=f"MevEvalDataset '{body.eval_dataset_id}' not found for objective")
    if len(body.predictions) != len(body.actuals):
        raise HTTPException(status_code=422, detail="predictions and actuals must be the same length")
    if not body.predictions:
        raise HTTPException(status_code=422, detail="no rows to evaluate")

    overall = _compute_metrics(objective.problem_type, body.predictions, body.actuals, body.probability)

    # Per-subset (fairness slice) metrics: filter rows where filter_column value in filter_values.
    subset_metrics: Dict[str, Any] = {}
    subsets = db.query(MevEvalSubset).filter(
        MevEvalSubset.eval_dataset_id == body.eval_dataset_id).all()
    rows = body.rows or []
    for ss in subsets:
        if not rows:
            subset_metrics[ss.name] = {"count": 0, "note": "no per-row attributes supplied"}
            continue
        idxs = [i for i, r in enumerate(rows)
                if i < len(body.predictions) and r.get(ss.filter_column) in ss.filter_values]
        if not idxs:
            subset_metrics[ss.name] = {"count": 0}
            continue
        s_preds = [body.predictions[i] for i in idxs]
        s_actuals = [body.actuals[i] for i in idxs]
        s_prob = ([body.probability[i] for i in idxs]
                  if body.probability is not None and len(body.probability) == len(body.predictions)
                  else None)
        subset_metrics[ss.name] = _compute_metrics(
            objective.problem_type, s_preds, s_actuals, s_prob)

    _audit(db, "modeling.evaluation.run", "model_submission", body.submission_id,
           {"objective_id": objective_id, "eval_dataset_id": body.eval_dataset_id})
    db.commit()
    return {
        "submission_id": body.submission_id,
        "eval_dataset_id": body.eval_dataset_id,
        "problem_type": objective.problem_type,
        "metrics": overall,
        "subset_metrics": subset_metrics,
    }


# ---------------------------------------------------------------------------
# Experiments
# ---------------------------------------------------------------------------

@router.post("/modeling/submissions/{submission_id}/experiments", response_model=MevExperimentRead)
def create_experiment(submission_id: str, body: MevExperimentCreate, db: Session = Depends(get_db)):
    _get_submission(db, submission_id)
    eid = body.id or uuid.uuid4().hex
    if db.query(MevExperiment).filter(MevExperiment.id == eid).first():
        raise HTTPException(status_code=400, detail="MevExperiment already exists")
    row = MevExperiment(
        id=eid, submission_id=submission_id, hyperparameters=body.hyperparameters,
        metrics=body.metrics, artifacts=body.artifacts, created_at=_now(),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@router.get("/modeling/submissions/{submission_id}/experiments",
            response_model=List[MevExperimentRead])
def list_experiments(submission_id: str, db: Session = Depends(get_db)):
    _get_submission(db, submission_id)
    return db.query(MevExperiment).filter(
        MevExperiment.submission_id == submission_id).order_by(MevExperiment.created_at).all()


# ---------------------------------------------------------------------------
# Adapters
# ---------------------------------------------------------------------------

@router.post("/modeling/submissions/{submission_id}/adapter", response_model=MevAdapterRead)
def create_adapter(submission_id: str, body: MevAdapterCreate, db: Session = Depends(get_db)):
    _get_submission(db, submission_id)
    aid = body.id or uuid.uuid4().hex
    if db.query(MevAdapter).filter(MevAdapter.id == aid).first():
        raise HTTPException(status_code=400, detail="MevAdapter already exists")
    row = MevAdapter(
        id=aid, submission_id=submission_id, input_schema=body.input_schema,
        output_schema=body.output_schema, created_at=_now(),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@router.get("/modeling/submissions/{submission_id}/adapter", response_model=MevAdapterRead)
def get_adapter(submission_id: str, db: Session = Depends(get_db)):
    _get_submission(db, submission_id)
    row = db.query(MevAdapter).filter(MevAdapter.submission_id == submission_id).order_by(
        MevAdapter.created_at.desc()).first()
    if not row:
        raise HTTPException(status_code=404, detail="MevAdapter not found for submission")
    return row


def _type_ok(value: Any, type_name: str) -> bool:
    tn = (type_name or "").lower()
    if tn in ("string", "str", "text"):
        return isinstance(value, str)
    if tn in ("integer", "int"):
        return isinstance(value, int) and not isinstance(value, bool)
    if tn in ("double", "float", "number", "numeric"):
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if tn in ("boolean", "bool"):
        return isinstance(value, bool)
    # unknown type: accept (permissive) but value must be present
    return True


@router.post("/modeling/submissions/{submission_id}/adapter/infer")
def adapter_infer(submission_id: str, body: MevInferRequest, db: Session = Depends(get_db)) -> Dict[str, Any]:
    _get_submission(db, submission_id)
    adapter = db.query(MevAdapter).filter(MevAdapter.submission_id == submission_id).order_by(
        MevAdapter.created_at.desc()).first()
    if not adapter:
        raise HTTPException(status_code=404, detail="MevAdapter not found for submission")
    input_schema = adapter.input_schema or {}
    missing = [k for k in input_schema if k not in body.inputs]
    if missing:
        raise HTTPException(status_code=422, detail={"missing_inputs": missing})
    type_errors = [k for k, t in input_schema.items() if not _type_ok(body.inputs[k], t)]
    if type_errors:
        raise HTTPException(status_code=422, detail={"type_errors": type_errors})
    # Deterministic output matching output_schema.
    output_schema = adapter.output_schema or {}
    outputs: Dict[str, Any] = {}
    for key, type_name in output_schema.items():
        tn = (type_name or "").lower()
        if tn in ("integer", "int"):
            outputs[key] = sum(int(v) for v in body.inputs.values() if isinstance(v, (int, float)) and not isinstance(v, bool))
        elif tn in ("double", "float", "number", "numeric"):
            nums = [float(v) for v in body.inputs.values() if isinstance(v, (int, float)) and not isinstance(v, bool)]
            outputs[key] = round(sum(nums) / len(nums), 6) if nums else 0.0
        elif tn in ("boolean", "bool"):
            outputs[key] = len(body.inputs) % 2 == 0
        else:
            outputs[key] = ":".join(str(body.inputs[k]) for k in sorted(body.inputs))
    return {"submission_id": submission_id, "outputs": outputs}


# ---------------------------------------------------------------------------
# Deployment configs (bound to a specific release)
# ---------------------------------------------------------------------------

@router.post("/modeling/deployment-configs", response_model=MevDeploymentConfigRead)
def create_deployment_config(body: MevDeploymentConfigCreate, db: Session = Depends(get_db)):
    if body.kind not in VALID_DEPLOY_KINDS:
        raise HTTPException(status_code=422, detail=f"kind must be one of {sorted(VALID_DEPLOY_KINDS)}")
    release = db.query(MevRelease).filter(MevRelease.id == body.release_id).first()
    if not release:
        raise HTTPException(status_code=404, detail=f"MevRelease '{body.release_id}' not found")
    cid = body.id or uuid.uuid4().hex
    if db.query(MevDeploymentConfig).filter(MevDeploymentConfig.id == cid).first():
        raise HTTPException(status_code=400, detail="MevDeploymentConfig already exists")
    if body.kind == "live" and body.replicas is None:
        raise HTTPException(status_code=422, detail="live deployment config requires replicas")
    row = MevDeploymentConfig(
        id=cid, deployment_id=body.deployment_id, release_id=body.release_id, kind=body.kind,
        spark_profile=body.spark_profile, replicas=body.replicas, cpu=body.cpu, gpu=body.gpu,
        created_at=_now(),
    )
    db.add(row)
    _audit(db, "modeling.deployment_config.created", "mev_deployment_config", cid,
           {"release_id": body.release_id, "kind": body.kind})
    db.commit()
    db.refresh(row)
    return row


@router.get("/modeling/deployment-configs", response_model=List[MevDeploymentConfigRead])
def list_deployment_configs(db: Session = Depends(get_db)):
    return db.query(MevDeploymentConfig).order_by(MevDeploymentConfig.created_at.desc()).all()


@router.post("/modeling/deployment-configs/{config_id}/query")
def query_deployment_config(config_id: str, body: MevInferRequest,
                            db: Session = Depends(get_db)) -> Dict[str, Any]:
    """
    Validate query inputs against the adapter schema of the submission bound via the config's
    release, then return deterministic outputs.
    """
    cfg = db.query(MevDeploymentConfig).filter(MevDeploymentConfig.id == config_id).first()
    if not cfg:
        raise HTTPException(status_code=404, detail=f"MevDeploymentConfig '{config_id}' not found")
    release = db.query(MevRelease).filter(MevRelease.id == cfg.release_id).first()
    if not release:
        raise HTTPException(status_code=404, detail="Bound MevRelease not found")
    adapter = db.query(MevAdapter).filter(
        MevAdapter.submission_id == release.submission_id).order_by(
        MevAdapter.created_at.desc()).first()
    if not adapter:
        raise HTTPException(status_code=404, detail="MevAdapter not found for released submission")
    input_schema = adapter.input_schema or {}
    missing = [k for k in input_schema if k not in body.inputs]
    if missing:
        raise HTTPException(status_code=422, detail={"missing_inputs": missing})
    type_errors = [k for k, t in input_schema.items() if not _type_ok(body.inputs[k], t)]
    if type_errors:
        raise HTTPException(status_code=422, detail={"type_errors": type_errors})
    return {
        "config_id": config_id,
        "release_id": cfg.release_id,
        "submission_id": release.submission_id,
        "kind": cfg.kind,
        "validated": True,
        "echo": body.inputs,
    }

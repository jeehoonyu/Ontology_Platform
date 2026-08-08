"""
Foundry Model Studio — modeling objectives, training submissions, and live/batch deployments.
"""

from typing import Optional, List, Any, Dict
import time
import uuid
import hashlib
import math

from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy import String, Integer, JSON, Boolean, Float, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, Session, relationship
from pydantic import BaseModel, ConfigDict, Field

from .database import Base, get_db
from . import models, models_action, tenancy
from .production_auth import Principal, require_permission

# ---------------------------------------------------------------------------
# SQLAlchemy ORM models
# ---------------------------------------------------------------------------

class ModelingObjective(Base):
    """Defines the ML problem: what to predict and from which features."""
    __tablename__ = "modeling_objectives"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    project_id: Mapped[str] = mapped_column(String, default="default", index=True)
    display_name: Mapped[str] = mapped_column(String)
    description: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    problem_type: Mapped[str] = mapped_column(String)  # classification | regression
    target_field: Mapped[str] = mapped_column(String)
    feature_fields: Mapped[list] = mapped_column(JSON, default=list)
    input_asset_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    created_at: Mapped[int] = mapped_column(Integer)
    updated_at: Mapped[int] = mapped_column(Integer)


class ModelSubmission(Base):
    """A trained model artifact associated with an objective."""
    __tablename__ = "model_submissions"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    project_id: Mapped[str] = mapped_column(String, default="default", index=True)
    objective_id: Mapped[str] = mapped_column(String, ForeignKey("modeling_objectives.id"), index=True)
    algorithm: Mapped[str] = mapped_column(String)
    metrics: Mapped[dict] = mapped_column(JSON, default=dict)
    released: Mapped[bool] = mapped_column(Boolean, default=False)
    # Status lifecycle for a training submission: pending | running | success.
    status: Mapped[str] = mapped_column(String, default="success")
    # Optional training configuration captured at submission time.
    trainer_type: Mapped[Optional[str]] = mapped_column(String, nullable=True)  # forecasting | regression | classification
    training_dataset_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    target_column: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    eval_metric: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    quality_preset: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    created_at: Mapped[int] = mapped_column(Integer)

    objective = relationship("ModelingObjective")


class ModelDeployment(Base):
    """A running deployment backed by a released submission."""
    __tablename__ = "model_deployments"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    project_id: Mapped[str] = mapped_column(String, default="default", index=True)
    objective_id: Mapped[str] = mapped_column(String, ForeignKey("modeling_objectives.id"), index=True)
    submission_id: Mapped[str] = mapped_column(String, ForeignKey("model_submissions.id"), index=True)
    mode: Mapped[str] = mapped_column(String, default="live")  # live | batch
    status: Mapped[str] = mapped_column(String, default="running")
    created_at: Mapped[int] = mapped_column(Integer)

    objective = relationship("ModelingObjective")
    submission = relationship("ModelSubmission")


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------

class ModelingObjectiveCreate(BaseModel):
    id: Optional[str] = None
    project_id: str = "default"
    display_name: str
    description: Optional[str] = None
    problem_type: str = Field(..., pattern="^(classification|regression)$")
    target_field: str
    feature_fields: List[str] = Field(default_factory=list)
    input_asset_id: Optional[str] = None


class ModelingObjectiveRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    project_id: str
    display_name: str
    description: Optional[str]
    problem_type: str
    target_field: str
    feature_fields: List[Any]
    input_asset_id: Optional[str]
    created_at: int
    updated_at: int


class ModelSubmissionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    project_id: str
    objective_id: str
    algorithm: str
    metrics: Dict[str, Any]
    released: bool
    status: str
    trainer_type: Optional[str] = None
    training_dataset_id: Optional[str] = None
    target_column: Optional[str] = None
    eval_metric: Optional[str] = None
    quality_preset: Optional[str] = None
    created_at: int


# Valid AutoML trainer types accepted by the enriched /train endpoint.
VALID_TRAINER_TYPES = {"forecasting", "regression", "classification"}


class TrainRequest(BaseModel):
    # ``algorithm`` is retained for backward compatibility. When omitted the
    # trainer_type (or the objective's problem_type) seeds a default algorithm.
    algorithm: Optional[str] = None
    trainer_type: Optional[str] = Field(
        default=None,
        description="AutoML trainer family: forecasting | regression | classification",
    )
    training_dataset_id: Optional[str] = None
    target_column: Optional[str] = None
    eval_metric: Optional[str] = None
    quality_preset: Optional[str] = None


class ReleaseRequest(BaseModel):
    submission_id: str


class ModelDeploymentCreate(BaseModel):
    id: Optional[str] = None
    objective_id: str
    submission_id: str
    mode: str = Field(default="live", pattern="^(live|batch)$")


class ModelDeploymentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    project_id: str
    objective_id: str
    submission_id: str
    mode: str
    status: str
    created_at: int


class InferRequest(BaseModel):
    records: List[Dict[str, Any]]


class InferResponse(BaseModel):
    predictions: List[Any]


# Default Multi-I/O envelope key names (used when the model adapter signature
# does not pin specific input/output names).
DEFAULT_INPUT_NAME = "inference_data"
DEFAULT_OUTPUT_NAME = "output_data"
PREDICTION_FIELD = "prediction"


# ---------------------------------------------------------------------------
# Deterministic pseudo-metric helpers
# ---------------------------------------------------------------------------

def _pseudo_metric(seed: str, lo: float = 0.70, hi: float = 0.99) -> float:
    """Map an arbitrary string seed into [lo, hi] deterministically."""
    digest = int(hashlib.sha256(seed.encode()).hexdigest(), 16)
    # normalise to [0, 1) then scale
    norm = (digest % 10_000) / 10_000.0
    return round(lo + norm * (hi - lo), 4)


def _build_metrics(objective_id: str, algorithm: str, problem_type: str) -> Dict[str, float]:
    seed_base = f"{objective_id}:{algorithm}"
    accuracy = _pseudo_metric(seed_base + ":accuracy")
    auc = _pseudo_metric(seed_base + ":auc")
    if problem_type == "regression":
        return {
            "mae": round((1.0 - accuracy) * 10, 4),
            "rmse": round((1.0 - auc) * 15, 4),
            "r2": accuracy,
        }
    return {"accuracy": accuracy, "auc": auc, "f1": _pseudo_metric(seed_base + ":f1")}


# ---------------------------------------------------------------------------
# Deterministic local inference helpers
# ---------------------------------------------------------------------------

def _infer_regression(record: Dict[str, Any], feature_fields: List[str]) -> float:
    values = []
    for f in feature_fields:
        v = record.get(f, 0)
        try:
            values.append(float(v))
        except (TypeError, ValueError):
            values.append(0.0)
    return round(sum(values) / max(len(values), 1), 6)


_CLASSIFICATION_LABELS = ["class_A", "class_B", "class_C", "class_D"]


def _infer_classification(
    record: Dict[str, Any], feature_fields: List[str], objective_id: str
) -> str:
    sig = objective_id + ":" + ":".join(str(record.get(f, "")) for f in feature_fields)
    idx = int(hashlib.md5(sig.encode()).hexdigest(), 16) % len(_CLASSIFICATION_LABELS)
    return _CLASSIFICATION_LABELS[idx]


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

router = APIRouter(tags=["modeling"])


def _now() -> int:
    return int(time.time())


def _audit(
    db: Session,
    event_type: str,
    subject_type: str,
    subject_id: str,
    payload: Dict[str, Any],
    actor: str = "system",
) -> None:
    db.add(
        models_action.AuditLog(
            id=uuid.uuid4().hex,
            actor=actor,
            event_type=event_type,
            subject_type=subject_type,
            subject_id=subject_id,
            payload=payload,
        )
    )


def _asset_project_id(db: Session, asset_id: str) -> str:
    asset = db.get(models.DataAsset, asset_id)
    if not asset:
        raise HTTPException(status_code=404, detail=f"DataAsset '{asset_id}' not found")
    return str((asset.asset_schema or {}).get("project_id") or "default")


def _assert_asset_project(db: Session, asset_id: Optional[str], project_id: str) -> None:
    if not asset_id:
        return
    asset = db.get(models.DataAsset, asset_id)
    # Modeling accepts external dataset references; enforce ownership whenever
    # the identifier resolves to a locally governed DataAsset.
    if asset and str((asset.asset_schema or {}).get("project_id") or "default") != project_id:
        raise HTTPException(status_code=403, detail="Modeling dataset belongs to another project")


def _objective_for(db: Session, objective_id: str, principal: Principal, permission: str) -> ModelingObjective:
    objective = db.get(ModelingObjective, objective_id)
    if not objective:
        raise HTTPException(status_code=404, detail=f"ModelingObjective '{objective_id}' not found")
    tenancy.assert_project_permission(db, principal, objective.project_id, permission)
    _assert_asset_project(db, objective.input_asset_id, objective.project_id)
    return objective


def _submission_for(db: Session, submission_id: str, principal: Principal, permission: str) -> ModelSubmission:
    submission = db.get(ModelSubmission, submission_id)
    if not submission:
        raise HTTPException(status_code=404, detail=f"ModelSubmission '{submission_id}' not found")
    tenancy.assert_project_permission(db, principal, submission.project_id, permission)
    objective = db.get(ModelingObjective, submission.objective_id)
    if not objective or objective.project_id != submission.project_id:
        raise HTTPException(status_code=409, detail="Model submission has an invalid project or objective reference")
    return submission


def _deployment_for(db: Session, deployment_id: str, principal: Principal, permission: str) -> ModelDeployment:
    deployment = db.get(ModelDeployment, deployment_id)
    if not deployment:
        raise HTTPException(status_code=404, detail=f"ModelDeployment '{deployment_id}' not found")
    tenancy.assert_project_permission(db, principal, deployment.project_id, permission)
    objective = db.get(ModelingObjective, deployment.objective_id)
    submission = db.get(ModelSubmission, deployment.submission_id)
    if not objective or not submission or objective.project_id != deployment.project_id or submission.project_id != deployment.project_id:
        raise HTTPException(status_code=409, detail="Model deployment has an invalid cross-project reference")
    return deployment


# --- Modeling Objectives ---

@router.post("/modeling/objectives", response_model=ModelingObjectiveRead)
def create_objective(body: ModelingObjectiveCreate, principal: Principal = Depends(require_permission("edit")), db: Session = Depends(get_db)):
    tenancy.assert_project_permission(db, principal, body.project_id, "edit")
    _assert_asset_project(db, body.input_asset_id, body.project_id)
    obj_id = body.id or uuid.uuid4().hex
    existing = db.query(ModelingObjective).filter(ModelingObjective.id == obj_id).first()
    if existing:
        raise HTTPException(status_code=400, detail="ModelingObjective already exists")
    now = _now()
    row = ModelingObjective(
        id=obj_id,
        project_id=body.project_id,
        display_name=body.display_name,
        description=body.description,
        problem_type=body.problem_type,
        target_field=body.target_field,
        feature_fields=body.feature_fields,
        input_asset_id=body.input_asset_id,
        created_at=now,
        updated_at=now,
    )
    db.add(row)
    _audit(db, "modeling.objective.created", "modeling_objective", obj_id, body.model_dump(), actor=principal.id)
    db.commit()
    db.refresh(row)
    return row


@router.get("/modeling/objectives", response_model=List[ModelingObjectiveRead])
def list_objectives(project_id: Optional[str] = None, principal: Principal = Depends(require_permission("view")), db: Session = Depends(get_db)):
    query = db.query(ModelingObjective)
    if project_id:
        tenancy.assert_project_permission(db, principal, project_id, "view")
        query = query.filter(ModelingObjective.project_id == project_id)
    else:
        accessible = tenancy.accessible_project_ids(db, principal, "view")
        if accessible is not None:
            query = query.filter(ModelingObjective.project_id.in_(accessible)) if accessible else query.filter(ModelingObjective.id == "__none__")
    return query.order_by(ModelingObjective.created_at.desc()).all()


@router.get("/modeling/objectives/{objective_id}", response_model=ModelingObjectiveRead)
def get_objective(objective_id: str, principal: Principal = Depends(require_permission("view")), db: Session = Depends(get_db)):
    return _objective_for(db, objective_id, principal, "view")


# --- Training ---

@router.post("/modeling/objectives/{objective_id}/train", response_model=ModelSubmissionRead)
def train_model(objective_id: str, body: TrainRequest, principal: Principal = Depends(require_permission("execute")), db: Session = Depends(get_db)):
    objective = _objective_for(db, objective_id, principal, "execute")
    _assert_asset_project(db, body.training_dataset_id, objective.project_id)

    # Validate the optional AutoML trainer family.
    trainer_type = body.trainer_type
    if trainer_type is not None and trainer_type not in VALID_TRAINER_TYPES:
        raise HTTPException(
            status_code=422,
            detail=f"trainer_type must be one of {sorted(VALID_TRAINER_TYPES)}",
        )

    # ``algorithm`` stays the canonical identifier of the produced artifact.
    # Fall back to the trainer_type, then to the objective's problem_type so the
    # legacy ``{"algorithm": ...}`` contract and the new enriched contract both work.
    algorithm = body.algorithm or trainer_type or objective.problem_type

    # The pseudo-metric helper buckets by classification vs regression. Forecasting
    # is treated as a regression-style metric family for deterministic scoring.
    metric_family = "regression" if (trainer_type in ("regression", "forecasting")) else (
        "classification" if trainer_type == "classification" else objective.problem_type
    )
    metrics = _build_metrics(objective_id, algorithm, metric_family)

    submission_id = uuid.uuid4().hex
    row = ModelSubmission(
        id=submission_id,
        project_id=objective.project_id,
        objective_id=objective_id,
        algorithm=algorithm,
        metrics=metrics,
        released=False,
        # A synchronous train in this reference implementation completes
        # immediately; we still expose the documented lifecycle field.
        status="success",
        trainer_type=trainer_type,
        training_dataset_id=body.training_dataset_id,
        target_column=body.target_column,
        eval_metric=body.eval_metric,
        quality_preset=body.quality_preset,
        created_at=_now(),
    )
    db.add(row)
    _audit(
        db,
        "modeling.submission.created",
        "model_submission",
        submission_id,
        {
            "project_id": objective.project_id,
            "objective_id": objective_id,
            "algorithm": algorithm,
            "trainer_type": trainer_type,
            "training_dataset_id": body.training_dataset_id,
            "target_column": body.target_column,
            "eval_metric": body.eval_metric,
            "quality_preset": body.quality_preset,
            "status": "success",
            "metrics": metrics,
        }, actor=principal.id,
    )
    db.commit()
    db.refresh(row)
    return row


@router.get("/modeling/objectives/{objective_id}/submissions", response_model=List[ModelSubmissionRead])
def list_objective_submissions(objective_id: str, principal: Principal = Depends(require_permission("view")), db: Session = Depends(get_db)):
    objective = _objective_for(db, objective_id, principal, "view")
    return db.query(ModelSubmission).filter(
        ModelSubmission.objective_id == objective_id,
        ModelSubmission.project_id == objective.project_id,
    ).order_by(ModelSubmission.created_at.desc()).all()


@router.get("/modeling/submissions/{submission_id}", response_model=ModelSubmissionRead)
def get_model_submission(submission_id: str, principal: Principal = Depends(require_permission("view")), db: Session = Depends(get_db)):
    return _submission_for(db, submission_id, principal, "view")


# --- Release ---

@router.post("/modeling/objectives/{objective_id}/release", response_model=ModelSubmissionRead)
def release_model(objective_id: str, body: ReleaseRequest, principal: Principal = Depends(require_permission("publish")), db: Session = Depends(get_db)):
    objective = _objective_for(db, objective_id, principal, "publish")

    target = db.query(ModelSubmission).filter(
        ModelSubmission.id == body.submission_id,
        ModelSubmission.objective_id == objective_id,
    ).first()
    if not target:
        raise HTTPException(status_code=404, detail=f"ModelSubmission '{body.submission_id}' not found for objective")
    if target.project_id != objective.project_id:
        raise HTTPException(status_code=409, detail="Model submission belongs to another project")

    # Mark all others as not released, then mark target
    db.query(ModelSubmission).filter(
        ModelSubmission.objective_id == objective_id,
        ModelSubmission.project_id == objective.project_id,
        ModelSubmission.released == True,  # noqa: E712
    ).update({"released": False})
    target.released = True

    _audit(
        db,
        "modeling.submission.released",
        "model_submission",
        body.submission_id,
        {"project_id": objective.project_id, "objective_id": objective_id}, actor=principal.id,
    )
    db.commit()
    db.refresh(target)
    return target


# --- Deployments ---

@router.post("/modeling/deployments", response_model=ModelDeploymentRead)
def create_deployment(body: ModelDeploymentCreate, principal: Principal = Depends(require_permission("deploy")), db: Session = Depends(get_db)):
    dep_id = body.id or uuid.uuid4().hex

    objective = _objective_for(db, body.objective_id, principal, "deploy")

    submission = db.query(ModelSubmission).filter(
        ModelSubmission.id == body.submission_id,
        ModelSubmission.objective_id == body.objective_id,
    ).first()
    if not submission:
        raise HTTPException(status_code=404, detail=f"ModelSubmission '{body.submission_id}' not found")
    if submission.project_id != objective.project_id:
        raise HTTPException(status_code=409, detail="Model submission belongs to another project")
    if not submission.released:
        raise HTTPException(status_code=400, detail="ModelSubmission is not released; release it before deploying")

    row = ModelDeployment(
        id=dep_id,
        project_id=objective.project_id,
        objective_id=body.objective_id,
        submission_id=body.submission_id,
        mode=body.mode,
        status="running",
        created_at=_now(),
    )
    db.add(row)
    _audit(
        db,
        "modeling.deployment.created",
        "model_deployment",
        dep_id,
        {"project_id": objective.project_id, "objective_id": body.objective_id, "submission_id": body.submission_id, "mode": body.mode}, actor=principal.id,
    )
    db.commit()
    db.refresh(row)
    return row


@router.get("/modeling/deployments", response_model=List[ModelDeploymentRead])
def list_deployments(project_id: Optional[str] = None, principal: Principal = Depends(require_permission("view")), db: Session = Depends(get_db)):
    query = db.query(ModelDeployment)
    if project_id:
        tenancy.assert_project_permission(db, principal, project_id, "view")
        query = query.filter(ModelDeployment.project_id == project_id)
    else:
        accessible = tenancy.accessible_project_ids(db, principal, "view")
        if accessible is not None:
            query = query.filter(ModelDeployment.project_id.in_(accessible)) if accessible else query.filter(ModelDeployment.id == "__none__")
    return query.order_by(ModelDeployment.created_at.desc()).all()


# --- Inference ---

def _predict_records(
    records: List[Dict[str, Any]],
    objective: "ModelingObjective",
) -> List[Any]:
    """Run deterministic inference over a list of feature records."""
    feature_fields: List[str] = list(objective.feature_fields or [])
    predictions: List[Any] = []
    for record in records:
        if not isinstance(record, dict):
            record = {}
        if objective.problem_type == "regression":
            predictions.append(_infer_regression(record, feature_fields))
        else:
            predictions.append(_infer_classification(record, feature_fields, objective.id))
    return predictions


def _record_modelops_prediction_log(
    db: Session,
    *,
    deployment: "ModelDeployment",
    request_shape: str,
    input_count: int,
    response: Dict[str, Any],
) -> None:
    try:
        from . import modelops
        modelops.record_prediction_log(
            db,
            deployment=deployment,
            request_shape=request_shape,
            input_count=input_count,
            response=response,
        )
        db.commit()
    except Exception:
        db.rollback()


@router.post("/modeling/deployments/{deployment_id}/infer")
def infer(
    deployment_id: str,
    body: Dict[str, Any] = Body(...),
    principal: Principal = Depends(require_permission("execute")),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """Query a live deployment.

    Supports two request shapes:

    * **Multi-I/O REST envelope** (documented current standard) — a JSON object
      whose top-level keys are input names, each mapping to a list of records:
      ``{"inference_data": [{"ts": 5}, ...]}``. The response mirrors this shape
      with output names as top-level keys:
      ``{"output_data": [{"prediction": ...}, ...]}``.
    * **Legacy shape** — ``{"records": [{...}, ...]}`` returns the original
      ``{"predictions": [...]}`` response for backward compatibility.
    """
    deployment = _deployment_for(db, deployment_id, principal, "execute")
    if deployment.status != "running":
        raise HTTPException(status_code=400, detail="ModelDeployment is not in running status")

    objective = db.query(ModelingObjective).filter(
        ModelingObjective.id == deployment.objective_id
    ).first()
    if not objective:
        raise HTTPException(status_code=404, detail="Parent ModelingObjective not found")

    if not isinstance(body, dict):
        raise HTTPException(status_code=422, detail="Request body must be a JSON object")

    # --- Backward-compatible legacy shape: {"records": [...]} ---
    if "records" in body:
        records = body.get("records")
        if not isinstance(records, list):
            raise HTTPException(status_code=422, detail="'records' must be a list of records")
        predictions = _predict_records(records, objective)
        response = {"predictions": predictions}
        _record_modelops_prediction_log(
            db,
            deployment=deployment,
            request_shape="legacy_records",
            input_count=len(records),
            response=response,
        )
        return response

    # --- Multi-I/O REST envelope: {input_name: [{field: value}, ...], ...} ---
    # Each top-level key is an input name mapping to a list of records. The
    # response returns one output array per input, keyed by "<input>_out"
    # (or the documented default output name for the single-input case).
    input_names = [k for k, v in body.items() if isinstance(v, list)]
    if not input_names:
        raise HTTPException(
            status_code=422,
            detail=(
                "Multi-I/O request must contain at least one input name mapping to a "
                "list of records, or use the legacy {'records': [...]} shape"
            ),
        )

    response: Dict[str, Any] = {}
    single_input = len(input_names) == 1
    for input_name in input_names:
        records = body[input_name]
        if not all(isinstance(r, dict) for r in records):
            raise HTTPException(
                status_code=422,
                detail=f"Input '{input_name}' must be a list of field:value objects",
            )
        predictions = _predict_records(records, objective)
        out_records = [{PREDICTION_FIELD: p} for p in predictions]
        # Canonical single-input/single-output case uses the documented default
        # output name; otherwise namespace each output by its source input.
        if single_input and input_name == DEFAULT_INPUT_NAME:
            output_name = DEFAULT_OUTPUT_NAME
        else:
            output_name = f"{input_name}_out"
        response[output_name] = out_records

    _record_modelops_prediction_log(
        db,
        deployment=deployment,
        request_shape="multi_io",
        input_count=sum(len(body[input_name]) for input_name in input_names),
        response=response,
    )
    return response

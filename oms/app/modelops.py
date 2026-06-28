"""
Local deterministic ModelOps monitoring layer.

This module connects the existing Modeling lifecycle to operational monitoring:
prediction logs, drift checks, quality checks, and a compact summary API.
"""
from __future__ import annotations

import math
import time
import uuid
from collections import Counter
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import Boolean, Integer, JSON, String
from sqlalchemy.orm import Mapped, Session, mapped_column

from . import models, models_action
from .database import Base, get_db
from .modeling import ModelDeployment, ModelingObjective, ModelSubmission, _predict_records

router = APIRouter(tags=["modelops"])


def _now() -> int:
    return int(time.time())


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


class ModelMonitor(Base):
    __tablename__ = "model_monitors"

    id: Mapped[str] = mapped_column(String, primary_key=True, index=True)
    display_name: Mapped[str] = mapped_column(String)
    description: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    objective_id: Mapped[str] = mapped_column(String, index=True)
    deployment_id: Mapped[Optional[str]] = mapped_column(String, index=True, nullable=True)
    baseline_asset_id: Mapped[str] = mapped_column(String, index=True)
    feature_fields: Mapped[list] = mapped_column(JSON, default=list)
    prediction_field: Mapped[str] = mapped_column(String, default="prediction")
    target_field: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    thresholds: Mapped[dict] = mapped_column(JSON, default=dict)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[int] = mapped_column(Integer)
    updated_at: Mapped[int] = mapped_column(Integer)


class ModelMonitorRun(Base):
    __tablename__ = "model_monitor_runs"

    id: Mapped[str] = mapped_column(String, primary_key=True, index=True)
    monitor_id: Mapped[str] = mapped_column(String, index=True)
    objective_id: Mapped[str] = mapped_column(String, index=True)
    deployment_id: Mapped[Optional[str]] = mapped_column(String, index=True, nullable=True)
    baseline_asset_id: Mapped[str] = mapped_column(String, index=True)
    current_asset_id: Mapped[str] = mapped_column(String, index=True)
    baseline_profile: Mapped[dict] = mapped_column(JSON, default=dict)
    current_profile: Mapped[dict] = mapped_column(JSON, default=dict)
    drift_metrics: Mapped[dict] = mapped_column(JSON, default=dict)
    quality_metrics: Mapped[dict] = mapped_column(JSON, default=dict)
    alerts: Mapped[list] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String, default="PASS")
    created_at: Mapped[int] = mapped_column(Integer)


class ModelPredictionLog(Base):
    __tablename__ = "model_prediction_logs"

    id: Mapped[str] = mapped_column(String, primary_key=True, index=True)
    deployment_id: Mapped[str] = mapped_column(String, index=True)
    objective_id: Mapped[str] = mapped_column(String, index=True)
    submission_id: Mapped[str] = mapped_column(String, index=True)
    request_shape: Mapped[str] = mapped_column(String)
    input_count: Mapped[int] = mapped_column(Integer, default=0)
    output_count: Mapped[int] = mapped_column(Integer, default=0)
    prediction_summary: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[int] = mapped_column(Integer)


class ModelMonitorCreate(BaseModel):
    id: Optional[str] = None
    display_name: str
    description: Optional[str] = None
    objective_id: str
    deployment_id: Optional[str] = None
    baseline_asset_id: str
    feature_fields: List[str] = Field(default_factory=list)
    prediction_field: str = "prediction"
    target_field: Optional[str] = None
    thresholds: Dict[str, Any] = Field(default_factory=dict)
    enabled: bool = True


class ModelMonitorPatch(BaseModel):
    display_name: Optional[str] = None
    description: Optional[str] = None
    deployment_id: Optional[str] = None
    baseline_asset_id: Optional[str] = None
    feature_fields: Optional[List[str]] = None
    prediction_field: Optional[str] = None
    target_field: Optional[str] = None
    thresholds: Optional[Dict[str, Any]] = None
    enabled: Optional[bool] = None


class ModelMonitorRunRequest(BaseModel):
    current_asset_id: str
    actual_field: Optional[str] = None


def _audit(db: Session, event_type: str, subject_type: str, subject_id: str, payload: Dict[str, Any]) -> None:
    db.add(models_action.AuditLog(
        id=uuid.uuid4().hex,
        actor="modelops",
        event_type=event_type,
        subject_type=subject_type,
        subject_id=subject_id,
        payload=payload,
    ))


def _monitor_dict(row: ModelMonitor) -> Dict[str, Any]:
    return {
        "id": row.id,
        "display_name": row.display_name,
        "description": row.description,
        "objective_id": row.objective_id,
        "deployment_id": row.deployment_id,
        "baseline_asset_id": row.baseline_asset_id,
        "feature_fields": row.feature_fields or [],
        "prediction_field": row.prediction_field,
        "target_field": row.target_field,
        "thresholds": row.thresholds or {},
        "enabled": row.enabled,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


def _run_dict(row: ModelMonitorRun) -> Dict[str, Any]:
    return {
        "id": row.id,
        "monitor_id": row.monitor_id,
        "objective_id": row.objective_id,
        "deployment_id": row.deployment_id,
        "baseline_asset_id": row.baseline_asset_id,
        "current_asset_id": row.current_asset_id,
        "baseline_profile": row.baseline_profile or {},
        "current_profile": row.current_profile or {},
        "drift_metrics": row.drift_metrics or {},
        "quality_metrics": row.quality_metrics or {},
        "alerts": row.alerts or [],
        "status": row.status,
        "created_at": row.created_at,
    }


def _prediction_log_dict(row: ModelPredictionLog) -> Dict[str, Any]:
    return {
        "id": row.id,
        "deployment_id": row.deployment_id,
        "objective_id": row.objective_id,
        "submission_id": row.submission_id,
        "request_shape": row.request_shape,
        "input_count": row.input_count,
        "output_count": row.output_count,
        "prediction_summary": row.prediction_summary or {},
        "created_at": row.created_at,
    }


def _get_asset(db: Session, asset_id: str) -> models.DataAsset:
    asset = db.get(models.DataAsset, asset_id)
    if not asset:
        raise HTTPException(status_code=404, detail=f"DataAsset '{asset_id}' not found")
    return asset


def _get_objective(db: Session, objective_id: str) -> ModelingObjective:
    objective = db.get(ModelingObjective, objective_id)
    if not objective:
        raise HTTPException(status_code=404, detail=f"ModelingObjective '{objective_id}' not found")
    return objective


def _get_deployment(db: Session, deployment_id: str) -> ModelDeployment:
    deployment = db.get(ModelDeployment, deployment_id)
    if not deployment:
        raise HTTPException(status_code=404, detail=f"ModelDeployment '{deployment_id}' not found")
    return deployment


def _number(value: Any) -> Optional[float]:
    if isinstance(value, bool) or value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _is_numeric_field(records: List[Dict[str, Any]], field: str) -> bool:
    present = [row.get(field) for row in records if isinstance(row, dict) and row.get(field) is not None]
    if not present:
        return False
    numeric = [_number(value) for value in present]
    return sum(value is not None for value in numeric) >= max(1, int(len(present) * 0.7))


def _numeric_profile(records: List[Dict[str, Any]], field: str) -> Dict[str, Any]:
    total = len(records)
    values = [_number(row.get(field)) for row in records if isinstance(row, dict)]
    nums = [value for value in values if value is not None]
    missing = total - len(nums)
    if not nums:
        return {"type": "numeric", "count": 0, "missing_rate": 1.0, "mean": None, "stddev": None, "min": None, "max": None, "buckets": []}
    mean = sum(nums) / len(nums)
    variance = sum((value - mean) ** 2 for value in nums) / len(nums)
    minimum = min(nums)
    maximum = max(nums)
    bucket_count = 5
    if minimum == maximum:
        buckets = [{"label": str(round(minimum, 6)), "count": len(nums), "frequency": 1.0}]
    else:
        width = (maximum - minimum) / bucket_count
        counts = [0] * bucket_count
        for value in nums:
            idx = min(bucket_count - 1, int((value - minimum) / width))
            counts[idx] += 1
        buckets = [
            {
                "label": f"{round(minimum + width * idx, 6)}-{round(minimum + width * (idx + 1), 6)}",
                "count": count,
                "frequency": round(count / len(nums), 6),
            }
            for idx, count in enumerate(counts)
        ]
    return {
        "type": "numeric",
        "count": len(nums),
        "missing_rate": round(missing / total, 6) if total else 1.0,
        "mean": round(mean, 6),
        "stddev": round(math.sqrt(variance), 6),
        "min": round(minimum, 6),
        "max": round(maximum, 6),
        "buckets": buckets,
    }


def _categorical_profile(records: List[Dict[str, Any]], field: str) -> Dict[str, Any]:
    total = len(records)
    values = [row.get(field) for row in records if isinstance(row, dict)]
    present = [str(value) for value in values if value is not None and value != ""]
    missing = total - len(present)
    counts = Counter(present)
    top_values = [
        {"value": value, "count": count, "frequency": round(count / len(present), 6) if present else 0}
        for value, count in counts.most_common(10)
    ]
    return {
        "type": "categorical",
        "count": len(present),
        "missing_rate": round(missing / total, 6) if total else 1.0,
        "unique_count": len(counts),
        "top_values": top_values,
    }


def _profile_records(records: List[Dict[str, Any]], fields: List[str]) -> Dict[str, Any]:
    profiles = {}
    for field in fields:
        profiles[field] = _numeric_profile(records, field) if _is_numeric_field(records, field) else _categorical_profile(records, field)
    return {"row_count": len(records), "fields": profiles}


def _thresholds(thresholds: Dict[str, Any]) -> Dict[str, float]:
    defaults = {
        "numeric_mean_shift_warn": 0.2,
        "numeric_mean_shift_fail": 0.5,
        "missing_rate_delta_warn": 0.1,
        "missing_rate_delta_fail": 0.25,
        "unseen_category_rate_warn": 0.1,
        "unseen_category_rate_fail": 0.25,
        "frequency_shift_warn": 0.2,
        "frequency_shift_fail": 0.5,
    }
    merged = {**defaults, **(thresholds or {})}
    return {key: float(value) for key, value in merged.items() if isinstance(value, (int, float))}


def _status_for(value: float, warn: float, fail: float) -> str:
    if value >= fail:
        return "FAIL"
    if value >= warn:
        return "WARN"
    return "PASS"


def _combine_status(statuses: List[str]) -> str:
    if "FAIL" in statuses:
        return "FAIL"
    if "WARN" in statuses:
        return "WARN"
    return "PASS"


def _compare_profiles(baseline: Dict[str, Any], current: Dict[str, Any], thresholds: Dict[str, Any]) -> Tuple[Dict[str, Any], List[Dict[str, Any]], str]:
    limits = _thresholds(thresholds)
    metrics: Dict[str, Any] = {}
    alerts: List[Dict[str, Any]] = []
    statuses: List[str] = []
    baseline_fields = (baseline or {}).get("fields", {})
    current_fields = (current or {}).get("fields", {})
    for field, base_profile in baseline_fields.items():
        curr_profile = current_fields.get(field)
        if not curr_profile:
            continue
        field_statuses = []
        missing_delta = abs(float(curr_profile.get("missing_rate", 0)) - float(base_profile.get("missing_rate", 0)))
        missing_status = _status_for(missing_delta, limits["missing_rate_delta_warn"], limits["missing_rate_delta_fail"])
        field_statuses.append(missing_status)
        field_metric = {
            "type": base_profile.get("type"),
            "missing_rate_delta": round(missing_delta, 6),
        }
        if base_profile.get("type") == "numeric" and curr_profile.get("type") == "numeric":
            base_mean = base_profile.get("mean")
            curr_mean = curr_profile.get("mean")
            if base_mean is not None and curr_mean is not None:
                shift_abs = abs(float(curr_mean) - float(base_mean))
                shift_ratio = shift_abs / max(abs(float(base_mean)), 1.0)
            else:
                shift_abs = 0.0
                shift_ratio = 0.0
            mean_status = _status_for(shift_ratio, limits["numeric_mean_shift_warn"], limits["numeric_mean_shift_fail"])
            field_statuses.append(mean_status)
            field_metric.update({
                "mean_shift_abs": round(shift_abs, 6),
                "mean_shift_ratio": round(shift_ratio, 6),
            })
        else:
            base_freq = {item["value"]: item["frequency"] for item in base_profile.get("top_values", [])}
            curr_freq = {item["value"]: item["frequency"] for item in curr_profile.get("top_values", [])}
            curr_count = max(int(curr_profile.get("count") or 0), 1)
            unseen_count = sum(
                int(item["count"])
                for item in curr_profile.get("top_values", [])
                if item["value"] not in base_freq
            )
            unseen_rate = unseen_count / curr_count
            frequency_shift = max(
                [abs(curr_freq.get(value, 0) - base_freq.get(value, 0)) for value in set(base_freq) | set(curr_freq)] or [0.0]
            )
            unseen_status = _status_for(unseen_rate, limits["unseen_category_rate_warn"], limits["unseen_category_rate_fail"])
            freq_status = _status_for(frequency_shift, limits["frequency_shift_warn"], limits["frequency_shift_fail"])
            field_statuses.extend([unseen_status, freq_status])
            field_metric.update({
                "unseen_category_rate": round(unseen_rate, 6),
                "frequency_shift": round(frequency_shift, 6),
            })
        field_status = _combine_status(field_statuses)
        field_metric["status"] = field_status
        statuses.append(field_status)
        metrics[field] = field_metric
        if field_status != "PASS":
            alerts.append({
                "field": field,
                "status": field_status,
                "message": f"{field} drift status {field_status}",
                "metrics": field_metric,
            })
    return metrics, alerts, _combine_status(statuses)


def _regression_quality(predictions: List[float], actuals: List[float]) -> Dict[str, Any]:
    n = len(actuals)
    if not n:
        return {}
    abs_err = [abs(p - a) for p, a in zip(predictions, actuals)]
    sq_err = [(p - a) ** 2 for p, a in zip(predictions, actuals)]
    mean_actual = sum(actuals) / n
    ss_tot = sum((a - mean_actual) ** 2 for a in actuals)
    ss_res = sum(sq_err)
    return {
        "count": n,
        "mae": round(sum(abs_err) / n, 6),
        "rmse": round(math.sqrt(sum(sq_err) / n), 6),
        "r2": round(1.0 - (ss_res / ss_tot), 6) if ss_tot else 0.0,
    }


def _classification_quality(predictions: List[Any], actuals: List[Any]) -> Dict[str, Any]:
    n = len(actuals)
    if not n:
        return {}
    correct = sum(1 for p, a in zip(predictions, actuals) if str(p) == str(a))
    labels = sorted({str(item) for item in predictions + actuals})
    confusion = {label: {inner: 0 for inner in labels} for label in labels}
    for prediction, actual in zip(predictions, actuals):
        confusion[str(actual)][str(prediction)] += 1
    return {"count": n, "accuracy": round(correct / n, 6), "confusion_matrix": confusion}


def _compute_quality(objective: ModelingObjective, records: List[Dict[str, Any]], prediction_field: str, target_field: Optional[str]) -> Dict[str, Any]:
    if not target_field:
        return {"available": False, "reason": "no target field configured"}
    pairs = [
        (row.get(prediction_field), row.get(target_field))
        for row in records
        if isinstance(row, dict) and row.get(prediction_field) is not None and row.get(target_field) is not None
    ]
    if not pairs:
        return {"available": False, "reason": "no rows contain both prediction and target"}
    predictions = [item[0] for item in pairs]
    actuals = [item[1] for item in pairs]
    if objective.problem_type == "regression":
        return {"available": True, **_regression_quality([float(p) for p in predictions], [float(a) for a in actuals])}
    return {"available": True, **_classification_quality(predictions, actuals)}


def _prediction_summary(values: List[Any]) -> Dict[str, Any]:
    nums = [_number(value) for value in values]
    numeric = [value for value in nums if value is not None]
    if numeric and len(numeric) == len(values):
        return {
            "type": "numeric",
            "count": len(numeric),
            "mean": round(sum(numeric) / len(numeric), 6),
            "min": round(min(numeric), 6),
            "max": round(max(numeric), 6),
        }
    counts = Counter(str(value) for value in values)
    return {
        "type": "categorical",
        "count": len(values),
        "top_values": [{"value": value, "count": count} for value, count in counts.most_common(10)],
    }


def _extract_predictions(response: Dict[str, Any]) -> List[Any]:
    if "predictions" in response and isinstance(response["predictions"], list):
        return response["predictions"]
    predictions = []
    for value in response.values():
        if not isinstance(value, list):
            continue
        for row in value:
            if isinstance(row, dict) and "prediction" in row:
                predictions.append(row["prediction"])
    return predictions


def record_prediction_log(
    db: Session,
    *,
    deployment: ModelDeployment,
    request_shape: str,
    input_count: int,
    response: Dict[str, Any],
) -> Optional[ModelPredictionLog]:
    # Some standalone modeling tests include only the modeling router. Creating
    # the table lazily keeps prediction logging additive for those harnesses.
    ModelPredictionLog.__table__.create(bind=db.get_bind(), checkfirst=True)
    predictions = _extract_predictions(response)
    log = ModelPredictionLog(
        id=_new_id("pred_log"),
        deployment_id=deployment.id,
        objective_id=deployment.objective_id,
        submission_id=deployment.submission_id,
        request_shape=request_shape,
        input_count=input_count,
        output_count=len(predictions),
        prediction_summary=_prediction_summary(predictions),
        created_at=_now(),
    )
    db.add(log)
    try:
        from . import ops_control
        ops_control.record_ops_event(
            db,
            source="modelops",
            event_type="model.inference.logged",
            severity="info",
            title=f"Inference logged for deployment {deployment.id}",
            subject_type="model_deployment",
            subject_id=deployment.id,
            payload={"prediction_log_id": log.id, "input_count": input_count, "output_count": len(predictions)},
        )
    except Exception:
        pass
    return log


@router.get("/modelops/summary")
def modelops_summary(db: Session = Depends(get_db)):
    latest_runs = db.query(ModelMonitorRun).order_by(ModelMonitorRun.created_at.desc()).limit(20).all()
    status_counts = Counter(run.status for run in latest_runs)
    return {
        "objectives": db.query(ModelingObjective).count(),
        "submissions": db.query(ModelSubmission).count(),
        "deployments": db.query(ModelDeployment).count(),
        "monitors": db.query(ModelMonitor).count(),
        "prediction_logs": db.query(ModelPredictionLog).count(),
        "latest_monitor_status": dict(status_counts),
        "latest_runs": [_run_dict(run) for run in latest_runs[:5]],
    }


@router.post("/modelops/monitors")
def create_monitor(body: ModelMonitorCreate, db: Session = Depends(get_db)):
    _get_objective(db, body.objective_id)
    _get_asset(db, body.baseline_asset_id)
    if body.deployment_id:
        deployment = _get_deployment(db, body.deployment_id)
        if deployment.objective_id != body.objective_id:
            raise HTTPException(status_code=422, detail="deployment objective does not match monitor objective")
    monitor_id = body.id or _new_id("monitor")
    if db.get(ModelMonitor, monitor_id):
        raise HTTPException(status_code=400, detail="ModelMonitor already exists")
    now = _now()
    monitor = ModelMonitor(
        id=monitor_id,
        display_name=body.display_name,
        description=body.description,
        objective_id=body.objective_id,
        deployment_id=body.deployment_id,
        baseline_asset_id=body.baseline_asset_id,
        feature_fields=body.feature_fields,
        prediction_field=body.prediction_field,
        target_field=body.target_field,
        thresholds=body.thresholds,
        enabled=body.enabled,
        created_at=now,
        updated_at=now,
    )
    db.add(monitor)
    _audit(db, "modelops.monitor.created", "model_monitor", monitor.id, _monitor_dict(monitor))
    db.commit()
    db.refresh(monitor)
    return _monitor_dict(monitor)


@router.get("/modelops/monitors")
def list_monitors(db: Session = Depends(get_db)):
    monitors = db.query(ModelMonitor).order_by(ModelMonitor.updated_at.desc()).all()
    latest_by_monitor = {
        run.monitor_id: run
        for run in db.query(ModelMonitorRun).order_by(ModelMonitorRun.created_at.asc()).all()
    }
    return [
        {**_monitor_dict(monitor), "latest_run": _run_dict(latest_by_monitor[monitor.id]) if monitor.id in latest_by_monitor else None}
        for monitor in monitors
    ]


@router.get("/modelops/monitors/{monitor_id}")
def get_monitor(monitor_id: str, db: Session = Depends(get_db)):
    monitor = db.get(ModelMonitor, monitor_id)
    if not monitor:
        raise HTTPException(status_code=404, detail=f"ModelMonitor '{monitor_id}' not found")
    latest = db.query(ModelMonitorRun).filter(ModelMonitorRun.monitor_id == monitor_id).order_by(ModelMonitorRun.created_at.desc()).first()
    return {**_monitor_dict(monitor), "latest_run": _run_dict(latest) if latest else None}


@router.patch("/modelops/monitors/{monitor_id}")
def patch_monitor(monitor_id: str, body: ModelMonitorPatch, db: Session = Depends(get_db)):
    monitor = db.get(ModelMonitor, monitor_id)
    if not monitor:
        raise HTTPException(status_code=404, detail=f"ModelMonitor '{monitor_id}' not found")
    patch = body.model_dump(exclude_unset=True)
    if "baseline_asset_id" in patch:
        _get_asset(db, patch["baseline_asset_id"])
    if "deployment_id" in patch and patch["deployment_id"]:
        _get_deployment(db, patch["deployment_id"])
    for key, value in patch.items():
        setattr(monitor, key, value)
    monitor.updated_at = _now()
    _audit(db, "modelops.monitor.updated", "model_monitor", monitor.id, patch)
    db.commit()
    db.refresh(monitor)
    return _monitor_dict(monitor)


@router.post("/modelops/monitors/{monitor_id}/run")
def run_monitor(monitor_id: str, body: ModelMonitorRunRequest, db: Session = Depends(get_db)):
    monitor = db.get(ModelMonitor, monitor_id)
    if not monitor:
        raise HTTPException(status_code=404, detail=f"ModelMonitor '{monitor_id}' not found")
    if not monitor.enabled:
        raise HTTPException(status_code=409, detail="ModelMonitor is disabled")
    objective = _get_objective(db, monitor.objective_id)
    baseline_asset = _get_asset(db, monitor.baseline_asset_id)
    current_asset = _get_asset(db, body.current_asset_id)
    fields = monitor.feature_fields or list(objective.feature_fields or [])
    if not fields:
        raise HTTPException(status_code=422, detail="monitor requires feature fields")
    baseline_records = [dict(row) for row in (baseline_asset.records or []) if isinstance(row, dict)]
    current_records = [dict(row) for row in (current_asset.records or []) if isinstance(row, dict)]

    if monitor.deployment_id and monitor.prediction_field:
        deployment = _get_deployment(db, monitor.deployment_id)
        predictions = _predict_records(current_records, objective)
        for row, prediction in zip(current_records, predictions):
            row[monitor.prediction_field] = prediction
    else:
        deployment = None

    baseline_profile = _profile_records(baseline_records, fields)
    current_profile = _profile_records(current_records, fields)
    drift_metrics, drift_alerts, drift_status = _compare_profiles(baseline_profile, current_profile, monitor.thresholds or {})
    quality_metrics = _compute_quality(
        objective,
        current_records,
        monitor.prediction_field,
        body.actual_field or monitor.target_field,
    )
    quality_alerts = []
    quality_status = "PASS"
    if quality_metrics.get("available") and objective.problem_type == "regression" and quality_metrics.get("r2", 1.0) < float((monitor.thresholds or {}).get("quality_r2_warn", 0.0)):
        quality_status = "WARN"
        quality_alerts.append({"status": "WARN", "message": "regression quality r2 below warning threshold", "metrics": quality_metrics})
    status = _combine_status([drift_status, quality_status])
    alerts = drift_alerts + quality_alerts
    run = ModelMonitorRun(
        id=_new_id("monitor_run"),
        monitor_id=monitor.id,
        objective_id=monitor.objective_id,
        deployment_id=monitor.deployment_id,
        baseline_asset_id=monitor.baseline_asset_id,
        current_asset_id=current_asset.id,
        baseline_profile=baseline_profile,
        current_profile=current_profile,
        drift_metrics=drift_metrics,
        quality_metrics=quality_metrics,
        alerts=alerts,
        status=status,
        created_at=_now(),
    )
    db.add(run)
    _audit(db, "modelops.monitor.run", "model_monitor", monitor.id, {"run_id": run.id, "status": status, "alerts": len(alerts)})
    try:
        from . import ops_control
        ops_control.record_ops_event(
            db,
            source="modelops",
            event_type="model_monitor.run",
            severity="high" if status == "FAIL" else "medium" if status == "WARN" else "info",
            title=f"Model monitor {monitor.display_name} {status}",
            subject_type="model_monitor",
            subject_id=monitor.id,
            payload={"run_id": run.id, "status": status, "alerts": alerts, "current_asset_id": current_asset.id},
        )
    except Exception:
        pass
    db.commit()
    db.refresh(run)
    return _run_dict(run)


@router.get("/modelops/monitors/{monitor_id}/runs")
def list_monitor_runs(monitor_id: str, db: Session = Depends(get_db)):
    if not db.get(ModelMonitor, monitor_id):
        raise HTTPException(status_code=404, detail=f"ModelMonitor '{monitor_id}' not found")
    return [
        _run_dict(run)
        for run in db.query(ModelMonitorRun).filter(ModelMonitorRun.monitor_id == monitor_id).order_by(ModelMonitorRun.created_at.desc()).all()
    ]


@router.get("/modelops/deployments/{deployment_id}/prediction-logs")
def list_prediction_logs(deployment_id: str, db: Session = Depends(get_db)):
    _get_deployment(db, deployment_id)
    return [
        _prediction_log_dict(log)
        for log in db.query(ModelPredictionLog).filter(ModelPredictionLog.deployment_id == deployment_id).order_by(ModelPredictionLog.created_at.desc()).all()
    ]

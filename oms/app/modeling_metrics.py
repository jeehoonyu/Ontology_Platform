"""
Modeling evaluation metrics (deep-fidelity pass 7, Modeling).

Deepens Modeling Objectives evaluation with the documented metric families computed
from predictions vs. actuals: regression (RMSE / MAE / R^2 / MAPE) and classification
(accuracy / precision / recall / F1 / confusion matrix). Additive; deterministic.
"""
import math
from typing import Optional, List, Any, Dict

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

router = APIRouter(tags=["modeling_metrics"])


class RegressionRequest(BaseModel):
    predictions: List[float]
    actuals: List[float]


class ClassificationRequest(BaseModel):
    predictions: List[Any]
    actuals: List[Any]
    positive_label: Optional[Any] = None


@router.post("/modeling/metrics/regression")
def regression_metrics(body: RegressionRequest):
    p, a = body.predictions, body.actuals
    if len(p) != len(a) or not p:
        raise HTTPException(status_code=422, detail="predictions and actuals must be non-empty and equal length")
    n = len(p)
    errs = [p[i] - a[i] for i in range(n)]
    mse = sum(e * e for e in errs) / n
    mae = sum(abs(e) for e in errs) / n
    mean_a = sum(a) / n
    ss_tot = sum((y - mean_a) ** 2 for y in a) or 1.0
    ss_res = sum(e * e for e in errs)
    r2 = 1 - ss_res / ss_tot
    mape_terms = [abs((a[i] - p[i]) / a[i]) for i in range(n) if a[i] != 0]
    mape = (sum(mape_terms) / len(mape_terms) * 100) if mape_terms else None
    return {"n": n, "rmse": round(math.sqrt(mse), 6), "mae": round(mae, 6),
            "r2": round(r2, 6), "mape_pct": round(mape, 4) if mape is not None else None}


@router.post("/modeling/metrics/classification")
def classification_metrics(body: ClassificationRequest):
    p, a = body.predictions, body.actuals
    if len(p) != len(a) or not p:
        raise HTTPException(status_code=422, detail="predictions and actuals must be non-empty and equal length")
    n = len(p)
    labels = sorted({str(x) for x in a} | {str(x) for x in p})
    # confusion matrix: actual -> predicted -> count
    cm: Dict[str, Dict[str, int]] = {al: {pl: 0 for pl in labels} for al in labels}
    for i in range(n):
        cm[str(a[i])][str(p[i])] += 1
    correct = sum(cm[l][l] for l in labels)
    accuracy = correct / n

    per_label = {}
    precisions, recalls, f1s = [], [], []
    for l in labels:
        tp = cm[l][l]
        fp = sum(cm[al][l] for al in labels) - tp
        fn = sum(cm[l][pl] for pl in labels) - tp
        prec = tp / (tp + fp) if (tp + fp) else 0.0
        rec = tp / (tp + fn) if (tp + fn) else 0.0
        f1 = 2 * prec * rec / (prec + rec) if (prec + rec) else 0.0
        per_label[l] = {"precision": round(prec, 6), "recall": round(rec, 6), "f1": round(f1, 6),
                        "support": sum(cm[l].values())}
        precisions.append(prec)
        recalls.append(rec)
        f1s.append(f1)

    result = {
        "n": n, "accuracy": round(accuracy, 6), "labels": labels,
        "confusion_matrix": cm, "per_label": per_label,
        "macro": {"precision": round(sum(precisions) / len(labels), 6),
                  "recall": round(sum(recalls) / len(labels), 6),
                  "f1": round(sum(f1s) / len(labels), 6)},
    }
    if body.positive_label is not None:
        result["binary_for"] = str(body.positive_label)
        result["binary"] = per_label.get(str(body.positive_label))
    return result

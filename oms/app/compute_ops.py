"""
Compute Modules — deterministic transform execution (deep-fidelity pass 10).
The base compute-module invoke echoes input. This deepens it: a module runs a
declared, deterministic transform spec (map / filter / aggregate) over input
records — a local stand-in for containerized compute. Additive; deterministic.
"""
from typing import Optional, List, Any, Dict

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel, Field

from .database import get_db
from . import aip_extras as _ce

router = APIRouter(tags=["compute_ops"])


class RunRequest(BaseModel):
    records: List[Dict[str, Any]] = Field(default_factory=list)
    spec: List[Dict[str, Any]] = Field(default_factory=list)   # ordered ops


def _apply(records: List[Dict[str, Any]], op: Dict[str, Any]) -> Any:
    kind = op.get("op")
    if kind == "filter":
        return [r for r in records if r.get(op.get("field")) == op.get("equals")]
    if kind == "map":
        tgt, src, fn = op.get("target"), op.get("source"), op.get("fn", "identity")
        out = []
        for r in records:
            v = r.get(src)
            if fn == "upper" and isinstance(v, str):
                v = v.upper()
            elif fn == "double" and isinstance(v, (int, float)):
                v = v * 2
            out.append({**r, tgt: v})
        return out
    if kind == "aggregate":
        field = op.get("field")
        nums = [r.get(field) for r in records if isinstance(r.get(field), (int, float)) and not isinstance(r.get(field), bool)]
        agg = op.get("agg", "count")
        return {"count": len(records), "sum": sum(nums), "avg": (sum(nums) / len(nums) if nums else 0),
                "min": (min(nums) if nums else None), "max": (max(nums) if nums else None)}.get(agg if agg != "count" else "count") \
            if agg != "count" else len(records)
    raise HTTPException(status_code=422, detail=f"Unknown compute op '{kind}'")


@router.post("/compute-modules/{module_id}/run")
def run_module(module_id: str, body: RunRequest, db: Session = Depends(get_db)):
    module = db.get(_ce.ComputeModule, module_id)
    if not module:
        raise HTTPException(status_code=404, detail=f"Compute module '{module_id}' not found")
    result: Any = list(body.records)
    trace = []
    for op in body.spec:
        before = len(result) if isinstance(result, list) else 1
        result = _apply(result if isinstance(result, list) else [], op)
        trace.append({"op": op.get("op"), "rows_in": before,
                      "rows_out": len(result) if isinstance(result, list) else 1})
    return {"module_id": module_id, "mode": module.mode, "result": result, "trace": trace}

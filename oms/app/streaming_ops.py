"""
Streaming — windowed aggregation, watermarks/late-data & stateful transforms
(deep-fidelity pass 9). Based on the documented streaming transforms (Aggregate over
window, Assign timestamps and watermarks, Keys/partitioning, Streaming stateful
transforms) at /docs/foundry/data-integration/streaming.

Operates over a stream's stored records. Additive; deterministic; local.
"""
import math
from typing import Optional, List, Any, Dict

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel, Field

from .database import get_db
from . import streaming as _streaming
from .production_auth import Principal, require_permission

router = APIRouter(tags=["streaming_ops"])


def _agg(values: List[float], op: str, n: int) -> Any:
    if op == "count":
        return n
    nums = [v for v in values if isinstance(v, (int, float)) and not isinstance(v, bool)]
    if op == "sum":
        return sum(nums)
    if op == "avg":
        return round(sum(nums) / len(nums), 6) if nums else 0
    if op == "min":
        return min(nums) if nums else None
    if op == "max":
        return max(nums) if nums else None
    return n


class WindowRequest(BaseModel):
    window_type: str = "tumbling"        # tumbling | sliding | session
    size: float = 60                     # window size (in ts units)
    slide: Optional[float] = None        # sliding step (defaults to size)
    gap: float = 60                      # session inactivity gap
    timestamp_field: Optional[str] = None  # payload field; defaults to record.ts
    key_field: Optional[str] = None      # partition key (defaults to single partition)
    value_field: Optional[str] = None
    agg: str = "count"
    watermark: Optional[float] = None    # drop events older than watermark - allowed_lateness
    allowed_lateness: float = 0


class StatefulRequest(BaseModel):
    key_field: Optional[str] = None
    value_field: str
    op: str = "sum"                      # running sum | count | min | max


def _events(db: Session, stream_id: str, timestamp_field, key_field, value_field, principal: Principal):
    _streaming._get_stream_or_404(stream_id, db, principal, "view")
    out = []
    for r in db.query(_streaming.StreamRecord).filter(_streaming.StreamRecord.stream_id == stream_id).all():
        payload = r.payload or {}
        ts = payload.get(timestamp_field) if (timestamp_field and timestamp_field in payload) else r.ts
        if not isinstance(ts, (int, float)):
            continue
        out.append({
            "ts": float(ts),
            "key": payload.get(key_field) if key_field else "_all",
            "value": payload.get(value_field) if value_field else None,
        })
    return out


@router.post("/streams/{stream_id}/window")
def window(stream_id: str, body: WindowRequest, principal: Principal = Depends(require_permission("view")), db: Session = Depends(get_db)):
    events = _events(db, stream_id, body.timestamp_field, body.key_field, body.value_field, principal)
    dropped = 0
    if body.watermark is not None:
        cutoff = body.watermark - body.allowed_lateness
        kept = [e for e in events if e["ts"] >= cutoff]
        dropped = len(events) - len(kept)
        events = kept
    if not events:
        return {"window_type": body.window_type, "windows": [], "late_dropped": dropped}

    origin = min(e["ts"] for e in events)
    max_ts = max(e["ts"] for e in events)
    windows: List[Dict[str, Any]] = []

    if body.window_type == "tumbling":
        buckets: Dict[Any, List[Dict[str, Any]]] = {}
        for e in events:
            w_start = origin + math.floor((e["ts"] - origin) / body.size) * body.size
            buckets.setdefault((w_start, e["key"]), []).append(e)
        for (w_start, key), evs in sorted(buckets.items(), key=lambda kv: (kv[0][0], str(kv[0][1]))):
            windows.append({"window_start": w_start, "window_end": w_start + body.size, "key": key,
                            "count": len(evs), "value": _agg([x["value"] for x in evs], body.agg, len(evs))})

    elif body.window_type == "sliding":
        slide = body.slide or body.size
        starts = []
        s = origin
        while s <= max_ts:
            starts.append(s)
            s += slide
        for s in starts:
            in_win: Dict[Any, List[Dict[str, Any]]] = {}
            for e in events:
                if s <= e["ts"] < s + body.size:
                    in_win.setdefault(e["key"], []).append(e)
            for key, evs in sorted(in_win.items(), key=lambda kv: str(kv[0])):
                windows.append({"window_start": s, "window_end": s + body.size, "key": key,
                                "count": len(evs), "value": _agg([x["value"] for x in evs], body.agg, len(evs))})

    elif body.window_type == "session":
        by_key: Dict[Any, List[Dict[str, Any]]] = {}
        for e in events:
            by_key.setdefault(e["key"], []).append(e)
        for key, evs in sorted(by_key.items(), key=lambda kv: str(kv[0])):
            evs.sort(key=lambda x: x["ts"])
            session: List[Dict[str, Any]] = []
            for e in evs:
                if session and e["ts"] - session[-1]["ts"] > body.gap:
                    windows.append({"window_start": session[0]["ts"], "window_end": session[-1]["ts"], "key": key,
                                    "count": len(session), "value": _agg([x["value"] for x in session], body.agg, len(session))})
                    session = []
                session.append(e)
            if session:
                windows.append({"window_start": session[0]["ts"], "window_end": session[-1]["ts"], "key": key,
                                "count": len(session), "value": _agg([x["value"] for x in session], body.agg, len(session))})
    else:
        raise HTTPException(status_code=422, detail=f"Unknown window_type '{body.window_type}'")

    return {"window_type": body.window_type, "size": body.size, "window_count": len(windows),
            "windows": windows, "late_dropped": dropped}


@router.post("/streams/{stream_id}/stateful")
def stateful_transform(stream_id: str, body: StatefulRequest, principal: Principal = Depends(require_permission("view")), db: Session = Depends(get_db)):
    """Per-key running aggregation over the stream in arrival (ts) order."""
    events = sorted(_events(db, stream_id, None, body.key_field, body.value_field, principal), key=lambda e: e["ts"])
    state: Dict[Any, Any] = {}
    timeline: List[Dict[str, Any]] = []
    for e in events:
        key, val = e["key"], e["value"]
        cur = state.get(key)
        if body.op == "count":
            cur = (cur or 0) + 1
        elif body.op == "sum":
            cur = (cur or 0) + (val if isinstance(val, (int, float)) else 0)
        elif body.op == "min":
            cur = val if cur is None else min(cur, val)
        elif body.op == "max":
            cur = val if cur is None else max(cur, val)
        state[key] = cur
        timeline.append({"ts": e["ts"], "key": key, "running_" + body.op: cur})
    return {"op": body.op, "final_state": state, "timeline": timeline}

"""
Quiver time-series analysis & point-and-click ML (deep-fidelity pass 7, Analytics).

Deepens Quiver beyond breadth with the documented time-series capabilities:
build a series from an object set, transform it (moving average, cumulative, delta,
normalize, stats), and run point-and-click forecasting (least-squares linear
regression). Additive; deterministic; local.

Pass 8 adds the Quiver TIME-SERIES LIBRARY of point-and-click building blocks:
resample (time bucketing), rolling window, interpolate (fill gaps), event
detection, and an object-set -> chart aggregation that groups ObjectInstances
into a deterministic chart series. All additive; deterministic; local.
"""
from typing import Optional, List, Any, Dict

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel, Field

from .database import get_db
from . import models, runtime

router = APIRouter(tags=["quiver_runtime"])


class SeriesPoint(BaseModel):
    t: Any
    v: float


class TransformRequest(BaseModel):
    series: List[Dict[str, Any]]
    op: str = "stats"          # moving_average | cumulative | delta | normalize | stats
    window: int = 3


class ForecastRequest(BaseModel):
    series: List[Dict[str, Any]]
    periods: int = 3


class FromObjectsRequest(BaseModel):
    object_type_id: str
    time_field: str
    value_field: str
    filters: Dict[str, Any] = Field(default_factory=dict)


class ResampleRequest(BaseModel):
    series: List[Dict[str, Any]]
    bucket_seconds: int = 60
    agg: str = "mean"          # mean | sum | min | max | last


class RollingRequest(BaseModel):
    series: List[Dict[str, Any]]
    window: int = 3
    agg: str = "mean"          # mean | median | stdev | min | max


class InterpolateRequest(BaseModel):
    series: List[Dict[str, Any]]
    method: str = "ffill"      # ffill | bfill | linear


class DetectEventsRequest(BaseModel):
    series: List[Dict[str, Any]]
    mode: str = "threshold_crossing"   # threshold_crossing | peak | trough
    threshold: Optional[float] = None


class AggregateToChartRequest(BaseModel):
    object_type_id: str
    group_by: str
    metric: Optional[str] = None
    agg: str = "count"         # count | sum | mean | min | max
    filters: Dict[str, Any] = Field(default_factory=dict)


def _values(series: List[Dict[str, Any]]) -> List[float]:
    return [float(p.get("v")) for p in series if isinstance(p.get("v"), (int, float)) and not isinstance(p.get("v"), bool)]


def _is_number(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _sort_series(series: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return sorted(series, key=lambda p: (p.get("t") is None, p.get("t")))


def _agg_scalar(vals: List[float], agg: str) -> float:
    """Deterministic scalar reductions shared by resample / rolling / chart."""
    if not vals:
        return 0.0
    if agg == "sum":
        return sum(vals)
    if agg == "min":
        return min(vals)
    if agg == "max":
        return max(vals)
    if agg == "last":
        return vals[-1]
    if agg == "mean":
        return sum(vals) / len(vals)
    if agg == "median":
        s = sorted(vals)
        n = len(s)
        mid = n // 2
        return s[mid] if n % 2 else (s[mid - 1] + s[mid]) / 2
    if agg == "stdev":
        if len(vals) < 2:
            return 0.0
        m = sum(vals) / len(vals)
        var = sum((x - m) ** 2 for x in vals) / (len(vals) - 1)
        return var ** 0.5
    raise HTTPException(status_code=422, detail=f"Unknown agg '{agg}'")


@router.post("/quiver/timeseries/from-objects")
def series_from_objects(body: FromObjectsRequest, db: Session = Depends(get_db)):
    rows, _ = runtime._logic_object_rows(db, body.object_type_id, body.filters, limit=10 ** 9)
    series = []
    for r in rows:
        props = r.properties or {}
        if body.time_field in props and body.value_field in props:
            series.append({"t": props[body.time_field], "v": props[body.value_field]})
    series.sort(key=lambda p: (p["t"] is None, p["t"]))
    return {"object_type_id": body.object_type_id, "count": len(series), "series": series}


@router.post("/quiver/timeseries/transform")
def transform(body: TransformRequest):
    series = sorted(body.series, key=lambda p: (p.get("t") is None, p.get("t")))
    vals = _values(series)
    op = body.op
    if op == "stats":
        if not vals:
            return {"op": op, "count": 0}
        return {"op": op, "count": len(vals), "min": min(vals), "max": max(vals),
                "avg": round(sum(vals) / len(vals), 6), "sum": round(sum(vals), 6),
                "first": vals[0], "last": vals[-1]}
    out = []
    if op == "moving_average":
        w = max(1, body.window)
        for i in range(len(series)):
            window_vals = vals[max(0, i - w + 1): i + 1]
            out.append({"t": series[i].get("t"), "v": round(sum(window_vals) / len(window_vals), 6)})
    elif op == "cumulative":
        running = 0.0
        for i in range(len(series)):
            running += vals[i]
            out.append({"t": series[i].get("t"), "v": round(running, 6)})
    elif op == "delta":
        for i in range(len(series)):
            out.append({"t": series[i].get("t"), "v": 0.0 if i == 0 else round(vals[i] - vals[i - 1], 6)})
    elif op == "normalize":
        lo, hi = (min(vals), max(vals)) if vals else (0, 0)
        rng = (hi - lo) or 1.0
        for i in range(len(series)):
            out.append({"t": series[i].get("t"), "v": round((vals[i] - lo) / rng, 6)})
    else:
        raise HTTPException(status_code=422, detail=f"Unknown transform op '{op}'")
    return {"op": op, "window": body.window, "count": len(out), "series": out}


@router.post("/quiver/timeseries/forecast")
def forecast(body: ForecastRequest):
    """Point-and-click forecasting via least-squares linear regression on the index."""
    vals = _values(sorted(body.series, key=lambda p: (p.get("t") is None, p.get("t"))))
    n = len(vals)
    if n < 2:
        raise HTTPException(status_code=422, detail="need at least 2 points to forecast")
    xs = list(range(n))
    mean_x = sum(xs) / n
    mean_y = sum(vals) / n
    sxx = sum((x - mean_x) ** 2 for x in xs)
    sxy = sum((xs[i] - mean_x) * (vals[i] - mean_y) for i in range(n))
    slope = sxy / sxx if sxx else 0.0
    intercept = mean_y - slope * mean_x
    # R^2
    ss_tot = sum((y - mean_y) ** 2 for y in vals) or 1.0
    ss_res = sum((vals[i] - (intercept + slope * xs[i])) ** 2 for i in range(n))
    r2 = 1 - ss_res / ss_tot
    predictions = [{"index": n + k, "v": round(intercept + slope * (n + k), 6)} for k in range(body.periods)]
    return {"slope": round(slope, 6), "intercept": round(intercept, 6), "r2": round(r2, 6),
            "periods": body.periods, "predictions": predictions}


# ---------------------------------------------------------------------------
# Time-series LIBRARY (pass 8): resample / rolling / interpolate / detect-events
# ---------------------------------------------------------------------------

_RESAMPLE_AGGS = {"mean", "sum", "min", "max", "last"}
_ROLLING_AGGS = {"mean", "median", "stdev", "min", "max"}


@router.post("/quiver/timeseries/resample")
def resample(body: ResampleRequest):
    """
    Time-bucket the series into fixed-width windows of ``bucket_seconds`` and
    reduce each bucket with ``agg``. Numeric ``t`` values are floored to the
    bucket boundary; the bucket label is the boundary start. Down- or up-samples
    deterministically. Points with non-numeric ``t`` are ignored.
    """
    if body.agg not in _RESAMPLE_AGGS:
        raise HTTPException(status_code=422, detail=f"agg must be one of {sorted(_RESAMPLE_AGGS)}")
    if body.bucket_seconds <= 0:
        raise HTTPException(status_code=422, detail="bucket_seconds must be positive")

    bucket = int(body.bucket_seconds)
    buckets: Dict[int, List[float]] = {}
    for p in body.series:
        t = p.get("t")
        v = p.get("v")
        if not _is_number(t) or not _is_number(v):
            continue
        key = (int(t) // bucket) * bucket
        buckets.setdefault(key, []).append(float(v))

    out = [
        {"t": key, "v": round(_agg_scalar(buckets[key], body.agg), 6)}
        for key in sorted(buckets)
    ]
    return {"agg": body.agg, "bucket_seconds": bucket, "count": len(out), "series": out}


@router.post("/quiver/timeseries/rolling")
def rolling(body: RollingRequest):
    """
    Rolling-window reduction over a sorted series. For index ``i`` the window is
    the trailing ``window`` points ``[i-window+1, i]`` reduced by ``agg``.
    Deterministic; ``t`` is preserved per point.
    """
    if body.agg not in _ROLLING_AGGS:
        raise HTTPException(status_code=422, detail=f"agg must be one of {sorted(_ROLLING_AGGS)}")
    w = max(1, int(body.window))
    series = _sort_series(body.series)
    out = []
    for i in range(len(series)):
        window_vals = [
            float(series[j]["v"])
            for j in range(max(0, i - w + 1), i + 1)
            if _is_number(series[j].get("v"))
        ]
        val = round(_agg_scalar(window_vals, body.agg), 6) if window_vals else None
        out.append({"t": series[i].get("t"), "v": val})
    return {"agg": body.agg, "window": w, "count": len(out), "series": out}


@router.post("/quiver/timeseries/interpolate")
def interpolate(body: InterpolateRequest):
    """
    Fill null/missing ``v`` gaps in a sorted series.
      ffill  - carry the last known value forward
      bfill  - carry the next known value backward
      linear - linearly interpolate between bounding known values (uses numeric t
               for spacing when available, else equal index spacing)
    Leading/trailing gaps with no anchor on the needed side are left null.
    """
    if body.method not in {"ffill", "bfill", "linear"}:
        raise HTTPException(status_code=422, detail="method must be ffill|bfill|linear")

    series = _sort_series(body.series)
    n = len(series)
    vals: List[Optional[float]] = [
        float(p["v"]) if _is_number(p.get("v")) else None for p in series
    ]
    ts: List[Any] = [p.get("t") for p in series]
    out_vals: List[Optional[float]] = list(vals)
    filled = 0

    if body.method == "ffill":
        last: Optional[float] = None
        for i in range(n):
            if vals[i] is not None:
                last = vals[i]
            elif last is not None:
                out_vals[i] = last
                filled += 1
    elif body.method == "bfill":
        nxt: Optional[float] = None
        for i in range(n - 1, -1, -1):
            if vals[i] is not None:
                nxt = vals[i]
            elif nxt is not None:
                out_vals[i] = nxt
                filled += 1
    else:  # linear
        known = [i for i in range(n) if vals[i] is not None]
        for idx in range(len(known) - 1):
            lo, hi = known[idx], known[idx + 1]
            if hi - lo <= 1:
                continue
            y0, y1 = vals[lo], vals[hi]
            x0 = ts[lo] if _is_number(ts[lo]) else lo
            x1 = ts[hi] if _is_number(ts[hi]) else hi
            span = (x1 - x0) if (x1 - x0) else (hi - lo)
            for i in range(lo + 1, hi):
                xi = ts[i] if _is_number(ts[i]) else i
                frac = ((xi - x0) / span) if span else ((i - lo) / (hi - lo))
                out_vals[i] = round(y0 + (y1 - y0) * frac, 6)
                filled += 1

    out = [{"t": ts[i], "v": out_vals[i]} for i in range(n)]
    return {"method": body.method, "filled": filled, "count": len(out), "series": out}


@router.post("/quiver/timeseries/detect-events")
def detect_events(body: DetectEventsRequest):
    """
    Detect event points in a sorted series.
      threshold_crossing - points where the value crosses ``threshold`` relative
                           to the previous point (records direction up/down)
      peak               - local maxima (strictly greater than both neighbours)
      trough             - local minima (strictly less than both neighbours)
    Returns the detected event points. Deterministic.
    """
    if body.mode not in {"threshold_crossing", "peak", "trough"}:
        raise HTTPException(status_code=422, detail="mode must be threshold_crossing|peak|trough")

    series = _sort_series(body.series)
    pts = [p for p in series if _is_number(p.get("v"))]
    events: List[Dict[str, Any]] = []

    if body.mode == "threshold_crossing":
        if body.threshold is None:
            raise HTTPException(status_code=422, detail="threshold required for threshold_crossing")
        thr = float(body.threshold)
        for i in range(1, len(pts)):
            prev = float(pts[i - 1]["v"])
            cur = float(pts[i]["v"])
            if prev < thr <= cur:
                events.append({"t": pts[i].get("t"), "v": cur, "direction": "up"})
            elif prev > thr >= cur:
                events.append({"t": pts[i].get("t"), "v": cur, "direction": "down"})
    else:
        for i in range(1, len(pts) - 1):
            prev = float(pts[i - 1]["v"])
            cur = float(pts[i]["v"])
            nxt = float(pts[i + 1]["v"])
            if body.mode == "peak" and cur > prev and cur > nxt:
                events.append({"t": pts[i].get("t"), "v": cur, "kind": "peak"})
            elif body.mode == "trough" and cur < prev and cur < nxt:
                events.append({"t": pts[i].get("t"), "v": cur, "kind": "trough"})

    return {"mode": body.mode, "threshold": body.threshold, "count": len(events), "events": events}


# ---------------------------------------------------------------------------
# Object-set -> chart aggregation
# ---------------------------------------------------------------------------

_CHART_AGGS = {"count", "sum", "mean", "min", "max"}


@router.post("/quiver/object-sets/aggregate-to-chart")
def aggregate_to_chart(body: AggregateToChartRequest, db: Session = Depends(get_db)):
    """
    Group ObjectInstances of an object type by ``group_by`` and reduce ``metric``
    with ``agg`` into a deterministic chart series. Reuses runtime._logic_object_rows
    for the object set so filtering semantics match AIP Logic. ``count`` ignores
    ``metric``; numeric aggs require a numeric ``metric`` property.
    """
    if body.agg not in _CHART_AGGS:
        raise HTTPException(status_code=422, detail=f"agg must be one of {sorted(_CHART_AGGS)}")
    if body.agg != "count" and not body.metric:
        raise HTTPException(status_code=422, detail=f"metric required for agg '{body.agg}'")

    rows, _ = runtime._logic_object_rows(db, body.object_type_id, body.filters, limit=10 ** 9)
    grouped: Dict[str, List[float]] = {}
    counts: Dict[str, int] = {}
    for r in rows:
        props = r.properties or {}
        raw_key = props.get(body.group_by)
        key = str(raw_key if raw_key is not None else "null")
        counts[key] = counts.get(key, 0) + 1
        if body.metric:
            mv = props.get(body.metric)
            if _is_number(mv):
                grouped.setdefault(key, []).append(float(mv))
            else:
                grouped.setdefault(key, [])

    categories = sorted(counts.keys())
    series: List[Dict[str, Any]] = []
    for key in categories:
        if body.agg == "count":
            value: float = counts[key]
        else:
            value = round(_agg_scalar(grouped.get(key, []), body.agg), 6)
        series.append({"category": key, "value": value, "count": counts[key]})

    return {
        "object_type_id": body.object_type_id,
        "group_by": body.group_by,
        "metric": body.metric,
        "agg": body.agg,
        "count": len(series),
        "categories": categories,
        "series": series,
    }

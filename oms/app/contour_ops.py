"""
Contour — extended board engine (deep-fidelity pass 8, Analytics).

Deepens Contour with the documented board types beyond filter/aggregate/derive:
pivot, sort, top_n, and per-column summary, applied as a stateless board pipeline
over a record set. Additive; deterministic; local.

This module also hosts the *unified* board executor used by both Contour engines:
  - contour_ops `/analytics/contour/apply` (stateless board pipeline), and
  - analytics `/analytics/contour/{id}/run` (persisted boards over a DataAsset).

UNIFIED FILTER SCHEMA — a `filter` board accepts EITHER form:
  {"op": "filter", "field": "city", "equals": "NYC"}        # contour_ops form
  {"op": "filter", "config": {"field": "city", "value": "NYC"}}  # analytics form

DATA-PRODUCING boards (terminal-shaped, emit a derived record set):
  chart_series   group_by + metric over a category/time field -> series rows
  histogram      numeric field -> bins {bin_start, bin_end, count}
  distribution   numeric field -> percentile rows p25/p50/p75/p90/p99
  time_series    sort by a time field -> {t, value} rows

TRANSFORMS:
  enrich     add fields by lookup from a provided side-table on a key
  join       merge two record lists on a key (reuses runtime._join_pipeline_records)
  set_math   union | intersect | difference of two record lists by key
  unpivot    wide columns -> long {variable, value} rows

Preserved ops: filter / derive / aggregate(group_by) / pivot / sort / top_n / summary.
"""
from typing import Optional, List, Any, Dict

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from . import runtime

router = APIRouter(tags=["contour_ops"])


class ApplyRequest(BaseModel):
    records: List[Dict[str, Any]]
    boards: List[Dict[str, Any]] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Shared numeric / aggregation helpers
# ---------------------------------------------------------------------------

def _nums(rows, field):
    return [r.get(field) for r in rows if isinstance(r.get(field), (int, float)) and not isinstance(r.get(field), bool)]


def _agg(rows, op, field):
    vals = _nums(rows, field)
    if op == "count":
        return len(rows)
    if op == "sum":
        return sum(vals)
    if op == "avg":
        return round(sum(vals) / len(vals), 6) if vals else 0
    if op == "min":
        return min(vals) if vals else None
    if op == "max":
        return max(vals) if vals else None
    return None


def _percentile(sorted_vals: List[float], pct: float) -> Optional[float]:
    """Linear-interpolation percentile over an already-sorted numeric list."""
    if not sorted_vals:
        return None
    if len(sorted_vals) == 1:
        return round(float(sorted_vals[0]), 6)
    rank = (pct / 100.0) * (len(sorted_vals) - 1)
    low = int(rank)
    high = min(low + 1, len(sorted_vals) - 1)
    frac = rank - low
    val = sorted_vals[low] + (sorted_vals[high] - sorted_vals[low]) * frac
    return round(float(val), 6)


# ---------------------------------------------------------------------------
# UNIFIED FILTER NORMALIZATION
# ---------------------------------------------------------------------------

def _normalize_filter(board: Dict[str, Any]) -> tuple:
    """
    Read a filter board in EITHER supported shape and return (field, value).
      contour_ops form: {"field": ..., "equals": ...}
      analytics  form:  {"config": {"field": ..., "value": ...}}
    The contour_ops top-level keys win when both are present.
    """
    config = board.get("config") or {}
    field = board.get("field")
    if field is None:
        field = config.get("field")
    if "equals" in board:
        value = board.get("equals")
    elif "value" in config:
        value = config.get("value")
    else:
        value = board.get("value")
    return field, value


# ---------------------------------------------------------------------------
# Board executor — shared by both routers
# ---------------------------------------------------------------------------

def execute_board_pipeline(records: List[Dict[str, Any]], boards: List[Dict[str, Any]]):
    """
    Run the unified board pipeline over `records`.

    Returns a dict with at least {"row_count", "records", "trace"}. Terminal
    boards (summary / distribution) may attach an extra top-level payload key.
    """
    rows = [dict(r) for r in records]
    trace: List[Dict[str, Any]] = []
    for i, board in enumerate(boards):
        op = board.get("op")
        before = len(rows)
        result = _apply_board(rows, op, board)
        if isinstance(result, tuple):
            # Terminal board: (payload_key, payload, row_count)
            key, payload, count = result
            trace.append({"index": i, "op": op, "rows_in": before, "rows_out": count})
            return {key: payload, "row_count": count, "records": rows, "trace": trace}
        rows = result
        trace.append({"index": i, "op": op, "rows_in": before, "rows_out": len(rows)})
    return {"row_count": len(rows), "records": rows, "trace": trace}


def _apply_board(rows: List[Dict[str, Any]], op: Optional[str], board: Dict[str, Any]):
    if op == "filter":
        field, val = _normalize_filter(board)
        if not field:
            return rows
        return [r for r in rows if r.get(field) == val]

    if op == "derive":
        tgt = board["target"]
        a, b, arith = board.get("a"), board.get("b"), board.get("arith", "add")

        def _v(x, r):
            return r.get(x) if isinstance(x, str) and x in r else x

        new_rows = []
        for r in rows:
            av, bv = _v(a, r), _v(b, r)
            try:
                val = {"add": av + bv, "sub": av - bv, "mul": av * bv,
                       "div": (av / bv if bv else None)}[arith]
            except (TypeError, KeyError):
                val = None
            new_rows.append({**r, tgt: val})
        return new_rows

    if op in ("aggregate", "group_by"):
        group_by = board.get("group_by", [])
        aggs = board.get("aggregations", [])
        groups: Dict[Any, List[Dict[str, Any]]] = {}
        for r in rows:
            groups.setdefault(tuple(r.get(g) for g in group_by), []).append(r)
        return [
            {**{g: k for g, k in zip(group_by, key)},
             **{a.get("as", f"{a.get('op')}_{a.get('field')}"): _agg(grp, a.get("op", "count"), a.get("field")) for a in aggs}}
            for key, grp in groups.items()
        ]

    if op == "pivot":
        index, column, value, agg = board["index"], board["column"], board.get("value"), board.get("agg", "sum")
        pivoted: Dict[Any, Dict[str, Any]] = {}
        buckets: Dict[Any, Dict[Any, List[Dict[str, Any]]]] = {}
        for r in rows:
            buckets.setdefault(r.get(index), {}).setdefault(r.get(column), []).append(r)
        for idx_val, cols in buckets.items():
            row = {index: idx_val}
            for col_val, grp in cols.items():
                row[str(col_val)] = _agg(grp, agg, value)
            pivoted[idx_val] = row
        return list(pivoted.values())

    if op == "sort":
        field = board["field"]
        return sorted(
            rows,
            key=lambda r: (r.get(field) is None, r.get(field) if isinstance(r.get(field), (int, float)) else str(r.get(field))),
            reverse=bool(board.get("desc")),
        )

    if op == "top_n":
        return rows[: int(board.get("n", 10))]

    if op == "summary":
        cols = board.get("fields") or (list(rows[0].keys()) if rows else [])
        summary = {}
        for c in cols:
            vals = _nums(rows, c)
            summary[c] = {"count": len(rows), "non_null": sum(1 for r in rows if r.get(c) is not None),
                          "min": min(vals) if vals else None, "max": max(vals) if vals else None,
                          "avg": round(sum(vals) / len(vals), 6) if vals else None}
        return ("summary", summary, len(rows))

    # --- DATA-PRODUCING boards -------------------------------------------

    if op == "chart_series":
        # group_by a category/time field, compute a metric -> series rows.
        category = board.get("group_by") or board.get("field") or board.get("category")
        metric_op = board.get("metric", board.get("op", "count"))
        metric_field = board.get("metric_field", board.get("value"))
        groups: Dict[Any, List[Dict[str, Any]]] = {}
        for r in rows:
            groups.setdefault(r.get(category), []).append(r)
        series = [
            {"category": k, "value": _agg(grp, metric_op, metric_field)}
            for k, grp in groups.items()
        ]
        series.sort(key=lambda s: (s["category"] is None, str(s["category"])))
        return series

    if op == "histogram":
        field = board.get("field")
        vals = sorted(_nums(rows, field))
        bin_count = int(board.get("bins", 10))
        if not vals or bin_count < 1:
            return []
        lo, hi = vals[0], vals[-1]
        if hi == lo:
            return [{"bin_start": lo, "bin_end": hi, "count": len(vals)}]
        width = (hi - lo) / bin_count
        out = []
        for b in range(bin_count):
            start = lo + b * width
            end = hi if b == bin_count - 1 else lo + (b + 1) * width
            if b == bin_count - 1:
                count = sum(1 for v in vals if start <= v <= end)
            else:
                count = sum(1 for v in vals if start <= v < end)
            out.append({"bin_start": round(start, 6), "bin_end": round(end, 6), "count": count})
        return out

    if op == "distribution":
        field = board.get("field")
        vals = sorted(_nums(rows, field))
        pcts = board.get("percentiles", [25, 50, 75, 90, 99])
        dist = {f"p{int(p)}": _percentile(vals, float(p)) for p in pcts}
        dist["count"] = len(vals)
        return ("distribution", dist, len(vals))

    if op == "time_series":
        time_field = board.get("time_field", board.get("field", "t"))
        value_field = board.get("value_field", board.get("value"))

        def _tkey(r):
            t = r.get(time_field)
            is_num = isinstance(t, (int, float)) and not isinstance(t, bool)
            return (t is None, not is_num, t if is_num else str(t))

        ordered = sorted(rows, key=_tkey)
        return [
            {"t": r.get(time_field), "value": (r.get(value_field) if value_field is not None else None)}
            for r in ordered
        ]

    # --- TRANSFORMS -------------------------------------------------------

    if op == "enrich":
        # add field(s) by lookup from a provided side-table on a key.
        key = board.get("key")
        side_key = board.get("side_key", key)
        side = board.get("side_table", board.get("table", []))
        add_fields = board.get("fields")  # optional whitelist of columns to copy
        prefix = board.get("prefix", "")
        index: Dict[Any, Dict[str, Any]] = {}
        for s in side:
            index.setdefault(s.get(side_key), s)
        out = []
        for r in rows:
            match = index.get(r.get(key))
            new_row = dict(r)
            if match:
                for k, v in match.items():
                    if k == side_key:
                        continue
                    if add_fields is None or k in add_fields:
                        new_row[f"{prefix}{k}"] = v
            out.append(new_row)
        return out

    if op == "join":
        # merge two record lists on a key — reuse runtime helper.
        right = board.get("right", board.get("right_table", []))
        return runtime._join_pipeline_records(rows, right, board)

    if op == "set_math":
        mode = board.get("mode", "union")
        key = board.get("key")
        other = board.get("other", board.get("right", []))

        def _kof(r):
            return tuple(r.get(k) for k in key) if isinstance(key, list) else r.get(key)

        if mode == "union":
            out, seen = [], set()
            for r in list(rows) + list(other):
                m = _kof(r)
                if m not in seen:
                    seen.add(m)
                    out.append(r)
            return out
        other_keys = {_kof(r) for r in other}
        if mode == "intersect":
            return [r for r in rows if _kof(r) in other_keys]
        if mode == "difference":
            return [r for r in rows if _kof(r) not in other_keys]
        raise HTTPException(status_code=422, detail=f"Unknown set_math mode '{mode}'")

    if op == "unpivot":
        # wide columns -> long {variable, value} rows.
        id_fields = board.get("id_fields", [])
        value_cols = board.get("value_columns") or board.get("columns")
        var_name = board.get("var_name", "variable")
        val_name = board.get("value_name", "value")
        out = []
        for r in rows:
            cols = value_cols if value_cols is not None else [k for k in r.keys() if k not in id_fields]
            base = {k: r.get(k) for k in id_fields}
            for c in cols:
                out.append({**base, var_name: c, val_name: r.get(c)})
        return out

    raise HTTPException(status_code=422, detail=f"Unknown board op '{op}'")


@router.post("/analytics/contour/apply")
def apply_boards(body: ApplyRequest):
    return execute_board_pipeline(body.records, body.boards)

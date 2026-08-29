"""
Slate reactive runtime (deep-fidelity pass 6, Applications).

Slate is query-centric: **queries** fetch data, **functions** transform it, **widgets**
bind to query/function results, and **events** trigger queries/functions/actions. This
module adds that runtime over the existing `slate_apps` table (additive; existing
/apps/slate endpoints untouched).

Note: Foundry Slate supports custom JavaScript functions. To stay deterministic and
local, this implements a safe **function DSL** (filter/pluck/aggregate/format/concat/
arithmetic) rather than executing arbitrary JS — consistent with the platform's
"deterministic local approximation" design.
"""
import uuid
from typing import Optional, List, Any, Dict

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel, Field

from .database import get_db
from . import models, models_action, production_auth, runtime, apps, semantic_scope

router = APIRouter(tags=["slate_runtime"])


def _get_app(db: Session, app_id: str):
    app_ = db.get(apps.SlateApp, app_id)
    if not app_:
        raise HTTPException(status_code=404, detail=f"Slate app '{app_id}' not found")
    return app_


def _aggregate(rows: List[Dict[str, Any]], agg: str, field: Optional[str]) -> Any:
    nums = [r.get(field) for r in rows if isinstance(r.get(field), (int, float)) and not isinstance(r.get(field), bool)]
    if agg == "count":
        return len(rows)
    if agg == "sum":
        return sum(nums)
    if agg == "avg":
        return (sum(nums) / len(nums)) if nums else 0
    if agg == "min":
        return min(nums) if nums else None
    if agg == "max":
        return max(nums) if nums else None
    return len(rows)


def _rows(result: Any) -> List[Dict[str, Any]]:
    if isinstance(result, dict) and "objects" in result:
        return [o.get("properties", {}) for o in result["objects"]]
    if isinstance(result, list):
        return result
    return []


# ---------------------------------------------------------------------------
# Query resolution
# ---------------------------------------------------------------------------
def _resolve_query(db: Session, spec: Dict[str, Any], state: Dict[str, Any]) -> Any:
    qtype = spec.get("type", "static")
    if qtype == "static":
        return spec.get("value")
    if qtype == "state":
        return state.get(spec.get("key"), spec.get("default"))
    if qtype == "object_set":
        rows, count = runtime._logic_object_rows(db, spec.get("object_type_id"), spec.get("filters", {}), int(spec.get("limit", 1000)))
        return {"object_type_id": spec.get("object_type_id"), "count": count,
                "objects": [{"id": r.id, "properties": r.properties} for r in rows]}
    if qtype == "object_aggregation":
        rows, _ = runtime._logic_object_rows(db, spec.get("object_type_id"), spec.get("filters", {}), limit=10 ** 9)
        return _aggregate([r.properties for r in rows], spec.get("op", "count"), spec.get("field"))
    if qtype == "http":  # no real network locally — return the declared mock deterministically
        return {"url": spec.get("url"), "status": "mocked", "response": spec.get("mock_response")}
    return spec.get("value")


def resolve_queries(db: Session, queries: Dict[str, Any], state: Dict[str, Any]) -> Dict[str, Any]:
    return {name: _resolve_query(db, spec, state) for name, spec in (queries or {}).items() if isinstance(spec, dict)}


# ---------------------------------------------------------------------------
# Function DSL
# ---------------------------------------------------------------------------
def _ref(ref: Any, ctx: Dict[str, Any]) -> Any:
    if isinstance(ref, dict) and "const" in ref:
        return ref["const"]
    if isinstance(ref, str) and ref in ctx:
        return ctx[ref]
    return ref


def _refs_of(spec: Dict[str, Any]) -> List[str]:
    op = spec.get("op")
    if op in ("filter", "pluck", "aggregate"):
        return [spec.get("source")]
    if op == "format":
        return list(spec.get("inputs", {}).values())
    if op in ("concat", "sum", "product", "difference"):
        return list(spec.get("inputs", []))
    return []


def _eval_function(spec: Dict[str, Any], ctx: Dict[str, Any]) -> Any:
    op = spec.get("op")
    if op == "filter":
        rows = _rows(ctx.get(spec.get("source")))
        return [r for r in rows if r.get(spec.get("field")) == spec.get("equals")]
    if op == "pluck":
        rows = _rows(ctx.get(spec.get("source")))
        return [r.get(spec.get("field")) for r in rows]
    if op == "aggregate":
        rows = _rows(ctx.get(spec.get("source")))
        return _aggregate(rows, spec.get("agg", "count"), spec.get("field"))
    if op == "format":
        inputs = {k: _ref(v, ctx) for k, v in spec.get("inputs", {}).items()}
        try:
            return str(spec.get("template", "")).format(**inputs)
        except Exception:
            return spec.get("template", "")
    if op == "concat":
        return spec.get("separator", "").join("" if (v := _ref(r, ctx)) is None else str(v) for r in spec.get("inputs", []))
    if op in ("sum", "product", "difference"):
        vals = [_ref(r, ctx) for r in spec.get("inputs", [])]
        nums = [v for v in vals if isinstance(v, (int, float)) and not isinstance(v, bool)]
        if op == "sum":
            return sum(nums)
        if op == "product":
            out = 1
            for n in nums:
                out *= n
            return out
        return (nums[0] - sum(nums[1:])) if nums else 0
    return None


def resolve_functions(functions: Dict[str, Any], resolved_queries: Dict[str, Any], state: Dict[str, Any]) -> Dict[str, Any]:
    resolved: Dict[str, Any] = {}
    pending = {k: v for k, v in (functions or {}).items() if isinstance(v, dict)}
    fnames = set(pending.keys())
    for _ in range(8):
        if not pending:
            break
        progressed = False
        for name, spec in list(pending.items()):
            deps = [r for r in _refs_of(spec) if isinstance(r, str) and r in fnames]
            if any(d not in resolved for d in deps):
                continue
            ctx = {**state, **resolved_queries, **resolved}
            resolved[name] = _eval_function(spec, ctx)
            del pending[name]
            progressed = True
        if not progressed:
            break
    for name in pending:
        resolved[name] = None
    return resolved


# ---------------------------------------------------------------------------
# Widget rendering
# ---------------------------------------------------------------------------
def render_widgets(widgets: Dict[str, Any], resolved_queries: Dict[str, Any], resolved_functions: Dict[str, Any]) -> List[Dict[str, Any]]:
    out = []
    ctx = {**resolved_queries, **resolved_functions}
    for name, widget in (widgets or {}).items():
        wtype = widget.get("type")
        rendered: Dict[str, Any] = {"name": name, "type": wtype, "title": widget.get("title")}
        bound = ctx.get(widget.get("query")) if widget.get("query") else ctx.get(widget.get("function"))
        if wtype in ("object_table", "table", "object_list"):
            rows = _rows(bound)
            rendered["row_count"] = bound.get("count", len(rows)) if isinstance(bound, dict) else len(rows)
            rendered["sample"] = rows[:5]
        else:
            rendered["value"] = bound
        out.append(rendered)
    return out


# ---------------------------------------------------------------------------
# Schemas + endpoints
# ---------------------------------------------------------------------------
class StateRequest(BaseModel):
    state: Dict[str, Any] = Field(default_factory=dict)


class EventRequest(BaseModel):
    state: Dict[str, Any] = Field(default_factory=dict)
    events: List[Dict[str, Any]] = Field(default_factory=list)


def _resolve_all(db: Session, app_, state: Dict[str, Any]):
    rq = resolve_queries(db, app_.queries or {}, state)
    rf = resolve_functions(app_.functions or {}, rq, state)
    return rq, rf


def build_dependency_graph(
    queries: Dict[str, Any],
    functions: Dict[str, Any],
    widgets: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Expose the query/function/widget DAG used by the Slate resolver.

    Nodes: one per query (typed by its query type), one per function (typed by its
    op), one per widget. Edges: a function depends on the queries/functions it
    references (`_refs_of`); a widget depends on the query or function it binds.
    Reports a topological order over query+function nodes and flags cycles.
    """
    queries = queries or {}
    functions = functions or {}
    widgets = widgets or {}
    nodes: List[Dict[str, Any]] = []
    edges: List[Dict[str, Any]] = []

    for name, spec in queries.items():
        qtype = spec.get("type", "static") if isinstance(spec, dict) else "static"
        nodes.append({"id": name, "kind": "query", "query_type": qtype})

    fn_names = set(functions.keys())
    query_names = set(queries.keys())
    resolvable = query_names | fn_names
    for name, spec in functions.items():
        op = spec.get("op") if isinstance(spec, dict) else None
        nodes.append({"id": name, "kind": "function", "op": op})
        refs = _refs_of(spec) if isinstance(spec, dict) else []
        for ref in refs:
            if isinstance(ref, str) and ref in resolvable:
                edges.append({"from": ref, "to": name, "kind": "function_dependency"})

    for name, widget in widgets.items():
        if not isinstance(widget, dict):
            continue
        nodes.append({"id": f"widget:{name}", "kind": "widget", "widget_type": widget.get("type")})
        bound = widget.get("query") or widget.get("function")
        if bound:
            kind = "widget_query_binding" if widget.get("query") else "widget_function_binding"
            edges.append({"from": bound, "to": f"widget:{name}", "kind": kind})

    # Topological sort over query + function nodes (queries have no in-edges).
    indeg = {n: 0 for n in resolvable}
    adj: Dict[str, List[str]] = {n: [] for n in resolvable}
    for e in edges:
        if e["kind"] == "function_dependency" and e["from"] in resolvable and e["to"] in resolvable:
            indeg[e["to"]] += 1
            adj[e["from"]].append(e["to"])
    queue = sorted([n for n, d in indeg.items() if d == 0])
    order: List[str] = []
    while queue:
        n = queue.pop(0)
        order.append(n)
        for m in adj[n]:
            indeg[m] -= 1
            if indeg[m] == 0:
                queue.append(m)
        queue.sort()
    cyclic = sorted([n for n in resolvable if n not in order])
    return {
        "nodes": nodes,
        "edges": edges,
        "topological_order": order,
        "has_cycle": bool(cyclic),
        "cyclic_nodes": cyclic,
    }


@router.get("/apps/slate/{app_id}/dependencies")
def slate_dependencies(app_id: str, db: Session = Depends(get_db)):
    app_ = _get_app(db, app_id)
    graph = build_dependency_graph(app_.queries or {}, app_.functions or {}, app_.widgets or {})
    return {"app_id": app_id, **graph}


@router.post("/apps/slate/{app_id}/resolve")
def resolve_app(app_id: str, body: StateRequest, db: Session = Depends(get_db)):
    app_ = _get_app(db, app_id)
    rq, rf = _resolve_all(db, app_, body.state)
    return {"app_id": app_id, "queries": rq, "functions": rf}


@router.post("/apps/slate/{app_id}/run-query/{query_name}")
def run_query(app_id: str, query_name: str, body: StateRequest, db: Session = Depends(get_db)):
    app_ = _get_app(db, app_id)
    spec = (app_.queries or {}).get(query_name)
    if not spec:
        raise HTTPException(status_code=404, detail=f"Query '{query_name}' not found")
    return {"app_id": app_id, "query": query_name, "result": _resolve_query(db, spec, body.state)}


@router.post("/apps/slate/{app_id}/render")
def render_app(app_id: str, body: StateRequest, db: Session = Depends(get_db)):
    app_ = _get_app(db, app_id)
    rq, rf = _resolve_all(db, app_, body.state)
    return {"app_id": app_id, "widgets": render_widgets(app_.widgets or {}, rq, rf)}


@router.post("/apps/slate/{app_id}/event")
def fire_events(app_id: str, body: EventRequest, db: Session = Depends(get_db),
                principal: production_auth.Principal = Depends(
                    production_auth.require_permission("execute"))):
    app_ = _get_app(db, app_id)
    state = dict(body.state)
    effects: List[Dict[str, Any]] = []
    for event in body.events:
        etype = event.get("type")
        if etype == "set_variable":
            state[event["target"]] = event.get("value")
            effects.append({"type": etype, "status": "applied"})
        elif etype == "run_query":
            spec = (app_.queries or {}).get(event.get("query"))
            state[event.get("target", event.get("query"))] = _resolve_query(db, spec, state) if spec else None
            effects.append({"type": etype, "status": "applied" if spec else "error"})
        elif etype == "call_function":
            rq, rf = _resolve_all(db, app_, state)
            ctx = {**state, **rq, **rf}
            spec = (app_.functions or {}).get(event.get("function"))
            state[event.get("target", event.get("function"))] = _eval_function(spec, ctx) if spec else None
            effects.append({"type": etype, "status": "applied" if spec else "error"})
        elif etype == "apply_action":
            # Three things this did not do, all of which its sibling
            # workshop_runtime._apply_event has always done. It loaded any
            # ActionType by id, so a caller could drive another project's action;
            # it mutated immediately, skipping the approval gate that
            # POST /actions/execute enforces for the identical call; and it wrote
            # actor="slate", so the trail never named who asked. T5 of
            # GOAL_TENANCY_2026-08-27.
            try:
                action = semantic_scope.owned_row(
                    db, principal, models.ActionType, str(event.get("action_type_id") or ""),
                    "execute", "ActionType")
            except HTTPException as exc:
                if exc.status_code != 404:
                    raise
                action = None
            if not action:
                effects.append({"type": etype, "status": "error", "detail": "action not found"})
            else:
                params = {k: (state.get(v[1:]) if isinstance(v, str) and v.startswith("$") else v)
                          for k, v in (event.get("parameters") or {}).items()}
                rules = action.rules or {}
                requires_approval = bool(
                    rules.get("requires_approval")
                    or rules.get("approval_required")
                    or str(rules.get("risk_level", "")).lower() in {"high", "critical"}
                )
                if requires_approval:
                    approval_id = str(uuid.uuid4())
                    db.add(models_action.ApprovalRequest(
                        id=approval_id,
                        project_id=action.project_id,
                        action_type_id=action.id,
                        requester=principal.id,
                        parameters=params,
                        status=models_action.ApprovalStatus.PENDING.value,
                    ))
                    effects.append({
                        "type": etype, "status": "pending_approval",
                        "action_type_id": action.id, "approval_request_id": approval_id,
                        "mutated_object_ids": [],
                    })
                else:
                    mutated = runtime.apply_action_mutations(
                        db, action_type=action, parameters=params, actor=principal.id)
                    effects.append({"type": etype, "status": "applied",
                                    "action_type_id": action.id, "mutated_object_ids": mutated})
        else:
            effects.append({"type": etype, "status": "ignored"})
    db.commit()
    rq, rf = _resolve_all(db, app_, state)
    return {"app_id": app_id, "state": state, "effects": effects, "queries": rq, "functions": rf}

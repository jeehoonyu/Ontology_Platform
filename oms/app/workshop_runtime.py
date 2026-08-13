"""
Workshop reactive runtime (deep-fidelity pass 5, Applications).

The base `apps.py` stores a Workshop module's variables/widgets/layout and renders
shallowly. This module adds the documented reactive model over the SAME
`workshop_modules` table (additive — existing /apps/workshop endpoints untouched):

  * **Variables** resolved by `definition_type` against the live ontology:
    static, state, object_set, object_set_aggregation, object_property, function,
    variable_transformation (dependency-ordered resolution).
  * **Events** that mutate runtime state: set_variable, reset_variable, navigate,
    toggle_section, open_overlay/close_overlay, apply_action (applies via the
    action engine).
  * **Live render** of widgets against resolved variables.

Deterministic and local. No real frontend; this is the evaluation core a UI binds to.
"""
import time
import uuid
from typing import Optional, List, Any, Dict

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel, Field

from .database import get_db
from . import models, models_action, runtime, apps, ops_control
from .production_auth import Principal, require_permission

router = APIRouter(tags=["workshop_runtime"])


def _get_module(db: Session, module_id: str, principal: Principal, permission: str = "view"):
    return apps._get_workshop_module_or_404(db, module_id, principal, permission)


def _object_type_project_id(db: Session, object_type_id: str) -> str:
    object_type = db.get(models.ObjectType, object_type_id)
    if not object_type:
        raise HTTPException(status_code=422, detail=f"Object type '{object_type_id}' not found")
    return str(((object_type.properties or {}).get("__manager") or {}).get("project_id") or "default")


def _assert_object_type_project(db: Session, object_type_id: Optional[str], project_id: str) -> None:
    if object_type_id and _object_type_project_id(db, object_type_id) != project_id:
        raise HTTPException(status_code=403, detail={
            "message": "Workshop cannot access an object type owned by another project",
            "project_id": project_id,
            "object_type_id": object_type_id,
        })


# ---------------------------------------------------------------------------
# Variable resolution
# ---------------------------------------------------------------------------
def _aggregate(instances, op: str, field: Optional[str]) -> Any:
    nums = [
        (i.properties or {}).get(field) for i in instances
        if isinstance((i.properties or {}).get(field), (int, float)) and not isinstance((i.properties or {}).get(field), bool)
    ]
    if op == "count":
        return len(instances)
    if op == "sum":
        return sum(nums)
    if op == "avg":
        return (sum(nums) / len(nums)) if nums else 0
    if op == "min":
        return min(nums) if nums else None
    if op == "max":
        return max(nums) if nums else None
    return len(instances)


def _deps(spec: Dict[str, Any]) -> List[str]:
    dt = spec.get("definition_type", "static")
    if dt == "variable_transformation":
        return list(spec.get("inputs", []))
    if dt == "object_property" and spec.get("object_id_var"):
        return [spec["object_id_var"]]
    return []


def _val(name: str, resolved: Dict[str, Any], state: Dict[str, Any]) -> Any:
    return resolved[name] if name in resolved else state.get(name)


def _transform(spec: Dict[str, Any], resolved: Dict[str, Any], state: Dict[str, Any]) -> Any:
    op = spec.get("op", "concat")
    vals = [_val(i, resolved, state) for i in spec.get("inputs", [])]
    if op == "concat":
        return spec.get("separator", "").join("" if v is None else str(v) for v in vals)
    nums = [v for v in vals if isinstance(v, (int, float)) and not isinstance(v, bool)]
    if op == "sum":
        return sum(nums)
    if op == "product":
        out = 1
        for n in nums:
            out *= n
        return out
    if op == "difference":
        return (nums[0] - sum(nums[1:])) if nums else 0
    if op == "count":
        first = vals[0] if vals else None
        return len(first) if hasattr(first, "__len__") else 0
    if op == "pluck":
        first = vals[0] if vals else []
        field = spec.get("field")
        return [(r.get("properties", r) or {}).get(field) for r in first] if isinstance(first, list) else []
    if op == "first":
        first = vals[0] if vals else None
        return first[0] if isinstance(first, list) and first else None
    return vals


def _resolve_one(db: Session, spec: Dict[str, Any], state: Dict[str, Any], resolved: Dict[str, Any], project_id: str) -> Any:
    dt = spec.get("definition_type", "static")
    if dt == "static":
        return spec.get("value")
    if dt == "state":
        return state.get(spec.get("key"), spec.get("default"))
    if dt == "object_set":
        _assert_object_type_project(db, spec.get("object_type_id"), project_id)
        rows, count = runtime._logic_object_rows(db, spec.get("object_type_id"), spec.get("filters", {}), int(spec.get("limit", 1000)))
        return {"object_type_id": spec.get("object_type_id"), "count": count,
                "objects": [{"id": r.id, "properties": r.properties} for r in rows]}
    if dt == "object_set_aggregation":
        _assert_object_type_project(db, spec.get("object_type_id"), project_id)
        rows, _ = runtime._logic_object_rows(db, spec.get("object_type_id"), spec.get("filters", {}), limit=10 ** 9)
        return _aggregate(rows, spec.get("op", "count"), spec.get("field"))
    if dt == "object_property":
        oid = None
        if spec.get("object_id_var"):
            oid = _val(spec["object_id_var"], resolved, state)
        oid = oid or spec.get("object_id")
        obj = db.get(models.ObjectInstance, oid) if oid else None
        if obj:
            _assert_object_type_project(db, obj.object_type_id, project_id)
        return (obj.properties or {}).get(spec.get("property")) if obj else None
    if dt == "function":
        from . import ontology_functions as _of
        fn = db.get(_of.OntologyFunction, spec.get("function_id"))
        if not fn:
            return None
        _assert_object_type_project(db, fn.object_type_id, project_id)
        insts = db.query(models.ObjectInstance).filter(models.ObjectInstance.object_type_id == fn.object_type_id).all() if fn.object_type_id else []
        expr = fn.expression or {}
        return _aggregate(insts, expr.get("op", "count"), expr.get("field"))
    if dt == "variable_transformation":
        return _transform(spec, resolved, state)
    return spec.get("value")


def _resolve_variables(db: Session, variables: Dict[str, Any], state: Dict[str, Any], project_id: str = "default") -> Dict[str, Any]:
    resolved: Dict[str, Any] = {}
    pending = {k: v for k, v in (variables or {}).items() if isinstance(v, dict)}
    # plain (non-dict) variables are treated as static literals
    for k, v in (variables or {}).items():
        if not isinstance(v, dict):
            resolved[k] = v
    for _ in range(8):  # dependency-ordered fixed point
        if not pending:
            break
        progressed = False
        for name, spec in list(pending.items()):
            deps = _deps(spec)
            if any(d not in resolved and d not in state for d in deps):
                continue
            resolved[name] = _resolve_one(db, spec, state, resolved, project_id)
            del pending[name]
            progressed = True
        if not progressed:
            break
    for name in pending:  # unresolved (e.g. cyclic) -> None
        resolved[name] = None
    return resolved


# ---------------------------------------------------------------------------
# Widget rendering
# ---------------------------------------------------------------------------
def _render_widget(db: Session, widget: Dict[str, Any], resolved: Dict[str, Any], project_id: str) -> Dict[str, Any]:
    wtype = widget.get("type")
    out: Dict[str, Any] = {"type": wtype, "title": widget.get("title")}
    var = widget.get("variable") or (widget.get("config") or {}).get("variable")
    bound = resolved.get(var) if var else None
    if wtype in ("object_table", "object_list"):
        if isinstance(bound, dict) and "objects" in bound:
            out["row_count"] = bound.get("count", len(bound["objects"]))
            out["sample_ids"] = [o["id"] for o in bound["objects"][:5]]
        elif widget.get("object_type_id"):
            _assert_object_type_project(db, widget["object_type_id"], project_id)
            rows, count = runtime._logic_object_rows(db, widget["object_type_id"], widget.get("filters", {}), 5)
            out["row_count"] = count
            out["sample_ids"] = [r.id for r in rows]
        else:
            out["row_count"] = 0
            out["sample_ids"] = []
    elif wtype in ("metric", "kpi", "text"):
        out["value"] = bound
    elif wtype == "button":
        out["action_type_id"] = widget.get("action_type_id")
    else:
        out["value"] = bound
    return out


# ---------------------------------------------------------------------------
# Event engine
# ---------------------------------------------------------------------------
def _apply_event(db: Session, event: Dict[str, Any], state: Dict[str, Any], principal: Principal, project_id: str) -> Dict[str, Any]:
    etype = event.get("type")
    effect: Dict[str, Any] = {"type": etype, "status": "applied"}
    if etype == "set_variable":
        state[event["target"]] = event.get("value")
    elif etype == "reset_variable":
        state.pop(event.get("target"), None)
    elif etype == "navigate":
        state["_page"] = event.get("page")
    elif etype == "toggle_section":
        sections = state.setdefault("_sections", {})
        sections[event["section"]] = not sections.get(event["section"], False)
    elif etype in ("open_overlay", "close_overlay"):
        overlays = state.setdefault("_overlays", {})
        overlays[event["layer"]] = (etype == "open_overlay")
    elif etype == "apply_action":
        action = db.get(models.ActionType, event.get("action_type_id"))
        if not action:
            effect = {"type": etype, "status": "error", "detail": "action not found"}
        elif action.project_id != project_id:
            raise HTTPException(status_code=403, detail="Workshop action belongs to another project")
        else:
            params = {
                k: (state.get(v[1:]) if isinstance(v, str) and v.startswith("$") else v)
                for k, v in (event.get("parameters") or {}).items()
            }
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
                    project_id=project_id,
                    action_type_id=action.id,
                    requester=principal.id,
                    parameters=params,
                    status=models_action.ApprovalStatus.PENDING.value,
                ))
                apps._append_audit(
                    db,
                    actor=principal.id,
                    event_type="apps.workshop.action_approval_requested",
                    subject_type="approval_request",
                    subject_id=approval_id,
                    payload={"project_id": project_id, "action_type_id": action.id},
                )
                ops_control.record_ops_event(
                    db,
                    source="workshop",
                    event_type="workshop.action.approval_requested",
                    severity="high",
                    title=f"Workshop action approval requested for {action.id}",
                    subject_type="approval_request",
                    subject_id=approval_id,
                    payload={"project_id": project_id, "action_type_id": action.id, "workshop_event": event.get("id")},
                )
                effect = {
                    "type": etype,
                    "status": "approval_required",
                    "action_type_id": action.id,
                    "approval_request_id": approval_id,
                }
            else:
                mutated = runtime.apply_action_mutations(db, action_type=action, parameters=params, actor=principal.id)
                effect = {"type": etype, "status": "applied", "action_type_id": action.id, "mutated_object_ids": mutated}
    else:
        effect = {"type": etype, "status": "ignored"}
    return effect


# ---------------------------------------------------------------------------
# Schemas + endpoints
# ---------------------------------------------------------------------------
class StateRequest(BaseModel):
    state: Dict[str, Any] = Field(default_factory=dict)


class EventRequest(BaseModel):
    state: Dict[str, Any] = Field(default_factory=dict)
    events: List[Dict[str, Any]] = Field(default_factory=list)


def _widget_var(widget: Dict[str, Any]) -> Optional[str]:
    return widget.get("variable") or (widget.get("config") or {}).get("variable")


def build_dependency_graph(variables: Dict[str, Any], widgets: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Expose the variable/function DAG used by the reactive resolver.

    Nodes: one per variable (typed by definition_type) plus one per widget that
    binds a variable. Edges: dependency -> dependent (a variable's resolved value
    depends on its inputs; a widget depends on the variable it binds). Also reports
    a topological order (the same dependency-ordered fixed point the resolver uses)
    and flags cycles that cannot be ordered.
    """
    variables = variables or {}
    nodes: List[Dict[str, Any]] = []
    edges: List[Dict[str, Any]] = []

    var_names = set(variables.keys())
    for name, spec in variables.items():
        dt = spec.get("definition_type", "static") if isinstance(spec, dict) else "static"
        nodes.append({"id": name, "kind": "variable", "definition_type": dt})
        deps = _deps(spec) if isinstance(spec, dict) else []
        for dep in deps:
            edges.append({"from": dep, "to": name, "kind": "variable_dependency"})

    for idx, widget in enumerate(widgets or []):
        if not isinstance(widget, dict):
            continue
        wid = f"widget:{widget.get('title') or widget.get('type') or idx}"
        nodes.append({"id": wid, "kind": "widget", "widget_type": widget.get("type")})
        bound = _widget_var(widget)
        if bound:
            edges.append({"from": bound, "to": wid, "kind": "widget_binding"})

    # Kahn topological sort over variable nodes only (deps must be variables).
    indeg = {n: 0 for n in var_names}
    adj: Dict[str, List[str]] = {n: [] for n in var_names}
    for e in edges:
        if e["kind"] == "variable_dependency" and e["from"] in var_names and e["to"] in var_names:
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
    cyclic = sorted([n for n in var_names if n not in order])
    return {
        "nodes": nodes,
        "edges": edges,
        "topological_order": order,
        "has_cycle": bool(cyclic),
        "cyclic_nodes": cyclic,
    }


@router.get("/apps/workshop/{module_id}/dependencies")
def workshop_dependencies(module_id: str, principal: Principal = Depends(require_permission("view")), db: Session = Depends(get_db)):
    mod = _get_module(db, module_id, principal, "view")
    graph = build_dependency_graph(mod.variables or {}, list(mod.widgets or []))
    return {"module_id": module_id, **graph}


@router.post("/apps/workshop/{module_id}/resolve")
def resolve_variables(module_id: str, body: StateRequest, principal: Principal = Depends(require_permission("view")), db: Session = Depends(get_db)):
    mod = _get_module(db, module_id, principal, "view")
    resolved = _resolve_variables(db, mod.variables or {}, body.state, mod.project_id)
    return {"module_id": module_id, "state": body.state, "variables": resolved}


@router.post("/apps/workshop/{module_id}/render-live")
def render_live(module_id: str, body: StateRequest, principal: Principal = Depends(require_permission("view")), db: Session = Depends(get_db)):
    mod = _get_module(db, module_id, principal, "view")
    resolved = _resolve_variables(db, mod.variables or {}, body.state, mod.project_id)
    widgets = [_render_widget(db, w, resolved, mod.project_id) for w in (mod.widgets or [])]
    return {"module_id": module_id, "page": body.state.get("_page"),
            "variables": resolved, "widgets": widgets}


@router.post("/apps/workshop/{module_id}/event")
def fire_events(module_id: str, body: EventRequest, principal: Principal = Depends(require_permission("execute")), db: Session = Depends(get_db)):
    mod = _get_module(db, module_id, principal, "execute")
    state = dict(body.state)
    effects: List[Dict[str, Any]] = []
    proposed_actions: List[Dict[str, Any]] = []
    for event in body.events:  # events execute sequentially
        effect = _apply_event(db, event, state, principal, mod.project_id)
        effects.append(effect)
        if effect.get("type") == "apply_action" and effect.get("status") == "applied":
            proposed_actions.append({"action_type_id": effect["action_type_id"],
                                     "mutated_object_ids": effect["mutated_object_ids"]})
    db.commit()
    resolved = _resolve_variables(db, mod.variables or {}, state, mod.project_id)
    return {"module_id": module_id, "state": state, "effects": effects,
            "applied_actions": proposed_actions, "variables": resolved}

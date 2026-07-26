"""
Carbon workspace runtime (deep-fidelity pass 6, Applications).

Carbon is a unified workspace shell that ties multiple apps/modules together under
one navigation. This runtime resolves a workspace's navigation tree, looks up each
referenced module across the platform (Workshop, Slate, saved object sets, map
layers), and **opens** a module by delegating to the Workshop / Slate runtimes.
Additive over the existing `carbon_workspaces` table; deterministic; local.
"""
from typing import Optional, List, Any, Dict

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel, Field

from .database import get_db
from . import models, apps, workshop_runtime, slate_runtime
from .production_auth import Principal, require_permission

router = APIRouter(tags=["carbon_runtime"])


def _get_workspace(db: Session, workspace_id: str):
    ws = db.get(apps.CarbonWorkspace, workspace_id)
    if not ws:
        raise HTTPException(status_code=404, detail=f"Carbon workspace '{workspace_id}' not found")
    return ws


def _resolve_module(db: Session, module_id: str, principal: Principal) -> Dict[str, Any]:
    wm = db.get(apps.WorkshopModule, module_id)
    if wm:
        apps._get_workshop_module_or_404(db, module_id, principal, "view")
        return {"module_id": module_id, "kind": "workshop", "display_name": wm.display_name, "exists": True}
    sa = db.get(apps.SlateApp, module_id)
    if sa:
        return {"module_id": module_id, "kind": "slate", "display_name": sa.display_name, "exists": True}
    ss = db.get(models.SavedObjectSet, module_id)
    if ss:
        return {"module_id": module_id, "kind": "object_set", "display_name": ss.display_name, "exists": True}
    ml = db.get(models.MapLayerDefinition, module_id)
    if ml:
        return {"module_id": module_id, "kind": "map_layer", "display_name": ml.display_name, "exists": True}
    return {"module_id": module_id, "kind": "unknown", "display_name": None, "exists": False}


def _navigation(ws) -> Dict[str, Any]:
    nav = ws.navigation or {}
    if nav.get("sections"):
        return nav
    # derive a default single-section nav from module_ids
    return {"home": (ws.module_ids or [None])[0],
            "sections": [{"title": "Modules", "items": list(ws.module_ids or [])}]}


class StateRequest(BaseModel):
    state: Dict[str, Any] = Field(default_factory=dict)


class OutputBinding(BaseModel):
    source_output: str
    target_input: str


class NavigateRequest(BaseModel):
    from_module_id: str
    to_module_id: str
    output_bindings: List[OutputBinding] = Field(default_factory=list)
    state: Dict[str, Any] = Field(default_factory=dict)


def _module_outputs(db: Session, module_id: str, state: Dict[str, Any], principal: Principal):
    """
    Resolve a module's typed outputs by delegating to the owning runtime.

    Workshop -> resolved variables (definition_type-typed values).
    Slate     -> resolved queries + functions merged into one output namespace.
    Returns (kind, outputs_dict) or (kind, None) if the module is not resolvable.
    """
    wm = db.get(apps.WorkshopModule, module_id)
    if wm:
        apps._get_workshop_module_or_404(db, module_id, principal, "view")
        outputs = workshop_runtime._resolve_variables(db, wm.variables or {}, state, wm.project_id)
        return "workshop", outputs
    sa = db.get(apps.SlateApp, module_id)
    if sa:
        rq, rf = slate_runtime._resolve_all(db, sa, state)
        return "slate", {**rq, **rf}
    return _resolve_module(db, module_id, principal)["kind"], None


def _value_type(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, (int, float)):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, dict):
        if "objects" in value and "object_type_id" in value:
            return "object_set"
        return "object"
    if isinstance(value, list):
        return "array"
    return type(value).__name__


@router.get("/apps/carbon/{workspace_id}/resolve")
def resolve_workspace(workspace_id: str, principal: Principal = Depends(require_permission("view")), db: Session = Depends(get_db)):
    ws = _get_workspace(db, workspace_id)
    modules = [_resolve_module(db, mid, principal) for mid in (ws.module_ids or [])]
    return {"workspace_id": workspace_id, "display_name": ws.display_name,
            "module_count": len(modules), "modules": modules,
            "missing": [m["module_id"] for m in modules if not m["exists"]]}


@router.get("/apps/carbon/{workspace_id}/render")
def render_workspace(workspace_id: str, principal: Principal = Depends(require_permission("view")), db: Session = Depends(get_db)):
    ws = _get_workspace(db, workspace_id)
    nav = _navigation(ws)
    sections = []
    for section in nav.get("sections", []):
        items = [_resolve_module(db, mid, principal) for mid in section.get("items", [])]
        sections.append({"title": section.get("title"), "items": items})
    home = _resolve_module(db, nav.get("home"), principal) if nav.get("home") else None
    return {"workspace_id": workspace_id, "display_name": ws.display_name,
            "home": home, "sections": sections}


@router.post("/apps/carbon/{workspace_id}/open/{module_id}")
def open_module(workspace_id: str, module_id: str, body: StateRequest, principal: Principal = Depends(require_permission("view")), db: Session = Depends(get_db)):
    ws = _get_workspace(db, workspace_id)
    if module_id not in (ws.module_ids or []):
        raise HTTPException(status_code=404, detail=f"Module '{module_id}' is not part of this workspace")
    info = _resolve_module(db, module_id, principal)
    if info["kind"] == "workshop":
        mod = db.get(apps.WorkshopModule, module_id)
        resolved = workshop_runtime._resolve_variables(db, mod.variables or {}, body.state, mod.project_id)
        widgets = [workshop_runtime._render_widget(db, w, resolved, mod.project_id) for w in (mod.widgets or [])]
        return {**info, "rendered": {"variables": resolved, "widgets": widgets}}
    if info["kind"] == "slate":
        app_ = db.get(apps.SlateApp, module_id)
        rq, rf = slate_runtime._resolve_all(db, app_, body.state)
        widgets = slate_runtime.render_widgets(app_.widgets or {}, rq, rf)
        return {**info, "rendered": {"queries": rq, "functions": rf, "widgets": widgets}}
    if not info["exists"]:
        raise HTTPException(status_code=404, detail=f"Module '{module_id}' could not be resolved")
    return {**info, "rendered": None}


@router.post("/apps/carbon/{workspace_id}/navigate")
def navigate(workspace_id: str, body: NavigateRequest, principal: Principal = Depends(require_permission("view")), db: Session = Depends(get_db)):
    """
    Typed navigation between two modules in a workspace.

    Resolves the *source* module's typed output values (delegating to the Workshop
    or Slate runtime), then maps each requested `source_output` onto the named
    `target_input` of the destination module. Returns the typed inputs the caller
    should pass to the target module (e.g. as the next module's `state`).
    """
    ws = _get_workspace(db, workspace_id)
    members = ws.module_ids or []
    if body.from_module_id not in members:
        raise HTTPException(
            status_code=404,
            detail=f"Source module '{body.from_module_id}' is not part of this workspace",
        )
    if body.to_module_id not in members:
        raise HTTPException(
            status_code=404,
            detail=f"Target module '{body.to_module_id}' is not part of this workspace",
        )

    from_kind, outputs = _module_outputs(db, body.from_module_id, body.state, principal)
    if outputs is None:
        raise HTTPException(
            status_code=400,
            detail=f"Source module '{body.from_module_id}' (kind={from_kind}) exposes no resolvable outputs",
        )

    target_kind = _resolve_module(db, body.to_module_id, principal)["kind"]

    typed_inputs: Dict[str, Any] = {}
    bindings: List[Dict[str, Any]] = []
    unresolved: List[str] = []
    for b in body.output_bindings:
        if b.source_output in outputs:
            value = outputs[b.source_output]
            typed_inputs[b.target_input] = value
            bindings.append({
                "source_output": b.source_output,
                "target_input": b.target_input,
                "type": _value_type(value),
                "resolved": True,
            })
        else:
            unresolved.append(b.source_output)
            bindings.append({
                "source_output": b.source_output,
                "target_input": b.target_input,
                "type": "null",
                "resolved": False,
            })

    return {
        "workspace_id": workspace_id,
        "from_module_id": body.from_module_id,
        "from_kind": from_kind,
        "to_module_id": body.to_module_id,
        "to_kind": target_kind,
        "typed_inputs": typed_inputs,
        "bindings": bindings,
        "unresolved": unresolved,
        "available_outputs": sorted(outputs.keys()),
    }

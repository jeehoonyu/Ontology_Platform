"""
Ontology SDK (OSDK) — richer typed client generation (deep-fidelity pass 10).
Based on /docs/foundry/ontology-sdk: the OSDK generates typed object types
(properties), link traversal, Actions (with parameters), Functions/Queries, and
object-set operations. This emits a deterministic TypeScript + Python client
descriptor covering all of those. Additive; deterministic; local.
"""
from typing import Optional, List, Any, Dict

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from pydantic import BaseModel, Field

from .database import get_db
from . import models

router = APIRouter(tags=["osdk_ops"])

_TS = {"string": "string", "integer": "number", "number": "number", "double": "number",
       "long": "number", "boolean": "boolean", "geometry": "GeoJSON", "json": "unknown",
       "array": "unknown[]", "struct": "Record<string, unknown>", "timestamp": "string", "date": "string"}
_PY = {"string": "str", "integer": "int", "number": "float", "double": "float", "long": "int",
       "boolean": "bool", "geometry": "dict", "json": "Any", "array": "list", "struct": "dict",
       "timestamp": "str", "date": "str"}


def _t(definition: Any, table: Dict[str, str]) -> str:
    if isinstance(definition, dict):
        base = definition.get("type", "any")
    else:
        base = definition
    return table.get(str(base), table.get("json"))


class GenerateClientRequest(BaseModel):
    object_type_ids: Optional[List[str]] = None
    language: str = "both"  # typescript | python | both


@router.post("/osdk/generate-client")
def generate_client(body: GenerateClientRequest, db: Session = Depends(get_db)):
    q = db.query(models.ObjectType)
    if body.object_type_ids:
        q = q.filter(models.ObjectType.id.in_(body.object_type_ids))
    object_types = q.all()
    ot_ids = {o.id for o in object_types}
    link_types = db.query(models.LinkType).all()
    action_types = db.query(models.ActionType).all()
    try:
        from . import ontology_functions as _of
        functions = db.query(_of.OntologyFunction).all()
    except Exception:
        functions = []

    def pascal(s: str) -> str:
        return "".join(p.capitalize() for p in str(s).replace("-", "_").split("_"))

    sdk = []
    for ot in object_types:
        props = ot.properties or {}
        ts_props = "\n".join(f"  {k}: {_t(v, _TS)};" for k, v in props.items())
        py_props = "\n".join(f"    {k}: {_t(v, _PY)}" for k, v in props.items()) or "    pass"
        # link traversal methods originating from this object type
        links = [lt for lt in link_types if lt.source_object_type_id == ot.id and lt.target_object_type_id in ot_ids]
        link_methods_ts = "\n".join(
            f"  {lt.id}(): ObjectSet<{pascal(lt.target_object_type_id)}>;  // {lt.cardinality}" for lt in links)
        ts = (
            f"export interface {pascal(ot.id)} {{\n{ts_props}\n}}\n\n"
            f"export interface {pascal(ot.id)}Links {{\n{link_methods_ts}\n}}\n\n"
            f"export const {pascal(ot.id)}Objects = {{\n"
            f"  where(filter: Partial<{pascal(ot.id)}>): ObjectSet<{pascal(ot.id)}>;\n"
            f"  fetchPage(opts?: {{ pageSize?: number }}): Page<{pascal(ot.id)}>;\n"
            f"  aggregate(op: 'count'|'sum'|'avg'|'min'|'max', property?: keyof {pascal(ot.id)}): number;\n"
            f"}};"
        )
        py = (
            f"@dataclass\nclass {pascal(ot.id)}:\n{py_props}\n\n"
            f"class {pascal(ot.id)}ObjectSet:\n"
            f"    def where(self, **filters) -> '{pascal(ot.id)}ObjectSet': ...\n"
            f"    def fetch_page(self, page_size: int = 50) -> list['{pascal(ot.id)}']: ...\n"
            f"    def aggregate(self, op: str, prop: str | None = None) -> float: ..."
        )
        sdk.append({"name": pascal(ot.id), "object_type_id": ot.id,
                    "properties": list(props.keys()),
                    "links": [{"name": lt.id, "target": lt.target_object_type_id, "cardinality": lt.cardinality} for lt in links],
                    "typescript": ts, "python": py})

    actions = [{
        "name": pascal(at.id), "action_type_id": at.id,
        "parameters": list((at.parameters or {}).keys()),
        "typescript": f"export function applyAction_{at.id}(params: {{ {', '.join(f'{p}: unknown' for p in (at.parameters or {}).keys())} }}): ActionResult;",
        "python": f"def apply_action_{at.id}(" + ", ".join(f"{p}=None" for p in (at.parameters or {}).keys()) + ") -> dict: ...",
    } for at in action_types]

    fns = [{
        "name": pascal(getattr(fn, "id", "")), "function_id": fn.id,
        "kind": getattr(fn, "kind", "query"), "object_type_id": getattr(fn, "object_type_id", None),
        "typescript": f"export function {fn.id}(inputs?: Record<string, unknown>): unknown;",
        "python": f"def {fn.id}(inputs: dict | None = None): ...",
    } for fn in functions]

    return {
        "object_type_count": len(sdk), "action_count": len(actions), "function_count": len(fns),
        "sdk": sdk, "actions": actions, "functions": fns,
        "preamble_ts": "// Generated OSDK client — types based on the relevant Ontology subset\n"
                       "type ObjectSet<T> = { data: T[] }; type Page<T> = { data: T[]; nextPageToken?: string };\n"
                       "type GeoJSON = { type: string; coordinates: unknown }; type ActionResult = { editedObjectIds: string[] };",
    }

"""
Palantir MCP — callable tool surface (AIP).

The base platform only exposed ``/mcp/context`` (a read-only export). This adds an
actual Model-Context-Protocol-style tool catalog and dispatch, reusing existing
ontology / object-set / dataset machinery:

  * search_foundry_ontology         — find object/link types by keyword
  * query_foundry_objects           — filter object instances of a type
  * aggregate_foundry_objects       — group-by count / sum over a property
  * run_sql_query_on_foundry_dataset— SELECT / WHERE / GROUP BY over a dataset's rows
  * create_or_update_foundry_object_type — UPSERT, gated behind a PROPOSAL unless committed

Mutating tools stage a PROPOSAL (returned, not applied) unless the call sets
``commit: true`` — mirroring MCP's global-branch / staging gate. Deterministic; local.
Prefix: Mcp / mcp_.
"""
import time
import uuid
from typing import Optional, List, Any, Dict

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import String, Integer, JSON
from sqlalchemy.orm import Mapped, mapped_column, Session
from pydantic import BaseModel, Field

from .database import Base, get_db
from . import models, runtime

router = APIRouter(tags=["mcp_tools"])


def _now() -> int:
    return int(time.time())


class McpProposal(Base):
    __tablename__ = "mcp_proposals"
    id: Mapped[str] = mapped_column(String, primary_key=True, index=True)
    tool: Mapped[str] = mapped_column(String)
    arguments: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String, default="staged")  # staged | committed
    created_at: Mapped[int] = mapped_column(Integer)


# ---------------------------------------------------------------------------
# Tool catalog
# ---------------------------------------------------------------------------

_TOOLS: List[Dict[str, Any]] = [
    {"name": "search_foundry_ontology", "description": "Search object and link types by keyword.",
     "input_schema": {"keyword": "string"}},
    {"name": "query_foundry_objects", "description": "Filter object instances of a type.",
     "input_schema": {"object_type_id": "string", "filters": "object?"}},
    {"name": "aggregate_foundry_objects", "description": "Group-by count/sum over a property.",
     "input_schema": {"object_type_id": "string", "group_by": "string", "metric": "string?", "agg": "string?"}},
    {"name": "run_sql_query_on_foundry_dataset", "description": "SELECT/WHERE/GROUP BY over a dataset's rows.",
     "input_schema": {"dataset_id": "string", "select": "array?", "where": "object?",
                      "group_by": "string?", "aggregate": "object?"}},
    {"name": "create_or_update_foundry_object_type", "description": "Upsert an object type (staged as a proposal unless commit=true).",
     "input_schema": {"id": "string", "display_name": "string", "properties": "object"},
     "mutating": True},
]
_MUTATING = {t["name"] for t in _TOOLS if t.get("mutating")}
_TOOL_NAMES = {t["name"] for t in _TOOLS}


class McpCallRequest(BaseModel):
    arguments: Dict[str, Any] = Field(default_factory=dict)
    commit: bool = False


# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------

def _is_num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _t_search(db: Session, args: Dict[str, Any]) -> Dict[str, Any]:
    kw = str(args.get("keyword", "")).lower()
    ots = [ot for ot in db.query(models.ObjectType).all()
           if kw in ot.id.lower() or kw in (ot.display_name or "").lower()]
    lts = [lt for lt in db.query(models.LinkType).all()
           if kw in lt.id.lower() or kw in (getattr(lt, "display_name", "") or "").lower()]
    return {"object_types": [{"id": o.id, "display_name": o.display_name} for o in ots],
            "link_types": [{"id": l.id} for l in lts]}


def _t_query(db: Session, args: Dict[str, Any]) -> Dict[str, Any]:
    otid = args.get("object_type_id")
    if not db.query(models.ObjectType).filter(models.ObjectType.id == otid).first():
        raise HTTPException(status_code=404, detail=f"ObjectType '{otid}' not found")
    rows, _ = runtime._logic_object_rows(db, otid, args.get("filters") or {}, limit=10 ** 9)
    return {"object_type_id": otid, "count": len(rows),
            "objects": [{"id": r.id, "properties": r.properties or {}} for r in rows]}


def _t_aggregate(db: Session, args: Dict[str, Any]) -> Dict[str, Any]:
    otid = args.get("object_type_id")
    if not db.query(models.ObjectType).filter(models.ObjectType.id == otid).first():
        raise HTTPException(status_code=404, detail=f"ObjectType '{otid}' not found")
    rows, _ = runtime._logic_object_rows(db, otid, args.get("filters") or {}, limit=10 ** 9)
    group_by = args.get("group_by")
    metric = args.get("metric")
    agg = (args.get("agg") or "count").lower()
    groups: Dict[str, Dict[str, Any]] = {}
    for r in rows:
        props = r.properties or {}
        key = str(props.get(group_by))
        g = groups.setdefault(key, {"count": 0, "_vals": []})
        g["count"] += 1
        if metric and _is_num(props.get(metric)):
            g["_vals"].append(props[metric])
    out = []
    for k, g in sorted(groups.items()):
        entry = {"group": k, "count": g["count"]}
        if metric:
            vals = g["_vals"]
            if agg == "sum":
                entry["value"] = round(sum(vals), 6)
            elif agg == "avg":
                entry["value"] = round(sum(vals) / len(vals), 6) if vals else None
            elif agg in ("min", "max"):
                entry["value"] = (min(vals) if agg == "min" else max(vals)) if vals else None
        out.append(entry)
    return {"object_type_id": otid, "group_by": group_by, "groups": out}


def _t_sql(db: Session, args: Dict[str, Any]) -> Dict[str, Any]:
    asset = db.query(models.DataAsset).filter(models.DataAsset.id == args.get("dataset_id")).first()
    if not asset:
        raise HTTPException(status_code=404, detail=f"DataAsset '{args.get('dataset_id')}' not found")
    rows = list(asset.records or [])
    where = args.get("where") or {}
    rows = [r for r in rows if all(r.get(k) == v for k, v in where.items())]
    group_by = args.get("group_by")
    aggregate = args.get("aggregate") or {}
    if group_by:
        groups: Dict[str, List[dict]] = {}
        for r in rows:
            groups.setdefault(str(r.get(group_by)), []).append(r)
        result = []
        for k, grp in sorted(groups.items()):
            entry = {group_by: k, "count": len(grp)}
            field = aggregate.get("field")
            func = (aggregate.get("func") or "").lower()
            if field and func:
                vals = [g[field] for g in grp if _is_num(g.get(field))]
                if func == "sum":
                    entry[f"{func}_{field}"] = round(sum(vals), 6)
                elif func == "avg":
                    entry[f"{func}_{field}"] = round(sum(vals) / len(vals), 6) if vals else None
                elif func in ("min", "max"):
                    entry[f"{func}_{field}"] = (min(vals) if func == "min" else max(vals)) if vals else None
            result.append(entry)
        return {"dataset_id": asset.id, "grouped": True, "rows": result}
    select = args.get("select")
    if select:
        rows = [{k: r.get(k) for k in select} for r in rows]
    return {"dataset_id": asset.id, "grouped": False, "row_count": len(rows), "rows": rows}


def _t_upsert_object_type(db: Session, args: Dict[str, Any]) -> Dict[str, Any]:
    otid = args.get("id")
    if not otid:
        raise HTTPException(status_code=422, detail="id is required")
    now = _now()
    existing = db.query(models.ObjectType).filter(models.ObjectType.id == otid).first()
    if existing:
        existing.display_name = args.get("display_name", existing.display_name)
        existing.properties = args.get("properties", existing.properties)
        existing.updated_at = now
        action = "updated"
    else:
        db.add(models.ObjectType(id=otid, display_name=args.get("display_name", otid),
                                 description=args.get("description", ""),
                                 properties=args.get("properties", {}), created_at=now, updated_at=now))
        action = "created"
    db.commit()
    return {"object_type_id": otid, "action": action}


_DISPATCH = {
    "search_foundry_ontology": _t_search,
    "query_foundry_objects": _t_query,
    "aggregate_foundry_objects": _t_aggregate,
    "run_sql_query_on_foundry_dataset": _t_sql,
    "create_or_update_foundry_object_type": _t_upsert_object_type,
}


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/mcp/tools")
def list_tools():
    return {"tools": _TOOLS}


@router.post("/mcp/tools/{name}/call")
def call_tool(name: str, body: McpCallRequest, db: Session = Depends(get_db)):
    if name not in _TOOL_NAMES:
        raise HTTPException(status_code=404, detail=f"unknown MCP tool '{name}'")
    # Proposal gate: mutating tools stage a proposal unless explicitly committed.
    if name in _MUTATING and not body.commit:
        pid = uuid.uuid4().hex
        db.add(McpProposal(id=pid, tool=name, arguments=body.arguments, status="staged", created_at=_now()))
        db.commit()
        return {"staged": True, "proposal_id": pid, "tool": name,
                "note": "mutation staged; POST /mcp/proposals/{id}/commit or recall with commit=true"}
    result = _DISPATCH[name](db, body.arguments)
    return {"staged": False, "tool": name, "result": result}


@router.get("/mcp/proposals")
def list_proposals(db: Session = Depends(get_db)):
    return [{"id": p.id, "tool": p.tool, "status": p.status, "arguments": p.arguments}
            for p in db.query(McpProposal).order_by(McpProposal.created_at.desc()).all()]


@router.post("/mcp/proposals/{proposal_id}/commit")
def commit_proposal(proposal_id: str, db: Session = Depends(get_db)):
    p = db.query(McpProposal).filter(McpProposal.id == proposal_id).first()
    if not p:
        raise HTTPException(status_code=404, detail=f"proposal '{proposal_id}' not found")
    if p.status == "committed":
        raise HTTPException(status_code=400, detail="proposal already committed")
    result = _DISPATCH[p.tool](db, p.arguments)
    p.status = "committed"
    db.commit()
    return {"committed": True, "proposal_id": proposal_id, "tool": p.tool, "result": result}

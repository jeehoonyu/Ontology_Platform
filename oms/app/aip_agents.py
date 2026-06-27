"""
AIP Agent Studio — faithful tool-calling + retrieval (deep-fidelity pass 3).

The base platform's agent sessions keyword-match allowed actions and build a
context pack. This module adds the documented Agent Studio model: an agent is
configured with **tools** (Object Query, Action, Function, Command) and
**retrieval context** (ontology + documents), and an `invoke` call deterministically
selects and executes the relevant tools, producing a tool-call trace, proposed
actions, and a grounded answer. Additive — leaves /agents and /agents/{id}/sessions
untouched. Deterministic and local (no LLM calls).
"""
import time
import uuid
from typing import Optional, List, Any, Dict

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import String, Integer, JSON
from sqlalchemy.orm import Mapped, mapped_column, Session
from pydantic import BaseModel, ConfigDict, Field

from .database import Base, get_db
from . import models, models_action, runtime

router = APIRouter(tags=["aip_agents"])


def _now() -> int:
    return int(time.time())


# ---------------------------------------------------------------------------
# ORM models
# ---------------------------------------------------------------------------
class AgentToolConfig(Base):
    __tablename__ = "agent_tool_configs"
    agent_id: Mapped[str] = mapped_column(String, primary_key=True, index=True)
    # tools: [{name, type: object_query|action|function|command, ...config, trigger?, always?}]
    tools: Mapped[list] = mapped_column(JSON, default=list)
    # retrieval: {ontology: [object_type_ids], documents: [strings]}
    retrieval: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[int] = mapped_column(Integer)
    updated_at: Mapped[int] = mapped_column(Integer)


class AgentToolRun(Base):
    __tablename__ = "agent_tool_runs"
    id: Mapped[str] = mapped_column(String, primary_key=True, index=True)
    agent_id: Mapped[str] = mapped_column(String, index=True)
    prompt: Mapped[str] = mapped_column(String)
    tool_calls: Mapped[list] = mapped_column(JSON, default=list)
    proposed_actions: Mapped[list] = mapped_column(JSON, default=list)
    answer: Mapped[str] = mapped_column(String, default="")
    created_at: Mapped[int] = mapped_column(Integer)


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------
class ToolSpec(BaseModel):
    name: str
    type: str  # object_query | action | function | command
    object_type_id: Optional[str] = None
    filters: Dict[str, Any] = Field(default_factory=dict)
    action_type_id: Optional[str] = None
    function_id: Optional[str] = None
    command: Optional[str] = None
    response: Optional[str] = None
    trigger: Optional[str] = None       # keyword that selects this tool
    always: bool = False                # always run regardless of prompt


class ToolConfigUpsert(BaseModel):
    tools: List[ToolSpec] = Field(default_factory=list)
    retrieval: Dict[str, Any] = Field(default_factory=dict)


class ToolConfigRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    agent_id: str
    tools: List[Any]
    retrieval: Dict[str, Any]
    created_at: int
    updated_at: int


class InvokeRequest(BaseModel):
    prompt: str
    parameters: Dict[str, Any] = Field(default_factory=dict)
    select: Optional[List[str]] = None  # force-select tools by name


# ---------------------------------------------------------------------------
# Tool config endpoints
# ---------------------------------------------------------------------------
@router.put("/aip/agents/{agent_id}/tools", response_model=ToolConfigRead)
def configure_agent_tools(agent_id: str, body: ToolConfigUpsert, db: Session = Depends(get_db)):
    if not db.get(models.AgentDefinition, agent_id):
        raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found")
    now = _now()
    tools = [t.model_dump() for t in body.tools]
    cfg = db.get(AgentToolConfig, agent_id)
    if cfg:
        cfg.tools = tools
        cfg.retrieval = body.retrieval
        cfg.updated_at = now
    else:
        cfg = AgentToolConfig(agent_id=agent_id, tools=tools, retrieval=body.retrieval, created_at=now, updated_at=now)
        db.add(cfg)
    db.add(models_action.AuditLog(id=uuid.uuid4().hex, actor="system", event_type="aip.agent.tools_configured",
                                  subject_type="agent", subject_id=agent_id, payload={"tools": len(tools)}))
    db.commit(); db.refresh(cfg)
    return cfg


@router.get("/aip/agents/{agent_id}/tools", response_model=ToolConfigRead)
def get_agent_tools(agent_id: str, db: Session = Depends(get_db)):
    cfg = db.get(AgentToolConfig, agent_id)
    if not cfg:
        raise HTTPException(status_code=404, detail="No tool config for this agent")
    return cfg


# ---------------------------------------------------------------------------
# Tool execution helpers
# ---------------------------------------------------------------------------
def _aggregate(instances, op: str, field: Optional[str]) -> Any:
    nums = [
        (i.properties or {}).get(field)
        for i in instances
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


def _run_tool(db: Session, tool: Dict[str, Any], prompt: str, parameters: Dict[str, Any]) -> Dict[str, Any]:
    ttype = tool.get("type")
    if ttype == "object_query":
        rows, count = runtime._logic_object_rows(db, tool.get("object_type_id"), tool.get("filters", {}), 50)
        return {"object_type_id": tool.get("object_type_id"), "count": count,
                "rows": [{"id": r.id, "properties": r.properties} for r in rows]}
    if ttype == "function":
        from . import ontology_functions as _of
        fn = db.get(_of.OntologyFunction, tool.get("function_id"))
        if not fn:
            return {"error": f"function '{tool.get('function_id')}' not found"}
        insts = db.query(models.ObjectInstance).filter(models.ObjectInstance.object_type_id == fn.object_type_id).all() if fn.object_type_id else []
        expr = fn.expression or {}
        return {"function_id": fn.id, "output": _aggregate(insts, expr.get("op", "count"), expr.get("field"))}
    if ttype == "action":
        action = db.get(models.ActionType, tool.get("action_type_id"))
        if not action:
            return {"error": f"action '{tool.get('action_type_id')}' not found"}
        # resolve params from request parameters by matching names
        resolved = {k: parameters.get(k) for k in (action.parameters or {}).keys()}
        return {"action_type_id": action.id, "display_name": action.display_name, "parameters": resolved,
                "staged": True, "requires_approval": bool((action.rules or {}).get("requires_approval"))}
    if ttype == "command":
        return {"command": tool.get("command"), "response": tool.get("response", "ok")}
    return {"error": f"unknown tool type '{ttype}'"}


def _select(tool: Dict[str, Any], prompt_lc: str, select: Optional[List[str]]) -> bool:
    if select is not None:
        return tool.get("name") in select
    if tool.get("always"):
        return True
    trigger = (tool.get("trigger") or tool.get("name") or "").lower()
    keys = {trigger, str(tool.get("object_type_id") or "").lower(), str(tool.get("action_type_id") or "").lower()}
    return any(k and k in prompt_lc for k in keys)


@router.post("/aip/agents/{agent_id}/invoke")
def invoke_agent(agent_id: str, body: InvokeRequest, db: Session = Depends(get_db)):
    agent = db.get(models.AgentDefinition, agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found")
    cfg = db.get(AgentToolConfig, agent_id)
    tools = (cfg.tools if cfg else []) or []
    retrieval_cfg = (cfg.retrieval if cfg else {}) or {}
    prompt_lc = body.prompt.lower()

    # 1) retrieval context
    ontology_types = retrieval_cfg.get("ontology") or agent.allowed_object_types or []
    context = runtime.build_context_pack(db, allowed_object_types=ontology_types, filters={}, limit=5) if ontology_types else {"packs": []}
    documents = retrieval_cfg.get("documents", [])
    retrieval = {
        "ontology_packs": context.get("packs", []),
        "documents": documents,
        "retrieved_object_count": sum(len(p.get("objects", [])) for p in context.get("packs", [])),
    }

    # 2) tool selection + execution
    tool_calls: List[Dict[str, Any]] = []
    proposed_actions: List[Dict[str, Any]] = []
    for tool in tools:
        if not _select(tool, prompt_lc, body.select):
            continue
        output = _run_tool(db, tool, body.prompt, body.parameters)
        tool_calls.append({"tool": tool.get("name"), "type": tool.get("type"), "output": output})
        if tool.get("type") == "action" and output.get("staged"):
            proposed_actions.append({"action_type_id": output["action_type_id"], "parameters": output["parameters"],
                                     "requires_approval": output["requires_approval"]})

    # 3) grounded deterministic answer
    answer = (
        f"Agent '{agent.display_name}' handled the request using {len(tool_calls)} tool(s): "
        + ", ".join(tc["tool"] for tc in tool_calls)
        + f". Retrieved {retrieval['retrieved_object_count']} ontology object(s)."
        + (f" Proposed {len(proposed_actions)} action(s) for review." if proposed_actions else "")
    )

    run = AgentToolRun(id=uuid.uuid4().hex, agent_id=agent_id, prompt=body.prompt,
                       tool_calls=tool_calls, proposed_actions=proposed_actions, answer=answer, created_at=_now())
    db.add(run)
    db.add(models_action.AuditLog(id=uuid.uuid4().hex, actor="system", event_type="aip.agent.invoked",
                                  subject_type="agent", subject_id=agent_id, payload={"tools_used": len(tool_calls)}))
    db.commit()
    return {"agent_id": agent_id, "prompt": body.prompt, "retrieval": retrieval,
            "tool_calls": tool_calls, "proposed_actions": proposed_actions, "answer": answer, "run_id": run.id}

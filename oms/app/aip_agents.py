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
from . import models, models_action, ops_control, platform_runtime, runtime, tenancy
from .production_auth import Principal, require_permission

router = APIRouter(tags=["aip_agents"])


def _now() -> int:
    return int(time.time())


def _agent_for(db: Session, agent_id: str, principal: Principal, permission: str):
    agent = db.get(models.AgentDefinition, agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found")
    tenancy.assert_project_permission(db, principal, agent.project_id, permission)
    return agent


def _object_type_project_id(db: Session, object_type_id: str) -> str:
    object_type = db.get(models.ObjectType, object_type_id)
    if not object_type:
        raise HTTPException(status_code=404, detail=f"Object type '{object_type_id}' not found")
    return str(((object_type.properties or {}).get("__manager") or {}).get("project_id") or "default")


def _assert_tool_resources(db: Session, project_id: str, tools: List[Dict[str, Any]], retrieval: Dict[str, Any]) -> None:
    object_type_ids = {str(value) for value in (retrieval.get("ontology") or []) if value}
    for tool in tools:
        if tool.get("object_type_id"):
            object_type_ids.add(str(tool["object_type_id"]))
        action_type_id = tool.get("action_type_id")
        if action_type_id:
            action = db.get(models.ActionType, str(action_type_id))
            if not action:
                raise HTTPException(status_code=404, detail=f"Action type '{action_type_id}' not found")
            if action.project_id != project_id:
                raise HTTPException(status_code=403, detail="Agent tool action belongs to another project")
    for object_type_id in sorted(object_type_ids):
        if _object_type_project_id(db, object_type_id) != project_id:
            raise HTTPException(status_code=403, detail="Agent tool object type belongs to another project")


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
    retrieval: Mapped[dict] = mapped_column(JSON, default=dict)
    policy_summary: Mapped[dict] = mapped_column(JSON, default=dict)
    execution_job_id: Mapped[Optional[str]] = mapped_column(String, nullable=True, unique=True, index=True)
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


class AsyncInvokeRequest(InvokeRequest):
    priority: int = Field(default=60, ge=0, le=100)
    max_attempts: int = Field(default=3, ge=1, le=20)
    timeout_seconds: int = Field(default=300, ge=1, le=86400)
    idempotency_key: Optional[str] = Field(default=None, min_length=1, max_length=200)


class AgentWorkerRunRequest(BaseModel):
    worker_id: str = Field(default="aip-agent-worker", min_length=1, max_length=200)
    lease_seconds: int = Field(default=60, ge=10, le=900)
    job_id: Optional[str] = None


# ---------------------------------------------------------------------------
# Tool config endpoints
# ---------------------------------------------------------------------------
@router.put("/aip/agents/{agent_id}/tools", response_model=ToolConfigRead)
def configure_agent_tools(agent_id: str, body: ToolConfigUpsert, principal: Principal = Depends(require_permission("edit")), db: Session = Depends(get_db)):
    agent = _agent_for(db, agent_id, principal, "edit")
    now = _now()
    tools = [t.model_dump() for t in body.tools]
    _assert_tool_resources(db, agent.project_id, tools, body.retrieval)
    cfg = db.get(AgentToolConfig, agent_id)
    if cfg:
        cfg.tools = tools
        cfg.retrieval = body.retrieval
        cfg.updated_at = now
    else:
        cfg = AgentToolConfig(agent_id=agent_id, tools=tools, retrieval=body.retrieval, created_at=now, updated_at=now)
        db.add(cfg)
    db.add(models_action.AuditLog(id=uuid.uuid4().hex, actor=principal.id, event_type="aip.agent.tools_configured",
                                  subject_type="agent", subject_id=agent_id, payload={"project_id": agent.project_id, "tools": len(tools)}))
    db.commit(); db.refresh(cfg)
    return cfg


@router.get("/aip/agents/{agent_id}/tools", response_model=ToolConfigRead)
def get_agent_tools(agent_id: str, principal: Principal = Depends(require_permission("view")), db: Session = Depends(get_db)):
    _agent_for(db, agent_id, principal, "view")
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
        validation_errors = runtime.validate_action_parameters(action, resolved)
        rules = action.rules or {}
        return {"action_type_id": action.id, "display_name": action.display_name, "parameters": resolved,
                "staged": not validation_errors, "validation_errors": validation_errors,
                "requires_approval": bool(
                    rules.get("requires_approval")
                    or rules.get("approval_required")
                    or str(rules.get("risk_level", "")).lower() in {"high", "critical"}
                )}
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


def _tool_citations(tool: Dict[str, Any], output: Dict[str, Any]) -> List[Dict[str, str]]:
    tool_type = tool.get("type")
    if tool_type == "object_query":
        return [
            {"type": "ontology_object", "id": str(row.get("id"))}
            for row in (output.get("rows") or [])[:10]
            if row.get("id")
        ]
    if tool_type == "function" and output.get("function_id"):
        return [{"type": "ontology_function", "id": str(output["function_id"])}]
    if tool_type == "action" and output.get("action_type_id"):
        return [{"type": "action_type", "id": str(output["action_type_id"])}]
    return [{"type": "agent_tool", "id": str(tool.get("name") or tool_type or "tool")}]


def _run_dict(run: AgentToolRun) -> Dict[str, Any]:
    return {
        "agent_id": run.agent_id,
        "prompt": run.prompt,
        "retrieval": run.retrieval or {},
        "tool_calls": run.tool_calls or [],
        "proposed_actions": run.proposed_actions or [],
        "policy_summary": run.policy_summary or {},
        "answer": run.answer,
        "run_id": run.id,
        "execution_job_id": run.execution_job_id,
        "created_at": run.created_at,
    }


def _invoke_agent(
    agent_id: str,
    body: InvokeRequest,
    db: Session,
    *,
    actor: str = "system",
    execution_job_id: Optional[str] = None,
    execution_lease_token: Optional[str] = None,
    expected_project_id: Optional[str] = None,
) -> Dict[str, Any]:
    if execution_job_id:
        prior = db.query(AgentToolRun).filter(AgentToolRun.execution_job_id == execution_job_id).first()
        if prior:
            return {**_run_dict(prior), "idempotent_replay": True}
    agent = db.get(models.AgentDefinition, agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found")
    if expected_project_id is not None and agent.project_id != expected_project_id:
        raise HTTPException(status_code=403, detail="Agent belongs to another project")
    cfg = db.get(AgentToolConfig, agent_id)
    tools = (cfg.tools if cfg else []) or []
    retrieval_cfg = (cfg.retrieval if cfg else {}) or {}
    _assert_tool_resources(db, agent.project_id, tools, retrieval_cfg)
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
    approval_count = 0
    denied_tools = 0
    for tool in tools:
        if not _select(tool, prompt_lc, body.select):
            continue
        started = time.perf_counter()
        output = _run_tool(db, tool, body.prompt, body.parameters)
        policy_decision = "ALLOWED"
        approval_request_id = None
        if tool.get("type") == "action" and output.get("validation_errors"):
            policy_decision = "DENIED"
            denied_tools += 1
        if tool.get("type") == "action" and output.get("staged"):
            policy_decision = "APPROVAL_REQUIRED" if output["requires_approval"] else "REVIEW_REQUIRED"
            if output["requires_approval"]:
                approval_request_id = uuid.uuid4().hex
                approval_count += 1
                db.add(models_action.ApprovalRequest(
                    id=approval_request_id,
                    project_id=agent.project_id,
                    action_type_id=output["action_type_id"],
                    requester=actor,
                    parameters=output["parameters"],
                    status=models_action.ApprovalStatus.PENDING.value,
                    reason=f"Proposed by agent {agent_id}",
                    created_at=_now(),
                ))
                db.add(models_action.AuditLog(
                    id=uuid.uuid4().hex,
                    actor=actor,
                    event_type="aip.agent.approval_requested",
                    subject_type="approval_request",
                    subject_id=approval_request_id,
                    payload={"project_id": agent.project_id, "agent_id": agent_id, "action_type_id": output["action_type_id"], "execution_job_id": execution_job_id},
                ))
                ops_control.record_ops_event(
                    db,
                    source="aip_agent",
                    event_type="aip.agent.approval_requested",
                    severity="high",
                    title=f"Agent {agent.display_name} requested action approval",
                    subject_type="approval_request",
                    subject_id=approval_request_id,
                    payload={"project_id": agent.project_id, "agent_id": agent_id, "action_type_id": output["action_type_id"], "execution_job_id": execution_job_id},
                )
            proposed_actions.append({
                "action_type_id": output["action_type_id"],
                "parameters": output["parameters"],
                "requires_approval": output["requires_approval"],
                "policy_decision": policy_decision,
                "approval_request_id": approval_request_id,
                "executed": False,
            })
        tool_calls.append({
            "tool": tool.get("name"),
            "type": tool.get("type"),
            "input": {"prompt": body.prompt, "parameters": body.parameters},
            "output": output,
            "citations": _tool_citations(tool, output),
            "policy_decision": policy_decision,
            "approval_gate": policy_decision == "APPROVAL_REQUIRED",
            "duration_ms": max(1, round((time.perf_counter() - started) * 1000)),
        })

    # 3) grounded deterministic answer
    answer = (
        f"Agent '{agent.display_name}' handled the request using {len(tool_calls)} tool(s): "
        + ", ".join(tc["tool"] for tc in tool_calls)
        + f". Retrieved {retrieval['retrieved_object_count']} ontology object(s)."
        + (f" Proposed {len(proposed_actions)} action(s) for review." if proposed_actions else "")
    )

    policy_summary = {
        "decision": "DENIED" if denied_tools else ("APPROVAL_REQUIRED" if approval_count else ("REVIEW_REQUIRED" if proposed_actions else "ALLOWED")),
        "approval_requests": approval_count,
        "proposed_actions": len(proposed_actions),
        "denied_tools": denied_tools,
        "direct_mutations": 0,
    }
    run = AgentToolRun(
        id=uuid.uuid4().hex,
        agent_id=agent_id,
        prompt=body.prompt,
        tool_calls=tool_calls,
        proposed_actions=proposed_actions,
        retrieval=retrieval,
        policy_summary=policy_summary,
        execution_job_id=execution_job_id,
        answer=answer,
        created_at=_now(),
    )
    db.add(run)
    db.add(models_action.AuditLog(id=uuid.uuid4().hex, actor=actor, event_type="aip.agent.invoked",
                                  subject_type="agent", subject_id=agent_id, payload={"project_id": agent.project_id, "tools_used": len(tool_calls), "run_id": run.id, "execution_job_id": execution_job_id, "policy_summary": policy_summary}))
    if execution_job_id:
        db.flush()
        active_job = db.query(platform_runtime.PlatformJob).filter(platform_runtime.PlatformJob.id == execution_job_id).with_for_update().first()
        active_lease = db.query(platform_runtime.PlatformJobLease).filter(platform_runtime.PlatformJobLease.job_id == execution_job_id).with_for_update().first()
        if not active_job or active_job.status != "RUNNING" or not active_lease or active_lease.token != execution_lease_token:
            db.rollback()
            raise HTTPException(status_code=409, detail="Agent invocation was cancelled or lost its execution lease before commit")
    db.commit()
    return {**_run_dict(run), "idempotent_replay": False}


@router.post("/aip/agents/{agent_id}/invoke")
def invoke_agent(agent_id: str, body: InvokeRequest, principal: Principal = Depends(require_permission("execute")), db: Session = Depends(get_db)):
    agent = _agent_for(db, agent_id, principal, "execute")
    return _invoke_agent(agent_id, body, db, actor=principal.id, expected_project_id=agent.project_id)


@router.post("/aip/agents/{agent_id}/invoke/async", status_code=202)
def enqueue_agent_invocation(
    agent_id: str,
    body: AsyncInvokeRequest,
    principal: Principal = Depends(require_permission("execute")),
    db: Session = Depends(get_db),
):
    agent = _agent_for(db, agent_id, principal, "execute")
    return platform_runtime.create_job(platform_runtime.JobCreate(
        project_id=agent.project_id,
        job_type="aip.agent.invoke",
        subject_type="agent",
        subject_id=agent_id,
        payload={
            "agent_id": agent_id,
            "prompt": body.prompt,
            "parameters": body.parameters,
            "select": body.select,
        },
        priority=body.priority,
        max_attempts=body.max_attempts,
        timeout_seconds=body.timeout_seconds,
        idempotency_key=body.idempotency_key,
    ), principal, db)


@router.post("/aip/agents/workers/run-next")
def run_next_agent_job(
    body: AgentWorkerRunRequest = AgentWorkerRunRequest(),
    principal: Principal = Depends(require_permission("execute")),
    db: Session = Depends(get_db),
):
    from . import worker_control
    supported_job_types = worker_control.effective_worker_job_types(
        db, principal, body.worker_id, ["aip.agent.invoke"],
    )
    claimed = platform_runtime.claim_job(platform_runtime.JobClaimRequest(
        worker_id=body.worker_id,
        supported_job_types=supported_job_types,
        lease_seconds=body.lease_seconds,
        job_id=body.job_id,
    ), principal, db).get("job")
    if not claimed:
        return {"job": None, "result": None}
    job_id = str(claimed["id"])
    lease_token = str(claimed["lease_token"])
    payload = dict(claimed.get("payload") or {})
    try:
        platform_runtime.heartbeat_job(job_id, platform_runtime.JobHeartbeatRequest(
            lease_token=lease_token,
            progress=15,
            message="Agent context loaded; selecting governed tools",
            metrics={"agent_id": payload.get("agent_id")},
            lease_seconds=body.lease_seconds,
        ), principal, db)
        result = _invoke_agent(
            str(payload.get("agent_id") or claimed.get("subject_id") or ""),
            InvokeRequest(
                prompt=str(payload.get("prompt") or ""),
                parameters=dict(payload.get("parameters") or {}),
                select=payload.get("select"),
            ),
            db,
            actor=principal.id,
            execution_job_id=job_id,
            execution_lease_token=lease_token,
            expected_project_id=str(claimed.get("project_id") or "default"),
        )
        db.expire_all()
        current = db.get(platform_runtime.PlatformJob, job_id)
        if current and current.status == "CANCELLED":
            return {"job": platform_runtime.get_job(job_id, principal, db), "result": None}
        completed = platform_runtime.complete_job(job_id, platform_runtime.JobCompleteRequest(
            lease_token=lease_token,
            result=result,
        ), principal, db)
        return {"job": completed, "result": result}
    except HTTPException as exc:
        db.rollback()
        current = db.get(platform_runtime.PlatformJob, job_id)
        if not current or current.status != "RUNNING":
            return {"job": platform_runtime.get_job(job_id, principal, db) if current else None, "result": None}
        failed = platform_runtime.fail_job(job_id, platform_runtime.JobFailRequest(
            lease_token=lease_token,
            error=str(exc.detail),
            retriable=exc.status_code >= 500,
            details={"status_code": exc.status_code},
        ), principal, db)
        return {"job": failed, "result": None}
    except Exception as exc:
        db.rollback()
        current = db.get(platform_runtime.PlatformJob, job_id)
        if not current or current.status != "RUNNING":
            return {"job": platform_runtime.get_job(job_id, principal, db) if current else None, "result": None}
        failed = platform_runtime.fail_job(job_id, platform_runtime.JobFailRequest(
            lease_token=lease_token,
            error=str(exc),
            retriable=True,
            details={"exception_type": type(exc).__name__},
        ), principal, db)
        return {"job": failed, "result": None}


@router.get("/aip/agents/{agent_id}/runs")
def list_agent_runs(
    agent_id: str,
    limit: int = 50,
    principal: Principal = Depends(require_permission("view")),
    db: Session = Depends(get_db),
):
    _agent_for(db, agent_id, principal, "view")
    rows = db.query(AgentToolRun).filter(AgentToolRun.agent_id == agent_id).order_by(AgentToolRun.created_at.desc()).limit(max(1, min(limit, 200))).all()
    return [_run_dict(row) for row in rows]

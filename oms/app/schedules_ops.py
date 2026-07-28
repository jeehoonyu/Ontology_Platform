"""
Schedules — cron-due evaluation & compound trigger engine
(deep-fidelity pass 9). Based on the documented trigger types reference
(/docs/foundry/building-pipelines/triggers-reference): time (cron), event
(new transaction), job-succeeded, schedule-succeeded, manual, and compound
AND / OR triggers. Additive; deterministic; local.
"""
import time
from typing import Optional, List, Any, Dict

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel, Field

from .database import get_db
from . import production_auth, schedules as _schedules, semantic_scope

router = APIRouter(tags=["schedules_ops"])


# ---------------------------------------------------------------------------
# Cron matching (standard 5-field Unix cron)
# ---------------------------------------------------------------------------
def _cron_field(expr: str, lo: int, hi: int) -> set:
    values: set = set()
    for part in str(expr).split(","):
        step = 1
        token = part
        if "/" in token:
            token, step_s = token.split("/")
            step = int(step_s)
        if token == "*":
            rng = range(lo, hi + 1)
        elif "-" in token:
            a, b = token.split("-")
            rng = range(int(a), int(b) + 1)
        else:
            v = int(token)
            rng = range(v, v + 1)
        for v in rng:
            if (v - lo) % step == 0:
                values.add(v)
    return values


def cron_due(cron: str, timestamp: int) -> Dict[str, Any]:
    fields = cron.split()
    if len(fields) != 5:
        raise HTTPException(status_code=422, detail="cron must have 5 fields: min hour dom month dow")
    tm = time.gmtime(timestamp)
    minute, hour, dom, month = tm.tm_min, tm.tm_hour, tm.tm_mday, tm.tm_mon
    cron_dow = (tm.tm_wday + 1) % 7  # Python Mon=0..Sun=6 -> cron Sun=0..Sat=6
    m = minute in _cron_field(fields[0], 0, 59)
    h = hour in _cron_field(fields[1], 0, 23)
    mon = month in _cron_field(fields[3], 1, 12)
    dom_star = fields[2].strip() == "*"
    dow_star = fields[4].strip() == "*"
    dom_match = dom in _cron_field(fields[2], 1, 31)
    dow_match = cron_dow in _cron_field(fields[4], 0, 6)
    # standard cron day semantics: AND when one is '*', else OR
    if dom_star and dow_star:
        day = True
    elif dom_star:
        day = dow_match
    elif dow_star:
        day = dom_match
    else:
        day = dom_match or dow_match
    due = bool(m and h and mon and day)
    return {"due": due, "matched": {"minute": m, "hour": h, "month": mon, "day": day},
            "utc": time.strftime("%Y-%m-%d %H:%M UTC", tm)}


# ---------------------------------------------------------------------------
# Trigger evaluation (recursive, with compound AND/OR)
# ---------------------------------------------------------------------------
def evaluate_trigger(trigger: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
    ttype = trigger.get("type")
    if ttype == "time":
        ts = context.get("timestamp")
        if ts is None:
            return {"type": ttype, "satisfied": False, "reason": "no timestamp in context"}
        res = cron_due(trigger.get("cron", "* * * * *"), int(ts))
        return {"type": ttype, "cron": trigger.get("cron"), "satisfied": res["due"], "detail": res["matched"]}
    if ttype == "event":
        ev = trigger.get("event")
        sat = ev in set(context.get("events", []))
        return {"type": ttype, "event": ev, "satisfied": sat}
    if ttype == "job_succeeded":
        job = trigger.get("job")
        return {"type": ttype, "job": job, "satisfied": job in set(context.get("succeeded_jobs", []))}
    if ttype == "schedule_succeeded":
        sch = trigger.get("schedule")
        return {"type": ttype, "schedule": sch, "satisfied": sch in set(context.get("succeeded_schedules", []))}
    if ttype == "manual":
        return {"type": ttype, "satisfied": bool(context.get("manual"))}
    if ttype in ("and", "or"):
        children = [evaluate_trigger(t, context) for t in trigger.get("triggers", [])]
        if ttype == "and":
            satisfied = all(c["satisfied"] for c in children) and len(children) > 0
        else:
            satisfied = any(c["satisfied"] for c in children)
        return {"type": ttype, "satisfied": satisfied, "children": children}
    return {"type": ttype, "satisfied": False, "reason": f"unknown trigger type '{ttype}'"}


class CronDueRequest(BaseModel):
    cron: str
    timestamp: int


class TriggerRequest(BaseModel):
    trigger: Dict[str, Any]
    context: Dict[str, Any] = Field(default_factory=dict)


class ScheduleEvalRequest(BaseModel):
    context: Dict[str, Any] = Field(default_factory=dict)


@router.post("/schedules/cron-due")
def cron_due_endpoint(body: CronDueRequest, _principal: production_auth.Principal = Depends(production_auth.require_permission("view"))):
    return {"cron": body.cron, "timestamp": body.timestamp, **cron_due(body.cron, body.timestamp)}


@router.post("/schedules/evaluate-trigger")
def evaluate_trigger_endpoint(body: TriggerRequest, _principal: production_auth.Principal = Depends(production_auth.require_permission("view"))):
    return {"result": evaluate_trigger(body.trigger, body.context)}


@router.post("/schedules/{schedule_id}/evaluate")
def evaluate_schedule(schedule_id: str, body: ScheduleEvalRequest, db: Session = Depends(get_db), principal: production_auth.Principal = Depends(production_auth.require_permission("view"))):
    sched = semantic_scope.owned_row(db, principal, _schedules.Schedule, schedule_id, "view", "Schedule")
    # a compound trigger may be stored in event_input.trigger; otherwise build from trigger_type/cron
    trigger = (sched.event_input or {}).get("trigger") if isinstance(sched.event_input, dict) else None
    if not trigger:
        if sched.trigger_type == "cron":
            trigger = {"type": "time", "cron": sched.cron or "* * * * *"}
        else:
            trigger = {"type": "event", "event": (sched.event_input or {}).get("event") if isinstance(sched.event_input, dict) else sched.target_id}
    result = evaluate_trigger(trigger, body.context)
    return {"schedule_id": schedule_id, "enabled": sched.enabled, "trigger": trigger,
            "would_fire": bool(sched.enabled and result["satisfied"]), "result": result}

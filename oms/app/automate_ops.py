"""
Foundry AUTOMATE (richer): conditions, multi-effects, retries, execution settings,
manual execution, run history, lifecycle, and automation dependencies.

This is a PARALLEL, richer model set to the simple `models.AutomationDefinition`.
Every ORM class name and __tablename__ is prefixed with Atm/atm_ to avoid
collisions on the shared SQLAlchemy Base.

Docs basis: automate/{overview,condition-objects,condition-time,effect-actions,
effect-notification,effect-logic,effect-fallback,retries,history,manual-execution,
execution-settings,automation-dependencies}.

CRITIC CORRECTIONS honored:
  * The retries page does NOT document a backoff base or jitter formula. We implement
    constant + exponential backoff; the exponential base (2) and the absence of jitter
    are an IMPLEMENTATION ASSUMPTION made for determinism, NOT documented fact. See
    `_compute_retry_intervals` for the explicit comment.
  * The permission model / activity-telemetry detail pages 404'd, so permission handling
    is kept minimal and we do NOT assert any undocumented permission semantics.
"""

from .database import Base, get_db
from . import models, models_action
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import String, Integer, JSON, Boolean, Float, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, Session
from pydantic import BaseModel, ConfigDict, Field
from typing import Optional, List, Any, Dict
import time, uuid, hashlib, json

# ---------------------------------------------------------------------------
# SQLAlchemy models  (all prefixed Atm/atm_)
# ---------------------------------------------------------------------------

CONDITION_TYPES = {
    "object_count", "object_added", "object_removed", "object_modified",
    "run_on_all", "threshold_crossed", "time",
}
EFFECT_TYPES = {"action", "notification", "logic", "function", "fallback"}
SCOPE_MODES = {"user_scoped", "project_scoped"}
EXECUTION_MODES = {"sequential", "parallel"}
BACKOFF_TYPES = {"constant", "exponential"}
RUN_STATUSES = {"TRIGGERED", "SKIPPED", "SUCCEEDED", "PARTIALLY_FAILED", "FAILED"}
ACTIVITY_EVENTS = {
    "triggered", "recovered", "config_changed", "paused", "resumed",
    "muted", "unmuted", "evaluation_error", "effect_error",
}


class AtmAutomation(Base):
    __tablename__ = "atm_automations"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    display_name: Mapped[str] = mapped_column(String)
    description: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    scope_mode: Mapped[str] = mapped_column(String, default="user_scoped")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    muted: Mapped[bool] = mapped_column(Boolean, default=False)
    owner: Mapped[str] = mapped_column(String, default="system")
    created_at: Mapped[int] = mapped_column(Integer)
    updated_at: Mapped[int] = mapped_column(Integer)
    last_evaluated_at: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)


class AtmCondition(Base):
    __tablename__ = "atm_conditions"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    automation_id: Mapped[str] = mapped_column(String, ForeignKey("atm_automations.id"), index=True)
    condition_type: Mapped[str] = mapped_column(String)
    config: Mapped[dict] = mapped_column(JSON, default=dict)
    last_snapshot: Mapped[dict] = mapped_column(JSON, default=dict)
    last_state: Mapped[dict] = mapped_column(JSON, default=dict)


class AtmEffect(Base):
    __tablename__ = "atm_effects"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    automation_id: Mapped[str] = mapped_column(String, ForeignKey("atm_automations.id"), index=True)
    effect_type: Mapped[str] = mapped_column(String)
    execution_order: Mapped[int] = mapped_column(Integer, default=0)
    parent_effect_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    config: Mapped[dict] = mapped_column(JSON, default=dict)


class AtmExecSettings(Base):
    __tablename__ = "atm_exec_settings"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    automation_id: Mapped[str] = mapped_column(String, ForeignKey("atm_automations.id"), index=True)
    execution_mode: Mapped[str] = mapped_column(String, default="sequential")
    batch_size: Mapped[int] = mapped_column(Integer, default=100)
    parallelism: Mapped[int] = mapped_column(Integer, default=1)


class AtmRetryConfig(Base):
    __tablename__ = "atm_retry_configs"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    automation_id: Mapped[str] = mapped_column(String, ForeignKey("atm_automations.id"), index=True)
    max_attempts: Mapped[int] = mapped_column(Integer, default=1)
    interval_seconds: Mapped[int] = mapped_column(Integer, default=0)
    backoff: Mapped[str] = mapped_column(String, default="constant")


class AtmRun(Base):
    __tablename__ = "atm_runs"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    automation_id: Mapped[str] = mapped_column(String, ForeignKey("atm_automations.id"), index=True)
    manual: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String, default="TRIGGERED")
    condition_result: Mapped[bool] = mapped_column(Boolean, default=False)
    triggered_object_ids: Mapped[list] = mapped_column(JSON, default=list)
    effect_results: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[int] = mapped_column(Integer)
    completed_at: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)


class AtmActivity(Base):
    __tablename__ = "atm_activities"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    automation_id: Mapped[str] = mapped_column(String, ForeignKey("atm_automations.id"), index=True)
    event_type: Mapped[str] = mapped_column(String)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[int] = mapped_column(Integer)


class AtmDependency(Base):
    __tablename__ = "atm_dependencies"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    automation_id: Mapped[str] = mapped_column(String, ForeignKey("atm_automations.id"), index=True)
    dependent_id: Mapped[str] = mapped_column(String, ForeignKey("atm_automations.id"), index=True)
    additional_condition: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[int] = mapped_column(Integer)


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------

class AutomationCreate(BaseModel):
    id: Optional[str] = None
    display_name: str
    description: Optional[str] = None
    scope_mode: str = "user_scoped"
    enabled: bool = True
    owner: str = "system"


class AutomationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    display_name: str
    description: Optional[str] = None
    scope_mode: str
    enabled: bool
    muted: bool
    owner: str
    created_at: int
    updated_at: int
    last_evaluated_at: Optional[int] = None


class ConditionCreate(BaseModel):
    id: Optional[str] = None
    condition_type: str
    config: Dict[str, Any] = Field(default_factory=dict)


class ConditionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    automation_id: str
    condition_type: str
    config: Dict[str, Any]
    last_snapshot: Dict[str, Any]
    last_state: Dict[str, Any]


class EffectCreate(BaseModel):
    id: Optional[str] = None
    effect_type: str
    execution_order: int = 0
    parent_effect_id: Optional[str] = None
    config: Dict[str, Any] = Field(default_factory=dict)


class EffectRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    automation_id: str
    effect_type: str
    execution_order: int
    parent_effect_id: Optional[str] = None
    config: Dict[str, Any]


class ExecSettingsCreate(BaseModel):
    execution_mode: str = "sequential"
    batch_size: int = 100
    parallelism: int = 1


class RetryConfigCreate(BaseModel):
    max_attempts: int = 1
    interval_seconds: int = 0
    backoff: str = "constant"


class RunRequest(BaseModel):
    now: Optional[int] = None
    manual: bool = True


class DependencyCreate(BaseModel):
    dependent_id: str
    additional_condition: Dict[str, Any] = Field(default_factory=dict)


class CronPreviewRequest(BaseModel):
    cron: str
    now: int


class ConditionValidateRequest(BaseModel):
    condition_type: str
    config: Dict[str, Any] = Field(default_factory=dict)


class EffectValidateRequest(BaseModel):
    effect_type: str
    config: Dict[str, Any] = Field(default_factory=dict)
    parent_effect_id: Optional[str] = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now() -> int:
    return int(time.time())


def _audit(db: Session, event_type: str, subject_id: str, payload: dict) -> None:
    db.add(models_action.AuditLog(
        id=uuid.uuid4().hex, actor="system", event_type=event_type,
        subject_type="atm_automation", subject_id=subject_id, payload=payload,
    ))


def _get_automation(db: Session, automation_id: str) -> AtmAutomation:
    row = db.query(AtmAutomation).filter(AtmAutomation.id == automation_id).first()
    if not row:
        raise HTTPException(status_code=404, detail=f"Automation '{automation_id}' not found")
    return row


def _activity(db: Session, automation_id: str, event_type: str, payload: dict) -> None:
    db.add(AtmActivity(
        id=uuid.uuid4().hex, automation_id=automation_id, event_type=event_type,
        payload=payload, created_at=_now(),
    ))


# --- cron matcher (standard 5-field Unix cron; mirrors schedules_ops) -------

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


def cron_matches(cron: str, timestamp: int) -> Dict[str, Any]:
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
    # Standard cron day semantics: AND when one field is '*', otherwise OR.
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


def _matching_objects(db: Session, config: Dict[str, Any]) -> List[models.ObjectInstance]:
    """Return ObjectInstances of config.object_type_id matching config.filters (equality)."""
    ot_id = config.get("object_type_id")
    q = db.query(models.ObjectInstance)
    if ot_id:
        q = q.filter(models.ObjectInstance.object_type_id == ot_id)
    rows = q.all()
    filters = config.get("filters") or {}
    if filters:
        out = []
        for r in rows:
            props = r.properties or {}
            if all(props.get(k) == v for k, v in filters.items()):
                out.append(r)
        return out
    return rows


def _prop_hash(props: dict) -> str:
    return hashlib.sha256(json.dumps(props or {}, sort_keys=True, default=str).encode()).hexdigest()


_OPERATORS = {
    ">": lambda a, b: a > b,
    ">=": lambda a, b: a >= b,
    "<": lambda a, b: a < b,
    "<=": lambda a, b: a <= b,
    "==": lambda a, b: a == b,
    "!=": lambda a, b: a != b,
}


def _apply_operator(left: Any, op: str, right: Any) -> bool:
    fn = _OPERATORS.get(op)
    if fn is None:
        raise HTTPException(status_code=422, detail=f"unsupported operator '{op}'")
    try:
        return bool(fn(left, right))
    except TypeError:
        return False


def evaluate_condition(db: Session, cond: AtmCondition, now: Optional[int]) -> Dict[str, Any]:
    """Dispatch condition evaluation by type. Returns
    {triggered: bool, triggered_object_ids: [...], detail: {...}, mutated: bool}.
    `mutated` indicates snapshot/state was changed and should be committed."""
    ct = cond.condition_type
    cfg = cond.config or {}

    if ct == "object_count":
        rows = _matching_objects(db, cfg)
        count = len(rows)
        op = cfg.get("operator", ">=")
        threshold = cfg.get("threshold", 0)
        triggered = _apply_operator(count, op, threshold)
        ids = [r.id for r in rows] if triggered else []
        return {"triggered": triggered, "triggered_object_ids": ids,
                "detail": {"count": count, "operator": op, "threshold": threshold}, "mutated": False}

    if ct in ("object_added", "object_removed", "object_modified"):
        rows = _matching_objects(db, cfg)
        if ct == "object_modified":
            current = {r.id: _prop_hash(r.properties) for r in rows}
        else:
            current = {r.id: True for r in rows}
        prev = (cond.last_snapshot or {}).get("set", {})
        if ct == "object_added":
            changed = [oid for oid in current if oid not in prev]
        elif ct == "object_removed":
            changed = [oid for oid in prev if oid not in current]
        else:  # object_modified: same id, different hash
            changed = [oid for oid in current if oid in prev and current[oid] != prev[oid]]
        cond.last_snapshot = {"set": current}
        triggered = len(changed) > 0
        return {"triggered": triggered, "triggered_object_ids": sorted(changed),
                "detail": {"changed_count": len(changed), "kind": ct}, "mutated": True}

    if ct == "run_on_all":
        rows = _matching_objects(db, cfg)
        ids = [r.id for r in rows]
        return {"triggered": True, "triggered_object_ids": ids,
                "detail": {"count": len(ids)}, "mutated": False}

    if ct == "threshold_crossed":
        # Boolean predicate over an aggregate or a single object property.
        prop = cfg.get("property")
        op = cfg.get("operator", ">=")
        value = cfg.get("value")
        agg = cfg.get("aggregate")  # "count" | None (single value via config.current_value)
        rows = _matching_objects(db, cfg)
        if agg == "count":
            left = len(rows)
        elif "current_value" in cfg:
            left = cfg.get("current_value")
        elif prop is not None and rows:
            left = rows[0].properties.get(prop)
        else:
            left = len(rows)
        predicate = _apply_operator(left, op, value)
        prev_state = (cond.last_state or {}).get("predicate")
        crossing = None
        triggered = False
        if prev_state is None:
            # First evaluation seeds state; a transition to true counts as a crossing.
            if predicate:
                crossing = "false_to_true"
                triggered = True
        elif predicate != prev_state:
            crossing = "false_to_true" if predicate else "true_to_false"
            triggered = True
        cond.last_state = {"predicate": predicate}
        return {"triggered": triggered, "triggered_object_ids": [],
                "detail": {"predicate": predicate, "crossing": crossing, "left": left,
                           "operator": op, "value": value}, "mutated": True}

    if ct == "time":
        if now is None:
            return {"triggered": False, "triggered_object_ids": [],
                    "detail": {"reason": "no 'now' supplied"}, "mutated": False}
        res = cron_matches(cfg.get("cron", "* * * * *"), int(now))
        return {"triggered": res["due"], "triggered_object_ids": [],
                "detail": res, "mutated": False}

    raise HTTPException(status_code=422, detail=f"unknown condition_type '{ct}'")


# --- retry interval computation --------------------------------------------

def _compute_retry_intervals(retry: Optional[AtmRetryConfig]) -> List[int]:
    """Return the per-attempt wait intervals (seconds) BEFORE each retry attempt.

    IMPLEMENTATION ASSUMPTION (NOT documented in the Foundry retries page): for the
    'exponential' strategy the base is 2 and there is NO jitter (jitter would break
    determinism). The docs only state that retries occur with a configured interval and
    a constant-or-exponential strategy; the precise growth factor is our choice.
    """
    if retry is None or retry.max_attempts <= 1:
        return []
    base_interval = retry.interval_seconds or 0
    intervals = []
    for attempt in range(2, retry.max_attempts + 1):  # attempt 1 is the initial try
        if retry.backoff == "exponential":
            intervals.append(base_interval * (2 ** (attempt - 1 - 1)))
        else:  # constant
            intervals.append(base_interval)
    return intervals


def _run_action_effect(db: Session, automation: AtmAutomation, cfg: dict,
                       triggered_ids: List[str]) -> Dict[str, Any]:
    """ACTUALLY execute an action effect against the ontology.

    Looks up the configured ActionType and invokes
    ``app.runtime.apply_action_mutations`` so that object properties are really
    mutated. The REAL list of mutated object ids returned by the runtime is
    recorded as ``mutated_object_ids`` (instead of merely echoing triggered ids).

    Parameter resolution: ``config.parameters`` is passed through to the runtime
    (its mutation rules reference these via ``$param`` / ``object_id_param``). As
    a convenience, the triggered object ids are also exposed so a mutation rule
    using ``object_id_param: "_triggered_object_ids"`` (or the first triggered id
    via ``object_id_param: "_object_id"``) can target the automation's matches.

    Raises ValueError/LookupError on a missing action type or an invalid mutation
    so the caller can mark the effect FAILED (and run its fallback).
    """
    # Imported lazily to avoid import-order coupling at module load time.
    from app.runtime import apply_action_mutations

    action_type_id = cfg.get("action_type_id")
    if not action_type_id:
        raise ValueError("action effect requires config.action_type_id")

    action_type = db.query(models.ActionType).filter(
        models.ActionType.id == action_type_id
    ).first()
    if not action_type:
        raise LookupError(f"ActionType '{action_type_id}' not found")

    # Build the parameter map handed to the runtime. Caller-supplied parameters
    # win; we additionally surface the automation's triggered object ids so a
    # mutation rule can target them without the caller restating the ids.
    parameters: Dict[str, Any] = dict(cfg.get("parameters") or {})
    parameters.setdefault("_triggered_object_ids", list(triggered_ids))
    if triggered_ids and "_object_id" not in parameters:
        parameters["_object_id"] = triggered_ids[0]

    mutated_object_ids = apply_action_mutations(
        db,
        action_type=action_type,
        parameters=parameters,
        actor=f"automation:{automation.id}",
    )
    return {
        "type": "action",
        "action_type_id": action_type_id,
        "objects": list(triggered_ids),
        "mutated_object_ids": list(mutated_object_ids),
    }


def _render_notification(config: dict, triggered_ids: List[str]) -> Dict[str, str]:
    heading = str(config.get("heading", "Automation notification"))
    message = str(config.get("message", ""))
    subs = {"count": str(len(triggered_ids)), "ids": ", ".join(triggered_ids)}
    for token, val in subs.items():
        heading = heading.replace("{" + token + "}", val)
        message = message.replace("{" + token + "}", val)
    return {"heading": heading, "message": message}


def execute_effects(db: Session, automation: AtmAutomation, effects: List[AtmEffect],
                    retry: Optional[AtmRetryConfig], triggered_ids: List[str]) -> List[Dict[str, Any]]:
    """Execute effects in execution_order. Sequential semantics: a failed non-fallback
    effect SKIPS subsequent non-fallback effects and triggers its fallback (if any)."""
    ordered = sorted([e for e in effects if e.effect_type != "fallback"],
                     key=lambda e: e.execution_order)
    fallbacks_by_parent: Dict[str, AtmEffect] = {
        e.parent_effect_id: e for e in effects if e.effect_type == "fallback" and e.parent_effect_id
    }
    results: List[Dict[str, Any]] = []
    failed_parent = False

    for eff in ordered:
        cfg = eff.config or {}
        if failed_parent:
            results.append({"effect_id": eff.id, "effect_type": eff.effect_type,
                            "status": "SKIPPED", "reason": "prior effect failed"})
            continue

        simulate_fail = bool(cfg.get("simulate_fail"))
        attempts: List[Dict[str, Any]] = []
        intervals = _compute_retry_intervals(retry)
        max_attempts = (retry.max_attempts if retry else 1) or 1
        success = False
        for attempt in range(1, max_attempts + 1):
            ok_attempt = not simulate_fail
            attempts.append({"attempt": attempt, "ok": ok_attempt,
                             "wait_before_seconds": (intervals[attempt - 2] if attempt >= 2 and (attempt - 2) < len(intervals) else 0)})
            if ok_attempt:
                success = True
                break

        base_result = {"effect_id": eff.id, "effect_type": eff.effect_type,
                       "attempts": attempts}
        if eff.effect_type == "action":
            # The deterministic simulate_fail path (used by the test suite) never
            # touches the ontology. On the SUCCESS path we ACTUALLY mutate objects
            # via the runtime and record the REAL mutated_object_ids. A runtime
            # error (missing action type / invalid mutation) flips success -> False
            # so the effect FAILS and any fallback fires, mirroring simulate_fail.
            if success:
                try:
                    base_result["result"] = _run_action_effect(db, automation, cfg, triggered_ids)
                except (ValueError, LookupError, KeyError) as exc:
                    success = False
                    base_result["result"] = {"type": "action",
                                             "action_type_id": cfg.get("action_type_id"),
                                             "objects": list(triggered_ids),
                                             "mutated_object_ids": [],
                                             "error": str(exc)}
            else:
                base_result["result"] = {"type": "action",
                                         "action_type_id": cfg.get("action_type_id"),
                                         "objects": list(triggered_ids),
                                         "mutated_object_ids": []}
        elif eff.effect_type == "notification":
            base_result["result"] = {"type": "notification", **_render_notification(cfg, triggered_ids)}
        elif eff.effect_type == "logic":
            base_result["result"] = {"type": "logic",
                                     "logic_function_id": cfg.get("logic_function_id"),
                                     "mode": cfg.get("mode", "default")}
        elif eff.effect_type == "function":
            base_result["result"] = {"type": "function", "function_id": cfg.get("function_id")}

        if success:
            base_result["status"] = "SUCCEEDED"
            results.append(base_result)
        else:
            base_result["status"] = "FAILED"
            results.append(base_result)
            _activity(db, automation.id, "effect_error",
                      {"effect_id": eff.id, "attempts": len(attempts)})
            fb = fallbacks_by_parent.get(eff.id)
            if fb:
                fb_cfg = fb.config or {}
                results.append({
                    "effect_id": fb.id, "effect_type": "fallback", "status": "SUCCEEDED",
                    "result": {"type": "fallback",
                               "error_message": fb_cfg.get("error_message", "effect failed"),
                               "automation_rid": automation.id,
                               "event_id": uuid.uuid4().hex,
                               "for_effect_id": eff.id}})
            failed_parent = True  # skip the rest of the non-fallback chain

    return results


def _chunk(seq: List[Any], size: int) -> List[List[Any]]:
    size = max(1, int(size))
    return [seq[i:i + size] for i in range(0, len(seq), size)]


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

router = APIRouter(tags=["automate"])


# --- Automation CRUD --------------------------------------------------------

@router.post("/automations", response_model=AutomationRead)
def create_automation(body: AutomationCreate, db: Session = Depends(get_db)):
    if body.scope_mode not in SCOPE_MODES:
        raise HTTPException(status_code=422, detail=f"scope_mode must be one of {sorted(SCOPE_MODES)}")
    aid = body.id or uuid.uuid4().hex
    if db.query(AtmAutomation).filter(AtmAutomation.id == aid).first():
        raise HTTPException(status_code=400, detail="Automation already exists")
    now = _now()
    row = AtmAutomation(
        id=aid, display_name=body.display_name, description=body.description,
        scope_mode=body.scope_mode, enabled=body.enabled, muted=False,
        owner=body.owner, created_at=now, updated_at=now, last_evaluated_at=None,
    )
    db.add(row)
    _audit(db, "automate.automation.created", aid, {"display_name": body.display_name})
    db.commit()
    db.refresh(row)
    return row


@router.get("/automations", response_model=List[AutomationRead])
def list_automations(db: Session = Depends(get_db)):
    return db.query(AtmAutomation).order_by(AtmAutomation.created_at).all()


@router.get("/automations/{automation_id}", response_model=AutomationRead)
def get_automation(automation_id: str, db: Session = Depends(get_db)):
    return _get_automation(db, automation_id)


# --- Conditions -------------------------------------------------------------

@router.post("/automations/{automation_id}/conditions", response_model=ConditionRead)
def add_condition(automation_id: str, body: ConditionCreate, db: Session = Depends(get_db)):
    _get_automation(db, automation_id)
    if body.condition_type not in CONDITION_TYPES:
        raise HTTPException(status_code=422, detail=f"condition_type must be one of {sorted(CONDITION_TYPES)}")
    cid = body.id or uuid.uuid4().hex
    if db.query(AtmCondition).filter(AtmCondition.id == cid).first():
        raise HTTPException(status_code=400, detail="Condition already exists")
    row = AtmCondition(id=cid, automation_id=automation_id, condition_type=body.condition_type,
                       config=body.config, last_snapshot={}, last_state={})
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@router.get("/automations/{automation_id}/conditions", response_model=List[ConditionRead])
def list_conditions(automation_id: str, db: Session = Depends(get_db)):
    _get_automation(db, automation_id)
    return db.query(AtmCondition).filter(AtmCondition.automation_id == automation_id).all()


@router.post("/automations/conditions/validate")
def validate_condition(body: ConditionValidateRequest):
    errors: List[str] = []
    if body.condition_type not in CONDITION_TYPES:
        errors.append(f"condition_type must be one of {sorted(CONDITION_TYPES)}")
    cfg = body.config or {}
    if body.condition_type == "object_count":
        if "threshold" not in cfg:
            errors.append("object_count requires config.threshold")
        if cfg.get("operator", ">=") not in _OPERATORS:
            errors.append("invalid operator")
    if body.condition_type == "threshold_crossed":
        if "value" not in cfg:
            errors.append("threshold_crossed requires config.value")
    if body.condition_type == "time":
        if len(str(cfg.get("cron", "")).split()) != 5:
            errors.append("time condition requires a 5-field cron")
    return {"valid": len(errors) == 0, "errors": errors}


# --- Effects ----------------------------------------------------------------

@router.post("/automations/{automation_id}/effects", response_model=EffectRead)
def add_effect(automation_id: str, body: EffectCreate, db: Session = Depends(get_db)):
    _get_automation(db, automation_id)
    if body.effect_type not in EFFECT_TYPES:
        raise HTTPException(status_code=422, detail=f"effect_type must be one of {sorted(EFFECT_TYPES)}")
    if body.effect_type == "fallback" and not body.parent_effect_id:
        raise HTTPException(status_code=422, detail="fallback effect requires parent_effect_id")
    if body.parent_effect_id:
        parent = db.query(AtmEffect).filter(AtmEffect.id == body.parent_effect_id).first()
        if not parent:
            raise HTTPException(status_code=404, detail="parent_effect_id not found")
    eid = body.id or uuid.uuid4().hex
    if db.query(AtmEffect).filter(AtmEffect.id == eid).first():
        raise HTTPException(status_code=400, detail="Effect already exists")
    row = AtmEffect(id=eid, automation_id=automation_id, effect_type=body.effect_type,
                    execution_order=body.execution_order, parent_effect_id=body.parent_effect_id,
                    config=body.config)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@router.get("/automations/{automation_id}/effects", response_model=List[EffectRead])
def list_effects(automation_id: str, db: Session = Depends(get_db)):
    _get_automation(db, automation_id)
    return db.query(AtmEffect).filter(AtmEffect.automation_id == automation_id)\
        .order_by(AtmEffect.execution_order).all()


@router.post("/automations/effects/validate")
def validate_effect(body: EffectValidateRequest):
    errors: List[str] = []
    if body.effect_type not in EFFECT_TYPES:
        errors.append(f"effect_type must be one of {sorted(EFFECT_TYPES)}")
    if body.effect_type == "fallback" and not body.parent_effect_id:
        errors.append("fallback effect requires parent_effect_id")
    if body.effect_type == "action" and not (body.config or {}).get("action_type_id"):
        errors.append("action effect should declare config.action_type_id")
    return {"valid": len(errors) == 0, "errors": errors}


# --- Execution settings & retry config -------------------------------------

@router.put("/automations/{automation_id}/execution-settings")
def set_execution_settings(automation_id: str, body: ExecSettingsCreate, db: Session = Depends(get_db)):
    _get_automation(db, automation_id)
    if body.execution_mode not in EXECUTION_MODES:
        raise HTTPException(status_code=422, detail=f"execution_mode must be one of {sorted(EXECUTION_MODES)}")
    if body.batch_size < 1:
        raise HTTPException(status_code=422, detail="batch_size must be >= 1")
    row = db.query(AtmExecSettings).filter(AtmExecSettings.automation_id == automation_id).first()
    if not row:
        row = AtmExecSettings(id=uuid.uuid4().hex, automation_id=automation_id)
        db.add(row)
    row.execution_mode = body.execution_mode
    row.batch_size = body.batch_size
    row.parallelism = body.parallelism
    db.commit()
    return {"automation_id": automation_id, "execution_mode": row.execution_mode,
            "batch_size": row.batch_size, "parallelism": row.parallelism}


@router.put("/automations/{automation_id}/retry-config")
def set_retry_config(automation_id: str, body: RetryConfigCreate, db: Session = Depends(get_db)):
    _get_automation(db, automation_id)
    if not (1 <= body.max_attempts <= 5):
        raise HTTPException(status_code=422, detail="max_attempts must be in 1..5")
    if body.backoff not in BACKOFF_TYPES:
        raise HTTPException(status_code=422, detail=f"backoff must be one of {sorted(BACKOFF_TYPES)}")
    row = db.query(AtmRetryConfig).filter(AtmRetryConfig.automation_id == automation_id).first()
    if not row:
        row = AtmRetryConfig(id=uuid.uuid4().hex, automation_id=automation_id)
        db.add(row)
    row.max_attempts = body.max_attempts
    row.interval_seconds = body.interval_seconds
    row.backoff = body.backoff
    db.commit()
    return {"automation_id": automation_id, "max_attempts": row.max_attempts,
            "interval_seconds": row.interval_seconds, "backoff": row.backoff}


# --- Cron preview -----------------------------------------------------------

@router.post("/automations/cron/preview")
def cron_preview(body: CronPreviewRequest):
    fields = body.cron.split()
    if len(fields) != 5:
        raise HTTPException(status_code=422, detail="cron must have 5 fields")
    res = cron_matches(body.cron, body.now)
    descr = (f"At minute {fields[0]}, hour {fields[1]}, day-of-month {fields[2]}, "
             f"month {fields[3]}, day-of-week {fields[4]}")
    return {"cron": body.cron, "now": body.now, "matches": res["due"],
            "detail": res["matched"], "utc": res["utc"], "description": descr}


# --- Lifecycle --------------------------------------------------------------

def _lifecycle(db: Session, automation_id: str, action: str) -> AtmAutomation:
    auto = _get_automation(db, automation_id)
    if action == "pause":
        auto.enabled = False
        _activity(db, automation_id, "paused", {})
    elif action == "resume":
        auto.enabled = True
        _activity(db, automation_id, "resumed", {})
    elif action == "mute":
        auto.muted = True
        _activity(db, automation_id, "muted", {})
    elif action == "unmute":
        auto.muted = False
        _activity(db, automation_id, "unmuted", {})
    auto.updated_at = _now()
    db.commit()
    db.refresh(auto)
    return auto


@router.post("/automations/{automation_id}/pause", response_model=AutomationRead)
def pause_automation(automation_id: str, db: Session = Depends(get_db)):
    return _lifecycle(db, automation_id, "pause")


@router.post("/automations/{automation_id}/resume", response_model=AutomationRead)
def resume_automation(automation_id: str, db: Session = Depends(get_db)):
    return _lifecycle(db, automation_id, "resume")


@router.post("/automations/{automation_id}/mute", response_model=AutomationRead)
def mute_automation(automation_id: str, db: Session = Depends(get_db)):
    return _lifecycle(db, automation_id, "mute")


@router.post("/automations/{automation_id}/unmute", response_model=AutomationRead)
def unmute_automation(automation_id: str, db: Session = Depends(get_db)):
    return _lifecycle(db, automation_id, "unmute")


# --- Dependencies -----------------------------------------------------------

@router.post("/automations/{automation_id}/dependencies")
def add_dependency(automation_id: str, body: DependencyCreate, db: Session = Depends(get_db)):
    _get_automation(db, automation_id)
    _get_automation(db, body.dependent_id)
    row = AtmDependency(id=uuid.uuid4().hex, automation_id=automation_id,
                        dependent_id=body.dependent_id,
                        additional_condition=body.additional_condition, created_at=_now())
    db.add(row)
    db.commit()
    return {"id": row.id, "automation_id": automation_id, "dependent_id": body.dependent_id,
            "additional_condition": body.additional_condition}


@router.get("/automations/{automation_id}/dependencies")
def list_dependencies(automation_id: str, db: Session = Depends(get_db)):
    _get_automation(db, automation_id)
    rows = db.query(AtmDependency).filter(AtmDependency.automation_id == automation_id).all()
    return [{"id": r.id, "dependent_id": r.dependent_id,
             "additional_condition": r.additional_condition} for r in rows]


# --- Core run engine --------------------------------------------------------

def _run_once(db: Session, automation: AtmAutomation, now: Optional[int], manual: bool,
              extra_condition: Optional[Dict[str, Any]] = None) -> AtmRun:
    """Evaluate conditions then execute effects, recording an AtmRun."""
    created = _now()
    run = AtmRun(id=uuid.uuid4().hex, automation_id=automation.id, manual=manual,
                 status="TRIGGERED", condition_result=False, triggered_object_ids=[],
                 effect_results=[], created_at=created, completed_at=None)

    # Paused automations skip.
    if not automation.enabled:
        run.status = "SKIPPED"
        run.completed_at = _now()
        db.add(run)
        automation.last_evaluated_at = created
        db.commit()
        db.refresh(run)
        return run

    conditions = db.query(AtmCondition).filter(AtmCondition.automation_id == automation.id).all()
    all_triggered = True
    triggered_ids: List[str] = []
    details: List[Dict[str, Any]] = []
    try:
        for cond in conditions:
            res = evaluate_condition(db, cond, now)
            details.append({"condition_id": cond.id, "type": cond.condition_type, **res})
            if res["triggered"]:
                triggered_ids.extend(res["triggered_object_ids"])
            else:
                all_triggered = False
        # An additional dependency condition (ad-hoc, not persisted) gates dependent runs.
        if extra_condition is not None:
            tmp = AtmCondition(id="tmp", automation_id=automation.id,
                               condition_type=extra_condition.get("condition_type", "run_on_all"),
                               config=extra_condition.get("config", {}), last_snapshot={}, last_state={})
            extra_res = evaluate_condition(db, tmp, now)
            details.append({"condition_id": "additional", "type": tmp.condition_type, **extra_res})
            if not extra_res["triggered"]:
                all_triggered = False
    except HTTPException:
        run.status = "FAILED"
        run.completed_at = _now()
        _activity(db, automation.id, "evaluation_error", {})
        db.add(run)
        db.commit()
        db.refresh(run)
        raise

    # dedupe object ids preserving order
    seen = set()
    triggered_ids = [x for x in triggered_ids if not (x in seen or seen.add(x))]

    run.condition_result = all_triggered and (len(conditions) > 0 or extra_condition is not None)
    run.triggered_object_ids = triggered_ids
    automation.last_evaluated_at = created

    if not run.condition_result:
        run.status = "SKIPPED"
        run.effect_results = []
        run.completed_at = _now()
        db.add(run)
        db.commit()
        db.refresh(run)
        return run

    _activity(db, automation.id, "triggered", {"object_ids": triggered_ids, "manual": manual})

    effects = db.query(AtmEffect).filter(AtmEffect.automation_id == automation.id).all()
    retry = db.query(AtmRetryConfig).filter(AtmRetryConfig.automation_id == automation.id).first()
    exec_settings = db.query(AtmExecSettings).filter(AtmExecSettings.automation_id == automation.id).first()
    batch_size = exec_settings.batch_size if exec_settings else 100

    batches = _chunk(triggered_ids, batch_size) if triggered_ids else [[]]
    all_results: List[Dict[str, Any]] = []
    any_failed = False
    any_success = False
    for bi, batch in enumerate(batches):
        batch_results = execute_effects(db, automation, effects, retry, batch)
        for r in batch_results:
            r["batch_index"] = bi
            if r["status"] == "FAILED":
                any_failed = True
            if r["status"] == "SUCCEEDED":
                any_success = True
        all_results.extend(batch_results)

    run.effect_results = all_results
    if any_failed and any_success:
        run.status = "PARTIALLY_FAILED"
    elif any_failed:
        run.status = "FAILED"
    else:
        run.status = "SUCCEEDED"
    run.completed_at = _now()
    db.add(run)
    db.commit()
    db.refresh(run)
    return run


@router.post("/automations/{automation_id}/run")
def run_automation(automation_id: str, body: RunRequest, db: Session = Depends(get_db)):
    automation = _get_automation(db, automation_id)
    run = _run_once(db, automation, body.now, body.manual)

    dependent_runs: List[str] = []
    # Fire dependents only when this run TRIGGERED (effects ran).
    if run.condition_result:
        deps = db.query(AtmDependency).filter(AtmDependency.automation_id == automation_id).all()
        for dep in deps:
            dependent = db.query(AtmAutomation).filter(AtmAutomation.id == dep.dependent_id).first()
            if not dependent:
                continue
            extra = dep.additional_condition or None
            drun = _run_once(db, dependent, body.now, manual=False, extra_condition=extra)
            dependent_runs.append(drun.id)

    return {
        "run_id": run.id, "status": run.status, "condition_result": run.condition_result,
        "triggered_object_ids": run.triggered_object_ids,
        "effect_results": run.effect_results,
        "batch_count": len(_chunk(run.triggered_object_ids, _batch_size_for(db, automation_id)))
        if run.triggered_object_ids else 0,
        "dependent_run_ids": dependent_runs,
    }


def _batch_size_for(db: Session, automation_id: str) -> int:
    s = db.query(AtmExecSettings).filter(AtmExecSettings.automation_id == automation_id).first()
    return s.batch_size if s else 100


@router.post("/automations/{automation_id}/run/retry-failed-batches")
def retry_failed_batches(automation_id: str, db: Session = Depends(get_db)):
    """Re-run effects for the batches that contained a failure in the latest run."""
    automation = _get_automation(db, automation_id)
    last_run = db.query(AtmRun).filter(AtmRun.automation_id == automation_id)\
        .order_by(AtmRun.created_at.desc()).first()
    if not last_run:
        raise HTTPException(status_code=404, detail="no prior run to retry")
    failed_batches = sorted({r.get("batch_index") for r in (last_run.effect_results or [])
                             if r.get("status") == "FAILED"})
    effects = db.query(AtmEffect).filter(AtmEffect.automation_id == automation_id).all()
    retry = db.query(AtmRetryConfig).filter(AtmRetryConfig.automation_id == automation_id).first()
    batch_size = _batch_size_for(db, automation_id)
    batches = _chunk(last_run.triggered_object_ids or [], batch_size)
    retried = []
    for bi in failed_batches:
        if bi is None or bi >= len(batches):
            continue
        res = execute_effects(db, automation, effects, retry, batches[bi])
        retried.append({"batch_index": bi, "results": res})
    return {"automation_id": automation_id, "retried_batches": failed_batches, "results": retried}


# --- History & activities ---------------------------------------------------

@router.get("/automations/{automation_id}/runs")
def list_runs(automation_id: str, db: Session = Depends(get_db)):
    _get_automation(db, automation_id)
    rows = db.query(AtmRun).filter(AtmRun.automation_id == automation_id)\
        .order_by(AtmRun.created_at.desc()).all()
    return [{"id": r.id, "status": r.status, "manual": r.manual,
             "condition_result": r.condition_result,
             "triggered_object_ids": r.triggered_object_ids,
             "effect_results": r.effect_results,
             "created_at": r.created_at, "completed_at": r.completed_at} for r in rows]


@router.get("/automations/{automation_id}/activities")
def list_activities(automation_id: str, db: Session = Depends(get_db)):
    _get_automation(db, automation_id)
    rows = db.query(AtmActivity).filter(AtmActivity.automation_id == automation_id)\
        .order_by(AtmActivity.created_at.desc()).all()
    return [{"id": r.id, "event_type": r.event_type, "payload": r.payload,
             "created_at": r.created_at} for r in rows]


@router.get("/automations/{automation_id}/history")
def automation_history(automation_id: str, db: Session = Depends(get_db)):
    _get_automation(db, automation_id)
    runs = db.query(AtmRun).filter(AtmRun.automation_id == automation_id)\
        .order_by(AtmRun.created_at.desc()).all()
    acts = db.query(AtmActivity).filter(AtmActivity.automation_id == automation_id)\
        .order_by(AtmActivity.created_at.desc()).all()
    return {
        "automation_id": automation_id,
        "runs": [{"id": r.id, "status": r.status, "manual": r.manual,
                  "condition_result": r.condition_result, "created_at": r.created_at} for r in runs],
        "activities": [{"id": a.id, "event_type": a.event_type, "payload": a.payload,
                        "created_at": a.created_at} for a in acts],
        "run_count": len(runs), "activity_count": len(acts),
    }

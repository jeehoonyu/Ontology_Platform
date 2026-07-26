"""
AIP Evals — graders & metrics (deep-fidelity pass 3).

The base platform's eval suites check only "expected actions/context subset". This
module adds the documented grader model: a library of grader types applied to an
actual result (or to the output of an AIP Logic function run per case), producing
per-grader pass/fail and aggregate metrics (pass rate). Additive; deterministic.

Pass 4 (this revision) adds documented AIP Evals graders that score a *similarity*
(not just pass/fail) and a grid-search EXPERIMENTS endpoint:

  * ``levenshtein`` / ``edit_distance`` — normalized edit-distance similarity in [0,1].
  * ``set_match`` / ``array_match`` — precision / recall / F1 over an expected vs.
    actual set (Foundry's "object set contains" / fuzzy comparison family).
  * ``llm_judge`` — a *deterministic mock* of Foundry's LLM-as-judge / rubric grader:
    scores 1-5 from keyword (词) overlap between an expected reference and the actual
    text (no network; reproducible).

Experiments mirror Foundry's grid-search: given a ``param_grid`` of {name: [values]},
produce the Cartesian product of configurations; each configuration is scored by an
aggregate over its per-case grades, so the best-performing parameter combination can
be identified. Additive; deterministic.
"""
import re
import time
import uuid
import itertools
from typing import Optional, List, Any, Dict, Tuple

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import String, Integer, JSON
from sqlalchemy.orm import Mapped, mapped_column, Session
from pydantic import BaseModel, ConfigDict, Field

from .database import Base, get_db
from . import models, models_action, runtime, tenancy
from .production_auth import Principal, require_permission

router = APIRouter(tags=["aip_evals"])


def _now() -> int:
    return int(time.time())


class AipEvalRun(Base):
    __tablename__ = "aip_eval_runs"
    id: Mapped[str] = mapped_column(String, primary_key=True, index=True)
    project_id: Mapped[str] = mapped_column(String, default="default", index=True)
    target: Mapped[str] = mapped_column(String)          # "actual" | logic function id
    total: Mapped[int] = mapped_column(Integer, default=0)
    passed: Mapped[int] = mapped_column(Integer, default=0)
    pass_rate: Mapped[float] = mapped_column(default=0.0)
    results: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[int] = mapped_column(Integer)


# ---------------------------------------------------------------------------
# Grader engine
# ---------------------------------------------------------------------------
def _dig(value: Any, path: Optional[str]) -> Any:
    """Resolve a dotted path (a.b.0.c) into a nested dict/list structure."""
    if not path:
        return value
    cur = value
    for part in str(path).split("."):
        if isinstance(cur, dict):
            cur = cur.get(part)
        elif isinstance(cur, list):
            try:
                cur = cur[int(part)]
            except (ValueError, IndexError):
                return None
        else:
            return None
    return cur


# ---------------------------------------------------------------------------
# Similarity-scoring grader primitives (documented AIP Evals graders)
# ---------------------------------------------------------------------------
def _levenshtein(a: str, b: str) -> int:
    """Classic edit distance (insert/delete/substitute) via DP. O(len(a)*len(b))."""
    a = "" if a is None else str(a)
    b = "" if b is None else str(b)
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, start=1):
        cur = [i]
        for j, cb in enumerate(b, start=1):
            cost = 0 if ca == cb else 1
            cur.append(min(
                prev[j] + 1,        # deletion
                cur[j - 1] + 1,     # insertion
                prev[j - 1] + cost,  # substitution
            ))
        prev = cur
    return prev[-1]


def _levenshtein_similarity(a: Any, b: Any) -> float:
    """Normalized similarity in [0,1]: 1 - distance/max_len. 1.0 == identical."""
    sa = "" if a is None else str(a)
    sb = "" if b is None else str(b)
    longest = max(len(sa), len(sb))
    if longest == 0:
        return 1.0
    return round(1.0 - (_levenshtein(sa, sb) / longest), 4)


def _as_set(value: Any) -> set:
    """Coerce a scalar/list/set/dict-keys into a comparable set of stringified members."""
    if value is None:
        return set()
    if isinstance(value, dict):
        members = list(value.keys())
    elif isinstance(value, (list, tuple, set)):
        members = list(value)
    else:
        members = [value]
    out = set()
    for m in members:
        out.add(m if isinstance(m, (str, int, float, bool)) else repr(m))
    return out


def _set_match_metrics(expected: Any, actual: Any) -> Dict[str, Any]:
    """Precision/recall/F1 over an expected vs. actual set of members."""
    exp = _as_set(expected)
    act = _as_set(actual)
    tp = len(exp & act)
    precision = round(tp / len(act), 4) if act else 0.0
    recall = round(tp / len(exp), 4) if exp else 0.0
    f1 = round(2 * precision * recall / (precision + recall), 4) if (precision + recall) else 0.0
    return {
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "true_positives": tp,
        "expected_size": len(exp),
        "actual_size": len(act),
        "missing": sorted([str(x) for x in (exp - act)]),
        "unexpected": sorted([str(x) for x in (act - exp)]),
    }


_TOKEN_RE = re.compile(r"\w+", re.UNICODE)


def _tokens(text: Any) -> set:
    """Lowercased word/词 tokens. The \\w+ class is Unicode-aware so CJK chars match."""
    if text is None:
        return set()
    return set(t.lower() for t in _TOKEN_RE.findall(str(text)))


def _llm_judge_score(expected: Any, actual: Any) -> Dict[str, Any]:
    """Deterministic mock of LLM-as-judge / rubric grader.

    Scores the actual text against an expected reference on a 1-5 scale derived from
    keyword/词 overlap (Jaccard of token sets). No network call; fully reproducible so
    it is usable in CI. Mirrors Foundry's rubric grader output shape (score + reason).
    """
    exp_tokens = _tokens(expected)
    act_tokens = _tokens(actual)
    if not exp_tokens and not act_tokens:
        overlap = 1.0
    elif not exp_tokens or not act_tokens:
        overlap = 0.0
    else:
        overlap = len(exp_tokens & act_tokens) / len(exp_tokens | act_tokens)
    # Map Jaccard overlap [0,1] -> integer 1..5 rubric score.
    score = int(round(1 + overlap * 4))
    score = max(1, min(5, score))
    matched = sorted(exp_tokens & act_tokens)
    return {
        "score": score,
        "max_score": 5,
        "overlap": round(overlap, 4),
        "matched_keywords": matched,
        "reason": f"keyword/词 overlap (jaccard) {round(overlap, 4)} -> rubric score {score}/5",
    }


def _grade_one(grader: Dict[str, Any], actual: Any) -> Dict[str, Any]:
    gtype = grader.get("type")
    value = _dig(actual, grader.get("path"))
    passed = False
    detail = ""
    score: Optional[float] = None      # similarity/rubric graders attach a numeric score
    metrics: Optional[Dict[str, Any]] = None  # set_match / llm_judge attach sub-metrics
    try:
        if gtype == "exact_match":
            passed = value == grader.get("expected")
        elif gtype == "contains":
            passed = str(grader.get("expected")) in str(value)
        elif gtype == "regex":
            passed = bool(value is not None and re.search(grader.get("pattern", ""), str(value)))
        elif gtype == "not_null":
            passed = value is not None
        elif gtype == "in_set":
            passed = value in (grader.get("expected") or [])
        elif gtype == "length":
            n = len(value) if hasattr(value, "__len__") else 0
            passed = _num_cmp(n, grader.get("op", "gte"), grader.get("value", 0))
            detail = f"length={n}"
        elif gtype == "numeric":
            passed = isinstance(value, (int, float)) and _num_cmp(value, grader.get("op", "eq"), grader.get("value"))
            detail = f"value={value}"
        elif gtype == "json_path_equals":
            passed = value == grader.get("expected")
        elif gtype in ("levenshtein", "edit_distance"):
            sim = _levenshtein_similarity(grader.get("expected"), value)
            threshold = float(grader.get("threshold", 0.8))
            passed = sim >= threshold
            score = sim
            detail = f"similarity={sim} threshold={threshold}"
        elif gtype in ("set_match", "array_match"):
            m = _set_match_metrics(grader.get("expected"), value)
            metric = grader.get("metric", "f1")  # f1 | precision | recall
            threshold = float(grader.get("threshold", 1.0))
            score = m.get(metric, m["f1"])
            passed = score >= threshold
            metrics = m
            detail = f"{metric}={score} threshold={threshold}"
        elif gtype in ("llm_judge", "llm_as_judge", "rubric"):
            j = _llm_judge_score(grader.get("expected"), value)
            min_score = int(grader.get("min_score", 3))
            score = j["score"]
            passed = j["score"] >= min_score
            metrics = j
            detail = j["reason"]
        else:
            detail = f"unknown grader type '{gtype}'"
    except Exception as exc:  # graders never crash the run
        detail = f"error: {exc}"
    out = {"id": grader.get("id", gtype), "type": gtype, "passed": bool(passed),
           "actual": value if not isinstance(value, (dict, list)) else "<structured>", "detail": detail}
    if score is not None:
        out["score"] = score
    if metrics is not None:
        out["metrics"] = metrics
    return out


def _num_cmp(left: Any, op: str, right: Any) -> bool:
    try:
        if op in ("eq", "=="):
            return left == right
        if op == "gt":
            return left > right
        if op == "gte":
            return left >= right
        if op == "lt":
            return left < right
        if op == "lte":
            return left <= right
        if op in ("ne", "!="):
            return left != right
    except TypeError:
        return False
    return False


def _grade_all(graders: List[Dict[str, Any]], actual: Any) -> Dict[str, Any]:
    results = [_grade_one(g, actual) for g in graders]
    passed = sum(1 for r in results if r["passed"])
    total = len(results)
    scores = [r["score"] for r in results if r.get("score") is not None]
    metrics = {"total": total, "passed": passed,
               "pass_rate": round(passed / total, 4) if total else 0.0}
    if scores:
        metrics["avg_score"] = round(sum(scores) / len(scores), 4)
    return {"results": results, "metrics": metrics}


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------
class GradeRequest(BaseModel):
    project_id: str = "default"
    actual: Any
    graders: List[Dict[str, Any]]


class EvalCase(BaseModel):
    id: Optional[str] = None
    inputs: Dict[str, Any] = Field(default_factory=dict)
    graders: List[Dict[str, Any]] = Field(default_factory=list)


class GradeLogicRequest(BaseModel):
    logic_function_id: str
    cases: List[EvalCase]


class GradeOneRequest(BaseModel):
    """Single-grader convenience shape: {grader, expected, actual}."""
    grader: str
    project_id: str = "default"
    actual: Any = None
    expected: Any = None
    # optional knobs forwarded to the grader (threshold, metric, min_score, path, pattern, op, value...)
    options: Dict[str, Any] = Field(default_factory=dict)


class ExperimentCase(BaseModel):
    id: Optional[str] = None
    # `actual` may be a literal value or a template string containing {param} placeholders
    actual: Any = None
    graders: List[Dict[str, Any]] = Field(default_factory=list)


class ExperimentsRequest(BaseModel):
    """Grid-search over a param grid (Cartesian product of configurations).

    Each configuration is applied to every case. If a case's `actual` is a string it is
    formatted with the configuration's params ({model}, {prompt}, ...) before grading,
    letting different parameter values yield different outputs/scores.
    """
    project_id: str = "default"
    param_grid: Dict[str, List[Any]]
    cases: List[ExperimentCase] = Field(default_factory=list)
    metric: str = "score"  # which aggregate drives ranking: "score" | "pass_rate"


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------
@router.get("/aip/evals/grader-types")
def grader_types():
    return {"grader_types": ["exact_match", "contains", "regex", "not_null", "in_set",
                             "length", "numeric", "json_path_equals",
                             "levenshtein", "edit_distance",
                             "set_match", "array_match",
                             "llm_judge", "llm_as_judge", "rubric"],
            "scoring_graders": {
                "levenshtein": "normalized edit-distance similarity in [0,1]; passes when >= threshold (default 0.8)",
                "set_match": "precision/recall/F1 over expected vs actual sets; passes when chosen metric (default f1) >= threshold (default 1.0)",
                "llm_judge": "deterministic mock LLM-as-judge: 1-5 rubric score from keyword/词 overlap; passes when score >= min_score (default 3)",
            },
            "notes": "Each grader takes an optional dotted `path` into the actual result; scoring graders also attach `score`/`metrics`."}


@router.post("/aip/evals/grade")
def grade(body: GradeRequest, principal: Principal = Depends(require_permission("execute")), db: Session = Depends(get_db)):
    tenancy.assert_project_permission(db, principal, body.project_id, "execute")
    graded = _grade_all(body.graders, body.actual)
    run = AipEvalRun(id=uuid.uuid4().hex, project_id=body.project_id, target="actual", total=graded["metrics"]["total"],
                     passed=graded["metrics"]["passed"], pass_rate=graded["metrics"]["pass_rate"],
                     results=graded["results"], created_at=_now())
    db.add(run); db.commit()
    return {"run_id": run.id, **graded}


@router.post("/aip/evals/grade-one")
def grade_one(body: GradeOneRequest, principal: Principal = Depends(require_permission("execute")), db: Session = Depends(get_db)):
    """Single-grader convenience endpoint matching the {grader, expected, actual} shape.

    Folds `expected`/`options` into a grader dict and runs it through the same engine
    used by /aip/evals/grade, so e.g. levenshtein/set_match/llm_judge are all reachable.
    """
    tenancy.assert_project_permission(db, principal, body.project_id, "execute")
    grader: Dict[str, Any] = {"type": body.grader}
    grader.update(body.options or {})
    if body.expected is not None and "expected" not in grader:
        grader["expected"] = body.expected
    result = _grade_one(grader, body.actual)
    run = AipEvalRun(id=uuid.uuid4().hex, project_id=body.project_id, target="actual", total=1,
                     passed=1 if result["passed"] else 0,
                     pass_rate=1.0 if result["passed"] else 0.0,
                     results=[result], created_at=_now())
    db.add(run)
    db.add(models_action.AuditLog(id=uuid.uuid4().hex, actor=principal.id,
                                  event_type="aip.evals.graded_one",
                                  subject_type="aip_eval", subject_id=run.id,
                                  payload={"project_id": body.project_id, "grader": body.grader, "passed": result["passed"]}))
    db.commit()
    return {"run_id": run.id, "result": result}


def _format_actual(actual: Any, params: Dict[str, Any]) -> Any:
    """If `actual` is a template string, substitute {param} placeholders; else passthrough."""
    if isinstance(actual, str):
        try:
            return actual.format(**params)
        except (KeyError, IndexError, ValueError):
            return actual
    return actual


def _expand_grid(param_grid: Dict[str, List[Any]]) -> List[Dict[str, Any]]:
    """Cartesian product of the param grid -> list of configuration dicts."""
    if not param_grid:
        return [{}]
    names = list(param_grid.keys())
    value_lists = [param_grid[n] if isinstance(param_grid[n], list) else [param_grid[n]] for n in names]
    configs: List[Dict[str, Any]] = []
    for combo in itertools.product(*value_lists):
        configs.append({n: v for n, v in zip(names, combo)})
    return configs


@router.post("/aip/evals/experiments")
def experiments(body: ExperimentsRequest, principal: Principal = Depends(require_permission("execute")), db: Session = Depends(get_db)):
    """Grid-search experiment: Cartesian product of param_grid -> per-config aggregate score.

    Mirrors Foundry AIP Evals experiments: each parameter combination is a separate
    evaluation run; results are aggregated per configuration and the best is reported.
    """
    tenancy.assert_project_permission(db, principal, body.project_id, "execute")
    configs = _expand_grid(body.param_grid)
    metric_key = body.metric if body.metric in ("score", "pass_rate") else "score"

    config_results: List[Dict[str, Any]] = []
    for cfg in configs:
        total = 0
        passed = 0
        all_scores: List[float] = []
        per_case: List[Dict[str, Any]] = []
        for case in body.cases:
            actual = _format_actual(case.actual, cfg)
            graded = _grade_all(case.graders, actual)
            total += graded["metrics"]["total"]
            passed += graded["metrics"]["passed"]
            for r in graded["results"]:
                if r.get("score") is not None:
                    all_scores.append(r["score"])
            per_case.append({"case_id": case.id, "config_actual": actual, **graded})
        pass_rate = round(passed / total, 4) if total else 0.0
        avg_score = round(sum(all_scores) / len(all_scores), 4) if all_scores else 0.0
        agg = {"total": total, "passed": passed, "pass_rate": pass_rate, "avg_score": avg_score}
        agg["aggregate_score"] = agg[metric_key if metric_key != "score" else "avg_score"]
        config_results.append({"config": cfg, "metrics": agg, "cases": per_case})

    # Rank configurations by the chosen aggregate (descending).
    ranked = sorted(config_results, key=lambda c: c["metrics"]["aggregate_score"], reverse=True)
    best = ranked[0] if ranked else None

    run = AipEvalRun(id=uuid.uuid4().hex, project_id=body.project_id, target="experiment",
                     total=sum(c["metrics"]["total"] for c in config_results),
                     passed=sum(c["metrics"]["passed"] for c in config_results),
                     pass_rate=round(best["metrics"]["pass_rate"], 4) if best else 0.0,
                     results=[{"config": c["config"], "metrics": c["metrics"]} for c in config_results],
                     created_at=_now())
    db.add(run)
    db.add(models_action.AuditLog(id=uuid.uuid4().hex, actor=principal.id,
                                  event_type="aip.evals.experiment",
                                  subject_type="aip_experiment", subject_id=run.id,
                                  payload={"project_id": body.project_id, "num_configs": len(configs), "metric": metric_key,
                                           "best_config": best["config"] if best else None}))
    db.commit()
    return {
        "run_id": run.id,
        "param_grid": body.param_grid,
        "metric": metric_key,
        "num_configs": len(configs),
        "configurations": config_results,
        "best": {"config": best["config"], "metrics": best["metrics"]} if best else None,
    }


@router.post("/aip/evals/grade-logic")
def grade_logic(body: GradeLogicRequest, principal: Principal = Depends(require_permission("execute")), db: Session = Depends(get_db)):
    fn = db.get(models.LogicFunction, body.logic_function_id)
    if not fn:
        raise HTTPException(status_code=404, detail=f"LogicFunction '{body.logic_function_id}' not found")
    tenancy.assert_project_permission(db, principal, fn.project_id, "execute")
    case_results = []
    total = 0
    passed = 0
    for case in body.cases:
        run_result = runtime.execute_logic_blocks(db, logic_function=fn, inputs=case.inputs)
        actual = {"outputs": run_result["outputs"], "proposed_actions": run_result["proposed_actions"]}
        graded = _grade_all([g if isinstance(g, dict) else g.dict() for g in case.graders], actual)
        total += graded["metrics"]["total"]
        passed += graded["metrics"]["passed"]
        case_results.append({"case_id": case.id, "inputs": case.inputs, **graded})
    metrics = {"cases": len(body.cases), "total": total, "passed": passed,
               "pass_rate": round(passed / total, 4) if total else 0.0}
    run = AipEvalRun(id=uuid.uuid4().hex, project_id=fn.project_id, target=body.logic_function_id, total=total, passed=passed,
                     pass_rate=metrics["pass_rate"], results=case_results, created_at=_now())
    db.add(run)
    db.add(models_action.AuditLog(id=uuid.uuid4().hex, actor=principal.id, event_type="aip.evals.graded_logic",
                                  subject_type="logic_function", subject_id=body.logic_function_id,
                                  payload={"project_id": fn.project_id, **metrics}))
    db.commit()
    return {"run_id": run.id, "logic_function_id": body.logic_function_id, "metrics": metrics, "cases": case_results}


@router.get("/aip/evals/runs")
def list_eval_runs(project_id: Optional[str] = None, principal: Principal = Depends(require_permission("view")), db: Session = Depends(get_db)):
    query = db.query(AipEvalRun)
    if project_id:
        tenancy.assert_project_permission(db, principal, project_id, "view")
        query = query.filter(AipEvalRun.project_id == project_id)
    else:
        accessible = tenancy.accessible_project_ids(db, principal, "view")
        if accessible is not None:
            query = query.filter(AipEvalRun.project_id.in_(accessible)) if accessible else query.filter(AipEvalRun.id == "__none__")
    rows = query.order_by(AipEvalRun.created_at.desc()).limit(100).all()
    return [{"id": r.id, "project_id": r.project_id, "target": r.target, "total": r.total, "passed": r.passed,
             "pass_rate": r.pass_rate, "created_at": r.created_at} for r in rows]

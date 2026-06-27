"""Standalone self-test for app.aip_evals (graders + experiments).

Builds a local FastAPI app from ONLY the aip_evals router. Does NOT import app.main
(siblings edit other files concurrently). Run from oms/:
    ./venv312/Scripts/python.exe test_aip_evals.py
"""
import os
import tempfile

_t = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(_t.name, 't.db')}"

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.database import Base, engine, SessionLocal  # noqa: E402
from app import models, models_action  # noqa: E402,F401
from app import aip_evals as M  # noqa: E402

Base.metadata.create_all(bind=engine)
api = FastAPI()
api.include_router(M.router)
client = TestClient(api)

passed = 0


def check(cond, msg):
    global passed
    assert cond, "FAILED: " + msg
    passed += 1
    print(f"  ok: {msg}")


# ---------------------------------------------------------------------------
# Unit-level grader primitives
# ---------------------------------------------------------------------------
check(M._levenshtein("kitten", "sitting") == 3, "levenshtein kitten/sitting == 3")
check(M._levenshtein_similarity("abc", "abc") == 1.0, "levenshtein similarity identical == 1.0")
check(0.0 <= M._levenshtein_similarity("abc", "xyz") < 1.0, "levenshtein similarity differing < 1.0")

sm = M._set_match_metrics(["a", "b", "c"], ["a", "b", "d"])
check(sm["true_positives"] == 2, "set_match true_positives == 2")
check(sm["precision"] == round(2 / 3, 4) and sm["recall"] == round(2 / 3, 4), "set_match precision/recall == 2/3")
check(sm["f1"] == round(2 / 3, 4), "set_match f1 == 2/3")
check("c" in sm["missing"] and "d" in sm["unexpected"], "set_match reports missing/unexpected")

j_hi = M._llm_judge_score("the quick brown fox", "the quick brown fox")
j_lo = M._llm_judge_score("the quick brown fox", "totally unrelated zebra content")
check(j_hi["score"] == 5, "llm_judge identical text -> score 5")
check(1 <= j_lo["score"] <= 5 and j_lo["score"] < j_hi["score"], "llm_judge unrelated text lower score")
# Unicode/词 tokenization
j_cjk = M._llm_judge_score("数据 分析 报告", "数据 分析 报告")
check(j_cjk["score"] == 5, "llm_judge CJK/词 overlap -> score 5")

# Cartesian product expansion
grid = M._expand_grid({"model": ["a", "b"], "temp": [0.0, 1.0]})
check(len(grid) == 4, "grid expansion 2x2 == 4 configs")
check({"model": "a", "temp": 0.0} in grid and {"model": "b", "temp": 1.0} in grid, "grid contains expected corners")
check(M._expand_grid({}) == [{}], "empty grid -> single empty config")

# ---------------------------------------------------------------------------
# Endpoint: grader-types lists new graders
# ---------------------------------------------------------------------------
r = client.get("/aip/evals/grader-types")
check(r.status_code == 200, "GET grader-types 200")
gt = r.json()["grader_types"]
for needed in ("levenshtein", "set_match", "array_match", "llm_judge"):
    check(needed in gt, f"grader-types lists {needed}")

# ---------------------------------------------------------------------------
# Endpoint: grade-one {grader, expected, actual}
# ---------------------------------------------------------------------------
r = client.post("/aip/evals/grade-one", json={
    "grader": "levenshtein", "expected": "hello world", "actual": "hello world",
})
check(r.status_code == 200, "POST grade-one levenshtein 200")
res = r.json()["result"]
check(res["passed"] is True and res["score"] == 1.0, "grade-one levenshtein identical passes score 1.0")

r = client.post("/aip/evals/grade-one", json={
    "grader": "set_match", "expected": ["x", "y", "z"], "actual": ["x", "y", "z"],
})
check(r.json()["result"]["passed"] is True, "grade-one set_match perfect passes")
check(r.json()["result"]["metrics"]["f1"] == 1.0, "grade-one set_match f1 == 1.0")

r = client.post("/aip/evals/grade-one", json={
    "grader": "set_match", "expected": ["x", "y", "z"], "actual": ["x"],
    "options": {"metric": "recall", "threshold": 0.5},
})
check(r.json()["result"]["passed"] is False, "grade-one set_match recall below threshold fails")

r = client.post("/aip/evals/grade-one", json={
    "grader": "llm_judge", "expected": "summarize the quarterly revenue report",
    "actual": "summarize the quarterly revenue report",
})
check(r.json()["result"]["score"] == 5, "grade-one llm_judge identical -> 5")

# ---------------------------------------------------------------------------
# Endpoint: grade (existing multi-grader shape) still works WITH new graders
# ---------------------------------------------------------------------------
r = client.post("/aip/evals/grade", json={
    "actual": {"text": "the quick brown fox", "tags": ["a", "b"]},
    "graders": [
        {"type": "levenshtein", "path": "text", "expected": "the quick brown fox"},
        {"type": "set_match", "path": "tags", "expected": ["a", "b"]},
        {"type": "exact_match", "path": "text", "expected": "the quick brown fox"},
    ],
})
check(r.status_code == 200, "POST grade multi-grader 200")
body = r.json()
check(body["metrics"]["pass_rate"] == 1.0, "grade multi-grader pass_rate 1.0")
check("avg_score" in body["metrics"], "grade multi-grader exposes avg_score")

# preserve: a plain exact_match-only grade still works (no score key required)
r = client.post("/aip/evals/grade", json={
    "actual": {"k": 5}, "graders": [{"type": "numeric", "path": "k", "op": "gte", "value": 3}],
})
check(r.json()["metrics"]["passed"] == 1, "grade preserved numeric grader passes")

# ---------------------------------------------------------------------------
# Endpoint: experiments grid-search
# ---------------------------------------------------------------------------
r = client.post("/aip/evals/experiments", json={
    "param_grid": {"prefix": ["the quick brown fox", "wrong"], "suffix": ["", "!"]},
    "cases": [
        {"id": "c1", "actual": "{prefix}{suffix}",
         "graders": [{"type": "llm_judge", "expected": "the quick brown fox"}]},
    ],
    "metric": "score",
})
check(r.status_code == 200, "POST experiments 200")
exp = r.json()
check(exp["num_configs"] == 4, "experiments Cartesian product == 4 configs")
check(len(exp["configurations"]) == 4, "experiments returns 4 configuration results")
check(exp["best"] is not None, "experiments reports a best config")
check(exp["best"]["config"]["prefix"] == "the quick brown fox", "experiments best config uses matching prefix")
check(exp["best"]["metrics"]["aggregate_score"] >= 4, "experiments best aggregate_score high")
# every config carries an aggregate metric
check(all("aggregate_score" in c["metrics"] for c in exp["configurations"]),
      "experiments each config has aggregate_score")

# experiments with pass_rate metric
r = client.post("/aip/evals/experiments", json={
    "param_grid": {"v": ["a", "b", "c"]},
    "cases": [{"id": "c", "actual": "{v}", "graders": [{"type": "exact_match", "expected": "b"}]}],
    "metric": "pass_rate",
})
exp2 = r.json()
check(exp2["num_configs"] == 3, "experiments single-param grid == 3 configs")
check(exp2["best"]["config"]["v"] == "b", "experiments pass_rate best config == b")

# ---------------------------------------------------------------------------
# Endpoint: runs listing reflects experiment + grade runs
# ---------------------------------------------------------------------------
r = client.get("/aip/evals/runs")
check(r.status_code == 200, "GET runs 200")
targets = [row["target"] for row in r.json()]
check("experiment" in targets, "runs include an experiment run")
check("actual" in targets, "runs include a direct grade run")

# audit logs were written for experiments + grade-one
with SessionLocal() as db:
    logs = db.query(models_action.AuditLog).filter(
        models_action.AuditLog.event_type == "aip.evals.experiment").all()
    check(len(logs) >= 1, "audit log written for experiment")

print(f"\n{passed} assertions passed")

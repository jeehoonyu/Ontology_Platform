"""Every Tier A sub-condition is computed from the machine, not asserted in source.

Condition R7 of GOAL_REPAIR_2026-08-23. The commit that introduced `audit_tier_a.py`
is titled *"Compute Tier A instead of asserting it, and record the four parts that
hold"*. It computed six of its eight answers. `check_alembic_postgres` and
`check_images` were single `return` statements emitting `unavailable`, inspecting
nothing.

That is worse than it sounds, because of a rule the gate states itself:
`unavailable` is not a pass. Two sub-conditions hardcoded to `unavailable` do not
merely go unmeasured -- they make the tier unclaimable *in principle*, on any
machine, with postgres and docker running and every image built. The distance
between this repository and a Tier A claim included two `return` statements.

So the gate this file applies is the general form rather than the two instances:
no sub-condition checker may be a constant. A checker that cannot change its
verdict is indistinguishable from one that always fails, and both are
indistinguishable from work nobody has done.

It also asserts that each checker states what it needs when it cannot answer,
since that sentence is the only thing telling a reader whether the gap is theirs
to close.
"""
import ast
import inspect
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))

import audit_tier_a  # noqa: E402

SOURCE = REPO_ROOT / "oms" / "audit_tier_a.py"

NEEDS_SOMETHING = {
    "check_suite",             # a sequential verify.py run
    "check_alembic_postgres",  # a reachable postgres
    "check_images",            # docker, its engine, and the deployment env
    "check_browser",           # a Playwright report
    "check_frontend",          # node_modules
}

passed = 0


def check(condition, label, payload=None):
    global passed
    assert condition, f"{label}: {payload}"
    passed += 1


tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
checkers = {node.name: node for node in tree.body
            if isinstance(node, ast.FunctionDef) and node.name.startswith("check_")}

check(len(checkers) == 8,
      "every Tier A sub-condition has a checker", sorted(checkers))

for name, node in sorted(checkers.items()):
    body = [stmt for stmt in node.body
            if not (isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Constant))]
    constant = len(body) == 1 and isinstance(body[0], ast.Return)
    check(not constant,
          f"{name} inspects something rather than returning a constant verdict",
          "a checker that cannot change its answer makes the tier unclaimable")

    returned = {n.id for stmt in ast.walk(node) if isinstance(stmt, ast.Return)
                for n in ast.walk(stmt) if isinstance(n, ast.Name)}
    check("MET" in returned, f"{name} can report success", sorted(returned))
    if name in NEEDS_SOMETHING:
        # These five depend on something a clone may not have -- a suite run, a
        # postgres, a docker, a browser report, node_modules. Each must be able
        # to say so, because `unavailable` with its requirement beside it is the
        # only answer that tells a reader whether the gap is theirs to close.
        check("UNAVAILABLE" in returned,
              f"{name} can report that it could not answer, and say what it needs",
              sorted(returned))

# The two that were constants are the regression this file exists to prevent, so
# they are also asserted by name: a rewrite that reintroduced either would
# otherwise only be caught if it kept the same function name.
for name in ("check_alembic_postgres", "check_images"):
    source = inspect.getsource(getattr(audit_tier_a, name))
    check(len(source.strip().splitlines()) > 5,
          f"{name} is implemented rather than stubbed",
          f"{len(source.strip().splitlines())} lines")
    check("subprocess.run" in source,
          f"{name} asks the machine rather than the author")

# Reaching a verdict must not need an argument the runner cannot supply: the
# probes in CHEAP are called with none, and check_images is called with the deep
# flag the way check_browser is called with the report path.
for label, probe in audit_tier_a.CHEAP:
    signature = inspect.signature(probe)
    check(not [p for p in signature.parameters.values()
               if p.default is inspect.Parameter.empty],
          f"{probe.__name__} is callable from the CHEAP loop with no arguments", str(signature))

check("production compose renders and images build"
      not in [label for label, _ in audit_tier_a.CHEAP],
      "check_images left the CHEAP loop when it grew the deep flag, "
      "so the label is emitted exactly once")

results = audit_tier_a.evaluate(deep=False, report=None)
check(len(results) == 8, "eight sub-conditions are reported", len(results))
check(len({label for label, _, _ in results}) == 8,
      "each sub-condition is reported exactly once",
      [label for label, _, _ in results])
for label, state, detail in results:
    check(state in (audit_tier_a.MET, audit_tier_a.UNMET, audit_tier_a.UNAVAILABLE),
          f"{label} reports one of the three words", state)
    if state == audit_tier_a.UNAVAILABLE:
        check(detail.strip(), f"{label} says what it needs to be answerable")

print(f"Tier A computation verified: {passed} assertions passed "
      f"({len(checkers)} checkers, 0 constant).")

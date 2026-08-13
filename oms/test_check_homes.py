"""Give the checks that need nothing an automated home, and prove they run here.

Condition C2 of GOAL_2026-08-13. Five checks require no PostgreSQL, no broker, no
object store and no sandbox -- they read the tree and judge it. Four of them were
reachable only from a CI workflow that has never provisioned a runner, and one,
`audit_query_bounds`, was in no workflow and no test at all. It is named as a
ratchet by the standing goal and ran on 2026-08-13 only because a person typed
the command.

This file is their home. It matters that they are *executed* here rather than
inspected: every benchmark and verifier in this repository already has a contract
test that reads its source with `read_text` and asserts things about it, and nine
of them looked covered for exactly that reason while never running.

Two of the five legitimately exit nonzero today, and both are gated accordingly:

  validate_tier_b_evidence       Tier B stands at 7 of 10 and is not claimed
  validate_external_evaluations  no external team has submitted an evaluation

Asserting those pass would be asserting work is finished that is not. They are
run and required to *complete*, because a check that has stopped executing is the
failure this goal is about, and a check that runs and reports FAIL is working. CI
already treats the Tier B report this way, with the reason written beside it.
"""
import io
import sys
from contextlib import redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import audit_check_coverage  # noqa: E402
import audit_query_bounds  # noqa: E402
import validate_docs_conformance  # noqa: E402
import validate_external_evaluations  # noqa: E402
import validate_tier_b_evidence  # noqa: E402
from check_registry import DECLARATIONS, discover, requirements_of  # noqa: E402
from enforcement_runs import recording  # noqa: E402

passed = 0


def check(condition, label, payload=None):
    global passed
    assert condition, f"{label}: {payload}"
    passed += 1


def run(name, module):
    """Execute a check, recording the run, and return its exit code."""
    captured = io.StringIO()
    try:
        with redirect_stdout(captured):
            code = recording(name, module.main)
    except SystemExit as stop:
        code = 0 if stop.code is None else stop.code
    return int(code or 0), captured.getvalue()


# --- checks that must pass ---------------------------------------------------

code, output = run("audit_query_bounds", audit_query_bounds)
check(code == 0, "the query-bounds ratchet holds", output[-400:])
check("Ratchet held" in output or "ratchet" in output.lower(),
      "and says so, so a silent zero is not mistaken for a pass", output[-200:])

code, output = run("validate_docs_conformance", validate_docs_conformance)
check(code == 0, "documentation conformance holds", output[-400:])

code, _ = run("audit_check_coverage", audit_check_coverage)
check(code == 0, "no check is undeclared or newly unautomated")

# --- checks that legitimately report FAIL ------------------------------------
# Required to complete, not to pass. The distinction is the point: a check that
# stopped running is invisible, and a check that runs and reports FAIL is doing
# its job.

code, output = run("validate_tier_b_evidence", validate_tier_b_evidence)
check(isinstance(code, int), "the Tier B audit completes", code)
check("of 10 gates satisfied" in output,
      "and reports a gate count rather than dying silently", output[-300:])

code, output = run("validate_external_evaluations", validate_external_evaluations)
check(isinstance(code, int), "the external-evaluation validator completes", code)

# --- the registry describes the tree, not a wish -----------------------------

declared, found = set(DECLARATIONS), set(discover())
check(not (found - declared),
      "every check-shaped script is declared", sorted(found - declared))
check(not (declared - found),
      "and no declaration names a script that no longer exists", sorted(declared - found))

# Requirements are inferred from source rather than declared, so a check that
# grows a dependency cannot keep a declaration claiming it needs nothing.
check(requirements_of("verify_ontology_query_postgres"),
      "a PostgreSQL verifier reports its requirement")
check(not requirements_of("audit_query_bounds"),
      "and a static audit reports none, which is why it belongs in this file")

for name, declaration in DECLARATIONS.items():
    check(declaration.get("gates") and declaration.get("cadence"),
          f"{name} declares what it gates and how often it runs", declaration)

print(f"Check homes verified: {passed} assertions passed.")

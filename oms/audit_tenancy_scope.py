"""Count the reads of a project-scoped table that name no project, and ratchet it down.

R6 closed privilege: 258 mutating handlers with no permission became 75. It did
not close tenancy, and the difference matters. A permission is a *tier* — it says
an editor may edit. It says nothing about *whose* rows. A caller holding `edit` on
their own project and hitting a handler that selects by id alone reads and writes
another project's data with a permission that looks entirely correct.

Nine of the modules classified during R6 were flagged for exactly this while their
tier was being chosen: `fusion_ops` write-back assigns into `ObjectInstance.properties`
after selecting by id with no project filter; `datasets_ext` folds transactions over
`DataAsset.records` reached by `db.get`; `osdk_ops`, `analytics`, `quiver_runtime`
and `ontology_core` never call `semantic_scope` at all. None of that is visible to
`audit_auth_coverage`, which asks only whether a route checks *something*.

**What is measured.** Every `db.query(X)` and `db.get(X, ...)` where X is an ORM
class whose table carries a `project_id` column, and whether `project_id` appears
in the six lines that follow. 122 of the 271 tables are project-scoped; the rest
are the tenancy substrate itself (`admin_users`, `admin_projects`, `admin_spaces`)
or global infrastructure, and reads of those are not counted.

**What the number is not.** Six lines of proximity is a coarse proxy for "this
read is scoped", and it is wrong in both directions. It clears a read whose filter
mentions `project_id` for an unrelated reason, and it flags a read whose id was
already authorized by `semantic_scope.owned_row` three lines earlier. It is a
ratchet, not a verdict: what it can honestly say is that the count fell, and a
count that only falls cannot hide a new unscoped read arriving. Every finding
still needs a person to look at it. Stating that is the point — a measure that
claims more than it checks is the defect this repository keeps finding.

  python oms/audit_tenancy_scope.py
  python oms/audit_tenancy_scope.py --verbose
  python oms/audit_tenancy_scope.py --set-baseline
"""
from __future__ import annotations

import argparse
import ast
import json
import os
import re
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, List

REPO_ROOT = Path(__file__).resolve().parent.parent
APP = REPO_ROOT / "oms" / "app"
BASELINE = REPO_ROOT / "docs" / "tenancy-scope-baseline.json"

# How far after the read a project predicate may appear and still count as scoping
# it. Chosen from the shape of this codebase's query chains, which are commonly
# `db.query(X).filter(...).filter(...).first()` broken over three or four lines.
PROXIMITY_LINES = 6

# What counts as naming a project near a read. `project_id` is the literal spelling;
# `object_type_project(` is the accessor that returns one, and it earns its place here by
# preserving the measure rather than relaxing it. The seven modules it replaced each
# inlined an expression containing the word `project_id`, so their reads were already
# counted as scoped -- had this token not been added, folding those copies into one
# function would have raised the count by one without a single read changing. A ratchet
# that moves when a refactor deletes a string is measuring the string.
SCOPING_TOKENS = ("project_id", "object_type_project(")


def scoped_classes() -> set:
    """ORM classes whose table carries a project_id column."""
    scratch = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
    os.environ["DATABASE_URL"] = f"sqlite:///{Path(scratch.name, 'tenancy.db').as_posix()}"
    os.environ["AUTH_MODE"] = "local"
    os.environ["APP_ENV"] = "test"
    os.environ["SKIP_CREATE_ALL"] = "1"
    sys.path.insert(0, str(REPO_ROOT / "oms"))

    from app.main import app  # noqa: F401  (registers every model on the shared Base)
    from app import models

    names = {
        mapper.class_.__name__
        for mapper in models.Base.registry.mappers
        if getattr(mapper.class_, "__table__", None) is not None
        and "project_id" in mapper.class_.__table__.columns
    }
    scratch.cleanup()
    return names


def _queried_class(node: ast.Call, scoped: set) -> str | None:
    """The scoped class a db.query(...) or db.get(...) names, if any."""
    func = node.func
    if not isinstance(func, ast.Attribute) or func.attr not in ("query", "get"):
        return None
    for argument in node.args:
        for inner in ast.walk(argument):
            if isinstance(inner, ast.Name) and inner.id in scoped:
                return inner.id
            if isinstance(inner, ast.Attribute) and inner.attr in scoped:
                return inner.attr
    return None


# Where a read sits decides what repairing it costs, so the count is split three ways
# rather than reported as one number that hides the difference.
#
# `semantic_scope`'s accessors authorize a caller, so they need one in hand. A handler
# that declares `principal` has it: the repair is a mechanical swap of the raw read for
# the typed accessor. A private helper in the same module does not -- it took `db` and
# an id from its caller -- so repairing it means threading a principal down, or lifting
# the read up to the handler. That is a real change to a call graph, not a swap, and
# counting it with the swaps overstated how much of this is mechanical. A worker has no
# caller to authorize at all; its question is containment, not permission, and every
# model reached from one here carries `project_id`, so the scope exists and only the
# filter is missing.
UNAUTHORIZED = "unauthorized"  # holds a principal, authorizes nothing: swap in the accessor
TRANSITIVE = "transitive"      # authorized something first: probably already scoped
HELPER = "helper"           # routed module, but no principal here: thread one through
WORKER = "worker"           # no request surface: contain by the job's own project


# A function that resolved an id through one of these has already proved the row is the
# caller's, and a later read filtered by that same id inherits the proof. Counting those
# as unscoped overstated the work by a fifth, and "fixing" one would add a redundant
# predicate rather than close anything. They are reported separately, not cleared: the
# inheritance holds only if the later read really is keyed on the authorized id, and that
# still takes a person to confirm.
AUTHORIZING = re.compile(r"\b(semantic_scope\.\w+|owned_row|assert_project|accessible_query"
                         r"|_artifact_for|_locked_artifact_for|_project_for|require_project)\s*\(")


def _authorized_names(fn: ast.AST) -> set:
    """Variables holding a row that some call was handed the principal to fetch.

    The named-helper list above never keeps up: every module grows its own
    `_processor(db, id, principal, "execute")` or `_agent_task_or_404(id, principal, db)`,
    and a read filtering by `row.id` straight afterwards inherits that proof. Matching the
    shape rather than the name catches those without a list to maintain -- and the shape is
    specific, because handing a function the principal is what delegating the check looks
    like. Merely mentioning `principal` is not: nearly every handler passes `principal.id`
    to an audit-log call, and treating that as authorization cleared all 83 sites at once
    when it was tried, which is how the rule was found to be worthless.

    Only `<name>.id` counts, never any attribute of the row. Inheriting from
    `row.child_id` would be inheriting from a *payload* -- an id the authorized row happens
    to carry -- and that is precisely the confusion this whole condition is about. Every
    defect T2 turned up was an id taken out of something already authorized: a reversal
    entry, a widget definition, a task graph, a workspace's module list. A census that
    cleared those would have reported nothing while the bugs were live.
    """
    out = set()
    for node in ast.walk(fn):
        if not isinstance(node, ast.Assign) or not isinstance(node.value, ast.Call):
            continue
        arguments = list(node.value.args) + [word.value for word in node.value.keywords]
        if any(isinstance(item, ast.Name) and item.id == "principal" for item in arguments):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    out.add(target.id)
    return out


def _principal_bearing(tree: ast.AST, lines: List[str]) -> List[tuple]:
    """(range, authorizes, authorized_names) for each function declaring its own principal."""
    out: List[tuple] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        names = [a.arg for a in node.args.args + node.args.kwonlyargs]
        if "principal" not in names:
            continue
        end = node.end_lineno or node.lineno
        body = "\n".join(lines[node.lineno - 1:end])
        out.append((range(node.lineno, end + 1), bool(AUTHORIZING.search(body)),
                    _authorized_names(node)))
    return out


def _site_kind(line: int, routed: bool, bearing: List[tuple], window: str) -> str:
    for span, authorizes, names in bearing:
        if line in span:
            if authorizes or any(f"{name}.id" in window for name in names):
                return TRANSITIVE
            return UNAUTHORIZED
    return HELPER if routed else WORKER


# Whether the read's result is ever *used*, or only tested for presence. The distinction
# decides whether a site is repairable at all. `existing = db.query(X).filter(X.id == ...)`
# followed by a 409 is asking whether an id is taken, and ids here are primary keys, so a
# row in another project still occupies one: adding a project predicate turns a correctly
# refused insert into a duplicate-key error. `undo_action_log` had both shapes three lines
# apart -- three reads that wrote through the row, and two that only asked whether an id
# was free -- and scoping all five would have broken it.
#
# So the ceiling is not a debt that can reach zero, and a condition demanding that of it
# would generate work that makes the code worse. It stays a full-coverage ratchet, which is
# what stops a new unscoped read arriving unnoticed; `row_used` is the part that can
# actually be driven down, and it is what T2 aims at.


def _uses_row(fn: ast.AST, line: int) -> bool:
    """Does anything read an attribute off what this query returned?"""
    target = None
    for node in ast.walk(fn):
        if isinstance(node, ast.If) and node.test is not None:
            for sub in ast.walk(node.test):
                if isinstance(sub, ast.Call) and sub.lineno <= line <= (sub.end_lineno or sub.lineno):
                    return False  # the read is the condition itself
        if isinstance(node, ast.Assign) and node.lineno <= line <= (node.end_lineno or node.lineno):
            if len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
                target = node.targets[0].id
    if target is None:
        return True  # returned, passed on, or iterated: assume the rows are used
    for node in ast.walk(fn):
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) \
                and node.value.id == target:
            return True
    return False


def _enclosing(functions: List[Any], line: int):
    best = None
    for fn in functions:
        if fn.lineno <= line <= (fn.end_lineno or fn.lineno):
            if best is None or fn.lineno > best.lineno:
                best = fn
    return best


def read() -> Dict[str, Any]:
    scoped = scoped_classes()
    reads = 0
    sites: List[Dict[str, Any]] = []

    for path in sorted(APP.glob("*.py")):
        text = path.read_text(encoding="utf-8", errors="replace")
        lines = text.splitlines()
        routed = "@router." in text or "@app." in text
        try:
            tree = ast.parse(text)
        except SyntaxError:
            continue
        bearing = None
        functions = [n for n in ast.walk(tree)
                     if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            cls = _queried_class(node, scoped)
            if not cls:
                continue
            reads += 1
            bearing = bearing if bearing is not None else _principal_bearing(tree, lines)
            window = "\n".join(lines[max(0, node.lineno - 1):node.lineno + PROXIMITY_LINES])
            if not any(token in window for token in SCOPING_TOKENS):
                owner = _enclosing(functions, node.lineno)
                sites.append({"module": path.name, "line": node.lineno,
                              "model": cls,
                              "kind": _site_kind(node.lineno, routed, bearing, window),
                              "uses_row": _uses_row(owner, node.lineno) if owner else True})

    modules: Dict[str, int] = {}
    for site in sites:
        modules[site["module"]] = modules.get(site["module"], 0) + 1

    return {
        "row_used": sum(1 for s in sites if s["uses_row"]),
        "existence_only": sum(1 for s in sites if not s["uses_row"]),
        "unauthorized": sum(1 for s in sites if s["kind"] == UNAUTHORIZED),
        "transitive": sum(1 for s in sites if s["kind"] == TRANSITIVE),
        "helper": sum(1 for s in sites if s["kind"] == HELPER),
        "worker": sum(1 for s in sites if s["kind"] == WORKER),
        "scoped_models": len(scoped),
        "scoped_reads": reads,
        "unscoped_reads": len(sites),
        "modules": dict(sorted(modules.items(), key=lambda item: -item[1])),
        "sites": sites,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--set-baseline", action="store_true")
    args = parser.parse_args()

    reading = read()
    print(f"{reading['scoped_reads']} reads of a project-scoped model "
          f"({reading['scoped_models']} such models); "
          f"{reading['unscoped_reads']} name no project within "
          f"{PROXIMITY_LINES} lines")
    print(f"    {reading['row_used']:>4}  read a row and then use it -- the part that can reach zero")
    print(f"    {reading['existence_only']:>4}  only ask whether an id is taken (see _uses_row)")
    print(f"    {reading['unauthorized']:>4}  hold a principal but authorize nothing "
          f"(swap in the accessor)")
    print(f"    {reading['transitive']:>4}  authorized an id first, and read by it "
          f"(inherited, still needs a reader)")
    print(f"    {reading['helper']:>4}  in a helper below one (thread a principal down)")
    print(f"    {reading['worker']:>4}  with no caller to authorize (contain by job project)")
    for module, count in list(reading["modules"].items())[:12]:
        print(f"    {count:>4}  {module}")
    if args.verbose:
        for site in reading["sites"]:
            print(f"      {site['module']}:{site['line']}  {site['model']}")

    if args.set_baseline:
        BASELINE.write_text(json.dumps({
            "provenance": {
                "recorded_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "stale_after": "recomputed each run",
            },
            "note": ("Ratchet. Reads of a project-scoped model with no project predicate "
                     "within six lines. Coarse in both directions and wrong about "
                     "individual sites; what it can honestly say is that the count fell, "
                     "and that a new unscoped read cannot arrive unnoticed."),
            "unscoped_reads_ceiling": reading["unscoped_reads"],
            "scoped_reads_reference": reading["scoped_reads"],
            "row_used_reference": reading["row_used"],
            "existence_only_reference": reading["existence_only"],
            "unauthorized_reference": reading["unauthorized"],
            "transitive_reference": reading["transitive"],
            "helper_reference": reading["helper"],
            "worker_reference": reading["worker"],
        }, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(f"\nBaseline set: ceiling {reading['unscoped_reads']}.")
        return 0

    if not BASELINE.exists():
        print("\nNo baseline recorded. Run with --set-baseline to start the ratchet.")
        return 0

    ceiling = json.loads(BASELINE.read_text(encoding="utf-8"))["unscoped_reads_ceiling"]
    if reading["unscoped_reads"] > ceiling:
        print(f"\nRATCHET BROKEN: {reading['unscoped_reads']} unscoped reads, above the "
              f"ceiling of {ceiling}. A read that names no project returns another "
              f"tenant's rows to a caller whose permission looks correct.")
        return 1
    if reading["unscoped_reads"] < ceiling:
        print(f"\nRatchet held, and improved: {ceiling} -> {reading['unscoped_reads']}. "
              f"Re-run with --set-baseline to lock it in.")
        return 0
    print(f"\nRatchet held: {reading['unscoped_reads']} <= {ceiling}.")
    return 0


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from enforcement_runs import recording  # noqa: E402

    sys.exit(recording("audit_tenancy_scope", main))

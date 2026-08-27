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


def read() -> Dict[str, Any]:
    scoped = scoped_classes()
    reads = 0
    sites: List[Dict[str, Any]] = []

    for path in sorted(APP.glob("*.py")):
        text = path.read_text(encoding="utf-8", errors="replace")
        lines = text.splitlines()
        try:
            tree = ast.parse(text)
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            cls = _queried_class(node, scoped)
            if not cls:
                continue
            reads += 1
            window = "\n".join(lines[max(0, node.lineno - 1):node.lineno + PROXIMITY_LINES])
            if "project_id" not in window:
                sites.append({"module": path.name, "line": node.lineno, "model": cls})

    modules: Dict[str, int] = {}
    for site in sites:
        modules[site["module"]] = modules.get(site["module"], 0) + 1

    return {
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

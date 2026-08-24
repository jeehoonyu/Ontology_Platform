"""Count the object writes that do not pass the chokepoint, and ratchet it down.

R3 of GOAL_REPAIR_2026-08-23. Seven modules construct `models.ObjectInstance`
directly. Four validated the properties, five recorded a change event, and the
three that did neither were the same three -- so one refactor closes three
findings, and this is the number that says how far it has got.

Why a ratchet rather than a test that asserts zero: the conversion is several
commits, and a gate that is red until the last one is a gate everybody learns to
push past. The ceiling starts at what the tree holds today and may only fall.

What counts as a bypass is a construction of the row outside `app/object_writes.py`
-- not a mention, not an import, not a query. `models.py` declares the class and
`schemas.py` names it in a response model, so neither is a write.

The second reading is the one the findings came from, and it is reported per site
rather than ratcheted, because it is a property of each site and not a total: does
the module that constructs the row also record a change event? An object with no
change event is not merely unlogged. Temporal reads resolve from
`object_change_events` and never touch `object_instances`, so as far as every
as-of query is concerned that object does not exist.

  python oms/audit_object_writes.py
  python oms/audit_object_writes.py --verbose
  python oms/audit_object_writes.py --set-baseline
"""
from __future__ import annotations

import argparse
import ast
import json
import sys
import time
from pathlib import Path
from typing import Any, Dict, List

REPO_ROOT = Path(__file__).resolve().parent.parent
APP = REPO_ROOT / "oms" / "app"
BASELINE = REPO_ROOT / "docs" / "object-writes-baseline.json"

CHOKEPOINT = "object_writes.py"
# The class is declared in one and named in the other. Neither writes a row.
DECLARATION_ONLY = {"models.py", "schemas.py"}
RECORDERS = ("record_object_change",)


def _constructs_object_instance(node: ast.AST) -> bool:
    if not isinstance(node, ast.Call):
        return False
    func = node.func
    if isinstance(func, ast.Attribute):
        return func.attr == "ObjectInstance"
    return isinstance(func, ast.Name) and func.id == "ObjectInstance"


def _enclosing_function(tree: ast.AST, line: int) -> str:
    best, best_line = "<module>", -1
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.lineno <= line and node.lineno > best_line:
                best, best_line = node.name, node.lineno
    return best


def read() -> Dict[str, Any]:
    sites: List[Dict[str, Any]] = []
    for path in sorted(APP.glob("*.py")):
        if path.name == CHOKEPOINT or path.name in DECLARATION_ONLY:
            continue
        source = path.read_text(encoding="utf-8")
        try:
            tree = ast.parse(source)
        except SyntaxError:
            continue
        records = any(marker in source for marker in RECORDERS)
        uses_chokepoint = "object_writes" in source
        for node in ast.walk(tree):
            if _constructs_object_instance(node):
                sites.append({
                    "module": path.name,
                    "line": node.lineno,
                    "function": _enclosing_function(tree, node.lineno),
                    "module_records_changes": records,
                    "module_uses_chokepoint": uses_chokepoint,
                })
    silent = [s for s in sites if not s["module_records_changes"]]
    return {
        "bypass_sites": len(sites),
        "sites": sites,
        "modules": sorted({s["module"] for s in sites}),
        "silent_modules": sorted({s["module"] for s in silent}),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--set-baseline", action="store_true")
    args = parser.parse_args()

    reading = read()
    print(f"Object writes outside app/{CHOKEPOINT}: {reading['bypass_sites']} "
          f"across {len(reading['modules'])} module(s)")
    for site in reading["sites"] if args.verbose else []:
        flag = "" if site["module_records_changes"] else "  <- records no change event"
        print(f"    {site['module']}:{site['line']} {site['function']}{flag}")
    if reading["silent_modules"]:
        print(f"  modules writing objects with no change event anywhere: "
              f"{', '.join(reading['silent_modules'])}")
        print("  objects created there are absent from every as-of read, not stale")

    if args.set_baseline:
        BASELINE.write_text(json.dumps({
            "provenance": {
                "recorded_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "stale_after": "recomputed each run",
            },
            "note": ("Ratchet. Object writes outside app/object_writes.py. This count "
                     "may fall and must never rise: a new direct construction is a "
                     "write that can skip validation and leave no history."),
            "bypass_sites_ceiling": reading["bypass_sites"],
        }, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(f"\nBaseline set: ceiling {reading['bypass_sites']}.")
        return 0

    if not BASELINE.exists():
        print("\nNo baseline recorded. Run with --set-baseline to start the ratchet.")
        return 0

    ceiling = json.loads(BASELINE.read_text(encoding="utf-8"))["bypass_sites_ceiling"]
    if reading["bypass_sites"] > ceiling:
        print(f"\nRATCHET BROKEN: {reading['bypass_sites']} object writes bypass the "
              f"chokepoint, above the ceiling of {ceiling}. A direct construction can "
              f"skip validation and leave no change event.")
        return 1
    if reading["bypass_sites"] < ceiling:
        print(f"\nRatchet held, and improved: {ceiling} -> {reading['bypass_sites']}. "
              f"Re-run with --set-baseline to lock it in.")
        return 0
    print(f"\nRatchet held: {reading['bypass_sites']} <= {ceiling}.")
    return 0


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from enforcement_runs import recording  # noqa: E402

    sys.exit(recording("audit_object_writes", main))

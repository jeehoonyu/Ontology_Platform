"""Count object-set materializations whose size follows the object type.

Condition B2 of ``docs/GOAL_2026-08-06.md``. The B1 harness measures four query
shapes; this counts the sites, because the product issues more shapes than any
harness enumerates and a fix that only satisfies the measured four would leave
the rest exactly as they are.

An object set is *materialized* when every row of an object type is loaded into
Python before any limit applies. Two primitives do it:

  runtime._query_object_rows   ``query.all()`` with no SQL limit, then a Python
                               filter pass. Callers slice afterwards.
  runtime._logic_object_rows   ``.all()``, then a Python filter, then
                               ``matched[:limit]``. The limit argument never
                               reaches SQL, so a call site asking for five rows
                               loads the type just as thoroughly as one asking
                               for a billion.

The registry below is not a hardcoded verdict. Each primitive is re-checked
against its own source every run, so when one starts expressing a limit in SQL
its call sites stop counting without anyone editing this file. That matters:
the first version of the chaos gate carried a hand-maintained zero that had to
be remembered on the day it changed, and it was not.

  python oms/audit_query_bounds.py
  python oms/audit_query_bounds.py --set-baseline
"""
from __future__ import annotations

import argparse
import ast
import json
import sys
from pathlib import Path
from typing import Dict, List, Tuple

REPO_ROOT = Path(__file__).resolve().parent.parent
APP_DIR = REPO_ROOT / "oms" / "app"
BASELINE = REPO_ROOT / "docs" / "query-bounds-baseline.json"

# Primitives that load an object set. Value is the module they are defined in.
PRIMITIVES = {
    "_logic_object_rows": "runtime.py",
    "iter_object_rows": "runtime.py",
}

# A `limit` argument this large is not a bound. Call sites pass it when what
# they actually want is the exact total, which is condition B3.
NOMINAL_LIMIT = 100_000

# Decorators that make the enclosing function an HTTP entry point.
ROUTE_DECORATORS = {"get", "post", "put", "patch", "delete", "head", "options"}


def _is_route_handler(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    for decorator in node.decorator_list:
        call = decorator.func if isinstance(decorator, ast.Call) else decorator
        if isinstance(call, ast.Attribute) and call.attr in ROUTE_DECORATORS:
            return True
    return False


def _primitive_body(name: str) -> ast.AST:
    source = (APP_DIR / PRIMITIVES[name]).read_text(encoding="utf-8")
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return node
    raise SystemExit(f"{name} is not defined in {PRIMITIVES[name]}; update the registry")


def primitive_materializes(name: str) -> bool:
    """Whether the primitive can hold an object set proportional to the type.

    A primitive is safe when it either bounds the query in SQL with a
    ``.limit(...)`` or streams. ``.all()`` on an unbounded query is the tell,
    and a nominal ``.limit(10**9)`` does not count as a bound because it
    satisfies the letter of the check while loading the type.
    """
    node = _primitive_body(name)
    streams = False
    bounded = False
    for inner in ast.walk(node):
        if isinstance(inner, ast.Call) and isinstance(inner.func, ast.Attribute):
            if inner.func.attr == "execution_options":
                streams = any(kw.arg == "yield_per" for kw in inner.keywords)
            if inner.func.attr == "limit":
                argument = inner.args[0] if inner.args else None
                nominal = (isinstance(argument, ast.Constant)
                           and isinstance(argument.value, int)
                           and argument.value > NOMINAL_LIMIT)
                bounded = bounded or not nominal
        if isinstance(inner, ast.Name) and inner.id == "_stream_object_rows":
            streams = True
    return not (streams or bounded)


def nominal_limit_sites() -> List[Dict[str, object]]:
    """Call sites that ask a primitive for effectively everything.

    These are bounded in memory now -- the primitives stream -- but still walk
    every matching row, because the caller wants an exact total. Condition B3
    is about removing the reason they do that, so the count is tracked
    separately rather than folded into the materialization number, where a
    clean zero would read as the whole problem being solved.
    """
    sites: List[Dict[str, object]] = []
    for path in sorted(APP_DIR.glob("*.py")):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            name = (func.attr if isinstance(func, ast.Attribute)
                    else func.id if isinstance(func, ast.Name) else None)
            if name not in PRIMITIVES:
                continue
            arguments = list(node.args[3:4]) + [
                kw.value for kw in node.keywords if kw.arg == "limit"]
            for argument in arguments:
                value = None
                if isinstance(argument, ast.Constant) and isinstance(argument.value, int):
                    value = argument.value
                elif (isinstance(argument, ast.BinOp) and isinstance(argument.op, ast.Pow)
                      and isinstance(argument.left, ast.Constant)
                      and isinstance(argument.right, ast.Constant)):
                    value = argument.left.value ** argument.right.value
                if value is not None and value > NOMINAL_LIMIT:
                    sites.append({"module": path.name, "line": node.lineno, "limit": value})
    return sites


def find_call_sites() -> List[Dict[str, object]]:
    sites: List[Dict[str, object]] = []
    for path in sorted(APP_DIR.glob("*.py")):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        # Map each call node to its enclosing function, so route handlers can be
        # told from helpers a handler calls.
        enclosing: Dict[ast.AST, ast.AST] = {}
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                for child in ast.walk(node):
                    enclosing.setdefault(child, node)

        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            name = (func.attr if isinstance(func, ast.Attribute)
                    else func.id if isinstance(func, ast.Name) else None)
            if name not in PRIMITIVES:
                continue
            holder = enclosing.get(node)
            if isinstance(holder, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if holder.name == name:
                    continue  # the definition's own recursion, not a call site
                holder_name = holder.name
                direct = _is_route_handler(holder)
            else:
                holder_name = "<module>"
                direct = False
            sites.append({
                "module": path.name,
                "function": holder_name,
                "primitive": name,
                "line": node.lineno,
                "route_handler": direct,
            })
    return sites


# Ways to write an object row that never reach the mapper, and so never reach
# the listener that maintains `geo_min_lon`/`geo_indexed`.
MAPPER_BYPASSES = (
    "ObjectInstance.__table__.insert",
    "bulk_insert_mappings",
    "bulk_save_objects",
    "INSERT INTO object_instances",
)


def mapper_bypass_sites() -> List[Dict[str, object]]:
    """Application writes that skip the ORM, and so skip the geo-bounds listener.

    A row written this way arrives with `geo_indexed` false. That is handled --
    `spatial_query_objects` falls back to a scan rather than returning a wrong
    answer -- but it is handled by being slow, silently, for as long as nobody
    runs `runtime.backfill_geo_bounds`. Benchmarks and migrations legitimately
    bulk-load and set the columns themselves; application code should not, so
    this is ratcheted at zero.
    """
    sites: List[Dict[str, object]] = []
    for path in sorted(APP_DIR.glob("*.py")):
        text = path.read_text(encoding="utf-8")
        for number, line in enumerate(text.splitlines(), start=1):
            for marker in MAPPER_BYPASSES:
                if marker in line:
                    sites.append({"module": path.name, "line": number, "marker": marker})
    return sites


def measure() -> Dict[str, object]:
    unbounded = {name for name in PRIMITIVES if primitive_materializes(name)}
    sites = find_call_sites()
    live = [site for site in sites if site["primitive"] in unbounded]
    nominal = nominal_limit_sites()
    return {
        "primitives": {name: ("materializes" if name in unbounded else "bounded")
                       for name in sorted(PRIMITIVES)},
        "call_sites_total": len(sites),
        "unbounded_call_sites": len(live),
        "unbounded_modules": sorted({str(site["module"]) for site in live}),
        "direct_route_handlers": sum(1 for site in live if site["route_handler"]),
        "sites": live,
        "nominal_limit_call_sites": len(nominal),
        "nominal_limit_sites": nominal,
        "mapper_bypass_sites": mapper_bypass_sites(),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--set-baseline", action="store_true")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    reading = measure()
    print("Object-set materialization audit\n")
    for name, state in reading["primitives"].items():
        print(f"  {name:<24} {state}")
    print(f"\n  materializing call sites        {reading['unbounded_call_sites']}")
    print(f"  of those, route handlers        {reading['direct_route_handlers']}")
    print(f"  modules affected                {len(reading['unbounded_modules'])}")
    for module in reading["unbounded_modules"]:
        count = sum(1 for site in reading["sites"] if site["module"] == module)
        print(f"    {module:<28} {count}")
    print(f"\n  call sites asking for everything (B3, still scan)  "
          f"{reading['nominal_limit_call_sites']}")
    bypasses = reading["mapper_bypass_sites"]
    print(f"  application writes bypassing the geo-bounds listener  {len(bypasses)}")
    for site in bypasses:
        print(f"    {site['module']}:{site['line']} {site['marker']}")
    if args.verbose:
        for site in reading["nominal_limit_sites"]:
            print(f"    {site['module']}:{site['line']} limit={site['limit']:,}")
    if args.verbose:
        print()
        for site in reading["sites"]:
            marker = "route" if site["route_handler"] else "     "
            print(f"    {marker} {site['module']}:{site['line']} "
                  f"{site['function']} -> {site['primitive']}")

    if args.set_baseline:
        BASELINE.write_text(json.dumps({
            "unbounded_call_sites_ceiling": reading["unbounded_call_sites"],
            "note": "Ratchet. This count may fall and must never rise. "
                    "A new call site on an unbounded primitive fails the build.",
        }, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(f"\nBaseline set: ceiling {reading['unbounded_call_sites']}.")
        return 0

    if not BASELINE.exists():
        print("\nNo baseline recorded. Run with --set-baseline to start the ratchet.")
        return 0
    ceiling = json.loads(BASELINE.read_text(encoding="utf-8"))["unbounded_call_sites_ceiling"]
    if reading["unbounded_call_sites"] > ceiling:
        print(f"\nRATCHET BROKEN: {reading['unbounded_call_sites']} unbounded call "
              f"sites, above the ceiling of {ceiling}.")
        return 1
    if reading["mapper_bypass_sites"]:
        print("\nRATCHET BROKEN: application code writes object rows without the "
              "mapper, so their geographic bounds are never computed. Spatial "
              "queries then fall back to scanning, correctly but silently.")
        return 1
    print(f"\nRatchet held: {reading['unbounded_call_sites']} <= {ceiling}, "
          f"0 mapper bypasses.")
    return 0


if __name__ == "__main__":
    from enforcement_runs import recording  # noqa: E402
    sys.exit(recording("audit_query_bounds", main))
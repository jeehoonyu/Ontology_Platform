"""Measure what every request costs, using the test suite as the traffic.

A GET with no path parameter can be called by a machine walking the route table.
A POST cannot: it needs a body the route will accept, and inventing 547 valid
payloads is not a census, it is a rewrite of the suite. So this uses the suite
that already exists -- 224 scripts that create object types, run pipelines,
approve actions and import snapshots, all with payloads the routes accept.

It attaches to the application rather than changing it. The test scripts do
`from app.main import app` and build their own client; importing that module
first and wrapping the same object means every request they make is counted,
and nothing in `oms/app/` knows this file exists.

  python oms/measure_suite_cost.py --out costs.jsonl            # whole suite
  python oms/measure_suite_cost.py --out costs.jsonl --only test_admin.py

Each line of the output is one request: method, route template, statement count,
distinct shapes, worst repeat. Aggregation is a separate step, because a census
that can only be read through its own summariser is hard to disagree with.
"""
from __future__ import annotations

import argparse
import json
import os
import runpy
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional

REPO_ROOT = Path(__file__).resolve().parent.parent
OMS = REPO_ROOT / "oms"


def install(app: Any, engine: Any, sink: Path) -> None:
    """Count the statements each request runs, and write one line per request.

    The route *template* is recorded, not the path: `/object-types/{id}` rather
    than a thousand ids. Without that a census of a suite reads as thousands of
    one-off routes and says nothing.
    """
    from starlette.middleware.base import BaseHTTPMiddleware

    from request_cost import attach, collecting, summarize

    handle = sink.open("a", encoding="utf-8")
    attach(engine)

    class Recorder(BaseHTTPMiddleware):
        async def dispatch(self, request, call_next):
            # `collecting`, not `counting`: one listener is attached to the engine
            # for the whole process and routes each statement to the request in
            # scope. A per-block listener on a shared engine records every
            # concurrent request's work as this one's.
            with collecting() as collected:
                response = await call_next(request)
            route = request.scope.get("route")
            template = getattr(route, "path", None) or request.url.path
            summary = summarize(collected)
            handle.write(json.dumps({
                "method": request.method,
                "route": template,
                "status": response.status_code,
                "queries": summary["queries"],
                "distinct_shapes": summary["distinct_shapes"],
                "worst_repeat": summary["worst_repeat"],
                "worst_shape": (summary["repeats"][0]["statement"][:200]
                                if summary["repeats"] else None),
            }, sort_keys=True) + "\n")
            handle.flush()
            return response

    app.add_middleware(Recorder)


def run_one(script: Path, sink: Path) -> int:
    """Run one test script in a child process with the recorder attached."""
    runner = f'''
import sys
from pathlib import Path
sys.path.insert(0, r"{OMS}")
import runpy
script = r"{script}"
sink = Path(r"{sink}")

# The script sets DATABASE_URL before importing the app, so the recorder cannot
# be installed until after that import happens. Patch the import instead: the
# first time `app.main` is imported, wrap it.
import builtins
_real_import = builtins.__import__
_installed = []

def _hooked(name, globals=None, locals=None, fromlist=(), level=0):
    module = _real_import(name, globals, locals, fromlist, level)
    if not _installed and name in ("app.main", "main") or (
            not _installed and fromlist and "app" in name and hasattr(module, "app")):
        target = getattr(module, "app", None)
        if target is not None:
            try:
                from app.database import engine
                from measure_suite_cost import install
                install(target, engine, sink)
                _installed.append(True)
            except Exception:
                pass
    return module

builtins.__import__ = _hooked
try:
    runpy.run_path(script, run_name="__main__")
finally:
    builtins.__import__ = _real_import
'''
    completed = subprocess.run([sys.executable, "-c", runner], cwd=REPO_ROOT,
                               capture_output=True, text=True)
    return completed.returncode


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True, help="JSONL sink, one line per request")
    parser.add_argument("--only", default=None, help="A single test script name")
    args = parser.parse_args()

    sink = Path(args.out)
    sink.parent.mkdir(parents=True, exist_ok=True)
    sink.write_text("", encoding="utf-8")

    scripts = sorted(OMS.glob("test_*.py"))
    if args.only:
        scripts = [path for path in scripts if path.name == args.only]
        if not scripts:
            print(f"No test script named {args.only}")
            return 1

    failures = 0
    for index, script in enumerate(scripts, 1):
        code = run_one(script, sink)
        failures += 1 if code else 0
        state = "ok  " if code == 0 else "FAIL"
        print(f"  [{index:3d}/{len(scripts)}] {state} {script.name}", flush=True)

    lines = sum(1 for _ in sink.open(encoding="utf-8"))
    print(f"\n{lines} requests recorded from {len(scripts)} scripts "
          f"({failures} script(s) exited non-zero).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

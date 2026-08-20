"""Drive a browser over the workspace routes and record what each costs to open.

Separate from the audit, the way `measure_suite_cost.py` is separate from
`audit_suite_cost.py`: a measurement that can only be read through its own judge
is hard to disagree with, and `frontend/route-cost.json` is one object per route
that someone can open.

  python oms/measure_route_cost.py

Needs node and a Chrome channel, which is why the audit reads a file rather than
running the browser itself -- the fast tier must stay fast.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
FRONTEND = REPO_ROOT / "frontend"
OUT = FRONTEND / "route-cost.json"


def main() -> int:
    if not (FRONTEND / "node_modules").exists():
        print("needs node_modules; run npm ci in frontend/")
        return 1
    completed = subprocess.run(
        ["npx", "playwright", "test", "--project=desktop-1280", "route-cost",
         "--reporter=line"],
        cwd=FRONTEND, capture_output=True, text=True, shell=os.name == "nt")
    if not OUT.exists():
        print(completed.stdout[-2000:])
        print(completed.stderr[-1000:])
        print(f"No measurement written to {OUT}")
        return completed.returncode or 1
    measured = json.loads(OUT.read_text(encoding="utf-8"))
    total = sum(entry["requests"] for entry in measured.values())
    print(f"{len(measured)} routes measured, {total} requests on open, "
          f"written to {OUT.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

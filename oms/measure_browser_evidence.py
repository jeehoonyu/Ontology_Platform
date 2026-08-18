"""Build the frontend, run the browser suite, and record what was proved.

The browser half of this product has never been measured by anything. `npm test`
is `tsc --noEmit`, which proves the TypeScript compiles; the Playwright suite
exists, is good, and was run by nobody.

Two artifacts come out of here, and they answer different questions:

  **provenance** -- what source the served bundle was built from. Without it a
  green run means very little, because Playwright starts `uvicorn` rather than
  the production image, and the app serves whatever `frontend/dist` happens to
  contain. Measured before this file existed: a `dist` built 2026-08-11 with 42
  source files newer than it, including the drag-and-drop workspace. The suite
  was passing against code that was not in the repository.

  **the report** -- Playwright's JSON, one entry per test per viewport, carrying
  the distinction that matters most here: ran versus skipped. The suite declares
  four viewports and skips 32 of its 34 stateful tests everywhere but desktop,
  so more than half of all runs are skips. That was not a number anyone had.

  python oms/measure_browser_evidence.py --build          # bundle + provenance
  python oms/measure_browser_evidence.py --run --out report.json
  python oms/audit_browser_evidence.py report.json        # judge it

Separate from the audit on purpose, the same way `measure_suite_cost.py` is
separate from `audit_suite_cost.py`: a measurement that can only be read through
its own judge is hard to disagree with.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Dict, List

REPO_ROOT = Path(__file__).resolve().parent.parent
FRONTEND = REPO_ROOT / "frontend"
DIST = FRONTEND / "dist"
PROVENANCE = DIST / "build-provenance.json"

# Everything the bundle is built from. A change to any of it means the bundle on
# disk no longer describes the repository, which is the whole point of hashing:
# mtimes do not survive a clone and say nothing about content.
SOURCE_GLOBS = ("src/**/*",)
SOURCE_FILES = ("index.html", "package.json", "package-lock.json",
                "vite.config.ts", "tsconfig.json", "tsconfig.node.json")


def source_inputs() -> List[Path]:
    found: List[Path] = []
    for pattern in SOURCE_GLOBS:
        found.extend(path for path in FRONTEND.glob(pattern) if path.is_file())
    for name in SOURCE_FILES:
        candidate = FRONTEND / name
        if candidate.exists():
            found.append(candidate)
    return sorted(set(found))


def source_fingerprint() -> str:
    """One hash over every input the bundle is built from."""
    digest = hashlib.sha256()
    for path in source_inputs():
        digest.update(str(path.relative_to(FRONTEND)).replace("\\", "/").encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def read_provenance() -> Dict[str, object]:
    if not PROVENANCE.exists():
        return {}
    try:
        return json.loads(PROVENANCE.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def build(verbose: bool = True) -> int:
    """Build the bundle and record the source it came from."""
    if verbose:
        print("building frontend...")
    completed = subprocess.run(["npx", "vite", "build"], cwd=FRONTEND,
                               capture_output=True, text=True, shell=os.name == "nt")
    if completed.returncode != 0:
        print(completed.stdout[-2000:])
        print(completed.stderr[-2000:])
        return completed.returncode
    fingerprint = source_fingerprint()
    PROVENANCE.write_text(json.dumps({
        "source_hash": fingerprint,
        "built_at": int(time.time()),
        "inputs": len(source_inputs()),
    }, indent=2) + "\n", encoding="utf-8")
    if verbose:
        print(f"built from {len(source_inputs())} source inputs, hash {fingerprint[:16]}")
    return 0


def run_suite(out: Path, grep: str = "") -> int:
    """Run the browser suite, writing Playwright's JSON report to `out`."""
    out.parent.mkdir(parents=True, exist_ok=True)
    environment = dict(os.environ)
    environment["PLAYWRIGHT_JSON_OUTPUT_NAME"] = str(out)
    command = ["npx", "playwright", "test", "--reporter=json"]
    if grep:
        command += ["-g", grep]
    completed = subprocess.run(command, cwd=FRONTEND, env=environment,
                               capture_output=True, text=True, shell=os.name == "nt")
    # A non-zero exit means tests failed, which is the audit's business to
    # report, not this file's business to hide. The report is still written.
    if not out.exists():
        print(completed.stdout[-3000:])
        print(completed.stderr[-3000:])
        print(f"No report written to {out}")
        return completed.returncode or 1
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build", action="store_true", help="Build the bundle and record provenance")
    parser.add_argument("--run", action="store_true", help="Run the browser suite")
    parser.add_argument("--out", default=str(REPO_ROOT / "browser-report.json"),
                        help="Where to write Playwright's JSON report")
    parser.add_argument("--grep", default="", help="Only tests matching this pattern")
    args = parser.parse_args()

    if not args.build and not args.run:
        parser.error("nothing to do: pass --build, --run, or both")

    if args.build:
        code = build()
        if code:
            return code

    if args.run:
        out = Path(args.out)
        code = run_suite(out, args.grep)
        if code:
            return code
        report = json.loads(out.read_text(encoding="utf-8"))
        stats = report.get("stats", {})
        print(f"report written to {out}: {stats.get('expected', 0)} passed, "
              f"{stats.get('skipped', 0)} skipped, {stats.get('unexpected', 0)} failed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

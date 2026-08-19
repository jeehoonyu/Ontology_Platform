"""Verify this tree, in one command, at a tier you choose.

Everything needed to know whether this repository is healthy already existed and
none of it composed. Establishing it during the session that produced this file
meant an ad-hoc shell loop over 230 test scripts, retyped by hand eight separate
times, plus a browser run and four audits invoked individually. That knowledge
lived in one head.

Three tiers, because the costs differ by two orders of magnitude and pretending
otherwise is how a verification step gets skipped:

  python oms/verify.py --fast     # static audits only, seconds
  python oms/verify.py            # + the 230-script suite, ~25 minutes
  python oms/verify.py --full     # + browser suite and the suite-cost census

`--fast` is what you type before a commit. The default is what you type before a
push. `--full` is what you type when you are about to believe a number.

The output is one table: what ran, what it said, and how long it took. The exit
code is non-zero if anything failed, so a scheduler can call it without reading.

What it deliberately does not do is decide *what* to fix. `audit_iteration_state`
already names the next step, and this answers the other question -- whether the
last one worked.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import List, Optional, Tuple

REPO_ROOT = Path(__file__).resolve().parent.parent
OMS = REPO_ROOT / "oms"

# The static checks: they read the tree and judge it, need no service, and finish
# in seconds. Ordered cheapest-first so a failure surfaces early.
# Two of these run and report FAIL because the work they describe is genuinely
# unfinished -- Tier B stands at 7 of 10 and no external team has submitted an
# evaluation. `test_check_homes.py` already settled how to treat them: they are
# required to *complete*, never to pass, because "asserting those pass would be
# asserting work is finished that is not". A runner that painted them red every
# run would be teaching its reader to ignore red.
REPORTING = {
    "validate_tier_b_evidence": "Tier B stands at 7 of 10 and is not claimed",
    "validate_external_evaluations": "no external team has submitted an evaluation",
}

FAST_CHECKS = [
    "audit_iteration_state",
    "audit_check_coverage",
    "audit_enforcement",
    "audit_evidence_corpus",
    "audit_dependency_provenance",
    "audit_extensibility",
    "audit_query_bounds",
    "audit_route_coverage",
    "audit_snapshot_scope",
    "audit_ui_states",
    "audit_route_payload",
    "audit_style_scope",
    "audit_ui_primitives",
    "validate_docs_conformance",
    "validate_schema_freeze",
    "validate_tier_b_evidence",
    "validate_external_evaluations",
]


class Result:
    def __init__(self, name: str, code: int, seconds: float, detail: str = ""):
        self.name = name
        self.code = code
        self.seconds = seconds
        self.detail = detail

    @property
    def ok(self) -> bool:
        return self.code == 0


def run_check(name: str) -> Result:
    started = time.time()
    completed = subprocess.run([sys.executable, str(OMS / f"{name}.py")],
                               cwd=REPO_ROOT, capture_output=True, text=True)
    detail = ""
    code = completed.returncode
    if name in REPORTING:
        # It had to run; what it reported is the product's state, not this run's.
        crashed = bool(completed.stderr and "Traceback" in completed.stderr)
        detail = REPORTING[name]
        code = 1 if crashed else 0
    elif code:
        lines = [line for line in (completed.stdout or "").splitlines() if line.strip()]
        detail = lines[-1][:100] if lines else (completed.stderr or "")[-100:]
    return Result(name, code, time.time() - started, detail)


def run_suite() -> Result:
    """Every `oms/test_*.py`, each in its own process, the way the suite is written."""
    started = time.time()
    scripts = sorted(OMS.glob("test_*.py"))
    failed: List[str] = []
    for index, script in enumerate(scripts, 1):
        completed = subprocess.run([sys.executable, str(script)],
                                   cwd=REPO_ROOT, capture_output=True, text=True)
        if completed.returncode:
            failed.append(script.name)
        # Carriage-return progress is for a terminal. Redirected to a file it
        # accumulates into one unreadable line, which is exactly what the log of
        # the first standard run looked like.
        if sys.stdout.isatty():
            print(f"\r  suite {index}/{len(scripts)}  {len(failed)} failed   ",
                  end="", flush=True)
        elif index % 50 == 0 or index == len(scripts):
            print(f"  suite {index}/{len(scripts)}  {len(failed)} failed", flush=True)
    if sys.stdout.isatty():
        print("\r" + " " * 46 + "\r", end="")
    detail = ("; ".join(failed[:3]) + (f" (+{len(failed) - 3} more)" if len(failed) > 3 else "")
              if failed else f"{len(scripts)} scripts")
    return Result("python suite", 1 if failed else 0, time.time() - started, detail)


def run_browser(report: Path) -> List[Result]:
    started = time.time()
    build = subprocess.run([sys.executable, str(OMS / "measure_browser_evidence.py"),
                            "--build", "--run", "--out", str(report)],
                           cwd=REPO_ROOT, capture_output=True, text=True)
    results = [Result("browser suite", build.returncode, time.time() - started,
                      "" if not build.returncode else (build.stdout or "")[-100:])]
    if report.exists():
        results.append(run_named("audit_browser_evidence", [str(report)]))
    return results


def run_named(name: str, args: Optional[List[str]] = None) -> Result:
    started = time.time()
    completed = subprocess.run([sys.executable, str(OMS / f"{name}.py")] + (args or []),
                               cwd=REPO_ROOT, capture_output=True, text=True)
    detail = ""
    if completed.returncode:
        lines = [line for line in (completed.stdout or "").splitlines() if line.strip()]
        detail = lines[-1][:100] if lines else ""
    return Result(name, completed.returncode, time.time() - started, detail)


def run_census(census: Path) -> List[Result]:
    started = time.time()
    measured = subprocess.run([sys.executable, str(OMS / "measure_suite_cost.py"),
                               "--out", str(census)],
                              cwd=REPO_ROOT, capture_output=True, text=True)
    results = [Result("suite-cost census", measured.returncode, time.time() - started)]
    if census.exists():
        results.append(run_named("audit_suite_cost", [str(census)]))
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    tier = parser.add_mutually_exclusive_group()
    tier.add_argument("--fast", action="store_true", help="Static audits only, seconds")
    tier.add_argument("--full", action="store_true",
                      help="Everything, including the census and the browser")
    parser.add_argument("--artifacts", default=str(REPO_ROOT / ".verify"),
                        help="Where the census and browser report are written")
    args = parser.parse_args()

    artifacts = Path(args.artifacts)
    artifacts.mkdir(parents=True, exist_ok=True)

    label = "fast" if args.fast else ("full" if args.full else "standard")
    print(f"verifying, tier: {label}\n")

    results: List[Result] = []
    for name in FAST_CHECKS:
        if not (OMS / f"{name}.py").exists():
            continue
        result = run_check(name)
        results.append(result)
        mark = "ok  " if result.ok else "FAIL"
        if name in REPORTING and result.ok:
            mark = "note"
        suffix = f"  -- {result.detail}" if name in REPORTING else ""
        print(f"  {mark}  {result.seconds:6.1f}s  {name}{suffix}")

    # `audit_tier_a` reads what the last recorded run established, so it runs
    # *after* the suite rather than with the other static checks. Ordered first,
    # it judged this run by the previous one's record -- and a single failure then
    # made the next run's fast tier fail for a reason that was already fixed,
    # which is a loop that cannot clear itself.
    if not args.fast:
        print()
        results.append(run_suite())
        last = results[-1]
        print(f"  {'ok  ' if last.ok else 'FAIL'}  {last.seconds:6.1f}s  python suite "
              f"({last.detail})")

    # Record what this run established, so a later check can read it instead of
    # re-running twenty-five minutes of suite. `audit_tier_a` asks whether the
    # backend suite passes sequentially; the answer existed and was discarded.
    suite = next((r for r in results if r.name == "python suite"), None)
    if suite is not None:
        from datetime import datetime, timezone

        try:
            sys.path.insert(0, str(OMS))
            from audit_evidence_corpus import current_head

            head = current_head()
        except Exception:
            head = None
        (artifacts / "last-run.json").write_text(json.dumps({
            "recorded_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "migration_head": head,
            "tier": label,
            "suite_passed": suite.ok,
            "suite_detail": suite.detail,
            "seconds": round(suite.seconds, 1),
        }, indent=2) + chr(10), encoding="utf-8")

    if not args.fast:
        # The record is now this run's, so the question it answers is current.
        result = run_check("audit_tier_a")
        results.append(result)
        print(f"  {'ok  ' if result.ok else 'FAIL'}  {result.seconds:6.1f}s  audit_tier_a")

    if args.full:
        print()
        for result in run_browser(artifacts / "browser-report.json"):
            results.append(result)
            print(f"  {'ok  ' if result.ok else 'FAIL'}  {result.seconds:6.1f}s  {result.name}")
        for result in run_census(artifacts / "costs.jsonl"):
            results.append(result)
            print(f"  {'ok  ' if result.ok else 'FAIL'}  {result.seconds:6.1f}s  {result.name}")

    failures = [result for result in results if not result.ok]
    total = sum(result.seconds for result in results)
    print(f"\n{len(results) - len(failures)} of {len(results)} passed in {total / 60:.1f} min")

    if failures:
        print(f"\nFAIL -- {len(failures)}:")
        for result in failures:
            print(f"  {result.name}: {result.detail or 'exited non-zero'}")
        return 1

    # The other half of the loop: what to do next, from the gate that knows.
    if not args.fast:
        state = subprocess.run([sys.executable, str(OMS / "audit_iteration_state.py"), "--status"],
                               cwd=REPO_ROOT, capture_output=True, text=True)
        for line in (state.stdout or "").splitlines():
            if line.startswith("Next:"):
                print(f"\n{line}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Answer whether Tier A is met, per sub-condition, from evidence.

`GOAL_2026-08-03.md` declares Tier A as seven sub-conditions and carried the note
*"no artifact claims the tier complete"* for two weeks. That note was accurate and
also misleading: several of the seven are demonstrably satisfied and nothing
recorded it, which is the same gap the iteration goal was opened about -- work
done, record absent -- one level further down.

Each sub-condition gets one of three answers, and the third is the honest one
this repository kept needing:

  **met**          checked here, now, and it holds
  **unmet**        checked here, now, and it does not
  **unavailable**  cannot be checked on this machine, and it says what it needs

`unavailable` is not a pass. It is counted separately and printed with its
requirement, so that "Tier A is met" can never be claimed from a run that could
not look at three of its seven parts.

What is gated is regression: a sub-condition recorded as met may not become
unmet. What is reported is everything else, including how many are still
unavailable, because that number is the distance between this machine and a
claim about the tier.

  python oms/audit_tier_a.py           # the cheap checks
  python oms/audit_tier_a.py --deep    # + alembic, frontend build and npm audit
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Tuple

REPO_ROOT = Path(__file__).resolve().parent.parent
OMS = REPO_ROOT / "oms"
FRONTEND = REPO_ROOT / "frontend"
MATRIX = REPO_ROOT / "foundry-docs" / "VALIDATION_MATRIX.md"
BASELINE = REPO_ROOT / "docs" / "tier-a-baseline.json"

MET, UNMET, UNAVAILABLE = "met", "unmet", "unavailable"

_STATUS = re.compile(r"`?(MATCH|LOCAL_ANALOG|INTENTIONAL_DIFFERENCE|PARTIAL|MISSING)`?")


def matrix_rows() -> Tuple[int, Dict[str, int]]:
    """Statuses from the table rows, not from the legend that defines the words.

    Counting occurrences of `PARTIAL` in the file reports one, every time,
    because the legend explains what `PARTIAL` means. That is how this check was
    first written and it produced a finding that did not exist.
    """
    if not MATRIX.exists():
        return 0, {}
    counts: Dict[str, int] = {}
    rows = 0
    for line in MATRIX.read_text(encoding="utf-8").splitlines():
        if not line.strip().startswith("|"):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) < 3 or set(cells[0]) <= set("-: "):
            continue
        found = [cell for cell in cells if _STATUS.fullmatch(cell)]
        if not found:
            continue
        rows += 1
        status = found[0].strip("`")
        counts[status] = counts.get(status, 0) + 1
    return rows, counts


def check_matrix() -> Tuple[str, str]:
    rows, counts = matrix_rows()
    if not rows:
        return UNAVAILABLE, "no validation matrix found"
    bad = counts.get("PARTIAL", 0) + counts.get("MISSING", 0)
    detail = f"{rows} rows: " + ", ".join(f"{v} {k}" for k, v in sorted(counts.items()))
    return (UNMET if bad else MET), detail


def check_docs() -> Tuple[str, str]:
    completed = subprocess.run([sys.executable, str(OMS / "validate_docs_conformance.py")],
                               cwd=REPO_ROOT, capture_output=True, text=True)
    tail = [line for line in (completed.stdout or "").splitlines() if line.strip()]
    return (MET if completed.returncode == 0 else UNMET), (tail[-1][:80] if tail else "")


def check_alembic_sqlite() -> Tuple[str, str]:
    """The chain applies twice without complaint, on the dialect available here."""
    with tempfile.TemporaryDirectory() as tmp:
        # A POSIX-style path here fails to open on Windows, which read as a
        # broken migration chain the first time this was run by hand.
        database = Path(tmp) / "tier_a.db"
        env = dict(os.environ, DATABASE_URL=f"sqlite:///{database}")
        for attempt in (1, 2):
            completed = subprocess.run(
                [sys.executable, "-m", "alembic", "-c", "alembic.ini", "upgrade", "head"],
                cwd=OMS, env=env, capture_output=True, text=True)
            if completed.returncode:
                return UNMET, f"upgrade {attempt} failed: {(completed.stderr or '')[-70:]}"
        current = subprocess.run(
            [sys.executable, "-m", "alembic", "-c", "alembic.ini", "current"],
            cwd=OMS, env=env, capture_output=True, text=True)
        head = re.findall(r"[0-9]{4}_[a-z_]+", current.stdout or "")
    return MET, f"applies twice at {head[-1] if head else 'unknown head'} (SQLite only)"


def check_alembic_postgres() -> Tuple[str, str]:
    """The chain applies twice on postgres and survives a downgrade round trip.

    This returned `unavailable` unconditionally and inspected nothing, so the
    sub-condition could not change verdict on a machine that had postgres. It is
    reached only when DATABASE_URL names a postgres dialect, which is a
    deliberate act, so the cost is paid by whoever asked for it.
    """
    url = os.getenv("TIER_A_POSTGRES_URL") or os.getenv("DATABASE_URL", "")
    if not url:
        return UNAVAILABLE, ("needs postgres: set TIER_A_POSTGRES_URL (or DATABASE_URL) "
                             "to a postgresql:// dialect")
    if not url.startswith("postgres"):
        return UNAVAILABLE, f"needs postgres; DATABASE_URL names {url.split(':', 1)[0]}"

    env = dict(os.environ, DATABASE_URL=url)

    def alembic(*command: str) -> subprocess.CompletedProcess:
        return subprocess.run([sys.executable, "-m", "alembic", "-c", "alembic.ini", *command],
                              cwd=OMS, env=env, capture_output=True, text=True)

    reachable = alembic("current")
    if reachable.returncode:
        # A database that cannot be reached is not a failing migration chain, and
        # calling it one would put an unplugged server and a broken revision
        # under the same word.
        return UNAVAILABLE, f"postgres unreachable: {(reachable.stderr or '').strip()[-70:]}"

    for attempt in (1, 2):
        completed = alembic("upgrade", "head")
        if completed.returncode:
            return UNMET, f"upgrade {attempt} failed: {(completed.stderr or '').strip()[-70:]}"

    down = alembic("downgrade", "-1")
    if down.returncode:
        return UNMET, f"downgrade -1 failed: {(down.stderr or '').strip()[-70:]}"
    back = alembic("upgrade", "head")
    if back.returncode:
        return UNMET, f"upgrade after downgrade failed: {(back.stderr or '').strip()[-70:]}"

    current = alembic("current")
    head = re.findall(r"[0-9]{4}_[a-z_]+", current.stdout or "")
    return MET, (f"applies twice and survives downgrade/upgrade at "
                 f"{head[-1] if head else 'unknown head'} (PostgreSQL)")


def check_frontend() -> Tuple[str, str]:
    if not (FRONTEND / "node_modules").exists():
        return UNAVAILABLE, "needs node_modules; run npm ci in frontend/"
    shell = os.name == "nt"
    types = subprocess.run(["npx", "tsc", "--noEmit"], cwd=FRONTEND,
                           capture_output=True, text=True, shell=shell)
    if types.returncode:
        return UNMET, "typecheck fails"
    build = subprocess.run(["npx", "vite", "build"], cwd=FRONTEND,
                           capture_output=True, text=True, shell=shell)
    if build.returncode:
        return UNMET, "production build fails"
    audit = subprocess.run(["npm", "audit", "--omit=dev", "--audit-level=high"],
                           cwd=FRONTEND, capture_output=True, text=True, shell=shell)
    if audit.returncode:
        return UNMET, "npm audit reports a high or critical vulnerability"
    return MET, "typecheck, production build, and npm audit --audit-level=high all clean"


def check_browser(report: Path | None) -> Tuple[str, str]:
    """Every skip attributable to a declared project condition, not a failure."""
    candidates = [report] if report else []
    candidates += [REPO_ROOT / ".verify" / "browser-report.json"]
    for path in candidates:
        if path and path.exists():
            break
    else:
        return UNAVAILABLE, "needs a browser report; run oms/verify.py --full"
    sys.path.insert(0, str(OMS))
    from audit_browser_evidence import FAILED, SKIPPED, outcomes

    found = outcomes(json.loads(path.read_text(encoding="utf-8")))
    failures = [name for name, outcome in found.items() if outcome == FAILED]
    skips = sum(1 for outcome in found.values() if outcome == SKIPPED)
    if failures:
        # A failure declared in `known_failing` is debt the browser gate carries
        # deliberately, and it is still a failure here. Tier A is a completion
        # claim -- "the matrix passes" -- so a quarantined failure means it does
        # not pass. Recording this sub-condition as met once meant recording a
        # run in which a known race happened not to fire.
        declared = {}
        baseline = REPO_ROOT / "docs" / "browser-evidence-baseline.json"
        if baseline.exists():
            try:
                declared = json.loads(baseline.read_text(encoding="utf-8")).get(
                    "known_failing", {})
            except json.JSONDecodeError:
                declared = {}
        known = [name for name in failures if name in declared]
        detail = f"{len(failures)} failing test(s); {skips} skips"
        if known:
            detail += f"; {len(known)} of them declared in known_failing"
        return UNMET, detail
    return MET, f"no failures, {skips} skips, all from declared project conditions"


def check_suite() -> Tuple[str, str]:
    """Read what a verify run established rather than spending 25 minutes again.

    Only accepted while it describes this migration head. A suite that passed
    against an older schema is a historical record, which is the same rule the
    baselines carry.
    """
    record = REPO_ROOT / ".verify" / "last-run.json"
    if not record.exists():
        return UNAVAILABLE, "needs a sequential suite run; use oms/verify.py"
    try:
        payload = json.loads(record.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return UNAVAILABLE, "the recorded run is unreadable; re-run oms/verify.py"
    sys.path.insert(0, str(OMS))
    try:
        from audit_evidence_corpus import current_head

        head = current_head()
    except Exception:
        head = None
    if head and payload.get("migration_head") and payload["migration_head"] != head:
        return UNAVAILABLE, (f"last run was at {payload['migration_head']}, head is {head}; "
                             f"re-run oms/verify.py")
    if payload.get("tier") == "fast":
        return UNAVAILABLE, "the last verify run was --fast and did not run the suite"
    detail = f"{payload.get('suite_detail', '')} at {payload.get('recorded_at', '?')}"
    return (MET if payload.get("suite_passed") else UNMET), detail


COMPOSE_MODEL = ("-f", "docker-compose.yml", "-f", "docker-compose.production.yml")
PRODUCTION_IMAGES = (
    ("oms/Dockerfile", "ontology-platform:tier-a"),
    ("oms/plugin-executor.Dockerfile", "ontology-plugin-executor:tier-a"),
    ("oms/plugin-egress-proxy.Dockerfile", "ontology-plugin-egress-proxy:tier-a"),
)


def check_images(deep: bool = False) -> Tuple[str, str]:
    """Does the production model render, and do its images build?

    This returned `unavailable` unconditionally and inspected nothing, which made
    the sub-condition unsatisfiable by any amount of work on any machine -- and
    since `unavailable` is not a pass, it made Tier A unclaimable in principle
    rather than in fact. It is two questions and they cost two orders of
    magnitude apart, so they are answered separately: rendering needs no daemon
    and takes under a second, building needs one and takes minutes.
    """
    docker = subprocess.run(["docker", "--version"], capture_output=True, text=True)
    if docker.returncode:
        return UNAVAILABLE, "needs docker to render compose and build the images"

    rendered = subprocess.run(["docker", "compose", *COMPOSE_MODEL, "config", "--quiet"],
                              cwd=REPO_ROOT, capture_output=True, text=True)
    if rendered.returncode:
        message = (rendered.stderr or "").strip()
        missing = sorted(set(re.findall(r'required variable "?([A-Z_]+)"? is missing', message)))
        if missing:
            # An unset deployment secret is not a broken compose model. Naming
            # them is the difference between "fix the file" and "set the env".
            return UNAVAILABLE, f"compose needs {', '.join(missing[:4])} set in the environment"
        return UNMET, f"production compose does not render: {message[-70:]}"

    if not deep:
        return UNAVAILABLE, "compose renders; the image build needs --deep"

    engine = subprocess.run(["docker", "info"], capture_output=True, text=True)
    if engine.returncode:
        return UNAVAILABLE, "compose renders; the docker engine is not running, so images cannot build"

    for dockerfile, tag in PRODUCTION_IMAGES:
        built = subprocess.run(["docker", "build", "--file", dockerfile, "--tag", tag, "."],
                               cwd=REPO_ROOT, capture_output=True, text=True)
        if built.returncode:
            return UNMET, f"{dockerfile} does not build: {(built.stderr or '').strip()[-70:]}"

    return MET, (f"production compose renders and {len(PRODUCTION_IMAGES)} images build "
                 f"(application, plugin executor, egress proxy)")


CHEAP = [
    ("validation matrix has no PARTIAL or MISSING row", check_matrix),
    ("documentation conformance passes", check_docs),
    ("backend suite passes sequentially", check_suite),
    ("alembic applies twice on postgres, with downgrade", check_alembic_postgres),
]
DEEP = [
    ("alembic applies twice on sqlite", check_alembic_sqlite),
    ("frontend typechecks, builds, and audits clean", check_frontend),
]


def evaluate(deep: bool, report: Path | None) -> List[Tuple[str, str, str]]:
    results = []
    for label, probe in CHEAP:
        state, detail = probe()
        results.append((label, state, detail))
    state, detail = check_images(deep)
    results.append(("production compose renders and images build", state, detail))
    state, detail = check_browser(report)
    results.append(("browser matrix passes with attributable skips", state, detail))
    for label, probe in DEEP:
        if deep:
            state, detail = probe()
        else:
            state, detail = UNAVAILABLE, "not checked; pass --deep"
        results.append((label, state, detail))
    return results


def compare(results, baseline: Dict[str, Any]):
    recorded = baseline.get("sub_conditions", {})
    failures, notes = [], []
    for label, state, detail in results:
        prior = recorded.get(label)
        if prior == MET and state == UNMET:
            failures.append(f"{label}: was met, now unmet -- {detail}")
        elif prior == MET and state == UNAVAILABLE:
            notes.append(f"{label}: was met and could not be checked here -- {detail}")
        elif prior in (None, UNMET, UNAVAILABLE) and state == MET:
            notes.append(f"{label}: now met -- re-run with --set-baseline")
    return not failures, failures, notes


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--deep", action="store_true",
                        help="Also run alembic, the frontend build, and npm audit")
    parser.add_argument("--report", default=None, help="A Playwright JSON report to read")
    parser.add_argument("--set-baseline", action="store_true")
    args = parser.parse_args()

    results = evaluate(args.deep, Path(args.report) if args.report else None)
    met = sum(1 for _, state, _ in results if state == MET)
    unmet = sum(1 for _, state, _ in results if state == UNMET)
    unavailable = sum(1 for _, state, _ in results if state == UNAVAILABLE)

    print(f"Tier A: {met} met, {unmet} unmet, {unavailable} unavailable "
          f"of {len(results)} sub-conditions\n")
    for label, state, detail in results:
        print(f"  {state:<12}{label}")
        if detail:
            print(f"              {detail[:96]}")

    if args.set_baseline:
        BASELINE.write_text(json.dumps({
            "provenance": {"stale_after": "recomputed each run"},
            "note": ("Per sub-condition state of Tier A. A sub-condition recorded met may "
                     "not become unmet. `unavailable` is not a pass."),
            "sub_conditions": {label: state for label, state, _ in results},
        }, indent=2) + "\n", encoding="utf-8")
        print(f"\nBaseline set: {met} met of {len(results)}.")
        return 0

    if not BASELINE.exists():
        print(f"\nNo baseline at {BASELINE.relative_to(REPO_ROOT)}. Record one with "
              f"--set-baseline.")
        return 1

    ok, failures, notes = compare(results, json.loads(BASELINE.read_text(encoding="utf-8")))
    for note in notes:
        print(f"\n  {note}")
    if failures:
        print(f"\nFAIL -- {len(failures)}:")
        for failure in failures:
            print(f"  {failure}")
        return 1
    outstanding = unmet + unavailable
    if outstanding:
        print(f"\nNo sub-condition regressed. Tier A is not claimable while {outstanding} "
              f"of {len(results)} are unmet or unavailable.")
    else:
        # This sentence could not be printed before. The verdict was a single
        # unconditional line saying the tier was not claimable, formatted with the
        # count -- so a complete run read "not claimable while 0 of 8 are unmet or
        # unavailable", and the gate that exists to compute the tier could not
        # report the one answer it was built to find. The same shape as the two
        # constant checkers R7 replaced, in the sentence that reports them.
        print(f"\nAll {len(results)} sub-conditions are met on this machine, none "
              f"unavailable. Tier A is claimable against this run.")
    return 0


if __name__ == "__main__":
    from enforcement_runs import recording

    raise SystemExit(recording("audit_tier_a", main))

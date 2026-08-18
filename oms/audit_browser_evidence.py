"""Gate what the browser suite proved, and refuse to let its coverage narrow.

Fourteen declared checks measure this product and, until this one, none of them
opened a browser. 16,455 lines of TypeScript across 22 screens were held to
`tsc --noEmit`. This is the first standing invariant -- *no claim outlives its
proof* -- pointed at the half of the product a user actually touches.

Three separate things are gated here, because three separate things were wrong.

**The bundle must be the repository's bundle.** Playwright starts `uvicorn`, not
the production image, and `_workspace_shell` serves whatever `frontend/dist`
contains -- or silently falls back to `oms/app/ui/`, 7,856 lines of hand-written
UI that no test touches, whenever the build is missing. Measured before this
existed: the `dist` on disk was built from source 42 files out of date, including
the drag-and-drop workspace. A green run described code that was not in the repo.
So the recorded source hash must match the source, and every asset the served
shell names must exist.

**Nothing may newly fail.** Obvious, and it had no gate. The first run of this
audit found two things nobody knew: `pipeline deploys an immutable snapshot`
fails on both attempts because the execution reports SUCCEEDED before the
finalize job's result carries `row_count`, and `pipeline creates a graph and
accepts a dragged node` -- the test that answers "does drag-and-drop work" -- is
flaky, failing once with zero nodes and passing on retry.

A failure already known is carried in `known_failing` with a written reason and
reported loudly every run; a failure that is not on that list fails the gate. The
list is in the baseline, so growing it is an edit someone has to make on purpose
and a reviewer can see. That is the write-cost ratchet's treatment of debt,
applied to tests: a gate that goes red on day one for a defect it just found is
a gate someone turns off, but a gate that hides the defect is worse than none.

**Coverage may not narrow.** The suite declares four viewports and skips 32 of
its 34 stateful tests everywhere but `desktop-1280`: 100 ran, 115 skipped. The
product is verified to *look* right at four widths and to *work* at one, and that
is what hid a pipeline canvas a touch user cannot add a node to. The ratchet is
per test per viewport, and it gates the direction that matters:

  - *Gated:* a test that ran at baseline and is skipped now. That is coverage
    narrowing, and it is named, not counted.
  - *Reported:* a test that disappeared. Deleting an obsolete test is ordinary
    work and a ratchet is not a test inventory.
  - *Reported:* a new test, whether it runs or skips. Adding a desktop-only test
    does not narrow anything that existed.

Gate the thing ordinary work does not do; report the thing it does. Adding a test
is ordinary. Turning a test that ran into one that does not is not.

  python oms/measure_browser_evidence.py --build --run --out browser-report.json
  python oms/audit_browser_evidence.py browser-report.json

The suite takes 1.8 minutes, so unlike the suite-cost census this is affordable
often. It needs node and a Chrome channel, which is why it is declared on demand
rather than wired into `pre-push`.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Tuple

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))

BASELINE = REPO_ROOT / "docs" / "browser-evidence-baseline.json"
FRONTEND = REPO_ROOT / "frontend"
DIST = FRONTEND / "dist"
LEGACY_SHELL = REPO_ROOT / "oms" / "app" / "ui" / "index.html"

# A report that reached almost nothing must not clear anything. The same guard
# the suite-cost ratchet carries, for the same reason: a crashed run passes every
# gate by never contradicting one.
MINIMUM_COVERAGE = 0.90

RAN = "ran"
SKIPPED = "skipped"
FAILED = "failed"
# Passed, but only on retry. Counts as coverage -- the test did execute and
# did assert -- but it is named in the output every single run, because a
# suite whose flakes are invisible is a suite people stop believing.
FLAKY = "flaky"


def outcomes(report: Dict[str, Any]) -> Dict[Tuple[str, str], str]:
    """One outcome per (viewport, test title). Playwright nests suites; flatten."""
    found: Dict[Tuple[str, str], str] = {}

    def walk(suites: List[dict]) -> None:
        for suite in suites or []:
            for spec in suite.get("specs", []) or []:
                title = spec.get("title") or ""
                for test in spec.get("tests", []) or []:
                    project = test.get("projectName") or "?"
                    status = test.get("status") or "?"
                    if status == "skipped":
                        outcome = SKIPPED
                    elif status == "flaky":
                        outcome = FLAKY
                    elif status == "expected":
                        outcome = RAN
                    else:
                        outcome = FAILED
                    # A title can appear in more than one file; worst wins.
                    prior = found.get((project, title))
                    order = {FAILED: 3, FLAKY: 2, RAN: 1, SKIPPED: 0}
                    if prior is None or order[outcome] > order[prior]:
                        found[(project, title)] = outcome
            walk(suite.get("suites", []))

    walk(report.get("suites", []))
    return found


def per_viewport(found: Dict[Tuple[str, str], str]) -> Dict[str, Dict[str, int]]:
    counts: Dict[str, Dict[str, int]] = defaultdict(
        lambda: {RAN: 0, SKIPPED: 0, FAILED: 0, FLAKY: 0})
    for (project, _title), outcome in found.items():
        counts[project][outcome] += 1
    return dict(counts)


def check_provenance() -> Tuple[List[str], List[str]]:
    """Is the bundle on disk built from the source in the repository?"""
    from measure_browser_evidence import read_provenance, source_fingerprint

    failures: List[str] = []
    notes: List[str] = []

    index = DIST / "index.html"
    if not index.exists():
        failures.append(
            f"no bundle at {index.relative_to(REPO_ROOT)} -- the server falls back to "
            f"{LEGACY_SHELL.relative_to(REPO_ROOT)}, which no test touches. "
            f"Run: python oms/measure_browser_evidence.py --build")
        return failures, notes

    html = index.read_text(encoding="utf-8")
    if 'id="root"' not in html:
        failures.append("the built index.html is not the React shell")

    referenced = set(re.findall(r'/react/assets/([A-Za-z0-9._-]+)', html))
    missing = sorted(name for name in referenced if not (DIST / "assets" / name).exists())
    if missing:
        failures.append(f"the served shell names assets that do not exist: {', '.join(missing[:4])}")
    notes.append(f"served shell references {len(referenced)} asset(s), all present")

    recorded = read_provenance()
    if not recorded:
        failures.append(
            "the bundle carries no build provenance, so nothing says what source it came "
            "from. Run: python oms/measure_browser_evidence.py --build")
        return failures, notes

    actual = source_fingerprint()
    if recorded.get("source_hash") != actual:
        failures.append(
            f"the bundle was built from different source than the repository contains "
            f"(recorded {str(recorded.get('source_hash'))[:16]}, actual {actual[:16]}). "
            f"A run against it proves nothing about this commit. "
            f"Run: python oms/measure_browser_evidence.py --build")
    else:
        notes.append(f"bundle built from the current {recorded.get('inputs')} source inputs "
                     f"({actual[:16]})")
    return failures, notes


def compare(found: Dict[Tuple[str, str], str],
            baseline: Dict[str, Any]) -> Tuple[bool, List[str], List[str]]:
    """Returns (ok, failures, notes)."""
    recorded: Dict[str, str] = baseline.get("tests", {})
    quarantined: Dict[str, str] = baseline.get("known_failing", {})
    failures: List[str] = []
    notes: List[str] = []

    def key_of(project: str, title: str) -> str:
        return f"{project} :: {title}"

    seen = {key_of(project, title) for project, title in found}

    if recorded:
        coverage = len(seen & set(recorded)) / len(recorded)
        if coverage < MINIMUM_COVERAGE:
            failures.append(
                f"the report covers {coverage:.0%} of the {len(recorded)} baseline entries "
                f"(minimum {MINIMUM_COVERAGE:.0%}); a run that reached nothing cannot clear "
                f"anything")

    for (project, title), outcome in sorted(found.items()):
        name = key_of(project, title)
        if outcome == FAILED:
            reason = quarantined.get(name)
            if reason:
                notes.append(f"KNOWN FAILURE  {name} -- {reason}")
            else:
                failures.append(f"FAILED  {name}")
            continue
        if outcome == FLAKY:
            notes.append(f"FLAKY   {name}: failed once and passed on retry -- this is "
                         f"coverage that cannot be relied on")
        prior = recorded.get(name)
        if prior is None:
            notes.append(f"new     {name} ({outcome})")
        elif prior == RAN and outcome == SKIPPED:
            failures.append(
                f"narrowed  {name}: ran at baseline, skipped now. Behavioural coverage "
                f"may widen and may not narrow.")
        elif prior == SKIPPED and outcome in (RAN, FLAKY):
            notes.append(f"widened {name}: skipped at baseline, runs now -- "
                         f"baseline should be raised")

    for name, prior in sorted(recorded.items()):
        if name not in seen:
            notes.append(f"gone    {name} (was {prior}) -- deleted or renamed")

    # A quarantined test that passes is a debt paid; say so, so the list shrinks
    # instead of silently outliving the defect it describes.
    for name in sorted(quarantined):
        outcome = found.get(tuple(name.split(" :: ", 1)))
        if outcome in (RAN, FLAKY):
            notes.append(f"RECOVERED  {name} now passes -- remove it from "
                         f"known_failing in the baseline")

    return not failures, failures, notes


def build_baseline(found: Dict[Tuple[str, str], str],
                   known_failing: Dict[str, str] | None = None) -> Dict[str, Any]:
    counts = per_viewport(found)
    # Evidence without a migration head cannot be shown to be stale, so it never
    # expires; `audit_evidence_corpus` ratchets that and was right to catch this
    # file arriving without one. The browser suite runs against a migrated
    # database, so the head is exactly what dates this evidence -- alongside the
    # source hash, which dates the bundle it describes.
    from audit_evidence_corpus import current_head
    from dependency_provenance import digest, resolved
    from measure_browser_evidence import read_provenance

    installed = resolved()
    return {
        "provenance": {
            "migration_head": current_head(),
            # The npm side needs no separate digest: `package-lock.json` is one of
            # the inputs to the bundle hash, so a dependency change there changes
            # the hash and the gate refuses the bundle.
            "bundle_source_hash": read_provenance().get("source_hash"),
            "dependencies": {"digest": digest(installed), "closure": len(installed)},
        },
        "known_failing": dict(sorted((known_failing or {}).items())),
        "note": ("One outcome per viewport per test from a full browser run. A test that "
                 "ran here may not become skipped; new tests and deletions are reported, "
                 "not gated."),
        "viewports": {project: dict(sorted(entry.items()))
                      for project, entry in sorted(counts.items())},
        # A flake is recorded as `ran`: it is coverage, and a baseline that
        # flipped between `ran` and `flaky` from run to run would make the
        # ratchet fail for reasons that have nothing to do with coverage.
        "tests": {f"{project} :: {title}": (RAN if outcome == FLAKY else outcome)
                  for (project, title), outcome in sorted(found.items())},
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", help="Playwright JSON report from measure_browser_evidence.py")
    parser.add_argument("--write-baseline", action="store_true")
    parser.add_argument("--skip-provenance", action="store_true",
                        help="Judge the report only; do not check the bundle")
    args = parser.parse_args()

    path = Path(args.report)
    if not path.exists():
        print(f"No report at {path}. Run:\n"
              f"  python oms/measure_browser_evidence.py --build --run --out {path}")
        return 1
    try:
        report = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        print(f"{path} is not readable JSON: {error}")
        return 1

    found = outcomes(report)
    if not found:
        print(f"{path} records no tests.")
        return 1

    counts = per_viewport(found)
    total_skipped = sum(entry[SKIPPED] for entry in counts.values())
    total_failed = sum(entry[FAILED] for entry in counts.values())
    total_flaky = sum(entry[FLAKY] for entry in counts.values())
    # A flaky test executed and asserted, so it is coverage; it is counted as ran
    # here and named individually below, never folded away.
    total_ran = sum(entry[RAN] + entry[FLAKY] for entry in counts.values())
    print(f"{len(found)} test runs over {len(counts)} viewport(s): "
          f"{total_ran} ran, {total_skipped} skipped, {total_failed} failed, "
          f"{total_flaky} flaky\n")
    print(f"  {'viewport':<16}{'ran':>6}{'skipped':>10}{'failed':>9}{'flaky':>8}")
    for project, entry in sorted(counts.items()):
        print(f"  {project:<16}{entry[RAN] + entry[FLAKY]:>6}{entry[SKIPPED]:>10}"
              f"{entry[FAILED]:>9}{entry[FLAKY]:>8}")

    provenance_failures, provenance_notes = ([], [])
    if not args.skip_provenance:
        provenance_failures, provenance_notes = check_provenance()

    if args.write_baseline:
        if provenance_failures:
            print("\nRefusing to record a baseline from an unpinned bundle:")
            for failure in provenance_failures:
                print(f"  {failure}")
            return 1
        BASELINE.write_text(json.dumps(build_baseline(found), indent=2) + "\n", encoding="utf-8")
        print(f"\nBaseline written to {BASELINE.relative_to(REPO_ROOT)} "
              f"({len(found)} entries, {total_skipped} of them skipped).")
        return 0

    if not BASELINE.exists():
        print(f"\nNo baseline at {BASELINE.relative_to(REPO_ROOT)}. Record one with "
              f"--write-baseline once the run is trusted.")
        return 1

    baseline = json.loads(BASELINE.read_text(encoding="utf-8"))
    ok, failures, notes = compare(found, baseline)
    failures = provenance_failures + failures
    notes = provenance_notes + notes

    if notes:
        print(f"\n{len(notes)} change(s) worth reading, none of them gated:")
        for note in notes[:30]:
            print(f"  {note}")
        if len(notes) > 30:
            print(f"  ... and {len(notes) - 30} more")

    if failures:
        print(f"\nFAIL -- {len(failures)} problem(s):")
        for failure in failures:
            print(f"  {failure}")
        return 1

    known = len(baseline.get("known_failing", {}))
    print(f"\nNo new failure, the bundle is the repository's, and no test that ran has "
          f"become skipped.")
    print(f"  {total_skipped} skip(s) and {known} known failure(s) remain; both may only "
          f"go down."
          + (f" {total_flaky} test(s) passed only on retry." if total_flaky else ""))
    return 0


if __name__ == "__main__":
    from enforcement_runs import recording

    raise SystemExit(recording("audit_browser_evidence", main))

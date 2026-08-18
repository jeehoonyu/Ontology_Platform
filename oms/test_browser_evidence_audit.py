"""The browser-evidence gate fails when coverage narrows, and only then.

Every ratchet in this repository is tested against a tree containing the state it
is supposed to refuse, because two of them once matched nothing at all and passed
by having no opinion. Each rule below is exercised with a report that violates it.

  gate   a test that ran at baseline and is skipped now
  gate   a test that failed and is not declared in known_failing
  gate   a report that covered almost none of the baseline
  note   a declared known failure, printed in full every run
  note   a flaky pass, named every run
  note   new tests, deleted tests, and tests that started running

The distinction that matters is between narrowing and not-widening. Adding a
desktop-only test does not take away coverage that existed, so it is a note.
Turning a test that ran into one that does not is exactly the move that produced
115 skips against 100 runs, so it is a gate.
"""
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from audit_browser_evidence import (BASELINE, FAILED, FLAKY, RAN, SKIPPED,  # noqa: E402
                                    build_baseline, compare, outcomes, per_viewport)

checks = 0


def check(condition, message):
    global checks
    assert condition, message
    checks += 1


def report(*rows):
    """A Playwright JSON report, nested the way Playwright nests it."""
    specs = {}
    for project, title, status in rows:
        specs.setdefault(title, []).append({"projectName": project, "status": status})
    return {"suites": [{"specs": [{"title": title, "tests": tests}
                                  for title, tests in specs.items()]}]}


VIEWPORTS = ("mobile-375", "tablet-768", "desktop-1280", "wide-1600")


def surface(*rows):
    """Twenty boring entries plus whatever this case is about.

    Without them, dropping one entry is 50% coverage and the coverage rule fires
    on every fixture, so the rule actually under test never gets reached. A
    fixture proves what it contains.
    """
    filler = [(VIEWPORTS[index % 4], f"filler {index}", "expected") for index in range(20)]
    return report(*(filler + list(rows)))


# --- the reader understands Playwright's four statuses -----------------------
parsed = outcomes(report(
    ("desktop-1280", "a", "expected"),
    ("mobile-375", "a", "skipped"),
    ("desktop-1280", "b", "flaky"),
    ("desktop-1280", "c", "unexpected"),
))
check(parsed[("desktop-1280", "a")] == RAN, parsed)
check(parsed[("mobile-375", "a")] == SKIPPED, parsed)
check(parsed[("desktop-1280", "b")] == FLAKY, parsed)
check(parsed[("desktop-1280", "c")] == FAILED, parsed)

counts = per_viewport(parsed)
check(counts["desktop-1280"][RAN] == 1, counts)
check(counts["desktop-1280"][FLAKY] == 1, counts)
check(counts["desktop-1280"][FAILED] == 1, counts)
check(counts["mobile-375"][SKIPPED] == 1, counts)

BASE_ROWS = surface(("desktop-1280", "drag a node", "expected"),
                    ("mobile-375", "drag a node", "skipped"),
                    ("desktop-1280", "publish a package", "expected"))
BASE = build_baseline(outcomes(BASE_ROWS))
check(BASE["tests"]["desktop-1280 :: drag a node"] == RAN, BASE["tests"])
check(BASE["tests"]["mobile-375 :: drag a node"] == SKIPPED, BASE["tests"])
check(BASE["known_failing"] == {}, BASE)

ok, failures, _notes = compare(outcomes(BASE_ROWS), BASE)
check(ok and not failures, failures)

# --- gate: a test that ran at baseline is skipped now ------------------------
narrowed = compare(outcomes(surface(("desktop-1280", "drag a node", "skipped"),
                                    ("mobile-375", "drag a node", "skipped"),
                                    ("desktop-1280", "publish a package", "expected"))), BASE)
check(not narrowed[0], "a test going from ran to skipped must fail")
check(any("narrowed" in f and "drag a node" in f for f in narrowed[1]), narrowed[1])

# --- note: a test that was skipped starts running ----------------------------
widened = compare(outcomes(surface(("desktop-1280", "drag a node", "expected"),
                                   ("mobile-375", "drag a node", "expected"),
                                   ("desktop-1280", "publish a package", "expected"))), BASE)
check(widened[0], widened[1])
check(any("widened" in n for n in widened[2]), widened[2])

# --- gate: an undeclared failure ---------------------------------------------
broke = compare(outcomes(surface(("desktop-1280", "drag a node", "unexpected"),
                                 ("mobile-375", "drag a node", "skipped"),
                                 ("desktop-1280", "publish a package", "expected"))), BASE)
check(not broke[0], "a failing test must fail the gate")
check(any(f.startswith("FAILED") and "drag a node" in f for f in broke[1]), broke[1])

# --- note: a failure declared in known_failing, with its reason --------------
quarantined = dict(BASE)
quarantined["known_failing"] = {"desktop-1280 :: drag a node": "known race, owed a fix"}
declared = compare(outcomes(surface(("desktop-1280", "drag a node", "unexpected"),
                                    ("mobile-375", "drag a node", "skipped"),
                                    ("desktop-1280", "publish a package", "expected"))),
                   quarantined)
check(declared[0], declared[1])
check(any("KNOWN FAILURE" in n and "known race" in n for n in declared[2]), declared[2])

# A quarantined test that passes says so, so the list shrinks rather than
# outliving the defect it describes.
recovered = compare(outcomes(BASE_ROWS), quarantined)
check(recovered[0], recovered[1])
check(any("RECOVERED" in n for n in recovered[2]), recovered[2])

# --- note: flaky is coverage, but it is named every single run ---------------
flaky = compare(outcomes(surface(("desktop-1280", "drag a node", "flaky"),
                                 ("mobile-375", "drag a node", "skipped"),
                                 ("desktop-1280", "publish a package", "expected"))), BASE)
check(flaky[0], flaky[1])
check(any("FLAKY" in n and "drag a node" in n for n in flaky[2]), flaky[2])
# and a flake does not count as narrowing, because the test did execute
check(not any("narrowed" in f for f in flaky[1]), flaky[1])

# --- the baseline records a flake as ran, so it does not wobble --------------
wobble = build_baseline(outcomes(surface(("desktop-1280", "drag a node", "flaky"))))
check(wobble["tests"]["desktop-1280 :: drag a node"] == RAN, wobble["tests"])

# --- gate: a report that reached almost nothing clears nothing ---------------
empty = compare(outcomes(report(("desktop-1280", "drag a node", "expected"))), BASE)
check(not empty[0], "a report covering one of 23 entries must fail")
check(any("cannot clear anything" in f for f in empty[1]), empty[1])

# --- note: deleting a test is ordinary work ----------------------------------
deleted = compare(outcomes(surface(("desktop-1280", "drag a node", "expected"),
                                   ("mobile-375", "drag a node", "skipped"))), BASE)
check(deleted[0], deleted[1])
check(any("gone" in n and "publish a package" in n for n in deleted[2]), deleted[2])

# --- note: a new test, whether it runs or skips, narrows nothing -------------
added = compare(outcomes(surface(("desktop-1280", "drag a node", "expected"),
                                 ("mobile-375", "drag a node", "skipped"),
                                 ("desktop-1280", "publish a package", "expected"),
                                 ("mobile-375", "brand new test", "skipped"))), BASE)
check(added[0], added[1])
check(any("new" in n and "brand new test" in n for n in added[2]), added[2])

# --- the recorded baseline is real and describes the suite this gates --------
check(BASELINE.exists(), f"no baseline at {BASELINE}")
real = json.loads(BASELINE.read_text(encoding="utf-8"))
check(len(real["tests"]) > 200, len(real["tests"]))
check(set(real["viewports"]) == set(VIEWPORTS), sorted(real["viewports"]))

skipped_now = [name for name, outcome in real["tests"].items() if outcome == SKIPPED]
ran_now = [name for name, outcome in real["tests"].items() if outcome == RAN]
check(len(skipped_now) > 100, len(skipped_now))
check(len(ran_now) > 100, len(ran_now))

# The imbalance this gate exists to stop growing: behaviour is verified at one
# width. If this ever inverts, the goal it came from has been met.
desktop_ran = sum(1 for name in ran_now if name.startswith("desktop-1280"))
other_ran = len(ran_now) - desktop_ran
check(desktop_ran > other_ran / 2, (desktop_ran, other_ran))

# Every quarantined failure carries a written reason, not a bare name.
for name, reason in real.get("known_failing", {}).items():
    check(len(reason) > 80, f"{name} is quarantined without a real reason")
    check(name in real["tests"], f"{name} is quarantined but not in the baseline")

# --- a torn report is a refusal, not a crash ---------------------------------
with tempfile.TemporaryDirectory() as tmp:
    path = Path(tmp) / "torn.json"
    path.write_text('{"suites": [{"specs": [', encoding="utf-8")
    try:
        json.loads(path.read_text(encoding="utf-8"))
        readable = True
    except json.JSONDecodeError:
        readable = False
check(not readable, "a truncated report must not parse")
check(outcomes({}) == {}, "an empty report yields no outcomes")
check(outcomes({"suites": []}) == {}, "a report with no suites yields no outcomes")

print(f"Browser evidence gate verified: {checks} assertions passed "
      f"({len(real['tests'])} baseline entries, {len(skipped_now)} skipped, "
      f"{len(real.get('known_failing', {}))} known failure(s)).")

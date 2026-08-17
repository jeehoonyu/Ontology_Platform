"""The suite-cost ratchet fails when a route gets worse, and only then.

Every ratchet in this repository has been tested against a tree containing the
state it is supposed to refuse, because two of them turned out to match nothing
at all and passed by having no opinion. The same discipline here: each rule below
is exercised with a census that violates it.

The rules under test, and why each is a gate or a note:

  gate   a route repeating a shape more often than its baseline
  gate   a route absent from the baseline arriving above the ceiling
  gate   a watched route (already above the ceiling) missing from the census
  gate   a census that covered almost none of the baseline
  note   statement counts, new routes under the ceiling, improvements

The last of those is not squeamishness. Two full censuses agreed on the worst
repeat for 695 of 695 route+method pairs and on the statement count for 692; the
three that moved are recorded in the module docstring. Gating a number that
moves on its own teaches people to re-run until it passes, which is worse than
not gating it.
"""
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from audit_suite_cost import (BASELINE, REPEAT_CEILING, aggregate, build_baseline,  # noqa: E402
                              compare, load_baseline, load_census)

checks = 0


def check(condition, message):
    global checks
    assert condition, message
    checks += 1


def census(*rows):
    return [{"method": m, "route": r, "status": 200, "queries": q,
             "distinct_shapes": max(1, q // 2), "worst_repeat": w,
             "worst_shape": "SELECT ? FROM t"} for m, r, q, w in rows]


# Twenty routes that do nothing interesting, so that dropping one from a census
# is 95% coverage rather than 67%. Without them the coverage rule fires on every
# fixture and the rule under test never gets reached -- a fixture proves what it
# contains, and this one has to contain a plausible surface.
FILLER = census(*[("GET", f"/filler/{index}", 3, 1) for index in range(20)])


def surface(*rows):
    """A census of the boring routes plus whatever this case is about."""
    return FILLER + census(*rows)


BASE_ROWS = surface(("GET", "/things", 10, 2),
                    ("POST", "/things", 20, 4),
                    ("POST", "/heavy", 900, 400))
BASE = build_baseline(aggregate(BASE_ROWS))

check(BASE["routes"]["POST /heavy"]["worst_repeat"] == 400, BASE)
check(BASE["repeat_ceiling"] == REPEAT_CEILING, BASE)

# The unchanged surface passes.
ok, failures, _notes = compare(aggregate(BASE_ROWS), BASE)
check(ok and not failures, failures)

# --- gate: an existing route repeats a shape more than it used to ------------
worse = compare(aggregate(surface(("GET", "/things", 10, 2),
                                  ("POST", "/things", 20, 5),
                                  ("POST", "/heavy", 900, 400))), BASE)
check(not worse[0], "a route going from 4 repeats to 5 must fail")
check(any("POST /things" in f and "baseline 4" in f for f in worse[1]), worse[1])

# One more repeat on the worst offender fails too. Debt is frozen at the number
# measured, not at "roughly a thousand".
creep = compare(aggregate(surface(("GET", "/things", 10, 2),
                                  ("POST", "/things", 20, 4),
                                  ("POST", "/heavy", 900, 401))), BASE)
check(not creep[0], "x400 -> x401 on a route already in debt must fail")

# --- note: an improvement passes, and says the baseline should move ----------
better = compare(aggregate(surface(("GET", "/things", 10, 2),
                                  ("POST", "/things", 20, 4),
                                  ("POST", "/heavy", 40, 3))), BASE)
check(better[0], better[1])
check(any("baseline should be lowered" in n for n in better[2]), better[2])

# --- gate: new code is held to the ceiling, not grandfathered ----------------
newly_bad = compare(aggregate(BASE_ROWS + census(("POST", "/fresh", 500, 90))), BASE)
check(not newly_bad[0], "a new route at 90 repeats must fail")
check(any("/fresh" in f and "new route" in f for f in newly_bad[1]), newly_bad[1])

# A new route inside the ceiling is a note, not a failure.
newly_fine = compare(aggregate(BASE_ROWS + census(("POST", "/fresh", 30, REPEAT_CEILING))),
                     BASE)
check(newly_fine[0], newly_fine[1])
check(any("/fresh" in n and "new route" in n for n in newly_fine[2]), newly_fine[2])

# The boundary is the ceiling itself: at the ceiling passes, one above fails.
edge = compare(aggregate(BASE_ROWS + census(("POST", "/edge", 30, REPEAT_CEILING + 1))), BASE)
check(not edge[0], f"a new route at {REPEAT_CEILING + 1} must fail")

# --- gate: a watched route may not go dark ----------------------------------
gone = compare(aggregate(surface(("GET", "/things", 10, 2),
                                 ("POST", "/things", 20, 4))), BASE)
check(not gone[0], "dropping the x400 route from the census must fail")
check(any("/heavy" in f and "go dark" in f for f in gone[1]), gone[1])

# A route *under* the ceiling disappearing is not a failure -- routes get
# deleted, and the ratchet is not a route inventory.
quiet = compare(aggregate(surface(("POST", "/things", 20, 4),
                                  ("POST", "/heavy", 900, 400))), BASE)
check(quiet[0], quiet[1])

# --- gate: a census that reached almost nothing clears nothing ---------------
empty = compare(aggregate(census(("GET", "/things", 10, 2))), BASE)
check(not empty[0], "a census covering a third of the baseline must fail")
check(any("cannot clear a route of anything" in f for f in empty[1]), empty[1])

# --- note: statement drift alone never fails --------------------------------
drifted = compare(aggregate(surface(("GET", "/things", 999, 2),
                                    ("POST", "/things", 20, 4),
                                    ("POST", "/heavy", 900, 400))), BASE)
check(drifted[0], drifted[1])
check(any("10 -> 999 statements (+989)" in n for n in drifted[2]), drifted[2])

# --- the worst observation wins, never the mean -----------------------------
many = aggregate(census(("POST", "/x", 5, 1), ("POST", "/x", 5, 1),
                        ("POST", "/x", 800, 99), ("POST", "/x", 5, 1)))
check(many[("POST", "/x")]["worst_repeat"] == 99, many)
check(many[("POST", "/x")]["queries"] == 800, many)
check(many[("POST", "/x")]["calls"] == 4, many)

# --- the recorded baseline is real and self-consistent ----------------------
check(BASELINE.exists(), f"no baseline at {BASELINE}")
real = load_baseline(BASELINE)
check(real["repeat_ceiling"] == REPEAT_CEILING, real["repeat_ceiling"])
check(len(real["routes"]) > 600, len(real["routes"]))
writes = [name for name in real["routes"]
          if name.split(" ", 1)[0] in {"POST", "PUT", "PATCH", "DELETE"}]
check(len(writes) > 300, len(writes))

# The surface this ratchet exists for: write routes above the ceiling, which the
# GET walk never issues. If this ever reads zero the gate has lost its subject.
debt = {name: entry for name, entry in real["routes"].items()
        if entry["worst_repeat"] > REPEAT_CEILING}
check(len(debt) >= 30, len(debt))
check(any(name.startswith(("POST", "PUT", "PATCH", "DELETE")) for name in debt), debt)
check("POST /pipeline-builder/workers/run-next" in debt, sorted(debt)[:5])
check(debt["POST /pipeline-builder/workers/run-next"]["worst_repeat"] >= 1000, debt)

# A malformed line in a census is skipped, not fatal: the recorder appends from
# 225 subprocesses and a torn write must not take the gate down with it.
with tempfile.TemporaryDirectory() as tmp:
    path = Path(tmp) / "torn.jsonl"
    path.write_text('{"method": "GET", "route": "/a", "queries": 3, "worst_repeat": 1}\n'
                    '{"method": "GET", "route": "/b", "quer\n'
                    '{"method": "GET", "route": "/c", "queries": 4, "worst_repeat": 2}\n',
                    encoding="utf-8")
    rows = load_census(path)
check(len(rows) == 2, rows)
check({row["route"] for row in rows} == {"/a", "/c"}, rows)

print(f"Suite cost ratchet verified: {checks} assertions passed "
      f"({len(real['routes'])} routes baselined, {len(debt)} above the ceiling of "
      f"{REPEAT_CEILING}).")

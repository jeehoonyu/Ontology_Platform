"""The ratchet has to fail on the thing it was built for, and only on that.

An audit that has only ever been run against a passing tree is an assertion
about that tree. These build the states it is supposed to catch and the states
it must not, because the second list is what decides whether anyone keeps it.

The distinction it exists to hold: a repeated statement shape is gated, a large
total is not. `/project/export` issues 139 queries and 138 of them are distinct
-- one per exported collection, which is what exporting everything costs. An
audit that failed on totals would fail that endpoint forever, and a check people
have to route around is worse than no check.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import audit_request_cost as audit  # noqa: E402

passed = 0


def check(condition, label, payload=None):
    global passed
    assert condition, f"{label}: {payload}"
    passed += 1


def row(queries, shapes, repeat):
    return {"queries": queries, "distinct_shapes": shapes, "worst_repeat": repeat}


CEILING = audit.REPEAT_CEILING
check(CEILING >= 2, "the ceiling leaves room for an honest repeat", CEILING)

# --- what must fail ---------------------------------------------------------

failures, _notes = audit.compare(
    {"/loopy": row(queries=40, shapes=3, repeat=CEILING + 1)},
    {"/loopy": row(queries=40, shapes=3, repeat=CEILING + 1)},
)
check(len(failures) == 1, "a shape over the ceiling fails", failures)
check("/loopy" in failures[0], "the failure names the route", failures)
check(str(CEILING) in failures[0], "and the ceiling it broke", failures)

# It fails even when the baseline already recorded it. A ratchet that grandfathers
# whatever was there when it was written enforces nothing on the code that
# already exists -- and the loops this was built for were all pre-existing.
check(audit.compare({"/old": row(20, 2, CEILING + 5)}, {"/old": row(20, 2, CEILING + 5)})[0],
      "a pre-existing violation is not grandfathered by the baseline", None)

# The migration-record and command-center defects, at the counts they had.
for repeat, name in ((32, "the migration records loop"), (13, "the command-center counts")):
    caught, _ = audit.compare({"/was": row(300, 200, repeat)}, {})
    check(len(caught) == 1, f"{name} would have been caught", (repeat, caught))

# --- what must NOT fail -----------------------------------------------------

failures, notes = audit.compare(
    {"/project/export": row(queries=139, shapes=138, repeat=2)},
    {"/project/export": row(queries=139, shapes=138, repeat=2)},
)
check(failures == [], "139 distinct queries is not a failure", failures)
check(notes == [], "and an unchanged route is not even drift", notes)

# Drift is reported, never gated. If a route grows a query the audit says so and
# exits 0 -- otherwise every ordinary change fails the build, which is how a
# check gets deleted.
failures, notes = audit.compare({"/thing": row(12, 12, 1)}, {"/thing": row(9, 9, 1)})
check(failures == [], "a route growing three queries does not fail", failures)
check(any("+3" in note for note in notes), "the growth is reported with its size", notes)

failures, notes = audit.compare({"/new": row(4, 4, 1)}, {})
check(failures == [], "a new route does not fail", failures)
check(any("new route" in note and "/new" in note for note in notes),
      "a new route is reported", notes)

failures, notes = audit.compare({}, {"/gone": row(4, 4, 1)})
check(failures == [], "a route that stopped being measured does not fail", failures)
check(any("/gone" in note for note in notes), "but it is reported", notes)

# A route at exactly the ceiling passes; the ceiling is a limit, not a target.
check(audit.compare({"/edge": row(9, 3, CEILING)}, {})[0] == [],
      "exactly at the ceiling is allowed", None)

# --- the recorded baseline ---------------------------------------------------

check(audit.BASELINE.exists(), "a baseline is committed", audit.BASELINE)
payload = json.loads(audit.BASELINE.read_text(encoding="utf-8"))
routes = payload.get("routes") or {}
check(len(routes) > 100, "the baseline covers the collection surface", len(routes))
check(payload.get("repeat_ceiling") == CEILING,
      "the baseline records the ceiling it was taken under", payload.get("repeat_ceiling"))
for path, recorded in routes.items():
    check(set(recorded) == {"queries", "distinct_shapes", "worst_repeat"},
          "each baseline row carries all three numbers", (path, recorded))
    break
worst = max(recorded["worst_repeat"] for recorded in routes.values())
check(worst <= CEILING,
      "the committed baseline satisfies its own ceiling, so the tree starts clean", worst)

# --- and it runs end to end --------------------------------------------------
#
# The fixture cases prove the logic; this proves the measurement still boots the
# app and walks the surface. Without it the audit could rot into something that
# passes because it measures nothing, which is a failure mode this repository
# has already met twice.

argv = sys.argv[:]
try:
    sys.argv = ["audit_request_cost.py"]
    code = audit.main()
finally:
    sys.argv = argv
check(code == 0, "the audit passes against the current tree", code)

measured = audit.measure_surface()
check(len(measured) > 100, "the walk measures the whole collection surface", len(measured))
check(max(item["worst_repeat"] for item in measured.values()) <= CEILING,
      "no route currently exceeds the ceiling",
      max(item["worst_repeat"] for item in measured.values()))

print(f"Request cost audit verified: {passed} assertions passed "
      f"({len(measured)} routes measured, ceiling {CEILING}).")

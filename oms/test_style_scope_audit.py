"""A class that couples a second screen must be declared, not discovered later.

Also this check's home: `audit_style_scope` declares `every suite run`, and
`audit_iteration_state` fails a check whose cadence names a place it does not run.

J2 asked for the measurement before the work, and the measurement decided the
work. 358 classes in one stylesheet: 297 used by exactly one file, 33 by more
than one. Scoping the 297 would rewrite hundreds of sites across twenty-two
files to remove a coupling that is mostly theoretical -- a class one file uses
cannot restyle another. The 33 are the coupling, and they are the design system
nobody had named: `.button-row` in twenty files, `.empty` in thirteen.

So the gate is on the *event*, not the layout: a class going from one user to two
is the moment a change to it starts moving two screens.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from audit_style_scope import BASELINE, compare, scan, shared_of  # noqa: E402

checks = 0


def check(condition, message):
    global checks
    assert condition, message
    checks += 1


DEFINED = {"solo", "pair", "everywhere", "gone"}
USERS = {"solo": ["a.tsx"], "pair": ["a.tsx", "b.tsx"],
         "everywhere": ["a.tsx", "b.tsx", "c.tsx"]}
BASE = {"shared": {"pair": ["a.tsx", "b.tsx"], "everywhere": ["a.tsx", "b.tsx", "c.tsx"]}}

check(set(shared_of(USERS)) == {"pair", "everywhere"}, shared_of(USERS))
check("solo" not in shared_of(USERS), "a class with one user is not shared")

ok, failures, _notes = compare(DEFINED, USERS, BASE)
check(ok and not failures, failures)

# --- gate: a single-file class gains a second screen -------------------------
coupled = dict(USERS, solo=["a.tsx", "d.tsx"])
grew = compare(DEFINED, coupled, BASE)
check(not grew[0], "a class going from one file to two must fail")
check(any(".solo" in f and "was used by one" in f for f in grew[1]), grew[1])
check(any("d.tsx" in f for f in grew[1]), "the failure must name the second screen")

# --- note: an already-shared class gaining another user ----------------------
wider = compare(DEFINED, dict(USERS, pair=["a.tsx", "b.tsx", "e.tsx"]), BASE)
check(wider[0], "a class that was already shared may spread; it is a note")
check(any(".pair" in n and "2 -> 3" in n for n in wider[2]), wider[2])

# --- gate: a declared shared class vanishing from the stylesheet -------------
deleted = compare({"solo", "everywhere", "gone"}, USERS, BASE)
check(not deleted[0], "deleting a class thirteen files use must fail")
check(any(".pair" in f and "no longer defined" in f for f in deleted[1]), deleted[1])

# --- note: a class that stopped being shared ---------------------------------
narrowed = compare(DEFINED, dict(USERS, pair=["a.tsx"]), BASE)
check(narrowed[0], narrowed[1])
check(any("no longer shared" in n for n in narrowed[2]), narrowed[2])

# --- the live stylesheet ------------------------------------------------------
defined, users, unlisted = scan()
check(len(defined) > 300, len(defined))
shared = shared_of(users)
single = sum(1 for files in users.values() if len(files) == 1)
check(single > len(shared) and single > 200, (single, len(shared)))

check(BASELINE.exists(), f"no baseline at {BASELINE}")
recorded = json.loads(BASELINE.read_text(encoding="utf-8"))
check(recorded["provenance"]["stale_after"] == "recomputed each run", recorded)
# The design system the measurement found. If `.button-row` ever stops being the
# most shared class, the stylesheet has been restructured and this baseline is
# describing something that no longer exists.
check("button-row" in recorded["shared"], sorted(recorded["shared"])[:6])
check(len(recorded["shared"]["button-row"]) >= 15, recorded["shared"]["button-row"])

# Classes no literal mentions are reported, never gated: sixteen of them are
# assembled at runtime, so "no literal" is not "unused".
check(unlisted, "the scan found no dynamically-built classes, which is suspicious")

print(f"Style scope gate verified: {checks} assertions passed "
      f"({len(defined)} classes, {len(shared)} shared, {single} single-file, "
      f"{len(unlisted)} built dynamically or unused).")

"""The empty-state gate refuses a new hand-written copy, and only that.

This is also the check's home: `audit_ui_states` declares `every suite run`, and
`audit_iteration_state` fails any check whose declared cadence names a place it
does not run.

What the gate is for is narrower than it first looks. Two treatments of "there is
nothing here" exist, they look different on purpose, and neither is wrong: the
bare `.empty` line and the `.empty-state-card`. The defect was that only the card
had a component, so the other was 42 hand-written copies that nothing could count
or change in one place.

So this does not police which treatment a screen picks. It refuses a *new copy*
of either, and it refuses a new class name that has not said what the existing
ones cannot express.
"""
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from audit_ui_states import BASELINE, DECLARED, compare, scan  # noqa: E402

checks = 0


def check(condition, message):
    global checks
    assert condition, message
    checks += 1


BASE = {"raw_empty_ceiling": 5}

# The recorded surface passes itself.
ok, failures, _notes = compare(Counter({"empty": 5}), {"a.tsx": 5}, BASE)
check(ok and not failures, failures)

# --- gate: one more hand-written copy ----------------------------------------
grew = compare(Counter({"empty": 6}), {"a.tsx": 5, "b.tsx": 1}, BASE)
check(not grew[0], "a sixth raw site must fail against a ceiling of five")
check(any("EmptyState inline" in f for f in grew[1]),
      "the failure must say what to use instead")

# --- note: a migration asks for the ceiling to be lowered --------------------
shrank = compare(Counter({"empty": 3}), {"a.tsx": 3}, BASE)
check(shrank[0], shrank[1])
check(any("lock the improvement in" in n for n in shrank[2]), shrank[2])

# --- gate: a treatment nobody has justified ----------------------------------
novel = compare(Counter({"empty": 5, "brand-new-empty": 1}), {"a.tsx": 5}, BASE)
check(not novel[0], "an undeclared treatment must fail")
check(any("brand-new-empty" in f for f in novel[1]), novel[1])

# A declared one passes, and the reason is what makes it declared.
known = compare(Counter({"empty": 5, "health-empty": 1}), {"a.tsx": 5}, BASE)
check(known[0], known[1])

# Every declared treatment says something a reader can act on, rather than
# merely existing on the list.
for name, reason in DECLARED.items():
    check(len(reason) > 25, f"{name} is declared without a real reason: {reason!r}")

# --- the live tree ------------------------------------------------------------
classes, per_file = scan()
raw_total = sum(per_file.values())
check(classes, "the scan found no empty-state treatments at all")
check(raw_total > 0, "the bare form is still in use; a zero here means the scan broke")
check(not [name for name in classes if name not in DECLARED],
      f"undeclared treatments in the tree: {[n for n in classes if n not in DECLARED]}")

# The card and the bare form both survive. If either disappears, the gate has
# lost half its subject and the DECLARED list needs revisiting rather than
# quietly passing.
check("empty" in classes, "the bare form vanished from the tree")

check(BASELINE.exists(), f"no baseline at {BASELINE}")
recorded = json.loads(BASELINE.read_text(encoding="utf-8"))
check(raw_total <= recorded["raw_empty_ceiling"],
      f"{raw_total} raw sites against a ceiling of {recorded['raw_empty_ceiling']}")

print(f"Empty-state gate verified: {checks} assertions passed "
      f"({len(classes)} declared treatments, {raw_total} raw site(s) remaining, "
      f"ceiling {recorded['raw_empty_ceiling']}).")

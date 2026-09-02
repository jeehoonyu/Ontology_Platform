"""The frontier is executed here, and it can actually fail.

Suite home for `audit_frontier`, which `audit_check_coverage` requires. The
assertions worth making are about the two ways this check could be useless: if it
found nothing it would pass vacuously forever, and if it could not distinguish an
owned gap from an unowned one it would pass vacuously too.

  python oms/test_frontier.py
"""
import io
import sys
from contextlib import redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import audit_frontier  # noqa: E402

passed = 0


def check(condition, label, payload=None):
    global passed
    assert condition, f"{label}: {payload}"
    passed += 1


rows = audit_frontier.gaps()
check(rows, "the frontier finds the ratchets that record a distance", rows)
check(all(row["distance"] > 0 for row in rows),
      "and only counts ceilings above zero -- a ratchet at 0 is not a gap", rows)
check(rows == sorted(rows, key=lambda r: -r["distance"]),
      "sorted by distance, so the report has an order that means something")

# A limit is not a debt. repeat_ceiling: 6 says no route may repeat one statement
# shape more than six times; counting it as six outstanding items would inflate
# the frontier with work nobody owes.
names = {row["baseline"] for row in rows}
for threshold in audit_frontier.THRESHOLDS:
    check(threshold not in names,
          f"{threshold} records a threshold, not a distance, and is excluded", sorted(names))

conditions = audit_frontier._condition_text()
check(conditions, "there are open or blocked conditions to own gaps", len(conditions))
for row in rows:
    check(audit_frontier.owners(row, conditions),
          f"{row['measure']} ({row['distance']}) is owned by some open condition",
          "a ratchet recorded and unowned is a number nobody is answerable for")

# Both spellings. A condition naming the measure in code style writes
# `raw_empty_ceiling`; one naming it in prose writes "raw empty". The first draft
# tried only the prose form and called an exactly-named condition unowned.
gap = {"baseline": "ui-states-baseline.json", "measure": "raw_empty_ceiling", "distance": 32}
for spelling in ("raw_empty_ceiling", "raw empty", "ui-states", "ui states"):
    check(audit_frontier.owners(gap, {"doc:X": f"a condition mentioning {spelling} here"}),
          f"a condition naming it as `{spelling}` counts as owning it")
check(not audit_frontier.owners(gap, {"doc:X": "a condition about something else entirely"}),
      "and one that never names it does not")

argv = sys.argv[:]
sys.argv = ["audit_frontier"]
try:
    with redirect_stdout(io.StringIO()) as captured:
        code = audit_frontier.main()
finally:
    sys.argv = argv
check(code == 0, "every measured gap is owned right now", captured.getvalue()[-300:])

print(f"Frontier verified: {passed} assertions passed "
      f"({len(rows)} gaps, largest {rows[0]['measure']} at {rows[0]['distance']}).")

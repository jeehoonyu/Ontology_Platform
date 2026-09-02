"""The motion census is executed here, not merely declared.

Suite home for `audit_ratchet_motion`, which `audit_check_coverage` requires.

Two things about this check are easy to get wrong in a direction nobody would notice, so
they are asserted rather than trusted. It must not count a ceiling recorded for the first
time -- charging the cost of measuring something to whoever measured it is how a
repository stops measuring. And it must not demand motion from a cost threshold, whose
ceiling is a limit that should hold rather than a debt that should shrink; a gate insisting
those fall is a gate insisting the budget be cut every release.

  python oms/test_ratchet_motion.py
"""
import io
import sys
from contextlib import redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import audit_ratchet_motion  # noqa: E402

passed = 0


def check(condition, label, payload=None):
    global passed
    assert condition, f"{label}: {payload}"
    passed += 1


reading = audit_ratchet_motion.read()

check(reading["ratchets"] > 10, "the census finds the recorded ratchets", reading["ratchets"])
check(len(reading["moved"]) + len(reading["unmoved"]) + len(reading["fresh"])
      == reading["ratchets"], "every ratchet lands in exactly one bucket", reading)
check(len(reading["moved"]) > len(reading["unmoved"]),
      "most ratchets have been paid down at least once -- if that inverted, this "
      "repository is recording measurements it does not act on", reading)

named = {record["measure"] for record in
         reading["moved"] + reading["unmoved"] + reading["fresh"]}
check(all(name.endswith("_ceiling") for name in named),
      "only ceilings are judged; reference values are not debts", sorted(named))

# A cost threshold's ceiling is a budget. Demanding it fall would demand the budget be cut.
for excluded in ("request-cost-baseline.json", "suite-cost-baseline.json"):
    check(excluded in audit_ratchet_motion.THRESHOLDS,
          f"{excluded} is a limit to hold, not a debt to shrink", excluded)
sources = {record["baseline"] for record in
           reading["moved"] + reading["unmoved"] + reading["fresh"]}
check(not (sources & audit_ratchet_motion.THRESHOLDS),
      "and no threshold reached the verdict", sorted(sources & audit_ratchet_motion.THRESHOLDS))

# A first recording is exempt, and stops being exempt once the file is written again.
for record in reading["fresh"]:
    check(record["versions"] <= 1,
          "only a ceiling nobody has revisited counts as fresh", record)
for record in reading["unmoved"]:
    check(record["versions"] > 1,
          "a ceiling is only held against its owner once the file was revisited", record)
    check(record["now"] > 0, "a ceiling already at zero has nothing left to lower", record)

check(audit_ratchet_motion.read()["unmoved"] == reading["unmoved"],
      "the census is reproducible, or a ratchet on it means nothing", None)

argv = sys.argv[:]
sys.argv = ["audit_ratchet_motion"]
try:
    with redirect_stdout(io.StringIO()) as captured:
        code = audit_ratchet_motion.main()
finally:
    sys.argv = argv
check(code == 0, "and the ratchet holds against its recorded ceiling",
      captured.getvalue()[-200:])

print(f"Ratchet motion verified: {passed} assertions passed "
      f"({len(reading['unmoved'])} never lowered of {reading['ratchets']}).")

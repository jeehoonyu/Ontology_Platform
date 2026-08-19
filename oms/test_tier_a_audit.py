"""Tier A's state is computed, and a sub-condition that was met may not regress.

This is also the check's home. `audit_tier_a` declares `every suite run`, and two
gates caught it within a minute of being written for not having one:
`audit_iteration_state` because its declared cadence named a place it did not
run, and `audit_check_coverage` because it was unautomated. Both were right.

The case that matters most here is the matrix parser. Counting occurrences of
`PARTIAL` in `VALIDATION_MATRIX.md` finds one every time, because the legend at
the top of the file explains what `PARTIAL` means. That is how the check was
first written by hand, and it produced a finding -- "two MISSING and one PARTIAL
row block Tier A" -- that was entirely an artifact of reading the legend. The
real answer is 73 rows and none of them PARTIAL or MISSING.

So the parser reads table cells, and the fixture below contains a legend, to
prove it is not counted.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import audit_tier_a as audit  # noqa: E402
from audit_tier_a import MET, UNAVAILABLE, UNMET, compare, evaluate  # noqa: E402

checks = 0


def check(condition, message):
    global checks
    assert condition, message
    checks += 1


# --- the legend is prose, not data -------------------------------------------
LEGEND_AND_ROWS = """
Statuses used below:

- `PARTIAL`: the behavior exists but lacks documented depth or visual fidelity.
- `MISSING`: no meaningful local behavior exists yet.

| Capability | Priority | Status |
| --- | --- | --- |
| Object explorer | P0 | `MATCH` |
| Pipeline builder | P0 | `LOCAL_ANALOG` |
| Something deliberate | P1 | `INTENTIONAL_DIFFERENCE` |
"""

original = audit.MATRIX
try:
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "VALIDATION_MATRIX.md"
        path.write_text(LEGEND_AND_ROWS, encoding="utf-8")
        audit.MATRIX = path
        rows, counts = audit.matrix_rows()
        check(rows == 3, f"three table rows, got {rows}")
        check("PARTIAL" not in counts,
              "the legend's mention of PARTIAL must not be counted as a row")
        check("MISSING" not in counts, "same for MISSING")
        state, detail = audit.check_matrix()
        check(state == MET, (state, detail))

        # A real PARTIAL row, in the table, must be seen.
        path.write_text(LEGEND_AND_ROWS + "| Half-built thing | P0 | `PARTIAL` |\n",
                        encoding="utf-8")
        rows, counts = audit.matrix_rows()
        check(counts.get("PARTIAL") == 1, counts)
        check(audit.check_matrix()[0] == UNMET, "a PARTIAL row must read unmet")

        # A missing matrix is unavailable, never a pass.
        audit.MATRIX = Path(tmp) / "absent.md"
        check(audit.check_matrix()[0] == UNAVAILABLE, "an absent matrix cannot be met")
finally:
    audit.MATRIX = original

# --- gate: a sub-condition that was met may not become unmet ------------------
BASE = {"sub_conditions": {"a": MET, "b": MET, "c": UNAVAILABLE}}

ok, failures, _notes = compare([("a", MET, ""), ("b", MET, ""), ("c", UNAVAILABLE, "")], BASE)
check(ok and not failures, failures)

broke = compare([("a", UNMET, "it broke"), ("b", MET, ""), ("c", UNAVAILABLE, "")], BASE)
check(not broke[0], "met -> unmet must fail")
check(any("was met, now unmet" in f for f in broke[1]), broke[1])

# Becoming uncheckable is a note, not a pass and not a failure: the evidence did
# not contradict anything, it simply was not gathered.
dark = compare([("a", UNAVAILABLE, "no postgres"), ("b", MET, ""), ("c", UNAVAILABLE, "")], BASE)
check(dark[0], dark[1])
check(any("could not be checked here" in n for n in dark[2]), dark[2])

# Newly met is a note asking for the baseline to move.
gained = compare([("a", MET, ""), ("b", MET, ""), ("c", MET, "")], BASE)
check(gained[0], gained[1])
check(any("now met" in n for n in gained[2]), gained[2])

# --- the live tree ------------------------------------------------------------
results = evaluate(deep=False, report=None)
check(len(results) >= 8, len(results))
states = {label: state for label, state, _ in results}
check(states["validation matrix has no PARTIAL or MISSING row"] == MET, states)
check(states["documentation conformance passes"] == MET, states)

# `unavailable` is counted apart from `met` on purpose. If this ever reads zero
# unavailable and zero unmet, Tier A is claimable and the goal document should
# say so rather than this file quietly passing.
unavailable = [label for label, state, _ in results if state == UNAVAILABLE]
check(not [label for label, state, _ in results if state == UNMET],
      f"unmet sub-conditions: {[l for l, s, _ in results if s == UNMET]}")

check(audit.BASELINE.exists(), f"no baseline at {audit.BASELINE}")
recorded = json.loads(audit.BASELINE.read_text(encoding="utf-8"))
check(recorded["provenance"]["stale_after"] == "recomputed each run", recorded)
met_at_baseline = [k for k, v in recorded["sub_conditions"].items() if v == MET]
check(len(met_at_baseline) >= 4, met_at_baseline)

print(f"Tier A audit verified: {checks} assertions passed "
      f"({len(met_at_baseline)} sub-condition(s) recorded met, "
      f"{len(unavailable)} unavailable on this machine).")

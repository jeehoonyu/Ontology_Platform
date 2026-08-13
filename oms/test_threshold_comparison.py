"""Every Tier B verdict is derived here, so the ways it can be wrong matter.

`compare` is the single function that turns measurements into a PASS or a list of
breaches. Ten gates depend on it and none of them tested it directly. These cases
are the ones where a wrong answer is silent: a threshold that cannot fail, a
missing measurement that reads as satisfied, or a reading the comparison cannot
perform at all.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from tier_b_evidence import build_evidence_provenance, compare, current_head  # noqa: E402

passed = 0


def check(condition, label, payload=None):
    global passed
    assert condition, f"{label}: {payload}"
    passed += 1


check(compare({"latency_ms_max": 300.0}, {"latency_ms": 9.7}) == [],
      "a value inside a maximum satisfies it")
check(compare({"latency_ms_max": 300.0}, {"latency_ms": 300.0}) == [],
      "a value exactly at the maximum satisfies it")
check(compare({"latency_ms_max": 300.0}, {"latency_ms": 300.1}) != [],
      "a value past the maximum breaches")

check(compare({"objects_min": 10}, {"objects": 10}) == [],
      "a value exactly at the minimum satisfies it")
check(compare({"objects_min": 10}, {"objects": 9}) != [],
      "a value below the minimum breaches")

# A measurement that was never taken must never read as satisfied. This is the
# same failure the durability aggregator guards against from the other side: a
# `_max` with nothing to compare would otherwise pass for want of a maximum.
absent = compare({"latency_ms_max": 300.0}, {})
check(absent and "not measured" in absent[0], "an absent measurement breaches", absent)

# A harness that could not take a reading records None. Comparing it used to
# raise, which aborted the run before any evidence was written -- so the gate
# disappeared instead of failing, and an auditor reading the corpus would see one
# fewer gate rather than one more failure.
null = compare({"latency_ms_max": 300.0}, {"latency_ms": None})
check(null and "not measured" in null[0], "a null measurement breaches", null)
try:
    compare({"latency_ms_max": 300.0}, {"latency_ms": None})
    passed += 1
except TypeError:
    raise AssertionError("a null measurement raised instead of breaching")

# A threshold whose key carries no direction cannot be checked. Silently
# ignoring it would let a gate declare a bound it never applies.
undirected = compare({"latency_ms": 300.0}, {"latency_ms": 9.7})
check(undirected and "no _max/_min direction" in undirected[0],
      "a threshold with no direction is itself a breach", undirected)

# Every breach is reported, not just the first: a run that fails three ways
# should not have to be repeated three times to learn that.
several = compare(
    {"a_max": 1, "b_min": 10, "c_max": 5},
    {"a": 2, "b": 1, "c": 99},
)
check(len(several) == 3, "every unmet threshold is reported", several)

# The 0/1 encoding the scale gate uses to assert which path served a facet.
# `compare` is numeric, so "came from the rollup" has to be a number, and it has
# to fail when the path changes even if the latency happens to look fine.
gate = {"facet_p95_ms_max": 300.0, "facet_from_rollup_min": 1}
check(compare(gate, {"facet_p95_ms": 9.686, "facet_from_rollup": 1}) == [],
      "a fast read from the rollup satisfies the facet gate")
fast_but_exact = compare(gate, {"facet_p95_ms": 12.0, "facet_from_rollup": 0})
check(fast_but_exact and any("from_rollup" in breach for breach in fast_but_exact),
      "a fast read that did not use the rollup still breaches -- the path is the subject",
      fast_but_exact)
check(compare(gate, {"facet_p95_ms": 2713.288, "facet_from_rollup": 0}) != [],
      "and the exact fallback breaches on both counts")

check(compare({}, {"anything": 1}) == [], "no thresholds is no breaches")

provenance = build_evidence_provenance(
    "oms/test_threshold_comparison.py",
    entry_points=["POST /api/v1/example"],
    request_shapes=["bounded diagnostic request"],
)
check(provenance["migration_head"] == current_head(), "raw evidence records repository migration head")
check(provenance["observed_migration_head"] is None,
      "raw evidence does not invent a measured database head")
check(provenance["harness"] == "oms/test_threshold_comparison.py", "raw evidence records harness")
check(provenance["entry_points"] == ["POST /api/v1/example"], "raw evidence records entry points")
check(provenance["request_shapes"] == ["bounded diagnostic request"], "raw evidence records request shapes")
check(isinstance(provenance["captured_at"], int) and provenance["captured_at"] > 0,
      "raw evidence records capture time")

print(f"Threshold comparison verified: {passed} assertions passed.")

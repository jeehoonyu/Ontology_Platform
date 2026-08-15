"""The worst of at least six observations, enforced rather than remembered.

`latency_observations.py` exists because the contract's quiescence rule was
stated and unimplemented for the whole life of the tier. These are the
properties that keep it implemented: the worst reading wins, a later fast run
cannot lower it, readings from another schema are not pooled in, and a gate
short of its observations is not emitted at all.

That last one is not tidiness. A gate emitted below the required count fails its
own threshold, a recorded FAIL at the same head is sticky by design, and the
sixth run could then not promote it without an explicit supersede -- five honest
runs would lock the gate they were accumulating toward.
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from latency_observations import (  # noqa: E402
    LATENCY_GATES,
    REQUIRED_OBSERVATIONS,
    at_head,
    load,
    observed_worst,
    record,
    shortfall,
    summarize,
)
from tier_b_evidence import current_head  # noqa: E402

HEAD = current_head()
passed = 0


def check(condition, label, payload=None):
    global passed
    assert condition, f"{label}: {payload}"
    passed += 1


def observation(gate, value, *, head=HEAD, observed=HEAD, harness="oms/fake_harness.py"):
    return {"gate": gate, "at": 1_700_000_000, "harness": harness,
            "migration_head": head, "observed_migration_head": observed,
            "readings": {"ack_p95_ms": value}}


# --- what may be recorded ---------------------------------------------------

with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
    path = Path(tmpdir) / "observations.jsonl"

    try:
        record("not_a_gate", {"ack_p95_ms": 1.0}, "oms/fake_harness.py", observations_file=path)
        raise AssertionError("an unknown gate was recorded")
    except ValueError:
        passed += 1

    try:
        record("collaboration", {"ack_p95_ms": "fast"}, "oms/fake_harness.py",
               observations_file=path)
        raise AssertionError("a reading with no numbers was recorded")
    except ValueError:
        passed += 1

    # A run that names the database it measured must have named this head. The
    # alternative is a fast reading of an old schema qualifying a new one.
    try:
        record("collaboration", {"ack_p95_ms": 1.0}, "oms/fake_harness.py",
               observed_head="0001_something_older", observations_file=path)
        raise AssertionError("an observation of another schema was recorded")
    except ValueError:
        passed += 1

    check(load(path) == [], "nothing rejected was written", load(path))

# --- which observations count -----------------------------------------------

rows = [
    observation("collaboration", 100.0),
    observation("collaboration", 200.0),
    observation("identity", 999.0),                       # another gate
    observation("collaboration", 300.0, head="0001_old"), # another repository head
    observation("collaboration", 400.0, observed="0001_old"),  # another database
    observation("collaboration", 500.0, observed=None),   # could not name one; kept
]
current = at_head(rows, "collaboration", HEAD)
check(len(current) == 3, "only this gate at this head, database included", len(current))
check(sorted(row["readings"]["ack_p95_ms"] for row in current) == [100.0, 200.0, 500.0],
      "the excluded rows are the ones from elsewhere", current)

# --- what the summary says --------------------------------------------------

summary = summarize(current)
check(summary["observations"] == 3, "counts the observations", summary)
check(summary["worst"]["ack_p95_ms"] == 500.0, "the worst reading wins", summary)
check(summary["observation_spread"]["ack_p95_ms"] == 400.0, "spread is max minus min", summary)
check(summary["observation_distributions"]["ack_p95_ms"] == [100.0, 200.0, 500.0],
      "the whole distribution is published, not just the worst", summary)

# The mean is what the contract rules out, and this is why: it passes.
mean = sum(summary["observation_distributions"]["ack_p95_ms"]) / 3
check(mean < 300.0 < summary["worst"]["ack_p95_ms"],
      "the mean would have flattered a reading the worst case fails", (mean, summary["worst"]))

check(summarize([])["observations"] == 0, "an empty set observes nothing", summarize([]))
check(summarize([])["worst"] == {}, "an empty set has no worst reading", summarize([]))

# --- accumulating toward the threshold --------------------------------------

with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
    path = Path(tmpdir) / "observations.jsonl"
    counts, worsts = [], []
    # Descending, so every run after the first is faster than the record. A
    # harness reporting its own run would report 60 ms at the end; the gate must
    # still be judged on the 160 ms someone actually observed.
    for value in (160.0, 140.0, 120.0, 100.0, 80.0, 60.0):
        measurements, count = observed_worst(
            "collaboration", {"ack_p95_ms": value}, "oms/fake_harness.py",
            observed_head=HEAD, observations_file=path)
        counts.append(count)
        worsts.append(measurements["ack_p95_ms"])

    check(counts == [1, 2, 3, 4, 5, 6], "each run adds exactly one observation", counts)
    check(worsts == [160.0] * 6, "a later fast run never lowers the recorded worst", worsts)
    check(count >= REQUIRED_OBSERVATIONS, "six runs reach the required count", count)
    check(measurements["observations"] == 6, "the count travels with the measurements", measurements)
    check(measurements["observation_spread"]["ack_p95_ms"] == 100.0,
          "the spread reports how unlike the observations were", measurements)
    check(len(load(path)) == 6, "every observation is kept, not just the worst", len(load(path)))

    # Below the threshold the operator is told what is owed, not handed a verdict.
    message = shortfall(2)
    check(f"of {REQUIRED_OBSERVATIONS}" in message and "4 more" in message,
          "the shortfall names how many runs remain", message)

# --- the ledger is not written by running this ------------------------------

check(all(gate.islower() for gate in LATENCY_GATES), "gate ids are canonical", LATENCY_GATES)

# --- the audit must fail on an unwired gate ---------------------------------
#
# An audit only ever run against a passing tree is an assertion about that tree.
# These build the two ways a latency gate goes unwired and check the audit says
# so, naming the gate.

from audit_latency_observations import survey  # noqa: E402

WIRED = '''
from latency_observations import REQUIRED_OBSERVATIONS, observed_worst
from tier_b_evidence import write_evidence
_m, _n = observed_worst("collaboration", {"ack_p95_ms": 1.0}, harness="x")
write_evidence("collaboration",
               thresholds={"ack_p95_ms_max": 250.0, "observations_min": REQUIRED_OBSERVATIONS},
               measurements={}, harness="x")
'''

with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
    fake = Path(tmpdir)
    (fake / "harness.py").write_text(WIRED, encoding="utf-8")
    seen, failures = survey(fake)
    check(seen["collaboration"]["declares_observations"], "a wired gate is seen as wired", seen)
    check([f for f in failures if "collaboration" in f] == [],
          "a wired gate raises no finding", failures)
    check(len(failures) == len(LATENCY_GATES) - 1,
          "every gate with no harness in this tree is reported", failures)

    # Declared but never recorded: the threshold is present and the number is
    # still one run's, which is the failure that looks fixed from the file.
    (fake / "harness.py").write_text(WIRED.replace("_m, _n = observed_worst", "# removed"),
                                     encoding="utf-8")
    _seen, failures = survey(fake)
    check(any("collaboration" in f and "observed_worst" in f for f in failures),
          "declaring the threshold without recording is caught", failures)

    # Recorded but never gated: observations accumulate and nothing checks them.
    (fake / "harness.py").write_text(WIRED.replace('"observations_min": REQUIRED_OBSERVATIONS', ""),
                                     encoding="utf-8")
    _seen, failures = survey(fake)
    check(any("collaboration" in f and "observations_min" in f for f in failures),
          "recording without gating is caught", failures)
docs_ledger = Path(__file__).resolve().parent.parent / "docs" / "latency-observations.jsonl"
before = docs_ledger.read_bytes() if docs_ledger.exists() else None
summarize(at_head(load(docs_ledger), "collaboration", HEAD))
after = docs_ledger.read_bytes() if docs_ledger.exists() else None
check(before == after, "reading the ledger does not write to it", None)

print(f"Latency observations verified: {passed} assertions passed.")

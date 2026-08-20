"""A route may not issue more requests on open than it does today.

Also this check's home: `audit_route_cost` declares `every suite run`.

Which of the three measured numbers may be gated was decided by measuring twice,
not by judgement:

    requests     identical 16/16 across two runs      gated, no tolerance
    bytes        identical 16/16 across two runs      gated, 15% tolerance
    settled_ms   identical  0/16, worst drift 2.6%    recorded, never gated

Wall-clock is wall-clock. A gate on it fails for reasons a reader cannot act on,
which is how a gate becomes something people re-run until it passes -- the same
argument that kept statement counts out of the suite-cost ratchet.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from audit_route_cost import BASELINE, BYTES_TOLERANCE, compare, load  # noqa: E402

checks = 0


def check(condition, message):
    global checks
    assert condition, message
    checks += 1


MEASURED = {"map": {"requests": 25, "bytes": 900_000, "settled_ms": 640},
            "ops": {"requests": 18, "bytes": 450_000, "settled_ms": 630}}
BASE = {"bytes_tolerance": 0.15,
        "routes": {"map": {"requests": 25, "bytes": 900_000},
                   "ops": {"requests": 18, "bytes": 450_000}}}

ok, failures, _notes = compare(MEASURED, BASE)
check(ok and not failures, failures)

# --- gate: one more request on open ------------------------------------------
creep = compare({**MEASURED, "ops": {"requests": 19, "bytes": 450_000, "settled_ms": 1}}, BASE)
check(not creep[0], "a nineteenth request must fail against a ceiling of eighteen")
check(any("ops" in f and "one more call" in f.lower() for f in creep[1]), creep[1])

# --- note: fewer requests ------------------------------------------------------
better = compare({**MEASURED, "ops": {"requests": 12, "bytes": 450_000, "settled_ms": 1}}, BASE)
check(better[0], better[1])
check(any("18 -> 12 requests" in n for n in better[2]), better[2])

# --- gate: bytes beyond the tolerance ------------------------------------------
heavy = compare({**MEASURED, "ops": {"requests": 18, "bytes": 700_000, "settled_ms": 1}}, BASE)
check(not heavy[0], "a 55% jump in transferred bytes must fail")
inside = compare({**MEASURED, "ops": {"requests": 18, "bytes": 500_000, "settled_ms": 1}}, BASE)
check(inside[0], "an 11% move is inside the tolerance and is ordinary")

# --- timing is never gated -----------------------------------------------------
slow = compare({**MEASURED, "ops": {"requests": 18, "bytes": 450_000, "settled_ms": 99_999}},
               BASE)
check(slow[0], "wall-clock must not fail a gate; it is recorded, not judged")

# --- gate: a route with no ceiling ---------------------------------------------
fresh = compare({**MEASURED, "brand-new": {"requests": 9, "bytes": 1, "settled_ms": 1}}, BASE)
check(not fresh[0], "a route with no recorded ceiling must fail")
check(any("brand-new" in f and "no\n" not in f for f in fresh[1]), fresh[1])

# --- note: a route not measured this run ---------------------------------------
partial = compare({"map": MEASURED["map"]}, BASE)
check(partial[0], "a route missing from one run is a note, not a failure")
check(any("ops" in n and "not measured" in n for n in partial[2]), partial[2])

# --- the recorded baseline ------------------------------------------------------
check(BASELINE.exists(), f"no baseline at {BASELINE}")
recorded = json.loads(BASELINE.read_text(encoding="utf-8"))
check(recorded["provenance"]["stale_after"] == "recomputed each run", recorded)
check(recorded["bytes_tolerance"] == BYTES_TOLERANCE, recorded["bytes_tolerance"])
check(len(recorded["routes"]) >= 12, len(recorded["routes"]))
check(all("requests" in e and "bytes" in e for e in recorded["routes"].values()), recorded)
# settled_ms is deliberately absent from the baseline: recording a number the
# gate refuses to use would invite someone to start using it.
check(all("settled_ms" not in e for e in recorded["routes"].values()),
      "wall-clock must not be written into the baseline")

# The measurement itself is gitignored -- it is produced by a browser run, like
# the census, and a committed copy would go stale silently.
live = load()
if live:
    check(all("settled_ms" in e for e in live.values()),
          "the measurement records timing even though the gate ignores it")

print(f"Route cost gate verified: {checks} assertions passed "
      f"({len(recorded['routes'])} routes baselined, "
      f"{sum(e['requests'] for e in recorded['routes'].values())} requests on open).")

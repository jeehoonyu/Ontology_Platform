"""The identity gate must be derived from a run, not asserted by one.

Until 2026-08-08 this gate's evidence was written by hand. The emitter under
test reads what the oidc-scale browser profile measured and lets the thresholds
decide. These cases are the ways that can go wrong quietly.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from identity_scale_evidence import (  # noqa: E402
    LOGIN_P95_LIMIT_MS, REQUIRED_IDENTITIES, REQUIRED_REPLICAS,
    _replica_count, measurements_from_run,
)
from tier_b_evidence import compare  # noqa: E402

passed = 0


def check(condition, label, payload=None):
    global passed
    assert condition, f"{label}: {payload}"
    passed += 1


THRESHOLDS = {
    "identities_min": REQUIRED_IDENTITIES,
    "unique_principals_min": REQUIRED_IDENTITIES,
    "mutation_denials_min": REQUIRED_IDENTITIES,
    "replicas_verified_min": REQUIRED_REPLICAS,
    "login_p95_ms_max": LOGIN_P95_LIMIT_MS,
}


def run(**overrides):
    base = {
        "status": "PASS",
        "identities": 200,
        "unique_principals": 200,
        "mutation_denials": 200,
        "replicas_verified": ["http://primary:8000", "http://peer:8001"],
        "login_p95_ms": 4244.765,
        "login_p50_ms": 3122.733,
        "concurrency": 20,
        "elapsed_seconds": 38.914,
    }
    base.update(overrides)
    return base


def verdict(**overrides):
    return compare(THRESHOLDS, measurements_from_run(run(**overrides)))


check(not verdict(), "a complete passing run satisfies the gate", verdict())

# The spec writes a list of replica URLs; the gate counts them. A run that
# verified one replica twice has verified one replica.
check(_replica_count(["a", "b"]) == 2, "two distinct replicas count as two")
check(_replica_count(["a", "a"]) == 1, "the same replica twice counts as one")
check(verdict(replicas_verified=["only-one"]), "a single replica breaches")

# The run declares itself PASS before any threshold is consulted. That field
# must not survive into the verdict.
breaches = verdict(login_p95_ms=LOGIN_P95_LIMIT_MS + 1, status="PASS")
check(breaches, "a self-declared PASS does not rescue a breaching latency", breaches)
check("status" not in measurements_from_run(run()),
      "the run's own status is not carried into the measurements")

check(verdict(identities=199), "one identity short breaches")
check(verdict(unique_principals=199),
      "two hundred logins that resolved to fewer principals breaches")
check(verdict(mutation_denials=0),
      "authenticated viewers that were never denied a mutation breaches")

# A partial run must refuse to produce evidence rather than default a gap. A
# missing latency defaulted to zero would pass silently.
for missing in ("identities", "unique_principals", "mutation_denials",
                "replicas_verified", "login_p95_ms"):
    incomplete = run()
    incomplete[missing] = None
    try:
        measurements_from_run(incomplete)
        raise AssertionError(f"a run missing {missing} produced measurements")
    except SystemExit:
        passed += 1

try:
    _replica_count(True)
    raise AssertionError("a boolean was accepted as a replica count")
except ValueError:
    passed += 1

print(f"Identity gate emission: {passed} assertions passed.")

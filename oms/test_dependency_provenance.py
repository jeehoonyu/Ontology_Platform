"""Evidence must name the third-party code that produced it.

Conditions D1 and D2 of GOAL_REPRODUCIBILITY_2026-08-13. Until 2026-08-13 a gate
recorded its git commit and its migration head and nothing about the libraries
that compiled its queries, ran its pipeline and owned the memory it measured, so
a number that moved after a SQLAlchemy upgrade was indistinguishable from one
that moved because of a code change.

The cases here are the ways that record could be present and still worthless: a
closure drawn too narrow to contain what matters, a digest that does not move
when a version does, and bookkeeping that takes a gate down with it when package
metadata cannot be read.
"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import dependency_provenance as dp  # noqa: E402
from tier_b_evidence import build_evidence_provenance  # noqa: E402

passed = 0


def check(condition, label, payload=None):
    global passed
    assert condition, f"{label}: {payload}"
    passed += 1


# --- D1: nothing is left to float ------------------------------------------

loose = dp.unpinned()
check(loose == [], "every declared dependency is pinned exactly", loose)
check(len(dp.declared()) >= 16, "and the declarations were not thinned to achieve it",
      len(dp.declared()))

with tempfile.TemporaryDirectory() as directory:
    floors = Path(directory) / "requirements.txt"
    floors.write_text("fastapi>=0.110.0\nsqlalchemy==2.0.50\n# a comment\n", encoding="utf-8")
    check(dp.unpinned(floors) == ["fastapi>=0.110.0"],
          "a floor is reported and an exact pin is not", dp.unpinned(floors))
    check(dp.declared(floors) == ["fastapi", "sqlalchemy"],
          "declarations parse names without their constraints", dp.declared(floors))

# --- D2: the closure is the right size ---------------------------------------
# Too narrow misses starlette and greenlet, which move benchmarks. Too wide is
# the whole shared interpreter -- 101 distributions here, including packages
# belonging to unrelated projects -- and would report drift as noise.

versions = dp.resolved()
check(len(versions) > len(dp.declared()),
      "the closure is transitive, not just the declared roots", len(versions))
for transitive in ("starlette", "greenlet", "anyio"):
    check(transitive in versions,
          f"{transitive} is inside the closure -- it can move a measurement",
          sorted(versions)[:12])

import importlib.metadata as metadata  # noqa: E402

installed = len(list(metadata.distributions()))
check(len(versions) < installed,
      "and the closure is narrower than the whole interpreter",
      {"closure": len(versions), "installed": installed})

# --- the digest has to actually move -----------------------------------------

baseline = dp.digest(versions)
check(baseline == dp.digest(versions), "the digest is stable for one set")
bumped = dict(versions)
name = sorted(bumped)[0]
bumped[name] = bumped[name] + ".999"
check(dp.digest(bumped) != baseline,
      "and changes when any single version changes", name)
check(dp.digest({}) != baseline, "an empty set does not collide with a real one")

# --- D2 in the envelope ------------------------------------------------------

block = build_evidence_provenance("oms/test_dependency_provenance.py")
check("dependencies" in block, "provenance carries a dependencies block", sorted(block))
recorded = block["dependencies"]
check(recorded.get("python", "").startswith("3."), "recording the Python version", recorded.get("python"))
check(recorded.get("digest") == baseline, "and the digest of what is installed now")
check(recorded.get("closure") == len(versions), "and the closure size")
check(isinstance(recorded.get("versions"), dict) and recorded["versions"],
      "and the versions themselves, so a reader can rebuild the set")

# --- bookkeeping must never take a gate down ---------------------------------
# A gate that cannot write its result is worse than one whose provenance is
# incomplete. The incompleteness is recorded rather than silently omitted.

import tier_b_evidence  # noqa: E402

original = dp.provenance
try:
    def explode():
        raise RuntimeError("package metadata unreadable")

    dp.provenance = explode
    sys.modules["dependency_provenance"].provenance = explode
    degraded = tier_b_evidence._dependency_provenance()
    check("unavailable" in degraded,
          "an unreadable environment is recorded, not swallowed", degraded)
    check("RuntimeError" in degraded["unavailable"],
          "and names what went wrong", degraded)
finally:
    dp.provenance = original
    sys.modules["dependency_provenance"].provenance = original

check("unavailable" not in tier_b_evidence._dependency_provenance(),
      "and the real path is restored afterwards")

print(f"Dependency provenance verified: {passed} assertions passed.")

"""D3 and D5 of GOAL_REPRODUCIBILITY_2026-08-13.

D3 is the audit that says whether evidence still names the environment that made
it. D5 is the path a stranger follows to check a measurement, and the test for it
is structural rather than behavioural: running the real script takes ten minutes
and generates ten million rows, so what is asserted here is that the script still
contains the steps that make it trustworthy, and that the document describing it
has not drifted away from it.

The step that matters most is the one that exists because the mistake was made.
On 2026-08-13 a reproduction was reported as succeeding with measurements
matching to the last decimal; the run had crashed at import, the evidence file
was never rewritten, and the comparison was the committed file against itself. A
reproduction that silently no-ops agrees perfectly. If that guard is ever removed
from the script, this test fails.
"""
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import audit_dependency_provenance as audit  # noqa: E402
from audit_dependency_provenance import (  # noqa: E402
    CURRENT, DRIFTED, UNRECORDED, UNREADABLE, classify,
)
from dependency_provenance import digest, resolved  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "reproduce-measurement.sh"
GUIDE = REPO_ROOT / "docs" / "REPRODUCING_A_MEASUREMENT.md"

passed = 0


def check(condition, label, payload=None):
    global passed
    assert condition, f"{label}: {payload}"
    passed += 1


# --- D3: the four states -----------------------------------------------------

installed = resolved()

with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as directory:
    docs = Path(directory)

    def write(name, block):
        payload = {"provenance": {}} if block is None else {"provenance": {"dependencies": block}}
        (docs / name).write_text(json.dumps(payload), encoding="utf-8")

    write("current-evidence.json",
          {"digest": digest(installed), "closure": len(installed), "versions": installed})
    stale = dict(installed)
    stale["starlette"] = "0.0.1-not-installed"
    write("drifted-evidence.json",
          {"digest": digest(stale), "closure": len(stale), "versions": stale})
    write("unrecorded-evidence.json", None)
    (docs / "torn-evidence.json").write_text("{not json", encoding="utf-8")

    report = classify(docs)
    check(report["current-evidence.json"]["state"] == CURRENT,
          "evidence recording the installed set reads CURRENT")
    check(report["drifted-evidence.json"]["state"] == DRIFTED,
          "evidence recording a different set reads DRIFTED")
    check(report["unrecorded-evidence.json"]["state"] == UNRECORDED,
          "evidence recording no set reads UNRECORDED")
    check(report["torn-evidence.json"]["state"] == UNREADABLE,
          "an unparseable file reads UNREADABLE rather than being skipped")

    # Drift has to name what moved. "Something changed" sends a reader looking
    # through 45 packages by hand.
    moved = report["drifted-evidence.json"]["moved"]
    check(any(name == "starlette" for name, _, _ in moved),
          "drift names the package that moved", moved)
    check(any(was == "0.0.1-not-installed" for _, was, _ in moved),
          "and what it moved from", moved)

    # A digest that matches must not be second-guessed by a version-by-version
    # comparison, and one that differs must not be waved through.
    check(not report["current-evidence.json"].get("moved"),
          "a matching digest reports no movement")

# --- D3: the live ratchet ----------------------------------------------------

live = classify()
unrecorded = sum(1 for row in live.values() if row["state"] == UNRECORDED)
baseline = {}
if audit.BASELINE.exists():
    baseline = json.loads(audit.BASELINE.read_text(encoding="utf-8"))
ceiling = baseline.get("unrecorded_ceiling")
check(ceiling is not None, "a dependency-provenance baseline is recorded", baseline)
check(unrecorded <= ceiling,
      "no new evidence has been added without naming its dependency set",
      {"unrecorded": unrecorded, "ceiling": ceiling})

# --- D5: the path stays trustworthy ------------------------------------------

check(SCRIPT.exists(), "the reproduction script exists", SCRIPT)
script = SCRIPT.read_text(encoding="utf-8")

check("requirements.lock" in script,
      "it installs from the lock, not the declarations -- pinning the 17 still let "
      "11 of 42 transitive packages move")
# Checked on the install lines rather than the whole file: the header explains
# why requirements.txt is the wrong input, and that explanation should stay.
installs = [line for line in script.splitlines() if "pip install" in line and "-r" in line]
check(installs, "it installs requirements from a file at all", installs)
check(all("requirements.lock" in line for line in installs),
      "and every such install reads the lock, not the declarations", installs)

# The guard that exists because the mistake was made.
check("git diff --quiet" in script,
      "it checks the evidence file actually changed before comparing")
check("nothing to compare" in script or "did not rewrite" in script,
      "and says why a silent no-op is not a reproduction", script[-900:])

check("git clone" in script, "it works from a fresh clone")
check("venv" in script, "in an isolated interpreter")
check("VERDICTS DISAGREE" in script,
      "a differing verdict fails, which a differing latency does not")

check(GUIDE.exists(), "the guide exists", GUIDE)
guide = GUIDE.read_text(encoding="utf-8")
check("reproduce-measurement.sh" in guide,
      "the guide names the executable path rather than describing steps in prose")
check("requirements.lock" in guide, "and tells the reader to install from the lock")
check("perfect agreement" in guide or "agrees perfectly" in guide,
      "and warns that a no-op reproduction agrees perfectly")
check("pipeline_scale" in guide,
      "and says which gate it reproduces, since the others need infrastructure")

print(f"Reproducibility conditions verified: {passed} assertions passed.")

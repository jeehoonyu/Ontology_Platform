"""Validation reads the snapshot's shape, so it must not pay for its contents.

`validate_project` built the full portable project snapshot -- 133 collections,
every row of every table -- and passed it to `_snapshot_coverage`, which reads
exactly two things from it: which collection names are present, and how long
each one is. 110 integers, and nothing else.

Finalizing that snapshot deep-copies the whole project, redacts secrets it will
never show anyone, and takes a canonical-JSON sha256 of the result. Measured on
a small project: 5.6 ms of the snapshot's 26.6 ms, and both halves grow with the
project while the answer stays 110 integers.

Two properties, and the first is what makes the second safe: skipping the
finalize step must not change the coverage answer, and the export must still be
finalized -- an exported artifact without its checksum is the defect this would
otherwise introduce while fixing another.
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
os.environ["DATABASE_URL"] = f"sqlite:///{Path(tmpdir.name, 'validation-cost.db').as_posix()}"
os.environ["AUTH_MODE"] = "local"
os.environ["APP_ENV"] = "test"
sys.path.insert(0, str(Path(__file__).resolve().parent))

from fastapi.testclient import TestClient  # noqa: E402

from app import system_hardening as hardening  # noqa: E402
from app.database import SessionLocal  # noqa: E402
from app.main import app  # noqa: E402

passed = 0


def check(condition, label, payload=None):
    global passed
    assert condition, f"{label}: {payload}"
    passed += 1


client = TestClient(app)
client.get("/health/ready")
check(client.post("/project/demo/bootstrap", json={}).status_code == 200,
      "the demo scenario bootstraps, so this runs against real rows", None)

# --- the two snapshots must agree about coverage ----------------------------

with SessionLocal() as db:
    finalized = hardening._snapshot(db, "default", "local")
    lean = hardening._snapshot(db, "default", "local", finalize=False)
    from_finalized = hardening._snapshot_coverage(finalized)
    from_lean = hardening._snapshot_coverage(lean)

check(from_finalized == from_lean,
      "coverage is identical whether or not the snapshot was finalized",
      (from_finalized["status"], from_lean["status"]))
check(from_lean["counts"], "coverage actually counted something", len(from_lean["counts"]))
check(any(value > 0 for value in from_lean["counts"].values()),
      "and the counts are of real rows, not an empty project", from_lean["counts"])
check(from_lean["missing"] == [], "no expected collection is missing", from_lean["missing"])

# --- finalize is what an exported artifact needs, and only that --------------

check("integrity" in finalized, "a finalized snapshot carries its integrity block", None)
check(len((finalized.get("integrity") or {}).get("checksum", "")) == 64,
      "with a sha256 checksum", (finalized.get("integrity") or {}).get("checksum"))
check("integrity" not in lean,
      "an unfinalized snapshot does not pretend to have one", list(lean)[:3])
check("rebind_required" not in lean,
      "nor the rebind list, which only a restore reads", None)

# The collections themselves must be the same either way -- finalize redacts
# secrets inside rows, and coverage counts rows, so a difference here would mean
# the cheap path was counting something else.
lists_finalized = {key: len(value) for key, value in finalized.items() if isinstance(value, list)}
lists_lean = {key: len(value) for key, value in lean.items() if isinstance(value, list)}
check(lists_lean == {k: v for k, v in lists_finalized.items() if k != "rebind_required"},
      "every collection has the same length in both", None)

# --- the routes ---------------------------------------------------------------

export = client.get("/project/export")
check(export.status_code == 200, "export still answers", export.status_code)
body = export.json()
check(len((body.get("integrity") or {}).get("checksum", "")) == 64,
      "export is still finalized and checksummed", None)

validation = client.get("/project/validate")
check(validation.status_code == 200, "validate still answers", validation.status_code)
coverage = (validation.json().get("sections") or {}).get("snapshot_coverage") or {}
check(coverage.get("status") in {"PASS", "WARN"}, "with a snapshot coverage section", coverage)
# Key sets, not values: the export above wrote an audit row, so `audit_logs` has
# legitimately moved since `from_lean` was taken. Value equality between the two
# paths is proven above, where both are computed from the same session at the
# same instant -- asserting it again across a write would be pinning the clock.
check(set(coverage.get("counts") or {}) == set(from_lean["counts"]),
      "the route reports coverage over the same collections the cheap path counts",
      set(from_lean["counts"]) ^ set(coverage.get("counts") or {}))

readiness = client.get("/project/readiness")
check(readiness.status_code == 200, "readiness still answers", readiness.status_code)

# The cheap path must stay cheap: a route that finalizes again would undo this
# silently, and the only visible symptom would be a slower request.
calls = []
original = hardening._finalize_snapshot
try:
    def counted(snapshot):
        calls.append(1)
        return original(snapshot)

    hardening._finalize_snapshot = counted
    calls.clear()
    client.get("/project/validate")
    check(calls == [], "validating a project finalizes no snapshot", len(calls))
    calls.clear()
    client.get("/project/readiness")
    check(calls == [], "nor does the readiness check", len(calls))
    calls.clear()
    client.get("/project/export")
    check(len(calls) == 1, "exporting one finalizes exactly one", len(calls))
finally:
    hardening._finalize_snapshot = original

print(f"Project validation cost verified: {passed} assertions passed "
      f"({len(from_lean['counts'])} collections counted without finalizing).")

"""Operations and the Command Center count the same incidents as open.

Operations counted an incident open when its status was OPEN, TRIAGE or INVESTIGATING; the
Command Center, when it was anything but CLOSED. So a RESOLVED incident was open on the Command
Center and not in Operations, and a status neither list named -- status is free text, and a
runbook step can set any word -- was open only on the Command Center. `ops_control` now holds
one definition, `CLOSED_INCIDENT_STATUSES`: an incident is open until it is resolved or closed.
Both screens count by it, and the Resolve button reads its mirror in `opsApi.ts`.

This holds the two screens to one count below the Command Center's window of 20 (where it counts
the rows it loaded) and past it (where it counts in SQL), and holds the frontend's copy equal.

Run:
  python oms/test_incident_open_definition.py
"""
import os
import re
import tempfile
from pathlib import Path

tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tmpdir.name, 'incident_open.db')}"

from fastapi.testclient import TestClient  # noqa: E402
from app import ops_control  # noqa: E402
from app.main import app  # noqa: E402

client = TestClient(app)
passed = 0


def ok(response, label, expect=200):
    global passed
    success = response.status_code == expect or (expect == 200 and 200 <= response.status_code < 300)
    assert success, f"{label}: expected {expect}, got {response.status_code} -> {response.text[:600]}"
    passed += 1
    return response.json() if response.content else {}


def check(condition, label, detail=None):
    global passed
    assert condition, f"{label}: {detail}"
    passed += 1


# --- the frontend's copy is the server's ---------------------------------------------------
source = (Path(__file__).resolve().parent.parent / "frontend" / "src" / "api" / "opsApi.ts").read_text(encoding="utf-8")
literals = re.findall(r"export const CLOSED_INCIDENT_STATUSES[^=]*=\s*\[([^\]]*)\]", source)
check(len(literals) == 1, "expected one `export const CLOSED_INCIDENT_STATUSES = [...]` in opsApi.ts; "
      "if it was reformatted, update this pattern", len(literals))
frontend = tuple(re.findall(r"\"([^\"]*)\"", literals[0]))
check(frontend == ops_control.CLOSED_INCIDENT_STATUSES, "the Resolve button and the server disagree on which incidents are closed",
      (frontend, ops_control.CLOSED_INCIDENT_STATUSES))
check(set(ops_control.CLOSED_INCIDENT_STATUSES) == {"RESOLVED", "CLOSED"}, "an incident no longer ends by being resolved or closed",
      ops_control.CLOSED_INCIDENT_STATUSES)


def incident(name, status):
    return ok(client.post("/ops/incidents", json={"display_name": name, "severity": "medium", "status": status}), f"incident {name}")


def compare(label):
    """The open count from each screen, beside the count from every incident there is."""
    every = ok(client.get("/ops/incidents"), "every incident")
    truth = sum(1 for row in every if row["status"] not in ("RESOLVED", "CLOSED"))
    operations = ok(client.get("/ops/summary"), "the operations summary")
    command_center = ok(client.get("/ui-state/command-center"), "the Command Center")["summary"]["kpis"]
    check(operations["open_incidents"] == truth, f"{label}: Operations counts {operations['open_incidents']} open incidents, not {truth}",
          sorted(row["status"] for row in every))
    check(command_center["open_incidents"] == truth,
          f"{label}: the Command Center counts {command_center['open_incidents']} open incidents, not {truth}",
          sorted(row["status"] for row in every))
    return every, operations


ok(client.post("/scenarios/asset-reliability/bootstrap", json={"actor": "test"}), "bootstrap")

# --- 1. below the window: every status the two screens used to disagree on ------------------
for status in ("OPEN", "TRIAGE", "INVESTIGATING", "MITIGATED", "RESOLVED", "CLOSED"):
    incident(f"Status {status}", status)
every, operations = compare("below the window")
check(len(every) < 20, "the first block stays below the Command Center's window of 20", len(every))
latest = {row["display_name"] for row in operations["latest_incidents"]}
check("Status MITIGATED" in latest, "Operations leaves out an incident whose status it does not name", latest)
check(not {"Status RESOLVED", "Status CLOSED"} & latest, "Operations lists a resolved or closed incident as open", latest)

# --- 2. past it: the Command Center counts in SQL once it loads 20 ---------------------------
for index in range(18):
    incident(f"Past the window {index}", ("RESOLVED", "OPEN", "MONITORING")[index % 3])
every, _ = compare("past the window")
check(len(every) > 20, "the second block reaches past the Command Center's window of 20", len(every))

print(f"Open incidents counted one way on both screens: {passed} assertions passed.")
from app.database import engine as _engine  # noqa: E402
_engine.dispose()
tmpdir.cleanup()

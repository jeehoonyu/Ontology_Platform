"""Operations' Latest incidents are the ten most recently updated open incidents.

`/ops/summary` read its open incidents with no order and returned the first ten as
`latest_incidents`, so the panel listed whichever ten the database returned first -- in SQLite,
the ten written earliest. It now orders by `updated_at`, newest first, then by `created_at`,
newest first, then by id, so ties in the one-second clock break the same way every time. The
count stays every open incident; the panel says so when it lists fewer.

Run:
  python oms/test_ops_latest_incidents.py
"""
import os
import tempfile

tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tmpdir.name, 'ops_latest_incidents.db')}"

from fastapi.testclient import TestClient  # noqa: E402
from app import ops_control  # noqa: E402
from app.database import SessionLocal  # noqa: E402
from app.main import app  # noqa: E402

client = TestClient(app)
passed = 0


def check(condition, label, detail=None):
    global passed
    assert condition, f"{label}: {detail}"
    passed += 1


# Written in reverse id order and updated out of any order, so neither the order a read with no
# ORDER BY returns nor the id order is the order of change. Two open incidents share an
# `updated_at` and differ in `created_at`, and two share both. Two resolved incidents are the
# most recently updated of all, and are not open.
UPDATED = [305, 110, 990, 440, 720, 720, 150, 860, 860, 530, 610, 280, 999, 998]
CREATED = [100, 101, 102, 103, 104, 105, 106, 107, 107, 109, 110, 111, 112, 113]
with SessionLocal() as db:
    ops_control._ensure_tables(db)
    for index, (updated, created) in reversed(list(enumerate(zip(UPDATED, CREATED)))):
        db.add(ops_control.Incident(
            id=f"latest-{index:02d}", project_id="default", display_name=f"Latest {index:02d}", severity="medium",
            status="RESOLVED" if index >= 12 else "OPEN", linked_objects=[], alert_ids=[], approval_ids=[],
            runbook_execution_ids=[], timeline=[], created_at=created, updated_at=updated))
    db.commit()

response = client.get("/ops/summary")
check(response.status_code == 200, "the operations summary", response.text[:400])
summary = response.json()
open_rows = [(UPDATED[i], CREATED[i], f"latest-{i:02d}") for i in range(12)]
expected = [row_id for _, _, row_id in sorted(open_rows, key=lambda row: (-row[0], -row[1], row[2]))][:10]
latest = [row["id"] for row in summary["latest_incidents"]]
check(summary["open_incidents"] == 12, "the count is every open incident", summary["open_incidents"])
check(len(latest) == 10, "Latest incidents lists ten", latest)
check(latest[0] == "latest-02", "Latest incidents does not start with the most recently updated", latest)
check(latest == expected, "Latest incidents is not the ten most recently updated, newest first", (latest, expected))
check(latest.index("latest-05") < latest.index("latest-04"), "a tie in `updated_at` does not put the newer incident first", latest)
check(latest.index("latest-07") < latest.index("latest-08"), "a tie in both times does not break by id", latest)
check(not {"latest-12", "latest-13"} & set(latest), "a resolved incident is listed as open", latest)

print(f"Latest incidents, newest change first: {passed} assertions passed.")
from app.database import engine as _engine  # noqa: E402
_engine.dispose()
tmpdir.cleanup()

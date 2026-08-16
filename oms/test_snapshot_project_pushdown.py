"""A project's snapshot must not read other projects' rows to build it.

`_scope_snapshot` dropped them afterwards, so the answer was always right and
the cost was not: on a fixture with 200 rows belonging to a second project the
builder read 322 rows to keep 124, and `object_types` alone read 206 to keep 6.
The ratio is not fixed — it grows with every project a deployment gains, because
the builder read all of them to serve one.

The predicate pushed into SQL is not a new rule. It is the same rule
`_scope_snapshot` already applies, asked where it can be answered cheaply, which
is why the property worth pinning is *equivalence* rather than speed.

Three things have to hold, and the third is the one a careless change breaks:

  * no foreign row is loaded at all
  * every row that belongs in the snapshot is still there, including children
    re-added by parent identity, which have no `project_id` of their own
  * an **unscoped** snapshot still reads everything, because `_snapshot(db)` with
    no project is how the whole-instance export works
"""
from __future__ import annotations

import os
import sys
import tempfile
import time
from pathlib import Path

tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
os.environ["DATABASE_URL"] = f"sqlite:///{Path(tmpdir.name, 'pushdown.db').as_posix()}"
os.environ["AUTH_MODE"] = "local"
os.environ["APP_ENV"] = "test"
sys.path.insert(0, str(Path(__file__).resolve().parent))

from fastapi.testclient import TestClient  # noqa: E402

from app import models, system_hardening as hardening  # noqa: E402
from app.database import SessionLocal  # noqa: E402
from app.main import app  # noqa: E402

MINE, THEIRS = "default", "other_project"
passed = 0


def check(condition, label, payload=None):
    global passed
    assert condition, f"{label}: {payload}"
    passed += 1


def build(project_id):
    """Snapshot, and also capture what the builder loaded before scoping."""
    loaded = {}
    original = hardening._scope_snapshot
    try:
        def spy(db, snapshot, scoped_project, organization_id):
            loaded.update({key: list(value) for key, value in snapshot.items()
                           if isinstance(value, list)})
            return original(db, snapshot, scoped_project, organization_id)
        hardening._scope_snapshot = spy
        with SessionLocal() as db:
            scoped = hardening._snapshot(db, project_id, "local", finalize=False)
    finally:
        hardening._scope_snapshot = original
    return loaded, scoped


client = TestClient(app)
client.get("/health/ready")
check(client.post("/project/demo/bootstrap", json={}).status_code == 200,
      "the demo scenario bootstraps", None)

now = int(time.time())
with SessionLocal() as db:
    for index in range(25):
        db.add(models.ObjectType(id=f"theirs_{index}", project_id=THEIRS,
                                 display_name=f"Theirs {index}", properties={},
                                 created_at=now, updated_at=now))
    for index in range(3):
        db.add(models.ObjectType(id=f"mine_{index}", project_id=MINE,
                                 display_name=f"Mine {index}", properties={},
                                 created_at=now, updated_at=now))
    # A child with no project_id column of its own, on each side. It survives
    # only through its parent, which is the case a project filter cannot see.
    function_columns = {column.name for column in models.LogicFunction.__table__.columns}
    run_columns = {column.name for column in models.LogicRun.__table__.columns}
    for suffix, project in (("mine", MINE), ("theirs", THEIRS)):
        db.add(models.LogicFunction(**{key: value for key, value in {
            "id": f"fn_{suffix}", "project_id": project, "display_name": f"Fn {suffix}",
            "description": None, "expression": "1",
            "created_at": now, "updated_at": now}.items() if key in function_columns}))
        db.add(models.LogicRun(**{key: value for key, value in {
            "id": f"run_{suffix}", "logic_function_id": f"fn_{suffix}", "status": "OK",
            "inputs": {}, "outputs": {}, "proposed_actions": [], "trace": {},
            "created_at": now, "completed_at": now}.items() if key in run_columns}))
    db.commit()

# --- nothing foreign is read ------------------------------------------------

loaded, scoped = build(MINE)
foreign = [
    (key, row.get("id"))
    for key, rows in loaded.items()
    for row in rows
    if row.get("project_id") not in (None, MINE)
]
check(foreign == [], "the builder loads no row belonging to another project", foreign[:5])

loaded_types = {row["id"] for row in loaded.get("object_types") or []}
check(loaded_types and not any(name.startswith("theirs_") for name in loaded_types),
      "and object_types in particular", sorted(loaded_types)[:5])
check(len(loaded_types) < 25, "the 25 foreign types were never read", len(loaded_types))

# --- everything of mine is still there --------------------------------------

kept_types = {row["id"] for row in scoped.get("object_types") or []}
for index in range(3):
    check(f"mine_{index}" in kept_types, "my object types survive", sorted(kept_types))
    break
check({f"mine_{i}" for i in range(3)} <= kept_types, "all three of them", sorted(kept_types))
check(not any(name.startswith("theirs_") for name in kept_types),
      "and none of theirs", sorted(kept_types))

# The child closure still works. `logic_runs` has no project_id column at all,
# so a project filter cannot select it -- it comes back through its parent.
check("project_id" not in {c.name for c in models.LogicRun.__table__.columns},
      "logic_runs really has no project column", None)
kept_runs = {row["id"] for row in scoped.get("logic_runs") or []}
check(kept_runs == {"run_mine"},
      "the child of my logic function survives and theirs does not", kept_runs)

# --- an unscoped snapshot still reads everything ----------------------------
#
# `_for_project` is a no-op without a project, and it has to be: an unscoped
# snapshot is how a whole instance is exported, and a filter on a missing value
# would quietly export nothing.

with SessionLocal() as db:
    everything = hardening._snapshot(db, None, None, finalize=False)
all_types = {row["id"] for row in everything.get("object_types") or []}
check({f"theirs_{i}" for i in range(25)} <= all_types,
      "an unscoped snapshot still contains other projects", len(all_types))
check({f"mine_{i}" for i in range(3)} <= all_types, "and mine", len(all_types))

# --- the routes still answer -------------------------------------------------

export = client.get("/project/export")
check(export.status_code == 200, "export answers", export.status_code)
exported = {row["id"] for row in export.json().get("object_types") or []}
check(not any(name.startswith("theirs_") for name in exported),
      "and exports only this project", sorted(exported)[:6])
check(len((export.json().get("integrity") or {}).get("checksum", "")) == 64,
      "still checksummed", None)

validate = client.get("/project/validate")
check(validate.status_code == 200, "validate answers", validate.status_code)
coverage = (validate.json().get("sections") or {}).get("snapshot_coverage") or {}
check(coverage.get("counts", {}).get("object_types") == len(kept_types),
      "and its coverage counts agree with the scoped snapshot",
      (coverage.get("counts", {}).get("object_types"), len(kept_types)))

# --- a child belongs to its parent's project, not to its own column ----------
#
# This is the regression the first pass shipped. Fifteen child collections carry
# a `project_id` of their own, and filtering on it looked equivalent -- it is
# not. `_scope_snapshot` reads children from the *unscoped* list and keeps the
# ones whose foreign key points at a parent in scope, so a row whose parent is
# in the project belongs in the snapshot whatever its own column says. Narrowing
# by the column first deleted it before the closure could see it.

from sqlalchemy import Boolean, Float, Integer, JSON  # noqa: E402

from app import event_outbox  # noqa: E402
from app.system_hardening import (  # noqa: E402
    _SNAPSHOT_CHILD_QUERIES, _SNAPSHOT_CHILD_RELATIONS,
)

check(set(_SNAPSHOT_CHILD_QUERIES) == set(_SNAPSHOT_CHILD_RELATIONS),
      "the two child maps describe the same set, so neither drifts alone",
      set(_SNAPSHOT_CHILD_QUERIES) ^ set(_SNAPSHOT_CHILD_RELATIONS))


def filled(model, **overrides):
    """A row with every non-nullable column populated, whatever they are."""
    values = {}
    for column in model.__table__.columns:
        if column.name in overrides:
            values[column.name] = overrides[column.name]
            continue
        if column.nullable or column.default is not None or column.server_default is not None:
            continue
        kind = type(column.type)
        values[column.name] = (
            0 if issubclass(kind, Integer) else
            0.0 if issubclass(kind, Float) else
            False if issubclass(kind, Boolean) else
            {} if issubclass(kind, JSON) else "x")
    return model(**values)


with SessionLocal() as db:
    db.add(filled(event_outbox.EventOutbox, id="evt_mine", project_id=MINE,
                  created_at=now, updated_at=now))
    db.add(filled(event_outbox.EventOutbox, id="evt_theirs", project_id=THEIRS,
                  created_at=now, updated_at=now))
    db.flush()
    # Deliberately crossed: each child's own project_id contradicts its parent.
    db.add(filled(event_outbox.PlatformEventLog, sequence=901, event_id="e_mine",
                  outbox_event_id="evt_mine", project_id=THEIRS, created_at=now))
    db.add(filled(event_outbox.PlatformEventLog, sequence=902, event_id="e_theirs",
                  outbox_event_id="evt_theirs", project_id=MINE, created_at=now))
    db.commit()

loaded, scoped = build(MINE)
parents = sorted(row.get("outbox_event_id") for row in scoped.get("platform_event_log") or [])
check(parents == ["evt_mine"],
      "the child of my parent is kept even though its own project_id says otherwise",
      parents)
check("evt_theirs" not in parents,
      "and the child claiming my project is not, because its parent is not mine", parents)
check(len(loaded.get("platform_event_log") or []) == 1,
      "only the one child row was read at all", len(loaded.get("platform_event_log") or []))

print(f"Snapshot project pushdown verified: {passed} assertions passed "
      f"({len(loaded_types)} object types read, {len(kept_types)} kept, 25 foreign never touched).")

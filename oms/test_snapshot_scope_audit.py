"""The scope ratchet must name the collection that would vanish.

The failure it guards has no symptom. A collection whose serialised rows omit
`project_id` is dropped in its entirety by `_scope_snapshot`, and the export
still succeeds, the snapshot is still well formed, and a restore is simply short
of data nobody saw leave. Nothing goes red.

So the audit is checked against synthetic trees that contain that state, not
only against the real one that does not. An audit only ever run against a
passing tree is an assertion about that tree.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import audit_snapshot_scope as audit  # noqa: E402

passed = 0


def check(condition, label, payload=None):
    global passed
    assert condition, f"{label}: {payload}"
    passed += 1


def tree(collections: str, scope_assignments: str = "") -> str:
    """A source file shaped enough for the audit to read."""
    return (
        "def _snapshot(db, project_id=None, organization_id=None):\n"
        "    snapshot = {\n"
        f"{collections}"
        "    }\n"
        "    if project_id:\n"
        "        snapshot = _scope_snapshot(db, snapshot, project_id, organization_id)\n"
        "    return snapshot\n"
        "\n\n"
        "def _scope_snapshot(db, snapshot, project_id, organization_id):\n"
        "    scoped = {}\n"
        f"{scope_assignments}"
        "    return scoped\n"
        "\n\n"
        "def _after():\n"
        "    return None\n"
    )


SAFE = ('        "widgets": [\n'
        '            _row_dict(row, ["id", "project_id", "name"])\n'
        '            for row in db.query(models.Widget).all()\n'
        '        ],\n')
UNSAFE = ('        "gadgets": [\n'
          '            _row_dict(row, ["id", "name"])\n'
          '            for row in db.query(models.Gadget).all()\n'
          '        ],\n')

# --- the state that has no symptom ------------------------------------------

entries, unsafe = audit.survey(tree(SAFE + UNSAFE), child_relations=set())
check(len(unsafe) == 1, "a collection that omits project_id is reported", unsafe)
check("gadgets" in unsafe[0], "and it is named", unsafe)
check("dropped" in unsafe[0], "with what happens to it", unsafe)
check(entries["widgets"]["safe"] and not entries["gadgets"]["safe"],
      "the one that carries the key is fine", entries)

# --- the three ways to be safe ----------------------------------------------

_entries, unsafe = audit.survey(tree(SAFE), child_relations=set())
check(unsafe == [], "serialising project_id is enough", unsafe)

_entries, unsafe = audit.survey(tree(UNSAFE), child_relations={"gadgets"})
check(unsafe == [], "being a declared child is enough", unsafe)

_entries, unsafe = audit.survey(
    tree(UNSAFE, '    scoped["gadgets"] = [row for row in snapshot["gadgets"]]\n'),
    child_relations=set())
check(unsafe == [], "being assigned explicitly by _scope_snapshot is enough", unsafe)

# The explicit rules are read from the scoping function rather than listed, so
# a hand-maintained exception list cannot drift away from the code.
keys = audit.explicit_scope_keys(
    tree("", '    scoped["a"] = []\n    scoped["b"] = copy.deepcopy(x)\n'))
check(keys == {"a", "b"}, "explicit assignments are read out of the source", keys)

# A child declaration for a collection that does not exist must not silence a
# different one -- the ratchet has to fail on the gadget, not be satisfied by
# an unrelated declaration.
_entries, unsafe = audit.survey(tree(UNSAFE), child_relations={"something_else"})
check(len(unsafe) == 1 and "gadgets" in unsafe[0],
      "an unrelated child declaration does not cover it", unsafe)

# --- the real tree ------------------------------------------------------------

from app.system_hardening import _SNAPSHOT_CHILD_RELATIONS  # noqa: E402

source = audit.SOURCE.read_text(encoding="utf-8")
real, real_unsafe = audit.survey(source, set(_SNAPSHOT_CHILD_RELATIONS))
check(len(real) > 100, "the audit reads the whole snapshot builder", len(real))
check(real_unsafe == [], "no collection currently vanishes from a scoped snapshot", real_unsafe)
check(all(entry["safe"] for entry in real.values()), "every collection is safe by some route", None)

covered = {route: sum(1 for entry in real.values()
                      if entry.get(route) and not entry["carries_project_id"])
           for route in ("child", "explicit")}
check(covered["child"] > 0, "the parent closure genuinely covers some of them", covered)
check(sum(1 for entry in real.values() if entry["carries_project_id"]) > 100,
      "and most simply carry the key", None)

print(f"Snapshot scope audit verified: {passed} assertions passed "
      f"({len(real)} collections, {len(real_unsafe)} unsafe).")

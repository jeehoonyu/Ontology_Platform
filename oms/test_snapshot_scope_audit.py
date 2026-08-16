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

# --- narrowing a collection the closure reads unscoped -----------------------
#
# The second regression this file exists to refuse, and the one the full suite
# caught rather than this audit: filtering `data_assets` by project in the
# builder deleted the legacy rows `_scope_snapshot` recognises by reading
# `row["asset_schema"]["project_id"]`, and the export came out short. A restore
# then failed with "references missing scoped data_assets 'ingestion_target'".

def narrowing_tree(query: str) -> str:
    return (
        "def _snapshot(db, project_id=None, organization_id=None):\n"
        "    snapshot = {\n"
        '        "data_assets": [\n'
        '            _row_dict(row, ["id", "project_id"])\n'
        f"            for row in {query}.all()\n"
        "        ],\n"
        "    }\n"
        "    snapshot = _scope_snapshot(db, snapshot, project_id, organization_id)\n"
        "    return snapshot\n\n\n"
        "def _scope_snapshot(db, snapshot, project_id, organization_id):\n"
        "    scoped = {}\n"
        '    legacy = [row for row in snapshot.get("data_assets") or [] if row]\n'
        "    return scoped\n\n\n"
        "def _after():\n"
        "    return None\n"
    )


_entries, unsafe = audit.survey(
    narrowing_tree("_for_project(db.query(models.DataAsset), models.DataAsset.project_id, project_id)"),
    child_relations=set())
check(any("data_assets" in line and "unscoped" in line for line in unsafe),
      "narrowing a collection the closure reads unscoped is refused", unsafe)

_entries, unsafe = audit.survey(narrowing_tree("db.query(models.DataAsset)"), child_relations=set())
check(unsafe == [], "and allowed once the builder stops narrowing it", unsafe)

# The matcher has to walk whole entries. A pattern reaching from the key to the
# call cannot cross the `]` that closes `_row_dict`'s field list, and the first
# version of this check matched nothing at all -- passing by measuring nothing.
narrowed = audit.narrowed_in_builder(
    narrowing_tree("_for_project(db.query(models.DataAsset), models.DataAsset.project_id, project_id)"))
check(narrowed == {"data_assets"},
      "the matcher sees a narrowed entry whose serialiser contains a bracket", narrowed)

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

source = audit.SOURCE.read_text(encoding="utf-8")
overlap = audit.narrowed_in_builder(source) & audit.closure_reads(source)
check(overlap == set(),
      "no collection in the real tree is both narrowed and read unscoped", sorted(overlap))
check(len(audit.narrowed_in_builder(source)) > 50,
      "and the matcher is actually finding the narrowed ones", len(audit.narrowed_in_builder(source)))
check(len(audit.closure_reads(source)) > 3,
      "and the closure reads it protects", sorted(audit.closure_reads(source)))

print(f"Snapshot scope audit verified: {passed} assertions passed "
      f"({len(real)} collections, {len(real_unsafe)} unsafe).")

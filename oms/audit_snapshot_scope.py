"""Ratchet: no snapshot collection may be silently emptied by scoping.

`_scope_snapshot` narrows a portable snapshot to one project by filtering every
collection on `row.get("project_id")` -- the **serialised key**, not the column.
A collection whose rows do not carry that key is therefore dropped in its
entirety, and the failure has no symptom: the export succeeds, the snapshot is
well formed, and the collection is simply absent. A restore from it is short of
data nobody noticed leaving.

Three things save a collection from that, and one of them is enough:

  * its serialised rows carry `project_id`, so the filter can see them
  * it is declared in `_SNAPSHOT_CHILD_RELATIONS`, so the closure re-adds it by
    parent identity -- `logic_runs` has no `project_id` column at all and comes
    back through `logic_functions`
  * `_scope_snapshot` assigns it explicitly, as it does for `projects`,
    `organizations`, `plugin_trust_keys` and the ontology packages

The census on 2026-08-15 found 133 collections and **zero** unsafe ones, which
is exactly when this is cheapest to install: it costs nothing today and refuses
the first collection added without one of the three.

Nothing here is hand-maintained. The child relations are read from the module,
the explicit rules are read from `_scope_snapshot`'s own assignments, and the
serialised keys are read from each entry. A list of exceptions would be the
thing that rots.

  python oms/audit_snapshot_scope.py
"""
from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Dict, List, Set, Tuple

REPO_ROOT = Path(__file__).resolve().parent.parent
SOURCE = REPO_ROOT / "oms" / "app" / "system_hardening.py"


def snapshot_body(source: str) -> str:
    """The dict literal `_snapshot` builds, up to where scoping takes over."""
    start = source.index("def _snapshot(db")
    end = source.index("_scope_snapshot(db, snapshot", start)
    return source[start:end]


def scope_body(source: str) -> str:
    start = source.index("def _scope_snapshot(")
    remainder = source[start + 1:]
    offset = remainder.index("\ndef ")
    return source[start:start + 1 + offset]


def collections(source: str) -> Dict[str, Dict[str, object]]:
    """Every list-valued collection, and whether its rows carry `project_id`.

    Two serialiser shapes exist. `_row_dict(row, [...])` states its fields
    inline and can be read exactly. A custom `_x_dict(row)` cannot, so the
    function's own source is searched for the key -- a heuristic, and reported
    as one rather than presented as a reading.
    """
    found: Dict[str, Dict[str, object]] = {}
    for match in re.finditer(r'"(\w+)":\s*\[(.*?)\],\n', snapshot_body(source), re.S):
        key, inner = match.group(1), " ".join(match.group(2).split())
        fields = re.search(r"_row_dict\(row, \[(.*?)\]\)", inner)
        if fields:
            found[key] = {"carries_project_id": '"project_id"' in fields.group(1),
                          "read": "field list"}
            continue
        serialiser = re.match(r"([A-Za-z_][\w.]*)\(", inner)
        found[key] = {"carries_project_id": None,
                      "read": f"custom serialiser {serialiser.group(1)}" if serialiser else "unknown",
                      "serialiser": serialiser.group(1) if serialiser else None}
    return found


def closure_reads(source: str) -> Set[str]:
    """Collections whose scoped result is computed from the UNSCOPED snapshot.

    `_scope_snapshot` reads some collections back out of `snapshot` rather than
    out of `scoped`, because their rule depends on the rows the generic
    project filter would already have thrown away: a legacy `data_asset` is
    recognised by `row["asset_schema"]["project_id"]`, and every child is
    matched against its parent's id.

    Narrowing those in the builder deletes the rows before the rule can see
    them. That is not a slower snapshot, it is a smaller one -- and both times it
    happened the export simply lacked data, which is the failure this file exists
    to refuse. The full suite caught the second instance:

        Resource 'connection_syncs:maintenance_sync' references
        missing scoped data_assets 'ingestion_target'
    """
    return set(re.findall(r'snapshot\.get\("(\w+)"\)', scope_body(source)))


def narrowed_in_builder(source: str) -> Set[str]:
    r"""Collections the builder filters by project before scoping sees them.

    Matched by walking whole entries rather than by a pattern that has to reach
    across one. The first version used `[^\]]*?` between the key and the call,
    which cannot cross the `]` that closes `_row_dict`'s own field list -- so it
    matched nothing at all and the check passed by measuring nothing. Verified
    against a tree containing the state it is meant to refuse.
    """
    narrowed = set()
    for match in re.finditer(r'"(\w+)":\s*\[(.*?)\],\n', snapshot_body(source), re.S):
        if "_for_project(" in match.group(2):
            narrowed.add(match.group(1))
    return narrowed


def explicit_scope_keys(source: str) -> Set[str]:
    """Collections `_scope_snapshot` assigns by name, whatever the rule is."""
    return set(re.findall(r'scoped\["(\w+)"\]\s*=', scope_body(source)))


def resolve_custom(entries: Dict[str, Dict[str, object]]) -> None:
    """Ask each custom serialiser's source whether it emits `project_id`."""
    import inspect

    sys.path.insert(0, str(REPO_ROOT / "oms"))
    from app import system_hardening  # noqa: F401

    namespace = vars(system_hardening)
    for entry in entries.values():
        if entry.get("carries_project_id") is not None:
            continue
        name = entry.get("serialiser")
        target = None
        if name:
            target = namespace.get(name.split(".")[0])
            for part in name.split(".")[1:]:
                target = getattr(target, part, None)
        try:
            body = inspect.getsource(target) if target is not None else ""
        except (OSError, TypeError):
            body = ""
        entry["carries_project_id"] = '"project_id"' in body
        entry["read"] = entry["read"] + (" (source searched)" if body else " (unreadable)")


def survey(source: str, child_relations: Set[str]) -> Tuple[Dict[str, Dict[str, object]], List[str]]:
    entries = collections(source)
    resolve_custom(entries)
    explicit = explicit_scope_keys(source)
    unsafe = [
        f"{key}: narrowed by project in the builder, but _scope_snapshot reads it from the "
        "unscoped snapshot -- the rows its rule needs are deleted before it runs"
        for key in sorted(closure_reads(source) & narrowed_in_builder(source))
    ]
    for key, entry in sorted(entries.items()):
        entry["child"] = key in child_relations
        entry["explicit"] = key in explicit
        entry["safe"] = bool(entry["carries_project_id"]) or entry["child"] or entry["explicit"]
        if not entry["safe"]:
            unsafe.append(
                f"{key}: rows carry no project_id ({entry['read']}), it is not a declared "
                "child, and _scope_snapshot never assigns it -- every row is dropped"
            )
    return entries, unsafe


def main() -> int:
    sys.path.insert(0, str(REPO_ROOT / "oms"))
    from app.system_hardening import _SNAPSHOT_CHILD_RELATIONS

    source = SOURCE.read_text(encoding="utf-8")
    entries, unsafe = survey(source, set(_SNAPSHOT_CHILD_RELATIONS))

    carried = sum(1 for entry in entries.values() if entry["carries_project_id"])
    children = sum(1 for entry in entries.values() if entry["child"] and not entry["carries_project_id"])
    explicit = sum(1 for entry in entries.values()
                   if entry["explicit"] and not entry["carries_project_id"] and not entry["child"])
    print(f"Snapshot scope safety over {len(entries)} collections\n")
    print(f"  {carried:4d}  serialise project_id")
    print(f"  {children:4d}  re-added by the parent closure")
    print(f"  {explicit:4d}  assigned explicitly by _scope_snapshot")
    print(f"  {len(unsafe):4d}  dropped entirely by scoping")

    if unsafe:
        print(f"\nRATCHET BROKEN: {len(unsafe)} collection(s) would vanish from every snapshot:")
        for line in unsafe:
            print(f"  {line}")
        return 1
    print("\nEvery collection survives scoping by one of the three routes.")
    return 0


if __name__ == "__main__":
    from enforcement_runs import recording

    raise SystemExit(recording("audit_snapshot_scope", main))

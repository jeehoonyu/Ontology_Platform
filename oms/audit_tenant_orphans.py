"""Count the tables that name no tenant, directly or through any parent, and ratchet it.

T2 assumed every unscoped read could be scoped once someone got round to it. Opening
the modules showed that is not true. `render_workshop_module` resolved widget ids across
every project and was repaired in an afternoon, because `WorkshopModule` carries a
`project_id` to scope to. The same defect in `render_document` cannot be repaired at
all: `NotepadDocument` has no such column, and neither does any table it reaches. There
is no project to filter on. `SlateApp` and `AtmAutomation` were already recorded under
T5 for the same reason.

So the unscoped-read census measures a symptom. This measures the cause: a table holding
tenant work that never records which tenant. No read of such a table can be scoped, no
accessor can be written for it, and every route over it is cross-tenant by construction.

**What is measured.** Every mapped table, walked through its foreign keys. A table is
tenanted if it carries `project_id` or reaches a table that does. The rest name no tenant
at all, and are split against `docs/tenancy-substrate.json`:

  * *substrate* -- tables that should not carry a project, because they are what projects
    are made of (users, roles, spaces), the global policy vocabulary (markings,
    classifications), platform telemetry, or key material. Each entry records why.
  * *orphans* -- everything else. Tenant work with no tenant recorded. This is the ratchet.

**What the number is not.** The split is a judgement, not a derivation, which is why it
lives in a file that can be argued with rather than in this code. A table in the wrong
column is a wrong number, and the remedy is to move it and say why. What the ratchet can
honestly say is that the count fell, and that a new table cannot quietly join either list:
an unclassified table fails the gate rather than defaulting to harmless.

  python oms/audit_tenant_orphans.py
  python oms/audit_tenant_orphans.py --verbose
  python oms/audit_tenant_orphans.py --set-baseline
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, List

REPO_ROOT = Path(__file__).resolve().parent.parent
BASELINE = REPO_ROOT / "docs" / "tenant-orphans-baseline.json"
SUBSTRATE = REPO_ROOT / "docs" / "tenancy-substrate.json"


def _tables() -> Dict[str, Any]:
    scratch = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
    os.environ["DATABASE_URL"] = f"sqlite:///{Path(scratch.name, 'orphans.db').as_posix()}"
    sys.path.insert(0, str(REPO_ROOT / "oms"))
    from app import main  # noqa: F401  -- imports every router, and so every model
    from app.database import Base

    out = {}
    for mapper in Base.registry.mappers:
        table = mapper.class_.__table__
        out[table.name] = (mapper.class_.__name__, table)
    return out


def _convention_targets(column: str, index: Dict[str, str]) -> List[str]:
    """Tables a `<something>_id` column plausibly points at.

    Only 66 of the 271 tables declare a ForeignKey; the rest carry `artifact_id` or
    `module_id` as a bare string and rely on the name. Walking declared constraints alone
    therefore called plenty of well-parented children orphans -- `ArtifactRevision` among
    them, which is a revision *of* a project-carrying artifact.

    The match is a heuristic and it is deliberately generous: a column resolving to
    several tables counts as tenanted if any of them is, so the error runs toward
    declaring a table fine. That undercounts the debt, which is the safe direction for a
    number whose whole purpose is to be paid down -- an inflated one would be paid off by
    argument rather than by work.
    """
    stem = column[:-3]
    if not stem:
        return []
    key = stem.replace("_", "")
    return [table for suffix, table in index.items() if suffix.endswith(key)]


def read() -> Dict[str, Any]:
    tables = _tables()
    carries = {name for name, (_, table) in tables.items()
               if "project_id" in {column.name for column in table.columns}}

    # Both spellings a `<stem>_id` column might be aiming at: the mapped class name and
    # the physical table name, normalized so `artifact_id` reaches `PlatformArtifact`.
    index: Dict[str, str] = {}
    for name, (cls, _) in tables.items():
        index.setdefault(cls.lower(), name)
        index.setdefault(name.replace("_", "").rstrip("s"), name)
        index.setdefault(name.replace("_", ""), name)

    edges: Dict[str, set] = {}
    for name, (_, table) in tables.items():
        out = {fk.column.table.name for fk in table.foreign_keys}
        for column in table.columns:
            if column.name.endswith("_id") and column.name != "project_id":
                out.update(_convention_targets(column.name, index))
        edges[name] = {target for target in out if target != name}

    # Fixpoint: a table is tenanted if it carries a project or reaches one that does.
    tenanted = set(carries)
    changed = True
    while changed:
        changed = False
        for name, out in edges.items():
            if name not in tenanted and out & tenanted:
                tenanted.add(name)
                changed = True

    untenanted = sorted(cls for name, (cls, _) in tables.items() if name not in tenanted)

    substrate = json.loads(SUBSTRATE.read_text(encoding="utf-8"))["substrate"] \
        if SUBSTRATE.exists() else {}
    orphans = [name for name in untenanted if name not in substrate]

    # An exemption goes stale when its subject gains a project column of its own or stops
    # existing -- both are facts about the schema. Reaching a tenanted table through the
    # convention walk is not: that walk is generous by design, and letting it retire
    # exemptions would quietly drop identity and policy tables out of the list on the
    # strength of a name match.
    live = {cls: table for _, (cls, table) in tables.items()}
    stale = sorted(name for name in substrate
                   if name not in live
                   or "project_id" in {column.name for column in live[name].columns})

    return {
        "tables": len(tables),
        "tenanted": len(tenanted),
        "untenanted": len(untenanted),
        "substrate": sum(1 for name in untenanted if name in substrate),
        "orphans": orphans,
        "stale_substrate": stale,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--set-baseline", action="store_true")
    args = parser.parse_args()

    reading = read()
    print(f"{reading['tables']} mapped tables; {reading['tenanted']} name a tenant "
          f"directly or through a parent")
    print(f"    {reading['substrate']:>4}  name none by design (docs/tenancy-substrate.json)")
    print(f"    {len(reading['orphans']):>4}  hold tenant work with no tenant recorded")
    if args.verbose:
        for name in reading["orphans"]:
            print(f"      {name}")

    if reading["stale_substrate"]:
        print(f"\nFAIL -- {len(reading['stale_substrate'])} table(s) listed as substrate no "
              f"longer exist or now carry a tenant: {', '.join(reading['stale_substrate'])}. "
              f"An exemption outliving its subject is an exemption nobody checked.")
        return 1

    if args.set_baseline:
        BASELINE.write_text(json.dumps({
            "provenance": {
                "recorded_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "stale_after": "recomputed each run",
            },
            "note": ("Ratchet. Tables holding tenant work that record no tenant, directly or "
                     "through any parent. A read of one cannot be scoped and no accessor can "
                     "be written for it, so this is the cause the unscoped-read census "
                     "measures the symptom of. The substrate split is a judgement recorded "
                     "in docs/tenancy-substrate.json, not a derivation."),
            "tenant_orphan_ceiling": len(reading["orphans"]),
            "substrate_reference": reading["substrate"],
            "tables_reference": reading["tables"],
        }, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(f"\nBaseline set: ceiling {len(reading['orphans'])}.")
        return 0

    if not BASELINE.exists():
        print("\nNo baseline recorded. Run with --set-baseline to start the ratchet.")
        return 0

    ceiling = json.loads(BASELINE.read_text(encoding="utf-8"))["tenant_orphan_ceiling"]
    count = len(reading["orphans"])
    if count > ceiling:
        print(f"\nRATCHET BROKEN: {count} tables name no tenant, above the ceiling of "
              f"{ceiling}. A table that records no project cannot have its reads scoped, "
              f"so every route over it is cross-tenant by construction.")
        return 1
    if count < ceiling:
        print(f"\nRatchet held, and improved: {ceiling} -> {count}. "
              f"Re-run with --set-baseline to lock it in.")
        return 0
    print(f"\nRatchet held: {count} <= {ceiling}.")
    return 0


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from enforcement_runs import recording  # noqa: E402

    sys.exit(recording("audit_tenant_orphans", main))

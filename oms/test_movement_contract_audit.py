"""A move the contract cannot vouch for must trip the rule, and a proven one must not.

Also this check's home: `audit_movement_contract` declares `every suite run`.

The reference `docs/MOVEMENT_CONTRACT.md` reports a gap count, and a gap count is
only worth something once the rules have been shown to refuse. The assertions
below run the real judge over synthetic surfaces.

The group that matters most is the one about `na`. Every other way to lower this
count needs a behaviour and a browser test; declaring a stage not applicable needs
a sentence. If that passed, the gate would report a number that is wrong rather
than merely high.
"""
import copy
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from audit_movement_contract import (  # noqa: E402
    BASELINE, REFERENCE, STAGES, SURFACES, cell_problem, cells_of, compare, render, required_pairs,
)
from audit_drag_affordances import scan as drag_scan  # noqa: E402

checks = 0


def check(condition, message):
    global checks
    assert condition, message
    checks += 1


found = drag_scan()
live_baseline = {"gaps": len(cells_of(SURFACES, "gap")), "gap_cells": cells_of(SURFACES, "gap"),
                 "na_cells": cells_of(SURFACES, "na")}

# --- the live tree ---------------------------------------------------------------
ok, failures, _ = compare(found, live_baseline, check_reference=False)
check(ok, f"the current tree fails its own rules: {failures}")
check(required_pairs(found) <= {(s["file"], s["mechanism"]) for s in SURFACES.values()},
      "a drag the census knows has no surface")
check(len(required_pairs(found)) >= 8, f"only {len(required_pairs(found))} (file, mechanism) pairs; "
      "the drag census is not being read")

# --- a cell says exactly one thing, and says something -----------------------------
check(cell_problem({}) != "", "an empty cell passes")
check(cell_problem({"gap": "x", "test": "y"}) != "", "a cell claiming two states passes")
check(cell_problem({"gap": ""}) != "", "a gap with no reason passes")
check(cell_problem({"na": "   "}) != "", "an n/a with only whitespace passes")
check(cell_problem({"maybe": "x"}) != "", "an unknown state passes")
check(cell_problem({"gap": "not measured"}) == "", "a well-formed gap is refused")

# --- a met stage names a test that exists ------------------------------------------
check("does not exist" in cell_problem({"test": "no-such.spec.ts::anything"}),
      "a test in a spec file that does not exist passes")
check("no longer contains" in cell_problem({"test": "movement-contract.spec.ts::a title nobody wrote"}),
      "a title the spec does not contain passes")
check("names no browser test" in cell_problem({"test": "just a sentence"}),
      "a claim with no spec::title shape passes")
check(cell_problem({"test": "movement-contract.spec.ts::Escape during a pane drag leaves the pane in its slot"}) == "",
      "a real test is refused")

# --- every drag the census knows is covered -----------------------------------------
without = copy.deepcopy(SURFACES)
del without["platform-graph-node"]
ok, failures, _ = compare(found, live_baseline, without, check_reference=False)
check(not ok and any("PlatformGraph.tsx moves something with xyflow" in f for f in failures),
      f"removing the only surface for a live drag is not refused: {failures}")

stale = copy.deepcopy(SURFACES)
stale["invented"] = {"file": "workspaces/Automate.tsx", "mechanism": "dnd-kit", "moves": "nothing",
                     "cancel": {"gap": "x"}, "recover": {"gap": "x"}, "alternative": {"gap": "x"}}
ok, failures, _ = compare(found, live_baseline, stale, check_reference=False)
check(not ok and any("no longer finds there" in f for f in failures),
      f"a surface whose file has no such drag is not refused: {failures}")

# --- the evasion path: n/a written instead of a behaviour ------------------------------
evaded = copy.deepcopy(SURFACES)
evaded["visual-node"]["cancel"] = {"na": "a graph editor handles its own pointers"}
ok, failures, notes = compare(found, live_baseline, evaded, check_reference=False)
check(not ok and any("newly declared not applicable" in f for f in failures),
      "turning a gap into n/a lowers the count and passes -- this is the gate's own evasion path")

# --- the ratchet ----------------------------------------------------------------------
regressed = copy.deepcopy(SURFACES)
regressed["pane-move"]["cancel"] = {"gap": "stopped restoring"}
ok, failures, _ = compare(found, live_baseline, regressed, check_reference=False)
check(not ok and any("up from" in f for f in failures), f"a rising gap count is not refused: {failures}")
check(not ok and any("pane-move.cancel is a gap the baseline does not hold" in f for f in failures),
      "a met stage becoming a gap is not named")

# A swap that keeps the total level: one gap closed, another stage regressed.
swapped = copy.deepcopy(regressed)
swapped["visual-node"]["cancel"] = {"test": "movement-contract.spec.ts::Escape during a pane drag leaves the pane in its slot"}
ok, failures, _ = compare(found, live_baseline, swapped, check_reference=False)
check(not ok and any("pane-move.cancel" in f for f in failures),
      f"closing one gap while opening another passes because the total held: {failures}")

improved = copy.deepcopy(SURFACES)
improved["visual-node"]["cancel"] = {"test": "movement-contract.spec.ts::Escape during a pane drag leaves the pane in its slot"}
ok, failures, notes = compare(found, live_baseline, improved, check_reference=False)
check(ok and any("->" in n for n in notes), f"closing a gap is refused or unreported: {failures} {notes}")

# --- rendering --------------------------------------------------------------------------
text = render()
check(render() == text, "rendering twice gives the same bytes")
check(f"**{len(cells_of(SURFACES, 'gap'))} gaps**" in text, text[:300])
for name, surface in SURFACES.items():
    for stage in STAGES:
        check(f"| `{name}` | {surface['mechanism']} |" in text and f"| {stage} |" in text,
              f"{name}.{stage} is missing from the reference")

check(BASELINE.exists(), f"no baseline at {BASELINE}")
check(REFERENCE.exists(), f"no reference at {REFERENCE}")
check(REFERENCE.read_text(encoding="utf-8") == text, "the committed reference is stale; run --write")

print(f"Movement contract gate verified: {checks} assertions passed "
      f"({len(cells_of(SURFACES, 'gap'))} gaps, {len(cells_of(SURFACES, 'test'))} met, "
      f"{len(cells_of(SURFACES, 'na'))} n/a across {len(SURFACES)} surfaces).")

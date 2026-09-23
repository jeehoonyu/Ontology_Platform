"""Every movement surface, counted against cancel, recover and a single-pointer alternative.

V1 of `GOAL_MOVEMENT_2026-09-12.md`. The September 12 research proposes an
interaction contract for every drag in the product and puts one item before any
feature: *recheck the existing implementation against the contract and record
the gaps.* This is that record, made a gate so it cannot quietly go stale.

`audit_drag_affordances` already answers *which* mechanism each drag uses and
whether it can be reached without a mouse. This asks what happens around a
move, in three stages:

    cancel        Escape mid-drag restores the exact starting arrangement and
                  writes nothing
    recover       one Undo reverses one completed move
    alternative   a single pointer can do it without dragging -- WCAG 2.5.7, which
                  keyboard support does not satisfy

**A surface is finer than a file.** `Pane.tsx` moves a pane between slots on
`DragKit` and resizes a slot on a pointer listener, and those two cancel
differently -- one restores on Escape and the other commits -- so they are two
rows. The drag census supplies the files and mechanisms; every one of them must
be covered by at least one surface here, and a surface naming a mechanism its
file no longer has is refused.

**Each cell is one of three things, and says why:**

    {"test": "spec::title"}   met, and the named browser test still exists
    {"gap": "..."}             not met, or not measured -- counted
    {"na": "..."}              the stage does not apply, with the reason

Not measured is a gap. The census that preceded this found two drags that
"passed" Escape because they had never started; a stage nobody has operated is
not a stage that works.

**Declaring a stage not applicable is this gate's evasion path, and is refused.**
Every other way to lower the gap count needs a behaviour and a test. Writing
`na` needs a sentence. So an `na` the baseline does not already hold fails the
gate, and becomes an edit to the baseline someone makes in the open -- the same
shape as the empty handler in `audit_inert_controls` and the call-site slice in
`audit_table_truncation`.

  - *Reported:* every surface against every stage.
  - *Gated:* the gap count rising, and any cell that was met becoming a gap.
  - *Gated:* a cell newly declared not applicable.
  - *Gated:* a met cell naming a test that does not exist.
  - *Gated:* a drag the census knows that no surface covers, or a surface whose
    mechanism has left its file.
  - *Gated:* the checked-in reference disagreeing with the source.

  python oms/audit_movement_contract.py            # judge
  python oms/audit_movement_contract.py --write    # regenerate the reference
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Set, Tuple

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))

from audit_drag_affordances import proof_missing, scan as drag_scan  # noqa: E402

REFERENCE = REPO_ROOT / "docs" / "MOVEMENT_CONTRACT.md"
BASELINE = REPO_ROOT / "docs" / "movement-contract-baseline.json"

STAGES = ("cancel", "recover", "alternative")
MECHANISMS = ("dnd-kit", "xyflow", "pointer")

Cell = Dict[str, str]

SURFACES: Dict[str, Dict[str, Any]] = {
    "pane-move": {
        "file": "components/layout/Pane.tsx", "mechanism": "dnd-kit",
        "moves": "a pane between the slots of a screen",
        "cancel": {"test": "movement-contract.spec.ts::Escape during a pane drag leaves the pane in its slot"},
        "recover": {"na": "a pane's slot is a viewing preference rather than an edit: `Move to…` "
                          "puts it back in one choice and `Reset panes` restores every pane"},
        "alternative": {"test": "pane-layout.spec.ts::a pane moves to another slot without a drag"},
    },
    "pane-resize": {
        "file": "components/layout/Pane.tsx", "mechanism": "pointer",
        "moves": "the boundary between two slots",
        "cancel": {"test": "movement-contract.spec.ts::Escape during a splitter resize restores the "
                           "width and writes nothing"},
        "recover": {"na": "a width is a viewing preference; arrow keys, `Home`, `End` and "
                          "`Reset panes` all set it back"},
        "alternative": {"test": "movement-contract.spec.ts::a slot resizes with a single pointer and no drag"},
    },
    "pipeline-node": {
        "file": "components/canvas/PipelineCanvas.tsx", "mechanism": "dnd-kit",
        "moves": "a node around the pipeline canvas",
        "cancel": {"test": "movement-contract.spec.ts::Escape during a pipeline node drag restores "
                           "it and saves nothing"},
        "recover": {"test": "movement-contract.spec.ts::one Undo takes back a committed pipeline node move"},
        "alternative": {"gap": "moves from the keyboard, and not from a single pointer without a drag"},
    },
    "pipeline-lasso": {
        "file": "components/canvas/PipelineCanvas.tsx", "mechanism": "dnd-kit",
        "moves": "a selection rectangle over the pipeline canvas (X2 of GOAL_GRAPH)",
        "cancel": {"test": "graph-editor.spec.ts::a lasso selects the nodes inside it and Escape "
                           "selects nothing"},
        "recover": {"na": "a lasso moves nothing and writes nothing, so there is no move to undo; "
                          "Escape, a click or another lasso replaces what it selected"},
        "alternative": {"test": "graph-editor.spec.ts::the nodes a lasso selects can be selected "
                                "without a drag"},
    },
    "pipeline-palette": {
        "file": "workspaces/PipelineBuilder.tsx", "mechanism": "dnd-kit",
        "moves": "a node type from the palette onto the pipeline canvas",
        "cancel": {"test": "movement-contract.spec.ts::Escape during a palette drag onto the pipeline "
                           "canvas adds no node and writes nothing"},
        "recover": {"gap": "an added node can be deleted with `Delete node`; nothing undoes the add"},
        "alternative": {"test": "touch-authoring.spec.ts::a touch user can add the first node to a pipeline"},
    },
    "visual-library": {
        "file": "workspaces/VisualBuilder.tsx", "mechanism": "dnd-kit",
        "moves": "a node type from the library onto an artifact canvas",
        "cancel": {"test": "movement-contract.spec.ts::Escape during a library drag onto an artifact "
                           "canvas adds no node and records nothing"},
        "recover": {"test": "movement-contract.spec.ts::one Undo takes back a node dropped from the library"},
        "alternative": {"test": "drag-affordances.spec.ts::a library node reaches the canvas without a drag"},
    },
    "visual-field-order": {
        "file": "workspaces/VisualBuilder.tsx", "mechanism": "dnd-kit",
        "moves": "a configuration field up or down in the inspector",
        "cancel": {"test": "movement-contract.spec.ts::Escape during a field reorder keeps the order "
                           "and records nothing"},
        "recover": {"test": "movement-contract.spec.ts::one Undo takes back one field reorder"},
        "alternative": {"gap": "the grip is the only control; it sorts from the keyboard and there "
                               "is no Up or Down"},
    },
    "ontology-field-map": {
        "file": "workspaces/OntologyManager.tsx", "mechanism": "dnd-kit",
        "moves": "a source dataset field onto a property",
        "cancel": {"test": "movement-contract.spec.ts::Escape during a field-mapping drag maps nothing "
                           "and writes nothing"},
        "recover": {"gap": "the mapping panel has no undo"},
        "alternative": {"test": "drag-affordances.spec.ts::a source field maps onto a property "
                                "without a drag"},
    },
    "ontology-property-order": {
        "file": "workspaces/OntologyManager.tsx", "mechanism": "dnd-kit",
        "moves": "a property row up or down",
        "cancel": {"test": "movement-contract.spec.ts::Escape during a property-row drag keeps the order "
                           "and writes nothing"},
        "recover": {"gap": "the property list has no undo"},
        "alternative": {"test": "drag-affordances.spec.ts::a property row reorders without a drag"},
    },
    "visual-node": {
        "file": "workspaces/VisualBuilder.tsx", "mechanism": "xyflow",
        "moves": "a node around a Workshop, AIP Logic, Investigations or Entity Resolution canvas",
        "cancel": {"test": "movement-contract.spec.ts::Escape during an artifact canvas drag restores "
                           "the node and records nothing"},
        "recover": {"test": "movement-contract.spec.ts::one drag on an artifact canvas is taken back by "
                            "one Undo"},
        "alternative": {"gap": "no control places a node without dragging it"},
    },
    "ontology-graph-node": {
        "file": "workspaces/OntologyManager.tsx", "mechanism": "xyflow",
        "moves": "an object type around the relationship designer",
        "cancel": {"gap": "not measured; the same library as the artifact canvases"},
        "recover": {"gap": "no undo; since V8 an arrangement is kept in this browser rather than "
                           "discarded on reload"},
        "alternative": {"gap": "no control places a node without dragging it"},
    },
    "platform-graph-node": {
        "file": "workspaces/PlatformGraph.tsx", "mechanism": "xyflow",
        "moves": "a resource around the platform graph",
        "cancel": {"gap": "not measured; the same library as the artifact canvases"},
        "recover": {"gap": "no undo; `Save positions on this device` keeps them and `Auto layout` "
                           "replaces them"},
        "alternative": {"gap": "no control places a node without dragging it"},
    },
}


def required_pairs(found: Dict[str, Any]) -> Set[Tuple[str, str]]:
    """Every (file, mechanism) the drag census says moves something."""
    return ({(f, "dnd-kit") for f in found["dnd-kit"]}
            | {(f, "xyflow") for f in found["xyflow"]}
            | {(f, "pointer") for f in found["pointer"]})


def kind_of(cell: Cell) -> str:
    return next(iter(cell)) if len(cell) == 1 else ""


def cell_problem(cell: Any) -> str:
    """Empty when the cell is well formed and, if it claims a test, the test exists."""
    if not isinstance(cell, dict) or len(cell) != 1 or kind_of(cell) not in ("test", "gap", "na"):
        return "must be exactly one of test, gap or na"
    value = cell[kind_of(cell)]
    if not isinstance(value, str) or not value.strip():
        return f"is `{kind_of(cell)}` with nothing said"
    if kind_of(cell) == "test":
        return proof_missing({"proven_by": value})
    return ""


def cells_of(surfaces: Dict[str, Dict[str, Any]], kind: str) -> List[str]:
    return sorted(f"{name}.{stage}" for name, surface in surfaces.items()
                  for stage in STAGES if kind_of(surface.get(stage, {})) == kind)


def render(surfaces: Dict[str, Dict[str, Any]] = SURFACES) -> str:
    gaps, met, na = (len(cells_of(surfaces, kind)) for kind in ("gap", "test", "na"))
    lines = [
        "# Cancel, recover, and a way without dragging",
        "",
        "Generated by `oms/audit_movement_contract.py`. Do not edit by hand — the gate",
        "regenerates this and fails if it disagrees with the source.",
        "",
        f"**{gaps} gaps** across {len(surfaces)} movement surfaces and {len(STAGES)} stages: "
        f"{met} met by a named browser test, {na} not applicable with a reason.",
        "",
        "- **cancel** — Escape mid-drag restores the exact starting arrangement and writes nothing.",
        "- **recover** — one Undo reverses one completed move.",
        "- **alternative** — a single pointer can do it without dragging (WCAG 2.5.7);",
        "  keyboard support alone does not count.",
        "",
        "Not measured is a gap. A stage nobody has operated is not a stage that works.",
        "",
        "| Surface | Mechanism | Moves | Stage | State | Evidence |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    labels = {"test": "met", "gap": "**gap**", "na": "n/a"}
    for name, surface in surfaces.items():
        for stage in STAGES:
            cell = surface.get(stage, {})
            kind = kind_of(cell)
            evidence = cell.get(kind, "") if kind else ""
            if kind == "test":
                evidence = f"`{evidence.replace('::', '` — ')}"
            lines.append(f"| `{name}` | {surface['mechanism']} | {surface['moves']} | {stage} "
                         f"| {labels.get(kind, '**malformed**')} | {evidence} |")
    lines += ["", "## Per stage", "", "| Stage | Met | Gap | n/a |", "| --- | --- | --- | --- |"]
    for stage in STAGES:
        counts = {kind: sum(1 for s in surfaces.values() if kind_of(s.get(stage, {})) == kind)
                  for kind in ("test", "gap", "na")}
        lines.append(f"| {stage} | {counts['test']} | {counts['gap']} | {counts['na']} |")
    lines.append("")
    return "\n".join(lines)


def compare(found: Dict[str, Any], baseline: Dict[str, Any],
            surfaces: Dict[str, Dict[str, Any]] = SURFACES,
            check_reference: bool = True) -> Tuple[bool, List[str], List[str]]:
    failures: List[str] = []
    notes: List[str] = []

    for name, surface in surfaces.items():
        if surface.get("mechanism") not in MECHANISMS:
            failures.append(f"{name}: mechanism {surface.get('mechanism')!r} is not one of {MECHANISMS}")
        for stage in STAGES:
            problem = cell_problem(surface.get(stage))
            if problem:
                failures.append(f"{name}.{stage} {problem}")

    required = required_pairs(found)
    declared = {(s["file"], s["mechanism"]) for s in surfaces.values()}
    for file, mechanism in sorted(required - declared):
        failures.append(f"{file} moves something with {mechanism} and no surface here counts what "
                        f"cancelling or undoing that move does")
    for name, surface in surfaces.items():
        if (surface["file"], surface["mechanism"]) not in required:
            failures.append(f"{name} is declared as {surface['mechanism']} in {surface['file']}, "
                            f"which the drag census no longer finds there")

    gaps = cells_of(surfaces, "gap")
    ceiling = baseline.get("gaps")
    recorded_gaps = set(baseline.get("gap_cells", []))
    recorded_na = set(baseline.get("na_cells", []))
    if ceiling is None:
        failures.append("the baseline records no gap count; re-run with --set-baseline")
    elif len(gaps) > ceiling:
        failures.append(f"{len(gaps)} gap(s), up from {ceiling}. A move that cannot be cancelled "
                        f"or taken back is the defect this counts.")
    elif len(gaps) < ceiling:
        notes.append(f"gaps {ceiling} -> {len(gaps)}; re-run with --set-baseline")
    for cell in gaps:
        if cell not in recorded_gaps:
            failures.append(f"{cell} is a gap the baseline does not hold -- a stage that was met, "
                            f"or a new surface, arriving with a gap")
    for cell in cells_of(surfaces, "na"):
        if cell not in recorded_na:
            failures.append(f"{cell} is newly declared not applicable. That is the cheapest way to "
                            f"lower this count -- a sentence instead of a behaviour and a test -- "
                            f"so it is an edit to the baseline made in the open, not here.")

    if check_reference:
        if not REFERENCE.exists():
            failures.append(f"{REFERENCE.relative_to(REPO_ROOT)} is missing; regenerate with --write")
        elif REFERENCE.read_text(encoding="utf-8") != render(surfaces):
            failures.append(f"{REFERENCE.relative_to(REPO_ROOT)} disagrees with the source. "
                            f"Regenerate it: python oms/audit_movement_contract.py --write")
    return not failures, failures, notes


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true", help="Regenerate the reference")
    parser.add_argument("--set-baseline", action="store_true")
    args = parser.parse_args()

    found = drag_scan()
    gaps, met, na = (cells_of(SURFACES, kind) for kind in ("gap", "test", "na"))
    print(f"{len(SURFACES)} movement surface(s): {len(met)} met, {len(gaps)} gap(s), {len(na)} n/a\n")
    for stage in STAGES:
        missing = [c.split(".")[0] for c in gaps if c.endswith(f".{stage}")]
        print(f"  {stage:<12} {len(missing):>2} gap(s)")

    if args.write:
        REFERENCE.write_text(render(), encoding="utf-8")
        print(f"\nWrote {REFERENCE.relative_to(REPO_ROOT)} ({len(gaps)} gaps).")
        return 0

    if args.set_baseline:
        BASELINE.write_text(json.dumps({
            "provenance": {"stale_after": "recomputed each run"},
            "note": ("Movement stages not met: cancel, recover, single-pointer alternative. A "
                     "ceiling, not a floor. A cell listed under na_cells was declared not "
                     "applicable on purpose; adding one is an edit someone makes here."),
            "gaps": len(gaps),
            "gap_cells": gaps,
            "na_cells": na,
        }, indent=2) + "\n", encoding="utf-8")
        print(f"\nBaseline set: {len(gaps)} gaps, {len(na)} not applicable.")
        return 0

    if not BASELINE.exists():
        print(f"\nNo baseline at {BASELINE.relative_to(REPO_ROOT)}. Record one with --set-baseline.")
        return 1

    ok, failures, notes = compare(found, json.loads(BASELINE.read_text(encoding="utf-8")))
    if notes:
        print(f"\n{len(notes)} change(s), none of them gated:")
        for note in notes:
            print(f"  {note}")
    if failures:
        print(f"\nFAIL -- {len(failures)}:")
        for failure in failures:
            print(f"  {failure}")
        return 1
    print(f"\nEvery drag is counted against the contract. {len(gaps)} gap(s) remain, and the count "
          f"may only fall.")
    return 0


if __name__ == "__main__":
    from enforcement_runs import recording

    raise SystemExit(recording("audit_movement_contract", main))

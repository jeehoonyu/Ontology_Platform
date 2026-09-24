"""Every control the original's graph editor offers, against the handler ours maps it to.

X1 of `GOAL_GRAPH_2026-09-23.md`. That goal read fifteen graph controls from the
original's public documentation -- the controls a person who has used it will reach
for on our pipeline canvas -- and set them beside `PipelineBuilder` and
`PipelineCanvas`. A table like that goes stale the day it is written: a handler is
renamed, a gap is closed and nobody updates the row, or a row claims a control that
has since been removed. So the table is this file, and the reference is generated.

Public documentation describes a capability; it does not prove the feature is
enabled in any enrollment. Nothing here is a parity claim. The two regions the
goal's table also lists -- the preview panel and the details sidebar -- are panes
ours already has, and are not controls on the graph, so they are not rows here.

**Each control names what ours maps it to, and a state:**

    handler                    an identifier in the named file that does all or part
                               of the job, or None where ours has nothing
    {"test": "spec::title"}    met: the named browser test operates it
    {"gap": "..."}             not met, and what is missing -- counted
    {"na": "..."}              deliberately not taken, with the reason

A control can name a handler and still be a gap: ours zooms with buttons and has no
key that fits, deletes one node and not a selection. The handler is what the gap is
measured from.

  - *Reported:* every control, its handler, its state; the count met.
  - *Gated:* a row naming a handler its file no longer has.
  - *Gated:* a met control naming no handler, or a test that does not exist.
  - *Gated:* the gap count rising, and a control that was met becoming a gap.
  - *Gated:* a control newly declared not taken -- a sentence instead of a feature,
    so it is an edit to the baseline made in the open, as `audit_movement_contract`
    holds its `na` cells.
  - *Gated:* the checked-in reference disagreeing with the source.

  python oms/audit_graph_editor.py            # judge
  python oms/audit_graph_editor.py --write    # regenerate the reference
  python oms/audit_graph_editor.py --set-baseline
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))

from audit_drag_affordances import proof_missing  # noqa: E402

FRONTEND_SRC = REPO_ROOT / "frontend" / "src"
REFERENCE = REPO_ROOT / "docs" / "GRAPH_EDITOR_PARITY.md"
BASELINE = REPO_ROOT / "docs" / "graph-editor-baseline.json"

BUILDER = "workspaces/PipelineBuilder.tsx"
CANVAS = "components/canvas/PipelineCanvas.tsx"
FILES = (BUILDER, CANVAS)

Control = Dict[str, Any]

# The fifteen rows of the goal's table, in its order. `original` is what the
# original's documentation describes; `ours` is what the pipeline canvas has.
CONTROLS: Dict[str, Control] = {
    "lasso": {
        "original": "Drag Select Mode; Shift+drag from panning mode lassos nodes",
        "ours": "a drag on bare canvas selects the nodes it closes over; Shift adds; Shift+click too",
        "file": BUILDER, "handler": "selectRegion",
        "state": {"test": "graph-editor.spec.ts::a lasso selects the nodes inside it and Escape "
                          "selects nothing"},
    },
    "select-all": {
        "original": "Select all nodes; Ctrl+A",
        "ours": "Select all, and Ctrl+A",
        "file": BUILDER, "handler": "selectAll",
        "state": {"test": "graph-editor.spec.ts::Select all, parents and children write the one "
                          "selection and send nothing"},
    },
    "select-family": {
        "original": "Ctrl+D selects children, Ctrl+E selects parents",
        "ours": "Select children and Select parents, one edge at a time; Ctrl+D and Ctrl+E",
        "file": BUILDER, "handler": "selectAlongEdges",
        "state": {"test": "graph-editor.spec.ts::Ctrl+A, Ctrl+E and Ctrl+D do what their buttons do"},
    },
    "remove-selected": {
        "original": "Remove the selected nodes",
        "ours": "Delete selected and the Delete key: every selected node and its edges, in one request",
        "file": BUILDER, "handler": "deleteSelected",
        "state": {"test": "graph-editor.spec.ts::Delete removes every selected node in one request"},
    },
    "layout": {
        "original": "Layout: evenly disperse and organise the graph; grid snapping",
        "ours": "Auto layout: a column per layer, one save and one Undo; no grid snapping",
        "file": BUILDER, "handler": "autoLayout",
        "state": {"test": "graph-editor.spec.ts::auto layout moves every node and one Undo restores "
                          "every position"},
    },
    "zoom-fit": {
        "original": "Zoom in, out and fit; Up Arrow fits",
        "ours": "Zoom in, Zoom out and Fit to view buttons; Up Arrow does what Fit to view does",
        "file": CANVAS, "handler": "onZoom",
        "state": {"gap": "Fit to view returns to one fixed zoom; it does not fit the graph to the canvas"},
    },
    "copy-paste": {
        "original": "Ctrl+C / Ctrl+V copy and paste nodes, across pipelines",
        "ours": "Copy and Paste, Ctrl+C and Ctrl+V: nodes and their edges, one batch, across pipelines",
        "file": BUILDER, "handler": "pasteNodes",
        "state": {"test": "graph-editor.spec.ts::three copied nodes paste into a second pipeline with "
                          "their edges"},
    },
    "hide": {
        "original": "Ctrl+H hides the selection, Ctrl+K shows every hidden node",
        "ours": "Hide selected and Ctrl+H, in this browser; Show all and Ctrl+Shift+H, since Ctrl+K is the command palette",
        "file": BUILDER, "handler": "hideSelection",
        "state": {"test": "graph-editor.spec.ts::two hidden nodes are counted, survive a reload here, and are "
                          "hidden nowhere on the server"},
    },
    "search": {
        "original": "Ctrl+F opens Search pipeline",
        "ours": "Search pipeline and Ctrl+F: matches by name, id or type are selected",
        "file": BUILDER, "handler": "searchNodes",
        "state": {"test": "graph-editor.spec.ts::a search selects what matches, and a tool used after "
                          "it takes that"},
    },
    "organise": {
        "original": "Legend and colour groups; folders; text nodes",
        "ours": "a legend of the four node categories",
        "file": CANVAS, "handler": None,
        "state": {"na": "deliberately not taken: organisation for a large graph, and the "
                        "bootstrap pipeline has under ten nodes (GOAL_GRAPH, what is not taken)"},
    },
    "connect": {
        "original": "Drag an output circle to an input circle to connect",
        "ours": "drag a node's output port onto another's input port, or Connect two selected nodes",
        "file": BUILDER, "handler": "connectNodes",
        "state": {"test": "graph-editor.spec.ts::dragging an output port onto an input port inserts one "
                          "edge and one Undo removes it"},
    },
    "context-menu": {
        "original": "Right-click a node: Copy, Paste, Open",
        "ours": "a menu under the node selected by a click, with inserts and Delete",
        "file": CANVAS, "handler": "onContextInsert",
        "state": {"gap": "no right-click menu"},
    },
    "undo-redo": {
        "original": "Undo and Redo in the top toolbar",
        "ours": "Undo, one step: a move of any number of nodes, a layout or a paste",
        "file": BUILDER, "handler": "undoLast",
        "state": {"gap": "no redo, and a single add or a delete is not undone"},
    },
    "save-state": {
        "original": "Explicit Save, a filled Saved state, View changes for unsaved work",
        "ours": "positions save on drop; node configuration is held in drafts",
        "file": BUILDER, "handler": "moveNodes",
        "state": {"gap": "nothing says whether there is unsaved work"},
    },
    "hotkeys": {
        "original": "Help, View hotkeys",
        "ours": "View hotkeys, rendered from the table the listener reads; each key names its button",
        "file": BUILDER, "handler": "showHotkeys",
        "state": {"test": "graph-editor.spec.ts::the hotkeys reference lists the table, and each key "
                          "does what its button does"},
    },
}

KINDS = ("test", "gap", "na")


def kind_of(cell: Any) -> str:
    return next(iter(cell)) if isinstance(cell, dict) and len(cell) == 1 else ""


def definition_of(handler: str) -> str:
    """A function, a `const` bound to one, or a component prop typed as one.

    A name that is only called or passed along is not a definition. Matching any
    mention let a renamed function pass while its callers still said the old name,
    which is a build that does not compile and a row that says all is well.
    """
    name = re.escape(handler)
    return rf"\bfunction\s+{name}\s*\(|\b(?:const|let)\s+{name}\s*=|\b{name}\??\s*:\s*\("


def handler_missing(control: Control) -> str:
    """Empty when the control names no handler, or its file still defines it."""
    handler = control.get("handler")
    if not handler:
        return ""
    if control.get("file") not in FILES:
        return f"names {control.get('file')}, which this audit does not scan"
    path = FRONTEND_SRC / control["file"]
    if not path.exists():
        return f"names {control['file']}, which does not exist"
    if not re.search(definition_of(handler), path.read_text(encoding="utf-8")):
        return f"names `{handler}`, which {control['file']} no longer defines"
    return ""


def state_problem(control: Control) -> str:
    """Empty when the state is well formed and, if met, proven and mapped."""
    cell = control.get("state")
    kind = kind_of(cell)
    if kind not in KINDS:
        return "state must be exactly one of test, gap or na"
    value = cell[kind]
    if not isinstance(value, str) or not value.strip():
        return f"is `{kind}` with nothing said"
    if kind == "test":
        if not control.get("handler"):
            return "is met and names no handler that does it"
        return proof_missing({"proven_by": value})
    return ""


def controls_of(controls: Dict[str, Control], kind: str) -> List[str]:
    return sorted(name for name, control in controls.items() if kind_of(control.get("state")) == kind)


def render(controls: Dict[str, Control] = CONTROLS) -> str:
    met, gaps, na = (controls_of(controls, kind) for kind in ("test", "gap", "na"))
    partial = [name for name in gaps if controls[name].get("handler")]
    lines = [
        "# The original's graph controls, against the pipeline canvas",
        "",
        "Generated by `oms/audit_graph_editor.py`. Do not edit by hand — the gate",
        "regenerates this and fails if it disagrees with the source.",
        "",
        f"**{len(met)} of {len(controls)}** controls met, each operated by a named browser test. "
        f"{len(gaps)} gaps, {len(partial)} of them with a handler that does part of the job; "
        f"{len(na)} not taken, with the reason.",
        "",
        "The controls were read from the original's public documentation "
        "(`GOAL_GRAPH_2026-09-23.md`). Documentation describes a capability and proves "
        "nothing about any enrollment, so this is not a parity claim: it is a list of what a "
        "person who has used the original will reach for here, and what happens when they do.",
        "",
        "| Control | The original | Ours | Handler | State | Evidence |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    labels = {"test": "met", "gap": "**gap**", "na": "not taken"}
    for name, control in controls.items():
        cell = control.get("state", {})
        kind = kind_of(cell)
        evidence = cell.get(kind, "") if kind else ""
        if kind == "test":
            evidence = f"`{evidence.replace('::', '` — ')}"
        handler = f"`{control['handler']}` in `{control['file']}`" if control.get("handler") else "—"
        lines.append(f"| `{name}` | {control['original']} | {control['ours']} | {handler} "
                     f"| {labels.get(kind, '**malformed**')} | {evidence} |")
    lines.append("")
    return "\n".join(lines)


def compare(baseline: Dict[str, Any], controls: Dict[str, Control] = CONTROLS,
            check_reference: bool = True) -> Tuple[bool, List[str], List[str]]:
    failures: List[str] = []
    notes: List[str] = []

    for name, control in controls.items():
        for problem in (state_problem(control), handler_missing(control)):
            if problem:
                failures.append(f"{name} {problem}")

    gaps = controls_of(controls, "gap")
    ceiling = baseline.get("gaps")
    recorded_gaps = set(baseline.get("gap_controls", []))
    recorded_na = set(baseline.get("na_controls", []))
    if ceiling is None:
        failures.append("the baseline records no gap count; re-run with --set-baseline")
    elif len(gaps) > ceiling:
        failures.append(f"{len(gaps)} gap(s), up from {ceiling}. A control the original offers "
                        f"that ours stopped offering is the defect this counts.")
    elif len(gaps) < ceiling:
        notes.append(f"gaps {ceiling} -> {len(gaps)}; re-run with --set-baseline")
    for name in gaps:
        if name not in recorded_gaps:
            failures.append(f"{name} is a gap the baseline does not hold -- a control that was met, "
                            f"or a new row, arriving as a gap")
    for name in controls_of(controls, "na"):
        if name not in recorded_na:
            failures.append(f"{name} is newly declared not taken. A sentence instead of a feature "
                            f"is the cheapest way to lower this count, so it is an edit to the "
                            f"baseline made in the open, not here.")

    if check_reference:
        if not REFERENCE.exists():
            failures.append(f"{REFERENCE.relative_to(REPO_ROOT)} is missing; regenerate with --write")
        elif REFERENCE.read_text(encoding="utf-8") != render(controls):
            failures.append(f"{REFERENCE.relative_to(REPO_ROOT)} disagrees with the source. "
                            f"Regenerate it: python oms/audit_graph_editor.py --write")
    return not failures, failures, notes


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true", help="Regenerate the reference")
    parser.add_argument("--set-baseline", action="store_true")
    args = parser.parse_args()

    met, gaps, na = (controls_of(CONTROLS, kind) for kind in ("test", "gap", "na"))
    partial = [name for name in gaps if CONTROLS[name].get("handler")]
    print(f"{len(met)} of {len(CONTROLS)} graph controls met; {len(gaps)} gap(s), "
          f"{len(partial)} of them with a handler that does part of the job; {len(na)} not taken")

    if args.write:
        REFERENCE.write_text(render(), encoding="utf-8")
        print(f"\nWrote {REFERENCE.relative_to(REPO_ROOT)} ({len(met)} of {len(CONTROLS)} met).")
        return 0

    if args.set_baseline:
        BASELINE.write_text(json.dumps({
            "provenance": {"stale_after": "recomputed each run"},
            "note": ("Graph controls the original offers that the pipeline canvas does not. A "
                     "ceiling, not a floor. A control under na_controls was declared not taken "
                     "on purpose; adding one is an edit someone makes here."),
            "gaps": len(gaps),
            "met": len(met),
            "gap_controls": gaps,
            "na_controls": na,
        }, indent=2) + "\n", encoding="utf-8")
        print(f"\nBaseline set: {len(gaps)} gaps, {len(met)} met, {len(na)} not taken.")
        return 0

    if not BASELINE.exists():
        print(f"\nNo baseline at {BASELINE.relative_to(REPO_ROOT)}. Record one with --set-baseline.")
        return 1

    ok, failures, notes = compare(json.loads(BASELINE.read_text(encoding="utf-8")))
    if notes:
        print(f"\n{len(notes)} change(s), none of them gated:")
        for note in notes:
            print(f"  {note}")
    if failures:
        print(f"\nFAIL -- {len(failures)}:")
        for failure in failures:
            print(f"  {failure}")
        return 1
    print(f"\nEvery row names a handler its file still has. {len(met)} of {len(CONTROLS)} met, "
          f"and the gap count may only fall.")
    return 0


if __name__ == "__main__":
    from enforcement_runs import recording
    raise SystemExit(recording("audit_graph_editor", main))

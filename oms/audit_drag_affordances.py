"""One drag mechanism, configured once, and nothing may leave through the gaps.

The question that produced this was whether React would suit a complicated
drag-and-drop UI. React was never the variable -- it has been the product all
along, and a browser fires `dragstart` the same way whatever renders the element.
The variable is the mechanism, and the interface had **four** of them:

    html5     4 sources   native `draggable` + `dataTransfer`
    pointer   1 canvas    `onPointerDown` with `setPointerCapture`, hand-rolled
    dnd-kit   1 source    `useSortable`
    xyflow    3 canvases  the node graph, which handles its own pointers

The first two are now gone. Every drag outside the xyflow canvases runs through
`components/dnd/DragKit`, and the reason is not tidiness:

  - **Native HTML5 drag-and-drop cannot be reached from a keyboard or from touch
    at all.** That is a property of the platform. Each of those four sites needed
    a second control beside it doing the same job; the controls are good and they
    stayed, but the drag itself was a mouse-only feature in every one of them.
  - **The hand-rolled pointer drag was worse, because nothing counted it.** The
    first version of this audit reported three mechanisms and there were four:
    pipeline nodes were positioned by `onPointerDown` and `setPointerCapture`,
    which is neither a `draggable` attribute nor a sensor library, so it matched
    no pattern here. It worked from touch. It could not be reached from a
    keyboard, and a node's position had no other control at all -- so the layout
    of a pipeline was, quietly, mouse-and-finger only. A census that reports a
    number it did not measure is worse than no census.

So the shape of the gate changed with the migration. It no longer asks each drag
to declare an escape hatch; it refuses drags that are not on the one mechanism:

  - *Gated:* a native HTML5 drag -- `onDragStart` or an `onDrop` target.
  - *Gated:* a hand-rolled pointer drag -- `setPointerCapture`, or `onPointerMove`
    wired in JSX. This is the rule that would have caught what the first census
    missed, and it is here because it did.
  - *Gated:* a `DndContext` that does not take `useWorkspaceSensors`. The shared
    sensors carry an 8px activation distance, which is what stops a click on a
    palette entry reading as a zero-length drag; a context configured by hand
    loses that and silently breaks the non-drag control beside it.
  - *Gated:* a file holding a dnd-kit drag with no entry in `SENSOR_BACKED`, or
    an entry naming a browser test that no longer exists. A sensor library
    supporting touch is a claim about the library: `.drag-grip` had no
    `touch-action: none` and could not be dragged by a finger at all while
    `@dnd-kit` "supported touch" the whole time.
  - *Reported:* the census, and what each file drags.

The xyflow canvases are left alone. They are a third-party graph editor handling
its own pointers, and replacing that is not a drag-mechanism question.

  python oms/audit_drag_affordances.py            # judge
  python oms/audit_drag_affordances.py --write    # regenerate the reference
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))

FRONTEND_SRC = REPO_ROOT / "frontend" / "src"
SPECS = REPO_ROOT / "frontend" / "tests"
REFERENCE = REPO_ROOT / "docs" / "DRAG_AFFORDANCES.md"
KIT = "components/dnd/DragKit.tsx"

# Native drag, in both directions.
_HTML5 = re.compile(r"onDragStart=|onDrop=\{|onDragOver=\{")
# A drag written by hand on raw pointer or mouse events.
#
# The first version of this rule was `setPointerCapture(|onPointerMove={` -- which
# is to say, exactly the two lines the migration had just deleted. It would have
# caught the drag that was already gone and nothing else. A review of the
# migration found two ordinary ways to reintroduce the class without tripping it:
# `useEffect` with `window.addEventListener("pointermove", ...)`, which is the
# standard way to hand-roll a drag that survives the pointer leaving the element
# and needs no capture at all, and the older `onMouseDown`/`onMouseMove` pair.
# Neither matches any other rule here either -- no dnd-kit hook means no
# `SENSOR_BACKED` entry is owed and the file is invisible to the whole audit --
# so the census would have printed "0 hand-rolled" over a live one. That is the
# failure this file names as its reason for existing, one level up.
#
# `onMouseDown=` alone is deliberately absent: three modal backdrops use it to
# close on an outside press, and those are not drags.
_POINTER = re.compile(
    r"setPointerCapture\(|onPointerMove=\{|onMouseMove=\{"
    r"""|addEventListener\(\s*['"](?:pointer|mouse)move""")
# A context, and whether it takes the shared sensors.
_CONTEXT = re.compile(r"<DndContext([^>]*)>", re.S)
_KIT_HOOK = re.compile(r"\buseWorkspaceSensors\s*\(")
_DND_HOOK = re.compile(r"\buse(?:Sortable|Draggable|Droppable)\s*\(")
_FLOW = re.compile(r"<ReactFlow\b")
# What each draggable carries, so the reference names something a reader can find.
_ID = re.compile(r'use(?:Draggable|Droppable)\(\{\s*id:\s*[`"]([^`"$]*)')

# Every file that drags, what it drags, and the browser test that operates it
# without a mouse. `proven_by` names a spec and a test title; the gate checks the
# spec still contains the title, so renaming a test away from its claim fails
# here rather than quietly stopping proving it.
SENSOR_BACKED: Dict[str, Dict[str, str]] = {
    "components/canvas/PipelineCanvas.tsx": {
        "moves": "a node around the pipeline canvas, and receives palette drops",
        "reachable": "the node's position had no non-drag control at all and now moves "
                     "from the keyboard; the canvas offers `Add <type>` when it is empty",
        "proven_by": "drag-affordances.spec.ts::a pipeline node moves with the keyboard",
    },
    "workspaces/OntologyManager.tsx": {
        "moves": "a source dataset field onto a property, and a property row up or down",
        "reachable": "the `Map <property>` select beside every target, and `Up` and `Down` "
                     "on every row; both grips are keyboard-operable buttons",
        "proven_by": "drag-affordances.spec.ts::a property row reorders without a drag",
    },
    "workspaces/PipelineBuilder.tsx": {
        "moves": "a node type from the palette onto the canvas",
        "reachable": "tapping the palette entry arms the type, and the empty canvas offers "
                     "`Add <type>`; once nodes exist the edge insert control does it",
        "proven_by": "touch-authoring.spec.ts::a touch user can add the first node to a pipeline",
    },
    "workspaces/VisualBuilder.tsx": {
        "moves": "a node type from the library onto the artifact canvas, and a configuration "
                 "field up or down in the inspector",
        "reachable": "the library entry is a button that places the node on tap; the field "
                     "grip is reachable by touch and by keyboard",
        "proven_by": "drag-affordances.spec.ts::a library node reaches the canvas without a drag",
    },
}


def scan() -> Dict[str, Any]:
    """Every drag in the source, by mechanism."""
    html5: List[str] = []
    pointer: List[str] = []
    unshared: List[str] = []
    dnd_kit: Dict[str, List[str]] = {}
    xyflow: List[str] = []

    for path in sorted(FRONTEND_SRC.rglob("*.tsx")):
        label = str(path.relative_to(FRONTEND_SRC)).replace("\\", "/")
        text = path.read_text(encoding="utf-8")
        # A line that only talks about a mechanism is not one. Comments carry the
        # history of what was removed, and the history must not fail the gate.
        code = "\n".join(line for line in text.split("\n")
                         if not line.lstrip().startswith(("*", "//", "/*")))
        # `<DndContext onDragStart=...>` is dnd-kit's prop, not the DOM attribute
        # of the same name. Strip the context tags before looking for native drag,
        # or the migration flags itself.
        without_contexts = _CONTEXT.sub("", code)
        if _HTML5.search(without_contexts):
            html5.append(label)
        if _POINTER.search(code):
            pointer.append(label)
        for attributes in _CONTEXT.findall(code):  # noqa: E501 -- read before stripping
            if "sensors=" not in attributes:
                unshared.append(label)
        if label != KIT and _DND_HOOK.search(code):
            dnd_kit[label] = sorted(set(_ID.findall(code)))
        if _FLOW.search(code):
            xyflow.append(label)

    kit = (FRONTEND_SRC / KIT).exists()
    return {"html5": sorted(html5), "pointer": sorted(pointer),
            "unshared_context": sorted(set(unshared)), "dnd-kit": dnd_kit,
            "xyflow": sorted(xyflow), "kit": kit}


def proof_missing(declaration: Dict[str, str]) -> str:
    """Empty when the named browser test exists and still carries that title."""
    reference = declaration.get("proven_by", "")
    if "::" not in reference:
        return "names no browser test"
    spec_name, title = reference.split("::", 1)
    spec = SPECS / spec_name
    if not spec.exists():
        return f"names {spec_name}, which does not exist"
    if title not in spec.read_text(encoding="utf-8"):
        return f"names a test titled {title!r} that {spec_name} no longer contains"
    return ""


def render(found: Dict[str, Any]) -> str:
    lines = [
        "# Every drag, on one mechanism",
        "",
        "Generated by `oms/audit_drag_affordances.py`. Do not edit by hand — the gate",
        "regenerates this and fails if it disagrees with the source.",
        "",
        "Native HTML5 drag-and-drop cannot be reached from a keyboard or from touch. A",
        "hand-rolled pointer drag can be reached from touch and not from a keyboard, and",
        "is counted by nothing, which is how one of them sat in the pipeline canvas while",
        "a census reported three mechanisms. Everything below runs through",
        "`components/dnd/DragKit`, whose sensors are configured once.",
        "",
        "| File | Drags | Reachable without a mouse | Proven by |",
        "| --- | --- | --- | --- |",
    ]
    for file in sorted(found["dnd-kit"]):
        declared = SENSOR_BACKED.get(file, {})
        lines.append(f"| `{file}` | {declared.get('moves', '**undeclared**')} "
                     f"| {declared.get('reachable', '—')} "
                     f"| {declared.get('proven_by', '**unproven**').split('::')[-1]} |")
    lines += [
        "",
        "## What each file registers",
        "",
        "| File | Draggable and droppable ids |",
        "| --- | --- |",
    ]
    for file, ids in sorted(found["dnd-kit"].items()):
        lines.append(f"| `{file}` | {', '.join(f'`{i}`' for i in ids) or '—'} |")
    lines += [
        "",
        "## Mechanisms in use",
        "",
        "| Mechanism | Files | Keyboard | Touch |",
        "| --- | --- | --- | --- |",
        f"| native HTML5 | **{len(found['html5'])}** | never | never |",
        f"| hand-rolled pointer | **{len(found['pointer'])}** | never | yes |",
        f"| `@dnd-kit` via `DragKit` | {len(found['dnd-kit'])} | yes | grips only, by design |",
        f"| `@xyflow/react` | {len(found['xyflow'])} | pane only | yes |",
        "",
        "A finger on a palette or a long list is scrolling. The shared sensors take no",
        "touch gesture except on an explicit grip, which is 22px wide and scrolls nothing;",
        "touch reaches the rest through the control beside the drag.",
        "",
    ]
    return "\n".join(lines)


def compare(found: Dict[str, Any]) -> Tuple[bool, List[str], List[str]]:
    failures: List[str] = []
    notes: List[str] = []

    if not found["kit"]:
        failures.append(f"{KIT} is gone; there is no shared mechanism left to be on")

    for file in found["html5"]:
        failures.append(
            f"{file} starts or receives a native HTML5 drag. It cannot be operated from a "
            f"keyboard or from touch, whatever is done in the handler. Use `useDraggable` "
            f"and `useDroppable` with `useWorkspaceSensors` from {KIT}.")
    for file in found["pointer"]:
        failures.append(
            f"{file} drags on raw pointer events. This is the mechanism the first census "
            f"missed entirely -- it is neither a `draggable` attribute nor a sensor "
            f"library, so nothing counted it, and pipeline node layout was mouse-and-finger "
            f"only for as long as it existed. Use {KIT}.")
    for file in found["unshared_context"]:
        failures.append(
            f"{file} builds a DndContext without `sensors`. The shared sensors carry an 8px "
            f"activation distance; without it a click on a draggable button reads as a "
            f"zero-length drag and the non-drag control beside it stops working.")

    for file, ids in sorted(found["dnd-kit"].items()):
        declaration = SENSOR_BACKED.get(file)
        if declaration is None:
            failures.append(
                f"{file} drags ({', '.join(ids) or 'no registered id'}) and nothing says how "
                f"it is reached without a mouse or which browser test operates it. A sensor "
                f"library supporting touch is a claim about the library.")
            continue
        gap = proof_missing(declaration)
        if gap:
            failures.append(f"{file} is declared and {gap}.")
    for file in sorted(SENSOR_BACKED):
        if file not in found["dnd-kit"]:
            failures.append(f"{file} is declared as dragging and no longer does")

    if not REFERENCE.exists():
        failures.append(f"{REFERENCE.relative_to(REPO_ROOT)} is missing; regenerate with --write")
    elif REFERENCE.read_text(encoding="utf-8") != render(found):
        failures.append(f"{REFERENCE.relative_to(REPO_ROOT)} disagrees with the source. "
                        f"Regenerate it: python oms/audit_drag_affordances.py --write")

    notes.append(f"{len(found['dnd-kit'])} file(s) drag through {KIT}; "
                 f"{len(found['xyflow'])} xyflow canvas(es) handle their own pointers")
    return not failures, failures, notes


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true", help="Regenerate the reference")
    args = parser.parse_args()

    if not FRONTEND_SRC.exists():
        print(f"No frontend source at {FRONTEND_SRC}")
        return 1

    found = scan()
    print(f"{len(found['html5'])} native HTML5, {len(found['pointer'])} hand-rolled pointer, "
          f"{len(found['dnd-kit'])} through DragKit, {len(found['xyflow'])} xyflow\n")
    for file, ids in sorted(found["dnd-kit"].items()):
        declared = SENSOR_BACKED.get(file)
        mark = "ok " if declared and not proof_missing(declared) else "-- "
        print(f"  {mark}{file}  ({len(ids)} id(s))")

    if args.write:
        REFERENCE.write_text(render(found), encoding="utf-8")
        print(f"\nWrote {REFERENCE.relative_to(REPO_ROOT)}.")
        return 0

    ok, failures, notes = compare(found)
    for note in notes:
        print(f"\n  {note}")
    if failures:
        print(f"\nFAIL -- {len(failures)}:")
        for failure in failures:
            print(f"  {failure}")
        return 1
    print(f"\nEvery drag runs on the shared mechanism, and a browser test operates each one "
          f"without a mouse.")
    return 0


if __name__ == "__main__":
    from enforcement_runs import recording

    raise SystemExit(recording("audit_drag_affordances", main))

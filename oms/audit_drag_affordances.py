"""Every drag in the interface, and the control that does the same thing without one.

The question that produced this was whether React would be better for a
complicated drag-and-drop UI. React is already the product, so the framework is
not the variable. The variable is *which drag mechanism*, and this interface has
three of them running at once:

    html5     4 sources   native `draggable` + `dataTransfer`
    dnd-kit   1 source    `useSortable`, pointer and keyboard sensors
    xyflow    3 canvases  the node graph, which handles its own pointers

**Native HTML5 drag-and-drop does not fire from touch input at all**, and it is
not operable from the keyboard. That is a fact about the platform, not a
preference between libraries: a finger on `<button draggable>` scrolls the page,
and no amount of care in the handler changes it. `touch-authoring.spec.ts`
measured exactly this on the pipeline builder -- palette and canvas both visible,
and neither a tap nor a touch-drag produced a node.

The obvious conclusion, that the library-backed drag is therefore the safe one,
was wrong, and measuring is what showed it. `@dnd-kit`'s pointer sensor does
support touch; the one place this product uses it did not, because `.drag-grip`
carried no `touch-action: none` and the browser claimed every gesture for
scrolling before the sensor saw a move. A finger could not reorder a
configuration field at all. The fix was one CSS line. **A library supporting
touch and a screen working from a finger are different claims**, and only the
second is worth anything.

So the rule is not "stop using HTML5 drag". A mouse user dragging a field onto a
property is a good interaction and worth keeping. The rule is that **the drag may
not be the only way**, and the alternative may not be a claim:

  - *Gated:* an HTML5 drag source with no entry in `NON_DRAG_PATHS`. A new
    `draggable` is exactly when a screen becomes touch-only by accident, because
    the author is at a desk with a mouse and the drag works.
  - *Gated:* a declaration whose site is gone, so the list cannot rot into
    describing drags that no longer exist.
  - *Gated:* a sensor-backed drag with no entry in `SENSOR_BACKED`. Same rule,
    different shape: no alternative control is owed, but a touch drag in a
    browser is.
  - *Gated:* a declaration naming a browser test that does not exist, or a test
    title that spec no longer contains. An alternative nobody operated is an
    assertion; these are operated by a finger, on a touch viewport, in Chrome.
  - *Reported:* the mechanism census, and who uses which.

Migrating the four onto `@dnd-kit` would remove the whole native class. That is a
real option and this does not take it, for two reasons. A drag that cannot be
reached is a worse defect than a drag implemented twice, and this rule fixes the
first without betting the authoring screens on a rewrite. And the one place
already on `@dnd-kit` was the one place a finger could not use *at all* -- so
"move everything onto the library" would have spread a defect while looking like
a cleanup. What makes a drag reachable is the measurement, not the dependency.

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

_HANDLER = re.compile(r"onDragStart=")
_DROP_TARGET = re.compile(r"onDrop=\{")
_MIME = re.compile(r'setData\(\s*"([^"]+)"')
_SETTER = re.compile(r"\b(set[A-Z][A-Za-z0-9]*)\s*\(")
_SORTABLE = re.compile(r"\buse(?:Sortable|Draggable)\s*\(")
_FLOW = re.compile(r"<ReactFlow\b")

# Every HTML5 drag source, what it moves, and the control that does the same
# thing without a drag. `proven_by` names a browser test that operates that
# control with a finger; the gate checks the spec still contains the title, so a
# renamed or deleted test fails here rather than quietly stopping proving it.
NON_DRAG_PATHS: Dict[str, Dict[str, str]] = {
    "workspaces/OntologyManager.tsx::setDraggedField": {
        "moves": "a source dataset field onto an ontology property, to map one to the other",
        "without_drag": "the `Map <property>` select beside every target property, which "
                        "lists the same source fields",
        "proven_by": "drag-affordances.spec.ts::a source field maps onto a property "
                     "without a drag",
    },
    "workspaces/OntologyManager.tsx::setDragName": {
        "moves": "a property row above or below its neighbours, to reorder the schema",
        "without_drag": "the `Up` and `Down` buttons on every row",
        "proven_by": "drag-affordances.spec.ts::a property row reorders without a drag",
    },
    "workspaces/PipelineBuilder.tsx::application/x-node-type": {
        "moves": "a node type from the palette onto the pipeline canvas",
        "without_drag": "tapping the palette entry arms the type, and the empty canvas "
                        "offers `Add <type>`; once nodes exist, the edge insert control does it",
        "proven_by": "touch-authoring.spec.ts::a touch user can add the first node to a pipeline",
    },
    "workspaces/VisualBuilder.tsx::application/ontology-builder-node": {
        "moves": "a node type from the library onto the artifact canvas",
        "without_drag": "the library entry is a button; tapping it calls `addNode` and places "
                        "the node without any pointer travel",
        "proven_by": "drag-affordances.spec.ts::a library node reaches the canvas without a drag",
    },
}

# The library-backed drags. These need no alternative control, because the sensor
# is supposed to handle touch itself -- but "the library supports touch" and "this
# screen works from a finger" are different claims, and the first was true here
# while the second was false. `.drag-grip` carried no `touch-action: none`, so
# the browser spent every gesture on scrolling before the pointer sensor saw a
# move. The fix was one CSS line; finding it took a measurement. So the rule for
# these is the same rule in a different shape: a browser test drags them with a
# real touch point, or the claim does not stand.
SENSOR_BACKED: Dict[str, Dict[str, str]] = {
    "workspaces/VisualBuilder.tsx": {
        "moves": "a configuration field above or below its neighbours in the node inspector",
        "sensor": "@dnd-kit `useSortable`, pointer and keyboard sensors",
        "proven_by": "drag-affordances.spec.ts::the sortable field list reorders from touch",
    },
}


def _body(text: str, start: int) -> str:
    """The `{...}` immediately after an attribute, brace-balanced."""
    opening = text.find("{", start)
    if opening < 0:
        return ""
    depth = 0
    for index in range(opening, min(len(text), opening + 4000)):
        if text[index] == "{":
            depth += 1
        elif text[index] == "}":
            depth -= 1
            if depth == 0:
                return text[opening:index + 1]
    return text[opening:opening + 4000]


def _key_for(body: str) -> str:
    """A name for this drag source that survives the line moving.

    The payload a drag carries is the stable thing about it: a MIME type it puts
    on `dataTransfer`, or the state setter it calls when there is no
    `dataTransfer`. Line numbers are not stable and the surrounding markup is
    reformatted by ordinary work.
    """
    mime = _MIME.search(body)
    if mime:
        return mime.group(1)
    setter = _SETTER.search(body)
    if setter:
        return setter.group(1)
    return "unnamed"


def scan() -> Dict[str, Any]:
    """Drag sources by mechanism, keyed so a declaration can name one."""
    html5: Dict[str, Dict[str, Any]] = {}
    dnd_kit: List[str] = []
    xyflow: List[str] = []
    drop_targets: List[str] = []

    for path in sorted(FRONTEND_SRC.rglob("*.tsx")):
        text = path.read_text(encoding="utf-8")
        label = str(path.relative_to(FRONTEND_SRC)).replace("\\", "/")
        for match in _HANDLER.finditer(text):
            body = _body(text, match.end())
            key = f"{label}::{_key_for(body)}"
            html5[key] = {
                "file": label,
                "line": text.count("\n", 0, match.start()) + 1,
                "carries": _key_for(body),
            }
        if _SORTABLE.search(text):
            dnd_kit.append(label)
        if _FLOW.search(text):
            xyflow.append(label)
        if _DROP_TARGET.search(text):
            drop_targets.append(label)

    return {"html5": html5, "dnd-kit": sorted(dnd_kit), "xyflow": sorted(xyflow),
            "drop_targets": sorted(drop_targets)}


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
        "# Drag interactions, and how to do them without dragging",
        "",
        "Generated by `oms/audit_drag_affordances.py`. Do not edit by hand — the gate",
        "regenerates this and fails if it disagrees with the source.",
        "",
        "Native HTML5 drag-and-drop does not fire from touch input and is not operable",
        "from the keyboard. That is a property of the platform, not of this code. Every",
        "HTML5 drag below therefore carries a second control that does the same thing,",
        "and a browser test that operates that control with a finger.",
        "",
        "| Drag | Moves | Without a drag | Proven by |",
        "| --- | --- | --- | --- |",
    ]
    for key in sorted(found["html5"]):
        entry = found["html5"][key]
        declared = NON_DRAG_PATHS.get(key, {})
        proof = declared.get("proven_by", "—").split("::")[-1]
        lines.append(f"| `{entry['file']}` — {entry['carries']} | {declared.get('moves', '—')} "
                     f"| {declared.get('without_drag', '**undeclared**')} | {proof} |")
    lines += [
        "",
        "## Drags a sensor library carries",
        "",
        "No alternative control, because the sensor is meant to handle touch itself. That is a",
        "claim about the library, and it was true here while the screen was still unusable: the",
        "grip carried no `touch-action: none`, so the browser spent every gesture on scrolling",
        "before the pointer sensor saw a move. Each one below is dragged by a real touch point",
        "in a browser test.",
        "",
        "| File | Moves | Sensor | Proven by |",
        "| --- | --- | --- | --- |",
    ]
    for file in sorted(found["dnd-kit"]):
        declared = SENSOR_BACKED.get(file, {})
        lines.append(f"| `{file}` | {declared.get('moves', '—')} | {declared.get('sensor', '—')} "
                     f"| {declared.get('proven_by', '**unproven**').split('::')[-1]} |")
    lines += [
        "",
        "## Mechanisms in use",
        "",
        "| Mechanism | Where | Reachable without a mouse |",
        "| --- | --- | --- |",
        f"| native HTML5 | {len(found['html5'])} sources in "
        f"{len({e['file'] for e in found['html5'].values()})} files "
        f"| never — by a second control only |",
        f"| `@dnd-kit` | {', '.join('`' + f + '`' for f in found['dnd-kit']) or '—'} "
        f"| yes, measured by touch |",
        f"| `@xyflow/react` | {', '.join('`' + f + '`' for f in found['xyflow']) or '—'} "
        f"| pan and zoom, not node placement |",
        "",
        "Drop targets: "
        + (", ".join(f"`{f}`" for f in found["drop_targets"]) or "—")
        + ".",
        "",
    ]
    return "\n".join(lines)


def compare(found: Dict[str, Any]) -> Tuple[bool, List[str], List[str]]:
    failures: List[str] = []
    notes: List[str] = []
    html5 = found["html5"]

    for key in sorted(html5):
        if key not in NON_DRAG_PATHS:
            entry = html5[key]
            failures.append(
                f"{entry['file']}:{entry['line']} starts an HTML5 drag carrying "
                f"{entry['carries']!r} and nothing declares how to do it without dragging. "
                f"Native drag does not fire from touch and is not keyboard-operable, so "
                f"this control is unreachable for anyone not holding a mouse. Add the "
                f"alternative, then declare it in NON_DRAG_PATHS with the test that "
                f"operates it.")
            continue
        gap = proof_missing(NON_DRAG_PATHS[key])
        if gap:
            failures.append(f"{key} declares a non-drag path and {gap}. An alternative "
                            f"nobody operated is an assertion.")

    for key in sorted(NON_DRAG_PATHS):
        if key not in html5:
            failures.append(
                f"{key} is declared and no longer exists in the source. Either the drag was "
                f"removed -- delete the declaration -- or its payload was renamed, in which "
                f"case the alternative deserves a second look.")

    for file in found["dnd-kit"]:
        declaration = SENSOR_BACKED.get(file)
        if declaration is None:
            failures.append(
                f"{file} drags with a sensor library and nothing proves it works from a "
                f"finger. The sensor supporting touch is a claim about the library; a grip "
                f"with no `touch-action: none` loses every gesture to scrolling, which is "
                f"what this file did until it was measured. Add a touch test and declare it "
                f"in SENSOR_BACKED.")
            continue
        gap = proof_missing(declaration)
        if gap:
            failures.append(f"{file} is declared sensor-backed and {gap}.")
    for file in sorted(SENSOR_BACKED):
        if file not in found["dnd-kit"]:
            failures.append(f"{file} is declared sensor-backed and no longer uses one")

    notes.append(f"{len(html5)} drag(s) need an alternative control because the platform gives "
                 f"them none; {len(found['dnd-kit'])} carry sensors and are proven by touch")
    if not REFERENCE.exists():
        failures.append(f"{REFERENCE.relative_to(REPO_ROOT)} is missing; regenerate with --write")
    elif REFERENCE.read_text(encoding="utf-8") != render(found):
        failures.append(f"{REFERENCE.relative_to(REPO_ROOT)} disagrees with the source. "
                        f"Regenerate it: python oms/audit_drag_affordances.py --write")
    return not failures, failures, notes


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true", help="Regenerate the reference")
    args = parser.parse_args()

    if not FRONTEND_SRC.exists():
        print(f"No frontend source at {FRONTEND_SRC}")
        return 1

    found = scan()
    html5 = found["html5"]
    print(f"{len(html5)} native HTML5 drag source(s), {len(found['dnd-kit'])} @dnd-kit, "
          f"{len(found['xyflow'])} @xyflow canvas(es)\n")
    for key in sorted(html5):
        declared = NON_DRAG_PATHS.get(key)
        mark = "ok " if declared and not proof_missing(declared) else "-- "
        print(f"  {mark}{key}  (line {html5[key]['line']})")

    if args.write:
        REFERENCE.write_text(render(found), encoding="utf-8")
        print(f"\nWrote {REFERENCE.relative_to(REPO_ROOT)} ({len(html5)} HTML5 drags).")
        return 0

    ok, failures, notes = compare(found)
    for note in notes:
        print(f"\n  {note}")
    if failures:
        print(f"\nFAIL -- {len(failures)}:")
        for failure in failures:
            print(f"  {failure}")
        return 1
    print(f"\nEvery drag can be done without dragging, and a browser test operates each "
          f"alternative with a finger.")
    return 0


if __name__ == "__main__":
    from enforcement_runs import recording

    raise SystemExit(recording("audit_drag_affordances", main))

"""One drag mechanism, and nothing may leave through the gaps.

Also this check's home: `audit_drag_affordances` declares `every suite run`.

The question this came from was whether React would suit a complicated
drag-and-drop UI. React was never the variable — it has been the product
throughout, and a browser fires `dragstart` the same way whatever renders the
element. The variable was the mechanism, and there were four:

    html5     4 sources   native `draggable` + `dataTransfer`
    pointer   1 canvas    `onPointerDown` with `setPointerCapture`, hand-rolled
    dnd-kit   1 source    `useSortable`
    xyflow    3 canvases  a third-party graph editor, left alone

The first two are gone. The assertions below hold that: native drag cannot be
operated from a keyboard or touch at all, and the hand-rolled pointer drag was
worse than either — it could not be reached from a keyboard, a pipeline node's
position had no other control, and *no census counted it*. The first version of
this audit reported three mechanisms and there were four, so the rule that
catches raw pointer drags is here because one hid from the rule that came first.

The other thing held here is the sensor configuration. A `DndContext` built
without `useWorkspaceSensors` loses the 8px activation distance, and every
draggable in this product is also a button that does the same job on click — so
losing it does not break the drag, it breaks the control beside it.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from audit_drag_affordances import (  # noqa: E402
    KIT, REFERENCE, SENSOR_BACKED, SPECS, compare, proof_missing, render, scan,
)

checks = 0


def check(condition, message):
    global checks
    assert condition, message
    checks += 1


found = scan()

# --- the two mechanisms that were migrated away are gone, and stay gone --------
check(found["html5"] == [], f"native HTML5 drag is back in: {found['html5']}")
check(found["pointer"] == [],
      f"a hand-rolled pointer drag is back in: {found['pointer']}. This is the class no "
      f"census counted; it is gated because one hid in the pipeline canvas.")
check(found["kit"], f"{KIT} is gone; there is no shared mechanism left to be on")

# The rule must be able to see what it claims to see. A file that drags on raw
# pointer events has to trip it, or "0 hand-rolled" means only that nothing
# matched a pattern that matches nothing.
from audit_drag_affordances import _HTML5, _POINTER, _CONTEXT  # noqa: E402

check(_POINTER.search("event.currentTarget.setPointerCapture(event.pointerId);"),
      "the pointer rule does not match setPointerCapture")
check(_POINTER.search("onPointerMove={moveNode}"), "the pointer rule does not match onPointerMove")

# Those two spellings are exactly what the migration deleted, so matching them
# proves only that the rule catches code that is already gone. A review of the
# migration found two ordinary ways back in that the first version scanned
# clean, and neither trips any other rule here either -- no dnd-kit hook means
# no declaration is owed and the file is invisible to the whole audit.
check(_POINTER.search('window.addEventListener("pointermove", onMove);'),
      "a drag hand-rolled on a window listener -- the standard way to write one that "
      "survives the pointer leaving the element -- is not caught")
check(_POINTER.search("window.addEventListener('mousemove', onMove);"),
      "the single-quoted window listener is not caught")
check(_POINTER.search("<div onMouseDown={start} onMouseMove={move} onMouseUp={stop} />"),
      "the pre-pointer-events spelling of the same drag is not caught")
# ...and the rule must not swallow things that are not drags.
check(not _POINTER.search('window.addEventListener("keydown", handler);'),
      "a keyboard listener reads as a hand-rolled drag")
check(not _POINTER.search('<div className="modal-backdrop" onMouseDown={onClose}>'),
      "a modal backdrop that closes on an outside press reads as a drag; three of "
      "those exist and none of them drags anything")
check(_HTML5.search('onDragStart={() => setDragName(name)}'), "the native rule misses onDragStart")
check(_HTML5.search('onDrop={() => dropOn(name)}'), "the native rule misses onDrop")
# ...and must not trip on dnd-kit's context props, which share three of the names.
context = '<DndContext sensors={sensors} onDragStart={pick} onDragEnd={drop}>'
check(not _HTML5.search(_CONTEXT.sub("", context)),
      "dnd-kit's own onDragStart reads as a native drag once the context is stripped")

# --- every context takes the shared sensors -----------------------------------
check(found["unshared_context"] == [],
      f"DndContext without `sensors` in: {found['unshared_context']}. The 8px activation "
      f"distance is what stops a click on a draggable button reading as a zero-length drag.")

# --- every file that drags is declared, and proven ----------------------------
check(len(found["dnd-kit"]) == 4, sorted(found["dnd-kit"]))
check("components/canvas/PipelineCanvas.tsx" in found["dnd-kit"],
      "the pipeline canvas is where the uncounted mechanism lived; it must stay declared")
undeclared = [f for f in found["dnd-kit"] if f not in SENSOR_BACKED]
check(not undeclared, f"files that drag and declare nothing: {undeclared}")
stale = [f for f in SENSOR_BACKED if f not in found["dnd-kit"]]
check(not stale, f"declared as dragging and no longer does: {stale}")

for file, declaration in sorted(SENSOR_BACKED.items()):
    gap = proof_missing(declaration)
    check(not gap, f"{file} {gap}")
    check(len(declaration["reachable"]) > 30, f"{file} does not say how it is reached")
    check(len(declaration["moves"]) > 20, f"{file} does not say what it drags")

# The specs must operate these without a mouse. A spec reaching for `dragTo`
# would be proving the thing that already worked.
specs = {declaration["proven_by"].split("::")[0] for declaration in SENSOR_BACKED.values()}
check(specs == {"drag-affordances.spec.ts", "touch-authoring.spec.ts"}, sorted(specs))
for name in sorted(specs):
    text = (SPECS / name).read_text(encoding="utf-8")
    check(".tap()" in text, f"{name} proves a touch path without tapping anything")
    check("dragTo" not in text and "dragAndDrop" not in text,
          f"{name} drags with a mouse, so it cannot be evidence that a mouse is unnecessary")
check("keyboard.press" in (SPECS / "drag-affordances.spec.ts").read_text(encoding="utf-8"),
      "nothing presses a key, so the capability the migration bought is unproven")

# --- rendering is a pure function of the scan ---------------------------------
text = render(found)
check(render(found) == text, "rendering twice gives the same bytes")
check("| File | Drags | Reachable without a mouse | Proven by |" in text, text[:200])
for file in found["dnd-kit"]:
    check(f"`{file}`" in text, f"{file} is missing from the reference")

# --- the gate ------------------------------------------------------------------
ok, failures, notes = compare(found)
check(ok, failures)
check(REFERENCE.exists(), f"no reference at {REFERENCE}")
check(REFERENCE.read_text(encoding="utf-8") == text,
      "the committed reference is stale; run --write")

print(f"Drag mechanism gate verified: {checks} assertions passed "
      f"({len(found['dnd-kit'])} files on the shared kit, 0 native, 0 hand-rolled).")

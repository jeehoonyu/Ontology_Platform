"""Every drag has a second way, and a browser test operates it with a finger.

Also this check's home: `audit_drag_affordances` declares `every suite run`.

The question this came from was whether React would suit a complicated
drag-and-drop UI. React is already the product, so the framework was never the
variable. The variable is the mechanism, and three run at once: native HTML5 in
four places, `@dnd-kit` in one, `@xyflow/react` on three canvases.

Native HTML5 drag-and-drop does not fire from touch input and is not
keyboard-operable -- a property of the platform, not of this code. Two of those
four sites already had an alternative and nobody had ever operated it, so a
tidy-up could have deleted one and left a workspace mouse-only with the suite
still green. That is what these assertions are for.

The tidy conclusion -- that the library-backed drag is the safe one and the other
four should move onto it -- is the thing measuring disproved. The `@dnd-kit`
sortable was the single drag in this product a finger could not use at all,
because `.drag-grip` had no `touch-action: none` and the browser spent every
gesture on scrolling before the pointer sensor saw a move. So the gate treats
both kinds the same way: the alternative, or the sensor, is proven in a browser
or it is not claimed.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from audit_drag_affordances import (  # noqa: E402
    NON_DRAG_PATHS, REFERENCE, SENSOR_BACKED, SPECS, _body, _key_for, compare, proof_missing,
    render, scan,
)

checks = 0


def check(condition, message):
    global checks
    assert condition, message
    checks += 1


# --- the key is the payload, so it survives the line moving -------------------
check(_key_for('{(event) => event.dataTransfer.setData("application/x-node-type", t)}')
      == "application/x-node-type", "a MIME payload names the drag")
check(_key_for("{() => setDragName(name)}") == "setDragName",
      "a drag with no dataTransfer is named by the state it sets")
check(_key_for("{() => noop()}") == "unnamed", "an unrecognisable drag is still keyed")

# Brace balancing, because a handler body contains braces of its own and a naive
# scan to the first `}` would key every arrow function as `unnamed`.
sample = 'onDragStart={(e) => { if (x) { set(1) } }} onDrop={y}'
check(_body(sample, sample.index("=") + 1) == "{(e) => { if (x) { set(1) } }}", _body(sample, 11))

# --- the live tree -------------------------------------------------------------
found = scan()
html5 = found["html5"]
check(len(html5) == 4, f"expected the four known HTML5 drags, found {sorted(html5)}")
check(found["dnd-kit"] == ["workspaces/VisualBuilder.tsx"], found["dnd-kit"])
check(len(found["xyflow"]) == 3, found["xyflow"])

# Every native drag is declared. A new one fails here rather than at the point a
# touch user opens the screen.
undeclared = [key for key in html5 if key not in NON_DRAG_PATHS]
check(not undeclared, f"HTML5 drags with no non-drag path declared: {undeclared}")

stale = [key for key in NON_DRAG_PATHS if key not in html5]
check(not stale, f"declared drags that no longer exist in the source: {stale}")

# The one library-backed drag needed proof as much as the hand-rolled ones, and
# for a while did not have it. `@dnd-kit`'s pointer sensor supports touch; this
# screen did not, because the grip had no `touch-action: none` and the browser
# spent every gesture on scrolling. A finger could not reorder a configuration
# field at all. Moving the other four onto the library would have spread that.
unproven = [f for f in found["dnd-kit"] if f not in SENSOR_BACKED]
check(not unproven, f"sensor drags with nothing proving they work from touch: {unproven}")
check(proof_missing(SENSOR_BACKED["workspaces/VisualBuilder.tsx"]) == "",
      "the sortable reorder names a touch test that is gone")

# --- the declarations point at tests that exist and still carry the title ------
for key, declaration in sorted(NON_DRAG_PATHS.items()):
    gap = proof_missing(declaration)
    check(not gap, f"{key} {gap}")
    check(len(declaration["without_drag"]) > 30,
          f"{key} declares an alternative without saying what it is")
    check(len(declaration["moves"]) > 20, f"{key} does not say what the drag moves")

# Three of the four are proven by one spec written for this; the fourth was
# already proven by the touch-authoring measurement, and is not restated.
specs = {declaration["proven_by"].split("::")[0]
         for declaration in list(NON_DRAG_PATHS.values()) + list(SENSOR_BACKED.values())}
check(specs == {"drag-affordances.spec.ts", "touch-authoring.spec.ts"}, sorted(specs))

# Those specs must operate the alternatives by tap, never by drag. A spec that
# reached for `dragTo` would be proving the thing that already works.
for name in sorted(specs):
    text = (SPECS / name).read_text(encoding="utf-8")
    check(".tap()" in text, f"{name} proves a touch path without tapping anything")
    check("dragTo" not in text and "dragAndDrop" not in text,
          f"{name} drags, so it cannot be evidence that a drag is unnecessary")

# --- rendering is a pure function of the scan ---------------------------------
text = render(found)
check(render(found) == text, "rendering twice gives the same bytes")
check("| Drag | Moves | Without a drag | Proven by |" in text, text[:200])
for key in html5:
    check(html5[key]["carries"] in text, f"{key} is missing from the reference")

# --- the gate ------------------------------------------------------------------
ok, failures, notes = compare(found)
check(ok, failures)
check(REFERENCE.exists(), f"no reference at {REFERENCE}")
check(REFERENCE.read_text(encoding="utf-8") == text,
      "the committed reference is stale; run --write")

print(f"Drag affordance gate verified: {checks} assertions passed "
      f"({len(html5)} native drags, {len(html5)} declared, 0 reachable only by dragging).")

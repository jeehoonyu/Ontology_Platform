# Goal — Panes that move, and drags that share a screen

Stated 2026-09-11. Follows [`GOAL_DRAG_2026-08-19.md`](GOAL_DRAG_2026-08-19.md), which put
every drag on one mechanism and gave each a keyboard. This is the next question that asks:
now that a drag is one thing, can the *screen* be rearranged, and can several drags live
on one screen at once without eating each other.

## The request, read against the code

Two asks: **flexible and concurrent drag and drop**, and **panes that move around and are
easily movable**. Neither is a framework question, and neither is a drag-library question;
both were settled by the prior two goals. What is left is layout and interaction, and the
code says how much of each exists today.

### What moves today

| Drag | Mechanism | Keyboard | Touch |
| --- | --- | --- | --- |
| pipeline node around its canvas | `DragKit` | yes | yes |
| palette entry onto the pipeline canvas | `DragKit` | yes | button beside it |
| library entry onto the artifact canvas | `DragKit` | yes | button beside it |
| dataset field onto a property; property row reorder | `DragKit` | yes | select / grip |
| inspector field reorder | `DragKit` | yes | grip |
| nodes on the three xyflow graphs | `@xyflow/react` | pane only | yes |

### What does not

**No pane on any screen can be moved, resized, collapsed, docked or hidden by the person
using it.** Every pane is a fixed CSS grid track:

| Screen | Tracks | Where |
| --- | --- | --- |
| app shell | `286px` sidebar, `1fr` workspace | `.app-shell` |
| pipeline builder | `220px` library, `1fr` canvas, utility rail; `330px` inspector | `.pipeline-body`, `.builder-shell` |
| visual builders (4 artifact types) | `190–220px` library, `1fr` canvas, `270–330px` inspector | `.visual-builder-grid` |
| ontology manager | mapping panel, property list, xyflow graph, stacked | `.panel` |
| bottom drawer | fixed height, tabbed | `.bottom-drawer` |

The only layout a person can change and keep is node positions on the platform graph,
saved to `localStorage` under `ontology.platformGraph.layout`. That is the precedent for
persistence and the whole of it.

### What "concurrent" means here, since the word carries three meanings

All three are in scope, and they are different work:

1. **Several drag kinds on one screen at once.** A pane grip over a canvas that drags
   nodes, over a list that sorts rows. The failure is one context stealing the other's
   pointer, or a click on a palette entry reading as a zero-length pane drag.
2. **Several items in one drag.** Shift-select three pipeline nodes and move them
   together. `@dnd-kit` carries one `active` id; the selection has to ride in the drag's
   data.
3. **Several people.** The builders are collaborative
   ([`COLLABORATION.md`](COLLABORATION.md)): a move is a command, the server rebases
   non-overlapping batches and returns `409` on overlap. Two people dragging the same
   node is the conflict case, and today nothing shows that someone else is holding it.

## Design

### One pane primitive

`components/layout/Pane.tsx`, wrapping the existing `Panel`. Its header carries:

- **a grip**, which is `DragHandle` from `DragKit`, so the drag census counts it and the
  gate refuses a hand-rolled one;
- **a "Move to…" menu** — left, right, bottom, hide — the control beside the drag, in
  the shape every other drag here already has;
- **a collapse toggle**, so a pane can get out of the way without leaving.

Between adjacent panes sits a **splitter**: a `button` with `role="separator"`,
`aria-valuenow`, `aria-orientation`, arrow keys to resize, and the pointer sensor for a
mouse. `.pane-grip` and `.pane-splitter` carry `touch-action: none` and nothing else does,
which is the lesson of L5 written into CSS before a finger measures it this time.

### One layout model

```ts
type PaneLayout = {
  slots: Record<"left" | "center" | "right" | "bottom", string[]>;  // pane ids, in order
  sizes: Record<string, number>;                                    // px per slot, clamped
  collapsed: string[];
  hidden: string[];
};
```

Keyed by screen (`ontology.panes.pipeline`, `ontology.panes.workshop`, …) in `localStorage`,
matching the existing key convention, with a **Reset layout** control in the workspace
header and a **Panes** menu that lists hidden ones so nothing can be lost. A layout is a
viewing preference: it is never shared through collaboration, never sent to the server,
and never part of an artifact revision. That is a decision, not a deferral.

### Nested contexts, and why grip-only activation solves reading 1

Each screen gets one pane `DndContext` outside the canvas and list contexts it contains.
The pane context's listeners are attached **only to the grip**, never to the pane body, so
a pointer that starts on a node, a palette entry or a row belongs to the inner context and
the outer one never sees it. Every context takes `useWorkspaceSensors`, which the gate
already requires, so the 8px activation distance holds and a click on a grip that is also
a menu trigger stays a click.

Keyboard moves between slots need a coordinate getter that jumps between slot rectangles,
not between siblings in a sortable list and not by pixels. `useWorkspaceSensors` takes a
third `kind`, `"slots"`, with that getter — the same shape as the `"sortable"` correction
in L8, added for the same reason.

### Multi-item drag (reading 2)

Selection on the pipeline canvas: click selects, shift-click extends, `Escape` clears. A
node's `useDraggable` carries `data: { ids }` — the selection if the dragged node is in
it, else itself. `onDragEnd` applies one delta to every id and commits **once**, as the
single-node drag already does. A `DragOverlay` shows a count badge above two. The
keyboard drag moves the whole selection the same way.

### Several people (reading 3)

The heartbeat already carries selection. A node inside another participant's selection
renders a **held-by** badge, and the drag overlay says who, before the drop rather than in
the `409` after it. The rebase-or-reject model stays exactly as documented; this only
makes the overlap visible early. No locking is added: a lock that outlives a dropped
connection is worse than a conflict a person can read.

### Responsive

Below 700px the four slots become one stack and slot order becomes list order. The grip
stays, "Move to…" becomes "Move up / down", the splitter disappears, and the render sweep
at four widths must stay green. Hidden panes stay reachable from the **Panes** menu.

### Floating panes are deliberately last

A pane that floats over a canvas competes with the canvas for every pointer and with the
page for every finger. Docked slots, collapse and resize cover the ask for movable panes;
floating is M8, taken only if the measured layouts show people wanting it, and then still
on `DragKit` in a portal.

## Gates this must clear, before any of it is written

| Gate | What it will say |
| --- | --- |
| `audit_drag_affordances` | every new file with a dnd hook owes a `SENSOR_BACKED` entry naming a browser test; every `DndContext` takes the shared sensors |
| `audit_style_scope` | `.pane`, `.pane-grip`, `.pane-splitter`, `.pane-slot` will be shared across many files — declared shared in the first commit, not discovered by the gate later |
| `audit_ui_primitives` | `Pane` appears with its user count; the count is the rollout ratchet |
| `audit_route_cost` | layout is local; the pane chrome may add **zero** requests to any route |
| `audit_ui_states` | a pane with nothing in it shows `EmptyState`, not a blank track |
| render sweep | 375, 768, 1280, 1600, overflow and contrast |

And one new one, written first because the number it produces decides the shape of the
rest: `oms/audit_pane_layout.py` scans each workspace for pane regions (`aside`, `section`
with an `aria-label`), reports which sit in a fixed track, which are movable, which are
resizable, and generates [`PANE_LAYOUT.md`](PANE_LAYOUT.md). It ratchets the movable
count upward and refuses a new fixed-track pane in a screen already on `Pane`.

## Conditions

- **M1 — Count the panes before moving any.** **Met** — `oms/audit_pane_layout.py`,
  [`PANE_LAYOUT.md`](PANE_LAYOUT.md) generated from the scan, and a baseline.

  | First run | |
  | --- | --- |
  | pane regions | **21**, across 13 screens |
  | movable by the person using them | **0** |
  | screens offering a splitter | **0** |

  The estimate above said "roughly fourteen" and is left standing, because an estimate
  corrected by a measurement is the reason for measuring first. The gap is mostly
  `<section>` regions carrying an accessible name — release studio, registry, health
  centre, contract panel, execution drawer — which read as panels and are laid out as
  fixed tracks exactly like the rails.

  Two judgements are written into the scan rather than left implicit. `<Panel>` usages are
  **not** counted: `Panel` renders a labelled `<section>` at runtime, there are dozens, and
  counting them would bury the twenty-one under a number nobody could act on. Dialogs are
  excluded: the command palette is `role="dialog"` with `aria-modal`, and a modal is a
  different interaction with different rules.

  This ratchet runs the opposite way from every other one here. It is a **floor**: a pane
  that stopped being movable is a person's layout taken away. Both refusals are asserted
  against synthetic inputs in `test_pane_layout_audit.py`, because a floor that has never
  refused anything is a number printed beside a claim.
- **M2 — One pane primitive, on the pipeline builder first.** **Met** — `Pane` with grip,
  "Move to…", collapse and the **Panes** menu, applied to the library, the canvas, the
  inspector and the bottom drawer. Proven by `pane-layout.spec.ts::a pane moves to another
  slot without a drag`, on the 390×844 touch viewport, with `locator.tap()` and never a
  drag. Four of twenty-three regions now move, across seven tests.

  **The palette drag broke silently, and only the full tier found it.** Putting the
  library and the canvas in separate panes put `useDraggable` and `useDroppable` in
  separate `DndContext`s, so the drop never fired — with no error, because a draggable
  whose droppable is in another context simply never reports a target. Nesting cannot fix
  it: grips and palette entries are intermixed across panes, so whichever context is
  nearer captures both. One context per screen, owned by `usePaneLayout` and dispatching
  on the id prefix, is the shape that works.

  That was not sufficient either. A pane slot is a droppable that *contains* the canvas,
  so a slot won every geometric contest and a palette entry dropped on the canvas reported
  the slot. `slotAwareCollision` filters candidates by what is moving: a `pane:` drag sees
  only slots, everything else sees everything except slots. That is M4's "none steals the
  other's target" arriving early, because M2 could not be finished without it.
- **M3 — Resize from a keyboard, and keep it.** **Met** — a `role="separator"` splitter
  with a live `aria-valuenow`, arrow keys (`Shift` for a coarser step, `Home`/`End` for the
  bounds), pointer dragging, and persistence under `ontology.panes.pipeline`. Two tests
  assert on the stored size and the reported value, never a bounding box, for the reason
  L8 records; the resize one was shown to fail with the arrow handler removed. Below 700px
  the splitter is `display: none`, because stacked panes have no boundary to drag — which
  is why those two tests open a desktop context of their own rather than using this file's
  touch viewport.

  **The splitter is the one thing here not on `DragKit`, and the drag gate refused it.**
  It uses a pointer listener, which is exactly the pattern that gate started refusing two
  commits ago. Rather than quietly exempt it, `POINTER_ALLOWED` is a list of one that
  demands both halves of an argument: why the file keeps a listener, and the name of a
  browser test operating the same control **from a keyboard**. The reason a splitter
  qualifies is that it is not a drag between containers — it has no droppable to land on,
  so `useDraggable` would model a journey it never makes — and the reason the exemption is
  worth anything is the keyboard test, which the gate checks still exists. Adding an escape
  hatch to one's own gate is the circumstance that most deserves saying out loud.
- **M4 — A pane drag over a node drag over a row drag, and none steals.** **Met** — the
  `"slots"` sensor kind, and four assertions in `concurrent-drags.spec.ts`, each shown to
  fail against a build with the thing it defends removed.

  **Two of the three pieces this condition asked for were already built, and the third
  premise was wrong.** The nested contexts are gone: M2 found that separate contexts break
  the palette outright and that nesting cannot fix it, so a screen has one context that
  dispatches on an id prefix. `slotAwareCollision` arrived with it. What was left was the
  keyboard, and it is the piece that could not have been seen without a test — dnd-kit's
  default getter moves a drag 25px a press, so crossing a slot took about forty presses,
  and nothing anywhere said so.

  **One context means one keyboard sensor, so the coordinate getter has to dispatch too.**
  Handing the whole context slot-jumping would have broken `a pipeline node moves with the
  keyboard` in exactly the way L8 records: the wrong getter reaching a draggable it was not
  written for, silently, with every pointer drag still working. A non-pane drag is handed
  back to dnd-kit's own default rather than a copy of it. Three things now ask the same
  question about the same prefix, so `isPaneDrag` is named once in `DragKit` and the other
  two call it.

  **Grip-only activation does not do what this condition assumed.** The premise was that
  the grip is what stops a pane stealing a node's pointer. It is not. Spreading the pane's
  listeners across its whole section and rebuilding left every palette and node test green,
  because dnd-kit refuses a second activation while one is live and a nested draggable's
  listener fires before its ancestor's. What the grip actually protects is everything in a
  pane that is *not* a draggable — prose a person is selecting, a list they are scrolling —
  and the assertion that catches it drags the pane's own text and requires the pane to stay
  put. The click-still-clicks assertion is kept as a guard rather than a proof, and says so:
  it passes with the grip wiring removed, because the 8px activation distance is what makes
  a click a click.

  **The keyboard test was flaky before it was right, and the flake was the same
  staleness twice.** The getter first found the slot it was leaving from
  `currentCoordinates`, which is the pane's top-left at pick-up; page scroll moves that
  point out from under its own slot, measured as the same drag reporting y=392 in one run
  and y=329 in another. It reads `context.over` now — the slot `slotAwareCollision` has
  already chosen, and therefore the one the drop will act on. The remaining flake was in
  the test: a re-render between the pick-up and the arrow key takes dnd-kit's document
  listener with it, and the symptom is the coordinate getter never being entered at all.
  It waits for the screen to settle first, and asserts the mid-drag announcement rather
  than only the outcome, so a failure says which slot the drag was over when it stopped.

  **A pane was never rendering its drag.** `useDraggable` returned a transform that `Pane`
  computed and discarded, so a dragged pane faded and sat still under the pointer — shipped
  that way in M2 and not noticed, because the drop worked. M4 found it from the other end: a
  keyboard move announced `slot:center` and then committed `slot:left`, because the element
  was still physically in its old slot and a re-render mid-drag re-measured it there.
- **M5 — More than one node in one drag.** **Met** — on the pipeline canvas, click selects a
  node, Shift-click adds or removes one, and Escape clears the selection. Dragging any node of
  a multi-node selection carries all of them by the same delta, live, and commits once: one
  layout request and one `Undo move` entry, however many nodes moved. A node outside the
  selection still moves alone. Proven by `three selected nodes move together and commit
  once` in `multi-node-drag.spec.ts`, which reads committed positions — `style.left`, never a
  bounding box — and counts the `PATCH …/layout` requests, because "moved together" and
  "saved once" are separate claims and a build can make the first true with three requests.

  Two things differ from the design above, and both are deliberate. **The selection rides in
  the drop handler rather than in `data: { ids }`**: the handler already knows the selection,
  so copying it into every draggable's data would be a second copy to keep in step with the
  first. **The other selected nodes follow the drag through `useDndMonitor`**, because dnd-kit
  transforms only the active draggable — without it the rest of the selection sat still and
  jumped into place on release. The count badge in a `DragOverlay` is not built; the selection
  highlight on every carried node already says what is moving, and a badge is a design choice
  this condition does not need.

  Negative runs, three builds. A drag that moves only the dragged node: `the move was not
  committed as one`. The rest of the selection not following a live drag: `selected node 2
  did not move with the drag while it was live`, the transform empty. Escape leaving the
  selection: `Received: 3`. Restored, it passed, with every pipeline cancel, undo, zoom,
  scrolled-canvas and reset test from `GOAL_MOVEMENT`, the concurrent drags, the keyboard node
  move, the palette drop and the zoom controls green on the same build — nineteen tests.

  Escape during a live node drag still cancels the drag, as dnd-kit does, and also clears the
  selection. The cancel test holds position and writes; the selection is transient state, so
  clearing it is not a mutation, and it is named here rather than left for someone to find.
- **M6 — The person holding a node is visible before the conflict.** **Open** — the
  held-by badge from heartbeat selection. Proven by a two-context browser test where the
  second page sees the first page's selection on the node within one heartbeat.
- **M7 — Every builder is on `Pane`, and the count cannot fall.** **Open** — the four
  visual-builder artifact types, then the ontology manager. The rollout is the
  `audit_ui_primitives` user count for `Pane` and the `audit_pane_layout` movable ratchet.
- **M8 — Floating panes, if the layouts ask for them.** **Open** — last, optional, and
  only on `DragKit` through a portal. Not started until M1–M7 are met.

## Order and size

| Step | Touches | Commits |
| --- | --- | --- |
| M1 | `oms/audit_pane_layout.py`, `docs/PANE_LAYOUT.md`, `verify.py` registry, baseline | 1 |
| M2 | `components/layout/Pane.tsx`, `PipelineBuilder.tsx`, `styles.css` (declared shared classes), one spec | 2 |
| M3 | `Pane.tsx` splitter, `lib/paneLayout.ts`, spec | 1–2 |
| M4 | `DragKit.tsx` (`"slots"`), `PipelineBuilder.tsx` contexts, spec | 1–2 |
| M5 | `PipelineCanvas.tsx`, `PipelineBuilder.tsx`, spec | 1 |
| M6 | `VisualBuilder.tsx`, `PipelineCanvas.tsx`, spec | 1 |
| M7 | `VisualBuilder.tsx`, `OntologyManager.tsx`, `styles.css` | 2–3 |

Every test is run once against a build with the thing it defends removed before it is
believed, which is the discipline that caught both bugs in the drag migration.

## What this is not

Not a change of drag library, and not a second drag mechanism: a pane moves by the same
`DragKit` a node moves by, and the gate that refuses anything else stays as it is.

Not a shared layout. A screen arrangement belongs to the person looking at it.

Not a free-floating window system. That is M8, stated last on purpose, and it stays
unstarted until the docked layouts have been used enough to say whether it is wanted.

Not a touch-support claim for the whole interface. Two grips and a splitter gain a finger;
everything else keeps scrolling, which is the trade L5 measured and this keeps.

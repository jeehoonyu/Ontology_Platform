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
- **M2 — One pane primitive, on the pipeline builder first.** **Open** — `Pane` with grip,
  "Move to…", collapse and the **Panes** menu, applied to the library, the inspector and
  the bottom drawer. Proven by `pane-layout.spec.ts::a pane moves to another slot without
  a drag`, on the 390×844 touch viewport, with `locator.tap()` and never a drag.
- **M3 — Resize from a keyboard, and keep it.** **Open** — the splitter, arrow keys,
  persistence under `ontology.panes.<screen>`, and **Reset layout**. Proven by `a pane
  resizes from the keyboard and survives a reload`, asserting on the stored size and not
  on a bounding box, for the reason L8 records.
- **M4 — A pane drag over a node drag over a row drag, and none steals.** **Open** — the
  nested contexts, grip-only activation, and the `"slots"` sensor kind. Proven by three
  assertions in one test: a pane drags by its grip, a node under the pane still drags by
  itself, and a click on a palette entry under a pane grip still adds a node. Shown to
  fail with the grip-only wiring removed.
- **M5 — More than one node in one drag.** **Open** — selection, `data: { ids }`, one
  commit. Proven by `three selected nodes move together and commit once`, reading
  committed positions and counting the command batch.
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

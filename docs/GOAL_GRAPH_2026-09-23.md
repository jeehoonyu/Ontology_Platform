# Goal — Work the graph the way the original does

Stated 2026-09-23. Follows [`GOAL_SHELL_2026-09-23.md`](GOAL_SHELL_2026-09-23.md), which came
from opening our build at widths the tests never visit. This one comes from opening the
product ours is modelled on and reading what its graph editor does that ours does not.

## Where this was read

The live DigitalGlobe enrollment is authenticated and was not reopened; the September 11
review ([`FOUNDRY_PLATFORM_UI_REVIEW_2026-09-11.md`](FOUNDRY_PLATFORM_UI_REVIEW_2026-09-11.md))
remains the evidence for what is enabled there. What follows was read on 2026-09-23 from
Palantir's public documentation, in the browser, page body and all:

- [Pipeline Builder — Navigation](https://www.palantir.com/docs/foundry/pipeline-builder/navigation/)
- [Pipeline Builder — Tips and tricks](https://www.palantir.com/docs/foundry/pipeline-builder/tips-and-tricks/)
- [Workshop — Drag and drop](https://www.palantir.com/docs/foundry/workshop/drag-and-drop)
- [Quiver — Dashboards](https://www.palantir.com/docs/foundry/quiver/dashboards-create)

Public documentation describes a capability; it does not prove the feature is enabled in any
enrollment. Nothing here is a parity claim. It is a list of things a person who has used the
original will reach for on our pipeline canvas, and what happens when they do.

## The original's graph editor, against ours

The original's Edit view is four regions — top toolbar, details sidebar, graph, preview pane —
and the graph carries a fixed set of controls. Ours, after the pane and movement goals, has
the regions. It is the controls on the graph itself where the gap is.

| The original | Ours, `PipelineBuilder` and `PipelineCanvas` | Gap |
| --- | --- | --- |
| **Drag Select Mode**; Shift+drag from panning mode lassos nodes | click selects; Shift+click extends (M5) | no lasso |
| **Select** all nodes; `Ctrl+A` | — | none |
| `Ctrl+D` select children, `Ctrl+E` select parents | — | none |
| **Remove** selected nodes | `Delete node`, one node | multi-node delete |
| **Layout**: evenly disperse and organise the graph; grid snapping | — on the pipeline canvas (`PlatformGraph` has `Auto layout`) | none |
| Zoom in, out, **fit**; `Up Arrow` fits | Zoom in, out, `Fit` buttons | no key |
| `Ctrl+C` / `Ctrl+V` copy and paste nodes, colour groups preserved, across pipelines | — | none |
| `Ctrl+H` hide selected, `Ctrl+K` unhide all | — | none |
| `Ctrl+F` **Search pipeline** panel | — | none |
| **Legend** and colour groups; folders; text nodes | — | none |
| Click and drag an output circle to an input circle to connect | edge-insert control on each edge; `insertAfter` | no port drag |
| Right-click a node: Copy, Paste, Open | — | no context menu |
| **Undo / Redo** in the top toolbar | `Undo move`, one step, moves only | no redo; adds and deletes are not undone (a V-goal gap) |
| Explicit **Save**; a filled *Saved* state; *View changes* for unsaved work | positions save on drop; the strip says `Layout is saved.` | no unsaved-changes view |
| Help → **View hotkeys** | one hotkey, `Escape` clears the selection | no reference |
| Preview panel expands from the lower-left of the graph | the `Outputs` pane, movable and resizable | — |
| Details sidebar collapses from an icon | a pane's collapse toggle | — |

Two rows are worth reading twice. **Lasso** is how the original selects a region of a graph,
and it is the gesture the pane goal made structurally safe: `useWorkspaceSensors` activates
only past 8px from a grip or node, so a drag that starts on empty canvas belongs to nobody
today and can belong to a selection rectangle. **Layout** is the one control that fixes a
graph a person has made a mess of, and ours has it on one canvas out of four.

## What is deliberately not taken from the original

- **Folders, colour groups, text nodes.** Organisation of a large graph. The bootstrap
  pipeline has under ten nodes; a colour legend for it is decoration until a measured graph
  is large enough to need one.
- **Branches, proposals, review progress.** The original's collaboration model. Ours has
  revisions and rebased commands ([`COLLABORATION.md`](COLLABORATION.md)); the review model
  is a product decision, not a graph-editor gap.
- **Workshop's section tree and typed data drops.** The research's P1, and still the right
  next design project. It stays named in [`GOAL_MOVEMENT_2026-09-12.md`](GOAL_MOVEMENT_2026-09-12.md)
  and is the successor to this goal, not part of it.
- **AI generate and explain.** Out of scope for a goal about gestures.

## Design

**Selection is a set, and every tool takes the set.** M5 made selection a list on the
builder. Lasso, select all, select parents, select children all write that list; delete,
copy, hide, layout and the multi-node drag all read it. One state, in the file it already
lives in.

**Lasso on `DragKit`, not beside it.** A drag that starts on empty canvas becomes a
selection rectangle: a `useDraggable` on the canvas background with the shared sensors,
so the drag census counts it and Escape cancels it through the mechanism every other drag
uses. Shift held on pick-up adds to the selection instead of replacing it, as the original
does from panning mode. Touch is not claimed: a finger on empty canvas scrolls, and select
all is the control beside the gesture.

**Hotkeys are one table, and the table is the help.** A `HOTKEYS` list in one module —
key, label, handler — drives both the `keydown` listener and a `View hotkeys` dialog, so
the reference cannot disagree with the wiring. The original's keys are used where they do
not collide with the browser: `Ctrl+A`, `Ctrl+C`, `Ctrl+V`, `Ctrl+D`, `Ctrl+E`, `Ctrl+H`,
`Ctrl+K`, `Ctrl+F`, `Up Arrow` to fit, `Delete`. Every hotkey has a button that does the
same thing, so `audit_inert_controls` sees a wired control and a keyboard-only user is not
the only one served.

**Layout is a command with one undo.** `Auto layout` on the pipeline canvas uses the
layered placement `PlatformGraph` already has, commits positions once, and records one
move-history entry for every node it moved, so one `Undo move` puts the graph back. This is
the V4 rule, applied to the one canvas that lacked the command.

**Copy and paste are commands, and paste is a batch.** Copy writes the selected nodes and
the edges between them to the clipboard as JSON under a private MIME type and as text.
Paste sends one command batch, offset from the original positions, and records one undo
entry. Across pipelines is what makes it worth having, and it works because the payload is
self-describing.

**Hidden is a view state, not an edit.** `Ctrl+H` hides the selection in this browser;
edges to hidden nodes draw to a small badge that says how many are hidden, in the honest-UI
form; `Ctrl+K` and a `Show all` button restore. Nothing is saved to the server.

**Search finds and selects.** `Ctrl+F` focuses a search box in the canvas pane; matches
are selected and the first is scrolled into view. It reuses the selection set, so `Delete`
or `Ctrl+H` after a search does what a person expects.

**Connect by dragging a port.** An output port on each node is a draggable; an input port
is a droppable; both on `DragKit`. A drop calls the same `insertAfter` path the edge
control calls, so the edge is created by one command and undone by one undo. The edge
control stays, because it is the control beside the drag.

**Unsaved work is visible.** The original refuses to auto-save a branch and shows a filled
*Saved* state. Ours saves positions on drop and holds typed configuration in drafts. The
strip gains one honest line: `3 unsaved changes` when drafts exist, `Saved` when none do,
and the count is a button that lists them.

## Gates this must clear

| Gate | What it will say |
| --- | --- |
| `audit_drag_affordances` | the lasso and the two ports are dnd-kit drags in files with `SENSOR_BACKED` entries; no native drag, no hand-rolled pointer |
| `audit_movement_contract` | three new surfaces — `pipeline-lasso`, `pipeline-connect`, `pipeline-layout` — each with cancel, recover and alternative named |
| `audit_inert_controls` | every hotkey has a wired button; the count stays at zero |
| `audit_table_truncation` | the hidden-node badge states its count |
| `audit_route_cost` | search, hide, and lasso add no requests; paste adds one command batch |
| `audit_style_scope` | `.canvas-lasso`, `.node-port` declared shared if `VisualBuilder` takes them |

## Conditions

- **X1 — The gap is a table, and the table is kept.** **Met** — `docs/GRAPH_EDITOR_PARITY.md`,
  generated by `oms/audit_graph_editor.py` from a list of the original's controls and a scan
  of `PipelineBuilder.tsx` and `PipelineCanvas.tsx` for the handler each maps to. The gate
  refuses a row that names a handler the file no longer has, and reports the count met.
  First run: 3 of 15.

  **What was built.** The fifteen rows are the fifteen graph controls in the table above, in
  its order. The preview panel and the details sidebar are regions ours already has as panes,
  not controls on the graph, so they are not rows. Each row names the original's control,
  what ours has, the handler ours maps it to (or none), and a state:
  - met, with a named browser test that operates it;
  - a gap, and what is missing;
  - not taken, with the reason.

  A row can name a handler and still be a gap. Ours zooms with buttons and has no key that
  fits; it deletes one node, not a selection. The gate:
  - refuses a handler its file no longer **defines**, as a function, a `const` or a typed
    prop;
  - refuses a met row with no handler, or with a test that does not exist;
  - refuses a rising gap count, or a met control becoming a gap;
  - refuses a row newly declared not taken, as `audit_movement_contract` refuses a new `na`;
  - refuses a reference that disagrees with the source.

  It is the twenty-fourth check in the fast tier, is declared in the check registry and the
  enforcement ledger, and is run by `oms/test_graph_editor_audit.py`.

  **The first run reads 0 of 15, not 3.** Seven rows have a handler doing part of the job:
  `selectNode`, `removeNode`, `onZoom`, `insertAfter`, the click menu's `onContextInsert`,
  `undoMove` and `moveNodes`. Seven have nothing. The legend and colour groups row is not
  taken, as the goal says. No row does the whole of what the original's control does, so
  none is met. "3 of 15" reads as the three rows the goal marks with the nearest partial
  handler (zoom, delete, undo). The baseline holds 14 gaps, and the count may only fall.

  **Negative runs:**
  - **N1, the handler check removed:** the test failed at `a row naming a handler its file
    does not have passes`.
  - **N2, not taken accepted without the baseline:** failed at `turning a gap into not taken
    lowers the count and passes`.
  - **N3, `undoMove` renamed in `PipelineBuilder.tsx` with its callers left alone:** the audit
    failed at `undo-redo names undoMove, which workspaces/PipelineBuilder.tsx no longer
    defines`. The first version matched any mention of the name, found the callers, and
    passed. That is why the check now asks for a definition.
  - **N4, a row claimed met by a test nobody wrote:** the audit failed on the missing test.
  - Restored, the sources are byte for byte what they were.
- **X2 — A region of the canvas selects with a drag, and the set is what every tool takes.**
  **Open** — lasso on `DragKit`, Shift adds, `Select all` and `Ctrl+A`, parents and children.
  Proven by `graph-editor.spec.ts::a lasso selects the nodes inside it and Escape selects
  nothing`, reading the selection list, and shown to fail with the background draggable
  removed.

  **First half, the set and the tools that write it.** The builder has one set of nodes the
  tools act on: `selection`, or, when that is empty, the node last clicked. A node shows as
  selected only if it is in that set. It used to show as selected if it was either, so a
  node outside a Shift-built selection still looked selected because it had been clicked
  last. Each node carries `data-node-id` and `data-in-selection`, which is how a test
  reads the set. The count reads `N of M selected` above the canvas, beside three
  buttons:
  - `Select all`;
  - `Select parents`, which adds the selected nodes' parents, one edge away, so pressing it
    again walks further up;
  - `Select children`, the same downwards.

  All three write the set and nothing else, so they send no request. A change to the
  clicked node costs four requests, which is why none of them touches it. Their keys are
  `Ctrl+A`, `Ctrl+E` and `Ctrl+D`, the original's. They are rows in one table in
  `lib/hotkeys.ts`, whose listener is driven by the table and nothing else. A key counts
  only when nothing in particular has the focus or the focus is on the canvas. A key typed
  into a field belongs to the field.

  Proven by three tests in `graph-editor.spec.ts`, each on a pipeline it builds through the
  API with nodes where it put them:
  - `Select all, parents and children write the one selection and send nothing`;
  - `Ctrl+A, Ctrl+E and Ctrl+D do what their buttons do`;
  - `a key typed into a field is the field's`.

  `GRAPH_EDITOR_PARITY.md` reads 2 of 15 met, `select-all` and `select-family`, and its
  baseline holds 12 gaps. On the same build, 130 tests pass on the desktop-1280 project,
  one skipped: the multi-node, movement, shell, evaluator, truncation, inert, drag and
  concurrent-drag specs.

  **Negative runs,** each on a rebuilt `dist`:
  - **N1, `Ctrl+A` taken out of the table:** failed at `Ctrl+A did not select every node`.
  - **N2, `Select all` also moving the clicked node:** failed before it reached the requests
    it counts. Moving the clicked node also changed what Escape falls back to, so `c` was no
    longer the node left selected.
  - **N3, a key typed into a field taken by the canvas:** failed at `Ctrl+A in a field
    selected nodes`.
  - Restored, the three pass, and the two sources are byte for byte what they were.
- **X3 — One command lays out the pipeline, and one undo puts it back.** **Open** — `Auto
  layout` on the pipeline canvas, one history entry. Proven by `auto layout moves every node
  and one Undo restores every position`, reading committed positions.
- **X4 — Every hotkey has a button, and the help is the wiring.** **Open** — the `HOTKEYS`
  table, the `View hotkeys` dialog rendered from it, the listener driven by it. Proven by a
  test that reads the dialog, presses each key, and checks the same outcome as the button;
  shown to fail with one key removed from the table, because the dialog then omits it.
- **X5 — Nodes copy and paste, within and across pipelines, as one batch.** **Open** —
  proven by `three copied nodes paste into a second pipeline with their edges`, counting
  the command batch and the nodes after.
- **X6 — Hidden nodes are a view state that says how many it hides.** **Open** — `Ctrl+H`,
  `Ctrl+K`, `Show all`, the badge. Proven by a test that hides two, reads the badge, reloads,
  and finds nothing hidden on the server.
- **X7 — A port drag connects two nodes by the same command as the edge control.** **Open** —
  proven by `dragging an output port onto an input port inserts one edge and one Undo removes
  it`, and by the existing edge-control test still passing.
- **X8 — The strip says whether there is unsaved work.** **Open** — `Saved` or `N unsaved
  changes`, the count a button. Proven by a test that types into a node draft and reads the
  strip, shown to fail with the draft count disconnected.

## Order and size

| Step | Touches | Commits |
| --- | --- | --- |
| X1 | `oms/audit_graph_editor.py`, reference, registry, baseline | 1 |
| X2 | `PipelineCanvas.tsx`, `PipelineBuilder.tsx`, `styles.css`, spec, `SENSOR_BACKED`, contract rows | 2 |
| X3 | `PipelineBuilder.tsx`, layout helper shared with `PlatformGraph.tsx`, spec | 1 |
| X4 | `lib/hotkeys.ts`, `PipelineBuilder.tsx`, spec | 1–2 |
| X5 | `PipelineBuilder.tsx`, API command batch, spec | 1–2 |
| X6 | `PipelineCanvas.tsx`, `PipelineBuilder.tsx`, spec, truncation reference | 1 |
| X7 | `PipelineCanvas.tsx`, spec, `SENSOR_BACKED`, contract rows | 1 |
| X8 | `PipelineBuilder.tsx`, spec | 1 |

Every test is run once against a build with the thing it defends removed. Every new drag is
proven to cancel on Escape before it is believed to work, because that is the order the
movement goal found bugs in.

## What this is not

Not parity with the original, and not a claim that the original works the way its
documentation says in any enrollment. Fifteen controls were read from two public pages;
they are the ones a person will reach for.

Not the Workshop composer. That is the successor, and it needs the section census the
research asked for before a single drop label can be honest.

Not a second drag mechanism. Lasso, ports and layout all run through `DragKit` or through
commands; the census counts every one and the gate refuses the rest.

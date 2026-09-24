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
  **Met** — lasso on `DragKit`, Shift adds, `Select all` and `Ctrl+A`, parents and children.
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

  **Second half, the lasso.** A drag that starts on bare canvas draws a rectangle, and on
  release selects the nodes whose centres it closes over. It is a `useDraggable` on
  `DragKit`'s shared sensors, on its own surface under everything else on the stage, so a
  press on a node, an edge control or a menu is theirs, and a click stays a click below
  8 px. Only the listeners are spread on it, not the attributes: it is not a control, so it
  takes no role and no tab stop, and a key pressed on a button can never start it.
  - The rectangle starts where the pointer went down, measured against the stage at that
    moment, and grows by dnd-kit's delta, which already counts any scroll of the canvas.
  - Shift held when it starts adds to the selection; otherwise it replaces it.
  - Escape cancels it through dnd-kit, and nothing is selected by it.
  - The drop outline stays off, because nothing can land.
  - Touch is not claimed: without `touch-action: none` a finger on bare canvas scrolls.

  The scouts found one trap before it shipped. Every non-node drag that ends over the canvas
  was read as a palette drop, which creates a node of the dragged id's type. The builder now
  stops at the lasso's id first, and the second negative below shows what that line
  prevents.

  Three more tests in `graph-editor.spec.ts`:
  - `a lasso selects the nodes inside it and Escape selects nothing`: it proves the lasso
    is live before judging it, reads the set from the nodes, and counts that nothing was
    written or created;
  - `Shift held when a lasso begins adds to the selection`;
  - `the nodes a lasso selects can be selected without a drag`, the single-pointer way, by
    Shift+click.

  The fixture's nodes sit inside the 568 stage pixels the canvas shows at 1280, clear of the
  legend in its top right corner. A first version put the right column where the canvas
  could not show it, so the lasso started on the legend.

  **Gates.** `MOVEMENT_CONTRACT.md` gains `pipeline-lasso`, with cancel and alternative met
  by those tests. Its recover stage is declared not applicable in the baseline, an edit made
  here in the open: a lasso moves nothing and writes nothing, so there is no move to undo. The
  gap count holds at 12. `DRAG_AFFORDANCES.md` lists `lasso:canvas` among the pipeline
  canvas's drags. `PipelineCanvas.tsx` already had its sensor-backed entry, and the census
  finds no native drag and no hand-rolled pointer. `GRAPH_EDITOR_PARITY.md` reads 3 of 15
  met, with `lasso` added, and its baseline holds 11 gaps. On the same build, 109 tests pass
  on the desktop-1280 project, one skipped: the multi-node, movement, evaluator, drag, touch,
  concurrent-drag, inert, shell and graph-editor specs.

  **Negative runs,** each on a rebuilt `dist`:
  - **N1, the background draggable removed, as the goal asks:** failed at `the lasso never
    started`.
  - **N2, the builder's guard removed:** failed at `a lasso wrote something; it selects, and a
    selection is not an edit`. The lasso had gone on to the palette drop.
  - **N3, Shift ignored:** failed at `a Shift lasso replaced the selection`.
  - **N4, the drop outline lit by a lasso:** failed at `a lasso lit the drop outline`.
  - Restored, the six tests pass, and the two sources are byte for byte what they were.
- **X3 — One command lays out the pipeline, and one undo puts it back.** **Met** — `Auto
  layout` on the pipeline canvas, one history entry. Proven by `auto layout moves every node
  and one Undo restores every position`, reading committed positions.

  **What was built.** `Auto layout`, beside the selection tools, lays the pipeline out left to
  right with a column per layer. A node nothing flows into is layer 0, and every other node
  is one past the deepest node that flows into it, so every edge points to a later column.
  Within a column, the nodes keep the top-to-bottom order a person had already given them.
  A graph with a cycle still lays out and loses no node.

  The goal said the layout would use "the layered placement `PlatformGraph` already has".
  `PlatformGraph` places by columns, not layers: a column per kind of resource. So what is
  shared is the placement: `lib/graphLayout.ts` holds `columnLayout`, which `PlatformGraph`
  now uses with its kinds and the pipeline uses with its layers. `PlatformGraph` places
  exactly as it did.

  Node moves and the layout now commit through one function, `commitPositions`. It sends
  one layout request and pushes one history entry holding every position from before, so
  one `Undo move` takes back the whole change. If a layout would move nothing, it moves
  nothing and says so.

  **Proven by** `auto layout moves every node and one Undo restores every position`. It runs
  on a four-node pipeline placed out of order on purpose, and checks:
  - each node's committed position after the layout;
  - that the layout was one save;
  - that one Undo put every node back exactly, with one more save;
  - that nothing was left to undo.

  **Gates.**
  - `MOVEMENT_CONTRACT.md` gains `pipeline-layout`, as a new `command` mechanism: a move
    made by one click, which the drag census cannot see. A command surface names its
    handler, and the gate checks its file still defines it. `test_movement_contract_audit`
    holds a renamed handler and a missing one.
  - The surface's recover and alternative stages are met by the test above. Its cancel
    stage is declared not applicable in the baseline, in the open: one click has no gesture
    under way to take back part of. The gap count holds at 12.
  - `GRAPH_EDITOR_PARITY.md` reads 4 of 15, with `layout` met. Grid snapping is still not
    there and is said so. The baseline holds 10 gaps.
  - On the same build, 98 tests pass on the desktop-1280 project, one skipped: evaluator,
    movement, multi-node, graph-editor, drag and inert.

  **A ceiling raised, in the open.** `audit_route_payload` failed the pipeline route at 562,471
  bytes against a ceiling of 552,973 recorded on 2026-09-13. Built without this commit, the
  route was already 561,031 bytes, 134 bytes inside the 8 KB tolerance. The pane menu, the
  status strip and the selection tools of the last day had spent the rest, and this commit
  adds 1,440 bytes. Every one of those is a feature a condition asked for, so the pipeline
  route's ceiling is set to 562,471 by hand, and no other route's ceiling moves.
  `PlatformGraph` is 778 bytes heavier and still inside its tolerance.

  **Negative runs,** each on a rebuilt `dist`:
  - **N1, the undo entry keeping one node's position:** failed at `one Undo did not put b
    back`.
  - **N2, every node in one column:** failed at `auto layout did not place b in its layer`.
  - Restored, the test passes, and `PipelineBuilder.tsx` is byte for byte what it was.
- **X4 — Every hotkey has a button, and the help is the wiring.** **Met** — the `HOTKEYS`
  table, the `View hotkeys` dialog rendered from it, the listener driven by it. Proven by a
  test that reads the dialog, presses each key, and checks the same outcome as the button;
  shown to fail with one key removed from the table, because the dialog then omits it.

  **What was built.** The builder's `hotkeys` table has five rows now:
  - `Ctrl+A`, `Ctrl+E` and `Ctrl+D`, from X2;
  - `Ctrl+F`, which opens Search pipeline;
  - `Up Arrow`, which does what `Fit to view` does.

  Each row is the keys, what they do, the button that does the same, and the handler.
  `View hotkeys` renders the table as a dialog. The dialog takes the focus when it opens, so
  Escape reaches it, and hands the focus back to its button when it closes.

  Search pipeline selects every node whose name, id or type contains what was typed, says
  how many of how many match, and scrolls the first into view. It writes the selection, so
  a tool used after a search takes what it found.

  `Ctrl+C`, `Ctrl+V`, `Ctrl+H` and `Delete` arrive as rows with the conditions that give them
  something to do (X5 and X6). The reference picks them up because it is the table.

  **Two keys the goal named do not land as written.** `Ctrl+K`, the original's "show all
  hidden", is this product's command palette on every screen (`App.tsx`), and a pipeline
  canvas taking it would take the palette away there. X6 gives "show all" its own key.
  `Up Arrow` fits the way our `Fit to view` does: it returns to one fixed zoom and does not
  fit the graph to the canvas. The `zoom-fit` parity row stays a gap for that.

  **The test caught its own premise.** The first version of the table said a keyboard drag
  handles Up Arrow first and prevents its default, so a hotkey would leave it alone. A test
  written to prove that failed. Up Arrow in a keyboard drag refitted the canvas under the
  drag, 1.02 back to 0.86, because this listener runs before the drag's own. The builder
  now tracks a live drag through the drag context's start, end and cancel, and the hotkeys
  stand down while one is live.

  **Proven by** three more tests in `graph-editor.spec.ts`:
  - `the hotkeys reference lists the table, and each key does what its button does`. It reads
    the rows from the dialog, and for each checks that the named button is on the page and
    that pressing the key gives what clicking the button gives: the selection for the
    selection rows, the focus for search, the zoom for fit. A row it has no way to observe
    fails it.
  - `a search selects what matches, and a tool used after it takes that`.
  - `Up Arrow during a keyboard drag moves the node, not the zoom`.

  `GRAPH_EDITOR_PARITY.md` reads 6 of 15, with `search` and `hotkeys` met, and its baseline
  holds 8 gaps. On the same build, the ten graph-editor tests pass. So do 43 multi-node,
  drag, movement and concurrent-drag tests. Before the drag fix, 124 across nine specs had
  passed.

  **Route payload, re-measured.** With this commit `audit_route_payload` failed Vertex, a route
  this work never touched, at 8.6 KB over its ceiling. The global stylesheet ships in the
  entry, so every class added for the pane menu, the canvas tools, the lasso, the search and
  this reference lands on every route. The shared closure has grown 5,728 bytes since the
  ceilings were set on 2026-09-11: about 2 KB is this session's stylesheet, and the rest came
  in between. The ceilings are re-measured with `--set-baseline`, the ceremony the gate
  names. Every route rose by the shared growth plus its own, from +2,865 bytes (the pipeline
  builder, whose ceiling was raised by hand in X3) to +8,583 (Vertex).

  **Negative runs,** each on a rebuilt `dist`:
  - **N1, `Ctrl+A` taken out of the table, as the goal asks:** failed at `the hotkeys
    reference does not list Ctrl+A`, the reference reading the other four.
  - **N2, the hotkeys running during a drag:** failed at `Up Arrow refitted the canvas in the
    middle of a drag`.
  - **N3, the reference not taking the focus:** failed at `Escape did not close the
    reference`.
  - **N4, a search that selects nothing:** failed at `the search did not select the node it
    matched`.
  - Restored, the ten tests pass, and the two sources are byte for byte what they were.
- **X5 — Nodes copy and paste, within and across pipelines, as one batch.** **Met** —
  proven by `three copied nodes paste into a second pipeline with their edges`, counting
  the command batch and the nodes after.

  **There was no batch to send.** The pipeline builder speaks REST: one request per node
  added, inserted or deleted, and nothing that connects two nodes already there. The
  artifact command API is the visual builder's. So the pipeline gets
  `POST /pipeline-builder/graphs/{id}/commands`, a batch of four commands:
  - `add_node`, which may name a `ref`, and a later edge in the same batch may use that
    ref in place of the id the server has not yet given;
  - `add_edge`;
  - `delete_node`, which takes the node's edges with it;
  - `delete_edge`.

  The batch is checked command by command against a copy of the graph, and the copy is
  written once, so it applies whole or not at all. It is scoped and permissioned like
  every other edit to a graph and recorded as one audit event. The response is the canvas
  and `created`, each ref with its new id, which is what lets a paste be taken back
  exactly. `oms/test_pipeline_commands.py`, 42 assertions, holds:
  - a paste with its edges;
  - an edge between an existing node and a new one;
  - five refused batches that change nothing;
  - the undo of a paste;
  - an edge taken back;
  - another project's editor and a viewer refused.

  The auth, tenancy, route, query-bound and object-write audits all hold. The route
  requires `edit`, and the tenancy census is unchanged at 360.

  **Copy, paste and delete.** Copy puts the selected nodes and the edges between them on the
  system clipboard as JSON twice: under a private format, and as text. The payload names
  its own kind, so a paste reads it rather than guessing at whatever text is on the
  clipboard. The last copy is also kept in the tab, for when the clipboard cannot be read.
  A clipboard that was read and holds something else has nothing to paste.

  Paste sends one batch: the nodes 40 px down and right of where they were, then their
  edges, by ref. The pasted nodes become the selection. It re-fetches nothing, because the
  batch returns the canvas. One Undo takes the whole paste back in one request, and the
  button says so, `Undo paste`, as it says `Undo move` after a move.

  `Delete selected` and the `Delete` key take every selected node and its edges in one
  request. Unlike `Delete node`, they do not join a deleted node's neighbours: with several
  nodes going, which neighbours would join has no one answer. `Ctrl+C`, `Ctrl+V` and
  `Delete` are rows in the hotkeys table, and the reference test observes them too:
  - the clipboard, which its reset empties;
  - the number of nodes added or removed since its reset.

  Its first version read "the change so far" before an asynchronous paste had landed, got 0
  for the button and 0 for the key, and called them the same.

  **Proven by** `three copied nodes paste into a second pipeline with their edges`. It copies
  three of four nodes, reads the system clipboard, and opens a second pipeline in a fresh page
  load, so the paste must come from the clipboard and not from anything the page kept. It
  then checks:
  - that one command batch was the only edit;
  - that the server holds three new nodes and exactly the two edges between them, each
    node 40 px from its original;
  - that the pasted nodes are what is selected;
  - that one `Undo paste` in one request leaves the pipeline as it was.

  `Delete removes every selected node in one request` is the second test. Its first version
  counted the preview and suggestions POSTs for the node shown next, which are reads, so
  edits are counted and those are not. `GRAPH_EDITOR_PARITY.md` reads 8 of 15, with
  `copy-paste` and `remove-selected` met, and its baseline holds 6 gaps. The twelve
  graph-editor tests pass, and so do 103 movement, multi-node, evaluator, drag, inert,
  shell, concurrent-drag and touch tests.

  **Negative runs,** each on a rebuilt `dist` or a restarted test:
  - **N1, a paste sent as two batches, nodes then edges:** failed at `the paste was not one
    command batch`.
  - **N2, a copy that drops the edges between the nodes:** failed at `Copied 3 nodes and 2
    edges.`, `Received: "Copied 3 nodes."`.
  - **N3, a paste pushed to no history:** timed out looking for `Undo paste`.
  - **N4, Delete taking only the node last clicked:** failed at `Deleted 2 nodes`, `Received:
    "Deleted 1 node."`.
  - **N5, the backend letting an unknown node through:** `test_pipeline_commands.py` failed at
    `a batch naming a node that is not there: 200`, with an edge to `nobody` written.
  - Restored, the tests pass, and the sources are byte for byte what they were.
- **X6 — Hidden nodes are a view state that says how many it hides.** **Met** — `Ctrl+H`,
  `Ctrl+K`, `Show all`, the badge. Proven by a test that hides two, reads the badge, reloads,
  and finds nothing hidden on the server.

  **What was built.** `Hide selected` and `Ctrl+H` hide the selected nodes from this view.
  The hidden set is kept per pipeline in this browser, like a pane layout, and never sent to
  the server. The canvas leaves the hidden nodes out, and each node that remains puts an
  `n hidden` badge where an edge to a hidden node was. The canvas also says `N of M nodes
  hidden in this browser`, in a note, beside `Show all`. A hidden node is out of every
  tool's reach: `Select all`, the lasso, search, parents and children, and the node last
  clicked when it is hidden.

  **`Ctrl+K` is not the key.** It opens this product's command palette on every screen, and the
  pipeline canvas taking it would take the palette away there. `Show all` is `Ctrl+Shift+H`, a
  row in the hotkeys table, and the reference test observes both new rows by how many nodes
  the canvas draws.

  **The truncation audit learned what hiding is.** It read two ways of showing part of a set,
  `.slice(` and an index filter, and a hidden view is a third: a predicate filter, which it
  did not see. It now reads a filter that drops members of a set named `hidden...`, by name,
  because the same shape computes data elsewhere. `builderKernel`'s removed nodes are one
  example, and a rule taking every exclusion filter would charge those as cuts. A hidden
  view must, in its own component:
  - render a count in a `role="note"`, as text and not an attribute;
  - offer `Show all`.

  Otherwise it is an unfixed truncation, held to the same ceiling as the rest.
  `TABLE_TRUNCATION.md` has a section for them, where the canvas reads yes and yes. Two
  filters in the builder, which keep hidden nodes from the tools and draw nothing, are
  declared not a view in `DELIBERATE_VIEWS` with the reason, and added to the baseline's
  `na`, in the open. The unfixed count holds at 12. `test_table_truncation_audit` holds the
  rule with 7 more assertions, one of them against a note whose only braces are an
  `onClick`, which the first version accepted as a count.

  **Proven by** `two hidden nodes are counted, survive a reload here, and are hidden nowhere on the
  server`. It hides two nodes with `Ctrl+H` and reads `2 of 4 nodes hidden in this browser`
  and two `1 hidden` badges, with no edit sent. It reloads and finds them still hidden here.
  It then reads the pipeline from the server: four nodes, and no mention of hiding.
  `Show all` brings all four back. `a hidden node is out of every tool's reach` is the second
  test. `GRAPH_EDITOR_PARITY.md` reads 9 of 15, and its baseline holds 5 gaps.

  On the same build, 111 tests pass across the graph-editor, multi-node, movement, evaluator,
  drag, inert and shell specs. One failed: `pipeline creates a graph and accepts a dragged
  node`. It passed five times out of five alone. It had also failed once in the run after
  the canvas-surface fix, before any of this goal's code existed, so it predates this
  condition. It is named here to be looked at, not explained.

  **Negative runs,** each on a rebuilt `dist` or against the source:
  - **N1, no note:** failed at `the canvas does not say how many it hides`.
  - **N2, hiding kept only until a reload:** failed at `the hidden nodes came back on reload`,
    4 where 2 were expected.
  - **N3, a hidden node still in the tools' reach.** The first version removed `Select all`'s
    filter, and passed, because the tools' own filter still held. That filter is the one that
    matters, and the test gained an assertion it alone answers. With that filter removed, the
    test failed at `a hidden node is still what the tools act on`: `1 of 4 selected` where
    `0 of 4` was right. `Select all`'s filter is a second guard, and removing it alone changes
    nothing a person sees.
  - **N4, an edge to a hidden node leaving no badge:** failed at `left no trace on the node it
    came from`.
  - **N5, the count written without `role="note"`:** `audit_table_truncation` failed at
    `view:PipelineCanvas.tsx::PipelineCanvas::hiddenNodes is an unfixed truncation`.
  - Restored, the tests pass, and the sources are byte for byte what they were.
- **X7 — A port drag connects two nodes by the same command as the edge control.** **Met** —
  proven by `dragging an output port onto an input port inserts one edge and one Undo removes
  it`, and by the existing edge-control test still passing.

  **Not the edge control's command, because it connects nothing.** The edge control on each
  edge calls `insertAfter`, which creates a new node after the selected one and re-points that
  node's outgoing edges. It cannot join two nodes already there, and no route could. So a port
  drop sends X5's batch with one `add_edge`, and one `Undo connect` sends one `delete_edge`.
  The goal's other premise did not hold either: there was no edge-control test. There is now
  one, `the insert control on an edge still inserts a node after the selected one`. Writing
  it found that a selected node's click menu, tall and opening to its right, sits over the
  edge controls of a left-hand column. That overlap is older than this goal, and the test
  selects a node whose menu is clear.

  **What was built.** Every node shown has two ports. The output, on its right edge, is a
  `useDraggable`; the input, on its left, is a `useDroppable`. Both are on `DragKit`'s shared
  sensors. A drag draws a dashed edge from the port to the pointer, and an input port lights
  when a port is over it. The drop outline stays off, because a port never lands on bare
  canvas. Dropped on an input, it connects. Dropped anywhere else, it does nothing, and the
  builder stops at a port's id before the palette drop that would create a node. Escape
  cancels through dnd-kit.

  The ports are pointer affordances, not tab stops: two per node would bury the canvas.
  `Connect` is the way without a drag: it joins two selected nodes, the first selected
  feeding the second. The history grows a third kind, so the Undo button names what it takes
  back: `Undo move`, `Undo paste` or `Undo connect`.

  **Proven by** five tests in `graph-editor.spec.ts`:
  - `dragging an output port onto an input port inserts one edge and one Undo removes it`
    reads the edges from the server after the drop and after the Undo, one command each;
  - `Escape during a port drag connects nothing and writes nothing`;
  - `a port dropped on bare canvas connects nothing and creates nothing`;
  - `two selected nodes connect without a drag`;
  - the edge-control test.

  **Gates.**
  - `MOVEMENT_CONTRACT.md` gains `pipeline-connect`, with cancel, recover and alternative all
    met by those tests. The gap count holds at 12.
  - `DRAG_AFFORDANCES.md` lists `port-in:` and `port-out:` among the pipeline canvas's drags,
    and its entry names `Connect` as the way without one.
  - `GRAPH_EDITOR_PARITY.md` reads 10 of 15, with `connect` met, and its baseline holds 4
    gaps.
  - On the same build, 121 tests pass across the graph-editor, multi-node, movement,
    evaluator, drag, inert, shell, touch and concurrent-drag specs, one skipped.

  **The pipeline route's payload, raised by hand again.** Its ceiling was 565,336 bytes from
  X4's re-measure. X5 and X6 brought it to 571,329, inside the tolerance, and the ports add
  2,401 more, 573,730, which is past it. The ceiling is set to that, and no other route's
  moves.

  **Negative runs,** each on a rebuilt `dist`:
  - **N1, the output port's draggable removed:** failed at `the port drag never started`.
  - **N2, the builder's stop at a port's id removed.** The first round passed: a drop on an
    input still connected, and no test dropped a port anywhere else. The bare-canvas test was
    written for that, and with the stop removed it failed at `a port dropped on bare canvas
    wrote something`, a node posted with the port's id as its type.
  - **N3, a connect pushed to no history:** timed out looking for `Undo connect`.
  - **N4, `Connect` joining the pair backwards:** failed at `Connected b to c.`, `Received:
    "Connected c to b."`.
  - Restored, the tests pass, and the two sources are byte for byte what they were.
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

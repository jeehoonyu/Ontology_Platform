# Goal — A move you can take back, and a save that says what it keeps

Stated 2026-09-12, from [`FOUNDRY_UI_RESEARCH_2026-09-12.md`](FOUNDRY_UI_RESEARCH_2026-09-12.md),
which extends the [platform review](FOUNDRY_PLATFORM_UI_REVIEW_2026-09-11.md). Runs
alongside [`GOAL_PANES_2026-09-11.md`](GOAL_PANES_2026-09-11.md), open at M8, and
[`GOAL_HONEST_UI_2026-09-11.md`](GOAL_HONEST_UI_2026-09-11.md), open at N7.

## Why this, out of a plan with eight work packages

The research proposes an interaction contract — discover, start, preview, traverse,
reject, commit, cancel, recover — and a delivery order whose first item is not a feature:
*recheck the existing pane and canvas implementation against the contract, record current
behaviour and remaining gaps.* It says in as many words that the earlier review's code
observations are a dated baseline that must be rechecked before anything is built.

That recheck is this goal's census, and it was run before a condition was written. It
is the same discipline as every goal before it: count, gate the count, then fix. The later
packages — typed drop targets, a nested layout editor, saved views with private and shared
defaults, map camera stability, rendering cost, narrow screens — are real, and each needs
its own census. They are listed at the end as not started, not as done.

## What the census says

Measured in a browser against the build at `bd44a57`, by a probe that recorded each drag's
mid-drag state before judging it — the class a live drag carries, the transform it writes,
the announcement it makes. Two of the probe's first readings were wrong for exactly that
reason: a pipeline node drag and a VisualBuilder drag each "passed" Escape because the drag
had never started. One was aimed at a node scrolled out of view, so the pointer landed on
the sidebar. A cancel test that does not prove the drag was live proves nothing.

### Cancel and recover, per movement surface

| Surface | Mechanism | Escape mid-drag | Undo after | Measured |
| --- | --- | --- | --- | --- |
| pane between slots | `DragKit` | **restores**, no write | not applicable — a layout preference; `Reset layout` and `Move to…` | live: transform and `moved over slot:right` before Escape |
| pipeline node on its canvas | `DragKit` | **restores**, no request | **none** — the drop saves to the server and nothing takes it back | live: `dragging` class, transform, announcement |
| pane splitter | hand-written pointer listener | **does not cancel** — 220 → 382 during, 382 after, 382 written to `localStorage` | not applicable | live: `aria-valuenow` 382 mid-drag |
| VisualBuilder node (xyflow) | `@xyflow/react` | **does not cancel** — (120, 100) → (192, 128), stays | **8 undo presses for one drag** | live: `dragging` class |
| VisualBuilder node, click with no movement | `@xyflow/react` | — | **no entry**, as the contract asks | one Undo removed the node added before it |
| palette entry, library entry, field and property rows | `DragKit` | same sensor as the pipeline node; not separately measured | — | — |
| ontology designer and platform graph nodes | `@xyflow/react` | same library as VisualBuilder; not separately measured | none | — |

**One VisualBuilder drag writes eight undo entries into a fifty-entry history.** `changeNodes`
snapshots on every `position` change, and xyflow emits one for each grid step a drag
crosses. So one move takes eight presses to take back, and six ordinary drags push the
oldest real edit out of the history entirely. The research's recover rule is one undo per
completed move; this is one per sixteen pixels.

**The splitter is the only surface where Escape commits.** It is the one control not on
a drag library — kept on a pointer listener on purpose, with the reason recorded in
`DRAG_AFFORDANCES.md` — and it listens for `pointermove` and `pointerup` and nothing else.
No `pointercancel` either, so a touch interrupted by the system leaves it resizing.

**And the splitter has no single-pointer alternative.** It resizes by drag and by arrow
keys. The research is specific that keyboard support does not satisfy WCAG 2.5.7, which
asks for a way to do a dragging operation with a single pointer and no drag. Every *move*
in the product already has one (`Move to…`, `Up`/`Down`, tap-to-place); the *resize* does
not.

### Where a drag lands, at a zoom other than one

**At the zoom floor the preview shows a little over half of the move.** A keyboard drag of
a pipeline node at `scale(0.55)`, chosen so that no bounding box is read: dnd-kit's delta
was 88 screen pixels, and it is written as the node's transform *inside* the scaled stage,
so while the drag was live the node had moved 48.4 pixels on screen. The drop divided the
delta by the zoom, as it should, committed 160 stage pixels, and the node landed 88 pixels
from where it began. The preview trails its own landing by 40 pixels and the node jumps on
release.

The commit is right and the preview is wrong: `endCanvasDrag` divides by `zoom` and
`PipelineNodeCard`'s transform does not. At the ceiling, `1.35`, the same arithmetic puts
the preview 35% *past* the landing — derived from the code, not measured. This is the
research's first evaluation scenario, and it fails at both ends of the range that
`GOAL_HONEST_UI` N2 wired to the canvas zoom controls.

The pointer version of this measurement failed three times before the keyboard one was
used, and not for a reason about zoom: after twelve zoom presses the canvas was still
scrolling, so a node's box read before the pointer went down was somewhere else by the
time it did. That is worth a sentence because it is the same lesson as `GOAL_DRAG` L8 from
the other side — a bounding box is what the layout engine was doing at the moment it was
read.

### Every save and reset, and the scope it actually has

The research names four scopes — personal workspace, authored artifact, saved analysis
view, transient work — and asks that each save action be named by the one it touches. Read
from the source, not measured:

| Control | Screen | Writes | Scope | What it says |
| --- | --- | --- | --- | --- |
| `Reset layout` | Pipeline Builder | pane slots, sizes, collapsed, hidden — `localStorage` | personal workspace | nothing; the layout changes |
| `Save layout` | Pipeline Builder | node positions — server | authored artifact | "Layout saved for this graph." |
| a node drop | Pipeline Builder | node positions — server | authored artifact | "Saved *id* position." |
| `Save view` | Platform Graph | node positions only — `localStorage` | personal workspace | **nothing** |
| `Save view` | Object Explorer | filters, columns, charts, search — server | saved analysis view | "Saved exploration *name*"; no private or shared choice |
| autosave | the four VisualBuilder artifacts | a revision, 1.2 s after an edit — server | authored artifact | the revision reason |
| `Reset view` | Map | the camera | transient | — |
| *(no control)* | Ontology designer | node positions — **nowhere** | — | the panel says *drag object types to arrange the ontology* |

Three things in that table are the defect the research describes:

- **`Save layout` and `Reset layout` sit on the same screen and mean different things.**
  One writes the artifact to the server for everyone; the other clears a personal
  arrangement in this browser. The same noun names two scopes, and the one with the wider
  reach is the one that sounds smaller. `Save layout` also re-sends positions every drop
  has already saved.
- **Platform Graph's `Save view` saves node positions and nothing else, silently.** The
  search, the kind filters and the neighbourhood toggle — the things a person would call a
  view — are not in it, and the button gives no sign it did anything.
- **The ontology designer invites arranging and keeps none of it.** Positions live in
  component state; a reload lays the graph out again. The instruction is on the panel and
  the arrangement is discarded without a word.

## Conditions

- **V1 — Count the contract, and make the count a gate.** **Met** —
  `oms/audit_movement_contract.py`, [`MOVEMENT_CONTRACT.md`](MOVEMENT_CONTRACT.md) generated
  from it, a baseline, and `test_movement_contract_audit.py` at 58 assertions.
  **25 gaps** across 11 surfaces and 3 stages: 6 met by a named browser test, 2 not
  applicable with a reason. Per stage: cancel 9 gaps, recover 9, alternative 7.

  **A surface is finer than a file.** `Pane.tsx` moves a pane on `DragKit` and resizes a
  slot on a pointer listener, and the two cancel oppositely, so they are two rows. The drag
  census supplies every (file, mechanism) pair — eight of them — and each must be covered by
  a surface; a surface whose mechanism has left its file is refused. Not measured is a gap:
  eleven of the twenty-five say so, because a stage nobody has operated is not one that
  works, and the census probe had already shown two drags "restoring" on Escape that had
  never started.

  **The gate's own evasion path is `na`.** Every other way to lower the count needs a
  behaviour and a test; declaring a stage not applicable needs a sentence. So an `na` the
  baseline does not already hold fails the gate. The two in the baseline — a pane's slot
  and a slot's width have no Undo, because both are viewing preferences with `Move to…`,
  arrow keys and `Reset layout` to put them back — are written there in the open, where
  someone disagreeing can see them.

  Two stages were already met and had no test, so V1 wrote them before it could count them:
  `movement-contract.spec.ts`, Escape during a pane drag and during a pipeline node drag.
  Each first asserts the state only a live drag has — the transform and the "moved over
  slot:right" announcement; the `dragging` class — and only then presses Escape. Negative
  run: a build wiring `onDragCancel` to the drop handlers failed both, `Received: "right"`
  and `Received: "242.093px"`, and the restored build passed. Seven source mutations of the
  gate — `na` without the baseline, a met stage turning gap while the total holds, an
  uncovered drag, a stale surface, a test never checked, a blank reason, no total ceiling —
  were each caught by a named assertion.
- **V2 — Escape cancels a resize.** **Met** — the splitter restores the width it started
  from and writes nothing, on `Escape` and on `pointercancel`. Proven by
  `movement-contract.spec.ts`, three tests: Escape during a live resize, a system
  `pointercancel` during one, and — the guard on the other side of the change — a released
  resize still stored and still there after a reload.

  **The fix is a preview, not an undo.** The splitter wrote the layout on every
  `pointermove`, so by the time Escape could mean anything the width was already in
  `localStorage`. A live resize now only sets state; release stores it; Escape and
  `pointercancel` put back the arrangement captured when the pointer went down — the whole
  layout, so a slot that had no stored width at all goes back to having none. Keyboard
  steps still store at once, because each is a deliberate change rather than a position a
  hand passed through.

  Negative runs, three builds, each breaking one half. Cancel wired to commit: Escape and
  `pointercancel` both `Received: 382`, expected 220. The preview stored on every move:
  the width came back and `localStorage` did not — `a cancelled resize wrote the layout`,
  which is the assertion that tells a restore from an undo. Release not stored: only the
  guard failed, `Received: undefined`. Restored: four passed, with the pane layout and
  concurrent-drag specs — thirteen more — green on the same build.
- **V3 — A resize without a drag or a key.** **Met** — a width select for each occupied side
  slot in the panes bar: Narrow, Default, Wide, Widest, from 160 to 640 pixels. Proven by
  `a slot resizes with a single pointer and no drag`, which chooses a width and asserts the
  stored size. Hidden below 700 pixels with the splitter, because stacked slots have no
  width to choose. WCAG 2.5.7 asks for a single pointer without a drag, which keyboard
  support does not satisfy, and every *move* in the product already had one; the resize was
  the only operation that did not. The negative build without the selects failed that test
  and no other.

  `MOVEMENT_CONTRACT.md` falls from **25 gaps to 23**: `pane-resize` cancel and alternative
  are met, and its recover stays `na` in the baseline where it was written.
- **V4 — One move, one undo.** **Met** — a node drag on the four artifact canvases records
  one history entry, taken when xyflow reports the drag starting; the position changes it
  emits while the drag is live are the drag itself, not edits, and the artifact is marked
  unsaved when the drag stops rather than on every step. A position change with no drag in
  progress — a node nudged from the keyboard — still records its own entry. Proven by `one
  drag on an artifact canvas is taken back by one Undo`, which also asserts that the Undo
  took back only the move and not the node's creation. The click-with-no-movement guard
  stayed green through every build below.
- **V5 — Escape cancels a graph node drag.** **Met**, for the artifact canvases — Escape
  during a live drag puts back the nodes, edges, redo history and unsaved state captured at
  drag start and removes the drag's history entry. xyflow has no cancel of its own and keeps
  reporting the drag it still believes in until the pointer is released, so those reports
  are discarded rather than applied. Proven by `Escape during an artifact canvas drag
  restores the node and records nothing`, which carries the pointer on after Escape — that
  one extra move is the part of the test that proves the discard — and then presses Undo,
  expecting the node's *creation* to be the entry it takes back. The ontology designer and
  the platform graph run on the same library and are still recorded as unmeasured gaps; the
  fix is in `VisualBuilder`, not in xyflow, and has not reached them.

  Negative runs, three builds. Every position change recorded again: one Undo left the node
  at `(192, 128)`, and the cancel test failed too — `Expected: 1, Received: 2` nodes after
  Undo — because Escape removed one of the drag's many entries and left the rest. Escape
  wired to nothing: the node finished at `(-240, -240)`, where the pointer carried it after
  Escape. Reports after Escape applied instead of discarded: the same, which is why the test
  keeps moving. Restored: three passed, with the visual builder workflow, the two-editor
  collaboration test and the library and field-list drags green on the same build.

  **The gate's own test file broke on this condition, and not because of the gate.** It had
  named `visual-node.cancel` as the gap to close in its ratchet assertions and
  `pane-move.cancel` as the met stage to regress. V5 met the first, so "closing a gap"
  closed nothing and the assertion failed for a reason about today's census rather than
  about the rule. It now chooses both cells from the tree. That is the same mistake the
  inert-controls tests made at N2, made again one goal later.

  **And a second gate misread the fix.** `audit_drag_affordances` matched native drags with
  `onDragStart=` and no word boundary, and xyflow's `onSelectionDragStart=` — added here so a
  dragged selection box takes back the same way — ends in exactly that. The fast tier
  failed with *VisualBuilder starts or receives a native HTML5 drag*, and the reference
  had already been regenerated to say `native HTML5 | 1` before the diff was read. The rule
  has word boundaries now, its test holds both halves — the xyflow prop is not native, a bare
  `onDragStart=` still is — and the regenerated reference is byte-for-byte the committed
  one. Regenerating a reference to clear a stale-reference failure writes whatever the rule
  currently believes into the document, so the diff has to be read before it is kept.

  `MOVEMENT_CONTRACT.md` falls from **23 gaps to 21**.
- **V6 — A pipeline node move can be taken back.** **Met** — `Undo move` in the pipeline
  header reverses one committed move by saving the positions from before it back to the
  server. Each committed drop records the graph, the node and every position before it;
  the history belongs to the graph it was made on and empties when another is selected; a
  node deleted since the move is left out of the restore rather than resurrected. Proven by
  `one Undo takes back a committed pipeline node move`, which moves a node from the keyboard,
  waits for the server's *Saved … position*, and then asserts three things the screen alone
  cannot fake: the node is back, the `PATCH …/layout` the Undo sent carries the original
  position, and nothing further is left to undo.

  Negative runs, two builds. Moves not recorded: `the committed move left nothing to undo`.
  Undo restoring the screen and not the server — the version that looks right until a
  reload: `Undo move did not send the restored positions to the server`, zero requests.
  Restored: both passed. The click guard passed in every build, because a click never
  activates dnd-kit's 8-pixel sensor and so never reaches the drop handler at all; it is
  labelled a guard in its title for that reason.

  `MOVEMENT_CONTRACT.md` falls from **21 gaps to 20**.
- **V7 — The preview lands where the drop does, at every zoom.** **Met** — a pipeline
  node's live transform is divided by the stage's scale, the same division the drop already
  made, so the preview and the landing agree within a pixel. Proven by three tests in
  `movement-contract.spec.ts`, at the floor, the fitted zoom and the ceiling, each comparing
  the live transform with the committed move in stage pixels from a keyboard drag.

  The unfixed build ran first and failed all three, which turned the census's one
  measurement and one derivation into three measurements:

  | Zoom | Preview, stage px | Landed, stage px | Jump on release |
  | --- | --- | --- | --- |
  | 0.55 | 88.0 | 160.0 | 72.0 |
  | 0.86 | 92.0 | 107.0 | 15.0 |
  | 1.35 | 63.0 | 46.7 | 16.3 |

  The ceiling row is the census's derivation — *35% past the landing* — now measured:
  63.0 / 46.7 is 1.349. The middle row is the one worth saying out loud. `0.86` is the zoom
  every pipeline opens at, so this was not an edge of the range: every node drag anyone had
  made jumped fifteen stage pixels on release, and it read as the grid snapping. The fixed
  build passed all three, with the cancel, undo, keyboard-move and shared-context tests
  green beside them. This condition's negative run is the unfixed build, run before the fix
  rather than after it; the break and the thing it breaks are the same line.
- **V8 — Every save and reset says which scope it touches.** **Met** — three changes, each
  proven by a test in `movement-contract.spec.ts`:

  - **Pipeline Builder's `Save layout` is gone, and `Reset layout` is `Reset panes`.** Every
    drop already saves node positions to the graph — V6's test reads the request — so the
    button re-sent what was stored, and it sat beside a reset of a browser preference under
    the same noun. The panes' reset now names what it touches. `the pipeline screen has one
    control per scope`.
  - **Platform Graph's `Save view` is `Save positions on this device`, and confirms what it
    kept and what it did not**: *Search text, type filters and Neighbors are not part of it.*
    `platform graph positions are kept on this device, and it says so` drags a node, saves,
    reads the confirmation and reloads.
  - **The ontology designer keeps an arrangement in this browser.** It rebuilt positions on
    a grid whenever its object types loaded *and* whenever a different type was selected —
    so it forgot an arrangement on every click in the resource list, not only on reload,
    which the census had not seen. A node now keeps the position it has, then the one this
    browser stored, then its grid slot; a drag's end stores it. `the ontology designer keeps
    an arrangement across a reload`. The selection half is fixed in the same line and is not
    separately asserted.

  Negative runs, two builds. `Save layout` restored, the confirmation removed and the
  designer's store removed: all three failed, each at its own assertion — `Received: 1`,
  `saving gave no sign of what it kept`, and the designer back at `translate(0px, 0px)`
  after reload. A confirmation that claims a save nobody wrote: the reload failed, the
  message having passed — which is the case a message-only test would have called met.
  Restored: 29 of 30 passed across the movement contract, the pane layout, the concurrent
  drags and both graph workflows. The thirtieth, `one arrow key carries a pane to the next
  slot`, failed once in that run and passed five of five alone on the same build; it is the
  timing-sensitive keyboard test M4 already records, and it is named here rather than
  re-run until green.

  Two test fixes came with this, and one of them found V10. The designer test first
  dragged thin air — the designer sits below the fold and a mouse moved to off-screen
  coordinates reaches nothing — and now scrolls the node into view. The other is recorded
  under V10.

  `.inline-success` is declared shared by one more file, `PlatformGraph.tsx`; the rename
  went through the three specs that press the button, fourteen occurrences.
- **V9 — Resetting a layout touches only the layout.** **Met** — `Reset panes` leaves the
  graph's node positions exactly as they were, sends nothing to the server, and keeps
  anything typed into a pane and not yet saved. Proven by `Reset panes leaves the graph and
  unsent input exactly as they were`, the research's fourth scenario.

  **It was not true, and the census had no way to see it.** The first run of the test
  failed on the committed build: a label typed into the selected node's configuration came
  back as the saved one — `Received: "Input Dataset"`. A pane moved to another slot is a new
  parent, React remounts what it holds, and the form's own state went with it. So it was
  not the reset that lost the draft; *any* pane move did, and the reset was only the second
  way in. The test was strengthened to type first, move the pane, check, then reset and
  check again. The Execution Policy selects in the same pane survived all along, because
  their state already lived in `PipelineBuilder` rather than in the pane.

  The fix keeps the node form's draft above the panes, keyed by graph and node, and clears it
  when a save succeeds; a remount reads it back. It is a fix for the one form a pane on this
  screen holds, not a guarantee about every future pane's contents — a component with its
  own unsaved state, placed in a pane, will lose it on a move the same way, and nothing gates
  that yet. Rendering every pane in one stable container would remove the remount, and
  would also change the slot droppables, the keyboard slot getter and M2–M4's tests; that is
  not done here.

  Negative run: a build that never hands the form its draft failed at the move — `moving the
  pane threw away input that had not been sent` — before it reached the reset. Restored,
  it passed, with the movement contract and the pipeline workflows green on the same build,
  sixteen tests.
- **V10 — Picking a node up on a scrolled canvas does not move it.** **Met** — the pipeline
  canvas's drop target is a wrapper inside the scrolling canvas instead of the canvas
  itself. Proven by two tests on a canvas scrolled 100 pixels sideways: a pick-up and drop
  with no movement leaves the node where it was and saves nothing, and one arrow key to the
  right moves it to the right.

  **The cause was in how the canvas was wired to dnd-kit, not in dnd-kit.** dnd-kit adds up
  scroll offsets over the scrollable ancestors of the node being dragged — and, once the drag
  is over a droppable, over the ancestors of *that* droppable instead. The droppable here was
  `.pipeline-canvas`, which is also the element that scrolls, and an element is not its own
  ancestor. So at pick-up the canvas's scroll was in the sum, a frame later the node was over
  the canvas and it was not, and dnd-kit read the difference as the canvas having scrolled
  back by `scrollLeft`. That predicts a pick-up transform of exactly `-scrollLeft / zoom` and
  nothing at all on an unscrolled canvas, which is what the probe had measured before the
  source was read. Found by reading `useScrollableAncestors(overNode ?? activeNode)` in
  dnd-kit's own build after the numbers, not before.

  The fix puts the droppable one level inside the scroll container, so the dragged node and
  the thing it is over share the same scrolling ancestors, canvas included. The canvas became
  a one-item grid so the wrapper stretches to the whole visible canvas, with a minimum size of
  the zoomed stage so a drop anywhere on the drawn graph still lands. The wrapper is not
  positioned, so the zoom controls and legend still place themselves against the canvas.

  The unfixed build ran first and failed both: the pick-up transform read
  `translate3d(-116.279px, 0px, 0px)` — `-100 / 0.86` — and the node was saved at `3.72`
  instead of `120`; one arrow key right moved it `-87.2`. The fixed build passed both, and
  twenty-one more beside them across four widths: every cancel, undo and zoom test in the
  spec, the palette drop onto the canvas, the touch first-node add, the keyboard node move,
  the zoom controls, the shared-context drags, and the pipeline screen's render and
  accessibility sweep.

  Found while V8 was being verified, not by the census. A pipeline node picked up on a canvas already
  scrolled sideways is displaced by that scroll offset before any key is pressed, and the
  drop commits the displacement. Measured by a probe recording every scrollable ancestor
  press by press:

  | Canvas scrolled at pick-up | Transform on pick-up | Four presses right, then drop |
  | --- | --- | --- |
  | 0 px, zoom 0.86 | 0 | +116.3 stage px |
  | 15 px, zoom 0.86 | −17.4 | +98.8 |
  | 103 px, zoom 0.86 | −119.8 | **−3.5** |
  | 162 px, zoom 1.35 | −120.0 | **−45.9** |

  The transform on pick-up is exactly the canvas's `scrollLeft` divided by the zoom, so the
  drag measures the scroll from zero rather than from where it was when the drag began. The
  pointer probe earlier in this goal already showed it without anyone reading it that way: a
  120-pixel pointer move produced a 105-pixel transform on a canvas scrolled 15 pixels.

  It matters more than a test fixture: at 1280 pixels wide the pipeline canvas's viewport is
  **236 pixels** across a 1500-pixel stage, so it is scrolled sideways almost as soon as
  anyone looks at a node past the first. The preview and the landing still agree, because
  both carry the displacement — which is why V7's own comparison passed and only its
  movement floor noticed.

  **How it was found is worth recording.** V6 and V7 went red after V8 removed a header
  button, because the canvas opened scrolled differently. Three placements were tried —
  scroll the node into view, centre it, put it at the edge — and each moved the canvas and
  failed a new way. That was three guesses at a mechanism nobody had measured; the fourth
  step was a probe, and the probe found the defect. V6 and V7 now start from an unscrolled
  canvas and say why. Proven, when met, by a pick-up and drop with no movement on a canvas
  scrolled sideways, which must leave the node where it was.
- **V11 — Every stage that already works is measured.** **Met** — `MOVEMENT_CONTRACT.md` falls
  from **20 gaps to 12**, and no product source changed: eight cells were recorded as gaps for
  behaviour the product already had, and each is now held by a named test that can fail. Per stage:
  cancel 2 gaps, recover 5, alternative 5. V1 made the count a ceiling, and nothing since has re-read a gap's reason, so a stage
  that began working, or had always worked, could stay in the reference as a gap with nothing due to
  notice. This condition is where the count is kept.

  **One of the eight was never a gap.** `ontology-field-map`'s alternative said *the `Map <property>`
  select exists and no browser test operates it*, and `drag-affordances.spec.ts` had operated it since
  19 August, more than three weeks before the census wrote the sentence. `a source field maps onto a
  property without a drag` chooses a field the property does not hold, on a 390-pixel touch viewport,
  and asserts the select now holds it. It can hold it only if `mapField` ran -- the function the drop
  calls -- because the select is controlled from the mappings and snaps back otherwise. A native select
  chosen without a drag is the standard V3's width select was met by. The census counted the control
  and did not search the specs for it.

  **The other seven were not measured, and the code already did them.** dnd-kit answers Escape by
  calling `onDragCancel`, and none of the five contexts involved -- the pipeline screen's, the artifact
  screen's, the inspector's field list, the ontology field mapping and the ontology property list -- has
  one, so a cancelled drag reaches no handler that commits anything; the pipeline canvas's monitor only
  clears its carried-selection preview. A library entry's click and its drop both go through `addNode`,
  which records one history entry, and a field reorder goes through `updateSelected`, which records one.
  Seven tests in `movement-contract.spec.ts`, each of which first asserts what only a live drag over its
  target has -- the palette entry's `dragging` class and the pipeline canvas's `drag-active`; the
  artifact canvas's `drag-active`; the second field or property row moved up to make room for the first;
  the mapping target's `drag-active` -- and only then presses Escape or lets go:

  - `Escape during a palette drag onto the pipeline canvas adds no node and writes nothing`
  - `Escape during a library drag onto an artifact canvas adds no node and records nothing`
  - `one Undo takes back a node dropped from the library`
  - `Escape during a field reorder keeps the order and records nothing`
  - `one Undo takes back one field reorder`
  - `Escape during a field-mapping drag maps nothing and writes nothing`
  - `Escape during a property-row drag keeps the order and writes nothing`

  The palette and ontology tests read the requests before the screen: each of those drops writes at
  once -- a node, a mapping preview, a saved order -- and draws only when the server answers, so a
  request is the witness that cannot arrive late. The artifact screen's two cancels prove *records
  nothing* the way V5 does, not with a request count, because the autosave of an earlier edit can land
  during the drag: a node is added by click first, and after the cancel one Undo must remove that node.
  The two Undo tests add the earlier entry for the opposite reason: an Undo that took back more than the
  one move shows.

  **Both Undo tests first failed, and the product was not why.** After a drop the library test's one
  Undo left the dropped node in place, and the next autosave wrote it into a revision; the field test's
  Undo left the fields reordered. A build that logged every change xyflow reported showed one history
  entry for the drop and nothing after it, so the entry Undo needed was there. The Undo never ran: an
  activated dnd-kit sensor stops the propagation of the click that follows a drop until its listeners
  detach, 50 ms after the drag ends (`@dnd-kit/core`, `core.esm.js:1479` and `:1506`), and the tests
  pressed Undo 22 to 26 ms after releasing. No person clicks that fast. Both tests now wait 150 ms, and
  say why.

  **The proof.** The seven tests pass on the desktop-1280 project, with the existing field-map test.
  `MOVEMENT_CONTRACT.md` reads **12 gaps** across 11 surfaces, 19 met and 2 not applicable, and
  `test_movement_contract_audit.py` passes with 58 assertions. No product source changed, so the tenancy,
  inert-control, truncation, style-scope and route-cost gates see nothing new.

  **Negative runs,** each on a rebuilt `dist`:
  - **N1, an `onDragCancel` on the pipeline screen that commits the drop:** the palette test failed at
    `a cancelled palette drag sent a write to the server`.
  - **N2, the same on the artifact screen:** the library cancel test failed, a node added on release.
  - **N3, `addNode` recording no history entry:** the library Undo test failed, its Undo button disabled.
  - **N4, a field-list `onDragCancel` that reorders:** the field cancel test failed, the order changed on
    release.
  - **N5, a reorder recording no history entry:** the field Undo test failed, its Undo taking back the
    node's addition instead.
  - **N6, the `Map <property>` select mapping nothing:** the existing field-map test failed, `Expected:
    "asset_class"`, `Received: "name"`.
  - **N7, a field-mapping `onDragCancel` that maps:** the mapping test failed, a write sent.
  - **N8, a property-list `onDragCancel` that saves the order:** the property test failed, a write sent.
  - Restored: the thirteen matching browser tests and the audit test pass, and the three sources are byte
    for byte what they were.

  **What is left is 12, and they are behaviour that does not exist.** No way to move a node on the
  pipeline, artifact, ontology or platform canvas, or a configuration field in the inspector, with a
  single pointer and no drag; no Undo for a palette add, a field mapping, a property order, or an
  arrangement on either graph; and the xyflow cancels on the ontology designer and the platform graph,
  which V5 fixed in `VisualBuilder` and not in the library. None of them is a stage that works unmeasured.
- **V12 — A pane that moves keeps what was typed into it, on every screen with panes.**
  **Met** — the ontology manager's package form, the artifact review compose boxes and the
  AIP Logic agent runtime keep what was chosen and typed when their pane moves, the way V9
  made the pipeline node form keep it. Proven by six tests in `movement-contract.spec.ts`
  under `a pane that moves keeps what was typed into it`: the package form moved with
  `Move to…` and dragged by its grip, a review comment and proposal title, an agent
  instruction with its parameters, and one for each of the two search boxes below.

  **V9 left this open, and said so.** It fixed the one form it had measured and recorded
  that any other component holding unsaved state of its own, placed in a pane, would lose it
  on a move the same way. `PaneHost` renders one `Slot` per slot and each pane inside the
  slot it is in, so a pane that changes slot changes parent and React mounts what it holds
  afresh. This is the census V9 did not take, read from the source for every component the
  three `PaneHost` screens render inside a pane that can move; anchored panes cannot, and
  are left out.

  | Screen | Pane | Unsent input, and where it lived | On a move |
  | --- | --- | --- | --- |
  | Ontology Manager | Resources | package, owning and target project, new version, namespace — `OntologyPackagePanel` | **lost** |
  | Ontology Manager | Resources | dataset to generate from, all drafts shown — the screen | kept |
  | Workshop, AIP Logic, Investigations, Entity Resolution | Inspector | a review comment, a proposal title — `ArtifactReviewPanel` | **lost** |
  | the same four | Inspector, Node library | node name, description and fields; the library search — the screen | kept |
  | AIP Logic | Run results | agent, execution mode, instruction, parameters — `AgentRuntimePanel` | **lost** |
  | Pipeline Builder | Outputs | node label and fields (V9); execution policy — the screen | kept |
  | Pipeline Builder | Outputs | `Search outputs...`, an input with no state and no handler | **lost**, and it searched nothing |

  A tab, a table page or an open disclosure in a moved pane starts again where it starts.
  Those are where a person was looking rather than something they wrote, and none is held.

  **The fix is V9's, three more times.** Each component's unsent input lives in the screen,
  above the panes, and is handed back in, so a remount reads it instead of its defaults. The
  package form is one object; its reload still picks a first project and a first package,
  but only for what nobody has chosen, and `Create a package` — the empty string, and a
  real choice — is no longer read as no choice. A review draft is keyed by artifact, so a
  comment belongs to the artifact it was typed for. The agent runtime keeps its own when a
  caller passes nothing, because the Decision workspace renders it outside any pane.
  `Reset panes`, a hide and a collapse unmount the same way and read the same held state
  back; none of the three is separately asserted.

  **The two search boxes were decided by what their panes list.** The ontology manager's
  `Search resources...` sat in the top bar, outside the panes, with no value, no handler and
  no form: it kept its text through a move and did nothing with it. Discover lists every
  object type the person can see, uncapped — the ontology's resources, where Drafts holds
  generator drafts not yet applied — so the box now narrows Discover by name or id, is
  labelled `Search object types`, and says when nothing matches. Pipeline Outputs lists the
  graph's output nodes and the five builds the canvas loads, a window `TABLE_TRUNCATION.md`
  already holds as a gap, so a search there would read as a search of every build; it is
  gone. `audit_inert_controls` counts buttons and links, and could see neither.

  Still not gated, as V9 said: a component with unsaved state of its own, placed in a pane,
  loses it on a move. This census is a reading, taken once.

  **The proof.** The six tests pass on the desktop-1280 project. On the same build, so do the four
  tests nearest the change: `Reset panes leaves the graph and unsent input exactly as they were`,
  `ontology manager publishes and installs a governed package`, `a property row reorders without a
  drag` and `a released pointer resize is kept and survives a reload`. The search test finds one object
  type by its name and another by its id.

  **Negative runs,** each on a rebuilt `dist`:
  - **N1, the package panel keeping its own state again:** the move test failed at `moving the pane
    threw away a version that had not been sent`, `Expected: "2.7.1"`, `Received: "1.0.0"`.
  - **N2, the panel holding the form itself instead of the screen:** the drag test failed at `dragging
    the pane threw away a version that had not been sent`, with the same values.
  - **N3, a reload reading `Create a package` as no choice:** the move test failed at `moving the pane
    took back the choice to create a package`, because the reload had chosen the first package.
  - **N4, the review panel keeping its own draft:** the review test failed at `moving the pane threw
    away a proposal title that had not been sent`, `Received: ""`.
  - **N5, the agent runtime ignoring the draft it is handed:** the agent test failed at `moving the
    pane threw away an instruction that had not been run`, which received the default instruction.
  - **N6, a search that narrows nothing:** the search test failed at `the search did not narrow the
    object types to the one that matches`, with two rows where one was expected.
  - **N7, the Outputs search box put back:** the Outputs test failed at `a search box wired to nothing
    is back in the Outputs pane`, `Expected: 0`, `Received: 1`.
  - **N8, no note over a narrowed list:** the search test failed at `a narrowed list reads as every
    object type`, because it found no note.
  - **N9, a search by name only:** the search test failed at `the search did not match an object type
    by its id`, `Expected: 1`, `Received: 0`.
  - Restored: the ten tests pass, and the six sources are byte for byte what they were.

  N6 and N9 ran in a second pass. N6 was written against the filter before it matched name and id
  separately, so the first pass did not apply it. The id assertion and N9 were added in the second
  pass.

  **Gates.**
  - `TABLE_TRUNCATION.md` was regenerated. Only line numbers moved, and it still names 12 unfixed.
  - The style-scope baseline records `.compact-input` in three files, not four, because the Outputs
    box is gone.
  - `audit_inert_controls` still finds no inert control, and tenancy holds at 360.
  - No route exceeds its payload ceiling or sends more requests when it opens.
  - The fast tier passes 23 of 23.

  **Followed through, 2026-09-23: the run, not only the draft.** V12 held the agent
  runtime's draft above the panes, but not its run. The job, the task graph's stages, the
  result and whether the run was still going stayed in the panel, and so did the loop that
  drives a run and the poll that follows it. Moving Run results remounted the panel empty.
  A finished run's answer, tool trace and proposals were gone. A run still in flight
  finished into the panel the move had replaced, and the moved pane never showed it.
  - **The change.** The run and everything that drives it now live in `useAgentRun`. The
    builder calls the hook and hands the run in beside the draft. The Decision workspace
    renders the panel in no pane and passes nothing, and the panel runs its own there.
  - **The test.** `an agent run in flight lands in Run results after it moves, and its answer
    survives the next move`, in `movement-contract.spec.ts`. It holds the worker's
    `run-next` request, starts a run and moves Run results mid-run. It requires the moved
    panel still running, with its job state. It then releases the request and requires the
    answer in the moved panel. Last, it moves the pane back and requires the same answer and
    job.
  - **Also passing.** The draft test beside it and `AIP agent runtime exposes durable policy
    and citation evidence`, which runs a task graph through the hook.
  - **Negative runs,** on a rebuilt `dist`. With the builder passing no run, and with the
    panel preferring its own run to the one it is handed, the test failed at `moving the
    pane forgot a run that was still going`. Both fail before the answer is read, so the
    answer checks have run only against a working build. Restored, the three agent tests
    pass, and both sources are byte for byte what they were.
  - `TABLE_TRUNCATION.md` was regenerated; only line numbers in `VisualBuilder.tsx` moved.
    The fast tier passes 24 of 24.

- **V13 — A collapsed pane keeps what it holds.** **Met** — 2026-09-23. Proven by
  `a collapsed pane keeps what it holds` in `movement-contract.spec.ts`.

  **V12 recorded the gap.** It said a collapse unmounts a pane's contents the way a move
  does. `Pane` rendered nothing in place of a collapsed pane's body, so an expand mounted
  what it held afresh. Anything a component kept for itself started again: the review
  panel's tab, a table's page, an open disclosure, and an agent run's result. A move changes
  a pane's parent and has to remount. A collapse does not: the pane stays where it was.

  **The body is now hidden, not removed.** A collapsed pane's body carries the `hidden`
  attribute. It takes no space, no focus and no place in the accessibility tree, and it
  stays mounted. A `.pane-body[hidden]` rule keeps it hidden if a later rule gives pane
  bodies a `display`. No rule does today, so nothing yet tests that guard. The collapse
  button now names the body with `aria-controls` and says whether it is open with
  `aria-expanded`. It could not name the body before, because a collapsed pane had none.
  Hiding a pane still unmounts it, and so does moving one; V12's held state is still what
  brings a moved pane's input back.

  - **The test.** It opens the Workshop, switches the Inspector's review panel to Proposals
    and collapses the Inspector. It requires the review panel hidden and its tabs gone from
    the accessibility tree. It then expands the Inspector and requires Proposals still
    selected. It also reads `aria-expanded`, `true` and then `false`, on the two controls.
    It passes on desktop-1280. So do all 57 tests in `movement-contract.spec.ts`,
    `pane-layout.spec.ts` and `shell-widths.spec.ts`. No default layout collapses a pane, so
    no other test starts with a collapsed body.
  - **Negative runs,** each on a rebuilt `dist`:
    - with the body removed on collapse again, the test failed at `expanding the pane
      mounted the review panel afresh, back on Comments`: `aria-selected` was `false`;
    - with the body never hidden, it failed at `a collapsed pane still shows what it holds`;
    - with no `aria-expanded`, it failed at `the collapse control does not say its pane is
      open`.

    Restored, the seven collapse and move tests in `movement-contract.spec.ts` pass, and
    `Pane.tsx` is byte for byte what it was.
  - **Gates.** `TABLE_TRUNCATION.md` was regenerated; only line numbers in `Pane.tsx`
    moved. The style-scope, pane-layout, movement-contract, inert-control and
    drag-affordance audits hold, and the fast tier passes 24 of 24.

## Order and size

| Step | Touches | Commits |
| --- | --- | --- |
| V1 | `oms/audit_movement_contract.py`, test, reference, baseline, registries | 1 |
| V2, V3 | `components/layout/Pane.tsx`, spec | 1 |
| V4, V5 | `workspaces/VisualBuilder.tsx`, spec | 1–2 |
| V6 | `workspaces/PipelineBuilder.tsx`, spec | 1 |
| V7 | `components/canvas/PipelineCanvas.tsx`, spec | 1 |
| V8 | `PipelineBuilder.tsx`, `PlatformGraph.tsx`, `OntologyManager.tsx`, spec | 1–2 |
| V9 | spec | 1 |
| V10 | `components/canvas/PipelineCanvas.tsx`, `styles.css`, spec, truncation reference | 1 |
| V11 | `oms/audit_movement_contract.py`, spec, reference, baseline | 1 |
| V12 | `OntologyPackagePanel.tsx`, `OntologyManager.tsx`, `ArtifactReviewPanel.tsx`, `AgentRuntimePanel.tsx`, `VisualBuilder.tsx`, `PipelineBuilder.tsx`, spec, truncation reference, style-scope baseline | 1 |
| V13 | `components/layout/Pane.tsx`, `styles.css`, spec, truncation reference | 1 |

Every test is run once against a build with the thing it defends removed, and every cancel
test first proves the drag was live.

## Deliberately not here

- **Typed drop targets with effect labels** ("Use 12 flights as chart input"). The research's
  P1. Needs a census of what each droppable accepts before any label can be honest.
- **A nested operational layout editor** — sections, rows, proportions. P1, and a design
  project, not a defect.
- **Saved views with private and global defaults.** P1. Object Explorer's `Save view` is
  the one real saved view today and has no audience choice; that is recorded above and
  left for its own goal.
- **Map camera stability, rendering cost under repeated resizes, narrow-screen
  presentation.** P2, each with its own measurement.
- **Undo for a multi-node drag.** Was listed here to ride with `GOAL_PANES` M5, and it
  did: `moveNodes` commits a drag of any number of pipeline nodes through
  `commitPositions`, one history entry, so one `Undo move` puts every node back.
  (Corrected 2026-09-23; this line still said it was not built.)

## What this is not

Not a restatement of the research. Its visual references and product observations stand
where they are; this goal cites them and copies neither.

Not a claim that the contract's other stages are met. Discover, start, preview, traverse,
reject and commit are not measured here; V1's census is where they would be added, one
column at a time, once each has a test that can fail.

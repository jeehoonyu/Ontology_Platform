# Goal — A move you can take back, and a save that says what it keeps

Stated 2026-09-12, from [`FOUNDRY_UI_RESEARCH_2026-09-12.md`](FOUNDRY_UI_RESEARCH_2026-09-12.md),
which extends the [platform review](FOUNDRY_PLATFORM_UI_REVIEW_2026-09-11.md). Runs
alongside [`GOAL_PANES_2026-09-11.md`](GOAL_PANES_2026-09-11.md), open at M5, and
[`GOAL_HONEST_UI_2026-09-11.md`](GOAL_HONEST_UI_2026-09-11.md), open at N5.

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
- **V6 — A pipeline node move can be taken back.** **Open** — one Undo reverses one
  committed move, re-saving the previous positions. A drop that moved nothing records
  nothing, which the drop handler already guarantees and the test holds.
- **V7 — The preview lands where the drop does, at every zoom.** **Open** — a pipeline
  node's live transform is divided by the stage's scale, so the preview and the landing
  agree within a pixel at 0.55, 1 and 1.35. Proven by the keyboard measurement above,
  turned into an assertion at all three zoom levels; today it reads 48.4 against 88 at the
  floor.
- **V8 — Every save and reset says which scope it touches.** **Open** — the two
  Pipeline Builder controls stop sharing a noun; Platform Graph's control says what it
  keeps and confirms it; the ontology designer either keeps an arrangement as a personal
  preference or stops inviting one. Each proven by a test that reloads.
- **V9 — Resetting a layout touches only the layout.** **Open** — `Reset layout` leaves the
  artifact's nodes and any unsent input exactly as they were. The research's fourth
  scenario; nothing asserts it today.

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
- **Undo for a multi-node drag.** Rides with `GOAL_PANES` M5, which introduces the
  multi-node drag.

## What this is not

Not a restatement of the research. Its visual references and product observations stand
where they are; this goal cites them and copies neither.

Not a claim that the contract's other stages are met. Discover, start, preview, traverse,
reject and commit are not measured here; V1's census is where they would be added, one
column at a time, once each has a test that can fail.

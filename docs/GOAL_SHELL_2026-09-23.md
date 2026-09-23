# Goal — The screen you get at the width you have

Stated 2026-09-23. Follows [`GOAL_PANES_2026-09-11.md`](GOAL_PANES_2026-09-11.md), met through
M7, and [`GOAL_MOVEMENT_2026-09-12.md`](GOAL_MOVEMENT_2026-09-12.md), met through V12. Both were
judged by tests on four widths — 375, 768, 1280, 1600 — and by a render sweep at the same
four. This goal comes from opening the built app at the widths in between, which nobody had.

## What was seen, and the numbers

The served build of 2026-09-18, a fresh database, the asset-reliability scenario bootstrapped,
`/workspace/pipeline`, no console errors at any width.

### Between 901 and 1100 pixels wide, the first screen is empty

| Width | Sidebar height | Workspace begins at |
| --- | --- | --- |
| 800 | 62 px | 62 px |
| 900 | 62 px | 62 px |
| **1000** | **700 px — the whole viewport** | **700 px** |
| **1024** | **768 px — the whole viewport** | **768 px** |
| **1100** | **700 px — the whole viewport** | **700 px** |
| 1101 | 700 px, beside the workspace | 0 px |

At 1024×768 — an iPad in landscape, a laptop with the sidebar of a browser open — the page is a
dark bar with the brand centred in it and nothing else. Every workspace is one full scroll
down. Two rules disagree, and the widths where both apply are the gap:

- `@media (max-width: 1100px)` stacks the sidebar into a top bar and gives `.app-shell` one
  column.
- `@media (min-width: 901px)` gives `.sidebar` and `.workspace` `height: 100vh`, which is right
  for the side-by-side layout it was written for and wrong for a bar.

The render sweep checks 768 and 1280. Neither is in the band. **A sweep at four widths is a
claim about four widths**, and this is the case that shows it.

### The pipeline builder reserves 330 px for a column that is always empty

At 1280 wide the workspace is 994 px. `.pipeline-workbench-page .builder-shell` is
`minmax(760px, 1fr) 330px`; the shell has **one child**, `.builder-main`, and nothing has
rendered in the second track since the inspector became a pane. The four panes share 671 px:

| Pane | Width at 1280 |
| --- | --- |
| Add data / transforms | 220 px |
| **Pipeline** — the canvas | **169 px** |
| Outputs | 220 px |
| empty second track | 308 px |

The one surface a person came to work on is the narrowest thing on the screen, and the space it
lacks is blank beside it. Making panes movable did not fix this and could not: the host row is
inside the track that is too small.

### Pane titles clip at their default width

`Add data / transforms` and `Outputs` render with an ellipsis at 220 px, because the header holds a
grip, a collapse button, a `Move to…` select and a hide button before the title gets any room.
The title is what tells a person which pane they are about to move.

### The status strip says "loading" when nothing is

With no pipeline selected the strip reads `loading`, from
`canvas?.validation.status || "loading"`. Nothing is loading; there is no canvas. That is the
class of claim [`GOAL_HONEST_UI_2026-09-11.md`](GOAL_HONEST_UI_2026-09-11.md) removed from
tables and controls, still standing in a badge.

## Design

**Measure at every width, not four.** A browser test walks the widths from 320 to 1920 in
steps that land on the breakpoints and on either side of each — 640, 700, 760, 900, 901, 1000,
1100, 1101, 1200, 1500 — plus 1024 and 1366, which are what real screens are. At each width,
on every screen with panes, it asserts three things:

1. the workspace's first content begins inside the first viewport;
2. the widest pane on the screen is the canvas, and the pane host row fills the track it is in
   to within the gutter;
3. no pane title is clipped — `scrollWidth` equals `clientWidth`.

The widths and the three assertions are the gate. They are cheap: one page per width, no data
beyond the bootstrap the drag tests already use.

**One rule per layout.** The `min-width: 901px` block becomes `min-width: 1101px`, so
`height: 100vh` applies only where the sidebar stands beside the workspace. The stacked bar
gets its own height from its content, which it already does below 901.

**Drop the track nothing fills.** `.pipeline-workbench-page .builder-shell` becomes one column.
The pane host takes the width, and the canvas pane's default share is set so that it is the
widest pane at 1280 and above.

**The pane header gives the title the room first.** The controls collapse into one `⋯` menu
button holding Collapse, Move to…, and Hide, on a pane narrower than 280 px; wider than that
they stay as they are. The grip stays outside the menu, because the grip is the drag. The
menu is a button and a list, reachable by keyboard and a finger, and the drag census does not
change: nothing new drags.

**A badge says what is true.** With no canvas, the strip reads `No pipeline selected`. With one,
it reads the validation status, as it does now.

## Gates this must clear

| Gate | What it will say |
| --- | --- |
| `audit_pane_layout` | movable count unchanged at 11 of 24; no pane becomes a fixed track |
| `audit_drag_affordances` | no new mechanism; `Pane.tsx` keeps its `SENSOR_BACKED` entry |
| `audit_movement_contract` | the pane-move and pane-resize rows keep their evidence |
| `audit_style_scope` | `.pane-menu` declared shared in the first commit |
| `audit_inert_controls` | the `⋯` button is wired; the count stays at zero |
| `audit_route_cost` | no route sends one more request |
| render sweep | still green at 375, 768, 1280, 1600, and now the sweep above at 12 more |

## Conditions

- **S1 — Measure the widths in between, and make the measurement a gate.** **Met** —
  `shell-widths.spec.ts`, the width list above, the three assertions, on every screen with
  panes. Its first run is expected to fail at 1000, 1024, 1100 on assertion 1, at 1280 and
  above on the pipeline builder on assertion 2, and at 220 px panes on assertion 3. Those
  failures are the record; the test is committed red before any fix, so each fix has a test
  that was seen to fail.

  **What was built.** `SHELL_WIDTHS` is 320, 375, 640, 700, 760, 768, 900, 901, 1000, 1024,
  1100, 1101, 1200, 1280, 1366, 1500, 1600 and 1920: the twelve widths above, the four the
  projects already visit, and the two ends of the walk. 1024 and 1366 are measured at 768
  high and the rest at 700. The three screens with panes are the pipeline builder, the
  ontology manager and Workshop, which stands for the four artifact screens that share its
  layout. Each width is reloaded from `Reset panes` and judged with soft assertions, so one
  run reports every width that fails. Assertion 1 is read as "the workspace begins in the top half of the
  first viewport", because a first screen that is mostly sidebar is the same defect as one
  that is all of it. Assertion 2 compares the panes in the row, since a bottom pane spans the
  screen by design, and holds the pane host to the workspace's content width within 24 px.

  The check registry named no browser spec, so it gained `BROWSER_GATES`.
  `audit_check_coverage` now fails if a named spec is deleted, or if its `SHELL_WIDTHS`
  stops parsing as one ascending list, and `oms/test_check_homes.py` holds both. The browser
  suite is run by hand, and the declaration says so.

  **The first run, before any fix.** It came back redder than predicted:

  | Screen | Assertion | Fails at |
  | --- | --- | --- |
  | Pipeline builder | 1, workspace in the first screen | 901, 1000, 1024, 1100: the workspace begins at 700 of 700, and at 768 of 768 |
  | Pipeline builder | 2, canvas the widest | 901 (132 px), 1101 (64), 1200 (139), 1280 (200), against the 220 px library |
  | Pipeline builder | 2, host fills the workspace | every width from 901 to 1920: 618 of 869 at 901, 686 of 950 at 1280, 1303 of 1590 at 1920 |
  | Pipeline builder | 3, no clipped title | 320 (`Add data / transforms`, 108 of 125 px), then every width from 760: the same title 51 of 125 and `Outputs` 40 of 46; at 1101 also `Pipeline`, 4 of 45 |
  | Ontology manager | 1 | 901, 1000, 1024, 1100 |
  | Ontology manager | 2 and 3 | nowhere |
  | Workshop | 1 | 901, 1000, 1024, 1100 |
  | Workshop | 2, canvas the widest | 320 (304 px against a 310 px inspector), 760 (150), 768 (158), 900 (290), 901 (291), 1101 (205), 1200 (304) |
  | Workshop | 3 | every width: `Node library`, 60 of 71 px |

  Four findings the goal did not predict. The band begins at 901, not 1000: the rule that
  stacks the sidebar and the rule that makes it full height overlap from 901 to 1100. The
  pipeline's empty track fails from 901, because the `min-width: 901px` block, which comes
  later in the stylesheet, re-splits the builder there. Workshop's canvas loses to its
  inspector below 1280. And Workshop's side panes keep 238 and 310 px even when the panes
  stack, including at 320: M7's declared widths are written as inline styles, which the
  stacking rule cannot override. So `Node library` is clipped at every width, and at 320 the
  inspector is wider than the canvas above it.
- **S2 — No width gives the sidebar a screen to itself.** **Met** — the `min-width: 901px`
  block moves to 1101. Proven by S1 at 1000, 1024 and 1100, and shown to fail again with the
  block moved back.

  One line in `styles.css`, with a comment saying why the block starts at 1101. Assertion 1
  now passes at all eighteen widths on all three screens, and the ontology manager passes
  every assertion at every width. Between 901 and 1100 the pipeline builder also takes the
  one-column rules the 1100 block already gave it, because the 901 block is no longer there
  to re-split it. The remaining failures on the pipeline builder and Workshop belong to S3
  and S4.

  **Negative run,** on a rebuilt `dist`: with the block back at `min-width: 901px`, the spec
  failed on all three screens at `the workspace begins at 700px of a 700px first screen` for
  901, 1000 and 1100, and `768px of a 768px` for 1024. Restored, no screen reports it at any
  width, and `styles.css` is byte for byte what it was. The served-shell and legacy sweeps
  pass at the four project widths, none of which is in the band. Their one failure, on every
  project, is the bundle carrying no `build-provenance.json`, because this `dist` was built
  with `vite build` rather than `measure_browser_evidence.py --build`.
- **S3 — The pipeline canvas is the widest pane at every desktop width.** **Met** — the
  empty 330 px track goes; the canvas takes the share. Proven by S1 assertion 2 at 1101 and
  above. The numbers before: canvas 169 px of 994 available at 1280.

  **Two changes, because S1 found the pipeline was not the only screen.**
  `.pipeline-workbench-page .builder-shell` is one column, both in its base rule and in the
  1101 block, and the pane host takes the width. In `paneLayout.ts` a side slot's declared
  width becomes a ceiling rather than a size: `sideWidth` keeps a width a person chose
  exactly, and caps a declared one at a third of the row after its splitters and gaps. That
  leaves the canvas at least as wide as either side. `PaneHost` measures the row before
  paint and passes the width as `--slot-width`, not an inline `width`, so the stacking rule
  below 700 px can override it at last. A layout saved by an older build stored the
  declared width as if someone had chosen it, so a stored width equal to the declared one
  is read as no choice.

  | Width | Pipeline: library · canvas · outputs | Workshop: library · canvas · inspector |
  | --- | --- | --- |
  | 760 | 220 · 241 · 220 | 232 · 234 · 232 (was 238 · 150 · 310) |
  | 1101 | 220 · 328 · 220 (canvas was 64) | 238 · 265 · 250 (was 238 · 205 · 310) |
  | 1280 | 220 · 507 · 220 (canvas was 169, then 200 at 700 high) | 238 · 384 · 310 |
  | 1920 | 220 · 1147 · 220 | 238 · 1024 · 310 |

  At 1280 and above the cap does not bind on any screen, so Workshop's inspector keeps the
  310 px M7 gave its forms. The ontology manager's Resources pane keeps 260 from 1280 up and
  gives up to 34 px of it below.

  **The proof.** Assertion 2 passes at all eighteen widths on all three screens. What still
  fails is assertion 3 alone, the titles, which is S4. On the same build, the 84 tests in
  `pane-layout`, `movement-contract`, `multi-node-drag`, `truncation-sites`,
  `drag-affordances`, `touch-authoring` and `concurrent-drags` pass on the desktop-1280
  project. They include every splitter, width-preset and `Reset panes` test.

  **Negative runs,** each on a rebuilt `dist`:
  - **N1, the empty track back in the 1101 block:** the pipeline builder failed at `the pane
    host is 550px of 771px the workspace has` at 1101, and at every width up to `1303px of
    1590px` at 1920.
  - **N2, a declared width that is never capped:** Workshop failed at `Canvas is 205px,
    narrower than Inspector at 310px` at 1101, and at 760, 768, 900, 901 and 1200.
  - **N3, the width written as an inline style again:** Workshop's titles clipped from 320 to
    700, where the slots stack. `Node library` and `Inspector` had 0 px each at 320.
  - Restored, only assertion 3 fails, and the three sources are byte for byte what they were.
- **S4 — A pane title is never clipped at the pane's default width.** **Met** — the `⋯` menu
  below 280 px. Proven by S1 assertion 3 on every pane screen, and by a tap test on the
  390×844 touch viewport that opens the menu and moves a pane from it, so the control beside
  the drag is still reachable when it is behind a menu.

  **What was built.** Below 280 px, Collapse, `Move to…` and Hide move behind one `⋯` button
  named `Pane actions for <title>`. The grip stays in the header, because it is the drag. The
  menu opens in the flow under the header, not as a popover over the body, so a collapsed
  pane, which has no body, still shows all of it. It holds the same three controls with the
  same names, and only one set is ever rendered, so a keyboard, a screen reader and a test
  reach the same select either way. Escape closes it and puts the focus back on its button.

  **280 was not enough on its own.** At 320 the pipeline library pane is 287 px, and beside
  the three controls `Add data / transforms` still lost 17 of its 125 pixels. So a pane also
  takes the menu wherever its whole title and the three controls do not fit side by side.
  The controls are measured while they are in the header, and that width is kept, so a pane
  whose menu has made room does not measure the room as a reason to put them back.

  **The tap test moved to a tablet.** At 390×844 the panes stack at 346 px, and every title
  fits beside its controls, so there is no menu to tap. The test runs at 1024×768 with touch,
  where the side panes are 220 px. It is in `pane-layout.spec.ts` under `a narrow pane's
  controls are one tap away`, in three tests:
  - with a tap, the menu opens and moves the library pane, and the title is not clipped
    beside it;
  - from the keyboard, Enter opens the menu, Tab reaches its first control, and Escape
    closes it and returns the focus;
  - Hide works from the menu, and the Panes list brings the pane back.

  The four desktop tests that choose `Move to…` on a pane now 220 px wide open its menu
  first: three in `movement-contract.spec.ts` and one in `pane-layout.spec.ts`.

  `.pane-menu` is not declared shared, although the goal's gate table asks for it.
  `audit_style_scope` counts the files whose `className` names a class, and only
  `Pane.tsx` names this one, even though every pane screen renders it. A one-file class
  declared shared only produces a note, and the next `--set-baseline` erases it.

  **The proof.** `shell-widths.spec.ts` passes at all eighteen widths on all three screens:
  S1's gate is green. So do the four tests above, which include a fourth: at 320, a pane its
  title crowds keeps its menu open and the title whole. On the same build, 124 tests in
  `movement-contract`, `multi-node-drag`, `truncation-sites`, `drag-affordances`,
  `touch-authoring`, `concurrent-drags`, `inert-controls` and `evaluator` pass on the
  desktop-1280 project, with one skipped. In one of six runs of the shell spec, one step
  failed a visibility wait with `element(s) not found`. The output that would have named the
  step was overwritten, and the next five runs, nine repetitions among them, passed.

  **Negative runs,** each on a rebuilt `dist`:
  - **N1, the menu by width alone, as first designed:** the spec failed at `320px: pane
    titles clipped: Add data / transforms (125 in 108)`.
  - **N2, no menu at all:** the tap test failed at `the title is still clipped beside its
    controls`, `Received: 74`.
  - **N3, the grip put away with the controls:** failed at `the grip went into the menu; it
    is the drag and stays in the header`.
  - **N4, Escape doing nothing in the menu:** failed at `Escape did not close the menu`.
  - **N5, the controls measured while they are behind the menu:** the crowded-pane test
    timed out tapping the menu button. With its own button measured as the controls, the
    pane put them back, found itself crowded and took the menu again, over and over, so
    the button never held still long enough to tap. The test was written after this
    mutation passed the other tests in a first round.
  - Restored, the seven tests pass, and `Pane.tsx` is byte for byte what it was.

  **Gates.** `INERT_CONTROLS.md` reads 0 inert of 333: the `⋯` button is the one new control,
  and it is wired. `TABLE_TRUNCATION.md` moved line numbers only. The movable pane count
  holds at 11 of 24, `Pane.tsx` keeps its drag entry, and the fast tier passes 23 of 23.
- **S5 — The status strip says "loading" only while something loads.** **Open** — `No pipeline
  selected` with no canvas. Proven by a test that opens the pipeline builder with no graph and
  reads the strip, shown to fail with the fallback restored.
- **S6 — 1024 and 1366 stay in the sweep for good.** **Open** — the two widths join the
  Playwright projects so the existing render sweep, route sweep and touch tests run there
  too, and the check registry names them. Proven by `audit_check_coverage` seeing the
  projects.

## Order and size

| Step | Touches | Commits |
| --- | --- | --- |
| S1 | `frontend/tests/shell-widths.spec.ts`, check registry | 1, committed red |
| S2 | `styles.css` one media query | 1 |
| S3 | `styles.css` `.pipeline-workbench-page .builder-shell`, `Pane.tsx` default sizes | 1 |
| S4 | `Pane.tsx`, `styles.css` (`.pane-menu`, declared shared), spec | 1–2 |
| S5 | `PipelineBuilder.tsx`, spec | 1 |
| S6 | `playwright.config.ts`, registry, baselines that record widths | 1 |

Every fix is preceded by the assertion that catches it, seen red, and every one is shown to
fail again with the fix removed.

## Housekeeping the loop will ask for first

`audit_iteration_state --status` names re-measuring `extensibility-baseline.json`, 48 days old,
as the next step, ahead of any condition here. That is the ordering the loop states and this
goal does not jump it.

Done 2026-09-23, before S1. The re-measurement closed K5 of
[`GOAL_CONTINUOUS.md`](GOAL_CONTINUOUS.md) — its one coupling was a `typeof` guard — and found
that `audit_ratchet_motion` had read no history on Windows. Both are recorded there. The seven
other baselines past thirty days were re-measured next; every ceiling held, one floor rose
from 17 to 33, and the loop's next step is an open condition again.

## What this is not

Not a redesign of the shell. Two media queries disagree on a band of widths; the fix is to
make them agree. The desktop layout above 1100 and the bar below 901 are both kept as they are.

Not a new pane feature. Nothing here moves that did not move before; the pane goal's eleven
movable regions stay eleven.

Not a claim about every width. Twelve more widths join four. A width not in the list is still
a width nobody has looked at, and the list is in one place so the next one is one line.

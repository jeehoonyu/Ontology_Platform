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

- **S1 — Measure the widths in between, and make the measurement a gate.** **Open** —
  `shell-widths.spec.ts`, the width list above, the three assertions, on every screen with
  panes. Its first run is expected to fail at 1000, 1024, 1100 on assertion 1, at 1280 and
  above on the pipeline builder on assertion 2, and at 220 px panes on assertion 3. Those
  failures are the record; the test is committed red before any fix, so each fix has a test
  that was seen to fail.
- **S2 — No width gives the sidebar a screen to itself.** **Open** — the `min-width: 901px`
  block moves to 1101. Proven by S1 at 1000, 1024 and 1100, and shown to fail again with the
  block moved back.
- **S3 — The pipeline canvas is the widest pane at every desktop width.** **Open** — the
  empty 330 px track goes; the canvas takes the share. Proven by S1 assertion 2 at 1101 and
  above. The numbers before: canvas 169 px of 994 available at 1280.
- **S4 — A pane title is never clipped at the pane's default width.** **Open** — the `⋯` menu
  below 280 px. Proven by S1 assertion 3 on every pane screen, and by a tap test on the
  390×844 touch viewport that opens the menu and moves a pane from it, so the control beside
  the drag is still reachable when it is behind a menu.
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
that `audit_ratchet_motion` had read no history on Windows. Both are recorded there.

## What this is not

Not a redesign of the shell. Two media queries disagree on a band of widths; the fix is to
make them agree. The desktop layout above 1100 and the bar below 901 are both kept as they are.

Not a new pane feature. Nothing here moves that did not move before; the pane goal's eleven
movable regions stay eleven.

Not a claim about every width. Twelve more widths join four. A width not in the list is still
a width nobody has looked at, and the list is in one place so the next one is one line.

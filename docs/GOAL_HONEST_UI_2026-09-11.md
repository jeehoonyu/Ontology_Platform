# Goal — A control that does nothing, and a table that hides rows

Stated 2026-09-11, from [`FOUNDRY_PLATFORM_UI_REVIEW_2026-09-11.md`](FOUNDRY_PLATFORM_UI_REVIEW_2026-09-11.md)
and its [companion canvas plan](FOUNDRY_UI_IMPROVEMENT_PLAN_2026-09-11.md). Runs alongside
[`GOAL_PANES_2026-09-11.md`](GOAL_PANES_2026-09-11.md), which is open at M5.

## Why these two, out of a review that lists twenty-four workspaces

The review covers 61 launcher entries and proposes a target layout for every local
workspace. Most of that is design work whose value cannot be measured until it is built.
Two of its findings are different in kind: they are defects that exist today, are true of
many screens at once, and can be counted before anything is designed.

Both are the same defect wearing different clothes. **The interface asserts something the
code does not do.**

- A `<button>` with no handler renders a hover state, takes a focus ring and accepts a
  click. Nothing happens. A person cannot tell it from a control that is broken, slow, or
  waiting on a network call they should keep waiting for.
- A table that renders forty of five thousand rows, with no row forty-one and no sentence
  saying so, is read as the answer to the question. The rows are not slow or pending. They
  are gone, and the screen does not say it.

Everything else in this repository's discipline is about the gap between a claim and a
measurement. These are that gap rendered in the product rather than in a document, so
they get the same treatment: count first, gate the count, then fix.

## What the census says

Both numbers below are measured, not estimated, and both were measured before anything
was changed.

### Controls that do nothing — `oms/audit_inert_controls.py`

| | |
| --- | --- |
| `<button>` and `<a>` elements in the frontend | **335** |
| carrying no handler, no `href`, no `type="submit"`, no spread, no `disabled` | **17** |
| of those, inside a `.map()` — one source line, many dead buttons | **3** |

Concentrated rather than scattered: ten of the seventeen are in `OntologyManager.tsx`
(`SQL console`, `Preview`, `Object mode`, `Guide`, `Overview`, `Files`, `Previous`,
`Next`, `Actions`, `Open in`), three are the pipeline canvas's `+`, `−` and `Fit`, and the
three repeating sites are the pipeline's tab strip, its six-button utility rail
(`R S L B C D`), and the canvas toolbar's two-letter action buttons — which are drawn from
server-supplied toolbar groups, so their count on screen is whatever the server sends.

The scan reads `disabled` as wired on purpose. The review's criterion is that a control
*works or explains why it is unavailable*, and a disabled control with a title is the
explanation. The defect is silence, not absence.

### What the shared table hides — `frontend/src/components/data/DataDisplay.tsx`

`DataTable` is the product's table. **75 call sites across 16 files.** It truncates three
ways, and says none of them:

```tsx
const columns = useMemo(() => {
  const seen = new Set<string>();
  for (const row of safeRows.slice(0, 10)) Object.keys(row || {}).slice(0, 8).forEach(...)
  return Array.from(seen);
}, [safeRows]);
...
{safeRows.slice(0, 40).map((row, index) => (
```

1. **Rows past the fortieth are not rendered.** No count, no paging, no scrollbar that
   reaches them — the fortieth row is the last row as far as the screen is concerned.
2. **Columns are discovered from the first ten rows.** A field that first appears in row
   eleven has no column, so its value is invisible in *every* row, including the ten that
   were sampled.
3. **At most eight keys are taken per sampled row.** A row with twelve fields contributes
   eight.

The second is the worst of the three, because it is silent even when the data is small
enough that nothing looks truncated. Forty rows of eleven fields render as forty complete
rows with three fields missing, and nothing on screen distinguishes that from a dataset
that has eight fields.

One call site out of seventy-five already does the right thing by accident:
`PipelineBuilder.tsx` slices to twenty-five under a summary reading
`{issues.length} contract issue{...}`, so the true count is beside the partial list. That
is the shape the other seventy-four need, and it should come from the component rather
than from each caller remembering.

`DataTable` also takes an optional `specs` so cells can be drawn by their declared
ontology type. **Zero of the seventy-five call sites pass it.** That is a separate finding
and is N6 below, not part of the truncation work.

## Design

### A control acts, links, submits, or says it is unavailable

There is no fifth option, and the audit is the thing that says so. Each of the seventeen
resolves one of four ways, and *which* way is a judgement per control, not a policy:

- **Wire it** where the behaviour exists and is merely unconnected. The canvas `+`, `−`
  and `Fit` are this: `PipelineCanvas` already receives `zoom` as a prop, so the
  controls are three lines and a handler each.
- **Disable it with a reason** where the behaviour is real but unavailable in this state.
- **Make it a link** where it navigates.
- **Delete it** where it was never anything. The utility rail's `R S L B C D` is six
  letters in a column with no meaning attached to any of them; drawing nothing is more
  honest than drawing six buttons.

The gate does not care which. It cares that none of them stays a `<button>` that renders
and does nothing.

### The empty handler is the gate's own evasion path, and is refused

`onClick={() => {}}` satisfies every rule that looks for a handler. It is the cheapest way
to clear this gate and it makes the census report a number that is *wrong* rather than
merely high, which is worse. So a handler whose body is empty counts as inert, and the
test asserts that against `() => {}`, `()=>{ }`, `() => undefined` and `noop`.

Writing that rule found a defect in the scan itself. The first version matched an opening
tag with `<(button|a)[^<>]*?>`, and `onClick={() => run()}` contains a `>` inside the
arrow — so the tag ended at `onClick={() =`, every label was wrong, and the empty-handler
rule could never fire because it had already been cut off from the body it needed to see.
The scanner now walks the tag counting braces and quotes. It finds 335 controls where the
regex found 331. **The rule that catches the evasion is what found the hole in the rule.**

### A table says what it is showing

`DataTable` gains, in this order:

- **A caption line with the true count** whenever it renders fewer rows than it was given:
  `Showing 40 of 5,213 rows`. This is the smallest change and the one that makes the
  remaining ones optional rather than urgent — a limit a person can see is a limit, and a
  limit a person cannot see is a lie.
- **Column discovery over every row**, not the first ten, and no eight-key cap. This is
  the only one of the three truncations with no defensible reason: the sample was a
  performance guess about a component that already renders at most forty rows.
- **Paging**, so the rows past the limit are reachable rather than merely counted.

The count comes from the component, not from each of seventy-five callers, because a
convention seventy-five places must remember is a convention that will be wrong in some of
them and nobody will know which.

### What is deliberately not here

**Not the full data grid.** The review asks for column visibility, reorder, resize, pin,
sorting, filtering, selection and virtualization. That is a large component and it is
worth building, but it is worth building *after* the existing table stops hiding things,
because a grid rolled out over seventy-five call sites while the truth problem is open
just moves the problem into a bigger file.

**Not the twenty-four workspace layouts.** Those depend on the pane work, which has its
own goal and its own ratchet.

**Not a claim that a wired control is a good control.** N3 makes `Fit` fit. Whether
fitting is the right behaviour at three zoom levels is the canvas work in the companion
plan, and it is measured there.

## Gates this must clear

| Gate | What it will say |
| --- | --- |
| `audit_inert_controls` | new, N1; the inert count may fall and never rise, per file as well as in total |
| `audit_table_truncation` | new, N4; the shared table may not drop a row or a column without rendering the true count |
| `audit_ui_primitives` | `DataTable`'s user count; adding a caption must not fork it into a second table |
| `audit_style_scope` | the caption's class is shared across sixteen files — declared in the first commit |
| `audit_route_payload` / `audit_route_cost` | a caption is text; it may add zero requests and must stay inside the byte ceiling |
| `audit_ui_states` | a table given no rows still shows `EmptyState`, not a caption reading `0 of 0` |
| render sweep | 375, 768, 1280, 1600 — a caption that wraps into two lines on a phone is still a caption |

## Conditions

- **N1 — Count the controls that do nothing.** **Met** — `oms/audit_inert_controls.py`,
  [`INERT_CONTROLS.md`](INERT_CONTROLS.md) generated from the scan, a baseline, and
  `test_inert_controls_audit.py` at 46 assertions. Ceiling, not floor: 17 of 335, and the
  number may only fall. The refusals are asserted against synthetic tags — a bare button,
  a `title`-only button, an anchor with no `href`, a multi-line opening tag, and the four
  spellings of an empty handler — because a gate that has never refused anything is a
  number printed beside a claim.
- **N2 — Wire, disable, link, or delete every one of the seventeen.** **Met** — the census
  is at **0 of 318** and the ceiling is reset to zero. Three were wired and fourteen
  deleted, and the split is the finding: only three of the seventeen had any behaviour to
  connect. Proven by `inert-controls.spec.ts`, three tests, all shown to fail against a
  build with the handlers removed and the deleted strip restored.

  **The canvas zoom controls were dead while a working copy of the same three sat in the
  document action row**, between `Save layout` and `Delete node`. So the obvious place to
  zoom did nothing and the place that worked was where a person looks for Save. The
  handlers moved onto the canvas with their clamp, which is where a viewport control
  belongs; the row now holds only document actions.

  The other fourteen had nothing behind them: a `Guide / Overview / Files` tab strip with
  one drawn as selected, `Previous` and `Next` on a walkthrough with no step state, a
  `SQL console / Preview / Object mode` footer, `Actions` and `Open in` beside two real
  buttons, a `Create new link type` offered by an empty state that could not create one, a
  `Graph / Proposals / History` nav whose two other names are real tabs elsewhere, and a
  six-button rail reading `R S L B C D`. Deleting them removed 22 lines of CSS with no
  remaining user and one fixed-track pane region.

  The canvas toolbar was the one that could not simply go. It drew server-supplied action
  names as two-letter buttons with the full name in a `title` and no handler — unreadable
  and dead at once. The names are real information the canvas state carries, so they stay,
  as the labels they are rather than as the controls they were not.

  **Turning those buttons into labels broke the keyboard, and the render sweep caught it.**
  The strip is `overflow-x: auto`, and the dead buttons were the only focusable thing
  inside it — so removing them left a region that scrolls and no keyboard can reach, which
  axe reports as a serious `scrollable-region-focusable` violation on the pipeline at two
  widths. It is a focusable labelled region now, the same shape `DataTable`'s wrapper
  already uses. Worth stating plainly: deleting a false affordance removed a real one,
  because the false affordance had been carrying it. Nothing in the inert-control census
  could have predicted that, and nothing but the accessibility sweep would have found it.
- **N3 — The table says how many rows it is showing.** **Met** — a `<caption>` reading
  `Showing 40 of 60 rows`, rendered only when rows were actually dropped. Proven by
  `data-table.spec.ts`, two tests: one against a sixty-record fixture, one asserting a
  complete table stays silent, because a caption on a three-row table saying `3 of 3`
  teaches a person to stop reading captions and costs exactly what the first one buys.

  **N5's column half moved here.** Stating a row count while columns are still dropped
  silently is a half-true caption, and the column fix is one line. The fixture makes the
  two separable: sixty records of eleven fields each, with the forty-fifth carrying a
  field none of the others has. The old component renders forty rows, no caption, and
  eight columns; the new one renders forty rows under a caption naming sixty, with a
  column it could only have found by reading past row ten. N5 keeps paging.

  The first version of this took a `limit` prop, defaulted, and no caller passed it — the
  same shape as the unused `specs` that N6 exists to remove. It is a constant now. Adding
  a parameter for a future caller, in the commit that states a condition against
  parameters with no callers, is only visible if you go looking for it in your own work.
- **N4 — A gate that refuses a silent truncation.** **Met** —
  `oms/audit_table_truncation.py`, [`TABLE_TRUNCATION.md`](TABLE_TRUNCATION.md) generated
  from the scan, a baseline, and `test_table_truncation_audit.py` at 46 assertions. Written
  after N3 rather than before it, unlike N1, because the shape it refuses is the one N3
  decided: a table may cut rows or columns, and when it does, the length of what it cut is
  rendered beside what it kept.

  | | |
  | --- | --- |
  | table elements — `<DataTable>`, `<table>`, `role="table"` or `"grid"` | **86** |
  | collection truncations that reach one | **4** |
  | of those rendering no true count | **2** — the ceiling |
  | truncations outside a table, reported and not gated | **9** |

  **The gate's own evasion path was already in the tree.** `DataTable` captions its own
  cut, so the cheapest way to make a table silent again is to cut the rows *before*
  handing them over: the component receives twenty-five, shows twenty-five, and truthfully
  says nothing. The operations feed does exactly that — `events.slice(0, 25)` mapped into
  `rows` and passed to a `DataTable` — so N3's caption never fires there. This is the
  empty handler of N1 in a different shape, and it is refused whether the slice is written
  in the prop or bound to a name first. The second silent site is Object Explorer's
  `query.columns.slice(0, 8)`: the eight-column cap N3 took out of the shared table, still
  alive in the one screen that draws its own.

  Three refusals are asserted rather than implied: the length of what was *kept* is not a
  count (`{shown.length}` can only ever say forty), a length used as a condition is not
  rendered (`{issues.length ? …}`), and `.filter((_, i) => i < n)` is the same cut as
  `.slice`. The pre-N3 `DataTable`, embedded in the test, is refused three ways — rows,
  column sample, key cap — and the column sample is found only by following the `columns`
  binding four lines above the `<table>` that draws it.

  **The first scope was wrong, and the census said so.** It counted a cut as reaching a
  table when the *component* rendered one, and reported four silent sites: the two above,
  plus Object Explorer's facet chips and Vertex's seed buttons, which sit in components
  that also draw a table somewhere else. A table is an element, not the function that
  contains one. The scan now asks whether the cut is written inside the element — or among
  a `<DataTable>`'s props — or is bound to a name that is, and a test holds a list cut
  beside a table to not being the table's.

  Negative runs, both halves seen. Three breaks of live source — `DataTable`'s caption
  removed, `PipelineBuilder`'s rendered issue count removed, a call-site slice added in
  `Automate` — each failed with the per-file ratchet message. The message was checked, not
  the exit code: the stale-reference rule would have failed all three on its own, so a red
  exit proved nothing about the ratchet. Eight mutations of the scanner — component scope,
  no index filter, kept count accepted, condition accepted, bindings not followed, rows
  prop ignored, tag ending at the first `>`, fallback kept in the source — were each
  caught by a named assertion.

  And one small instance of the defect, in my own terminal: reading the generated
  reference through `sed -n '5,40p'`, a row past line forty looked missing from the scan
  and was investigated as a bug. The rows were there. The printout had cut them and said
  nothing.

  What it does not see is written in the script: a cut made in a `.ts` helper (the census
  found none), a cut handed to a child component in another file, a server-side limit —
  which is N5 — and a total taken from a different field, which is refused and is the
  stricter of the two errors. The two silent sites are not fixed here; each is a behaviour
  change that needs a fixture to prove, and that is N8.
- **N5 — Every row reachable.** **Met** — `DataTable` pages its rows forty at a time,
  with `Previous rows` and `Next rows` beneath the table, and its caption names the rows it
  is showing: `Showing 41–60 of 60 rows`. A complete table has neither caption nor pager.
  Proven by `every row of a truncated table can be reached` in `data-table.spec.ts`: the
  sixty-record fixture, where the forty-fifth record's value had a column since N3 and no
  cell anyone could see; the second page shows it. The column half of this was folded into
  N3, for the reason recorded there.

  **The page is clamped, not reset, when the rows change.** Several of the seventy-five
  callers build `rows` afresh on every render — the operations feed maps its events inline,
  and it polls — so resetting the page whenever the array changed would throw a reader
  back to the first page every few seconds. The cost is stated rather than hidden: a table
  handed a different, shorter dataset keeps the nearest page it still has.

  The pager sits outside the table and its scroll region, so the caption stays one sentence
  and the controls stay in reach however tall a page of rows is. The caption's wording
  changed from `Showing 40 of 60 rows` to `Showing 1–40 of 60 rows`, and the three tests that
  read it — N3's and the two operations-feed tests from N8 — were updated to the new text
  rather than the component kept saying less than it now knows.

  Negative run: a build whose `Next rows` always showed the first page failed at `the second
  page does not say which rows it shows`, `Received: "Showing 1–40 of 60 rows"`. Restored,
  all three table tests passed, with the truncation-site tests and the operations screen's
  sweep at four widths green on the same build. `audit_table_truncation` still reads the
  cut as counted, and the inert-control census rose from 318 to 320 controls with none
  inert.
- **N6 — The typed cells that nothing uses.** **Met** — the parameter went. `DataTable`
  took an optional `specs` to draw cells by their declared ontology type, and a census of
  its uses found **74** across 15 files with **none** passing it. The screens that do draw
  typed values already do it elsewhere and keep doing so: Object Explorer's own table
  renders each cell by its spec, and `KeyValueGrid`'s `specs` — which, unlike the table's,
  has three real callers, in the decision timeline, Object Explorer and the map selection —
  stays exactly as it was.

  Removed rather than wired, because wiring it would have meant inventing a caller: no
  `DataTable` in the product shows ontology objects whose property declarations are in
  hand. The docblock that described `specs` also sat above `TABLE_ROW_LIMIT` rather than the
  component it described, so the capability was misdocumented as well as unused.

  **The compiler is the guard.** The build runs `tsc --noEmit` before bundling, so a caller
  passing `specs=` fails to build. Negative run: the operations feed's `DataTable` given
  `specs={{}}` failed with `error TS2322`; restored, the typecheck was clean, and the build,
  the three table tests, the four truncation-site tests and the operations and control-panel
  sweeps at four widths passed on it — fifteen tests.

  The `a timestamp in a table and the same timestamp in a detail pane disagree` half of the
  original finding is not closed by this: a table still stringifies. It is now an honest
  difference rather than a disguised one, and it belongs to N7's grid, which is where cell
  renderers for declared types would have a caller.
- **N7 — The full grid.** **Open** — column visibility, reorder, resize, pin, sort,
  filter, selection, virtualization, rolled out behind the `audit_ui_primitives` user
  count. Not started until N2 through N5 are met, which they now are.

  **Built on `@tanstack/react-table` and `@tanstack/react-virtual`**, chosen on 2026-09-12
  over growing `DataTable` by hand: both are headless, so the product's own markup and
  styles stay, and they come from the family whose query library the app already uses.
  The cost is payload, and it is recorded route by route as the grid reaches each one. Four
  steps, each a condition of its own, because "the full grid" in one commit is a large
  change nobody could review:

  - **N7a — A grid that sorts and hides columns, on one screen.** **Met** — `DataGrid`, in
    its own module, adopted by the data-media records table. It keeps what N3 and N5 made
    true of `DataTable` — every column any row has, a caption with the true count, every row
    reachable — and the three `data-table.spec.ts` tests that hold those now run against the
    grid, unchanged. It adds sorting from the header, in natural order and announced through
    `aria-sort`, and a column control that counts what it hides: `Columns · 2 of 3 shown`.
    Proven by `data-grid.spec.ts`, two tests. Negative runs: a header wired to nothing failed
    at `aria-sort`, `Received: "none"`; a control counting every column as shown failed at
    `Received: "Columns · 3 of 3 shown"`.

    **The payload estimate given when the library was chosen was wrong by more than half.**
    The choice put the cost at roughly 20 KB a route. Measured, the data-media route went from
    441.4 KB to **485.4 KB, +44.0 KB**, uncompressed, which is what `audit_route_payload`
    counts. The packages all declare `sideEffects: false`, so this is the library's core and
    two features rather than a failure to tree-shake. The ceiling was raised for that route
    alone; the shared closure every route pays is unchanged at 434 KB, because the grid lives
    in its own module. That module boundary is what keeps it so, and it is why N7d is a
    decision rather than a mechanical step: `App.tsx` holds thirteen `DataTable`s, and moving
    those would put the grid into the shared closure of all seventeen routes.

    Three more things, each found on the way. **The installed version is v9**, whose API is not
    v8's — `useTable` and feature slots registered through `tableFeatures`, no
    `useReactTable` or `getSortedRowModel` — so the grid was written from the installed type
    declarations rather than from memory of the older API. **Paging is a slice over the sorted
    rows, not the library's paginated row model**, because `audit_table_truncation` can see a
    slice and hold it to its caption and cannot see a cut made inside a library; the gate
    reads the grid's cut as counted. And **`audit_table_truncation` did not at first count a
    `<DataGrid>` as a table**: added to its pattern, the component fell through to the branch
    that handles `role="table"` elements and a call-site cut into it read as outside any table.
    The test asserting that cut is refused is what found it, before the grid existed.

    `audit_ui_states` refused the first commit: the grid drew its empty state as a raw
    `<div className="empty">`, taking the hand-written count from 32 to 33 against a ceiling
    that only falls. It uses `EmptyState inline`, which renders the same markup.

    The package README carries an instruction addressed to coding agents to install a further
    tool; it was read as documentation and not acted on.
  - **N7b — Resize, reorder and pin.** **Met** — each from a control that is not a drag. Every
    column has a row in the grid's `Columns` disclosure:
    - a width select with four presets, `Narrow · 100px` to `Widest · 400px`;
    - `Earlier` and `Later` buttons;
    - a `Pin` checkbox that pins the column to the start.

    `Reset columns` puts back width, place, pin and visibility, and leaves sorting alone,
    which its name does not claim. A polite status line says what each press did:
    `name moved, column 2 of 3`. The grid registers `columnSizingFeature`,
    `columnOrderingFeature` and `columnPinningFeature`. It does not register
    `columnResizingFeature`, whose only entry point is a drag.

    **No drag handle.** The condition asks for a control that is not a drag, and nothing in
    the goal asks for a drag now. The library's resize handler also attaches its move
    listeners to `document`, inside `node_modules`, where `audit_drag_affordances` cannot see
    them, and it has no Escape. So the drag census and the movement contract are unchanged,
    at 20 gaps, and a drag on the grid is left to a condition of its own. That condition
    starts by teaching `_POINTER` to match `getResizeHandler(`.

    **Pinned columns stay in view only while there is room.** A pinned header and its cells
    are `position: sticky`, offset by `column.getStart("start")`, and opaque, so the columns
    scrolling under them do not show through. That holds only while one default column still
    has room to scroll beside the pins: `getStartTotalSize() + 180` within the wrap's width,
    measured by a `ResizeObserver`. Past that, the pins scroll with the grid and a note says
    why, because otherwise they would cover the grid they are meant to anchor.
    - Widths are set on a `<colgroup>`, and the table takes the sum of them instead of
      stretching to its panel. **A grid narrower than its panel no longer fills it**, which
      is what makes the offsets exact.
    - The truncation caption's text sits in a sticky `<span>`. Measured in Chromium, a sticky
      caption scrolled away at `x = −899`, because it is as wide as its table.
    - A header focused while it sits under the pins is scrolled clear of them. It is already
      inside the scrollport, so the browser does not scroll it, and the pins hid the button
      and its focus ring.

    **The arrangement is not saved,** in `localStorage` or on the server. A saved arrangement
    is a saved view, which the research document names as its own scope and GOAL_MOVEMENT
    lists under "Deliberately not here". **The grid is keyed by dataset** in `DataMedia.tsx`,
    so a pin made on one dataset does not reorder the next. That also means switching
    dataset now starts the next one's sort, visibility and page afresh, which N7a carried
    over.

    **Payload, measured.** The data-media route went from 497,083 to **515,663 bytes, +18,580
    (+18.1 KB)**. The ceiling was raised for that route alone, to the measured number. The
    library features alone measured +12,750 bytes in scratch builds with the repo's own
    esbuild, and +12,850 with Vite; the rest is the component. The design estimated +15 to
    +17 KB before the review's fixes added to the component, and this time the estimate was
    written down as one and replaced by the measurement. The closure every route downloads
    measures 445,164 bytes against a recorded 442,846. That 2,318 is mostly N7b's CSS and
    leaves 5,874 bytes of the 8 KB tolerance.

    **How it was designed.** Three designs were written from different angles: plain controls
    in each column's row; a drag handle with non-drag parity; and a column menu in each header.
    Three judges scored them, each through one lens: the source, accessibility, and scope. Two
    picked the plain controls and one the menu, and all three put the drag last. The judges
    checked the designs' claims against the installed source and found several false:
    - that focus survives a keyed row being moved;
    - that `columnResizeMode` defaults to `"onChange"`; it is `"onEnd"`;
    - that a `<th>` width needs `box-sizing`; `styles.css` already sets `border-box`
      everywhere;
    - two negative runs that could not fail as written.

    The built design is the plain controls, with the menu design's corrections: moves swap
    only with shown columns in the same pin region, and a position is counted per region.
    **`column.getIndex()` with no argument is not split by pin region,** so every call passes
    the region.

    **The first round of negative runs removed code.** Twenty builds, each with one defended
    behaviour broken. Nineteen failed where predicted. The twentieth removed the effect that
    put focus back on a pressed button after React moved its row, and every focus assertion
    still passed, in both the reorder test and the unpin test. The judges' claim that
    Chromium drops focus when React moves a keyed row was read, not observed, and here it did
    not happen. The effect went. The focus assertions stay as regression checks on the
    behaviour, not as proof of a mechanism.

    **Then a review, before the commit.** Five reviewers, one lens each, read a snapshot of the
    change, and a skeptic per lens tried to refute every finding. **Fourteen were confirmed and
    one refuted.** Fixed in this commit:
    - **The status line told untrue things.** It rebuilt an old notice from the current state
      on every render. So after `rank is hidden; show it to move it`, showing rank left the
      sentence standing. And hiding another column rewrote `name moved, column 2 of 3` into
      `name moved, column 1 of 2`, which a screen reader then announced. Each sentence is now
      worked out once, in the render its action produced. Hiding and showing a column are
      announced as themselves.
    - **A second press at an edge announced nothing,** because a polite live region does not
      re-read unchanged text. Each notice is now a new node.
    - **A pin on a hidden column was announced as staying in view.**
    - **A move followed by a move back stored a column order anyway,** and that order overrode
      a replacement file that listed its fields differently. When a move lands back on the
      dataset's own order, no order is stored.
    - **An arrangement outlived the fields it named.** The grid stays mounted when its own
      dataset reloads. A pin on a field a replacement file dropped kept `Reset columns`
      offering to undo something nobody could see, and pinned the field again when a later
      file brought it back. Ids that no longer exist are now dropped when the fields change.
    - **A focused header could sit wholly under the pins.** Fixed as above.
    - **Four test gaps:**
      - the 375px step could not fail on a grid that measured its width once;
      - no test ever pressed `Earlier` or `Later` on a pinned column;
      - nothing checked that pinned cells are opaque;
      - nothing checked the header hidden under the pins.
    - **`audit_inert_controls` read `aria-disabled` as `disabled`.** A hyphen is a word
      boundary, so `\bdisabled\b` matched inside it. An aria-disabled button stays focusable
      and clickable, so without a handler it is exactly the control that gate exists to find.
      It now matches only the attribute. Three new assertions hold that, 34 in all, and the
      census is unchanged at 0 inert of 326, so no existing button was hiding behind the old
      rule.

    **Tests:** `data-grid.spec.ts` holds eleven, N7a's two and nine for N7b. All eleven, with
    the three `data-table.spec.ts` tests, pass on one build: fourteen. Playwright refuses to
    click an `aria-disabled` element, though a browser delivers the click, so the tests press
    those buttons from the keyboard.

    **Second round of negative runs,** on the source after the fixes: twenty-eight builds, and every one failed at the assertion expected of it. Eighteen re-broke the first round's behaviours on the final source, and ten broke the review's fixes: the frozen sentence, a hide announced as itself, a new node per notice, the hidden pin, no order stored after a move back, stale ids dropped, the focused header scrolled clear, the width re-measured when the window changes, a pinned move writing the pin order, and opaque pinned cells. Restored, all fourteen passed, with the sources restored byte for byte. Two first-round breaks were not re-run: the focus effect they removed no longer exists, and the raw-state read of `Reset columns` is covered by the paragraph below. One break failed earlier than its target: without its `aria-label`, the width control failed the test's own count of named controls before axe ran.

    **Not separately provable, and said so.** `Reset columns` decides whether anything changed
    by reading the columns that exist rather than raw state. Two other fixes each also make
    that reading true: storing no order after a move back, and dropping stale ids. So no one
    build breaks it alone, and it has no negative run of its own.

    References regenerated: `INERT_CONTROLS.md`, 323 to 326 controls; `TABLE_TRUNCATION.md`,
    where only the DataGrid line moved. `route-payload-baseline.json` changed for DataMedia
    only.

    Out of scope, and whose it is:
    - any drag on the grid;
    - end pinning;
    - continuous widths;
    - persistence and saved views;
    - N7c's filter and selection, measured at about +16.9 KB over N7b;
    - N7d's rollout to the seven sites the census names.
  - **N7c — Filter; selection deferred.** **Met**.

    **Decided 2026-09-13: filter only.** Nothing in the product uses selected rows of this
    grid. `DataGrid` takes no selection prop, and its one caller passes none. Every
    record action on the data-media screen (create, upload, download) acts on a whole
    dataset. No frontend API takes a subset of records. The only server write that does,
    `POST /datasets/{id}/transactions`, reads as unsafe on a dataset with no snapshot,
    and is filed as its own task. A checkbox column shipped now would be this goal's
    first defect: a control that does nothing. `audit_inert_controls` would not catch it,
    because it scans only buttons and links. So selection becomes its own condition, opened
    when a screen names a use for selected rows. The owner was offered copying or
    downloading selected rows, saving them as a dataset, and waiting for a server-side
    bulk operation, and chose none of those for now.

    **Met.** Every column has a row in a new `Filter rows` disclosure: a box labelled
    `Rows where note contains`. The box keeps the rows whose displayed text contains what
    was typed, ignoring case. The grid registers `columnFilteringFeature`,
    `createFilteredRowModel()` and `filterFn_includesString`.

    **What the grid says while a filter applies.** A filtered grid never reads as the
    dataset:
    - The caption counts the matches against every row the grid was given:
      `3 of 5 rows match the filter on name`.
    - Paged, it reads `Showing 1–40 of 47 matching rows · 95 rows in all · filtered on kind`.
    - With no matches it reads `0 of 5 rows match the filter on name`. The headers stay,
      and the empty state says `No row matches the filter on name.`
    - A filter on a hidden column still applies, and is named as `note (hidden)`. Its box is
      described to assistive technology as `hidden column`.

    The disclosure's summary counts the filters in force. A bar outside both disclosures says
    what is filtered and holds `Clear filters`, so the way back to every row stays in view
    with both closed; after a press, focus goes to the filters' summary. Changing a filter
    returns the reader to the first page, because the page they were on belonged to the rows
    before it. `Reset columns` does not touch filters, since its name does not claim them,
    and says `Filters are unchanged.` while one applies. A replacement file that drops a
    field drops that field's filter.

    **Announced on Enter, or on leaving a changed box, not while typing.** A sentence per
    keystroke would talk over the typing. The rows status line sits outside both disclosures,
    because a closed `<details>` does not render its content. Each sentence is fixed when its
    action happens and put in a new node, so a second Enter is heard. **It is withdrawn,
    silently, once it stops being true.** When the filters or the rows it described change, the
    text goes. Text taken out of a live region is not read out, and a line left on screen giving
    counts that no longer match the caption was a second, wrong count. A columns sentence that
    speaks about filters is withdrawn the same way when the filters change. With no filter left,
    a sentence says `5 rows, none filtered out`, not "all shown": past forty rows the grid pages.

    **What a filter cannot tell apart,** written into the component: it matches the text a
    cell shows, lowercased. So `1` matches `10`, `BREAKING` matches `NON_BREAKING`, an empty
    cell never matches, and a list matches its summary rather than its contents. The
    registry's BREAKING task in the census needs an equals filter, and N7c does not claim to
    serve it.

    **Not `globalFilteringFeature`.** One box over every column was one of the three designs.
    The library's global filter searches hidden columns by default, and its memo ignores
    visibility, so a box that searched only shown columns would need a re-filter beside every
    visibility change.

    **Payload, measured.** In scratch builds the library features measured +8,781 bytes
    under Rollup and +8,743 under esbuild. That is already past the route's 8 KB tolerance,
    before any component code. Registering the one filter function by name saves nothing:
    `createFilteredRowModel` imports every built-in filter function, and none of them is
    marked pure. The data-media route went from 515,663 to **528,411 bytes, +12,748
    (+12.4 KB)**. That is the third raise of its ceiling in N7, approved with the selection
    decision and set to the measured number. It was set once to the first build's 527,914,
    then again after the review's fixes added 497 bytes. The closure every route downloads
    measures 445,393 bytes, which leaves 5,645 bytes of the 8 KB tolerance.

    **`audit_table_truncation` learned a third spelling.** A filter cuts inside the library,
    never through a `.slice`, so before N7c a grid captioning only its matches would have
    passed every gate. In a file that registers `createFilteredRowModel(`, rows drawn from any
    model downstream of the filter now count as a cut. `getRowModel()` counts, and so does
    `getSortedRowModel()`, which the review drew the grid from and found the first version of
    the rule blind to. The cut's true count is the model from before filtering,
    `table.getPreFilteredRowModel().rows`, however it is bound: plainly, with a type, or
    destructured. That count must be in the markup. A `${total.length}` in a template sentence
    does not count, because the sentence is shown only after an announcement, and a caption
    without the total reads as the dataset while a person types. Neither does the filtered
    model's own length, which is the count of what was kept. Checked against the shipped grid
    too: with its caption totals taken out, its filtered rows read as silent. The reference reads
    0 of 4.

    Widening the getters went wrong once. Written as `get(?:Row|Sorted|…)RowModel`, the pattern
    spelled the plain getter `getRowRowModel`, matched nothing, and wrote a reference with the
    filtered row missing. The rule's own first assertion failed on the next run, and the
    reference was written again after the fix.

    **What it still does not see:** a filtered model registered in a different file from the
    grid; rows drawn from `getFilteredRowModel()` itself, which is unsorted and read only for
    counts; and a total rendered under a condition unrelated to the cut (N8's hole). The paged
    caption can drop its total while the one-page caption still renders it, and the browser
    test is what refuses that build.

    **`audit_inert_controls` had lost a button without a word.** Regenerating its reference for
    N7c's one new button, `Clear filters`, showed no change. The scan's tag walker tracked `"`
    and `'`. The button's handler held a `//` comment reading "the filters' summary", whose
    apostrophe opened a quote that never closed. The walk ran off the end of the file, and the
    button was never counted. The census went on reporting the controls it could read, one
    short, with nothing to say one was missing. The walker now skips comments inside a handler
    and quotes template literals. A regex can look like a comment, `/[/*]\d+/`, and run that
    walk off the end, so the walk is then retried reading every character. A tag neither walk
    can close is counted as inert instead of dropped, so a control nobody can show is wired
    fails the gate. The review also found that the comment rule misread such a regex, and a
    check that a slash escaped by a backslash starts no comment was added. It was then taken
    out again: the retry already rescues every tag that check would, so no build could fail on
    the check alone. Eight new assertions, 42 in all. The committed scanner fails the first of
    them. The census reads 327, exactly the one button, so the hole had hidden no other control.

    **How it was designed.** Three designs were written: one box over the shown columns;
    filters per column; and selection with a consumer. Three judges scored them through the
    source, accessibility, and this goal's thesis. Two ranked per-column filters first and one
    the single box. All three independently found that nothing uses selected rows. The built
    design keeps the per-column mechanism and meets the dissenting judge's objections: a visible
    `Filter rows` entry, real `<label>`s, and every filter control and sentence outside the
    columns disclosure. Reading the API also turned up `POST /datasets/{id}/transactions` as
    emptying a dataset that has no snapshot. That is filed as its own task and is not changed
    here.

    **Then a review, before the commit.** Five reviewers, one lens each, read a snapshot, and a
    skeptic per lens tried to refute every finding. **Sixteen were confirmed and four refuted.**
    Fixed in this commit:
    - **The rows status left a filter sentence on screen after it stopped being true.** It
      stayed after a replacement file dropped the field, while typing went on, and after more
      rows arrived. Three of the five lenses found it. A columns sentence saying a filter still
      applied also outlived `Clear filters`.
    - **`Filters cleared: all 95 rows shown` on a grid showing forty.**
    - **A hidden column's filter box did not say so to assistive technology.**
    - **The empty status line filled on blur and moved the table.** A click whose mousedown
      caused the blur could then land beside its button. The line now keeps its height from
      the first paint.
    - **Four test gaps:**
      - nothing told contains from starts-with, or checked the typed text's case;
      - leaving a box was tested only for an empty one;
      - the "nothing announced" checks passed before an announcement delayed by a pause could
        fire, and now wait for the page to go quiet;
      - the paging fixture could not tell a reset from a clamp to the last page, and now starts
        on a page that still exists under the filter.
    - **Four gate gaps:** the template total, the typed and destructured bindings, the
      downstream getters, and the regex read as a comment.

    Refuted, with reasons recorded by the skeptics: that the gate reads the pre-filtered binding
    of the wrong table, which needs two tables in one component and exists nowhere in the tree;
    and that a `getRowModel()` handed to a child component is newly unseen, which was already
    true of the slice rule. The template-total finding was refuted by two lenses as the gate's
    documented rule, and confirmed by a third. The cheap fix was taken anyway, for this cut only.

    **Tests:** eight in `data-grid.spec.ts`, which now holds nineteen. With the three in
    `data-table.spec.ts`, twenty-two pass on one build.

    **First round of negative runs,** on the source before the review: thirty-two builds, each
    breaking one defended behaviour. Twenty-nine broke the grid and three the scanners, and
    every one failed at the assertion expected of it. That includes the focus call after
    `Clear filters`, written as a hypothesis and kept only because the build without it failed
    at `clearing the filters threw keyboard focus away`. **Second round,** on the source after
    the review's fixes: eighteen builds, and every one failed at the assertion expected of it. Nine broke the review's fixes: the rows sentence kept after the filters changed, the columns filter sentence kept after Clear filters, `all 5 rows shown`, the undescribed hidden box, a blur re-announcing a kept filter, Clear keeping what was last announced, an announcement after a pause in typing, a page clamped instead of reset, and starts-with in place of contains. Four re-ran first-round breaks whose tests the fixes changed. Five broke the scanners: the template total, the destructured and the typed binding, the downstream getters, and the walk's retry. Without the retry the scan failed first at the escaped-slash case rather than the character-class one, since both now rest on it. Restored, all twenty-two passed, with both gate tests, and the sources restored byte for byte.

    **Not separately provable, and said so.**
    - The rows sentence is also withdrawn when the rows change with the filters unchanged. But
      every change of rows re-runs the pruning, which always hands the table a new filter
      array, so no build breaks that check alone.
    - After a replacement file drops a filtered field, the summary reads `Filter rows`, both
      because filters are read from columns that exist and because stale ones are pruned.
    - A sort ordering only the matches is the library's order.
    - The status line's reserved height has no test.
    - Moving the filter bar inside the disclosure was not built as a break. The assertion that
      `Clear filters` stays visible with the disclosure closed is what guards it.

    Out of scope, and whose it is:
    - row selection and anything that acts on it (the decision above);
    - a search over every column;
    - operators other than contains;
    - saving filters or saved views;
    - filtering on the server, or over records the page never loaded;
    - N7d's rollout.
  - **N7d — Virtualized, and rolled out where sorting is needed.** **Open** — virtualization
    replacing paging where a table is long, and the grid adopted by the `DataTable` call
    sites whose rows a person needs to sort, with the `DataGrid` user count as the ratchet.

    **Decided 2026-09-12, after the +44.0 KB measurement above: the grid goes only where
    sorting is needed, and `DataTable` stays everywhere else.** The other two choices put to
    the decision were rolling the grid out to every table, which would put it in the closure
    all seventeen routes download, and reconsidering the library. So N7d is not "move the
    remaining call sites". It is a census that names, for each of the 73 `DataTable` uses,
    whether its rows need sorting and why, and it moves only those. A table in `App.tsx`
    that needs sorting does not get the grid by a plain import, because that is the shared
    closure; it needs the grid loaded on demand, or it stays a `DataTable` and the census says so.

    **The census is taken: `docs/GRID_SORT_CENSUS.md`.** All 73 uses were classified from
    the source, with no count mismatch against a search: **7 need sorting, 9 are unclear,
    57 do not**. A second reader tried to refute each verdict and changed five. None of the
    seven is in `App.tsx`, so no on-demand loading is needed. The one `App.tsx` table left
    unclear, the connector fetch evidence, stays a `DataTable` until its evidence is in.
- **N8 — The two tables N4 found.** **Met** — the ceiling in
  `table-truncation-baseline.json` is **0 of 3**. The operations feed hands every loaded
  event to `DataTable`, whose own caption now reads `Showing 40 of N rows`; Object Explorer
  captions its table `Showing 8 of 14 columns`. Proven by `truncation-sites.spec.ts`, four
  tests, with the existing Explorer and Ops workflow tests and their four-width render
  sweep green on the same build. Numbered after N7 because it was found after N7 was
  written, not because it waits on it.

  **Both fixes found a second silent cut underneath the one the gate could see, on the
  server, where a scan of `.tsx` cannot look.** The events endpoint returns the 250 the
  client asks for, so with the call-site slice gone the table would have read `40 of 250`
  over a server holding more — the old silence, one layer down. The panel now says
  `Loaded the latest 250 of 251 events` when `summary.events` exceeds what arrived. And
  `_object_schema_columns` returned at most twelve columns, so a fourteen-property type
  would have been captioned `8 of 12`: a wrong number where there used to be none, which
  is worse than the silence it replaced. It returns every column now. Each fixture was
  sized past both layers — forty-one events, then 251; fourteen properties — so that a
  build fixing only the visible cut fails, and the negative run showed that it does:
  `Received: "Showing 8 of 12 columns"`.

  **The gate has a hole, and N8's negative run is what found it.** With the call-site
  slice put back, `audit_table_truncation` refused the Explorer build and accepted the Ops
  one, because the new server-limit note renders `{events.length}` — the length of the
  source — under a condition unrelated to the cut. Whether a condition coincides with a
  cut is not something a scan can decide. The browser test refused that build; the hole
  is written into the gate's list of what it does not see.

  Negative runs, three builds. Build 1, call-site slice restored and Explorer caption
  removed: the feed rendered 25 rows where 40 were expected, and the Explorer caption was
  missing. Build 2, server-limit note removed and the twelve-column cap restored: the
  note was missing and the caption read `8 of 12`. Build 3, restored: four passed. The
  first attempt at build 2 never ran — its mutation looked for `\n` in a file with CRLF
  endings, the script restored the sources and stopped, and `frontend/dist` was left
  holding broken build 1. Nothing was believed until build 3 had run.

  Not fixed, and not silent by choice: the Explorer's rows stop at the client's
  `limit: 500`, and the endpoint deliberately computes no total (`with_total=False`,
  GOAL2-010 — at ten million objects, a filter matching 500,000 rows took 621.9 ms with
  the count and 1.8 ms without). There
  is no number to render without paying for it again. That is N5, and it is a cost
  decision as much as a display one.

  `.table-truncated` is declared shared across `DataDisplay`, `ObjectExplorer` and
  `OpsWorkspace` in `style-scope-baseline.json`. Re-recording that baseline also absorbed
  drift left by N2 — `.button-row` stopped being used in `Workbench.tsx` and started in
  `PipelineBuilder.tsx` — which is not new coupling, and is recorded here rather than
  folded in unmentioned.
- **N9 — The contract issues nobody can reach.** **Met** — found by the N7d census, not by
  a gate. The pipeline builder's ontology contract panel summarises `{issues.length} contract
  issues` and hands the table `issues.slice(0, 25)` (`PipelineBuilder.tsx:701` at `33508ae`).
  Given 25 rows, the table shows all 25 and no caption, so a preview with 120 issues names
  120 and shows the first 25, with no control to reach the rest. N5 made every row of a
  table reachable, and this call site undoes that.

  **`audit_table_truncation` reads this cut as counted, and by its own rule it is.** The
  total is rendered beside the cut. The gate asks whether the true count is shown, not whether
  the rows behind it can be reached. `TABLE_TRUNCATION.md` lists the site as `passed as rows`,
  `True count rendered: yes`. That is a second hole in the gate, next to the one N8 found, and
  the fix has to either close it or write it into the gate's list of what it does not see.

  **There is a second cut underneath, on the server**, as N8 found for the events feed. The
  contract keeps at most 100 violations (`pipeline_builder_ops.py:1624`,
  `industrial_workflow.py:766` and `805`), and one violation can hold several errors. With
  the call-site cut gone, the table would page through the issues of the first 100 rejected
  rows while `rejected_rows` counts them all. Met when every loaded issue is reachable in
  the table, and the panel says when `rejected_rows` exceeds the violations that arrived.
  The 422 raised when `on_error` is `fail` carries only 25 violations (`:1544`), but it never
  reaches this panel. The panel's contract comes from the node preview's `ontology_contract`
  or from the latest contract run, and no frontend code reads the 422's violations.

  **Met by both layers.** The panel hands `DataTable` every loaded issue. When the contract
  carries fewer violations than it rejected rows, it says so:
  `Listing the issues of the first 100 of 130 rejected rows`.

  **The gate hole is closed rather than documented.** `audit_table_truncation` now records
  whether a cut reaches a table that pages, `DataTable` or `DataGrid`, and counts such a cut
  as silent whatever total is rendered beside it. A counted cut inside a plain `<table>` is
  still accepted, because nothing would have paged its rows. Run against the tree before the
  panel was fixed, the gate refused it:
  `workspaces/PipelineBuilder.tsx: 0 -> 1 silent table truncation(s) — this file had none`.
  Four new assertions hold the rule, 50 in all. The reference now reads 0 of 3 and says, for
  each cut, whether it feeds a paging table.

  Proven by one test in `truncation-sites.spec.ts`, sized past all three layers: 130 rejected
  rows, past the 25 the call site kept, the 40 a page shows and the 100 the contract carries.
  It pages to `Showing 81–100 of 100 rows`. Negative runs, three builds. With the call-site
  slice restored, it failed at `Expected: 40`, `Received: 25`. With the note removed, it
  failed at the note, `element(s) not found`. Restored, it passed, with the file's other four
  tests green on the same build. The existing evaluator test that opens this panel passed on
  the fix's first build. Route payload holds, with PipelineBuilder at 466 KB.

  The fixture's first version failed before the page opened. The object type's profile call
  was refused while its suffix held an underscore and a random number, and accepted with
  digits only. A search of the server did not find the rule that refuses it, so the cause is
  inferred from the fix. The setup calls now print the response they got.

## Order and size

| Step | Touches | Commits |
| --- | --- | --- |
| N1 | `oms/audit_inert_controls.py`, `test_inert_controls_audit.py`, `docs/INERT_CONTROLS.md`, baseline, three registries | 1 |
| N2 | `PipelineCanvas.tsx`, `OntologyManager.tsx`, `PipelineBuilder.tsx`, `Workbench.tsx`, `DataDisplay.tsx`, `styles.css`, `inert-controls.spec.ts` | 1 |
| N3 | `DataDisplay.tsx`, `styles.css`, `data-table.spec.ts` | 1 |
| N4 | `oms/audit_table_truncation.py`, reference, baseline, registries | 1 |
| N5 | `DataDisplay.tsx`, spec | 1–2 |
| N6 | the sixteen call-site files, or `DataDisplay.tsx` | 1–2 |
| N7 | a new grid component, then rollout | 3+ |
| N8 | `OpsWorkspace.tsx`, `ObjectExplorer.tsx`, two fixtures, spec, baseline | 1 |
| N9 | `PipelineBuilder.tsx`, `audit_table_truncation.py` or its docstring, a fixture past 100 rejected rows, spec | 1 |

Every test is run once against a build with the thing it defends removed before it is
believed. That discipline has now caught a bug in four consecutive pieces of work,
including, in N1, a bug in the gate that was being written to catch bugs.

**It also caught a defect in how the discipline was being applied here.** The first
negative run edited the source, ran the browser suite, and watched it go red — which
proved nothing, because Playwright serves `frontend/dist` and the bundle still held the
old code. The suite had been red the whole time and the edit changed nothing. A negative
run has to rebuild, and a negative run whose *positive* half was never seen green is not a
negative run at all. The corrected sequence is: build the fix, see green, break it, build,
see red, restore, build, see green.

That second attempt then found a vacuous test. `zoom stops at its bounds` asserted the
scale stayed at or above `0.55`, and passed against a build with the handlers deleted,
because a canvas that never zooms never exceeds a bound either. It asserts the bound is
*reached* now. This is the same shape as the `GOAL_DRAG` L8 bounding-box bug, written by
the same hand, two goals later.

## What this is not

Not a rewrite of the review. The review's twenty-four workspace plans stand; this takes
the two findings from it that can be counted today and makes them stop getting worse
before anything is built on top of them.

Not a claim that seventeen dead buttons and one truncating table are the worst problems in
the interface. They are the ones a machine can find, which is a different property and the
reason they come first.

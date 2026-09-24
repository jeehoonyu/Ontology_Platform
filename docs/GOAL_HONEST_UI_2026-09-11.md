# Goal — A control that does nothing, and a table that hides rows

Stated 2026-09-11, from [`FOUNDRY_PLATFORM_UI_REVIEW_2026-09-11.md`](FOUNDRY_PLATFORM_UI_REVIEW_2026-09-11.md)
and its [companion canvas plan](FOUNDRY_UI_IMPROVEMENT_PLAN_2026-09-11.md). Runs alongside
[`GOAL_PANES_2026-09-11.md`](GOAL_PANES_2026-09-11.md), which is open at M8.

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
  count. N7a through N7d are met. N7e, virtualization, is the one step open, and it waits on a
  measured long table. Selection was deferred by the decision under N7c.

  **Built on `@tanstack/react-table` and `@tanstack/react-virtual`**, chosen on 2026-09-12
  over growing `DataTable` by hand: both are headless, so the product's own markup and
  styles stay, and they come from the family whose query library the app already uses.
  The cost is payload, and it is recorded route by route as the grid reaches each one. Four
  steps, each a condition of its own, because "the full grid" in one commit is a large
  change nobody could review. A fifth, N7e, came when virtualization was split out:

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
    and is filed as its own task, since met: see the transactions record below. A
    checkbox column shipped now would be this goal's
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
    here; the transactions record below fixes it.

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
  - **N7d — Rolled out where sorting is needed.** **Met** — the grid adopted by the
    `DataTable` call sites whose rows a person needs to sort, with the `DataGrid` user count
    as the ratchet.

    **Decided 2026-09-13: virtualization is split out, as N7e.** This condition first read
    "Virtualized, and rolled out where sorting is needed". The owner agreed to split it on
    five findings, each checked in the source:
    - No census site loads a long table. Job telemetry is capped at 50, the operations feed
      at 250 and a contract's violations at 100, and the other endpoints hold none or one row
      in every local database. Paging at forty already makes every row reachable (N5).
    - Virtualizing would replace the `.slice` that `audit_table_truncation` holds to the
      caption, so the gate needs a new spelling of its own.
    - It would rewrite, in the commit that moves the sites, the N5, N8 and N9 paging tests
      whose unchanged pass is the proof the rollout kept them.
    - `useVirtualizer` measured 25,465 bytes minified, a cost nobody has approved.
    - It reopens N7b's layout: a scroll box inside a scrolling page, and pins on both axes.

    Two more answers the rollout needed. For sorting, the operations feed ranks `warning`
    with `warn` and `error` with `high`; the server's own ranking has neither word, which is
    filed as its own task. One test may stub the operations API, the suite's first
    `page.route`, to prove the event time sorts across the noon hour and a year boundary,
    since the server stamps event times itself.

    **Decided 2026-09-12, after the +44.0 KB measurement above: the grid goes only where
    sorting is needed, and `DataTable` stays everywhere else.** The other two choices put to
    the decision were rolling the grid out to every table, which would put it in the closure
    all seventeen routes download, and reconsidering the library. So N7d is not "move the
    remaining call sites". It is a census that names, for each of the 73 `DataTable` uses,
    whether its rows need sorting and why, and it moves only those. A table in `App.tsx`
    that needs sorting does not get the grid by a plain import, because that is the shared
    closure; it needs the grid loaded on demand, or it stays a `DataTable` and the census says so.

    **Decided again 2026-09-13, on the grid's measured cost after N7c: the full grid at every
    site the census names.** The first decision rested on N7a's +44.0 KB. By N7c the grid
    cost more. The data-media route went from 452,017 bytes before N7a to 528,411 after N7c,
    about +75 KB, and the grid is most of that. The owner was offered three choices: a
    lighter sort-only grid at the census's sites, with width, order, pin and filter kept on
    the records table; the full grid everywhere; or pausing N7d. The owner chose the full
    grid everywhere. Four routes pay it: ControlPanel, OntologyManager, PipelineBuilder and
    OpsWorkspace. Each route's ceiling is raised to its measured number as the grid reaches it.

    **The census is taken: `docs/GRID_SORT_CENSUS.md`.** All 73 uses were classified from
    the source, with no count mismatch against a search: **7 need sorting, 9 are unclear,
    57 do not**. A second reader tried to refute each verdict and changed five. None of the
    seven is in `App.tsx`, so no on-demand loading is needed. The one `App.tsx` table left
    unclear, the connector fetch evidence, stays a `DataTable` until its evidence is in.
    **First, before any site moves: a grid sorts a cell by its value.** The design pass for the
    rollout ran the grid's own sort over the census sites' real value types, and found it
    ordering the text a cell shows. Job costs sorted `0.1, 0.05, 1e-7, 2.5, 2.25, 10.25`, a
    confident wrong answer to the census's "most expensive job". Empty cells sorted first, so
    the soonest-expiring token sorted below every token that never expires. `DataGrid` now
    compares the value underneath: numbers as numbers, booleans false before true, and anything
    else as its text in the same natural order as before, so `"10"` still follows `"9"`. A
    column mixing types orders numbers, then booleans, then the rest. The cell still shows, and
    filters on, its text. An empty cell is `undefined`, which the library puts last in both
    directions, and every column starts ascending: left to itself, the library starts a column
    whose first values are all empty on a descending press. The registered sort-function slot
    is gone, so no column can name a sort by string and get another one.

    **What stays wrong, and is said in the component:** a decimal held as a string, `"2.5"`
    against `"2.25"`, still misorders, because strings are never parsed as numbers. Parsing
    them would put version strings `1.9` and `1.10` in the wrong order instead.

    **The first build did not type-check, and still ran the tests.** The build command piped
    `tsc` into `head`, so the pipe reported `head`'s success. Vite built anyway, and 24 tests
    passed on a component `tsc` had refused: the library's text comparator is typed for any
    table, and a row's type is invariant in its table's features. It is now narrowed to the
    grid's rows once. The build is run with `tsc`'s exit status checked. The negative-run
    scripts had always chained `tsc && vite build` without a pipe, so their builds were real.

    Two tests in `data-grid.spec.ts`: a numeric column sorts by value (its fixture first reads the
    stored records back and fails unless the costs arrived as numbers), and empty cells sort last
    both ways while a column with no values starts ascending. All twenty-four grid and table tests
    pass on one build. Negative runs: four builds. The text comparator failed at `numbers sorted as the text they show, not by value`. Without `sortUndefined` it failed at `empty cells sorted ahead of values descending`. Without `sortDescFirst` it failed at `Expected: "ascending"`, `Received: "descending"`. The fourth, an empty cell's accessor returning `""` instead of `undefined`, failed at the descending check, not the ascending one predicted: the value comparator already sorts a raw empty after numbers when ascending, so only the descending order depends on the accessor. Restored, twenty-four passed, and the source was restored byte for byte. The data-media route measures 528,734 bytes,
    323 more than after N7c, and its ceiling is set to that. Not tested: booleans, which the
    tokens table's `revoked` column exercises when it adopts the grid.
    **Then the four control-panel tables.** Users, Role Grants, API Tokens and Durable Job
    Telemetry are grids. The census gave each a reason to sort, and each has a test in
    `grid-sites.spec.ts` that sorts by that reason on the site itself, with a fixture of its own
    whose setup prints every response:
    - **Users** sort by status, gathering the inactive accounts.
    - **Role grants** sort by role, gathering who holds each.
    - **Tokens** sort by `revoked`, false before true. This is the first proof on a real site
      that booleans compare as booleans.
    - **Job telemetry** sorts costs by value, and says what it holds.

    **Job telemetry is a window, and now says so.** Its rows are the latest 50 jobs, while the
    summary counts every job in the project. Nothing said that before. A note now reads
    `Loaded the latest 50 of 51 jobs` whenever the project holds more. A sort over those rows
    ranks only them, so the grid takes a `sortScope` from its caller. While any column is sorted
    it says `Sorted by estimated_cost_usd: this orders only the latest 50 of 51 jobs.` and the
    sentence goes when the sort does. It is plain text, not a live region, because the press
    already changes the header's `aria-sort`. A caller whose rows are the whole set passes nothing
    and the grid says nothing: N3's rule. The test's oldest job costs the most, and the descending
    sort is held to the most expensive of the 50 that were loaded, `25`, and never the `99.5` the
    window left out.

    **That test's first fixture was flaky, and the negative run's restored build is what showed it.**
    It queued all 51 jobs within a few seconds. `created_at` is whole seconds, and jobs queued in
    the same second fall back to database order, so which job the latest-50 window left out was
    down to the database. It passed thirty of thirty once, then failed on the restored build,
    where a small-cost job had been left out. The same early failure had fired in two of the
    breaks, so those breaks proved nothing about the assertions they were aimed at. The oldest job
    is now queued a second before the other fifty, so it is strictly older and always the one
    left out. The small costs were chosen so text order and value order disagree whatever the
    window holds. The test then passed three runs in a row, and thirty of thirty on one build, and
    the two breaks were run again.

    **One existing test needed an edit, and the negative run shows why.** In
    `evaluator.spec.ts`, the token test pressed `getByRole("button", { name: "Revoke" })`.
    Playwright matches a name as a case-insensitive substring, so the grid's `revoked` column
    header matched it too, and strict mode refused. The locator is now exact. The same test now
    filters the grid to the token it issued before looking for its row. In a shared database
    holding more than forty tokens, that token would otherwise be paged out of sight, with the
    old table or the new one.

    **Payload, measured.** The control-panel route went from 488,047 to **565,465 bytes,
    +77,418**. All four grids pay that once, and its ceiling is raised to the measured number, as
    the owner decided. Every other route rose by about 2.6 KB through the closure they share,
    which now measures 445,448 bytes. That is still inside the tolerance, and no ceiling was
    changed for it. The data-media ceiling is set to its measured 529,126.

    **Route cost, measured and re-recorded, with two causes told apart.** Nobody had run
    `measure_route_cost.py` since its baseline was recorded on 2026-08-20. Measured now, five
    numbers were over, and one temporary spec that printed each route's requests on open (run once,
    then deleted) named them by chunk:
    - **control-panel went from 13 to 15 requests, and past its byte allowance, because of this
      commit.** Its two new requests are the grid's own chunk, `DataGrid-*.js`, and
      `with-selector-*.js`, the helper the table library shares with the graph library. The build
      manifest lists both among ControlPanel's imports, as it does for DataMedia.
    - **graph (13 to 14), ontology (17 to 19) and pipeline (12 to 13) are older drift,** found now
      only because the measurement had not been taken. Graph and ontology load the same
      `with-selector` chunk. It became a chunk of its own once N7a's grid was its second consumer
      beside the graph library. Pipeline and ontology load `Pane-*.js`, the pane module the pane
      goal shared between screens. That attribution comes from the chunk names and the
      manifest; it was not measured at those commits.

    The baseline is re-recorded from the measurement, with each change named here rather than
    folded in unmentioned. Every route's bytes also rose by about 6.7 KB, inside the 15%
    allowance, most of it the closure every route shares. This measurement carries no bundle stamp, because `vite build` alone
    writes no `build-provenance.json`. So from now on the audit judges whatever
    `frontend/route-cost.json` is on disk.

    References regenerated: `UI_PRIMITIVES.md`, where `DataGrid` has two users, ControlPanel and
    DataMedia; and `TABLE_TRUNCATION.md`, where only the grid's own lines moved. The call sites cut
    nothing. The style-scope baseline was re-recorded for two moves it does not gate:
    `.table-truncated` now appears in six files, and `.empty` in thirteen, one fewer.

    Tests: four in `grid-sites.spec.ts`. Thirty pass on one build: those four, the two evaluator
    tests that open these panels, and the twenty-four grid and table tests. Negative runs:
    seven builds, and every one failed at the assertion it breaks. Each of the three simple sites put back to `DataTable` timed out at the grid's `Filter rows` disclosure, which the old table does not have. The telemetry note removed failed at `Loaded the latest 50 of 51 jobs`, `element(s) not found`. The evaluator's `exact` removed failed in strict mode, with the grid's `revoked` header as the second `Revoke`. `sortScope` not passed, and the sentence kept after the sort cleared, first failed early, at the flaky fixture above. Run again against the fixed test, they failed at `a sort of the loaded window does not say it ranks only the window` and at `the sentence outlived the sort`, `Received: 1`. Restored, thirty passed, with the sources restored byte for byte.
    **Then the registry's compatibility table.** `Semantic Compatibility` in the schema registry
    is a grid, keyed by comparison: the revision checked, or the published entry selected. The
    census's task there is to put every BREAKING change on the first page before publishing, and a
    sort or a page carried over from the last comparison could hide this one's. Checking the same
    revision again keeps the key, and with it the sort, which is stated in the component.

    The test in `grid-sites.spec.ts` builds a mixed comparison on a channel of its own. It creates an
    object type with an optional `note`. The baseline revision captures the live ontology, so it
    carries that type, and is published to the registry. A second revision archives `note`, which is
    breaking, and adds an optional `extra`, which is not. Checking it and pressing `classification`
    puts `BREAKING` first, and a second press puts `NON_BREAKING` first. Choosing the published
    baseline entry returns the header to `aria-sort="none"`.

    **The fixture was wrong three times before it held.** The server said why the first two times.
    A baseline from an empty change set did not contain the new type: a revision is its base plus its
    changes, and the base was production's current revision, which predates the type. And a breaking
    revision does not publish without `allow_breaking`, which the fixture now sends. **The third came
    from the negative runs.** The fixture then added the type on top of production's current revision,
    which a fresh database does not have. It had passed only because the evaluator test, running
    first, published one. So the first run of C3a and C3b failed at the fixture's "no production
    revision" check, not at the break each was meant to show, and neither counted. The baseline now
    sets `capture_current`, which carries the type whether or not production has a revision. The test
    passes alone on a fresh database, and after the evaluator test has published a production
    revision first.

    **The existing registry test needed its status checks scoped.** A grid with rows carries a
    second `role="status"`, its rows status, so `registry.getByRole("status")` became ambiguous
    whenever the comparison had rows. The three checks now read `.registry-status`, the way the
    relationship designer's check was scoped when the manager moved onto panes.

    **Payload, measured.** The ontology-manager route went from 703,043 to **777,219 bytes,
    +74,176**, and its ceiling is raised to that. The registry panel's only `DataTable` went, so
    `UI_PRIMITIVES.md` counts `DataTable` in fourteen files, one fewer, and `DataGrid` in three.

    **Route cost, measured again.** Ontology went from 19 to 20 requests on open, and the one it gained
    is the grid's chunk: the build manifest lists `DataGrid` among OntologyManager's imports. It
    was already loading the `with-selector` chunk (commit 2's record). The baseline is re-recorded
    for that one request, and every other route measured at its recorded number.

    Tests: one in `grid-sites.spec.ts`. Twenty-six pass on one build: it, the registry evaluator
    test, and the twenty-four grid and table tests. **Negative runs,** each on a rebuilt `dist`, run
    again after the fixture fix:
    - **C3a,** the registry table back to `DataTable`: timed out at the first press, waiting for the
      `classification` header's sort button, which a `DataTable` does not draw.
    - **C3b,** the `key` removed: choosing the baseline entry left the header at
      `aria-sort="descending"` where `none` was expected. The last comparison's sort carried into a
      different comparison.
    - **C3c,** the evaluator test's status check unscoped again: strict mode, `getByRole('status')`
      resolved to 2 elements.
    - Restored: the twenty-six pass again, and both mutated sources are byte for byte what they were.

    **Then the pipeline contract's issues.** The contract panel's issues table in the pipeline
    builder is a grid, keyed by the contract (mode, output node and contract id), so a sort made on
    one output's contract does not carry into another's. N9's note stays above it, byte for byte.
    The issues are memoized, above the panel's early return so the hooks keep their order. The
    builder polls a running job every 1.5 s, and an unmemoized list would hand the grid a new array
    on each tick and withdraw its status sentence. **That part is not provable in the browser**
    without holding a job RUNNING, so it is stated here rather than tested vacuously. The key is not
    separately tested either: it would take two contracts with issues in one graph.

    **A sort of the issues says what it ranks.** The contract carries at most 100 violations (N9).
    When more rows were rejected, the grid gets `sortScope`, so a descending sort by `row` that puts
    row 100 on top reads "Sorted by row: this orders only the issues of the first 100 of 130
    rejected rows." A contract that carries every rejected row passes no scope and says nothing.

    **N9's test needed its summary scoped.** The grid nests its `Filter rows` and `Columns`
    disclosures inside the issues `<details>`, so `issues.locator("summary")` matched three. It now
    reads `:scope > summary`. Its other checks pass unchanged: forty rows, the caption, paging to
    81–100, and the note.

    **The panel's styles reach into the grid.** The grid scrolls inside the same `.table-wrap` the
    table used, so `.ontology-contract-panel .table-wrap` still caps it at 230px with its own scroll.
    The panel's `summary` rule, meant for the issues and lineage disclosures, now also styles the
    grid's `Filter rows` and `Columns` summaries inside it. No gate sees either.

    T8 now saves a screenshot of the issues (`test-results/screenshots/contract-issues-grid.png`).
    At desktop-1280, where the Outputs pane is about 180px wide, it showed three things.
    - **Only the `row` column fits.** Every grid column starts at 180px, so reading an issue takes a
      sideways scroll. This is the risk the design named for wide fixed tables, and hiding or
      pinning columns is the way round it. The pager's second button is cut at the pane's edge too.
    - **N9's note is cut off after "of",** hiding the "130 rejected rows" it exists to state,
      because `.table-truncated` does not wrap. That predates this commit and is flagged as a task
      of its own.
    - **A slip from commit 2.** The sort sentence rendered at the page's 16px, four lines deep in
      this pane. It shared a rule with two lines that sit inside the grid's 12px column disclosure,
      and it set no size of its own, so on every grid site it alone took the page's size. It is
      12px now, like the rows status beside it, and reads in three lines.

    **Payload, measured.** The pipeline-builder route measures **552,973 bytes** against a ceiling of
    471,270, and the ceiling is raised to the measured number. The closure every route shares
    measures 445,486 bytes, 32 of them the sort sentence's font-size rule. That is inside the
    tolerance, and no other ceiling changed. `UI_PRIMITIVES.md` counts `DataGrid` in four files,
    adding PipelineBuilder. `DataTable` stays in fourteen, because the panel's lineage table keeps it.

    **Route cost, measured again.** Pipeline went from 13 to **15 requests** on open, and from
    491,397 to 566,186 bytes, +74,789. The two requests are the grid's own chunk, `DataGrid-*.js`,
    and `with-selector-*.js`, the helper the table library shares with the graph library, which the
    pipeline route had never loaded. The build manifest lists both among PipelineBuilder's imports,
    the same pair that took control-panel from 13 to 15 in commit 2. Every other route measured at
    its recorded request count, each 36 bytes heavier, 32 of them the font-size rule. The baseline
    is re-recorded for pipeline's two requests.

    Tests: T8 in `truncation-sites.spec.ts`, "contract issues sort, and say they rank only the issues
    the contract carries". On the final build, with the font-size rule, thirty-five pass on
    desktop-1280: all of `truncation-sites.spec.ts`, `data-grid.spec.ts`, `data-table.spec.ts` and
    `grid-sites.spec.ts`, whose sort sentences the rule restyles. So do the evaluator's contract and
    registry tests and the accessibility sweeps of the pipeline, ontology and control-panel routes
    at all four widths: 14 passed, 6 skipped by design.

    **Negative runs,** each on a rebuilt `dist`:
    - **C4a,** the issues back in a `DataTable`: T8 timed out at its first press, waiting for the
      `row` header's sort button, which a `DataTable` does not draw.
    - **C4b,** `sortScope` not passed: the descending sort put row 100 on top, and
      `.grid-sort-scope` was not found where "Sorted by row: this orders only the issues of the first
      100 of 130 rejected rows." was expected.
    - **C4c,** N9's summary check unscoped again: strict mode, `summary` resolved to 3 elements.
    - Restored: thirty pass on desktop-1280, the contract test and the pipeline sweep pass (5 passed,
      3 skipped by design), and both mutated sources are byte for byte what they were.

    **Then the operations feed, and N7d is met.** The Live Operational Feed is a grid, the last of
    the census's seven sites, and it brings the one per-column API the rollout needed. `DataGrid`
    takes `columns`, a module-level map from field name to a `GridColumnSpec`:
    - `rank`, lowercased value to rank. A ranked value sorts above one with no rank, two ranked
      values compare by rank, and two unranked values compare as values. Equal ranks return 0, so
      the library keeps arrival order inside a rank whichever way the column sorts. The lookup is
      own-keys only, so a value such as `constructor` is not read as a rank.
    - `show: "epoch-seconds"`, which draws a number of seconds as local time, the same text the
      feed drew before. The filter matches that text; the sort still compares the number.
    - `firstSort`, the first header press, ascending unless the caller says otherwise.

    The feed ranks severity `info` 0, `low` 1, `medium`, `warn` and `warning` 2, `high` and
    `error` 3, `critical` 4, as the owner decided, and its first press puts the worst first.
    `occurred` holds `created_at` as the number and shows it as before, so it sorts in time rather
    than as text, where "1:00 PM" comes before "11:59 AM". Its first press is oldest first, because
    the feed arrives newest first and a first press that changed nothing would look broken. The rows
    are memoized. N8's note stays above the grid, and the grid gets `sortScope` when the server
    holds more events than were loaded.

    Tests, both in `grid-sites.spec.ts`:
    - **T9, "the operations feed ranks severity, keeps arrival order within a rank, and returns to
      it".** Nine events from a source of the test's own, one per severity word plus `notice`,
      which no rank knows. Filtered to that source, the first press reads `aria-sort="descending"`
      and the rank tiers read 4, 3, 3, 2, 2, 2, 1, 0 and then the unranked one. The second press
      ascends. The third press returns `aria-sort="none"` and the order the rows arrived in.
    - **T10, "occurred sorts in time across the 12 o'clock hour and a year boundary, and says what a
      sort ranks".** The ingest endpoint stamps its own time, so this is the suite's first stubbed
      response, as the owner allowed: `/ops/events` and `/ops/summary` are served, under
      `locale: "en-US"` and `timezoneId: "UTC"`. Nine events from 23:00 on 2025-12-31 through
      13:00 on 2026-01-01 sort in time both ways, read through titles that name each time so the
      check does not depend on how the browser spaces "PM". The scope sentence reads "Sorted by
      occurred: this orders only the latest 9 of 1,204 events." and goes with the sort.

    On one build, thirty-seven pass on desktop-1280: all of `grid-sites.spec.ts`,
    `truncation-sites.spec.ts`, `data-grid.spec.ts` and `data-table.spec.ts`. That includes N8's feed
    test, unchanged, which hands the grid every loaded event and reads its caption. The evaluator's
    operations workflow passes, and so does the ops route's accessibility sweep at all four widths
    (5 passed, 3 skipped by design).

    **Not re-recorded: `browser-evidence-baseline.json`.** No N7d commit changed it, and neither did
    N7b's or N7c's. The fast tier does not gate it, and recording it takes a run of the whole browser
    suite, so the grid tests these commits added are not yet in that record.

    **Payload, measured.** The operations route measures **532,639 bytes** against a ceiling of
    454,562, and the ceiling is raised to the measured number. The column specs made the grid's own
    chunk heavier, so the four routes already carrying it each measured 507 to 545 bytes more:
    - pipeline-builder 553,480 against 552,973;
    - control-panel 566,010 against 565,465;
    - ontology-manager 777,762 against 777,219;
    - data-media 529,671 against 529,126.

    All four are inside the 8 KB tolerance, and their ceilings are unchanged. `UI_PRIMITIVES.md`
    counts `DataGrid` in five files. `TABLE_TRUNCATION.md` moved only by line numbers and still
    counts no silent cut.

    **Route cost, measured again.** Ops went from 18 to **20 requests** on open, and from 459,888 to
    535,150 bytes, +75,262. The two requests are the grid's own chunk, `DataGrid-*.js`, and
    `with-selector-*.js`, neither of which the ops route had loaded. The build manifest lists both
    among OpsWorkspace's imports, the same pair control-panel and pipeline gained. Every other route
    measured at its recorded request count. The three that already load the grid, control-panel,
    ontology and pipeline, are 507 bytes heavier with its chunk, and the rest are 4 bytes heavier.
    The baseline is re-recorded for ops' two requests.

    **Negative runs,** each on a rebuilt `dist`:
    - **C5a,** severity's rank removed: the tiers came out in the order of the words, not the
      ranks, and failed "severity sorts as text, not by rank".
    - **C5b,** `firstSort` removed: the first press read `aria-sort="ascending"` where
      `descending` was expected.
    - **C5c,** `enableSortingRemoval: false` passed to the table: the third press left
      `aria-sort="descending"` where `none` was expected.
    - **C5d,** the rows built from `toLocaleString()` again: `occurred` sorted as text, with 13:00 on
      2026-01-01 first and 23:00 on 2025-12-31 after the new year's times.
    - **C5e,** `sortScope` not passed: the sort ran with no `.grid-sort-scope` where "Sorted by
      occurred: this orders only the latest 9 of 1,204 events." was expected.
    - Restored: thirty-seven pass on desktop-1280, the operations workflow and the ops sweep pass
      (5 passed, 3 skipped by design), and both mutated sources are byte for byte what they were.
    - **Not separately provable:** the rows memo. Holding the rows' identity across a page
      re-render would need a re-render that keeps the page mounted, and every action here unmounts it.

    **Kept, not fixed.** Refresh, Evaluate alerts and every action on the operations page set it
    loading, which unmounts it, so a sort or a filter on the feed is lost after each. The page reset
    the same way under `DataTable`, but losing a sort is new. It shows as `aria-sort="none"`, and the
    fix belongs to the page's loading state, not to the grid. Grid columns start 180px wide at every
    site, so a narrow panel scrolls sideways, as commit 4's screenshot showed; hiding and pinning
    columns are the way round it.

    **N7d is met.** Every site the census named sorts, each proven on the site with a fixture of its
    own:
    - Users, Role Grants, API Tokens and Job Telemetry in the control panel;
    - the registry's Semantic Compatibility;
    - the pipeline contract's issues;
    - the operations feed.

    With the records grid from N7a, `DataGrid` is in five files and `DataTable` in fourteen, and
    `UI_PRIMITIVES.md` holds that count as the ratchet. The nine sites the census left unclear, and
    the 57 it said do not need sorting, stay `DataTable`. N7e, virtualization, stays open.

  - **N7e — Virtualization replacing paging where a table is measured long.** **Open**, not
    started. It opens when a site has a measured row count at which a forty-row page costs
    something. It brings a truncation-gate spelling for a virtualized draw, captions for a
    window that scrolls, a rewrite of the paging tests, and a payload decision of its own.
    `@tanstack/react-virtual` stays installed and imported by nothing until then.
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

  **Then the note itself was cut off.** A screenshot T8 takes (N7d, commit 4) showed it. At
  desktop-1280 the pipeline builder's Outputs pane is about 180px wide, and `.table-truncated`
  set `white-space: nowrap`, so the note read "Listing the issues of the first 100 of" and the
  count it exists to state lay past the pane's edge. A statement of what is missing that hides
  its own number is the silence this condition removed, one layer further down.

  **Measured before the fix, at all four widths.** A probe, run once and deleted, measured how
  far each truncation statement's text ran past the nearest box that clips it. It covered 54
  statements across the operations feed, the contract panel and job telemetry, first unfiltered
  and then filtered and sorted. Two were cut:
  - the contract note, by 87 to 90px, at the tablet, desktop and wide widths, where the Outputs
    pane is 180px wide;
  - the grid's filtered caption, "Showing 1–40 of 100 matching rows · 100 rows in all · filtered
    on field", by 168px in the same pane and by 74px at mobile. The operations feed's filtered
    caption was cut by 68px at mobile.

  Unfiltered captions, the operations and telemetry notes, the rows status and the sort sentence
  were whole. Job telemetry at mobile was not measured: the probe could not reach its Runtime tab
  at that width.

  **The fix is in two places.** `.table-truncated` no longer sets `white-space: nowrap`, so a note
  wraps inside its box. That alone does not reach the grid's caption. Its words sit in a sticky
  span as wide as the words, inside a caption as wide as the table, so nothing makes them wrap.
  The span is now held to the width the scroll area shows, less the caption's padding, using the
  width the grid already tracks for pinned columns. A `DataTable` caption is as wide as its table,
  at least 620px, so a short one still reads on one line.

  **A read-only sweep of the source agreed, and found more.** Three readers, of the CSS, the
  markup and the tests, listed every statement that could clip, and a skeptic tried to refute each
  one. The sweep read the tree while this fix was landing. Its nine findings about the contract
  note and the grid captions were refuted for that reason: the source they were checked against no
  longer set `nowrap`, and already held the caption span to the scroll area's width.

  Three findings stood. All three are estimated from font metrics rather than measured, and none is
  fixed here:
  - **A `DataTable` caption in the Outputs pane.** The table's scroll area there shows about 140px
    of a caption at least 620px wide. The field lineage table's caption clips by a few pixels from
    row 81, and a caption with four-digit counts, or any caption at the pane's `Narrow · 160px`
    width, clips further. Scrolling the table sideways reaches the tail, but the start then
    scrolls out. Wrapping cannot fix it, because the caption is as wide as its table; it needs what
    the grid now has, a span held to the visible width.
  - **Each Ontology Contracts row's "N accepted / M rejected"** is ellipsized in a 122px track once
    the two counts reach about four digits between them.
  - **The ontology manager's Drafts list is cut to six**, with nothing saying more exist. That is
    not a clipped statement but a missing one.

  Each is filed as a task of its own, to be measured before it is fixed.

  **Proven in the three tests that render a note, which now also ask that its words fit.**
  `truncation-sites.spec.ts` measures how far a statement's words run past the nearest box that
  clips them, the probe's own measure. `scrollWidth` cannot do this for a caption, whose span is
  as wide as its words wherever they land. On the build before the fix the contract test failed at
  that check. The operations note and the job telemetry note fit at desktop-1280 either way, so
  those two checks guard rather than prove. The contract test now also filters its issues on
  `field` and holds the caption to the same check, where the unfixed build hid 168px.

  On the fixed build, 37 pass on desktop-1280 across `truncation-sites.spec.ts`,
  `grid-sites.spec.ts`, `data-grid.spec.ts` and `data-table.spec.ts`. The accessibility sweeps of
  the pipeline, operations, control-panel and ontology routes pass at all four widths, with the
  contract test: 17 passed, 3 skipped by design. The probe, run again and deleted, found no hidden
  text in any of the 54 statements.

  **Negative runs,** each on a rebuilt `dist`:
  - **With `nowrap` back on `.table-truncated`,** the contract test failed at the note, 87px of
    it past the pane.
  - **With the caption span no longer held to the scroll area's width,** the note wrapped and
    passed, and the test failed at the filtered caption, 168px past the pane.
  - Restored: 37 pass on desktop-1280, and both mutated sources are byte for byte what they were.

  **Payload and route cost hold.** The shared closure is 19 bytes lighter and the grid's chunk 59
  bytes heavier, a net 40 bytes on each route that carries the grid. Every route stays inside its
  tolerance, no ceiling moved, and route cost reports no route over its requests or bytes.

  **Then the Outputs pane's other counts.** The sweep above left two there, both estimated, and
  they were measured before anything changed.

  A probe, run once and deleted, measured them on the unfixed build at all four widths and at the
  pane's `Narrow · 160px` width. The graph was real, and only the counts in three responses were
  enlarged, taken from the real reply: 12,345 field lineage rows, 1,234 execution events, 100
  partition jobs, 130 mapped lineage rows, and a contract of 12,345 accepted and 3,456 rejected
  rows.
  - **The field lineage caption was cut.** Paged to "Showing 81–120 of 12,345 rows", it ran 13px
    past the table's scroll area at the tablet, desktop and wide widths, and 73px at the narrow
    width. On its first page it reached the edge within 1px.
  - **The contract row's counts were cut.** "12345 accepted / 3456 rejected" needed 153px in a
    122px column, so 31px went behind the ellipsis, and 89px at the narrow width, the rejected
    count first. The same squeeze took the node name beside it down to no width at all.
  - **The execution events, partition jobs and mapped lineage captions measured whole** at every
    width. At mobile the panes stack, nothing ran past its right edge, and there is no narrow
    width to choose.

  **The fix.**
  - `DataTable`'s caption now holds its words in a sticky span, as the grid's does, kept to the
    width its scroll area shows. The width tracking moved out of `DataGrid` into one hook in
    `DataDisplay.tsx`, `useScrollAreaWidth`, which both tables use, with `captionFit` for the
    span's style. The CSS rule for that span now reads `.table-truncated > span`, so it covers
    both tables' captions.
  - Each Ontology Contracts row puts its counts on a line of their own across the row, where they
    wrap, and formats them with `toLocaleString` as the note does. The counts come after the status
    badge, as before, so the row's accessible name reads in the same order. Only the object type
    and node names above them can still be cut.

  **The first build of this fix still cut the counts at the narrow width, by 50px.** The row is a
  `<button>`, and every button in the product sets `white-space: nowrap`, so the counts took their
  new line but never wrapped on it. A diagnostic, run once and deleted, showed the line 72px wide
  holding 157px of text. At the default width that overflowed the row by 15px and stayed inside the
  rail; at 160px it ran 50px past the rail's edge, the test's own figure. The line now sets
  `white-space: normal`. The same diagnostic settled a probe reading: at the narrow width the lineage
  caption's span is held to 70px of a 90px scroll area. The probe's 47px there was measured before
  the pane had finished resizing, which the test's polling check does not do.

  **Proven by one test in `truncation-sites.spec.ts`,** "the Outputs pane keeps a table's
  caption and a contract's counts in view, at its default and narrow widths". Its lineage is real:
  an input over one record of 1,200 fields gives 1,200 lineage rows, and the test pages the caption
  to "Showing 81–120 of 1,200 rows". The contract counts come from the real contracts reply with
  only its counts enlarged, to 12,345 accepted and 3,456 rejected, because counts that large need a
  run over that many rows. The test holds the caption and the counts to the note's measure,
  `hiddenPx`, now taken from the statement's own box outwards, first at the default width and then
  at `Narrow · 160px`. The expected numbers are formatted by the browser, since no locale is pinned.

  On the fixed build the four desktop specs pass, 38 tests with this one, among them the grid's
  sticky caption test and the filtered caption check, unchanged after the grid moved onto the shared
  hook. The pipeline route's accessibility sweep passes at all four widths, with the pipeline
  preview, deploy and ontology contract tests: 7 passed, 9 skipped by design. On the build just
  before the counts' `white-space` line, the sweeps of all sixteen routes passed at all four widths
  (67 passed, 9 skipped by design), and so did the legacy render sweep, 4 of 4. That one declaration
  touches only the contract rows, and the pipeline sweep ran again after it.

  **Negative runs,** each on a rebuilt `dist`:
  - **N1, the `DataTable` caption without its width cap:** the test failed at the caption, 7px past
    the scroll area.
  - **N2, the counts moved back beside the badge, formatted the same:** it failed at the counts, 35px
    behind the ellipsis.
  - **N3, the span rule scoped to the grid again:** `DataTable`'s span went inline, its cap did
    nothing, and the test failed at the caption, 7px.
  - **N4, the counts without `white-space: normal`:** they kept their own line, inherited the
    button's `nowrap`, and the test failed at the narrow width, 50px.
  - Restored: 38 pass on desktop-1280, and all three mutated sources are byte for byte what they
    were.

  **Payload and route cost hold.** The shared closure is 382 bytes heavier, now holding the hook
  and the caption rule, and the grid's chunk is 162 bytes lighter for losing its own copy of the
  hook. So each route with a grid is 220 bytes heavier, the pipeline builder 283 with its row
  markup, and a route without a grid by the closure's 382. Every route stays inside its tolerance,
  no ceiling moved, and route cost reports no route over its requests or bytes.
  `TABLE_TRUNCATION.md` moved only by line numbers.

  **Then the ontology manager's Drafts list, which no gate could see.** The Drafts panel in the
  manager's Resources pane rendered `(drafts.value || []).slice(0, 6)`. The endpoint returns every
  generator draft, newest first by `updated_at`, with no cap, so the panel showed the six most
  recently updated and nothing else. A seventh draft could not be seen or applied from there, and
  nothing on the screen said it existed. `audit_table_truncation` follows cuts into tables only.
  `TABLE_TRUNCATION.md` did list this one, as `drafts.value (slice)`, mapped, not reaching a table
  and with no true count rendered, and for that reason never counted it as silent.

  **The fix keeps the six and says so.** The panel still opens on the six most recently updated
  drafts. When there are more, it says "Showing the 6 most recently updated of N drafts", in the
  same `table-truncated` note the other lists use, and a button, "Show all N drafts", lists every
  one; "Show only the 6 most recent" folds it back. The button carries `aria-expanded`.

  **Proven by one test in `truncation-sites.spec.ts`,** "the ontology manager's Drafts list says how
  many drafts there are, and shows the rest". It makes two drafts, waits a second, and makes six
  more. Draft times are whole seconds, so those two are the ones a correct list hides first. On the
  panel it checks that six rows show and all six newer drafts are among them, that the note states
  the total and is not cut off in the 260px pane, that "Show all" lists every draft including the
  two older ones and drops the note, and that the list folds back to six. The count is formatted by
  the browser. Run on the committed build before the fix, the test showed the six newer drafts and
  failed at the note: `Expected: "Showing the 6 most recently updated of 8 drafts"`, element not
  found.

  On the fixed build the test passes, and so do the other tests of `truncation-sites.spec.ts` and
  `grid-sites.spec.ts`, 15 in all. Every evaluator test that opens the ontology manager passes too,
  among them the ontology route's accessibility sweep at all four widths: 14 passed, 30 skipped by
  design.

  **Negative runs,** each on a rebuilt `dist`:
  - **N1, the silent six back:** six drafts and no note, and the test failed at the note, element
    not found.
  - **N2, a Show all that still lists six:** the note and the button were there, and the test failed
    at the drafts past the sixth: `Expected: 8`, `Received: 6`.
  - Restored: 15 pass on desktop-1280 across the two specs, the ontology evaluator tests pass, and
    the source is byte for byte what it was.

  **A sweep for other silent list cuts found nine.** Three read-only readers searched the frontend by
  code pattern, by API limit and by list panel, and a skeptic tried to refute each finding against the
  source. The Drafts finding was refuted for the right reason: the tree it read already stated the
  count. Nine stood. None has been measured in a browser yet, and none is fixed here:
  - Object Explorer loads 500 objects and reads the page as the whole set, already recorded above as
    not fixed;
  - the Decision Risk Board and its metrics score only the first 250 objects by id;
  - entity resolution scans only 1,000 objects for duplicates;
  - map layers stop at 2,000 features, and the status strip's count reads as the whole layer;
  - the platform graph stops at 500 of each kind;
  - Object Explorer's facets show 7 buckets, so a numeric facet's eighth bin, the one holding the
    maximum, is always hidden;
  - Vertex shows 24 of the 50 seed objects it fetches;
  - reliability shows the 8 newest of 25 contract runs, beside status counts taken over all 25;
  - connector fetch evidence shows the newest 50 attempts with no total.

  Five more candidates were not verified, because the readers disagreed about them: plugin executions
  and import jobs stopping at 50, the connector preview dropping its next page, the pipeline node
  preview's five rows, and the mapping preview's twenty. The sweep also read the gate.
  `audit_table_truncation` already reports plain-list slices without gating them, and it cannot see a
  request limit, a server default or a server-side cap at all. The nine findings, the five candidates
  and the gate are filed as four tasks of their own.

  **Payload, route cost and style scope.** The ontology manager route measures 778,409 bytes, 387
  more than after the Outputs pane fix and 1,190 over its recorded ceiling of 777,219. That is
  inside the 8 KB tolerance, so the ceiling is unchanged, and the shared closure did not move. Route
  cost reports no route over its requests or bytes. `.table-truncated` is now used in seven files,
  the Drafts note being the seventh; the style-scope gate reports that as a change it does not gate,
  and its baseline is re-recorded to match. The re-record also counts 311 single-file classes, not
  310: `contract-row-counts` came in with the Outputs pane fix, which did not re-record it.
  `INERT_CONTROLS.md` now counts 0 of 328 controls inert, the Show all toggle being the 328th. The
  first fast-tier run refused this commit until that reference was regenerated.

  **The truncation reference lost a row, and the gate learned nothing.** Regenerated,
  `TABLE_TRUNCATION.md` no longer lists the Drafts cut. The cut is still there on purpose, since the
  panel opens on six. The scanner still finds the `.slice(`; what it cannot read is where the result
  goes. It records a cut only when `.map` follows the slice's closing parenthesis, or when the result
  is iterated, passed as `rows`, or assigned and mapped later (`_how`), and it skips any cut it
  cannot place without a word (`cuts_in`: `if how is None: continue`). In
  `(allDrafts ? draftList : draftList.slice(0, RECENT_DRAFTS)).map(`, a parenthesis closes the
  condition before `.map`. So the reference stopped naming a list it used to name. It still counts no
  silent cut, which is true, but for a reason it cannot see, and the same wrapping would hide an
  unstated cut just as well. That hole is filed with the gate task above.

  **Then the Decision workspace's Risk Board, which scored the first 250 objects by id.** The
  workspace posted `/decision/evaluate` with `limit: 250`. The server ran `ORDER BY id LIMIT 250`,
  and the board and its metrics read as the whole type. "Objects evaluated" read 250, "High-risk
  findings" and "Average risk" were counted from those 250, the selected object was the lowest id,
  and the ops event took its severity from them. A critical object at id 251 changed no number and
  never reached the board.

  **The fix scores the whole scope, keeps the riskiest findings, and says how much of each there
  is.** The server scores every object in scope, up to a named ceiling, `EVALUATE_SCAN_CEILING`,
  still 10,000, in batches of 1,000 with the rule and scorecard catalogs loaded once.
  - It counts the scope with the scan's own filters, including `is_active`, and returns that as
    `objects_in_scope`. A total from the object-set endpoints would have counted retired objects
    too.
  - It returns `band_counts`, `high_risk_count` and an unrounded `average_score` over every scored
    object.
  - With `finding_limit: 250`, which the workspace now sends, it keeps the 250 highest scores,
    lowest id on a tie, and reports `unlisted_max_score`. A call without it keeps every finding in
    id order, as the Object Explorer's and the industrial workflow's calls still expect.
  - The saved run carries the scored count, the kept findings and the bands. The ops event takes
    its severity from all the bands, and its payload carries the totals instead of one band per
    object.

  The workspace takes its metrics from the server. When the board lists fewer findings than were
  scored, the Risk Board says "Showing the 250 highest-risk of N evaluated objects; none of the other
  M scores above S". Only when the ceiling cut the scope does a note above the metrics say "Scored the
  first N of M active objects, by id. Every figure and the board below cover only those N." The
  selected object is now the riskiest. The legacy shell sends the same request.

  **Measured before landing: scoring the whole scope is cheap enough for a click.**
  `oms/measure_decision_evaluate_cost.py` hydrates a fresh type and times one evaluation through the
  API, with one rule and a two-feature scorecard. On this Windows host 1,000 objects took 0.049 s
  and 10,000 took 0.556 s, about 0.056 s per 1,000, and the response stayed near 300 KB, because
  only the 250 kept findings travel. The ceiling stays at 10,000. Hydrating the 10,000 objects took
  12.4 s; that is the fixture's cost, not the click's.

  **Proven by one backend script and two browser tests.** `oms/test_decision_scope_totals.py`
  builds 300 real objects through a pipeline run, with index 2 and 251 to 300 critical under a rule
  and a scorecard of its own, and holds 37 assertions:
  - every scored object is counted: 300 of 300 in scope, bands of 249 low and 51 critical, a
    high-risk count of 51 and an average of 15.3;
  - the 250 kept findings are the riskiest, object 2 first, with every critical object past id 250
    among them;
  - the Object Explorer's call, which names its objects, still keeps every finding in id order;
  - with the ceiling lowered to 100, 100 are scored and 300 still counted in scope;
  - retiring 5 objects leaves 295 in scope;
  - on a type whose only critical objects sit past id 250, the ops event is critical, and it carries
    band counts rather than one band per object.

  Run against the committed server, the script failed at once with `KeyError: 'objects_in_scope'`.
  The twelve backend scripts that exercise the evaluator and its callers pass: decision intelligence
  and its tenancy, the project-scope migration, ops and reliability, the asset reliability command
  center, the five industrial workflows, project snapshots, and docs conformance.

  In `truncation-sites.spec.ts`, the first browser test builds the same 300 objects and evaluates
  them from the workspace. The metrics read 300, 51 and 15, the board lists 250 cards with objects
  251, 275 and 300 among them, object 2 is selected, and the board's note reads "Showing the 250
  highest-risk of 300 evaluated objects; none of the other 50 scores above 0." without being cut
  off, while no ceiling note shows. The second builds 5 objects and enlarges only `objects_in_scope`
  in the real evaluate reply, and the ceiling note reads "Scored the first 5 of 12,345 active
  objects, by id. Every figure and the board below cover only those 5." Both pass on the fixed build,
  and so do the existing Decision Intelligence workflow test and the decision route's accessibility
  sweep at all four widths: 5 passed, 3 skipped by design.

  **Negative runs,** each on a rebuilt `dist`:
  - **B1, the total counted after the limit:** with the ceiling lowered to 100, the backend script
    failed, reading 100 in scope where there were 300.
  - **N1, the committed Decision code, server and workspace both:** the browser test failed at the
    first metric, Objects evaluated, `Expected: "300"`, `Received: "250"`.
  - **N2, the server fixed but the metrics counted from the kept findings:** it failed at Average
    risk, `Expected: "15"`, `Received: "18"`, the average of 51 critical objects among 250 kept.
  - **N3, the board's note removed:** it failed at the note, element not found.
  - **N4, the server keeping the first 250 findings by id:** it failed at critical object 251, not
    on the board.
  - **N5, the ceiling note keyed to the findings kept rather than to the cut:** the ceiling test
    failed at the note, element not found.
  - Restored: 17 pass across `truncation-sites.spec.ts` and `grid-sites.spec.ts`, the Decision
    workflow test and sweep pass (5 passed, 3 skipped by design), and all three mutated sources are
    byte for byte what they were.

  **Payload, route cost and the references.** The decision workspace route measures 468,589 bytes,
  3,557 over its recorded ceiling of 465,032 and inside the 8 KB tolerance, so the ceiling is
  unchanged. Route cost holds: the decision route still opens with 13 requests, 913 bytes heavier.
  `.table-truncated` is now used in eight files, the Risk Board's notes being the eighth, and the
  style-scope baseline is re-recorded to match. `TABLE_TRUNCATION.md` moved only by line numbers.
  It still lists each card's `drivers.slice(0, 3)`, a per-object preview whose full list the Explain
  tab shows. `INERT_CONTROLS.md` does not move, since the fix adds no control. Entity resolution's
  scan, the other limit in this workspace, lands in a commit of its own.

  **Then entity resolution, which compared the first 1,000 objects in no stated order.** The
  workspace posted `/entity-resolution/jobs` with `limit: 1000`. The server read up to that many
  objects with no `ORDER BY` and compared every pair among them. The Candidate Review Queue read as
  the type's whole duplicate list, an empty queue said "No candidates", and Explain called any object
  with no pending candidate "clear", including objects the job never read.

  **The fix states what each job compared; it does not yet reach the rest.** The scan now reads in
  id order under a named `ENTITY_SCAN_CEILING` of 5,000, so "the first N" names a set. Each job
  keeps three facts in new nullable columns, added by migration `0044_entity_resolution_coverage`:
  `objects_in_scope`, counted with the scan's own filters; `objects_scanned`; and `last_scanned_id`.
  The job list returns them after a reload, the create response adds the scan order and limit, the
  audit entry carries them, and project snapshots export and restore them. Explain gains
  `duplicate_coverage` from the latest completed job over the object's type. An object counts as
  compared only if its id is at or below the job's last id, checked in SQL so the order is the one
  the scan used, and it existed when the job ran. Explain also gains `duplicate_warning_count`, since
  its list stops at five.

  The workspace keeps the whole job, not only its candidates. When a job compared fewer objects
  than its type holds, the queue says "Compared the first N of M objects, by id. Pairs involving the
  other K were not compared.", and an empty queue says "No candidates among the first N objects". The
  duplicate badge says "clear" only when the latest job compared the object and left nothing pending;
  otherwise it reads "not compared", or "not loaded" before an explanation. The legacy shell's toast
  names the same counts.

  **Reaching past the scan is a product decision, and it is open.** Every pair is compared inside
  the request, so the cost grows with the square of the scan: 499,500 pairs at 1,000 objects, 12.5
  million at the 5,000 ceiling. The goal doc has no precedent for reaching the rest of a quadratic
  scan, and each way of doing it trades recall, latency or a locked screen, so the question is put to
  the owner rather than settled here.

  **The proof.** `oms/test_entity_resolution_coverage.py` builds 1,002 objects of one type. A
  duplicate pair with the highest ids is hydrated from a source asset whose id sorts before the
  fillers'. SQLite reads this scope through the materialization index, in source-asset order and
  then id order, so a scan without `ORDER BY` would read the pair first; only a scan in id order
  leaves it out. The 1,000 fillers carry no name. A job at limit 1,000 must count 1,002 in
  scope and 1,000 compared, end at filler 999, report `scan_order` "id", write no candidate, and keep
  all three facts in the reloaded job list. Explain must say the pair's first object was not
  compared, a filler was, and an object made after the job was not. A job at limit 5,000 must find
  the pair, and Explain must then count one warning. A type no job has read gets no coverage. Run
  against the committed server, it failed at once: every coverage field came back `None`.
  `oms/test_entity_resolution_coverage_migration.py` upgrades to 0043 and removes the three columns
  that `0001`'s `create_all` builds from today's models, so it stands for a database from before
  them. It inserts a job, upgrades to head, checks that the old job's three columns are NULL, applies
  head twice, downgrades and upgrades again. The first draft asserted that 0043 had no such columns,
  and it failed for exactly that reason, which is how the `create_all` baseline showed itself. On the
  fix both pass: 31 assertions and the migration check. So do the backend scripts over the evaluator,
  entity resolution, snapshots, tenancy and the migration head, 32 in all. The
  tenancy census caught one read the first draft added, the SQL id comparison with no project
  filter, and passed once it named the object's project.

  In `truncation-sites.spec.ts`, the first browser test builds 1,100 objects with a duplicate pair
  at 1 and 2 and another at 1,099 and 1,100, runs Find duplicates, and finds the first pair. The
  queue's note reads "Compared the first 1,000 of 1,100 objects, by id. Pairs involving the other 100
  were not compared." without being cut off, and Explain on object 1,099 reads "not compared". The
  second builds 1,002 objects with nothing to match, and the empty queue reads "No candidates among
  the first 1,000 objects". Both pass on the fixed build.

  **Negative runs,** each on a rebuilt `dist` where the browser is involved:
  - **B0, the committed server:** the backend script failed at the job's coverage, every field
    `None`.
  - **B1, the scan without `ORDER BY`:** it failed with the pair read inside the first 1,000: one
    candidate, and the last id read filler 997. It took three fixtures. With the pair stored first
    by insertion, and then by a hydrate run of its own, the mutation passed both times, because
    SQLite reads this scope through `ix_object_instances_materialized_active`, ordered by source
    asset and then id whatever order the rows were stored in. The fixture now gives the pair a
    source asset that sorts first. The `ORDER BY` is what makes the order hold on a database whose
    plan does not.
  - **B2, the total counted after the limit:** it failed reading 1,000 in scope where there were
    1,002.
  - **B3, compared without the created-at check:** it failed at the object made after the job, called
    compared.
  - **N1, the committed Decision code, server, client and workspace:** the queue test failed at the
    note, element not found.
  - **N2, the server keeping coverage but the workspace keeping only the candidates:** it failed at the
    note, element not found.
  - **N3, the badge back to "clear":** it failed at object 1,099, `Expected: "not compared"`,
    `Received: "clear"`.
  - **N4, the empty state back to "No candidates":** the empty-queue test failed, element not found.
  - Restored: the four Decision tests in `truncation-sites.spec.ts` pass, the Decision workflow test and
    sweep pass (5 passed, 3 skipped by design), the coverage script passes, and all three mutated
    sources are byte for byte what they were.

  **Payload, route cost and the references.** The decision route still opens with 13 requests, at
  460 KB, and its chunk measures 458 KB with the shared closure, under its ceiling, so neither
  baseline moves. `.table-truncated` gains no file, since the queue's note is in
  `DecisionWorkspace.tsx`, already counted. `TABLE_TRUNCATION.md` moved only by line numbers, and
  `INERT_CONTROLS.md` does not move, since the fix adds no control. The migration head is now
  `0044_entity_resolution_coverage`.

  **The migration staled four baselines, and re-earning them found four reads per record.** Moving
  the head to 0044 is what `audit_iteration_state` exists to notice: four baselines record the head
  they were measured at, and the fast tier refused the commit with 22 of 23 until they described this
  schema. As at 0043, each was measured again rather than re-stamped, on a tree holding only this
  change. Query bounds held at 0 materializing call sites and 0 mapper bypasses. Request cost held: no
  route repeats a statement shape more than 4 times, under the ceiling of 6.

  The suite census did not hold. `POST /pipelines/{id}/run` repeated one statement 2,001 times where
  its baseline says 4. The route had not changed; its fixtures had. The census uses the suite as
  traffic, and this goal's backend scripts are the first to hydrate hundreds of objects in one run:
  300 in the Risk Board's, 1,002 in this one. Each census named the next per-record read once the one
  before it was gone:
  - **The object type's profile, twice per object.** `create_object` and `update_object` resolved the
    schema once to drop nulls and again to validate, and each resolve reads the profile. A type with
    no profile has nothing for `db.get` to keep, so every call read again. Both now take the schema
    the hydrate already resolves once per type, and resolve it once themselves otherwise.
  - **Whether each object exists,** one select per record. The hydrate now reads the batch's existing
    objects in chunks of 500 before its loop. Objects the loop creates are not added, so a record
    repeating an id behaves as it did.
  - **The project's production environment.** Only a found environment was cached, and no test
    project has one. A miss is now cached too, and forgotten by the first flush that writes an
    environment, before which the query could not have seen one.
  - **Each object's last decision snapshot.** `prime_snapshot_seqs` reads them for the batch in one
    grouped query a chunk, the trade `prime_change_versions` already makes.

  The route now runs 66 statements with a worst repeat of 4 on a hydrate of 1,000 records, where its
  baseline measured 68 on a handful. The census then wrote the suite-cost baseline over 696 route and
  method pairs, 32 of them above the ceiling of 6, one fewer than before: `run-next` falls from 2,006
  repeats to 1,004 with the same fixes, and five other routes improved. Three routes rise, none of
  them by this change, and each is recorded as measured. `POST /artifacts/adopt` repeats a project
  lookup 3 times against 2, and the package version capture 4 times against 2; both lookups arrived
  with the tenancy commit of 2026-09-02, after the last census, and both stay under the ceiling. `GET
  /project/readiness` repeats a migration-record insert 33 times against 22. That is the fallback
  taken when concurrent first calls race to write the 32 migration records: in three runs of its one
  script, 17, 15 and 9 of 48 calls took it, and the first census today stayed within 22, so the count
  follows timing rather than code. The probe was not repeated on the committed tree.
  `test_request_cost_concurrency.py` exits non-zero under the census recorder in both censuses and
  passes on its own, and `test_iteration_state_audit.py` failed until these baselines were written.

  The browser run found one more thing the new tests' data exposed. The legacy shell's accessibility
  test failed at wide-1600, the last width to run, with "Form elements must have labels", and passed
  when run alone. A diagnostic that creates one ontology generator draft reproduced it: the draft's
  property table renders a disabled Include checkbox per row with no name. Earlier specs leave drafts
  behind, so the page listed one only once they had run. Each checkbox is now named for its property,
  and the same diagnostic then reported no label violation. The browser run then passed at all four
  widths, 220 ran, 388 skipped by design, 0 failed and 0 flaky, from a bundle built from the current
  source, and its baseline is written with the one known failure still listed.

  **Then the server's severity ranking, filed at N7d.** The operations feed ranks `warning` with
  `warn` and `error` with `high`, as the owner decided. The server did not. `ops_control.py` and
  `platform_core.py` each kept an identical map with neither word, so both ranked with `info`. The
  platform's own emitters send exactly those words: a job that runs out of retries says `error`, a
  failed connection sync says `error`, stream backpressure and quarantine say `warning`, and an SLO
  breach says `warning` or `error`. A rule at minimum high, the default for a new rule, the React
  form and the reliability scenario, therefore raised no alert and no inbox notification for any of
  them, and a rule at minimum medium missed every warning. Event subscriptions missed the same events.

  **One map, read through one helper.** `ops_control.SEVERITY_RANK` gains the two words, and
  `severity_rank(value, unknown)` compares them trimmed and lowercased. `platform_core` drops its copy
  and reads through the helper; it already imported `ops_control`, so there is no cycle. The alert
  rule's threshold is now lowercased too, as the subscription's already was, so a stored "Critical"
  means critical. A critical rule still does not fire on `error`, which ranks with high. Each path
  keeps its default for a word in no rank: an unknown rule threshold still acts as high, an unknown
  subscription threshold still matches everything, and an unknown event word still ranks as info.
  Rejecting unknown words with a 422, or giving both paths one default, would change stored rules and
  subscriptions nobody has reviewed, so both are known and not fixed. Only the feed's comment changes
  in the frontend, since its map was already the owner's; it now names the test that holds the two
  equal. Existing databases will show more alerts once someone presses "Evaluate alerts", because old
  warning and error events will match rules they always should have.

  **The proof.** `oms/test_ops_severity_rank.py` runs five blocks, each on its own, and prints every
  failure. Rules and events go through the real routes. On an `ERROR` event there are rules at
  high, critical and "Critical", and on a `warning` event rules at medium and high. The alerts raised
  must be exactly the high rule on the error and the medium rule on the warning. The same thresholds
  as subscriptions must match 1, 0, 1 and 0. One block requires one map and a helper that trims and
  lowercases. Another reads the feed's map out of `OpsWorkspace.tsx` and requires it to equal the
  server's. The last guards the kept defaults for unknown words. Run against the committed server,
  four blocks failed: the map lacked both words, the feed's map differed from it, no alert was raised
  at all, and all four subscriptions matched nothing. The unknown-word guard passed, as it should. On
  the fix, 41 assertions pass. So do the four scripts that exercise these routes: ops and
  reliability, the unified platform, operational-plane tenancy, and the asynchronous job runtime.

  **Negative runs,** one mutation at a time:
  - **`error` dropped from the map:** only the medium rule fired; `sub_e_high` matched 0.
  - **`warning` dropped:** only the high rule on the error fired; `sub_w_medium` matched 0.
  - **`error` ranked 4:** the critical and "Critical" rules fired on the error; `sub_e_crit` matched 1.
  - **`warning` ranked 3:** the high rule fired on the warning; `sub_w_high` matched 1.
  - **The rule threshold not lowercased:** "Critical" fell to the unknown default, high, and fired on
    the error. Only the alert block failed.
  - **Subscriptions reading the old map:** every subscription matched 0. Only that block failed.
  - **An unknown rule threshold defaulting to info, an unknown subscription threshold to high, an
    unknown event word to low:** each failed only the unknown-word guard, at its own assertion.
  - **A second copy of the map in `platform_core`:** only the one-map block failed, although every
    alert and subscription still came out right.
  - **The helper not trimming:** " Warning " ranked unknown.
  - **`error: 3` dropped from the feed's map:** only the feed block failed.
  - **The server gaining a word the feed lacks:** the map and feed blocks failed, and so did the
    unknown-word guard, since `notice` was no longer unknown.
  - Restored: 41 pass, and both sources are byte for byte what they were.

  **Then the transactions route that emptied a dataset, filed under N7c.** `POST
  /datasets/{id}/transactions` rebuilt the dataset's rows as the fold of its transaction log, and
  the fold starts from nothing. A dataset made by `POST /data-assets` has rows and no log. So APPEND
  left only the appended rows, UPDATE left only the patch fields, and DELETE of one row emptied the
  dataset, while the 201 reply reported only the payload's size. A dataset with a snapshot was not
  safe either: an upload, a connector sync or a pipeline run writes rows outside the log, and the next
  transaction dropped them. A branch of a dataset with no log seeded no rows.

  **Reconcile, never discard.** Before a transaction or a branch folds over master, the new
  `_reconcile_master` compares the log's fold with the dataset's rows. When they differ it records the
  rows as a baseline SNAPSHOT, so the caller's transaction starts from them, and it audits that as
  `dataset.transaction.baseline_recorded` with the reason: no history, or rows changed outside the
  log. A SNAPSHOT still replaces, but the rows it replaced stay reachable with `as_of_seq`. The
  committed audit entry now says how many rows the dataset holds. On a dataset with rows the log never
  saw, the caller's first transaction takes seq 1 instead of 0; nothing in the repo reads that seq.
  The route fetches the dataset once instead of twice, so the tenancy census falls from 361 unscoped
  reads to 360, and its recorded ceiling is lowered to match. No response shape, route or screen
  changes.

  Five neighbours are left as their own tasks: the pipeline builder's own snapshot commit, which
  replaces by design; a transaction on a branch that was never created; assets whose rows live in a
  parquet snapshot; the seq race, since nothing makes (dataset, branch, seq) unique; and project
  scoping in `datasets_ext`. N7c's row selection stays deferred: this fix names no use for selected
  rows.

  **The proof.** `oms/test_dataset_transaction_base.py` runs nine blocks, each on its own, and prints
  every failure. Datasets are made by `POST /data-assets` with two rows. APPEND must keep both. DELETE
  of one must leave the other. UPDATE of one field must keep the row's other fields. A SNAPSHOT must
  replace the rows but keep them at `as_of_seq=0`. A row uploaded after a SNAPSHOT must survive the
  next APPEND. A branch must seed both rows. The baseline must be audited once, with its reason, and
  the committed entry must say how many rows the dataset holds. Two guards pass on the old code by
  design: a dataset whose every write went through the log gets no baseline and applies nothing
  twice, and a write to another branch leaves master alone. Run against the committed route, seven
  blocks failed, each with the loss it guards: APPEND left ids [3], DELETE left [], UPDATE left
  `[{'id': 1, 'v': 99}]`, `as_of_seq=0` gave `[{'id': 9}]`, the uploaded row was dropped (ids [1, 3]),
  the branch seeded 0 rows, and no baseline was audited. On the fix, 80 assertions pass. So do the six
  scripts over the same routes: data integration, uploads, the deep Foundry programs, asynchronous
  pipeline execution, the datasets and connectivity extension, and the tenancy census, now at 360.

  **Negative runs,** one mutation at a time:
  - **No baseline ever written:** the same seven blocks failed as on the committed route.
  - **A baseline only when the log is empty:** only the drift blocks failed, ids [1, 3] and no drift
    baseline audited, which is what separates this fix from the weaker rule.
  - **A baseline on every transaction:** the in-sync guard failed on a log of six entries where three
    were written, and `test_data_integration` failed at its time travel, `as_of_seq=0` giving 0 rows.
  - **A branch seeded from the log alone:** only the branch block failed, 0 rows.
  - **Other branches reconciling master:** only the other-branch guard failed, master gaining id 3.
  - **A flush, then folding the log again:** the caller's transaction applied twice, ids
    [1, 2, 3, 3], and `test_data_integration` failed the same way.
  - **A SNAPSHOT exempt from the baseline:** only the history block failed.
  - **The baseline not audited:** only the audit block failed.
  - Restored: 80 pass, data integration passes, and the source is byte for byte what it was.

  **Then the Object Explorer's facet cards, the first of the smaller lists.** Each card drew the first
  seven buckets of its facet, whatever the facet was. A histogram always has eight bins, and the last
  one holds the maximum, so the top of every numeric distribution was missing. A value list kept the
  seven most common of the twenty the server sends, of however many values there were, and said
  nothing about either cut.

  **A histogram draws every bin; a value list says how many values it holds.** The server's value
  lists now carry `distinct_count`, which costs nothing, since the counts it sorts already hold every
  value; the twenty-value cap stays. A new `FacetCard` draws every histogram bin. A value list shows
  the seven most common, and when that is fewer than it holds, a note reads "Showing the 7 most common
  of N values". Its toggle, with `aria-expanded`, reads "Show all N values" when the server sent every
  value, "Show the 20 most common" when it kept twenty, and "Show only the 7 most common" to fold back.
  A value list the card shows whole says nothing. The counts cover the loaded page of up to 500
  objects, as the facets always have; that the page reads as the set stays filed on its own.

  **The proof.** `test_deep_foundry_programs.py` now requires every value list in its explorer query
  to carry `distinct_count` equal to the distinct values among the returned objects, and to keep
  twenty at most. Run against the committed server, it failed at the first value list, which had no
  `distinct_count`. In `truncation-sites.spec.ts`, a new browser test builds 23 objects: 23 names, 10
  sites, and scores 0 to 110. The score card draws 8 bins, the last holding 110, with no note. The name
  card draws 7 and reads "Showing the 7 most common of 23 values" without being cut off; "Show the 20
  most common" draws 20 with `aria-expanded` true and reads "Showing the 20 most common of 23 values";
  "Show only the 7 most common" folds back. The site card reads "Showing the 7 most common of 10
  values", and "Show all 10 values" draws 10 and removes the note. It passes on the fixed build with
  the Object Explorer workflow test and the explorer columns test.

  **Negative runs,** each on a rebuilt `dist`:
  - **N1, histograms cut to seven again:** it failed at the score card, `Expected: 8`, `Received: 7`.
  - **N2, the note removed:** it failed at the name card's note, element not found.
  - **N3, the total taken from the kept buckets:** it failed at the note, `Received: "Showing the 7 most
    common of 20 values"`.
  - **N4, a toggle that does nothing:** it failed at the name card, `Expected: 20`, `Received: 7`.
  - **N5, the server without `distinct_count`:** the card fell back to the twenty it was sent and failed
    the same way, "of 20 values".
  - Restored: the three explorer tests pass, the backend script passes, and both sources are byte for
    byte what they were.

  **The truncation reference lost the facet cut, the Drafts hole again.** `TABLE_TRUNCATION.md` no
  longer lists `facet.buckets (slice)`. The cut is now bound to a name, `shown`, and mapped, but the
  binding holds a condition: `listogram && !expanded ? facet.buckets.slice(...) : facet.buckets`.
  `_how` follows a cut only when it is the whole right side of `const x =`, or is mapped at once, so a
  cut behind a condition is not followed. That is the gap the gate task at the end of this list
  closes, and this cut is one it must find. The inert-control reference counts the toggle: 0 of 329.
  The Object Explorer route still opens with 13 requests, at 449 KB, and its chunk measures 447 KB
  with the shared closure of 436 KB, under its ceiling. No class became shared: the card's footer
  class is the explorer's own, and `.table-truncated` was already used in this file.

  **Then Vertex's seed list.** "Seed from object type" asked `/objects/{type}` for 50 objects, which
  returns a bare list with no total and no order, and drew the first 24 as buttons. Past the 24th, no
  object of a type could be picked from the panel, and nothing said the type held more.

  **The list now pages through the type with a true total.** The panel asks the existing
  `/object-sets/search` for 24 objects at an offset, with `with_total`, so no route or response
  changes. It draws every object it is given. When the type holds more, a note reads "Showing 1–24 of
  N objects", and Previous objects and Next objects buttons, disabled at the ends and while a page
  loads, reach the rest. The wording says which objects by position, never "latest": the search has no
  `ORDER BY`, and pages follow insertion order.

  **The first build's note ran ahead of its objects.** The note was counted from the offset asked for,
  so pressing Next changed it to "Showing 25–48" at once, while the buttons were still the first 24
  until the page arrived. The browser test caught it: the text and the counts matched at every step,
  and paging reached only 36 distinct objects of 60, because the second page's ids were read before
  they had replaced the first. The note and the buttons now count from the page on screen, which the
  search result carries. The test holds the next page's response back with `page.route` and requires
  the note to still read "Showing 1–24 of 60 objects" while it waits.

  **The proof.** In `truncation-sites.spec.ts`, a new browser test hydrates 60 objects of a fresh type,
  opens Vertex, and picks the type under "Seed from object type". The panel draws 24 buttons and reads
  "Showing 1–24 of 60 objects" without being cut off, with Previous objects disabled. Holding the next
  page's response back, it presses Next objects and requires Next to be disabled and the note to still
  read "Showing 1–24 of 60 objects" while the page loads; released, the second page reads "Showing
  25–48 of 60 objects" with 24 buttons, and the third "Showing 49–60 of 60 objects" with 12 and Next
  disabled. The ids read across the three pages are the 60 created, each once. It passes on the fixed
  build.

  **Negative runs,** each on a rebuilt `dist`:
  - **N1, the committed view and client:** it failed at the note, element not found, with 24 of the 50
    buttons drawn.
  - **N2, the total taken from the page:** a page read as the type, and the note was not found.
  - **N3, a Next button that does not move the offset:** no page was asked for, and it failed at Next,
    still enabled.
  - **N4, the note counted from the offset asked for:** it failed while the page was held,
    `Received: "Showing 25–48 of 60 objects"` over the first 24 objects.
  - Restored: the test passes, and both sources are byte for byte what they were.

  **The references.** `TABLE_TRUNCATION.md` drops the Vertex row, since the cut moved from the client
  to the server's page. `INERT_CONTROLS.md` counts the two new buttons: 0 of 331. `.table-truncated`
  is now used in nine files, Vertex the ninth, and the style-scope baseline is re-recorded to match.
  The Vertex route's chunk measures 452 KB with the shared closure of 436 KB, under its ceiling;
  the route is not among the sixteen route cost measures.

  **Then the Reliability tab.** `GET /reliability/summary` read the 25 newest data contract runs, built
  its status counts and the posture's PASS, WARN or FAIL from them, and returned 8 of the 25. The tab
  showed the counts beside a "Data contracts" metric that counts every contract, and listed the 8
  under "Latest Data Contract Runs". Nothing said the counts covered 25 runs, or that the list was 8 of
  them.

  **Every run the counts came from is listed, and both panels say what they cover.** The summary now
  returns all the runs it read, with `contract_runs`, a count of every run, and
  `contract_run_window`, how many it read. Both are in the response only, so the snapshot row each
  call writes keeps its shape, and the posture's meaning is unchanged: it is still the latest 25, now
  said. When more runs exist, the posture reads "Status counts cover the latest 25 of N contract runs"
  and the table "Loaded the latest 25 of N contract runs".

  **The proof.** `test_ops_investigations_reliability.py` now runs its contract 26 more times and requires
  the summary's `contract_runs` to equal the contract's own run list, more than 25, and the runs it lists
  to number 25, equal to `contract_run_window`. In `truncation-sites.spec.ts`, a new browser test runs one
  contract 26 times, reads the true count from the summary, and opens the Operations Reliability tab: the
  table lists 25 runs, it reads "Loaded the latest 25 of N contract runs", and the posture reads "Status
  counts cover the latest 25 of N contract runs", neither cut off. Both pass on the fix: 65 backend
  assertions and the browser test.

  **Negative runs,** each on a rebuilt `dist` where the browser is involved:
  - **B1, the list cut to eight again:** the backend script failed reading 8 runs where the counts came
    from 25.
  - **B2, the total counted from the runs read:** it failed reading 25 where 27 exist.
  - **N1, the server listing eight with both notes kept:** the browser test failed at the table,
    `Expected: 25`, `Received: 8`.
  - **N2, the table's note removed:** it failed at that note, element not found.
  - **N3, the posture's note removed:** it failed at that note, element not found.
  - **N4, the committed server and screen:** it failed at the fixture's check, the summary reporting no
    `contract_runs`.
  - Restored: the Reliability test and the operations feed tests pass, the backend script passes, and all
    three sources are byte for byte what they were.

  **The references.** The operations route still opens with 20 requests, at 523 KB, and its chunk
  measures 521 KB with the shared closure of 436 KB, under its ceiling. `.table-truncated` was already
  used in `OpsWorkspace.tsx`, and neither `TABLE_TRUNCATION.md` nor `INERT_CONTROLS.md` moves.

  **Then Fetch Evidence.** Data Onboarding's Fetch Evidence panel listed a connector source's fetch
  attempts from `GET /connections/sources/{id}/fetch-attempts`, which returns the 50 newest as a bare
  list with no total. The table paged the 50, and nothing said the source held more.

  **The server says how many attempts there are, in a header.** The route counts the same filtered
  query and sets `X-Total-Count`. The body stays a bare list, because the REST, Kafka, S3 and SFTP
  backend tests and any other caller count it; wrapping it would have broken them, and a separate
  count route would have been a second request for one number. The shared client gains
  `apiWithTotal`, which reads the header beside the JSON body. When the source holds more than was
  loaded, the panel reads "Loaded the latest 50 of N fetch attempts".

  **The proof.** `test_live_connector_runtime.py` now asks for a window of one attempt and requires a
  list of one with `x-total-count` of 3, the attempts the script made; the Kafka, S3 and SFTP scripts,
  which count the same list, pass unchanged. In `truncation-sites.spec.ts`, a new browser test serves
  a REST source from a local server, previews it once through the screen, 51 times through the API and
  once more through the screen, and requires the panel to read "Loaded the latest 50 of 53 fetch
  attempts", not cut off, over a table of 50 rows. It passes on the fixed build, with the existing live
  connector workflow test.

  **Negative runs,** each on a rebuilt `dist` where the browser is involved:
  - **B1, the header dropped:** the backend script failed at the header, the response carrying only
    its length and type.
  - **N1, the server sending no header:** the browser test failed at the note, element not found.
  - **N2, the client counting the list it received:** the total equalled the 50 loaded, and the note
    was not found.
  - **N3, the committed code:** it failed at the note, element not found.
  - Restored: both browser tests pass, the backend script passes, and all four sources are byte for
    byte what they were.

  **The references.** The shared closure every route loads holds at 436 KB with `apiWithTotal` in it, and
  no route exceeds its payload ceiling. Data Onboarding still opens with 12 requests, at 443 KB.
  `.table-truncated` is now used in ten files, `App.tsx` the tenth, and the style-scope baseline is
  re-recorded to match. `TABLE_TRUNCATION.md` and `INERT_CONTROLS.md` do not move.

  **Then Data Onboarding's import jobs.** `GET /ui-state/imports` loaded the 50 most recently updated
  import jobs and counted everything from them: the "Import jobs" metric read `len(jobs)`, so it showed
  50 however many jobs existed, and the ready, invalid, promoted and dataset counts in its sections came
  from the same 50. "Recent Import Jobs" listed `GET /imports/jobs`, which returns the 50 newest, and
  said nothing about the rest.

  **Every count is over every job, and the recent list says it is a window.** The summary now counts
  every accessible job in SQL: the job count, the counts by status, the promoted jobs and the distinct
  datasets they promoted to. The one count that needs each job's stored schema, the jobs with
  transformations, stays over the latest 50 and is renamed `transformed_in_latest_50` to say so.
  `GET /imports/jobs` keeps `count` as the jobs returned, which callers read, and adds `total`. When more
  jobs exist than it lists, "Recent Import Jobs" reads "Loaded the latest 50 of N import jobs". The
  warnings and evidence links still cover the latest 50 with nothing said; they are listed here as not
  fixed.

  **The proof.** `test_human_ui_readiness.py` now creates 51 more import jobs and requires the summary's
  job count to equal `/imports/jobs`' total, more than 50, its counts by status to add up to it, and its
  upload section to carry the same count; `test_productized_platform.py` requires a window of one job to
  report the same total as the whole list, and `test_import_tenancy.py` a total of 0 for a project that
  sees none. In `truncation-sites.spec.ts`, a new browser test creates 51 jobs, reads the true total from
  the list, and requires Data Onboarding's "Import jobs" metric to show it and "Recent Import Jobs" to
  read "Loaded the latest 50 of N import jobs", not cut off. They pass on the fix, with the Data
  Onboarding connector tests and the compatibility, UI alignment and tenancy scripts.

  **Negative runs,** each on a rebuilt `dist` where the browser is involved:
  - **B1, the list without its total:** `test_productized_platform.py` failed with `KeyError: 'total'`.
  - **B2, the summary counting the jobs it loaded:** `test_human_ui_readiness.py` failed reading 50
    jobs where 52 exist.
  - **N1, the metric counting the jobs loaded:** the browser test failed at the metric, `Expected: "51"`,
    `Received: "50"`.
  - **N2, the note removed:** it failed at the note, element not found.
  - **N3, the committed code:** it failed at the fixture's check, the list reporting no total.
  - Restored: the five Data Onboarding browser tests pass, the five backend scripts pass, and both
    sources are byte for byte what they were.

  **The references.** Data Onboarding still opens with 12 requests, at 443 KB, and no route exceeds its
  payload ceiling. `.table-truncated` was already used in `App.tsx`, and neither `TABLE_TRUNCATION.md`
  nor `INERT_CONTROLS.md` moves. The tenancy census holds at 360: every new count runs on the
  project-scoped job query.

  **Then an extension's runs.** The Control Panel's Extensions section loaded an extension's runs from
  `GET /api/v1/plugins/{id}/executions`, which returns the 50 newest with no total, and listed them as
  its execution evidence with nothing said about any older run.

  **The server counts the runs, and the panel says when it loaded the latest of more.** The response,
  already an object, gains `total`, counted over the same project-scoped filter. The section keeps it
  beside the runs; a run queued from the screen raises it by one unless that run was already listed.
  When there are more runs than were loaded, the evidence panel reads "Loaded the latest L of N runs".

  **A real extension, with its count enlarged.** The browser test registers a real signed extension,
  built by `oms/build_rehearsal_plugin.py`, activates it and queues three runs through the API. Past
  fifty real sandboxed runs the fixture would be a load test, so the real run list is fulfilled with
  only its `total` enlarged by 75, the arrangement the Outputs pane test already uses. Registering an
  extension writes its bundle, and the browser suite's server did not say where, so bundles went to a
  folder at the repository root that git does not ignore; `playwright.config.ts` now sends them under
  `oms/storage`, which it does.

  **The proof.** `test_signed_plugin_runtime.py` now reads a window of one run and requires its `total`
  to equal the length of the whole list. In `truncation-sites.spec.ts`, a new browser test registers the
  extension, queues three runs, fulfils the run list with its `total` enlarged by 75, and requires the
  evidence panel to read "Loaded the latest 3 of 78 runs". They pass on the fix, with
  `test_async_plugin_execution.py`.

  **Negative runs,** each on a rebuilt `dist` where the browser is involved:
  - **B1, the window without its total:** `test_signed_plugin_runtime.py` failed at the new assertion,
    the one-run window carrying no `total`.
  - **N1, the note removed:** the browser test failed at the note, element not found.
  - **N2, the total taken from the runs loaded:** it failed at the note, which never rendered.
  - **N3, the server without a total:** it failed at the note; the reply it enlarges had no total.
  - **N4, the committed code:** it failed at the note.
  - Restored: the four matching Control Panel, extension and evaluator browser tests pass, both plugin
    backend scripts pass, and the three sources are byte for byte what they were.

  **The references.** The Control Panel still opens with 15 requests, at 556 KB, within its payload
  ceiling. `.table-truncated` was already used in `ControlPanel.tsx`, and neither `TABLE_TRUNCATION.md`
  nor `INERT_CONTROLS.md` moves. The tenancy census holds at 360: the count runs on the project-scoped
  execution query.

  **Then the pipeline drawer's preview.** Selecting a node asks `POST .../nodes/{id}/preview` for 50
  rows. The endpoint sliced the node's stored sample, and `_execute_graph` cut every node's sample to 5,
  so the drawer drew at most 5 rows of any node, with nothing said, and the `limit` did nothing. Beside
  it the Selected Node panel labelled the node's full row count `preview_rows`.

  **The preview returns what it asks for, and says how many the node holds.** `_execute_graph` takes the
  node a preview names and keeps that node's rows up to the limit; every other node's sample stays at
  5, because the canvas and node details carry every node's sample. The drawer's preview tab reads
  "Previewing the first N of M rows" when the node holds more, counted from the same reply its rows
  came from, and pages the rows it has. The Selected Node panel's key is now `rows`, the name the
  drawer's selection tab already used for the same number.

  **And the drawer could not be reached at 1280 by 900.** Above 900px wide the Pipeline Builder fixes
  its page to the viewport and hides what overflows, and the row of side-by-side panes keeps a 520px
  floor, so the bottom slot, the Evidence drawer holding this preview, sat below the clip where no
  pointer or wheel could reach it. The browser test found it: its click on the drawer's tab landed on
  `section.builder-main`. The panes now scroll inside their row. Scrolling alone was not enough, and the
  second run showed why: the bottom slot, a flex child with no floor of its own, shrank to nothing and
  the drawer spilled under the row above, where the click landed on the node library. Each part of the
  pane host now keeps its height.

  **The proof.** A new `test_pipeline_node_preview_window.py` previews a 60-row input and requires 50
  rows back with a row count of 60, and 3 rows for a limit of 3, while the canvas and node details keep
  every sample at 5. In `truncation-sites.spec.ts`, a new browser test builds the same graph, opens the
  drawer's preview tab, requires "Previewing the first 50 of 60 rows", not cut off, and pages the table
  to "41–50 of 50 rows"; its two clicks are the hit test that the drawer can be reached. They pass on
  the fix, with the pipeline evaluator tests, the Outputs pane test, all 20 movement-contract tests and
  five pipeline backend scripts.

  **Negative runs,** each on a rebuilt `dist` where the browser is involved:
  - **B1, the preview cut to five again:** the backend script failed, "the preview asked for 50 rows and
    returned 5".
  - **B2, every node keeping more:** it failed at the canvas, "the canvas carries samples of [60, 60]
    rows".
  - **N1, the server cutting to five:** the browser test failed at the note, which read "Previewing the
    first 5 of 60 rows".
  - **N2, the note removed,** and **N3, the total taken from the rows shown:** each failed at the note,
    element not found.
  - **N4, the committed code,** and **N5, the pane rules removed:** each failed at the click on the
    drawer's preview tab.
  - Restored: the three matching browser tests and six backend scripts pass, and the four sources are
    byte for byte what they were.

  **The references.** The Pipeline Builder opens with 15 requests, no more than before, at 555 KB,
  within its payload ceiling. `.table-truncated` reaches `PipelineCanvas.tsx`, an eleventh file, and the
  style-scope baseline records it. `TABLE_TRUNCATION.md` moves only by line: the canvas's two list cuts
  sit seven lines lower. `INERT_CONTROLS.md` does not move, and the tenancy census holds at 360.

  **Then the mapping and live previews, the last of the smaller lists.** Ontology Manager's mapping
  drawer read "Hydrated object preview · 20 rows", the length of the rows the server hydrated, for a
  dataset of any size, though the reply carries the dataset's row count. Data Onboarding's live
  connector preview asked a source for 25 records and drew them with nothing said.

  **Both say they are windows.** The mapping summary reads "the first 20 of N rows" when the dataset
  holds more than was hydrated, and "N rows" when it does not; no server change was needed. The live
  preview is the weak one the sweep named: no adapter reports how many records a source holds, and a
  REST source made by the form has no cursor to say there are more, so a statement is the only honest
  fix. Its limit is a named constant, and a preview that fills it reads "Showing the first 25 records.
  The preview stops at 25, and this source does not say how many it holds." A preview that stops short
  of its limit is the whole source and says nothing.

  **The proof.** In `truncation-sites.spec.ts`, a new browser test maps a 25-record dataset and requires
  the drawer's summary to read "Hydrated object preview · the first 20 of 25 rows"; a second serves a
  live REST source of 30 records and requires "Showing the first 25 records. The preview stops at 25,
  and this source does not say how many it holds.", not cut off. The live connector test in
  `evaluator.spec.ts`, whose source holds two records, now requires no such note. They pass on the fix,
  with the ontology, Object Explorer, map, decision and Drafts tests the same run matched.

  **Negative runs,** each on a rebuilt `dist`:
  - **N1, the summary counting the rows it kept:** the mapping test failed, `Received: "Hydrated object
    preview · 20 rows"`.
  - **N2, the live note removed:** the live test failed at the note, element not found.
  - **N3, the note shown for any preview:** the evaluator's two-record test failed, one note where it
    requires none.
  - **N4, the committed code:** both new tests failed at their statements.
  - Restored: the five matching browser tests pass, and both sources are byte for byte what they were.

  **The references.** Ontology Manager opens with 20 requests at 764 KB and Data Onboarding with 12 at
  444 KB, no more than before and within their payload ceilings; the shared closure is 437 KB.
  `.table-truncated` was already used in both files, and neither `TABLE_TRUNCATION.md` nor
  `INERT_CONTROLS.md` moves. No server file changed.

  **Then the facet filter.** Object Explorer's facet cards count objects per bucket, and a click filtered
  by something no object matched. A histogram bucket carried rounded edges and no value, so its button
  sent its label, "0 - 13.75", which no number equals; a value list keyed its buckets by their text, so
  a True bucket sent "True", which no stored true equals. Every such click read "No matching objects"
  under a count that said there were some.

  **A bucket filters by what it counted.** The server keeps a histogram bin's exact edges, and a value
  bucket sends the value itself, keyed by its JSON so that True and "True" stay two values. The card
  filters a bin by its range, including the upper edge for the last bin and for a single-value bin, as
  the server counted them, and the filter chip names the range it holds.

  **The proof.** A new `test_explorer_facet_filters.py` hydrates 23 objects whose highest score makes a
  bin width of 13.7500001, so the value 13.75 falls in the first bin by the edges the counts used and in
  the second by rounded ones; it requires every score bin's range filter, and every value of a boolean
  facet, to return exactly the bucket's count, and the boolean buckets to send booleans. In
  `truncation-sites.spec.ts`, a new browser test clicks the top score bin and requires the table to hold
  its count, with no "No matching objects" and a chip reading "score: N – 110", then clicks the True
  bucket and requires its count. They pass on the fix, with the three Object Explorer browser tests
  beside them and two backend scripts.

  **Negative runs,** each on a rebuilt `dist` where the browser is involved:
  - **B1, rounded edges:** the backend script failed, "score bin 0 (0.0 - 13.75) counts 4 and its
    filter {'gte': 0.0, 'lt': 13.75} returns 3".
  - **B2, values keyed by their text:** it failed, "the active facet sends ['True', 'False'], not
    booleans".
  - **N1, the client sending the bin's label:** the browser test failed at the top bin, `Expected: 3`,
    `Received: 0`. Its first mutation did not compile and was replaced by one that does.
  - **N2, the last bin excluding its upper edge:** the browser test failed at the top bin, `Expected: 3`,
    `Received: 2`.
  - **N3, the server sending text values:** it failed at the True bucket, `Expected: 12`, `Received: 0`.
  - **N4, the committed code:** it failed at the top bin, `Expected: 3`, `Received: 0`.
  - Restored: the four Object Explorer browser tests and three backend scripts pass, and both sources
    are byte for byte what they were.

  **The references.** Object Explorer opens with 13 requests at 450 KB, no more than before and within
  its payload ceiling. No class became shared, `TABLE_TRUNCATION.md` moves only by line (the column cut
  sits 17 lines lower), `INERT_CONTROLS.md` does not move, and the tenancy census holds at 360.

  **Then the map.** The Operational Map asked for 2,000 features and read them as the type. The status
  strip said "2000 features", the rail listed the first 12 with no way to the rest, and a geofence
  classified only the objects the query kept, so every object inside the fence past them was missed,
  and the operations event took its severity from that count.

  **The map says how many it loaded of how many, lists them all on request, and a geofence counts every
  object.** The feature collection's metadata keeps the query's `total` beside `feature_count`. The strip
  reads "2,000 of 2,001 features"; the rail says "Loaded 2,000 of 2,001 features. The map and this list
  show only these.", lists 12 under "Listing 12 of 2,000 loaded features", and lists every loaded feature
  on request. A geofence counts inside and outside over every object in the query, and its lists stay
  the objects it kept. The truncation gate's list cut in `MapWorkspace` closes with it.

  **The proof.** `test_gis_runtime.py` now renders a window of one and requires `feature_count` 1 and
  `total` 2, and evaluates a geofence with a limit of one and requires its summary to count both objects;
  `test_foundry_gis_features.py` requires a layer's `total`, including one rendered with room for no
  features. In `truncation-sites.spec.ts`, a new browser test hydrates 2,001 objects at one point and
  requires the strip to read "2,000 of 2,001 features", the rail's two notes, not cut off, twelve listed
  features, all 2,000 after Show all and twelve again after folding it, and a geofence reading "2,001
  inside" and "0 outside"; a second requires a map of three objects to say nothing about windows. They
  pass on the fix, with the Operational Map evaluator test and five backend scripts.

  **Negative runs,** each on a rebuilt `dist` where the browser is involved:
  - **B1, the collection dropping its total:** `test_gis_runtime.py` failed with `KeyError: 'total'`.
  - **B2, the geofence counting what it kept:** it failed on a summary of `{'total': 1, 'inside': 0,
    'outside': 1}`.
  - **N1, the server dropping the total,** and **N2, the strip counting the features loaded:** the
    browser test failed at the strip, `Received: "2,000 features"`.
  - **N3, Show all doing nothing:** it failed at the list, `Expected: 2000`, `Received: 12`.
  - **N4, the geofence counting what it kept:** it failed at the summary, which read "2,000 inside".
  - **N5, the window note shown on a whole type:** the three-object test failed, one note where it
    requires none.
  - Restored: the three map browser tests and five backend scripts pass, and the three sources are byte
    for byte what they were.

  **The references.** The Operational Map opens with 25 requests at 906 KB, no more than before and
  within its payload ceiling. `.table-truncated` reaches `MapWorkspace.tsx`, a twelfth file, and the
  style-scope baseline records it; `INERT_CONTROLS.md` counts the new Show all button among 332 wired
  controls. `TABLE_TRUNCATION.md` loses the map's feature-list row: the cut now sits in a condition,
  which the committed gate cannot place and so drops, the first of the holes the gate record below
  closes. The tenancy census holds at 360.

  **Then the platform graph.** The graph asked for 500 of each kind and read what came back as the
  platform. Its kind chips counted the loaded nodes and nothing said a kind had more; its edges were cut
  at three times the limit in the order they were added, so a pipeline's connections could be empty; and
  a scoped viewer's incidents were limited before the rule that hides the ones they cannot see, so fewer
  showed than they could see.

  **The graph says which kinds it loaded only part of, and keeps every edge between loaded nodes.**
  `/graph/overview` returns `loaded` and `totals` per kind, counting a kind only when it reached the
  limit, and every edge between the nodes it loaded. The screen reads "Loaded 500 of 501 objects. The
  canvas, type counts, search and connections cover only what was loaded."; a partial kind's chip reads
  "500 of 501"; an empty search says it covered only loaded resources; and the neighborhood toggle reads
  "Show all loaded nodes".

  **The proof.** A new `test_graph_overview_totals.py` creates three objects and three assets and
  requires a graph of one per kind to report `loaded` 1 and `totals` 3 for each, and its edge list to
  equal its edge count; at the default limit it requires totals equal to what was loaded. In
  `truncation-sites.spec.ts`, a new browser test hydrates 501 objects, reads the real overview, and
  requires the note to name every partial kind from its totals, not cut off, the object chip to read "500
  of N", and the neighborhood toggle to read "Show all loaded nodes"; a second fulfils the real reply with
  each total set to what was loaded and requires no note and no chip total. The second creates an object
  type of its own first: run alone, as its negative run ran it, it found an empty graph with no kind chips
  and never reached its note, and it had passed only after the first test filled the database. They pass
  on the fix, the second alone as well, with the platform graph evaluator test and six backend scripts,
  the tenancy census among them.

  **Negative runs,** each on a rebuilt `dist` where the browser is involved:
  - **B1, totals that are what loaded:** the backend script failed on totals of 1 where 3 exist.
  - **N1, the server's totals that are what loaded:** the browser test failed at the reply, `Expected:
    >= 501`, `Received: 500`.
  - **N2, the edges cut again:** it failed at the edges, `Expected: 1001`, `Received: 1000`.
  - **N3, the note removed:** it failed at the note, element not found.
  - **N4, the chips without totals:** it failed at the object chip, element not found.
  - **N5, the old toggle label:** it failed at the toggle, element not found.
  - **N6, the note shown whenever totals exist:** the whole-graph test, run alone, failed at the note, one
    where it requires none. Its first two runs failed earlier, on the empty graph the test's own fixture now fills.
  - Restored: the three platform graph browser tests and six backend scripts pass, and both sources are
    byte for byte what they were.

  **The references.** The platform graph opens with 14 requests at 635 KB, no more than before and
  within its payload ceiling. `.table-truncated` reaches `PlatformGraph.tsx`, a thirteenth file, and the
  style-scope baseline records it. Neither `TABLE_TRUNCATION.md` nor `INERT_CONTROLS.md` moves. The
  tenancy census holds at 360: the counts run on the same accessible queries as the rows, and a scoped
  viewer's incidents are read through the rule that already scoped them.

  **Then the gate, which had three holes the sweep walked through.** `audit_table_truncation` dropped any
  cut it could not place: the Drafts list's `(allDrafts ? draftList : draftList.slice(0, 6)).map(` left
  the scan and the reference without a word. It gated only cuts reaching a table, so every list, canvas
  and chip cut was reported and never refused; the map's feature list read as counted because a length
  appeared elsewhere on the screen, and nothing past the twelfth feature could be reached. And it read
  `.tsx` files only, and no limit a request sends or a server keeps, so every screen fixed in this sweep
  had been a window the gate could not see.

  **A cut is placed, classified, or gated by name.** A cut in one branch of a condition whose group is
  consumed is placed, and read as "all on request" when the other branch is the whole source. A slice that
  is not a collection is read from a closed, tested set: text, a prefix dropped, a last item dropped, or a
  request payload built inside a handler. Anything else is recorded as not placed and gated by name. Every
  `.slice(` in `.ts` and `.tsx` is accounted for: 35 calls, of which 11 are placed as collection cuts, 16
  are text, 5 drop a prefix, 1 drops a last item, 1 builds a request payload, and 1, the App's recent
  views, is not placed and is declared not a list with its reason.

  **A list cut is stated by a note and a way to the rest.** A `role="note"` element must render the
  source's length, or a name bound to an expression that includes it, and the cut must be taken only
  behind a `useState` value whose setter a `<button>` calls. A count in a button's label does not count as
  the note, and a note with no control does not make the rest reachable.

  **Loaded windows are a census and a registry.** The gate reads every request limit a screen sends, every
  server default a request reaches by leaving the limit out, and every fixed cap (`.limit(N)`, or
  `NAME[:N]` in a returned value) on a route a screen calls, following a helper that posts its caller's
  body and up to three same-module calls below a route. Keys name what a window is, never a line. Each is
  claimed by one entry in `WINDOWS`: stated by a named browser test and the text of the note, caption or
  summary that states it, a gap held by name, or not applicable with a reason. A new n/a is refused, as
  `audit_movement_contract` refuses one. The census finds 35 windows: 16 stated, each a screen this goal
  fixed; 8 gaps; and 11 not applicable, each a limit on something no screen draws as a set -- a batch
  size, a generated name, fields typed and never rendered.

  **What the census found.** Beyond the windows this sweep fixed, it named windows nobody had filed: the
  Command Center's Open alerts, Open approvals and incident counts stop at the 20 the scenario loads; Data
  Onboarding's validation warnings come from the latest 50 import jobs; Latest incidents lists up to 10
  with nothing said; each pipeline node's latest contract run comes from the 50 newest runs; Pipeline
  Outputs draws the 5 builds the canvas loads; an object profile counts its linked objects from the 50
  returned; and a Visual Builder preview keeps 20 nodes and lists 6. Each is a gap held by name, with
  Object Explorer's result count, left under N5's cost decision.

  **The baseline names what is left.** `table-truncation-baseline.json` now holds `unfixed`, the sorted
  `unfixed_names`, `per_file` and `na`, and no longer the `tables`, `reaching` and `silent` it never
  compared. A name the baseline does not hold fails even when the total is level. Recorded after every fix
  in this sweep landed, it lists exactly 13 names: five list cuts -- the pipeline mini-graph's `nodes` and
  `edges`, the Risk Board's `drivers`, and Visual Builder's `participants` and `sample_output` -- and
  eight gap windows, `artifact-preview`, `command-center-counts`, `contract-run-history`,
  `explorer-objects`, `imports-warnings`, `object-profile-links`, `ops-latest-incidents` and
  `pipeline-output-builds`. Twelve more are declared not applicable, each with its reason in the
  reference.

  **The proof.** `test_table_truncation_audit.py` now runs 228 assertions, each over the real scanner.
  Synthetic components test every rule: the Drafts shape placed and stated; both branches cut; the note
  removed while the button's label keeps the length; the control removed, or moved to a span; the map's
  shape, a count with no way to the rest; the shipped Drafts list with its note and then its toggle taken
  out; eight slices that are not collections and three evasions of them; every `.slice(` in `.ts` and
  `.tsx` accounted for; unplaced and declared cuts by name; eight request spellings; a route module's
  default spellings, caps and helper; linking, omission, a helper's caller and a limit with no route; the
  registry's malformed, missing and stale states; every stated window with its statement taken out of its
  screen; and a gap declared away, a test borrowed, a window removed, invented or claimed twice.

  **Negative runs,** each a mutation of `oms/audit_table_truncation.py` with the test run against it. All
  17 failed, and the audit restored byte for byte to 228 passing assertions. The test stops at its first
  failure, so each was refused by the first assertion it broke: placing a grouped cut (T1), the button in
  the reach rule (the shipped Drafts list with its toggle removed, T7), the note's markup (T3), recording
  every unplaced slice (the string-cut assertion that predates this change), the payload rule's setter
  guard (T8), scanning `.tsx` alone (T10, 32 of 35 slices), comparing names (T11), refusing a new n/a
  (T12), reporting a limit with no route (T15), the proof check (T16), the statement check (T17) and the
  claim check (T18). Resolving a parameter's default, the router prefix, following helpers, linking an
  omitted limit and naming gap windows were each refused first by the live tree failing its own baseline,
  where the census lost a window the registry claims. `verify.py --fast` passes 23 of 23 on the new
  baseline.

  **What it still does not see:** the legacy `oms/app/ui/app.js`; a cap computed by an expression or taken
  from a variable; a cap in another module's helper, or written into a value before the return; a request
  whose path or body is assembled away from the call; and whether a note's condition matches its window,
  which each named browser test proves.

  **Then a cost the Reliability tab's change left behind.** That change listed every one of the latest 25
  contract runs, and `reliability_summary` built the list after committing its snapshot. The commit
  expired each run loaded above it, so building the list read every run again, one statement apiece.
  Neither the Reliability tests nor the fast tier measure statements per request; the suite cost census
  does, and it runs when a baseline is re-earned, which the entity resolution migration below required.
  It found `GET /reliability/summary` repeating one statement 25 times.

  **The lists are built before the commit.** The runs, backfills and impacts are turned into the
  response's dictionaries while they are still loaded, and the snapshot is committed after. Measured by
  `measure_suite_cost.py --only test_ops_investigations_reliability.py`, the route falls from 41
  statements with one shape repeated 25 times to 14 with none repeated; the committed file, swapped back
  in and measured the same way, gives 41 and 25 again, and the fixed file is restored byte for byte. The
  reliability, operations, industrial and platform scripts that call the route pass.

  **Then entity resolution's reach, which the owner decided.** A job compared every pair among the first
  1,000 objects of its type by id and said so, and nothing reached the objects past them. Of the ways
  offered, the owner chose to keep the full comparison of the first 1,000 and add an exact pass over the
  whole type.

  **Every pair among the first N, and every object paired on an exact value.** After the scan, the job
  streams every object in scope as columns and groups them by each matching field's value, lowercased
  with punctuation removed. A group pairs its members where at least one lies past the scan, since the
  scan compared every pair inside it, and each such pair is scored exactly as the scan scores one, with
  the same threshold. A value shared by more than `ENTITY_EXACT_GROUP_CEILING`, 50 objects, is not
  paired past the scan, since that many would be every pair again, and the job counts those values. Two
  new nullable columns, added by migration `0045_entity_exact_pass`, keep `exact_objects` and
  `exact_values_skipped`; the job list, the create response, the audit entry and project snapshots carry
  them, and a job from before the pass keeps both NULL. The results are a superset of the scan's. The
  revision was first named `0045_entity_resolution_exact_pass`, 33 characters, and
  `test_production_rehearsal_contract.py` refused it: `alembic_version` holds 32, so a production upgrade
  would have failed writing the new head. The suite cost census ran that script and reported it exiting
  non-zero, which is how it was found.

  **The queue and Explain say which part found what.** A partial job's note reads "Compared every pair
  among the first 1,000 of 1,100 objects, by id, and paired all 1,100 on an exact name or serial_number,
  ignoring case and punctuation. Pairs involving the other 100 were compared only where they share such
  a value.", and adds "1 shared value held by more than 50 objects was not paired." when one was. An
  empty queue says it found nothing in either part. Explain's `duplicate_coverage` gains `exact_checked`:
  the badge reads "clear" for an object the scan compared, "no exact-match candidate" for one the pass
  read when no value was left unpaired, and "not compared" otherwise, including for an object made after
  the job. The legacy shell's toast names the exact pass too.

  **The proof.** `oms/test_entity_resolution_coverage.py` now holds five named objects past the scan of
  1,000 fillers: an exact pair, a near pair that shares no value, and one object sharing an exact name
  with the scan's first filler. A job at limit 1,000 must count 1,005 in scope, 1,000 compared and 1,005
  read by the exact pass with no value skipped, and find exactly the exact pair and the pair across the
  scan's edge, scored 100 on `name`, while the near pair stays uncompared; a reloaded job list must keep
  all five facts. Explain must say an object past the scan was checked but not compared and carries its
  warning, a scanned object was compared, and an object made after the job was neither. A job at limit
  5,000 must find the near pair too. A second type of 51 objects sharing one name and two twins, run at
  limit 2, must count one value unpaired and find only the scan's pair and the twins. The script passes
  with 92 assertions, and `test_entity_resolution_exact_pass_migration.py` upgrades from 0044 with the two
  columns removed, keeps a prior job's columns NULL, applies head twice, downgrades and upgrades again. The
  Decision, snapshot, tenancy and industrial scripts that touch entity resolution pass, 12 in all.

  In `truncation-sites.spec.ts`, the queue test builds 1,100 objects: a pair inside the scan, an exact
  pair past it, a near pair past it, and 51 objects from 1,001 sharing one name. It requires both pairs
  reached and the near pair absent, the note naming both parts and the unpaired value, not cut off, a
  crowded object's badge reading "not compared" and the exact pair's reading "1 warnings". The empty-queue
  test requires the title naming both parts and an object past the scan reading "no exact-match
  candidate". Both pass, with the Decision workflow and accessibility tests.

  **Negative runs,** each on a rebuilt `dist` where the browser is involved:
  - **B0, the committed server:** the backend script failed at the exact pass, every exact field `None`.
  - **B1, the scan without `ORDER BY`:** it failed at the scan, the last id read filler 994 with three
    candidates.
  - **B2, exact pairs found but not scored:** it failed at the pairs, none found.
  - **B3, pairs only where both lie past the scan:** it failed at the pairs, the pair across the scan's
    edge missing.
  - **B4, no ceiling:** it failed at the crowd, no value counted as unpaired.
  - **B5, checked without the created-at test:** it failed at the object made after the job, called
    checked.
  - **N1, the committed Decision code:** the queue test failed at the exact pair past the scan, `Expected:
    1`, `Received: 0`.
  - **N2, the note without the exact pass,** and **N3, the unpaired value unsaid:** each failed at the
    note, which read the old sentence, or the new one without its last.
  - **N4, the badge ignoring unpaired values:** it failed at the crowded object, `Received: "no
    exact-match candidate"`.
  - **N5, the badge without the exact pass:** the empty-queue test failed at its object, `Received: "not
    compared"`.
  - **N6, the empty title without the exact pass:** the empty-queue test failed at its title, element not
    found. Its first mutation did not compile and was replaced by one that does.
  - Restored: the four Decision browser tests and three backend scripts pass, and the three sources are
    byte for byte what they were.

  **Creating a job read each candidate and its objects one at a time.** The commit expires every object
  and candidate the job loaded, and the exact pass reads objects past the scan as columns, so building the
  response refreshed each candidate and fetched each of its objects apart. The suite cost census found
  `POST /entity-resolution/jobs` repeating one statement 6 times. The handler now reloads the job's
  candidates in one read before anything reads one, and their objects in one read per 500 ids, keeping
  that result referenced because the session holds unchanged objects only weakly; the first draft of the
  preload threw its result away and changed nothing. On `test_entity_resolution_coverage.py` the route
  falls from 20 statements with a shape repeated 6 times to 14 with none repeated. Measured the same way
  with only the candidate reload removed it reads 15 statements with 3 repeats, and with both removed 20
  and 6, and the file is restored byte for byte after each.

  **The references.** The Decision route opens with 13 requests at 473 KB, within its ceiling; one
  measurement in the gate run read 6, and two more read 13 each. `.table-truncated` gains no file and
  `INERT_CONTROLS.md` does not move. `TABLE_TRUNCATION.md` changes only where the gate names the queue's
  test, whose title moved, and still holds 13 unfixed. The tenancy census holds at 360: every read the
  pass adds runs on the scan's project-scoped query.

  **The migration head is now 0045, and re-earning its four baselines found two costs.** Query bounds
  holds its ceiling of 0, and the browser evidence baseline records 234 passed, 0 failed and the new
  tests. The suite cost census found the two costs: `GET /reliability/summary`, from the Reliability tab's
  change and committed on its own before this record, and `POST /entity-resolution/jobs`, fixed here and
  now repeating no statement. The census also runs every backend script, and three exited non-zero across
  its runs. `test_production_rehearsal_contract.py` refused the 33-character revision id, above;
  `test_iteration_state_audit.py` failed while the browser evidence baseline still named the old head, and
  passes once it is re-recorded from a bundle built with provenance; and
  `test_request_cost_concurrency.py` exits non-zero under the census's instrumentation and passes on its
  own. Two routes' statement counts moved in both directions between runs,
  `/runtime/observability/summary` from 91 to 80 to 107 and `/project/demo/reset` from 826 to 801 to 825,
  and are reported and not gated. Request cost re-records 150 routes with no shape repeated more than 4
  times, under its ceiling of 6. It reported three routes drifting by one to three statements,
  `/imports/jobs`, `/reliability/summary` and `/ui-state/imports`, each a route an earlier change in this
  goal counted or listed more of; drift is reported and not gated.

  **Then the Command Center's counts.** `_open_alerts`, `_open_approvals` and `_incidents` in
  `asset_reliability_scenario.py` each load the 20 newest rows, and `_summarize` counted those lists: Open
  alerts and Open approvals were their lengths, the approval card's open incidents were the unclosed among
  the 20 most recently updated incidents, and the report card's incident count was `len(incidents)`. With
  25 open alerts the screen read 20. The legacy shell's Command Center and the exported report print the
  same counts.

  **Every count is over every matching row, and the lists stay the 20 newest.** Each loader now returns its
  list and how many rows match. A list shorter than 20 is every row, so its length is the count; one that
  reaches 20 is counted in SQL on the query that loaded it, the way the platform graph counts a kind that
  reached its limit, and open incidents keep the same `!= "CLOSED"` test in SQL. The incident total becomes
  a KPI the report card reads. The section cards draw their metrics and never their rows, so the screen
  draws one thing from the loaded lists: Governed Approval and Action shows the newest pending approval,
  and when more are open it now reads "Showing the newest of N open approvals". The legacy shell and the
  report's two count lines read the same KPIs and change with them. Bootstrap and triage read the alerts
  through the same loader and still take its 20.

  **Not fixed here.** Bootstrap and triage link the pump's incident to the 20 newest open alerts in the
  database, of any project or subject, so Operations' incident queue counts only alerts that were among
  the newest 20 at some run, and a first bootstrap fails with 422 when one of them belongs to another
  project. The report's evidence ids list the 20 loaded approvals and incidents with nothing said, and the
  legacy shell's recommendation card names the newest approval as the approval. Open incidents counts a
  RESOLVED incident as open, where Operations counts OPEN, TRIAGE and INVESTIGATING. And the scenario's
  three reads name no project, as the tenancy census already records.

  **The proof.** A new `oms/test_command_center_counts.py` bootstraps the scenario beside one closed
  incident and requires, below the 20 the scenario loads, that Open alerts, Open approvals, the approval
  card's open incidents and the report card's incident count each equal what `/ops/alerts`, `/approvals`
  and `/ops/incidents` list. It then adds 25 open alerts, 25 pending approvals and 24 incidents, 2 of them
  closed, runs triage, and requires the same four counts past the window, 28, 26, 23 and 26, with each
  list still the 20 newest; the summary the legacy shell reads and the exported report's two count lines
  must agree. The script passes with 137 assertions. `test_asset_reliability_command_center.py`,
  `test_maintenance_summary_cost.py`, with 1 count statement on the route under its 6,
  `test_human_ui_readiness.py` and `test_ui_alignment_acceptance.py` pass.

  In `truncation-sites.spec.ts`, the new test adds 21 open alerts, pending approvals and open incidents
  through the API, reads the true counts from the routes that list every row, and requires Open alerts,
  Open approvals, the approval card's two counts and the report card's incident count to read them, and
  Governed Approval and Action to read "Showing the newest of N open approvals", not cut off. It reads the
  industrial workflow as unset, because an earlier evaluator test configures one on this project and its
  approval then takes the panel. It passes, with the three Command Center tests in `evaluator.spec.ts`. A second new test serves the scenario's own
  reply with one open approval and requires the panel to show it with no note.

  **Negative runs,** each on a rebuilt `dist` where the browser is involved:
  - **B0, the committed server:** the backend script failed at the counts past the window, `open_alerts`
    reading `(20, 28)`, after 123 assertions.
  - **B1, open alerts counted from the loaded list:** it failed at the same check, `(20, 28)`.
  - **B2, open approvals counted from the loaded list:** it failed at `open_approvals`, `(20, 26)`.
  - **B3, the report card's count from the loaded list:** it failed at `incident_count`, `(20, 26)`.
  - **B4, open incidents counted over the 20 loaded:** it failed at `open_incidents`, `(18, 23)`.
  - **B5, the SQL count without its CLOSED test:** it failed at `open_incidents`, `(26, 23)`.
  - **B6, closed incidents counted as open below the window:** it failed below the window, `(2, 1)`,
    after 11 assertions.
  - **N1, open alerts from the loaded list:** the browser test failed at Open alerts, `Expected: "21"`, `Received: "20"`.
  - **N2, the note removed:** it failed at the panel's note, element not found.
  - **N3, the committed server:** it failed at Open alerts, `Received: "20"`.
  - **N4, the note shown for one approval:** the one-approval test failed, one note where it requires none.
  - Restored: the five matching browser tests and three backend scripts pass, and both sources are byte
    for byte what they were.

  **The references.** The tenancy census holds at 360: each loader keeps its one read and counts on the
  query it built. `TABLE_TRUNCATION.md` reads 12 unfixed, 5 of 12 truncations and 7 of 35 loaded windows,
  and names the new test for `command-center-counts`; `test_table_truncation_audit.py` runs 232
  assertions. `.table-truncated` gains no file and `INERT_CONTROLS.md` does not move. Below the window
  `/ui-state/command-center` issues the same 74 statements; past it, 4 more (72 to 76), and triage 5 more
  (296 to 301), with no shape repeated more often than before. The Command Center opens with 11
  requests at 447 KB.

  **Followed up, 2026-09-23.** Three items from "Not fixed here" are closed.
  - The 422 on a first bootstrap is fixed. So are the three reads that named no project. Both
    landed in 626aacf and are recorded in GOAL_TENANCY_2026-08-27, "The Command Center".
  - The two screens now count open incidents one way. `ops_control.CLOSED_INCIDENT_STATUSES` is
    `("RESOLVED", "CLOSED")`: an incident is open until it is resolved or closed. `/ops/summary`
    counts by it, and so does the Command Center, on the rows it loaded and in SQL past its 20.
    The Resolve button reads its mirror in `opsApi.ts`.
  - Two behaviours change. The Command Center no longer counts a RESOLVED incident as open.
    Operations now counts as open any status it did not name: status is free text, and a
    runbook step can set any word. The button was off only for RESOLVED, so it now also refuses
    to resolve a CLOSED incident a second time.
  - **Proven by** `oms/test_incident_open_definition.py`, 42 assertions. It holds the frontend's
    copy equal to the server's. It then runs six statuses below the window and 18 more
    incidents past it. At each stage `/ops/summary` and the Command Center must both read the
    open count from `/ops/incidents`. Operations must list the MITIGATED incident and neither
    the RESOLVED nor the CLOSED one. A browser test in `evaluator.spec.ts` serves five
    incidents. It requires Resolve on OPEN, TRIAGE and MITIGATED, and off on RESOLVED and
    CLOSED.
  - `test_command_center_counts.py`, `test_command_center_tenancy.py` and the Command Center
    count test in `truncation-sites.spec.ts` computed the old rule. They now read the shared
    definition and pass.
  - **Negative runs.** Operations' three statuses restored failed below the window: 4 open, not
    5. The Command Center's `!= "CLOSED"` restored over its loaded rows failed below the
    window: 6, not 5. The same test in SQL failed past it: 24, not 17. The frontend's copy
    without CLOSED failed at the parity check. The button's RESOLVED-only test failed in the
    browser at "Resolve is offered for a CLOSED incident". Restored, the four sources are byte
    for byte what they were.
  - **Still open from that list.** The pump's incident still links only alerts that were among
    the 20 newest at some run, now `default`'s. The report's evidence ids list the 20 loaded
    approvals and incidents with nothing said. The legacy shell's recommendation card names
    the newest approval as the approval.

  **And Operations' Latest incidents, the gap window `ops-latest-incidents`.** `/ops/summary`
  read its open incidents in no order and returned the first ten as `latest_incidents`, so the
  panel listed whichever ten the database returned first. In SQLite those were the ten written
  earliest, with nothing said.
  - The read is now ordered by `updated_at`, newest first. Ties in the one-second clock break by
    `created_at`, newest first, then by id. The ten stay ten, and the count is every open
    incident.
  - When more are open, the panel says "Showing the 10 most recently updated of N open
    incidents. The Incidents tab lists every one."
  - The window is declared stated, and `TABLE_TRUNCATION.md` reads 11 unfixed: 5 of 12
    truncations and 6 of 35 loaded windows. `test_table_truncation_audit.py` runs 246
    assertions.
  - **Proven by** `oms/test_ops_latest_incidents.py`, 8 assertions. It writes twelve open and
    two resolved incidents in reverse id order, with explicit times out of any order. Two share
    `updated_at`, and two share both times. It requires the ten most recently updated, the
    newer creation first on a tie, and the id order on a full tie.
  - Two new tests in `truncation-sites.spec.ts` cover the screen. One writes twelve incidents,
    updates the sixth a second later, and requires it first, ten listed, and the note with the
    open count, not cut off. The other serves a summary whose two open incidents are both
    listed, and requires no note.
  - **Negative runs.** In the backend test:
    - no order failed at the first listed, `latest-11`, the last written;
    - no `created_at` tie-break failed at the order, 04 before 05;
    - no id tie-break failed at 08 before 07.

    In the browser:
    - no order failed at the first listed, the first written;
    - ordering by creation failed at the first listed, a later-written incident;
    - no note failed at the note, element not found;
    - a note even on a complete list failed at the second test, one note where none belongs.

    The first browser run updated the first-written incident, which a read in no order also
    returns first, so the no-order mutation passed. The test now updates one written in the
    middle. Restored, both sources are byte for byte what they were.

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

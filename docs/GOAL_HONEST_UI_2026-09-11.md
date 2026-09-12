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
- **N5 — Every row reachable.** **Open** — paging past the limit, so the rows the caption
  now counts can be read. The column half of this was folded into N3, for the reason
  recorded there.
- **N6 — The typed cells that nothing uses.** **Open** — `DataTable` takes `specs` and no
  caller passes it, so a timestamp in a table and the same timestamp in a detail pane
  disagree today. Either the call sites pass it or the parameter goes; a primitive with a
  feature nobody uses is a claim in the source about a capability the product does not
  have.
- **N7 — The full grid.** **Open** — column visibility, reorder, resize, pin, sort,
  filter, selection, virtualization, rolled out behind the `audit_ui_primitives` user
  count. Not started until N2 through N5 are met.
- **N8 — The two tables N4 found.** **Open** — the operations feed stops cutting its
  events before `DataTable` sees them, so the component's own caption can count them, and
  Object Explorer says how many of the object type's columns it is drawing. Numbered after
  N7 because it was found after N7 was written, not because it waits on it. Each needs a
  fixture larger than the cut — more than forty operational events, an object type with
  more than eight properties — and the ceiling in `table-truncation-baseline.json` falls
  to zero when both land.

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

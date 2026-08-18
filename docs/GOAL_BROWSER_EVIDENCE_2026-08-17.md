# Goal — What the product does in a browser

Stated 2026-08-17. Follows [`GOAL_WRITE_COST_2026-08-16.md`](GOAL_WRITE_COST_2026-08-16.md),
which finished measuring the server and, in finishing, made the next gap obvious.

## The direction

Five goals have now measured this product. Every one of them measured the server: query
bounds, request cost, snapshot scope, latency observations, write cost. The enforcement
system has fourteen declared checks and three ratchets, and **not one of them opens a
browser**.

| | |
| --- | --- |
| Python suite scripts | 227 |
| Lines of TypeScript in `frontend/src` | 16,455 |
| Product screens (`src/workspaces`) | 22 |
| Declared checks that run any of it | **0** |

`npm test` is `tsc --noEmit`. It proves the frontend compiles. Nothing in `pre-push`,
`check_registry.py` or `enforcement_runs.py` mentions the frontend at all, so the half of
the product a user actually touches is held to *"it type-checks"*.

This is the first standing invariant — **no claim outlives its proof** — pointed at the part
of the system that has never had one.

## What was measured before writing this

Three questions were asked directly, and answered by running the product rather than reading
it. The bundle was rebuilt from current source first, because the one on disk was stale (see
Finding 3).

| Question | Answer | Evidence |
| --- | --- | --- |
| Does drag-and-drop work? | **Yes, on desktop** | `pipeline creates a graph and accepts a dragged node`, `platform graph supports selection, dragging` — pass |
| Does the ontology creator work? | **Yes** | `ontology maps dataset fields with hydrated preview`, `ontology manager publishes and installs a governed package`, `relationship designer creates a governed link by connecting ports` — pass |
| Do the transformer / builder functions work? | **Yes** | `visual builder supports typed configuration, preview, save, and publish` — pass |

The full suite: **100 passed, 0 failed, 115 skipped.** The product works. That is the good
news, and it is not the finding.

## Finding 1 — the browser suite skips more than it runs

| Viewport | Ran | Skipped |
| --- | --- | --- |
| mobile-375 | 18 | 36 |
| tablet-768 | 17 | 37 |
| **desktop-1280** | **48** | 5 |
| wide-1600 | 17 | 37 |
| | **100** | **115** |

Four viewports are declared. **32 of the 34 stateful tests carry
`test.skip(testInfo.project.name !== "desktop-1280")`.** What runs everywhere is the render
sweep: the shell is visible, no `[object Object]` leaked into the page, no horizontal
overflow, and an axe pass at WCAG 2.1 AA — genuinely good work, and entirely about
*appearance*.

So the product is verified to **look** right at four widths and to **work** at one. Three of
the four declared viewports are decoration.

## Finding 2 — and here is what that hides

A pipeline is built by dragging a node from the palette onto the canvas. `PipelineBuilder`
uses **native HTML5 drag-and-drop** (`draggable`, `onDragStart`, `onDrop`), which does not
fire from touch input. Measured on a 390×844 viewport with `hasTouch`:

```
PROBE source visible: true, canvas visible: true
PROBE nodes after tap: 0, after touch-drag: 0
PROBE RESULT: a touch user CANNOT add a pipeline node
```

The palette and the canvas are both visible and reachable — the screen looks usable. There
is a non-drag path: `onClick` sets a quick-add type. But the control that consumes it is the
`+` button rendered **at the midpoint of an existing edge**, and a new pipeline starts with
zero nodes and zero edges, so there are no `+` buttons to press. On an empty canvas the only
affordance for the first node is a drag a finger cannot perform.

Two drag systems exist in this codebase and only one has this problem: `VisualBuilder` uses
`@dnd-kit` (pointer events, touch-capable), `PipelineBuilder` uses native HTML5. The suite
cannot tell them apart, because it never tries either one off desktop.

This is the third standing invariant in a new costume. *A measurement is evidence only for
the path it traverses* — and a skip traverses nothing.

## Finding 3 — the tests describe a build nothing pins

`frontend/dist` is gitignored, correctly: the production `Dockerfile` builds it in a
multi-stage step and copies it in. But Playwright's `webServer` starts **uvicorn directly**,
not the image, and `_workspace_shell` serves whatever it happens to find:

```python
react_index = FRONTEND_DIST_DIR / "index.html"
if react_index.exists() and not legacy:
    return FileResponse(react_index)
return FileResponse(UI_DIR / "index.html")
```

Two consequences, both measured on this machine:

- The `dist` present before this investigation was built **2026-08-11 20:11**, with **42
  source files newer than it** — including `VisualBuilder.tsx`, the drag-and-drop workspace,
  modified a day later. A green e2e run was describing code that was not the code in the repo.
- On a fresh clone there is no `dist` at all, so the server silently falls back to
  `oms/app/ui/` — **7,856 lines of hand-written UI, last touched 2026-06-28, six weeks older
  than the React app, referenced by no test whatsoever.** `git clone && uvicorn` serves it,
  and nothing anywhere says so.

## Finding 4 — nobody counts what the browser pays

The request-cost ratchet gates statements per request. Its counterpart does not exist.

| | |
| --- | --- |
| Shipped JS + CSS | **1,101 KB** across 27 chunks |
| Largest chunks | `index` 242 KB, `canvas-vendor` 178 KB, `MapWorkspace` 160 KB |
| Anything constraining it | **nothing** |

The splitting is real work, done well — `MapWorkspace`, `OntologyManager` and `ControlPanel`
are separate chunks, so a user who never opens the map never downloads Leaflet. What is
missing is the ratchet: the argument that made statements-per-request worth gating makes
kilobytes-per-route worth gating, and only one of them has a baseline file.

## Conditions

- **G1 — A gate that opens a browser.** Register the Playwright suite in `check_registry.py`
  and `enforcement_runs.py` like every other check, with a purpose and a cadence. It takes
  1.8 minutes; there is no cost argument against running it.
- **G2 — The bundle under test is the bundle in the repo.** The e2e run must build from
  source, or refuse. A run that serves a stale `dist` — or silently serves the legacy UI
  because `dist` is missing — must fail loudly rather than pass quietly. The assertion is
  cheap: the served `index.html` names its own asset hashes.
- **G3 — Make the skip a number, and ratchet it.** 115 skips is a fact nobody had. Record
  skipped-per-viewport as a baseline and gate it downward, so behavioural coverage can widen
  and never narrow. Gate the thing ordinary work does not do: adding a test is ordinary,
  adding a `test.skip` is not.
- **G4 — Decide what touch is owed, then enforce the decision.** Either the pipeline builder
  gains a touch-capable path to the first node — an insert control that exists on an empty
  canvas would very nearly do it — or the product states that authoring is desktop-only and
  the suite stops declaring `mobile-375` and `tablet-768` as though they were supported. Both
  are defensible. Shipping a screen that renders and cannot be used is not.
- **G5 — A payload budget per route.** Record KB per workspace route and gate growth, the way
  `docs/suite-cost-baseline.json` gates statements. Report the total; gate the regression.
- **G6 — Say what the legacy UI is for.** 7,856 lines that no test touches, reachable by
  `?legacy=1` and served by default on any machine that has not run a build. Either it is
  supported — in which case it needs the render sweep at minimum — or it is retired. Carrying
  an untested second UI as the silent fallback is the worst of the three options.

## What this is not

Not a redesign, and not a verdict on how the product looks. The render sweep already checks
alignment, readability and WCAG 2.1 AA at four widths, and it passes; that work is done and
this goal does not reopen it.

Not a demand for full behavioural coverage at every viewport either. Some of the 115 skips
are certainly correct — a stateful workflow that legitimately needs a wide canvas should say
so once, deliberately, somewhere countable. The objection is not that skips exist. It is that
nothing knew how many there were.

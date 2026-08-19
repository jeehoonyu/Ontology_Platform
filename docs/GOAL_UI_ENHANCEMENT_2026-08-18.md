# Goal — Making the interface consistent, not making it again

Stated 2026-08-18. Follows [`GOAL_BROWSER_EVIDENCE_2026-08-17.md`](GOAL_BROWSER_EVIDENCE_2026-08-17.md),
which put a browser in the gate and left three conditions open. This absorbs them rather than
restating them, because the backlog is now counted and a duplicated condition is a lie about
how much is owed.

## The question that prompted this, answered first

*Would React be better for the long run and a more enhanced UI/UX?*

**React is already the product**, and has been for some time. This is not a decision waiting
to be made:

| | |
| --- | --- |
| `frontend/src` | React 19.2, Vite 7.2, TypeScript 5.9 |
| Product screens | 22 workspaces, 16,455 lines |
| Served at `/workspace/*` | whenever a build exists — which is the normal case |

The framework is also the right one, and the evidence is in the dependency list rather than
in taste. The hardest parts of this interface are a node-graph editor and a map: `@xyflow/react`,
`@dnd-kit`, `react-leaflet` and `@tanstack/react-query` are all React-native, and the pipeline
canvas and platform graph are built on them. Moving frameworks would mean rebuilding exactly
the pieces that are hardest and already work. **There is no leverage in the framework choice.**

The leverage is in three things that are measurable today, and none of them is React's fault.

## Finding 1 — there are two user interfaces, and the older one wins by default

| | Lines | Tested by | Served when |
| --- | --- | --- | --- |
| `frontend/src` (React) | 16,455 | 34 stateful specs + a 16-route render sweep | a build exists |
| `oms/app/ui` (hand-written) | 7,856 | **nothing** | it does not |

`_workspace_shell` falls back to the hand-written UI whenever `frontend/dist` is absent, which
is the state of every fresh clone, since `dist` is correctly gitignored and built by the
Dockerfile. The fallback was last touched 2026-06-28, six weeks before the React app, and no
test in the repository exercises it.

This is the single largest structural risk in the interface, and it is not a UI problem so
much as a *which UI* problem. It was already open as G6.

## Finding 2 — the design system exists; its adoption is uneven

A first count of `src/components` returned four files and read like an absence. It is not:
those four export **22 primitives** — `Page`, `Panel`, `DataTable`, `Toolbar`, `StatusBadge`,
`KeyValueGrid`, `Metric`, `EvidenceList`, `WarningList`, `LoadingState`, `EmptyState`,
`ErrorBanner` and more. The system is real and it is good.

What is uneven is who uses it.

| Primitive | Workspaces using it, of 22 |
| --- | --- |
| `Panel` | 20 |
| `ErrorBanner` | 16 |
| `LoadingState` | 15 |
| `DataTable` | 14 |
| `EmptyState` | 14 |
| `Page` | 12 |
| **`WorkspaceHeader`** | **1** |

**Seven workspaces use neither `LoadingState` nor `EmptyState`:** `OntologyManager` (908
lines), `PipelineBuilder` (668), `OntologyReleasePanel`, `AgentRuntimePanel`,
`OntologyRegistryPanel`, `OntologyHealthPanel`, `OntologyPackagePanel`.

### Correction — that measured adoption, and was described as absence

Doing the work showed the sentence that followed here was wrong. It said those screens *show
nothing while loading and a blank region when empty*. **All seven handle every state.** What
they use is a bare `<div className="empty">`, and `OntologyHealthPanel`'s is better than the
generic form — its text changes with health status, "No active findings" against "Run a health
check", which `EmptyState` cannot express. Its `message` line carries successes as well as
errors, so rendering it through `ErrorBanner` would have been a regression, not an adoption.

Measuring the treatments rather than the imports gives the real shape:

| Treatment | Sites |
| --- | --- |
| bare `<div className="empty">` | **42** |
| `.empty-state-card` via `EmptyState` | a handful |
| `health-empty`, `package-empty-state`, `agent-runtime-empty` | 1 each |
| `review-empty`, `inspector-empty`, `visual-builder-empty` | found only when the gate ran |

The bare form is not a deviation in seven screens. It is the **most common** treatment in the
application, and there were **seven** distinct treatments where five had been counted — the
last three surfaced by the gate on its first run, not by reading.

So the defect was never a missing state. It was that of the two main treatments only one had a
component, so only one could be counted, changed in one place, or kept consistent. The other
was forty-two copies of the same three lines.

## Finding 3 — one stylesheet, 357 classes, nothing scoped

| | |
| --- | --- |
| `src/styles.css` | **6,233 lines** |
| Distinct class selectors | **357** |
| CSS modules or scoped styles | **0** |

Every screen draws from one global namespace. There is nothing wrong with a global stylesheet
at small scale, and at 22 screens and 357 classes it means a change made for one workspace can
alter any other, with no mechanism that would say so. The browser suite's render sweep would
catch a catastrophic break — it checks overflow and readability at four widths — but not a
panel that quietly acquires the wrong padding on a screen nobody opened during the run.

## Conditions

Carried forward from the browser-evidence goal, unchanged and still owed:

- **G4 (carried) — Decide what touch is owed, then enforce it.** **Open** — a touch user
  cannot add the first node to a pipeline; measured, and awaiting a product decision rather
  than more measurement.
- **G5 (carried) — A payload budget per route.** **Open** — 1,101 KB ships with nothing
  constraining it.
- **G6 (carried) — Say what the legacy UI is for.** **Open** — Finding 1 above.

New, from what is measured here:

- **J1 — One component behind every way of saying "there is nothing here".** **Met** —
  `EmptyState` gained an `inline` variant rendering the bare form byte for byte, so migrating a
  site cannot change what a user sees; twelve sites in the named workspaces moved onto it, and
  `oms/audit_ui_states.py` freezes the 32 that remain and refuses a new treatment that has not
  said what the existing ones cannot express. The condition as first written — adopt the
  primitives in seven screens that lack the states — was based on a measurement of imports
  described as a measurement of behaviour. It is restated here as what the evidence supports.
  Browser suite after the migration: 113 passed, 0 failed.
- **J2 — A change to one screen cannot silently restyle another.** **Met** — and the
  measurement it asked for first is what decided the work. It is lopsided:

  | Of 358 classes in the one stylesheet | |
  | --- | --- |
  | used by exactly one file | **297 (83%)** |
  | used by two or more | **33** |
  | in no `className` literal | 28, of which 16 are built at runtime |

  So the stylesheet was **not** scoped. Rewriting hundreds of class usages across twenty-two
  files, verified by a render sweep that checks overflow and contrast rather than layout,
  would be a large risky change against a coupling that is mostly theoretical: a class one
  file uses cannot restyle another file.

  The 33 are the coupling, and they are the design system nobody had named — `.button-row`
  across twenty files, `.empty` across thirteen, then `.two-col`, `.metrics`, `.grid`,
  `.table-wrap`. `oms/audit_style_scope.py` records them and gates the *event* rather than the
  layout: **a class going from one user to two fails**, naming the second screen, because that
  is the moment a change to it starts moving both. Declaring it shared is a one-line edit;
  doing it by accident is what is refused.

  Deleting the 28 is deliberately not gated. Sixteen are assembled at runtime —
  `context-action-${kind}` and the like — so "no literal mentions it" is not "nothing uses
  it", and a gate that cannot tell those apart would push someone to delete a live style.
- **J3 — The primitives are documented where they are used.** **Open** — `WorkspaceHeader` is
  used by one screen of twenty-two. Either it is the intended header and twenty-one screens
  have not adopted it, or it is dead. A primitive nobody can find gets rewritten inline, which
  is how the seven screens in Finding 2 came to hand-roll their states.
- **J4 — Perceived performance has a number.** **Open** — Nobody measures what a workspace
  costs to open: requests issued, bytes fetched, time to first meaningful content. The
  request-cost work counted what the *server* spends per call; the equivalent for the browser
  does not exist. Measure before budgeting, and budget only what proves reproducible — the
  suite-cost census had to demonstrate 695 of 695 agreement before it was allowed to gate.

## What this is not

Not a redesign, and not a component-library migration. The primitives are good and the render
sweep passes WCAG 2.1 AA at four widths; that work is done and this does not reopen it.

Not a rewrite in another framework, for the reason given at the top: the framework is already
React and the hard parts are built on its ecosystem. Anyone proposing to change that should be
asked which measurement it improves.

And not a licence to restyle screens by taste. Every condition here is a count — how many
workspaces handle empty state, how many classes are shared, how many bytes a route costs — so
that "the UI is better" can be a claim someone checks rather than a claim someone makes.

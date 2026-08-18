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
`OntologyRegistryPanel`, `OntologyHealthPanel`, `OntologyPackagePanel`. Two of those are the
largest screens in the product and the rest are the entire ontology panel family — the part a
user of an ontology platform spends the most time in.

This is what "inconsistent UX" actually means in a codebase: not ugliness, but a screen that
shows nothing while it loads and a blank region when a collection is empty, sitting next to
one that handles both. A user reads that as unreliability.

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

- **J1 — Every workspace handles loading, empty and error.** **Open** — Adopt `LoadingState`,
  `EmptyState` and `ErrorBanner` in the seven workspaces that use none of them, or record per
  screen why a state cannot occur there. Then ratchet adoption: it may rise and must not fall.
  The gate is a count, not a judgement of taste.
- **J2 — A change to one screen cannot silently restyle another.** **Open** — Give the
  stylesheet scope: tokens for what is genuinely global (colour, spacing, type) and module or
  component scope for the rest. Measure first — how many of the 357 classes are used by more
  than one workspace — because the ones used once are the cheap half and the ones used
  everywhere are the design system in disguise.
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

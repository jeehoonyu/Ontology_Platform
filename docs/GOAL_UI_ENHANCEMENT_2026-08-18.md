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
- **J3 — The primitives are documented where they are used.** **Met** — and the premise was
  wrong in an instructive way. `WorkspaceHeader` was not the intended header that twenty-one
  screens had failed to adopt. It hardcodes the word *"Batch"* and highlights a tab called
  *"Graph"*: it is the pipeline builder's header, wearing a general name in the shared layer.
  One workspace used it and two wrote the same markup by hand. That is worse than no
  primitive — a reader who opens it learns not to trust the layer. It now lives in
  `PipelineBuilder.tsx` as `PipelineHeader`.

  [`UI_PRIMITIVES.md`](UI_PRIMITIVES.md) lists all twenty, where each is defined and which
  files import it. It is **generated from source**, because a hand-maintained component list
  is a claim that decays the first time someone adds a component; the gate regenerates and
  fails if the committed file disagrees.

  It also failed on its first run, naming `DebugJson` as an export nobody imports — and the
  fix I made was wrong. Deleting it broke `test_ui_alignment_acceptance.py`, which asserts
  that raw JSON is isolated to collapsed developer evidence: `DebugJson` was the only
  component rendering raw JSON, and it renders it inside `DeveloperEvidence`. **Unimported is
  not dead.** It is restored, and the rule now takes a declaration — an unused export may stay
  if it says what it holds, so a reader who finds it learns why it is there.

  The suite caught that inside one run, which is the argument for verifying before pushing
  rather than after.

  Adoption is reported, never gated upward. Twelve of twenty-two workspaces using `Page` is a
  fact worth seeing, not a rule — some screens legitimately do not want the wrapper, and a
  gate demanding uniformity would be enforcing taste rather than preventing a defect.
- **J4 — Perceived performance has a number.** **Met** — three of them, and which may be
  gated was decided by measuring twice rather than by judgement:

  | | Two runs, 16 routes | |
  | --- | --- | --- |
  | requests on open | identical **16/16** | gated, no tolerance |
  | bytes transferred | identical **16/16** | gated, 15% tolerance |
  | wall-clock to settle | identical **0/16**, worst drift 2.6% | recorded, never gated |

  The map issues **25 requests** to open; the median screen issues 13, and 223 across sixteen
  routes. Requests are gated with no tolerance because they were exactly stable and because
  the failure mode is creep — one more call per change, until a screen makes forty. Bytes get
  a tolerance, since a response body legitimately moves with the data behind it. Wall-clock is
  wall-clock: a gate on it fails for reasons a reader cannot act on, which is how a gate
  becomes something people re-run until it passes. It is not even written into the baseline,
  because recording a number the gate refuses to use invites someone to start using it.

  `measure_route_cost.py` drives the browser and `audit_route_cost.py` judges the file, split
  the way the census is split from its ratchet. A machine with no measurement says so and
  claims nothing, rather than reddening the fast tier for a missing artifact; `verify.py
  --full` produces it and then judges it, so the gate has teeth where a browser exists.

  This is `audit_route_payload`'s other half. That one asks what the *bundle* costs, computed
  statically from the build manifest. This asks what the *screen* costs once it is running.

  **Correction, from the first run after the chunk split.** The measurement originally reused
  one browser page for all sixteen routes, so every route after the first was measured against
  a warm cache. `security` read 454 KB on one build and 26 KB on the next — not because the
  screen changed, but because more of what it needed had already been fetched by whatever ran
  before it. The number was a function of visit order, and it was **reproducible while being
  wrong**: 16 of 16 identical across two runs, which is the more dangerous kind of stable.
  Each route now gets a fresh context. It is still 16 of 16 on requests and bytes, and timing
  now drifts 53.8% rather than 2.6%, which only strengthens keeping it out of the gate.

  The measurement also stamps the bundle it describes, because the gate judged one taken
  against an older build and failed a ceiling for a change that had already happened. Every
  baseline here already guards against stale evidence; this artifact did not.

## What this is not

Not a redesign, and not a component-library migration. The primitives are good and the render
sweep passes WCAG 2.1 AA at four widths; that work is done and this does not reopen it.

Not a rewrite in another framework, for the reason given at the top: the framework is already
React and the hard parts are built on its ecosystem. Anyone proposing to change that should be
asked which measurement it improves.

And not a licence to restyle screens by taste. Every condition here is a count — how many
workspaces handle empty state, how many classes are shared, how many bytes a route costs — so
that "the UI is better" can be a claim someone checks rather than a claim someone makes.

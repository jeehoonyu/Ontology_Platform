# Goal — Say only what is true, then give every app the same foundations

Stated 2026-09-25, as [`GOAL_LOOK`](GOAL_LOOK_2026-09-24.md)'s U11. This is the plan's A goal:
[`FOUNDRY_UI_PLAN`](FOUNDRY_UI_PLAN_2026-09-24.md)'s app-wide trust fixes from wave 0 (A1–A5),
then its wave 1 foundations (A6–A9). It runs before and beside GOAL_LOOK, not after it, because
the plan puts wave 0 first. GOAL_LOOK's U10 is Met. Its `raw_colour_ceiling` (599) passes here
to A8, whose Tabs replace eight per-screen tab styles.

Wave 0 also holds O1–O3, W2, Y1–Y2 and H1. They belong to the O, W, Y and H goals, which are not
stated yet, and are not conditions here. Three wave-0 items were filed as separate tasks for
immediate repair: O2 (masking), O1 with O3 (the search cut and the action binding), and A5 (search
and media-set scoping). If that A5 task lands first, A5 below records what it proved rather than
doing the work twice.

Everything below was re-read against the code at `38b096a` on 2026-09-25. The plan's line numbers
had drifted by one or two. Where a finding is worse than the plan said, or narrower, this says so.

## What is true today

| Item | At `38b096a` |
| --- | --- |
| **A1** status tags | **Discharged by GOAL_LOOK U8** (`2b90ee3`): every `StatusBadge` caller passes an intent from `components/data/intents.ts`, unknown words render neutral, and `look.spec.ts::OFFLINE is not shown as success` holds it. The plan's second half, refusing unknown *severity* words, is GOAL_HONEST_UI's open item; `WarningList` renders them neutral. |
| **A2** storage | **True.** Five of the fourteen storage calls in `frontend/src` are unguarded. `App.tsx:211` parses `ontology.recentViews` during render; `:232` writes it in a handler, which only logs. `VisualBuilder.tsx:160` and `:163` run inside an effect, through `collaborationClientId()`, which is evaluated before the promise whose `.catch` would see it; `crypto.randomUUID()` at `:162` is unguarded too. `PlatformGraph.tsx:80` runs in an effect, and its `try` covers only `JSON.parse`. There is no error boundary anywhere (`main.tsx:16-22`), so any of these unmounts the whole tree. A stored `null` or a plain string in `recentViews` also blanks the app, at `App.tsx:264`. No test makes storage throw. |
| **A3a** Platform Graph | **True.** The subtitle promises "expand neighborhoods" (`PlatformGraph.tsx:157`). The Neighbors control filters the ≤500 nodes already loaded (`:99-113`), nothing is fetched, and `/graph/overview` takes only a limit (`platform_core.py:1039-1043`). The control's own label and the truncation note are honest; the subtitle is not. |
| **A3b** Automate | **True.** "Paused" is rows minus enabled (`Automate.tsx:160`), so an automation created disabled reads "paused" in the metric, its row and its detail. The backend has no paused state: pausing sets `enabled = False` (`automate_ops.py:865-867`). |
| **A3c** ModelOps | **Worse than the plan said.** "Create release" keys on `submission.status === "success"` (`ModelOps.tsx:235-238`), and the Releases tab never receives the eligibility the Gates tab shows. `onRelease` (`:209`) first calls `POST /modeling/objectives/{id}/release`, which sets `released = True` without checking eligibility (`modeling.py:447-478`), and only then asks for a release, which is refused with 422 (`modeling_evaluation_ops.py:577-582`). One click on a gate-blocked submission leaves it marked released, and "Start deployment" enables. |
| **A3d** Ops | **True.** One `source` and one `severity` state serve both the alert-rule form and the test-event form (`OpsWorkspace.tsx:70-71`). The test event has no source field, and posts whatever the rule's source input holds. |
| **A3e** Vertex | **True, and wider.** `toGraphNodes` drops the server's x/y (`Vertex.tsx:73-81`), and `MiniGraph` puts every node on a fixed ellipse anyway (`PipelineCanvas.tsx:495-498`). Six buttons and four server layouts give one picture. `MiniGraph` also ignores `faded`, so "Filter (fade non-matching)" changes nothing on the canvas either; the subtitle promises "lay out, filter". |
| **A4** grants | **True for data reads.** `POST /projects/{id}/grants` (`security_access.py:212`) and `POST /admin/roles/grant` (`admin_directory.py:363`) return 201 and write `role_grants` and `admin_role_grants`. Reads are scoped by tenancy alone (`semantic_scope.py:25`, `:30`, then `tenancy.py:92-109`: memberships and the principal's claims). The grant tables are read by their own list and access-check endpoints, which answer only when asked, and by `_can_manage_membership` (`admin_directory.py:307-332`), which governs admin-group membership when a request names an actor. Neither screen says so, and their copy implies the opposite (`Security.tsx:719`, `:768`, `:816`; `ControlPanel.tsx:544`, `:611`). A Security grant checks a `projects` table that is not tenancy's `platform_projects` (`security_access.py:219`). |
| **A5** search, media sets | **True, and the ratchets see only half.** Search filters events (`platform_core.py:417-421`, reading the project from the event's payload, not its `project_id` column) and not incidents (`:424-427`), though `Incident` has `project_id` and `/ops/incidents` is scoped (`ops_control.py:1069`). `MediaSet` has no project (`media_sets.py:17-30`); its list (`:166-168`), get, items and extract are unscoped behind the router's `edit` permission. The search read is counted in `unscoped_reads_ceiling` (344), but filed as *transitive*, because `semantic_scope.effective_principal(` matches the audit's authorizing pattern (`audit_tenancy_scope.py:127-128`) though it authorizes nothing. Media sets are not in the 344 at all (the census reads only tables with a `project_id`); they are among `tenant_orphan_ceiling`'s 52, not in T2's debt as the plan said. No test covers either: `test_semantic_plane_tenancy.py` seeds no incidents. |
| **A6** URLs | One query reader: `ObjectExplorer.tsx:89` reads `?type=` at mount, falls back to the first type silently (`:131`) and never writes back. `navigate(view)` (`utils/navigation.ts:7-10`) pushes the view and drops the query unless a caller concatenates one. Nothing calls `replaceState`, and no module maps a resource kind to a route. Links are written with no reader: `/workspace/imports?asset=` (`PipelineBuilder.tsx:1201`), and `/workspace/pipeline?graph=` and `/workspace/ontology?object_type=` from the backend (`industrial_workflow.py:1252`, `:1300`, `:1301`). No test uses Back. The server allows 27 views (`main.py:447-451`) against `CORE_VIEWS`' 23. |
| **A7** overlays | Three `role="dialog"`: the command palette (`App.tsx:320-337`; Escape closes, no trap, focus not returned), Object Explorer's action modal (`ObjectExplorer.tsx:255`; no Escape, no initial focus, no trap), and the Pipeline hotkeys (`PipelineBuilder.tsx:917-944`; Escape, focus returned, not modal). Two menus without menu semantics: the pane actions group (`Pane.tsx:173-199`, in the flow on purpose) and the node context menu (`PipelineCanvas.tsx:299-312`). No `role="menu"`, `tooltip`, `aria-haspopup` or `<dialog>`; 34 native `title=` tooltips on elements. `UI_PRIMITIVES.md` lists no overlay. |
| **A8** tabs | Eight ad-hoc tab sets. Decision, Ops and ModelOps: a named `nav`, an `active` class, no state. Security and the drawer: an unnamed `nav`. The artifact review: `role="tab"` with `aria-selected` in an unnamed tablist, no arrow keys. Delivery: the sidebar's `nav-item` classes in a button row. The builder breakpoint: a labelled `div`. Control Panel repeats Security's pattern. One segmented control (`OntologyHealthPanel.tsx:107`), with no `aria-pressed`. `getByRole("tab")` appears 7 times, all on the artifact review. |
| **A9** registry | `CORE_VIEWS` (`App.tsx:62`, 23) and `NAV_ITEMS` (`App.tsx:81-105`, 23, with no category, icon or create path) are separate literals. The render switch (`App.tsx:278-300`) holds the four builders' titles; `FLOW_STAGES`, `ENDPOINT_INVENTORY` and the server's 27-view allow-list are more lists. No literal app count is shown. |

## Design

**A claim is made true or taken away.** For each A3 item the default is the smaller change: the
copy or the control goes, unless the backend already supports the claim and making it true is
S-sized. Either way the test fails on the old behaviour.

**Data comes before copy.** A3c changes server state on an action the server then refuses. Its
fix is in the backend (the release endpoint checks eligibility) as well as on the button.

**Scoping re-records its ratchets lower in the same change** (K8). A5 lowers
`unscoped_reads_ceiling` and `tenant_orphan_ceiling`, and stops `audit_tenancy_scope` counting
`effective_principal(` as authorization, which may raise the unauthorized count before the fix
lowers it; that is named in the open.

**A foundation lands with an adopter and replaces the copies it names.** `audit_ui_primitives`
refuses a primitive nothing imports. Each takes its look from `UI_CONFIG.md`, as GOAL_LOOK's did,
and deletes the per-screen CSS it replaces, lowering `raw_colour_ceiling`.

**Test hooks stay** (decision N, option (a) assumed). The dialogs keep the names "Search
workspaces" and "Hotkeys". The artifact review tabs keep `role="tab"` for their seven locators.
The Decision, Ops and ModelOps tabs keep the button role and gain `aria-current`; node menu items
stay buttons.

**One commit per item, and per screen for A3, each measured.** The fast tier before each commit;
a re-baselined gate's own test and the default tier (about 25 minutes) whenever a baseline moves,
because the fast tier runs no `oms/test_*.py` (GOAL_LOOK U8 broke one unseen); the full
six-project run for anything a browser renders.

## Owner decisions this goal needs

The register is in [the plan](FOUNDRY_UI_PLAN_2026-09-24.md#owner-decisions).
- **O** (the project model): A4 labels the grant forms until O is made. Retiring the grants, or
  making them govern reads, waits on it.
- **N** (Tabs and Menu semantics): A7 and A8 assume option (a), buttons with `aria-current` or
  `aria-pressed`.
- **A5's migration:** `media_sets` gains a `project_id`. Which project existing rows take (a
  default project, or none until reviewed) is the owner's choice; A5 assumes none, which hides
  them from project principals until assigned.

## Gates this must clear

| Gate | What it will say |
| --- | --- |
| `audit_tenancy_scope` | `unscoped_reads_ceiling` (344) lowered by A5; `effective_principal(` no longer read as authorizing |
| `audit_tenant_orphans` | `tenant_orphan_ceiling` (52) lowered once `MediaSet` and `MediaItem` carry a project |
| `audit_style_tokens` | `raw_colour_ceiling` (599) falls as A7 and A8 replace per-screen CSS |
| `audit_ui_primitives` | each new primitive has an adopter; `docs/UI_PRIMITIVES.md` regenerated |
| `audit_inert_controls` | 0; a primitive takes its action as a required prop |
| `audit_route_payload`, `audit_route_cost` | each primitive inside tolerance, or re-baselined in the open with per-route deltas |
| `audit_iteration_state`, `audit_frontier` | A1–A9 parse; every ceiling named here is owned by an open condition |
| evaluator axe sweep | clean at every width, and with each overlay open |
| the default tier | after any baseline moves |
| heading locators, tab locators | all still find their elements |

## Conditions

- **A1 — Status tags say what their caller means.** **Met** — discharged by GOAL_LOOK U8
  (`2b90ee3`). Every `StatusBadge` caller passes an intent; unknown words render neutral; OFFLINE
  renders danger, not success. Proven by `look.spec.ts::OFFLINE is not shown as success`, shown
  to fail with the substring rule restored (`rgb(28, 110, 66)`), and by `…::A warning badge reads
  at AA contrast`. Refusing unknown severity words stays GOAL_HONEST_UI's open item.
- **A2 — Blocked or corrupt storage never blanks the app.** **Met** — every read and write of
  browser storage is guarded; `recentViews` is parsed and shape-checked; an error boundary keeps
  the shell standing when a screen throws, and says which screen failed. To be proven by
  `frontend/tests/trust.spec.ts::A blocked store leaves every screen standing`, with an init script
  that makes `Storage.prototype.getItem` and `setItem` throw: the sidebar and the heading render on
  Command Center, the four builder routes (each with an artifact) and Platform Graph. And by
  `…::A corrupt recents list is ignored`, seeding `{bad`, `null` and `"x"`. Each is shown to fail
  at `38b096a`, and with the guard removed.

  **What changed.**
  - `frontend/src/lib/storage.ts` has three functions: `readStored`, `writeStored` and
    `readStoredJson`. The last keeps a parsed value only if a shape check passes. A read that
    fails gives the fallback, and a write that fails is dropped.
  - The five unguarded calls use it:
    - App's recents are read with a list-of-strings check (`isViewList`) and written guarded.
    - The builders' collaboration client id falls back to one id per page when storage is
      blocked. It also no longer needs `crypto.randomUUID`, which exists only in secure
      contexts.
    - Platform Graph's saved layout is read guarded.
  - The nine calls that were already guarded (pane layouts, the pipeline's hidden nodes, the
    ontology layout, the graph's save) keep their own guards.
  - `components/layout/ScreenBoundary.tsx` wraps the workspace switch, keyed by view:
    - A screen that throws while rendering, or in an effect, shows "*Screen* failed." with the
      error, in `ErrorBanner`, and a Try again button.
    - The sidebar, the flow strip and the backend bar stay, and navigating away starts the next
      screen clean.
    - It reuses `ErrorBanner` rather than `.state-block`, which `audit_style_scope` would
      otherwise count as a new coupling.

  Proven by the five tests in `frontend/tests/trust.spec.ts`:
  - `A blocked store leaves every screen standing`. Each builder waits for its collaboration
    join request, the sign that its effect ran. Platform Graph, with the asset scenario loaded,
    waits for a placed node, since it places nodes only after reading its layout.
  - `A corrupt recents list is ignored`, run for `{bad`, `null` and `"x"`. No recents render.
  - `A screen that throws leaves the shell standing and names itself`. An overview whose nodes
    are not a list makes Platform Graph throw in its layout effect. The alert reads "Platform
    Graph failed.", and the sidebar still navigates to Command Center.

  **Negative runs,** each restoring the code at `38b096a` at one site, against a rebuilt dist:
  - The recents read unguarded again: with storage blocked, and with each corrupt value, no
    sidebar was found, because the page was blank.
  - The builders' client id unguarded again: the join request never came (the test timed out).
  - Platform Graph's layout read unguarded again: no node was placed.
  - The boundary removed: no alert, because the whole root unmounted.
  - Every file was restored byte for byte, and the hash matched (`c4897bcff57c4964`).

  **Measured.** The full six-project run: 380 passed, 0 failed, none retried; the five new tests
  run once, on desktop. Route cost holds at 266 requests. The shared closure measured 509 KB,
  inside the 8 KB tolerance. `docs/INERT_CONTROLS.md` (350 → 351 controls, the Try again button)
  and `docs/TABLE_TRUNCATION.md` (moved lines) were regenerated, and the browser-evidence
  baseline was re-recorded.
- **A3 — Each screen claims only what it does.** **Open** — five commits, one per screen, each
  with a test that fails on the old behaviour:
  - **a.** Platform Graph's subtitle drops "expand neighborhoods", unless a fetch that adds
    nodes lands with it. The test selects a node, turns on Neighbors, and checks the copy against
    what was requested.
  - **b.** Automate's metric reads "Disabled", or counts only automations paused after being
    enabled. The test creates an automation with "Enabled on create" off.
  - **c.** The release endpoint refuses an ineligible submission before it marks anything
    released, and the button reads the Gates tab's eligibility. A backend test posts
    `/modeling/objectives/{id}/release` for a gate-blocked submission and expects a refusal with
    `released` still false. A browser test expects the button disabled and no request sent.
  - **d.** The rule form and the test-event form keep their own severity and source. The test
    sets the event's severity and reads the rule's unchanged, and checks the event's POST.
  - **e.** Vertex's layout buttons move the nodes, or go, and the filter fades nodes, or goes.
    The test clicks two layouts and compares node positions.

  **a. Platform Graph.** The smaller change: the subtitle no longer promises to "expand
  neighborhoods". It reads "narrow to a node's loaded neighbors", which is what Neighbors does.
  Nothing fetches more nodes, and the control's own label ("Show all loaded nodes") and the
  truncation note were already honest.
  - Proven by `trust.spec.ts::Platform Graph promises only the neighbours it has loaded`. With
    the asset scenario loaded, it selects a node and turns on Neighbors. It records that no
    `/graph/` request was made, and requires that the page header not say "expand".
  - Negative run: the old subtitle put back failed "the header's promise". Restored byte for
    byte; the hash matched (`6784b5b56289efef`).
  - Measured: the full six-project run passed 381 of 381, with none retried; route cost and the
    payload hold.
- **A4 — The grant forms say they do not govern data access.** **Open** — until decision O,
  Security's project grants and Control Panel's role grants each carry "does not govern data
  access" beside the form, and the backend docstrings stop claiming otherwise. To be proven by
  `trust.spec.ts::Grant forms say what they govern`, shown to fail at `38b096a`. A pytest pins the
  behaviour the copy describes: a grant without a membership still reads nothing.
- **A5 — Search and media sets are scoped to the caller's projects.** **Open** —
  `unscoped_reads_ceiling` (344) and `tenant_orphan_ceiling` (52) are re-recorded lower in the same
  change (K8). Search filters incidents by `project_id`, and events by their column rather than
  their payload. `media_sets` gains a project, and its list, get, items and extract are scoped.
  `audit_tenancy_scope` stops reading `effective_principal(` as authorization. To be proven by
  `oms/test_search_scope.py` (a project-B principal finds none of project A's incidents) and
  `oms/test_media_set_scope.py` (B neither lists nor reads A's set), each shown to fail at
  `38b096a`. The OIDC tier repeats both, because local mode resolves every caller to `*`.
- **A6 — Every resource kind has a URL.** **Open** — one module maps each kind to a
  `/workspace/<view>?…` route, and `navigate(view, params)` keeps the query and dispatches
  `popstate`. The readers this wave adds: `?graph=` (Pipeline), `?type=&section=&page=`
  (Ontology), `?artifact=` (the builders), `?dataset=` (Data & Media), `?type=&object=` (Object
  Explorer) and `?tab=` (Ops). Filters use `replaceState` and view changes `pushState`; a default
  or automatic selection never rewrites the URL. To be proven by
  `frontend/tests/routes.spec.ts`: for each kind, `page.goto(route)` selects that resource, Back
  restores the previous one, and an unknown id shows a NonIdealState naming it, never the first
  item. Each is shown to fail at `38b096a`. The server's view list and `CORE_VIEWS` come from one
  source (with A9).
- **A7 — Dialog, Menu with Popover, and Tooltip exist and are adopted.** **Open** — Dialog traps
  focus, closes on Escape and returns focus; Menu opens from a button with `aria-haspopup`, arrow
  keys move and Escape returns focus; Tooltip opens on hover and on focus. Their look is
  UI_CONFIG's overlays. The first adopters are the command palette and Object Explorer's action
  modal (Dialog), the pane actions (Menu, if decision N allows it) and the canvas's icon buttons
  (Tooltip). To be proven by `frontend/tests/overlays.spec.ts`: focus stays inside while open,
  Escape closes and returns focus, axe is clean with each open, and Escape never also cancels a
  live drag. Each is shown to fail with the primitive's behaviour removed.
- **A8 — Tabs and SegmentedControl replace the ad-hoc tabs.** **Open** — `raw_colour_ceiling`
  (599) falls as the eight per-screen tab styles go, re-recorded in each commit (K8). Underline,
  tint, pill and vertical variants; SegmentedControl with `aria-pressed`. The Decision, Ops and
  ModelOps tabs gain `aria-current`, and the artifact review keeps `role="tab"`. To be proven by a
  `look.spec.ts` test per variant, reading its spec from UI_CONFIG, each shown to fail with the
  variant's CSS removed; the seven tab locators and the class locators still pass.
- **A9 — One app registry.** **Open** — one list is the source of `CORE_VIEWS`, the sidebar, the
  command palette and the server's view list, each app with a category, icon, one-line
  description and, where one exists, a create path. Counts derive from its length. To be proven by
  a test that asserts the registry is the only source of all four, shown to fail at `38b096a`
  (where the server allows 27 views and the client 23).

Every test is run once against a build with the thing it defends removed before it is believed.

## Order and size

| Step | Touches | Size | Commits |
| --- | --- | --- | --- |
| A2 | `App.tsx`, `VisualBuilder.tsx`, `PlatformGraph.tsx`, a new error boundary, `trust.spec.ts` | S | 1 |
| A3 a–e | one screen each; A3c also `modeling.py` | S each | 5 |
| A4 | `Security.tsx`, `ControlPanel.tsx`, two docstrings | S | 1 |
| A5 | `platform_core.py`, `media_sets.py` and a migration, `audit_tenancy_scope.py`, two baselines | S (search) · M (media) | 2 |
| A6 | a route module, `navigation.ts`, six screens, `routes.spec.ts` | L | 1 per reader |
| A7 | three primitives and their adopters | M | 3 |
| A8 | Tabs, SegmentedControl, eight screens | M | 1, then 1 per screen |
| A9 | a registry module, `App.tsx`, `main.py` | S | 1 |

Wave 0 (A2–A5) comes first, because a screen that lies costs more than a screen that is missing.
A6–A9 follow in the plan's order; A6 and A9 share the view list, so A9 may land first.

## What this is not

- Not the O, W, Y or H goals. Their wave-0 items (O1–O3, W2, Y1–Y2, H1) wait for their own
  documents, or for the separate tasks already filed.
- Not decision O. A4 labels the grants; it does not retire or wire them.
- Not the approvals inbox (A10), which is wave 2 and needs A6.
- GOAL_GRAPH's successor, the Workshop composer, is unaffected (decision M): nothing here adds a
  drop target.

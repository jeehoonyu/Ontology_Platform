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
- **N** (Tabs and Menu semantics): **decided 2026-09-26, option (a)**. Tabs and menus stay
  buttons, with `aria-current` or `aria-pressed`, and a menu is a disclosure popover with
  `aria-expanded`. The artifact review keeps its existing tablist.
- **A5's migration:** **decided 2026-09-26**. `media_sets` gains a `project_id`, and existing
  sets get none until someone assigns one. Project principals do not see them; administrators
  do.

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
- **A3 — Each screen claims only what it does.** **Met** — five commits, one per screen, each
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

  **b. Automate.** An automation has one switch, `enabled`. Pause turns it off, and so does
  creating one with "Enabled on create" unchecked. The screen now names the off state for what
  it is: the metric reads "Disabled", and the row and detail badges read "disabled", where all
  three said "paused". The Pause and Resume actions keep their names.
  - Proven by `trust.spec.ts::Automate does not call a never-enabled automation paused`. It
    creates an automation with "Enabled on create" unchecked, and reads "disabled" in its row
    and its detail, with no Paused metric.
  - Negative run: the old wording put back failed "its row". Restored byte for byte; the hash
    matched (`39481a619ee66bf2`).
  - Measured: the full six-project run passed 382 of 382, with none retried.
  - Committed with the fast tier failing: the comment moved a table's line in
    `docs/TABLE_TRUNCATION.md`, and the tier's exit code was lost in a pipe. `356ec94`
    regenerated the reference. No table changed, and the tier's exit code is now read directly.

  **c. ModelOps.** The data came first.
  - `POST /modeling/objectives/{id}/release` now asks the release gate
    (`_release_eligibility`) before it marks anything. It refuses an ineligible submission with
    the same 422 detail as the gated release, and changes nothing. With no gate defined, a
    submission releases as before.
  - The Releases tab now receives the eligibility the Gates tab shows. "Create release" needs
    it as well as a successful training run, and a note says why the button is off.
  - `test_modeling_io` releases through the modeling router alone, so it now registers the
    gate's tables.
  - Proven by `oms/test_model_release_gate.py`. With an automatic gate that rejects it, a
    submission's release is refused with the rejected check named, and `released` stays false.
    An eligible one still releases, and so does one with no gate at all. At `db24fe8` it failed:
    "a gate-blocked submission is refused: 200 … "released":true".
  - Also proven by `trust.spec.ts::ModelOps releases only what its gates allow`. A trained
    submission with a manual gate pending: "Create release" and "Start deployment" are disabled,
    the note shows, and no release request is sent.
  - The modeling tests that release (`test_modeling_io`, `test_modeling_evaluation_ops`,
    `test_modelops`, `test_foundry_tools`, `test_docs_conformance`) all pass.
  - Later, the suite-cost measurement at A5 found this route loading the objective twice,
    because the gate commits and the route read `objective.project_id` again afterwards. It
    was fixed in A5's commit.

  **Negative runs:**
  - The backend's gate check removed: the pytest failed again with the submission released. The
    file was restored byte for byte.
  - The button keyed on training status again: "Create release, with a gate pending" was
    enabled. Restored byte for byte; the hash matched (`73cf4a48f449eecf`).
  - Measured: the full six-project run passed 383 of 383, with none retried. That includes the
    evaluator's ModelOps flow, which releases a submission after its automatic gate approves it.

  **d. Ops.** The test-event form has its own severity and a source field ("Operational event
  source"), where it used to share the rule form's. The defaults still match (source
  `decision`, severity `high`), so a new rule still catches the default test event, as the
  evaluator's Ops flow relies on.
  - Proven by `trust.spec.ts::Ops' rule form and test-event form keep their own fields`. It sets
    the event's severity to critical and reads the rule's minimum still at high. It then types a
    rule-only source and checks that the event's POST carries severity `critical` and source
    `decision`.
  - Negative run: the event form wired back to the rule's fields failed "the rule's minimum
    severity". Restored byte for byte; the hash matched (`2ab6019b38ef4737`).
  - Measured: the full six-project run passed 384 of 384, with none retried.

  **e. Vertex.** Made true rather than removed, because the server already computes the
  layouts.
  - `toGraphNodes` now passes the server's x/y on. `MiniGraph`, used by Vertex alone, draws
    positioned nodes at those coordinates, scaled to fit the canvas; nodes without positions
    still sit on the ellipse.
  - A node the filter faded is drawn at 30% opacity.
  - Six buttons still give four pictures, because the server treats auto as grid and circular
    as radial (`vertex_ops.py:314-324`). That is the server's vocabulary, not a claim the canvas
    breaks.
  - Proven by `trust.spec.ts::Vertex's layouts move the nodes and its filter fades them`. With
    the asset scenario loaded, it builds a graph from `asset_pump_4` and `facility_1`. Grid then
    radial must place the two nodes differently. Filtering on `asset_class exists` must report
    1 matched and 1 faded, and draw one faded node.
  - `docs/TABLE_TRUNCATION.md` now reads `MiniGraph`'s 40-node cut as "held as shown", where it
    said "mapped". It is still unfixed and counted among the 11.

  **Negative runs,** against a rebuilt dist:
  - The server's positions dropped again: grid and radial drew the same picture.
  - The fade ignored again: no faded node.
  - Both files were restored byte for byte, and the hash matched (`ad5dcb6d597a0a6b`).

  **Measured.** The full six-project run passed 385 of 385, with none retried. Route cost and
  the payload hold.

  **A3 is Met:** five screens, five commits, each with a test that fails on the old behaviour.
- **A4 — The grant forms say they do not govern data access.** **Met** — until decision O,
  Security's project grants and Control Panel's role grants each carry "does not govern data
  access" beside the form, and the backend docstrings stop claiming otherwise. To be proven by
  `trust.spec.ts::Grant forms say what they govern`, shown to fail at `38b096a`. A pytest pins the
  behaviour the copy describes: a grant without a membership still reads nothing.

  **What changed.**
  - Security's "Project Role Grants" panel says: "These grants do not govern data access.
    Reads are scoped by project memberships, so a grant here lets no one read a project's data."
  - Control Panel's "Grant Role" panel says: "Role grants do not govern data access. Reads are
    scoped by project memberships; a grant here decides only who may manage an admin group's
    members." The last half is the one thing they do govern (`_can_manage_membership`).
  - The docstrings no longer claim otherwise. Security's `Project` no longer "governs access",
    and Control Panel's module no longer promises "real access resolution".

  Proven by `trust.spec.ts::Grant forms say what they govern`, which reads each panel's note.
  Also by `oms/test_grants_do_not_govern_reads.py`: a principal granted a role on project alpha
  by both forms (each returns 201), with no membership, lists none of alpha's datasets or
  object types and is refused alpha's object (403). That test pins the behaviour, so it passes
  today. It fails the day a grant starts to govern a read, and the notes are then revisited.

  **Negative runs:**
  - Security's note removed, then Control Panel's: each failed with its panel's note not found.
    Restored byte for byte; the hash matched (`85883128fd917826`).
  - The pin, with the granted principal given alpha's project (a grant that governs), failed on
    the dataset list.
  - The security and admin backend tests (`test_admin`, `test_security_admin`,
    `test_security_data`, `test_security_governance`) and `test_docs_conformance` pass with the
    new docstrings.

  **Measured.** The full six-project run: 386 passed and 0 failed.
  - One test retried: the evaluator's Workshop sweep, whose page showed no `.app-shell` within
    10 seconds of loading. That is a blank page at first paint, not a screen error, which the A2
    boundary would have caught inside the shell.
  - Its trace was lost, because the route-cost measurement after the run clears
    `test-results`. Runs now copy `test-results` first.
  - Repeated 4 times alongside the trust tests that create Workshop drafts, it passed 12 of 12.
    It is recorded as unexplained.
  - Route cost and the payload hold, and the browser-evidence baseline was re-recorded.
- **A5 — Search and media sets are scoped to the caller's projects.** **Met** —
  `unscoped_reads_ceiling` (344) and `tenant_orphan_ceiling` (52) are re-recorded lower in the same
  change (K8). Search filters incidents by `project_id`, and events by their column rather than
  their payload. `media_sets` gains a project, and its list, get, items and extract are scoped.
  `audit_tenancy_scope` stops reading `effective_principal(` as authorization. To be proven by
  `oms/test_search_scope.py` (a project-B principal finds none of project A's incidents) and
  `oms/test_media_set_scope.py` (B neither lists nor reads A's set), each shown to fail at
  `38b096a`. The OIDC tier repeats both, because local mode resolves every caller to `*`.

  **What changed.**
  - **Search.** Events and incidents go through `_safe_all`, the same project scope as every
    other kind, by the project column the row is filed under. Events were filtered by their
    payload's `project_id`, and incidents not at all.
  - **Media sets.** They gain a nullable, indexed `project_id` (migration `0048`).
    - Existing sets keep none, as the owner decided on 2026-09-26. Only a principal who holds
      every project reaches an unassigned set, and `POST /media-sets/{id}/project` assigns one.
    - New sets are created in a project, which the caller must be able to edit.
    - Every route is scoped by the set's project: in `media_sets.py` the list, get, items and
      extract; in `media_ops.py` chunk, entities, process, upload and content. Items reach
      their project through their set.
  - **The audit.** `audit_tenancy_scope` no longer reads every `semantic_scope.<name>(` as
    authorization. It now reads only the accessors that check the caller, so
    `effective_principal(` stops filing reads as authorized.
  - **The ratchets.** `tenant_orphan_ceiling` falls from 52 to 50: media sets, and their items
    through their set, now name a tenant. `unscoped_reads_ceiling` holds at 344, not lower,
    and here is why:
    - Search's incident read left the count.
    - `media_sets` entered the census when it gained a `project_id`, and one of its reads
      counts: creation's check that the new id is free. That check has to look across
      projects, because ids are global primary keys.
  - **Baselines at the new migration head.** Adding `0048` left four baselines stamped with
    `0047`: query bounds, request cost, suite cost and browser evidence. Each was re-measured.

  **Proven by:**
  - `oms/test_search_scope.py`: beta finds none of alpha's incident or event, including an
    event whose payload names beta. Alpha finds both. At `108e8bc` it failed: "beta found
    alpha's rows: ['event', 'incident']".
  - `oms/test_media_set_scope.py`, 30 assertions:
    - Beta cannot list, read, fill, extract, chunk or fetch the content of alpha's set or item.
    - Alpha cannot create a set in beta.
    - An unassigned set is hidden from both project principals and cannot be claimed by them.
      The administrator sees it, assigns it to beta, and beta then reaches it.
  - `oms/test_media_set_project_migration.py`: an existing set stays NULL through the upgrade,
    the upgrade applies twice, and the downgrade drops the index and the column.
  - The media, tenancy and platform tests pass: `test_connectivity_media_notepad`,
    `test_tenancy_scope`, `test_tenant_orphans`, `test_semantic_plane_tenancy` and
    `test_unified_platform`.

  **Negative runs:**
  - The list's project filter removed: beta listed alpha's set.
  - The set authorizer emptied: beta read alpha's set (200).
  - Both were restored byte for byte.

  **Found by the suite-cost measurement** (`measure_suite_cost`, which only the full tier
  runs): two routes repeated a query shape where their baseline allows none. Both were fixed by
  reading the value before a commit expires the row.
  - `POST /media-items/{id}/extract` (this change) read `item.media_set_id` after its audit
    commit, which loaded the item a second time.
  - `POST /modeling/objectives/{id}/release` (A3c, `d999cc3`): the release gate commits, and
    the route's later reads of `objective.project_id` loaded the objective again. The fast and
    default tiers do not measure query shapes, so A3c's own measurements missed it. With that fixed,
    the next measurement showed the gate itself reading the objective's checks twice:
    `_evaluate_submission_checks` loaded them, and `_release_eligibility` queried them again.
    The gate now reads them once and keeps each check's kind before the evaluation commits,
    which helps every route that asks it.

  **Measured.**
  - The full six-project run at migration head `0048` passed 399 of 399, with none retried.
    The Platform Graph test at 1366 passed at 41.0 s, just under its 45 s limit, so its task
    stands.
  - Data & Media's flows pass with the scoping on.
  - Route cost and the payload hold. The suite-cost census passed, with several routes now
    running fewer statements.
  - The browser-evidence, query-bounds, request-cost and suite-cost baselines are re-recorded
    at `0048`.

  **Not done:** the OIDC tier (`frontend/tests/production/oidc-rbac.spec.ts`) needs an identity
  provider this machine does not have, so it was not run. The pytest principals stand in for
  it: they are real, project-limited principals, not local mode's `*`.
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

  **Assumed, not yet decided** (the plan's U, V and W, 2026-09-26): `page` names an ontology-level
  panel and `section` a type's navigation id; old spellings such as `objectType` are not read;
  the server holds a copy of the route table and builds its links from it. Settled by this
  condition's own text: a tab is a selection, so Ops tabs are pushed and Back restores the last
  one; Object Explorer's search is the first filter and is replaced, never pushed; and each test
  is run against a build of `38b096a` to show it fails there.

  **1. The route table, `navigate`, and Ops' `?tab=`.** `frontend/src/routes.json` is the one
  table: each view's params in the order a URL writes them, with defaults left out, and each
  kind's view and param (rows land with their readers). `utils/navigation.ts` reads it:
  - `useRouteParams(view)` re-reads the query on every `navigate`, Back and Forward, since the
    screen stays mounted while only the query changes (ScreenBoundary is keyed by view).
  - `navigate(view, params)` pushes, builds the URL from `params` alone so a view change
    carries none of the last view's query, and adds nothing when the place is already open,
    however its URL spells it (`?tab=command`, or a param no screen reads). Only event handlers
    call it, so a default never writes the URL.
  - `navigateHref` opens a server-written link in the page; `?legacy=1` and other paths load.
  - The `alongside`/`flushSync` parameter the spec proposed is gone: its premise, that a URL
    write after an await renders a pass early, is false under React 19.2.7.
  - `oms/app/workspace_routes.py` is the server's copy (`workspace_href`, `app_url`), and
    `oms/test_workspace_routes.py` holds the two equal, requires a routes.spec case for every
    kind and view, and counts hand-built workspace links by file (the count may only fall).
    The incident evidence link is the first built from it: `/workspace/ops?tab=incidents`.
  - Ops reads `?tab=`; choosing a tab pushes, so Back restores the tab before; an unknown tab is
    named by `UnknownResource` and no tab is current. Sign-in's `next=` keeps the query.
  - ScreenBoundary clears a caught error when a history step changes the query, so Back from a
    tab that threw lands on the tab that did not.

  Proven by `frontend/tests/routes.spec.ts` (four cases so far) and the Python tests. Negative
  runs, each failing: the open place pushing again ("opening the view already open added a
  history entry"); the open place compared by spelling only ("the open tab, spelled
  ?tab=command, added a history entry"); Ops' tab as its own state ("the URL's tab, not Command
  Center"); the tab read once at mount (Incidents never shows); an unknown tab not named; a
  history step not clearing a caught error ("the failure of the tab left behind stayed over the
  one Back returned to"); sign-in keeping only the path ("sign-in drops the query …"); the
  incident link unbuilt; a hand-built count off by one, the server's default edited, and a view
  with no case (each `test_workspace_routes` message). An adversarial review confirmed five
  findings, all fixed above; eight were refuted.

  **2. Data & Media's `?dataset=`.** The dataset section reads the URL, with the first dataset as a
  default it adopts and never writes. Choosing a row and creating a dataset open it with
  `openResource`, so Back returns. Every answer the screen shows carries the id it answers (the
  detail, the declared schema, the upload receipt), so Back, Forward or a chosen row never leave
  one dataset's records, receipt or error under another; while an answer is on its way, the
  screen says it is loading. A 403 or 404 names the id with `UnknownResource` (`isNotFound`);
  any other failure is shown as one. A failed create or upload clears when another dataset is
  chosen. Pipeline Builder's quarantine link and the imports evidence link are built from the
  table: both used to point where nothing read them (imports, and the ontology view), and both
  now open the dataset in Data & Media. That quarantine link is shadowed in practice, since the
  contract panel always prefers the preview contract; that is filed as its own task, and the
  evaluator test strips the preview to reach it.

  Proven by two dataset cases in `routes.spec.ts`, the evaluator's contract test and
  `test_industrial_asset_workflow`. Negative runs, each failing: the URL unread ("the URL's
  dataset, not the first"); a row not writing the URL; an unknown dataset not named; a created
  dataset not opening; the receipt not tied to its dataset ("the last dataset's upload receipt
  followed Back to the one before"); the detail not tied to its id ("the last dataset's records
  stayed while the next one's answer was on its way"); a failed upload not cleared; any failure
  counted as unknown ("a server failure was not shown as one"); a 403 not counted; and each
  link built by hand again. An adversarial review confirmed seven findings, all fixed above
  (among them the receipt following Back, the previous id's error reappearing, and tests that
  could not fail); seven were refuted.

  **3. Pipeline Builder's `?graph=`.** The pipeline is the URL's, with the server's most recently
  updated one as a default it adopts and never writes. A row and "New pipeline" open theirs with
  `openResource`; the new pipeline's URL and state render in one pass, so its canvas is asked for
  once. The canvas, its failure, the outputs and the ontology contracts each carry the pipeline
  they answer, so Back, Forward or a chosen row never leave one pipeline's rail, failure or
  unknown card under another, and a pipeline asked again reads as loading, not its old failure.
  A 403 or 404 names the id, says "Pipeline not found" in the strip and turns off Propose,
  Preview and Deploy; a 500 stays "Canvas failed to load". A new pipeline or dataset that lands
  after the user has moved on (Back, another row, another view) no longer opens over their
  choice. The server builds its pipeline links from the table: the onboarding and workflow
  actions, the Command Center's evidence and its stepper, whose newest pipeline is now the newest
  the viewer may open (`test_command_center_tenancy` puts a newer one in another project; before,
  the link would have named it).

  Proven by four pipeline cases in `routes.spec.ts`, one more dataset case, and the tenancy test.
  Negative runs, each failing: the URL unread ("the URL's pipeline, not the newest"); the URL
  read once; the new pipeline's updates a pass after its URL ("a new pipeline asked for its canvas
  more than once"); an unknown pipeline not named; the failure not tied to its pipeline ("the
  unknown pipeline's card stayed while the real one loaded"); a 403 not counted; a row not
  writing the URL; Deploy left on; outputs not tied to their pipeline; a late new pipeline, and a
  late new dataset, opened over the user's move; a pipeline asked again keeping its old failure;
  the evidence link and the stepper link spelled by hand; the Command Center's newest pipeline
  unscoped ("lists another project's rows: ['beta-graph']"). The contracts carry their pipeline
  the same way as the outputs; no test separates them. An adversarial review confirmed seven
  findings, all fixed above; eleven were refuted.
- **A7 — Dialog, Menu with Popover, and Tooltip exist and are adopted.** **Open** — `raw_colour_ceiling`
  (571 after A8) passes here and falls as hand-styled overlays such as `.action-modal` go. Dialog traps
  focus, closes on Escape and returns focus; Menu is a disclosure, a button with `aria-expanded`
  that names its panel with `aria-controls` while open (decision N (a): no `aria-haspopup` and no
  ARIA menu roles), whose arrow keys move and whose Escape returns focus; Tooltip opens on hover
  and on focus. Their look is UI_CONFIG's overlays. The first adopters are the command palette
  and Object Explorer's action modal (Dialog), the pipeline strip's unsaved-changes list (Menu;
  the pane actions stay in the page's flow, as GOAL_SHELL S4 put them) and the canvas's icon
  buttons (Tooltip). To be proven by `frontend/tests/overlays.spec.ts`: focus stays inside while open,
  Escape closes and returns focus, axe is clean with each open, and Escape never also cancels a
  live drag. Each is shown to fail with the primitive's behaviour removed.

  **Where it stands.** Dialog, Menu and Tooltip are in and adopted (1–3 below), and each proof
  named above holds. The popover is `placement.ts` with the `.menu-panel` surface: a Popover
  export only the Menu imported would fail `audit_ui_primitives`, and the arrow comes with the
  Notifications layout (H8). A7 stays Open while it owns `raw_colour_ceiling` (563): the node
  context menu's look, seven raw colours, is the next hand-styled overlay to go, and whether
  that is A7's or Y15's is the owner's call.

  **1. Dialog, with its two first adopters.** `components/layout/Dialog.tsx`:
  - Focus moves inside on open, and Tab and Shift+Tab stay inside.
  - Escape closes it. Escape is taken in the capture phase and goes no further, so it never
    also cancels a drag or a selection behind it.
  - The backdrop closes it, and focus goes back to whatever opened it. The opener is read
    during the first render, before a child's `autoFocus` moves focus.
  - The look is UI_CONFIG's light dialog: white, radius 4, `--shadow-overlay`, over
    `--overlay-backdrop`.
  - The command palette ("Search workspaces") and Object Explorer's action dialog adopt it.
    Their hand-set backdrops, borders and shadows go. The palette keeps its width and its place
    near the top, as a quick-search sits.
  - Raw colours fall from 571 to 563. `docs/UI_PRIMITIVES.md` lists 27 primitives.

  Before this:
  - The palette closed on Escape but left focus nowhere, and Tab walked out behind it.
  - The action dialog did not close on Escape, set no initial focus and held no focus.

  Proven by `frontend/tests/overlays.spec.ts`. Each dialog's test opens it, checks focus
  inside, tabs through and back without leaving it, runs axe on the open dialog, presses
  Escape, and checks that focus is back on the control that opened it. The evaluator's palette
  and Object Explorer tests pass.

  **Negative runs,** each failing both tests against a rebuilt dist:
  - Focus not given back: "focus went back to … that opened it".
  - The Tab trap removed: "focus left the dialog after 3 Tab(s)" in the palette, and after 5
    in the action dialog.
  - Escape ignored: neither dialog closed.
  - Restored byte for byte; the hash matched (`e8c09699f1630fd7`).
  - Measured: the full six-project run passed 399 of 399, with the known Platform Graph retry.
    `Dialog` rides in the entry chunk, which App already loads; route cost holds at 266, and the
    shared closure is 510 KB.

  **2. Menu, with its first adopter.** `components/layout/Menu.tsx`, placed by
  `components/layout/placement.ts`:
  - A disclosure (decision N (a)): the button carries `aria-expanded` and names its panel with
    `aria-controls` only while it is open. There is no `aria-haspopup`, which a screen reader
    reads as a menu, and no menu or menuitem role. The items are plain buttons.
  - The panel follows its button in the page, so Tab goes from the button into it and a
    dialog's trap still holds it. It floats on `position: fixed`, 8px under the button and
    flush with its edge, so a pane's edge or a scroll box does not clip it. It follows the
    button however the button moves (its box is read each frame while the panel is open, since
    the page laying out again around it fires no event), and keeps its own scroll when placed
    again. It closes when the button goes out of sight: off the screen, clipped by a scroll
    box, or covered, as the narrow layout's sticky bar covers the strip; what is at the
    button's middle is not the button. A keyboard on a button out of sight opens nothing.
  - A click or Enter opens it and leaves focus on the button; ArrowDown and ArrowUp open onto
    the first or last item. Inside, the arrows, Home and End move between items and go round,
    leaving a field's or a select's arrows to it.
  - Choosing an item closes it and gives focus back to the button, before anything the item
    opens renders. Escape closes it and gives focus back. A press outside, or focus moving to
    anything outside, closes it; focus dropped to the page, as when the window loses it, does
    not.
  - Escape is taken on window in the capture phase, and only with focus on the button or in
    the panel: before a dialog's listener and every drag's, so one Escape closes the menu and
    nothing else, and an Escape pressed elsewhere belongs to whatever has focus.
  - The look is UI_CONFIG's menu: white, radius 4, `--shadow-overlay`, 4px in, 14px/22px items
    at least 30px tall with the minimal hover, and an outline in forced colours. The Dialog
    backdrop's 1100 became the `--z-overlay` token the panel shares.
  - The pipeline strip's unsaved-changes count adopts it. Its list pushed the canvas down,
    stayed open until the count was pressed again, and came back open with the next typed
    change. The list now floats, closes when a node is chosen, and unmounts with the count, so
    it never reopens by itself. `.unsaved-list` goes.
  - The pane actions stay in the page's flow, as GOAL_SHELL S4 put them (a collapsed pane has
    no body to hold a popover). The node context menu keeps its own look until Y15.
  - Raw colours hold at 563. `docs/UI_PRIMITIVES.md` lists 28 primitives.

  Proven by seven tests in `frontend/tests/overlays.spec.ts`, on a pipeline each builds with
  up to four node configurations typed and not saved:
  - The disclosure, on four items: no `aria-haspopup`; `aria-controls` only while open; a click
    leaves focus on the button; Tab goes into the panel; ArrowDown, End, ArrowDown (round to
    the first), ArrowUp (round to the last), ArrowUp, Home and Home land on B, D, A, D, C, A
    and A, so no key can be taken for another; Escape from an item and from the button closes
    and gives focus back; ArrowUp and ArrowDown on the button open onto the last and the first.
  - The float: 8px under the button and flush with it, over the canvas; the look; axe clean
    with it open; a 12px scroll carries it along, and so does the status before the button
    growing 120px; a bar drawn over the strip closes it on the next move; the button moved out
    of sight closes it; ArrowDown on that button opens nothing and keeps focus on it.
  - Its own scroll: with items taller than the room, ArrowUp scrolls the panel to the last one,
    and placing it again after a scroll keeps that offset.
  - Choosing an item closes it, gives focus back and runs the item; Shift+Tab away closes it;
    a press on the strip closes it; focus dropped to the page leaves it open.
  - During a live lasso, with focus in the list, the first Escape closes the list and the lasso
    stays; the second cancels the lasso. With focus outside, the Escape cancels the lasso and
    the list stays.
  - Escape keeps the canvas selection a lasso made, and Enter on an item runs it.
  - The list does not come back open after its count goes and returns.

  **Negative runs,** each against a rebuilt dist, each failing:
  - Escape not stopped: "the Escape that closed the list also cancelled the drag behind it"
    and "… also cleared the selection".
  - Escape taken only from the panel: the disclosure test, at Escape on the button.
  - Escape taken whenever open: "an Escape pressed outside the list did not cancel the drag".
  - A click that focuses the first item: "opening moved focus off the button".
  - No arrow keys in the panel: "ArrowDown did not move focus where it should".
  - The panel portalled to the body: "Tab from the button did not go into its panel".
  - No `position: fixed`: "the panel is not 8px under its button".
  - `aria-controls` always set: the disclosure test.
  - Focus leaving not closing: "focus left and the list stayed over the page".
  - A press outside not closing: "a press outside left the list open".
  - Choosing not closing: "choosing an item left the list open", and the keyboard test.
  - Arrows on a closed button doing nothing: the lasso and keyboard tests.
  - The old in-page open state: "the list came back open".
  - No minimal hover: the hover colour.
  - No following: "the panel stayed where the button was".
  - No hit-test: "the panel floated on over a bar that covers its button".
  - Focus moved into a panel that failed to place: "ArrowDown on a button out of sight dropped
    focus to the page".
  - The panel's scroll not kept: "the panel did not scroll to its last item" (the panel's
    first placing after it opens already threw the scroll away).
  - ArrowUp stepping down, and Home taken for an arrow: "… did not move focus where it should".
  - Restored byte for byte; the hashes matched.

  An adversarial review of the change (four readers, each finding checked by a second reader
  trying to refute it) confirmed five findings, all fixed above: the panel's scroll lost on
  placing, focus dropped when the button is out of sight (found twice), a covered button, a
  button moved by layout alone, and an arrow test on two items that could not tell
  directions apart. Eleven others were refuted.
  - Measured: the full six-project run passed 420 of 420, with the known Platform Graph
    readiness retry. `Menu` rides in the PipelineBuilder chunk, its one importer, so route
    cost holds. Route payload, re-baselined in the open: the shared closure is 4,650 B above
    its record (A2 through A9, the Dialog and this menu's CSS, each inside the tolerance), and
    Menu with placement adds 3,740 B to PipelineBuilder, which took it 198 B past the 8 KB
    tolerance. One earlier run failed a strip test that never renders the menu: its route
    handler's canvas fetch hung past teardown, the late-run backend stall under separate
    investigation; it passed alone three times and in the next full run.

  **3. Tooltip, with its first adopters.** `components/layout/Tooltip.tsx`:
  - UI_CONFIG's dark tooltip: `--tooltip-bg` with `--tooltip-text` at 14px/18px, 8px 12px in,
    radius 4, the overlay shadow, no arrow, over everything on `--z-tooltip` (1200). It sits
    8px from its child, turned to the other side when it does not fit, and is portalled to
    the body on `position: fixed`, so the canvas's scaled stage neither scales nor clips it.
  - It opens once a mouse comes to rest on its child (each move restarts a 100ms wait, a SHIP
    CHOICE), and at once when the keyboard focuses it (`:focus-visible`); a finger never opens
    it, and neither does the page moving under a resting pointer. It never opens while a
    button is held, and a press, Enter or Space shuts it until the pointer comes back or the
    keyboard focuses the child again, so a drag never shows one.
  - WCAG 1.4.13: the pointer can rest in the 8px gap (a `::before` bridge on the side it took)
    or cross onto it, and it stays; it does not time out; Escape hides it without moving focus
    or the pointer.
  - Escape with focus on its child is the tooltip's alone: taken on window in the capture
    phase, so a tooltip the keyboard opened during a drag hides and the drag goes on. With
    focus anywhere else, it hides and the Escape goes on, so a tooltip under a resting mouse
    never costs the pipeline search, a dialog, or the canvas clearing its selection its Escape.
  - It never supplies a name. When its text says more than the child's name ("Auto-layout
    nodes" on Layout), the child is described by it at all times through a hidden copy, as the
    title described it, since a screen reader's cursor moves no focus and opens no bubble.
    When it says the same ("Zoom in"), it describes nothing.
  - It follows its child however the child moves: its box is read each frame while it shows,
    since the canvas's zoom moves an edge insert with no scroll and no resize. It hides when
    the child is out of sight: off the screen, clipped by a scroll box, or covered, judged by
    what is at the child's middle looking through the bubble itself (the Menu's check now looks
    through its panel the same way). The window losing focus hides it.
  - Adopters: the canvas's Zoom in, Zoom out and Fit to view (to their right, since they are a
    stack) and its edge inserts, which gain the name "Insert selected node type" in place of
    "+"; Workshop's Layout, and Duplicate node and Delete node, whose title was their only name
    and which now have their own. Their titles go.
  - Titles that stay native: table cells and spans that cannot take focus, the aria-hidden
    ports, the hidden-link count, truncation sites, Delivery's disabled-reason (which should
    become visible text), and Workshop's Undo and Redo, which are disabled when there is
    nothing to take back and so cannot take focus. They come with the second wave.
  - `Tooltip` and `placement` ride in the dragdrop-vendor chunk, which every route loads:
    Pipeline and Vertex share the canvas that imports the Tooltip, and Workshop imports it
    too, so either would otherwise be a chunk of its own and a request on those routes.
  - Raw colours hold at 563. `docs/UI_PRIMITIVES.md` lists 29 primitives.

  Proven by twelve tests in `frontend/tests/overlays.spec.ts`:
  - Hover on Zoom in: a sweep across it in 1px steps opens nothing until the pointer rests;
    then the dark tooltip 8px to its right and level with it, on the body, no title, no
    description; the look, `position: fixed` and z-index 1200 included; resting in the gap
    keeps it and the gap is the bubble's; on the bubble it stays, and 1.5s later still; Escape
    hides it and focus is the same element; back on the button it shows; a press shuts it, a
    move on the pressed button leaves it shut, and leaving and coming back shows it.
  - Keyboard focus: Shift+Tab onto Zoom in shows it; axe is clean while it shows; Tab moves it
    to Zoom out and Fit to view; Enter shuts it, and so does Space; blur hides it.
  - Workshop: Layout is described as "Auto-layout nodes" before, during and after its bubble;
    Duplicate and Delete node have names of their own, no title and no description.
  - The edge insert at the largest zoom (1.35): the bubble 8px above, centred, on the body and
    unscaled; resting in the gap above keeps it; from the keyboard, Up Arrow fits the canvas
    and the bubble follows the insert.
  - A clipped insert: scrolled just under the pane host's edge and then 30px more, its middle
    lands where the bubble stood, above the edge; the bubble goes.
  - A button held down from bare page onto Zoom in (the pointer checked to be on the button)
    shows no tooltip; a lasso ending on an edge insert shows none, and Escape still cancels it.
  - During a live lasso, a tooltip opened from the keyboard takes the first Escape and the
    lasso the second.
  - With focus in the pipeline search and the mouse resting on Zoom in, one Escape hides the
    tooltip and closes the search; the keyboard then opens it without the mouse moving.
  - With nothing focused, Enter shuts a hover tooltip while the pointer stays on the button
    (checked); the keyboard focusing the button then opens it.
  - With nothing focused, one Escape hides a hover tooltip and clears the lasso's selection.
  - A synthetic touch opens nothing; the pane host scrolling Zoom in under a resting pointer
    opens nothing until the pointer moves; a keyboard tooltip follows a 30px scroll; the window
    losing focus hides it; scrolled up past the pane host's top, clipped but inside the window,
    it goes.
  - On a touch screen (`hasTouch`), a tap on Zoom in opens nothing.

  **Negative runs,** each against a rebuilt dist, each failing:
  - Focus not opening it: "keyboard focus did not show the tooltip", in two tests.
  - The keyboard arriving not clearing a dismissal: "a key pressed while hovering kept the
    keyboard's tooltip shut". (The search test alone did not catch it: closing the search moves
    the button off the resting pointer, which clears the dismissal by itself.)
  - Escape not hiding it: the hover test, at Escape.
  - Escape on its child not kept: "the Escape that hid the tooltip also cancelled the drag".
  - Escape kept with focus on nothing: "the tooltip took the Escape that clears the selection".
  - Escape kept whatever has focus: "the tooltip took the Escape that belonged to the search".
  - Opening under a held button: "a tooltip opened under a held button". (The lasso alone did
    not prove it: its rectangle lies over what it crosses.)
  - A finger opening it: "a touch opened a tooltip". The tap test passes either way, since a tap
    makes no pointer move; it guards the tap flow as a whole.
  - The bubble rendered inline: "the bubble is not on the body", in two tests.
  - `pointer-events: none` on the bubble, and each bridge removed: "the tooltip closed with the
    pointer resting in the gap" beside Zoom in, and above the insert.
  - Describing always: "a tooltip that repeats the name describes nothing", in two tests.
  - Describing never, and describing only while it shows: "Layout's explanation is heard only
    while its bubble shows".
  - A press not shutting it: the hover test, after the click. A move on the pressed button
    reopening it: "a move on the button just pressed brought the tooltip back".
  - Coming back not reopening it: "after Escape, coming back to the button did not show it
    again".
  - Enter, and Space, not shutting it: "Enter left the tooltip showing", "Space left the tooltip
    showing".
  - Not following its child: "the tooltip stayed where the insert was before the zoom" and "the
    tooltip stayed where its button was".
  - No hit-test: "the bubble took itself for the insert and floated on" and "the tooltip floated
    on after its button was scrolled out of sight". The bubble counted as its child: the first.
  - Opening 100ms after the first move, resting or not: "the tooltip opened while the pointer
    was still moving".
  - Opening on the pointer coming in rather than on its moves: "the page moving under a resting
    pointer opened a tooltip".
  - The Menu's hit-test, now looking through its panel, removed: "the panel floated on over a
    bar that covers its button".
  - Restored byte for byte; the hashes matched.

  An adversarial review (four readers, each finding checked by a second reader trying to refute
  it) confirmed fourteen findings, all fixed above: the bubble left behind by a zoom or any move
  without a scroll (found three times); the hit-test taking the bubble's old place for the child
  (and the same hole in the Menu's, through its panel); a dismissal from a key pressed elsewhere
  keeping the keyboard's tooltip shut (twice); Layout's explanation heard only while its bubble
  showed, where its title had always been heard; a hover tooltip taking the canvas's
  clear-selection Escape with nothing focused; opening 100ms after the first move rather than on
  rest; and tests that could not fail (a press, the bridge, the body branch, the lasso's guard,
  claims with no test). The line that dropped a child's title went, since no adopter has one.
  Four others were refuted.
  - Measured: the full six-project run passed 432 of 432, none flaky. Route cost holds. Route
    payload holds without re-recording: the shared closure is 4,600 B above the ceiling the
    Menu recorded (the Tooltip, `placement` and their CSS now in a chunk every route loads),
    3,592 B inside the tolerance; PipelineBuilder's own share fell as `placement` left it.
- **A8 — Tabs and SegmentedControl replace the ad-hoc tabs.** **Met** — `raw_colour_ceiling`
  (599) falls as the eight per-screen tab styles go, re-recorded in each commit (K8). Underline,
  tint, pill and vertical variants; SegmentedControl with `aria-pressed`. The Decision, Ops and
  ModelOps tabs gain `aria-current`, and the artifact review keeps `role="tab"`. To be proven by a
  `look.spec.ts` test per variant, reading its spec from UI_CONFIG, each shown to fail with the
  variant's CSS removed; the seven tab locators and the class locators still pass.

  **1. The primitives, with a first adopter each.** `components/layout/Tabs.tsx`:
  - `Tabs`, the underline kind: a 40px bar ruled by the divider, 14px labels at 400 set 20px
    apart, and the selected one in `--text-selected` over a 3px indicator. Tabs stay buttons
    in a named `nav`, marked with `aria-current`, and keep the `active` class.
  - `SegmentedControl`: 30px, the selected option white with the button ring and drop, the
    others transparent in `--text-muted`, each with `aria-pressed`. The ground was not read in
    the original; it uses `--surface-app`.
  - Decision's tabs adopt `Tabs`, and keep `.decision-tabs` for U3's test and the class
    locators. Their bordered-box CSS goes.
  - Ontology Health's severity filter adopts `SegmentedControl`. Its navy active state goes.
  - The tint, pill and vertical kinds come with the first screen that needs each.
  - Raw colours fell from 599 to 594. `docs/UI_PRIMITIVES.md` lists 26 primitives.

  Proven by two tests in `look.spec.ts`:
  - `Tabs are the original's underline tabs`, on Decision: the bar at 40px with a 20px gap and
    the rule; the selected tab at 14px 400 in `#215db0` with the 3px indicator and
    `aria-current`; another tab in `#1c2127` with neither.
  - `A segmented control is 30px with the selected option raised`, on Ontology Health: 30px,
    the selected option white with the ring and `aria-pressed="true"`, another transparent in
    `#5f6b7c`.
  - U3's Decision tab check still passes.

  **Negative runs,** against a rebuilt dist:
  - The bar and tab rules removed: no gap or rule, and the selected tab in the text colour with
    no indicator.
  - The selected option's rule removed: it read transparent in `#5f6b7c`.
  - Restored byte for byte; the hash matched (`24897d2f35d1bba1`).

  **Found by the full run.** Route cost measured Decision and Ontology Manager at one more
  request on open each (16 and 23 against 15 and 22).
  - Rollup had given `Tabs.tsx` a chunk of its own, because two lazy routes import it. That is
    the trap `DragKit` and `graphLayout` fell into before.
  - It now rides in `dragdrop-vendor`, a chunk every route already loads, with the same comment
    in `vite.config.ts`. The routes are back at 266 requests, and the shared closure is 510 KB,
    inside the tolerance.
  - The rerun on the folded build passed 388 of 388. Route cost holds at 266, and the payload at
    510 KB.

  **A growing retry, not A8's.** Both runs retried "the Platform Graph does not move when
  readiness and job counts land" at 1366. It timed out waiting for the responses it holds back.
  - The trace shows `/jobs/summary` answering in 0.7 s after release, while `/project/readiness`
    never answers.
  - Its duration at 1366 across today's runs: 17 s at U10's last commit, about 38 s from A2
    onward (A2 added the stateful trust tests), 43 s at A4, then past the 45 s timeout.
  - In-process, readiness takes 0.04 s even after ten scenario loads or 40 artifacts with
    collaboration joins. So the endpoint is cheap, and something starves the one server the
    full run shares.
  - It passed 4 of 4 alone.
  - Without the trust tests (`--grep-invert "GOAL_FOUNDATIONS A"`), the full run took it back
    to 20.5 s with no retry. The stateful tests this goal adds are part of the load.
  - Looking for the cause turned up a real server bug. The collaboration WebSocket and both
    server-sent-event streams (collaboration and job events) ran a synchronous SQLAlchemy poll
    on the event loop's own thread, holding the whole server for each open page. Those reads
    now run in the threadpool.
  - `oms/test_collaboration_socket_off_loop.py` slows the database, holds a socket open and
    times a plain request. Before the fix it waited 0.43 s and 0.50 s; after it, under 0.3 s.
    The collaboration, pipeline-execution and runtime stream tests pass.
  - The retry did not go away. The traces show `/project/readiness` itself unanswered, while
    `/jobs/summary` answers. SQLite's 30 s lock wait and the 40-thread limit on sync endpoints
    are the leading suspects. It stays filed as its own task, with these findings, to be found
    with server-side evidence rather than by raising the timeout.

  **2. Ops.** Ops' tab bar is `Tabs`, and keeps `.ops-tabs` and its name. Its three rules go.
  They used tokens only, so raw colours hold at 594.
  - Proven by `look.spec.ts::The ops tabs are the Tabs primitive`, one case of a test that grows
    with each screen: the named bar is a `.tabs` nav with exactly one `aria-current` tab. U3's
    Ops border check and the evaluator's Ops flow pass.
  - Negative run: the hand-written buttons put back read no primitive and no current tab.
    Restored byte for byte; the hash matched (`fc8872e4a3d32e0c`).
  - `docs/INERT_CONTROLS.md` counts 350 controls, one fewer, because the tab buttons are now
    written once, in `Tabs`.
  - Measured: the full six-project run passed 390 of 390, with the same single retry of the
    Platform Graph test, a third run in a row.

  **3. ModelOps.** ModelOps' tab bar is `Tabs`, keeping `.modelops-tabs` for its 12px margin
  and its name. Its navy bordered box goes, and raw colours fall from 594 to 587.
  - Proven by `look.spec.ts::The models tabs are the Tabs primitive`. The evaluator's ModelOps
    flow and the release-gate test pass.
  - Negative run: the hand-written buttons put back read no primitive and no current tab.
    Restored byte for byte; the hash matched (`ef0734a926df5e88`).
  - Measured: the full six-project run passed 391 of 391, with the known Platform Graph retry.

  **4. Security and Control Panel.** Their workspace-header tab bars are `Tabs`, in one commit,
  because they shared the `.workspace-header nav` rules and those could go only once both had
  moved.
  - Each nav gains the name it lacked: "Security & Governance views" and "Administration
    sections".
  - Inside the 42px header, the bar draws no rule of its own, because the header's border is
    the rule. The header itself stays, since the resource header is the plan's Q5.
  - Raw colours hold at 587: the shared rules' colours remain for the drawer, which moves next.
  - Proven by the security and control-panel cases of `look.spec.ts::The … tabs are the Tabs
    primitive`. A screenshot of both headers shows the underline tabs sitting on the header's
    bottom edge.
  - Negative runs: each screen's hand-written nav put back read no primitive and no current
    tab. Both were restored byte for byte, and the hash matched (`a48b54730ab38665`).
  - Measured: the full six-project run passed 393 of 393, with the known Platform Graph retry.

  **5. The pipeline drawer, the tint kind.**
  - `Tabs` gains `variant="tint"`: a 35px bar, the selected tab on `--surface-selected` in
    `--text-selected`, with no indicator.
  - The pipeline's bottom drawer uses it, named "Drawer views". Its hand-drawn blue underline
    and its bar rule go, and raw colours fall from 587 to 584.
  - The truncation test that clicks the drawer's "preview" tab and reads its note passes, as do
    the pane-layout tests.
  - Proven by `look.spec.ts::The pipeline drawer's tabs are the original's tint tabs`. It reads
    a 35px `.tabs` bar and the selected tab on the tint in `#215db0` with no indicator.

  **Negative runs,** against a rebuilt dist:
  - The tint's selected rule removed: the selected tab went clear, with the underline indicator
    instead.
  - The hand-written nav put back: the bar read no primitive, at 30px.
  - Restored byte for byte; the hash matched (`fb15add54380b81c`).
  - Measured: the full six-project run passed 394 of 394, with the known Platform Graph retry.

  **6. The artifact review, as a tablist.**
  - `Tabs` gains `semantics="tablist"`: a `role="tablist"` of `role="tab"` buttons with
    `aria-selected`, one tab stop (the selected tab is tabIndex 0, the others -1), and the
    arrow keys moving the selection and focus. The hand-written tabs had no arrow keys and a
    tab stop on each tab.
  - The artifact review uses it, named "Review views", so the seven `getByRole("tab")` locators
    keep their role (decision N). The underline look replaces its 11px teal-underlined pair.
    The two tabs still split the pane's width.
  - Raw colours fall from 584 to 577.
  - Proven by `look.spec.ts::The artifact review tabs are a Tabs tablist`. It reads Comments
    selected at tabIndex 0 and Proposals at -1, presses ArrowRight, and reads Proposals selected
    and focused. The movement-contract review tests and the U10 tag test pass.

  **Negative runs,** against a rebuilt dist:
  - The arrow keys ignored: the selection stayed on Comments, and focus did not move.
  - The hand-written tablist put back: no primitive, and a tab stop on both tabs.
  - Restored byte for byte; the hash matched (`9d5d16be717dcc4a`).
  - Measured: the full six-project run passed 395 of 395, with the known Platform Graph retry.

  **7. Delivery and the Workshop breakpoint.**
  - Delivery's three section buttons, which borrowed the sidebar's `nav-item` classes, are
    `Tabs`, named "Delivery sections". Each button used to carry a one-line hint as a second
    line; the active section's hint now sits in a muted line under the bar, so nothing is lost.
  - The Workshop breakpoint switch is `SegmentedControl`, named "Workshop breakpoint", with
    capitalized labels and `aria-pressed`. Its own navy-accented CSS goes.
  - Three imports of `classNames` that no longer had a caller (Delivery, Security, Control
    Panel) go with them.
  - Raw colours fall from 577 to 571.
  - Proven by the delivery case of `look.spec.ts::The … tabs are the Tabs primitive`, and by
    `…::The Workshop breakpoint switch is the SegmentedControl`. The latter reads Desktop
    pressed, chooses Tablet, and reads Tablet pressed.

  **Negative runs,** against a rebuilt dist:
  - Delivery's hand-written buttons put back: no primitive and no current tab.
  - The breakpoint's hand-written buttons put back: no primitive and no `aria-pressed`.
  - Both were restored byte for byte, and the hash matched (`d668a6281fb56443`).
  - Measured: the full six-project run passed 397 of 397, with the known Platform Graph retry.

  **A8 as a whole.** All eight tab sets the goal names now draw from `Tabs`: decision, ops,
  modelops, security (with Control Panel), the drawer, the artifact review, delivery and the
  breakpoint. Raw colours fell from 599 to 571.
  - **Narrowed, in the open:** the underline and tint kinds were built, plus the tablist
    semantics and `SegmentedControl`. The pill and vertical kinds were not, because no screen
    here needs them. They come with their first readers, the H goal's Files pill tabs and
    project navigation.
  - `raw_colour_ceiling` passes to A7.
- **A9 — One app registry.** **Met** — one list is the source of `CORE_VIEWS`, the sidebar, the
  command palette and the server's view list, each app with a category, icon, one-line
  description and, where one exists, a create path. Counts derive from its length. To be proven by
  a test that asserts the registry is the only source of all four, shown to fail at `38b096a`
  (where the server allows 27 views and the client 23).

  **What changed.** `frontend/src/apps.json` is the registry: the 23 apps in sidebar order,
  each with an id, a label and a one-line description, taken from the old `NAV_ITEMS`, so
  nothing a user sees changed.
  - `CORE_VIEWS`, the sidebar and the command palette derive from it.
  - Its `legacy_only` list names the four views only the legacy UI draws: home, files,
    applications and search. Backend tests request `/workspace/search`.

  **Narrowed from the text above, in the open:**
  - The server cannot read the registry at runtime: the production image ships
    `frontend/dist`, not `frontend/src` (`oms/Dockerfile`). Its list is now a named constant,
    `WORKSPACE_VIEWS` in `main.py`, and a test holds it equal to the registry's ids plus
    `legacy_only`.
  - Category, icon and create path land with their first reader, the plan's H launcher and
    sidebar. No screen reads them yet, and a field nothing reads is a field nothing checks.
  - No app has a create route today.

  Proven by `oms/test_workspace_registry.py`:
  - the server's list equals the registry's ids plus `legacy_only`;
  - App.tsx's screen switch covers exactly the registry's ids;
  - no client file lists ten or more apps by hand;
  - each app has an id, a label and a description.

  **Negative runs,** each with the file restored byte for byte afterwards:
  - An extra server view ("reports") failed: "serves ['reports'] it does not list".
  - Fusion's screen removed from the switch failed: "no screen for ['fusion']".
  - The old `CORE_VIEWS` literal put back failed: "App.tsx lists 23 apps by hand".
  - At `38b096a` there is no registry to read.
  - The backend route tests (`test_asset_reliability_command_center`, `test_unified_platform`,
    `test_docs_conformance`) pass against the constant.

  **Measured.** The full six-project run passed 386 of 386, with none retried. The registry
  rides in the entry chunk, and the shared closure holds at 509 KB.

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

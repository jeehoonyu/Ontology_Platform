# Foundry UI plan — similar functionality, read from the live product

September 24, 2026. This is a plan document: it has no conditions of its own. It orders work into
goals, names the owner decisions each needs, and states what not to copy. The conditions live in
the goals it names, starting with [`GOAL_LOOK_2026-09-24.md`](GOAL_LOOK_2026-09-24.md) for the
look.

It follows [`FOUNDRY_PLATFORM_UI_REVIEW_2026-09-11.md`](FOUNDRY_PLATFORM_UI_REVIEW_2026-09-11.md)
(the 61-app coverage ledger) and [`FOUNDRY_UI_RESEARCH_2026-09-12.md`](FOUNDRY_UI_RESEARCH_2026-09-12.md)
(the movement research). The first came from a signed-in pass over all 61 launcher entries that
measured no computed styles; the second added public documentation to it. This one measured the
original with `getComputedStyle` in a signed-in browser on September 24, 2026: sixteen surfaces,
in fifteen captures: home, Quicksearch, Notifications, the Applications launcher (62 apps),
Files, a project folder, a dataset, Object Explorer's home, an exploration, an Object View, a
menu, a Workshop module at runtime, the Pipeline Builder, the Ontology Manager, an app landing
page and a resource dialog. The numbers are in [`UI_CONFIG.md`](UI_CONFIG.md); the tokens in
[`frontend/src/tokens.css`](../frontend/src/tokens.css).

What was read cannot prove everything. Nothing was clicked that changes data, so behavior behind
a save, a build or an action run is described from what the screen shows, not from a run. The
enrollment is a trial with example content: counts and names on its screens are its own.

## The short version

1. **The original feels like one product because of connective tissue, not screens.** Every
   resource has a URL; one search finds any of them; recents and favorites follow you; every app
   opens on the same header, menu, dialog and tag. We have none of that tissue. Our 23 workspaces
   are reached from a flat list, and only Object Explorer reads a query parameter (`?type=`);
   the rest take only their view name from the path. The foundations wave builds that tissue
   before any per-app screen.
2. **Our backend is ahead of our UI.** Global search (`GET /search`), a reactive Workshop runtime
   (`oms/app/workshop_runtime.py`), dataset branches and transactions, tenancy memberships,
   object-set cursors and SQL aggregation, and ontology branches and proposals all exist with no
   React caller; ontology change sets have one, but only as a section of one object type. A large
   share of this plan is wiring, not building.
3. **Some of what we ship today is untrue or unsafe, and that comes first.** Object Explorer's
   search looks only inside the first 500 objects; its reads skip property masking; its action
   dialog can change an object the user did not pick; status badges show OFFLINE in green; a
   progress strip marks steps complete on screens that have nothing to do with them. Wave 0 fixes
   those before a single surface is added.
4. **The look is a table, applied through a few base rules and primitives.** That half is
   [`GOAL_LOOK`](GOAL_LOOK_2026-09-24.md), rewritten today from the verified config. It runs
   alongside the functional waves and gates nothing in them except the primitives they share.
5. **Copy what our data can honestly back.** The original shows usage counts, promotion,
   portfolios, SQL consoles, Mapbox, marketplace examples and an AI chat. Where we have no data or
   engine behind them, they stay out; [a table](#what-not-to-copy) says why for each.

## How items are labelled

Items carry the prefix of the goal that will hold them. Prefixes were chosen from the ones no
goal uses (A, H, O, Q, W, Y, Z; U is GOAL_LOOK's):

| Prefix | Goal (to be stated) | Covers |
| --- | --- | --- |
| **A** | app-wide honesty and foundations | status truth, crash-safe storage, the route table, overlay primitives, the app registry, approvals |
| **H** | home and shell | Quicksearch, Home, recents, notifications, launcher, sidebar, account |
| **Q** | projects, files and resource apps | Files, project pages, the dataset app, share and access |
| **O** | Object Explorer and Object View | catalog, exploration, results, Object View, lists |
| **W** | Workshop runtime and composer | View mode, widgets, filter wiring, the composer (GOAL_GRAPH's named successor) |
| **Y** | builders | Pipeline Builder and Ontology Manager parity |
| **U** | look ([`GOAL_LOOK`](GOAL_LOOK_2026-09-24.md)) | tokens, fonts, base rules, primitives' look |

Priority: **P0** blocks trust or safety; **P1** is the core daily workflow; **P2** is important;
**P3** is polish. Effort: **S** under a day, **M** one to three days, **L** about a week,
**XL** more. Every acceptance line below is written to be run once against a build with the
thing it defends removed before it is believed; the goals will name each test.

## Order

| Wave | What | Why here |
| --- | --- | --- |
| 0 | Trust fixes (A1–A5, O1–O3, W2, Y1–Y2, H1) | a screen that lies costs more than a screen that is missing |
| 1 | Foundations: the route table (A6), overlay primitives (A7), Tabs and segmented control (A8), the app registry (A9); GOAL_LOOK U1–U3 | nearly every later item needs a URL, a menu or a dialog |
| 2 | Home and shell (H2–H16), approvals (A10) | the tissue that joins the apps |
| 3 | Projects, files and resource apps (Q) | after decision O on the project model |
| 4 | Object Explorer and Object View (O4–O21) | after O1–O3 and the route table |
| 5 | Builders (Y3–Y25) | geometry after stage bounds; colour groups after decision S |
| parallel | Workshop runtime (W1, W3–W9), then the census W0 and the composer (W10–W13), then W14–W21 | W0 is GOAL_MOVEMENT's precondition for GOAL_GRAPH's named successor, the composer; the runtime adds no drop target and does not need it |

**This plan runs alongside GOAL_GRAPH's named successor, the Workshop composer, and does not
replace it** (decision M). The composer is W11 here and keeps its precondition: the
section/droppable census (W0) that [`GOAL_MOVEMENT`](GOAL_MOVEMENT_2026-09-12.md) requires before
any drop label can be honest. Nothing below adds a drop target before W0 is Met.

Five of the nine L-sized builds in waves 3–5 (Q6, Q8, O8, O10, O13) touch the route-payload ceilings,
DataGrid tests and heading locators. They run one at a time, so a ceiling breach can be
attributed.

## Wave 0 — what we ship today that is untrue or unsafe

| Item | Defect | Where | Fix and acceptance | P / size |
| --- | --- | --- | --- | --- |
| **A1** | StatusBadge picks its tone by substring and defaults to green: OFFLINE, UNKNOWN, BLOCKED, REJECTED, DENY, BROKEN and "not scored" render green; "inactive" renders as a warning because it contains "active" | `components/data/DataDisplay.tsx:64-78`; `styles.css:2344-2366` | Callers pass an explicit intent; unknown words render neutral; unknown severity words are refused (a GOAL_HONEST_UI open item). A test asserts OFFLINE is not green on the backend bar | P0 / S |
| **A2** | Blocked browser storage blanks the whole app: `App.tsx:210` throws on first render. Once that is guarded, the unguarded reads in `VisualBuilder.tsx:157-164` (four builder routes) and `PlatformGraph.tsx:80` still throw inside effects, and with no error boundary that unmounts the whole tree. Corrupt JSON in `ontology.recentViews` blanks it too | `App.tsx:210`, `:231`; `VisualBuilder.tsx:157-164`; `PlatformGraph.tsx:80` | Guard every read and write. With `localStorage.getItem` made to throw, the sidebar, each builder route and Platform Graph still render | P0 / S |
| **A3** | Shipped screens claim what the code does not do: Platform Graph promises "expand neighborhoods" but only filters loaded nodes; Automate's "Paused" counts disabled automations; ModelOps enables "Create release" from submission status, not the gate the Gates tab shows; Ops' rule and test-event forms share one severity and source state; Vertex's six layout buttons change nothing visible (the mini-graph ignores x/y) | `PlatformGraph.tsx:157`, `:99-113`; `Automate.tsx:159`; `ModelOps.tsx:237`; `OpsWorkspace.tsx:69-70`; `Vertex.tsx:73-81` | One commit per screen. Each claim either becomes true or its control and copy go; each gets a test that fails on the old behavior | P0 / S each |
| **A4** | Security's project grants and Control Panel's role grants return 201 for grants that govern nothing: only tenancy memberships govern reads | `security_access.py:51-63`, `:212`; `admin_directory.py:106-114`, `:363-374`; `semantic_scope.py:9-43` | Until decision O, both screens say "does not govern data access" beside the grant form | P0 / S |
| **A5** | Global search returns every project's incidents (events are filtered, incidents are not); the media-set list returns every tenant's sets (MediaSet has no project) | `platform_core.py:424-427`; `media_sets.py:17-30`, `:166-168` | Scope both; a principal of project A gets nothing from B; re-record the tenancy ratchets lower (K8). Sign-in is required in OIDC mode, so these are cross-project reads by signed-in users (any viewer for search, any editor for media sets), inside GOAL_TENANCY T2's tracked debt; the new UI would expose them | P0 / S (search) · M (media, migration) |
| **H1** | The PlatformFlow strip on every workspace marks Import, Ontology and Pipeline complete on unrelated screens, and its links reload the page | `Workbench.tsx:42-67`, `:52`, `:58` | Remove it; its job moves to the walkthrough panel (H12) fed by the server's real step statuses. Re-measure the heights that subtract it (`styles.css:5591`, `:666` and its ≤1100px override `:1930`) and GOAL_SHELL S1 at every width | P0 / S |
| **O1** | Object Explorer's text search runs after the 500-row page limit, so a match at object 501 is never found; counts and facets describe the page, not the set | `object_explorer_ops.py:319-348`; `ObjectExplorer.tsx:110` | Push the text predicate before the limit; use `query_object_set`'s `max_total` for a capped total (the route GOAL2-010 left open); state "10,000+" when capped | P0 / M |
| **O2** | Property masking is applied only by `POST /api/v1/objects/query` and `POST /api/v1/graph/query`; every endpoint Object Explorer uses returns masked properties in the clear | `ontology_runtime_v1.py:1928-1937`, `:2038-2043`; `object_explorer_ops.py:310-529`; `main.py:678-698`; `platform_core.py:390-393` | Apply the existing mask on every read; charts over a masked field refuse. Proven in pytest and the OIDC tier (`frontend/tests/production/oidc-rbac.spec.ts`), because local mode resolves every caller to `*` | P0 / M |
| **O3** | Inspecting a row also selects it for actions; the dialog says "N selected objects" but the executor changes the one object named by a typed parameter; any action with an object mutation is offered on every type (a substring match on `object_id`); a failed run's error sits under the dialog's backdrop | `ObjectExplorer.tsx:142-143`, `:254`; `ontology_core.py:1524`; `object_explorer_ops.py:227-231` | Inspect does not select; the parameter is prefilled from a single selection, or the dialog refuses a multi-selection; bind by `object_mutations[].object_type_id`; errors show inside the dialog | P0 / M |
| **W2** | Workshop "Preview" reports every node READY and SUCCEEDED without evaluating anything | `platform_runtime.py:1614-1636`; `VisualBuilder.tsx:812-827` | For Workshop only (AIP Logic shares the endpoint), show "Structure check: N widgets, M errors, nothing was run" until the View mode (W3) renders real values | P0 / S |
| **Y1** | Pipeline Builder's "Propose" only validates; Output Settings labels a row count as "mapped columns"; six mutations have no error handling, so a failure leaves "Deleting…" on screen | `PipelineBuilder.tsx:815`, `:229-232`, `:1122`, `:290-328`, `:716-724`, `:763-777`; `pipeline_builder_ops.py:685` | No "Propose" while no pipeline proposal endpoint exists; a "Checks" control counts validation results; "Rows out", not columns; every mutation reports its failure | P0 / S |
| **Y2** | Ontology Manager applies a generator draft on a row click, rolls production back on "Restore" with no confirmation, and eight mutations fail silently; audit actors are the literal strings `ontology_manager` and `react` | `OntologyManager.tsx:170-234`, `:292`; `OntologyReleasePanel.tsx:206-209`; `ontology_core.py:1155` | A draft row previews; only "Apply draft" applies; Restore confirms, naming both revisions; failures are announced; actors are principal ids | P0 / S |

Three of these are also filed as separate tasks for immediate repair: O2 (masking), O1 with O3
(search cut and action binding), and A5 (search and media-set scoping).

## Wave 1 — foundations

| Item | What | Acceptance | Depends | P / size |
| --- | --- | --- | --- | --- |
| **A6** | **One route table: every resource kind has a URL.** One module maps each kind to a `/workspace/<view>?…` route. It is shared by the frontend now, and by search's `app_url` (H2) and the resource index (Q4) when they land. `navigate(view, params)` keeps the query and dispatches `popstate`. Readers in this wave: `?graph=` (pipeline), `?type=&section=&page=` (ontology), `?artifact=` (builders; `&mode=` with W3), `?dataset=` (`&branch=` with Q12, `&tab=` with Q6), `?type=&object=&exploration=` (Object Explorer), `?tab=` (ops). Filters use `replaceState`, view changes `pushState`; a default or automatic selection never rewrites the URL | For each kind, `page.goto(route)` selects that resource and Back restores the previous one; an unknown id renders an EmptyState naming it (NonIdealState once GOAL_LOOK U10 lands), never the first item silently | — | P1 / L (first wave) |
| **A7** | **Overlay primitives: Dialog, Menu with Popover, Tooltip.** Dialog traps focus and closes on Escape; Menu opens from a button with `aria-haspopup`, arrow keys move, Escape returns focus; Tooltip opens on hover and focus. The look is UI_CONFIG's overlays. Keep today's hooks: role=dialog with the names "Search workspaces" and "Hotkeys"; node menu items stay buttons (decision N) | Each is in `docs/UI_PRIMITIVES.md` with an adopter; axe-clean while open; Escape never also cancels a live drag | U3 | P1 / M (first wave) |
| **A8** | **Tabs and SegmentedControl.** Underline, tint, pill and vertical variants; segmented with `aria-pressed`. Replaces eight ad-hoc tab styles (decision, ops, modelops, security, drawer, artifact review, delivery, breakpoint) as screens are touched | Each variant matches UI_CONFIG; existing tab locators still pass. The decision, ops and modelops tabs are plain buttons with an `active` class and no ARIA state today; they gain `aria-current` (decision N) and keep the button role. The artifact review tabs are already `role="tab"` with `aria-selected`, and six locators use `getByRole("tab")`; they keep that role | U3 | P1 / M |
| **A9** | **The app registry.** One list is the source of `CORE_VIEWS`, the sidebar and the launcher, each app with a category, icon, one-line description and (where a create route exists) a create path. Counts derive from the registry's length, never a literal | A test asserts the registry is the only source of all three | — | P1 / S |
| **U1–U3** | GOAL_LOOK's first three conditions: count the style table, make the payload gate see fonts, import the tokens and resolve the seven undefined names | See [`GOAL_LOOK`](GOAL_LOOK_2026-09-24.md) | — | P1 |

## Wave 2 — home and shell

Our shell is one component (`App.tsx`) with a 286px sidebar of 23 two-line text buttons, a Ctrl+K
palette that filters those 23 names, a recents list of workspace ids, an always-empty "Legacy
during migration" block, and two bars above every workspace. The original has a 230px sidebar of
grouped icon rows, a Quicksearch over every resource kind, a Notifications popover, an
Applications launcher, and nothing above the app but the app's own header.

| Item | What | Backend | Acceptance | Depends | P / size |
| --- | --- | --- | --- | --- | --- |
| **H2** | **Quicksearch.** Ctrl+J (added; Ctrl+K stays the app palette, as GOAL_GRAPH decided) opens a dialog: kind chips (Apps, Objects, Datasets, Pipelines, More; Files once Q4's resource index gives search a file kind), rows with type icon, name, path and kind chip, arrow keys, Enter, and an "All results" row when the server total exceeds the rows shown | `GET /search` after A5, with a true total before the cut, per-kind counts, an `app_url` from A6, SQL-side predicates, repeatable `kind`, and kinds for builder artifacts, PB graphs, automations, workbooks and Vertex graphs; media sets only after their scoping | Typing a dataset name shows its row with the chip "Datasets"; Enter opens its `app_url`; "Showing N of M" when cut | A5, A6, A7, A9, O2 | P1 / M |
| **H3** | Full results page at `/workspace/search?q=` with kind facets and counts | as H2 | Each row links to its route; "Showing N of M" | H2 | P2 / S |
| **H4** | **Home as the default route.** "Welcome back, *name*" (a level-1 heading), the search pill, a "Get started" card that opens the walkthrough (or links to Command Center until H12), "Recently opened" with Files / Projects toggles, an "Apps · 8 of 23 · View all" grid. No training, community, newsletter or "Install examples" cards | `GET /auth/session`, `GET /tenancy/projects` (ordered by name and unpaged; `updated_at` is written only when a project is created, so the pill reads "Projects", newest first by `created_at`, with "N of M") | `/workspace` and `/workspace/home` show the heading; Recent is empty with an EmptyState (NonIdealState after U10) in a clean browser and lists what was opened after | A6, A9, H5 | P1 / M |
| **H5** | **Recents of resources**, opened in this browser, crash-safe, with kinds (app, dataset, pipeline, object type, object, module) | none (personal workspace scope, labelled "in this browser") | Open X then Y; Home and the sidebar list Y then X; a cut states "N of M" | A2, A6 | P1 / S |
| **H6** | **Applications launcher.** Search, categories with counts, rows with icon, name and description, a details pane with "Open" and (only where that app reads a create intent) "Create new". Command Center goes under Support; Validation, a developer page, leaves the product categories (recommendation) | none | "All apps N" equals the registry length; each category's count equals its rows | A7, A9 | P1 / M |
| **H7** | **Sidebar structure.** Grouped single-line icon rows (Home, Search, Notifications · Recent, Ontology, Applications; Files joins with Q8 in wave 3), an APPLICATIONS section (current app and favorites, else "Default apps"), a bottom group (Walkthroughs once H12 ships, Status with H9, Account with H10). Width and breakpoints per decision H. Needs its own class: `.nav-item` is shared with Delivery's switcher | none | At 1280, ≤ 12 top-level entries, each ≤ 32px with an icon and an accessible name; at 375 the menu still lists every app by category (keeps `evaluator.spec.ts:432-446`) | A9, H5; H8–H10 for their rows; decision H | P1 / M |
| **H8** | **Notifications popover** with an unacknowledged count ("unacknowledged", because read state is team-wide acknowledgement), newest first, subject links, "View all" to Ops' inbox | `GET /ops/inbox` needs a limit and counts (today unbounded; the count lives inside the heavy `/ops/summary`) | Seed 3; the item reads "Notifications, 3 unacknowledged"; "Showing 20 of 57" when cut; Acknowledge lowers the count; no edit permission, disabled with a reason | A7, A6 | P1 / M |
| **H9** | The BackendConnection bar becomes a sidebar **Status** item with a popover, plus an error banner only while the backend is offline; readiness loads on open, offsetting H8's badge request under the zero-tolerance request gate | existing | No bar above the workspace; `shell-widths.spec.ts:250-277` re-pointed in the same commit | A7 | P1 / S (with H8) |
| **H10** | **Account menu** at every width: name, email, roles; Sign out and Sign out of all sessions (disabled with a reason in local mode); Keyboard shortcuts (a global dialog listing Ctrl+J, Ctrl+K and each app's table); Open legacy shell; Documentation | `GET /auth/session`, `POST /auth/logout` | At 375, 1024 and 1280 the menu opens with those items; Escape returns focus | A7 | P1 / S |
| **H11** | Legacy links leave page headers and the sidebar; the legacy shell stays one click away in the Account menu | none | No "Legacy" link in any header; `legacy-shell.spec` still passes | H10 | P2 / S |
| **H12** | **Walkthrough panel**: docked, 450px, dark, between the sidebar and the app, fed by the server's workflow steps. Steps navigate in-app; a mutating step confirms before it runs. Only segments with content (no "Overview / Files" without them) | `/ui-state/command-center` workflow steps; the ontology walkthrough endpoint | "Get started" opens it; step labels and statuses equal the server's; the canvas-widest rule holds with it open | H1, A6, A8 | P2 / M |
| **H13** | **Favorites**, one store for apps, object types and resources (decision T) | a principal-scoped table, or one browser module with one label | Starring pins to the sidebar and Home; state survives reload | A9, decision T | P2 / S–M |
| **H14** | Sidebar collapses to an icon rail with tooltips (a class, not a new breakpoint) | none | Collapsed, every item has a tooltip; shell-widths passes collapsed | H7, A7 | P3 / M |
| **H15** | **AIP Assist**, stated honestly: "Answers come from keyword matching over local metadata; no language model is used", whatever the model gateway lists, until `/aip/assist/query` calls the gateway | `POST /aip/assist/query` (a keyword matcher that says it calls no model) | The panel names its source; prompt results are in-app links | A7, A6 | P3 / M |
| **H16** | Each view names itself in the tab title; no "React evaluator shell" copy | none | `document.title` is "*App* · Ontology AIP" on every view | A9 | P3 / S |
| **A10** | **Approvals inbox.** `GET /approvals` and `POST /approvals/{id}/decision` exist and nothing lists approvals; Command Center shows "the newest of N" with no way to reach the rest; Ops shows a dead "Pending approvals" number | `GET /approvals` needs a limit and a total | The inbox lists open approvals with "N of M"; a decision updates Command Center and Ops | A6 | P1 / M |

## Wave 3 — projects, files and resource apps

We have no Files surface, no project page, no resource header and no share dialog. The server
already whitelists `/workspace/files` and `/workspace/home`; the SPA renders Command Center for
both. Three unrelated project stores exist (`security_access`, `admin_directory`, `tenancy`), and
only tenancy governs reads, so **decision O comes first**.

| Item | What | Backend | Acceptance | Depends | P / size |
| --- | --- | --- | --- | --- | --- |
| **Q1** | **Share and Access write the model that governs reads.** Tenancy is the project model; the other two stores are retired, re-pointed or labelled | exists: tenancy list, members, upsert; missing: revoke (DELETE), project PATCH, the caller's role name, groups | Granting viewer on P lets X read P's datasets; revoking returns 403 | decision O | P1 / M |
| **Q2** | **A viewer can read what a resource app shows.** Router-wide `edit` gates on `datasets_ext`, `lineage_ops` and `media_sets` make every GET need edit; split them per route without un-gating a write | per-route dependencies | A view-only member gets 200 on transactions, branches, schema, view; 403 on writes; `audit_auth_coverage` loses no gate | — | P1 / S |
| **Q3** | **Dataset history that is true.** Uploads write a transaction; 17 other functions assign `DataAsset.records` directly (three in `data_plane.py` move rows to snapshot storage), so History states when rows changed outside it | upload writes SNAPSHOT/APPEND; transactions return `log_matches_rows` and `committed_by` (migration). The server already appends a system SNAPSHOT (`dataset.transaction.baseline_recorded`, reason `records_changed_outside_log`) at the next master transaction or branch (`datasets_ext.py:217-239`), so History is wrong only until the next write | After a bypassing write, History shows "Rows were changed outside this history after transaction #N" | — | P1 / M (precondition of Q6) |
| **Q4** | **One scoped, paged resource index**: `GET /resources` with totals and facet counts, built from column projections (no `records`) | new route over data assets, PB graphs, artifacts, pipelines, object types | A viewer of A sees A's totals and facets only; pages sum to the total; a 200-dataset response stays under a fixed byte bound | A6, Q1 | P1 / M |
| **Q5** | **ResourceHeader primitive**: breadcrumb (project › resource), title as a heading, and only the parts with a backend (branch after Q12, build status after Q13, Share after Q9) | tenancy project names | On a dataset: a level-1 heading, a breadcrumb link to the project, Share opens a dialog | A6, A7 | P1 / M |
| **Q6** | **Dataset resource app**: Preview, History (with "View as of #N"), Details, Health tabs; media sets move to their own screen | transactions, `view?as_of_seq`, schema, on-demand checks | Four tabs, no Compare or Time Travel tab; "Viewing transaction #N of M"; Health says when no monitors exist | Q2, Q3, A6, Q5, A8 | P1 / L |
| **Q7** | **About panel**: updated and created with actor (only when the audit row is at least as new as the data), project location, id with copy, "C columns · R rows", inputs, linked object types, editable description | audit rows under both subject spellings; a description PATCH | The copy button copies the id; a description edit survives reload; "by an unrecorded writer" when the audit is older than the data | Q6 | P1 / M |
| **Q8** | **Files**: projects and resources in one scoped, faceted, paged table; name over path; your role; "+ New ▾" enabled only inside a project; adds the sidebar Files item and the registry entry in the same commit | Q4 | Facet counts equal the index; "Showing 1–40 of N"; each row opens its route | A6, Q4, Q1 | P1 / L |
| **Q9** | **Resource details dialog**: Overview / Access / Activity (no Resource queues, no requirements flow) | members endpoint; a new scoped activity route (the existing `/activity/timeline` has no project scoping) | Share opens it; Access rows equal members; Activity newest first with "N of M"; another project's viewer gets 403 | A7, Q1, Q7 | P1 / M |
| **Q10** | **Create in a chosen project**, not always `default`; ids collide visibly, not silently | `project_id` is already accepted by dataset, artifact and PB graph creates | A dataset created inside P has `project_id == P` | Q1 | P1 / M |
| **Q11** | **Project page**: vertical tabs Files and Access, editable title for administrators | Q4 filtered by project; project PATCH | Rows equal the index for P; a viewer sees no edit affordance | Q1, Q4, Q8 | P2 / M |
| **Q12** | Branch picker and "New branch" on datasets; an unknown branch says so instead of showing zero rows | branches exist (the list omits master) | `?branch=unknown` reads "Branch *b* does not exist" | Q2, Q5, A6 | P2 / S |
| **Q13** | Build status for a dataset, naming which of the three build stores were read | three stores; one is edit-gated | The tags equal the union and the tooltip names the sources read | Q2, Q5 | P2 / M |
| **Q14** | **App landings** (Pipeline Builder, Workshop, AIP Logic, Investigations, Entity Resolution) as opt-in pages (`?home=1` or the header tile): "+ New *thing*" in a chosen project, "Recently edited by you", an empty state. Plain routes still open the editor (more than 20 specs depend on that) | artifact and graph lists | The landing lists the first 10 with "Showing 10 of N"; `/workspace/workshop` still opens the editor | Q4, Q10 | P2 / M |
| **Q15** | Lineage that knows Pipeline Builder graphs and is scoped, for "Inputs" and "Updated via" | adjacency ignores PB graphs; `lineage.py` routes take no principal | B's About shows "Updated via *graph*" linking to the pipeline | Q2, A6 | P2 / M |
| **Q16** | Typed preview grid: the type under each column name, row and column counts, column search | declared or inferred schema | Each header shows its type or "inferred" | Q6 | P2 / S |
| **Q17** | Principal lookup when sharing, scoped to the caller's organization (a privacy decision) | a new directory route | Three letters list principals from the caller's organization only | Q1 | P2 / M |
| **Q18** | Rename, move and delete resources from a row menu; delete states downstream dependents | PATCH and DELETE with a dependents check | Rename persists; delete is disabled with the dependent count when above zero | Q1, Q4, Q15 | P2 / L |
| **Q19** | Compare two transactions or branches | a paged diff route | Added, removed and changed counts equal the server diff | Q3, Q6 | P3 / M |
| **Q20** | Data & Media stops describing its API to users ("Uploads to /data-assets/{id}/upload as multipart…") | — | No API paths in page text | fold into Q6 | P3 / S |

## Wave 4 — Object Explorer and Object View

Ours is one 257-line screen: a type select and a search box above three columns (saved explorations and facets, results, preview), up to 500 rows and 8
columns, a preview panel. The original opens on a catalog, explores with cards that filter,
shows a results table, and gives every object a page. Analytics charts the same fields over the
whole type while Object Explorer counts the loaded page, so one field shows two numbers.

| Item | What | Backend | Acceptance | Depends | P / size |
| --- | --- | --- | --- | --- | --- |
| **O4** | **Action forms typed by parameter type**: numbers, booleans, enums, required markers, "Needs approval" when set; per-object runs only once the approvals inbox exists (decision Q) | types exist server-side and a string for an integer is refused today | `quantity` posts as a JSON number; an empty required field blocks submit | O3, A7, A10 | P1 / M |
| **O5** | The URL carries the exploration and the object (the Object Explorer part of A6) | none with query parameters | `?type=asset&q=pump&object=…` restores everything on reload | A6 | P1 / S |
| **O6** | **Objects and types by title, icon and colour**; display names for properties | `ObjectTypeProfile` has title key, icon, colour, groups; Object Explorer never fetches it | Rows show the title with a tile in the type's colour | — | P1 / S |
| **O7** | **Home: the object type catalog with counts, and the object set catalog.** No usage column (no usage is recorded); a status column shows the Ontology Manager status (`__manager.status`, default "Example", set by the metadata PATCH) | a new catalog route with one grouped count (measure at 10M first); a rollup count says "as of" | One row per accessible type; counts equal the aggregate | O6 | P1 / M |
| **O8** | **Exploration cards**: property search adds a chart or filter card; listogram rows filter (Ctrl-click for "or", Exclude); histograms filter by range; dates bin by month or day | the filter language already has `in`, `not_equals`, ranges; date bucketing is new | Clicking "OPEN" narrows the count to the server's; min/max send `gte`/`lte` | O1, O6, O5 | P1 / L |
| **O9** | **One set of object charts**: Analytics' histogram, listogram, statistic, table and grid move into Object Explorer cards; Analytics keeps the Contour board runner and is renamed for it | endpoints exist; move counts to SQL aggregation | Analytics no longer shows the object charts; the route payload falls | O8, O1 | P1 / M |
| **O10** | **Explore | Results**: a results table with a column chooser, server sort and paging | `POST /objects/query` has order, cursor, total and masking | "Showing 1–100 of 1,234"; a descending sort's first row equals the server's | O1, O2, O5; DataGrid row selection (new, under N7 tests) | P1 / L |
| **O11** | Export CSV of the filtered, masked set, saying how many rows it holds | a streaming export route, capped | "Exported the first 10,000 of 12,345 objects" when capped | O1, O10, O2 | P2 / M |
| **O12** | **Saved explorations with an audience** (only me / everyone in the project), a real owner, rename, delete, a URL (the research's open P1) | missing: DELETE, audience, owner from the principal, a per-user default | A second principal cannot list a private exploration; `?exploration=` restores it | O5, O8, decision R | P1 / M |
| **O13** | **Object View page**: a header with "‹ 1 of N ›", Prominent, Properties with copy, Linked objects by link type with counts. Not on `/object-views/*` (edit-gated, unscoped, reads every link) | profile, link types, search-around, history exist | Sections headed Prominent, Properties, Linked objects; Next opens "2 of N" | O5, O6, O1, O2 | P1 / L |
| **O14** | Object lists that hold selected objects under a name | saved sets hold filters only; needs a kind, member PATCH, DELETE, and an owner taken from the principal (today `owner` is caller-supplied, default "system") | "Pumps to check" shows exactly its 3 objects | O3, O12, O7 | P2 / M |
| **O15** | Linked objects card pivots the exploration to the linked set, stating any seed cap | search-around exists | The pill equals the distinct linked objects; the cap is stated | O1, O8 | P2 / M |
| **O16** | Search objects of every type from the catalog (delegates to H2) | H2 | Results grouped by type with counts | H2, O13 | P2 / M |
| **O17** | Shortcuts: recent and favorite types, your object sets | H5, H13 | Recents list types most recent first | O7, O12 | P2 / S |
| **O18** | "Open in" Map, Vertex, Decision and Automate; an item without a working target is omitted | each target must read URL parameters | "Open in ▸ Map" lands on a visible layer; no edit, Vertex disabled with a reason | O5, O12 | P2 / M |
| **O19** | Object View "More ▾": Add to list, Export as CSV, Copy link | O14, O5 | A role=menu with those three items | O13, O14, A7 | P2 / S |
| **O20** | Risk shows only for scored types and links to Decision | scorecards | No `/decision/evaluate` request for an unscored type | O10 | P3 / S |
| **O21** | Document tabs for several explorations and objects | none | Opening an object adds a tab; closing returns with filters intact | O5, O13 | P3 / M |

## Wave 5 — builders

Pipeline Builder already has a working graph editor (GOAL_GRAPH X1–X8 Met; parity 11 of 15).
What it lacks against the original is a URL, a node that reads like the original's, a stage that
fits the graph, undo for every edit, and the chrome around the canvas. Ontology Manager's backend
is richer than its UI: a section endpoint serving all thirteen navigation sections, a ten-field metadata PATCH (the UI edits two),
create routes for object, link and action types and interfaces, and change sets with diffs.

| Item | What | Acceptance | Depends | P / size |
| --- | --- | --- | --- | --- |
| **Y3** | Pipeline Builder: open a pipeline by URL, name it on create, rename it | `?graph=` shows that graph; Back restores; an unknown id says so | A6, A7 | P1 / M |
| **Y4** | Ontology Manager: deep links for type, section and page; honour the server's own `?object_type_id=` walkthrough link | `?type=…&section=properties` renders that page; Back returns | A6 | P1 / M |
| **Y5** | The stage grows to the graph and Fit fits it (parity gap "zoom-fit"): the fixed 1500 × 700 stage already clips edges past x ≈ 1328, and server defaults place the sixth node at x = 1420 | A node at (1700, 900) has its edge painted; Fit keeps every node in view or states how many it left out | — | P1 / M (before Y6) |
| **Y6** | **The node as the original draws it**: 200 × 60 (a join 200 × 110), a 30px band of a 30px icon cell and the group colour, title 14px 600, body "*n* columns", one input port per join input, 14px ports at the band's edge. Touches `PipelineCanvas.tsx:24-25, 40, 44-45, 112-113, 196, 222-235, 255, 270, 300, 357-365, 421-424`, `styles.css:3011-3015` (`.pipeline-node` 172 × ≥58) and `:2942-2947` (16px `.node-port`), and auto-layout spacing (y 110 equals a join's height) | At zoom 1 every node is 200 × 60; dropping on "right" creates an edge with `target_port: right`; all graph-editor specs pass | Y5; `add_edge.target_port` | P1 / L |
| **Y7** | **Undo and Redo for every graph edit**, Ctrl+Z and Ctrl+Shift+Z (parity gap "undo-redo") | Delete two nodes, Undo: the canvas deep-equals the one before; Redo deletes again | `add_node.node_id`, `add_edge.target_port` | P1 / M |
| **Y8** | Ontology Manager: object-type sections as pages, not one long surface; Object views, Automations and History stop being stubs when data exists | Each nav item renders its page; History lists the type's audit events | Y4, Y9 | P1 / L |
| **Y9** | Ontology Manager navigation: Discover, Proposals, History, the resource kinds with counts, Health issues; on a type, "← Discover", a header with its object count, a "Last edited by" footer. No nav item without a scoped endpoint: Groups, Value types, Cleanup and configuration have none, and Shared properties has only `/shared-property-types` (`ontology_interfaces.py:203-341`), which takes no principal and records no project, so it waits for scoping | Each count equals its list endpoint | Y4 | P1 / M |
| **Y10** | Ontology Manager "+ New ▾": object type, link type, action type, interface, generate from dataset, each through a naming dialog | One POST, then navigation to the new resource; Escape sends nothing | A7, Y4 | P1 / M |
| **Y11** | Ontology-level Proposals and History built on change sets and revisions (not on `/ontology/proposals`, whose merge applies nothing) | Proposals list change sets with diff and consumers; Restore confirms | Y4, Y9 | P1 / M |
| **Y12** | **Legend colour groups as a function**: named groups with counts, an eye toggle (the X6 hide state), "+ Add color" from a selection; ungrouped bands white. Reopens GOAL_GRAPH's "organise" row (decision S); assignment by menu, never by drag (a drop target needs W0) | One commands request creates a group; one Undo removes it | Y6, Y7, A7, decision S | P2 / L |
| **Y13** | A right rail that switches one tool view at a time, listing only views with a backend (outputs, search, changes, deploy, build settings, contracts, node config, pipelines), within GOAL_SHELL S3's third-of-row cap | A vertical tablist; switching keeps typed input (V9, V13) | Y3 | P2 / M |
| **Y14** | One grouped icon toolbar with a 12px label under each group, replacing the label strip and the row of text buttons; icon names keep today's accessible names | graph-editor locators still match | A7 | P2 / M |
| **Y15** | Right-click node menu (parity gap "context-menu"); no "+" on every edge at rest | Shift+F10 opens it; no edge control at rest | A7 | P2 / S |
| **Y16** | Bottom panel as "Selection preview · Suggestions · Pipeline warnings (*n*)" with an empty state | The warnings count equals validation | — | P2 / S |
| **Y17** | A graph History tab on a new scoped history endpoint; no Proposals tab | Another project's viewer gets 403 | Y3 | P2 / M |
| **Y18** | Outputs panel with search, editable settings that do not clobber other parameters, and a true columns-mapped line | One PATCH leaves other keys unchanged | Y1 | P2 / S |
| **Y19** | Ontology Manager Discover: type cards with object count, status and dependents; recently viewed | Counts come from one grouped query | Y9 | P2 / M |
| **Y20** | Metadata card with inline editing of every field the PATCH accepts (EditableText and TagInput primitives) | Enter sends one PATCH with only that key | A7 | P2 / M |
| **Y21** | Properties card with type glyphs, primary- and title-key badges, search, "+ New" | Badges exactly for the profile's keys | Y8 | P2 / S |
| **Y22** | Link types card with list and graph views; a port connect opens a naming dialog instead of posting an auto-named link | The ghost node and "+ New" open the same dialog | A7, Y8 | P2 / M |
| **Y23** | Resource results (object types, action types) in the Ctrl+K palette; the Ontology Manager header search opens Quicksearch pre-filtered, with the Ctrl+J hint | One Ctrl+K listener | H2 | P2 / M |
| **Y24** | Pipeline palette with search, category headings and icons | "N of M node types"; drag and arm unchanged | — | P2 / S |
| **Y25** | Pipeline resource header: breadcrumb, a File / Settings / Help menu bar containing only items that act, checks tag, Deploy split with build settings; no Legacy link | No inert menu item | Y1, Y3, A7 | P3 / M |

## Workshop runtime and composer (parallel track)

Foundry's Workshop is a page composer whose runtime shows a tree of sections: in the measured
module, a 400px filter column, a row of joined metric tiles, a full-bleed map and a table, all
reading one filtered object set. Ours is VisualBuilder: an xyflow graph of widget nodes with no
View mode. The backend holds two Workshop stores that do not meet: the artifact store the React
UI uses (collaboration, proposals, versions, publish), and a WorkshopModule store with a working
reactive runtime (`oms/app/workshop_runtime.py`: typed variables, events, render, dependencies),
called only by the legacy UI.

| Item | What | Acceptance | Depends | P / size |
| --- | --- | --- | --- | --- |
| **W0** | **The droppable census** GOAL_GRAPH names: five drop families today, each declaring what it accepts, generating `docs/DROP_TARGETS.md`; the gate refuses an undeclared `useDroppable` | Synthetic refusals in a test; the check joins the fast tier | — | P1 / S (must be Met before W11, W13) |
| **W1** | **One Workshop store and a page model** with stable section and widget ids (decision P; recommended: author in the artifact store, reuse the runtime's resolver) | An artifact with a page renders widgets in section order; one with only nodes renders as one column; another project's type is refused | decision P | P0 / M |
| **W3** | **View mode** that renders a module as a page: nested rows and columns with fixed, fit and flex sizing; no graph chrome; Edit/View in the URL | An absolute-400 section measures 400 ± 1px; no `.react-flow` in View | W1 | P0 / L |
| **W4** | Object-set variables that take filter inputs; filters wire between widgets | Ticking DEGRADED changes the metric, the table caption and the map count in one render request | W1 | P1 / M |
| **W5** | Filter list widget: value rows with checkbox, count and bar; "only"; keyword; "Show all N"; counts under the other filters | Counts equal the listogram under the other filters | W4 | P1 / M |
| **W6** | Metric tiles bound to aggregations, joined edge to edge, coloured from a closed list | Values equal the resolved aggregation | W4 | P1 / S |
| **W7** | Object table with honest paging and a selection other widgets follow | "40 of 1,234"; a row click highlights one map feature | W4 | P1 / M |
| **W8** | Map widget that keeps its camera after the first fit (also the research's open P2 for the Map workspace) | A filter change leaves center and zoom unchanged | W4 | P1 / M |
| **W9** | **Acceptance: the Common Operating Picture rebuilt on our asset objects** (status, criticality, geometry), with no names or demo data from the original | One spec: a filter tick changes all consumers consistently; stacks at 375 | W1, W3–W8 | P0 / S |
| **W10** | Variables panel with used-by and typed bindings | Binding selects offer only compatible variables | W1, W4 | P1 / M |
| **W11** | **The composer, button-first**: outline, page, inspector; Move up / down / into; sizing select; real breakpoint reflow. GOAL_GRAPH's named successor | A widget moves between sections byte-identical; one Undo restores it | W0 Met, W1, W3 | P1 / L |
| **W12** | Move the Workshop route off the xyflow graph without losing the eleven tests that open `/workspace/workshop` directly, nor the evaluator and shell-widths route loops that include it (re-point them at `/workspace/aip`, still VisualBuilder) | Every listed spec passes; movement gaps stay ≤ 12 | lands with W3 or W11 | P1 / M |
| **W13** | Composer drag with typed drop targets and effect labels ("Move Map into Right column"); Escape restores exactly | New movement-contract rows carry cancel, recover and alternative tests | W0 Met, W11 | P2 / L |
| **W14–W21** | Tab list with live counts; module header, Markdown and collapsible sections; chart widget; the dark scope for runtime sections (GOAL_LOOK's dark half); landing with rename and delete; action button with approvals; date histogram filter; pages and overlays | per item | W3, W4 | P2–P3 |

Where the original's own colours fail our accessibility sweep, ours differ: a module title is
`#fff` (not `#f6f7f9`, 4.31:1 on `#7961db`), a selected tab's count tag is white with `#2d72d2`
text (not white on `rgb(108,156,223)`, 2.82:1), and muted text on dark is `#abb3bf` (5.92:1 on
`#2f343c`; not on `#404854`, where it is 4.37:1), never `#5f6b7c` (2.31:1 on `#2f343c`).

## Every workspace, placed

| Workspace | Where it goes | Notes |
| --- | --- | --- |
| Command Center | stays an app, under Support; Home replaces it as the default route (H4) | its GOAL_HONEST_UI leftovers stay owned there |
| Data Onboarding | left as is for now; its CSV textarea and hard-coded transforms are stated weaknesses | a Data Connection-style source list is not in this plan |
| Validation | out of the product categories (H6 recommendation) | a developer and QA page |
| Ontology Manager and its four panels | Y2, Y4, Y8–Y11, Y19–Y23; Releases become ontology-level Proposals and History (Y11); Governed Packages moves to an ontology-level page | — |
| Pipeline Builder | Y1, Y3, Y5–Y7, Y12–Y18, Y24–Y25 | — |
| Object Explorer | O1–O21 | — |
| Analytics | loses its object charts to Object Explorer (O9); keeps the Contour board runner, renamed for it | — |
| Operational Map | shares the camera rule (W8); its `window.prompt` moves to the Dialog (A7); an "Open in" target that reads URL parameters (O18) | — |
| Fusion | left alone | fixed A–H columns and no formula bar are known; a spreadsheet goal is not in this plan |
| Data & Media | becomes the dataset resource app (Q6) and a media screen | — |
| Automate | A3 (the Paused number); an "Open in" target (O18); authoring conditions and effects is not in this plan (not measured live) | — |
| ModelOps | A3 (release gating) | — |
| Delivery | its switcher stops borrowing the sidebar's `.nav-item` (H7) | — |
| Security & Governance | A4, then Q1; an audit viewer waits for scoped audit reads (GOAL_TENANCY T2) | — |
| Control Panel | A4 | a scoped left navigation is a later item |
| Decision Intelligence | A1; an "Open in" target that reads URL parameters (O18) and the destination of O20's risk link; Entity Resolution exists both here and as a builder route: merge or label (recommendation) | — |
| Operational Control | its inbox is reached from H8; A3 (shared form state) | — |
| Vertex | A3 (layout buttons); an "Open in" target (O18); expansion must not use the unscoped `/graph/neighbors` | — |
| Platform Graph | A3 (the "expand neighborhoods" copy) | same unscoped-endpoint caution |
| Workshop | W1–W21 | — |
| AIP Logic, Investigations, Entity Resolution | stay VisualBuilder; opt-in landings (Q14) | W12 moves only Workshop |
| Agent runtime panel | stays embedded; H15 states the assist source honestly | — |
| Artifact review panel | stays; a diff preview is a later item | — |
| Notepad (backend only) | not shipped; "Copy for Notepad" is not copied | `/notepad/documents` exists with no UI |

## Owner decisions

Lettered from G, continuing [`GOAL_REPAIR`](GOAL_REPAIR_2026-08-23.md) (D, E) and
[`GOAL_HONEST_UI`](GOAL_HONEST_UI_2026-09-11.md) (F). None is decided; each is recorded when made
as "Decided YYYY-MM-DD: … (options offered: …)".

| Decision | Question | Options | Recommendation |
| --- | --- | --- | --- |
| **G** | Which face ships? | (a) Source Sans 3 400, 400 italic, 600, about 55–65 KB and 2–3 requests per route; (b) system-ui, dropping "Inter", which is not bundled and not installed, so today the app renders Segoe UI | (a) if matching the original is the goal |
| **H** | The sidebar | (a) colour only; (b) colour and the original's 230px, which reopens GOAL_SHELL (its breakpoints and width tables were tuned to 286px); (c) leave it | (a) now; (b) with H7, as its own condition re-proving all 18 widths |
| **I** | How much gets restyled | (a) tokens, base element rules and primitives; (b) new primitives only (two looks); (c) the whole sheet at once (GOAL_UI_ENHANCEMENT J2 declined this) | (a) |
| **J** | Import the token file whole? | (a) whole, about 13.2 KB minified (13,219 B by esbuild), re-baselining route payload in the open; (b) only referenced tokens | (a) |
| **K** | Body text 16px → 14px / 18px? | (a) yes, in its own commit; (b) keep 16px | (a) |
| **L** | Where the font files come from | (a) vendored woff2 with the licence and a checksum header; (b) an npm package; (c) a CDN | (a); someone downloads them once, with the owner's go-ahead |
| **M** | Order against GOAL_GRAPH's successor | (a) this plan and GOAL_LOOK run alongside the composer and touch no drop target; (b) the composer first | (a), stated in each goal |
| **N** | Semantics for Tabs and Menu | (a) keep buttons with `aria-current` / `aria-pressed`; (b) ARIA tablist and menu, moving about 8 locators | (a) |
| **O** | The project model | (a) tenancy is the one model; the other two are retired or labelled; (b) keep three | (a) |
| **P** | The authoritative Workshop store | (a) the artifact store, reusing the runtime's resolver; (b) WorkshopModule | (a) |
| **Q** | Actions over several objects | (a) one run per object with one approval each; (b) refuse multi-selection | (b) until the approvals inbox exists, then (a) |
| **R** | Saved exploration defaults | (a) a private default per user and a project default; (b) private only | (a) |
| **S** | Reopen "organise" for legend colour groups | (a) yes, citing capture 12; (b) keep it declined | (a), groups only (no folders or text nodes) |
| **T** | Where favorites and recents live | (a) a principal-scoped table; (b) one browser module, labelled "in this browser" | (b) for recents; (a) for favorites |

## Gates every item touches

| Gate | Today | What the plan does to it |
| --- | --- | --- |
| `audit_inert_controls` | 0 inert of 350 (the baseline file still records 318 from 2026-09-11) | a copied control acts, links, submits or says why not; the audit counts a bare `disabled` as wired, so every disabled control carries its reason |
| `audit_table_truncation` | 11 unfixed names | O1 and O13 remove two; every new request limit is a stated window; owners for the rest: Decision's drivers (A3 era), the mini-graph (Vertex, A3), VisualBuilder participants and preview (W2), contract-run history (Pipeline Builder: the 50-run cap in `/ui-state/pipeline/{id}/ontology-contracts`, a Y-wave item), import warnings (Data Onboarding), pipeline output builds (Y18) |
| `audit_route_payload` | shared closure 448,574 B, 8 KB tolerance; measured 450,142 B | one ledger across goals; every `--set-baseline` is named in the open; overlays, Home and the launcher load lazily; fonts only after the gate can see them (U2) |
| `audit_route_cost` | 16 rows; requests have no tolerance | new rows for home, files, search, data-media, fusion, vertex, workshop, aip, investigations and entity-resolution, added in the open; H8's badge request is offset by H9 |
| `audit_ui_states` | raw empty ceiling 32 | new screens use EmptyState; the NonIdealState step lowers it |
| `audit_style_scope` | 35 shared classes | a class going from one user to two is declared in its first commit |
| `audit_ui_primitives` | 24 primitives | each new primitive lands with an adopter |
| `audit_pane_layout` | 11 of 24 movable (a floor) | unchanged or higher |
| `audit_graph_editor` | 11 met, 3 gaps, 1 declined | Y5, Y7, Y15 close the three gaps; Y12 reopens the declined row by decision S |
| `audit_movement_contract` | 12 gaps | never rises; W13 adds rows with their tests |
| `audit_tenancy_scope`, `audit_tenant_orphans` | ceilings 344 and 52 | A5, Q9 and Q15 lower them (Q2 changes permission tiers, which neither audit counts); nothing is built on an unscoped read |
| `audit_auth_coverage`, `audit_route_coverage` | — | Q2 splits router gates without un-gating a write |
| `audit_extensibility` (coupling ceiling 0) | 0 | Home, walkthrough and risk work must not add asset-specific couplings |
| `audit_frontier` (K1) | — | every new non-zero ceiling is named by an open condition |
| browser gates | `shell-widths.spec.ts` at 18 widths; the evaluator axe sweep; 64 heading-role locators | titles stay heading elements; permission-dependent items are proven in the OIDC tier |

## What not to copy

| Original | Why not |
| --- | --- |
| Palantir logo, Blueprint icon font, the isometric illustrations, Foundry product names, Blueprint as a library | brand; we take the values, not the marks, and a UI library would break the payload gate |
| The full 62-app catalogue | we list our own apps; a listed app we lack is an inert entry |
| "What's New", "Support", training, community, newsletter and "Install examples" | no feed, desk, training platform or example gallery behind them |
| Portfolios, promoted items, "Promoted files", tags and custom metadata, org badges | no model behind them; the count would always be 0 or 1 |
| Views and usage counts, "Last viewed" | no view events are recorded (the one usage store, `admin_usage_records`, holds compute, storage and row metrics, not views); the numbers would be invented |
| "Shared with you" | memberships record no granter, so it cannot be told apart from "you created it" |
| Trash | no resource kind Files would list is soft-deleted or restorable; data assets have no delete route yet (Q18 first) |
| SQL console, "Create table", "Object mode" | no route runs a person's SQL (DuckDB runs only structured snapshot queries and pipeline plans); GOAL_HONEST_UI N2 deleted our `SQL console / Preview / Object mode` footer as inert |
| File / Theme / Help menu bars with nothing in them, a theme toggle | no dark theme or help content; an empty menu is inert |
| Pipeline and ontology branch pickers, pipeline Proposals | no pipeline branch backend; ontology merge applies nothing |
| Rail views for schedules, file tree, evaluation suites, unit tests; Resource queues; branch protection on datasets | no backend for pipeline graphs or datasets |
| "Calculate row count", "Time Travel [Beta]", marketing "New" tags | our row count is exact; time travel is a History action |
| Mapbox basemap | a licence, a token and a third-party tile network; OSM with attribution stays |
| An AI chat that answers from keyword matching | the assist endpoint says it calls no model; H15 says so on screen |
| "Copy for Notepad", "Switch to configured view", object comments | no Notepad UI, `/object-views/*` is edit-gated and unscoped, no object comment store |
| Replacing Ctrl+K with Ctrl+J | GOAL_GRAPH keeps Ctrl+K as the app palette; Ctrl+J is added |
| Colours that fail AA on our sweep | the module title, the selected count tag and muted text on dark (see the Workshop section) |
| Free x/y positioning of widgets, automatic state saving across sessions | the original's "absolute" is a size; saves are named by scope (V8) |

## What this plan does not know

- How any enterprise-only feature behaves behind a click: nothing that changes data was clicked.
- The PB bottom panel's open height, a switch control, a selected light table row, the port ring
  colour: not measured (listed in [`UI_CONFIG.md`](UI_CONFIG.md#what-was-not-measured)).
- The cost of the grouped counts at ten million objects (O7), of the text predicate before the
  limit (O1), and of date bucketing (O8, W20): each is measured before its number is chosen, as
  GOAL2-010 did.
- Whether the owner wants parity or a product of our own on any line above: the decisions table
  is where that is recorded.

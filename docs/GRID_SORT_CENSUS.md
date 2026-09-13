# Grid sort census

Which `DataTable` call sites need their rows sorted, and so get `DataGrid` under N7d of
`GOAL_HONEST_UI_2026-09-11.md`. Taken on 2026-09-12 against commit `33508ae`; line numbers
are as of that commit and drift as files change.

The decision this serves: after N7a measured the grid at **+44.0 KB** on its route, the owner
chose to adopt it only where a person needs to sort the rows, and to keep `DataTable`
everywhere else. A verdict here is a claim about the product, made from the source, and it
names the finding task that sorting serves. Being a list is not enough.

## How it was taken

Five readers split the fifteen files that use `DataTable` and classified every `<DataTable`
occurrence. For each, a reader recorded where the rows come from, how many there can be, what
order they arrive in and what the columns are. Each reader's per-file count had to match a
search for `<DataTable` over `frontend/src`, which found 73. All fifteen files matched and
no site was missed. A second reader per group then opened the source at every cited line and
tried to refute each verdict. **5 verdicts changed**, listed below. The census read
the code and the local databases only. It did not observe anyone using the product, so a
verdict that turns on real usage is marked unclear and says what would settle it.

**7 need sorting, 9 are unclear, 57 do not.**

## What adopting the grid at the sorting sites involves

- **No `App.tsx` table needs sorting**, so nothing has to load the grid on demand, and the
  shared closure every route downloads is unaffected. The one `App.tsx` site left unclear, the
  connector fetch evidence, stays a `DataTable` until its evidence is in.
- **Four of the seven are in `ControlPanel.tsx`** (users, role grants, API tokens, job
  telemetry). That route pays +44 KB once for all four. The other three charge their own
  routes: `OntologyManager` (the registry compatibility panel is imported only by it),
  `PipelineBuilder` and `OpsWorkspace`.
- **The grid sorts cells as displayed text, and two sites need more than that.** The
  operations feed has a severity column holding `info, warn, warning, error, medium, high,
  critical`, which text order does not rank. Its `occurred` column is a locale string, which
  text order does not put in time order. Those columns need their own sort functions before
  the feed adopts the grid, and its unsorted state has to stay newest first.
- **Sorting a loaded window ranks only the window.** The job telemetry holds the latest 50
  jobs and the operations feed the latest 250 events. A sorted column there must not read as
  "slowest job ever".
- **The contract-issues table cuts its rows at the call site.** `PipelineBuilder.tsx` hands the
  table `issues.slice(0, 25)`. Sorting that would reorder a sample while looking like the whole
  set, so the cut has to go first. See N9 in the goal document.
- **Several sorting tasks would be served as well or better by a filter.** Examples are finding
  one user by name and gathering every BREAKING row before a registry publish. That is N7c,
  and it does not remove the need to sort.

## Sites that need sorting (7)

### `workspaces/ControlPanel.tsx:333` — Users section > Users

**Verdict: sort**, upheld by the second reader.

- **Rows:** users.value from admin.listUsers -> GET /admin/users (controlPanelApi.ts:62-64); handler admin_directory.py:271-274, query(AdminUser).all(), no limit or paging
- **How many:** Unbounded: one row per human account, never deleted (status flips to inactive, admin_directory.py:277-289). Grows with the organization; any real enrollment passes the 40-row page
- **Arrival order:** No ORDER BY, so insertion order in effect. Incidental: not alphabetical, not by status.
- **Columns:** id, username, status, organization_ids, marking_ids (display_name and email are not returned). username and status are the columns a person orders by.
- **Route cost:** control-panel route only (lazy chunk, App.tsx:69): the first adopting site in this file pays +44 KB for the route and later sites here add nothing; the shared closure is untouched

Census reader: Finding task: locate one account by username, or gather every inactive account, in a list that arrives in arbitrary order and is paged by 40 with no search. Sorting on username brings it to a known position; sorting on status clusters the inactive ones. This table is the only place the page shows each user's organization_ids and marking_ids; the status select at :315-321 lists usernames but not those. A filter (N7c) would serve this better; sorting is what the grid offers now.

Second reader: Refutation failed. rows = users.value from GET /admin/users (controlPanelApi.ts:62-64); handler admin_directory.py:271-274 is query(AdminUser).all() with no order, limit or paging. Nothing deletes users: set_user_status (:277-289) only flips status. The model has no unique constraint on username (:64-74, index only), and a grep of oms found no other writer of AdminUser, so the list is unbounded and in insertion order. The finding task is real. The page counts inactive users (Metric at :291) but never lists which ones; sorting on status gathers them. The Change User Status select (:315-321) labels users 'username (status)', but its options are in the same arbitrary order and omit organization_ids and marking_ids, which only this table shows. Sorting on username puts a known account at a known position across 40-row pages (TABLE_ROW_LIMIT, DataDisplay.tsx:94). Control-panel route only. The first adopting site in this file pays the +44 KB and later ones add nothing.

### `workspaces/ControlPanel.tsx:571` — Roles section > Role Grants

**Verdict: sort**, upheld by the second reader.

- **Rows:** grants.value from admin.listRoleGrants() with no scope filter -> GET /admin/roles (controlPanelApi.ts:153-156); handler admin_directory.py:377-383, q.all(), no limit
- **How many:** Unbounded: one row per principal x scope x role, appended on every grant with no dedupe (admin_directory.py:363-374). Grows with users, groups and scopes, so it passes 40 in any multi-team enrollment
- **Arrival order:** No ORDER BY, and the response carries no id or created_at, so the order is neither chronological nor grouped. Incidental.
- **Columns:** scope_type, scope_id, principal_type, principal_id, role
- **Route cost:** control-panel route only (lazy chunk, App.tsx:69); shares the one +44 KB charge with the other sort sites in this file

Census reader: Finding task, an access review: who holds administrator or owner (sort by role), and everything one principal holds (sort by principal_id) or everything granted at one scope (sort by scope_id). Sorting also puts duplicate grants side by side. The Access Check panel (ControlPanel.tsx:575-608) resolves one user at one scope only and cannot answer 'who holds administrator'. In arbitrary order across 40-row pages, this table cannot answer it either.

Second reader: Refutation failed. rows = grants.value from listRoleGrants() with no scope filter (ControlPanel.tsx:481), i.e. GET /admin/roles (controlPanelApi.ts:153-156). Handler admin_directory.py:377-383, q.all(), no order, no limit. It returns scope_type, scope_id, principal_type, principal_id and role, but not id or created_at, even though the model has created_at (:106-114). grant_role (:363-374) always inserts with no dedupe, there is no revoke endpoint, and a grep found no other writer, so the list only grows. The access-review task is real. Access Check (:575-608) resolves one user at one scope and cannot answer 'who holds administrator or owner' (sort by role) or 'everything principal X holds' (sort by principal_id). Sorting also puts duplicate grants side by side. Control-panel route only.

### `workspaces/ControlPanel.tsx:742` — Auth section > API Tokens

**Verdict: sort**, upheld by the second reader.

- **Rows:** tokens.value from admin.listTokens() with no principal filter -> GET /admin/tokens (controlPanelApi.ts:310-313); handler admin_auth.py:255-263, q.all(), no limit
- **How many:** Unbounded and monotonic: every issuance adds a row (admin_auth.py:206-221, 'Issue once' at ControlPanel.tsx:724), and revoke only sets revoked=True (admin_auth.py:245-252), so rows are never removed. Passes 40 in any environment that rotates worker tokens.
- **Arrival order:** No ORDER BY (database order), even though created_at exists. Incidental.
- **Columns:** id, principal_id, principal_type, token_prefix, scopes, revoked, expires_at, created_at, last_used_at
- **Route cost:** control-panel route only (lazy chunk, App.tsx:69); shares the single +44 KB charge

Census reader: Finding task: choose which tokens to revoke. Sort by last_used_at to find tokens never or least recently used, by expires_at to find the soonest or never-expiring ones, by principal_id to see all of one account's tokens, and by revoked to separate dead rows from live ones. The Revoke select in this panel's action (ControlPanel.tsx:741) lists non-revoked tokens by prefix only, so this table is where the decision is made, over an ever-growing list in arbitrary order.

Second reader: Refutation failed. rows = tokens.value from listTokens() with no principal filter (ControlPanel.tsx:622), i.e. GET /admin/tokens (controlPanelApi.ts:310-313). Handler admin_auth.py:255-263, q.all(), no ORDER BY, although created_at is returned. Each issue_token call inserts a row (:206-221), revoke only sets revoked=True (:245-252), and the only db.delete in admin_auth.py is for OAuth clients (:298). Rows are never removed and the list only grows. The task is real: deciding which tokens to revoke. The Revoke select in this panel's action (:741) lists non-revoked tokens by token_prefix only, with no principal, last_used_at or expires_at. Those appear only in this table, where sorting on last_used_at, expires_at, principal_id or revoked turns up stale, soon-expiring or never-expiring, per-account and dead tokens. Control-panel route only.

### `workspaces/ControlPanel.tsx:1423` — Runtime section > Durable Job Telemetry

**Verdict: sort**, upheld by the second reader.

- **Rows:** jobs.value from admin.listRuntimeJobs(projectId) -> GET /runtime/observability/jobs?project_id=..&limit=50 (controlPanelApi.ts:587-589); handler runtime_observability.py:390-400, after backfilling every PlatformJob in the project (:317-338)
- **How many:** Capped at 50 by the client's limit=50 (server allows 1-500). Any active project fills the cap, since all historical jobs are backfilled, so 50 rows = two pages of 40.
- **Arrival order:** created_at desc (runtime_observability.py:400). Newest first is meaningful, but it is not the only meaningful order for this data.
- **Columns:** 21 columns from _observation_dict (runtime_observability.py:120-125): id, project_id, job_id, correlation_id, job_type, actor, status, attempt, progress, queue_latency_ms, duration_ms, compute_seconds, token_units, record_units, estimated_cost_usd, metrics, spans, error, created_at, updated_at, completed_at
- **Route cost:** control-panel route only (lazy chunk, App.tsx:69): +44 KB once for the route, shared with the other sort sites in this file; the shared closure is untouched

Census reader: Finding task: the metrics directly above report P95 execution, P95 queue and estimated cost (ControlPanel.tsx:1362-1364). This table is where a person finds the jobs behind those numbers: sort by duration_ms or queue_latency_ms for the worst latency, estimated_cost_usd for the most expensive, status for FAILED ones, attempt for retries. Across 50 newest-first rows split over two pages, the worst job may sit on page 2, invisible. Caveat for adoption: a sort reorders only the latest 50 the client asked for, so the caption must not read as all-time 'slowest job'.

Second reader: Refutation failed. rows = jobs.value from GET /runtime/observability/jobs?project_id=..&limit=50 (controlPanelApi.ts:587-589). The handler (runtime_observability.py:390-400) first backfills an observation for every historical PlatformJob in the project (:317-338), then returns created_at desc, limited to 50 (the server default is 100, range 1-500). Any active project fills all 50 rows, which is two 40-row pages. There are 21 columns (_observation_dict :120-125), including duration_ms, queue_latency_ms, estimated_cost_usd, status and attempt. The task is concrete: the metrics just above show P95 execution, P95 queue and estimated cost (ControlPanel.tsx:1362-1364), and this is the only place to find the jobs behind them. Without a sort, the slowest or failed job can sit unseen on page 2. The census caveat still applies: a sort ranks only the latest 50 loaded, not all time. Control-panel route only, sharing one +44 KB charge.

### `workspaces/OntologyRegistryPanel.tsx:183` — Schema Registry (section schema_registry of Ontology Manager) > Panel "Semantic Compatibility"

**Verdict: sort**, upheld by the second reader.

- **Rows:** compatibilityRows (useMemo, L58-63), mapped from compatibility.entries (POST /ontology/registry/compatibility, run by "Check compatibility") or else selected.compatibility.entries (stored on the registry entry). Entries come from ontology_versioning._ontology_diff between the channel's latest registry manifest and the revision manifest (oms/app/ontology_registry.py:440-444, 466-469; oms/app/ontology_versioning.py:445-483).
- **How many:** Unbounded by construction and project-wide. The diff covers every object type, link type and action type in the project. It emits one row per added or removed resource, per changed link or action type, and per added, archived or changed property on every object type, plus metadata changes. A first publish against the empty manifest gives one row per resource.
- **Arrival order:** Grouped by resource type (object, link, action), then by change kind (added, removed, changed), with ids and property names sorted within each group. BREAKING rows are interleaved, for example PROPERTY_ARCHIVED among PROPERTY_ADDED. The order is incidental to the decision the panel supports.
- **Columns:** change (kind with underscores as spaces), resource (resource_id), property (property_name or "-"), classification (BREAKING | NON_BREAKING)
- **Route cost:** OntologyManager route only. OntologyRegistryPanel is statically imported only by OntologyManager.tsx:42, so it lives in the OntologyManager lazy closure (App.tsx:62; ceiling 703,043 B); the shared closure (442,846 B) is untouched.

Census reader: The finding task is to find every BREAKING change before ticking "Acknowledge breaking changes" and pressing "Publish registry" (L157-158). The status message gives only the total change count and overall classification (L71), not which rows break. In arrival order, BREAKING rows are scattered through groups, and past 40 rows some fall onto later pages. Sorting by classification puts every BREAKING row first (B sorts before N) on page one. Sorting by resource gathers one object type's changes when judging a single consumer's exposure. The set is a project-wide, per-property diff, so it can reach dozens of rows in one release. This is the only site in these files where column order changes what a person can find before an irreversible publish. Caveat: a BREAKING-count caption or a classification filter (N7c) would also serve this task.

Second reader: I tried to refute this and could not. The rows are compatibilityRows (L58-63), mapped from _ontology_diff entries (ontology_versioning.py:445-483) through _compatibility (ontology_registry.py:440-444, 466-469). The diff is project-wide and has no cap. Its order is: for each resource type, ADDED (not breaking), then REMOVED (always breaking), then per object type PROPERTY_ADDED (breaking only if required), PROPERTY_ARCHIVED (always breaking), PROPERTY_CHANGED (mixed) and METADATA_CHANGED. That places BREAKING rows in several separate stretches, and past 40 rows some fall onto later pages. The finding task is concrete. Publishing a BREAKING diff without the acknowledgement is refused (ontology_registry.py:483-484), and the person decides whether to tick 'Acknowledge breaking changes' before 'Publish registry' (L157-158). The status line shows only the overall classification and the total change count (L71). The server's summary.breaking count is never shown, so the rows are the only place breaking changes are named. The classification column holds two values, and an ascending sort puts BREAKING first. Caveats: a first publish against the empty manifest emits only ADDED rows, none breaking (ontology_versioning.py:450-451), so the task applies to later publishes. The row mapping also drops resource_type (L58-63). A BREAKING-count caption or an N7c filter would serve the same task. Route: OntologyRegistryPanel is imported statically only by OntologyManager.tsx:42, and OntologyManager only through lazy() at App.tsx:62. Adopting the grid would charge only the OntologyManager route and leave the shared closure (442,846 B) untouched.

### `workspaces/PipelineBuilder.tsx:701` — Selected Node > Ontology contract > details '{n} contract issues' (OntologyContractPanel)

**Verdict: sort**, changed from unclear by the second reader.

- **Rows:** issues.slice(0, 25). issues is contract.violations flattened into one row per error, {row, object, field, issue} (PipelineBuilder.tsx:675-680). The contract comes from details.metadata.ontology_contract (prospective) or latestContract. The server keeps at most 100 violations (pipeline_builder_ops.py:1624, industrial_workflow.py:766/805), and one violation can hold several errors.
- **How many:** Cut to at most 25 rows at the call site, out of an issues list that can exceed 100 (up to 100 violations times errors per violation). The summary shows issues.length, but the rest are not reachable from the table. This slice is not named in docs/table-truncation-baseline.json.
- **Arrival order:** Violation order, i.e. preview row order
- **Columns:** row, object, field, issue
- **Route cost:** PipelineBuilder only (manifest.json:263-276). OntologyContractPanel is defined in PipelineBuilder.tsx.

Census reader: There is a real finding task: which ontology property is rejecting rows, i.e. group issues by field. But the table holds only the first 25 issues, and sorting a 25-row slice would reorder a sample while looking like the whole set. What settles it: (a) whether the slice(0, 25) at PipelineBuilder.tsx:701 is removed so every loaded issue is in the table, and (b) whether real contract previews produce more than about 40 issues across several fields. If both hold, sort by field; otherwise no. A per-field count would answer the same question without the grid.

Second reader: The source settles the census's condition (b).

How many issues can exist:
- The prospective contract (PipelineBuilder.tsx:413) comes from _execute_graph.
- _execute_graph checks every row of the input asset: rows = asset.records, no limit (pipeline_builder_ops.py:1667).
- Each rejected row becomes one violation holding one or more errors (lines 1510-1538).
- An unknown mapped target adds an error to every row (lines 1515-1516), and required-missing and type-mismatch errors are added per property (lines 1520-1527).
- The server keeps up to 100 violations (pipeline_builder_ops.py:1624; industrial_workflow.py:766, 805).
- So issues exceed 40 whenever more than about 40 rows are rejected. That is common for any systemic mapping problem on a real dataset.

The order is row index. For the real finding task, 'which ontology property is rejecting rows, and what are all the issues for property X', that order is incidental: errors for different fields interleave row by row across 100+ issues and 3+ pages. Sorting by field (or by issue) makes each property's rejections contiguous. Nothing else on the panel breaks rejections down by field; the KeyValueGrid shows only totals (lines 693-700).

Prerequisites, the same as the census's condition (a):
- Remove issues.slice(0, 25) at line 701 first, or in the same change. It is an unregistered silent cut, and a sort over it would reorder a hidden sample.
- Caption that the list covers at most the first 100 rejected rows out of rejected_rows.

A per-field count summary is the cheaper alternative, if the owner prefers it to the grid.

Route: PipelineBuilder only. OntologyContractPanel is defined in PipelineBuilder.tsx, which is its own entry (manifest.json:263-276).

### `workspaces/OpsWorkspace.tsx:46` — Live Operational Feed (Command Center tab)

**Verdict: sort**, upheld by the second reader.

- **Rows:** rows = events.map(...) (OpsWorkspace.tsx:44). events come from listOpsEvents(), GET /ops/events?limit=250 (opsApi.ts:15). The server allows up to 1000 (ops_control.py:942) and applies the client's 250 (ops_control.py:954).
- **How many:** Capped at 250 rows by the client limit. The server's summary.events can be larger, and the panel says so (OpsWorkspace.tsx:45-46). 250 rows is 7 pages of 40.
- **Arrival order:** Newest first, created_at desc (ops_control.py:954). The chronological order carries meaning, but it only helps someone looking for the most recent event.
- **Columns:** severity, source, event, title, status, occurred (a toLocaleString string)
- **Route cost:** OpsWorkspace route only. It is lazy-loaded (App.tsx:68) and nothing else imports it.

Census reader: The finding task is picking the critical/high events, or the ones still open, out of the latest 250 without paging through seven pages; ordering by severity, status or source does that. No other view lists raw events: Current Severity (OpsWorkspace.tsx:46) only gives counts, and the Alerts tab lists alert events, not raw ones. Two caveats for adoption. First, DataGrid sorts cells as displayed text (DataGrid.tsx:41-43, sortFn_alphanumeric), so 'occurred', as a locale string, will not sort chronologically across dates, and severity sorts alphabetically, not by rank. Second, the unsorted state has to stay newest-first.

Second reader: The verdict holds, but one of its two finding tasks is wrong. rows = events.map(...) (OpsWorkspace.tsx:44). The source is GET /ops/events?limit=250 (opsApi.ts:15). The server allows up to 1000 and returns created_at desc (ops_control.py:942,954). Events are written automatically from many paths: 67 record_ops_event calls in 24 files, including pipeline runs (main.py:1371,1427,1457), action execution (main.py:1654), stream processors (stream_processing.py:961) and ingestion (ingestion_runtime.py:346). The local frontend/playwright-ci-runtime.db already holds 53 ops_events, more than one page of 40. Finding the critical/high/error rows, or one source's rows, is real: Current Severity counts open ALERTS, not events (ops_control.py:920-921). REFUTED PART: 'the ones still open' is not a real task. status defaults to 'OPEN' (ops_control.py:579; OpsEventIngest:179), and no code ever updates OpsEvent.status (the only references are the filters at ops_control.py:905,953), so the column is effectively constant. ADOPTION CAVEATS: severity values are mixed: info, warn, warning, error, medium, high, critical (connectivity.py:652, platform_runtime.py:2729, modelops.py:706). An alphanumeric sort (DataGrid.tsx:43,67) puts critical, error, high first by accident, but splits warn from warning and puts medium after info. 'occurred' is a toLocaleString string, which will not sort chronologically. Route: OpsWorkspace only (lazy, App.tsx:68; no other importer).

## Unclear (9)

Each stays a `DataTable` until the evidence it names is in.

### `App.tsx:1046` — Fetch Evidence (DataOnboarding, /workspace/imports)

**Verdict: unclear**, upheld by the second reader.

- **Rows:** fetchAttempts state, loaded only for the source just previewed (App.tsx:880-887, 938, 941) from GET /connections/sources/{id}/fetch-attempts. The client passes no limit (api/connectorApi.ts:45), so the server default applies (connector_runtime.py:1035-1039). Mapped client-side to seven columns.
- **How many:** Server default of 50 rows (max 500). An attempt is recorded for every preview and every ingestion sync: fetch_records defaults operation to 'sync' (connector_runtime.py:283-290), and ingestion_runtime.py:234 passes operation='sync'. A source that syncs repeatedly can therefore reach 50 rows: 40 on page one and 10 on page two.
- **Arrival order:** Newest first, by created_at then id descending. It is a chronological evidence log, so the order means something.
- **Columns:** status, adapter, operation, records, bytes, duration_ms, error
- **Route cost:** shared closure

Census reader: This is the only App.tsx table with a column a person could plausibly rank to find something: the slowest fetch (duration_ms), the FAILED attempts (status or error), or the largest read (bytes). Once a source is at the 50-row window, a failure in rows 41-50 is on page two. But the panel is shown right after a live preview, where the relevant row is the newest one, and the code does not show anyone diagnosing a source's sync history here. Two things would settle it: (a) the real number of ConnectorFetchAttempt rows per source in a pilot or production database, where routinely 40 or fewer means 'no'; and (b) whether diagnosing a slow or failing sync leads a person to this panel or to ingestion run views. If both point here, sorting by duration_ms or status serves 'find the slow or failed fetches'.

Second reader: Confirmed: listConnectorFetchAttempts passes no limit (connectorApi.ts:44-46), so the server default applies, 50 with a maximum of 500, ordered created_at desc then id desc (connector_runtime.py:1036-1038). fetch_records writes an attempt for every call (290-311). Previews use operation='preview' (1026) and ingestion syncs use operation='sync' (ingestion_runtime.py:231-235), so a sync-heavy source reaches the cap. The source settles half of the census's question (b): App.tsx is the only frontend reader of fetch attempts (a grep of frontend/src finds only App.tsx:37,883,941 and the api and type declarations). The panel is filled only by connectorPreview for the source in the form (App.tsx:880-887, 936-941), which puts a fresh attempt in row 1. New finding: the endpoint returns a bare list with no total, so beyond 50 attempts the table's true-count caption counts only the 50 it was given. Older failures are cut on the server, and no sort could surface them. Still open, and not answerable from code: (a) how many attempts a real source accumulates, where routinely 40 or fewer means 'no'; and (b) whether people come to this panel to diagnose failed or slow syncs rather than just confirming the preview they ran. If both point here, the finding task is 'find the FAILED or slowest fetches in the last 50' (sort by status or duration_ms). Shared closure, so the grid would have to be lazy-loaded.

### `workspaces/ControlPanel.tsx:423` — Groups section > Groups

**Verdict: unclear**, upheld by the second reader.

- **Rows:** groups.value from admin.listGroups -> GET /admin/groups (controlPanelApi.ts:105-107); handler admin_directory.py:299-304, q.all(), no limit
- **How many:** Unbounded server-side. Groups are created one at a time (form at ControlPanel.tsx:363-376, POST handler admin_directory.py:292-296); no bulk or IdP sync path appears in these handlers. Expected tens.
- **Arrival order:** No ORDER BY (database order). Incidental.
- **Columns:** id, organization_id, display_name
- **Route cost:** control-panel route only (lazy chunk, App.tsx:69)

Census reader: Only three name-like columns. Sorting helps only if the list passes one page. Evidence that settles it: group counts in a real deployment, or an IdP/group-sync path that creates groups in bulk. Above 40 groups, sorting by display_name (find a group) or organization_id (see one org's groups) is the task. Below it, the list is scannable as it is.

Second reader: rows = groups.value from GET /admin/groups (controlPanelApi.ts:105-107); handler admin_directory.py:299-304, q.all(), no order, no limit. Columns are id, organization_id, display_name. The source adds two facts, neither decisive. First, no bulk path exists: a grep of oms found AdminGroup written only by create_group (:292-296), and system_hardening.py (snapshot import) mentions no admin_ table, so groups arrive one form submission at a time. Second, choosing a group for membership happens in the Add Member select (:429-435), not in this table. The table's only extra information is organization_id per group. Still unsettled: the group count in a real deployment. Above 40 groups, sorting by display_name or organization_id is a real find task. Below that, the table is scannable. Control-panel route only.

### `workspaces/ControlPanel.tsx:465` — Groups section > Members (of the group chosen in Add Member)

**Verdict: unclear**, upheld by the second reader.

- **Rows:** members.value from admin.listGroupMembers(selectedGroupId) -> GET /admin/groups/{id}/members (controlPanelApi.ts:113-115); handler admin_directory.py:352-360, filter by group_id, .all(), no limit
- **How many:** Unbounded per group; memberships are appended one at a time (admin_directory.py:335-349), with no dedupe or unique constraint visible
- **Arrival order:** No ORDER BY (database order). Incidental.
- **Columns:** user_id (a uuid hex unless an id was supplied, admin_directory.py:192), expiration, expired, manage_permission, manage_membership. There is no username column, so sorting by user_id finds nobody by name.
- **Route cost:** control-panel route only (lazy chunk, App.tsx:69)

Census reader: The useful sorts would be expired (find lapsed memberships) and manage_membership/manage_permission (find who can change this group). They matter only when a group has more than a page of members. Evidence that settles it: real member counts per group. If groups routinely pass 40 members, sort for that access-review task; if not, the rows are short enough to scan.

Second reader: rows = members.value from GET /admin/groups/{id}/members (controlPanelApi.ts:113-115); handler admin_directory.py:352-360, filtered by group_id, .all(), no order, no limit. The response has user_id, expiration, expired, manage_permission, manage_membership, and no name column. GroupMembership has no unique constraint (model :95-103), and add_member (:335-349) always inserts, so duplicate rows can pile up. user_id is a uuid hex unless supplied (:192), so a sort finds no one by name. The useful sorts are expired (lapsed memberships) and manage_membership or manage_permission (who can change the group), plus user_id to put duplicates side by side. All of these matter only when a group has more than 40 members. Unsettled: real member counts per group. Control-panel route only.

### `workspaces/ControlPanel.tsx:873` — Usage section > Quotas

**Verdict: unclear**, upheld by the second reader.

- **Rows:** quotas.value from admin.listQuotas -> GET /admin/usage/quotas (controlPanelApi.ts:367-369); handler admin_usage.py:122-126, .all() filtered in Python to accessible scopes, no limit
- **How many:** Unbounded: roughly scopes (projects plus organizations) x 3 metrics, and createQuota appends without a unique constraint (admin_usage.py:40-47, 116), so duplicates accumulate
- **Arrival order:** No ORDER BY (database order), and the response has no id or created_at. Incidental.
- **Columns:** scope_type, scope_id, metric, limit_value
- **Route cost:** control-panel route only (lazy chunk, App.tsx:69)

Census reader: If the quota count passes a page, sorting by scope_id groups one scope's quotas (and shows duplicates next to each other) and sorting by limit_value compares limits. That is a real task, but it applies only at that size, and the Check Quota panel (ControlPanel.tsx:877-905) already answers the single scope x metric lookup. Evidence that settles it: quota row counts in a deployment, i.e. whether projects x metrics routinely pass 40.

Second reader: rows = quotas.value from GET /admin/usage/quotas (controlPanelApi.ts:367-369). Handler admin_usage.py:122-126 does .all() filtered in Python by accessible scope, with no order and no limit; a principal with '*' sees every quota (tenancy.py:122-123). The response has no id or created_at. UsageQuota has no unique constraint (:40-47) and create_quota always inserts (:109-119), so duplicate scope x metric rows can exist. check_quota picks one with .first() and no order (:135-136), which makes duplicates a real hazard that only a sort by scope_id (or metric) would surface. Size is still unsettled: roughly (projects + organizations) x 3 metrics plus duplicates. Anything past about 13 scopes already exceeds a page, but real scope counts are not in the source. Evidence that settles it: quota row counts in a deployment. Control-panel route only.

### `workspaces/ControlPanel.tsx:1233` — Extensions section > {plugin_id} execution evidence

**Verdict: unclear**, upheld by the second reader.

- **Rows:** executions state, mapped inline at :1233; filled by admin.listPluginExecutions(version.id) -> GET /api/v1/plugins/{id}/executions (controlPanelApi.ts:264-266, no limit passed), with newly queued runs prepended client-side (ControlPanel.tsx:1150)
- **How many:** Server default limit 50 (plugin_runtime.py:897; max 500 but never requested), plus any runs queued in this session, so 50+ at most: up to two pages of 40
- **Arrival order:** created_at desc, id desc (plugin_runtime.py:899), with just-queued runs placed on top. Chronological, and that order carries the page's run-then-verify flow.
- **Columns:** id, job_id, operation, status, duration_ms, sandbox, error, actor, created_at
- **Route cost:** control-panel route only (lazy chunk, App.tsx:69); free in payload terms if another site in this file already adopts the grid

Census reader: Same shape as the job telemetry table: status and duration_ms would let a person find failed or slow runs. But the rows are per plugin version, and the page's own flow ('Run extension' then 'Refresh runs') relies on the newest-first order; a sort would move the just-queued row away from the top. Evidence that settles it: whether execution counts per version in use reach the 50-row cap. If they do, sort (find FAILED runs, slowest duration_ms). If versions usually have a few runs, chronological order is the only one needed.

Second reader: rows come from GET /api/v1/plugins/{id}/executions with no limit passed (controlPanelApi.ts:264-266), so the server default of 50 applies (plugin_runtime.py:897), ordered created_at desc, id desc (:899). Just-queued runs are prepended client-side (ControlPanel.tsx:1150). New from source: executions are created only by POST invoke-async (_queue_plugin_execution :640-660), whose only frontend caller is this panel's Run extension (controlPanelApi.ts:268-272, ControlPanel.tsx:1143), or by the direct POST invoke (:860-870), which has no frontend caller. No pipeline, connector or platform_runtime path creates plugin runs: platform_runtime only syncs status (:2709-2711, :3127-3129), and connector_runtime's 'plugins' are Python registry modules (:161-169). Within the product, rows per version therefore grow one person's click at a time, which argues for short lists. External API callers could still exceed 40. Also corrected: the census said a sort would push the just-queued row off the top, but DataGrid starts unsorted (useTable with no initial sorting, DataGrid.tsx:69), so that happens only after a header click. Evidence that settles it: whether any external client calls /invoke or /invoke-async enough to fill the 50-row cap per version. If so, sort for finding FAILED or slow runs. If not, chronological order is enough. Control-panel route only.

### `workspaces/Security.tsx:738` — Projects & Roles tab > Panel "Project Role Grants" (rendered only after a project is chosen)

**Verdict: unclear**, upheld by the second reader.

- **Rows:** grants.value from listProjectGrants(selectedProject) -> GET /projects/{id}/grants; server returns db.query(RoleGrant).filter(project_id).all() with no order_by and no limit (oms/app/security_access.py:271-276). Each (principal, role) pair is unique (dedup at security_access.py:227-241).
- **How many:** Unbounded by construction: one row per principal-role pair on the chosen project. It grows with the number of users and groups given access.
- **Arrival order:** Database default order. Incidental: neither grouped by role nor newest first.
- **Columns:** id, project_id (constant within the table), principal, role_id, created_at
- **Route cost:** Security route only (lazy chunk, App.tsx:70)

Census reader: This is a "who has access" table. Sorting by role_id would gather every owner, sorting by principal would find one user's grants, and sorting by created_at would find the grant just added. Arrival order supports none of these. The verdict would be settled by the grant count per project in a real deployment. Above 40, rows fall onto later pages in arbitrary order, and auditing role holders needs sort, so the verdict becomes "sort". If projects typically hold a handful of grants, it is "no". Also relevant: whether the per-principal question is already answered by Access Check (Security.tsx:773), which would leave only the by-role audit as a sort task.

Second reader: The census holds up, and the code cannot settle the verdict. The rows are grants.value from listProjectGrants(selectedProject) (L626-629) via GET /projects/{id}/grants, which returns db.query(RoleGrant).filter(project_id).all() with no order_by and no limit (security_access.py:271-276). The only dedup is one row per (principal, role) (security_access.py:227-241). The only code that creates RoleGrant rows is that endpoint (security_access.py:243); no seed creates grants in bulk. So the size is unbounded, and real counts are unknown. Arrival order is incidental. The columns are id, project_id (the same on every row), principal, role_id, created_at (securityApi.ts:173-179). There is a real 'who has access' audit: list every holder of a role, or every grant one principal holds. Access Check (L773-834) cannot answer the by-role question, because it needs a principal and a permission as input and returns only matched_roles. One point against a large table: principals can be groups (the placeholder at L229 shows group:analysts), so a project granted mostly to groups would have few rows. What would settle it: the number of grants per project in a real deployment. Above 40, the list pages in arbitrary order and becomes 'sort' on role_id and principal. With a handful per project, it is 'no'. Route: Security lazy chunk only (App.tsx:70).

### `workspaces/OntologyManager.tsx:442` — Object type surface > Panel "Downstream Contracts {count}" (under the per-status counts strip, L437-441)

**Verdict: unclear**, upheld by the second reader.

- **Rows:** manager.cards.contract_health.rows from GET /ui-state/ontology/object-types/{id} (workspaceState.ts:136). Built at oms/app/ontology_core.py:817-831 from ontology_runtime_v1.contract_binding_health: ACTIVE contract_binding definitions for this object type, order_by(resource_id).all(), no limit (ontology_runtime_v1.py:711-719).
- **How many:** Unbounded by construction: one row per active consumer contract bound to this one object type. Scoped to a single object type, not the project.
- **Arrival order:** By resource_id. Incidental to the status question the panel exists to answer.
- **Columns:** id, consumer_kind, consumer_id, consumer_version, properties (array), status (CURRENT|COMPATIBLE_STALE|BROKEN|UNVERSIONED|NO_ACTIVE_REVISION), compatible, reason, bound_revision_id, active_revision_id
- **Route cost:** OntologyManager route only (lazy chunk, App.tsx:62; ceiling 703,043 B, route-payload-baseline.json:20)

Census reader: There is a concrete finding task. The counts strip announces something like "3 broken", and the person needs to find which consumers those are. Sorting by status puts BROKEN first, since it is alphabetically first. Whether that needs sort depends on size, and the code does not show it. The verdict would be settled by the count of ACTIVE contract_binding rows per object type in real use. If it routinely exceeds a page (40), the BROKEN rows can sit on page 2 behind resource_id order, and the verdict becomes "sort" on status. If it is a handful, the status column is readable at a glance and the verdict is "no". A filter to status (N7c) may serve the task better than sort.

Second reader: I confirmed the rows: manager.cards.contract_health.rows, built at ontology_core.py:817-831 from contract_binding_health. That function runs an ACTIVE contract_binding query filtered to this object type, order_by(resource_id).all(), with no limit (ontology_runtime_v1.py:711-719). The census's bound needs one refinement. bind_ontology_contract archives a consumer's earlier ACTIVE bindings when a new version binds (ontology_runtime_v1.py:858-862), so the table holds at most one row per distinct consumer (kind, id) referencing this type, not one per consumer version. The size is still unbounded, but it grows with the number of consumers, not with releases. The finding task is real. The counts strip above the table (L437-441, counts at runtime_v1:720-723) says how many rows are BROKEN but not which ones, and rows arrive in resource_id order. The five status values sort ascending with BROKEN first. The code does not show how many consumers bind to one object type. What would settle it: the ACTIVE binding count per object type in real use. Above 40, the verdict is 'sort' on status. With a handful, it is 'no', since the status column can be scanned. Route: OntologyManager lazy chunk only (App.tsx:62; ceiling 703,043 B). No other file imports OntologyManager statically.

### `workspaces/OntologyManager.tsx:960` — Panel "Properties {count}" (read mode; edit mode replaces it with the sortable drag list, L879-958)

**Verdict: unclear**, upheld by the second reader.

- **Rows:** manager.cards.properties.rows from GET /ui-state/ontology/object-types/{id}. Built by _property_rows (oms/app/ontology_core.py:460-500, 850): one row per declared property.
- **How many:** Unbounded by construction: one row per property of one object type. Real types can be wide; the N8 fixture has 14 properties (GOAL_HONEST_UI_2026-09-11.md:408-411).
- **Arrival order:** The declared property order (the "order" column, 1..n). A person curates it in edit mode with drag and Up/Down, and it is persisted through reorderOntologyProperties (L866-874, L906-913). The order is meaningful, but it is not the only meaningful order.
- **Columns:** About 21: order, name, api_name, base_type, status, required, display_name, indexed, sensitive, description, minimum, maximum, min_length, max_length, pattern, enum, unit, geometry_type, source, can_edit, can_delete
- **Route cost:** OntologyManager route only (lazy chunk, App.tsx:62)

Census reader: There are real scan-and-compare tasks: which properties are required, sensitive or indexed, which are deprecated, which have a given base_type. Sorting by those columns would gather them. Against that, the arrival order is the curated order that the same panel edits, and a view sort in read mode would show a different order from the one saved (the "order" column would let a person sort back). The verdict would be settled by (a) property counts per object type in real ontologies: above 40, the table pages and scanning for sensitive/required fails, so the verdict becomes "sort"; at about 15 or fewer, the columns are scannable and it is "no"; and (b) whether the grid's header toggle (DataGrid.tsx:118, the library's getToggleSortingHandler) can return to unsorted, so the curated order stays reachable without sorting by "order". Separately from sort, the grid's column hiding would plainly help a 21-column table, but that is outside the owner's sort-only criterion.

Second reader: I confirmed the rows are manager.cards.properties.rows (L828), built by _property_rows (ontology_core.py:460-515, which skips __ keys at L514). There is one row per property, with no cap. The table has about 21 columns, including order, required, indexed, sensitive, status and base_type. Arrival order is the order people curate with drag and Up/Down, and it is saved through reorderOntologyProperties (L862-874, L906-913). The 'order' column would let a person sort back to it. The scan tasks the census names are real: find the required, sensitive, indexed or deprecated properties, or those of one base_type. The code does not settle how many properties a real object type has. Generate From Dataset (L251-256) can turn a wide dataset into a wide type, but nothing caps or measures that. The 14-property fixture the census cites (GOAL doc L408-413) is Object Explorer's, not evidence about this panel. I could not confirm from the installed @tanstack build whether a header click returns to unsorted. The only hit is a SKILL.md example that sets enableSortingRemoval: false, which hints that removal is on by default but does not prove it. DataGrid.tsx:118 wires getToggleSortingHandler with no sort options set (L38-45, L69). What would settle it: property counts per object type in real ontologies. Above 40, the verdict is 'sort' on required, sensitive, status or base_type. At about 15 or fewer, it is 'no'. The toggle behaviour should also be checked in the built grid. Route: OntologyManager lazy chunk only.

### `workspaces/PipelineBuilder.tsx:566` — Execution > details 'Partition jobs ({n})' (output pane)

**Verdict: unclear**, upheld by the second reader.

- **Rows:** executionJob.dependencies mapped to {partition, job, type, status}. The field comes from GET /jobs/{id} -> _job_dict (platform_runtime.py:2899-2901) -> _dependency_rows (platform_runtime.py:2744-2752), which keeps the depends_on order. For a partitioned DuckDB run those dependencies are the child partition jobs created one per file group (data_plane.py:633-661).
- **How many:** Bounded by construction: partition_count = min(max(2, max_partitions), snapshot file count) (data_plane.py:601). max_partitions is limited to 2..100 on the server (data_plane.py:101) and clamped to the same range on the client (PipelineBuilder.tsx:537); the client default is 8 (PipelineBuilder.tsx:127). So 2-8 rows by default, 100 at most, fewer when the snapshot has fewer files.
- **Arrival order:** Partition index order, preserved by _dependency_rows, so the synthesized 'partition' column (index+1) is truthful. The order is meaningful, not incidental.
- **Columns:** partition, job (id), type, status
- **Route cost:** PipelineBuilder only. PipelineBuilder.tsx is its own dynamic entry (manifest.json:263-276), so a grid imported in this file lands in the PipelineBuilder chunk.

Census reader: There is one concrete finding task: after a failed or stalled partitioned run, find which partitions are FAILED, BLOCKED or still RUNNING. At the default of 8 rows a person reads that at a glance, and partition order is already meaningful. At 100 partitions with 40-row paging, a failed partition can sit on page 3, and sorting by status would bring it forward. What settles it: the partition_count recorded on real partitioned executions (partition_execution.partition_count, data_plane.py:658-664). If runs routinely exceed about 40 partitions, the verdict is sort; if they stay near the default of 8, no. A status count in the summary could serve the same task without the grid.

Second reader: Stays unclear, with corrections and new evidence.

Size. data_plane.py:101 defaults max_partitions to 16, not 8, but that default never applies from this screen. The UI always sends its own value (PipelineBuilder.tsx:222): default 8 (line 127), clamped to 2..100 (line 537). partition_count = min(max(2, max_partitions), snapshot file count) (data_plane.py:601-602), and the file list comes from the snapshot manifest with no cap (data_plane.py:584-587). The binding limit is therefore the user's setting: 8 rows by default, 100 at most.

Order. The finalizer's depends_on is child_ids in partition index order (data_plane.py:657, 690), and _dependency_rows keeps that order (platform_runtime.py:2744-2752), so the synthesized partition number is truthful.

The finding task is real, and failures can land anywhere in the list. The census missed two things. When the browser drives the run, shards go one at a time and stop at the first failure (PipelineBuilder.tsx:232-249), so statuses read SUCCEEDED..., then one FAILED, then QUEUED..., and the failure sits at that boundary. But worker daemons also claim pipeline.duckdb.partition jobs (worker_daemon.py:21-22, 212-214), and each partition allows 3 attempts (data_plane.py:651). Under workers, FAILED or RUNNING rows can be scattered.

What settles it: the partition_count recorded on real finalizer payloads (partition_execution, data_plane.py:658-664, 684), and whether deployments run workers with pipeline.duckdb.partition in WORKER_JOB_TYPES. If runs exceed about 40 partitions under parallel workers, the verdict is sort (sort by status to find FAILED or BLOCKED shards past the first 40-row page). At the default of 8, it is no.

Route: PipelineBuilder only (manifest.json:263-276).

## Verdicts the second reader changed to no (4)

### `App.tsx:1094` — Docs Matrix (ValidationWorkspace, /workspace/validation)

**Verdict: no**, changed from unclear by the second reader.

- **Rows:** filteredRows. It is validationUi.value.rows from GET /ui-state/validation, returned at system_hardening.py:2337, then filtered client-side by the status select (App.tsx:1066-1067, 1086-1093). Server-side, _docs_matrix_rows parses the markdown table foundry-docs/VALIDATION_MATRIX.md (system_hardening.py:1716-1737). The file itself was not opened, per instruction.
- **How many:** One row per 7-cell line in the matrix file, so it only changes when the document is edited. docs/GOAL_2026-08-03.md:242 records 72 rows. Unfiltered, that is more than one 40-row page.
- **Arrival order:** The order of lines in the document. Whether that already groups rows by domain or priority is not visible from code.
- **Columns:** domain, source, behavior, evidence, status, gap, priority
- **Route cost:** shared closure

Census reader: This is the one App.tsx table that consistently spans two pages, and it has columns a reviewer might order by (priority, domain). The existing controls already cover the main finding task: the status filter, plus the 'Required gaps' section card listing P0/P1 rows that are PARTIAL or MISSING (system_hardening.py:2281, 2306-2314). That same GOAL_2026-08-03 line recorded zero PARTIAL and zero MISSING. Two things would settle it: (a) whether the matrix file is already ordered by domain and priority, which requires reading foundry-docs/VALIDATION_MATRIX.md (excluded from this census); and (b) whether anyone reviews the matrix by priority (for example 'every P0 row, whatever its status'), which neither the filter nor the gaps card serves. If (b) holds and (a) does not, sorting by priority serves that review. Since this view lives in App.tsx, the grid would have to be loaded on demand.

Second reader: filteredRows (App.tsx:1066-1067) is validationUi rows (system_hardening.py:2337) filtered by the status select (App.tsx:1086-1093). _docs_matrix_rows parses the 7-cell lines of a document (system_hardening.py:1716-1737), so the size is bounded by that document: 72 rows as of docs/GOAL_2026-08-03.md:213,242. There is no server limit. The census's open question (b), whether anyone reviews by priority, is answered in the source: the repo's documented priority review is P0/P1 conformance (GOAL_2026-08-03.md:110-113). That review is served by the CLI (oms/validate_docs_conformance.py:68-85, P0 rows that do not conform) and by the 'Required gaps' section card (system_hardening.py:2281, 2306-2314, P0/P1 rows that are PARTIAL or MISSING, also surfaced as warnings at 2333-2336). Status-based finding is served by the filter. No code or doc describes a 'browse every P0 row' or 'group by domain' task, and a 'sort' verdict has to name a real one. It is a document-bounded reference matrix with status filtering and a gaps summary, so 'no'. It should reopen only if someone documents a review by priority or domain that the gaps card does not cover. The file's line order could not be checked, because foundry-docs is excluded. Shared closure.

### `workspaces/Security.tsx:432` — Classification / CBAC tab > Panel "Classifications"

**Verdict: no**, changed from unclear by the second reader.

- **Rows:** classifications.value from listClassifications() -> GET /classification/classifications; server returns db.query(ClsClassification).all() with no order_by and no limit (oms/app/classification_ops.py:225-227). Rows come from manual Apply Classification (classification_ops.py:207) and from a derive path that writes derived=True (classification_ops.py:297-298).
- **How many:** Unbounded by construction: one row per classified file, data or project resource, plus derived rows. The UI shows only the first 40 per page.
- **Arrival order:** Database default order. It is incidental: not newest first and not grouped by level or kind.
- **Columns:** id, scheme_id, kind (file|data|project), level, categories (array), derived (bool), created_at
- **Route cost:** Security route only (lazy chunk, App.tsx:70)

Census reader: If the table grows past one page, it has plausible finding tasks. Sorting by level would find every top_secret resource, sorting by derived would separate inherited rows from applied ones, and sorting by created_at would find the one just applied, since arrival order is not newest first. One caveat: the grid's alphanumeric sort orders levels lexically, not by the scheme's level order. The verdict would be settled by (a) the row count of /classification/classifications in a seeded or real deployment, where more than 40 rows makes arrival order hide rows, and (b) whether anyone does the "list resources at level X" task here, rather than per resource through Check Access (Security.tsx:566). With the row count above 40, this becomes "sort" on level/kind/derived; with it below roughly 15, "no".

Second reader: The census's main finding task is not real. It says sorting by level would find every top_secret resource, but a classification row does not name a resource. The ClsClassification model holds only id, scheme_id, kind, level, categories, derived, created_at (classification_ops.py:57-66, which the TS type at securityApi.ts:86-94 mirrors), and Apply Classification sends no resource id (Security.tsx:484-489, classification_ops.py:216-217). Sorting by level or kind would therefore group unattached labels identified only by uuid, and could not tell anyone which file, dataset or project is top_secret. The one thing a person does with a classification on this tab is pick it in the Check Access select. That select already lists every row as kind:level (id) (L572-578) and does not depend on table order. The derived=True rows come only from POST /classification/compute-data (classification_ops.py:277-304), and nothing on this screen calls that endpoint. So 'separate derived from applied' has no follow-on action here. What remains is 'find the one just applied', which the Classifications metric beside the table covers (L385). The list is unbounded by construction (GET returns .all() with no order_by or limit, classification_ops.py:225-227), but no scan-and-compare task exists over it. Reopen this only if the model gains a resource reference column. Route: Security lazy chunk only (App.tsx:70).

### `workspaces/Vertex.tsx:440` — Nodes (n)

**Verdict: no**, changed from unclear by the second reader.

- **Rows:** toGraphNodes(graph) (Vertex.tsx:72-80). The graph comes from GET /vertex/graphs/{id} or the explore/filter/merge responses (vertexApi.ts:151-161).
- **How many:** Unbounded. Explore does BFS up to depth 6 over all LinkInstance rows, optionally one link type, with no node cap (vertex_ops.py:404-444). Realistic size depends on project link density and is not established.
- **Arrival order:** Node list order: seeds first, then nodes added by expansion. Somewhat meaningful, not strictly required.
- **Columns:** id, type, label (type: id, redundant), is_seed, faded
- **Route cost:** Vertex route only (App.tsx:73, lazy).

Census reader: If graphs routinely pass 40 nodes, there is a real finding task: after 'Apply filter', sorting by faded brings the matched nodes together, and sorting by type groups nodes by object type. What would settle it: node counts of graphs people actually build (fixtures, or the Vertex graphs table in a used database). If they usually fit on one page, this is 'no'. The graph canvas also already fades non-matching nodes (MiniGraph, Vertex.tsx:330).

Second reader: Resolved with the evidence the census asked for. Every local database has an empty vtx_graphs table (oms.db, oms/oms.db, frontend/oms.db, ontology-studio-dev.db, frontend/playwright.db, frontend/playwright-ci-runtime.db, oms/ci-local-validation.db), and none holds more than 8 object_instances or 5 link_instances. Any graph built on them is at most 8 nodes, one page. Explore is not bounded by construction (vertex_ops.py:404-446 scans all links with no node cap), so revisit only if link-dense projects appear. The finding task is weak regardless. Node rows carry no properties (Vertex.tsx:72-80), so sorting cannot show the value a filter matched. Filter only sets faded (vertex_ops.py:795-798), which the canvas already renders (Vertex.tsx:330). label just repeats type:id.

### `workspaces/Vertex.tsx:443` — Edges (n)

**Verdict: no**, changed from unclear by the second reader.

- **Rows:** toGraphEdges(graph) (Vertex.tsx:82-91), from the same graph payloads as the nodes table. count and weight are filled only after 'Merge links' (merged_count/merged_weight).
- **How many:** Unbounded before a merge: one row per traversed LinkInstance, no cap (vertex_ops.py:413-440). After a merge it shrinks to one row per group.
- **Arrival order:** Edge map insertion order from BFS, so incidental.
- **Columns:** id, source, target, link_type_id, count, weight
- **Route cost:** Vertex route only (App.tsx:73, lazy).

Census reader: There is a candidate finding task: after a merge, rank edges by count or weight to find the strongest aggregated links. But a merge is exactly what shrinks the edge list, and before a merge count and weight are empty. What would settle it: whether merged graphs in real use still have more than 40 edge rows, and whether anyone ranks by merged_weight or merged_count. If merged sets fit on one page, this is 'no'.

Second reader: Resolved. No local database holds more than 5 link_instances or any vtx_graphs, so no real edge list reaches one page. count and weight are filled only by merge_links (Vertex.tsx:88-89; vertex_ops.py:729,737), which replaces the edge list with passthrough edges plus one edge per group (vertex_ops.py:711-747). The only ranking task (strongest merged links) therefore exists only on the shrunken list. Before a merge the rows are opaque ids in BFS insertion order (vertex_ops.py:433-446).

## Every site (73)

| Site | Panel | How many rows | Verdict | Why |
| --- | --- | --- | --- | --- |
| `App.tsx:358` | Developer evidence: readiness checks (BackendConnection banner in the app shell, App.tsx:356-361) | Fixed at 7 rows by construction: schema, migrations, events, snapshot, docs, routes, plugin_execution. | no | Seven fixed rows in a collapsed developer-evidence block. |
| `App.tsx:359` | Developer evidence: readiness checks (BackendConnection banner in the app shell, App.tsx:356-361) | 1 to 7 rows: at most one per readiness check. | no | A short derived summary of at most 7 rows, with no numeric or status column to rank. |
| `App.tsx:767` | High-Risk Assets (CommandCenter, /workspace/command-center) | No server limit. _risk_findings loads every ObjectInstance of type 'asset' (817) and keeps those scored high or critical (853-856), so size is bounded only by how many asset objects are in the database. | no | The one ordering a person needs here, worst risk first, is already applied by the server. |
| `App.tsx:991` | Mapping Suggestions (DataOnboarding, /workspace/imports) | Exactly 9 rows, because the caller always asks for the asset template, which declares 9 fields (imports_ops.py:129-139). | no | A fixed set of 9 rows seen at once. |
| `App.tsx:1030` | Live Connector (DataOnboarding, /workspace/imports) | At most 25 rows. | no | At most 25 rows. |
| `App.tsx:1043` | Connector Adapters (DataOnboarding, /workspace/imports) | About 5 rows. | no | A small catalog, effectively constant, and fully visible. |
| `App.tsx:1046` | Fetch Evidence (DataOnboarding, /workspace/imports) | Server default of 50 rows (max 500). | unclear | This is the only App.tsx table with a column a person could plausibly rank to find something: the slowest fetch (duration_ms), the FAILED attempts (status or error), or the largest read (bytes). |
| `App.tsx:1050` | Sample Templates (DataOnboarding, /workspace/imports) | Exactly 4 rows, one per template: asset, work_order, sensor_reading, facility (imports_ops.py:124-190). | no | Four constant reference rows. |
| `App.tsx:1053` | Recent Import Jobs (DataOnboarding, /workspace/imports) | Server default of 50 rows (max 500), so at most 2 pages. | no | The only list-wide task sorting could serve is grouping by status to find broken imports, and the same screen already does that. |
| `App.tsx:1084` | Project Readiness (ValidationWorkspace, /workspace/validation) | Fixed at 7 rows by construction. | no | Seven fixed rows, all visible at once. |
| `App.tsx:1094` | Docs Matrix (ValidationWorkspace, /workspace/validation) | One row per 7-cell line in the matrix file, so it only changes when the document is edited. docs/GOAL_2026-08-03.md:242 records 72 rows. | no (changed) | filteredRows (App.tsx:1066-1067) is validationUi rows (system_hardening.py:2337) filtered by the status select (App.tsx:1086-1093). _docs_matrix_rows parses the 7-cell lines of a document (system_hardening.py:1716-1737), so the size is bounded by that document: 72 rows as of docs/GOAL_2026-08-03.md:213,242. |
| `App.tsx:1098` | Developer evidence: UI endpoint inventory (ValidationWorkspace, /workspace/validation) | Fixed at 11 rows by construction. | no | An 11-row constant reference table in a collapsed developer-evidence block. |
| `App.tsx:1114` | CSV Import and Transform, ImportJobSummary (DataOnboarding, /workspace/imports; component at App.tsx:1104-1116) | Always empty in practice, since the key is never present. | no | A small, per-job diagnostic list of about 12 rows or fewer, which nobody would sort. |
| `workspaces/ControlPanel.tsx:206` | Organizations section > Enrollments | Unbounded server-side, small by nature: an enrollment is the top of the enrollment > organization > space > project hierarchy (admin_directory.py:386-409), typically one or a handful | no | A handful of top-level rows with two name-like columns. |
| `workspaces/ControlPanel.tsx:231` | Organizations section > Organizations | Unbounded server-side, small by nature: organizations sit under an enrollment, typically a few | no | Few hierarchy containers, three identifier and name columns, no metric or status to order by. |
| `workspaces/ControlPanel.tsx:235` | Organizations section > Spaces | Unbounded server-side; spaces are coarse containers between organization and project, expected to be few per organization | no | A short list of containers with three identifier columns and nothing comparative. |
| `workspaces/ControlPanel.tsx:333` | Users section > Users | Unbounded: one row per human account, never deleted (status flips to inactive, admin_directory.py:277-289). | sort | Finding task: locate one account by username, or gather every inactive account, in a list that arrives in arbitrary order and is paged by 40 with no search. |
| `workspaces/ControlPanel.tsx:423` | Groups section > Groups | Unbounded server-side. | unclear | Only three name-like columns. |
| `workspaces/ControlPanel.tsx:465` | Groups section > Members (of the group chosen in Add Member) | Unbounded per group; memberships are appended one at a time (admin_directory.py:335-349), with no dedupe or unique constraint visible | unclear | The useful sorts would be expired (find lapsed memberships) and manage_membership/manage_permission (find who can change this group). |
| `workspaces/ControlPanel.tsx:571` | Roles section > Role Grants | Unbounded: one row per principal x scope x role, appended on every grant with no dedupe (admin_directory.py:363-374). | sort | Finding task, an access review: who holds administrator or owner (sort by role), and everything one principal holds (sort by principal_id) or everything granted at one scope (sort by scope_id). |
| `workspaces/ControlPanel.tsx:713` | Auth section > Auth Providers | Unbounded server-side, small by nature: SAML/OIDC identity providers (protocol is restricted to saml or oidc, admin_auth.py:116), a handful per deployment | no | A handful of configuration rows that can be read at a glance. |
| `workspaces/ControlPanel.tsx:739` | Auth section > Service Accounts | Unbounded server-side; in practice one machine identity per worker or integration, created one at a time (ControlPanel.tsx:645-659) | no | A small registry with three identifier columns and nothing to compare. |
| `workspaces/ControlPanel.tsx:742` | Auth section > API Tokens | Unbounded and monotonic: every issuance adds a row (admin_auth.py:206-221, 'Issue once' at ControlPanel.tsx:724), and revoke only sets revoked=True (admin_auth.py:245-252), so rows are never removed. | sort | Finding task: choose which tokens to revoke. |
| `workspaces/ControlPanel.tsx:746` | Auth section > OAuth Clients | Unbounded server-side, small by nature: registered applications, and clients can be deleted (admin_auth.py:293) | no | A few application registrations. |
| `workspaces/ControlPanel.tsx:842` | Usage section > Usage Summary | A derived summary: one row per distinct key of the chosen group_by. 3 rows for metric; the number of accessible projects, principals or organizations; potentially many for resource. | no | The rows already arrive in the order the finding task needs (largest usage first). |
| `workspaces/ControlPanel.tsx:873` | Usage section > Quotas | Unbounded: roughly scopes (projects plus organizations) x 3 metrics, and createQuota appends without a unique constraint (admin_usage.py:40-47, 116), so duplicates accumulate | unclear | If the quota count passes a page, sorting by scope_id groups one scope's quotas (and shows duplicates next to each other) and sorting by limit_value compares limits. |
| `workspaces/ControlPanel.tsx:1016` | Recovery section > Recovery Validation (credential rebinds) | Derived from the loaded snapshot: one row per credential-bearing resource (webhook listeners with secrets, redacted connection sources, webhook credentials, outbound apps). | no | A to-do list of credentials to recreate after restore, meant to be worked through completely rather than searched. |
| `workspaces/ControlPanel.tsx:1211` | Extensions section > Active Extensions | At most one ACTIVE version per plugin_id per project, because activation marks earlier ACTIVE versions SUPERSEDED (plugin_runtime.py:490-492). | no | One row per installed extension, already ordered by kind and then name. |
| `workspaces/ControlPanel.tsx:1233` | Extensions section > {plugin_id} execution evidence | Server default limit 50 (plugin_runtime.py:897; max 500 but never requested), plus any runs queued in this session, so 50+ at most: up to two pages of 40 | unclear | Same shape as the job telemetry table: status and duration_ms would let a person find failed or slow runs. |
| `workspaces/ControlPanel.tsx:1423` | Runtime section > Durable Job Telemetry | Capped at 50 by the client's limit=50 (server allows 1-500). | sort | Finding task: the metrics directly above report P95 execution, P95 queue and estimated cost (ControlPanel.tsx:1362-1364). |
| `workspaces/ControlPanel.tsx:1452` | Runtime section > Queue Policy | 0 or 1 row: RuntimeQueuePolicy.project_id is unique (worker_control.py:51) and the query filters by it. | no | Bounded to one row by a unique constraint. |
| `workspaces/ControlPanel.tsx:1463` | Runtime section > Project Budgets | At most 5 rows: unique (project_id, metric) (runtime_observability.py:54), with metric restricted to five values (:100); upsert replaces rather than appends (:344-350) | no | At most five rows, one per metric, already in metric order. |
| `workspaces/Security.tsx:167` | Markings tab > Panel "Markings" (beside "Create Marking" form) | Not capped by the server. | no | A small, hand-authored catalog, shown as a companion to a create form, and already newest first. |
| `workspaces/Security.tsx:389` | Classification / CBAC tab > Panel "Classification Schemes" | Not capped by the server, but realistically a few rows: one per classification regime (the test seeds a single "US Gov" scheme, oms/test_classification_ops.py:34). | no | A handful of reference definitions. |
| `workspaces/Security.tsx:432` | Classification / CBAC tab > Panel "Classifications" | Unbounded by construction: one row per classified file, data or project resource, plus derived rows. | no (changed) | The census's main finding task is not real. |
| `workspaces/Security.tsx:659` | Projects & Roles tab > Panel "Projects" (beside "Create Project" form) | Not capped by the server. | no | A companion to the Create Project form, already newest first. |
| `workspaces/Security.tsx:695` | Projects & Roles tab > Panel "Roles" | Not capped by the server, but a role catalog is a few rows (the form's default is viewer/editor/owner, Security.tsx:632). | no | A small role catalog. |
| `workspaces/Security.tsx:738` | Projects & Roles tab > Panel "Project Role Grants" (rendered only after a project is chosen) | Unbounded by construction: one row per principal-role pair on the chosen project. | unclear | This is a "who has access" table. |
| `workspaces/Security.tsx:883` | Cipher tab > Panel "Cipher Channels" | Not capped by the server, but realistically a few rows: one per key/sensitivity class. | no | A few configuration records, used mainly as a reference for the selects below them. |
| `workspaces/OntologyManager.tsx:442` | Object type surface > Panel "Downstream Contracts {count}" (under the per-status counts strip, L437-441) | Unbounded by construction: one row per active consumer contract bound to this one object type. | unclear | There is a concrete finding task. |
| `workspaces/OntologyManager.tsx:445` | Object type surface > Panel "Dependents {count}" | Not capped, but small: the number of pipeline nodes that write this object type. | no | A short list of the pipelines that feed the object type. |
| `workspaces/OntologyManager.tsx:449` | Object type surface > Panel "{section title} Detail" / "Selected Section" (under a KeyValueGrid of the section summary) | Varies by section. | no | A polymorphic detail view. |
| `workspaces/OntologyManager.tsx:452` | Object type surface > Panel "Datasources and Health" | Small in practice: the datasets that back one object type, typically 1 to 3. | no | A few rows describing where the object type's data comes from. |
| `workspaces/OntologyManager.tsx:632` | Panel "Dataset to Ontology Mapping" > validation findings (rendered only when errors or warnings exist) | Bounded by construction. | no | The arrival order already carries the meaning: the blocking errors that disable Save come first, and non-blocking warnings follow. |
| `workspaces/OntologyManager.tsx:633` | Panel "Dataset to Ontology Mapping" > details "Hydrated object preview · {n} rows" | At most 20 rows by construction, under one page. | no | A 20-row sample that shows what hydration will produce. |
| `workspaces/OntologyManager.tsx:960` | Panel "Properties {count}" (read mode; edit mode replaces it with the sortable drag list, L879-958) | Unbounded by construction: one row per property of one object type. | unclear | There are real scan-and-compare tasks: which properties are required, sensitive or indexed, which are deprecated, which have a given base_type. |
| `workspaces/OntologyRegistryPanel.tsx:183` | Schema Registry (section schema_registry of Ontology Manager) > Panel "Semantic Compatibility" | Unbounded by construction and project-wide. | sort | The finding task is to find every BREAKING change before ticking "Acknowledge breaking changes" and pressing "Publish registry" (L157-158). |
| `workspaces/Delivery.tsx:258` | Products {n} (Products section) | Unbounded by construction and by server (no limit). | no | A small catalog people curate by hand, already newest first. |
| `workspaces/Delivery.tsx:309` | Marketplace {n} (Marketplace section) | Unbounded by construction; one row per product, so the same realistic size as the Products table (tens at most) | no | Same small hand-curated set as the Products table. |
| `workspaces/Delivery.tsx:531` | Repositories {n} (Code section) | Unbounded by construction; repositories are made by hand in Create Repository, so realistically small | no | Small hand-made set; the columns are near-constant attributes (language, template, branch) nobody ranks by. |
| `workspaces/Delivery.tsx:534` | Workbooks {n} (Code section) | Unbounded by construction; workbooks are made by hand, so realistically small | no | Small hand-made set with nothing to rank; node count is not a lookup key. |
| `workspaces/Delivery.tsx:568` | Compute Modules {n} | Unbounded by construction; modules are registered by hand in Create Compute Module, so realistically small | no | Small registry. |
| `workspaces/Delivery.tsx:573` | Compute Modules {n}: run result, shown under the module table after Run module | Bounded by construction: exactly 2 rows (one per op in the constant spec) | no | Two fixed rows in pipeline order; sorting would break the step-to-step reading. |
| `workspaces/PipelineBuilder.tsx:566` | Execution > details 'Partition jobs ({n})' (output pane) | Bounded by construction: partition_count = min(max(2, max_partitions), snapshot file count) (data_plane.py:601). max_partitions is limited to 2..100 on the server (data_plane.py:101) and clamped to the same range on the client (PipelineBuilder.tsx:537); the client default is 8 (PipelineBuilder.tsx:127). | unclear | There is one concrete finding task: after a failed or stalled partitioned run, find which partitions are FAILED, BLOCKED or still RUNNING. |
| `workspaces/PipelineBuilder.tsx:578` | Execution > details 'Execution events' (collapsed) | Unbounded by construction (no limit), but realistically small: one job gets queued, claimed, a couple of progress events (pipeline_builder_ops.py:2185-2201), succeeded or failed, plus retry or dependency events. | no | A short per-job chronological feed whose only meaningful order is the one it arrives in. |
| `workspaces/PipelineBuilder.tsx:611` | Selected Node > details 'Field lineage' (collapsed) | Unbounded by construction: one row per output column of the node, so as many rows as the dataset is wide. | no | 'operation' is identical on every row and 'origins' is a stringified array, so the only column a person would order by is field. |
| `workspaces/PipelineBuilder.tsx:701` | Selected Node > Ontology contract > details '{n} contract issues' (OntologyContractPanel) | Cut to at most 25 rows at the call site, out of an issues list that can exceed 100 (up to 100 violations times errors per violation). | sort (changed) | The source settles the census's condition (b). |
| `workspaces/PipelineBuilder.tsx:702` | Ontology contract > details 'Mapped field lineage ({n})' (collapsed) | Bounded by the number of properties the ontology output maps, which is bounded by the object type's properties. | no | A mapping list someone reads to check where one property comes from. |
| `components/canvas/PipelineCanvas.tsx:263` | BottomDrawer, tab 'selection preview' (drawer-split beside the node KeyValueGrid) | Unbounded by construction: one row per output column (_schema scans the first 200 sample rows). | no | A column-schema list. |
| `components/canvas/PipelineCanvas.tsx:266` | BottomDrawer, tabs preview / transformations / suggestions / pipeline warnings | preview: at most 5 rows by construction, out of a row_count that can be far larger. transformations: one row per config key (a handful). suggestions: at most 3 fixed entries plus one per validation error on this node. warnings: bounded by graph size (a few). | no | All four sources are short. |
| `workspaces/AgentRuntimePanel.tsx:188` | Agent runtime > Task graph | Bounded by construction: 1 context + selected tools + 1 synthesis. | no | A short pipeline of stages whose execution order is what a person reads: context runs first, tools depend on it, synthesis depends on the tools. |
| `workspaces/OpsWorkspace.tsx:46` | Live Operational Feed (Command Center tab) | Capped at 250 rows by the client limit. | sort | The finding task is picking the critical/high events, or the ones still open, out of the latest 250 without paging through seven pages; ordering by severity, status or source does that. |
| `workspaces/OpsWorkspace.tsx:64` | Latest Data Contract Runs (Reliability tab) | At most 8 rows by construction: latest_contract_runs[:8] (reliability_ops.py:654), taken from a limit(25) query (reliability_ops.py:633). | no | At most 8 rows, always on one page. |
| `workspaces/Automate.tsx:289` | Conditions and Effects: Conditions | No hard cap, but it holds the conditions configured on a single automation, which is a handful in practice. | no | This is a small per-automation configuration list, read in full, not searched. |
| `workspaces/Automate.tsx:291` | Conditions and Effects: Effects | No hard cap, but it holds the effects configured on a single automation, which is a handful in practice. | no | The rows arrive in execution order, the one order that matters for effects, and there are few of them. |
| `workspaces/Automate.tsx:328` | Activity | Unbounded, but it grows only on actions. | no | Order is the meaning of an audit feed, and the only other useful column, event type, has few values. |
| `workspaces/DecisionWorkspace.tsx:123` | Object Explanation (Explain Object tab) | One row per matched rule or scorecard feature for one object (decision_intelligence.py:628-655), so it is bounded by the object type's rule catalog. | no | Just a few rows for one object, one page. |
| `workspaces/DecisionWorkspace.tsx:138` | Before / After Impact (Scenario Simulator tab) | 0 or 1 row by construction. | no | This UI can only produce at most one row. |
| `workspaces/ModelOps.tsx:243` | Latest Drift Evidence (Monitoring tab) | One row per monitored field that is present in both profiles (modelops.py:345-348). | no | Few rows, one page. |
| `workspaces/ModelOps.tsx:249` | Predictions (Inference Playground tab) | One output per input record (test_modeling_io.py:163), and the input records are typed one at a time into the form (ModelOps.tsx:249, 'Add record'), so a handful. | no | A few hand-entered rows whose order ties each prediction to its input record. |
| `workspaces/Vertex.tsx:440` | Nodes (n) | Unbounded. | no (changed) | Resolved with the evidence the census asked for. |
| `workspaces/Vertex.tsx:443` | Edges (n) | Unbounded before a merge: one row per traversed LinkInstance, no cap (vertex_ops.py:413-440). | no (changed) | Resolved. |
| `workspaces/DataMedia.tsx:226` | Schema (n) | One row per column of the selected dataset, bounded by its column count, typically one page. | no | This is a definitional list in the dataset's own column order, usually one page, and the source column never varies. |

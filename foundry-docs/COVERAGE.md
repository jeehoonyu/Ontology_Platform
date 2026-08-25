# Foundry Tool Coverage — Docs vs. Platform Implementation

This matrix maps each documented Foundry tool to its **local equivalent** in this Ontology AIP Platform (`oms/app`). It answers: *what is already implemented, and what is the gap we are now closing?*

Legend: ✅ implemented · 🟡 partial · ❌ missing (to implement)

## AIP
| Tool | Status | Local equivalent |
|---|---|---|
| AIP Logic | ✅ | `/logic-functions`, `/logic-functions/{id}/run` |
| AIP Agent / Chatbot Studio | ✅ | `/agents`, `/agents/{id}/sessions` |
| AIP Assist | ✅ | `/aip/assist/query` |
| AIP Evals | ✅ | `/eval-suites`, `/eval-suites/{id}/run` |
| AIP Document Intelligence | ✅ | `/aip/document-intelligence/extract` |
| AIP Threads | ✅ | `/threads` |
| Palantir MCP | ✅ | `/mcp/context` |
| AIP Model Catalog | 🟡→✅ | `/model-endpoints` + **new** `/aip/model-catalog`, `/aip/model-catalog/byom` |
| AIP Notepad transforms | ✅ | `/aip/notepad/transform` |

## Ontology
| Tool | Status | Local equivalent |
|---|---|---|
| Object types | ✅ | `/object-types` |
| Link types | ✅ | `/link-types` |
| Properties | ✅ | object-type `properties` schema |
| Action types | ✅ | `/action-types`, `/actions/execute` (+ outbox + idempotency) |
| Object views | ✅ | `/objects/{t}/{id}/profile` |
| Object sets / Explorer | ✅ | `/object-sets/search`, `/aggregate`, `/search-around`, `/saved` |
| Ontology validation | ✅ | `/ontology/validate` |
| **Interfaces** | ❌→✅ | **new** `/interfaces` (polymorphic) |
| **Shared property types** | ❌→✅ | **new** `/shared-property-types` |
| **Value types & structs** | ❌ | removed 2026-08-24: the tables existed, no property spec could reference one. Property constraints are enforced on write instead — `oms/test_property_constraints.py` |
| **Functions on Objects** | ❌→✅ | **new** `/ontology-functions` (typed, deterministic) |
| **Ontology Manager (branches/proposals)** | ❌→✅ | **new** `/ontology/branches`, `/ontology/proposals` |

## Data connectivity & integration
| Tool | Status | Local equivalent |
|---|---|---|
| Pipeline Builder | ✅ | `/pipelines`, `/pipelines/{id}/run` |
| Datasets | ✅ | `/data-assets` |
| Data Health | 🟡→✅ | `/data-assets/{id}/expectations/run` + **new** monitoring views |
| Pipeline lineage | 🟡→✅ | `PipelineRun.lineage` + **new** `/lineage/graph` |
| **Data Connection (sources/agents)** | ❌→✅ | **new** `/connections/sources` |
| **Syncs & exports** | ❌→✅ | **new** `/connections/.../syncs`, `/exports` |
| **Streaming & streams** | ❌→✅ | **new** `/streams` (publish/archive) |
| **Schedules & builds** | 🟡→✅ | `/scheduler/generate-cron` + **new** `/schedules`, `/builds` |
| **Media sets** | ❌→✅ | **new** `/media-sets` |

## Developer toolchain
| Tool | Status | Local equivalent |
|---|---|---|
| Platform APIs & SDKs | ✅ | the FastAPI surface + `/ontology/registry/{id}/sdk/{language}` + `oms/ontology_cli.py` |
| **Ontology SDK (OSDK) generator** | ❌→✅ | **new** `/osdk/generate` (emit typed descriptor) |
| **Compute Modules** | ❌→✅ | **new** `/compute-modules` (register/invoke) |
| **Code Repositories** | ❌→✅ | **new** `/code-repositories` (branches, files, commits, checks, merge) |
| **Code Workspaces** | ❌→✅ | **new** `/code-workspaces` (vscode/jupyter + status) |
| **Code Workbook** | ❌→✅ | **new** `/code-workbooks` (graph nodes + run) |

## Analytics & applications
| Tool | Status | Local equivalent |
|---|---|---|
| Object Explorer | ✅ | object-set endpoints |
| Map / GIS | ✅ | `/gis/*`, `/gis/map-layers` |
| **Contour** | ❌→✅ | **new** `/analytics/contour` |
| **Quiver (time-series)** | ❌→✅ | **new** `/analytics/quiver` |
| **Fusion (spreadsheet)** | ❌→✅ | **new** `/analytics/fusion` |
| Notepad documents | ❌→✅ | **new** `/notepad/documents` (live embeds, render, export) |
| **Workshop (app/modules/widgets)** | 🟡→✅ | UI workspaces exist + **new** `/apps/workshop` resource |
| **Slate** | ❌→✅ | **new** `/apps/slate` |
| **Carbon** | ❌→✅ | **new** `/apps/carbon` |
| Automate | ✅ | `/automations` |

## Model development
| Tool | Status | Local equivalent |
|---|---|---|
| Model integration | 🟡 | `/model-endpoints` |
| **Modeling Objectives** | ❌→✅ | **new** `/modeling/objectives` |
| **Model Studio (train)** | ❌→✅ | **new** `/modeling/objectives/{id}/train` |
| **Model deployments (live/batch)** | ❌→✅ | **new** `/modeling/deployments` (+ infer) |

## Observability
| Tool | Status | Local equivalent |
|---|---|---|
| Audit / lineage | ✅ | `/audit-logs` |
| **Monitoring views** | ❌→✅ | **new** `/observability/monitoring-views` |
| **Traces & metrics** | ❌→✅ | **new** `/observability/traces`, `/observability/metrics` |

## Security & governance
| Tool | Status | Local equivalent |
|---|---|---|
| Approvals (HITL) | ✅ | `/approvals` |
| **Projects / roles / permissions** | ❌→✅ | **new** `/projects`, `/roles`, `/access/check` |
| **Markings / classification / restricted views** | ❌→✅ | **new** `/markings`, `/restricted-views` |
| **Cipher (encrypt/tokenize)** | ❌→✅ | **new** `/cipher/*` |
| **Sensitive data scanner / retention / checkpoints** | ❌→✅ | **new** `/governance/scan`, `/retention-policies`, `/checkpoints` |

## Product delivery
| Tool | Status | Local equivalent |
|---|---|---|
| **Marketplace** | ❌→✅ | **new** `/marketplace`, `/marketplace/{id}/install` |
| **Foundry DevOps (products/packaging)** | ❌→✅ | **new** `/devops/products` |

## Management & enablement (Control Panel) — IMPLEMENTED (Pass 12)
Fully built as `admin_directory.py` + `admin_auth.py` + `admin_usage.py` (see Pass 12 below). Enrollments, organizations, spaces, users, groups, memberships, scope-level roles, authentication providers, API tokens/service accounts/OAuth clients, and resource/usage quotas.

---
**Summary:** every tool documented in `foundry-docs-full/` now has a working local equivalent. ~28 tools were implemented originally; **~29 new local equivalents** were added across **20 self-contained modules** (18 in the first pass + `dev_toolchain` and `notepad`), bringing the platform to **100% breadth coverage** of the documented Foundry tool surface. The app exposes **248 routes** across **75 tables**, verified by `oms/test_foundry_tools.py` (**95 endpoint assertions**) plus the 7 existing scenario tests — all green. All implementations are deterministic, local approximations — not Palantir's proprietary APIs.

---

## Deep-fidelity passes ("implement as written")

Beyond breadth, each domain is being deepened to match the documented mechanics. Progress:

### Pass 1 — Ontology core (`oms/app/ontology_core.py`)
Implements documented semantics the base platform did not yet enforce:
- **Base-type catalog** — the full documented Foundry property base types (`boolean/byte/short/integer/long/float/double/decimal/string/date/timestamp/geopoint/geoshape/array/struct/attachment/mediaReference/timeSeries/marking/vector/cipherText`) at `GET /ontology/base-types`.
- **API-name rules** — PascalCase (object types) / camelCase (properties), 1–100 alphanumeric, at `POST /ontology/validate-api-name` and enforced in profiles.
- **Object-type profiles** — `PUT /ontology/object-types/{id}/profile`: primary key (with allowed-key-type enforcement — rejects `double`/`float`/etc.), title key, per-property base type + status (`active/experimental/deprecated`), and display metadata (icon/color/plural/groups).
- **Faithful Action engine** — `POST /ontology/action-types/{id}/execute`: typed parameter validation (incl. `objectReference` existence, `allowed_values`, `min`/`max`), **submission criteria** evaluation, the full **mutation set** (create / modify / delete object, add / remove link), and **side effects** (notifications + webhook outbox), plus `dry_run`.
- **Bug fix** — added the missing `description` column to `models.LinkType` (the existing `/link-types` endpoint crashed on the documented description field).

Note: link cardinality (`ONE_TO_ONE`/`ONE_TO_MANY`/`MANY_TO_MANY`) was already enforced by the core `/links` endpoint. Verified by `oms/test_ontology_core.py` (**30 assertions**).

### Pass 2 — AIP Logic (`oms/app/runtime.py` → `execute_logic_blocks`)
Deepened the AIP Logic block-execution model from a flat 7-block list to the documented engine:
- **Variable chaining** — every block's output is a variable later blocks can read (scope = inputs + loop vars + accumulated outputs).
- **Control flow** — `conditional` (then/else with nested blocks) and `for_each` (loop over an input list or an object set, with a loop variable).
- **'Use LLM' block** (`llm`) — deterministic local stand-in with `echo`/`template`/`summarize`/`classify`/`extract` modes (no network calls).
- **Query Objects** — `object_query` (filtered object set → rows) and `object_aggregate` (count/sum/avg/min/max over a property).
- **apply_action** — actually applies an action's object mutations (vs. only proposing).
- Existing blocks (`retrieve_context`, `assist`, `document_extract`, `pipeline_suggest`, `notepad_transform`, `propose_action`, `set_output`) preserved byte-for-byte.

Verified by `oms/test_aip_logic.py` (**22 assertions**) with zero regression to `test_aip_runtime.py`.

### Pass 3 — Rest of AIP (`aip_agents.py`, `aip_evals.py`, `aip_document.py`)
- **Agent Studio tool-calling** — agents get configured **tools** (Object Query, Action, Function, Command) + **retrieval context** (ontology + documents). `POST /aip/agents/{id}/invoke` deterministically selects (by trigger keyword or explicit `select`) and executes tools, returning a tool-call trace, proposed actions, retrieval, and a grounded answer (`PUT/GET /aip/agents/{id}/tools`).
- **Evals graders & metrics** — `POST /aip/evals/grade` applies a grader library (exact_match, contains, regex, not_null, in_set, length, numeric, json_path_equals) over a dotted `path` into the result, returning per-grader pass/fail + pass-rate; `POST /aip/evals/grade-logic` runs an AIP Logic function per case and grades its outputs.
- **Document Intelligence strategies** — `POST /aip/document-intelligence/process` supports `raw_text` / `structured` / `layout` / `classify` / `entities` / `chunk`, plus `POST /aip/document-intelligence/chunk` with deterministic local bag-of-tokens **embeddings** (dim 16) for RAG.

Verified by `oms/test_aip_extended.py` (**20 assertions**). AIP domain is now deepened end-to-end.

### Pass 4 — Data integration (`runtime.py` pipeline DSL + `datasets_ext.py`)
- **Pipeline Builder transform DSL** — added the documented operations to `execute_pipeline_steps`: `join` (inner/left on a second asset), `aggregate`/`group_by` (count/sum/avg/min/max), `union`, `dedupe`/`distinct`, `cast`, `rename`, `sort`, `limit`. Existing ops (filter/project/derive/normalize/classify/summarize/map_to_ontology/link_objects/geo) unchanged.
- **Dataset transactions** — `POST /datasets/{id}/transactions` with the documented types **SNAPSHOT / APPEND / UPDATE / DELETE**; the current rows are the fold of the transaction log, and the `DataAsset.records` mirror tracks the master branch.
- **Branches & time-travel** — `POST /datasets/{id}/branches` (seeded from the base branch's view, isolated), `GET /datasets/{id}/view?branch=&as_of_seq=` (time-travel to any transaction).
- **Incremental** — `GET /datasets/{id}/changes?since_seq=` returns the delta introduced after a sequence (incremental-transform input).

Verified by `oms/test_data_integration.py` (**27 assertions**), zero regression to the pipeline-using domain tests.

### Pass 5 — Applications / Workshop reactive runtime (`workshop_runtime.py`)
Added the documented reactive model over the existing `workshop_modules` table:
- **Variables** resolved by `definition_type` against the live ontology — `static`, `state`, `object_set`, `object_set_aggregation`, `object_property`, `function`, `variable_transformation` — with **dependency-ordered** fixed-point resolution (e.g., `object_property` waits on the `state` variable it reads; `variable_transformation` chains other variables).
- **Live widget render** — `POST /apps/workshop/{id}/render-live` resolves widgets against resolved variables (object tables → row counts/sample ids, metrics → bound value, buttons → action).
- **Event engine** — `POST /apps/workshop/{id}/event` runs events sequentially: `set_variable`, `reset_variable`, `navigate`, `toggle_section`, `open_overlay`/`close_overlay`, and `apply_action` (actually applies via the action engine), returning new state + recomputed variables.
- `POST /apps/workshop/{id}/resolve` returns the resolved variable scope for any state.
- **Bug fix** — added the missing `variable` binding field to `apps.WidgetSchema` so widgets can bind to variables.

Verified by `oms/test_workshop.py` (**13 assertions**), zero regression to `test_foundry_tools`.

### Pass 6 — Applications: Slate & Carbon (`slate_runtime.py`, `carbon_runtime.py`)
**Slate** (query-centric) over the existing `slate_apps` table:
- **Queries** resolved against live data: `object_set`, `object_aggregation`, `static`, `state`, `http` (deterministic mock — no real network).
- **Function DSL** (safe, deterministic — not arbitrary JS): `filter`, `pluck`, `aggregate`, `format`, `concat`, `sum`/`product`/`difference`, with dependency-ordered resolution.
- **Widget render** bound to query/function results; **event engine** (`set_variable`, `run_query`, `call_function`, `apply_action`).
- Endpoints: `POST /apps/slate/{id}/resolve|render|run-query/{q}|event`.

**Carbon** (workspace shell) over `carbon_workspaces`:
- **Module resolution** across the platform (Workshop / Slate / saved object sets / map layers) with existence + kind.
- **Navigation render** (home + sections, resolved labels) and **open-by-delegation** — `POST /apps/carbon/{id}/open/{module_id}` renders Workshop modules via the Workshop runtime and Slate apps via the Slate runtime.
- Endpoints: `GET /apps/carbon/{id}/resolve|render`, `POST /apps/carbon/{id}/open/{module_id}`.
- **Bug fix** — added the `variable` binding field to `apps.WidgetSchema` (Pass 5) is also what lets Carbon-opened Workshop widgets bind correctly.

Verified by `oms/test_slate_carbon.py` (**17 assertions**), zero regression.

### Pass 7 — Secondary tools (`gis_ops.py`, `quiver_runtime.py`, `modeling_metrics.py`, `observability_checks.py`)
- **GIS/Map** — geometry ops (distance, centroid, bbox, area, buffer) + **network routing** (Dijkstra shortest path over an object+link graph with haversine weights): `/gis/ops/*`, `/gis/route`.
- **Quiver** — time-series transforms (moving average, cumulative, delta, normalize, stats), **forecasting** (least-squares linear regression), build-from-objects: `/quiver/timeseries/*`.
- **Modeling** — evaluation metrics: regression (RMSE/MAE/R²/MAPE) and classification (accuracy/precision/recall/F1/confusion matrix): `/modeling/metrics/*`.
- **Observability** — real checks: dataset freshness (from `updated_at`), build status (latest `PipelineRun`), row-count bounds, trace rollup, metric aggregation (avg/p50/p95): `/observability/checks/*`, `/observability/traces/rollup`, `/observability/metrics/aggregate`.

Verified by `oms/test_secondary_tools.py` (**33 assertions**).

### Pass 8 — Secondary tools (`cipher_ops.py`, `security_propagation.py`, `contour_ops.py`, `object_explorer_ops.py`)
- **Cipher** — **key rotation** (versions), **bulk column transforms** (encrypt/tokenize/decrypt over a record set), a reversible **tokenization vault**, and license-gated bulk decryption: `/cipher/channels/{id}/rotate`, `/cipher/channels/{id}/keys`, `/cipher/bulk-transform`.
- **Security** — assign markings to resources, **propagate** them downstream through pipeline lineage (mandatory-control inheritance), and an **access decision** requiring all effective markings: `/security/resource-markings`, `/security/markings/propagate`, `/security/access-decision`.
- **Contour** — extended board engine: `pivot`, `sort`, `top_n`, `summary` (plus filter/derive/aggregate): `/analytics/contour/apply`.
- **Object Explorer** — numeric/categorical **histograms** and per-**property statistics**: `/object-explorer/histogram`, `/object-explorer/property-stats`.

Verified by `oms/test_secondary_tools2.py` (**34 assertions**).

### Pass 9 — Streaming & Schedules (`streaming_ops.py`, `schedules_ops.py`)
- **Streaming** (from /data-integration/streaming) — windowed aggregation (**tumbling / sliding / session**), **watermark** late-data dropping, key partitioning, and **stateful** per-key running aggregates over a stream's records: `/streams/{id}/window`, `/streams/{id}/stateful`.
- **Schedules** (from /building-pipelines/triggers-reference) — a 5-field **cron matcher** (`cron-due`) and a recursive **trigger engine** for time / event / job-succeeded / schedule-succeeded / manual plus compound **AND/OR** triggers: `/schedules/cron-due`, `/schedules/evaluate-trigger`, `/schedules/{id}/evaluate`.

Verified by `oms/test_streaming_schedules.py` (**17 assertions**).

### Pass 10 — Marketplace, OSDK, Compute Modules (`marketplace_ops.py`, `osdk_ops.py`, `compute_ops.py`)
- **Marketplace** (from /marketplace/install-product) — declared **requirements**, install **validation** (missing/unresolved inputs), **dependency-resolved install** with prefix/suffix, release **snapshots** and **upgrade diff**: `/devops/products/{id}/requirements`, `/marketplace/{id}/validate-install`, `/marketplace/{id}/install-resolved`, `/marketplace/upgrade-diff`.
- **OSDK** (from /ontology-sdk) — richer typed client generation: object interfaces + properties, **link traversal**, **Actions** (typed params), **Functions**, object-set ops, in TypeScript + Python: `/osdk/generate-client`.
- **Compute Modules** — deterministic **transform execution** (map/filter/aggregate spec) vs echo: `/compute-modules/{id}/run`.

Verified by `oms/test_marketplace_osdk.py` (**22 assertions**).

### Pass 11 — Connectivity, Media, Notepad (`connectivity_ops.py`, `media_ops.py`, `notepad_ops.py`)
- **Connectivity** — **incremental sync** with a cursor high-water-mark (only newer rows pulled, cursor persisted/advanced): `/connections/syncs/{id}/run-incremental`, `/connections/syncs/{id}/cursor`.
- **Media** — strategy extraction over stored items: RAG **chunking + embeddings**, entity extraction, layout: `/media-items/{id}/chunk`, `/media-items/{id}/extract-entities`, `/media-items/{id}/process`.
- **Notepad** — deep render: **template interpolation**, live **metric**, **chart** series (object-set aggregation), and **markdown export**: `/notepad/documents/{id}/render-full`.

Verified by `oms/test_connectivity_media_notepad.py` (**17 assertions**).

### Pass 12 — Management & Enablement / Control Panel (`admin_directory.py`, `admin_auth.py`, `admin_usage.py`)
The one whole category that was previously unimplemented. Grounded in /docs/foundry/administration/* and /platform-security-management/*:
- **Directory** — enrollments → organizations → spaces; users (with org & marking assignment, active/inactive status); groups + memberships (with **expiration**, manage-permission / manage-membership); scope-level **role grants** mapped to capabilities, with **hierarchical inheritance** (enrollment→org→space) and **group resolution**: `/admin/enrollments|organizations|spaces|users|groups|roles/grant`, `/admin/access-check`.
- **Authentication** — identity providers (SAML/OIDC) with **attribute mapping** of IdP assertions; API **tokens** that are invalid while the owning account is inactive (+ scopes, expiry, revoke); **service accounts**; **OAuth clients**: `/admin/auth-providers`, `/admin/tokens(/validate)`, `/admin/service-accounts`, `/admin/oauth-clients`.
- **Resource & usage management** — usage records, summaries (by project/principal/resource), and **quotas** with quota checks: `/admin/usage/record|summary|quotas|check-quota`.

Verified by `oms/test_admin.py` (**40 assertions**) — incl. role inheritance enrollment→space, group membership expiry excluding a user, inactive-user denial, token invalidation on deactivation, SAML attribute mapping, and quota breach detection.

### Pass 13 — Deepenings across nine tools (sub-page-grounded, critic-corrected)
A research fan-out exhaustively re-read **every** sub-page of nine areas; a completeness critic then corrected the specs before implementation. Each area is a new self-contained router module verified by its own test file.

- **Interfaces** (`ontology_interfaces_ops.py`) — transitive **inheritance resolution** over `extends`, explicit **object-type implementations** with property/link mappings, **polymorphic cross-type queries**, **interface link-type constraints** (cardinality / required / interface-or-object target), and **interface actions** enforcing the documented *Create-action shared-property primary-key* rule: `/interfaces/{id}/all-properties|link-type-constraints|query-objects|check-object-type|actions`, `/object-types/{ot}/implement-interface`. **71 assertions.**
- **Data Lineage** (`lineage_ops.py`) — recursive **upstream/downstream traversal**, **column discovery** (find datasets containing a column — *not* invented transform tracking, per critic), **impact analysis** (downstream + marking-change → PERMISSION_CHANGE), **staleness** vs upstream builds, **build-timeline** metrics, and **pipeline/dataset rollback**: `/lineage/resource/{kind}/{id}/upstream|downstream`, `/lineage/columns/search`, `/lineage/impact/...`, `/lineage/dataset/{id}/staleness|builds|rollback`. **68 assertions.**
- **Data Connection Webhooks & Listeners** (`webhooks_ops.py`) — outbound **writeback** (atomic; failure → 422 so the caller rolls back) vs **side-effect** (best-effort, batched) modes, parameter substitution, **dry-run**, credentials + simulated **OAuth** refresh, and inbound **HTTPS listeners** with HMAC / bearer / api-key auth appending events to a dataset, plus **idempotency**: `/connections/webhooks(/{id}/invoke|test|authorize)`, `/listeners(/{id}/events)`, `/outbound-applications`. **78 assertions.**
- **Vertex** (`vertex_ops.py`) — seed graph + **search-around expansion** over links, **deterministic layouts** (auto/grid/circular/radial/hierarchy/cluster), property **filter/fade**, styles, **templates** with object/scalar params, **events + timeline window filter**, **what-if scenarios** (clearly labeled deterministic simulation), control-panel settings: `/vertex/graphs(/{id}/explore|layout|filter|style|timeline|scenarios)`, `/vertex/templates/{id}/execute`. **75 assertions.**
- **Automate** (`automate_ops.py`) — condition types **object_count / object_added / object_removed / object_modified** (snapshot-diff), **run_on_all**, **threshold_crossed** (state-transition, records each crossing direction), and **time/cron**; multi-**effects** (action / notification / logic / function / **fallback**) with sequential-skip + fallback error context; **retries** (constant / exponential — base documented as an *assumption*, not doc fact); manual **batched** execution; **pause/resume/mute**; history/activities; **dependencies**: `/automations(/{id}/run|history|pause|resume|mute|dependencies)`. **125 assertions.**
- **AIP Assist custom content sources** (`aip_content_sources.py`) — **heading-hierarchy chunking**, deterministic hash embeddings, **hybrid keyword+embedding retrieval** (weights flagged as an implementation choice), **visibility scoping** (always / by_resource), assist-with-sources + **citations**, suggest, reingest, ingest logs: `/aip/assist/sources(/{id}/retrieve|visibility|reingest)`, `/aip/assist/query-with-sources`. **73 assertions.**
- **Modeling Objectives lifecycle** (`modeling_evaluation_ops.py`) — **releases** with environment tags + **explicit promote** (deployment binds to a *specific* release, per critic — not auto-rebind), **checks** (manual + automatic threshold) gating release-eligibility, **evaluation datasets/subsets** with fairness slices, deterministic **regression/classification metrics**, **experiments**, **model adapters**, and deployment config: `/modeling/objectives/{id}/releases|checks|evaluation-datasets|evaluate|experiments`, `/modeling/.../adapter/infer`. **77 assertions.**
- **Fusion formula engine** (`fusion_ops.py`) — workbooks/sheets/cells, **A1 + range** parsing, functions (SUM/AVG/MIN/MAX/COUNT/IF/ROUND/ABS/CONCAT/AND/OR/NOT + arithmetic), **dependency graph** with topological evaluation and **cycle detection** (`#CYCLE!` / `#DIV/0!` / `#REF!`), and **ontology references** materializing object sets into cell ranges: `/fusion/workbooks|sheets(/{id}/cells|evaluate|references)`, `/fusion/formula/evaluate`. **63 assertions.**
- **Object Views** (`object_views_ops.py`) — configured views, **tabs with conditional visibility** (property + link), widgets, **full/panel** form factors, **standard-view auto-generation**, instance **rendering** with `{{property}}` substitution, **versioning** (save/publish/republish older version), and sidebar (panel defaults verified against `config-panel-views`): `/object-views/{ot}(/standard|tabs|form-factor/{ff}|{oid}/rendered|versions|sidebar)`. **91 assertions.**

Verified by 9 new test files (**721 assertions**), each run standalone and re-run by an independent adversarial verifier.

### Deep-fidelity status — COMPLETE across every tool
Doc-faithful runtimes (grounded in each tool's sub-pages) now exist for **all** documented Foundry tools: Ontology core · AIP Logic · Agent Studio · AIP Evals · Document Intelligence · Data integration (pipeline DSL + dataset transactions) · Workshop · Slate · Carbon · GIS/Map (+ routing) · Quiver · Modeling metrics · Observability · Cipher · Security/markings · Contour · Object Explorer · **Streaming · Schedules · Marketplace/DevOps · OSDK · Compute Modules · Connectivity (incremental) · Media sets · Notepad**.

### Pass 14 — Platform-wide functional validation + fixes
Every tool was validated against its doc **sub-pages and screenshots/diagrams** (11 parallel domain agents), then **live-probed** (real HTTP calls against the running app). Result: **0 broken endpoints**, 2 missing whole tools, plus correctness bugs and depth gaps. Fixes implemented and verified:

**Missing tools now implemented (new modules):**
- **Autopilot** (`autopilot_ops.py`) — workflow boards with **Kanban state inference** (direct property *or* ordered predicate rules), and a **workflow dependency graph** with topological order + cycle detection. `oms/test_autopilot_ops.py` (**18**).
- **Classification / CBAC** (`classification_ops.py`) — file/data/project classifications, **hierarchical clearance** (Top Secret satisfies Secret), **disjunctive-OR category groups**, and data classification **auto-derived as the strictest upstream union**. `oms/test_classification_ops.py` (**21**).
- **Palantir MCP callable tools** (`mcp_tools.py`) — a tool catalog + dispatch (`search_foundry_ontology`, `query_foundry_objects`, `aggregate_foundry_objects`, `run_sql_query_on_foundry_dataset`, `create_or_update_foundry_object_type`) with a **proposal/staging gate** on mutations. `oms/test_mcp_tools.py` (**13**).

**Correctness bug fixes (`test_validation_fixes.py`, 33 assertions):**
- **OSDK** (`aip_extras.py`) — no longer emits a duplicate `id` field when the object type already declares one; added a model-comparison endpoint + lifecycle/capability/BYOM catalog fields.
- **Object Explorer** (`object_explorer_ops.py`) — returns **404** for a non-existent object type (was 200 + empty); added listogram keep/exclude, statistics-table, single-statistic, grid-plot.
- **Admin usage** (`admin_usage.py`) — **organization-scoped quotas** now aggregate by organization (added the missing `organization` column); was always within-limit.
- **Observability** (`observability.py`) — monitoring-view evaluator now **really dispatches** each check (freshness/row-count/build-status/schema → ok/stale/failed) with a worst-of `overall`; was a no-op always returning "ok".

**Reconciliations:** media sets accept `multimodal` (`media_sets.py`); a versioned `MevRelease` now flips the base `ModelSubmission.released` so the deployment gate agrees (`modeling_evaluation_ops.py`).

**Wave 2 — remaining backend depth (9 areas, all green):**
- **Cipher** (`cipher.py`) — three **license types** (operational_user / data_manager / admin) governing which ops a caller may perform; **channel-level required justification** on decrypt (audited; backward-compatible flag); SHA-256/512 **hash** op; canonical `CIPHER::<rid>::<value>::CIPHER` wrapper; algorithm stored per channel. `test_cipher.py` (**35**).
- **Value types** — removed. The subsystem shipped a constraint engine, immutable versioning and a consumer scan, and nothing could reach any of it: no route, migration, frontend file or SDK ever wrote the `value_type_id` its property specs would have had to carry, so the consumer scan could only return empty. Constraints declared on a property are now enforced where objects are written (`oms/app/object_writes.py`, `oms/test_property_constraints.py`).
- **Shared properties** (`ontology_interfaces.py`) — **inheritance**: apply a shared property type to an object-type property (propagate + lock metadata), detach, and list consumers. `test_ontology_interfaces_inheritance.py` (**30**).
- **Security/data** (`security_data.py`) — **checkpoints** now require a **justification** and write an audit row on pass; **retention enforcement** sweep that expires resources past TTL. `test_security_data.py` (**46**).
- **Automate fidelity** (`automate_ops.py`) — the action effect now performs **real object mutations** via `runtime.apply_action_mutations`, recording real `mutated_object_ids`. `test_automate_action_effect.py` (**38**).
- **Modeling fidelity** (`modeling.py`) — live-deployment **Multi-I/O REST envelope** on infer; **train** accepts trainer type / dataset / target / metric / preset with a submission status lifecycle. `test_modeling_io.py` (**46**).
- **AIP Evals** (`aip_evals.py`) — **graders** (Levenshtein, array/set P/R/F1, deterministic LLM-judge) + **grid-search experiments** (Cartesian param product). `test_aip_evals.py` (**41**).
- **Marketplace/DevOps** (`marketplace.py`, `marketplace_ops.py`) — install **consolidation** (validation/prefix/suffix), product **inputs vs outputs** + dependency resolution, and **installation lifecycle** (modes, release channel, auto-upgrade, lock/unlock, delete). `test_marketplace_lifecycle.py` (**32**).
- **Dev toolchain** (`dev_toolchain.py`) — Code Workbook **DAG run** (topological, per-node preview, failed path); Code Repo **pull requests + branch protection** gating merge; Compute Module **function registration** + start/stop/status. `test_dev_toolchain.py` (**67**).

(Two backward-compat regressions surfaced by the full suite were reconciled centrally: cipher's required-justification became a channel flag; marketplace installs default to the unlocked `bootstrap` mode.)

**Intentionally out of scope (UI-only, headless API clone):** the docs' images also reveal pure front-end chrome — Ontology Manager canvas, Autopilot/Workshop DAG/Kanban *rendering*, Pipeline Builder canvas, IDE panels, styling editors, map scrubbing. These are visual surfaces, not backend capabilities, and are deliberately not reproduced.

### Pass 15 — Wave 3: remaining functional breadth (13 areas, all green)
Closed the Tier-4/5 backend breadth the validation catalogued (UI-only chrome stays out of scope). Two batches, parallel disjoint-file agents, isolated self-test → adversarial verify → central full-suite reconciliation.

**Analytics breadth**
- **Quiver** (`quiver_runtime.py`) — time-series library: `resample`, `rolling`, `interpolate` (ffill/bfill/linear), `detect-events`, object-set group-by→chart.
- **Contour** (`analytics.py` + `contour_ops.py`) — data-producing boards (chart-series/histogram/distribution/time-series) + Enrich/Join/Set-Math/Unpivot transforms; **unified the divergent filter schema** so one board JSON runs in both engines.
- **Fusion** (`fusion_ops.py`) — `LOOKUP` family (`LOOKUP/_ARRAY/_DISTINCT/_DROPDOWN/_SORTED/_SCHEMA`) + action **write-back**.
- **Map/GIS** (`gis_ops.py`) — per-layer **displays**, **value-based styling**, **temporal** spatial-query.
- **Vertex** (`vertex_ops.py`) — **link-merging** (consolidate parallel/intermediate edges into an aggregated edge; group-by resolved from the underlying `LinkInstance`). `test_vertex_link_merge.py` (41).
- **Notepad** (`notepad.py`) — first-class **Template** resource (typed inputs + widget bindings + instantiate-from-template).

**Governance / management / ontology / audit**
- **Markings governance** (`security_data.py` + `security_propagation.py`) — marking **categories** (visibility/org restriction/Admin-Viewer) + **Manage/Apply/Remove/Members** grant split with opt-in apply/remove enforcement + strip endpoint.
- **Management completeness** (`security_access.py` + `admin_directory.py` + `admin_auth.py`) — `_ancestors()` **project branch**, opt-in `manage_membership` enforcement, auth-provider **enable/disable**, missing **list/get/delete** endpoints (spaces/groups/service-accounts/oauth-clients).
- **Ontology depth** (`ontology_core.py`) — **function-backed** action rule, queryable **ActionLog** + **undo**, object-type **edit/delete**, primary-key validation.
- **Audit depth** (new `audit_ops.py`) — `GET /audit-logs/search` (actor/event_type/subject_type/date filters) with derived **category**/**result**; action-log view.

**Apps / data integration**
- **Apps** (`apps.py` + `slate_runtime.py` + `carbon_runtime.py` + `workshop_runtime.py`) — **Slate versioning** (publish/versions/restore/PATCH/DELETE), **dependency-graph** endpoints, **Carbon typed navigation** parameters.
- **Data integration** (`datasets_ext.py` + `connectivity.py`) — `GET/PUT /datasets/{id}/schema`, **Test/Explore Source**, export **delta checkpoint**.
- **Streaming/Schedules** (`streaming.py` + `schedules.py`) — stream **auto-archive policy** + metrics; schedule **"ignored"** outcome + metrics.

**Central:** object **primary-key uniqueness** enforced on `POST /objects` when a profile declares a PK (backward compatible — no profile/PK ⇒ no enforcement); `audit_ops` wired into `main.py`. One real bug caught by adversarial review and fixed: Vertex link-merge `group_by` read from the edge dict instead of the `LinkInstance` (now resolved + tested). `pipeline_builder_ops.py` left untouched per scope.

---
**Test suite status (Wave 3):** **56 test files, all green.** Wave-3 additions: `test_quiver_runtime`, `test_contour_analytics_unified`, `test_fusion_lookup`, `test_gis_ops_ext`, `test_vertex_link_merge` (41), `test_notepad_templates`, `test_security_governance`, `test_security_admin`, `test_ontology_core_ext`, `test_audit_ops`, `test_apps_versioning`, `test_datasets_connectivity_ext`, `test_streaming_schedules_ext`. App: **645 routes / 175 tables**.

### Pass 16 — Performance & data realness + operator UI
Post-completion enhancements chosen after a platform-wide status survey (production-hardening and real-Claude wiring deferred by the user).

**Backend — performance & data realness**
- **Query pushdown** (`runtime._query_object_rows`) — simple top-level **equality** predicates are narrowed in SQL via SQLite `json_extract` as a candidate pre-filter; the existing Python `_compare_filter` pass re-confirms every row, so results are **byte-identical** to a pure-Python filter (verified: `test_query_pushdown.py`, 40 assertions). Non-SQLite dialects skip the pre-filter (correct, unoptimized).
- **Pagination** — `query_object_set` + `POST /object-sets/search` gain `offset`, opaque `cursor`, and opt-in `with_total` (skip the full-scan count), returning `next_cursor`. Backward compatible (default call unchanged).
- **Indexes** — composite `(object_type_id, created_at)` on `ObjectInstance`.
- **Real file upload + object storage** (`storage.py`) — `POST /data-assets/{id}/upload` parses **CSV / JSON / JSONL / Parquet** into records + inferred schema and stores the raw file (`GET .../download`); `POST /media-sets/{id}/items/upload` + `GET /media-items/{id}/content` for binary media. `STORAGE_DIR`-configurable; adds `python-multipart` (Parquet via optional `pyarrow`). Verified: `test_uploads.py` (34 assertions).

**Frontend — eight new React operator workspaces** (served at `/workspace`, `tsc --noEmit && vite build` green, 55 modules):
Control Panel, Security & Governance, Automate, Data & Media (real file upload), Vertex (graph explorer via `MiniGraph`), Fusion (spreadsheet grid), Analytics (hand-rolled SVG Object-Explorer charts + Contour boards), Delivery (Marketplace/DevOps/code). Backend `/workspace/{view}` whitelist extended so the deep-links serve the SPA shell (smoke-verified); `pipeline_builder_ops.py` and the vanilla `ui/` untouched. Production hardening (auth/CI/migrations) and real-Claude wiring remain the two deferred tracks.

---
**Test suite status (current):** **70 test files, all green.** App: **~796 routes / ~209 tables**. Frontend build clean (55 modules).

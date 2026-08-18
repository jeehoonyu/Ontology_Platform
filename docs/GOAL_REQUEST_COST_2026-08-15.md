# Goal — What a request costs

Stated 2026-08-15. Governed by [`GOAL_2026-08-03.md`](GOAL_2026-08-03.md), which defines
the outcome, scope, and severity gate this document does not restate.

## The direction, and why this one

The last several goals measured the *evidence*: whether a gate could show its head, whether
a claim outlived its proof, whether a rule in the contract was enforced anywhere. That work
found real defects, and one of them says where to look next.

`/health/ready` reflected the entire schema on every call — **275 catalog round-trips, 220
ms at rest** — and nothing in this repository would have found it. It surfaced only because
that endpoint is the one the availability gate is *defined* on, so it eventually failed a
threshold by being slow to answer. It was a tripwire, and it was there by accident.

**There are 951 routes and not one of them has a bound on what it costs to serve.**

That is the third standing invariant with the numbers filled in: *a measurement is evidence
only for the path it traverses*. Ten paths are measured. Nine hundred and forty-one are
not, and the one defect found in that space was a 275-query health check.

## What is already known, before any census

Counted, not estimated:

| | |
| --- | --- |
| Routes | **951** (489 POST, 404 GET, 27 PATCH, 18 PUT, 13 DELETE) |
| Routes with a query-count bound | **0** |
| Schema reflections on request paths | **7** |
| Of those, using a list-everything API to answer a yes/no question | **1** |

`audit_query_bounds.py` sounds like it covers this and does not. It counts *materialization
sites* — object sets loaded into Python before a limit applies — which is rows, not
round-trips. A route can issue three hundred queries without materializing anything.

The one list-everything call was `webhooks_ops._validate_source_project`, on a write path,
asking `get_table_names()` — every table in the schema, 279 of them in a populated
deployment — to learn whether one table exists. `has_table` answers the same question with
one targeted query. That is `/health/ready` again in miniature, and it is fixed.

## Conditions

- **E1 — An instrument.** **Met** — `oms/request_cost.py`. `oms/request_cost.py`: count the statements one request executes,
  normalise them so a shape run many times reads as *one shape, N times*, and decide from a
  series of measurements whether cost follows the data. **Done**, with
  `oms/test_request_cost.py` pinning the properties that carry the weight — a shape with
  varying literals must collapse, the listener must not outlive its block or every
  measurement after the first is wrong, and a verdict must be refused on fewer than three
  points rather than guessed.
- **E2 — A census.** **Met** — 151 collection GET routes walked. Walk the reachable route surface and record what each request costs.
  **Done for the 151 collection routes**, the shape where a per-row query hides. Two
  exclusions were needed and both are honest: routes that reach outside the process block on
  their own timeouts, and streaming routes, which never return a body — `/events/stream`
  stalled the first run at route 52 of 154.

  112 of 151 issue one query or fewer. Twenty issue more than ten. The worst:

  | Route | Queries, empty database | Worst repeated shape |
  | --- | --- | --- |
  | `/project/readiness` | **297** | ×32 |
  | `/project/validate` | 200 | ×32 |
  | `/ui-state/validation` | 200 | ×32 |
  | `/project/export` | 139 | ×2 |
  | `/ui-state/command-center` | 80 | ×13 |
  | `/system/migrations` | 35 | ×32 |

  The ×32 in four of those is one shape: a `SELECT` on `system_migration_records`, from
  `_ensure_migration_records`, which calls `db.get(MigrationRecord, version)` **once per
  migration** in a Python loop. There are 32 records and the number only goes up. That is a
  real per-item loop, and `/project/readiness` is now a worse offender than `/health/ready`
  was at 275.
- **E3 — Growth, not size.** **Met** — `request_cost.shape()`, which refuses fewer than three points. The absolute count is the weak signal; the strong one is
  whether the count moves when rows are added.

  **No route's cost grew with object-type count.** The single candidate did not survive
  checking: `/ui-state/ontology` measured 1 query empty and 9 with eight object types, which
  reads as exactly one query per row. At sixteen and thirty-two it is still 9. It has a
  branch that runs only when a row exists — a step, not a slope.

  That was a defect in the instrument, not the product, and the more useful of the two
  findings. `growth()` compared two points and could not tell a fixed cost that appears once
  from a cost that accrues forever; empty-against-non-empty is exactly the comparison a test
  fixture makes by default. It is replaced by `shape()`, which **refuses to answer** on
  fewer than three points and takes its slope across the non-empty ones.

  The growth column is therefore reported as unmeasured for the other 150 routes rather than
  as zero. Seeding eight object types exercises growth only for routes that read object
  types, and the first run of the census seeded **nothing at all** — the payload was wrong
  and every creation returned 422 — so its "0 routes grew" was a null result wearing a
  pass. The census now aborts if it seeds nothing.
- **E4 — Fix what the census finds.** **Met** — five defects fixed and measured. Two landed.

  `_ensure_migration_records` asked `db.get(MigrationRecord, version)` once per migration
  inside a loop, on four routes. One `SELECT` answers all 32 questions, and the first run
  against a fresh database inserts in one savepoint instead of a SAVEPOINT/INSERT/RELEASE
  per row. `checkfirst=True` on the table create — a further round-trip per call, asking
  whether a table exists that cannot stop existing — is asked once per engine now.

  | Route | Before | After | |
  | --- | --- | --- | --- |
  | `/system/migrations` | 35 | **3** | −91% |
  | `/project/readiness` | 297 | **169** | −43% |
  | `/project/validate` | 200 | **168** | −32 |
  | `/ui-state/validation` | 200 | **168** | −32 |

  `oms/test_migration_record_cost.py` pins the property rather than the number: doubling
  `MIGRATIONS` must not change the statement count. A constant would be bumped by whoever
  next added a migration; a comparison cannot be.

  And `webhooks_ops._validate_source_project` asked `get_table_names()` — every table in the
  schema — to learn whether one table exists, on a write path.

  `/ui-state/command-center` ran 13 `count(*)` statements, and attributing them by caller
  showed two separate defects on the same two lines:

  - `maintenance_summary` counted six object types with **six** `SELECT count(*)`, one per
    entry of a list literal. One `GROUP BY` answers all six. The dict is rebuilt from the
    declared list rather than from the rows, because `GROUP BY` returns nothing for a type
    with no instances and a missing key would read as an absent object type rather than an
    empty one.
  - `_summarize` called `maintenance_summary(db)` **twice in the same dict literal**, so the
    route paid for the whole thing twice. The `asset_count` KPI beside it was a third query
    for a number the summary had already computed.

  | | Before | After |
  | --- | --- | --- |
  | `/ui-state/command-center` queries | 80 | **67** |
  | of which aggregate statements | 13 | **1** |

  `oms/test_maintenance_summary_cost.py` pins the shape, not the total: one grouped count,
  computed once per request, agreeing with per-type counting on real rows, and zero rather
  than missing for a type with no instances. Writing that test surfaced a trap worth naming
  — the first version matched `count(*)` literally, and the fixed code spells it
  `count(object_instances.id)`, so it scored the fix as issuing no counts at all. A fix
  marked correct for having stopped doing the thing being measured.

  **`/project/export` was examined and is not a defect.** 139 queries, and 138 of them are
  distinct shapes: it assembles a portable project snapshot from **133 list-valued
  collections**, one `SELECT` per collection. One query per exported table is not something
  to improve — a union would be worse, and reading everything is what export means.

  Measured rather than assumed, at four points:

  | Object types | Queries | Payload |
  | --- | --- | --- |
  | 0 | 139 | 7.1 KB |
  | 8 | 139 | 31.2 KB |
  | 16 | 139 | 55.3 KB |
  | 32 | 139 | 99.7 KB |

  `shape()` returns **flat**. The query count does not follow the data; the payload does,
  which is the definition of the endpoint working.

  What *is* worth recording is a different axis: all 133 reads are `.all()` with no limit,
  so a large project's export materialises the entire project in Python with no streaming or
  pagination. That is the bound `audit_query_bounds.py` measures, and it does not cover these
  sites — it tracks object-set primitives, not the snapshot builder. Bounded queries,
  unbounded memory. Named here rather than fixed, because for an export endpoint it may well
  be the correct trade, and deciding that is not the same as noticing it.

  **`/project/readiness` got that look, and half of it was fixable.** It is not a loop:
  169 queries, 160 distinct shapes. The breadth comes from `validate_project`, which builds
  the **entire portable project snapshot** — the same 133-collection export `/project/export`
  serves — and hands it to `_snapshot_coverage`. That function reads exactly two things from
  it: which collection names are present, and how long each one is. **110 integers.**

  Measured on a small project, before:

  | | |
  | --- | --- |
  | `_snapshot(db)` | 26.6 ms |
  | `_snapshot_coverage()`, all it needs from that | **0.009 ms** |
  | rows materialised to compute 110 lengths | 324 |

  So 68% of a readiness check was building an export it discarded. Both numbers grow with
  the project; the answer does not.

  Fixed here: `_snapshot(..., finalize=False)` for the coverage path. Finalizing deep-copies
  the whole project, redacts secrets nobody will see, and takes a canonical-JSON sha256 of
  the result — everything an *exported artifact* needs and a discarded one does not.

  | Route | Before | After |
  | --- | --- | --- |
  | `_snapshot` | 26.3 ms | **19.3 ms** |
  | `/project/readiness` | 39.0 ms | **33.2 ms** |
  | `/project/validate` | 41.2 ms | **33.3 ms** |
  | `/ui-state/validation` | 40.3 ms | **34.0 ms** |

  Query counts are unchanged, as they should be — this is the memory and CPU axis, not the
  round-trip one, and `audit_request_cost.py` correctly reports no drift.

  `oms/test_project_validation_cost.py` pins both halves: coverage must be identical with
  and without finalizing, and **the export must still be finalized**, because shipping an
  artifact without its checksum is the defect this would otherwise introduce while removing
  another. It counts `_finalize_snapshot` calls per route — zero for validate and readiness,
  exactly one for export.

  **The count-only refactor was attempted and is wrong.** Replacing each `.all()` with a
  `.count()` does not produce the same numbers, because `_snapshot` does not return what the
  tables contain — it returns a **single-project dependency closure**, computed in Python
  from the rows after they are loaded.

  Measured, with seven object types belonging to a second project:

  | | |
  | --- | --- |
  | `SELECT count(*) FROM object_types` | **13** |
  | `coverage["counts"]["object_types"]` | **6** |

  `_scope_snapshot` filters every collection by `row.get("project_id")`, then applies rules
  that need the payloads: plugin trust keys are selected by the `signer_key_id` values
  referenced from *this project's* plugin versions, and legacy data assets are recognised by
  reading `row["asset_schema"]["project_id"]`. It also **adds** rows — `organizations` and
  `projects` come out of scoping with one entry each having loaded none. A `count(*)` cannot
  reproduce any of that. The refactor as stated is not risky; it is incorrect.

  **What the rows are actually being spent on is worth more than the count question.**
  Scoping discards most of what the builder loads:

  | | |
  | --- | --- |
  | rows loaded by the builder | 322 |
  | rows surviving the scope | 124 |
  | **discarded** | **198 (61%)** |

  `object_types` alone loaded 206 rows to keep 6, and that ratio grows with every project
  the deployment gains — the builder reads *all* projects to serve one.

  So the tractable change is **scope pushdown**, not count-only: filter `project_id` in SQL
  for the collections whose scope rule is exactly that, and keep the payload-dependent
  closure rules in Python for the handful that need them. That is a different and larger
  piece of work than this goal set out to do, and it is worth its own measurement first —
  which collections carry a `project_id` column, and which of the closure rules survive
  being asked in SQL.
- **E5 — A ratchet.** **Met** — `oms/audit_request_cost.py` with `docs/request-cost-baseline.json`. `oms/audit_request_cost.py`, with the surface recorded in
  `docs/request-cost-baseline.json`. **Done.**

  **It gates the repeated shape and reports everything else**, and that split is the whole
  design. One statement executed many times in a request is the N+1 signature — it is what
  every defect in E4 looked like, and it is not something ordinary work does. Totals are
  reported and never gated, because a large total is often correct: `/project/export` issues
  139 queries and 138 are distinct. An audit that failed on totals would fail that endpoint
  forever, and a check people route around is worse than no check. That is the rule this
  project has now learned three times.

  The ceiling is **6**, chosen from the measured surface after the loops came out: the worst
  remaining repeat is 4, so there is room for an honest change and a ×13 or a ×32 fails the
  day it lands. The ratchet is that the count of routes above the ceiling stays at zero.

  It boots the app against a scratch SQLite database rather than whatever `DATABASE_URL`
  happens to be set — an audit that measures the caller's database measures the machine it
  runs on rather than the code it checks. 151 routes in **9 seconds**.

  `oms/test_request_cost_audit.py` builds the states it must catch and the states it must
  not: a shape over the ceiling fails **even when the baseline already recorded it** — a
  ratchet that grandfathers what was there when it was written enforces nothing on existing
  code, and every loop this found was pre-existing. The migration-record ×32 and the
  command-center ×13 are both replayed as fixtures, so the audit is tested against the
  defects it was built for rather than only against a tree that already passes.

- **E6 — The column census, before any pushdown.** **Met** — the column census recorded in this document. The scope-pushdown idea needs to know,
  per collection, whether `project_id` can be asked in SQL. `_scope_snapshot` filters on
  `row.get("project_id")` — the *serialised* key, not the column — so three things have to
  hold, and each was checked rather than assumed.

  Of the 133 collections `_snapshot` builds:

  | | | |
  | --- | --- | --- |
  | **114** | pushdown-able | has the column, serialises it, no existing filter |
  | 1 | already filtered | |
  | 18 | no `project_id` column | re-included by the parent closure or an explicit rule |
  | **0** | column present but not serialised | the case that would empty a collection silently |

  That last row is the one the census was really looking for. A collection whose model has
  `project_id` but whose row dict omits it would be dropped entirely by scoping while looking
  healthy — every export missing it, every restore short of it, and nothing to see in the
  code. **There are none.**

  The 18 without the column are not a gap either. `_SNAPSHOT_CHILD_RELATIONS` re-includes
  them by parent identity — `logic_runs` through `logic_functions`, `agent_sessions` through
  `agent_definitions`, `stream_records` through `streams`, and so on. Verified rather than
  read: a logic run whose function belongs to the project survives the scope, and one whose
  function belongs to another project does not.

  So the work splits cleanly, and the split is the point of doing this first:

  - **114 collections take a one-line filter each.** The SQL predicate is exactly what the
    Python loop already computes, so the equivalence test is that `_snapshot` output is
    identical before and after on a multi-project fixture.
  - **18 need a second phase** — scope the parents, then fetch children by `parent_id IN
    (...)`. That is a design change to `_snapshot`, two passes instead of one dict literal,
    not a per-line edit.
  - The explicit closure rules stay in Python, because they read payloads.

  One property here is worth a ratchet of its own and does not have one: a new collection
  that neither serialises `project_id` nor is declared a child would vanish from every
  snapshot silently. It is satisfied today at zero, which is exactly when a ratchet is
  cheapest to install.

- **E7 — The ratchet, then phase one.** **Met** — `oms/audit_snapshot_scope.py` landed before phase one. Both landed, in that order deliberately.

  `oms/audit_snapshot_scope.py` refuses a collection that scoping would empty without a
  symptom. 133 collections: **115** carry `project_id`, **12** come back through the parent
  closure, **6** are assigned explicitly by `_scope_snapshot`, **0** are dropped. Nothing in
  it is hand-maintained — child relations are read from the module, explicit rules from
  `_scope_snapshot`'s own assignments, serialised keys from each entry — because a list of
  exceptions is the part that rots. It went in at zero, which is when a ratchet costs
  nothing and cannot be argued with.

  Then the pushdown: `_for_project(query, column, project_id)` applied to the **114**
  qualifying collections, filtering in SQL what `_scope_snapshot` filtered in Python
  afterwards. Same rule, asked where it can be answered.

  | With 200 rows in a second project | Before | After |
  | --- | --- | --- |
  | rows the builder loads | 322 | **122** |
  | `_snapshot` (scoped) | 19.3 ms | **17.0 ms** |
  | `/project/readiness` | 33.2 ms | **27.8 ms** |
  | `/project/export` | 42.3 ms | **30.8 ms** |

  The ratio is the point rather than the milliseconds: the old builder read every project to
  serve one, so its cost grew with the tenants beside you. 122 rows is now the whole cost
  whether the deployment holds one other project or ten thousand.

  **Equivalence was proved against a fixed fixture, not argued.** The same SQLite file was
  snapshotted before and after; the scoped output is byte-identical except for `created_at`
  and `updated_at` on `projects` and `organizations` — and a **control run of the same code
  twice** shows those two fields differing by themselves, because `_scope_snapshot`
  synthesises those rows with a clock. Without the control they would have read as a
  regression.

  The harness produced one false regression before that, worth recording because it looked
  exactly like a real one: copying a live SQLite fixture without its `-wal` sidecar silently
  dropped every commit still in the write-ahead log, and the diff reported 18 missing rows
  as a defect in the code under test. A measurement can be wrong in the direction of alarm
  as easily as in the direction of comfort.

  `oms/test_snapshot_project_pushdown.py` pins three properties: no foreign row is loaded,
  every row that belongs is still there **including children re-added by parent identity**
  (`logic_runs` has no `project_id` column at all), and an unscoped `_snapshot(db)` still
  reads everything — because a filter on a missing project would quietly export nothing,
  which is the failure this change could most easily have introduced.

  **Phase two, which turned out to be a correctness fix.** Measuring first: with 500 child
  rows belonging to another project, the builder loaded 622 rows and **80% of them were
  children** — the collections phase one could not touch, because they have no project of
  their own.

  Then a worse finding. Fifteen of the 27 child collections *do* carry a `project_id`
  column, and phase one had filtered them by it. That is not the same predicate.
  `_scope_snapshot` reads children from the **unscoped** list and keeps the ones whose
  foreign key points at a parent in scope — so a row whose parent is in the project belongs
  in the snapshot whatever its own column says. Narrowing by the column deleted it before
  the closure could see it. Demonstrated: a `platform_event_log` row whose parent was in the
  project, and which the pre-phase-one code kept, **disappeared from the export**.

  The equivalence harness missed it because no fixture row had a child disagreeing with its
  parent. A byte-identical diff is only as strong as the states the fixture contains.

  So children are now selected by their parents, as a subquery — the closure's own
  predicate, asked where the rows are:

  | With 500 foreign child rows | Before | After |
  | --- | --- | --- |
  | rows the builder loads | 622 | **122** |
  | of which child rows | 500 | **0** |

  A subquery rather than a list of parent ids, deliberately: a list is bounded by the
  database's parameter cap, so a project with more parents than the cap would fail rather
  than merely slow down. It recurses for the one two-deep relation
  (`event_stream_receipts` → `event_stream_bindings` → `streams`).

  **All 27 are narrowed.** The last one took a second look. `ontology_package_versions`
  hangs off `ontology_packages`, which has no `project_id` — a package is in scope when the
  project **owns** it *or* when some installation **targeting** the project names it. There
  is no column for that, which is why the first pass left the versions reading every
  package's history.

  There is no column, but there is a predicate, and a predicate is a subquery like any
  other:

  ```sql
  owning_project_id = :project
  OR id IN (SELECT package_id FROM ontology_package_installations
            WHERE target_project_id = :project)
  ```

  `_SNAPSHOT_PARENT_PREDICATES` holds it, keyed by the *parent's* collection name so a
  child asks about its parent rather than about itself. The distinction that matters is
  tested in all three directions: a package owned here keeps its versions, a package owned
  elsewhere **but installed here** keeps its versions too, and a package owned elsewhere and
  not installed has its history never read at all.

  `_SNAPSHOT_CHILD_QUERIES` was **derived** from the existing relation map and the builder's
  own queries rather than hand-written, and a test asserts the two maps describe the same
  set so neither can drift alone. The crossed-parent case is now a test: a child of my parent
  is kept though its own column says otherwise, and a child claiming my project is dropped
  because its parent is not mine.

- **E8 — The full suite, which found what the harnesses did not.** **Met** — the full suite found the two regressions the harnesses did not. 224 test scripts,
  **223 passed and one failed**: `test_durable_ingestion_runtime.py`, on a restore.

  ```
  Snapshot validation failed
  Resource 'connection_syncs:maintenance_sync' references
  missing scoped data_assets 'ingestion_target'
  ```

  The same defect as the child collections, in a collection that is not a child.
  `_scope_snapshot` recognises a **legacy data asset** by reading
  `row["asset_schema"]["project_id"]` out of the *unscoped* snapshot and adding it back.
  Phase one had narrowed `data_assets` by its own `project_id` column, so those rows were
  gone before the rule could see them — the export came out short and the restore refused
  it. `project_memberships` was narrowed the same way.

  Both are reverted, and the rule behind them is now stated once and checked:

  > **A collection `_scope_snapshot` reads out of the unscoped snapshot must not be narrowed
  > in the builder.**

  That is nine collections — `data_assets`, `project_memberships`, `plugin_trust_keys`,
  `projects`, `organizations`, and the ontology packages — and `audit_snapshot_scope.py`
  now **fails** when any of them is narrowed, because this is data loss rather than drift.
  It is the invariant that covers both regressions: the child ones and this one.

  **The check did not work the first time, and that was the most useful part.** The matcher
  reached from a collection's key to the `_for_project(` call with `[^\]]*?`, which cannot
  cross the `]` closing `_row_dict`'s own field list — so it matched **nothing at all** and
  reported a clean tree. A check that passes by measuring nothing is the exact failure this
  repository keeps finding, and it was only caught by running the audit against a tree that
  *contains* the state it refuses. That tree is now a test case, along with the bracket that
  broke the matcher.

  Three defects, three harnesses, and the order they were caught in is the lesson: the
  equivalence fixture missed both because it contained no crossed row; the audit missed the
  second because it silently matched nothing; the suite caught it because a restore is a
  real use of the data. **A fixture proves what it contains. A suite proves what it does.**
## What this is not

Not a performance goal. Nothing here promises a route gets faster, and no threshold in it is
a latency bound — those belong to the Tier B gates and are measured on a quiet host with the
worst of six observations. This measures *round-trips*, which are countable exactly, are the
same on any hardware, and do not need a quiet machine to be true.

That distinction is the point. The three Tier B gates still MISSING are waiting on seven
days of a host that stays up. This waits on nothing.

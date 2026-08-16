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

- **E1 — An instrument.** `oms/request_cost.py`: count the statements one request executes,
  normalise them so a shape run many times reads as *one shape, N times*, and decide from a
  series of measurements whether cost follows the data. **Done**, with
  `oms/test_request_cost.py` pinning the properties that carry the weight — a shape with
  varying literals must collapse, the listener must not outlive its block or every
  measurement after the first is wrong, and a verdict must be refused on fewer than three
  points rather than guessed.
- **E2 — A census.** Walk the reachable route surface and record what each request costs.
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
- **E3 — Growth, not size.** The absolute count is the weak signal; the strong one is
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
- **E4 — Fix what the census finds.** Two landed.

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

  Still open: `/project/readiness` remains the worst route in the product at 169, and 226 of
  its statements are distinct shapes — so what is left there is breadth, not a loop, and it
  wants the same kind of look `/project/export` just got.
- **E5 — A ratchet.** `oms/audit_request_cost.py`, with the surface recorded in
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

## What this is not

Not a performance goal. Nothing here promises a route gets faster, and no threshold in it is
a latency bound — those belong to the Tier B gates and are measured on a quiet host with the
worst of six observations. This measures *round-trips*, which are countable exactly, are the
same on any hardware, and do not need a quiet machine to be true.

That distinction is the point. The three Tier B gates still MISSING are waiting on seven
days of a host that stays up. This waits on nothing.

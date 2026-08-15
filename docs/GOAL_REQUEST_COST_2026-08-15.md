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
- **E4 — Fix what the census finds.** One fix landed ahead of it, above.
- **E5 — A ratchet.** An audit that fails when a route's cost regresses past its recorded
  ceiling, and *reports* drift rather than failing on it — the rule this project learned
  twice, that a gate on something ordinary work breaks is a gate people route around.

## What this is not

Not a performance goal. Nothing here promises a route gets faster, and no threshold in it is
a latency bound — those belong to the Tier B gates and are measured on a quiet host with the
worst of six observations. This measures *round-trips*, which are countable exactly, are the
same on any hardware, and do not need a quiet machine to be true.

That distinction is the point. The three Tier B gates still MISSING are waiting on seven
days of a host that stays up. This waits on nothing.

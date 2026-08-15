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
  normalise them so a shape run many times reads as *one shape, N times*, and report the
  growth per row between two measurements. **Done**, with `oms/test_request_cost.py` pinning
  the two properties that carry the weight — a shape with varying literals must collapse,
  and the listener must not outlive its block or every measurement after the first is wrong.
- **E2 — A census.** Walk the reachable route surface and record what each request costs.
  **In progress.** The first attempt had to be narrowed: routes that reach outside the
  process block on their own timeouts and say nothing about database cost.
- **E3 — Growth, not size.** The absolute count is the weak signal; the strong one is
  whether the count moves when rows are added. A route whose cost follows the data passes on
  an empty test database and fails in front of a customer. **Owed**, and it is what the
  census exists to produce.
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

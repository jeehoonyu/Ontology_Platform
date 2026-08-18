# Goal — What a write costs

Stated 2026-08-16. Follows [`GOAL_REQUEST_COST_2026-08-15.md`](GOAL_REQUEST_COST_2026-08-15.md),
which measured reads and left the larger half of the surface untouched.

## The direction

The request-cost goal walked 151 **collection GET** routes and found five defects, the worst
of them a health check issuing 275 catalog round-trips. It never measured a single write.

| | |
| --- | --- |
| Write routes (POST/PUT/PATCH/DELETE) | **547** |
| Measured by anything | **0** |

That is not an oversight in the previous goal so much as a wall it hit. A GET with no path
parameter can be called by a machine walking the route table. A POST cannot: it needs a
body the route will accept, and inventing 547 valid payloads is not a census, it is a
rewrite of the test suite.

## The idea that makes it tractable

**The test suite already issues those writes, with payloads the routes accept.** 224 scripts
exercise the product end to end — creating object types, running pipelines, approving
actions, importing snapshots. Instrumenting the application while the suite runs turns every
one of those into a measurement, at no cost in invented fixtures.

It also measures the right thing. The third standing invariant says a measurement is
evidence only for the path it traverses; traffic the product's own tests generate traverses
the paths the product actually serves, which is a stronger claim than a synthetic walk of
the route table makes.

## Conditions

- **F1 — A recorder that attaches to a running app.** **Met** — `oms/measure_suite_cost.py`. Count the statements each request
  executes, keyed by route template and method, without touching production code. The
  existing `oms/request_cost.py` already counts and normalises; what is missing is the part
  that attributes a count to the route that caused it.
- **F2 — A census from the suite.** **Met** — 3,643 requests over 695 route+method pairs. Run all 224 scripts with the recorder attached and
  aggregate. Reads and writes together, ranked by worst repeated shape and by total.
- **F3 — Find the writes that repeat a shape.** **Met** — the census table above. The N+1 signature is the same on a write as
  on a read, and a write loop is worse: it holds a transaction open while it runs.
- **F4 — Fix what it finds**, on the evidence, with the equivalence discipline this project
  has now learned three times the hard way — a fixture proves what it contains, so the
  fixture has to contain the crossed case. **Met** — below.
- **F5 — Extend the ratchet.** `audit_request_cost.py` gates the repeated shape over GET
  collection routes. If the suite can produce write costs reproducibly, the same ceiling
  should cover writes. **Met** — `oms/audit_suite_cost.py`, below.

## What the census found

**3,643 requests — 2,368 of them writes — over 695 route+method pairs, of which 400 are
write pairs.** Every one issued by the suite with a payload the route accepts. Worst
observation per route, never the mean: a route called forty times with one expensive call is
a route with an expensive call.

| Repeats | Queries | Calls | Route |
| --- | --- | --- | --- |
| **×1006** | 10,203 | 44 | `POST /pipeline-builder/workers/run-next` |
| ×85 | 281 | 18 | `POST /project/import` |
| ×52 | 849 | 4 | `POST /project/demo/bootstrap` |
| ×49 | 786 | 1 | `POST /project/demo/reset` |
| ×44 | 705 | 4 | `POST /scenarios/asset-reliability/bootstrap` |
| ×33 | 1,140 | 57 | `GET /project/readiness` |
| ×20 | 83 | 15 | `GET /runtime/observability/summary` |

- `run-next` repeats **one `INSERT INTO event_outbox`** a thousand times in a single
  request, holding a transaction open across all of it. The largest finding here, and a
  write — which is what this goal was opened to look at.
- `/project/import` repeats a shape 85 times.
- `/project/readiness` is **not** a defect, and saying so took three attempts. Its ×33 is
  `INSERT INTO system_migration_records` — the 33 migration rows seeded on the first call
  against a fresh database, which 23 of the suite's scripts each trigger once. Of its 57
  calls, 31 sit at ×4 and 23 at exactly ×33; nothing in between scales. Measured directly
  against a growing audit log it is flat — 169 queries and ×4 at 0, 200, 400 and 800 rows.

The route was named as a defect twice before that: first at ×192, which was the instrument
counting other threads' work, and then at ×33 attributed to a `count(*)` over `audit_logs`,
which was a guess that the measurement above refutes. Both are left in this document on
purpose. The lesson is not that the route is fine; it is that **a repeated shape is a
question, not a finding** — one-time seeding, a fixed fan-out over seven event types, and a
loop over rows all look identical until something separates them, which is what `shape()`
is for and what neither claim used.

**These are the second set of numbers.** The first set was measured with an instrument that
was wrong under concurrency; what it claimed and what is true are set out below.

## Correction — the instrument was measuring the process, not the request

The recorder first published here attached a listener to the engine for the duration of one
request and appended every statement it saw to one list. That is correct while one request
runs at a time. **18 of the 224 suite scripts issue requests from more than one thread**, and
in those, each request collected every other in-flight request's statements. Because the
summariser takes the worst observation per route, the contaminated number is precisely the
one that won.

Measured directly, on 48 concurrent calls to `/project/readiness` whose true cost is 169
statements each:

| | Recorded per request | Sum |
| --- | --- | --- |
| listener on the engine | 2,184 – 9,823 | 195,377 |
| truth (same request, run alone) | 169 | 8,112 |

Twenty-four worker threads, twenty-four times the truth. What the two censuses say about the
findings that were published:

| Route | Published | Corrected | |
| --- | --- | --- | --- |
| `POST /pipeline-builder/workers/run-next` | ×1006 | **×1006** | holds exactly |
| `POST /project/import` | ×85 | **×85** | holds exactly |
| `GET /project/readiness` | ×192 | ×33 | overstated 6× |
| `POST /jobs/claim` | ×84 | ×13 | overstated 6× |
| `GET /runtime/observability/summary` | ×78 | ×20 | overstated 4× |

Every route named was really repeating a shape — none of the findings was invented — but
three were overstated by four to six times, and one of those was the example this document
leaned on hardest.

The fix is a context variable rather than a shared list: Starlette copies the calling context
into the worker thread that runs a sync endpoint, so a variable set in the middleware is
readable from the listener and names the request that owns the statement. With it, all 48
concurrent requests record 169 statements and a worst repeat of 4 — identical, to the
statement, to the same request run alone. `oms/test_request_cost_concurrency.py` asserts
that equality, and it is the assertion the old recorder could not have passed.

This is the third standing invariant turned on the tooling instead of the product: *a
measurement is evidence only for the path it traverses*, and a measurement that cannot say
which path it traversed is not evidence at all.

## The finding that matters most is about the ratchet

`audit_request_cost.py` walks **collection GET routes** against a **scratch, empty**
database, and the census says plainly which half of that is the problem.

| | Ratchet | Suite | |
| --- | --- | --- | --- |
| `POST /pipeline-builder/workers/run-next` | **never called** | 10,203 queries, **×1006** | the blind spot |
| `GET /project/readiness` | 169 queries, ×4 | 1,140 queries, ×33 | not a loop — see above |

**The blind spot is method, not emptiness.** The suspicion when this section was first
written was that an empty database hides loops over rows, and the readiness numbers looked
like proof. They were not: that route is flat in its data, and the gap between ×4 and ×33 is
first-call migration seeding rather than anything the ratchet's emptiness conceals. Two
attempts to seed a database into showing a loop — thirty object types, then eight hundred
audit rows — moved nothing, which is the same answer arrived at from the other direction.

What the census does establish is simpler and worse. The ratchet gates 151 collection GET
routes. **547 write routes are gated by nothing**, and the worst repeated shape in the
codebase — by a factor of nineteen over the next read — is an `INSERT` on a route the walk
never issues. The ceiling of 6 was chosen from the GET surface, every route on that surface
passes it, and a POST in the same codebase repeats an insert a thousand times per request
while holding a transaction open across all of it.

So the fix is F5, and it is not a bigger fixture: it is the census itself as the measurement
condition, because the suite already supplies the payloads that 547 invented bodies could
not.

## What the fix found: the loop was asking the schema a question

`POST /pipeline-builder/workers/run-next` hydrates about a thousand objects in one request.
Dumping the statement sequence rather than the summary showed a cycle of ten statements per
object, and **three of the ten asked a question whose answer was already known**:

| Per object, before | | |
| --- | --- | --- |
| `PRAGMA table_info("object_snapshots")` | 1,002× | `create(checkfirst=True)`, once per snapshot |
| `PRAGMA table_info("object_change_events")` | 1,002× | `has_table`, once per change event |
| `SELECT … ontology_environments …` | ~1,000× | the project's production revision |

A fifth of the most expensive request in the codebase was spent asking whether two tables
exist. Tables do not appear or vanish under a live request, so all three are now looked up
once per request and cached on the session.

| `POST /pipeline-builder/workers/run-next` | Statements | Per object |
| --- | --- | --- |
| before | 10,202 | 10.2 |
| after | **7,201** | **7.2** |
| removed | 3,002 (**29%**) | |

The census found the same fix reached six other routes, none of them touched deliberately:
`/project/demo/bootstrap` and `/project/demo/reset` (−8 each), `/scenarios/asset-reliability/bootstrap`
(−8), the industrial onboard route (−6), `/pipeline-builder/graphs/{graph_id}/deliver` (−4)
and an entity-resolution accept (−1). Every path that writes an object was paying it.

### The one that was not safe to cache the obvious way

The revision lookup is not constant, and the route that motivated the fix is exactly where
it changes. `industrial_workflow` promotes a new revision — `environment.current_revision_id
= revision.id` — and *then* hydrates the objects belonging to it, in one request. Caching the
revision **id** would have stamped every one of those objects with the revision the promotion
had just superseded, and the suite would have said nothing: the objects get written, the
request succeeds, and only the lineage is wrong.

So what is cached is the environment **row**, not the id read off it. SQLAlchemy's identity
map makes it the same instance the promotion mutates, so the read sees the new value, and a
commit in between expires the instance into refreshing itself rather than serving a stale
copy.

`oms/test_change_event_revision_freshness.py` contains a promotion followed by a write, and
was checked against the wrong implementation before being trusted: with the id cached it
fails with `got 'revision-one'`. A fixture that only records events against a stable revision
passes either way, which is the trap this project has now walked into four times.

### What is left, and why it is not waste

The worst repeat is unchanged at **×1006** — one `INSERT INTO event_outbox` per object — and
that is structural rather than sloppy. Sessions here are `autoflush=False`, so the explicit
`db.flush()` inside the change-event recorder is load-bearing: the next object's version
comes from `max(object_version)` over rows already written, and two changes to the same
object in one request would otherwise both compute version 1. Batching the inserts means
redesigning how versions are assigned, which is a different piece of work with a real
correctness surface, not a caching win.

It is recorded here rather than folded in, and the ratchet now holds it at 1006: it may go
down, and it fails at 1007.

## The ratchet that covers writes

`oms/audit_suite_cost.py` gates the census. **695 route+method pairs, 400 of them writes**,
against `docs/suite-cost-baseline.json`.

The prerequisite was reproducibility, since a gate on a number that moves is a gate people
learn to re-run until it passes. Two independent full censuses:

| | Agreement |
| --- | --- |
| route+method pairs discovered | 695 vs 695, none in one run only |
| **worst repeat per pair** | **695 / 695 identical** |
| statements per pair | 692 / 695 |

So the worst repeat is gated and the statement count is reported. The three that move —
`/runtime/observability/summary` (83 vs 107), `/jobs/claim` (55 vs 58), `run-next` (10,203 vs
10,202) — are exactly the notes the second census produced when checked against a baseline
built from the first.

What it gates, following the rule each ratchet here has had to be taught separately — *gate
the thing ordinary work does not do, report the thing it does*:

- **a route repeating a shape more often than its baseline.** Adding a query is ordinary;
  turning a fixed cost into a repeating one is not. The 33 pairs already above the ceiling
  are frozen at the value measured and may only go down — ×1006 fails at ×1007.
- **a route absent from the baseline arriving above the ceiling of 6.** New code is held to
  the standard rather than admitted to the debt.
- **a watched route missing from the census.** Debt that goes dark is debt paid off on paper.
- **a census that covered under 90% of the baseline.** A crashed run must not pass every gate
  by never contradicting one — the empty-fixture lesson, applied to the fixture that is now
  the whole suite.

This is a weaker claim than the GET ratchet makes, where a violation fails even if the
baseline recorded it, and the difference is deliberate: this surface starts with 33 real
debts on it, and a gate that fails on day one is a gate someone turns off.

It is not a pre-push check — the census is 225 subprocesses and about twenty minutes.
`audit_request_cost.py` stays the fast one; this runs on demand.

## What this is not

Not a latency goal, for the same reason as its predecessor: round-trips are countable
exactly and identical on any hardware. And not a transactional-correctness goal — whether a
failed write leaves partial state is a real question and a different one, needing fault
injection rather than counting. If the census surfaces a candidate, it gets recorded, not
silently folded in here.

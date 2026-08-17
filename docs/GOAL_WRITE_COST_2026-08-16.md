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

- **F1 — A recorder that attaches to a running app.** Count the statements each request
  executes, keyed by route template and method, without touching production code. The
  existing `oms/request_cost.py` already counts and normalises; what is missing is the part
  that attributes a count to the route that caused it.
- **F2 — A census from the suite.** Run all 224 scripts with the recorder attached and
  aggregate. Reads and writes together, ranked by worst repeated shape and by total.
- **F3 — Find the writes that repeat a shape.** The N+1 signature is the same on a write as
  on a read, and a write loop is worse: it holds a transaction open while it runs.
- **F4 — Fix what it finds**, on the evidence, with the equivalence discipline this project
  has now learned three times the hard way — a fixture proves what it contains, so the
  fixture has to contain the crossed case.
- **F5 — Extend the ratchet.** `audit_request_cost.py` gates the repeated shape over GET
  collection routes. If the suite can produce write costs reproducibly, the same ceiling
  should cover writes.

## What the census found

**3,643 requests over 695 route+method pairs — 2,368 writes and 1,275 reads.** Every one
issued by the suite with a payload the route accepts. Worst observation per route, never the
mean: a route called forty times with one expensive call is a route with an expensive call.

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
- `/project/readiness` repeats `SELECT count(*) FROM (SELECT audit_logs …)` 33 times.

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
database. That is what makes it fast and deterministic, and it is also why it sees none of
this. The blind spot has two halves, and the corrected census sharpens rather than softens
both:

| | Ratchet sees | Suite sees |
| --- | --- | --- |
| `GET /project/readiness` | 169 queries, ×4 | 1,140 queries, **×33** |
| `POST /pipeline-builder/workers/run-next` | **never called** | 10,203 queries, **×1006** |

The first half is emptiness: a loop over rows has nothing to loop over when there are no
rows, so the same route reads ×4 on the ratchet's database and ×33 on one the suite has
used. The second half is method: the ratchet walks GETs, and the worst repeat in the
codebase — by a factor of thirty — is a POST it never issues.

The ceiling of 6 was chosen from the empty-database GET surface, and every route on that
surface passes it, while a route in the same codebase repeats an `INSERT` a thousand times
per request.

This is the same mistake as the snapshot equivalence fixture, one level up: **a fixture
proves what it contains**, and an empty one contains nothing that grows. The ratchet is not
wrong about what it measures; it is measuring a condition under which the defect cannot
appear.

## What this is not

Not a latency goal, for the same reason as its predecessor: round-trips are countable
exactly and identical on any hardware. And not a transactional-correctness goal — whether a
failed write leaves partial state is a real question and a different one, needing fault
injection rather than counting. If the census surfaces a candidate, it gets recorded, not
silently folded in here.

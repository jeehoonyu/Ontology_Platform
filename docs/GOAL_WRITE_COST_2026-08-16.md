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

**3,641 requests over 695 route+method pairs — 2,368 writes and 1,273 reads.** Every one
issued by the suite with a payload the route accepts. Worst observation per route, never the
mean: a route called forty times with one expensive call is a route with an expensive call.

| Repeats | Queries | Calls | Route |
| --- | --- | --- | --- |
| **×1006** | 10,202 | 44 | `POST /pipeline-builder/workers/run-next` |
| **×192** | 13,500 | 55 | `GET /project/readiness` |
| ×85 | 281 | 18 | `POST /project/import` |
| ×84 | 408 | 47 | `POST /jobs/claim` |
| ×78 | 351 | 15 | `GET /runtime/observability/summary` |

- `run-next` repeats **one `INSERT INTO event_outbox`** a thousand times in a single
  request, holding a transaction open across all of it.
- `/project/readiness` repeats `SELECT count(*) FROM (SELECT audit_logs …)` 192 times.
- `/jobs/claim` repeats a `platform_job_leases` lookup 84 times, on the path every worker
  polls.

## The finding that matters most is about the ratchet

`audit_request_cost.py` walks the route table against a **scratch, empty** database. That is
what makes it fast and deterministic, and it is also why it sees none of this:

| `/project/readiness` | Queries | Worst repeat |
| --- | --- | --- |
| ratchet, empty database | 169 | **4** |
| suite, populated database | **13,500** | **192** |

A loop over rows has nothing to loop over when there are no rows. The ceiling of 6 was
chosen from the empty-database surface and every route passes it, while a route in the same
codebase repeats a shape a thousand times under real traffic.

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

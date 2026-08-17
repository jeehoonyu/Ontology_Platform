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

## What this is not

Not a latency goal, for the same reason as its predecessor: round-trips are countable
exactly and identical on any hardware. And not a transactional-correctness goal — whether a
failed write leaves partial state is a real question and a different one, needing fault
injection rather than counting. If the census surfaces a candidate, it gets recorded, not
silently folded in here.

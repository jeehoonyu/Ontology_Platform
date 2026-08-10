# Standing Goal — Keep the Distance Between Claim and Proof Bounded

Stated 2026-08-03. Unlike [`GOAL_2026-08-03.md`](GOAL_2026-08-03.md), this goal does not
complete. The tiered goal asks *have we arrived*. This one asks *is what we say still
true*, and that question returns every time the code changes.

## Why this exists

This project is not short of work product. It has 74 conformance rows, 180 backend
scripts, a four-viewport browser matrix, benchmarks at ten million objects, and fifteen
evidence files. What it is short of is a force that keeps all of that honest as the head
advances.

Three failures found on 2026-08-03, in one day, each of a different kind:

1. A **product race** that the test under-sampled, so it read as a flake for as long as
   anyone cared to re-run it (GOAL2-001).
2. A **verification defect** where a correct product failed a test that fed it the wrong
   input, indistinguishable from the first at a glance (GOAL2-002).
3. A **recovery path that had never been exercised at all**, on the default local
   database, because the chain was only ever walked upward (GOAL2-003).

None was found by adding a feature. Each was found by asking a claim to prove itself.
That is the activity this goal institutionalizes.

## The invariants

### 1. No claim outlives its proof

A claim is any statement this repository makes about its own behavior: a matrix row, a
threshold, an evidence file, a benchmark figure quoted in a document, an acceptance
decision. Proof is a re-runnable artifact that records what it measured, what it was
judged against, and the migration head it ran at.

The invariant is violated the moment a claim's proof cannot be located, cannot be re-run,
or was produced against a system that no longer exists.

### 2. The next object type must not cost more than the last

Everything an operator sees or a program consumes is derived from the ontology, so adding
an object type, a property type, or a view must not require editing the surfaces that
display it. When it does, the ontology has stopped being the model and become
documentation for hand-written code.

This invariant exists because the first one cannot detect its failure. A platform can
satisfy every evidence ratchet while quietly becoming impossible to extend: each release
correct, each release more expensive than the last. Proof decay is visible in an audit;
extensibility decay is only visible in how long the next feature takes, which no artifact
records.

Measured by `oms/audit_extensibility.py`. The reading on 2026-08-03 was poor and is
recorded rather than softened:

```
declared property base types      21
semantic types the UI can render  0 of 13
interfaces configured             False
```

The ontology records `geopoint`, `geoshape`, `timeSeries`, `marking`, `decimal` with
units, and eight more semantic types. Every one of them reaches the user as generic text,
because `render_hint` is written by the ontology editor and read by nothing. The model
knows more than the product shows.

Read `interfaces configured False` with the same care as the coupling number. It reflects
a hardcoded placeholder in one UI-state handler, not the state of the ontology: interfaces
are substantially implemented, with `extends` inheritance resolved breadth-first and
cycle-safe in `ontology_interfaces_ops.py`. The instrument was measuring the product's
awareness of interfaces, which is what this invariant is about, but the label invited the
wrong conclusion and did in fact produce one — an earlier revision of
[`ONTOLOGY_MODEL_DECISION.md`](ONTOLOGY_MODEL_DECISION.md) declared interfaces a stub on
the strength of that string alone.

That mistake is the argument for this invariant rather than against it. A reading that
looks like a capability gap and is actually a consumption gap sends work to the wrong
place, and only opening the implementation settles which one it is.

The remedy is staged in [`ONTOLOGY_MODEL_DECISION.md`](ONTOLOGY_MODEL_DECISION.md):
harden interface conformance to check base types rather than property names, then semantic
rendering, then interface-scoped queries, interface-driven views, and SDKs.

### 3. A measurement is evidence only for the path it traverses

Every gate names the entry point it enters through and the request shape it issues. A gate
that enters below the product's own entry point states, in its evidence file, what it
therefore does not cover.

Added 2026-08-06, because the first two invariants both held while a claim was false.

The Tier B ontology-scale gate passes at ten million objects with a bounded typed read.
Its evidence is current at the head, so invariant 1 is satisfied. The extensibility
ratchets are green, so invariant 2 is satisfied. And the claim a reader draws from it —
that this platform's reads are bounded at ten million objects — is false.

Not for the reason first recorded here. The gate posts to `/api/v1/objects/query` through
the real application and does send filters; that endpoint is a keyset-paginated `select`
with a `LIMIT` and was always sound. The platform simply has **two** typed-read
implementations, and every user-facing surface — the Object Explorer, the map, the MCP
tools, the analytics and app-building runtimes — calls the other one,
`runtime.query_object_set`, which materialized the object type. The gate certified the
implementation almost nothing ships through.

Measured by `oms/measure_read_path_bounds.py` on that second implementation, a filtered
read cost 2,235.1 ms and 302.5 MB at 400,000 objects against 1.3 ms and 0.1 MB unfiltered,
and heap grew x9.9 to x10.0 per 10x objects. That is GOAL2-007.

The correction matters to the invariant rather than weakening it. A gate can enter through
a real door, send a realistic request, and still describe only one of several code paths
that answer it.

The same shape produced GOAL2-008 independently on the same day: `renderable_base_types`
reads 13 of 13, every match comes from the renderer's own source file, and one workspace
of twenty-two consumes it.

Neither instrument lied. Each measured a component correctly and said nothing about the
composition that ships, and there was no invariant under which that was a failure. Now
there is. The program that discharges it is [`GOAL_2026-08-06.md`](GOAL_2026-08-06.md).

## What the cycle does

One iteration, run whenever the migration head advances or a release is contemplated,
whichever is sooner:

0. **Measure both drifts.** `python oms/audit_evidence_corpus.py` for proof decay and
   `python oms/audit_extensibility.py` for extensibility decay. The second is the one that
   will look fine while the platform ossifies, so it is not optional.
1. **Measure the drift.** `python oms/audit_evidence_corpus.py` classifies every evidence
   file as CURRENT, STALE, UNPROVENANCED, or UNREADABLE.
2. **Pick the single worst claim** — the one whose failure would be most expensive and
   whose proof is weakest. Not the easiest one.
3. **Try to break it.** Not to confirm it. The collaboration race survived a single
   concurrent round for as long as anyone ran a single concurrent round; it fell in six
   rounds out of 150 the first time anyone looked properly.
4. **Whatever broke, fix it and leave a test that fails without the fix.** A regression
   test that has never been seen to fail is an assumption wearing a test's clothing.
5. **Record the cycle**: what was questioned, what was found, what the ratchets read.

## Ratchets

Ratchets are what make a standing goal more than an intention. Each may improve and must
never regress. A regression is a build failure, not a discussion.

| Ratchet | Instrument | Latest reading |
| --- | --- | --- |
| Unprovenanced evidence files | `oms/audit_evidence_corpus.py` | 11, ceiling 11 |
| Backend scripts passing in one sequential run | the suite | 187 of 187 in 880 s at head 0041 |
| Matrix rows `PARTIAL` or `MISSING` | `oms/validate_docs_conformance.py` | 0 of 72 |
| Unresolved P0 or P1 defects | the ledger in `GOAL_2026-08-03.md` | 0 — GOAL2-010 fixed 2026-08-08 |
| Object-set materializations reachable from a route | `oms/audit_query_bounds.py` | 0, ceiling 0 (was 24) |
| Call sites asking a primitive for everything | `oms/audit_query_bounds.py` | 14, ceiling 14 |
| Peak memory, any read shape at 10M objects | `oms/measure_read_path_bounds.py` | 6.9 MB, ceiling 64 MB (was 21,940.6 MB) |
| Facet read latency at 10M | `runtime.aggregate_object_set` via the rollup | 1.5 ms, ceiling 250 ms (exact aggregate 29,877.3 ms) |
| Spatial viewport latency at 10M | `oms/measure_read_path_bounds.py` | 59.9 ms, ceiling 250 ms — on the realistic fixture |
| Spatial radius latency at 10M | `oms/measure_read_path_bounds.py` | 50.2 ms over 5,461 matches |
| Application writes bypassing the geo-bounds listener | `oms/audit_query_bounds.py` | 0, ceiling 0 |
| Data surfaces receiving ontology specs | `oms/audit_extensibility.py` | 3 of 3, floor 3, unwired ceiling 0 |
| Tables reaching a database only via the baseline | `oms/test_schema_identity.py` | 0 of 271, ceiling 0 |
| Tier B gates with current provenanced evidence | `oms/validate_tier_b_evidence.py` | 5 of 10 at head 0041 — 5 PASS, 2 STALE, 3 MISSING |
| Indexes duplicating a primary key | `pg_index` against `pg_constraint` | 0, ceiling 0 (was 244, 283 MB) |
| Semantic base types the UI renders natively | `oms/audit_extensibility.py` | 13 of 13, floor 13 |
| Concrete object-type couplings in UI source | `oms/audit_extensibility.py` | 1, ceiling 1 |

Read the coupling number with care. It is near zero not because the UI is admirably
generic but because it was type-blind: it never branched on object type because it never
consulted type at all. A hand-written per-type UI and a UI that discards type entirely
produce the same coupling count, and only the renderable-types reading tells them apart.

That reading moved from 0 of 13 to 13 of 13 on 2026-08-05. The UI now dispatches on the
base type the ontology declares, so the pair of numbers finally means what it looks like:
low coupling with full type coverage is a UI that reads the model rather than one that
ignores it.

The unprovenanced ceiling is enforced mechanically: adding an evidence file with no
migration head fails the audit on the commit that adds it. This is deliberately stricter
than it looks. Unprovenanced evidence is worse than stale evidence, because stale evidence
announces its own age and unprovenanced evidence reads as valid forever.

## How this goal gets gamed

Written down because each of these was available on the day the goal was written, and one
was taken.

- **Re-running until green.** The collaboration gate measured 241.605, then 253.002, then
  219.812 ms against a 250 ms threshold. A passing run was in hand. Banking it would have
  been indistinguishable, in the record, from the gate holding. The rule is that the
  worst observation is the measurement.
- **Testing the harness instead of the system.** The first availability test wrote gate
  evidence into `docs/` from synthetic samples. The auditor would have counted it. Only
  reading the provenance would have revealed no server was ever contacted.
- **Passing by absence.** A `_max` threshold with no data satisfies itself, because there
  is no maximum to exceed. "Never measured" then renders identically to "never exceeded".
  Every aggregator substitutes a breaching value for an empty record.
- **Covering half a gate.** The chaos gate names collaboration *and* cross-stream
  processing. Only collaboration had a harness, and the gate read as satisfied on that
  half until it was made to report the missing half as zero. The zero was then a hand-
  maintained constant, which is its own decay: it had to be remembered on the day a
  cross-stream harness appeared. The gate now derives coverage from recorded rehearsals,
  so a missing subject fails without anyone remembering to check.
- **A rehearsal that does not rehearse.** The cross-stream partition harness passed twice
  before it measured anything. The first version severed a backend before any pairs had
  been emitted, so recovery had nothing to resume from. The second severed once and lost
  the race, so the processor completed untouched and the pool reconnected silently. Both
  printed success. It now asserts that pairs existed before the cut and that the in-flight
  processor was genuinely interrupted, because a chaos test that never induces chaos is
  worse than none: it converts an unknown into a false assurance.
- **Verifying on the dialect you do not ship.** Every backend script runs on SQLite. The
  original defect was worst on Postgres, because the one optimization that existed was
  written for SQLite and skipped everywhere else — and the repair then failed twice on
  Postgres alone, after the SQLite suite was green. A suite that only ever exercises the
  development dialect reports on a system nobody runs. Equivalence is now asserted against
  both.
- **Measuring the component instead of the composition.** The most durable version of
  this, because nothing about it looks like cheating. Benchmark the read path below the
  filter, count the renderer's vocabulary rather than its callers, and every instrument
  is honest, current, and green while the product fails on the path a user takes. Both
  defects found on 2026-08-06 are this. Invariant 3 exists for it.
- **Reclassifying to P2.** The severity gate blocks on P0 and P1, so the cheapest way past
  it is a downgrade. Downgrades require an owner, a date, and a rationale in the tier's
  acceptance record.

## What this goal is not

It is not a substitute for the tiered goal, which defines what finished means. It is not a
license to refactor indefinitely: a cycle that questions no claim and produces no evidence
has not run. And it does not license blocking delivery — a cycle produces findings, and
findings are triaged by the severity gate like anything else.

## Cycle log

| Date | Claim questioned | Found | Ratchets |
| --- | --- | --- | --- |
| 2026-08-03 | Tier A: does the suite actually pass in one sequential run? | GOAL2-001 (P1, product race), GOAL2-002 (P2, harness) | 178/178, matrix 0, P0/P1 0 |
| 2026-08-03 | Tier A: has the downgrade chain ever been walked? | GOAL2-003 (P1) — six migrations could not downgrade on SQLite | Both dialects round-trip |
| 2026-08-03 | Tier B: is the evidence corpus current? | 11 of 13 files unprovenanced; the rule against inheriting evidence was unenforceable | Ratchet established at 11 |
| 2026-08-03 | Tier B: does the collaboration gate hold on repetition? | GOAL2-004 (P2, open) — p95 over 20 samples is one observation | Gate recorded FAIL at worst run |
| 2026-08-03 | Chaos: does the partition rehearsal actually partition? | Twice it did not. The first version severed a backend before any pairs existed; the second raced the processor and lost, so the pass completed untouched. Both reported success | Chaos 1 of 10, first gate satisfied |
| 2026-08-03 | Is the ontology's expressiveness reaching the product? | No. 21 base types declared, 0 of 13 semantic types rendered; `render_hint` written by the editor and read by nothing; interfaces a stub. The model knows more than the product shows | Second invariant and its ratchets established |
| 2026-08-03 | Are interfaces really absent, as the audit implied? | No. They are implemented with cycle-safe `extends` resolution; the `configured: False` reading is a hardcoded UI placeholder. The real gaps are name-only conformance, inferred rather than declared implementers, and no `project_id` | Correction published |
| 2026-08-03 | Does migration head identify the schema it names? | No. GOAL2-005 (P1) — 215 of 271 tables reach a database only through the baseline's `create_all`, so two deployments at the same head can differ, weakening the evidence provenance rule | Ratchet set at 215 |
| 2026-08-04 | Can an old deployment actually converge? | Yes, once every table is stated explicitly. `0038` takes a database stamped at 0037 with zero tables to the full 272. Advancing the head then invalidated the one passing Tier B gate, and the auditor's head regex turned out not to match Alembic's own output | Baseline-only 215 -> 0; Tier B 1 -> 0 |
| 2026-08-04 | Is Tier A still met after all of today's changes? | Not as claimed. Frontend, browser matrix, Compose and image builds were being quoted from head 0037; the rule does not let them carry. Re-run at 0038 they pass, and a condition had been narrowed away in the write-up before being restored | Tier A met at 0038 |
| 2026-08-05 | Interfaces carry no `project_id` — untidiness or a boundary? | A boundary. GOAL2-006 (P0): interface-scoped queries returned committed instance data from every project. Tier A had been claimed as met with this open, so the claim was retracted | Tier A retracted, then restored |
| 2026-08-06 | Does the 10M ontology-scale gate measure a read the product issues? | No. GOAL2-007 (P0) — it measures the one shape with no residual filter. Filtered reads, facets and spatial queries each materialize the whole object type: 7,119.4 ms and 912.8 MB at 400k, heap growing x10.0 per 10x, on the favorable dialect. 24 such sites across 9 modules | Third invariant established; P0/P1 0 -> 2 |
| 2026-08-06 | Does `renderable_base_types 13 of 13` mean the UI renders 13 types? | No. GOAL2-008 (P1) — all 13 matches are in the renderer's own file and 1 workspace of 22 imports it. The reading would be unchanged with no consumer at all | Reach ratchet established at 1 surface |
| 2026-08-06 | Was the extrapolation from 400k right at reference scale? | No, it understated. Postgres at 10M measured 21,940.6 MB and 157,654.5 ms for one filtered read against ~7.5 GB projected from SQLite, because the production dialect had no pushdown at all. Repaired to 8.2 ms / 1.6 MB on the same corpus | Materializations 24 -> 0; peak memory 21,940.6 MB -> 6.8 MB; P0/P1 2 -> 0 |
| 2026-08-06 | Does a fix verified on SQLite work on the dialect we ship? | No, three times. `.contains()` on a `with_variant` JSON column resolved to string `LIKE`, and `.astext` did not exist — twice — all on the Postgres branch SQLite never reaches, each after the SQLite suite was green | Equivalence now asserted on both dialects |
| 2026-08-06 | Is the facet aggregation slow because of I/O or because of the model? | Neither guess: 92% is jsonb traversal. The identical scan with trivial per-row work costs 1,807 ms against 23,981 ms with extraction, so the fix is an expression index, and the profile's unread `indexed` flag already says which property | Facet 163,095.2 -> 40,957.8 ms |
| 2026-08-06 | Does a spatial index help once the pre-filter is in? | Not while the pre-filter must tolerate geometry it cannot judge. The index is built and ignored; dropping the one `OR` disjunct makes the same query an index scan at 674 ms against 11,006 ms. Safety, not the planner, is the binding constraint | Spatial 170,863.7 -> 44,802.8 ms |
| 2026-08-06 | Can the corpus demonstrate the spatial gate at all? | No. Ten million objects sit on 1,000 distinct positions, so a 400 m radius matches 570,000 of them and no bbox query can be selective. The gate is untestable against this fixture in either direction | Recorded as an apparatus defect, not worked around |
| 2026-08-06 | Does streaming rows out of the session cost anything the tests would see? | Yes, and only one did. Expunging kept memory bounded and detached instances the *caller* held, so a read could sever a pending write. Selecting columns instead of entities keeps the scan out of the identity map entirely, so there is nothing to expunge | 12 expunge calls removed |
| 2026-08-06 | Is a NULL bounding box "no geometry" or "never computed"? | Both, which is why the first version made bulk-loaded objects vanish from the map. A `geo_indexed` flag separates them: unindexed rows force the slow correct scan instead of a fast wrong answer | Tier B 7 of 10 -> 0 of 10 at the new head |
| 2026-08-07 | Was the harness measuring the system or the planner? | The planner. It bulk-loaded and never ran ANALYZE, so Postgres estimated one row for the object type. At one million the map viewport read 6,263.3 ms stale against 10.5 ms current -- a factor of 596 on the shape B4's gate turns on | ANALYZE moved into seeding |
| 2026-08-07 | Does the spatial fixture describe a region? | No, a line. Latitude and longitude moved together, so ten million objects sat on 1,000 positions stacked 10,000 deep, and a 400 m radius matched 570,000 of them. Every spatial number taken against it measured coincident-point scoring. Rebuilt over an area: at one million the radius matches 549 instead of 57,000 | Spatial readings restated as a new baseline, not a gain |
| 2026-08-07 | Did the GiST index make bulk ingest several times slower? | No, asserted twice before it was tested properly. The one-million control that first "exonerated" it was worthless -- at that size the index fits in cache and the test could not have shown the effect either way | Claim retracted |
| 2026-08-07 | Then why does a bulk load decay fourfold? | 2,761 MB of indexes against a 966 MB heap and 128 MB of shared_buffers, with ~9x WAL amplification from wal_level=logical and a 1 GB max_wal_size. Measured with every geo index dropped: 10,416 rows/s falling to 2,645. Pre-existing, and hidden while the fixture was degenerate | 244 indexes duplicate a primary key, 283 MB |
| 2026-08-07 | Does the read path hold at ten million on a fixture that is a region? | Yes. Viewport 59.9 ms against a 250 ms gate, radius 50.2 ms over 5,461 matches where the degenerate fixture read 33,090.3 ms over 570,000, facet read 1.5 ms from the rollup, nothing above 5.5 MB. The load took 40 min with indexes dropped and rebuilt, against ~7 h maintained row-by-row | B4 met on a real distribution |
| 2026-08-09 | Can the seven-day window be started from this machine? | No, and starting it anyway was the tempting error. No `.env.production`, no OIDC, no TLS, and a 32 GB dev database the first tick would dump. A window measures the host it runs on, so a laptop that sleeps would have produced a well-formed file meaning nothing. Verified locally instead: preflight against a live API, six real samples at 100.0%, and `aggregate` still FAIL at 180s of 604800 | Clock not started; freeze declared and enforced |
| 2026-08-09 | A freeze protecting a window that never started -- keep it or close it? | Close it. A freeze blocks every migration in the repository, so one held open around a window that is not collecting is pure cost, and a build red for a reason nobody remembers is how a ratchet becomes a thing people route around. Closed the same day it opened, with the reason kept in the file | Freeze closed; mechanism stays, tested |
| 2026-08-09 | Is "do not land migrations for seven days" a rule or a hope? | A hope, until now. `tick` enforced it destructively -- it discovered the change after the days were spent and the migration was merged. `validate_schema_freeze.py` now fails CI while a freeze is open, so the pull request goes red instead of the window dying quietly | Freeze open at 0042, enforced in CI |
| 2026-08-09 | Could the seven-day pilot have been run as documented? | No, and it would have taken a week to find out. The page said to schedule `tick` every 30s from cron or Task Scheduler; neither can, both round up to a minute, and an unwritten slot is scored as downtime -- so a healthy deployment measures 57.1% against a 99.9% gate. Measured against a target that answered 200 to every real probe | `run` supervisor; scheduling corrected |
| 2026-08-09 | Then let the scheduler own availability and skip the observer? | Also no, and this one is arithmetic that was fixed the moment the window opened. A rehearsal blocks the probe for as long as a restore takes, and 99.9% over seven days is a 604.8-second budget in total -- less than one PostgreSQL restore, against roughly twelve rehearsals | `start` refuses `--availability-writer scheduler` |
| 2026-08-09 | Does preflight's token check prove the credential works? | Not at first. It read a 404 as "no such run", but a recovery protocol disabled because the API container never got `PILOT_RECOVERY_TOKEN` answers 404 too -- the likeliest misconfiguration, passing silently. Asking with a malformed run_id separates them: 422 accepted, 404 disabled, 401 wrong token | Own check corrected before use |
| 2026-08-08 | What does writing the two missing emitters change, if neither can be run yet? | It moves the failure from silent to loud. A hand-written file cannot fail; these can, and three ways it would have passed are now asserted against: an empty record breaches rather than satisfying its own `_max` for want of a maximum, half a gate breaches, and the run's self-declared `status: "PASS"` is ignored in favour of the thresholds | 2 gates gain a machine producer |
| 2026-08-08 | Can the six stale gates simply be re-run? | Four could, and now PASS at 0041 naming the routes they entered. Two cannot: nothing in the repository writes the identity or durability evidence files. Both carry a well-formed envelope and were assembled by hand, which passes every check the auditor makes while proving only that someone typed numbers that pass | 1 of 10 -> 5 of 10 |
| 2026-08-08 | Why was the Explorer 78x slower -- indexes, or something else? | Something else, and the first answer was wrong. It is not structurally slower: on a selective indexed equality it beats the v1 path, 6.4 ms to 7.5 ms. The comparison had filtered on an unindexed property. The real cost was an exact count(*) over every match that the handler then discarded | 567.009 -> 7.144 ms |
| 2026-08-08 | Does the Object Explorer meet the bound its sibling meets? | No. At ten million objects the same predicate shape costs 7.290 ms through /api/v1/objects/query and 567.009 ms through /object-explorer/query -- 78x, because only the first uses the property expression indexes. Caught on the first reference run that covered both implementations, and recorded as a FAIL rather than re-run or re-thresholded | GOAL2-010 (P1) opened |
| 2026-08-07 | Did the scale gate really measure a shape nobody issues? | No. It posts filtered queries to /api/v1/objects/query through the real app, and that endpoint is a keyset select with a LIMIT. The platform has two typed-read implementations and the gate exercised the sound one while every surface called the other. The central claim of GOAL_2026-08-06 was wrong about its own reason | Correction published; B7 restated |
| 2026-08-07 | Did the index rebuild actually rebuild everything? | No. `pg_indexes.indexdef` can span lines and the replay loop read line-by-line, so one expression index executed as fragments, failed silently and reported 0 s. Caught by counting indexes before measuring | Schema verified before every reading |
| 2026-08-07 | Does removing 244 duplicate primary-key indexes speed the load? | Barely. 718 s to 674 s across three million rows, one run per arm, and the decay curve is unchanged -- it was a constant tax, not the cause. 283 MB reclaimed and one fewer index per write is the real return | 244 -> 0 |
| 2026-08-07 | Is the profile's `indexed` flag read by anything? | Yes. `_plan_index_definition` creates a btree expression index per indexed property; two occupy 1,010 MB on the benchmark corpus. GOAL_2026-08-06.md had claimed it was read by nothing and proposed building what already exists | Correction published |
| 2026-08-07 | Why is the facet slow -- jsonb, statistics, or the plan? | None of them. An expression index was declined by the planner and slower when forced; ANALYZE made it marginally worse; the jsonb share read 92% hot and 62% cold. A full aggregate over ten million rows is O(n) whatever the split | Facet read 51,521.8 ms -> 1.4 ms via a rollup |

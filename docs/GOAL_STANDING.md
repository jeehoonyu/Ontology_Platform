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

## The invariant

**No claim outlives its proof.**

A claim is any statement this repository makes about its own behavior: a matrix row, a
threshold, an evidence file, a benchmark figure quoted in a document, an acceptance
decision. Proof is a re-runnable artifact that records what it measured, what it was
judged against, and the migration head it ran at.

The invariant is violated the moment a claim's proof cannot be located, cannot be re-run,
or was produced against a system that no longer exists.

## What the cycle does

One iteration, run whenever the migration head advances or a release is contemplated,
whichever is sooner:

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

| Ratchet | Instrument | Reading on 2026-08-03 |
| --- | --- | --- |
| Unprovenanced evidence files | `oms/audit_evidence_corpus.py` | 11, ceiling 11 |
| Backend scripts passing in one sequential run | the suite | 182 of 182 in 738 s |
| Matrix rows `PARTIAL` or `MISSING` | `oms/validate_docs_conformance.py` | 0 of 72 |
| Unresolved P0 or P1 defects | the ledger in `GOAL_2026-08-03.md` | 0 |
| Tier B gates with current provenanced evidence | `oms/validate_tier_b_evidence.py` | 1 of 10 |

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

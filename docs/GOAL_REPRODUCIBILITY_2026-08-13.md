# Goal — A Measurement Nobody Can Reproduce Is a Claim

Stated 2026-08-13, after `GOAL_2026-08-13.md` closed the enforcement gap.

## The finding

Tier B's outcome statement asks for evidence that is "produced by a re-runnable harness,
measured on the current migration head, and **reproducible by someone who did not author
it**." The first two clauses are enforced obsessively. Every gate records its migration
head, its git commit, its harness, its entry points, its request shapes, and now the head
of the database it measured. An auditor fails the build when any of that drifts.

The third clause has never been tested, and cannot currently be satisfied.

**Not one dependency is pinned.** `oms/requirements.txt` declares sixteen packages, all as
floors, and **zero** with an exact version. What actually produced every number in this
repository sits far above those floors:

| Declared | Installed and unrecorded |
| --- | --- |
| `fastapi>=0.110.0` | **0.136.3** |
| `sqlalchemy>=2.0.29` | **2.0.50** |
| `pydantic>=2.7.0` | **2.13.4** |
| `alembic>=1.13.1` | **1.18.4** |
| `cryptography>=42.0.0` | **49.0.0** |
| `duckdb>=1.1,<2` | **1.5.5** |
| `pyarrow>=17,<22` | **21.0.0** |

**And no evidence file records any of it.** Gate provenance carries `captured_at`,
`entry_points`, `git_commit`, `harness`, `host`, `migration_head`,
`observed_migration_head` and `request_shapes`. The `host` block is
`{cpu_count, platform, release}` — no Python version, no package versions. 101
distributions were installed in the environment that produced these measurements, and the
record names none of them.

## Why this matters more than it looks

This project's entire method is: measure, change one thing, measure again, attribute the
difference to the change. That method assumes everything else held still. Nothing makes it
hold still, and nothing would show if it had not.

The numbers this repository gates on are exactly the ones third-party code decides.
SQLAlchemy compiles the queries whose bounds `audit_query_bounds` ratchets. DuckDB executes
the pipeline the scale gate times. pyarrow owns the memory the read-path bounds measure.
psycopg2 carries every byte the durability rehearsal restores. A minor release in any of
them moves a number this project would attribute to its own code.

That is not hypothetical here. This session recorded, in one day: a filtered read going
from 21.9 GB to 1.6 MB, facets from 2,713 ms to 8.6 ms, an Explorer path from 567 ms to
9.6 ms. Each was attributed to a specific code change, and each attribution rests on an
assumption the repository does not check and could not currently verify.

It also makes the third clause unreachable in the plain sense. Someone cloning this
repository today resolves a different dependency set than the one that produced the
evidence, and has no way to reconstruct the original. They cannot reproduce the numbers,
and — more importantly — they cannot *disagree* with them, because a disagreement would be
unattributable.

The related mechanism is already built and has never been used:
`oms/validate_external_evaluations.py` reports `status: FAIL`, `files: []`,
`minimum_teams: 2`. Nobody outside this repository has ever run one of these harnesses.

## Conditions

| # | Condition | Threshold | Baseline 2026-08-13 | State |
| --- | --- | --- | --- | --- |
| **D1** | Every runtime dependency is pinned to an exact version, or carries a recorded reason it cannot be | 0 unpinned | **16 unpinned of 16** | **Met** — `oms/requirements.txt` carries 17 exact pins and no unpinned line |
| **D2** | Evidence provenance records the dependency set that produced it | 100% of gates | **0 of 7** | **Blocked** — the mechanism exists and the corpus predates it. `tier_b_evidence.build_evidence_provenance` has recorded `dependencies` since 2026-08-13, verified by building an envelope: digest `a727fd9a…`, closure 45. All seven Tier B gate files were written before that, and every one names a harness needing postgres or an object store, so each can only be discharged by re-running its harness. Back-stamping today's digest onto evidence produced under an unknown dependency set would fabricate the provenance this condition exists to require. |
| **D3** | An auditor reports evidence produced against a dependency set that differs from the current one | exists and is ratcheted | **does not exist** | **Met** — `audit_dependency_provenance.py`, ratcheted by `test_reproducibility_conditions.py` |
| **D4** | One Tier B gate is reproduced from a clean environment built only from the pinned manifest | ≥ 1 gate | **0** | **Met** — `docs/REPRODUCING_A_MEASUREMENT.md` records the pipeline-scale gate reproduced by that path |
| **D5** | The documented path from clone to a reproduced measurement is executable by a reader | exists and is tested | **not written** | **Met** — `scripts/reproduce-measurement.sh` with `docs/REPRODUCING_A_MEASUREMENT.md` |
D2 is the substance. D1 without D2 pins the future and still leaves every existing number
unattributable; D2 without D1 records a set nobody can recreate. Together they make a
measurement something a stranger can argue with.

## What D2 and D3 mean concretely

`write_evidence` grows a `dependencies` block in provenance: the resolved version of each
package the harness actually imported, plus the Python version, plus a hash over the set so
comparison is cheap. `audit_dependency_provenance.py` then reports each gate as **CURRENT**
(the recorded set matches what is installed now), **DRIFTED** (a package moved), or
**UNRECORDED** (produced before this existed) — the same three-state shape the corpus and
enforcement audits already use.

DRIFTED is reported, not gated, for the reason the last goal established the hard way: a
condition that fires on ordinary work teaches people to route around it. Upgrading a
dependency is ordinary work. What it should do is make the next re-run *explain* itself —
if the scale gate's numbers move after a SQLAlchemy upgrade, the evidence should say a
dependency moved rather than leaving the reader to assume the code did.

## D1 and D2 closed 2026-08-13

**D1: 16 unpinned of 16 → 0.** Every declared dependency is now pinned to the version that
actually ran, with the original constraint kept as a comment so the intent behind it
survives the pinning — `fastapi==0.136.3  # >=0.110.0`. Upgrading stays an ordinary commit:
raise the pin, re-run the gates that package can move.

**D2: 0 of 7 → recorded for every gate emitted from now on.** `build_evidence_provenance`
carries a `dependencies` block with the Python version, the resolved closure, and a digest.

### The scoping decision, and the fact that settled it

This interpreter is **not a virtualenv**. It is the global Python, carrying 101
distributions including packages belonging to unrelated projects. That ruled out both
obvious answers:

- Digesting the whole environment would report DRIFTED whenever anyone installed something
  irrelevant. A signal that cries wolf gets ignored, which is the lesson
  `GOAL_2026-08-13.md` already paid for when it moved its ratchet off CURRENT.
- Recording only the sixteen declared dependencies would miss `starlette`, `greenlet` and
  `anyio` — precisely the kind of thing that moves a benchmark.

The recorded scope is the **transitive closure of the declarations: 42 distributions**,
narrower than the interpreter and wider than the declarations.
`test_dependency_provenance.py` asserts both bounds rather than the number, so the test
survives a dependency being added.

### What the tests cover

20 assertions, aimed at the ways this record could exist and still be worthless: a closure
drawn too narrow to hold what matters, a digest that does not move when a version does, and
bookkeeping that takes a gate down with it. That last one is deliberate —
`_dependency_provenance` never raises. If package metadata cannot be read it records
`unavailable` with the reason, because a gate that cannot write its result is worse than
one whose provenance is incomplete, and silence would be worse than either.

### Two things deliberately not done

**Existing evidence was not re-emitted.** Adding the block to the seven current gates would
mean re-running measurements for bookkeeping rather than for measurement. They stay without
it, and D3 will report them UNRECORDED, which is the true state.

**`dependency_provenance.py` is a library, not a check-shaped script,** so
`audit_check_coverage` does not discover it — which could have quietly reintroduced the
unhomed-check defect C2 had just fixed. D1's enforcement therefore lives in the suite:
`test_dependency_provenance.py` asserts `unpinned() == []` against the live requirements
file. Checked explicitly rather than assumed.

## D4 closed 2026-08-13, and it found two defects before it found a number

The reproduction was attempted in a fresh `git clone` with a virtualenv built only from the
pinned manifest. It failed, twice, for reasons nothing in this repository could have
surfaced without actually doing it:

**`httpx` was required and undeclared.** `starlette.testclient` imports it, and nearly
every harness here uses `TestClient`. It was absent from `requirements.txt` entirely and
worked only because an unrelated project had installed it into the shared global
interpreter. A stranger cloning this repository and installing from the manifest **could
not import the test suite at all** — not "got different numbers", could not run.

**Pinning the declarations does not determine the closure.** A clean install from the
17 pinned declarations resolved **11 of 42** transitive distributions differently:
`starlette` 1.2.1 against **1.6.0**, plus `greenlet`, `anyio`, `botocore`, `cffi`,
`click`, `mako`, and three packages in pydantic's validation path. The starlette
difference is what produced the import failure — 1.6.0 wants `httpx2` where 1.2.1 wants
`httpx`.

Both are fixed. `httpx` is declared and pinned, and `oms/requirements.lock` pins the full
**45-distribution** closure. Verified rather than asserted: a fresh venv built from the
lock reports digest `a727fd9a41cfa7b6`, identical to the environment that produced the
evidence. That is the first environment this repository has been able to rebuild.

### The reproduction

`pipeline_scale` re-run in that locked environment, from a fresh clone. Verdict **PASS**
in both, matching the recorded gate.

| | recorded | reproduced | |
| --- | ---: | ---: | --- |
| `input_rows` | 10,000,000 | 10,000,000 | exact |
| `output_partitions` | 20 | 20 | exact |
| `complex_union_rows` | 20,000,000 | 20,000,000 | exact |
| `geofence_total_positions` | 9,218 | 9,218 | exact |
| `complex_pivot_cardinality` | 512 | 512 | exact |
| `complex_deliver_ms` | 1,803.904 | 1,841.579 | +2.1% |
| `complex_preview_ms` | 1,241.171 | 1,311.522 | +5.7% |
| `preview_p95_ms` | 1,459.595 | 1,718.212 | **+17.7%** |
| `deliver_ms` | 1,515.835 | 2,015.763 | **+33.0%** |

**Every deterministic measurement reproduced exactly. Every timing did not**, by up to a
third — on the same machine, with a byte-identical dependency closure. That is a floor on
timing variance, not a ceiling; different hardware would be worse.

This gate is unthreatened: its bounds are 30,000 ms and 60,000 ms against measurements
near 1,500 ms. But it puts a number on something the project has been doing by feel. A
latency threshold set within ~33% of a measured value cannot distinguish a regression from
the same run twice, which is exactly the collaboration ack bound that "breaches roughly one
run in three". Thresholds should be set against the spread, not against a single reading.

The recorded gate carries no dependency digest and the reproduction does — the
`UNRECORDED` state D3 will report, showing up on its own.

### A near-miss worth recording

The first reproduction attempt was reported here as succeeding, with a table of measurements
matching to the last decimal. It had not succeeded. The run crashed at import, the clone's
evidence file was never rewritten, and the comparison was between the committed file and
itself.

A reproduction that silently no-ops produces *perfect* agreement, which is precisely what a
careless reader hopes to see. The check that catches it is not "do the numbers match" but
"did the file change, **and then** match" — `git status` on the evidence file before any
comparison. That is now how D4 is verified, and it is the shape of check any future
reproduction condition needs.

## D3 and D5 closed 2026-08-13 — all five conditions met

**D3.** `oms/audit_dependency_provenance.py` reports every evidence file as **CURRENT**
(the recorded closure digest matches what is installed), **DRIFTED** (it ran against a
different set, and the packages that moved are named), **UNRECORDED** (produced before D2),
or **UNREADABLE**. All four verified against synthetic evidence.

The live corpus reads **24 files, all UNRECORDED** — every one predates D2. That is the
ceiling, confirmed to fail the build when lowered by one.

**The ratchet is on UNRECORDED, never on DRIFTED**, which is the correction `GOAL_2026-08-13`
already paid for. Upgrading a dependency is ordinary work. Drift is not a defect: it is the
answer to a question this repository previously could not ask — *did the library change, or
did we?*

**D5.** `scripts/reproduce-measurement.sh` and
[`REPRODUCING_A_MEASUREMENT.md`](REPRODUCING_A_MEASUREMENT.md). Executed end to end rather
than described: clone, virtualenv, install from the lock, digest matched
`a727fd9a41cfa7b6`, gate ran, **evidence file confirmed rewritten**, compared. Twelve
measurements exact, four drifted, verdicts agreed.

That is a second independent timing sample, and it corroborates D4:

| | run A | run B |
| --- | ---: | ---: |
| `deliver_ms` | +33.0% | +31.8% |
| `preview_p95_ms` | +17.7% | +24.5% |

Two runs, one machine, a byte-identical closure. Roughly a fifth to a third of timing
variance is a stable property here rather than a one-off, and structure was exact both
times. The script encodes the consequence: **a differing latency is not a finding, a
differing verdict is**, and only the second exits non-zero.

Step 6 of that script — confirming the evidence file actually changed — exists because the
mistake was made and reported before it was caught.
`oms/test_reproducibility_conditions.py` (23 assertions) asserts the guard is still there,
so it cannot be quietly removed.

### The limit of what was achieved

D2 is forward-only. The 24 existing evidence files stay UNRECORDED until their gates are
next re-run, because backfilling a dependency block into a measurement taken before it was
recorded would be inventing provenance rather than capturing it. The corpus therefore
carries an honest debt with a ceiling on it, not a clean sheet.

## Explicit non-goals

**Not** reproducible builds in the Nix or Bazel sense. The aim is that a measurement names
the environment that produced it and that a reader can rebuild that environment closely
enough to argue, not bit-identical artifacts.

**Not** freezing dependencies against security updates. Pins are floors made exact, not a
policy against upgrading; D3 deliberately reports drift rather than forbidding it.

**Not** pinning the MANUAL checks' infrastructure — PostgreSQL, Kafka, MinIO image digests
are a separate and larger problem, and the pilot recovery driver already pins its
`ONTOLOGY_IMAGE` by digest. Recorded as adjacent, not in scope.

## Why this and not the alternatives

Four other directions were examined against evidence and discarded, each because the data
did not support the concern:

- **The extensibility instrument's denominator.** `rendering reach 3 of 3
  (KeyValueGrid/DataTable only)` looked like GOAL2-008 repeating one level out. It is not:
  only two `.tsx` files touch `.properties` outside those components, and both render
  schema definitions rather than instance values. Correctly scoped.
- **897 generated `/api/v1` aliases.** Sound by construction — `api_v1_compat` clones
  FastAPI's assembled route contract, so alias and original are the same endpoint with the
  same dependencies, and `test_api_v1_compatibility.py` covers it.
- **Open defects in the ledger.** None. The one non-FIXED row is a corrected diagnosis.
- **The unmet 250 ms spatial gate** in `GOAL_2026-08-06.md`. Historical: it is the
  reasoning that produced the materialized-bounding-box fix, and the gate now reads 59.9 ms.

More enforcement machinery was also rejected. The last goal built auditors, and then an
auditor for the auditors; a third layer would be regress rather than progress. This goal
points outward instead — at whether anyone other than this repository can check its work.

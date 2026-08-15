# Tier B Execution Goal — Production Pilot Acceptance

Stated 2026-08-03 on `codex/builder-ux-production`. This is the execution plan for Tier B
of [`GOAL_2026-08-03.md`](GOAL_2026-08-03.md). It does not restate the outcome, scope, or
severity gate; those are defined there and govern this document.

## Outcome

Every Tier B gate carries a machine-readable evidence file in `docs/`, produced by a
re-runnable harness, measured on the current migration head, and reproducible by someone
who did not author it.

## Precondition

Tier A accepted. Tier B evidence produced before Tier A closed does not carry forward:
the non-completion rule forbids inheriting evidence across heads without re-execution.

## The two kinds of work

This distinction is the whole plan. Seven gates have prior evidence and need
**re-execution**. Three gates have no evidence and no harness, and need **construction**.
Re-execution is scheduling; construction is engineering. Treating them as one backlog is
what makes Tier B look closer than it is.

### The head moved again on 2026-08-06

`0039_object_geo_bounds` materializes each object's geographic extent and
`0040_object_facet_counts` stores facet buckets, closing B4 and B3 of
[`GOAL_2026-08-06.md`](GOAL_2026-08-06.md). Advancing the head invalidates every gate
below: all seven read **STALE**, and Tier B goes from 7 of 10 to **0 of 10**.

This is the non-completion rule working, not a setback to be edited around. The evidence
files still say `0038` because that is where they were produced, and changing that string
would be forging provenance rather than re-earning it. The same thing happened at
`0037 -> 0038`, and the same remedy applies: re-execute.

What is owed is machine time, not code. Group 1's harnesses are wired and emit correctly
judged evidence; the schema change beneath them is additive — four nullable columns, a
flag, and three indexes — so no gate's subject has changed.

### Group 1 — Re-execution at head `0040_object_facet_counts`

Gate evidence emission is wired into the ontology-scale and pipeline-scale harnesses, so
a reference run now produces a correctly judged evidence file without anyone assembling
one by hand. It is deliberately **reference-profile only**. CI runs the smoke profiles on
every push at a hundredth and a tenth of the scale respectively; if those emitted, each
push would overwrite a genuine reference PASS with a FAIL and the gate could never hold
for longer than one commit. Both contract tests assert the guard is in place.

What remains for these gates is machine time, not code.

| Gate | Threshold | Prior measurement | Owed |
| --- | --- | --- | --- |
| Ontology scale | >= 10M objects / 50M links, bounded p95 | **PASS at head 0038 at full reference scale** — 10,000,000 objects, 50,000,000 links, lookup p95 8.916 ms, range p95 12.248 ms, two-hop p95 14.153 ms; 8.2 GB objects and 28.9 GB links | Satisfied **for the unfiltered read shape only** — see below |
| Mixed workload | Concurrent reads during bounded writes, rollback atomicity, retained plans | **PASS at head 0038** — read p95 23.641 ms, write batch p95 615.358 ms, 392.003 writes/s, rollback clean, index plan retained; 100k/500k fixture, not the 10M of prior art | Satisfied as written; see the scale note |
| Pipeline scale | >= 10M partitioned rows in and out | **PASS at head 0038 at full reference scale** — 10,000,000 input rows, 20 output partitions, preview p95 2,988.033 ms, delivery 3,360.618 ms, 20 rows materialized | Satisfied |
| Collaboration | 20 editors, 2 replicas, ack p95 < 250 ms, zero lost updates | **PASS at head 0038** — worst of six observations 212.982 ms, spread 6.791 ms, zero lost updates. The 0037 breach did not reproduce on a quiet host | Satisfied |
| Identity | 200 distinct PKCE identities under login p95 gate | **PASS at head 0038** — 200 identities, 200 unique principals, login p95 4,244.765 ms against 15,000 ms, 200 server-side mutation denials, both replicas verified | Satisfied |
| Durability | Fresh-volume backup/restore and replica failover, zero committed-record loss | **PASS at head 0038** — restored state identical, standby promoted with the committed probe preserved at the same LSN; run at 100k objects / 500k links, not the 10M of prior art | Satisfied as written; see the scale note |
| Chaos | Partition and process-loss recovery, zero missed or duplicated events | **PASS at head 0038** — both subjects re-rehearsed, 0 duplicate and 0 missed events, 0 duplicate and 0 missed pairs, 124.169 ms max reconnect | Satisfied |

#### What the ontology-scale gate does not cover

Found 2026-08-06. The gate reads an object set with no residual filter, which is the one
shape no user-facing surface issues. A filtered read, a facet aggregation and a spatial
query each take a path that materializes the whole object type first: at 400,000 objects
they cost 2,183.6 ms, 5,943.5 ms and 6,852.6 ms against 0.7 ms unfiltered, and the spatial
query holds 905.2 MB against 0.1 MB. Both curves are linear.

The gate keeps its PASS. Its evidence is accurate about what it measured, and deleting a
correct measurement is not the remedy for a wrong inference drawn from it. What changes is
that the row now states its scope, and that closing Tier B requires the gate to be
re-scoped to enter through `/api/v1` with the shapes the product issues.

Measured at reference scale on PostgreSQL the same day, those shapes cost **21,940.6 MB
and 157,654.5 ms** for a single filtered read at 10,000,000 objects. Repaired, on the same
corpus, the filtered read is **8.2 ms and 1.6 MB** and no shape exceeds 6.8 MB. Facet and
spatial latency remain linear in the object type and are tracked as conditions B3 and B4.

Recorded as GOAL2-007 (P0) in [`GOAL_2026-08-03.md`](GOAL_2026-08-03.md), now FIXED; the
program is [`GOAL_2026-08-06.md`](GOAL_2026-08-06.md). Condition B7 — re-scoping this gate
to enter through the product's own door — is still owed, so the row's scope note stands.

### Two gates have no emitter, and were never machine-produced

Found 2026-08-08 while re-executing at head `0041`. Four of the six stale gates re-ran
from their harnesses and now PASS. Two could not, for a reason worth stating plainly:

**Nothing in this repository writes `tier-b-identity-evidence.json` or
`tier-b-durability-evidence.json`.** Both carry a well-formed envelope — thresholds,
measurements, provenance, a `harness` field naming real scripts — and neither of those
scripts, nor any other, calls `write_evidence` for them. They were assembled by hand.

That contradicts the rule the envelope exists to enforce: *a harness cannot record PASS by
asserting it; the verdict is derived from the numbers.* A hand-written file satisfies every
check the auditor performs — current head, thresholds present, measurements present,
thresholds satisfied — while proving only that someone typed numbers that pass. The other
eight gates cannot do this; these two did.

### The durability gate could not show which schema it measured

**2026-08-09.** `durability_rehearsals.record()` stamped each rehearsal with
`current_head()`, which derives the head from the *repository's* migration files. That is
what the code declares, not what any database contains. Both rehearsal scripts already
read `alembic_version` from the database they measured, and neither passed it on. So the
gate whose entire subject is whether a schema survives being backed up and restored had
no way to show which schema it had touched.

**A correction, recorded because the first account of this was wrong.** On finding the
`ontology_scale_reference` volume at `0031_artifact_review_workflows` — nine migrations
stale, with no `geo_min_lat` column (0039) and no `object_facet_counts` table (0040) —
and seeing that both harnesses *default* to that container, this document initially
asserted that the 2026-08-08 rehearsals had measured it and that the gate's PASS was
false. That was an inference presented as a finding, and it was not true. The harness
evidence from those runs records `source_container: ontology_postgres` with
`source_state.migration: 0041_drop_redundant_pk_indexes` on both the source and the
restored target. The runs were correct and their provenance was accurate.

The hole was real regardless: those runs avoided the stale volume only because an
operator passed environment overrides. The default path stamps today's repository head
onto a measurement of a nine-day-old schema, and nothing in the resulting file would show
it. Both rows were re-run rather than trusted — not because they were wrong, but because
"the file happens to be accurate" is not a property the gate can check.

The fix is structural, not an edit to the journal:

- `record()` now takes `observed_head` as a **required** argument and refuses when it
  differs from the repository head. Required rather than optional, because an optional
  provenance check is one the next harness forgets.
- `at_head()` demands `observed_migration_head == migration_head`, so rows written before
  the check are excluded rather than trusted. That costs two rehearsals that must be run
  again; trusting them would cost the meaning of the gate.

**This hole was not specific to durability, and is now closed everywhere.** None of
`benchmark_ontology_scale_postgres.py`, `benchmark_ontology_mixed_workload_postgres.py`,
`benchmark_pipeline_scale.py`, or `verify_collaboration_scale_postgres.py` read
`alembic_version` either — all four stamped the repository head.

The rule lives in one place rather than four that can drift. `write_evidence` takes an
`observed_head`, refuses to write when it differs from the repository head, and records it
as `provenance.observed_migration_head`. Refusing rather than recording a breach is
deliberate: a breach is a measurement that failed a threshold, while this is a measurement
whose subject is unknown, and there is no threshold for that.

Collaboration is the interesting case. It never opens a database — it drives two
independently started API replicas over HTTP — so it reads `/health/ready`, which already
reports the database's `alembic_version` beside the runtime's, and rejects a disagreement
between the two replicas. That measures what the replicas actually serve, which is a
stronger claim than what a separate connection would have found.

A floor in `audit_evidence_corpus.py` keeps it: the number of gates declaring a verified
database head may rise, never fall. Without it, deleting the argument still produces a
well-formed file and nothing notices. Verified by removing the field from a gate and
confirming the audit exits 1. The floor starts at 1 — only durability has been re-emitted
— and rises as the other three are re-run.

A related defect in the emitter itself: `aggregate` wrote only into `docs/`, and a
recorded FAIL at the current head is sticky by design, so running it merely to inspect
the journal replaced real evidence with a failure that then outlived its own reason. It
now accepts `--output-dir`.

No schema migration was needed to repair the gate. The development database is the
current fixture — head `0042`, 10,000,000 objects, 50,000,000 links, 200,000 mixed-workload
events, both `ix_oi_property_*` indexes, `wal_level=logical` — matching every harness
default. The rehearsals had simply been aimed at a stale volume.

**Both emitters were written on 2026-08-08.** What remains for these two gates is now
machine time and infrastructure, the same as the other seven:

| Gate | Emitter | Infrastructure still needed |
| --- | --- | --- |
| Durability | `oms/durability_rehearsals.py` — both rehearsal scripts now `record()` into `docs/durability-rehearsals.jsonl`, aggregated and head-filtered exactly as the chaos gate is | a second PostgreSQL container, `pg_basebackup`, a promotable standby |
| Identity | `oms/identity_scale_evidence.py` — reads what the `oidc-scale` Playwright profile measured and derives the verdict | Keycloak, two API replicas, a browser |

Three properties are worth naming, because each is a way the hand-written files could not
fail and the emitters can:

- **An empty record breaches.** A `_max` threshold with nothing to compare satisfies
  itself for want of a maximum, so "never rehearsed" would read as "never exceeded". Both
  aggregators substitute a breaching value, and `oms/test_durability_rehearsals.py`
  asserts it.
- **Half a gate breaches.** Durability names two subjects; a backup/restore alone and a
  failover alone each leave the gate unsatisfied.
- **The run does not get a vote.** The `oidc-scale` spec writes `status: "PASS"` as a
  literal before any threshold is consulted. The emitter ignores that field, and refuses
  to emit at all on a partial run rather than defaulting a missing measurement — a gap
  filled with a default is indistinguishable from a measurement once it is in the file.

The two hand-written files stay in place and stay STALE until a real run replaces them.
Deleting them would lose the prior art; editing their `migration_head` would forge
provenance. Neither is done.

### Group 2 — Construction, no evidence exists

| Gate | Threshold | What is missing |
| --- | --- | --- |
| Availability | Sustained 99.9% over a declared window | ~~No probe~~ **Harness built 2026-08-03.** Needs 7 days of wall clock against a pilot |
| RPO | <= 5 minutes, sampled repeatedly | ~~Nothing measures the gap~~ **Harness built 2026-08-03.** Needs a running backup cycle to sample against |
| RTO | <= 30 minutes, rehearsed on schedule | ~~Never scheduled~~ **Harness built 2026-08-03.** Needs four rehearsals, one timer-triggered |

Group 2 was the critical path and could not be compressed by running existing scripts
harder. The tooling now exists; what remains is wall clock and a pilot deployment to
measure. Availability still sets the floor at 7 days.

**Both harnesses were dry-run against real infrastructure on 2026-08-05, and the RPO
sampler was broken.** It read surviving marks from `GET /objects?object_type_id=...`,
which is a 405 because that path only accepts POST, so it saw nothing and reported
`total_loss` on every sample. The restored database held the marks perfectly: three marks,
maximum sequence three. Corrected to `/objects/{type}`, the same scenario measures
`surviving_sequence: 3` and `rpo_seconds: 25`, matching the real loss exactly.

Twenty-three unit tests over synthetic samples passed throughout and could not have caught
it, because they exercise the accounting and never the reading. Left undiscovered, the
seven-day window would have produced ten samples of false total loss, each recorded as a
breach, and the failure would have read as a durability defect rather than a broken
instrument. A week spent and the wrong conclusion drawn.

RTO validated clean on the same restore: restore 2.814 s, ready 3.528 s, first
authenticated write at 3.700 s against an 1,800 s limit.

The gates still need the declared window. What changed is that the window will measure the
system rather than a bug.

## Ordering

1. **Declare the measurement contract first.** Availability window, RPO sampling cadence,
   RTO rehearsal schedule, and what counts as "available" and "recovered". Without this,
   Group 2 harnesses cannot be written and Group 1 re-runs risk producing evidence in a
   shape the gates do not accept.
2. **Fix the evidence-file format once**, then make every harness emit it. Prior evidence
   files are per-benchmark ad hoc. One schema — gate id, threshold, measurement, head,
   host, timestamp, pass/fail — makes the tier auditable instead of narrated.
3. **Build the Group 2 harnesses**, longest-running first, since availability needs
   wall-clock time nothing else can shorten.
4. **Re-run Group 1** while Group 2 accumulates. These are independent.
5. **Assemble the acceptance record** only when every gate has a current evidence file.

## Margin note, now a finding

This section originally warned that the collaboration gate was passing but not safe at
241.605 ms against 250 ms. Measuring it three times at the same head on the same host
produced 241.605, 253.002, and 219.812 ms — the gate breaches roughly one run in three.

That is recorded as GOAL2-004 in [`GOAL_2026-08-03.md`](GOAL_2026-08-03.md). The cause is
that a p95 over 20 samples is a single observation. The gate is not measuring sustained
acknowledgement latency; it is sampling one request and comparing it to a threshold.

Resolve it before re-measuring, and resolve it by deciding — widen the estimator or
re-decide the threshold, recorded with an owner and rationale. The warning above was
written before the breach and the breach confirmed it; do not now discharge the finding
by running the harness until a green number appears.

## Tooling landed for this tier

- [`TIER_B_MEASUREMENT_CONTRACT.md`](TIER_B_MEASUREMENT_CONTRACT.md) fixes the evidence
  envelope and defines availability, RPO, and RTO, which had no definitions anywhere.
- `oms/tier_b_evidence.py` emits the envelope and derives `status` from the thresholds,
  so a harness cannot assert its own pass.
- `oms/validate_tier_b_evidence.py` audits all ten gates and exits non-zero unless each
  has current, provenanced, threshold-checked evidence at the current migration head.
  It reports `MISSING`, `INVALID`, `STALE`, `FAIL`, or `PASS` per gate.

- `oms/availability_probe.py` implements the availability gate: an append-only probe and
  an aggregator that derives uptime, opens outages by the two-failure rule, and emits gate
  evidence. `oms/test_availability_probe.py` covers the accounting.
- `oms/rto_rehearsal.py` times a recovery from the restore command to the first successful
  authenticated write, so migration and readiness sit inside the measurement rather than
  outside it. Requires four rehearsals with at least one unattended.
- `oms/rpo_sampler.py` writes monotonic timestamped marks and, after a restore, computes
  the gap between the last mark written and the highest mark surviving. Requires ten
  samples including two taken immediately before a scheduled backup.

All three report the **maximum**, never the mean. A mean lets one good sample bury one
that breached, and an operator experiences the worst case, not the average one.

All three also treat an empty record as a breach rather than a pass. A `_max` threshold
with no data satisfies itself by having no maximum, which would let "we never measured"
read as "we never exceeded". Each harness substitutes a breaching value when the record
is empty, and each test asserts it.

Group 2 is therefore no longer blocked on tooling. It is blocked on wall clock and on a
pilot to point the harnesses at.

Baseline on 2026-08-03: **0 of 10 gates satisfied** — 2 FAIL, 8 MISSING. Eleven of the
thirteen pre-contract evidence files record no migration head, so they cannot be shown to
be current and are retained as prior art rather than counted.

### Chaos gate covers half its scope

The Tier B chaos gate names collaboration **and** cross-stream processing. Only the
former has a harness. `verify_collaboration_websocket_chaos_postgres.py` now reports
`cross_stream_partition_rehearsals: 0` against a minimum of 1, so the gate reads FAIL
rather than appearing satisfied by the half it does cover. Collaboration itself is clean:
123.405 ms maximum reconnect against a 5,000 ms limit, zero duplicated and zero missed
events across a replica termination and restart.

Writing a cross-stream network-partition harness is the remaining work for this gate.

### Starting the availability clock

The availability gate cannot pass in less than 7 days, and the clock has not started.
Nothing else in Tier B is on a longer lead time, so starting it is the schedule-critical
action:

```bash
python oms/availability_probe.py probe --target https://<pilot-host>
```

Aggregate at any point to see budget burn; the aggregator reports how much window
remains and refuses to pass a short window however clean it is. The error budget at
99.9% over 7 days is 604.8 seconds.

### What the three pilot gates are actually waiting on

**2026-08-09.** The harnesses were complete and the documented procedure for running
them was not. Two defects would each have cost the full seven days, and neither is
visible until aggregation:

- The page said to schedule `pilot_window.py tick` every 30 seconds from cron or Task
  Scheduler. Neither can express that — `schtasks /SC MINUTE` takes 1..1439 *minutes*
  and cron's finest field is a minute — and an unwritten slot is scored as unavailable
  by design. Measured against a target that answered 200 to every real probe: **57.1%**,
  converging to 50%, against a 99.9% gate. `pilot_window.py run` now supervises the
  window in one process at the contract's cadence.
- Letting that process own availability fails a second way. A rehearsal blocks it for as
  long as a restore takes, and every blocked slot is backfilled as downtime against a
  604.8-second budget for the whole week — less than one PostgreSQL restore, against
  roughly twelve rehearsals. The `pilot-observability` container owns the journal
  instead and keeps probing throughout; the supervisor fails its tick when the observer
  stops advancing, so a dead observer is loud rather than silent. `start` refuses
  `--availability-writer scheduler`.

`pilot_window.py preflight` now checks the rest before the clock starts, because every
one of these is otherwise a seven-day round trip: health endpoints inside the 2,000 ms
the contract allows, a recovery URL that is genuinely a different identity, disk, a live
observer, and a recovery token that the API *accepts* rather than merely one that is long
enough. That last check was wrong when first written — it read 404 as "no such run", but
an API whose container never received `PILOT_RECOVERY_TOKEN` disables the protocol and
also answers 404, so the likeliest misconfiguration passed. It now asks with a malformed
run id, which a live route rejects with 422 only after accepting the credential.

What remains is not code:

| Prerequisite | State on 2026-08-09 |
| --- | --- |
| A pilot deployment with OIDC, TLS, and a real `.env.production` | Not created; `.env.production` does not exist in this checkout |
| A second isolated Compose project for restores | `docker-compose.pilot-recovery.yml` exists and its topology validates |
| **Seven days with a frozen migration head** | Mechanism built and proven; freeze **opened and closed on 2026-08-09** without collecting, because no host arrived |

The head freeze is the real gate on starting, and it is now mechanical rather than an
intention. `docs/SCHEMA_FREEZE.json` declares the frozen head with an owner and an end
date, and `oms/validate_schema_freeze.py` runs in CI beside the other ratchets: while the
freeze is open, any other head fails the build. That moves the enforcement from
destructive to cheap. `pilot_window.py tick` already refused to pool two schemas, but it
could only discover the change after the fact, when the days were spent and the migration
was merged. Now the pull request goes red instead. An expired freeze also fails, so the
file cannot quietly become a thing that looks like protection and is not.

The freeze was opened at `0042_stream_outer_joins` and **closed the same day, having
protected nothing**, because no pilot host materialised. That is the correct outcome
rather than a wasted step: a freeze blocks every migration in the repository, so one left
open around a window that is not running is pure cost, and a build that is red for a
reason nobody remembers is how a ratchet becomes something people route around. The file
retains why it was opened and why it closed. Reopen it at the then-current head when a
host exists; the mechanism is in place and tested, and opening it again is one commit.

### 2026-08-13: preflight reads 10 of 10, and the clock was deliberately not started

The full pilot configuration was exercised on the development host and
`pilot_window.py preflight` passed every check — including the two that had been failing:
the recovery driver's Compose topology and integrity key, and a live availability observer.
The gap is no longer configuration. It is seven consecutive days of a machine that stays
up.

The window was not opened, and that was a judgement rather than a limitation. 99.9% over
seven days is a **10 minute 5 second** total budget, observer loss counts against it, and
this host had been up 3.9 hours — it takes update restarts. One reboot plus a Docker start
is 2–5 minutes, so the budget survives roughly one and not two. A lost run does not merely
fail to produce a gate: a recorded FAIL at the current head is sticky until deliberately
superseded, which is a worse state than MISSING.

An earlier note here said a window could not run on this machine because "a window measures
the host it runs on". That was stricter than the contract, which constrains what is
measured and not the host class, and the correction matters: this is a risk judgement about
a 10-minute budget, not a rule forbidding it.

[`STARTING_THE_PILOT_WINDOW.md`](STARTING_THE_PILOT_WINDOW.md) records what the
verification established, so starting later is a command rather than a rediscovery.

### 2026-08-14: the window is open

Started `2026-08-14T00:34Z` at `0042_stream_outer_joins`, with the schema freeze open for
eight days. The decision above was reversed on instruction; the risk it described is
unchanged and is now simply being carried. **This window was abandoned two hours in and
restarted; the live window opened `2026-08-14T02:53Z`. See the entry below.**

Preflight passing had said the configuration was sound. It had not said the window could
run, and three things had to be established before the clock was worth starting — each by
running it, not by reading it.

**The database.** The development database is 32 GB, and RPO is the age of the recovery
point at the moment of failure: a five-minute objective requires a recovery point at least
that often, and a logical dump of 32 GB does not finish in five minutes. The 2026-08-09
note above flagged this and was right. The window therefore measures a **dedicated pilot
project** with its own volume, seeded to 254 MB — which is what the reference driver scopes
itself to in its own docstring, not a concession. Measured on that stack: backup 4.5s,
restore 32s, a complete rehearsal 33.2s against an 1800s limit.

**The recovery path.** Preflight validates that the recovery driver's configuration parses.
It does not restore anything. A full rehearsal was run before starting — marks, backup,
isolated restore, authenticated write at the restored head, RPO observation, cleanup —
because the first real one fires ten hours in, and a driver that cannot restore would have
been discovered on day one of seven. It restored, and reported `rpo_seconds: 0`.

A first attempt reported `total_loss: true`. That was the trial's own error — the marks were
written under the default project id and read back under `operations` — and not a defect:
`tick_once` passes one project id to both. Worth recording because a total-loss reading is
what a genuinely broken recovery point also looks like, and the difference is two arguments.

**The image.** It could not be built on this checkout at all. `core.autocrlf=true` rewrote
`oms/entrypoint.sh` with CRLF, the image built cleanly, and the container died with

```
exec /app/entrypoint.sh: no such file or directory
```

because the kernel reads the shebang literally and looks for `/bin/sh\r`. The error names
the script, so nothing points at the line ending. `.gitattributes` now pins `*.sh` to LF.
This is the reproducibility goal's own claim failing in a new place: the repository was
importable by a stranger and still not buildable by one on Windows.

Two operational limits are recorded rather than solved. Registering a scheduled task is
denied to this account — `Register-ScheduledTask` and `schtasks /Create` both answer
"Access is denied", elevated or not — so the supervisor is a host process that survives
this terminal but not a reboot; the command to bring it back is in
[`STARTING_THE_PILOT_WINDOW.md`](STARTING_THE_PILOT_WINDOW.md). And
`register-pilot-window.ps1` registered only a boot trigger, which never fires for a task
owned by an interactive account; it now registers a logon trigger too, which on a
workstation is the one that does the work.

### 2026-08-14: the readiness probe was failing the gate it defines

Two hours into the window, the availability journal already held two unavailable slots.
Both were `/health/ready` returning nothing after exactly 2003.4 ms — the probe's own
2,000 ms timeout — while `/health/live` answered in 3.5 ms and 6.2 ms beside them.

The cause is not the database and not the host. `/health/ready` calls `schema_health`,
which reflects the schema on **every** call: `inspector.get_columns(...)` once per mapped
table, 275 `information_schema` round-trips against this database, 220 ms at rest. The
availability gate is *defined* as that endpoint answering 200 within 2,000 ms, so the
readiness probe was on course to fail the gate by being slow to answer, with the product
behind it entirely healthy. Anything else touching the disk — and a `pg_dump` runs every
two minutes, a `pg_restore` every ten hours — pushed it over.

The rate matters more than the two samples. Two failures in 250 slots is 99.2% against a
99.9% target; at that rate the window ends in a recorded FAIL. Reflection is now cached
against the database's own migration head, which is the only thing that can legitimately
change the answer, and a head change ends a window regardless. **Measured: 220 ms to 6 ms,
275 statements to 1.** `oms/test_readiness_cost.py` counts the statements rather than
trusting the comment.

The window was **abandoned and restarted** on the rebuilt image. That cost two hours and
nothing else: `aggregate` had never run, so no evidence file existed and there was no FAIL
to supersede. The alternative — rebuilding the API inside a live window — would have
changed the subject of the measurement halfway through, which is worse than restarting it.
The abandoned journals are kept as `evidence-abandoned-20260813` rather than deleted.

**The restart was then discarded too, over a single slot.** Bringing the observer up
alongside the API recorded one refused connection while the API was still running
`alembic upgrade`, a minute before `start`. That matters more than one bad probe looks:
`summarize()` counts from the journal's first sample rather than from the window manifest,
so the availability journal — not `started_at` — is the window's clock, and a pre-window
startup gap is charged to the window as 30 seconds, 5% of the whole budget. The journal is
hash-chained, so the recorded sample cannot be edited out and should not be; the run was
discarded instead and the observer started last, against an API already answering 200. The
live window opened `2026-08-14T02:53Z`, closing `2026-08-21T02:53Z`, on a journal whose
first slots are clean.

**A contradiction in the contract, since resolved.** The availability section said both
that "a failed probe marks its whole 30-second interval unavailable" and that "two
consecutive failures are required to open an outage, so a single dropped probe does not
fabricate downtime". Those cannot both hold: under the first, an isolated dropped probe
costs 30 seconds of budget, which is precisely fabricated downtime.

The code was never ambiguous, and neither was its test. `summarize()` charges every failed
interval to `unavailable_seconds` and opens an outage only on two in a row, and
`test_availability_probe.py` already asserted exactly that — *"one failure still costs its
interval"*. The defect was in the prose, which drew a false inference from a correct rule:
the two-consecutive threshold governs `outages` and `longest_outage_seconds`, which
describe the **shape** of failures. It never governed their cost.

The decisive argument against the lenient reading is a system that answers every second
probe. It is half available, and no two of its failures are ever adjacent — so if the
outage rule also governed the budget it would record no downtime at all and score 100%.
That case is now a test rather than an argument: `summarize(samples("ud" * 8))` must report
50.0%, and the assertion fails loudly if anyone tries to discount isolated failures again.

Nothing about the running window changed. The behaviour was already the strict one; what
changed is that the contract now says so, and says why.

### 2026-08-14: the same defect, looked for in the other nine gates

The availability contradiction was one instance of a class — a rule stated in the contract
that the gated quantity does not implement — so every gate was checked the same way: the
contract clause, against the `thresholds={...}` dict, against what `summarize()` actually
computes. The enforcement mechanism itself is sound; `compare()` treats a threshold with no
matching measurement as a breach ("not measured"), so a bar cannot be declared and silently
skipped. The gaps are all bars that were never declared.

**RPO and RTO did not enforce their own window, and now do.** The contract says "at least
10 independent samples **across the 7-day window**" and "at least 4 rehearsals **across the
window**". Both harnesses counted; neither measured span. Ten samples taken inside ninety
seconds satisfied every RPO threshold, and four back-to-back restores satisfied every RTO
one — the gates whose entire subject is recovery over a week could be earned in an
afternoon. This was not hypothetical: the repository's own tests built exactly those
fixtures and called them a complete plan, spanning 91 and 999 seconds respectively.

`sampling_span_seconds` and `rehearsal_span_seconds` are now measured and gated at 5 days.
Not 7 — the first sample cannot be taken at t=0, because a recovery point has to exist
before there is anything to recover to, and the last cannot land on the closing second. The
old fixtures are kept as negative cases, so the state the gate used to accept now fails it
by name. The running window projects a 6.26-day span: 30 hours of margin, enough to lose
its first three rehearsals and still qualify.

Note this tightens rather than loosens, which is why it was safe to do with a window
running. The opposite change would not have been.

**No latency gate took the worst of six observations. Five now do.** The contract says
*"Latency gates are measured on an otherwise idle host, and the reading is the worst of at
least six observations"* — a rule added after a collaboration breach turned out to be a busy
machine rather than a slow system. Nothing implemented it. Every latency harness recorded
one run's p95, and the evidence envelope had no field for how many observations produced
the number, so an auditor could not distinguish a worst-of-six from a single lucky run. The
"worst of six" in the rows above was a person running a script six times.

`oms/latency_observations.py` is the same arrangement `durability_rehearsals.py` and
`chaos_rehearsals.py` already use, reused rather than reinvented: every run appends one
observation, the gate is derived from the worst of the union at the current head, and no
single run decides the verdict. `collaboration`, `identity`, `mixed_workload`,
`ontology_scale` and `pipeline_scale` each record their readings and carry
`observations_min: 6` — fourteen latency thresholds across the five.

**Below six the gate is not emitted at all**, and that is the load-bearing detail rather
than a nicety. A gate emitted short fails its own threshold; a recorded FAIL at the same
head is sticky by design; the sixth run could then not promote it without an explicit
supersede. Five honest runs would have locked the gate they were accumulating toward.

The quiescence half is **reported, not gated**, and the contract now says so instead of
implying otherwise. Nothing portable tells a Python process whether the machine beside it
is busy, and gating on spread would fail a system that is legitimately variable. So every
observation is kept and `observation_spread` is published beside the reading — a wide
spread is the signature of exactly the misdiagnosis this rule was written for, and it is
now in the file rather than in someone's memory of the run.

`oms/audit_latency_observations.py` is the ratchet, and it is static: it reads the harness
sources rather than running them, because the reference profiles take hours and a check
nobody can afford to run is not a check. It fails if any of the five stops recording or
stops gating, and if a sixth latency gate is added wired to neither. Its own negative cases
are tested against a fixture tree — an audit only ever run against a passing tree is an
assertion about that tree.

What is **not** claimed: none of the five has six observations yet. All five evidence files
predate the rule and carry no count, which the audit reports and does not fail on. Earning
them back means six reference runs each on a quiet host, and this host is not quiet for a
week. The gates are wired; the observations are owed.

**Also open: "at varied points in the backup cycle."** `phases_covered` is recorded and
nothing requires more than one phase. Unlike the span, "varied" has no number behind it,
and inventing one mid-window — on an unverified assumption about the running schedule's own
phase distribution — would risk failing a run that satisfies every stated requirement. The
contract now says the clause is unenforced instead of implying otherwise.

**One correction to an earlier statement here.** RTO's `failed_recoveries_max` is 0: a
single failed rehearsal anywhere in the seven days fails the gate outright, and every
attempt is journalled including the failures. Earlier notes about "tolerating" a few failed
rehearsals apply to RPO, which needs 10 successful samples out of however many are
attempted, and not to RTO, which tolerates none.

### What was verified locally on 2026-08-09, and what was not

Against a real API on the development stack, with `PILOT_EVIDENCE_ROOT` pointed at a
scratch directory so nothing entered the release evidence set:

- `preflight` reported the live configuration correctly, including the case it exists
  for: `PILOT_RECOVERY_TOKEN` exported in the operator's shell but absent from the API
  container, so the recovery protocol was disabled and answered 404. With the token
  plumbed into the container, the same request returned 422 — mounted, credential
  accepted.
- Six real availability samples against `/health/live` and `/health/ready`, all 200,
  100.0% available, hash chain intact.
- `aggregate` on that clean run still reported **FAIL**: `observed_seconds=180` against
  `604800`, `samples=6` against `20160`, and 167h 57m of window remaining. A clean window
  does not buy a short one.

**The seven-day clock was not started, and could not be from this machine.** There is no
`.env.production`, no OIDC issuer, and no TLS ingress here; the development database is
32 GB, so the first tick would fire a `pg_dump` of it. More to the point, a window
measures whatever host it runs on, and a laptop that sleeps and restarts is not a pilot
deployment — the third standing invariant, that a measurement is evidence only for the
path it traverses, applies to the machine as much as to the query. Starting a window here
would have produced a well-formed file that means nothing, which is the failure this tier
exists to prevent.

Starting the real window needs a deployed pilot host. On it, in order:
`validate_schema_freeze.py`, the `pilot-observability` profile, `pilot_window.py
preflight`, `pilot_window.py start`, then `register-pilot-window.ps1` and
`Start-ScheduledTask`.

## Exit criteria

- Ten gate evidence files in `docs/`, all at the then-current head, all in one schema.
- No unresolved P0 or P1 defect against Tier B scope, per the severity gate.
- Any threshold changed during this work is recorded with owner, date, and rationale
  rather than edited silently.
- The three production Playwright profiles (`oidc-rbac`, `oidc-scale`,
  `plugin-executor`) run rather than skip.

## Explicit non-goals for Tier B

External evaluator runs, external SDK registry publication, and compatibility-route
retirement are Tier C. Work advancing them does not advance Tier B.

### Seven of ten, and no stale gate

**2026-08-09.** The three gates left stale at `0041` were re-run at
`0042_stream_outer_joins` against the 10,000,000 object / 50,000,000 link fixture, in an
order chosen so the read-only gate measured the fixture before the mutating one touched
it:

| Gate | Result | Verified database head |
| --- | --- | --- |
| `ontology_scale` | PASS — lookup p95 10.557 ms, range p95 13.205 ms, two-hop p95 16.242 ms | `0042` |
| `mixed_workload` | PASS — 201.45 writes/s, write batch p95 1,183.62 ms, 0 invalid transitions, governed index plan intact after 100,000 mutations | `0042` |
| `pipeline_scale` | PASS — 10,000,020 rows scanned, preview p95 3,743.131 ms | none, by design |

`ontology_scale` reused the existing fixture rather than re-seeding, and records
`reused_existing_fixture: true` so the file does not imply a fresh load.

**`pipeline_scale` declares no database head on purpose.** The first attempt to wire it
failed with `no such table: alembic_version` on SQLite, because that harness overrides
`DATABASE_URL` to a throwaway file before importing the app: its subject is DuckDB
snapshot execution, and the ontology store is incidental. The scratch database is built by
`create_all` and has no migration head to report, so any value would have been invented —
the exact claim the argument exists to prevent. The reason now sits at the call site
rather than being an omission someone later repairs by supplying a number.

That failure is the check working. Under a wrong assumption it refused and crashed instead
of emitting a gate with a defaulted head.

`collaboration` was re-run the same day to pick up the check, and is the first live
exercise of the `/health/ready` path: both independently started replicas reported
`0042_stream_outer_joins` and agreed, so the gate records the schema its replicas actually
served. Ack p95 187.34 ms against a 250 ms limit, zero lost updates, 20 editors over 2
replicas with 200 readers. That is slower than the 177.515 ms it recorded before, which is
what an honest re-measurement looks like.

Tier B stands at **7 of 10 with no stale gate**: `ontology_scale`, `mixed_workload`,
`pipeline_scale`, `collaboration`, `identity`, `durability`, and `chaos` all PASS at
`0042`. The verified-head floor is **4** — every gate that measures a database now names
it. The three that do not each have a reason in the file rather than a silence:
`pipeline_scale` measures a scratch SQLite database with no `alembic_version`, and `chaos`
and `identity` aggregate rehearsals and a browser run rather than one measured database.

Only `availability`, `rpo`, and `rto` remain MISSING. As of `2026-08-14T02:53Z` they are
collecting: a window is open on this host until `2026-08-21T02:53Z` at `0042`, and what
they wait on now is seven frozen days rather than anything in this repository.


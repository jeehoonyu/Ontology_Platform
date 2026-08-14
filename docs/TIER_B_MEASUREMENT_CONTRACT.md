# Tier B Measurement Contract

Stated 2026-08-03. This is step 1 of [`GOAL_TIER_B_2026-08-03.md`](GOAL_TIER_B_2026-08-03.md).
It fixes what the Tier B gates mean before any harness measures them, so that a gate
cannot be quietly reinterpreted by the run that happens to satisfy it.

## Why this exists

Thirteen evidence files exist in `docs/`. Eleven record no migration head, no commit, and
no capture time. Two record a migration head. None declares which gate it satisfies or
what threshold it was judged against.

That makes the goal's non-completion rule unenforceable. "No tier's evidence is inherited
by a later tier without re-execution on the current head" cannot be checked against a file
that does not say what head produced it. Today the only way to know whether a measurement
is stale is to remember, and memory is not an artifact.

## Evidence envelope

Every Tier B gate emits one JSON file in `docs/` shaped as below. Harness-specific
numbers live under `measurements`; the envelope around them is identical everywhere.

```json
{
  "gate_id": "collaboration",
  "goal": "GOAL_2026-08-03",
  "tier": "B",
  "status": "PASS",
  "thresholds": { "ack_p95_ms_max": 250.0, "editors_min": 20, "lost_updates_max": 0 },
  "measurements": { "ack_p95_ms": 241.605, "editors": 20, "lost_updates": 0 },
  "provenance": {
    "migration_head": "0038_explicit_schema_baseline",
    "git_commit": "86d4481",
    "captured_at": 1785822847,
    "harness": "oms/verify_collaboration_scale_postgres.py",
    "host": { "platform": "win32", "cpu_count": 8 }
  }
}
```

Rules:

- `status` is `PASS` only when every threshold is satisfied by the paired measurement. A
  harness must not write `PASS` on partial coverage.
- `thresholds` is recorded in the file, not just in code. Evidence that does not carry the
  bar it was judged against cannot be audited later.
- `provenance.migration_head` is mandatory. Evidence whose head differs from the current
  head is **stale**, not passing.
- Threshold keys end in `_max` or `_min` so the comparison direction is explicit rather
  than inferred from the gate's name.

## Gate definitions

The seven re-execution gates keep the thresholds already stated in the goal. The three
construction gates need definitions that do not yet exist anywhere, and are fixed here.

### Identity

- **Definition**: 200 distinct users complete Authorization Code with PKCE against the
  configured production identity provider, resolve to 200 unique principals, read through
  two independently addressed API replicas, and each receive a backend `403` for a
  viewer-forbidden mutation.
- **Concurrency**: provisioning and authentication concurrency are harness controls, not
  acceptance thresholds. The containerized release rehearsal defaults to 20 provisioning
  workers and 10 browser login workers so a single Chromium process remains stable after
  image and plugin-executor stress. The separate collaboration gate owns the 20-editor and
  200-reader concurrency requirements.
- **Threshold**: 200 identities, 200 unique principals, 200 mutation denials, two replicas,
  and login p95 <= 15 seconds.
- **Provenance**: the raw browser result and derived Tier B envelope must both name the exact
  database/runtime migration head exercised by the run.

### Availability

- **Definition of available**: `GET /health/live` and `GET /health/ready` both return 200
  within 2,000 ms.
- **Probe cadence**: every 30 seconds from outside the application container.
- **Window**: 7 consecutive days. At 99.9% that is an error budget of 10 minutes 5 seconds.
- **Counting**: a failed probe marks its whole 30-second interval unavailable, and that
  interval is charged to the error budget whether or not another failure follows it. Two
  consecutive failures are required to open an **outage**, and an outage is backdated to
  its first failure — but that rule governs the outage count and the longest-outage
  duration, which describe the *shape* of the failures. It does not discount their cost.
  Nothing here distinguishes a dropped probe from a request a user would also have lost,
  and discounting isolated failures would score a system that fails every second probe —
  half available, no two failures ever adjacent — as fully available.
- **Planned restarts count against the budget.** A pilot that is only available when
  nobody deploys is not available.
- **Observer loss counts against the budget.** The production observer persists its next
  scheduled slot and appends every missed slot as unavailable after restart. Samples are
  hash chained and anchored by separate persisted state; altered, duplicated, torn, or
  rolled-back journals invalidate the run instead of silently shrinking the denominator.
- **Migration scoped**: a migration-head change starts a new seven-day run. Samples from
  different schema heads cannot be combined to satisfy the window.

### RPO

- **Definition**: the interval between the last write durably committed before an
  incident and the latest write present after recovery.
- **Measurement**: a writer appends monotonically increasing sequenced records
  continuously. Recovery is performed from the most recent backup, and RPO is the gap
  between the highest sequence written before the cut and the highest sequence present
  after restore, converted to elapsed time using the record timestamps.
- **Isolation and authentication**: marks use the dedicated bearer-authenticated recovery
  protocol and are persisted in the transactional event outbox. Observation is rejected
  when source and recovery URLs identify the same target, or when the restored database
  and runtime migration heads do not both equal the evidence head.
- **Integrity**: source-mark receipts and restored-target observations are hash chained.
  Altered, duplicated, reordered, torn, or mixed-head records invalidate the gate.
- **Sampling**: at least 10 independent samples across the 7-day window, at varied points
  in the backup cycle, including at least 2 taken immediately before a scheduled backup —
  the worst case, which a mid-cycle sample would hide.
- **Span**: the first and last samples must be at least **5 days** apart. "Across the
  window" was previously stated and unenforced, and ten samples taken inside ninety seconds
  satisfied every other threshold. Not the full 7 days: the first sample cannot be taken at
  t=0, because a recovery point has to exist before there is anything to recover to, and
  the last cannot land on the closing second. Five of seven separates a week from a sitting
  without failing a schedule for its own cadence.
  *"At varied points in the backup cycle" remains unenforced — `phases_covered` is recorded
  but nothing requires more than one phase, and turning "varied" into a number is a
  decision this contract has not made.*
- **Threshold**: every sample <= 5 minutes. The maximum is reported, not the mean.

### RTO

- **Definition**: elapsed time from declaring an incident to the system serving reads and
  writes at the restored head.
- **Measurement**: wall clock from the restore command to the first successful
  authenticated write, including migration time and readiness checks.
- **Isolation**: the restore command must produce a distinct API/database target. An
  already-running source, an empty restore command, a readiness-only response, or a write
  at a stale database/runtime head is a failed rehearsal.
- **Reference implementation**: `oms/pilot_postgres_recovery.py` and
  `docker-compose.pilot-recovery.yml` restore checksummed database, snapshot, and plugin
  artifacts into a distinct Compose project with fresh volumes. The source project is
  never stopped, renamed, or mutated by this driver. Logical dumps are suitable only for
  small pilots; large deployments must provide equivalent incremental/WAL recovery.
- **Integrity**: every attempted rehearsal, including command failure and timeout, is
  appended to a hash-chained journal and remains part of the maximum/failure count.
- **Schedule**: at least 4 rehearsals across the window, at least one unattended and
  triggered by a timer rather than a person. The first and last rehearsal must be at least
  **5 days** apart, for the reason given under RPO — four back-to-back restores in one
  afternoon satisfied the count, and counting was all this clause ever checked.
- **Threshold**: every rehearsal <= 30 minutes. The maximum is reported, and the
  distribution is retained.

## Consequences worth stating plainly

- Tier B cannot complete in less than 7 days of wall clock, because the availability
  window is 7 days and cannot be compressed. Any plan implying otherwise is wrong.
- The 11 unprovenanced evidence files do not satisfy their gates under this contract.
  They are not discarded, but they are not counted either; they become prior art that a
  re-run must reproduce.
- A gate that passes only after repeated attempts has not passed. If a harness is re-run
  after a failure, every run is recorded, and the failing run is part of the evidence.

- **Latency gates are measured on an otherwise idle host, and the reading is the worst of
  at least six observations.** This was missing and cost a wrong diagnosis. The
  collaboration gate was recorded as breaching because its p95 is taken over 20 samples,
  which was the wrong cause: six runs on a quiet host spread 6.791 ms, while the three
  earlier observations that produced a breach were taken while the machine was building
  images and running suites concurrently. A latency threshold with no stated quiescence
  condition measures the machine's mood as much as the system.

- **A recorded failure is not overwritten by a later pass at the same head.** The rule
  above was stated and unenforced: every harness rewrote its evidence file on every run,
  so re-running after a failure silently replaced it. `write_evidence` now preserves the
  failure and files the later attempt under `later_passing_attempts`; promoting a gate
  takes an explicit `supersede=True`, which asserts the cause was fixed rather than
  out-waited.

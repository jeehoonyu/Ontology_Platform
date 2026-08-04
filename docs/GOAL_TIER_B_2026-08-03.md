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

### Group 1 — Re-execution at head `0037_cross_stream_joins`

| Gate | Threshold | Prior measurement | Owed |
| --- | --- | --- | --- |
| Ontology scale | >= 10M objects / 50M links, bounded p95 | lookup 8.718 ms, range 11.830 ms, two-hop 13.721 ms p95 | Re-run at current head |
| Mixed workload | Concurrent reads during bounded writes, rollback atomicity, retained plans | 88,980 samples at 53.635 ms p95, 213.932 writes/s | Re-run at current head |
| Pipeline scale | >= 10M partitioned rows in and out | preview 3,663.405 ms, delivery 4,046.026 ms p95 | Re-run at current head |
| Collaboration | 20 editors, 2 replicas, ack p95 < 250 ms, zero lost updates | **FAIL: 241.605, 253.002, 219.812 ms across three runs at head 0037** | Resolve GOAL2-004 before re-measuring |
| Identity | 200 distinct PKCE identities under login p95 gate | 4,582.792 ms against a 15,000 ms gate | Re-run; needs Keycloak |
| Durability | Fresh-volume backup/restore and replica failover, zero committed-record loss | 36.59 GB basebackup in 50.917 s, promote in 0.686 s | Re-run at current head |
| Chaos | Partition and process-loss recovery, zero missed or duplicated events | 209.067 ms max reconnect, 3 ordered events | Re-run at current head |

### Group 2 — Construction, no evidence exists

| Gate | Threshold | What is missing |
| --- | --- | --- |
| Availability | Sustained 99.9% over a declared window | No measurement window is declared, no probe records uptime, and no artifact aggregates it. 99.9% requires a window long enough to be meaningful — over 7 days that is 10 minutes of budget |
| RPO | <= 5 minutes, sampled repeatedly | Backup/restore is rehearsed as a single pass/fail, not sampled. Nothing measures the actual gap between last durable write and recovery point, and "repeatedly" has no defined cadence |
| RTO | <= 30 minutes, rehearsed on schedule | Restore has been rehearsed on demand, never on a schedule, and elapsed time to a serving system is not recorded as a distribution |

Group 2 is the critical path. It cannot be compressed by running existing scripts harder.

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

Baseline on 2026-08-03: **0 of 10 gates satisfied** — 1 FAIL, 9 MISSING. Eleven of the
thirteen pre-contract evidence files record no migration head, so they cannot be shown to
be current and are retained as prior art rather than counted.

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

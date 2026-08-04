# PostgreSQL Ontology Mixed Workload Benchmark

OntologyOS includes a reproducible mixed workload benchmark for the living ontology. It runs concurrent typed API reads while PostgreSQL transactions update object JSONB state and append immutable temporal evidence.

## What It Proves

- Indexed exact and ordered-range reads remain bounded while object state is changing.
- Every committed object mutation has one matching append-only `object_change_events` record.
- Before/after risk transitions are internally consistent.
- A deliberately failed transaction rolls back both state and evidence.
- Governed expression indexes remain in the physical query plan after writes and `ANALYZE`.
- Disposing all SQLAlchemy connections and reconnecting preserves exact object and event counts.

The harness operates against the fixture created by `benchmark_ontology_scale_postgres.py`. It does not silently create a smaller fixture.

## Profiles

The CI `smoke` profile expects 100,000 objects and 500,000 links, updates 2,000 distinct objects in bounded batches, and runs four concurrent API readers.

The `reference` profile requires an existing fixture with at least 10,000,000 objects and 50,000,000 links. Attempts to label smaller counts as reference evidence fail before the workload begins.

```powershell
$env:DATABASE_URL = "postgresql+psycopg2://ontology:password@127.0.0.1:5432/ontology"
$env:ONTOLOGY_MIXED_PROFILE = "reference"
$env:ONTOLOGY_MIXED_WRITES = "100000"
$env:ONTOLOGY_MIXED_READERS = "8"
$env:ONTOLOGY_MIXED_BATCH_SIZE = "200"
$env:ONTOLOGY_MIXED_EVIDENCE_PATH = "docs/ontology-mixed-workload-reference-evidence.json"
python oms/benchmark_ontology_mixed_workload_postgres.py
```

Both profiles use bounded 200-object transactions by default. This keeps lock
duration and tail latency bounded while preserving the 100,000-mutation
reference workload. Performance failures are written to the configured evidence
path with `status: FAIL` and structured `gate_failures` before the process exits
nonzero, so a failed release gate remains diagnosable.

The default release thresholds are:

- concurrent typed-read p95 below 300 ms
- write-batch p95 below 2,000 ms
- at least 100 object mutations and temporal events per second

## Measured Results

On the documented Windows development host with PostgreSQL 15 in local Docker, the 100,000-object/500,000-link smoke fixture completed 2,000 mutations with four concurrent API readers:

| Read samples | Read p50 | Read p95 | Write batch p50 | Write batch p95 | Throughput |
|---:|---:|---:|---:|---:|---:|
| 1,114 | 21.644 ms | 30.485 ms | 638.586 ms | 858.462 ms | 307.459 writes/s |

All 2,000 temporal events matched distinct objects and valid before/after transitions. The rollback and connection-recovery probes passed, and PostgreSQL retained the governed property index in the post-mutation physical plan. Machine-readable smoke evidence is stored in `docs/ontology-mixed-workload-smoke-evidence.json`.

The strict profile was then run against 10,000,000 objects and 50,000,000
links. It committed 100,000 state changes and 100,000 matching temporal events
in 500 bounded transactions while eight readers completed 88,980 typed API
queries. Concurrent read p95 was 53.635 ms, write-transaction p95 was
1,117.156 ms, and throughput was 213.932 writes/s. Rollback integrity,
transition validity, post-mutation index plans, and connection recovery passed.
Machine-readable evidence is stored in
`docs/ontology-mixed-workload-reference-evidence.json`.

These are development-host regression gates, not universal capacity claims.
The workload uses one writer and multiple readers on one PostgreSQL primary.
Multi-primary active-active conflicts, repeated scheduled recovery, and
long-duration production saturation remain separate operations gates.

## Process-Restart Recovery

After a reference workload, the recovery rehearsal runs `VACUUM (ANALYZE)` on
object state and temporal evidence, restarts the PostgreSQL container, waits for
readiness, and verifies exact fixture/event counts plus the governed index plan:

```powershell
$env:DATABASE_URL = "postgresql+psycopg2://ontology:password@127.0.0.1:5432/ontology"
$env:ONTOLOGY_RECOVERY_CONTAINER = "ontology_scale_reference"
$env:ONTOLOGY_RECOVERY_EVIDENCE_PATH = "docs/ontology-scale-recovery-evidence.json"
python oms/rehearse_ontology_scale_recovery.py
```

The measured rehearsal vacuumed/analyzed the mutated tables, restarted the
database process, recovered in 2.714 seconds, preserved all 10,000,000 objects,
50,000,000 links, and 200,000 accumulated mixed-workload events, and retained
the governed index plan. Machine-readable evidence is stored in
`docs/ontology-scale-recovery-evidence.json`.

This proves process-restart recovery for the reference fixture. The following
sections provide the separate fresh-volume and streaming-failover evidence.

## Physical Backup To A Fresh Volume

`rehearse_ontology_scale_backup_restore.py` streams `pg_basebackup` from the
running reference database into a newly created Docker volume, starts an
independent PostgreSQL instance from that volume, and verifies migration state,
exact object/link/event counts, and the governed property-index plan. It refuses
to overwrite target containers or volumes unless reset is explicitly enabled.

```powershell
$env:DATABASE_URL = "postgresql+psycopg2://ontology:password@127.0.0.1:55432/ontology"
$env:ONTOLOGY_BACKUP_TARGET_DATABASE_URL = "postgresql+psycopg2://ontology:password@127.0.0.1:55433/ontology"
$env:ONTOLOGY_BACKUP_SOURCE_CONTAINER = "ontology_scale_reference"
$env:ONTOLOGY_BACKUP_POSTGRES_PASSWORD = "password"
$env:ONTOLOGY_BACKUP_EVIDENCE_PATH = "docs/ontology-scale-backup-restore-evidence.json"
python oms/rehearse_ontology_scale_backup_restore.py
```

The backup duration is a measured protection window, not a continuous five-
minute RPO claim. Continuous RPO requires WAL archival or a streaming replica.

On the reference host, the 36.59 GB physical backup completed in 50.917
seconds. A PostgreSQL process backed by the new volume became query-ready in
1.144 seconds with identical migration, object, link, temporal-event, and index-
plan state. Machine-readable evidence is stored in
`docs/ontology-scale-backup-restore-evidence.json`.

## Streaming Replica And Failover

`rehearse_ontology_scale_replica_failover.py` creates a fresh physical standby,
commits a linked object-state/temporal-event probe on the source, measures WAL
replay until that probe is queryable, terminates the source container, promotes
the standby, and verifies that the committed probe and complete strict fixture
remain available. The default gates are five minutes for committed-write replay
and 30 minutes for promotion.

The measured standby replayed the committed object/event probe in 0.015 seconds
at an identical WAL LSN. After source termination, promotion completed in 0.686
seconds with the probe and complete fixture preserved. Machine-readable evidence
is stored in `docs/ontology-scale-replica-failover-evidence.json`.

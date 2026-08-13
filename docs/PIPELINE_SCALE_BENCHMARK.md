# Snapshot-Native Pipeline Scale Benchmark

This benchmark proves that compiled Pipeline Builder DAGs can execute directly over multiple immutable Parquet snapshots without loading input datasets into Python objects. It is a bounded local reference test, not a distributed-compute claim.

## Execution Path

`POST /api/v1/datasets/{asset_id}/snapshots/register` registers a connector-produced Parquet file or bounded local/S3-compatible prefix. Partitioned registration records a stable relative-file manifest with per-file row count, byte size, and SHA-256 plus aggregate schema, rows, bytes, and content hash. Hive key paths can supply partition fields absent from Parquet bodies. It does not hydrate `DataAsset.records`. Direct row/query endpoints and Pipeline Builder read local files or integrity-checked S3 cache files through DuckDB; later unregistered local files/objects are ignored, missing/changed files fail, and recovery profiles can enable full local hash verification with `DATA_SNAPSHOT_VERIFY_HASH=true`.

`POST /api/v1/pipelines/{graph_id}/plans` compiles graph revision, schema, field lineage, validation, and a stable plan hash. Executing a DuckDB plan enqueues a durable preview or delivery job. The worker compiles supported nodes into parameterized SQL and scans the Parquet snapshot directly.

Preview returns bounded rows and a total count from one query. Delivery uses DuckDB `COPY` to create a new immutable Parquet snapshot, records source snapshot and plan lineage, and leaves the output asset's relational `records` collection empty. Dataset output nodes can select up to eight Hive partition fields. Delivery writes to a staging path, records an immutable per-file integrity manifest, atomically promotes the snapshot, and replaces an orphaned deterministic target on retry. A stable execution job ID makes committed delivery retry-safe: replay returns the existing output snapshot instead of committing a duplicate.

Snapshot publication is separately fenced from computation. A worker may build
an isolated staging snapshot, but before promotion it must hold the current,
unexpired job lease and the serialized output namespace. PostgreSQL uses a
transaction advisory lock so even a not-yet-created output asset has a lockable
identity. A worker whose lease expired cannot replace files or commit metadata;
the same claim poll requeues the job, and a replacement worker publishes one
snapshot. A late process can only read that immutable committed result.

Production workers now claim DuckDB jobs from the API but execute the compiled
plan inside the worker process. Database, object-store, and snapshot settings
are passed to each worker while its cache remains private. The API remains the
authoritative scheduler and lease owner; it no longer owns snapshot compute for
these jobs. `scripts/run-pipeline-worker-recovery.ps1` exercises this boundary
against PostgreSQL, MinIO, and an impaired Toxiproxy path. It kills the first
worker after a partition reaches its private cache, waits for lease recovery,
and starts a replacement with a different empty cache.

The production acceptance topology repeats this with the production image,
real Keycloak OIDC, an execute-only service token, PostgreSQL, digest-pinned
MinIO and Toxiproxy, and separate container tmpfs caches. The current reference
killed the first container with exit 137 after 14 of 32 files, then verified
that its replacement downloaded all 32 files and committed one fenced output.
This proves container isolation on one Docker host, not a multi-host claim.

A stronger focused profile loads the production image independently into two
Docker daemons with separate image stores, container filesystems, and caches.
The first daemon was killed after its worker cached 3 of 32 impaired-network
partitions; a worker in the second daemon rebuilt all 32, claimed attempt two,
and published one fenced 10,000-row output. Evidence is recorded in
`docs/pipeline-worker-multidaemon-recovery-evidence.json`. Both daemons still
run on one physical host, so provider networking and true host-loss recovery
remain separate acceptance work.

## Current SQL Subset

The snapshot-native executor supports branching plans containing:

- dataset input and dataset output
- filter, project/select, rename, cast, and derive
- null filling, normalization, and deduplication
- two-branch or snapshot-configured equi-joins
- schema-aligned union by column name
- deterministic unique identifiers
- dynamic pivot and configured unpivot
- row number, rank, and running-sum windows
- row validation with annotate, drop, or fail behavior
- latitude/longitude point derivation, radius filtering, MGRS encoding, polygon geofencing with holes, and coordinate/point spatial joins
- aggregate, sort, and limit

The release benchmark now runs two plans. The baseline covers the broad
transform chain above, including a selective high-vertex polygon with a hole.
Polygon rings are transported as compact JSON scalar parameters and decoded as
typed edge tables inside DuckDB. Containment is evaluated once per distinct
coordinate and joined back to repeated telemetry rows, keeping SQL text and
Python materialization bounded as polygon complexity grows. The complex plan joins two equal-size partitioned fact
snapshots, unions the joined stream with another large branch by field name,
pivots a configurable high-cardinality metric dimension, writes partitioned
Parquet output, and replays the same durable execution job to prove it returns
the already-committed snapshot instead of publishing a duplicate.

Unsupported operations fail compilation explicitly. The existing local executor retains the broader transform catalog. Arbitrary expressions, distributed partition scheduling, and multi-worker data-plane execution remain future scale work.

## Reproduce

CI smoke profile, one million rows:

```powershell
$env:PIPELINE_SCALE_PROFILE = "smoke"
$env:PIPELINE_SCALE_SAMPLES = "3"
python oms/benchmark_pipeline_scale.py
```

Strict reference profile, at least ten million rows:

```powershell
$env:PIPELINE_SCALE_PROFILE = "reference"
$env:PIPELINE_SCALE_ROWS = "10000000"
$env:PIPELINE_SCALE_SAMPLES = "3"
python oms/benchmark_pipeline_scale.py
```

Set `PIPELINE_SCALE_GATE_EVIDENCE_DIR` to a temporary directory for diagnostic
reference runs from an uncommitted worktree. Omit it only when intentionally
refreshing repository Tier B evidence from the release commit.

The reference profile refuses row counts below 10,000,000. Override `PIPELINE_PREVIEW_P95_LIMIT_MS` and `PIPELINE_DELIVER_LIMIT_MS` only when documenting different reference hardware and release gates.

## Measured Evidence

Development host on 2026-08-11:

- Windows 11, Python 3.12.10, DuckDB 1.5.5
- Intel64 Family 6 Model 198 Stepping 2
- 10,000,000 baseline rows and 10,000,000 large-join rows, each in eight immutable ZSTD Parquet partitions
- plan: fact input -> filter -> high-vertex geofence -> stable ID -> point -> radius -> MGRS + dimension input -> join -> partitioned window -> derive -> aggregate -> sort -> output
- two source snapshots and 10,000,020 total input rows
- 5,000,000 rows passed the score filter; a 9,218-position polygon (8,192-position outer ring and 1,024-position hole) selected 2,340,000 rows
- 20 aggregate rows were written into 20 Hive-style output partitions
- baseline preview p50 1,429.894 ms and p95 1,459.595 ms across three measured samples
- baseline delivery 1,515.835 ms
- only 20 result rows were materialized into Python; bulk input and output stayed snapshot-native
- complex plan: 10,000,000-by-10,000,000 equi-join, 20,000,000-row schema-aligned union, and 512-column pivot
- complex preview 1,241.171 ms and delivery 1,803.904 ms; only two rows were materialized into Python
- replay returned the exact previously committed output snapshot

The fixture is deliberately deterministic and highly compressible, so these timings demonstrate execution architecture and a repeatable regression boundary rather than arbitrary real-world throughput. MGRS is compiled into DuckDB SQL rather than a Python row UDF, and polygon containment uses validated WGS84 GeoJSON rings with hole exclusion. Production sizing must also use representative schemas and file sizes, object-storage latency, and sustained multi-worker data-plane recovery. Machine-readable evidence is stored in `docs/pipeline-scale-reference-evidence.json`.

The producer now writes the canonical repository-head, commit, harness, entry
point, and request-shape provenance envelope into raw benchmark output. The
checked-in file predates that contract and remains classified `UNPROVENANCED`;
it must be regenerated from a clean release reference run rather than
retroactively stamped.

## Automated Evidence

- `oms/test_duckdb_snapshot_pipeline.py` verifies preview, delivery, lineage, empty relational records, and idempotent delivery replay.
- `oms/test_duckdb_delivery_lease_fencing.py` expires a worker during delivery, proves stale publication and staging leakage are denied, reclaims the job in the same poll, and verifies one replacement snapshot plus audit/job evidence. CI runs it on SQLite and migrated PostgreSQL.
- `oms/rehearse_pipeline_worker_recovery.py` performs the stronger real-process rehearsal: the first worker is forcibly terminated during an S3-backed delivery, the replacement independently rebuilds its cache, and PostgreSQL records two claims plus one requeue and one fenced output snapshot. `docs/pipeline-worker-recovery-evidence.json` records the reference result; CI runs a bounded form.
- `frontend/tests/production/pipeline-worker-recovery.spec.ts` and `scripts/rehearse-production-acceptance.ps1 -OnlyPipelineWorkers` provide the production-image/OIDC/container boundary. `docs/pipeline-worker-container-recovery-evidence.json` records the migration-provenanced result.
- `scripts/rehearse-production-acceptance.ps1 -OnlyPipelineMultiDaemon` loads that image into two independent Docker daemons and proves lease recovery without a shared image store, worker filesystem, or cache. `docs/pipeline-worker-multidaemon-recovery-evidence.json` records the migration-provenanced result and its one-host boundary.
- `oms/test_duckdb_branching_pipeline.py` verifies filtered branches, join, union-by-name, aggregation, three-source lineage, delivery, and replay.
- `oms/test_duckdb_advanced_snapshot_transforms.py` verifies named-parameter composition, IDs, normalization, windows, validation modes, pivot/unpivot, point/radius operations, exact public-encoder MGRS parity, polygon holes, spatial joins, deterministic non-retriable failures, and a 9,218-position polygon whose SQL remains bounded because its edges are parameterized.
- `oms/test_partitioned_snapshot_pipeline.py` verifies multi-file input manifests, direct query pushdown, Hive-partitioned output manifests and queries, durable preview/delivery, invalid output partition rejection, idempotent replay, root containment, schema mismatch, empty directories, and content-mutation detection.
- `oms/test_s3_snapshot_pipeline.py` verifies exact-object and bounded-prefix registration, Hive schema recovery, cross-bucket/file-limit rejection, coordinated concurrent cold-cache reads, bounded capacity, lease-aware LRU pruning, cache metrics, Hive-partition publication, idempotent replay, and remote manifest corruption rejection without cloud dependencies.
- `oms/rehearse_s3_snapshot_minio.py` exercises connector-style prefix registration, Hive recovery, execution, publication, and query against the real optional MinIO service.
- `oms/benchmark_object_storage_minio.py` and `docs/OBJECT_STORAGE_BENCHMARK.md` provide separately scoped cold/warm object-storage evidence.
- `oms/test_pipeline_scale_benchmark_contract.py` protects benchmark and CI release contracts.
- `.github/workflows/ci.yml` runs both plans at the one-million-row-per-large-input smoke profile.
- `oms/benchmark_pipeline_scale.py` provides the strict manual reference profile and optional JSON evidence output.

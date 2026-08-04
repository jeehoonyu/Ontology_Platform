# Snapshot-Native Pipeline Scale Benchmark

This benchmark proves that compiled Pipeline Builder DAGs can execute directly over multiple immutable Parquet snapshots without loading input datasets into Python objects. It is a bounded local reference test, not a distributed-compute claim.

## Execution Path

`POST /api/v1/datasets/{asset_id}/snapshots/register` registers a connector-produced Parquet file or bounded local/S3-compatible prefix. Partitioned registration records a stable relative-file manifest with per-file row count, byte size, and SHA-256 plus aggregate schema, rows, bytes, and content hash. Hive key paths can supply partition fields absent from Parquet bodies. It does not hydrate `DataAsset.records`. Direct row/query endpoints and Pipeline Builder read local files or integrity-checked S3 cache files through DuckDB; later unregistered local files/objects are ignored, missing/changed files fail, and recovery profiles can enable full local hash verification with `DATA_SNAPSHOT_VERIFY_HASH=true`.

`POST /api/v1/pipelines/{graph_id}/plans` compiles graph revision, schema, field lineage, validation, and a stable plan hash. Executing a DuckDB plan enqueues a durable preview or delivery job. The worker compiles supported nodes into parameterized SQL and scans the Parquet snapshot directly.

Preview returns bounded rows and a total count from one query. Delivery uses DuckDB `COPY` to create a new immutable Parquet snapshot, records source snapshot and plan lineage, and leaves the output asset's relational `records` collection empty. Dataset output nodes can select up to eight Hive partition fields. Delivery writes to a staging path, records an immutable per-file integrity manifest, atomically promotes the snapshot, and replaces an orphaned deterministic target on retry. A stable execution job ID makes committed delivery retry-safe: replay returns the existing output snapshot instead of committing a duplicate.

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

The reference profile refuses row counts below 10,000,000. Override `PIPELINE_PREVIEW_P95_LIMIT_MS` and `PIPELINE_DELIVER_LIMIT_MS` only when documenting different reference hardware and release gates.

## Measured Evidence

Development host on 2026-07-31:

- Windows 11, Python 3.12.10, DuckDB 1.5.5
- Intel64 Family 6 Model 198 Stepping 2
- 10,000,000 generated rows in eight immutable ZSTD Parquet partitions totaling 15,572,089 bytes
- plan: fact input -> filter -> stable ID -> point -> radius -> MGRS -> polygon geofence + dimension input -> join -> partitioned window -> derive -> aggregate -> sort -> output
- two source snapshots and 10,000,020 total input rows
- 5,000,000 rows passed the filter and 20 aggregate rows were written into 20 Hive-style output partitions
- preview p50 3,073.799 ms and p95 3,663.405 ms across five measured samples after warmup
- delivery 4,046.026 ms
- only 20 result rows were materialized into Python; bulk input and output stayed snapshot-native

The fixture is deliberately deterministic and highly compressible, so these timings demonstrate execution architecture and a repeatable regression boundary rather than arbitrary real-world throughput. MGRS is compiled into DuckDB SQL rather than a Python row UDF, and polygon containment uses validated WGS84 GeoJSON rings with hole exclusion. Production sizing must also use representative schemas, cardinality, file sizes, large-to-large joins, complex polygons, object-storage latency, and multi-worker recovery. Machine-readable evidence is stored in `docs/pipeline-scale-reference-evidence.json`.

## Automated Evidence

- `oms/test_duckdb_snapshot_pipeline.py` verifies preview, delivery, lineage, empty relational records, and idempotent delivery replay.
- `oms/test_duckdb_branching_pipeline.py` verifies filtered branches, join, union-by-name, aggregation, three-source lineage, delivery, and replay.
- `oms/test_duckdb_advanced_snapshot_transforms.py` verifies named-parameter composition, IDs, normalization, windows, validation modes, pivot/unpivot, point/radius operations, exact public-encoder MGRS parity, polygon holes, spatial joins, and deterministic non-retriable failures.
- `oms/test_partitioned_snapshot_pipeline.py` verifies multi-file input manifests, direct query pushdown, Hive-partitioned output manifests and queries, durable preview/delivery, invalid output partition rejection, idempotent replay, root containment, schema mismatch, empty directories, and content-mutation detection.
- `oms/test_s3_snapshot_pipeline.py` verifies exact-object and bounded-prefix registration, Hive schema recovery, cross-bucket/file-limit rejection, coordinated concurrent cold-cache reads, bounded capacity, lease-aware LRU pruning, cache metrics, Hive-partition publication, idempotent replay, and remote manifest corruption rejection without cloud dependencies.
- `oms/rehearse_s3_snapshot_minio.py` exercises connector-style prefix registration, Hive recovery, execution, publication, and query against the real optional MinIO service.
- `oms/benchmark_object_storage_minio.py` and `docs/OBJECT_STORAGE_BENCHMARK.md` provide separately scoped cold/warm object-storage evidence.
- `oms/test_pipeline_scale_benchmark_contract.py` protects benchmark and CI release contracts.
- `.github/workflows/ci.yml` runs the one-million-row smoke profile.
- `oms/benchmark_pipeline_scale.py` provides the strict manual reference profile and optional JSON evidence output.

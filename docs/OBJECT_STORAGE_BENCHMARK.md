# S3-Compatible Snapshot Benchmark

This benchmark measures the complete public OntologyOS path for a connector-produced Hive-partitioned Parquet prefix stored in S3-compatible object storage. It separates cold-cache and warm-cache behavior and records cache transfer metrics. The checked-in reference evidence uses MinIO over local Docker loopback; it is not a WAN, managed-cloud, or cross-region latency claim.

## Measured Path

1. Generate deterministic Parquet partitions with DuckDB and upload them as `region=.../part.parquet` objects.
2. Register the prefix through `POST /api/v1/datasets/{asset_id}/snapshots/register`.
3. Validate every object, recover the Hive field, and commit the immutable manifest.
4. Prune the execution cache.
5. Measure a filtered/ordered public snapshot query with cold and warm caches.
6. Compile a DuckDB pipeline containing input, filter, aggregation, sort, and output nodes.
7. Prune the cache and measure durable worker preview with cold and warm caches.
8. Record cache hits, misses, downloaded bytes, integrity failures, and evictions.

Registration validation downloads every object once and computes full SHA-256 evidence before snapshot metadata becomes available. Cold execution downloads the immutable manifest into `DATA_SNAPSHOT_CACHE_ROOT`; warm execution reuses verified files.

## Reproduce

Start MinIO:

```powershell
docker compose --profile object-storage up -d minio
```

Smoke profile:

```powershell
$env:AWS_ACCESS_KEY_ID = "ontology"
$env:AWS_SECRET_ACCESS_KEY = "ontology-development-secret"
$env:OBJECT_STORAGE_BENCHMARK_PROFILE = "smoke"
python oms/benchmark_object_storage_minio.py
```

Reference profile:

```powershell
$env:OBJECT_STORAGE_BENCHMARK_PROFILE = "reference"
$env:OBJECT_STORAGE_BENCHMARK_ROWS = "1000000"
$env:OBJECT_STORAGE_BENCHMARK_PARTITIONS = "8"
$env:OBJECT_STORAGE_BENCHMARK_SAMPLES = "5"
$env:OBJECT_STORAGE_BENCHMARK_EVIDENCE_PATH = "docs/object-storage-reference-evidence.json"
python oms/benchmark_object_storage_minio.py
```

The reference profile rejects fewer than 1,000,000 rows. Thresholds can be configured with `OBJECT_STORAGE_REGISTRATION_LIMIT_MS`, `OBJECT_STORAGE_COLD_QUERY_LIMIT_MS`, `OBJECT_STORAGE_WARM_QUERY_P95_LIMIT_MS`, `OBJECT_STORAGE_COLD_PIPELINE_LIMIT_MS`, and `OBJECT_STORAGE_WARM_PIPELINE_P95_LIMIT_MS` when documenting different hardware or network conditions.

## Reference Evidence

Development host on 2026-07-31:

- Windows 11, Python 3.12.10, DuckDB 1.5.5
- MinIO at `http://127.0.0.1:9000` over local Docker loopback
- 1,000,000 rows across eight Hive partitions
- 467,776 compressed Parquet bytes
- prefix registration: 281.585 ms
- cold filtered/ordered query: 128.102 ms
- warm query p50: 76.260 ms; p95: 87.243 ms
- cold durable pipeline preview: 351.269 ms
- warm pipeline p50: 44.021 ms; p95: 49.161 ms
- 16 cache misses and 128 hits across the measured query/pipeline sequence
- 935,552 bytes downloaded because cold query and cold pipeline each intentionally repopulated the cache
- zero integrity failures

Machine-readable evidence is stored in `docs/object-storage-reference-evidence.json`.

## Interpretation

This proves the object-store boundary, manifest validation, cold/warm cache behavior, durable job execution, and repeatable local performance regression thresholds. Production sizing still requires the same benchmark against the intended S3 provider and deployment network using representative object sizes, partition counts, concurrency, encryption, proxies, and geographic placement. Cross-region and WAN results must be recorded as separate evidence profiles rather than replacing this local baseline.

## Automated Evidence

- `oms/test_s3_snapshot_pipeline.py` tests exact/prefix registration, Hive recovery, concurrency, integrity, quota, LRU behavior, and partitioned output without external services.
- `oms/rehearse_s3_snapshot_minio.py` verifies the complete functional path against real MinIO.
- `oms/test_object_storage_benchmark_contract.py` protects benchmark profiles, metrics, and release thresholds.
- `oms/benchmark_object_storage_minio.py` produces smoke/reference measurements and optional JSON evidence.

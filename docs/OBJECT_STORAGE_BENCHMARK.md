# S3-Compatible Snapshot Benchmark

This benchmark measures the complete public OntologyOS path for a connector-produced Hive-partitioned Parquet prefix stored in S3-compatible object storage. It separates cold-cache and warm-cache behavior, records cache transfer metrics, and races independently leased workers over one cold immutable cache. The checked-in reference evidence uses MinIO behind a Toxiproxy profile that adds 40 ms downstream latency and 5 ms jitter. It is a deterministic impaired-network baseline, not a managed-cloud or cross-region claim.

## Measured Path

1. Generate deterministic Parquet partitions with DuckDB and upload them as `region=.../part.parquet` objects.
2. Register the prefix through `POST /api/v1/datasets/{asset_id}/snapshots/register`.
3. Validate every object, recover the Hive field, and commit the immutable manifest.
4. Prune the execution cache.
5. Measure a filtered/ordered public snapshot query with cold and warm caches.
6. Compile a DuckDB pipeline containing input, filter, aggregation, sort, and output nodes.
7. Prune the cache and measure durable worker preview with cold and warm caches.
8. Record cache hits, misses, downloaded bytes, integrity failures, and evictions.
9. Prune again and execute four durable preview jobs concurrently.
10. Query Toxiproxy's admin API to prove the measured S3 endpoint is bound to the declared latency toxic.

Registration validation downloads every object once and computes full SHA-256 evidence before snapshot metadata becomes available. Cold execution downloads the immutable manifest into `DATA_SNAPSHOT_CACHE_ROOT`; warm execution reuses verified files.

## Reproduce

The reproducible reference harness starts isolated MinIO and digest-pinned
Toxiproxy containers, configures latency, runs the benchmark, and cleans up:

```powershell
./scripts/run-object-storage-reference.ps1
```

For an unimpaired smoke run, start MinIO:

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

Manual reference profile without impairment:

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

Development host on 2026-08-11:

- Windows 11, Python 3.12.10, DuckDB 1.5.5
- MinIO behind Toxiproxy at `http://127.0.0.1:19001`
- independently verified downstream latency toxic: 40 ms with 5 ms jitter
- 1,000,000 rows across eight Hive partitions
- 467,776 compressed Parquet bytes
- prefix registration: 884.284 ms
- cold filtered/ordered query: 534.057 ms
- warm query p50: 151.958 ms; p95: 172.907 ms
- cold durable pipeline preview: 502.387 ms
- warm pipeline p50: 96.006 ms; p95: 97.444 ms
- four concurrent cold-cache workers completed in 540.532 ms
- concurrent workers produced exactly eight cache misses and 24 hits: every partition downloaded once and was reused by the other three workers
- 24 total cache misses and 152 hits across registration-independent measured execution
- 1,403,328 bytes downloaded because cold query, cold pipeline, and concurrent cold workers each intentionally repopulated the cache
- zero integrity failures

Machine-readable evidence is stored in `docs/object-storage-reference-evidence.json`.

The producer now includes the canonical repository-head, commit, harness, entry
point, and request-shape provenance envelope. The existing checked-in reference
predates that contract and remains `UNPROVENANCED` until a clean reference run
re-earns it; this documentation does not retroactively assign provenance.

## Interpretation

This proves the object-store boundary, manifest validation, cold/warm cache behavior, independently verified latency injection, concurrent shared-cache coordination, durable job execution, and repeatable performance regression thresholds. It does not prove multi-host cache sharing or managed-provider behavior. Production sizing still requires the same benchmark against the intended S3 provider and deployment network using representative object sizes, partition counts, concurrency, encryption, proxies, and geographic placement. Cross-region and WAN results must be recorded as separate evidence profiles rather than replacing this impaired local baseline.

## Automated Evidence

- `oms/test_s3_snapshot_pipeline.py` tests exact/prefix registration, Hive recovery, concurrency, integrity, quota, LRU behavior, and partitioned output without external services.
- `oms/rehearse_s3_snapshot_minio.py` verifies the complete functional path against real MinIO.
- `oms/test_object_storage_benchmark_contract.py` protects benchmark profiles, metrics, and release thresholds.
- `oms/benchmark_object_storage_minio.py` produces smoke/reference measurements and optional JSON evidence.
- `scripts/run-object-storage-reference.ps1` creates the isolated latency-injected reference environment and always removes it.
- `.github/workflows/ci.yml` runs a 100,000-row, four-worker MinIO/Toxiproxy smoke profile on every pull request.

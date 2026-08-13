"""Static release contract for the real MinIO object-storage benchmark."""

from pathlib import Path


root = Path(__file__).resolve().parent
source = (root / "benchmark_object_storage_minio.py").read_text(encoding="utf-8")
harness = (root.parent / "scripts" / "run-object-storage-reference.ps1").read_text(encoding="utf-8")
workflow = (root.parent / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
for required in (
    'OBJECT_STORAGE_BENCHMARK_PROFILE',
    'REFERENCE_ROWS = 1_000_000',
    'Reference object-storage profile requires at least 1,000,000 rows',
    '"network_scope": NETWORK_SCOPE',
    'build_evidence_provenance(',
    '"provenance":',
    'OBJECT_STORAGE_NETWORK_SCOPE',
    'OBJECT_STORAGE_TOXIPROXY_ADMIN_URL',
    'OBJECT_STORAGE_TOXIPROXY_ENDPOINT',
    'OBJECT_STORAGE_BENCHMARK_CONCURRENT_WORKERS',
    '"network_fault_profile"',
    '"concurrent_workers"',
    '"concurrent_cold_pipeline_ms"',
    '"concurrent_cache_delta"',
    'ThreadPoolExecutor',
    'concurrent_cache_delta["misses"] == PARTITIONS',
    'concurrent_cache_delta["integrity_failures"] == 0',
    '"registration_ms"',
    '"cold_query_ms"',
    '"warm_query_p95_ms"',
    '"cold_pipeline_ms"',
    '"warm_pipeline_p95_ms"',
    '"cache_metrics"',
    '/snapshots/register',
    '/snapshot-cache/prune',
    '"executor": "duckdb"',
):
    assert required in source, required

for required in (
    "ghcr.io/shopify/toxiproxy@sha256:",
    "OBJECT_STORAGE_TOXIPROXY_ADMIN_URL",
    "OBJECT_STORAGE_BENCHMARK_CONCURRENT_WORKERS",
    "benchmark_object_storage_minio.py",
    "finally",
    "Remove-BenchmarkResources",
):
    assert required in harness, required

for required in (
    "Benchmark latency-injected S3-compatible execution",
    "benchmark_object_storage_minio.py",
    "OBJECT_STORAGE_BENCHMARK_CONCURRENT_WORKERS",
    "OBJECT_STORAGE_TOXIPROXY_ADMIN_URL",
    "ghcr.io/shopify/toxiproxy@sha256:",
):
    assert required in workflow, required

print("Object-storage benchmark contract verified: real MinIO, independently verified latency, "
      "concurrent cold-cache workers, and cleanup are defined.")

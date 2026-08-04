"""Static release contract for the real MinIO object-storage benchmark."""

from pathlib import Path


source = (Path(__file__).resolve().parent / "benchmark_object_storage_minio.py").read_text(encoding="utf-8")
for required in (
    'OBJECT_STORAGE_BENCHMARK_PROFILE',
    'REFERENCE_ROWS = 1_000_000',
    'Reference object-storage profile requires at least 1,000,000 rows',
    '"network_scope": "local-docker-loopback"',
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

print("Object-storage benchmark contract verified: real MinIO cold/warm query and pipeline profiles are defined.")

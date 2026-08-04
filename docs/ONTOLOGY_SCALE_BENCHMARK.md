# PostgreSQL Ontology Scale Benchmark

OntologyOS includes a reproducible benchmark for typed object queries and bounded two-hop graph expansion. It operates on the production PostgreSQL schema, uses the public `/api/v1` query endpoints, and verifies physical plans with `EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)`.

## What It Proves

- Generated object state is stored in `object_instances` JSONB with the normal foreign keys and indexes.
- Generated graph state is stored in `link_instances` with five distinct outgoing targets per source at the standard 5:1 link/object ratio.
- Exact string lookup and numeric range/order queries execute through the typed SQL compiler.
- Two-hop graph expansion executes through the bounded batched BFS endpoint and hydrates objects without N+1 reads.
- PostgreSQL uses the governed ontology expression index for object lookup.
- PostgreSQL uses source and target traversal indexes for bidirectional graph expansion.
- Object result masking performs a bounded type-level metadata lookup rather than a query per returned row.

## Profiles

The default `smoke` profile creates 100,000 objects and 500,000 links. It is wired into the PostgreSQL CI job with ten measured samples.

The `reference` profile creates 10,000,000 objects and 50,000,000 links. The harness exits before seeding if a reference run attempts to override either count below that boundary. This prevents a smaller rehearsal from being reported as release-scale evidence.

```powershell
$env:DATABASE_URL = "postgresql+psycopg2://ontology:password@127.0.0.1:5432/ontology"
$env:ONTOLOGY_SCALE_PROFILE = "reference"
$env:ONTOLOGY_SCALE_SAMPLES = "20"
python oms/benchmark_ontology_scale_postgres.py
```

Use a clean, migrated database. Optional evidence output is controlled by `ONTOLOGY_SCALE_EVIDENCE_PATH`.

## Measured Development-Host Results

Reference host: Windows 11, Python 3.12.10, PostgreSQL 16 Docker container, Intel64 Family 6 Model 198. Results include FastAPI/TestClient request handling and SQL execution. They are regression evidence for this machine, not universal capacity claims.

| Objects | Links | Samples | Exact lookup p95 | Range/order p95 | Two-hop p95 | Expanded graph | Seed time |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 100,000 | 500,000 | 20 | 9.513 ms | 16.431 ms | 15.815 ms | 77 nodes / 100 edges | 25.930 s |
| 1,000,000 | 5,000,000 | 10 | 12.095 ms | 47.778 ms | 22.509 ms | 77 nodes / 100 edges | 314.567 s |
| 10,000,000 | 50,000,000 | 10 | 10.076 ms | 12.937 ms | 15.953 ms | 77 nodes / 100 edges | 2,932 s initial run wall time |

The strict relations occupied 8,621,293,568 bytes for objects and 28,925,599,744 bytes for links, including indexes. The initial strict run exposed the ordered-range issue below after 2,932 seconds of total wall time. A count-verified fixture reuse run then applied the corrected index and completed all API and physical-plan gates in 29.3 seconds. All published profiles pass the declared object-query p95 limit of 300 ms and two-hop graph-query p95 limit of two seconds.

Set `ONTOLOGY_SCALE_REUSE_EXISTING=true` only to retest a previously seeded fixture. The harness verifies exact project/type counts before it skips seeding, preventing partial or duplicated data from being reported as reference evidence. The machine-readable strict result is stored in `docs/ontology-scale-reference-evidence.json`.

## Index Lifecycle Finding

Benchmarking exposed two production issues that are now guarded:

1. String property indexes used a `VARCHAR` coercion that was not planner-equivalent to PostgreSQL's native JSONB text extraction. Governed plans compile string values directly through `->>`.
2. Newly created expression indexes had no sampled expression statistics, allowing PostgreSQL to prefer an ordered primary-key scan. Applying a governed PostgreSQL index now runs `ANALYZE object_instances` before marking the plan active.
3. The first strict run measured numeric range/order at 993.054 ms p95 because a property-only index could not satisfy deterministic `risk DESC, id ASC` ordering. Strategy `BTREE_EXPRESSION_V3` appends object ID and aligns the keyset tie-break direction with the property order. The corrected strict p95 is 12.937 ms and the physical plan uses the governed composite expression index.

The benchmark fails if the expected property or traversal indexes disappear from physical plans.

## Remaining Scale Work

The declared 10-million-object/50-million-link reference profile is achieved on the documented development host. A separate bounded smoke workload now proves indexed reads during transactional state/event writes, rollback atomicity, statistics refresh, and connection recovery at 100,000 objects; see `ONTOLOGY_MIXED_WORKLOAD_BENCHMARK.md`. This does not establish universal capacity or strict-scale sustained mixed-workload performance. Partitioning remains evidence-driven work for write amplification, vacuum pressure, backup/recovery, and longer-running maintenance tests. The active platform goal remains incomplete until the other declared recovery, availability, OIDC, and evaluator gates pass.

# OntologyOS Runtime Core

This runtime increment makes ontology semantics, object history, bulk data, pipeline plans, and model calls explicit production contracts. Existing endpoints remain available; `/api/v1` is additive and compatibility-first.

The compatibility contract now covers the assembled product API rather than a
small manually duplicated subset. After every router is mounted,
`api_v1_compat.install_api_v1_compatibility()` adds typed `/api/v1` aliases for
eligible legacy handlers. Each alias calls the exact same endpoint and retains
its request validation, response model, dependencies, status code, streaming
class, and OpenAPI contract. Explicit v1 route-shape collisions always win;
browser pages, OIDC callbacks, health/metrics, and framework documentation stay
unversioned. `GET /api/v1/compatibility/manifest` exposes the runtime inventory,
while `oms/test_api_v1_compatibility.py` verifies state parity, tenant
authorization, permission inference, OpenAPI metadata, collision handling, and
idempotent installation. `oms/test_api_v1_route_coverage.py` caps deliberately
unversioned handlers so a new product endpoint cannot silently avoid v1.

## Semantic And Temporal Ontology

`POST /api/v1/ontology/compile` materializes normalized property and resource definitions from existing object types, profiles, links, and actions. Property definitions include constraints, display metadata, sensitivity, indexing intent, and stable order. Resource definitions preserve links, actions, interfaces, policies, datasources, and dependencies without forcing object values into an EAV model.

Current object state remains in `object_instances.properties`. Each create, action mutation, and pipeline hydration also appends an `object_change_events` record with transaction time, valid time, actor, source, before/after state, and evidence. Read history through `/api/v1/objects/{object_type_id}/{object_id}/history`.

`POST /api/v1/objects/query` compiles typed property filters, ordering, aggregates, temporal windows, radius constraints, and keyset pagination into SQL. It executes against PostgreSQL JSONB in production and SQLite JSON1 for local development. Sensitive properties are masked unless the principal has `view_sensitive` or wildcard permission. `POST /api/v1/graph/query` performs deterministic, node/edge-bounded breadth-first expansion with batched object hydration, traversal indexes, and the same property masking rules.

Properties marked `indexed` create governed index plans during semantic compilation. Inspect them with `GET /api/v1/ontology/indexes`, create explicit plans with `POST /api/v1/ontology/indexes/plan`, and require an `administer` permission to apply one through `POST /api/v1/ontology/indexes/{index_id}/apply`. Application records the exact dialect DDL, status, errors, actor, and audit evidence. PostgreSQL strategy `BTREE_EXPRESSION_V3` uses planner-compatible native JSONB extraction plus object-ID tie-breaking for ordered keyset scans and refreshes expression statistics before activation. PostgreSQL also maintains a JSONB GIN index and composite current/temporal lookup indexes through migration `0027_ontology_query_indexes`.

### Version-Bound Consumer Contracts

Published Workshop modules, shared visual artifacts, and delivered Pipeline Builder graphs persist exact downstream bindings to the active production ontology revision. Each binding records the consumer kind, ID and version, object or action target, referenced properties, structured source paths, ontology revision, and checksum. A consumer version is immutable: an idempotent repeat is accepted, but changing its contract or rebinding it to another ontology revision requires a new consumer version. Publishing that new version archives prior active bindings without deleting their evidence.

Validate a structured consumer payload with `POST /api/v1/ontology/contracts/validate`, persist it with `POST /api/v1/ontology/contracts/bind`, inspect version history through `GET /api/v1/ontology/contracts/bindings`, and read current compatibility through `GET /api/v1/ontology/contracts/health`. Health is `CURRENT` when the binding uses the active revision, `COMPATIBLE_STALE` when its targets and referenced properties still exist in a newer revision, `BROKEN` when they do not, `UNVERSIONED` for a compatible development binding without a revision, and `NO_ACTIVE_REVISION` when a versioned binding has no active production revision. Ontology publish and rollback responses include the same downstream health summary immediately.

Production defaults to strict enforcement: referenced object types, properties, and actions must exist in the active production revision. Set `ONTOLOGY_CONTRACT_ENFORCEMENT=strict` to exercise this behavior in non-production environments. Development without an active revision records compatible `UNVERSIONED` bindings with a warning; cross-project and missing live resources are always rejected.

`POST /ontology/changes/impact` and versioned change-set validation use these exact bindings for published consumers while retaining compatibility discovery for unpublished legacy resources. Property-level changes include only consumers that reference the changed field; bindings without an explicit property list intentionally represent a whole-object dependency. This prevents both silent omissions and noisy false positives during schema review.

Ontology Manager exposes this state in the object overview, a dedicated Contracts section, and the release studio. Release review names affected consumer versions and keeps breaking publication disabled until the operator explicitly acknowledges the migration plan and consumer impact. The API independently recomputes impact at publication and requires `acknowledged_consumer_binding_ids` to exactly equal the current breaking binding set. Missing, newly added, archived, or stale consumer versions return `409 DOWNSTREAM_CONSUMER_ACKNOWLEDGEMENT_REQUIRED`, preventing validation-to-publish races. Successful publish and rollback advance the authoring base revision to the revision that actually became production, preventing a subsequent change from accidentally branching from a stale draft.

## Dataset Snapshots And Pipeline Plans

Create immutable snapshots with `POST /api/v1/datasets/{asset_id}/snapshots`. The local backend writes beneath `DATA_SNAPSHOT_ROOT`; the S3 adapter uses `DATA_SNAPSHOT_BUCKET`, `DATA_SNAPSHOT_S3_ENDPOINT`, `DATA_SNAPSHOT_S3_REGION`, `DATA_SNAPSHOT_S3_ADDRESSING_STYLE`, and standard AWS credentials. `DATA_SNAPSHOT_S3_AUTO_CREATE_BUCKET=true` is intended for MinIO/demo bootstrapping; production buckets should normally be provisioned and governed separately. Parquet is the production default and JSONL is retained for deterministic fallback/interchange.

Connector-produced local Parquet files/directories or S3-compatible objects/prefixes can be registered without row materialization through `POST /api/v1/datasets/{asset_id}/snapshots/register`. Local paths remain inside `DATA_SNAPSHOT_ROOT`; S3 discovery is constrained to the configured bucket, bounded prefix, object-scan ceiling, and `DATA_SNAPSHOT_MAX_FILES`. Registration downloads each candidate once to validate size, Parquet schema, rows, bytes, and SHA-256 before metadata becomes visible. Partition manifests preserve stable relative files and per-file integrity; Hive registration recovers key-path partition fields into the public schema. Snapshot row/query APIs and DuckDB plans scan the immutable manifest through local files or the governed S3 cache.

Pipeline plans are compiled with `POST /api/v1/pipelines/{graph_id}/plans`. A plan captures the source graph lock version, topological logical plan, inferred schema, field lineage, validation result, and content hash. Execution through `/api/v1/pipeline-plans/{plan_id}/execute` delegates to the existing durable preview/deliver job runtime and rejects stale plans.

Plans compiled for the `duckdb` executor use direct Parquet SQL for the supported branching transform subset, including equi-joins, schema-aligned unions, reshape/window/validation operations, point/radius transforms, and spatial joins. S3 Parquet inputs are downloaded into the persistent `DATA_SNAPSHOT_CACHE_ROOT`, verified against snapshot or per-file manifest hashes, and then scanned through the same plan. Per-file coordination prevents duplicate concurrent downloads. `DATA_SNAPSHOT_CACHE_MAX_BYTES` bounds capacity and oldest-first pruning skips entries protected by the renewable `DATA_SNAPSHOT_CACHE_LEASE_SECONDS` window. `GET /api/v1/snapshot-cache/summary` exposes size, capacity, entries, hits, misses, downloaded bytes, integrity failures, and evictions; administrators can request lease-aware pruning with `POST /api/v1/snapshot-cache/prune`. Unique named parameters remain correct across nested branches regardless of SQL composition order. Preview materializes only bounded result rows. Delivery writes immutable single-file or Hive-partitioned output snapshots through atomic local staging, publishes files to the selected local or S3 adapter, records per-file integrity and every source snapshot in lineage, and uses the durable execution job ID for retry-safe replay. Deterministic plan/data errors are non-retriable while infrastructure failures retain worker retry semantics. See `docs/PIPELINE_SCALE_BENCHMARK.md` for the supported operations and 10-million-row evidence, and `docs/OBJECT_STORAGE_BENCHMARK.md` for separate cold/warm MinIO measurements.

For local persistent storage, Compose mounts `ontology_snapshots`. Start the optional MinIO fixture with:

```powershell
docker compose --profile object-storage up -d minio
```

For the local MinIO profile, set `DATA_SNAPSHOT_BACKEND=s3`, `DATA_SNAPSHOT_BUCKET=ontology-snapshots`, `DATA_SNAPSHOT_S3_ENDPOINT=http://minio:9000`, `DATA_SNAPSHOT_S3_ADDRESSING_STYLE=path`, `DATA_SNAPSHOT_S3_AUTO_CREATE_BUCKET=true`, and the matching MinIO credentials on the API service. Rehearse actual prefix registration, Hive schema recovery, pipeline execution, partition publication, and query from the host with `python oms/rehearse_s3_snapshot_minio.py` after MinIO becomes healthy.

Create a database and local-snapshot backup together with:

```powershell
./scripts/backup.ps1 -IncludeSnapshots
```

Restore both artifacts with:

```powershell
./scripts/restore.ps1 -BackupPath ./backups/ontology-YYYYMMDD-HHMMSS.dump -ConfirmRestore -RestoreSnapshots
```

The scripts verify separate SHA-256 checksums. Database-only backup and restore remain backward compatible. For S3, use bucket versioning and provider-native backup; the sidecar switch covers the local mounted backend.

## Governed Model Gateway

`/models/gateway/*` and `/api/v1/models/gateway/*` manage project-owned provider configurations and inference evidence. `deterministic-local` is the default. `openai-compatible` providers require both an environment-backed `secret_ref` and `external_calls_enabled`; secrets are never stored in provider rows or returned by the API.

Requests enforce model allowlists and input limits, record policy and usage evidence, and support idempotent replay. A requested ontology action is returned only as a proposal with `execution_allowed: false`; mutation must proceed through the existing policy, approval, and action runtime.

External provider URLs reject embedded credentials, enforce `MODEL_GATEWAY_ALLOWED_HOSTS`, resolve and reject private/local/reserved addresses unless `MODEL_GATEWAY_ALLOW_PRIVATE_NETWORKS=true`, and revalidate redirects. Keep private networking disabled unless model workers run in a controlled subnet.

Durable agent work is submitted through `POST /api/v1/agents/{agent_id}/tasks`, inspected through `GET /api/v1/agents/tasks/{task_id}`, and cancelled or retried through task subresources. Progress is available from `/api/v1/events/stream?job_id={task_id}`.

For independently recoverable execution, `POST /api/v1/agents/{agent_id}/task-graphs`
creates a deterministic context -> parallel tools -> synthesis DAG. The context
stage records the ontology/document retrieval pack. Each selected tool runs under
its own lease and immutable configuration snapshot, so one failed tool can be
retried without repeating successful tools. The synthesis job remains `BLOCKED`
until every stage succeeds, validates the task/config identities, and alone commits
the final `AgentToolRun`, approval requests, audit records, and Ops evidence.
Action tools only produce proposals: tool workers never mutate ontology objects,
and high-risk actions receive deterministic pending approval IDs during synthesis.
Graph cancellation cascades in dependency-safe order; graph retry resumes failed or
cancelled stages. The original `/tasks` single-job contract remains compatible.

## Current Scale Boundary

`oms/benchmark_ontology_scale_postgres.py` provides smoke and strict reference profiles with physical-plan assertions. The measured development-host boundary is 10 million objects and 50 million links: exact lookup measured 10.076 ms p95, numeric range/order 12.937 ms p95, and a 77-node/100-edge two-hop expansion 15.953 ms p95. See `docs/ONTOLOGY_SCALE_BENCHMARK.md` and its machine-readable evidence for exact conditions and limitations.

The snapshot-native pipeline reference profile has processed 10 million fact rows across eight immutable partitions through stable IDs, point/radius evaluation, SQL-native MGRS, polygon geofencing, a dimension join, a partitioned window, aggregation, direct Parquet pushdown, multi-source lineage, and idempotent recovery into 20 Hive-style output partitions. Preview measured 3,663.405 ms p95 and delivery 4,046.026 ms while only 20 result rows entered Python. The ontology reference profile separately proves 100,000 temporal mutations under eight concurrent readers on 10 million objects/50 million links, database-process restart, clean-volume physical restore, committed WAL replay, and standby promotion. Release still requires representative large-to-large spatial plans, complex high-vertex polygons, remote object-storage latency, multi-worker recovery, and the declared long-duration, external-evaluator, and availability gates.

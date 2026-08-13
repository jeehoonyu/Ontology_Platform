# Production Worker Daemon

`python -m app.worker_daemon` is an independently deployable, stateless executor for durable Pipeline, AIP Agent, connector-sync, and stream-replay jobs. It registers in the shared worker fleet, honors project and capability scope, polls compatible queues concurrently, publishes fleet heartbeats, and drains before process exit.

## Provision A Worker Identity

1. Deploy the API and Postgres without the `workers` profile.
2. Sign in as an administrator and open **Control Panel -> Auth**.
3. Create a service account in the same organization as the target project.
4. Issue a worker token for that project. The token receives only `project:<project-id>:execute` and is shown once.
5. Store it in the deployment secret manager and set `WORKER_TOKEN`. API token rows retain only a SHA-256 digest and display prefix.

Token revocation takes effect on the daemon's next API request. A `401` or `403` stops new polling and triggers daemon shutdown. Rotate by issuing a replacement token, updating the secret, rolling workers, and revoking the old token.

## Start Workers

```powershell
docker compose --env-file .env.production `
  -f docker-compose.yml -f docker-compose.production.yml `
  --profile workers up --build -d oms-worker
```

Scale with distinct stable names. Compose replicas cannot share `WORKER_NAME`; use separate environment files or an orchestrator that injects the pod/task identity.

Required settings:

- `WORKER_API_URL`: internal API URL.
- `WORKER_TOKEN`: one-time-issued service token.
- `WORKER_NAME`: stable unique fleet identity.
- `WORKER_PROJECT_ID`: optional hard project boundary.
- `WORKER_JOB_TYPES`: comma-separated capability allowlist. Production defaults include snapshot preview/delivery, resumable `industrial.ontology_hydrate`, ingestion, stream processing, event-to-stream routing, AIP agents, and `event.dispatch`. Add `event.kafka.dispatch` only after the API has valid `EVENT_KAFKA_*` broker configuration.
- `WORKER_CONCURRENCY`: maximum concurrent execution requests.
- `WORKER_LEASE_SECONDS`: durable lease interval accepted by the API.
- `DATABASE_URL`: the same PostgreSQL control plane used by the API. Snapshot-native DuckDB jobs execute inside the worker and validate publication leases directly in this database.
- `DATA_SNAPSHOT_*` and `AWS_*`: the shared immutable snapshot-store configuration. Each worker must use its own `DATA_SNAPSHOT_CACHE_ROOT`; production Compose deliberately does not mount the API cache into workers.

The daemon exposes `/health/live`, `/health/ready`, and `/metrics` on `WORKER_HEALTH_PORT` inside the container. Metrics include requests, jobs observed, successes, failures, API errors, last job, and last fleet heartbeat. They never include the bearer token or job payloads.

## Drain And Recover

SIGTERM and Ctrl+C stop new polling, wait for in-flight execution requests, call the fleet drain endpoint, and then exit. Operators can drain before replacement through `POST /runtime/workers/{name}/drain` and inspect active leases in the Control Panel.

If a process is killed before graceful drain, lease expiry returns unfinished jobs to the queue. The replacement worker receives a new lease token; stale completion attempts are fenced. Pipeline delivery, agent invocation, ingestion commits, and event transport receipts use durable IDs and active leases as their idempotency boundary. Kafka consumers should deduplicate the stable `ontologyos-event-id` header because a broker acknowledgement followed by a database interruption can cause a safe at-least-once replay.

## Dependent job graphs

`POST /jobs` accepts up to 100 same-project job IDs in `depends_on`. A dependent
job is persisted as `BLOCKED`, remains invisible to worker claims, and exposes
the current prerequisite statuses in its normal job response. The scheduler
atomically moves it to `QUEUED` only after every prerequisite succeeds. A
terminally failed, cancelled, dead-lettered, or missing prerequisite makes the
dependent job fail with `job.dependency_failed` audit and runtime-observability
evidence. Dependency IDs are immutable after creation, so cycles cannot be
introduced: every dependency must already exist when the child is created.

This primitive is also the coordinator boundary for partitioned DuckDB delivery
and durable agent task graphs.

## Partitioned DuckDB delivery

`POST /api/v1/pipeline-plans/{plan_id}/execute` accepts
`execution_strategy: partitioned` for durable delivery. The first production-safe
slice deliberately supports one immutable multi-file dataset input and row-local
operations only: filter, select/project, rename, cast, derive, null handling,
normalization, validation, latitude/longitude geometry, MGRS, spatial filtering,
and dataset output. Joins, unions, aggregates, sorting, limits, deduplication,
windows, pivots, unique-ID generation, spatial joins, and partitioned output
layouts require global state and are rejected. `execution_strategy: auto` uses the
same path when eligible and otherwise returns a documented single-worker fallback.

The scheduler creates up to 100 `pipeline.duckdb.partition` jobs over exact,
non-overlapping immutable manifest file sets. Each worker materializes one
content-hashed Parquet fragment; it does not mutate dataset metadata. A
`pipeline.duckdb.finalize` job remains `BLOCKED` until all shards succeed, verifies
every fragment hash and schema, and alone publishes the combined snapshot under
the active API lease. Its lineage records the execution group and every child job.
Terminal child failure propagates to the finalizer without publishing partial
state, while idempotency reuses the same child/finalizer graph and output snapshot.

`oms/test_distributed_duckdb_pipeline.py` proves the scheduler, shard boundaries,
fragment integrity, dependency release, lease-fenced publication, queryable output,
unsafe-plan rejection, and replay in one process. The independently deployable
worker daemon advertises and executes both job types. This is executable
distributed-worker semantics, but the checked-in test is not evidence of separate
physical hosts or managed object-store network behavior; use the production worker
recovery harness and a multi-host rehearsal for those claims.

Snapshot-native DuckDB jobs are a special local-compute path: the API claims and
leases work, but Parquet downloads, cache reads, DuckDB execution, and staging
occur in the worker process. Rehearse abrupt loss with:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/run-pipeline-worker-recovery.ps1
```

The harness creates clean PostgreSQL, MinIO, and Toxiproxy fixtures, kills the
first worker after its private cache receives data, waits for lease expiry, and
requires a second worker with a separate cache to publish exactly one fenced
snapshot. It removes all fixture containers and its network afterward.

Do not share a worker token across organizations, store it in source control, expose the worker health port publicly, or run multiple replicas with the same worker name.

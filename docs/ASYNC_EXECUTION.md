# Asynchronous Execution Runtime

The platform job runtime is a durable control plane for Pipeline, import, model, report, and AIP workers. Jobs and lifecycle events are persisted in Postgres or SQLite; workers are stateless and can be replaced without losing queued work.

## Producer Flow

Create a job with `POST /jobs`. The request supports:

- `job_type` and optional subject references
- `priority` from 0 to 100
- `max_attempts` and `timeout_seconds`
- `available_at` for delayed execution
- `idempotency_key` to prevent duplicate work for the same actor and job type
- a typed or domain-specific `payload`

The API persists an append-only receipt that scopes the key to project, actor, job type, and subject. It returns the existing job when the same request is submitted again, even after an unbounded number of later jobs or through another API replica. Reusing the key with a different payload or execution configuration returns `409`. Receipt insertion is database-unique, so concurrent producers reconcile to one job instead of enqueueing duplicate work. Job state can be inspected through `GET /jobs/{job_id}`, filtered through `GET /jobs`, or observed as server-sent events through `GET /events/stream`.

## Worker Flow

1. Claim compatible work with `POST /jobs/claim`. Supply a stable worker ID, supported job types, and lease duration.
2. Execute only when the response contains a job and lease token.
3. Send `POST /jobs/{job_id}/heartbeat` before the lease expires. Include progress, a concise status message, and non-sensitive metrics.
4. Finish with `POST /jobs/{job_id}/complete` or `/fail` using the lease token.
5. Discard the token after the terminal response. Lease tokens are intentionally excluded from normal job reads and project snapshots.

Only the current lease owner can report progress or terminate an execution. A stale token returns `409` and must not be retried as if it still owned the work.

## Recovery Semantics

- An expired worker lease or execution timeout is detected during queue reads, claims, summaries, or job inspection.
- Work is requeued while its retry budget remains; otherwise it becomes `FAILED`.
- PostgreSQL reapers lock stale jobs with `FOR UPDATE SKIP LOCKED`, so concurrent API replicas produce one recovery transition and one evidence trail.
- Retriable worker failures can set a delay before the next claim.
- Cancellation releases any active lease immediately.
- Every transition writes a `PlatformJobEvent` for SSE, audit, UI evidence, and incident correlation.

Recovery records the abandoned worker, prior lease expiry, incremented attempt, a dedicated runtime-observability `recovery` span, audit evidence, and a warning Ops event. A replacement worker receives a new lease token; completion with the abandoned token is fenced with `409`.

Workers should make side effects idempotent because a process can fail after performing work but before acknowledging completion. Use the platform job ID as the downstream idempotency key when writing datasets, invoking actions, or publishing reports.

Migration `0013_job_idempotency` backfills retained legacy job keys into `platform_job_idempotency_receipts`. Legacy duplicates are preserved as job evidence, while the earliest job becomes the replay target for that scope. Receipts are included in portable snapshots and authoritative database backups.

## Operations

`GET /jobs/summary` reports status counts, counts by job type, active workers and leases, oldest queue age, and stale jobs recovered during the request. The React shell polls this endpoint every 15 seconds and highlights failed work without exposing worker credentials.

Recommended alerts:

- failed jobs greater than zero for production-critical job types
- oldest queued time above the service-level objective
- no active workers while runnable jobs are queued
- repeated retry exhaustion for the same subject
- progress heartbeats that remain unchanged across multiple lease intervals

The worker API requires the backend `execute` permission. Production workers should use a dedicated service principal with only the job types and downstream permissions they require.

## Fleet and Queue Control

Production workers should register through `PUT /runtime/workers/{worker_name}`. Registration constrains project scope, supported job types, and maximum concurrent leases. Drain and resume endpoints support rolling worker deployment without abandoning active jobs.

The repository includes an independently deployable worker process at `python -m app.worker_daemon` and an optional production Compose `workers` profile. It uses a hashed, project-scoped service token, registers and heartbeats automatically, runs Pipeline, AIP Agent, and ingestion jobs concurrently, exposes container health, and drains on termination. See [Production Worker Daemon](WORKER_DAEMON.md).

Project queue policies configure fair-share weight, hard project concurrency, and claim pause state. Dispatch is fair across projects and priority-ordered within a project. Postgres serializes the final project-capacity decision by locking the queue policy row before a lease is committed. See [Worker Fleet and Fair Queue Control](WORKER_FLEET_CONTROL.md).

## Pipeline Integration

Pipeline Builder uses the runtime through:

- `POST /pipeline-builder/graphs/{graph_id}/preview/async`
- `POST /pipeline-builder/graphs/{graph_id}/deliver/async`
- `POST /pipeline-builder/workers/run-next`

The React workbench queues preview and deployment requests, executes the exact submitted job through the local worker adapter, polls durable status, and exposes progress, attempts, cancellation, retry, and event evidence. A separately deployed worker can use the same claim protocol instead of the local adapter.

Delivery uses the platform job ID as its transaction idempotency key. Before committing dataset transactions or ontology mutations, it locks and verifies the active job and lease. A retry after a worker failure returns the prior successful build rather than materializing the output twice. Cancellation is cooperative until this guarded commit boundary.

## AIP Agent Integration

Agent Studio uses the runtime through:

- `POST /aip/agents/{agent_id}/invoke/async`
- `POST /aip/agents/workers/run-next`
- `GET /aip/agents/{agent_id}/runs`

Each durable run persists its retrieved ontology context, selected tool inputs and outputs, citations, execution timing, policy decisions, proposed actions, and approval references. Governed action tools never mutate objects during agent invocation. Required action parameters are validated before proposal; invalid tools receive a `DENIED` decision and create no approval. Valid governed actions create a pending approval request when policy requires one and record `direct_mutations: 0` in the policy summary.

The execution job ID uniquely identifies the persisted agent run. Replaying the same job returns the prior run, while producer idempotency prevents duplicate jobs. Immediately before committing a run or approval request, the worker locks and verifies the active job and lease; cancellation or lease loss rolls back the entire invocation.

The React AIP workspace exposes this lifecycle as an Agent Runtime panel with progress, attempts, cancellation, retry, grounded answer, citation counts, tool policy decisions, and approval IDs. Raw tool payloads remain outside the normal user path.

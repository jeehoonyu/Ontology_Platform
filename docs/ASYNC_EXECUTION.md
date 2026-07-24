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

The API returns the existing job when the same idempotency key is submitted again. Job state can be inspected through `GET /jobs/{job_id}`, filtered through `GET /jobs`, or observed as server-sent events through `GET /events/stream`.

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
- Retriable worker failures can set a delay before the next claim.
- Cancellation releases any active lease immediately.
- Every transition writes a `PlatformJobEvent` for SSE, audit, UI evidence, and incident correlation.

Workers should make side effects idempotent because a process can fail after performing work but before acknowledging completion. Use the platform job ID as the downstream idempotency key when writing datasets, invoking actions, or publishing reports.

## Operations

`GET /jobs/summary` reports status counts, counts by job type, active workers and leases, oldest queue age, and stale jobs recovered during the request. The React shell polls this endpoint every 15 seconds and highlights failed work without exposing worker credentials.

Recommended alerts:

- failed jobs greater than zero for production-critical job types
- oldest queued time above the service-level objective
- no active workers while runnable jobs are queued
- repeated retry exhaustion for the same subject
- progress heartbeats that remain unchanged across multiple lease intervals

The worker API requires the backend `execute` permission. Production workers should use a dedicated service principal with only the job types and downstream permissions they require.

# Runtime Observability and Cost Controls

The runtime observability layer correlates every durable job with its project, actor, workflow type, worker lifecycle, progress, retries, timing, usage, cost estimate, and terminal result.

## Job Evidence

Durable jobs are instrumented at these transitions:

- queued and budget admitted
- worker claimed
- heartbeat and progress
- retry or stale-lease recovery
- succeeded, failed, or cancelled

`GET /runtime/observability/jobs` lists project-scoped observations. `GET /runtime/observability/jobs/{job_id}` returns the correlated spans and metrics for one job. Historical jobs are backfilled safely with unique, conflict-tolerant inserts when a project summary is first opened.

## Project Budgets

`PUT /runtime/observability/budgets` configures rolling limits for executions, compute seconds, token units, record units, or estimated cost. A `HARD` policy rejects a job before it enters the queue. A `WARN` policy retains the projected overage as admission evidence without blocking execution.

Job submission accepts explicit estimates:

- `estimated_compute_seconds`
- `estimated_cost_usd`
- `estimated_tokens`
- `estimated_records`

Workers replace estimates with observed values when they report progress or complete.

## Service-Level Objectives

Runtime SLO policies support availability, error rate, p95 execution latency, p95 queue latency, cost, and throughput. Policies can cover every project job or one job type. Evaluation writes immutable evidence and emits an Ops event on breach.

The React Control Panel Runtime tab shows project scope, availability, p95 latency, queue delay, estimated cost, job evidence, budgets, and SLO controls without exposing raw JSON.

## Recovery and Isolation

Observations, budgets, SLO policies, and evaluations are included in project export/import and database backup. All APIs enforce both global permission and project membership. Concurrent historical backfill is tested with multiple readers to ensure one observation per job.

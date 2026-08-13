# Worker Fleet and Fair Queue Control

The durable job runtime supports independently deployed, stateless workers sharing one Postgres control plane. Workers can be registered with project scope, supported job types, concurrency, and operational labels.

## Worker Lifecycle

1. Register or update a worker with `PUT /runtime/workers/{worker_name}`.
2. Claim work through `POST /jobs/claim` using the same stable worker name.
3. Heartbeat the worker registration and each active job lease.
4. Drain a worker before deployment with `POST /runtime/workers/{worker_name}/drain`.
5. Allow active jobs to finish, replace the process, then call `/resume`.

A registered worker cannot claim outside its project or declared job-type capabilities. Its active lease count cannot exceed `max_concurrency`. Unregistered workers remain supported for local compatibility, but production workers should always be registered and authenticated by a project-scoped service account.

## Fair Project Queues

`PUT /runtime/queues/{project_id}` configures:

- `weight`: proportional dispatch share across projects
- `max_concurrency`: hard active-job limit for the project
- `paused`: stop new claims without cancelling active jobs

Claims are ordered by historical dispatch share across projects and by priority and age within each project. On Postgres, the policy row is locked and project concurrency is rechecked immediately before the lease is committed. A unique job lease fences simultaneous workers that race for the same job.

## Failure and Recovery

- Expired leases requeue work while retry attempts remain.
- The old lease token is rejected after recovery, so a stale worker cannot commit success.
- Pipeline, agent, and ingestion workers use the job ID as their downstream idempotency key.
- Worker registrations and queue policies are included in project snapshots. Restored workers are forced to `OFFLINE` and must be explicitly resumed.

`GET /ui-state/worker-fleet` provides a human-facing fleet summary for the Control Panel. Runtime observations, budgets, and SLOs remain available through `/runtime/observability/*`.

SQLite uses WAL and a bounded busy timeout for local concurrency tests and small deployments. Postgres is required for multiple API or worker replicas and transactional queue-policy locking.

# Durable Ingestion Runtime

The ingestion runtime executes connector syncs and stream replays through the same durable job control plane used by pipelines and agents. Resources and jobs carry a project identity, and worker claims are filtered by project permissions.

## Runtime Flow

1. Create a project-scoped connection source and sync, or stream.
2. Enqueue work through `/ingestion/syncs/{id}/enqueue` or `/ingestion/streams/{id}/replay/enqueue`.
3. A worker claims the job through `/ingestion/workers/run-next`.
4. The worker heartbeats its lease, validates budgets, writes data and run evidence in one transaction, and completes the durable job.
5. Invalid records enter `/ingestion/dead-letters`; failed jobs follow the configured retry policy.

Each enqueue request accepts an idempotency key. Repeating the same key in a project returns the original run. A worker that crashes after the data transaction commits but before job completion detects the completed ingestion run and completes the recovered job without writing records twice.

## Cost and Performance Controls

Use `PUT /ingestion/budgets` to set per-project rolling limits for:

- `records`
- `bytes`
- `estimated_cost_usd`

`HARD` budgets reject execution before mutation. `WARN` budgets retain evidence without blocking. `/ingestion/summary` reports processed records, bytes, estimated cost, run status counts, pending dead letters, and current budget definitions.

The local cost estimate is deterministic and intended for governance testing. Production adapters can replace it with provider-specific billing metrics while retaining the same run contract.

## Recovery

- Worker leases and heartbeats recover abandoned work.
- Retriable failures return to the queue up to `max_attempts`.
- Terminal failures create dead-letter evidence.
- `/ingestion/dead-letters/{id}/replay` creates a new idempotent recovery job.
- Project export/import includes ingestion runs, budgets, and dead letters.
- Database backup remains the authoritative disaster-recovery mechanism.

## Connector Adapters

`GET /ingestion/connectors/catalog` describes the built-in REST, JDBC, S3, SFTP, and Kafka adapter contracts. The deterministic local runtime uses configured sample records in tests; external adapter processes can supply fetched records to the enqueue contract without bypassing project authorization, budgets, job leases, or audit evidence.

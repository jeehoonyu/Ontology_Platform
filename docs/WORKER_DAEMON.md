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

The daemon exposes `/health/live`, `/health/ready`, and `/metrics` on `WORKER_HEALTH_PORT` inside the container. Metrics include requests, jobs observed, successes, failures, API errors, last job, and last fleet heartbeat. They never include the bearer token or job payloads.

## Drain And Recover

SIGTERM and Ctrl+C stop new polling, wait for in-flight execution requests, call the fleet drain endpoint, and then exit. Operators can drain before replacement through `POST /runtime/workers/{name}/drain` and inspect active leases in the Control Panel.

If a process is killed before graceful drain, lease expiry returns unfinished jobs to the queue. The replacement worker receives a new lease token; stale completion attempts are fenced. Pipeline delivery, agent invocation, ingestion commits, and event transport receipts use durable IDs and active leases as their idempotency boundary. Kafka consumers should deduplicate the stable `ontologyos-event-id` header because a broker acknowledgement followed by a database interruption can cause a safe at-least-once replay.

Do not share a worker token across organizations, store it in source control, expose the worker health port publicly, or run multiple replicas with the same worker name.

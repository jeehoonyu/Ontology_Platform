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

`GET /connectors/adapters` is the executable adapter catalog. REST, JDBC, S3-compatible, and SFTP adapters fetch live records inside the durable ingestion boundary. Kafka appears as unavailable until a deployment registers a plugin through `CONNECTOR_PLUGIN_MODULES`; the API does not advertise integrations as implemented when no adapter is installed.

The S3 adapter signs requests with AWS Signature Version 4 and supports AWS S3 or path-style S3-compatible HTTPS endpoints. Store the secret access key as an `aws` runtime credential and set `access_key_id` (plus optional `session_token`) in credential metadata. Source configuration contains only non-secret fields: `bucket`, `region`, optional `endpoint_url`, `prefix`, `format`, and bounded object/record/byte limits. CSV, JSON arrays/objects, and JSONL are supported. For incremental syncs, use `_source_object_key` as the cursor field; successful object keys become the durable high-water mark.

The SFTP adapter requires a SHA-256 host-key pin and never accepts unknown hosts. Configure `host`, `port`, `username`, `remote_path`, and `host_key_sha256`; store either a `sftp_password` or unencrypted Ed25519/ECDSA/RSA private key as a write-only runtime credential. CSV, JSON, and JSONL files are decoded under file, byte, and record limits. Use `_source_file_path` as the incremental cursor field. Private SFTP networks remain blocked unless `CONNECTOR_ALLOW_PRIVATE_NETWORKS=true` is explicitly enabled in a controlled connector network.

The optional local demonstration uses a real SSH/SFTP server:

```powershell
docker compose --profile connectors up -d sftp-source
docker compose exec sftp-source ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub -E sha256
```

Use host `127.0.0.1`, port `2222`, username `demo`, remote path `/upload`, the printed `SHA256:` fingerprint, and a `sftp_password` credential with the demo password `demo`. This credential is only for the local profile.

Set those values as `SFTP_REHEARSAL_*` environment variables and run `python oms/rehearse_sftp_connector.py` to verify the full external-service preview and durable worker path.

Live REST sources enforce response limits, timeouts, redirect validation, and SSRF controls. Live JDBC sources accept PostgreSQL or local-development SQLite, reject mutating SQL, and require parameterized limits and cursors for custom queries. SQLite sources are disabled in the production profile unless explicitly enabled.

Credentials are stored separately from source configuration using Fernet encryption. Set `CONNECTOR_SECRET_KEY` and rotate `CONNECTOR_SECRET_KEY_ID` through deployment operations. Credential read APIs return metadata only; secrets are write-only. Portable project JSON exports intentionally omit credentials, while database backup and restore preserve encrypted credential rows. Rebind credentials after importing a portable project snapshot.

Use these operational APIs:

- `POST /connections/sources/{id}/runtime-credentials` rotates a bearer token, API key, or basic-auth password.
- `POST /connections/sources/{id}/live-preview` verifies a live source and persists fetch evidence.
- `GET /connections/sources/{id}/fetch-attempts` returns durable success/failure evidence without exposing secrets.
- `/ingestion/syncs/{id}/enqueue` and `/ingestion/workers/run-next` execute live fetches through leases, retries, cursor commits, budgets, dead letters, and idempotent dataset writes.

Production REST egress denies private, loopback, link-local, and unspecified addresses by default. Use `CONNECTOR_ALLOWED_HOSTS` for explicit destination names. `CONNECTOR_ALLOW_PRIVATE_NETWORKS=true` is intended only for controlled connector networks and local demonstrations.

# Production Pilot Operations

This deployment profile is intended for one organization and a small pilot team. It uses Postgres, OIDC, server-side sessions, TLS, versioned visual artifacts, and persistent Docker volumes.

Builder authoring and recovery behavior is documented in [Visual Builder Operations](VISUAL_BUILDERS.md).
Worker deployment and queue recovery behavior is documented in [Asynchronous Execution Runtime](ASYNC_EXECUTION.md).

## Prepare

1. Copy `deploy/.env.production.example` to `.env.production` and replace every placeholder.
2. Configure an OIDC client with Authorization Code flow, PKCE, and the callback `${PUBLIC_BASE_URL}/auth/callback`.
3. Map provider roles to `viewer`, `editor`, `operator`, `approver`, `publisher`, or `administrator`. Override `OIDC_ROLES_CLAIM` when roles are stored under a different claim.
4. Emit `organization_id` and a string-array `project_ids` claim. Effective access requires both a global role permission and project membership/claim. See [Project Tenancy And Ontology Packages](TENANCY_AND_PACKAGES.md).
5. Point `PUBLIC_HOST` at the server. Caddy obtains and renews TLS certificates automatically for public DNS names.
6. Generate a separate `CONNECTOR_SECRET_KEY`, configure `CONNECTOR_ALLOWED_HOSTS` (for AWS S3 this can include `s3.*.amazonaws.com`), and keep private-network connector access disabled unless the API runs in a controlled connector subnet. See [Durable Ingestion Runtime](DURABLE_INGESTION_RUNTIME.md).
7. For S3-backed dataset snapshots, provision `DATA_SNAPSHOT_BUCKET`, configure endpoint/region/addressing style and standard AWS credentials, and mount persistent `DATA_SNAPSHOT_CACHE_ROOT` storage on every API/worker that executes DuckDB plans. Size `DATA_SNAPSHOT_CACHE_MAX_BYTES` for concurrent working sets and keep `DATA_SNAPSHOT_CACHE_LEASE_SECONDS` at least as long as the maximum pipeline execution timeout. Monitor `/api/v1/snapshot-cache/summary`. Keep `DATA_SNAPSHOT_S3_AUTO_CREATE_BUCKET=false` in production; it is only for controlled MinIO demonstrations.

Production startup fails when `AUTH_MODE` is not `oidc` or required OIDC settings are missing. The local administrator bypass is therefore unavailable in the production profile.

## Deploy

```powershell
docker compose --env-file .env.production -f docker-compose.yml -f docker-compose.production.yml up --build -d
docker compose --env-file .env.production -f docker-compose.yml -f docker-compose.production.yml ps
```

### Start the pilot evidence clock

For an availability-only window, start the external observer with the production deployment. It has
no database or identity credentials and probes the API over the Compose network:

```bash
docker compose --env-file .env.production \
  -f docker-compose.yml -f docker-compose.production.yml \
  --profile pilot-observability up --build -d
```

The observer writes a hash-chained journal and a separate tail anchor to the
`ontology_pilot_evidence` volume. A restart resumes the same run at the same
migration head. Every missed 30-second schedule slot is appended as unavailable,
so stopping the observer cannot improve measured availability. The API mounts the
volume read-only and exposes progress through **Control Panel -> Runtime** and
`GET /runtime/pilot-evidence`. Availability collection needs no credential.

**Collecting all three gates requires this observer.** An earlier revision of
this page said the opposite -- to use the host scheduler alone and not to run the
observer beside it. That is wrong in both directions, and either way costs a
week:

- The host scheduler and the observer are indeed two writers for one journal, but
  the configuration below deliberately points `PILOT_EVIDENCE_ROOT` at the same
  directory as `PILOT_EVIDENCE_PATH`, so following the instructions produced the
  collision the warning forbade.
- Letting the host scheduler own availability does not avoid this; it fails
  differently. A recovery rehearsal blocks that process for as long as a restore
  takes, and every 30-second slot it misses is backfilled as unavailable.
  99.9% over seven days allows 604.8 seconds of downtime in total -- less than a
  single PostgreSQL restore, and there are roughly twelve rehearsals in a window.

So the observer owns the availability journal and keeps probing throughout each
rehearsal, and the host supervisor writes no availability sample. It instead
fails its tick when the observer stops advancing, so a dead observer is a loud
failure rather than a silent gap. This is what
`--availability-writer observer` selects, and it is the default;
`pilot_window.py start` refuses `--availability-writer scheduler` outright.

Complete availability, RPO, and RTO collection is deliberately a host-scheduled operation because it
must create and remove an isolated database/API stack. Configure a separate
high-entropy `PILOT_RECOVERY_TOKEN` on both source and recovered APIs. The
internal `/health/pilot-recovery/*` protocol is disabled when the token is empty,
rejects tokens shorter than 32 characters in production, and persists marks in
the transactional event outbox so ordinary backup and restore carries them.

Set `PILOT_EVIDENCE_PATH` in `.env.production` to a protected absolute host
directory and restart the API so Control Panel reads that directory through its
read-only mount. Set the host process's `PILOT_EVIDENCE_ROOT` to the same path.
Do not use the opaque named-volume default for the complete host-scheduled mode.

Start one migration-scoped pilot manifest from the project checkout. The source
and recovery URLs must resolve to different scheme/host/port/path identities.
The restore command must leave the isolated API running; the cleanup command is
executed after RPO observation even when measurement fails.

For a small pilot using local snapshot and plugin volumes, the shipped reference
driver provides those commands. Configure `PILOT_SOURCE_COMPOSE_FILES`, distinct
`PILOT_SOURCE_PROJECT` and `PILOT_RECOVERY_PROJECT` values, a protected absolute
`PILOT_BACKUP_ROOT`, `PILOT_RECOVERY_URL`, and an immutable `ONTOLOGY_IMAGE` as
shown in `.env.production.example`. Set a separate high-entropy
`PILOT_BACKUP_INTEGRITY_KEY`; it authenticates manifests but is never written to
them. Validate both Compose topologies before
opening the window:

```powershell
python oms/pilot_postgres_recovery.py validate
python oms/pilot_postgres_recovery.py backup
```

The backup command checks the live database migration head, validates the custom
PostgreSQL archive, checksums the database and local file-volume archives,
authenticates the manifest with HMAC-SHA256, and atomically advances a pointer
bound to the exact manifest bytes. The restore command verifies every
checksum before Docker mutation, removes only the distinct recovery project and
its volumes, waits past PostGIS's temporary initialization server, restores and
validates the database, restores snapshot/plugin volumes, then starts the
loopback-only recovery API. `cleanup` removes that isolated project and volumes.

### Freeze the schema first

A window is void the moment the migration head changes, and `tick` enforces that
destructively: it aborts, and the days already collected are gone. Declare the
freeze before opening the window so a migration fails CI instead:

```powershell
python oms/validate_schema_freeze.py
```

`docs/SCHEMA_FREEZE.json` holds the frozen head, an owner, a reason, and an end
date. While it is open, `validate_schema_freeze.py` fails the build for any other
head, so the pull request that would have voided the window goes red rather than
the window dying silently a week later. An expired freeze also fails, so the file
cannot decay into something that looks like protection and is not. Opening and
closing a freeze are both ordinary reviewable commits.

### Preflight

Check the configuration before opening the window. Every failure `preflight`
reports is one that would otherwise surface as a failed gate seven days later,
when the only remedy is another seven days:

```powershell
$env:PILOT_EVIDENCE_ROOT = 'C:\ontology-pilot-evidence'
$env:PILOT_RECOVERY_TOKEN = '<same-random-secret-configured-on-both-apis>'
python oms/pilot_window.py preflight `
  --target $env:PILOT_SOURCE_URL `
  --recovery-target $env:PILOT_RECOVERY_URL `
  --recovery-driver postgres-compose
```

It checks that the evidence root is writable and holds no open window, that both
health endpoints answer 200 inside the contract's 2,000 ms, that the recovery URL
is a different scheme/host/port/path identity, that the recovery token is long
enough *and actually accepted* by the source API (a read-only request against a
run that does not exist: 404 proves the credential, 401 or 403 disproves it),
that both Compose topologies parse and their URLs match the targets, that the
observer is currently writing, and that there is disk for the journals and
backups. It also prints the migration head, which must not change for seven days.

```powershell
python oms/pilot_window.py start `
  --target $env:PILOT_SOURCE_URL `
  --recovery-target $env:PILOT_RECOVERY_URL `
  --project-id operations `
  --recovery-driver postgres-compose
```

This logical backup driver is a complete, executable pilot reference, not the
large-scale five-minute backup architecture. At production data volume, replace
the three manual command hooks with tested WAL archival, incremental snapshots,
or a managed equivalent; keep the scheduler's distinct-target, marker, head,
write-probe, cleanup, and evidence requirements unchanged.

```powershell
$env:PILOT_EVIDENCE_ROOT = 'C:\ontology-pilot-evidence' # same as PILOT_EVIDENCE_PATH
$env:PILOT_RECOVERY_TOKEN = '<same-random-secret-configured-on-both-apis>'
python oms/pilot_window.py start `
  --target https://ontology.example.com `
  --recovery-target http://127.0.0.1:18001 `
  --project-id operations `
  --backup-command '<incremental backup or WAL checkpoint command>' `
  --restore-command '<start isolated restored database and API>' `
  --recovery-cleanup-command '<remove only the isolated recovery stack>'
```

The explicit-command form above remains the required path for WAL/incremental or
cloud-native recovery systems.

Run the supervisor. Do **not** schedule `tick`:

```powershell
python oms/pilot_window.py run
```

This form is for watching a window interactively, and it inherits
`PILOT_EVIDENCE_ROOT` and `PILOT_RECOVERY_TOKEN` from the shell that starts it.
A seven-day window should not depend on that shell surviving seven days, so the
registered form below passes the evidence root explicitly and reads the token
from a protected file:

```powershell
python oms/pilot_window.py `
  --evidence-root 'C:\ontology-pilot-evidence' `
  --environment-file 'C:\ontology-secrets\pilot-runtime.env' `
  --token-file 'C:\ontology-secrets\pilot-recovery-token' `
  run
```

The two are the same supervisor; only how it is bound differs. Prefer the second
for anything that must outlive a terminal, and pass the same flags to `status`
and `aggregate` so they read the window the supervisor is actually writing.

`pilot_window.py run` is one process that ticks every 30 seconds for the whole
window. An earlier revision of this page said to schedule `tick` every 30 seconds
from cron or Task Scheduler. Neither can do that. `schtasks /SC MINUTE` takes
1..1439 *minutes* and cron's finest field is a minute, so the real cadence would
be 60 seconds against a contract fixed at 30 -- and because an unwritten slot is
scored as unavailable, every second slot becomes downtime. Measured against a
target that returned 200 to every real probe: **57.1% availability**, converging
to 50%, against a 99.9% gate.

To survive reboots across the seven days, register the supervisor at startup:

```powershell
New-Item -ItemType File -Path 'C:\ontology-secrets\pilot-recovery-token' -Force
# Write the same 32+ character recovery token used by both APIs, then restrict
# this file to the scheduled-task account before registration.
./scripts/register-pilot-window.ps1 `
  -EvidenceRoot 'C:\ontology-pilot-evidence' `
  -TokenFile 'C:\ontology-secrets\pilot-recovery-token' `
  -EnvironmentFile 'C:\ontology-secrets\pilot-runtime.env'
Start-ScheduledTask -TaskName OntologyPilotWindow
```

The runtime environment file contains the persistent `PILOT_SOURCE_*`,
`PILOT_RECOVERY_*`, backup, image, and integrity settings from the validated
preflight environment. Keep the bearer token in its separate token file. The
task action contains only paths: it passes the evidence root explicitly and
loads both protected files at process start, so it does not depend on the shell
that opened the window or place a secret in the Task Scheduler command line.
Registration rejects either protected file when it is readable by Everyone,
Authenticated Users, or the built-in Users group.

On a systemd host, keep the nonsecret recovery-driver variables in a root-owned
environment file and the recovery token in a separate mode-`0600` file readable
by the service account:

```bash
sudo ./scripts/install-pilot-window-systemd.sh \
  --evidence-root /var/lib/ontology/pilot-evidence \
  --token-file /etc/ontology/pilot-recovery-token \
  --environment-file /etc/ontology/pilot-runtime.env \
  --user ontology
journalctl -fu ontology-pilot-window.service
```

Both installers refuse an unopened window or a stale availability observer.
They also reject broad token permissions; the systemd path proves the service
account can read the token and, for the Compose recovery driver, reach Docker.
Before registration, `verify-runtime` checks that the protected files still
name the window's source and isolated recovery targets, match the frozen
migration head, and authenticate against the live recovery protocol.
The generated service starts after Docker and network readiness and restarts
only after the 150-second single-writer lock has become reclaimable.

The supervisor takes a single-writer lock on the evidence root. Concurrent
journal appends are already serialized and duplicate slots rejected, so a second
supervisor could not corrupt the hash chain -- it would corrupt the *window*, by
read-modify-writing the same manifest and discarding the other's backup and
recovery counters. The lock's heartbeat goes stale after 150 seconds, which is
why the registration script requires a restart interval of at least three
minutes.

The default backup
cadence is five minutes and the default isolated recovery cadence is fourteen
hours, yielding at least ten recovery samples in seven days. A full `pg_dump`
every five minutes is not a scalable production design; use WAL archival,
streaming backup, or an equivalent incremental mechanism. The harness measures
the result and cannot make a six-hour backup policy satisfy a five-minute RPO.
Each isolated restore is also an unattended RTO rehearsal and is followed by an
RPO observation. A due pre-backup observation restores the previous recovery
point before the new backup command runs, preserving the worst-case sample.
Missing credentials, a same-target configuration, migration mismatch, failed
restore, failed authenticated write, or failed cleanup makes the scheduler tick
nonzero and remains visible in the evidence journal.

Do not emit gate evidence during the collection window: an incomplete aggregate
is correctly a failure, and failure evidence is intentionally not overwritten by
a later pass. After seven full days, aggregate inside the observer and copy the
result into the release evidence set:

```bash
docker compose --env-file .env.production \
  -f docker-compose.yml -f docker-compose.production.yml \
  --profile pilot-observability exec -T pilot-observer \
  python /app/availability_probe.py aggregate \
  --samples-file /var/lib/ontology/pilot-evidence/availability-samples.jsonl \
  --state-file /var/lib/ontology/pilot-evidence/availability-probe-state.json \
  --output-dir /var/lib/ontology/pilot-evidence/generated

docker compose --env-file .env.production \
  -f docker-compose.yml -f docker-compose.production.yml \
  --profile pilot-observability cp \
  pilot-observer:/var/lib/ontology/pilot-evidence/generated/tier-b-availability-evidence.json \
  docs/tier-b-availability-evidence.json
```

Any hash mismatch, duplicate schedule, torn record, or journal rollback behind
the persisted anchor invalidates the run. A schema migration begins a new run;
evidence from a previous migration head remains stale by design.

After the seven-day host scheduler reports complete, run
`python oms/pilot_window.py aggregate`. It emits availability, RPO, and RTO gate
files under `${PILOT_EVIDENCE_ROOT}/generated`; copy those immutable outputs into
the release evidence set only after all three report `PASS`.

Verify `https://${PUBLIC_HOST}/health/live`, `/health/ready`, and then `/workspace/command-center`. API containers apply the Alembic schema baseline before accepting traffic. PostgreSQL deployments serialize concurrent migration startup with an advisory transaction lock, allowing multiple replicas to start against a fresh database without racing schema DDL.

For an isolated OIDC demonstration, start the optional Keycloak service with `--profile demo-idp`, update `OIDC_ISSUER` to the reachable realm URL, and create at least one user with a supported realm role. When the identity provider has a private service address, set `OIDC_BACKCHANNEL_BASE_URL` so discovery, token, and JWKS requests avoid the public ingress path; ID-token issuer validation still uses `OIDC_ISSUER`. Do not use the included development realm configuration as an internet-facing identity service.

### Isolated production rehearsal

The rehearsal profile uses separate containers, ports, and a named Postgres volume. It validates real OIDC redirects and backend RBAC without touching the default development stack:

```powershell
./scripts/start-production-rehearsal.ps1 `
  -KeycloakAdminPassword '<temporary-admin-password>' `
  -PilotAdminPassword '<temporary-pilot-admin-password>' `
  -PilotViewerPassword '<temporary-pilot-viewer-password>' `
  -PostgresPassword '<temporary-postgres-password>'

$env:PRODUCTION_BASE_URL='http://localhost:18000'
$env:PILOT_ADMIN_PASSWORD='<temporary-pilot-admin-password>'
$env:PILOT_VIEWER_PASSWORD='<temporary-pilot-viewer-password>'
cd frontend
npm run test:production-oidc
cd ..
```

The rehearsal assigns both users to organization `pilot` and project `default`. The browser check proves that `pilot-admin` can mutate an artifact while `pilot-viewer` can read it but receives `403` for the same mutation. Remove all isolated containers and data after the rehearsal:

```powershell
./scripts/stop-production-rehearsal.ps1 -DeleteData
```

For the complete release gate, run the self-cleaning acceptance rehearsal instead:

```powershell
./scripts/rehearse-production-acceptance.ps1
```

It generates temporary secrets; starts digest-pinned Keycloak, Postgres, and two API replicas; registers the declared `organization_id` and `project_ids` claims; and runs the production browser workflow. The workflow verifies PKCE-backed OIDC sessions, administrator/viewer RBAC, organization boundaries, authenticated collaboration WebSockets, and own-data onboarding. Generated ontology resources are captured into a governed change set, validated, approved, and published before strict pipeline delivery; a delivery attempt without that active contract is rejected. It also creates project-owned Workshop, Action Type, AIP Logic, Agent, model endpoint, and evaluation resources, queues an asynchronous agent invocation, rejects cross-project creation, and proves viewers cannot mutate, execute, evaluate, invoke, publish, run Asset Reliability triage, or export its evidence report. The remaining gate exercises 50 concurrent reads, Asset Reliability approval/reporting, cross-replica collaboration and job idempotency, isolated plugin executor loss/recovery, abandoned-worker recovery with fencing, serialized Alembic startup, API restart, 200 distinct PKCE identities across two replicas, and fresh-volume backup/restore. Identity provisioning defaults to concurrency 20 while the browser login stage defaults to concurrency 10; this keeps Chromium stable after the preceding image/plugin workload without weakening the separate 20-editor collaboration gate. Use `-KeepStack` only for troubleshooting and `-SkipRecovery` only when the separate recovery gate has already passed for the same build; the success message explicitly records when recovery was skipped.

For direct WebSocket process-loss evidence against a migrated PostgreSQL database, run `COLLABORATION_WS_EVIDENCE_PATH=docs/collaboration-websocket-chaos-evidence.json python oms/verify_collaboration_websocket_chaos_postgres.py`. Production WebSocket origins default to `PUBLIC_BASE_URL`; add trusted alternate ingress origins through the comma-separated `WEBSOCKET_ALLOWED_ORIGINS` setting.

The complete containerized rehearsal remains available as the manually dispatched `Production acceptance` GitHub Actions workflow. Every pull request and push to `master` also runs the automatic `Continuous integration` workflow without duplicating feature-branch push runs. Its required jobs cover all backend scripts and docs conformance, SQLite and PostgreSQL migrations, frontend dependency audit/typecheck/build, the responsive WCAG browser suite, production Compose validation, and the multi-stage application image build. Protect `master` with these checks before accepting changes. The manual rehearsal remains the final OIDC, replica, load, chaos, and fresh-volume recovery gate for a release candidate.

The bundled Keycloak realm and user-profile files are demonstration fixtures. They are not an internet-facing identity service. A production identity provider must emit equivalent tenant claims and restrict their administration to trusted identity operators.

## Back Up and Restore

Create a database backup from the project root. Include local dataset snapshot files for a complete local-data-plane backup:

```powershell
./scripts/backup.ps1 -IncludeSnapshots
```

To target an isolated or non-default Compose project explicitly:

```powershell
./scripts/backup.ps1 `
  -ComposeFile ./docker-compose.rehearsal.yml `
  -ProjectName ontology_rehearsal `
  -DatabaseUser ontology `
  -DatabaseName ontology
```

Restore requires explicit confirmation. The script validates the archive, restores into a staging database, stops configured writers, and swaps databases only after the staging migration check passes:

```powershell
./scripts/restore.ps1 `
  -BackupPath ./backups/ontology-YYYYMMDD-HHMMSS.dump `
  -ConfirmRestore `
  -RestoreSnapshots `
  -RestorePlugins `
  -KeepPreviousDatabase
```

Pass the same `ComposeFile`, `ProjectName`, `DatabaseUser`, and `DatabaseName` options to `restore.ps1` for non-default stacks. Database, local snapshot, and signed-plugin archives have separate adjacent SHA-256 evidence and are recorded in the JSON manifest. Create them with `-IncludeSnapshots -IncludePlugins`. S3-backed snapshots require provider-native bucket backup/versioning. See `docs/RECOVERY.md` for staged swap, rollback, credential rebinding, and acceptance procedures.

Rehearse backup and restore against a fresh isolated Postgres volume:

```powershell
./scripts/rehearse-recovery.ps1
```

After restoration, verify `/health/ready`, sign in, inspect `/workspace/validation`, and compare artifact, object, audit, incident, and report counts. Editing leases and login sessions are intentionally ephemeral and are not part of project JSON exports.

## Upgrade and Roll Back

1. Run `./scripts/backup.ps1`.
2. Pull the reviewed release and run the production Compose command with `up --build -d`.
3. Check migration output, readiness, the Validation workspace, and the Asset Reliability workflow.
4. For rollback, restore the pre-upgrade database backup and deploy the previous application image. The baseline migration intentionally avoids destructive automatic downgrades.

## Demo Reset and Project Transfer

- `POST /project/demo/reset` returns the deterministic evaluator scenario to a known state.
- `GET /project/export?project_id={id}` exports an integrity-protected version 3 single-project snapshot, including visual artifact revisions, job evidence, tenancy memberships, installed ontology package dependencies, operational evidence, and collaboration events. Principals with access to multiple projects must choose the scope explicitly.
- `POST /project/import/validate` verifies checksum, compatibility, counts, and credential-rebind requirements without mutation.
- `POST /project/import` supports dry-run validation and transactional merge restore, rejects foreign-project rows and broken dependency references, and limits unscoped legacy restores to system-wide administrators with explicit confirmation.

Database backup remains the authoritative disaster-recovery mechanism because it also preserves all audit, security, and runtime tables.

Transactional outbox publication is local by default. To mirror published operational events into Kafka or Redpanda, configure the production `EVENT_KAFKA_*` settings and add `event.kafka.dispatch` to a dedicated worker capability list. Monitor transport receipts and dead letters through `/api/v1/outbox/summary` and `/api/v1/outbox/transport-receipts`; rehearse broker interruption and recovery using `docs/TRANSACTIONAL_EVENT_OUTBOX.md` before enabling downstream consumers.

Connector syncs and stream replays should be submitted through the durable `/ingestion/*` APIs in production. Configure project budgets before enabling schedules, monitor `/ingestion/summary`, and drain pending `/ingestion/dead-letters` during incident recovery. See `docs/DURABLE_INGESTION_RUNTIME.md` for the worker and recovery contract.

REST and JDBC source credentials are encrypted separately from source metadata and never appear in portable project exports. Database backups preserve the encrypted values, but a portable project import requires an administrator to bind fresh runtime credentials before live execution.

Third-party plugin code is never imported into the API process. Configure the Ed25519 trust registry and the production OCI settings in `.env.production`; invocation fails closed without a digest-pinned sandbox image. Network-enabled manifests must sign exact hosts and ports. Configure a digest-pinned egress proxy image and a separate random HMAC secret; the executor provisions an internal-only sandbox network and the proxy enforces each short-lived grant. See `docs/SIGNED_PLUGIN_RUNTIME.md`.

Build and verify the dedicated sandbox before enabling extensions:

```powershell
./scripts/rehearse-plugin-oci.ps1
./scripts/rehearse-plugin-egress.ps1
```

The rehearsal executes the SDK example and confirms that filesystem, network, subprocess, and incompatible-SDK attempts fail under the real non-root, read-only OCI boundary. Its egress stage also verifies signed custom-CA HTTPS, rejection without the signed CA, destination denial, and direct-bypass denial. The complete `rehearse-production-acceptance.ps1` gate additionally mints an execute-only service token through a real OIDC administrator session, runs a signed plugin through the dedicated executor, force-stops that executor during work, and verifies lease-expiry recovery without duplicate terminal success. The main API never receives an OCI socket.

Register every production worker, set project queue concurrency, and drain workers before replacement. Monitor `/ui-state/worker-fleet` together with runtime SLOs; restored worker registrations remain offline until an operator resumes them. See `docs/WORKER_FLEET_CONTROL.md`.

After the API is healthy, create a same-organization worker service account in **Control Panel -> Auth**, issue its one-time project execution token, set `WORKER_TOKEN`, and start the optional `workers` Compose profile. Worker tokens are stored as hashes and must use distinct stable `WORKER_NAME` values per replica. See `docs/WORKER_DAEMON.md`.

Before a release, the container-specific worker gate can be repeated without
the longer plugin, identity-scale, and backup stages:

```powershell
./scripts/rehearse-production-acceptance.ps1 -OnlyPipelineWorkers
```

It still uses the production image, real Keycloak OIDC, PostgreSQL, an
execute-only worker identity, digest-pinned MinIO/Toxiproxy, distinct tmpfs
caches, abrupt container loss, lease expiry, replacement execution, and fenced
single-snapshot publication. Passing this focused mode does not replace the
complete production acceptance or seven-day pilot.

For the stronger independent-runtime boundary, run:

```powershell
./scripts/rehearse-production-acceptance.ps1 -OnlyPipelineMultiDaemon
```

This profile loads the production image into two separate Docker daemons,
kills the first worker, and requires the replacement daemon to rebuild its
private cache and publish through the same PostgreSQL lease fence. The result
proves daemon-level isolation on one physical host; it does not replace a
provider-network or true host-loss rehearsal.

Configure runtime-wide execution, compute, token, record, and cost budgets before opening a project to users. The Control Panel Runtime tab and `/runtime/observability/summary` expose project SLOs and correlated durable-job evidence. See `docs/RUNTIME_OBSERVABILITY.md`.

## Troubleshooting

- `401`: begin at `/auth/login`; verify issuer reachability and callback URL.
- `403`: inspect the OIDC role, `organization_id`, `project_ids`, and persisted project membership shown in the response. Organization-scoped administrators cannot create organizations or projects outside their asserted tenant.
- `409`: reload the artifact because another revision was saved.
- `423`: another user holds the short editing lease; wait for expiry or coordinate ownership.
- `503` readiness: inspect Postgres connectivity and migration logs before restarting repeatedly.
- Login loop: verify HTTPS forwarding, `PUBLIC_BASE_URL`, provider redirect URIs, and server clock synchronization.

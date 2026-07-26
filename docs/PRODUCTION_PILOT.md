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

Production startup fails when `AUTH_MODE` is not `oidc` or required OIDC settings are missing. The local administrator bypass is therefore unavailable in the production profile.

## Deploy

```powershell
docker compose --env-file .env.production -f docker-compose.yml -f docker-compose.production.yml up --build -d
docker compose --env-file .env.production -f docker-compose.yml -f docker-compose.production.yml ps
```

Verify `https://${PUBLIC_HOST}/health/live`, `/health/ready`, and then `/workspace/command-center`. API containers apply the Alembic schema baseline before accepting traffic. PostgreSQL deployments serialize concurrent migration startup with an advisory transaction lock, allowing multiple replicas to start against a fresh database without racing schema DDL.

For an isolated OIDC demonstration, start the optional Keycloak service with `--profile demo-idp`, update `OIDC_ISSUER` to the reachable realm URL, and create at least one user with a supported realm role. Do not use the included development realm configuration as an internet-facing identity service.

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

It generates temporary secrets; starts digest-pinned Keycloak, Postgres, and two API replicas; registers the declared `organization_id` and `project_ids` user-profile attributes; and runs the production browser workflow. The workflow verifies PKCE-backed OIDC sessions, administrator/viewer RBAC, organization boundary enforcement, and a real own-data path from project-owned CSV import through mapping validation, dataset promotion, ontology draft application, pipeline delivery, and hydrated objects. It rejects imports, pipeline creation, and Workshop creation in an unclaimed project; permits viewer reads of owned pipelines and Workshop modules; and rejects viewer mutation, execution, and publication. It also exercises 50 concurrent authenticated reads, the Asset Reliability approval/action/report path, and visual workspaces. A collaborative artifact command submitted through the peer API must reach the primary API's SSE stream and artifact read, while replay through the primary must remain idempotent. A concurrent job submission through both replicas must similarly reconcile to one durable job, while a changed request behind the same key must fail. The workflow then abandons an active worker lease, races stale-job reaping through both replicas, requires exactly one recovery transition, fences the stale token, reclaims the job on a replacement worker, and verifies one successful completion with recovery telemetry. Starting both replicas against the same fresh database exercises serialized Alembic startup. The gate then restarts the primary API, reruns browser acceptance against preserved Postgres state, executes the isolated fresh-volume staged Postgres backup/restore rehearsal with deterministic cleanup. Use `-KeepStack` only for troubleshooting and `-SkipRecovery` only when the separate recovery gate has already passed for the same build.

The same gate is available as the manually dispatched `Production acceptance` GitHub Actions workflow. Enable a protected pull-request trigger when the repository has Linux Actions capacity; until then, the locally executed gate above is the authoritative release evidence and avoids treating account billing failures as product failures.

The bundled Keycloak realm and user-profile files are demonstration fixtures. They are not an internet-facing identity service. A production identity provider must emit equivalent tenant claims and restrict their administration to trusted identity operators.

## Back Up and Restore

Create a database backup from the project root:

```powershell
./scripts/backup.ps1
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
  -KeepPreviousDatabase
```

Pass the same `ComposeFile`, `ProjectName`, `DatabaseUser`, and `DatabaseName` options to `restore.ps1` for non-default stacks. Backups include adjacent SHA-256 and JSON manifests. See `docs/RECOVERY.md` for staged swap, rollback, credential rebinding, and acceptance procedures.

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
- `GET /project/export` exports an integrity-protected version 2 portable snapshot, including visual artifact revisions, job evidence, tenancy memberships, ontology packages/installations, and collaboration events.
- `POST /project/import/validate` verifies checksum, compatibility, counts, and credential-rebind requirements without mutation.
- `POST /project/import` supports dry-run validation and transactional merge restore.

Database backup remains the authoritative disaster-recovery mechanism because it also preserves all audit, security, and runtime tables.

Connector syncs and stream replays should be submitted through the durable `/ingestion/*` APIs in production. Configure project budgets before enabling schedules, monitor `/ingestion/summary`, and drain pending `/ingestion/dead-letters` during incident recovery. See `docs/DURABLE_INGESTION_RUNTIME.md` for the worker and recovery contract.

REST and JDBC source credentials are encrypted separately from source metadata and never appear in portable project exports. Database backups preserve the encrypted values, but a portable project import requires an administrator to bind fresh runtime credentials before live execution.

Register every production worker, set project queue concurrency, and drain workers before replacement. Monitor `/ui-state/worker-fleet` together with runtime SLOs; restored worker registrations remain offline until an operator resumes them. See `docs/WORKER_FLEET_CONTROL.md`.

After the API is healthy, create a same-organization worker service account in **Control Panel -> Auth**, issue its one-time project execution token, set `WORKER_TOKEN`, and start the optional `workers` Compose profile. Worker tokens are stored as hashes and must use distinct stable `WORKER_NAME` values per replica. See `docs/WORKER_DAEMON.md`.

Configure runtime-wide execution, compute, token, record, and cost budgets before opening a project to users. The Control Panel Runtime tab and `/runtime/observability/summary` expose project SLOs and correlated durable-job evidence. See `docs/RUNTIME_OBSERVABILITY.md`.

## Troubleshooting

- `401`: begin at `/auth/login`; verify issuer reachability and callback URL.
- `403`: inspect the OIDC role, `organization_id`, `project_ids`, and persisted project membership shown in the response. Organization-scoped administrators cannot create organizations or projects outside their asserted tenant.
- `409`: reload the artifact because another revision was saved.
- `423`: another user holds the short editing lease; wait for expiry or coordinate ownership.
- `503` readiness: inspect Postgres connectivity and migration logs before restarting repeatedly.
- Login loop: verify HTTPS forwarding, `PUBLIC_BASE_URL`, provider redirect URIs, and server clock synchronization.

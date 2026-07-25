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

Production startup fails when `AUTH_MODE` is not `oidc` or required OIDC settings are missing. The local administrator bypass is therefore unavailable in the production profile.

## Deploy

```powershell
docker compose --env-file .env.production -f docker-compose.yml -f docker-compose.production.yml up --build -d
docker compose --env-file .env.production -f docker-compose.yml -f docker-compose.production.yml ps
```

Verify `https://${PUBLIC_HOST}/health/live`, `/health/ready`, and then `/workspace/command-center`. The first API container start applies the Alembic schema baseline before accepting traffic.

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

Restore requires downtime and explicit confirmation:

```powershell
docker compose stop oms-api
./scripts/restore.ps1 -BackupPath ./backups/ontology-YYYYMMDD-HHMMSS.dump -ConfirmRestore
docker compose start oms-api
```

Pass the same `ComposeFile`, `ProjectName`, `DatabaseUser`, and `DatabaseName` options to `restore.ps1` for non-default stacks. Stop the API before restore so connection pools cannot write during replacement.

After restoration, verify `/health/ready`, sign in, inspect `/workspace/validation`, and compare artifact, object, audit, incident, and report counts. Editing leases and login sessions are intentionally ephemeral and are not part of project JSON exports.

## Upgrade and Roll Back

1. Run `./scripts/backup.ps1`.
2. Pull the reviewed release and run the production Compose command with `up --build -d`.
3. Check migration output, readiness, the Validation workspace, and the Asset Reliability workflow.
4. For rollback, restore the pre-upgrade database backup and deploy the previous application image. The baseline migration intentionally avoids destructive automatic downgrades.

## Demo Reset and Project Transfer

- `POST /project/demo/reset` returns the deterministic evaluator scenario to a known state.
- `GET /project/export` exports portable project resources, including visual artifact revisions, job evidence, tenancy memberships, ontology packages/installations, and collaboration events.
- `POST /project/import` restores a project JSON snapshot in merge mode.

Database backup remains the authoritative disaster-recovery mechanism because it also preserves all audit, security, and runtime tables.

Connector syncs and stream replays should be submitted through the durable `/ingestion/*` APIs in production. Configure project budgets before enabling schedules, monitor `/ingestion/summary`, and drain pending `/ingestion/dead-letters` during incident recovery. See `docs/DURABLE_INGESTION_RUNTIME.md` for the worker and recovery contract.

Configure runtime-wide execution, compute, token, record, and cost budgets before opening a project to users. The Control Panel Runtime tab and `/runtime/observability/summary` expose project SLOs and correlated durable-job evidence. See `docs/RUNTIME_OBSERVABILITY.md`.

## Troubleshooting

- `401`: begin at `/auth/login`; verify issuer reachability and callback URL.
- `403`: inspect the OIDC role, `organization_id`, `project_ids`, and persisted project membership shown in the response.
- `409`: reload the artifact because another revision was saved.
- `423`: another user holds the short editing lease; wait for expiry or coordinate ownership.
- `503` readiness: inspect Postgres connectivity and migration logs before restarting repeatedly.
- Login loop: verify HTTPS forwarding, `PUBLIC_BASE_URL`, provider redirect URIs, and server clock synchronization.

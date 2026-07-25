# Backup, Restore, and Failure Recovery

The platform has two recovery mechanisms with different purposes.

## Portable snapshot

Use **Control Panel -> Recovery** or `GET /project/export` to transfer governed platform resources between compatible installations. Version 2 snapshots include:

- a deterministic SHA-256 checksum and resource-count manifest;
- ontology, data, artifacts, revisions, collaboration events, jobs, ingestion evidence, monitors, incidents, investigations, packages, workers, and queue policies;
- explicit credential-rebind records.

Portable snapshots never contain connector credentials, service tokens, login sessions, or webhook listener secrets. Source configuration keys that can contain credentials are redacted. Only installation administrators can export, validate, or import a snapshot because several legacy resources do not yet carry project ownership.

Validate before import:

```http
POST /project/import/validate
{"snapshot": { ... }, "mode": "merge"}
```

Run a non-mutating rehearsal:

```http
POST /project/import
{"snapshot": { ... }, "mode": "merge", "dry_run": true}
```

An import validates the complete manifest before mutation and commits as one database transaction. A constraint failure rolls back every imported row. Existing separately stored credentials are preserved during a merge; resources created in a fresh installation remain unbound until an administrator supplies new credentials.

Version 1 snapshots do not have integrity manifests and are rejected by default. Use `allow_legacy: true` only for a controlled one-time migration after independently verifying the file, then immediately export a version 2 snapshot.

## Authoritative database backup

Database backup is the disaster-recovery source of truth because it preserves encrypted credentials, audit history, identity configuration, and every runtime table.

```powershell
./scripts/backup.ps1
```

The command creates a Postgres custom archive, validates its table of contents, and writes adjacent `.sha256` and `.json` manifest files. Store all three files in protected backup storage and test restoration regularly.

## Staged restore

```powershell
./scripts/restore.ps1 `
  -BackupPath ./backups/ontology-YYYYMMDD-HHMMSS.dump `
  -ConfirmRestore `
  -KeepPreviousDatabase
```

The restore command:

1. verifies the host checksum when present;
2. validates the archive before touching the live database;
3. restores into a new staging database;
4. verifies the restored Alembic migration table;
5. stops configured writer services;
6. preserves the live database under a timestamped previous name;
7. promotes the staged database;
8. restarts services;
9. automatically renames the previous database back if promotion fails.

Use `-KeepPreviousDatabase` during production rehearsals. Drop the previous database only after acceptance checks succeed. The default writer services are `oms-api` and `oms-worker`; only services present in the selected Compose configuration are stopped.

## Acceptance checks

After recovery:

1. Verify `/health/ready` and `/system/schema-health` return passing state.
2. Verify `/system/migrations` reports the expected runtime version.
3. Sign in through OIDC and confirm project permissions.
4. Inspect **Control Panel -> Runtime** for offline workers, expired leases, failed jobs, budgets, and SLO breaches.
5. Resume workers explicitly and replay dead letters only after dependencies are healthy.
6. Compare object, artifact revision, audit, incident, report, and job counts with the backup manifest or pre-recovery evidence.
7. Complete one Asset Reliability triage and approval workflow.

Never treat a successful `pg_restore` exit code alone as proof of recovery. The acceptance checks and a retained previous database provide the rollback boundary.

Run the isolated fresh-volume rehearsal before a production pilot or upgrade:

```powershell
./scripts/rehearse-recovery.ps1
```

It starts only the rehearsal Postgres service, waits for stable readiness, creates a probe and migration record, backs up the database, corrupts the live probe, runs the staged restore, verifies the original value, and removes the isolated Compose project and volume. Use `-KeepArtifacts` to retain the generated archive and manifests for inspection.

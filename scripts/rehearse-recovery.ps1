param(
    [string]$ProjectName = "ontology_recovery_rehearsal",
    [string]$ComposeFile = "docker-compose.rehearsal.yml",
    [switch]$KeepArtifacts
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$composePath = (Resolve-Path -LiteralPath (Join-Path $root $ComposeFile)).Path
$outputDirectory = ".recovery-rehearsal-$ProjectName"
$outputPath = Join-Path $root $outputDirectory

if (-not $env:REHEARSAL_POSTGRES_PASSWORD) { $env:REHEARSAL_POSTGRES_PASSWORD = "recovery-rehearsal-only" }
if (-not $env:REHEARSAL_KEYCLOAK_ADMIN_PASSWORD) { $env:REHEARSAL_KEYCLOAK_ADMIN_PASSWORD = "recovery-rehearsal-only" }
if (-not $env:REHEARSAL_CONNECTOR_SECRET_KEY) { $env:REHEARSAL_CONNECTOR_SECRET_KEY = "recovery-rehearsal-connector-key" }

function Invoke-RehearsalCompose {
    param([string[]]$Arguments, [string]$FailureMessage)
    & docker compose -f $composePath -p $ProjectName @Arguments
    if ($LASTEXITCODE -ne 0) { throw $FailureMessage }
}

try {
    Invoke-RehearsalCompose @("up", "-d", "postgres") "Could not start isolated rehearsal Postgres."
    $ready = $false
    $consecutiveReady = 0
    for ($attempt = 0; $attempt -lt 60; $attempt++) {
        & docker compose -f $composePath -p $ProjectName exec -T postgres pg_isready -U ontology -d ontology *> $null
        if ($LASTEXITCODE -eq 0) { $consecutiveReady++ } else { $consecutiveReady = 0 }
        if ($consecutiveReady -ge 5) { $ready = $true; break }
        Start-Sleep -Seconds 1
    }
    if (-not $ready) { throw "Rehearsal Postgres did not become ready." }

    $seedSql = "CREATE TABLE alembic_version(version_num varchar(32) primary key); INSERT INTO alembic_version VALUES ('0038_explicit_schema_baseline'); CREATE TABLE recovery_probe(id integer primary key, value text); INSERT INTO recovery_probe VALUES (1, 'before-backup');"
    Invoke-RehearsalCompose @("exec", "-T", "postgres", "psql", "-v", "ON_ERROR_STOP=1", "-U", "ontology", "-d", "ontology", "-c", $seedSql) "Could not seed recovery probe."

    $backupPath = & (Join-Path $PSScriptRoot "backup.ps1") `
        -OutputDirectory $outputDirectory `
        -ComposeFile $composePath `
        -ProjectName $ProjectName `
        -DatabaseUser ontology `
        -DatabaseName ontology | Select-Object -Last 1
    if (-not $backupPath) { throw "Backup script did not return a backup path." }

    Invoke-RehearsalCompose @("exec", "-T", "postgres", "psql", "-v", "ON_ERROR_STOP=1", "-U", "ontology", "-d", "ontology", "-c", "UPDATE recovery_probe SET value='corrupted-live-state' WHERE id=1;") "Could not mutate the live recovery probe."

    & (Join-Path $PSScriptRoot "restore.ps1") `
        -BackupPath $backupPath `
        -ConfirmRestore `
        -ComposeFile $composePath `
        -ProjectName $ProjectName `
        -DatabaseUser ontology `
        -DatabaseName ontology `
        -ApplicationServices none
    if ($LASTEXITCODE -ne 0) { throw "Staged restore failed." }

    $value = & docker compose -f $composePath -p $ProjectName exec -T postgres psql -At -U ontology -d ontology -c "SELECT value FROM recovery_probe WHERE id=1;"
    if ($LASTEXITCODE -ne 0 -or $value.Trim() -ne "before-backup") {
        throw "Recovery verification failed. Expected 'before-backup', received '$value'."
    }
    Write-Output "RECOVERY_REHEARSAL_PASSED: $($value.Trim())"
}
finally {
    $previousErrorAction = $ErrorActionPreference
    $ErrorActionPreference = "SilentlyContinue"
    & docker compose -f $composePath -p $ProjectName down -v --remove-orphans *> $null
    $ErrorActionPreference = $previousErrorAction
    if (-not $KeepArtifacts) {
        Remove-Item -LiteralPath $outputPath -Recurse -Force -ErrorAction SilentlyContinue
    }
}

param(
    [Parameter(Mandatory = $true)]
    [string]$BackupPath,
    [switch]$ConfirmRestore,
    [switch]$KeepPreviousDatabase,
    [string]$ComposeFile,
    [string]$ProjectName,
    [string]$DatabaseService = "postgres",
    [string]$DatabaseUser,
    [string]$DatabaseName,
    [string[]]$ApplicationServices = @("oms-api", "oms-worker")
)

$ErrorActionPreference = "Stop"
if (-not $ConfirmRestore) {
    throw "Restore replaces database contents. Re-run with -ConfirmRestore after taking a current backup."
}
$resolvedBackup = (Resolve-Path -LiteralPath $BackupPath).Path
if (-not (Test-Path -LiteralPath $resolvedBackup -PathType Leaf)) {
    throw "Backup file does not exist: $resolvedBackup"
}

$databaseUser = if ($DatabaseUser) { $DatabaseUser } elseif ($env:POSTGRES_USER) { $env:POSTGRES_USER } else { "admin" }
$databaseName = if ($DatabaseName) { $DatabaseName } elseif ($env:POSTGRES_DB) { $env:POSTGRES_DB } else { "ontology_ops" }
foreach ($identifier in @($databaseUser, $databaseName)) {
    if ($identifier -notmatch '^[A-Za-z_][A-Za-z0-9_]{0,62}$') {
        throw "Unsafe Postgres identifier: $identifier"
    }
}

$checksumPath = "$resolvedBackup.sha256"
if (Test-Path -LiteralPath $checksumPath) {
    $expectedChecksum = ((Get-Content -LiteralPath $checksumPath -Raw).Trim() -split '\s+')[0].ToLowerInvariant()
    $actualChecksum = (Get-FileHash -LiteralPath $resolvedBackup -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($actualChecksum -ne $expectedChecksum) {
        throw "Backup checksum mismatch. Restore was not started."
    }
}

$composeArguments = @("compose")
if ($ProjectName) { $composeArguments += @("-p", $ProjectName) }
if ($ComposeFile) {
    $resolvedCompose = (Resolve-Path -LiteralPath $ComposeFile).Path
    $composeArguments += @("-f", $resolvedCompose)
}

$stamp = Get-Date -Format "yyyyMMddHHmmss"
$containerFile = "/tmp/ontology-restore-$stamp.dump"
$stagingDatabase = (($databaseName.Substring(0, [Math]::Min($databaseName.Length, 38))) + "_restore_" + $stamp)
$previousDatabase = (($databaseName.Substring(0, [Math]::Min($databaseName.Length, 38))) + "_previous_" + $stamp)
$writersStopped = $false
$liveRenamed = $false
$swapCompleted = $false

function Invoke-Compose {
    param([string[]]$Arguments, [string]$FailureMessage)
    & docker @composeArguments @Arguments
    if ($LASTEXITCODE -ne 0) { throw $FailureMessage }
}

function Invoke-PostgresSql {
    param([string]$Sql, [string]$FailureMessage)
    Invoke-Compose @("exec", "-T", $DatabaseService, "psql", "-v", "ON_ERROR_STOP=1", "-U", $databaseUser, "-d", "postgres", "-c", $Sql) $FailureMessage
}

try {
    Invoke-Compose @("cp", $resolvedBackup, "${DatabaseService}:$containerFile") "Could not copy backup into the Postgres container."
    Invoke-Compose @("exec", "-T", $DatabaseService, "pg_restore", "--list", $containerFile) "Backup archive is corrupt or unreadable."

    Invoke-PostgresSql "DROP DATABASE IF EXISTS `"$stagingDatabase`" WITH (FORCE);" "Could not remove a stale staging database."
    Invoke-PostgresSql "CREATE DATABASE `"$stagingDatabase`" WITH OWNER `"$databaseUser`" TEMPLATE template0;" "Could not create the staging database."
    Invoke-Compose @("exec", "-T", $DatabaseService, "pg_restore", "-U", $databaseUser, "-d", $stagingDatabase, "--exit-on-error", "--no-owner", "--no-privileges", $containerFile) "Staging restore failed; the live database was not changed."
    Invoke-Compose @("exec", "-T", $DatabaseService, "psql", "-v", "ON_ERROR_STOP=1", "-U", $databaseUser, "-d", $stagingDatabase, "-c", "SELECT version_num FROM alembic_version LIMIT 1;") "Restored database failed migration metadata validation."

    $availableServices = @(& docker @composeArguments config --services)
    if ($LASTEXITCODE -ne 0) { throw "Could not inspect Compose services." }
    $servicesToStop = @($ApplicationServices | Where-Object { $availableServices -contains $_ })
    if ($servicesToStop.Count -gt 0) {
        Invoke-Compose (@("stop") + $servicesToStop) "Could not stop application writers before database swap."
        $writersStopped = $true
    }

    Invoke-PostgresSql "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname IN ('$databaseName', '$previousDatabase') AND pid <> pg_backend_pid();" "Could not terminate live database sessions."
    Invoke-PostgresSql "DROP DATABASE IF EXISTS `"$previousDatabase`" WITH (FORCE);" "Could not clear the previous-database slot."
    Invoke-PostgresSql "ALTER DATABASE `"$databaseName`" RENAME TO `"$previousDatabase`";" "Could not preserve the live database before swap."
    $liveRenamed = $true
    Invoke-PostgresSql "ALTER DATABASE `"$stagingDatabase`" RENAME TO `"$databaseName`";" "Could not promote the staged database."
    $swapCompleted = $true

    if ($writersStopped) {
        Invoke-Compose (@("start") + $servicesToStop) "Database was restored, but application services could not be restarted."
        $writersStopped = $false
    }
    if (-not $KeepPreviousDatabase) {
        Invoke-PostgresSql "DROP DATABASE IF EXISTS `"$previousDatabase`" WITH (FORCE);" "Restore succeeded, but the previous database could not be removed."
    }
    Write-Output "Restore completed from $resolvedBackup. Previous database: $previousDatabase"
}
catch {
    if ($liveRenamed -and -not $swapCompleted) {
        try {
            Invoke-PostgresSql "ALTER DATABASE `"$previousDatabase`" RENAME TO `"$databaseName`";" "Automatic database rollback failed."
        }
        catch {
            Write-Error "CRITICAL: database promotion and automatic rollback both failed. Previous database is $previousDatabase."
        }
    }
    if ($writersStopped) {
        try { & docker @composeArguments start @servicesToStop | Out-Null } catch { }
    }
    throw
}
finally {
    & docker @composeArguments exec -T $DatabaseService rm -f $containerFile 2>$null | Out-Null
    if (-not $swapCompleted) {
        & docker @composeArguments exec -T $DatabaseService psql -U $databaseUser -d postgres -c "DROP DATABASE IF EXISTS `"$stagingDatabase`" WITH (FORCE);" 2>$null | Out-Null
    }
}

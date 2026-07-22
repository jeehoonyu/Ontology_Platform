param(
    [Parameter(Mandatory = $true)]
    [string]$BackupPath,
    [switch]$ConfirmRestore,
    [string]$ComposeFile,
    [string]$ProjectName,
    [string]$DatabaseService = "postgres",
    [string]$DatabaseUser,
    [string]$DatabaseName
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
$composeArguments = @("compose")
if ($ProjectName) { $composeArguments += @("-p", $ProjectName) }
if ($ComposeFile) {
    $resolvedCompose = (Resolve-Path -LiteralPath $ComposeFile).Path
    $composeArguments += @("-f", $resolvedCompose)
}
$containerFile = "/tmp/ontology-restore.dump"

& docker @composeArguments cp $resolvedBackup "${DatabaseService}:$containerFile"
if ($LASTEXITCODE -ne 0) { throw "Could not copy backup into the Postgres container." }
& docker @composeArguments exec -T $DatabaseService pg_restore -U $databaseUser -d $databaseName --clean --if-exists --no-owner $containerFile
if ($LASTEXITCODE -ne 0) { throw "pg_restore failed. Keep the backup and inspect the Postgres logs before retrying." }
& docker @composeArguments exec -T $DatabaseService rm -f $containerFile

Write-Output "Restore completed from $resolvedBackup"

param(
    [string]$OutputDirectory = "backups",
    [string]$ComposeFile,
    [string]$ProjectName,
    [string]$DatabaseService = "postgres",
    [string]$DatabaseUser,
    [string]$DatabaseName
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$targetDirectory = [System.IO.Path]::GetFullPath((Join-Path $projectRoot $OutputDirectory))
if (-not $targetDirectory.StartsWith([System.IO.Path]::GetFullPath($projectRoot), [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "Backup output must remain inside the project directory."
}
New-Item -ItemType Directory -Path $targetDirectory -Force | Out-Null

$databaseUser = if ($DatabaseUser) { $DatabaseUser } elseif ($env:POSTGRES_USER) { $env:POSTGRES_USER } else { "admin" }
$databaseName = if ($DatabaseName) { $DatabaseName } elseif ($env:POSTGRES_DB) { $env:POSTGRES_DB } else { "ontology_ops" }
$composeArguments = @("compose")
if ($ProjectName) { $composeArguments += @("-p", $ProjectName) }
if ($ComposeFile) {
    $resolvedCompose = (Resolve-Path -LiteralPath $ComposeFile).Path
    $composeArguments += @("-f", $resolvedCompose)
}
$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$containerFile = "/tmp/ontology-$stamp.dump"
$targetFile = Join-Path $targetDirectory "ontology-$stamp.dump"

& docker @composeArguments exec -T $DatabaseService pg_dump -U $databaseUser -d $databaseName -Fc -f $containerFile
if ($LASTEXITCODE -ne 0) { throw "pg_dump failed." }
& docker @composeArguments cp "${DatabaseService}:$containerFile" $targetFile
if ($LASTEXITCODE -ne 0) { throw "Could not copy backup from the Postgres container." }
& docker @composeArguments exec -T $DatabaseService rm -f $containerFile

Write-Output $targetFile

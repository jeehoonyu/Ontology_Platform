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
& docker @composeArguments exec -T $DatabaseService pg_restore --list $containerFile | Out-Null
if ($LASTEXITCODE -ne 0) { throw "Backup archive validation failed." }
& docker @composeArguments cp "${DatabaseService}:$containerFile" $targetFile
if ($LASTEXITCODE -ne 0) { throw "Could not copy backup from the Postgres container." }
& docker @composeArguments exec -T $DatabaseService rm -f $containerFile

$checksum = (Get-FileHash -LiteralPath $targetFile -Algorithm SHA256).Hash.ToLowerInvariant()
$checksumFile = "$targetFile.sha256"
Set-Content -LiteralPath $checksumFile -Value "$checksum  $([System.IO.Path]::GetFileName($targetFile))" -Encoding ascii
$manifest = [ordered]@{
    format = "postgres-custom"
    created_at = (Get-Date).ToUniversalTime().ToString("o")
    database = $databaseName
    database_service = $DatabaseService
    sha256 = $checksum
    size_bytes = (Get-Item -LiteralPath $targetFile).Length
    backup_file = [System.IO.Path]::GetFileName($targetFile)
}
$manifest | ConvertTo-Json | Set-Content -LiteralPath "$targetFile.json" -Encoding utf8

Write-Output $targetFile

param(
    [string]$ProjectName = "ontology_rehearsal",
    [switch]$DeleteData
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$composeFile = Join-Path $projectRoot "docker-compose.rehearsal.yml"
# Compose resolves required variables even for `down`; placeholders are safe
# because shutdown never creates or reconfigures a service.
if (-not $env:REHEARSAL_POSTGRES_PASSWORD) { $env:REHEARSAL_POSTGRES_PASSWORD = "shutdown-only" }
if (-not $env:REHEARSAL_KEYCLOAK_ADMIN_PASSWORD) { $env:REHEARSAL_KEYCLOAK_ADMIN_PASSWORD = "shutdown-only" }
if (-not $env:REHEARSAL_CONNECTOR_SECRET_KEY) { $env:REHEARSAL_CONNECTOR_SECRET_KEY = "shutdown-only" }
$arguments = @("compose", "-p", $ProjectName, "-f", $composeFile, "down", "--remove-orphans")
if ($DeleteData) { $arguments += "--volumes" }
& docker @arguments
if ($LASTEXITCODE -ne 0) { throw "Could not stop the production rehearsal stack." }

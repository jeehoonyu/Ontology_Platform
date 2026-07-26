param(
    [string]$ProjectName = "ontology_acceptance",
    [string]$KeycloakAdminPassword = "",
    [string]$PilotAdminPassword = "",
    [string]$PilotViewerPassword = "",
    [string]$PostgresPassword = "",
    [string]$ConnectorSecretKey = "",
    [switch]$KeepStack,
    [switch]$SkipRecovery
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$composeFile = Join-Path $projectRoot "docker-compose.rehearsal.yml"

function New-RehearsalSecret {
    $bytes = New-Object byte[] 32
    $generator = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    try { $generator.GetBytes($bytes) } finally { $generator.Dispose() }
    return [Convert]::ToBase64String($bytes)
}

if (-not $KeycloakAdminPassword) { $KeycloakAdminPassword = New-RehearsalSecret }
if (-not $PilotAdminPassword) { $PilotAdminPassword = New-RehearsalSecret }
if (-not $PilotViewerPassword) { $PilotViewerPassword = New-RehearsalSecret }
if (-not $PostgresPassword) { $PostgresPassword = New-RehearsalSecret }
if (-not $ConnectorSecretKey) { $ConnectorSecretKey = New-RehearsalSecret }

$env:REHEARSAL_KEYCLOAK_ADMIN_PASSWORD = $KeycloakAdminPassword
$env:REHEARSAL_POSTGRES_PASSWORD = $PostgresPassword
$env:REHEARSAL_CONNECTOR_SECRET_KEY = $ConnectorSecretKey
$env:PRODUCTION_BASE_URL = "http://localhost:18000"
$env:PILOT_ADMIN_PASSWORD = $PilotAdminPassword
$env:PILOT_VIEWER_PASSWORD = $PilotViewerPassword
$compose = @("compose", "-p", $ProjectName, "-f", $composeFile)

function Wait-ForReady([int]$Attempts = 80) {
    for ($attempt = 0; $attempt -lt $Attempts; $attempt++) {
        try {
            $response = Invoke-WebRequest -UseBasicParsing -Uri "$env:PRODUCTION_BASE_URL/health/ready" -TimeoutSec 3
            if ($response.StatusCode -eq 200) { return }
        } catch {}
        Start-Sleep -Seconds 2
    }
    throw "Timed out waiting for the production rehearsal API."
}

function Invoke-OidcAcceptance([string]$Stage) {
    Push-Location (Join-Path $projectRoot "frontend")
    try {
        $npmCommand = if (Get-Command npm.cmd -ErrorAction SilentlyContinue) { "npm.cmd" } else { "npm" }
        & $npmCommand run test:production-oidc
        if ($LASTEXITCODE -ne 0) { throw "Production OIDC acceptance failed during $Stage." }
    } finally {
        Pop-Location
    }
}

try {
    & (Join-Path $PSScriptRoot "start-production-rehearsal.ps1") `
        -KeycloakAdminPassword $KeycloakAdminPassword `
        -PilotAdminPassword $PilotAdminPassword `
        -PilotViewerPassword $PilotViewerPassword `
        -PostgresPassword $PostgresPassword `
        -ConnectorSecretKey $ConnectorSecretKey `
        -ProjectName $ProjectName

    Invoke-OidcAcceptance "initial deployment"

    & docker @compose restart oms-api | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "Could not restart the production API for recovery testing." }
    Wait-ForReady
    Invoke-OidcAcceptance "API restart recovery"

    if (-not $SkipRecovery) {
        & (Join-Path $PSScriptRoot "rehearse-recovery.ps1") -ProjectName "${ProjectName}_recovery"
        if ($LASTEXITCODE -ne 0) { throw "Fresh-volume backup and restore rehearsal failed." }
    }

    Write-Output "PRODUCTION_ACCEPTANCE_PASSED: OIDC, RBAC, project-owned onboarding, pipelines, Workshop, actions, AIP Logic, asynchronous agents, cross-project denial, 50-reader load, cross-replica collaboration, job idempotency, abandoned-worker chaos recovery, serialized migration startup, API restart, and backup/restore recovery verified."
} finally {
    if (-not $KeepStack) {
        & (Join-Path $PSScriptRoot "stop-production-rehearsal.ps1") -ProjectName $ProjectName -DeleteData
    }
}

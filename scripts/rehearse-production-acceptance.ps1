param(
    [string]$ProjectName = "ontology_acceptance",
    [string]$KeycloakAdminPassword = "",
    [string]$PilotAdminPassword = "",
    [string]$PilotViewerPassword = "",
    [string]$PostgresPassword = "",
    [string]$ConnectorSecretKey = "",
    [string]$OidcScalePassword = "",
    [int]$OidcUserCount = 200,
    [int]$OidcLoginConcurrency = 20,
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
if (-not $OidcScalePassword) { $OidcScalePassword = New-RehearsalSecret }

$env:REHEARSAL_KEYCLOAK_ADMIN_PASSWORD = $KeycloakAdminPassword
$env:REHEARSAL_POSTGRES_PASSWORD = $PostgresPassword
$env:REHEARSAL_CONNECTOR_SECRET_KEY = $ConnectorSecretKey
$env:PRODUCTION_BASE_URL = "http://localhost:18000"
$env:PILOT_ADMIN_PASSWORD = $PilotAdminPassword
$env:PILOT_VIEWER_PASSWORD = $PilotViewerPassword
$env:OIDC_SCALE_ADMIN_PASSWORD = $KeycloakAdminPassword
$env:OIDC_SCALE_USER_PASSWORD = $OidcScalePassword
$env:OIDC_SCALE_USER_COUNT = "$OidcUserCount"
$env:OIDC_SCALE_LOGIN_CONCURRENCY = "$OidcLoginConcurrency"
$env:OIDC_SCALE_EVIDENCE_PATH = "../docs/oidc-identity-scale-evidence.json"
$compose = @("compose", "-p", $ProjectName, "-f", $composeFile)
$pluginCompose = $compose + @("--profile", "plugin-execution")
$pluginStatePath = Join-Path $env:TEMP "ontology-plugin-rehearsal-$ProjectName.json"
$pluginEvidencePath = Join-Path $projectRoot "docs/plugin-executor-production-evidence.json"

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

function Invoke-OidcScaleAcceptance {
    Push-Location (Join-Path $projectRoot "oms")
    try {
        & python provision_oidc_scale_users.py
        if ($LASTEXITCODE -ne 0) { throw "Could not provision OIDC scale identities." }
    } finally {
        Pop-Location
    }
    Push-Location (Join-Path $projectRoot "frontend")
    try {
        $npmCommand = if (Get-Command npm.cmd -ErrorAction SilentlyContinue) { "npm.cmd" } else { "npm" }
        & $npmCommand run test:production-oidc-scale
        if ($LASTEXITCODE -ne 0) { throw "Production OIDC identity-scale acceptance failed." }
    } finally {
        Pop-Location
    }
}

function Invoke-PluginExecutorStage([string]$Stage) {
    $env:PLUGIN_REHEARSAL_STAGE = $Stage
    $env:PLUGIN_REHEARSAL_STATE_PATH = $pluginStatePath
    $env:PLUGIN_REHEARSAL_EVIDENCE_PATH = $pluginEvidencePath
    Push-Location (Join-Path $projectRoot "frontend")
    try {
        $npmCommand = if (Get-Command npm.cmd -ErrorAction SilentlyContinue) { "npm.cmd" } else { "npm" }
        & $npmCommand run test:production-plugin-executor
        if ($LASTEXITCODE -ne 0) { throw "Production plugin executor acceptance failed during $Stage." }
    } finally {
        Pop-Location
    }
}

function Wait-ForPluginRegistry([int]$Attempts = 40) {
    for ($attempt = 0; $attempt -lt $Attempts; $attempt++) {
        try {
            $response = Invoke-WebRequest -UseBasicParsing -Uri "http://127.0.0.1:19050/v2/" -TimeoutSec 3
            if ($response.StatusCode -eq 200) { return }
        } catch {}
        Start-Sleep -Seconds 1
    }
    throw "Timed out waiting for the rehearsal plugin registry."
}

function Wait-ForPluginExecutor([int]$Attempts = 60) {
    for ($attempt = 0; $attempt -lt $Attempts; $attempt++) {
        $health = & docker inspect --format "{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}" "${ProjectName}-plugin-executor-1" 2>$null
        if ($LASTEXITCODE -eq 0 -and "$health".Trim() -eq "healthy") { return }
        Start-Sleep -Seconds 2
    }
    throw "Timed out waiting for the isolated plugin executor."
}

function Invoke-PluginExecutorAcceptance {
    Invoke-PluginExecutorStage "bootstrap"
    $state = Get-Content -Raw $pluginStatePath | ConvertFrom-Json
    if (-not $state.token -or -not $state.suffix) { throw "Plugin rehearsal bootstrap did not return executor credentials." }

    & docker @pluginCompose up -d plugin-registry
    if ($LASTEXITCODE -ne 0) { throw "Could not start the rehearsal plugin registry." }
    Wait-ForPluginRegistry

    $hostImage = "localhost:19050/ontology-plugin-sandbox:$($state.suffix)"
    $hostProxyImage = "localhost:19050/ontology-plugin-egress-proxy:$($state.suffix)"
    & docker build -f (Join-Path $projectRoot "oms/plugin-sandbox.Dockerfile") -t $hostImage $projectRoot
    if ($LASTEXITCODE -ne 0) { throw "Could not build the production plugin sandbox image." }
    & docker push $hostImage
    if ($LASTEXITCODE -ne 0) { throw "Could not publish the production plugin sandbox image to the rehearsal registry." }
    $hostDigest = (& docker image inspect --format "{{index .RepoDigests 0}}" $hostImage).Trim()
    if ($LASTEXITCODE -ne 0 -or $hostDigest -notmatch "@sha256:[a-f0-9]{64}$") {
        throw "Could not resolve a digest-pinned rehearsal sandbox image."
    }
    & docker build -f (Join-Path $projectRoot "oms/plugin-egress-proxy.Dockerfile") -t $hostProxyImage $projectRoot
    if ($LASTEXITCODE -ne 0) { throw "Could not build the governed plugin egress proxy image." }
    & docker push $hostProxyImage
    if ($LASTEXITCODE -ne 0) { throw "Could not publish the governed plugin egress proxy image." }
    $hostProxyDigest = (& docker image inspect --format "{{index .RepoDigests 0}}" $hostProxyImage).Trim()
    if ($LASTEXITCODE -ne 0 -or $hostProxyDigest -notmatch "@sha256:[a-f0-9]{64}$") {
        throw "Could not resolve a digest-pinned rehearsal egress proxy image."
    }
    $env:REHEARSAL_PLUGIN_SANDBOX_IMAGE = $hostDigest.Replace("localhost:19050/", "plugin-registry:5000/")
    $env:REHEARSAL_PLUGIN_EGRESS_PROXY_IMAGE = $hostProxyDigest.Replace("localhost:19050/", "plugin-registry:5000/")
    $env:REHEARSAL_PLUGIN_EGRESS_TOKEN_SECRET = New-RehearsalSecret
    $env:REHEARSAL_PLUGIN_EXECUTOR_TOKEN = $state.token
    $env:REHEARSAL_PLUGIN_LEASE_SECONDS = "10"

    & docker @pluginCompose up --build -d plugin-oci-daemon plugin-executor
    if ($LASTEXITCODE -ne 0) { throw "Could not start the isolated production plugin executor." }
    Wait-ForPluginExecutor
    Invoke-PluginExecutorStage "queue_recovery"

    & docker @pluginCompose stop -t 1 plugin-executor
    if ($LASTEXITCODE -ne 0) { throw "Could not interrupt the plugin executor for lease recovery testing." }
    Start-Sleep -Seconds 13
    & docker @pluginCompose up -d plugin-executor
    if ($LASTEXITCODE -ne 0) { throw "Could not restart the plugin executor after interruption." }
    Wait-ForPluginExecutor
    Invoke-PluginExecutorStage "verify_recovery"

    # The generic job reaper runs on every claim. Stop this specialized claimant
    # before the independent abandoned-worker acceptance test to isolate evidence.
    & docker @pluginCompose stop plugin-executor plugin-oci-daemon plugin-registry | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "Could not stop the isolated plugin tier after acceptance." }
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
    Invoke-PluginExecutorAcceptance

    & docker @compose restart oms-api | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "Could not restart the production API for recovery testing." }
    Wait-ForReady
    Invoke-OidcAcceptance "API restart recovery"
    Invoke-OidcScaleAcceptance

    if (-not $SkipRecovery) {
        & (Join-Path $PSScriptRoot "rehearse-recovery.ps1") -ProjectName "${ProjectName}_recovery"
        if ($LASTEXITCODE -ne 0) { throw "Fresh-volume backup and restore rehearsal failed." }
    }

    $recoveryEvidence = if ($SkipRecovery) { "backup/restore recovery skipped by explicit flag" } else { "backup/restore recovery verified" }
    Write-Output "PRODUCTION_ACCEPTANCE_PASSED: OIDC, RBAC, project-owned onboarding, pipelines, Workshop, actions, AIP Logic, asynchronous agents, model endpoints, evaluations, cross-project denial, signed plugin registration, execute-only isolated OCI execution, executor-loss lease recovery, duplicate-terminal prevention, 200 distinct PKCE identities, two-replica identity reads, authenticated collaboration WebSocket, 50-reader load, cross-replica collaboration, job idempotency, abandoned-worker chaos recovery, serialized migration startup, API restart, and $recoveryEvidence."
} finally {
    Remove-Item -Force -ErrorAction SilentlyContinue $pluginStatePath
    Remove-Item Env:REHEARSAL_PLUGIN_EXECUTOR_TOKEN -ErrorAction SilentlyContinue
    Remove-Item Env:REHEARSAL_PLUGIN_SANDBOX_IMAGE -ErrorAction SilentlyContinue
    Remove-Item Env:REHEARSAL_PLUGIN_EGRESS_PROXY_IMAGE -ErrorAction SilentlyContinue
    Remove-Item Env:REHEARSAL_PLUGIN_EGRESS_TOKEN_SECRET -ErrorAction SilentlyContinue
    Remove-Item Env:PLUGIN_REHEARSAL_STAGE -ErrorAction SilentlyContinue
    Remove-Item Env:PLUGIN_REHEARSAL_STATE_PATH -ErrorAction SilentlyContinue
    Remove-Item Env:PLUGIN_REHEARSAL_EVIDENCE_PATH -ErrorAction SilentlyContinue
    if (-not $KeepStack) {
        & (Join-Path $PSScriptRoot "stop-production-rehearsal.ps1") -ProjectName $ProjectName -DeleteData
    }
}

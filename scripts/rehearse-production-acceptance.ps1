param(
    [string]$ProjectName = "ontology_acceptance",
    [string]$KeycloakAdminPassword = "",
    [string]$PilotAdminPassword = "",
    [string]$PilotViewerPassword = "",
    [string]$PostgresPassword = "",
    [string]$ConnectorSecretKey = "",
    [string]$OidcScalePassword = "",
    [int]$OidcUserCount = 200,
    [int]$OidcLoginConcurrency = 10,
    [switch]$KeepStack,
    [switch]$SkipRecovery,
    [switch]$OnlyPipelineWorkers,
    [switch]$OnlyPipelineMultiDaemon
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
$pipelineCompose = $compose + @("--profile", "pipeline-workers")
$pipelineMultiCompose = $compose + @("--profile", "pipeline-workers", "--profile", "pipeline-multidaemon")
$pluginStatePath = Join-Path $env:TEMP "ontology-plugin-rehearsal-$ProjectName.json"
$pluginEvidencePath = Join-Path $projectRoot "docs/plugin-executor-production-evidence.json"
$pipelineWorkerStatePath = Join-Path $env:TEMP "ontology-pipeline-worker-rehearsal-$ProjectName.json"
$pipelineWorkerEvidencePath = Join-Path $projectRoot "docs/pipeline-worker-container-recovery-evidence.json"
$pipelineMultiDaemonEvidencePath = Join-Path $projectRoot "docs/pipeline-worker-multidaemon-recovery-evidence.json"

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
    Push-Location $projectRoot
    try {
        & python oms/identity_scale_evidence.py --run (Join-Path $projectRoot "docs/oidc-identity-scale-evidence.json")
        if ($LASTEXITCODE -ne 0) { throw "OIDC identity-scale gate evidence did not pass." }
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

function Invoke-PipelineWorkerStage([string]$Stage) {
    $env:PIPELINE_WORKER_REHEARSAL_STAGE = $Stage
    $env:PIPELINE_WORKER_REHEARSAL_STATE_PATH = $pipelineWorkerStatePath
    Push-Location (Join-Path $projectRoot "frontend")
    try {
        $npmCommand = if (Get-Command npm.cmd -ErrorAction SilentlyContinue) { "npm.cmd" } else { "npm" }
        & $npmCommand run test:production-pipeline-worker
        if ($LASTEXITCODE -ne 0) { throw "Pipeline worker acceptance failed during $Stage." }
    } finally {
        Pop-Location
    }
}

function Wait-ForPipelineContainer([string]$Service, [int]$Attempts = 60) {
    $container = "${ProjectName}-${Service}-1"
    for ($attempt = 0; $attempt -lt $Attempts; $attempt++) {
        $health = & docker inspect --format "{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}" $container 2>$null
        if ($LASTEXITCODE -eq 0 -and "$health".Trim() -eq "healthy") { return $container }
        Start-Sleep -Seconds 1
    }
    throw "Timed out waiting for $Service."
}

function Get-PipelineCacheFileCount([string]$Container) {
    $value = & docker exec $Container sh -c "find /var/cache/ontology/snapshots -type f -name '*.parquet' | wc -l"
    if ($LASTEXITCODE -ne 0) { throw "Could not inspect the private cache in $Container." }
    return [int]("$value".Trim())
}

function Invoke-PipelineWorkerAcceptance {
    & docker @pipelineCompose up -d minio snapshot-proxy
    if ($LASTEXITCODE -ne 0) { throw "Could not start the pipeline object-store fixtures." }
    for ($attempt = 0; $attempt -lt 40; $attempt++) {
        try {
            $response = Invoke-WebRequest -UseBasicParsing -Uri "http://127.0.0.1:19000/minio/health/live" -TimeoutSec 2
            if ($response.StatusCode -eq 200) { break }
        } catch {}
        if ($attempt -eq 39) { throw "Timed out waiting for the pipeline MinIO fixture." }
        Start-Sleep -Seconds 1
    }
    $headers = @{ "User-Agent" = "toxiproxy-cli" }
    $proxyBody = @{
        name = "pipeline-snapshot-latency"
        listen = "0.0.0.0:9000"
        upstream = "minio:9000"
        enabled = $true
    } | ConvertTo-Json
    Invoke-RestMethod -Headers $headers -Method Post -Uri "http://127.0.0.1:18575/proxies" `
        -ContentType "application/json" -Body $proxyBody | Out-Null
    $toxicBody = @{
        name = "pipeline-worker-response-latency"
        type = "latency"
        stream = "downstream"
        toxicity = 1.0
        attributes = @{ latency = 150; jitter = 0 }
    } | ConvertTo-Json -Depth 4
    Invoke-RestMethod -Headers $headers -Method Post `
        -Uri "http://127.0.0.1:18575/proxies/pipeline-snapshot-latency/toxics" `
        -ContentType "application/json" -Body $toxicBody | Out-Null

    $env:AWS_ACCESS_KEY_ID = "ontology"
    $env:AWS_SECRET_ACCESS_KEY = "ontology-rehearsal-storage"
    $env:PIPELINE_WORKER_REHEARSAL_ROWS = "100000"
    $env:PIPELINE_WORKER_REHEARSAL_PARTITIONS = "32"
    Invoke-PipelineWorkerStage "bootstrap"
    $state = Get-Content -Raw $pipelineWorkerStatePath | ConvertFrom-Json
    if (-not $state.token -or -not $state.jobId) { throw "Pipeline worker bootstrap did not return credentials and a job." }
    $env:REHEARSAL_PIPELINE_WORKER_TOKEN = $state.token

    & docker @pipelineCompose build pipeline-worker-one pipeline-worker-two
    if ($LASTEXITCODE -ne 0) { throw "Could not build the isolated pipeline workers." }
    & docker @pipelineCompose up --no-build --no-deps -d pipeline-worker-one
    if ($LASTEXITCODE -ne 0) { throw "Could not start the first pipeline worker." }
    $firstContainer = Wait-ForPipelineContainer "pipeline-worker-one"
    $firstCacheFiles = 0
    for ($attempt = 0; $attempt -lt 80; $attempt++) {
        $firstCacheFiles = Get-PipelineCacheFileCount $firstContainer
        if ($firstCacheFiles -gt 0) { break }
        Start-Sleep -Milliseconds 100
    }
    if ($firstCacheFiles -lt 1) { throw "The first pipeline worker never populated its private cache." }
    & docker kill $firstContainer | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "Could not abruptly terminate the first pipeline worker." }
    $firstExitCode = [int]((& docker inspect --format "{{.State.ExitCode}}" $firstContainer).Trim())
    if ($firstExitCode -eq 0) { throw "The first pipeline worker did not record an abrupt exit." }

    Start-Sleep -Seconds 13
    & docker @pipelineCompose up --no-build --no-deps -d pipeline-worker-two
    if ($LASTEXITCODE -ne 0) { throw "Could not start the replacement pipeline worker." }
    $secondContainer = Wait-ForPipelineContainer "pipeline-worker-two"
    Invoke-PipelineWorkerStage "verify"
    $secondCacheFiles = Get-PipelineCacheFileCount $secondContainer
    $state = Get-Content -Raw $pipelineWorkerStatePath | ConvertFrom-Json
    if (-not $state.verification -or $state.verification.databaseHead -ne $state.verification.runtimeHead) {
        throw "Pipeline worker verification did not prove a current migration head."
    }
    if ($secondCacheFiles -ne [int]$state.partitions) {
        throw "Replacement cache has $secondCacheFiles files; expected $($state.partitions)."
    }
    $evidence = [ordered]@{
        status = "PASS"
        provenance = [ordered]@{
            migration_head = $state.verification.runtimeHead
            observed_migration_head = $state.verification.databaseHead
            harness = "scripts/rehearse-production-acceptance.ps1"
        }
        profile = "production-oidc-container-worker-recovery"
        generated_at = (Get-Date).ToUniversalTime().ToString("o")
        job_id = $state.jobId
        input_snapshot_id = $state.inputSnapshotId
        input_rows = [int]$state.rows
        input_partitions = [int]$state.partitions
        first_worker = [ordered]@{
            container = $firstContainer
            exit_code = $firstExitCode
            private_cache_files_before_kill = $firstCacheFiles
        }
        replacement_worker = [ordered]@{
            container = $secondContainer
            private_cache_files = $secondCacheFiles
            attempt = [int]$state.verification.attempt
        }
        publication = [ordered]@{
            claim_count = [int]$state.verification.claimCount
            requeue_count = [int]$state.verification.requeueCount
            success_count = [int]$state.verification.successCount
            output_snapshot_id = $state.verification.outputSnapshotId
            output_rows = [int]$state.verification.outputRows
            output_snapshot_count = 1
            execution_fenced = $true
        }
    }
    $evidence | ConvertTo-Json -Depth 8 | Set-Content -Encoding UTF8 $pipelineWorkerEvidencePath
    Write-Output "PIPELINE_WORKER_RECOVERY_PASSED: first cache $firstCacheFiles, replacement cache $secondCacheFiles, job $($state.jobId)."
    & docker @pipelineCompose stop pipeline-worker-two snapshot-proxy minio | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "Could not stop pipeline worker fixtures after acceptance." }
}

function Wait-ForRemoteDocker([string]$Endpoint, [int]$Attempts = 60) {
    $pingUrl = $Endpoint.Replace("tcp://", "http://") + "/_ping"
    for ($attempt = 0; $attempt -lt $Attempts; $attempt++) {
        try {
            $response = Invoke-WebRequest -UseBasicParsing -Uri $pingUrl -TimeoutSec 2
            if ($response.StatusCode -eq 200 -and "$($response.Content)".Trim() -eq "OK") { return }
        } catch {}
        Start-Sleep -Seconds 1
    }
    throw "Timed out waiting for independent Docker daemon $Endpoint."
}

function Get-RehearsalServiceIp([string]$Service) {
    $container = (& docker @pipelineMultiCompose ps -q $Service).Trim()
    if ($LASTEXITCODE -ne 0 -or -not $container) { throw "Could not resolve the $Service container." }
    $address = (& docker inspect --format "{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}" $container).Trim()
    if ($LASTEXITCODE -ne 0 -or $address -notmatch '^\d+\.\d+\.\d+\.\d+$') {
        throw "Could not resolve a routable address for $Service."
    }
    return $address
}

function Start-RemotePipelineWorker(
    [string]$Endpoint,
    [string]$Image,
    [string]$WorkerName,
    [string]$ApiAddress,
    [string]$DatabaseAddress,
    [string]$SnapshotAddress,
    [string]$Token
) {
    $encodedPassword = [Uri]::EscapeDataString($PostgresPassword)
    $arguments = @(
        "-H", $Endpoint, "run", "-d", "--name", "ontology-pipeline-worker",
        "--read-only",
        "--tmpfs", "/tmp:rw,noexec,nosuid,nodev,size=64m,mode=1777",
        "--tmpfs", "/var/cache/ontology/snapshots:rw,noexec,nosuid,nodev,size=256m,mode=0700",
        "--tmpfs", "/var/lib/ontology/snapshots:rw,noexec,nosuid,nodev,size=256m,mode=0700",
        "-e", "APP_ENV=production",
        "-e", "DATABASE_URL=postgresql+psycopg2://ontology:${encodedPassword}@${DatabaseAddress}:5432/ontology",
        "-e", "WORKER_API_URL=http://${ApiAddress}:8000",
        "-e", "WORKER_TOKEN=$Token",
        "-e", "WORKER_NAME=$WorkerName",
        "-e", "WORKER_PROJECT_ID=default",
        "-e", "WORKER_JOB_TYPES=pipeline.duckdb.deliver",
        "-e", "WORKER_CONCURRENCY=1",
        "-e", "WORKER_LEASE_SECONDS=10",
        "-e", "WORKER_POLL_SECONDS=0.1",
        "-e", "WORKER_HEARTBEAT_SECONDS=2",
        "-e", "WORKER_HEALTH_PORT=8091",
        "-e", "DATA_SNAPSHOT_BACKEND=s3",
        "-e", "DATA_SNAPSHOT_ROOT=/var/lib/ontology/snapshots",
        "-e", "DATA_SNAPSHOT_BUCKET=ontology-rehearsal",
        "-e", "DATA_SNAPSHOT_S3_ENDPOINT=http://${SnapshotAddress}:9000",
        "-e", "DATA_SNAPSHOT_S3_REGION=us-east-1",
        "-e", "DATA_SNAPSHOT_S3_ADDRESSING_STYLE=path",
        "-e", "DATA_SNAPSHOT_S3_AUTO_CREATE_BUCKET=false",
        "-e", "DATA_SNAPSHOT_CACHE_ROOT=/var/cache/ontology/snapshots",
        "-e", "DATA_SNAPSHOT_CACHE_MAX_BYTES=2147483648",
        "-e", "DATA_SNAPSHOT_CACHE_LEASE_SECONDS=0",
        "-e", "AWS_ACCESS_KEY_ID=ontology",
        "-e", "AWS_SECRET_ACCESS_KEY=ontology-rehearsal-storage",
        $Image, "python", "-m", "app.worker_daemon"
    )
    $containerOutput = & docker @arguments
    $container = ("$containerOutput").Trim()
    if ($LASTEXITCODE -ne 0 -or -not $container) { throw "Could not start $WorkerName in $Endpoint." }
    return $container
}

function Wait-ForRemotePipelineWorker([string]$Endpoint, [int]$Attempts = 60) {
    for ($attempt = 0; $attempt -lt $Attempts; $attempt++) {
        $ready = $false
        try {
            & docker -H $Endpoint exec ontology-pipeline-worker python -c `
                "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8091/health/ready', timeout=2).read()" `
                2>$null | Out-Null
            $ready = $LASTEXITCODE -eq 0
        } catch {}
        if ($ready) { return }
        Start-Sleep -Seconds 1
    }
    & docker -H $Endpoint logs ontology-pipeline-worker
    throw "Timed out waiting for the pipeline worker in $Endpoint."
}

function Get-RemotePipelineCacheFileCount([string]$Endpoint) {
    $value = & docker -H $Endpoint exec ontology-pipeline-worker sh -c `
        "find /var/cache/ontology/snapshots -type f -name '*.parquet' | wc -l"
    if ($LASTEXITCODE -ne 0) { throw "Could not inspect the private cache in $Endpoint." }
    return [int]("$value".Trim())
}

function Invoke-PipelineWorkerMultiDaemonAcceptance {
    $firstEndpoint = "tcp://127.0.0.1:12375"
    $secondEndpoint = "tcp://127.0.0.1:22375"
    $imageArchive = Join-Path $env:TEMP "ontology-worker-image-$ProjectName.tar"
    try {
        & docker @pipelineMultiCompose up -d minio snapshot-proxy pipeline-worker-daemon-one pipeline-worker-daemon-two
        if ($LASTEXITCODE -ne 0) { throw "Could not start multi-daemon pipeline fixtures." }
        Wait-ForRemoteDocker $firstEndpoint
        Wait-ForRemoteDocker $secondEndpoint
        for ($attempt = 0; $attempt -lt 40; $attempt++) {
            try {
                $response = Invoke-WebRequest -UseBasicParsing -Uri "http://127.0.0.1:19000/minio/health/live" -TimeoutSec 2
                if ($response.StatusCode -eq 200) { break }
            } catch {}
            if ($attempt -eq 39) { throw "Timed out waiting for the multi-daemon MinIO fixture." }
            Start-Sleep -Seconds 1
        }
        $headers = @{ "User-Agent" = "toxiproxy-cli" }
        $proxyBody = @{
            name = "pipeline-multidaemon-latency"
            listen = "0.0.0.0:9000"
            upstream = "minio:9000"
            enabled = $true
        } | ConvertTo-Json
        Invoke-RestMethod -Headers $headers -Method Post -Uri "http://127.0.0.1:18575/proxies" `
            -ContentType "application/json" -Body $proxyBody | Out-Null
        $toxicBody = @{
            name = "pipeline-multidaemon-response-latency"
            type = "latency"
            stream = "downstream"
            toxicity = 1.0
            attributes = @{ latency = 150; jitter = 0 }
        } | ConvertTo-Json -Depth 4
        Invoke-RestMethod -Headers $headers -Method Post `
            -Uri "http://127.0.0.1:18575/proxies/pipeline-multidaemon-latency/toxics" `
            -ContentType "application/json" -Body $toxicBody | Out-Null

        $env:AWS_ACCESS_KEY_ID = "ontology"
        $env:AWS_SECRET_ACCESS_KEY = "ontology-rehearsal-storage"
        $env:PIPELINE_WORKER_REHEARSAL_ROWS = "100000"
        $env:PIPELINE_WORKER_REHEARSAL_PARTITIONS = "32"
        $env:PIPELINE_WORKER_FIRST_NAME = "rehearsal-multidaemon-worker-one"
        $env:PIPELINE_WORKER_REPLACEMENT_NAME = "rehearsal-multidaemon-worker-two"
        Invoke-PipelineWorkerStage "bootstrap"
        $state = Get-Content -Raw $pipelineWorkerStatePath | ConvertFrom-Json
        if (-not $state.token -or -not $state.jobId) { throw "Multi-daemon bootstrap did not return credentials and a job." }

        & docker @pipelineCompose build pipeline-worker-one
        if ($LASTEXITCODE -ne 0) { throw "Could not build the production worker image." }
        $workerImageTag = "${ProjectName}-pipeline-worker-one:latest"
        $image = (& docker image inspect --format "{{.Id}}" $workerImageTag).Trim()
        if ($LASTEXITCODE -ne 0 -or $image -notmatch '^sha256:[a-f0-9]{64}$') {
            throw "Could not resolve the production worker image digest."
        }
        & docker save -o $imageArchive $workerImageTag
        if ($LASTEXITCODE -ne 0) { throw "Could not export the production worker image." }
        & docker -H $firstEndpoint load -i $imageArchive | Out-Null
        if ($LASTEXITCODE -ne 0) { throw "Could not load the worker image into daemon one." }
        & docker -H $secondEndpoint load -i $imageArchive | Out-Null
        if ($LASTEXITCODE -ne 0) { throw "Could not load the worker image into daemon two." }

        $apiAddress = Get-RehearsalServiceIp "oms-api"
        $databaseAddress = Get-RehearsalServiceIp "postgres"
        $snapshotAddress = Get-RehearsalServiceIp "snapshot-proxy"
        $firstContainer = Start-RemotePipelineWorker $firstEndpoint $workerImageTag `
            $env:PIPELINE_WORKER_FIRST_NAME $apiAddress $databaseAddress $snapshotAddress $state.token
        Wait-ForRemotePipelineWorker $firstEndpoint
        $firstCacheFiles = 0
        for ($attempt = 0; $attempt -lt 80; $attempt++) {
            $firstCacheFiles = Get-RemotePipelineCacheFileCount $firstEndpoint
            if ($firstCacheFiles -gt 0) { break }
            Start-Sleep -Milliseconds 100
        }
        if ($firstCacheFiles -lt 1) { throw "The first independent daemon never populated its cache." }
        & docker -H $firstEndpoint kill ontology-pipeline-worker | Out-Null
        if ($LASTEXITCODE -ne 0) { throw "Could not kill the first independent worker." }
        $firstExitCode = [int]((& docker -H $firstEndpoint inspect --format "{{.State.ExitCode}}" ontology-pipeline-worker).Trim())
        if ($firstExitCode -eq 0) { throw "The first independent worker did not record an abrupt exit." }

        Start-Sleep -Seconds 13
        $replacementContainer = Start-RemotePipelineWorker $secondEndpoint $workerImageTag `
            $env:PIPELINE_WORKER_REPLACEMENT_NAME $apiAddress $databaseAddress $snapshotAddress $state.token
        Wait-ForRemotePipelineWorker $secondEndpoint
        Invoke-PipelineWorkerStage "verify"
        $replacementCacheFiles = Get-RemotePipelineCacheFileCount $secondEndpoint
        $state = Get-Content -Raw $pipelineWorkerStatePath | ConvertFrom-Json
        if (-not $state.verification -or $state.verification.databaseHead -ne $state.verification.runtimeHead) {
            throw "Multi-daemon verification did not prove a current migration head."
        }
        if ($replacementCacheFiles -ne [int]$state.partitions) {
            throw "Replacement daemon cache has $replacementCacheFiles files; expected $($state.partitions)."
        }
        $evidence = [ordered]@{
            status = "PASS"
            provenance = [ordered]@{
                migration_head = $state.verification.runtimeHead
                observed_migration_head = $state.verification.databaseHead
                harness = "scripts/rehearse-production-acceptance.ps1"
            }
            profile = "production-oidc-independent-docker-daemon-worker-recovery"
            generated_at = (Get-Date).ToUniversalTime().ToString("o")
            topology = [ordered]@{
                independent_docker_daemons = 2
                shared_worker_filesystem = $false
                shared_image_store = $false
                shared_cache = $false
                physical_hosts = 1
            }
            job_id = $state.jobId
            input_snapshot_id = $state.inputSnapshotId
            input_rows = [int]$state.rows
            input_partitions = [int]$state.partitions
            first_worker = [ordered]@{
                daemon = $firstEndpoint
                container = $firstContainer
                exit_code = $firstExitCode
                private_cache_files_before_kill = $firstCacheFiles
            }
            replacement_worker = [ordered]@{
                daemon = $secondEndpoint
                container = $replacementContainer
                private_cache_files = $replacementCacheFiles
                attempt = [int]$state.verification.attempt
            }
            publication = [ordered]@{
                claim_count = [int]$state.verification.claimCount
                requeue_count = [int]$state.verification.requeueCount
                success_count = [int]$state.verification.successCount
                output_snapshot_id = $state.verification.outputSnapshotId
                output_rows = [int]$state.verification.outputRows
                output_snapshot_count = 1
                execution_fenced = $true
            }
        }
        $json = $evidence | ConvertTo-Json -Depth 8
        [IO.File]::WriteAllText($pipelineMultiDaemonEvidencePath, $json, [Text.UTF8Encoding]::new($false))
        Write-Output "PIPELINE_MULTIDAEMON_RECOVERY_PASSED: first cache $firstCacheFiles, replacement cache $replacementCacheFiles, job $($state.jobId)."
    } finally {
        try {
            $firstRemoteContainer = (& docker -H $firstEndpoint ps -aq --filter "name=^/ontology-pipeline-worker$" 2>$null)
            if ($firstRemoteContainer) { & docker -H $firstEndpoint rm -f $firstRemoteContainer 2>$null | Out-Null }
        } catch {}
        try {
            $secondRemoteContainer = (& docker -H $secondEndpoint ps -aq --filter "name=^/ontology-pipeline-worker$" 2>$null)
            if ($secondRemoteContainer) { & docker -H $secondEndpoint rm -f $secondRemoteContainer 2>$null | Out-Null }
        } catch {}
        Remove-Item -Force -ErrorAction SilentlyContinue $imageArchive
        try {
            & docker @pipelineMultiCompose stop pipeline-worker-daemon-one pipeline-worker-daemon-two snapshot-proxy minio 2>$null | Out-Null
        } catch {}
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

    if ($OnlyPipelineWorkers -and $OnlyPipelineMultiDaemon) {
        throw "Choose only one focused pipeline-worker acceptance mode."
    } elseif ($OnlyPipelineWorkers) {
        Invoke-PipelineWorkerAcceptance
        Write-Output "PRODUCTION_PIPELINE_WORKER_ACCEPTANCE_PASSED: OIDC bootstrap, container loss, independent cache recovery, and fenced publication."
    } elseif ($OnlyPipelineMultiDaemon) {
        Invoke-PipelineWorkerMultiDaemonAcceptance
        Write-Output "PRODUCTION_PIPELINE_MULTIDAEMON_ACCEPTANCE_PASSED: OIDC bootstrap, independent Docker-daemon loss recovery, and fenced publication."
    } else {
        Invoke-OidcAcceptance "initial deployment"
        Invoke-PluginExecutorAcceptance
        Invoke-PipelineWorkerAcceptance
        Invoke-PipelineWorkerMultiDaemonAcceptance

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
        Write-Output "PRODUCTION_ACCEPTANCE_PASSED: OIDC, RBAC, project-owned onboarding, pipelines, Workshop, actions, AIP Logic, asynchronous agents, model endpoints, evaluations, cross-project denial, signed plugin registration, execute-only isolated OCI execution, executor-loss lease recovery, container-isolated and independent-Docker-daemon pipeline worker recovery with private caches, duplicate-terminal prevention, 200 distinct PKCE identities, two-replica identity reads, authenticated collaboration WebSocket, 50-reader load, cross-replica collaboration, job idempotency, abandoned-worker chaos recovery, serialized migrations, API restart, and $recoveryEvidence."
    }
} finally {
    Remove-Item -Force -ErrorAction SilentlyContinue $pluginStatePath
    Remove-Item -Force -ErrorAction SilentlyContinue $pipelineWorkerStatePath
    Remove-Item Env:REHEARSAL_PLUGIN_EXECUTOR_TOKEN -ErrorAction SilentlyContinue
    Remove-Item Env:REHEARSAL_PLUGIN_SANDBOX_IMAGE -ErrorAction SilentlyContinue
    Remove-Item Env:REHEARSAL_PLUGIN_EGRESS_PROXY_IMAGE -ErrorAction SilentlyContinue
    Remove-Item Env:REHEARSAL_PLUGIN_EGRESS_TOKEN_SECRET -ErrorAction SilentlyContinue
    Remove-Item Env:PLUGIN_REHEARSAL_STAGE -ErrorAction SilentlyContinue
    Remove-Item Env:PLUGIN_REHEARSAL_STATE_PATH -ErrorAction SilentlyContinue
    Remove-Item Env:PLUGIN_REHEARSAL_EVIDENCE_PATH -ErrorAction SilentlyContinue
    Remove-Item Env:REHEARSAL_PIPELINE_WORKER_TOKEN -ErrorAction SilentlyContinue
    Remove-Item Env:PIPELINE_WORKER_REHEARSAL_STAGE -ErrorAction SilentlyContinue
    Remove-Item Env:PIPELINE_WORKER_REHEARSAL_STATE_PATH -ErrorAction SilentlyContinue
    Remove-Item Env:PIPELINE_WORKER_REHEARSAL_ROWS -ErrorAction SilentlyContinue
    Remove-Item Env:PIPELINE_WORKER_REHEARSAL_PARTITIONS -ErrorAction SilentlyContinue
    Remove-Item Env:PIPELINE_WORKER_FIRST_NAME -ErrorAction SilentlyContinue
    Remove-Item Env:PIPELINE_WORKER_REPLACEMENT_NAME -ErrorAction SilentlyContinue
    Remove-Item Env:AWS_ACCESS_KEY_ID -ErrorAction SilentlyContinue
    Remove-Item Env:AWS_SECRET_ACCESS_KEY -ErrorAction SilentlyContinue
    if (-not $KeepStack) {
        & (Join-Path $PSScriptRoot "stop-production-rehearsal.ps1") -ProjectName $ProjectName -DeleteData
    }
}

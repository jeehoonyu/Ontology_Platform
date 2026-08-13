param(
    [int]$Rows = 100000,
    [int]$Partitions = 32,
    [int]$LatencyMs = 150
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$network = "ontologyos-worker-recovery"
$postgres = "ontologyos-worker-recovery-postgres"
$minio = "ontologyos-worker-recovery-minio"
$proxy = "ontologyos-worker-recovery-toxiproxy"
$postgresPort = 15439
$minioPort = 19100
$proxyPort = 19101
$adminPort = 18574
$toxiproxyImage = "ghcr.io/shopify/toxiproxy@sha256:9378ed52a28bc50edc1350f936f518f31fa95f0d15917d6eb40b8e376d1a214e"

function Remove-RecoveryResources {
    foreach ($name in @($postgres, $minio, $proxy)) {
        if (docker ps -a --format '{{.Names}}' | Where-Object { $_ -eq $name }) {
            docker rm -f $name | Out-Null
        }
    }
    if (docker network ls --format '{{.Name}}' | Where-Object { $_ -eq $network }) {
        docker network rm $network | Out-Null
    }
}

try {
    Remove-RecoveryResources
    docker network create $network | Out-Null
    docker run -d --name $postgres --network $network `
        -e POSTGRES_USER=ontology -e POSTGRES_PASSWORD=ontology-recovery `
        -e POSTGRES_DB=ontology_recovery -p "${postgresPort}:5432" postgres:16-alpine | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "PostgreSQL failed to start" }
    docker run -d --name $minio --network $network `
        -e MINIO_ROOT_USER=ontology -e MINIO_ROOT_PASSWORD=ontology-development-secret `
        -p "${minioPort}:9000" `
        minio/minio:RELEASE.2025-04-22T22-12-26Z server /data | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "MinIO failed to start" }
    docker run -d --name $proxy --network $network `
        -p "${adminPort}:8474" -p "${proxyPort}:9000" $toxiproxyImage | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "Toxiproxy failed to start" }

    $postgresReady = $false
    $minioReady = $false
    for ($attempt = 0; $attempt -lt 45; $attempt++) {
        if (-not $postgresReady) {
            docker exec $postgres pg_isready -U ontology -d ontology_recovery 2>$null | Out-Null
            $postgresReady = $LASTEXITCODE -eq 0
        }
        if (-not $minioReady) {
            try {
                $response = Invoke-WebRequest -UseBasicParsing "http://127.0.0.1:${minioPort}/minio/health/live" -TimeoutSec 2
                $minioReady = $response.StatusCode -eq 200
            } catch {}
        }
        if ($postgresReady -and $minioReady) { break }
        Start-Sleep -Seconds 1
    }
    if (-not $postgresReady) { throw "PostgreSQL did not become healthy" }
    if (-not $minioReady) { throw "MinIO did not become healthy" }

    $headers = @{ "User-Agent" = "toxiproxy-cli" }
    $proxyBody = @{
        name = "minio-recovery-latency"
        listen = "0.0.0.0:9000"
        upstream = "${minio}:9000"
        enabled = $true
    } | ConvertTo-Json
    Invoke-RestMethod -Headers $headers -Method Post `
        -Uri "http://127.0.0.1:${adminPort}/proxies" `
        -ContentType "application/json" -Body $proxyBody | Out-Null
    $toxicBody = @{
        name = "worker-recovery-response-latency"
        type = "latency"
        stream = "downstream"
        toxicity = 1.0
        attributes = @{ latency = $LatencyMs; jitter = 0 }
    } | ConvertTo-Json -Depth 4
    Invoke-RestMethod -Headers $headers -Method Post `
        -Uri "http://127.0.0.1:${adminPort}/proxies/minio-recovery-latency/toxics" `
        -ContentType "application/json" -Body $toxicBody | Out-Null

    $env:DATABASE_URL = "postgresql+psycopg2://ontology:ontology-recovery@127.0.0.1:${postgresPort}/ontology_recovery"
    $env:AWS_ACCESS_KEY_ID = "ontology"
    $env:AWS_SECRET_ACCESS_KEY = "ontology-development-secret"
    $env:DATA_SNAPSHOT_BACKEND = "s3"
    $env:DATA_SNAPSHOT_BUCKET = "ontology-recovery"
    $env:DATA_SNAPSHOT_S3_ENDPOINT = "http://127.0.0.1:${proxyPort}"
    $env:DATA_SNAPSHOT_S3_REGION = "us-east-1"
    $env:DATA_SNAPSHOT_S3_ADDRESSING_STYLE = "path"
    $env:DATA_SNAPSHOT_S3_AUTO_CREATE_BUCKET = "false"
    $env:DATA_SNAPSHOT_MAX_FILES = "256"
    $env:PIPELINE_RECOVERY_S3_ADMIN_ENDPOINT = "http://127.0.0.1:${minioPort}"
    $env:PIPELINE_RECOVERY_ROWS = [string]$Rows
    $env:PIPELINE_RECOVERY_PARTITIONS = [string]$Partitions
    $env:PIPELINE_RECOVERY_LEASE_SECONDS = "10"
    $env:PIPELINE_RECOVERY_EVIDENCE_PATH = "docs/pipeline-worker-recovery-evidence.json"

    Push-Location "$repoRoot/oms"
    try {
        python -m alembic upgrade head
        if ($LASTEXITCODE -ne 0) { throw "PostgreSQL migration failed" }
    } finally {
        Pop-Location
    }
    Push-Location $repoRoot
    try {
        python oms/rehearse_pipeline_worker_recovery.py
        if ($LASTEXITCODE -ne 0) { throw "Pipeline worker recovery rehearsal failed" }
    } finally {
        Pop-Location
    }
} finally {
    Remove-RecoveryResources
}

param(
    [int]$Rows = 1000000,
    [int]$Partitions = 8,
    [int]$Samples = 5,
    [int]$ConcurrentWorkers = 4,
    [int]$LatencyMs = 40,
    [int]$JitterMs = 5
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$network = "ontologyos-object-storage-benchmark"
$minio = "ontologyos-object-storage-minio"
$proxy = "ontologyos-object-storage-toxiproxy"
$minioPort = 19000
$proxyPort = 19001
$adminPort = 18474
$toxiproxyImage = "ghcr.io/shopify/toxiproxy@sha256:9378ed52a28bc50edc1350f936f518f31fa95f0d15917d6eb40b8e376d1a214e"

function Remove-BenchmarkResources {
    foreach ($name in @($minio, $proxy)) {
        if (docker ps -a --format '{{.Names}}' | Where-Object { $_ -eq $name }) {
            docker rm -f $name | Out-Null
        }
    }
    if (docker network ls --format '{{.Name}}' | Where-Object { $_ -eq $network }) {
        docker network rm $network | Out-Null
    }
}

try {
    Remove-BenchmarkResources
    docker network create $network | Out-Null
    docker run -d --name $minio --network $network `
        -e MINIO_ROOT_USER=ontology `
        -e MINIO_ROOT_PASSWORD=ontology-development-secret `
        -p "${minioPort}:9000" `
        minio/minio:RELEASE.2025-04-22T22-12-26Z server /data | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "MinIO failed to start" }
    docker run -d --name $proxy --network $network `
        -p "${adminPort}:8474" -p "${proxyPort}:9000" `
        $toxiproxyImage | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "Toxiproxy failed to start" }

    $ready = $false
    for ($attempt = 0; $attempt -lt 30; $attempt++) {
        try {
            $response = Invoke-WebRequest -UseBasicParsing `
                "http://127.0.0.1:${minioPort}/minio/health/live" -TimeoutSec 2
            if ($response.StatusCode -eq 200) { $ready = $true; break }
        } catch {}
        Start-Sleep -Seconds 1
    }
    if (-not $ready) { throw "MinIO did not become healthy" }

    $headers = @{ "User-Agent" = "toxiproxy-cli" }
    $proxyBody = @{
        name = "minio-latency"
        listen = "0.0.0.0:9000"
        upstream = "${minio}:9000"
        enabled = $true
    } | ConvertTo-Json
    Invoke-RestMethod -Headers $headers -Method Post `
        -Uri "http://127.0.0.1:${adminPort}/proxies" `
        -ContentType "application/json" -Body $proxyBody | Out-Null
    $toxicBody = @{
        name = "object-store-response-latency"
        type = "latency"
        stream = "downstream"
        toxicity = 1.0
        attributes = @{ latency = $LatencyMs; jitter = $JitterMs }
    } | ConvertTo-Json -Depth 4
    Invoke-RestMethod -Headers $headers -Method Post `
        -Uri "http://127.0.0.1:${adminPort}/proxies/minio-latency/toxics" `
        -ContentType "application/json" -Body $toxicBody | Out-Null

    $env:AWS_ACCESS_KEY_ID = "ontology"
    $env:AWS_SECRET_ACCESS_KEY = "ontology-development-secret"
    $env:DATA_SNAPSHOT_S3_ENDPOINT = "http://127.0.0.1:${proxyPort}"
    $env:OBJECT_STORAGE_NETWORK_SCOPE = "toxiproxy-${LatencyMs}ms-downstream-jitter-${JitterMs}ms"
    $env:OBJECT_STORAGE_TOXIPROXY_ADMIN_URL = "http://127.0.0.1:${adminPort}"
    $env:OBJECT_STORAGE_TOXIPROXY_NAME = "minio-latency"
    $env:OBJECT_STORAGE_TOXIPROXY_ENDPOINT = $env:DATA_SNAPSHOT_S3_ENDPOINT
    $env:OBJECT_STORAGE_BENCHMARK_PROFILE = "reference"
    $env:OBJECT_STORAGE_BENCHMARK_ROWS = [string]$Rows
    $env:OBJECT_STORAGE_BENCHMARK_PARTITIONS = [string]$Partitions
    $env:OBJECT_STORAGE_BENCHMARK_SAMPLES = [string]$Samples
    $env:OBJECT_STORAGE_BENCHMARK_CONCURRENT_WORKERS = [string]$ConcurrentWorkers
    $env:OBJECT_STORAGE_BENCHMARK_EVIDENCE_PATH = "docs/object-storage-reference-evidence.json"

    Push-Location $repoRoot
    try {
        python oms/benchmark_object_storage_minio.py
        if ($LASTEXITCODE -ne 0) { throw "Object-storage reference benchmark failed" }
    } finally {
        Pop-Location
    }
} finally {
    Remove-BenchmarkResources
}

param(
    [string]$EvidencePath = "docs/plugin-egress-rehearsal-evidence.json"
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$sandboxTag = "ontologyos-plugin-sandbox-egress-rehearsal"
$proxyTag = "ontologyos-plugin-egress-proxy-rehearsal"

& docker build -f (Join-Path $root "oms/plugin-sandbox.Dockerfile") -t $sandboxTag $root
if ($LASTEXITCODE -ne 0) { throw "Could not build the plugin sandbox image." }
& docker build -f (Join-Path $root "oms/plugin-egress-proxy.Dockerfile") -t $proxyTag $root
if ($LASTEXITCODE -ne 0) { throw "Could not build the plugin egress proxy image." }

$sandboxImage = (& docker image inspect --format "{{.Id}}" $sandboxTag).Trim()
$proxyImage = (& docker image inspect --format "{{.Id}}" $proxyTag).Trim()
& python (Join-Path $root "oms/rehearse_plugin_egress.py") `
    --sandbox-image $sandboxImage `
    --proxy-image $proxyImage `
    --evidence (Join-Path $root $EvidencePath)
if ($LASTEXITCODE -ne 0) { throw "Plugin egress policy rehearsal failed." }

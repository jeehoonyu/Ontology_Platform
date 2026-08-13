param(
    [string]$Tag = "ontologyos-plugin-sandbox:rehearsal",
    [string]$EvidencePath = "docs/plugin-oci-rehearsal-evidence.json",
    [switch]$KeepImage
)

$ErrorActionPreference = "Stop"
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path

& docker build --file (Join-Path $repoRoot "oms/plugin-sandbox.Dockerfile") --tag $Tag $repoRoot
if ($LASTEXITCODE -ne 0) { throw "Plugin sandbox image build failed." }

$imageId = (& docker image inspect --format '{{.Id}}' $Tag).Trim()
if ($LASTEXITCODE -ne 0 -or -not $imageId.StartsWith("sha256:")) { throw "Could not resolve the immutable sandbox image ID." }

try {
    & python (Join-Path $repoRoot "oms/rehearse_plugin_oci.py") --image $imageId --evidence (Join-Path $repoRoot $EvidencePath)
    if ($LASTEXITCODE -ne 0) { throw "Plugin OCI rehearsal failed." }
}
finally {
    if (-not $KeepImage) {
        & docker image rm $Tag | Out-Null
    }
}

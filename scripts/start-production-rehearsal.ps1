param(
    [Parameter(Mandatory = $true)]
    [string]$KeycloakAdminPassword,
    [Parameter(Mandatory = $true)]
    [string]$PilotAdminPassword,
    [Parameter(Mandatory = $true)]
    [string]$PilotViewerPassword,
    [string]$PostgresPassword = "rehearsal-postgres-only",
    [string]$ConnectorSecretKey = "",
    [string]$ProjectName = "ontology_rehearsal"
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$composeFile = Join-Path $projectRoot "docker-compose.rehearsal.yml"
$env:REHEARSAL_KEYCLOAK_ADMIN_PASSWORD = $KeycloakAdminPassword
$env:REHEARSAL_POSTGRES_PASSWORD = $PostgresPassword
if (-not $ConnectorSecretKey) {
    $bytes = New-Object byte[] 32
    $generator = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    try { $generator.GetBytes($bytes) } finally { $generator.Dispose() }
    $ConnectorSecretKey = [Convert]::ToBase64String($bytes)
}
$env:REHEARSAL_CONNECTOR_SECRET_KEY = $ConnectorSecretKey
$compose = @("compose", "-p", $ProjectName, "-f", $composeFile)

& docker @compose up --build -d
if ($LASTEXITCODE -ne 0) { throw "Could not start the production rehearsal stack." }

function Wait-ForUrl([string]$Url, [int]$Attempts = 80) {
    for ($attempt = 0; $attempt -lt $Attempts; $attempt++) {
        try {
            $response = Invoke-WebRequest -UseBasicParsing -Uri $Url -TimeoutSec 3
            if ($response.StatusCode -eq 200) { return }
        } catch {}
        Start-Sleep -Seconds 2
    }
    throw "Timed out waiting for $Url"
}

Wait-ForUrl "http://127.0.0.1:18080/realms/ontology/.well-known/openid-configuration"
Wait-ForUrl "http://127.0.0.1:18000/health/ready"
Wait-ForUrl "http://127.0.0.1:18001/health/ready"

$kcadm = "/opt/keycloak/bin/kcadm.sh"
& docker @compose exec -T keycloak $kcadm config credentials --server http://localhost:8080 --realm master --user rehearsal-admin --password $KeycloakAdminPassword | Out-Null
if ($LASTEXITCODE -ne 0) { throw "Could not authenticate to the rehearsal identity provider." }

& docker @compose exec -T keycloak $kcadm update users/profile -r ontology -f /opt/keycloak/conf/ontology-user-profile.json | Out-Null
if ($LASTEXITCODE -ne 0) { throw "Could not register tenant attributes in the rehearsal identity provider." }

function Ensure-RealmUser([string]$Username, [string]$Password, [string]$Role) {
    $json = & docker @compose exec -T keycloak $kcadm get users -r ontology -q "username=$Username"
    if ($LASTEXITCODE -ne 0) { throw "Could not query Keycloak user $Username." }
    $parsedUsers = ($json -join "`n") | ConvertFrom-Json
    $users = @($parsedUsers) | Where-Object { $_ -and $_.username }
    if ($users.Count -eq 0) {
        & docker @compose exec -T keycloak $kcadm create users -r ontology -s "username=$Username" -s enabled=true -s "email=$Username@rehearsal.local" -s emailVerified=true -s firstName=Pilot -s "lastName=$Role" | Out-Null
        if ($LASTEXITCODE -ne 0) { throw "Could not create Keycloak user $Username." }
        $json = & docker @compose exec -T keycloak $kcadm get users -r ontology -q "username=$Username"
        $parsedUsers = ($json -join "`n") | ConvertFrom-Json
        $users = @($parsedUsers) | Where-Object { $_ -and $_.username }
    }
    $userId = $users[0].id
    & docker @compose exec -T keycloak $kcadm update "users/$userId" -r ontology -s enabled=true -s emailVerified=true -s firstName=Pilot -s "lastName=$Role" -s 'requiredActions=[]' -s 'attributes.organization_id=pilot' -s 'attributes.project_ids=default' | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "Could not complete the profile for $Username." }
    $updatedJson = & docker @compose exec -T keycloak $kcadm get "users/$userId" -r ontology
    if ($LASTEXITCODE -ne 0) { throw "Could not verify the profile for $Username." }
    $updated = ($updatedJson -join "`n") | ConvertFrom-Json
    if ($updated.attributes.organization_id -notcontains "pilot" -or $updated.attributes.project_ids -notcontains "default") {
        throw "Tenant attributes were not persisted for $Username."
    }
    & docker @compose exec -T keycloak $kcadm set-password -r ontology --username $Username --new-password $Password | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "Could not set password for $Username." }
    & docker @compose exec -T keycloak $kcadm add-roles -r ontology --uusername $Username --rolename $Role | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "Could not assign role $Role to $Username." }
}

Ensure-RealmUser "pilot-admin" $PilotAdminPassword "administrator"
Ensure-RealmUser "pilot-viewer" $PilotViewerPassword "viewer"

Write-Output "Production rehearsal is ready."
Write-Output "Application: http://localhost:18000/workspace/command-center"
Write-Output "Peer API: http://localhost:18001"
Write-Output "Identity provider: http://idp.localhost:18080"
Write-Output "Users: pilot-admin (administrator), pilot-viewer (viewer)"

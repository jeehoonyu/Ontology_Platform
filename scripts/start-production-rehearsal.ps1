param(
    [Parameter(Mandatory = $true)]
    [string]$KeycloakAdminPassword,
    [Parameter(Mandatory = $true)]
    [string]$PilotAdminPassword,
    [Parameter(Mandatory = $true)]
    [string]$PilotViewerPassword,
    [string]$PostgresPassword = "rehearsal-postgres-only",
    [string]$ProjectName = "ontology_rehearsal"
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$composeFile = Join-Path $projectRoot "docker-compose.rehearsal.yml"
$env:REHEARSAL_KEYCLOAK_ADMIN_PASSWORD = $KeycloakAdminPassword
$env:REHEARSAL_POSTGRES_PASSWORD = $PostgresPassword
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

$kcadm = "/opt/keycloak/bin/kcadm.sh"
& docker @compose exec -T keycloak $kcadm config credentials --server http://localhost:8080 --realm master --user rehearsal-admin --password $KeycloakAdminPassword | Out-Null
if ($LASTEXITCODE -ne 0) { throw "Could not authenticate to the rehearsal identity provider." }

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
    & docker @compose exec -T keycloak $kcadm update "users/$userId" -r ontology -s enabled=true -s emailVerified=true -s firstName=Pilot -s "lastName=$Role" -s 'requiredActions=[]' | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "Could not complete the profile for $Username." }
    & docker @compose exec -T keycloak $kcadm set-password -r ontology --username $Username --new-password $Password | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "Could not set password for $Username." }
    & docker @compose exec -T keycloak $kcadm add-roles -r ontology --uusername $Username --rolename $Role | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "Could not assign role $Role to $Username." }
}

Ensure-RealmUser "pilot-admin" $PilotAdminPassword "administrator"
Ensure-RealmUser "pilot-viewer" $PilotViewerPassword "viewer"

Write-Output "Production rehearsal is ready."
Write-Output "Application: http://localhost:18000/workspace/command-center"
Write-Output "Identity provider: http://idp.localhost:18080"
Write-Output "Users: pilot-admin (administrator), pilot-viewer (viewer)"

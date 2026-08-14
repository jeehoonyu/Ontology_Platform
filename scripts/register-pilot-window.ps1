# Register the seven-day pilot supervisor so it survives reboots.
#
# This registers `pilot_window.py run` -- one long-lived process -- and NOT a
# repeating `tick`. Task Scheduler's finest granularity is one minute
# (`/SC MINUTE` accepts 1..1439 *minutes*), while the measurement contract fixes
# the probe interval at 30 seconds. A one-minute cadence leaves every second slot
# unwritten, an unwritten slot is unavailable by design, and a perfectly healthy
# deployment then measures about 50% available. Measured: 57.1%.
param(
    [string]$TaskName = "OntologyPilotWindow",
    [string]$EvidenceRoot = "",
    [string]$TokenFile = "",
    [string]$EnvironmentFile = "",
    [string]$PythonPath = "",
    [int]$RestartIntervalMinutes = 5,
    [switch]$Unregister
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot

if ($Unregister) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    Write-Host "Removed scheduled task $TaskName."
    exit 0
}

if (-not $EvidenceRoot) { throw "EvidenceRoot is required." }
if (-not $TokenFile) { throw "TokenFile is required; do not put the recovery token in task arguments." }
if (-not $EnvironmentFile) { throw "EnvironmentFile is required so recovery configuration survives restart." }
if (-not $PythonPath) { $PythonPath = (Get-Command python).Source }
if (-not (Test-Path -LiteralPath $EvidenceRoot)) {
    throw "EvidenceRoot $EvidenceRoot does not exist. Create it and restrict its ACL first."
}
if (-not (Test-Path -LiteralPath $TokenFile -PathType Leaf)) {
    throw "TokenFile $TokenFile does not exist."
}
if (-not (Test-Path -LiteralPath $EnvironmentFile -PathType Leaf)) {
    throw "EnvironmentFile $EnvironmentFile does not exist."
}
$resolvedEvidenceRoot = (Resolve-Path -LiteralPath $EvidenceRoot).Path
$resolvedTokenFile = (Resolve-Path -LiteralPath $TokenFile).Path
$resolvedEnvironmentFile = (Resolve-Path -LiteralPath $EnvironmentFile).Path
$token = (Get-Content -LiteralPath $resolvedTokenFile -Raw).Trim()
if ($token.Length -lt 32 -or $token.Contains("`n") -or $token.Contains("`r")) {
    throw "TokenFile must contain one secret of at least 32 characters."
}

# The secret is never embedded in the task action. Refuse the common broad ACLs
# before handing its path to a startup task.
$broadSids = @("S-1-1-0", "S-1-5-11", "S-1-5-32-545")
foreach ($protectedFile in @($resolvedTokenFile, $resolvedEnvironmentFile)) {
    foreach ($entry in (Get-Acl -LiteralPath $protectedFile).Access) {
        if ($entry.AccessControlType -ne "Allow") { continue }
        try { $sid = $entry.IdentityReference.Translate([System.Security.Principal.SecurityIdentifier]).Value }
        catch { continue }
        if ($sid -in $broadSids) {
            throw "$protectedFile grants access to a broad principal ($($entry.IdentityReference)); restrict its ACL first."
        }
    }
}
$token = $null

$manifest = Join-Path $resolvedEvidenceRoot "pilot-window.json"
if (-not (Test-Path -LiteralPath $manifest)) {
    throw "No open window at $manifest. Run `pilot_window.py preflight` and then `start` first."
}
$observerState = Join-Path $resolvedEvidenceRoot "availability-probe-state.json"
if (-not (Test-Path -LiteralPath $observerState -PathType Leaf)) {
    throw "The availability observer has not written $observerState. Start it before registering the supervisor."
}
$observerAge = ((Get-Date).ToUniversalTime() - (Get-Item -LiteralPath $observerState).LastWriteTimeUtc).TotalSeconds
if ($observerAge -gt 90) {
    throw "The availability observer state is stale ($([int]$observerAge)s old). Repair the observer before registration."
}

$pilotScript = Join-Path $root "oms/pilot_window.py"
& $PythonPath $pilotScript `
    --evidence-root $resolvedEvidenceRoot `
    --environment-file $resolvedEnvironmentFile `
    --token-file $resolvedTokenFile `
    verify-runtime
if ($LASTEXITCODE -ne 0) {
    throw "Persisted pilot runtime verification failed; the task was not registered."
}
$arguments = @(
    ('"{0}"' -f $pilotScript),
    "--evidence-root", ('"{0}"' -f $resolvedEvidenceRoot),
    "--environment-file", ('"{0}"' -f $resolvedEnvironmentFile),
    "--token-file", ('"{0}"' -f $resolvedTokenFile),
    "run"
) -join " "
$action = New-ScheduledTaskAction `
    -Execute $PythonPath `
    -Argument $arguments `
    -WorkingDirectory $root

# At startup, not on a repetition: the supervisor paces its own 30-second ticks.
#
# Two triggers, because one of them does not fire on a workstation. A task
# registered under an interactive account runs only while that account is
# logged on, so the boot trigger passes unfired on a machine sitting at the
# lock screen -- and the window would then lose every slot between the reboot
# and the next login. The logon trigger is the one that actually restarts the
# supervisor here; on a server with a service account the boot trigger is. The
# supervisor refuses to start twice against one evidence root, so registering
# both is safe rather than merely convenient.
#
# Docker must be up before the first tick can reach the source. Docker Desktop
# also starts at logon, so the first few ticks after a reboot may fail while it
# comes up; `run` records those and continues rather than ending the window.
#
# A boot trigger needs administrator rights to register at all -- unelevated,
# Register-ScheduledTask answers "Access is denied" and nothing is installed.
# So the choice is made explicitly and reported, rather than the caller
# discovering after a reboot that no supervisor came back.
$elevated = (New-Object System.Security.Principal.WindowsPrincipal(
    [System.Security.Principal.WindowsIdentity]::GetCurrent()
)).IsInRole([System.Security.Principal.WindowsBuiltInRole]::Administrator)
if ($elevated) {
    $trigger = @(
        (New-ScheduledTaskTrigger -AtStartup),
        (New-ScheduledTaskTrigger -AtLogOn)
    )
    $triggerDescription = "at startup and at logon"
} else {
    $trigger = @((New-ScheduledTaskTrigger -AtLogOn))
    $triggerDescription = "at logon (unelevated; a boot trigger needs administrator rights)"
}

# The supervisor holds a single-writer lock whose heartbeat goes stale after 150
# seconds. Restarting sooner than that makes the replacement refuse the lock, so
# keep the retry interval comfortably past it.
if ($RestartIntervalMinutes -lt 3) {
    throw "RestartIntervalMinutes must be at least 3; the supervisor lock stays warm for 150 seconds."
}
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -DontStopOnIdleEnd `
    -StartWhenAvailable `
    -RestartCount 999 `
    -RestartInterval (New-TimeSpan -Minutes $RestartIntervalMinutes) `
    -ExecutionTimeLimit (New-TimeSpan -Days 8)

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Description "OntologyOS seven-day availability/RPO/RTO pilot supervisor" `
    -Force | Out-Null

Write-Host "Registered $TaskName to run `pilot_window.py run` $triggerDescription."
Write-Host "Start it now with: Start-ScheduledTask -TaskName $TaskName"
Write-Host "Watch it with:     python oms/pilot_window.py --evidence-root `"$resolvedEvidenceRoot`" status"

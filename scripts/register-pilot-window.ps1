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
    [Parameter(Mandatory = $true)][string]$EvidenceRoot,
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

if (-not $PythonPath) { $PythonPath = (Get-Command python).Source }
if (-not (Test-Path -LiteralPath $EvidenceRoot)) {
    throw "EvidenceRoot $EvidenceRoot does not exist. Create it and restrict its ACL first."
}
if (-not $env:PILOT_RECOVERY_TOKEN -or $env:PILOT_RECOVERY_TOKEN.Length -lt 32) {
    throw "Set PILOT_RECOVERY_TOKEN (at least 32 characters) for the account that will run the task."
}

$manifest = Join-Path $EvidenceRoot "pilot-window.json"
if (-not (Test-Path -LiteralPath $manifest)) {
    throw "No open window at $manifest. Run `pilot_window.py preflight` and then `start` first."
}

$action = New-ScheduledTaskAction `
    -Execute $PythonPath `
    -Argument "oms/pilot_window.py run" `
    -WorkingDirectory $root

# At startup, not on a repetition: the supervisor paces its own 30-second ticks.
$trigger = New-ScheduledTaskTrigger -AtStartup

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

Write-Host "Registered $TaskName to run `pilot_window.py run` at startup."
Write-Host "PILOT_EVIDENCE_ROOT must be set to $EvidenceRoot for that account."
Write-Host "Start it now with: Start-ScheduledTask -TaskName $TaskName"
Write-Host "Watch it with:     python oms/pilot_window.py status"

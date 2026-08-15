# Bring the pilot supervisor back after a logon, idempotently.
#
# This exists because the two durable options are unavailable here.
# `Register-ScheduledTask` and `schtasks /Create` both answer "Access is denied"
# on this account, elevated or not, so `register-pilot-window.ps1` cannot
# install anything. A Startup-folder entry needs no privilege and fires at
# logon, which is also when Docker Desktop starts -- so it is the right trigger
# on a workstation regardless.
#
# The first window died to this gap: the supervisor was started from a terminal,
# the terminal went away, and 3h 36m later nothing was ticking. The machine then
# rebooted twice and the observer -- which did have a restart policy -- recorded
# 76,170 seconds of a 604.8-second budget as unavailable.
#
# Safe to run when it is not needed. It exits quietly if no window is open, if
# the window has already closed, or if a supervisor already holds the lock.
param(
    [Parameter(Mandatory = $true)][string]$EvidenceRoot,
    [Parameter(Mandatory = $true)][string]$EnvironmentFile,
    [Parameter(Mandatory = $true)][string]$TokenFile,
    [string]$PythonPath = "",
    [int]$DockerTimeoutSeconds = 600,
    [int]$ReadyTimeoutSeconds = 300
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$home_dir = Split-Path -Parent (Resolve-Path -LiteralPath $EvidenceRoot).Path
$log = Join-Path $home_dir "supervisor-$stamp.log"

function Note([string]$message) {
    $line = "$(Get-Date -Format 's') $message"
    Write-Host $line
    Add-Content -LiteralPath (Join-Path $home_dir "supervisor-launcher.log") -Value $line
}

# `docker` writes progress to stderr as a matter of course, and PowerShell 5.1
# turns a native command's stderr into ErrorRecords -- which, under
# ErrorActionPreference = Stop, terminates the script on a successful `compose
# up`. Redirecting the stream does not help; it is the wrapping that throws. So
# native calls run with Continue and are judged on $LASTEXITCODE, which is the
# only thing that actually reports what the command did.
#
# The arguments arrive as one array rather than as remaining parameters:
# `-f` and `-d` are bound by PowerShell before they ever reach docker
# otherwise, and the function then returns an exit code from something it did
# not run. That is how this first reported `compose up returned 1` while the
# same command returned 0 by hand.
function Invoke-Docker([string[]]$Arguments) {
    $previous = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        & docker @Arguments 2>&1 | Out-String | Out-Null
        return $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $previous
    }
}

if (-not (Test-Path -LiteralPath $EvidenceRoot)) { throw "EvidenceRoot $EvidenceRoot does not exist." }
if (-not (Test-Path -LiteralPath $EnvironmentFile -PathType Leaf)) { throw "EnvironmentFile $EnvironmentFile does not exist." }
if (-not (Test-Path -LiteralPath $TokenFile -PathType Leaf)) { throw "TokenFile $TokenFile does not exist." }
if (-not $PythonPath) { $PythonPath = (Get-Command python).Source }

$manifest = Join-Path $EvidenceRoot "pilot-window.json"
if (-not (Test-Path -LiteralPath $manifest)) {
    Note "No window open at $EvidenceRoot; nothing to supervise."
    exit 0
}
$window = Get-Content -LiteralPath $manifest -Raw | ConvertFrom-Json
$epoch = [int][double]::Parse((Get-Date -UFormat %s))
if ($epoch -ge ($window.started_at + $window.window_seconds)) {
    Note "Window closed at $($window.started_at + $window.window_seconds); run aggregate rather than this."
    exit 0
}

# Docker Desktop starts at logon too, and loses the race about as often as it
# wins it. Every 30-second slot spent waiting here is one the observer will
# score as unavailable, so this waits rather than failing fast -- the budget is
# already spent either way, and coming back late beats not coming back.
Note "Waiting for Docker."
$deadline = (Get-Date).AddSeconds($DockerTimeoutSeconds)
$dockerUp = $false
while ((Get-Date) -lt $deadline) {
    if ((Invoke-Docker @('info')) -eq 0) { $dockerUp = $true; break }
    Start-Sleep -Seconds 5
}
if (-not $dockerUp) { Note "Docker did not start within $DockerTimeoutSeconds s."; exit 1 }

# The pilot containers carry restart: unless-stopped, so Docker normally brings
# them back by itself. This covers the case it cannot: a project that was taken
# down rather than stopped. `up -d` is a no-op when everything already runs.
$token = (Get-Content -LiteralPath $TokenFile -Raw).Trim()
$env:PILOT_RECOVERY_TOKEN = $token
Push-Location $root
try {
    $code = Invoke-Docker @(
        "compose", "--env-file", $EnvironmentFile,
        "-f", "docker-compose.yml", "-f", "docker-compose.pilot-source.local.yml",
        "-p", "ontology_pilot_source", "up", "-d")
    if ($code -ne 0) { Note "compose up returned $code; continuing to the readiness wait." }
} finally {
    Pop-Location
    $env:PILOT_RECOVERY_TOKEN = $null
}

$target = ($window.target)
Note "Waiting for $target to serve."
$deadline = (Get-Date).AddSeconds($ReadyTimeoutSeconds)
$ready = $false
while ((Get-Date) -lt $deadline) {
    try {
        $response = Invoke-WebRequest -Uri "$target/health/ready" -TimeoutSec 5 -UseBasicParsing
        if ($response.StatusCode -eq 200) { $ready = $true; break }
    } catch { }
    Start-Sleep -Seconds 5
}
if (-not $ready) { Note "$target did not serve within $ReadyTimeoutSeconds s; starting anyway so ticks resume." }

# The lock is checked last, and by asking whether its holder still exists rather
# than how recently it was touched.
#
# A drill found this: killing the supervisor and running the launcher five
# seconds later produced "a supervisor is already ticking", because the lock's
# heartbeat was 25 seconds old and the rule was 150. The launcher then exited 0
# having done nothing, which is the exact shape of a morning with no ticks and
# no explanation. The file already carries the holder's pid; asking the
# operating system whether that process is alive is both cheaper and true.
#
# Checked last so that the container recovery above always runs. A supervisor
# can be ticking happily against a stack that is not there -- it records the
# failures and carries on -- so "someone is supervising" is not a reason to skip
# bringing the project back.
$lock = Join-Path $EvidenceRoot "pilot-window-supervisor.lock"
if (Test-Path -LiteralPath $lock) {
    $age = ((Get-Date).ToUniversalTime() - (Get-Item -LiteralPath $lock).LastWriteTimeUtc).TotalSeconds
    $holder = $null
    try {
        $recorded = [int]((Get-Content -LiteralPath $lock -TotalCount 1).Trim())
        $candidate = Get-Process -Id $recorded -ErrorAction SilentlyContinue
        # The name guard matters after a reboot, where the pid may have been
        # handed to something else entirely.
        if ($candidate -and $candidate.ProcessName -like "python*") { $holder = $candidate }
    } catch { }
    if ($holder -and $age -le 150) {
        Note "A supervisor is already ticking (pid $($holder.Id), lock $([int]$age)s old)."
        exit 0
    }
    $why = if ($holder) { "its holder pid $($holder.Id) is alive but the lock is $([int]$age)s stale" }
           else { "no live python holds it" }
    Note "Reclaiming the lock: $why."
    Remove-Item -LiteralPath $lock -Force -ErrorAction SilentlyContinue
}

$arguments = @(
    ('"{0}"' -f (Join-Path $root "oms\pilot_window.py")),
    "--evidence-root", ('"{0}"' -f $EvidenceRoot),
    "--environment-file", ('"{0}"' -f $EnvironmentFile),
    "--token-file", ('"{0}"' -f $TokenFile),
    "run"
) -join " "

# A new log per launch rather than one truncated on every restart. Diagnosing
# the first window's death depended on reading what the supervisor had been
# doing before it stopped, and a truncating redirect would have erased it.
$process = Start-Process -FilePath $PythonPath -ArgumentList $arguments `
    -WorkingDirectory $root -WindowStyle Hidden `
    -RedirectStandardOutput $log -RedirectStandardError "$log.err" -PassThru
Note "Supervisor started as pid $($process.Id), logging to $log"
exit 0

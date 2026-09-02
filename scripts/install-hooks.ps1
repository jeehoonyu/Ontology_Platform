# Install the versioned git hooks into this clone.
#
# Opt-in on purpose. Hooks change what `git push` does on someone's machine, and
# silently installing them from a script that ran for another reason is the kind
# of surprise that gets the whole mechanism turned off.
#
# Why this exists: GOAL_2026-08-13 C1 asks for a CI run that provisions a runner.
# GitHub's annotation on every run since 2026-07-26 says the job was not started
# because account payments failed or the spending limit needs raising -- an
# account setting, not a repository one. Until that is fixed, this hook is what
# makes the enforcement checks run automatically on a push.
param(
    [switch]$Uninstall
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$hooksDirectory = Join-Path $root ".git/hooks"
$source = Join-Path $PSScriptRoot "hooks"

if (-not (Test-Path -LiteralPath $hooksDirectory)) {
    throw "No .git/hooks directory at $hooksDirectory. Is this a git clone?"
}

foreach ($hook in Get-ChildItem -LiteralPath $source -File) {
    $target = Join-Path $hooksDirectory $hook.Name
    if ($Uninstall) {
        if (Test-Path -LiteralPath $target) {
            Remove-Item -LiteralPath $target -Force
            Write-Host "Removed $($hook.Name)"
        }
        continue
    }
    if ((Test-Path -LiteralPath $target) -and -not (Get-Content -LiteralPath $target -Raw).Contains("GOAL_2026-08-13")) {
        # Someone else's hook. Refuse rather than overwrite work this script did
        # not write.
        throw "$target already exists and was not installed from scripts/hooks. Move it aside first."
    }
    Copy-Item -LiteralPath $hook.FullName -Destination $target -Force
    Write-Host "Installed $($hook.Name)"
}

if (-not $Uninstall) {
    Write-Host ""
    Write-Host "pre-push now runs the thirteen static enforcement checks (about 10 seconds)."
    Write-Host "The PostgreSQL, broker and object-store checks stay MANUAL; see"
    Write-Host "oms/check_registry.py for what each needs and how often it should run."
}

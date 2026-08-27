#!/bin/sh
# Install the versioned git hooks into this clone. POSIX twin of
# scripts/install-hooks.ps1, which is PowerShell-only and therefore installed
# nothing on macOS or Linux.
#
# Opt-in on purpose, for the same reason the PowerShell one is: hooks change what
# `git push` does on someone's machine, and silently installing them from a
# script that ran for another reason is the kind of surprise that gets the whole
# mechanism turned off.
#
# The exec bit is the point. Git skips a hook that is not executable and says so
# only as a hint, so a copied-but-unexecutable hook is indistinguishable from a
# passing one -- which is the defect GOAL_2026-08-13 is about, one level down.
# scripts/hooks/pre-push is tracked mode 100755 and this script re-applies it
# after copying, because a checkout with core.fileMode=false can lose it.
#
#   sh scripts/install-hooks.sh              # install
#   sh scripts/install-hooks.sh --uninstall  # remove

set -e

case "${1:-}" in
    --uninstall) uninstall=1 ;;
    "")          uninstall=0 ;;
    *)           echo "usage: sh scripts/install-hooks.sh [--uninstall]" >&2; exit 2 ;;
esac

root=$(cd "$(dirname "$0")/.." && pwd)
source_dir="$root/scripts/hooks"
hooks_dir=$(cd "$root" && git rev-parse --git-path hooks)
case "$hooks_dir" in
    /*) ;;
    *)  hooks_dir="$root/$hooks_dir" ;;
esac

if [ ! -d "$hooks_dir" ]; then
    echo "No hooks directory at $hooks_dir. Is this a git clone?" >&2
    exit 1
fi

for hook in "$source_dir"/*; do
    [ -f "$hook" ] || continue
    name=$(basename "$hook")
    target="$hooks_dir/$name"

    if [ "$uninstall" -eq 1 ]; then
        if [ -e "$target" ]; then
            rm -f "$target"
            echo "Removed $name"
        fi
        continue
    fi

    # Someone else's hook. Refuse rather than overwrite work this script did not
    # write -- same marker the PowerShell installer checks for.
    if [ -e "$target" ] && ! grep -q "GOAL_2026-08-13" "$target" 2>/dev/null; then
        echo "$target already exists and was not installed from scripts/hooks. Move it aside first." >&2
        exit 1
    fi

    cp "$hook" "$target"
    chmod +x "$target"
    echo "Installed $name"
done

if [ "$uninstall" -eq 0 ]; then
    echo
    echo "pre-push now runs the twelve static enforcement checks (about 10 seconds)."
    echo "Two of them import the application, so they need the pinned requirements:"
    echo "  python3 -m venv oms/venv && oms/venv/bin/pip install -r oms/requirements.txt"
    echo "The PostgreSQL, broker and object-store checks stay MANUAL; see"
    echo "oms/check_registry.py for what each needs and how often it should run."
fi

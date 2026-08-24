"""Prove the enforcement hook can actually execute, on a machine that is not Windows.

Condition P0 of GOAL_REPAIR_2026-08-23, and the same defect GOAL_2026-08-13 named
one level down. That goal found the enforcement layer had never run and built this
hook as the reachable substitute. The hook was then unable to run for anyone who
cloned the repository onto macOS or Linux, for two reasons, and both were silent:

  1. `scripts/hooks/pre-push` was tracked mode 100644. Git refuses to execute a
     hook without the exec bit and reports it as a hint, not an error, so a
     correctly-installed hook and a skipped one look identical from the outside.
     Git for Windows runs hooks through sh.exe without consulting the bit, which
     is why this held only on the machine it was written on.
  2. The only installer was `scripts/install-hooks.ps1`. PowerShell.

A test that asserted the hook's *contents* would have passed throughout. So this
file asserts the two properties that decide whether it runs at all -- the tracked
file mode, and an interpreter that exists -- and then that what the hook names
matches what the repository actually has. It reads the index rather than the
working tree, because the working tree can carry a mode that was never committed.
"""
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))

from check_registry import DECLARATIONS  # noqa: E402

HOOK = REPO_ROOT / "scripts" / "hooks" / "pre-push"
POSIX_INSTALLER = REPO_ROOT / "scripts" / "install-hooks.sh"
WINDOWS_INSTALLER = REPO_ROOT / "scripts" / "install-hooks.ps1"

WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
         "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12}

passed = 0


def check(condition, label, payload=None):
    global passed
    assert condition, f"{label}: {payload}"
    passed += 1


def tracked_mode(path: Path) -> str:
    """The mode git has recorded, not the one the filesystem happens to hold."""
    relative = path.relative_to(REPO_ROOT).as_posix()
    output = subprocess.run(
        ["git", "ls-files", "-s", "--", relative],
        cwd=REPO_ROOT, capture_output=True, text=True, check=True,
    ).stdout.strip()
    check(output, f"{relative} is tracked by git", output)
    return output.split()[0]


hook_text = HOOK.read_text(encoding="utf-8")

# --- the two properties that decide whether the hook runs at all ---------------

check(tracked_mode(HOOK) == "100755",
      "the pre-push hook is tracked executable; git skips it silently otherwise",
      tracked_mode(HOOK))

check(POSIX_INSTALLER.exists(),
      "a POSIX installer exists, so the hook is installable off Windows")

check(tracked_mode(POSIX_INSTALLER) == "100755",
      "the POSIX installer is itself tracked executable",
      tracked_mode(POSIX_INSTALLER))

# `python` is not a command on a stock macOS or a modern Linux. A hook whose only
# interpreter is `python` dies on its first check with "command not found", which
# reads as a broken hook rather than a missing interpreter.
check("python3" in hook_text,
      "the hook can find an interpreter on a system with no bare `python`")

check(re.search(r"oms/venv|\.venv", hook_text),
      "the hook prefers the repository venv, which is the only interpreter "
      "carrying the pinned requirements the importing checks need")

# --- what the hook names must exist, and be declared --------------------------

named = re.findall(r"\b((?:audit|validate)_[a-z_]+)\b", hook_text)
# The interpreter-discovery comment block names no checks; only the `checks=`
# assignment does, and every name in it has to resolve to a script.
in_list = re.search(r"^checks=\"(?P<names>[^\"]+)\"", hook_text, re.M)
check(in_list, "the hook declares its checks in one parseable list")
hook_checks = in_list.group("names").split()

check(len(hook_checks) >= 9,
      "the hook still runs the static checks it was built for", len(hook_checks))

for name in hook_checks:
    check((REPO_ROOT / "oms" / f"{name}.py").exists(),
          f"{name} named by the hook exists as a script")
    check(name in DECLARATIONS,
          f"{name} is declared in check_registry, so a reader can learn what it gates")
    check(DECLARATIONS[name].get("cadence") == "every push",
          f"{name} runs on every push and says so", DECLARATIONS[name].get("cadence"))

check(set(named) >= set(hook_checks),
      "every check in the list is discoverable by the same pattern iteration_state "
      "uses to compare declarations against this hook")

# --- the installers must not describe a hook that no longer exists ------------

for installer in (POSIX_INSTALLER, WINDOWS_INSTALLER):
    text = installer.read_text(encoding="utf-8")
    stated = re.search(r"runs the (\w+) static enforcement checks", text)
    check(stated, f"{installer.name} says how many checks the hook runs", text[:80])
    check(WORDS.get(stated.group(1)) == len(hook_checks),
          f"{installer.name} states the number of checks the hook actually runs",
          f"says {stated.group(1)}, hook runs {len(hook_checks)}")

print(f"Hook installability verified: {passed} assertions passed "
      f"({len(hook_checks)} checks named, tracked mode 100755).")

"""Count how many ways this interface says "there is nothing here", and ratchet it.

The finding that opened J1 was that seven workspaces used neither `LoadingState`
nor `EmptyState`, and it was described as those screens not handling their empty
and loading states. That was wrong, and measuring properly is what showed it:
all seven handle every state. What they use is a bare `<div className="empty">`,
and far from being a deviation it is the app's **most common** treatment -- 42
sites against a handful for the `EmptyState` card.

So the defect was never a missing state. It was that of the two treatments only
one had a component, so only one could be counted, changed in a single place, or
kept consistent. The other was 42 copies of the same three lines.

`EmptyState` now renders both, `inline` producing the bare form byte for byte, so
a migration cannot change what a user sees. This gate counts what has not been
migrated yet and refuses to let it grow.

  - *Gated:* raw `className="empty"` sites outside the component. The number may
    fall and must never rise. A new screen writing the div by hand is how 42
    copies happened.
  - *Gated:* a new distinct empty-state class appearing. Three specialised ones
    are declared with reasons -- they carry status-dependent text or an action
    button, which the generic form cannot express. A fourth needs a reason too.
  - *Reported:* which files still hold raw sites, and how many each.

This is deliberately not a rule about which treatment a screen should use. Both
are legitimate and they look different on purpose; what is not legitimate is a
third, fourth and fifth copy of either appearing because there was nothing to
notice.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Tuple

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))

FRONTEND_SRC = REPO_ROOT / "frontend" / "src"
BASELINE = REPO_ROOT / "docs" / "ui-states-baseline.json"

_RAW_EMPTY = re.compile(r'className="(empty(?: compact)?)"')
_EMPTY_CLASS = re.compile(r'className="([a-z-]*empty[a-z-]*)"')

# Specialised treatments that earn their existence. Each says what the generic
# form cannot express; a class not on this list and not the bare form is new.
DECLARED = {
    "empty": "the bare form, rendered by EmptyState inline",
    "empty compact": "the bare form at reduced spacing",
    "empty-state-card": "the EmptyState card, with a title and an optional action",
    "health-empty": "text that changes with health status: 'No active findings' when a run "
                    "passed, 'Run a health check' when none has happened",
    "package-empty-state": "carries a button that creates the organization and project "
                           "governed publishing requires",
    "agent-runtime-empty": "sits inside the agent runtime panel's own grid layout",
    "review-empty": "a paragraph inside the review thread, where a card would break the "
                    "comment flow",
    "inspector-empty": "the inspector rail's prompt to select a node, with an icon the "
                       "generic form has no slot for",
    "visual-builder-empty": "a layout wrapper *around* EmptyState rather than a competing "
                            "treatment -- it adds the button beneath the card",
}

# Three of these were found by this gate on its first run, not by the reading that
# preceded it. Seven treatments existed where five had been counted, which is the
# same lesson as everywhere else here: a number nobody computes is a number nobody
# has.


def scan() -> Tuple[Counter, Dict[str, int]]:
    """Raw sites per file, and every empty-ish class name in use."""
    per_file: Dict[str, int] = {}
    classes: Counter = Counter()
    for path in sorted(FRONTEND_SRC.rglob("*.tsx")):
        text = path.read_text(encoding="utf-8")
        raw = len(_RAW_EMPTY.findall(text))
        if raw:
            per_file[str(path.relative_to(FRONTEND_SRC)).replace("\\", "/")] = raw
        for name in _EMPTY_CLASS.findall(text):
            classes[name] += 1
    return classes, per_file


def compare(classes: Counter, per_file: Dict[str, int],
            baseline: Dict[str, Any]) -> Tuple[bool, List[str], List[str]]:
    failures: List[str] = []
    notes: List[str] = []

    raw_total = sum(per_file.values())
    ceiling = baseline.get("raw_empty_ceiling")
    if ceiling is not None:
        if raw_total > ceiling:
            failures.append(
                f'{raw_total} raw className="empty" site(s), above the ceiling of {ceiling}. '
                f"Use <EmptyState inline> -- it renders the identical markup, and a hand-written "
                f"copy is invisible to every count.")
        elif raw_total < ceiling:
            notes.append(f"raw sites: {ceiling} -> {raw_total} -- re-run with --set-baseline "
                         f"to lock the improvement in")

    undeclared = sorted(name for name in classes if name not in DECLARED)
    if undeclared:
        failures.append(
            f"empty-state treatment(s) with no declared reason: {', '.join(undeclared)}. "
            f"Add the reason to DECLARED, or use an existing treatment.")

    return not failures, failures, notes


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--set-baseline", action="store_true")
    args = parser.parse_args()

    if not FRONTEND_SRC.exists():
        print(f"No frontend source at {FRONTEND_SRC}")
        return 1

    classes, per_file = scan()
    raw_total = sum(per_file.values())

    print(f"{len(classes)} empty-state treatment(s) in use, {raw_total} raw site(s)\n")
    print(f"  {'treatment':<24}{'uses':>6}  reason")
    for name, count in classes.most_common():
        print(f"  {name:<24}{count:>6}  {DECLARED.get(name, '** undeclared **')[:60]}")

    if per_file:
        print(f"\nfiles still writing the div by hand:")
        for name, count in sorted(per_file.items(), key=lambda item: -item[1])[:12]:
            print(f"  {count:>3}  {name}")

    if args.set_baseline:
        BASELINE.write_text(json.dumps({
            "note": ("Raw className=\"empty\" sites not yet routed through EmptyState. "
                     "May fall, must never rise."),
            "raw_empty_ceiling": raw_total,
        }, indent=2) + "\n", encoding="utf-8")
        print(f"\nBaseline set: {raw_total} raw site(s).")
        return 0

    if not BASELINE.exists():
        print(f"\nNo baseline at {BASELINE.relative_to(REPO_ROOT)}. Record one with --set-baseline.")
        return 1

    baseline = json.loads(BASELINE.read_text(encoding="utf-8"))
    ok, failures, notes = compare(classes, per_file, baseline)
    for note in notes:
        print(f"\n  {note}")
    if failures:
        print(f"\nFAIL -- {len(failures)} problem(s):")
        for failure in failures:
            print(f"  {failure}")
        return 1
    print(f"\nEvery empty-state treatment is declared, and no new one was written by hand.")
    return 0


if __name__ == "__main__":
    from enforcement_runs import recording

    raise SystemExit(recording("audit_ui_states", main))

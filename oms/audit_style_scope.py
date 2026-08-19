"""Which stylesheet classes are shared, and refuse a new sharing nobody declared.

J2 asked that a change to one screen cannot silently restyle another, and asked
for the measurement first, because the answer decides the shape of the work. The
measurement is lopsided enough to settle it:

    358 classes in one 6,233-line stylesheet
    297  used by exactly one file        (83%)
     33  used by two or more             -- the design system, undeclared
     28  in no className literal         -- 16 of them built dynamically

The 297 are single-screen styles living in a global namespace, and scoping them
would mean rewriting class usage at hundreds of sites across twenty-two files,
verified by a render sweep that checks overflow and contrast rather than layout.
That is a large, risky change for a coupling that is mostly theoretical: a class
one file uses cannot restyle another file.

The 33 are the coupling, and they are the design system in disguise -- `.button-row`
across twenty files, `.empty` across thirteen, `.two-col`, `.metrics`, `.grid`,
`.table-wrap`. Those are worth having and worth naming.

So this does not scope the stylesheet. It records who shares what, and gates the
moment the set grows:

  - *Gated:* a class used by one file that gains a second user. That is exactly
    the event J2 describes -- a screen borrowing another screen's style, after
    which a change to either silently moves both. Declaring it shared is a
    one-line edit; doing it by accident is what this refuses.
  - *Gated:* a class in the shared set that disappears from the stylesheet while
    files still use it.
  - *Reported:* the totals, the most-shared classes, and the ones no literal
    mentions.

Deleting the unused is deliberately not gated. Sixteen of the twenty-eight are
assembled at runtime -- `context-action-${kind}` and the like -- so "no literal
mentions it" is not "nothing uses it", and a gate that cannot tell those apart
would push someone to delete a live style.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Set, Tuple

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))

FRONTEND_SRC = REPO_ROOT / "frontend" / "src"
STYLESHEET = FRONTEND_SRC / "styles.css"
BASELINE = REPO_ROOT / "docs" / "style-scope-baseline.json"

_DEFINED = re.compile(r"^\.([a-zA-Z0-9_-]+)", re.M)
_CLASSNAME = re.compile(r'className="([^"]*)"')


def scan() -> Tuple[Set[str], Dict[str, List[str]], Set[str]]:
    """(classes defined, class -> files using it, classes no literal mentions)."""
    if not STYLESHEET.exists():
        return set(), {}, set()
    defined = set(_DEFINED.findall(STYLESHEET.read_text(encoding="utf-8")))
    users: Dict[str, Set[str]] = {}
    literal = set()
    for path in sorted(FRONTEND_SRC.rglob("*.tsx")):
        text = path.read_text(encoding="utf-8")
        label = str(path.relative_to(FRONTEND_SRC)).replace("\\", "/")
        for value in _CLASSNAME.findall(text):
            for token in value.split():
                literal.add(token)
                if token in defined:
                    users.setdefault(token, set()).add(label)
    return defined, {k: sorted(v) for k, v in users.items()}, defined - literal


def shared_of(users: Dict[str, List[str]]) -> Dict[str, List[str]]:
    return {name: files for name, files in users.items() if len(files) > 1}


def compare(defined: Set[str], users: Dict[str, List[str]],
            baseline: Dict[str, Any]) -> Tuple[bool, List[str], List[str]]:
    failures: List[str] = []
    notes: List[str] = []
    recorded: Dict[str, List[str]] = baseline.get("shared", {})
    shared = shared_of(users)

    for name, files in sorted(shared.items()):
        if name not in recorded:
            failures.append(
                f".{name} is now used by {len(files)} files ({', '.join(files[:3])}"
                f"{'…' if len(files) > 3 else ''}) and was used by one. A change to it now "
                f"moves every one of them. Declare it shared in the baseline, or give the "
                f"second screen its own class.")
        elif len(files) != len(recorded[name]):
            notes.append(f".{name}: {len(recorded[name])} -> {len(files)} files")

    for name in sorted(recorded):
        if name not in defined:
            failures.append(f".{name} is recorded as shared by {len(recorded[name])} files and "
                            f"is no longer defined in the stylesheet")
        elif name not in shared:
            notes.append(f".{name}: no longer shared -- re-run with --set-baseline")
    return not failures, failures, notes


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--set-baseline", action="store_true")
    args = parser.parse_args()

    if not STYLESHEET.exists():
        print(f"No stylesheet at {STYLESHEET}")
        return 1

    defined, users, unlisted = scan()
    shared = shared_of(users)
    single = sum(1 for files in users.values() if len(files) == 1)

    print(f"{len(defined)} classes defined; {single} used by one file, {len(shared)} shared, "
          f"{len(unlisted)} in no className literal\n")
    print("  most shared:")
    for name, files in sorted(shared.items(), key=lambda item: -len(item[1]))[:8]:
        print(f"    {len(files):>3} files  .{name}")

    if args.set_baseline:
        BASELINE.write_text(json.dumps({
            "provenance": {"stale_after": "recomputed each run"},
            "note": ("Classes used by more than one file. Growing this set couples screens, "
                     "so a new entry is an edit someone makes on purpose."),
            "single_file_classes": single,
            "shared": {k: v for k, v in sorted(shared.items())},
        }, indent=2) + "\n", encoding="utf-8")
        print(f"\nBaseline set: {len(shared)} shared class(es).")
        return 0

    if not BASELINE.exists():
        print(f"\nNo baseline at {BASELINE.relative_to(REPO_ROOT)}. Record one with "
              f"--set-baseline.")
        return 1

    ok, failures, notes = compare(defined, users,
                                  json.loads(BASELINE.read_text(encoding="utf-8")))
    if notes:
        print(f"\n{len(notes)} change(s), none of them gated:")
        for note in notes[:15]:
            print(f"  {note}")
    if failures:
        print(f"\nFAIL -- {len(failures)}:")
        for failure in failures:
            print(f"  {failure}")
        return 1
    print(f"\nNo class became shared without being declared. {len(shared)} class(es) couple "
          f"more than one screen; the other {single} cannot.")
    return 0


if __name__ == "__main__":
    from enforcement_runs import recording

    raise SystemExit(recording("audit_style_scope", main))

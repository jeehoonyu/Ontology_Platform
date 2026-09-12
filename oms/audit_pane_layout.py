"""Which panes a person can move, and a count that may only go up.

M1 of `GOAL_PANES_2026-09-11.md`, written before any pane is made movable,
because the number it produces decides the shape of the rest.

The ask was panes that move around and are easily movable. The code's answer is
that **not one pane on any screen can be moved, resized, collapsed, docked or
hidden by the person using it.** Every one is a fixed CSS grid track decided at
build time. The only layout anybody can change and keep is node positions on the
platform graph, in `localStorage` under `ontology.platformGraph.layout`; that is
the precedent for persistence and the whole of it.

**What counts as a pane here, and what deliberately does not.** A pane region is
a literal `<aside>`, or a `<section>` carrying `aria-label`/`aria-labelledby`,
written in a screen. Those are the layout regions -- a rail, a library, an
inspector, a drawer. `<Panel>` usages are *not* counted, though `Panel` renders a
labelled `<section>` at runtime: there are dozens of them, they are content
inside a region rather than regions themselves, and counting them would bury the
fourteen-to-twenty things this is actually about under a number nobody could act
on. Dialogs are excluded too -- `role="dialog"` and `aria-modal` are a different
interaction with different rules.

  - *Reported:* every region, its screen, and whether it is movable or resizable.
  - *Gated:* the movable count falling, in total or on any one screen. This is a
    ratchet in the opposite direction from most here: the number starts at zero
    and must climb.
  - *Gated:* a screen that already uses `Pane` growing a new raw region. Mixing a
    movable pane and a fixed track on one screen is how a layout becomes
    half-rearrangeable, which is worse than neither.
  - *Gated:* the checked-in reference disagreeing with the source.

  python oms/audit_pane_layout.py            # judge
  python oms/audit_pane_layout.py --write    # regenerate the reference
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))

FRONTEND_SRC = REPO_ROOT / "frontend" / "src"
REFERENCE = REPO_ROOT / "docs" / "PANE_LAYOUT.md"
BASELINE = REPO_ROOT / "docs" / "pane-layout-baseline.json"

# The primitives themselves render labelled sections; they are what panes are
# made of, not panes on a screen. `Pane.tsx` renders `<Pane>` twice inside
# `PaneHost`, so counting elements rather than declarations made the primitive
# read as the most rearrangeable screen in the product.
PRIMITIVES = ("components/data/DataDisplay.tsx", "components/layout/Pane.tsx")
PRIMITIVE = PRIMITIVES[0]

_ASIDE = re.compile(r"<aside\b([^>]*)>", re.S)
_SECTION = re.compile(r"<section\b([^>]*)>", re.S)
_HOST = re.compile(r"<PaneHost\b")
# A screen declares its panes as `PaneSpec` entries, and that declaration is what
# makes a pane movable -- not the element the host renders from it.
_SPEC = re.compile(r'id:\s*"([a-z0-9_-]+)"\s*,\s*title:[^}]*?slot:\s*"(?:left|center|right|bottom)"')
_CLASSNAME = re.compile(r'className=\{?"([^"]*)"')
_LABEL = re.compile(r'aria-label(?:ledby)?=')
_DIALOG = re.compile(r'role="dialog"|aria-modal')
_SPLITTER = re.compile(r'role="separator"|pane-splitter')
# The className expression is often `classNames("a", flag && "b")`; take the
# first literal, which is the region's own name.
_FIRST_LITERAL = re.compile(r'"([a-z][a-z0-9-]*)"')


def _name_of(attributes: str) -> str:
    literal = _CLASSNAME.search(attributes)
    if literal:
        return literal.group(1).split()[0]
    inner = _FIRST_LITERAL.search(attributes)
    return inner.group(1) if inner else "(unnamed)"


def scan() -> Dict[str, Any]:
    """Pane regions by screen, and which of them a person can move."""
    screens: Dict[str, Dict[str, Any]] = {}

    for path in sorted(FRONTEND_SRC.rglob("*.tsx")):
        label = str(path.relative_to(FRONTEND_SRC)).replace("\\", "/")
        if label in PRIMITIVES:
            continue
        text = path.read_text(encoding="utf-8")

        fixed: List[str] = []
        for attributes in _ASIDE.findall(text):
            fixed.append(_name_of(attributes))
        for attributes in _SECTION.findall(text):
            if _LABEL.search(attributes) and not _DIALOG.search(attributes):
                fixed.append(_name_of(attributes))
        movable = sorted(_SPEC.findall(text)) if _HOST.search(text) else []

        if not fixed and not movable:
            continue
        screens[label] = {
            "fixed": sorted(fixed),
            "movable": sorted(movable),
            # A screen on `PaneHost` is resizable because the host draws the
            # splitters -- in `Pane.tsx`, which is skipped as a primitive. Looking
            # for the splitter in the screen's own file reported "0 screen(s) offer
            # a splitter" from M3, when the pipeline builder had one, until M7
            # noticed the reference contradicting a screen it could see.
            "resizable": bool(_SPLITTER.search(text) or _HOST.search(text)),
        }
    return screens


def totals(screens: Dict[str, Any]) -> Tuple[int, int, int]:
    regions = sum(len(s["fixed"]) + len(s["movable"]) for s in screens.values())
    movable = sum(len(s["movable"]) for s in screens.values())
    resizable = sum(1 for s in screens.values() if s["resizable"])
    return regions, movable, resizable


def render(screens: Dict[str, Any]) -> str:
    regions, movable, resizable = totals(screens)
    lines = [
        "# Panes, and which of them move",
        "",
        "Generated by `oms/audit_pane_layout.py`. Do not edit by hand — the gate",
        "regenerates this and fails if it disagrees with the source.",
        "",
        f"**{movable} of {regions}** pane regions can be moved by the person using them;",
        f"{resizable} screen(s) offer a splitter. A pane region is a literal `<aside>`, or a",
        "`<section>` carrying an accessible name. `<Panel>` usages are content inside a",
        "region rather than regions themselves and are not counted; dialogs are a different",
        "interaction and are excluded.",
        "",
        "| Screen | Movable | Fixed track | Resizable |",
        "| --- | --- | --- | --- |",
    ]
    for screen, entry in sorted(screens.items()):
        lines.append(
            f"| `{screen}` | {', '.join(f'`{n}`' for n in entry['movable']) or '—'} "
            f"| {', '.join(f'`{n}`' for n in entry['fixed']) or '—'} "
            f"| {'yes' if entry['resizable'] else 'no'} |")
    lines.append("")
    return "\n".join(lines)


def compare(screens: Dict[str, Any],
            baseline: Dict[str, Any]) -> Tuple[bool, List[str], List[str]]:
    failures: List[str] = []
    notes: List[str] = []
    recorded: Dict[str, Any] = baseline.get("screens", {})
    _, movable, _ = totals(screens)
    floor = baseline.get("movable", 0)

    if movable < floor:
        failures.append(
            f"{movable} movable pane(s), down from {floor}. This ratchet runs the other "
            f"way: a pane that stopped being movable is a person's layout taken away.")
    elif movable > floor:
        notes.append(f"movable panes {floor} -> {movable}; re-run with --set-baseline")

    for screen, entry in sorted(screens.items()):
        was = recorded.get(screen, {})
        if len(entry["movable"]) < len(was.get("movable", [])):
            failures.append(f"{screen}: {len(was['movable'])} -> {len(entry['movable'])} "
                            f"movable pane(s)")
        # A screen part-way onto `Pane` is the worst of both: some panes move and
        # some do not, and nothing on screen says which.
        if entry["movable"] and entry["fixed"]:
            added = sorted(set(entry["fixed"]) - set(was.get("fixed", [])))
            if added:
                failures.append(
                    f"{screen} already uses `Pane` and grew a fixed-track region: "
                    f"{', '.join(added)}. Half a rearrangeable layout is worse than none; "
                    f"put it in a `Pane` or take the screen back off `Pane`.")

    for screen in sorted(recorded):
        if screen not in screens:
            notes.append(f"{screen}: no longer has pane regions")

    if not REFERENCE.exists():
        failures.append(f"{REFERENCE.relative_to(REPO_ROOT)} is missing; regenerate with --write")
    elif REFERENCE.read_text(encoding="utf-8") != render(screens):
        failures.append(f"{REFERENCE.relative_to(REPO_ROOT)} disagrees with the source. "
                        f"Regenerate it: python oms/audit_pane_layout.py --write")
    return not failures, failures, notes


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true", help="Regenerate the reference")
    parser.add_argument("--set-baseline", action="store_true")
    args = parser.parse_args()

    if not FRONTEND_SRC.exists():
        print(f"No frontend source at {FRONTEND_SRC}")
        return 1

    screens = scan()
    regions, movable, resizable = totals(screens)
    print(f"{regions} pane region(s) across {len(screens)} screen(s): {movable} movable, "
          f"{resizable} screen(s) resizable\n")
    for screen, entry in sorted(screens.items(), key=lambda i: -len(i[1]["fixed"]))[:8]:
        print(f"  {len(entry['movable']):>2} movable  {len(entry['fixed']):>2} fixed  {screen}")

    if args.write:
        REFERENCE.write_text(render(screens), encoding="utf-8")
        print(f"\nWrote {REFERENCE.relative_to(REPO_ROOT)} ({regions} regions).")
        return 0

    if args.set_baseline:
        BASELINE.write_text(json.dumps({
            "provenance": {"stale_after": "recomputed each run"},
            "note": ("Pane regions per screen, and how many a person can move. The movable "
                     "count is a floor, not a ceiling: it may rise and must never fall."),
            "regions": regions,
            "movable": movable,
            "screens": {k: v for k, v in sorted(screens.items())},
        }, indent=2) + "\n", encoding="utf-8")
        print(f"\nBaseline set: {movable} movable of {regions}.")
        return 0

    if not BASELINE.exists():
        print(f"\nNo baseline at {BASELINE.relative_to(REPO_ROOT)}. Record one with "
              f"--set-baseline.")
        return 1

    ok, failures, notes = compare(screens, json.loads(BASELINE.read_text(encoding="utf-8")))
    if notes:
        print(f"\n{len(notes)} change(s), none of them gated:")
        for note in notes[:12]:
            print(f"  {note}")
    if failures:
        print(f"\nFAIL -- {len(failures)}:")
        for failure in failures:
            print(f"  {failure}")
        return 1
    print(f"\nNo screen lost a movable pane, and no screen mixes `Pane` with a new fixed "
          f"track. {movable} of {regions} regions move.")
    return 0


if __name__ == "__main__":
    from enforcement_runs import recording

    raise SystemExit(recording("audit_pane_layout", main))

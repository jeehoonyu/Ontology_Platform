"""Controls that look like controls and do nothing, and a count that may only fall.

N1 of `GOAL_HONEST_UI_2026-09-11.md`, written before a single handler is added,
because the number decides how much of the interface is making a promise it does
not keep.

The platform review that prompted this asked for one outcome in particular:
*all visible toolbar buttons work or explain why unavailable; there are no
decorative action controls.* That is a claim about every screen at once, so it
needs a census rather than a reading. This is the census.

**A control here is a literal `<button>` or `<a>` written in a `.tsx` file.** It
is *wired* if its opening tag carries any of:

    onClick onPointerDown onMouseDown onKeyDown onSubmit onChange
    type="submit"        -- a form's own default action
    href=                -- a link goes somewhere by existing
    {...}                -- a spread, which is how `DragHandle` receives
                            dnd-kit's listeners and how forwarded props arrive
    disabled             -- a control that says it is unavailable is not lying

Anything else is **inert**: it renders as a control, it takes a hover, a focus
ring and a click, and nothing happens. A person cannot tell it apart from a
control that is merely slow.

Two things this scan does that a grep would not:

  - *A tag inside a `.map()` renders many times.* React requires `key=` on such
    an element, so `key=` is the marker, and the census reports repeated sites
    separately. Five source lines were producing far more than five dead
    controls on screen.
  - *An empty handler counts as inert.* `onClick={() => {}}` satisfies every
    pattern above and changes nothing, so it is the exact shape this gate would
    invite if it did not refuse it. Silencing a gate with a no-op is worse than
    the thing the gate was watching for, because the census then reports a
    number that is wrong rather than a number that is bad.

  - *Reported:* every control site, its file, and whether it repeats.
  - *Gated:* the inert count rising, in total or in any one file.
  - *Gated:* a file with no inert control today growing one.
  - *Gated:* the checked-in reference disagreeing with the source.

  python oms/audit_inert_controls.py            # judge
  python oms/audit_inert_controls.py --write    # regenerate the reference
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
REFERENCE = REPO_ROOT / "docs" / "INERT_CONTROLS.md"
BASELINE = REPO_ROOT / "docs" / "inert-controls-baseline.json"

# An opening tag cannot be found by a regex, and the first version of this file
# tried. `<button onClick={() => run()}>` contains a `>` inside the arrow, so
# `<(button|a)[^<>]*?>` ends the tag at `onClick={() =` -- which left the label
# wrong on every handler-bearing control and made the empty-handler rule below
# unreachable, since it could never see a body it had already been cut off from.
# The test file caught it by asserting the empty-handler case is refused.
# `_OPEN` finds the start; `_tags` walks forward counting braces and quotes.
_OPEN = re.compile(r"<(button|a)(?=[\s/>])")


def _tags(text: str):
    """Yield `(start, tag, attributes)` for every `<button>`/`<a>` opening tag."""
    for opener in _OPEN.finditer(text):
        index, depth, quote = opener.end(), 0, ""
        while index < len(text):
            character = text[index]
            if quote:
                if character == quote:
                    quote = ""
            elif character in "\"'":
                quote = character
            elif character == "{":
                depth += 1
            elif character == "}":
                depth -= 1
            elif character == ">" and depth == 0:
                yield opener.start(), index + 1, opener.group(1), \
                    text[opener.end():index].rstrip("/")
                break
            index += 1

# What makes a control do something. `disabled` is here on purpose: the review's
# criterion is "work or explain why unavailable", and a disabled control is the
# explanation.
_WIRED = re.compile(
    r"\bonClick\b|\bonPointerDown\b|\bonMouseDown\b|\bonKeyDown\b|\bonSubmit\b"
    r"|\bonChange\b|type=[\"']submit[\"']|\bhref=|\{\.\.\.|\bdisabled\b")

# A handler whose body is empty. `onClick={() => {}}`, `onClick={()=>{ }}`,
# `onClick={() => undefined}`, `onClick={noop}`.
_NOOP = re.compile(
    r"on[A-Z]\w+=\{\s*(?:\([^)]*\)|\w+)\s*=>\s*(?:\{\s*\}|undefined|null|void 0)\s*\}"
    r"|on[A-Z]\w+=\{\s*noop\s*\}")

# React needs a key on an element produced by a list, so a key means the site
# renders once per item rather than once.
_KEYED = re.compile(r"\bkey=")

# The name a reader would use for the control. Its text content, if the tag is
# immediately followed by a literal; else its title, aria-label or className.
_TITLE = re.compile(r"(?:title|aria-label)=\"([^\"]{1,40})\"")
_CLASS = re.compile(r"className=\{?\"([a-z][a-z0-9 -]*)\"")


def _label_of(attributes: str, following: str) -> str:
    text = following.lstrip()
    if text[:1] not in ("<", "{", ""):
        literal = text.split("<")[0].strip()
        if literal and len(literal) <= 40:
            return literal
    for pattern in (_TITLE, _CLASS):
        found = pattern.search(attributes)
        if found:
            return found.group(1)
    # A control whose text is an expression -- `{action}`, `{tab}` -- which is
    # the usual shape inside a `.map()`, and exactly the shape whose label
    # matters most because one line draws many buttons.
    expression = re.match(r"\s*\{([^{}]{1,44})\}", following)
    return f"{{{expression.group(1).strip()}}}" if expression else "(unlabelled)"


def scan() -> Dict[str, Any]:
    """Every `<button>` and `<a>` in the frontend, and which of them do nothing."""
    files: Dict[str, Dict[str, Any]] = {}
    total = 0

    for path in sorted(FRONTEND_SRC.rglob("*.tsx")):
        label = str(path.relative_to(FRONTEND_SRC)).replace("\\", "/")
        text = path.read_text(encoding="utf-8")
        inert: List[Dict[str, Any]] = []
        controls = 0

        for start, end, tag, attributes in _tags(text):
            controls += 1
            total += 1
            if _WIRED.search(attributes) and not _NOOP.search(attributes):
                continue
            inert.append({
                "line": text[:start].count("\n") + 1,
                "tag": tag,
                "label": _label_of(attributes, text[end:end + 80]),
                "repeats": bool(_KEYED.search(attributes)),
                "noop": bool(_NOOP.search(attributes)),
            })

        if controls:
            files[label] = {"controls": controls, "inert": inert}
    return {"files": files, "controls": total}


def totals(found: Dict[str, Any]) -> Tuple[int, int, int]:
    inert = sum(len(f["inert"]) for f in found["files"].values())
    repeated = sum(1 for f in found["files"].values() for i in f["inert"] if i["repeats"])
    return found["controls"], inert, repeated


def render(found: Dict[str, Any]) -> str:
    controls, inert, repeated = totals(found)
    lines = [
        "# Controls that do nothing",
        "",
        "Generated by `oms/audit_inert_controls.py`. Do not edit by hand — the gate",
        "regenerates this and fails if it disagrees with the source.",
        "",
        f"**{inert} of {controls}** `<button>` and `<a>` elements in the frontend carry no",
        "way to act: no handler, no `href`, no `type=\"submit\"`, no spread that could",
        f"supply one, and no `disabled` to say they are unavailable. {repeated} of the {inert}",
        "sit inside a list and render once per item, so the count a person meets on screen",
        "is higher than the count of source lines below.",
        "",
        "A control that renders a hover state, takes focus and accepts a click while doing",
        "nothing is indistinguishable from one that is broken or slow. That is the defect",
        "being counted, not the missing feature behind it.",
        "",
    ]
    if inert:
        lines += ["| File | Line | Control | Renders |", "| --- | --- | --- | --- |"]
        for name, entry in sorted(found["files"].items()):
            for site in entry["inert"]:
                note = "once per item" if site["repeats"] else "once"
                if site["noop"]:
                    note += ", empty handler"
                lines.append(f"| `{name}` | {site['line']} | "
                             f"`<{site['tag']}>` {site['label']} | {note} |")
    else:
        lines.append("No inert control remains. Every control acts, links, submits, or says")
        lines.append("it is unavailable.")
    lines.append("")
    return "\n".join(lines)


def compare(found: Dict[str, Any],
            baseline: Dict[str, Any]) -> Tuple[bool, List[str], List[str]]:
    failures: List[str] = []
    notes: List[str] = []
    _, inert, _ = totals(found)
    ceiling = baseline.get("inert")
    recorded: Dict[str, int] = baseline.get("per_file", {})

    if ceiling is None:
        failures.append("the baseline records no inert count; re-run with --set-baseline")
    elif inert > ceiling:
        failures.append(
            f"{inert} inert control(s), up from {ceiling}. A control that renders and does "
            f"nothing is a promise the code does not keep; wire it, link it, disable it "
            f"with a reason, or do not draw it.")
    elif inert < ceiling:
        notes.append(f"inert controls {ceiling} -> {inert}; re-run with --set-baseline")

    for name, entry in sorted(found["files"].items()):
        was = recorded.get(name, 0)
        now = len(entry["inert"])
        if now > was:
            failures.append(
                f"{name}: {was} -> {now} inert control(s)"
                + ("" if was else " — this file had none"))

    noops = [(name, site["line"]) for name, entry in sorted(found["files"].items())
             for site in entry["inert"] if site["noop"]]
    if noops:
        failures.append(
            "an empty handler is not a wired control: "
            + ", ".join(f"{name}:{line}" for name, line in noops)
            + ". Passing this gate with `() => {}` would make its number wrong rather "
              "than merely high.")

    if not REFERENCE.exists():
        failures.append(f"{REFERENCE.relative_to(REPO_ROOT)} is missing; regenerate with --write")
    elif REFERENCE.read_text(encoding="utf-8") != render(found):
        failures.append(f"{REFERENCE.relative_to(REPO_ROOT)} disagrees with the source. "
                        f"Regenerate it: python oms/audit_inert_controls.py --write")
    return not failures, failures, notes


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true", help="Regenerate the reference")
    parser.add_argument("--set-baseline", action="store_true")
    args = parser.parse_args()

    if not FRONTEND_SRC.exists():
        print(f"No frontend source at {FRONTEND_SRC}")
        return 1

    found = scan()
    controls, inert, repeated = totals(found)
    print(f"{controls} control(s) across {len(found['files'])} file(s): {inert} inert "
          f"({repeated} of them inside a list)\n")
    worst = Counter({n: len(e["inert"]) for n, e in found["files"].items() if e["inert"]})
    for name, count in worst.most_common(8):
        print(f"  {count:>2} inert  {name}")

    if args.write:
        REFERENCE.write_text(render(found), encoding="utf-8")
        print(f"\nWrote {REFERENCE.relative_to(REPO_ROOT)} ({inert} inert).")
        return 0

    if args.set_baseline:
        BASELINE.write_text(json.dumps({
            "provenance": {"stale_after": "recomputed each run"},
            "note": ("`<button>` and `<a>` elements with no way to act. A ceiling, not a "
                     "floor: the count may fall and must never rise."),
            "controls": controls,
            "inert": inert,
            "per_file": {n: len(e["inert"]) for n, e in sorted(found["files"].items())
                         if e["inert"]},
        }, indent=2) + "\n", encoding="utf-8")
        print(f"\nBaseline set: {inert} inert of {controls}.")
        return 0

    if not BASELINE.exists():
        print(f"\nNo baseline at {BASELINE.relative_to(REPO_ROOT)}. Record one with "
              f"--set-baseline.")
        return 1

    ok, failures, notes = compare(found, json.loads(BASELINE.read_text(encoding="utf-8")))
    if notes:
        print(f"\n{len(notes)} change(s), none of them gated:")
        for note in notes[:12]:
            print(f"  {note}")
    if failures:
        print(f"\nFAIL -- {len(failures)}:")
        for failure in failures:
            print(f"  {failure}")
        return 1
    print(f"\nNo file gained a control that does nothing. {inert} of {controls} remain "
          f"inert, and the count may only fall.")
    return 0


if __name__ == "__main__":
    from enforcement_runs import recording

    raise SystemExit(recording("audit_inert_controls", main))

"""Tables that show part of what they were given, and do not say so.

N4 of `GOAL_HONEST_UI_2026-09-11.md`. Written after N3 rather than before it,
unlike its sibling `audit_inert_controls`, because what it refuses is the shape
N3 decided: a table may drop rows or columns, and when it does, the true count
is rendered beside what it kept.

**A truncation here is a collection cut short in a `.tsx` file.** Two spellings:

    xs.slice(a, b)                  -- the one this codebase uses
    xs.filter((x, i) => i < n)      -- the same cut, and the obvious way round
                                       a rule that only knows the first

A `.slice` is a *collection* cut only if what it produces is used as one:
mapped or otherwise consumed, iterated with `for ... of`, handed to a table as
`rows`, or bound to a name that is then one of those. `run.id.slice(0, 8)`
shortens a string for display and is none of them, so it is not counted.

**A truncation reaches a table** when it is written inside one -- between
`<table>` and `</table>`, inside an element with `role="table"` or
`role="grid"`, or among a `<DataTable>`'s props -- or when it is bound to a name
that is, followed through up to four bindings. The binding is how every real
case arrives: `const columns = query.columns.slice(0, 8)` is written well above
the `<table>` that draws `columns.map(...)`.

The first version scoped this to the component instead, and counted Object
Explorer's facet chips and Vertex's seed list as table truncations because
those components also draw a table somewhere else. A table is an element, not
the function that happens to contain one.

**It is accompanied** when the same component renders the length of the
collection that was cut: `{issues.length}`, `{rows.length.toLocaleString()}`,
or `${issues.length}` inside a template. Four refusals are deliberate:

  - *The count of what was kept is not a count.* `const shown = rows.slice(0,
    40)` beside `{shown.length}` renders "40", which is the number the table
    already shows and the one number that cannot say anything is missing. Only
    the length of the source counts.
  - *A length used as a condition is not rendered.* `{issues.length ? ... }`
    decides whether to draw something; it does not tell a person how many.
  - *A slice at the call site is still a slice.* `DataTable` captions its own
    cut, so the cheapest way to make a table silent again is to cut the rows
    before handing them over: the component then receives twenty-five rows,
    shows twenty-five, and truthfully says nothing. That is this gate's
    equivalent of the empty handler in `audit_inert_controls`, and it is what
    the operations feed was already doing when this was written.
  - *A count does not bring back rows the table was never given.* `DataTable`
    and `DataGrid` page whatever they receive, so rows cut on the way in are
    hidden rather than paged, however truthfully the total is written beside
    them: `{issues.length} contract issues` over `rows={issues.slice(0, 25)}`
    names every issue and lets a person read twenty-five. N9 of the goal. The
    N7d census found it, and this gate had listed that site as counted. A cut
    into a paging table is silent whether or not its total is rendered. A
    counted cut into a plain `<table>` or a `role="table"` element, neither of
    which pages, is still accompanied.

What this does not see, stated rather than implied:

  - a cut made in a `.ts` helper and returned (the census found none);
  - a cut passed down to a child component declared in another file;
  - a limit applied by the server, which is paging and is N5;
  - a total from a different field -- a server-side `summary.events` beside a
    table of `events` -- which is refused, and is the stricter of the two errors;
  - a total rendered under a condition that has nothing to do with the cut.
    Found by N8's own negative run: the operations feed's server-limit note
    renders `{events.length}` only when the server holds more events than were
    loaded, and with the call-site slice put back this gate accepted the slice
    because of that note. Whether a condition coincides with a cut is not
    something a scan can decide, so the browser test is what refuses that build.

  - *Reported:* every truncation, whether it reaches a table, and whether it is
    accompanied. Truncations outside a table are listed and not gated.
  - *Gated:* a silent truncation reaching a table, in total or in any one file.
  - *Gated:* a file with no silent table truncation today growing one.
  - *Gated:* the checked-in reference disagreeing with the source.

  python oms/audit_table_truncation.py            # judge
  python oms/audit_table_truncation.py --write    # regenerate the reference
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Tuple

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))

FRONTEND_SRC = REPO_ROOT / "frontend" / "src"
REFERENCE = REPO_ROOT / "docs" / "TABLE_TRUNCATION.md"
BASELINE = REPO_ROOT / "docs" / "table-truncation-baseline.json"

# A component, at column zero. The body runs to the next one. Every component in
# the frontend is declared there, which is what makes this a usable scope for
# the one question that is about the component: whether it renders a count.
_DECLARATION = re.compile(
    r"^(?:export\s+)?(?:default\s+)?(?:async\s+)?"
    r"(?:function\s+(\w+)|(?:const|let)\s+(\w+))", re.MULTILINE)

# `DataGrid` is the product's second table, N7 of the goal. It is named here with
# `DataTable` because a call-site cut into either is the same evasion: the
# component captions what it is given and cannot caption what it never received.
_TABLE = re.compile(r"<(DataTable|DataGrid|table)\b|\brole=[\"'](?:table|grid)[\"']")
# The tables that page what they are given. A cut on the way into one of these
# hides rows the component would have paged, so no count beside it can make them
# reachable.
_PAGING = ("DataTable", "DataGrid")

# `.slice(` and the index filter. The first two groups mark where the argument
# list opens.
_CUT = re.compile(
    r"\.slice(\()"
    r"|\.filter(\()\s*\(\s*\w+\s*,\s*(\w+)\s*\)\s*=>\s*\3\s*<")

_CONSUMED = re.compile(r"\s*\.(map|forEach|flatMap|reduce|filter|some|every)\(")
_ITERATED = re.compile(r"\bof\s*$")
_ROWS_PROP = re.compile(r"\brows=\{\s*$")
_ASSIGNED = re.compile(r"\b(?:const|let)\s+(\w+)(?:\s*:[^=;]+)?\s*=\s*$")
_BINDING = re.compile(r"\b(?:const|let)\s+(\w+)(?:\s*:[^=;]+?)?\s*=(?![=>])")

_CLOSERS = {")": "(", "]": "[", "}": "{"}


def _receiver(text: str, dot: int) -> Tuple[int, str]:
    """The expression a `.slice` is called on, walked backwards from the dot."""
    index = dot
    while index > 0:
        character = text[index - 1]
        if character in _CLOSERS:
            opener, depth = _CLOSERS[character], 0
            while index > 0:
                index -= 1
                if text[index] == character:
                    depth += 1
                elif text[index] == opener:
                    depth -= 1
                    if depth == 0:
                        break
            continue
        if character == "`":
            index = max(text.rfind("`", 0, index - 1), 0)
            continue
        if character.isalnum() or character in "_$.?!":
            index -= 1
            continue
        break
    return index, text[index:dot]


def _close(text: str, opening: int) -> int:
    """The index just past the parenthesis that closes the one at `opening`."""
    depth = 0
    for index in range(opening, len(text)):
        if text[index] == "(":
            depth += 1
        elif text[index] == ")":
            depth -= 1
            if depth == 0:
                return index + 1
    return len(text)


def _tag_end(text: str, index: int) -> int:
    """The index just past the `>` ending an opening tag, counting braces and quotes.

    The same walk `audit_inert_controls` needed, for the same reason: an arrow
    inside a prop contains a `>` that does not end the tag.
    """
    depth, quote = 0, ""
    while index < len(text):
        character = text[index]
        if quote:
            if character == quote:
                quote = ""
        elif character in "\"'`":
            quote = character
        elif character == "{":
            depth += 1
        elif character == "}":
            depth -= 1
        elif character == ">" and depth == 0:
            return index + 1
        index += 1
    return len(text)


def _element_end(text: str, start: int, tag: str) -> int:
    """The index just past the element opened at `start`, nesting included."""
    depth = 0
    for match in re.finditer(rf"<{tag}\b|</{tag}\s*>", text[start:]):
        if match.group().startswith("</"):
            depth -= 1
            if depth == 0:
                return start + match.end()
            continue
        end = _tag_end(text, start + match.end())
        if text[end - 2] == "/":
            if depth == 0:
                return end
            continue
        depth += 1
    return len(text)


def table_extents(text: str) -> List[Tuple[int, int]]:
    """Where each table is written: a `<DataTable>`'s tag, or the whole element."""
    extents: List[Tuple[int, int]] = []
    for match in _TABLE.finditer(text):
        # A table component's extent is its own tag, props included. `DataGrid` has
        # to be named here as well as in `_TABLE`: added only to the pattern, it fell
        # through to the `role=` branch, which looks backwards for the element's
        # opening `<`, and a call-site cut into the grid read as outside any table.
        # The test that asserts that cut is refused is what found it.
        if match.group(1) in _PAGING:
            extents.append((match.start(), _tag_end(text, match.end())))
        elif match.group(1) == "table":
            extents.append((match.start(), _element_end(text, match.start(), "table")))
        else:
            start = text.rfind("<", 0, match.start())
            tag = re.match(r"<(\w+)", text[start:])
            if tag:
                extents.append((start, _element_end(text, start, tag.group(1))))
    return extents


def paging_extents(text: str) -> List[Tuple[int, int]]:
    """The tags of the tables that page: the subset of `table_extents` a cut hides rows from."""
    return [(match.start(), _tag_end(text, match.end()))
            for match in _TABLE.finditer(text) if match.group(1) in _PAGING]


def _statement_end(text: str, index: int) -> int:
    """Where the right-hand side of a binding ends."""
    depth, quote = 0, ""
    while index < len(text):
        character = text[index]
        if quote:
            if character == "\\":
                index += 1
            elif character == quote:
                quote = ""
        elif character in "\"`":
            quote = character
        elif character in "([{":
            depth += 1
        elif character in ")]}":
            depth -= 1
            if depth < 0:
                return index
        elif character == ";" and depth == 0:
            return index
        index += 1
    return len(text)


def _holder(body: str, position: int) -> Optional[Tuple[str, int]]:
    """The innermost `const NAME = ...` whose right-hand side contains `position`."""
    held = None
    for match in _BINDING.finditer(body, 0, position):
        end = _statement_end(body, match.end())
        if end > position:
            held = (match.group(1), end)
    return held


def _reaches(body: str, position: int, extents: List[Tuple[int, int]], hops: int = 4) -> bool:
    if any(start <= position < end for start, end in extents):
        return True
    held = _holder(body, position) if hops else None
    if not held:
        return False
    name, end = held
    return any(_reaches(body, end + use.start(), extents, hops - 1)
               for use in re.finditer(rf"\b{re.escape(name)}\b", body[end:]))


def _wrapped(text: str) -> bool:
    """Whether the whole of `text` is one parenthesised group."""
    if not (text.startswith("(") and text.endswith(")")):
        return False
    depth = 0
    for index, character in enumerate(text):
        depth += character == "("
        depth -= character == ")"
        if depth == 0 and index < len(text) - 1:
            return False
    return True


def source_of(receiver: str) -> str:
    """The collection whose length would be the true count.

    `(drafts.value || [])` is `drafts.value`: the fallback is what renders when
    there is nothing, so it is never the thing being counted.
    """
    text = receiver.replace("?.", ".").rstrip("!").strip()
    if _wrapped(text):
        text = re.split(r"\|\||\?\?", text[1:-1])[0].strip()
    return text


def _renders_total(body: str, source: str) -> bool:
    if not source:
        return False
    pattern = (r"(?:\{|\$\{)\s*" + re.escape(source)
               + r"\.length\s*(?:\.toLocaleString\(\)\s*)?\}")
    return bool(re.search(pattern, body.replace("?.", ".")))


def _declarations(text: str) -> Iterator[Tuple[int, int, str]]:
    found = list(_DECLARATION.finditer(text))
    for position, match in enumerate(found):
        end = found[position + 1].start() if position + 1 < len(found) else len(text)
        yield match.start(), end, match.group(1) or match.group(2)


def _how(body: str, begins: int, closed: int) -> Optional[str]:
    """How a cut's result is used, or None when it is not used as a collection."""
    after, before = body[closed:closed + 60], body[max(0, begins - 120):begins]
    consumed = _CONSUMED.match(after)
    if consumed:
        return "mapped" if consumed.group(1) == "map" else consumed.group(1)
    if _ITERATED.search(before):
        return "iterated"
    if _ROWS_PROP.search(before) and re.match(r"\s*\}", after):
        return "passed as rows"
    assigned = _ASSIGNED.search(before)
    if assigned:
        held = re.escape(assigned.group(1))
        if re.search(rf"\b{held}\s*\.(?:map|forEach|flatMap|reduce)\("
                     rf"|\bof\s+{held}\b|\brows=\{{\s*{held}\s*\}}", body[closed:]):
            return f"held as {assigned.group(1)}"
    return None


def cuts_in(text: str) -> List[Dict[str, Any]]:
    """Every collection truncation in one file's text."""
    cuts: List[Dict[str, Any]] = []
    for start, end, name in _declarations(text):
        body = text[start:end]
        extents = table_extents(body)
        paging = paging_extents(body)
        for match in _CUT.finditer(body):
            opening = match.start(1) if match.group(1) else match.start(2)
            begins, receiver = _receiver(body, match.start())
            how = _how(body, begins, _close(body, opening))
            if how is None:
                continue
            source = source_of(receiver)
            cuts.append({
                "line": text[:start + match.start()].count("\n") + 1,
                "declaration": name,
                "source": source or receiver.strip(),
                "spelling": "slice" if match.group(1) else "index filter",
                "how": how,
                "table": _reaches(body, match.start(), extents),
                "paging": _reaches(body, match.start(), paging),
                "counted": _renders_total(body, source),
            })
    return cuts


def _silent(cut: Dict[str, Any]) -> bool:
    """A cut reaching a table with no true count, or cut before a table that pages."""
    return cut["table"] and (not cut["counted"] or cut["paging"])


def scan() -> Dict[str, Any]:
    """Every collection truncation in the frontend, and which reach a table silently."""
    files: Dict[str, Dict[str, Any]] = {}
    tables = 0
    for path in sorted(FRONTEND_SRC.rglob("*.tsx")):
        label = str(path.relative_to(FRONTEND_SRC)).replace("\\", "/")
        text = path.read_text(encoding="utf-8")
        here = len(_TABLE.findall(text))
        tables += here
        cuts = cuts_in(text)
        if here or cuts:
            files[label] = {"tables": here, "cuts": cuts}
    return {"files": files, "tables": tables}


def totals(found: Dict[str, Any]) -> Tuple[int, int, int]:
    """(tables, truncations reaching a table, of those the silent ones)."""
    reaching = [c for f in found["files"].values() for c in f["cuts"] if c["table"]]
    return found["tables"], len(reaching), sum(1 for c in reaching if _silent(c))


def silent_per_file(found: Dict[str, Any]) -> Dict[str, int]:
    return {name: n for name, entry in sorted(found["files"].items())
            if (n := sum(1 for c in entry["cuts"] if _silent(c)))}


def _cut_rows(cuts: List[Tuple[str, Dict[str, Any]]], emphasise: bool) -> List[str]:
    lines = ["| File | Line | In | Cuts | How | Into a paging table | True count rendered |",
             "| --- | --- | --- | --- | --- | --- | --- |"]
    for name, cut in cuts:
        counted = "yes" if cut["counted"] else ("**no**" if emphasise else "no")
        paging = ("**yes**" if emphasise else "yes") if cut["paging"] else "no"
        lines.append(f"| `{name}` | {cut['line']} | `{cut['declaration']}` | "
                     f"`{cut['source']}` ({cut['spelling']}) | {cut['how']} | {paging} | {counted} |")
    return lines


def render(found: Dict[str, Any]) -> str:
    tables, reaching, silent = totals(found)
    every = [(n, c) for n, e in sorted(found["files"].items()) for c in e["cuts"]]
    inside = [(n, c) for n, c in every if c["table"]]
    outside = [(n, c) for n, c in every if not c["table"]]
    lines = [
        "# Tables that show part of what they were given",
        "",
        "Generated by `oms/audit_table_truncation.py`. Do not edit by hand — the gate",
        "regenerates this and fails if it disagrees with the source.",
        "",
        f"**{silent} of {reaching}** truncations that reach a table are silent: they render no"
        f" true count, or cut rows before a table that would have paged them. {tables} table elements",
        "(`<DataTable>`, `<table>`, `role=\"table\"` or `role=\"grid\"`) are written across the",
        "frontend.",
        "",
        "A table that renders forty of sixty rows and says nothing is read as sixty rows",
        "being forty. The rows are not pending; they are gone, and the screen does not say",
        "so. A count of what was kept does not fix that — only the length of what was cut.",
        "And no count fixes rows cut before `DataTable` or `DataGrid`, which page what they",
        "are given: the rows past the cut are named and cannot be reached.",
        "",
        "## Reaching a table",
        "",
    ]
    lines += _cut_rows(inside, emphasise=True) if inside else ["No truncation reaches a table."]
    lines += [
        "",
        "## Outside a table — reported, not gated",
        "",
        "Lists, canvases and chips cut the same way. They are outside N4's scope, which is",
        "the table, and they are listed so that the scope is a boundary someone can see",
        "rather than a count that quietly leaves them out. Some are deliberate — a first",
        "alert taken as a default is not a hidden row.",
        "",
    ]
    lines += _cut_rows(outside, emphasise=False) if outside else ["None."]
    lines.append("")
    return "\n".join(lines)


def compare(found: Dict[str, Any],
            baseline: Dict[str, Any]) -> Tuple[bool, List[str], List[str]]:
    failures: List[str] = []
    notes: List[str] = []
    _, _, silent = totals(found)
    ceiling = baseline.get("silent")
    recorded: Dict[str, int] = baseline.get("per_file", {})

    if ceiling is None:
        failures.append("the baseline records no silent count; re-run with --set-baseline")
    elif silent > ceiling:
        failures.append(
            f"{silent} silent table truncation(s), up from {ceiling}. A table that drops "
            f"rows or columns must render the length of what it cut -- not the length of "
            f"what it kept -- and rows for DataTable or DataGrid must not be cut at all: "
            f"they page what they are given, so hand them every row.")
    elif silent < ceiling:
        notes.append(f"silent table truncations {ceiling} -> {silent}; re-run with --set-baseline")

    for name, now in silent_per_file(found).items():
        was = recorded.get(name, 0)
        if now > was:
            failures.append(f"{name}: {was} -> {now} silent table truncation(s)"
                            + ("" if was else " — this file had none"))

    if not REFERENCE.exists():
        failures.append(f"{REFERENCE.relative_to(REPO_ROOT)} is missing; regenerate with --write")
    elif REFERENCE.read_text(encoding="utf-8") != render(found):
        failures.append(f"{REFERENCE.relative_to(REPO_ROOT)} disagrees with the source. "
                        f"Regenerate it: python oms/audit_table_truncation.py --write")
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
    tables, reaching, silent = totals(found)
    print(f"{tables} table element(s); {reaching} truncation(s) reach one, "
          f"{silent} of them silent\n")
    for name, count in Counter(silent_per_file(found)).most_common(8):
        print(f"  {count:>2} silent  {name}")

    if args.write:
        REFERENCE.write_text(render(found), encoding="utf-8")
        print(f"\nWrote {REFERENCE.relative_to(REPO_ROOT)} ({silent} silent).")
        return 0

    if args.set_baseline:
        BASELINE.write_text(json.dumps({
            "provenance": {"stale_after": "recomputed each run"},
            "note": ("Collection truncations that reach a table and render no true count. "
                     "A ceiling, not a floor: the count may fall and must never rise."),
            "tables": tables,
            "reaching": reaching,
            "silent": silent,
            "per_file": silent_per_file(found),
        }, indent=2) + "\n", encoding="utf-8")
        print(f"\nBaseline set: {silent} silent of {reaching}.")
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
    print(f"\nNo table gained a silent truncation. {silent} of {reaching} remain silent, "
          f"and the count may only fall.")
    return 0


if __name__ == "__main__":
    from enforcement_runs import recording

    raise SystemExit(recording("audit_table_truncation", main))

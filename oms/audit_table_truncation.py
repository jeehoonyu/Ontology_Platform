"""Tables, lists and loaded windows that show part of a set, and do not say so.

N4 of `GOAL_HONEST_UI_2026-09-11.md`. Written after N3 rather than before it,
unlike its sibling `audit_inert_controls`, because what it refuses is the shape
N3 decided: a table may drop rows or columns, and when it does, the true count
is rendered beside what it kept.

**A truncation here is a collection cut short in a `.ts` or `.tsx` file.** Two spellings:

    xs.slice(a, b)                  -- the one this codebase uses
    xs.filter((x, i) => i < n)      -- the same cut, and the obvious way round
                                       a rule that only knows the first

A `.slice` is a *collection* cut only if what it produces is used as one:
mapped or otherwise consumed, iterated with `for ... of`, handed to a table as
`rows`, or bound to a name that is then one of those. `run.id.slice(0, 8)`
shortens a string for display and is none of them, so it is not counted.

**A third spelling has no `.slice` at all.** N7c: a grid that registers
`createFilteredRowModel()` drops rows inside the library and draws
`table.getRowModel().rows`. In a file that registers one, each `getRowModel()`
reaching a table is a cut, and its true count is the model before filtering:
`const total = table.getPreFilteredRowModel().rows`, rendered as `{total.length}`.
The count of what matched is the count of what was kept, and is refused. For this
cut the total must be in the markup: a `${total.length}` in a template sentence
does not count, because that sentence is shown only after an announcement, and a
caption without the total reads as the dataset while a person types. Rows drawn
from any model downstream of the filter count as the draw, `getSortedRowModel()`
included; the review of N7c drew the grid from it and found the rule blind.

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

**A cut is placed, classified, or gated by name.** The first version dropped any cut it
could not place, and the ontology manager's Drafts list,
`(allDrafts ? draftList : draftList.slice(0, 6)).map(`, left the reference without a word. A
cut in one branch of a condition whose group is consumed is placed now, and reads as "all on
request" when the other branch is the whole source. A slice that is not a collection is read
from a closed set -- text, a prefix dropped, a last item dropped, or a request payload built
inside an event handler and not handed to a setter -- and is listed, not gated. Anything else
is recorded as not placed and gated by name. Every `.slice(` is accounted for in the reference.
A cut declared not to be a list, in `DELIBERATE_CUTS`, names its reason, and a new one fails.

**A list cut is stated by a note and a way to the rest.** Outside a table, a cut is silent
unless a `role="note"` element renders the source's length -- or a name bound to an expression
that includes it, a total from the server that falls back to the length -- and the cut is taken
only behind a `useState` value whose setter a `<button>` calls. A count in a button's label is
not the note: the Drafts list with its note removed kept its length there. A note with no
control is not enough: the map's feature list rendered a count and nothing past the twelfth
feature could be reached.

**A loaded window is claimed by name.** A screen that loads the latest 50 of a set and draws
them as the set is a table cut on the server. The census reads every request limit a screen
sends (a literal, a parameter's default, a module constant, or a helper's caller's body), every
route default a request reaches by leaving its limit out (`Query(N)`, `Query(default=N)`, a plain
default, a body model's field), and every fixed cap -- `.limit(N)`, or `NAME[:N]` in a returned
value -- on a route a screen calls, in its handler and up to three same-module calls below it.
Keys name what a window is, never a line. Each one is claimed by exactly one entry in `WINDOWS`:
stated by a named browser test and the text of the note, caption or summary that states it; a
gap held by name in the baseline; or not applicable with a reason, which, as in
`audit_movement_contract`, is the evasion path and fails when new. A request limit whose route
this cannot find fails too.

What this does not see, stated rather than implied:

  - a cut passed down to a child component declared in another file;
  - a filtered row model registered in a different file from the grid that draws it;
  - rows drawn from `getFilteredRowModel()` itself, which is unsorted and is read here
    only as a count;
  - a total from a different field beside a cut in the same file -- a server-side
    `summary.events` beside a table of `events` -- which is refused, the stricter of the two
    errors; a loaded window's total necessarily comes from another field, and its named
    browser test is what proves it;
  - a total rendered under a condition that has nothing to do with the cut.
    Found by N8's own negative run: the operations feed's server-limit note
    renders `{events.length}` only when the server holds more events than were
    loaded, and with the call-site slice put back this gate accepted the slice
    because of that note. Whether a condition coincides with a cut is not
    something a scan can decide, so the browser test is what refuses that build;
  - the legacy screens in `oms/app/ui/app.js`, which make some of the same requests;
  - a cap computed by an expression (`min(limit * 3, 1000)`) or taken from a variable;
  - a cap in another module's helper, deeper than three calls, or written into a value
    before the return;
  - a request whose path or body is assembled away from the call.

  - *Reported:* every truncation, whether it reaches a table, and whether it is
    accompanied; every slice read as not a collection; every loaded window and its state.
  - *Gated:* the unfixed truncations and gap windows, by count and by name -- a silent
    table cut, a list cut not stated, a cut not placed, a gap window.
  - *Gated:* a file with no unfixed truncation today growing one.
  - *Gated:* a loaded window no entry claims, a claim the census no longer finds, a
    stated window whose test or statement is gone, and a new declaration of not applicable.
  - *Gated:* the checked-in reference disagreeing with the source.

  python oms/audit_table_truncation.py            # judge
  python oms/audit_table_truncation.py --write    # regenerate the reference
"""
from __future__ import annotations

import argparse
import ast
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

# A third spelling, with no `.slice` at all: a library row model that filters.
# Presence is read per file, because the grid registers its features at module
# level, above the component that draws the rows.
_FILTERED_MODEL = re.compile(r"\bcreateFilteredRowModel\(")
# Every getter downstream of the filter that a grid could draw rows from. Not
# `getFilteredRowModel`, which is unsorted and read for counts; not the core or
# pre-filtered models, which come before the filter. A `.rows.length` read is a
# count, not a draw.
_ROW_MODEL = re.compile(
    r"\.get(?:Sorted|PreSorted|Grouped|PreGrouped|Expanded|PreExpanded|Paginated|PrePaginated)?"
    r"RowModel\(\)(?!\.rows\.length)")
_PRE_FILTERED = re.compile(
    r"\b(?:const|let)\s+(\w+)(?:\s*:[^=;]+?)?\s*=\s*[\w.]+\.getPreFilteredRowModel\(\)\.rows\b")
_PRE_FILTERED_DESTRUCTURED = re.compile(
    r"\b(?:const|let)\s+\{\s*rows\s*:\s*(\w+)\s*\}(?:\s*:[^=;]+?)?\s*=\s*[\w.]+\.getPreFilteredRowModel\(\)")

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


def _renders_total(body: str, source: str, markup_only: bool = False) -> bool:
    """Whether the length of `source` is rendered. `markup_only` refuses a template
    literal's `${...}`, for the filtered-row-model cut, whose count belongs in the
    caption rather than in a sentence shown only after an announcement."""
    if not source:
        return False
    opening = r"(?<!\$)\{" if markup_only else r"(?:\{|\$\{)"
    pattern = (opening + r"\s*" + re.escape(source)
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


# --- a cut behind a condition, and a slice that is not a collection ----------------------
_STRING_METHOD = re.compile(
    r"\s*\.(?:toUpperCase|toLowerCase|toLocaleUpperCase|toLocaleLowerCase|trim|trimStart|trimEnd"
    r"|split|replace|replaceAll|startsWith|endsWith|padStart|padEnd)\(")
_TEXT_RECEIVER = re.compile(r"(?:\.toLowerCase\(\)|\.toUpperCase\(\)|\.replace\(.*\)|randomUUID\(\))$", re.DOTALL)
_STRING_FALLBACK = re.compile(r"\s*(?:\|\||\?\?)\s*[\"'`]")
_HANDLER = re.compile(r"\bon[A-Z]\w*=\{")
_SETTER_CALL = re.compile(r"\bset[A-Z]\w*\(")
_USE_STATE = re.compile(r"\bconst\s*\[\s*(\w+)\s*,\s*(set\w+)\s*\]\s*=\s*useState\b")


def _brace_end(text: str, opening: int) -> int:
    """The index just past the brace that closes the one at `opening`, skipping quoted text."""
    depth, quote, index = 0, "", opening
    while index < len(text):
        character = text[index]
        if quote:
            if character == "\\":
                index += 1
            elif character == quote:
                quote = ""
        elif character in "\"'`":
            quote = character
        elif character == "{":
            depth += 1
        elif character == "}":
            depth -= 1
            if depth == 0:
                return index + 1
        index += 1
    return len(text)


def _ternary(text: str) -> Optional[Tuple[int, int]]:
    """The top-level `?` of an expression and its `:`, or None. `?.` and `??` are not ternaries."""
    depth, quote, question, nested, index = 0, "", None, 0, 0
    while index < len(text):
        character = text[index]
        if quote:
            if character == "\\":
                index += 1
            elif character == quote:
                quote = ""
        elif character in "\"'`":
            quote = character
        elif character in "([{":
            depth += 1
        elif character in ")]}":
            depth -= 1
        elif depth == 0 and character == "?":
            following = text[index + 1:index + 2]
            preceding = text[index - 1:index] if index else ""
            if following not in (".", "?") and preceding != "?":
                if question is None:
                    question = index
                else:
                    nested += 1
        elif depth == 0 and character == ":" and question is not None:
            if nested:
                nested -= 1
            else:
                return question, index
        index += 1
    return None


def _enclosing_group(body: str, begins: int, closed: int) -> Optional[Tuple[int, int]]:
    """The parenthesised group, not a call's argument list, that holds a cut and ends after it."""
    depth, index = 0, begins - 1
    while index >= 0:
        character = body[index]
        if character in ")]}":
            depth += 1
        elif character in "([{":
            if depth == 0:
                if character != "(":
                    return None
                before = body[:index].rstrip()
                if before and (before[-1].isalnum() or before[-1] in "_$)]"):
                    return None
                end = _close(body, index)
                return (index, end) if end >= closed else None
            depth -= 1
        elif character == ";" and depth == 0:
            return None
        index -= 1
    return None


def _branches(expression: str, cut_at: int) -> Optional[Tuple[str, str]]:
    """(condition, the branch not holding the cut) when `expression` is a ternary with the cut in a branch."""
    split = _ternary(expression)
    if not split:
        return None
    question, colon = split
    condition, yes, no = expression[:question], expression[question + 1:colon], expression[colon + 1:]
    if question < cut_at < colon:
        return condition, no
    if cut_at > colon:
        return condition, yes
    return None


def _on_request(other: str, source: str) -> bool:
    """Whether the other branch of a cut's condition is the whole of the source it cuts."""
    other = other.strip()
    return bool(source) and not _CUT.search(other) and source_of(other) == source


def place(body: str, begins: int, closed: int, source: str) -> Optional[Dict[str, str]]:
    """How a cut behind a condition is used: a branch of a consumed group, or of a bound ternary."""
    group = _enclosing_group(body, begins, closed)
    if group:
        start, end = group
        consumed = _CONSUMED.match(body[end:end + 60])
        if consumed:
            branches = _branches(body[start + 1:end - 1], begins - start - 1)
            if branches is None:
                return {"how": "mapped" if consumed.group(1) == "map" else consumed.group(1), "condition": ""}
            condition, other = branches
            how = "mapped, all on request" if _on_request(other, source) else "mapped (one branch)"
            return {"how": how, "condition": condition.strip()}
    held = _holder(body, begins)
    if held:
        name, end = held
        bindings = [m for m in _BINDING.finditer(body, 0, begins)
                    if m.group(1) == name and _statement_end(body, m.end()) == end]
        if bindings:
            binding = bindings[-1]
            branches = _branches(body[binding.end():end], begins - binding.end())
            used = re.search(rf"\b{re.escape(name)}\s*\.(?:map|forEach|flatMap|reduce)\(|\bof\s+{re.escape(name)}\b"
                             rf"|\brows=\{{\s*{re.escape(name)}\s*\}}", body[end:])
            if branches and used:
                condition, other = branches
                suffix = ", all on request" if _on_request(other, source) else " (one branch)"
                return {"how": f"held as {name}{suffix}", "condition": condition.strip()}
    return None


def not_a_collection(body: str, begins: int, opening: int, closed: int, receiver: str) -> Optional[str]:
    """Why a slice is not a collection cut, from a closed set, or None."""
    arguments = body[opening + 1:closed - 1]
    after = body[closed:closed + 60]
    stripped = receiver.strip()
    if _STRING_METHOD.match(after) or _STRING_FALLBACK.match(after):
        return "text"
    if stripped[:1] in "\"'`" or _TEXT_RECEIVER.search(stripped):
        return "text"
    child = re.search(r"(\$?)\{\s*$", body[max(0, begins - 3):begins])
    if child and re.match(r"\s*\}", after):
        # A template can only render what it interpolates as text; a JSX child can render a list,
        # so there only a property's slice (`run.id`) is read as text, never a bare name.
        if child.group(1) or re.search(r"[\w\])]\.\w+$", stripped.replace("?.", ".")):
            return "text"
    if "," not in arguments:
        return "prefix dropped"
    if re.match(r"\s*[\w.]+\s*,\s*-", arguments):
        return "last dropped"
    return None


def request_payload(body: str, position: int) -> bool:
    """A cut built into an event handler's call, and not into state the handler sets."""
    for handler in _HANDLER.finditer(body, 0, position):
        end = _brace_end(body, handler.end() - 1)
        if handler.end() <= position < end:
            for setter in _SETTER_CALL.finditer(body, handler.end(), position):
                if _close(body, setter.end() - 1) > position:
                    return False
            return True
    return False


def others_in(text: str) -> List[Dict[str, Any]]:
    """Every `.slice(` that is not a collection cut, and why."""
    found: List[Dict[str, Any]] = []
    for start, end, name in _declarations(text):
        body = text[start:end]
        for match in _CUT.finditer(body):
            if not match.group(1):
                continue
            opening = match.start(1)
            closed = _close(body, opening)
            begins, receiver = _receiver(body, match.start())
            source = source_of(receiver)
            if request_payload(body, match.start()):
                reason = "request payload"
            elif _how(body, begins, closed) or place(body, begins, closed, source):
                continue
            else:
                reason = not_a_collection(body, begins, opening, closed, receiver)
                if reason is None:
                    continue
            found.append({"line": text[:start + match.start()].count("\n") + 1, "declaration": name,
                          "source": source or receiver.strip(), "reason": reason})
    return found


def cuts_in(text: str) -> List[Dict[str, Any]]:
    """Every collection truncation in one file's text."""
    cuts: List[Dict[str, Any]] = []
    for start, end, name in _declarations(text):
        body = text[start:end]
        extents = table_extents(body)
        paging = paging_extents(body)
        for match in _CUT.finditer(body):
            opening = match.start(1) if match.group(1) else match.start(2)
            closed = _close(body, opening)
            begins, receiver = _receiver(body, match.start())
            source = source_of(receiver)
            if request_payload(body, match.start()):
                continue
            how, condition = _how(body, begins, closed), ""
            if how is None:
                placed = place(body, begins, closed, source)
                if placed:
                    how, condition = placed["how"], placed["condition"]
            if how is None:
                if match.group(1) and not_a_collection(body, begins, opening, closed, receiver):
                    continue
                how = "unplaced"
            cut = {
                "line": text[:start + match.start()].count("\n") + 1,
                "declaration": name,
                "source": source or receiver.strip(),
                "spelling": "slice" if match.group(1) else "index filter",
                "how": how,
                "condition": condition,
                "table": _reaches(body, match.start(), extents),
                "paging": _reaches(body, match.start(), paging),
                "counted": _renders_total(body, source),
            }
            if not cut["table"]:
                cut["noted"] = _noted(body, source)
                cut["reachable"] = _reachable(body, cut)
                cut["stated"] = cut["noted"] and cut["reachable"]
            cuts.append(cut)
        # N7c. A filter drops rows inside the library's row model and never passes
        # through a `.slice`, so a grid captioning only what matched would read as the
        # dataset. In a file that registers a filtered row model, each `getRowModel()`
        # reaching a table is a cut whose true count is the model before filtering.
        if _FILTERED_MODEL.search(text):
            bound = _PRE_FILTERED.search(body) or _PRE_FILTERED_DESTRUCTURED.search(body)
            for match in _ROW_MODEL.finditer(body):
                if not _reaches(body, match.start(), extents):
                    continue
                receiver = source_of(_receiver(body, match.start())[1])
                source = bound.group(1) if bound else f"{receiver}.getPreFilteredRowModel().rows"
                cuts.append({
                    "line": text[:start + match.start()].count("\n") + 1,
                    "declaration": name,
                    "source": source,
                    "spelling": "filtered row model",
                    "how": "filtered in the library",
                    "condition": "",
                    "table": True,
                    # Clearing the filter brings every row back: not N9's unreachable cut.
                    "paging": False,
                    "counted": _renders_total(body, source, markup_only=True),
                })
    return cuts


# Cuts declared not to be a list a person reads, each with its reason. Declaring one is this
# gate's evasion path, so a name here that the baseline's `na` does not hold fails.
DELIBERATE_CUTS: Dict[str, str] = {
    "cut:App.tsx::App::[nextView, ...recentViews.filter((item) => item !== nextView)]":
        "the five most recent views kept for navigation history; the full list of views is the nav itself",
}

_NOTE_OPEN = re.compile(r"<(\w+)\b[^<>]*?\brole=[\"']note[\"']")


def _note_markup(body: str) -> str:
    """Every `role="note"` element in a declaration, joined."""
    parts = []
    for match in _NOTE_OPEN.finditer(body):
        start = match.start()
        parts.append(body[start:_element_end(body, start, match.group(1))])
    return "\n".join(parts)


def _noted(body: str, source: str) -> bool:
    """A note renders the source's length, or a name bound to an expression that includes it.

    The second is a total from the server that falls back to the source's own length --
    `facet.distinct_count ?? facet.buckets.length` -- which is a count of the same set, where a
    field that never mentions the source (`summary.events` beside `events`) is not.
    """
    markup = _note_markup(body)
    if not markup or not source:
        return False
    if _renders_total(markup, source, markup_only=True):
        return True
    length = re.escape(source) + r"\.length\b"
    for binding in _BINDING.finditer(body.replace("?.", ".")):
        expression = body.replace("?.", ".")[binding.end():_statement_end(body.replace("?.", "."), binding.end())]
        if re.search(length, expression) and re.search(
                r"(?<!\$)\{\s*" + re.escape(binding.group(1)) + r"\s*(?:\.toLocaleString\(\)\s*)?\}", markup):
            return True
    return False


def _reachable(body: str, cut: Dict[str, Any]) -> bool:
    """Placed all on request, behind a `useState` value whose setter a `<button>` calls."""
    if "all on request" not in cut["how"]:
        return False
    names = set(re.findall(r"\b\w+\b", cut.get("condition", "")))
    for state in _USE_STATE.finditer(body):
        if state.group(1) not in names:
            continue
        for button in re.finditer(r"<button\b", body):
            tag = body[button.start():_tag_end(body, button.end())]
            if re.search(rf"\b{re.escape(state.group(2))}\(", tag):
                return True
    return False


def cut_name(file: str, cut: Dict[str, Any]) -> str:
    return f"cut:{file.split('/')[-1]}::{cut['declaration']}::{cut['source']}"


def _silent(cut: Dict[str, Any]) -> bool:
    """A cut reaching a table with no true count, or cut before a table that pages; a list cut
    that does not say how much it shows and let the rest be reached; or a cut nobody placed."""
    if cut["table"]:
        return not cut["counted"] or cut["paging"]
    return not cut.get("stated", False)


# --- windows: what a screen loads, and what the server keeps back ------------------------
APP_DIR = REPO_ROOT / "oms" / "app"
SPECS = FRONTEND_SRC.parent / "tests"
_CLIENT_CALL = re.compile(r"\b(api|apiWithTotal|postJson)\b(?=\s*[<(])")
_ROUTE_METHODS = ("get", "post", "put", "patch", "delete")
_LIMIT_NAME = re.compile(r"^(?:limit|\w+_limit)$")


def _read(path: Path, sources: Optional[Dict[str, str]] = None) -> str:
    key = path.relative_to(REPO_ROOT).as_posix()
    if sources and key in sources:
        return sources[key]
    return path.read_text(encoding="utf-8")


def _matching(text: str, opening: int, pair: str) -> int:
    """The index just past the `pair[1]` closing the `pair[0]` at `opening`, skipping quoted text."""
    depth, quote, index = 0, "", opening
    while index < len(text):
        character = text[index]
        if quote:
            if character == "\\":
                index += 1
            elif character == quote:
                quote = ""
        elif character in "\"'`":
            quote = character
        elif character == pair[0]:
            depth += 1
        elif character == pair[1]:
            depth -= 1
            if depth == 0:
                return index + 1
        index += 1
    return len(text)


def _skip_type_arguments(text: str, index: int) -> int:
    """Past a `<...>` type argument list at `index`; `=>` inside it does not close it."""
    while index < len(text) and text[index].isspace():
        index += 1
    if index >= len(text) or text[index] != "<":
        return index
    depth = 0
    for position in range(index, min(len(text), index + 4000)):
        character = text[position]
        if character == "<":
            depth += 1
        elif character == ">" and text[position - 1] != "=":
            depth -= 1
            if depth == 0:
                return position + 1
    return index


def _literal(text: str) -> Optional[Tuple[str, List[str]]]:
    """A string or template literal at the start of `text`: its text with each `${}` as `{#n}`, and the expressions."""
    stripped = text.lstrip()
    if not stripped or stripped[0] not in "\"'`":
        return None
    quote, out, expressions, index = stripped[0], [], [], 1
    while index < len(stripped):
        character = stripped[index]
        if character == "\\":
            out.append(stripped[index:index + 2])
            index += 2
            continue
        if character == quote:
            return "".join(out), expressions
        if quote == "`" and stripped.startswith("${", index):
            end = _matching(stripped, index + 1, "{}")
            expressions.append(stripped[index + 2:end - 1].strip())
            out.append("{#%d}" % (len(expressions) - 1))
            index = end
            continue
        out.append(character)
        index += 1
    return None


def _split_top(text: str, separator: str = ",") -> List[str]:
    parts, depth, quote, start, index = [], 0, "", 0, 0
    while index < len(text):
        character = text[index]
        if quote:
            if character == "\\":
                index += 1
            elif character == quote:
                quote = ""
        elif character in "\"'`":
            quote = character
        elif character in "([{":
            depth += 1
        elif character in ")]}":
            depth -= 1
        elif character == separator and depth == 0:
            parts.append(text[start:index])
            start = index + 1
        index += 1
    parts.append(text[start:])
    return [part.strip() for part in parts if part.strip()]


def _object_entries(text: str) -> Optional[Dict[str, str]]:
    """The top-level entries of an object literal, or None when it is not one or spreads another."""
    text = text.strip()
    if not text.startswith("{"):
        return None
    end = _matching(text, 0, "{}")
    if text[end:].strip():
        return None
    entries: Dict[str, str] = {}
    for part in _split_top(text[1:end - 1]):
        if part.startswith("..."):
            return None
        key = re.match(r"""^["']?([\w$]+)["']?\s*(?::\s*(.*))?$""", part, re.DOTALL)
        if not key:
            return None
        entries[key.group(1)] = (key.group(2) or key.group(1)).strip()
    return entries


def _resolve(value: str, head: str, file_text: str) -> Optional[int]:
    """An integer a limit's value names: a literal, a parameter's default above the call, or a module constant."""
    value = value.strip()
    if re.fullmatch(r"\d+", value):
        return int(value)
    if not re.fullmatch(r"[A-Za-z_$][\w$]*", value):
        return None
    default = re.findall(rf"\b{re.escape(value)}\s*(?::\s*[\w\[\]| ]+)?\s*=\s*(\d+)\b", head)
    if default:
        return int(default[-1])
    constant = re.search(rf"^(?:export\s+)?const\s+{re.escape(value)}\s*(?::\s*\w+)?\s*=\s*(\d+)\s*;?\s*$", file_text, re.MULTILINE)
    return int(constant.group(1)) if constant else None


def _parameters(text: str, head: str) -> List[str]:
    """The parameter names of the declaration whose text starts `head`."""
    opening = head.find("(")
    if opening < 0:
        return []
    closing = _matching(head, opening, "()")
    return [re.match(r"[\w$]*", part.lstrip(".")).group() for part in _split_top(head[opening + 1:closing - 1])]


def helper_calls(label: str, text: str, helpers: Dict[str, Tuple[int, Dict[str, Any]]]) -> List[Dict[str, Any]]:
    """Calls to a helper that posts one of its parameters, with that argument read as the request body."""
    calls: List[Dict[str, Any]] = []
    if not helpers:
        return calls
    declarations = list(_declarations(text))
    for match in re.finditer(r"\b(" + "|".join(map(re.escape, sorted(helpers))) + r")\s*\(", text):
        name = match.group(1)
        index, request = helpers[name]
        if request["file"] == label and request["declaration"] == name:
            continue
        opening = match.end() - 1
        before = text[max(0, match.start() - 20):match.start()]
        if re.search(r"(?:function|const|let|import|\.)\s*$", before):
            continue
        arguments = _split_top(text[opening + 1:_matching(text, opening, "()") - 1])
        declaration, head = "<module>", text[:match.start()]
        for start, end, holder in declarations:
            if start <= match.start() < end:
                declaration, head = holder, text[start:match.start()]
        entries = _object_entries(arguments[index]) if len(arguments) > index else None
        calls.append(dict(request, file=label, declaration=declaration, line=text[:match.start()].count("\n") + 1,
                          body={key: _resolve(value, head, text) for key, value in (entries or {}).items() if _LIMIT_NAME.match(key)},
                          body_known=entries is not None, helper=None, through=name))
    return calls


def _path_shape(path: str) -> str:
    return "/".join("{}" if "{" in segment else segment for segment in path.split("/"))


def requests_in(label: str, text: str) -> List[Dict[str, Any]]:
    """Every call to the API client whose path is written as a literal, with what it asks for."""
    calls: List[Dict[str, Any]] = []
    declarations = list(_declarations(text))
    for match in _CLIENT_CALL.finditer(text):
        opening = _skip_type_arguments(text, match.end())
        if opening >= len(text) or text[opening] != "(":
            continue
        closing = _matching(text, opening, "()")
        arguments = _split_top(text[opening + 1:closing - 1])
        literal = _literal(arguments[0]) if arguments else None
        if not literal or not literal[0].startswith("/"):
            continue
        raw, expressions = literal
        route, _, query = raw.partition("?")
        glued = re.search(r"(?<=[\w-])\{#\d+\}$", route)
        if glued:
            route, query = route[:glued.start()], (query + "&" if query else "") + glued.group()
        declaration, head = "<module>", text[:match.start()]
        for start, end, name in declarations:
            if start <= match.start() < end:
                declaration, head = name, text[start:match.start()]
        method, body = ("POST", arguments[1] if len(arguments) > 1 else "") if match.group(1) == "postJson" else ("GET", "")
        if match.group(1) == "api" and len(arguments) > 1:
            init = _object_entries(arguments[1]) or {}
            named = re.fullmatch(r"""["'](\w+)["']""", init.get("method", ""))
            method = named.group(1).upper() if named else method
            stringify = re.fullmatch(r"JSON\.stringify\((.*)\)", init.get("body", ""), re.DOTALL)
            body = stringify.group(1) if stringify else init.get("body", "")
        query_params: Dict[str, Optional[int]] = {}
        query_known = True
        for item in [part for part in query.split("&") if part]:
            name, equals, value = item.partition("=")
            if not equals:
                query_known = False
                continue
            placeholder = re.fullmatch(r"\{#(\d+)\}", value)
            query_params[name] = _resolve(expressions[int(placeholder.group(1))], head, text) if placeholder else (
                int(value) if value.isdigit() else None)
        helper = None
        if re.fullmatch(r"[A-Za-z_$][\w$]*", body.strip() or "-") and declaration != "<module>":
            parameters = _parameters(text, head)
            if body.strip() in parameters:
                helper = (declaration, parameters.index(body.strip()))
        entries = _object_entries(body) if body else {}
        body_params = {key: _resolve(value, head, text) for key, value in (entries or {}).items()
                       if _LIMIT_NAME.match(key)}
        calls.append({
            "file": label, "declaration": declaration, "line": text[:match.start()].count("\n") + 1,
            "method": method, "path": _path_shape(re.sub(r"\{#\d+\}", "{}", route)),
            "query": query_params, "query_known": query_known and "{#" not in query.split("=")[0],
            "body": body_params, "body_known": entries is not None, "helper": helper,
        })
    return calls


def _call_name(node: ast.AST) -> str:
    func = node.func if isinstance(node, ast.Call) else node
    return func.attr if isinstance(func, ast.Attribute) else func.id if isinstance(func, ast.Name) else ""


def _int_default(node: Optional[ast.AST]) -> Optional[int]:
    if isinstance(node, ast.Constant) and isinstance(node.value, int) and not isinstance(node.value, bool):
        return node.value
    if isinstance(node, ast.Call) and _call_name(node) in ("Query", "Field", "Body"):
        if node.args:
            return _int_default(node.args[0]) if not isinstance(node.args[0], ast.Call) else None
        for keyword in node.keywords:
            if keyword.arg == "default":
                return _int_default(keyword.value)
    return None


def _model_defaults(model: ast.ClassDef) -> Dict[str, int]:
    found = {}
    for statement in model.body:
        if isinstance(statement, ast.AnnAssign) and isinstance(statement.target, ast.Name) \
                and _LIMIT_NAME.match(statement.target.id):
            value = _int_default(statement.value)
            if value is not None:
                found[statement.target.id] = value
    return found


def _caps_of(function: ast.AST) -> List[str]:
    """Fixed caps written in one function: `.limit(N)`, and `NAME[:N]` inside a returned value. One row is a lookup."""
    shapes: List[str] = []
    for node in ast.walk(function):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "limit" \
                and node.args and (_int_default(node.args[0]) or 0) > 1:
            shapes.append(f".limit({node.args[0].value})")
        if isinstance(node, ast.Return) and node.value is not None:
            for inner in ast.walk(node.value):
                if isinstance(inner, ast.Subscript) and isinstance(inner.value, ast.Name) \
                        and isinstance(inner.slice, ast.Slice) and inner.slice.lower is None and inner.slice.step is None \
                        and (_int_default(inner.slice.upper) or 0) > 1:
                    shapes.append(f"{inner.value.id}[:{inner.slice.upper.value}]")
    named, seen = [], Counter()
    for shape in shapes:
        seen[shape] += 1
        named.append(shape if seen[shape] == 1 else f"{shape}#{seen[shape]}")
    return named


def routes_in(module: str, source: str, shared_models: Optional[Dict[str, ast.ClassDef]] = None) -> List[Dict[str, Any]]:
    """Every route a module declares, with its limit defaults and the caps it and its helpers write."""
    tree = ast.parse(source)
    prefixes: Dict[str, str] = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call) and _call_name(node.value) in ("APIRouter", "FastAPI"):
            prefix = next((keyword.value.value for keyword in node.value.keywords
                           if keyword.arg == "prefix" and isinstance(keyword.value, ast.Constant)), "")
            for target in node.targets:
                if isinstance(target, ast.Name):
                    prefixes[target.id] = prefix
    models = dict(shared_models or {})
    models.update({node.name: node for node in tree.body if isinstance(node, ast.ClassDef)})
    functions = {node.name: node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}

    def reached(function: ast.AST, depth: int, seen: set) -> List[str]:
        names = [function.name]
        if depth == 0:
            return names
        for node in ast.walk(function):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in functions \
                    and node.func.id not in seen:
                seen.add(node.func.id)
                names += reached(functions[node.func.id], depth - 1, seen)
        return names

    routes = []
    for function in functions.values():
        for decorator in function.decorator_list:
            if not (isinstance(decorator, ast.Call) and isinstance(decorator.func, ast.Attribute)
                    and decorator.func.attr in _ROUTE_METHODS and isinstance(decorator.func.value, ast.Name)
                    and decorator.func.value.id in prefixes and decorator.args
                    and isinstance(decorator.args[0], ast.Constant) and isinstance(decorator.args[0].value, str)):
                continue
            defaults: Dict[str, Tuple[int, str]] = {}
            arguments = function.args
            positional = arguments.posonlyargs + arguments.args
            for argument, default in list(zip(positional[len(positional) - len(arguments.defaults):], arguments.defaults)) \
                    + list(zip(arguments.kwonlyargs, arguments.kw_defaults)):
                value = _int_default(default)
                if value is not None and _LIMIT_NAME.match(argument.arg):
                    defaults[argument.arg] = (value, "query")
            for argument in positional + arguments.kwonlyargs:
                if isinstance(argument.annotation, ast.Name) and argument.annotation.id in models:
                    for name, value in _model_defaults(models[argument.annotation.id]).items():
                        defaults[name] = (value, "body")
            path = re.sub(r"\{[^}]*\}", "{}", prefixes[decorator.func.value.id] + decorator.args[0].value)
            helpers = reached(function, 3, {function.name})
            routes.append({"module": module, "function": function.name, "method": decorator.func.attr.upper(),
                           "path": path, "defaults": defaults,
                           "caps": [f"cap:{module}.{name}::{shape}" for name in helpers for shape in _caps_of(functions[name])]})
    return routes


def _match_routes(call: Dict[str, Any], routes: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    wanted = call["path"].split("/")
    best, score = [], -1
    for route in routes:
        have = route["path"].split("/")
        if route["method"] != call["method"] or len(have) != len(wanted):
            continue
        if not all(a == b or b == "{}" for a, b in zip(wanted, have)):
            continue
        exact = sum(1 for a, b in zip(wanted, have) if a == b)
        if exact > score:
            best, score = [route], exact
        elif exact == score:
            best.append(route)
    return best


def census(sources: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """Every window a screen can load: keyed by what it is, never by line."""
    schemas = ast.parse(_read(APP_DIR / "schemas.py", sources))
    shared = {node.name: node for node in schemas.body if isinstance(node, ast.ClassDef)}
    routes: List[Dict[str, Any]] = []
    for path in sorted(APP_DIR.glob("*.py")):
        try:
            routes += routes_in(path.stem, _read(path, sources), shared)
        except SyntaxError:
            continue
    texts = {str(path.relative_to(FRONTEND_SRC)).replace("\\", "/"): _read(path, sources)
             for path in sorted(FRONTEND_SRC.rglob("*"))
             if path.suffix in (".ts", ".tsx") and not path.name.endswith(".d.ts")}
    return dict(windows_from(texts, routes), routes=len(routes))


def windows_from(texts: Dict[str, str], routes: List[Dict[str, Any]]) -> Dict[str, Any]:
    """The census of loaded windows, from frontend sources by label and the routes they can call."""
    items: Dict[str, Dict[str, Any]] = {}
    unlinked: List[str] = []
    seen: Counter = Counter()
    calls = [call for label, source in texts.items() for call in requests_in(label, source)]
    helpers = {call["helper"][0]: (call["helper"][1], call) for call in calls if call["helper"]}
    calls = [call for call in calls if not call["helper"]] + [
        call for label, source in texts.items() for call in helper_calls(label, source, helpers)]
    for call in sorted(calls, key=lambda call: (call["file"], call["line"])):
        label = call["file"]
        matched = _match_routes(call, routes)
        asked = [(name, value) for name, value in list(call["query"].items()) + list(call["body"].items())
                 if _LIMIT_NAME.match(name) and value is not None]
        for name, value in asked:
            key = f"request:{label}::{call['declaration']}::{call['method']} {call['path']}::{name}"
            seen[key] += 1
            key = key if seen[key] == 1 else f"{key}#{seen[key]}"
            items[key] = {"kind": "request", "value": value, "at": f"{label}:{call['line']}"}
            if not matched:
                unlinked.append(key)
        for route in matched:
            for name, (value, where) in route["defaults"].items():
                passed = name in call["query"] or name in call["body"]
                known = call["query_known"] if where == "query" else call["body_known"]
                if passed or not known or (where == "body" and call["method"] == "GET"):
                    continue
                key = f"default:{route['method']} {route['path']}::{name}"
                item = items.setdefault(key, {"kind": "default", "value": value, "at": f"{route['module']}.{route['function']}", "via": []})
                item["via"].append(f"{label}:{call['line']}")
            for key in route["caps"]:
                item = items.setdefault(key, {"kind": "cap", "at": f"{route['method']} {route['path']}", "via": []})
                item["via"].append(f"{label}:{call['line']}")
    return {"items": dict(sorted(items.items())), "unlinked": sorted(unlinked)}


# Every loaded window, claimed once. A window is `stated` by a browser test that reads its note, a `gap`
# held by name in the baseline, or `na` with a reason -- the evasion path, so a new one fails. The census
# above says what exists; this says what each one is, as `audit_movement_contract` does for moves.
WINDOWS: Dict[str, Dict[str, Any]] = {
    # --- stated: a note on the screen, and a browser test that reads it ----------------------------------
    "ops-feed": {
        "claims": ["request:api/opsApi.ts::listOpsEvents::GET /ops/events::limit"],
        "screen": "workspaces/OpsWorkspace.tsx", "note": "of {held.toLocaleString()} events",
        "state": {"stated": "truncation-sites.spec.ts::the feed says so when the server holds more events than it loaded"}},
    "job-telemetry": {
        "claims": ["request:api/controlPanelApi.ts::listRuntimeJobs::GET /runtime/observability/jobs::limit"],
        "screen": "workspaces/ControlPanel.tsx", "note": "Loaded {jobsWindow}",
        "state": {"stated": "grid-sites.spec.ts::job telemetry says it holds the latest 50, and a cost sort says it ranks only those"}},
    "contract-violations": {
        "claims": ["cap:pipeline_builder_ops._execute_ontology_contract::violations[:100]"],
        "screen": "workspaces/PipelineBuilder.tsx", "note": "of {contract.rejected_rows.toLocaleString()} rejected rows",
        "state": {"stated": "truncation-sites.spec.ts::the contract panel's issues can all be read, and it says when the contract kept fewer"}},
    "extension-runs": {
        "claims": ["default:GET /api/v1/plugins/{}/executions::limit"],
        "screen": "workspaces/ControlPanel.tsx", "note": "of {executionTotal.toLocaleString()} runs",
        "state": {"stated": "truncation-sites.spec.ts::an extension's run list says how many runs it has"}},
    "fetch-attempts": {
        "claims": ["default:GET /connections/sources/{}/fetch-attempts::limit"],
        "screen": "App.tsx", "note": "of {fetchAttemptTotal.toLocaleString()} fetch attempts",
        "state": {"stated": "truncation-sites.spec.ts::Fetch Evidence says when the source holds more attempts than it loaded"}},
    "import-jobs": {
        "claims": ["default:GET /imports/jobs::limit"],
        "screen": "App.tsx", "note": "of {(jobs.value?.total ?? 0).toLocaleString()} import jobs",
        "state": {"stated": "truncation-sites.spec.ts::Data Onboarding counts every import job and says the recent list is a window"}},
    "vertex-seeds": {
        "claims": ["request:api/vertexApi.ts::searchSeedObjects::POST /object-sets/search::limit"],
        "screen": "workspaces/Vertex.tsx", "note": "of {seedTotal.toLocaleString()} objects",
        "state": {"stated": "truncation-sites.spec.ts::Vertex's seed list says how many objects the type holds and reaches every one"}},
    "decision-scope": {
        "claims": ["request:api/decisionApi.ts::evaluateDecision::POST /decision/evaluate::limit"],
        "screen": "workspaces/DecisionWorkspace.tsx", "note": "active objects, by id",
        "state": {"stated": "truncation-sites.spec.ts::the Risk Board says so when the server's ceiling cut the scope it scored"}},
    "risk-board-findings": {
        "claims": ["request:api/decisionApi.ts::evaluateDecision::POST /decision/evaluate::finding_limit"],
        "screen": "workspaces/DecisionWorkspace.tsx", "note": "highest-risk of",
        "state": {"stated": "truncation-sites.spec.ts::the Risk Board scores the whole type, counts every scored object, and says how much it lists"}},
    "entity-resolution": {
        "claims": ["request:api/decisionApi.ts::createEntityJob::POST /entity-resolution/jobs::limit"],
        "screen": "workspaces/DecisionWorkspace.tsx", "note": "Pairs involving the other",
        "state": {"stated": "truncation-sites.spec.ts::the Candidate Review Queue compares the first 1,000 in full, pairs every object on an exact value, and says so"}},
    "reliability-runs": {
        "claims": ["cap:reliability_ops.reliability_summary::.limit(25)"],
        "screen": "workspaces/OpsWorkspace.tsx", "note": "of {held.toLocaleString()} contract runs",
        "state": {"stated": "truncation-sites.spec.ts::the Reliability tab says what its counts cover and lists every run it loaded"}},
    "pipeline-node-preview": {
        "claims": ["request:api/workspaceState.ts::previewPipelineNode::POST /pipeline-builder/graphs/{}/nodes/{}/preview::limit",
                   "cap:pipeline_builder_ops._execute_graph::rows[:5]"],
        "screen": "components/canvas/PipelineCanvas.tsx", "note": "Previewing the first",
        "state": {"stated": "truncation-sites.spec.ts::the pipeline drawer previews the rows it asks for and says how many the node holds"}},
    # --- gaps: a screen draws part of a set as the set -----------------------------------------------------
    "mapping-preview": {
        "claims": ["request:api/workspaceState.ts::previewOntologyMapping::POST /ontology/mappings/preview::limit"],
        "screen": "workspaces/OntologyManager.tsx", "note": "of ${preview.asset.row_count.toLocaleString()} rows",
        "state": {"stated": "truncation-sites.spec.ts::the mapping preview says it hydrates only the first rows of a larger dataset"}},
    "live-connector-preview": {
        "claims": ["request:api/connectorApi.ts::previewLiveConnector::POST /connections/sources/{}/live-preview::limit"],
        "screen": "App.tsx", "note": "The preview stops at {LIVE_PREVIEW_LIMIT}",
        "state": {"stated": "truncation-sites.spec.ts::a full live connector preview says it stopped at its limit"}},
    "artifact-preview": {
        "claims": ["request:api/artifactApi.ts::previewArtifact::POST /artifacts/{}/preview::sample_limit"],
        "screen": "workspaces/VisualBuilder.tsx",
        "state": {"gap": "the server keeps a preview's first 20 nodes and the builder lists 6 of them beside the node count, with nothing said"}},
    "explorer-objects": {
        "claims": ["request:workspaces/ObjectExplorer.tsx::ObjectExplorer::POST /object-explorer/query::limit"],
        "screen": "workspaces/ObjectExplorer.tsx",
        "state": {"gap": "the results count is the length of the 500 objects loaded; not fixed, by the cost decision recorded under N5"}},
    "object-profile-links": {
        "claims": ["default:GET /objects/{}/{}/profile::linked_limit"],
        "screen": "workspaces/ObjectExplorer.tsx",
        "state": {"gap": "an object's profile counts its linked objects from the 50 the server returns"}},
    "map-features": {
        "claims": ["request:api/gisApi.ts::loadLayerFeatures::GET /gis/map-layers/{}/features::limit",
                   "request:api/gisApi.ts::loadTypeFeatures::POST /gis/feature-collection::limit"],
        "screen": "workspaces/MapWorkspace.tsx", "note": "The map and this list show only these.",
        "state": {"stated": "truncation-sites.spec.ts::the map says how many features a type holds, lists them all on request, and counts a geofence past its limit"}},
    "geofence": {
        "claims": ["request:api/gisApi.ts::evaluateGeofence::POST /gis/geofence/evaluate::limit"],
        "screen": "workspaces/MapWorkspace.tsx",
        "state": {"na": "the screen draws only a geofence's inside and outside counts, which cover every object; the lists it keeps are not drawn"}},
    "platform-graph": {
        "claims": ["request:workspaces/PlatformGraph.tsx::PlatformGraphWorkspace::GET /graph/overview::limit"],
        "screen": "workspaces/PlatformGraph.tsx", "note": "cover only what was loaded",
        "state": {"stated": "truncation-sites.spec.ts::the platform graph says which kinds it loaded only part of"}},
    "command-center-counts": {
        "claims": ["cap:asset_reliability_scenario._open_alerts::.limit(20)",
                   "cap:asset_reliability_scenario._open_approvals::.limit(20)",
                   "cap:asset_reliability_scenario._incidents::.limit(20)"],
        "screen": "App.tsx",
        "state": {"gap": "Open alerts, Open approvals and the section cards' incident counts count the 20 the scenario loads, so none reads past 20"}},
    "imports-warnings": {
        "claims": ["cap:imports_ops.imports_ui_state::.limit(50)"],
        "screen": "App.tsx",
        "state": {"gap": "Data Onboarding's validation warnings are built from the latest 50 import jobs and drawn as the warnings"}},
    "ops-latest-incidents": {
        "claims": ["cap:ops_control.ops_summary::open_incidents[:10]"],
        "screen": "workspaces/OpsWorkspace.tsx",
        "state": {"gap": "Latest incidents lists up to 10 open incidents with nothing said"}},
    "contract-run-history": {
        "claims": ["cap:pipeline_builder_ops.ontology_contract_ui_state::.limit(50)"],
        "screen": "workspaces/PipelineBuilder.tsx",
        "state": {"gap": "each node's latest contract run and the summary status come from the 50 newest runs, so an older node drops out"}},
    "pipeline-output-builds": {
        "claims": ["cap:pipeline_builder_ops._canvas_payload::.limit(5)"],
        "screen": "workspaces/PipelineBuilder.tsx",
        "state": {"gap": "Pipeline Outputs draws the 5 builds the canvas loads, with nothing said"}},
    # --- not applicable: nothing a person reads as a set -----------------------------------------------------
    "alert-evaluation": {
        "claims": ["request:api/opsApi.ts::evaluateAlerts::POST /ops/alerts/evaluate::limit"],
        "screen": "workspaces/OpsWorkspace.tsx",
        "state": {"na": "a batch size for rule evaluation; the screen says the rules ran and draws nothing from the reply"}},
    "agent-runs": {
        "claims": ["default:GET /aip/agents/{}/runs::limit"],
        "screen": "api/agentApi.ts",
        "state": {"na": "listAgentRuns has no caller; no screen draws an agent's runs"}},
    "pipeline-plan-execute": {
        "claims": ["default:POST /api/v1/pipeline-plans/{}/execute::limit"],
        "screen": "workspaces/PipelineBuilder.tsx",
        "state": {"na": "it bounds the rows a queued preview job computes; the builder shows the job's status, not its rows"}},
    "workflow-audit-rows": {
        "claims": ["cap:asset_reliability_scenario._workflow_state::.limit(100)"],
        "screen": "App.tsx",
        "state": {"na": "the audit rows only decide whether a report was exported"}},
    "transform-preview-rows": {
        "claims": ["cap:imports_ops._apply_transform_steps::rows[:25]"],
        "screen": "App.tsx",
        "state": {"na": "the screen keeps the transformed job, and shows its row count and errors, not its preview rows"}},
    "imports-evidence-links": {
        "claims": ["cap:imports_ops.imports_ui_state::jobs[:12]", "cap:imports_ops.imports_ui_state::promoted_jobs[:12]"],
        "screen": "App.tsx",
        "state": {"na": "they fill the imports state's evidence_links, which Data Onboarding does not render"}},
    "modelops-summary": {
        "claims": ["cap:modelops.modelops_summary::.limit(20)", "cap:modelops.modelops_summary::latest_runs[:5]"],
        "screen": "workspaces/ModelOps.tsx",
        "state": {"na": "latest_runs and latest_monitor_status are typed and never rendered; the screen shows counts"}},
    "generated-name": {
        "claims": ["cap:ontology_generator._pascal::result[:100]"],
        "screen": "workspaces/OntologyManager.tsx",
        "state": {"na": "a generated name cut to 100 characters, not a set"}},
    "ops-summary-unrendered": {
        "claims": ["cap:ops_control.ops_summary::.limit(10)", "cap:ops_control.ops_summary::.limit(10)#2",
                   "cap:ops_control.ops_summary::open_alerts[:10]"],
        "screen": "workspaces/OpsWorkspace.tsx",
        "state": {"na": "failed_pipelines, latest_events and latest_alerts are never rendered; the feed loads /ops/events"}},
    "reliability-summary-unrendered": {
        "claims": ["cap:reliability_ops.reliability_summary::.limit(10)", "cap:reliability_ops.reliability_summary::.limit(10)#2"],
        "screen": "workspaces/OpsWorkspace.tsx",
        "state": {"na": "latest_backfills and latest_impacts are never rendered"}},
}


# Where a screen states a window: a note, a table's caption, or a disclosure's summary heading.
_STATEMENT_OPEN = re.compile(r"<(summary|caption)\b|<(\w+)\b[^<>]*?\brole=[\"']note[\"']")


def _statement_markup(body: str) -> str:
    """Every element in `body` that can state a window, joined."""
    parts = []
    for match in _STATEMENT_OPEN.finditer(body):
        start = match.start()
        parts.append(body[start:_element_end(body, start, match.group(1) or match.group(2))])
    return "\n".join(parts)


def _state_kind(state: Any) -> str:
    return next(iter(state)) if isinstance(state, dict) and len(state) == 1 else ""


def proof_missing(reference: str) -> str:
    """Empty when the named browser test exists and still carries that title."""
    if "::" not in reference:
        return "names no browser test"
    spec_name, title = reference.split("::", 1)
    spec = SPECS / spec_name
    if not spec.exists():
        return f"names {spec_name}, which does not exist"
    if title not in spec.read_text(encoding="utf-8"):
        return f"names a test titled {title!r} that {spec_name} no longer contains"
    return ""


def window_problem(window: Any, sources: Optional[Dict[str, str]] = None) -> str:
    """Empty when a window's state is well formed and, if stated, its test and its note exist."""
    state = window.get("state") if isinstance(window, dict) else None
    kind = _state_kind(state)
    if kind not in ("stated", "gap", "na"):
        return "must be exactly one of stated, gap or na"
    value = state[kind]
    if not isinstance(value, str) or not value.strip():
        return f"is `{kind}` with nothing said"
    if kind != "stated":
        return ""
    missing = proof_missing(value)
    if missing:
        return f"is stated and {missing}"
    screen = FRONTEND_SRC / str(window.get("screen", ""))
    if not window.get("screen") or not screen.is_file():
        return f"is stated on {window.get('screen')!r}, which is not a frontend file"
    fragment = window.get("note")
    if not isinstance(fragment, str) or not fragment.strip():
        return "is stated and names no note: the text its note, caption or summary renders"
    if fragment not in _statement_markup(_read(screen, sources)):
        return (f"is stated and no note, caption or summary in {window['screen']} holds {fragment!r}: "
                f"it states nothing on screen")
    return ""


def scan(sources: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """Every truncation in the frontend, every slice that is not one, and why."""
    files: Dict[str, Dict[str, Any]] = {}
    tables = 0
    paths = sorted(path for path in FRONTEND_SRC.rglob("*")
                   if path.suffix in (".ts", ".tsx") and not path.name.endswith(".d.ts"))
    for path in paths:
        label = str(path.relative_to(FRONTEND_SRC)).replace("\\", "/")
        text = _read(path, sources)
        here = len(_TABLE.findall(text))
        tables += here
        cuts = cuts_in(text)
        others = others_in(text)
        if here or cuts or others:
            files[label] = {"tables": here, "cuts": cuts, "others": others}
    return {"files": files, "tables": tables, "windows": census(sources), "sources": dict(sources or {})}


def _named(found: Dict[str, Any]) -> List[Tuple[str, Dict[str, Any], str]]:
    """(file, cut, name) for every cut. A second cut of one source in one declaration is `#2`."""
    seen: Counter = Counter()
    named = []
    for file, entry in sorted(found["files"].items()):
        for cut in entry["cuts"]:
            key = cut_name(file, cut)
            seen[key] += 1
            named.append((file, cut, key if seen[key] == 1 else f"{key}#{seen[key]}"))
    return named


def _windows(found: Dict[str, Any], windows: Optional[Dict[str, Dict[str, Any]]]) -> Dict[str, Dict[str, Any]]:
    """The registry judged against a scan; a scan with no census, as in a synthetic test, has none."""
    return (WINDOWS if windows is None else windows) if "windows" in found else {}


def unfixed_names(found: Dict[str, Any], windows: Optional[Dict[str, Dict[str, Any]]] = None) -> List[str]:
    cuts = [key for _, cut, key in _named(found) if _silent(cut) and key not in DELIBERATE_CUTS]
    gaps = [f"window:{name}" for name, window in _windows(found, windows).items() if _state_kind(window.get("state")) == "gap"]
    return sorted(cuts + gaps)


def declared_na(found: Dict[str, Any], windows: Optional[Dict[str, Dict[str, Any]]] = None) -> List[str]:
    cuts = [key for _, _, key in _named(found) if key in DELIBERATE_CUTS]
    na = [f"window:{name}" for name, window in _windows(found, windows).items() if _state_kind(window.get("state")) == "na"]
    return sorted(cuts + na)


def totals(found: Dict[str, Any]) -> Tuple[int, int, int]:
    """(tables, truncations reaching a table, truncations anywhere left unfixed)."""
    reaching = sum(1 for _, cut, _ in _named(found) if cut["table"])
    return found["tables"], reaching, len(unfixed_names(found))


def silent_per_file(found: Dict[str, Any]) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for file, cut, key in _named(found):
        if _silent(cut) and key not in DELIBERATE_CUTS:
            counts[file] = counts.get(file, 0) + 1
    return dict(sorted(counts.items()))


def _cut_rows(cuts: List[Tuple[str, Dict[str, Any]]], emphasise: bool) -> List[str]:
    lines = ["| File | Line | In | Cuts | How | Into a paging table | True count rendered |",
             "| --- | --- | --- | --- | --- | --- | --- |"]
    for name, cut in cuts:
        counted = "yes" if cut["counted"] else ("**no**" if emphasise else "no")
        paging = ("**yes**" if emphasise else "yes") if cut["paging"] else "no"
        lines.append(f"| `{name}` | {cut['line']} | `{cut['declaration']}` | "
                     f"`{cut['source']}` ({cut['spelling']}) | {cut['how']} | {paging} | {counted} |")
    return lines


def _list_rows(cuts: List[Tuple[str, Dict[str, Any]]]) -> List[str]:
    lines = ["| File | Line | In | Cuts | How | Note from the true total | Rest reachable |",
             "| --- | --- | --- | --- | --- | --- | --- |"]
    for name, cut in cuts:
        lines.append(f"| `{name}` | {cut['line']} | `{cut['declaration']}` | `{cut['source']}` ({cut['spelling']}) "
                     f"| {cut['how']} | {'yes' if cut.get('noted') else '**no**'} | {'yes' if cut.get('reachable') else '**no**'} |")
    return lines


def accounting(found: Dict[str, Any]) -> Dict[str, int]:
    """Every `.slice(` found, by what it was read as."""
    slices = [cut for entry in found["files"].values() for cut in entry["cuts"] if cut["spelling"] == "slice"]
    counts = {"placed": sum(1 for cut in slices if cut["how"] != "unplaced"),
              "unplaced": sum(1 for cut in slices if cut["how"] == "unplaced")}
    for entry in found["files"].values():
        for other in entry.get("others", []):
            counts[other["reason"]] = counts.get(other["reason"], 0) + 1
    counts["found"] = sum(counts.values())
    return counts


def render(found: Dict[str, Any], windows: Optional[Dict[str, Dict[str, Any]]] = None) -> str:
    windows = _windows(found, windows)
    tables, reaching, _ = totals(found)
    unfixed = len(unfixed_names(found, windows))
    gaps = sum(1 for window in windows.values() if _state_kind(window.get("state")) == "gap")
    named = _named(found)
    every = [(file, cut) for file, cut, key in named if key not in DELIBERATE_CUTS]
    inside = [(file, cut) for file, cut in every if cut["table"]]
    lists = [(file, cut) for file, cut in every if not cut["table"] and cut["how"] != "unplaced"]
    unplaced = [(file, cut) for file, cut in every if not cut["table"] and cut["how"] == "unplaced"]
    counts = accounting(found)
    lines = [
        "# Tables and lists that show part of what they were given",
        "",
        "Generated by `oms/audit_table_truncation.py`. Do not edit by hand — the gate",
        "regenerates this and fails if it disagrees with the source.",
        "",
        f"**{unfixed} unfixed**: {unfixed - gaps} of {len(every)} truncations and {gaps} of {len(windows)} loaded windows.",
        "",
        "A truncation is unfixed when it renders no true count, cuts rows before a table that would have paged",
        f"them, or shows part of a list with no way to the rest. {reaching} reach one of the {tables} table elements",
        "(`<DataTable>`, `<DataGrid>`, `<table>`, `role=\"table\"` or `role=\"grid\"`) written across the frontend.",
        "A loaded window is unfixed when its screen draws part of a set as the set and says nothing.",
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
        "## Lists, canvases and chips",
        "",
        "A list cut is stated when a `role=\"note\"` element renders the true total -- the source's",
        "length, or a name bound to an expression that includes it -- and the rest can be reached: the",
        "cut is taken only behind a `useState` value whose setter a `<button>` calls. A count with no",
        "way to the rest names items nobody can reach.",
        "",
    ]
    lines += _list_rows(lists) if lists else ["None."]
    lines += ["", "## Found and not placed", "",
              "A cut whose result this could not follow into a list, a table or a binding. Each is gated by",
              "name until it is placed, fixed or declared.", ""]
    lines += _list_rows(unplaced) if unplaced else ["None."]
    items = found.get("windows", {}).get("items", {})
    lines += [
        "",
        "## Loaded windows",
        "",
        "Every request limit a screen sends, every server default a request reaches by leaving the limit out, and",
        "every fixed cap on a route a screen calls, each claimed by one window. A stated window names the browser",
        "test that reads its note; whether that note's condition matches the limit is the test's to prove.",
        "",
        "| Window | Screen | Claims | State | Evidence |",
        "| --- | --- | --- | --- | --- |",
    ]
    labels = {"stated": "stated", "gap": "**gap**", "na": "n/a"}
    for name, window in sorted(windows.items()):
        kind = _state_kind(window.get("state"))
        claims = "<br>".join(f"`{key}`" + (f" = {items[key]['value']}" if "value" in items.get(key, {}) else "")
                             for key in window.get("claims", []))
        evidence = window["state"][kind] if kind else ""
        if kind == "stated":
            evidence = f"`{evidence.replace('::', '` — ')}"
        lines.append(f"| `{name}` | `{window.get('screen', '')}` | {claims} | {labels.get(kind, '**malformed**')} | {evidence} |")
    claimed = {key for window in windows.values() for key in window.get("claims", [])}
    for key in sorted(set(items) - claimed):
        lines.append(f"| **unclaimed** | | `{key}` | **unclaimed** | {items[key].get('at', '')} |")
    lines += ["", "## Declared not a list", ""]
    declared = [key for key in declared_na(found, windows) if key in DELIBERATE_CUTS]
    lines += [f"- `{key}`: {DELIBERATE_CUTS[key]}" for key in declared] if declared else ["None."]
    lines += [
        "",
        "## Read as text, a prefix, a last item or a request payload",
        "",
        f"{counts['found']} `.slice(` calls found: {counts['placed']} placed as collection cuts, "
        f"{counts.get('text', 0)} text, {counts.get('prefix dropped', 0)} a prefix dropped, "
        f"{counts.get('last dropped', 0)} a last item dropped, {counts.get('request payload', 0)} a request payload, "
        f"and {counts['unplaced']} not placed.",
        "",
        "| File | Line | In | Slice of | Read as |",
        "| --- | --- | --- | --- | --- |",
    ]
    for file, entry in sorted(found["files"].items()):
        for other in entry.get("others", []):
            lines.append(f"| `{file}` | {other['line']} | `{other['declaration']}` | `{other['source']}` | {other['reason']} |")
    lines += [
        "",
        "## What this does not see",
        "",
        "- `oms/app/ui/app.js`, the legacy screens, which make some of the same requests outside `frontend/src`;",
        "- a cap computed by an expression (`min(limit * 3, 1000)`) or taken from a variable (`.limit(limit)`);",
        "- a cap in a helper another module defines, or more than three calls below the route;",
        "- a request whose path or body is assembled away from the call, whose limit is not read;",
        "- a cut passed down to a child component declared in another file;",
        "- whether a note's condition matches its window, which the named browser test proves.",
        "",
    ]
    return "\n".join(lines)


def compare(found: Dict[str, Any], baseline: Dict[str, Any],
            windows: Optional[Dict[str, Dict[str, Any]]] = None) -> Tuple[bool, List[str], List[str]]:
    failures: List[str] = []
    notes: List[str] = []
    windows = _windows(found, windows)
    current = unfixed_names(found, windows)
    ceiling = baseline.get("unfixed")
    held = set(baseline.get("unfixed_names", []))
    recorded: Dict[str, int] = baseline.get("per_file", {})

    if ceiling is None:
        failures.append("the baseline records no unfixed count; re-run with --set-baseline")
    elif len(current) > ceiling:
        failures.append(
            f"{len(current)} unfixed truncation(s), up from {ceiling}. A table that drops rows or columns "
            f"must render the length of what it cut, rows for DataTable or DataGrid must not be cut at all, "
            f"and a list must say how much it shows and let the rest be reached.")
    elif len(current) < ceiling:
        notes.append(f"unfixed truncations {ceiling} -> {len(current)}; re-run with --set-baseline")
    for key in current:
        if key not in held:
            failures.append(f"{key} is an unfixed truncation the baseline does not hold -- not placed, "
                            f"silent, or new")
    for key in sorted(held - set(current)):
        notes.append(f"{key} is no longer found unfixed")
    for key in declared_na(found, windows):
        if key not in set(baseline.get("na", [])):
            failures.append(f"{key} is newly declared not applicable. That is the cheapest way to lower this "
                            f"count, so it is an edit to the baseline made in the open.")

    if "windows" in found:
        items = found["windows"]["items"]
        for key in found["windows"]["unlinked"]:
            failures.append(f"{key} is a request limit whose route this cannot find")
        claimed = Counter(key for window in windows.values() for key in window.get("claims", []))
        for key in items:
            if not claimed[key]:
                failures.append(f"{key} is a loaded window no entry in WINDOWS claims: say whether its screen "
                                f"states it, or name the gap")
            elif claimed[key] > 1:
                failures.append(f"{key} is claimed by {claimed[key]} windows")
        for name, window in windows.items():
            for key in window.get("claims", []) if isinstance(window, dict) else []:
                if key not in items:
                    failures.append(f"window:{name} claims {key}, which the census no longer finds there")
            problem = window_problem(window, found.get("sources"))
            if problem:
                failures.append(f"window:{name} {problem}")

    for name, now in silent_per_file(found).items():
        was = recorded.get(name, 0)
        if now > was:
            failures.append(f"{name}: {was} -> {now} unfixed truncation(s)"
                            + ("" if was else " — this file had none"))

    if not REFERENCE.exists():
        failures.append(f"{REFERENCE.relative_to(REPO_ROOT)} is missing; regenerate with --write")
    elif REFERENCE.read_text(encoding="utf-8") != render(found, windows):
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
    tables, reaching, unfixed = totals(found)
    print(f"{tables} table element(s); {reaching} truncation(s) reach one; {unfixed} unfixed in all\n")
    for name, count in Counter(silent_per_file(found)).most_common(8):
        print(f"  {count:>2} unfixed  {name}")

    if args.write:
        REFERENCE.write_text(render(found), encoding="utf-8")
        print(f"\nWrote {REFERENCE.relative_to(REPO_ROOT)} ({unfixed} unfixed).")
        return 0

    if args.set_baseline:
        BASELINE.write_text(json.dumps({
            "provenance": {"stale_after": "recomputed each run"},
            "note": ("Truncations left unfixed, by name: a table cut with no true count or before a table "
                     "that pages, a list cut that does not say how much it shows and let the rest be "
                     "reached, and a cut nobody placed. The count may fall and must never rise, and a "
                     "name not held here fails. A name under `na` was declared not a list on purpose."),
            "unfixed": unfixed,
            "unfixed_names": unfixed_names(found),
            "per_file": silent_per_file(found),
            "na": declared_na(found),
        }, indent=2) + "\n", encoding="utf-8")
        print(f"\nBaseline set: {unfixed} unfixed.")
        return 0

    if not BASELINE.exists():
        print(f"\nNo baseline at {BASELINE.relative_to(REPO_ROOT)}. Record one with --set-baseline.")
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
    print(f"\nNo truncation was added unfixed. {unfixed} remain, each named, and the count may only fall.")
    return 0


if __name__ == "__main__":
    from enforcement_runs import recording

    raise SystemExit(recording("audit_table_truncation", main))

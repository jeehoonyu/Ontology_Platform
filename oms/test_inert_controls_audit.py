"""A control that does nothing must trip the rule, and a working one must not.

Also this check's home: `audit_inert_controls` declares `every suite run`.

The reason this file exists at all is that a census reporting "0 inert" is worth
nothing until the rule has been shown to refuse something. The assertions below
run the real matchers over synthetic tags, so the number in
`docs/INERT_CONTROLS.md` means "none matched a rule that matches" rather than
"none matched a rule that matches nothing".

The most valuable assertions here are the last two groups. One holds that a
control which merely *looks* wired -- `onClick={() => {}}` -- is still counted,
because that is the single edit that would make this gate report a falsehood.
The other holds that the wired spellings really are excused, because a gate that
refuses working code gets deleted rather than obeyed.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from audit_inert_controls import (  # noqa: E402
    _KEYED, _NOOP, _WIRED, BASELINE, REFERENCE, _tags, compare, render, scan, totals,
)

checks = 0


def check(condition, message):
    global checks
    assert condition, message
    checks += 1


def attributes_of(tag):
    """The attribute text the scan would read off one opening tag."""
    found = list(_tags(tag))
    assert found, f"the tag rule does not see {tag!r} as a control at all"
    return found[0][3]


def is_inert(tag):
    attributes = attributes_of(tag)
    return not _WIRED.search(attributes) or bool(_NOOP.search(attributes))


found = scan()
controls, inert, repeated = totals(found)

# --- the rule sees controls at all --------------------------------------------
check(controls > 200, f"only {controls} controls found; the tag rule is not matching")
check(len(found["files"]) > 20, f"only {len(found['files'])} files have controls")

# --- a control with nothing on it is inert ------------------------------------
check(is_inert("<button>Fit</button>"), "a bare button reads as wired")
check(is_inert('<button title="Zoom in">+</button>'),
      "a title is not an action; a tooltip on a dead button is the defect, not the excuse")
check(is_inert('<button className="active">Guide</button>'),
      "a class that draws a selected state does not make the control select anything")
check(is_inert("<a>Open in</a>"), "an anchor with no href goes nowhere")

# --- an opening tag broken across lines is still one control ------------------
check(is_inert('<button\n  className="tab"\n  title="Preview"\n>'),
      "a multi-line opening tag is missed, so any dead control can hide by wrapping")

# --- a wired control is not counted -------------------------------------------
check(not is_inert("<button onClick={run}>Run</button>"), "onClick is not recognised")
check(not is_inert('<button type="submit">Save</button>'),
      "a form's submit button has an action by being one")
check(not is_inert('<a href="/workspace/map">Map</a>'), "an href is not recognised")
check(not is_inert("<button {...listeners} {...attributes}>"),
      "a spread is how `DragHandle` receives dnd-kit's listeners; refusing it would "
      "make every grip in the product read as dead")
check(not is_inert('<button disabled title="Select a dataset first">Run</button>'),
      "the criterion is 'works or explains why unavailable', and `disabled` explains")
check(not is_inert("<button disabled={!ready}>Run</button>"), "an expression-valued disabled is not recognised")
# `aria-disabled` leaves the control focusable and clickable, so it explains nothing
# on its own: a press has to do something. The hyphen is a word boundary, and the
# first version of the rule read `aria-disabled=` as `disabled`.
# --- a control the walk cannot read is counted, not lost ------------------------
# N7c's `Clear filters` had `// ... the filters' summary.` in its handler. The
# apostrophe opened a quote that never closed, and the button vanished from the
# census without a word. Each of these tags must be found exactly once.
commented = "<button type=\"button\" onClick={() => {\n  reset();\n  // focus goes to the filters' summary\n  focus();\n}}>Clear filters</button>"
check(len(list(_tags(commented))) == 1, "an apostrophe in a // comment inside a handler hides the button from the census")
check(not is_inert(commented), "a handler with a commented apostrophe reads as inert")
block = "<button onClick={() => { /* it's the reset */ reset(); }}>Reset</button>"
check(len(list(_tags(block))) == 1 and not is_inert(block), "an apostrophe in a block comment hides the button")
template = "<button aria-label={`Clear ${column}'s filter`} onClick={clear}>Clear</button>"
check(len(list(_tags(template))) == 1 and not is_inert(template),
      "an apostrophe inside a template literal hides the button")
unterminated = "<button onClick={() => { run(\"x) }>Run</button>"
check(len(list(_tags(unterminated))) == 1 and is_inert(unterminated),
      "a tag the walk cannot close is dropped instead of counted as a control nobody can show is wired")
# ...and a slash that only looks like a comment does not start one.
escaped = '<button onClick={() => setPath(path.replace(/^\\/*\\s+/, ""))}>Trim</button>'
check(len(list(_tags(escaped))) == 1 and not is_inert(escaped),
      "an escaped slash before a star, in a regex, is read as a comment and turns a wired button inert")
bracketed = '<button onClick={() => setKey(key.replace(/[/*]\\d+/g, ""))}>Clean</button>'
check(len(list(_tags(bracketed))) == 1 and not is_inert(bracketed),
      "a slash and star inside a regex character class are read as a comment and turn a wired button inert")
divided = "<button onClick={() => setRatio(width / 2 / scale)}>Halve</button>"
check(len(list(_tags(divided))) == 1 and not is_inert(divided), "division is read as a comment")

check(is_inert("<button aria-disabled={atEdge}>Later</button>"),
      "aria-disabled passes as wired, so a focusable button that does nothing when pressed is not counted")
check(not is_inert("<button aria-disabled={atEdge} onClick={() => move(column, 1)}>Later</button>"),
      "an aria-disabled button with a handler reads as inert")
check(not is_inert("<button onPointerDown={start}>"), "onPointerDown is not recognised")

# --- and the one edit that would make this gate lie ---------------------------
# Every rule above is satisfied by `onClick={() => {}}`. If that passed, the
# cheapest way to clear this gate would be to add a handler that does nothing,
# and the census would then report a number that is wrong rather than high.
check(is_inert("<button onClick={() => {}}>Fit</button>"),
      "an empty arrow handler passes as wired -- this is the gate's own evasion path")
check(is_inert("<button onClick={() => undefined}>Fit</button>"),
      "a handler returning undefined passes as wired")
check(is_inert("<button onClick={()=>{ }}>Fit</button>"),
      "whitespace inside the empty body defeats the no-op rule")
check(is_inert("<button onClick={noop}>Fit</button>"), "a named no-op passes as wired")
check(not is_inert("<button onClick={() => setTab(item)}>"),
      "a handler with a body reads as empty")

# --- a repeated site is reported as repeated ----------------------------------
check(_KEYED.search(' key={tab} className="tab"'), "the list marker misses `key=`")
check(not _KEYED.search(' className="monkey"'),
      "`key` matches inside another word, so ordinary attributes read as list items")
check(repeated == sum(1 for entry in found["files"].values()
                      for site in entry["inert"] if site["repeats"]),
      "the repeating count disagrees with the sites it counts")

# --- rendering is a pure function of the scan ---------------------------------
text = render(found)
check(render(found) == text, "rendering twice gives the same bytes")
check(f"**{inert} of {controls}**" in text, text[:300])
for name, entry in found["files"].items():
    for site in entry["inert"]:
        check(f"| `{name}` | {site['line']} |" in text,
              f"{name}:{site['line']} is inert and missing from the reference")

# --- the ratchet refuses a rise, in total and per file ------------------------
# The live tree is at zero, so `inert - 1` is no longer a lower ceiling and
# these would pass for the wrong reason if they read it. They run on a synthetic
# scan, which is what they were always asking about: whether the rule refuses,
# not what today's number happens to be.
def synthetic(count, name="workspaces/Made.tsx"):
    sites = [{"line": 10 + index, "tag": "button", "label": f"Dead {index}",
              "repeats": index == 0, "noop": False} for index in range(count)]
    return {"files": {name: {"controls": count + 3, "inert": sites}}, "controls": count + 3}

two = synthetic(2)
ok, failures, _ = compare(two, {"inert": 1, "per_file": {"workspaces/Made.tsx": 2}})
check(not ok and any("up from" in f for f in failures),
      f"the total is not a ceiling: {failures}")

ok, failures, _ = compare(two, {"inert": 2, "per_file": {}})
check(not ok and any("this file had none" in f for f in failures),
      f"a file gaining its first inert control is not refused: {failures}")

# The per-file rule has to fire even when the total does not, because one file
# losing a control and another gaining one leaves the total unmoved.
ok, failures, _ = compare(two, {"inert": 2, "per_file": {"workspaces/Made.tsx": 1,
                                                         "workspaces/Gone.tsx": 1}})
check(not ok and any("1 -> 2" in f for f in failures),
      f"a swap that keeps the total level is not refused: {failures}")

# ...and a repeating site is rendered as such, whether or not the tree has one.
check("once per item" in render(synthetic(1)),
      "a control inside a list is not marked as repeating in the reference")

ok, _, _ = compare(found, {"inert": inert, "per_file": {n: len(e["inert"])
                                                        for n, e in found["files"].items()
                                                        if e["inert"]}})
check(ok, "the current tree fails its own baseline")

check(BASELINE.exists(), f"no baseline at {BASELINE}")
check(REFERENCE.exists(), f"no reference at {REFERENCE}")
check(REFERENCE.read_text(encoding="utf-8") == text,
      "the committed reference is stale; run --write")

print(f"Inert control gate verified: {checks} assertions passed "
      f"({inert} of {controls} controls do nothing, {repeated} of them once per item).")

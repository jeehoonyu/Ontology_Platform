"""The style-token gate counts what the browser actually drops, and nothing else.

This is also the check's home: `audit_style_tokens` declares `every suite run`, and
`audit_iteration_state` fails any check whose declared cadence names a place it does
not run.

Each rule below has a case that would pass if the rule were missing. The one that
matters most is the first: `tokens.css` defines every name `styles.css` is missing,
and nothing imports it, so a scan that counted every stylesheet under the source
tree would read zero undefined names on a tree where all 39 declarations are still
dropped. Definitions count only from sheets something imports.
"""
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import audit_style_tokens as audit  # noqa: E402

checks = 0


def check(condition, message):
    global checks
    assert condition, message
    checks += 1


def tree(files):
    """A throwaway frontend: {relative path: text}. Returns (src, index, tokens)."""
    root = Path(tempfile.mkdtemp())
    for name, text in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return root / "src", root / "index.html", root / "src" / "tokens.css"


# --- colours: what counts, and what only looks like a colour -----------------
check(audit.colours_in_css(".a { color: #fff; }") == 1, "#fff is a colour")
check(audit.colours_in_css(".a { color: #ffffff; background: #FFF; }") == 2,
      "#ffffff and #FFF are two literals, however alike")
check(audit.colours_in_css(".a { color: #12345678; border-color: #1234; }") == 2,
      "8- and 4-digit hex are colours")
check(audit.colours_in_css(".a { box-shadow: 0 1px rgba(0, 0, 0, .1), 0 0 hsl(0 0% 0%); }") == 2,
      "rgba() and hsl() are colours")
check(audit.colours_in_css(".a { color: red /* was: #d7dedf */; }") == 0,
      "a hex inside a comment is not in effect and must not count, even inside a value")
check(audit.colours_in_css("#add { color: blue; }") == 0,
      "an id selector that happens to be hex is a selector, not a colour")
check(audit.colours_in_css(".a { marker-end: url(#abc); }") == 0,
      "url(#id) names a fragment, not a colour")
check(audit.colours_in_css("@media (max-width: 700px) { .a { color: #222; } }") == 1,
      "a colour inside a media query still counts")

check(audit.colours_in_ts('const c = { dataset: "#2d72d2" };') == 1, "a hex string counts")
check(audit.colours_in_ts("const c = `rgba(76, 120, 168, ${a})`;") == 1,
      "rgba() in a template string counts")
check(audit.colours_in_ts('// legacy: "#123456"\nconst x = 1;') == 0,
      "a string inside a comment is not code")
check(audit.colours_in_ts('const href = "https://example.com/#facade";') == 1,
      "the TS side is coarse on purpose: a colour-length hex fragment in a string counts "
      "(recorded in the module docstring)")
check(audit.colours_in_ts('const href = "https://example.com/#faded";') == 0,
      "five hex digits is not a colour length, so #faded does not count")
check(audit.colours_in_ts('const u = "https://x.test/a"; // #fff') == 0,
      "// inside a URL string must not start a comment, and a trailing comment is not code")

# --- custom properties: live sheets define, unimported sheets do not ----------
src, index, tokens = tree({
    "src/main.tsx": 'import "./styles.css";\n',
    "src/styles.css": ".a { border: 1px solid var(--border); color: var(--muted, #555); }\n",
    "src/tokens.css": ":root { --border: #ccc; }\n",
    "index.html": "<html></html>\n",
})
found = audit.scan(src, index, tokens)
check(found["undefined"].get("--border") == {"src/styles.css": 1},
      f"tokens.css is not imported, so --border is undefined: {found['undefined']}")
check("--muted" not in found["undefined"] and found["fallback"] == {"--muted": 1},
      "a reference with a fallback renders and is reported, not counted")
check(found["tokens_live"] is False, "nothing imports tokens.css")

src, index, tokens = tree({
    "src/main.tsx": 'import "./tokens.css";\nimport "./styles.css";\n',
    "src/styles.css": ".a { border: 1px solid var(--border); }\n",
    "src/tokens.css": ":root { --border: #ccc; }\n",
    "index.html": "<html></html>\n",
})
found = audit.scan(src, index, tokens)
check(found["undefined"] == {}, "once imported, tokens.css defines --border")
check(found["tokens_live"] is True, "tokens.css is imported")
check(audit.totals(found)[2] == 0, "a colour inside tokens.css is the table, not a raw literal")

src, index, tokens = tree({
    "src/main.tsx": 'import "./styles.css";\n',
    "src/Pane.tsx": 'const s = { "--slot-width": `${size}px` };\n',
    "src/styles.css": ".a { width: var(--slot-width); }\n",
    "index.html": "<html></html>\n",
})
check(audit.scan(src, index, src / "tokens.css")["undefined"] == {},
      "a name a component sets inline is defined")

src, index, tokens = tree({
    "src/main.tsx": "export {};\n",
    "src/styles.css": ".a { color: var(--x); }\n",
    "index.html": '<link rel="stylesheet" href="/src/styles.css">\n',
})
check(audit.scan(src, index, src / "tokens.css")["live"] == ["src/styles.css"],
      "a <link> in index.html makes a sheet live")
check("--x" in audit.scan(src, index, src / "tokens.css")["undefined"],
      "a linked sheet's references are counted")

# --- the token file holds custom properties and nothing else ------------------
check(audit.token_file_problems(":root { --a: 1px; --b: var(--a); }") == [],
      "custom properties on :root are the whole allowed shape")
check(audit.token_file_problems(":root { --a: 1px; }\n.panel { --b: 2px; }"),
      "a class in tokens.css must be refused even when it holds only custom properties: "
      "audit_style_scope cannot see it")
check(audit.token_file_problems(":root { color: red; }"),
      "a plain declaration on :root is a style, not a token")

# --- the gate -----------------------------------------------------------------
base_found = {"undefined": {"--border": {"s.css": 2}}, "colours": {"s.css": 10},
              "token_problems": [], "missing": [], "fallback": {}, "live": [],
              "alias_uses": {n: 0 for n in audit.LEGACY_ALIASES}, "radii": {}, "heights": 0,
              "tokens_live": False, "token_count": 0, "tokens_unreferenced": None}
BASE = {"undefined_names": ["--border"], "undefined_names_ceiling": 1,
        "undefined_references_ceiling": 2, "raw_colour_ceiling": 10}
rendered = audit.render(base_found)

ok, failures, _ = audit.compare(base_found, BASE, rendered)
check(ok and not failures, f"the recorded surface passes itself: {failures}")

grew = dict(base_found, undefined={"--border": {"s.css": 2}, "--nope": {"t.css": 1}})
result = audit.compare(grew, BASE, audit.render(grew))
check(not result[0] and any("--nope" in f for f in result[1]),
      "a new undefined name must fail and name itself")

more_refs = dict(base_found, undefined={"--border": {"s.css": 3}})
check(not audit.compare(more_refs, BASE, audit.render(more_refs))[0],
      "a third reference to a recorded undefined name must fail")

more_colour = dict(base_found, colours={"s.css": 11})
result = audit.compare(more_colour, BASE, audit.render(more_colour))
check(not result[0] and any("raw colour" in f for f in result[1]),
      "an eleventh raw colour must fail against a ceiling of ten")

fewer = dict(base_found, colours={"s.css": 7})
result = audit.compare(fewer, BASE, audit.render(fewer))
check(result[0] and any("lock the improvement in" in n for n in result[2]),
      "a falling count passes and asks for the ceiling to be lowered")

classy = dict(base_found, token_problems=["selector '.panel'"])
check(not audit.compare(classy, BASE, audit.render(classy))[0],
      "a class in tokens.css fails the gate")

check(not audit.compare(base_found, BASE, rendered + "edited by hand\n")[0],
      "a reference edited by hand fails")

# --- the live tree ------------------------------------------------------------
live = audit.scan()
names, refs, colours = audit.totals(live)
check("src/styles.css" in live["live"], "styles.css is imported by main.tsx")
check(not live["missing"], f"every stylesheet import resolves: {live['missing']}")
check(colours > 0, "raw colours remain; a zero here means the scan broke")
check(not live["token_problems"], f"tokens.css holds only custom properties: {live['token_problems']}")
if audit.TOKENS.exists():
    token_text = audit.TOKENS.read_text(encoding="utf-8")
    missing_aliases = [n for n in audit.LEGACY_ALIASES if f"{n}:" not in token_text]
    check(not missing_aliases,
          f"tokens.css must define every legacy alias U3 resolves: {missing_aliases}")

# --- baselines are rewritten only when a number moves -------------------------
# U3 takes the undefined counts to zero and leaves every colour where it was. A
# colour ceiling written again at the same value would be a second version of its
# file that never fell, which audit_ratchet_motion counts against the ratchet.
scratch = Path(tempfile.mkdtemp()) / "x-baseline.json"
check(audit.write_if_changed(scratch, "n", {"raw_colour_ceiling": 5}), "a new file is written")
stamp = scratch.read_text(encoding="utf-8")
check(not audit.write_if_changed(scratch, "n", {"raw_colour_ceiling": 5}),
      "the same numbers must not rewrite the file")
check(scratch.read_text(encoding="utf-8") == stamp, "an unchanged baseline keeps its bytes")
check(audit.write_if_changed(scratch, "n", {"raw_colour_ceiling": 4}), "a lower number is written")
check("raw_colour_ceiling" not in json.loads(audit.BASELINE.read_text(encoding="utf-8"))
      if audit.BASELINE.exists() else True,
      "the colour ceiling must live in its own file, apart from the undefined counts")

check(audit.BASELINE.exists() and audit.COLOUR_BASELINE.exists(),
      f"no baselines at {audit.BASELINE} and {audit.COLOUR_BASELINE}")
recorded = audit.load_baselines()
check(names <= recorded["undefined_names_ceiling"],
      f"{names} undefined names against a ceiling of {recorded['undefined_names_ceiling']}")
check(refs <= recorded["undefined_references_ceiling"],
      f"{refs} references against a ceiling of {recorded['undefined_references_ceiling']}")
check(colours <= recorded["raw_colour_ceiling"],
      f"{colours} raw colours against a ceiling of {recorded['raw_colour_ceiling']}")
check(audit.REFERENCE.exists() and audit.REFERENCE.read_text(encoding="utf-8") == audit.render(live),
      "docs/STYLE_TOKENS.md matches the source; regenerate with --write")

print(f"Style-token gate verified: {checks} assertions passed ({names} undefined name(s), "
      f"{refs} reference(s), {colours} raw colour literal(s)).")

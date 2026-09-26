"""Count the style table before any of it is used, and refuse what makes it worse.

U1 of GOAL_LOOK_2026-09-24. The look goal puts one table of values
(`frontend/src/tokens.css`, read from the original) under a stylesheet that has
none: `styles.css` is 6,756 lines with no custom property of its own and three
hundred distinct hex colours. Before a single token is used, this measures the
two numbers the goal means to move, so that every later step is judged against a
count rather than a feeling.

**Undefined custom properties.** A `var(--x)` whose name no *live* stylesheet
defines and no component sets inline is invalid at computed-value time, and the
browser drops the whole declaration. `styles.css` does this 39 times, with seven
names (`--border`, `--muted`, `--accent`, `--surface`, `--surface-strong`,
`--text`, `--line`), which is why the Decision and Ops screens drew no borders,
grounds or active-tab marks until U3 imported `tokens.css`. A reference with a
fallback, `var(--x, 4px)`, renders its fallback and is reported, not counted.
Once `tokens.css` is imported, its own reads count too: a typo on the right of an
alias would drop every declaration the alias serves.

"Live" is the word the first draft got wrong. `tokens.css` already defines all
seven names, in an alias block written for U3, and nothing imported it then.
Counting every stylesheet under `frontend/src` read 0 undefined names on a tree
where all 39 declarations were still dropped. Only stylesheets something imports
-- a TS or TSX `import "….css"`, or a `<link>` in `index.html` -- define anything
here, and third-party sheets resolve through `node_modules`.

**Raw colour literals.** Hex of 3, 4, 6 or 8 digits and `rgb()`, `rgba()`,
`hsl()`, `hsla()`, outside `tokens.css`: in stylesheet declaration values (never
in comments, selectors or `url(#…)` fragments) and inside TS and TSX string
literals (never in comments). The TS side is coarse on purpose: a string that is
exactly `"#add"` would count. Nothing in the tree is such a string today.

  - *Gated:* an undefined name that is not already recorded, or more undefined
    references than recorded. Zero is the target U3 sets.
  - *Gated:* more raw colour literals than recorded (`raw_colour_ceiling`). It
    may only fall; U10 lowers it as primitives replace per-screen CSS.
  - *Gated:* `tokens.css` holding anything but custom properties on `:root`.
    `audit_style_scope` reads `styles.css` alone, so a class written into the
    token file would couple screens where nothing could see it.
  - *Gated:* `docs/STYLE_TOKENS.md` disagreeing with the source.
  - *Reported, not gated:* radius and height literals, uses of the legacy alias
    names, and tokens nothing reads, directly or through another token (a token
    only an unread token reads is not in effect). The look goal is not a rule
    that every radius come from a token -- GOAL_UI_ENHANCEMENT J3 warned against a
    gate that enforces uniformity -- so those are counts to read, not ceilings.

  python oms/audit_style_tokens.py
  python oms/audit_style_tokens.py --write         # regenerate the reference
  python oms/audit_style_tokens.py --set-baseline
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))

FRONTEND = REPO_ROOT / "frontend"
FRONTEND_SRC = FRONTEND / "src"
INDEX_HTML = FRONTEND / "index.html"
TOKENS = FRONTEND_SRC / "tokens.css"
BASELINE = REPO_ROOT / "docs" / "style-tokens-baseline.json"
# The colour count lives in a file of its own. U3 takes the undefined counts to zero
# without touching a colour, and one file holding both would record the colour
# ceiling a second time at the same value -- which `audit_ratchet_motion`, reading
# the file's history, counts as a ratchet recorded and never lowered.
COLOUR_BASELINE = REPO_ROOT / "docs" / "raw-colours-baseline.json"
REFERENCE = REPO_ROOT / "docs" / "STYLE_TOKENS.md"

# The names styles.css used before anything defined them. tokens.css aliased them
# (a SHIP CHOICE block) so U3 could resolve them in one import; U10 moved their 39
# uses to real names and deleted the block. A use now is an undefined name, which
# the first gate refuses; the count stays reported so the retirement reads as 0.
LEGACY_ALIASES = ("--border", "--surface", "--surface-strong", "--accent", "--muted",
                  "--text", "--line")

_COMMENT_CSS = re.compile(r"/\*.*?\*/", re.S)
_BLOCK = re.compile(r"\{([^{}]*)\}")
_URL = re.compile(r"url\([^)]*\)", re.I)
_HEX = re.compile(r"(?<![\w#-])#(?:[0-9a-fA-F]{8}|[0-9a-fA-F]{6}|[0-9a-fA-F]{3,4})(?![\w-])")
_FUNC = re.compile(r"\b(?:rgba?|hsla?)\(", re.I)
_VAR = re.compile(r"var\(\s*(--[A-Za-z0-9_-]+)\s*(,)?")
_DEFINE_CSS = re.compile(r"(?<![\w-])(--[A-Za-z0-9_-]+)\s*:")
_DEFINE_TS = re.compile(r"""["'\[](--[A-Za-z0-9_-]+)["'\]]\s*:""")
_IMPORT_CSS = re.compile(r"""^\s*import\s+(?:[^'"]*from\s+)?["']([^"']+\.css)["']""", re.M)
_LINK_CSS = re.compile(r"""<link[^>]+rel=["']stylesheet["'][^>]*href=["']([^"']+)["']""", re.I)
_TS_STRING = re.compile(r'"(?:\\.|[^"\\\n])*"|\'(?:\\.|[^\'\\\n])*\'|`(?:\\.|[^`\\])*`', re.S)
_TS_COMMENT = re.compile(r"//[^\n]*|/\*.*?\*/", re.S)
_RADIUS = re.compile(r"(?<![\w-])border(?:-[a-z]+)*-radius\s*:\s*([^;]+)")
_HEIGHT = re.compile(r"(?<![\w-])(?:min-|max-)?height\s*:\s*(-?\d+(?:\.\d+)?px)")
_SELECTOR_BEFORE_BLOCK = re.compile(r"([^{};]+)\{")


def _label(path: Path, root: Path = FRONTEND) -> str:
    try:
        return str(path.relative_to(root)).replace("\\", "/")
    except ValueError:
        return str(path).replace("\\", "/")


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def _strip_ts_comments(text: str) -> str:
    """TS source with comments removed but string literals kept intact.

    A plain comment regex would eat `//` inside a URL string, so strings are
    matched first and put back verbatim.
    """
    out: List[str] = []
    position = 0
    token = re.compile(_TS_STRING.pattern + r"|" + _TS_COMMENT.pattern, re.S)
    for match in token.finditer(text):
        out.append(text[position:match.start()])
        piece = match.group(0)
        out.append(piece if piece[0] in "\"'`" else " ")
        position = match.end()
    out.append(text[position:])
    return "".join(out)


# --------------------------------------------------------------------- colours

def css_values(text: str) -> List[str]:
    """Declaration values of a stylesheet: after the colon, inside the innermost
    blocks, with comments and `url(…)` removed. Selectors never reach here, so an
    id selector such as `#add` is not a colour."""
    body = _COMMENT_CSS.sub(" ", text)
    values: List[str] = []
    for block in _BLOCK.findall(body):
        for declaration in block.split(";"):
            if ":" not in declaration:
                continue
            values.append(_URL.sub(" ", declaration.split(":", 1)[1]))
    return values


def colours_in_css(text: str) -> int:
    return sum(len(_HEX.findall(value)) + len(_FUNC.findall(value)) for value in css_values(text))


def colours_in_ts(text: str) -> int:
    """Colour literals inside string literals. Comments are removed first."""
    count = 0
    for literal in _TS_STRING.findall(_strip_ts_comments(text)):
        literal = _URL.sub(" ", literal)
        count += len(_HEX.findall(literal)) + len(_FUNC.findall(literal))
    return count


# ------------------------------------------------------------ live stylesheets

def _resolve(spec: str, importer: Path, root: Path = FRONTEND) -> Optional[Path]:
    """A stylesheet specifier as a path: relative, root-absolute (as Vite serves
    `/src/…` from the frontend root), or a package under `node_modules`."""
    if spec.startswith("."):
        return (importer.parent / spec).resolve()
    if spec.startswith("/"):
        return (root / spec.lstrip("/")).resolve()
    return (root / "node_modules" / spec).resolve()


def source_files(src: Path = FRONTEND_SRC) -> List[Path]:
    return sorted(p for p in src.rglob("*") if p.suffix in (".ts", ".tsx") and p.is_file())


def live_stylesheets(src: Path = FRONTEND_SRC, index: Path = INDEX_HTML) -> Tuple[List[Path], List[str]]:
    """Stylesheets something imports, and specifiers that did not resolve."""
    live: Dict[Path, None] = {}
    missing: List[str] = []
    for path in source_files(src):
        for spec in _IMPORT_CSS.findall(_read(path)):
            target = _resolve(spec, path, src.parent)
            if target and target.exists():
                live[target] = None
            else:
                missing.append(f"{_label(path, src.parent)} imports {spec}")
    if index.exists():
        for href in _LINK_CSS.findall(_read(index)):
            target = _resolve(href, index, src.parent)
            if target and target.exists():
                live[target] = None
            else:
                missing.append(f"index.html links {href}")
    return list(live), missing


def _is_own(path: Path, src: Path = FRONTEND_SRC) -> bool:
    try:
        path.relative_to(src)
        return True
    except ValueError:
        return False


# ------------------------------------------------------------ custom properties

def definitions(live: Iterable[Path], sources: Iterable[Path]) -> Set[str]:
    """Names defined by a live stylesheet, or set by a component's inline style."""
    names: Set[str] = set()
    for path in live:
        for block in _BLOCK.findall(_COMMENT_CSS.sub(" ", _read(path))):
            names.update(_DEFINE_CSS.findall(block))
    for path in sources:
        names.update(_DEFINE_TS.findall(_strip_ts_comments(_read(path))))
    return names


def references(own_live: Iterable[Path], sources: Iterable[Path],
               root: Path = FRONTEND) -> List[Tuple[str, str, bool]]:
    """(name, file, has fallback) for every var() in our live sheets and TS strings."""
    found: List[Tuple[str, str, bool]] = []
    for path in own_live:
        for value in css_values(_read(path)):
            for name, comma in _VAR.findall(value):
                found.append((name, _label(path, root), bool(comma)))
    for path in sources:
        for literal in _TS_STRING.findall(_strip_ts_comments(_read(path))):
            for name, comma in _VAR.findall(literal):
                found.append((name, _label(path, root), bool(comma)))
    return found


_TOKEN_DECLARATION = re.compile(r"(?<![\w-])(--[A-Za-z0-9_-]+)\s*:\s*([^;]*)")


def in_effect_tokens(text: str, read_outside: Set[str]) -> Set[str]:
    """Tokens something outside tokens.css reads, directly or through other tokens.

    `--accent: var(--text-selected)` puts --text-selected in effect only because
    styles.css reads --accent; a token read only by a token nobody reads is not."""
    reads: Dict[str, Set[str]] = {}
    for block in _BLOCK.findall(_COMMENT_CSS.sub(" ", text)):
        for name, value in _TOKEN_DECLARATION.findall(block):
            reads.setdefault(name, set()).update(n for n, _ in _VAR.findall(value))
    found = {name for name in read_outside if name in reads}
    pending = list(found)
    while pending:
        for name in reads.get(pending.pop(), ()):
            if name in reads and name not in found:
                found.add(name)
                pending.append(name)
    return found


def token_file_problems(text: str) -> List[str]:
    """tokens.css may hold custom properties on :root and nothing else."""
    body = _COMMENT_CSS.sub(" ", text)
    problems = []
    for selector in _SELECTOR_BEFORE_BLOCK.findall(body):
        selector = selector.strip()
        if selector and selector != ":root":
            problems.append(f"selector {selector[:60]!r}")
    for block in _BLOCK.findall(body):
        for declaration in block.split(";"):
            declaration = declaration.strip()
            if declaration and not declaration.startswith("--"):
                problems.append(f"declaration {declaration[:60]!r}")
    return problems


# ------------------------------------------------------------------------ scan

def scan(src: Path = FRONTEND_SRC, index: Path = INDEX_HTML,
         tokens: Path = TOKENS) -> Dict[str, Any]:
    # Resolved, because imports resolve to absolute paths and a temp or 8.3 path
    # spelled differently would stop comparing equal to them.
    src, index, tokens = src.resolve(), index.resolve(), tokens.resolve()
    root = src.parent
    live, missing = live_stylesheets(src, index)
    sources = source_files(src)
    own_live = [p for p in live if _is_own(p, src) and p != tokens]
    defined = definitions(live, sources)

    undefined: Dict[str, Dict[str, int]] = {}
    fallback: Dict[str, int] = Counter()
    alias_uses: Dict[str, int] = Counter()
    referenced: Set[str] = set()
    for name, where, has_fallback in references(own_live, sources, root):
        referenced.add(name)
        if name in LEGACY_ALIASES:
            alias_uses[name] += 1
        if name in defined:
            continue
        if has_fallback:
            fallback[name] += 1
            continue
        undefined.setdefault(name, Counter())[where] += 1

    # Once imported, tokens.css's own reads are in effect too: the alias block
    # and every token built from another. A typo on the right of an alias would
    # drop each declaration the alias serves, and nothing else would notice.
    if tokens in live:
        for name, where, has_fallback in references([tokens], [], root):
            if name in defined:
                continue
            if has_fallback:
                fallback[name] += 1
                continue
            undefined.setdefault(name, Counter())[where] += 1

    colours: Dict[str, int] = {}
    radii: Counter = Counter()
    heights = 0
    own_sheets = sorted(p for p in src.rglob("*.css") if p != tokens)
    for path in own_sheets:
        text = _read(path)
        count = colours_in_css(text)
        if count:
            colours[_label(path, root)] = count
        body = _COMMENT_CSS.sub(" ", text)
        for block in _BLOCK.findall(body):
            for value in _RADIUS.findall(block):
                value = value.strip()
                if "var(" not in value:
                    radii[value] += 1
            heights += len(_HEIGHT.findall(block))
    for path in sources:
        count = colours_in_ts(_read(path))
        if count:
            colours[_label(path, root)] = count

    token_names: List[str] = []
    token_problems: List[str] = []
    in_effect: Set[str] = set()
    if tokens.exists():
        token_text = _read(tokens)
        token_names = sorted(set(_DEFINE_CSS.findall(_COMMENT_CSS.sub(" ", token_text))))
        token_problems = token_file_problems(token_text)
        in_effect = in_effect_tokens(token_text, referenced)

    tokens_live = tokens in live
    return {
        "live": sorted(_label(p, root) for p in live),
        "missing": missing,
        "undefined": {name: dict(sorted(files.items())) for name, files in sorted(undefined.items())},
        "fallback": dict(sorted(fallback.items())),
        "alias_uses": {name: alias_uses.get(name, 0) for name in LEGACY_ALIASES},
        "colours": dict(sorted(colours.items())),
        "radii": dict(sorted(radii.items(), key=lambda item: (-item[1], item[0]))),
        "heights": heights,
        "tokens_live": tokens_live,
        "token_count": len(token_names),
        "tokens_unreferenced": (len([n for n in token_names if n not in in_effect])
                                if tokens_live else None),
        "token_problems": token_problems,
    }


def totals(found: Dict[str, Any]) -> Tuple[int, int, int]:
    names = len(found["undefined"])
    refs = sum(sum(files.values()) for files in found["undefined"].values())
    return names, refs, sum(found["colours"].values())


# ------------------------------------------------------------------- reference

def render(found: Dict[str, Any]) -> str:
    names, refs, colours = totals(found)
    lines = [
        "# Style tokens",
        "",
        "Generated by `oms/audit_style_tokens.py`. Do not edit by hand — the gate",
        "regenerates this and fails if it disagrees with the source.",
        "",
        f"**{names} undefined custom propert{'y' if names == 1 else 'ies'}, used {refs} "
        f"time{'' if refs == 1 else 's'}**, and **{colours} raw colour literals** outside",
        "`frontend/src/tokens.css`. The first is the count GOAL_LOOK U3 takes to zero; the",
        "second may only fall, and U10 lowers it as primitives replace per-screen CSS.",
        "",
        "A custom property counts as defined only when a stylesheet something imports",
        "defines it, or a component sets it inline. `tokens.css` "
        + ("is imported, so its definitions count."
           if found["tokens_live"] else
           "is not imported yet, so nothing it defines is in effect."),
        "",
        "## Live stylesheets",
        "",
    ]
    lines += [f"- `{name}`" for name in found["live"]] or ["- none"]
    if found["missing"]:
        lines += ["", "Imports that did not resolve:", ""]
        lines += [f"- {entry}" for entry in found["missing"]]
    lines += ["", "## Undefined custom properties", ""]
    if found["undefined"]:
        lines += ["Each declaration naming one of these is dropped by the browser.", "",
                  "| Property | References | Where |", "| --- | --- | --- |"]
        for name, files in found["undefined"].items():
            where = ", ".join(f"`{f}` ×{n}" for f, n in files.items())
            lines.append(f"| `{name}` | {sum(files.values())} | {where} |")
    else:
        lines.append("None. Every `var()` names a property something defines.")
    if found["fallback"]:
        lines += ["", "Referenced with a fallback and defined nowhere (the fallback renders; not "
                  "counted): " + ", ".join(f"`{n}` ×{c}" for n, c in found["fallback"].items()) + "."]
    lines += ["", "## Raw colour literals", "",
              "| File | Literals |", "| --- | --- |"]
    for name, count in sorted(found["colours"].items(), key=lambda item: (-item[1], item[0])):
        lines.append(f"| `{name}` | {count} |")
    lines += ["", "## Reported, not gated", "",
              "Counts to read, not ceilings to meet: the goal is not a rule that every value "
              "come from a token.", ""]
    radius_total = sum(found["radii"].values())
    lines.append(f"- **Radius literals:** {radius_total} across {len(found['radii'])} distinct "
                 f"values: " + ", ".join(f"`{v}` ×{c}" for v, c in found["radii"].items()) + ".")
    lines.append(f"- **Height literals** (`height`, `min-height`, `max-height` in px): "
                 f"{found['heights']}.")
    alias = found["alias_uses"]
    lines.append(f"- **Legacy alias names in use:** {sum(alias.values())} ("
                 + ", ".join(f"`{n}` ×{c}" for n, c in alias.items()) + "). U10 moved their "
                 "uses to real token names and deleted the alias block; a use now is an "
                 "undefined name.")
    if found["tokens_live"]:
        lines.append(f"- **Tokens nothing reads,** directly or through another token: "
                     f"{found['tokens_unreferenced']} of {found['token_count']}.")
    else:
        lines.append(f"- **Tokens defined in `tokens.css`:** {found['token_count']}, none in "
                     f"effect until it is imported.")
    lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------- compare

def compare(found: Dict[str, Any], baseline: Dict[str, Any],
            reference_text: Optional[str] = None) -> Tuple[bool, List[str], List[str]]:
    failures: List[str] = []
    notes: List[str] = []
    names, refs, colours = totals(found)

    recorded_names = set(baseline.get("undefined_names", []))
    for name in sorted(set(found["undefined"]) - recorded_names):
        files = found["undefined"][name]
        failures.append(
            f"{name} is referenced ({', '.join(f'{f} ×{n}' for f, n in files.items())}) and "
            f"no imported stylesheet defines it, so every declaration naming it is dropped. "
            f"Define it in tokens.css, use an existing token, or give it a fallback.")

    for measure, value in (("undefined_names_ceiling", names),
                           ("undefined_references_ceiling", refs),
                           ("raw_colour_ceiling", colours)):
        ceiling = baseline.get(measure)
        if ceiling is None:
            failures.append(f"the baseline records no {measure}; re-run with --set-baseline")
        elif value > ceiling:
            advice = ("use a token from tokens.css instead of a literal"
                      if measure == "raw_colour_ceiling" else
                      "a var() must name something an imported stylesheet defines")
            failures.append(f"{measure.replace('_ceiling', '').replace('_', ' ')}: {value}, "
                            f"above the ceiling of {ceiling} -- {advice}")
        elif value < ceiling:
            notes.append(f"{measure}: {ceiling} -> {value} -- re-run with --set-baseline to "
                         f"lock the improvement in")

    for problem in found["token_problems"]:
        failures.append(f"tokens.css may hold only custom properties on :root, and holds a "
                        f"{problem}. audit_style_scope reads styles.css alone, so a class here "
                        f"would couple screens where nothing can see it.")

    if found["missing"]:
        notes.append("unresolved stylesheet imports: " + "; ".join(found["missing"]))

    if reference_text is None:
        reference_text = REFERENCE.read_text(encoding="utf-8") if REFERENCE.exists() else None
    if reference_text is None:
        failures.append(f"{REFERENCE.relative_to(REPO_ROOT)} is missing; regenerate with --write")
    elif reference_text != render(found):
        failures.append(f"{REFERENCE.relative_to(REPO_ROOT)} disagrees with the source. "
                        f"Regenerate it: python oms/audit_style_tokens.py --write")
    return not failures, failures, notes


def load_baselines() -> Dict[str, Any]:
    """Both recorded files, as one mapping of measure to value."""
    merged: Dict[str, Any] = {}
    for path in (BASELINE, COLOUR_BASELINE):
        if path.exists():
            merged.update({key: value for key, value
                           in json.loads(path.read_text(encoding="utf-8")).items()
                           if key not in ("provenance", "note")})
    return merged


def write_if_changed(path: Path, note: str, values: Dict[str, Any]) -> bool:
    """Rewrite a baseline only when one of its numbers changed.

    A rewrite at the same values is a new version of the file with an unmoved
    ceiling, which `audit_ratchet_motion` would count against whoever re-ran this.
    """
    if path.exists():
        current = json.loads(path.read_text(encoding="utf-8"))
        if all(current.get(key) == value for key, value in values.items()):
            return False
    path.write_text(json.dumps({"provenance": {"stale_after": "recomputed each run"},
                                "note": note, **values}, indent=2) + "\n", encoding="utf-8")
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true", help="Regenerate the reference")
    parser.add_argument("--set-baseline", action="store_true")
    args = parser.parse_args()

    if not FRONTEND_SRC.exists():
        print(f"No frontend source at {FRONTEND_SRC}")
        return 1

    found = scan()
    names, refs, colours = totals(found)
    print(f"{len(found['live'])} live stylesheet(s); tokens.css "
          f"{'imported' if found['tokens_live'] else 'not imported'} "
          f"({found['token_count']} properties)\n")
    print(f"  undefined custom properties: {names} name(s), {refs} reference(s)")
    for name, files in found["undefined"].items():
        print(f"    {sum(files.values()):>3}  {name}")
    print(f"  raw colour literals outside tokens.css: {colours}")
    for name, count in sorted(found["colours"].items(), key=lambda item: -item[1])[:6]:
        print(f"    {count:>4}  {name}")
    print(f"  reported: {sum(found['radii'].values())} radius literal(s) in "
          f"{len(found['radii'])} value(s), {found['heights']} height literal(s), "
          f"{sum(found['alias_uses'].values())} legacy alias use(s)")

    if args.write:
        REFERENCE.write_text(render(found), encoding="utf-8")
        print(f"\nWrote {REFERENCE.relative_to(REPO_ROOT)}.")
        return 0

    if args.set_baseline:
        written = []
        for path, note, values in (
            (BASELINE,
             ("Custom properties referenced and defined by no imported stylesheet. Ceilings, "
              "not floors: each may fall and must never rise. U3 of GOAL_LOOK_2026-09-24 takes "
              "both to zero."),
             {"undefined_names": sorted(found["undefined"]),
              "undefined_names_ceiling": names,
              "undefined_references_ceiling": refs}),
            (COLOUR_BASELINE,
             ("Raw colour literals outside tokens.css, in stylesheet values and TS strings. A "
              "ceiling, not a floor: it may fall and must never rise. U10 of "
              "GOAL_LOOK_2026-09-24 lowers it as primitives replace per-screen CSS."),
             {"raw_colour_ceiling": colours}),
        ):
            if write_if_changed(path, note, values):
                written.append(path.name)
        print(f"\nBaseline: {names} undefined name(s), {refs} reference(s), {colours} raw "
              f"colour literal(s); rewrote "
              f"{', '.join(written) if written else 'nothing (no number changed)'}.")
        return 0

    missing = [p for p in (BASELINE, COLOUR_BASELINE) if not p.exists()]
    if missing:
        print(f"\nNo baseline at {', '.join(str(p.relative_to(REPO_ROOT)) for p in missing)}. "
              f"Record one with --set-baseline.")
        return 1

    ok, failures, notes = compare(found, load_baselines())
    if notes:
        print(f"\n{len(notes)} change(s), none of them gated:")
        for note in notes:
            print(f"  {note}")
    if failures:
        print(f"\nFAIL -- {len(failures)}:")
        for failure in failures:
            print(f"  {failure}")
        return 1
    print(f"\nNo new undefined custom property and no new raw colour. {names} undefined "
          f"name(s) and {colours} raw colour(s) remain, and each count may only fall.")
    return 0


if __name__ == "__main__":
    from enforcement_runs import recording

    raise SystemExit(recording("audit_style_tokens", main))

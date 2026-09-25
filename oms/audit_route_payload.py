"""What each workspace route costs a browser, and a ceiling it may not exceed.

The request-cost ratchet gates statements per request. Its counterpart did not
exist: 1,101 KB of JavaScript and CSS shipped with nothing constraining it, and
no way to answer "what does opening the map cost" without reading Rollup output
by hand.

Computed from Vite's build manifest rather than from filenames, because the
number that matters is a **closure**: the entry chunk and everything it
statically imports, plus the lazily-loaded chunk for that route and everything
*it* imports. A route's cost is what a browser downloads to render it from cold,
not the size of the file named after it.

Measuring that immediately found something worth fixing. `@xyflow/react` -- the
node-graph library, 178 KB -- was listed in `manualChunks`, which made it a
static import of the entry, so all seventeen workspace routes downloaded it
including the fourteen that never render a graph. Removing that one line let
Rollup place it inside the three chunks that use it:

    shared entry closure   577 KB -> 429 KB
    lightest route         568 KB -> 436 KB

  - *Gated:* a route exceeding its recorded ceiling, and the shared closure
    exceeding its own. Both may fall and must never rise.
  - *Gated:* a route with no recorded ceiling. A new workspace is exactly when a
    payload gets away, so it must be measured before it is merged.
  - *Reported:* every route, sorted, with what changed.

The ceilings are per route rather than one global number because the routes are
not alike: a map that carries Leaflet is legitimately heavier than a settings
screen, and a single budget would either forgive the map or forbid it.

**Fonts are weighed too.** A face is as much a download as the script that asks
for it, and the first version read only each chunk's `file` and `css`. Vite lists
in a chunk's manifest `assets` what its stylesheet's `url()`s and its imports
resolve to, and for the entry what `index.html` links; the `.woff2`, `.woff`,
`.ttf`, `.otf` and `.eot` among them are counted, images are not. (An SVG font
cannot be told from an image by its name, and is not counted.) What builds with
fonts in them showed, each held by a test:

  - A face named by the entry's stylesheet and a route's is listed under both
    chunks and downloaded once, so a closure counts each file once.
  - Vite gives each file it emits for a `url()`, an import or an HTML link a
    manifest entry of its own, keyed by its source path. One under
    `src/workspaces/` is a file, not a route: a route is a script chunk.
  - Some fonts the build ships are fetched by no measured closure. One served
    from `public/` is copied into `dist/` and named by no manifest entry, so
    nothing says which route draws it. One named only by a chunk a route loads
    lazily sits outside every closure, because closures follow static imports
    and that chunk's own script is not counted either. Each is charged to the
    shared closure, by name: overstated rather than missed.

The count is what the build ships, an upper bound: a browser fetches a face only
when text in it renders, and only in the first format it supports. A font under
Vite's 4 KB inline limit is inside the stylesheet or script that names it (or in
`index.html`, which is not weighed, when only a preload names it), and one from
another origin is not in the build, so no count here can see it.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Sequence, Set, Tuple

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))

DIST = REPO_ROOT / "frontend" / "dist"
MANIFEST = DIST / ".vite" / "manifest.json"
BASELINE = REPO_ROOT / "docs" / "route-payload-baseline.json"

# Room for an honest change without a ceremony, but not for a vendor library
# arriving unnoticed. 148 KB is what one misplaced `manualChunks` line cost.
TOLERANCE_KB = 8

FONT_SUFFIXES = (".woff2", ".woff", ".ttf", ".otf", ".eot")

# How Vite's manifest plugin tells a chunk from an emitted asset.
CHUNK = re.compile(r"\.[cm]?js$")


def _size(dist: Path, name: str) -> int:
    path = dist / name
    return path.stat().st_size if name and path.exists() else 0


def is_font(name: str) -> bool:
    return name.lower().endswith(FONT_SUFFIXES)


def closure(manifest: Dict[str, Any], key: str, seen: Set[str]) -> Set[str]:
    """A chunk and everything it statically imports, transitively."""
    if key in seen or key not in manifest:
        return seen
    seen.add(key)
    for imported in manifest[key].get("imports") or []:
        closure(manifest, imported, seen)
    return seen


def files(manifest: Dict[str, Any], keys: Set[str]) -> Set[str]:
    """What a browser downloads for these chunks: scripts, stylesheets and fonts.

    A set, because a file two chunks name is fetched once."""
    found: Set[str] = set()
    for key in keys:
        entry = manifest.get(key, {})
        if entry.get("file"):
            found.add(entry["file"])
        found.update(entry.get("css") or [])
        found.update(name for name in entry.get("assets") or [] if is_font(name))
    return found


def weigh(manifest: Dict[str, Any], dist: Path, keys: Set[str]) -> int:
    return sum(_size(dist, name) for name in files(manifest, keys))


def closures(manifest: Dict[str, Any]) -> Tuple[Set[str], Dict[str, Set[str]]]:
    """The entry's closure, and each workspace route's, which includes the entry's."""
    entry = next((k for k, v in manifest.items() if v.get("isEntry")), None)
    if entry is None:
        return set(), {}
    shared = closure(manifest, entry, set())
    routes: Dict[str, Set[str]] = {}
    for key, value in manifest.items():
        # An imported image or font has an entry too, keyed by its source path.
        if "workspaces/" not in key or not CHUNK.search(value.get("file", "")):
            continue
        routes[key.split("/")[-1].removesuffix(".tsx")] = closure(manifest, key, set(shared))
    return shared, routes


def uncounted_fonts(manifest: Dict[str, Any], dist: Path) -> List[str]:
    """Fonts the build ships that no measured closure fetches.

    A `public/` copy is named by no manifest entry, a face only a lazily loaded
    chunk names is outside every closure, and an asset's own manifest entry is
    not a reference to it."""
    shared, routes = closures(manifest)
    counted = files(manifest, shared).union(*(files(manifest, keys)
                                              for keys in routes.values()))
    shipped = (path.relative_to(dist).as_posix() for path in dist.rglob("*")
               if path.is_file() and is_font(path.name))
    return sorted(name for name in shipped if name not in counted)


def measure(manifest_path: Path | None = None) -> Tuple[int, Dict[str, int]]:
    """(shared closure bytes, bytes per workspace route)."""
    path = manifest_path or MANIFEST
    manifest = json.loads(path.read_text(encoding="utf-8"))
    dist = path.parent.parent
    shared, routes = closures(manifest)
    if not shared:
        return 0, {}
    uncounted = sum(_size(dist, name) for name in uncounted_fonts(manifest, dist))
    return (weigh(manifest, dist, shared) + uncounted,
            {name: weigh(manifest, dist, keys) + uncounted for name, keys in routes.items()})


def compare(shared: int, routes: Dict[str, int], baseline: Dict[str, Any],
            shared_fonts: Sequence[str] = ()) -> Tuple[bool, List[str], List[str]]:
    failures: List[str] = []
    notes: List[str] = []
    tolerance = baseline.get("tolerance_kb", TOLERANCE_KB) * 1024

    prior_shared = baseline.get("shared_closure_bytes")
    if prior_shared is not None:
        if shared > prior_shared + tolerance:
            failures.append(
                f"the shared closure every route pays is {shared / 1024:.0f} KB, above its "
                f"ceiling of {prior_shared / 1024:.0f} KB. Something entered the entry graph; "
                f"a vendor library in `manualChunks` is the usual way."
                + (f" It pays for {len(shared_fonts)} font file(s): {', '.join(shared_fonts)}."
                   if shared_fonts else ""))
        elif shared < prior_shared:
            notes.append(f"shared closure {prior_shared / 1024:.0f} -> {shared / 1024:.0f} KB "
                         f"-- re-run with --set-baseline to lock it in")

    recorded: Dict[str, int] = baseline.get("routes", {})
    for name, size in sorted(routes.items()):
        ceiling = recorded.get(name)
        if ceiling is None:
            failures.append(
                f"{name}: {size / 1024:.0f} KB with no recorded ceiling. A new workspace is "
                f"exactly when a payload gets away; measure it before merging.")
        elif size > ceiling + tolerance:
            failures.append(f"{name}: {size / 1024:.0f} KB, ceiling {ceiling / 1024:.0f} KB "
                            f"(+{(size - ceiling) / 1024:.0f} KB)")
        elif size < ceiling:
            notes.append(f"{name}: {ceiling / 1024:.0f} -> {size / 1024:.0f} KB")

    for name in sorted(recorded):
        if name not in routes:
            notes.append(f"{name}: no longer in the build -- deleted or renamed")
    return not failures, failures, notes


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--set-baseline", action="store_true")
    args = parser.parse_args()

    if not MANIFEST.exists():
        print(f"No build manifest at {MANIFEST.relative_to(REPO_ROOT)}. Run:\n"
              f"  python oms/measure_browser_evidence.py --build")
        return 1

    shared, routes = measure()
    if not routes:
        print("The manifest names no workspace routes.")
        return 1

    print(f"{len(routes)} workspace routes; every one pays a shared closure of "
          f"{shared / 1024:.0f} KB\n")
    # Each font with who pays for it, so a re-baseline can name its faces.
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    dist = MANIFEST.parent.parent
    shared_keys, route_keys = closures(manifest)
    shared_files = files(manifest, shared_keys)
    own = {name: files(manifest, keys) - shared_files for name, keys in route_keys.items()}
    uncounted = uncounted_fonts(manifest, dist)
    shared_fonts = sorted(name for name in shared_files if is_font(name)) + uncounted
    route_fonts = sorted({name for names in own.values() for name in names if is_font(name)})
    for name in shared_fonts:
        where = ("fetched by no measured closure: charged to the shared closure"
                 if name in uncounted else "shared")
        print(f"  font {_size(dist, name):9,} B  {name}  ({where})")
    for name in route_fonts:
        paying = ", ".join(sorted(route for route, names in own.items() if name in names))
        print(f"  font {_size(dist, name):9,} B  {name}  ({paying})")
    if shared_fonts or route_fonts:
        print()
    for name, size in sorted(routes.items(), key=lambda item: -item[1]):
        print(f"  {size / 1024:7.0f} KB  {name}  (+{(size - shared) / 1024:.0f} KB of its own)")

    if args.set_baseline:
        BASELINE.write_text(json.dumps({
            "provenance": {"stale_after": "recomputed each run"},
            "note": ("Bytes a browser downloads to render each workspace route from cold: "
                     "the entry closure plus that route's lazy chunk closure. May fall, "
                     "must never rise beyond the tolerance."),
            "tolerance_kb": TOLERANCE_KB,
            "shared_closure_bytes": shared,
            "routes": dict(sorted(routes.items())),
        }, indent=2) + "\n", encoding="utf-8")
        print(f"\nBaseline set: {shared / 1024:.0f} KB shared, {len(routes)} routes.")
        return 0

    if not BASELINE.exists():
        print(f"\nNo baseline at {BASELINE.relative_to(REPO_ROOT)}. Record one with "
              f"--set-baseline.")
        return 1

    ok, failures, notes = compare(shared, routes,
                                  json.loads(BASELINE.read_text(encoding="utf-8")),
                                  shared_fonts)
    if notes:
        print(f"\n{len(notes)} change(s), none of them gated:")
        for note in notes[:20]:
            print(f"  {note}")
    if failures:
        print(f"\nFAIL -- {len(failures)}:")
        for failure in failures:
            print(f"  {failure}")
        return 1
    print(f"\nNo route exceeds its ceiling, and the shared closure holds at "
          f"{shared / 1024:.0f} KB.")
    return 0


if __name__ == "__main__":
    from enforcement_runs import recording

    raise SystemExit(recording("audit_route_payload", main))

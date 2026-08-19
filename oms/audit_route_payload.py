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
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Set, Tuple

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))

DIST = REPO_ROOT / "frontend" / "dist"
MANIFEST = DIST / ".vite" / "manifest.json"
BASELINE = REPO_ROOT / "docs" / "route-payload-baseline.json"

# Room for an honest change without a ceremony, but not for a vendor library
# arriving unnoticed. 148 KB is what one misplaced `manualChunks` line cost.
TOLERANCE_KB = 8


def _size(dist: Path, name: str) -> int:
    path = dist / name
    return path.stat().st_size if name and path.exists() else 0


def closure(manifest: Dict[str, Any], key: str, seen: Set[str]) -> Set[str]:
    """A chunk and everything it statically imports, transitively."""
    if key in seen or key not in manifest:
        return seen
    seen.add(key)
    for imported in manifest[key].get("imports") or []:
        closure(manifest, imported, seen)
    return seen


def weigh(manifest: Dict[str, Any], dist: Path, keys: Set[str]) -> int:
    total = 0
    for key in keys:
        entry = manifest.get(key, {})
        total += _size(dist, entry.get("file", ""))
        for sheet in entry.get("css") or []:
            total += _size(dist, sheet)
    return total


def measure(manifest_path: Path | None = None) -> Tuple[int, Dict[str, int]]:
    """(shared closure bytes, bytes per workspace route)."""
    path = manifest_path or MANIFEST
    manifest = json.loads(path.read_text(encoding="utf-8"))
    dist = path.parent.parent
    entry = next((k for k, v in manifest.items() if v.get("isEntry")), None)
    if entry is None:
        return 0, {}
    shared = closure(manifest, entry, set())
    shared_bytes = weigh(manifest, dist, shared)
    routes: Dict[str, int] = {}
    for key in manifest:
        if "workspaces/" not in key:
            continue
        name = key.split("/")[-1].removesuffix(".tsx")
        routes[name] = weigh(manifest, dist, closure(manifest, key, set(shared)))
    return shared_bytes, routes


def compare(shared: int, routes: Dict[str, int],
            baseline: Dict[str, Any]) -> Tuple[bool, List[str], List[str]]:
    failures: List[str] = []
    notes: List[str] = []
    tolerance = baseline.get("tolerance_kb", TOLERANCE_KB) * 1024

    prior_shared = baseline.get("shared_closure_bytes")
    if prior_shared is not None:
        if shared > prior_shared + tolerance:
            failures.append(
                f"the shared closure every route pays is {shared / 1024:.0f} KB, above its "
                f"ceiling of {prior_shared / 1024:.0f} KB. Something entered the entry graph; "
                f"a vendor library in `manualChunks` is the usual way.")
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
                                  json.loads(BASELINE.read_text(encoding="utf-8")))
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

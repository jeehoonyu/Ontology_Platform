"""A route may not grow past what it costs a browser today.

Also this check's home: `audit_route_payload` declares `every suite run`, and
`audit_iteration_state` fails a check whose cadence names a place it does not run.

The number under test is a *closure*, not a file size. A route costs the entry
chunk plus everything it statically imports, plus that route's lazy chunk plus
everything it imports. Measuring the file named after the workspace would have
reported `Automate` at 7 KB when a browser downloads 436 KB to render it.

Measuring it properly is what found the finding: `@xyflow/react` sat in
`manualChunks`, which made it a static import of the entry, so all seventeen
routes carried the 178 KB node-graph library including the fourteen that never
draw a graph. One line removed, and the shared closure fell 577 -> 429 KB.

Fonts are weighed from each chunk's manifest `assets` (GOAL_LOOK U2), before any
font exists, so the face U4 brings is counted the day it lands. The manifests
below have the fields Vite 7.3 wrote for probe builds: the entry's
`dynamicImports`, a route's `src` and `isDynamicEntry`, a face under the entry, a
route and an imported chunk, an asset's own entry, an image, a face only a lazily
loaded chunk names, and fonts in `public/`.
"""
import contextlib
import copy
import io
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import audit_route_payload as payload  # noqa: E402
from audit_route_payload import (BASELINE, closure, compare, is_font, measure,  # noqa: E402
                                 uncounted_fonts, weigh)

checks = 0


def check(condition, message):
    global checks
    assert condition, message
    checks += 1


# --- a closure is transitive, and a shared chunk is counted once -------------
MANIFEST = {
    "index.html": {"file": "assets/index.js", "isEntry": True, "imports": ["_shared.js"],
                   "dynamicImports": ["src/workspaces/Light.tsx", "src/workspaces/Heavy.tsx"]},
    "_shared.js": {"file": "assets/shared.js", "imports": ["_deep.js"]},
    "_deep.js": {"file": "assets/deep.js"},
    "src/workspaces/Light.tsx": {"file": "assets/light.js", "src": "src/workspaces/Light.tsx",
                                 "isDynamicEntry": True},
    "src/workspaces/Heavy.tsx": {"file": "assets/heavy.js", "src": "src/workspaces/Heavy.tsx",
                                 "isDynamicEntry": True, "imports": ["_big.js"]},
    "_big.js": {"file": "assets/big.js"},
}
check(closure(MANIFEST, "index.html", set()) == {"index.html", "_shared.js", "_deep.js"},
      closure(MANIFEST, "index.html", set()))
check(closure(MANIFEST, "src/workspaces/Heavy.tsx", set()) ==
      {"src/workspaces/Heavy.tsx", "_big.js"}, "a route pulls its own imports")

with tempfile.TemporaryDirectory() as tmp:
    dist = Path(tmp) / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / ".vite").mkdir()
    for name, kb in (("index", 10), ("shared", 20), ("deep", 5), ("light", 1), ("heavy", 2),
                     ("big", 100)):
        (dist / "assets" / f"{name}.js").write_bytes(b"x" * kb * 1024)
    (dist / ".vite" / "manifest.json").write_text(json.dumps(MANIFEST), encoding="utf-8")
    shared, routes = measure(dist / ".vite" / "manifest.json")
    check(shared == 35 * 1024, shared)
    # The light route pays the shared closure plus its own kilobyte, not one kilobyte.
    check(routes["Light"] == 36 * 1024, routes)
    check(routes["Heavy"] == 137 * 1024, routes)

# --- fonts: a face is a download ---------------------------------------------
SIZES = {"assets/index.js": 10 * 1024, "assets/shared.js": 20 * 1024,
         "assets/deep.js": 5 * 1024, "assets/light.js": 1024, "assets/heavy.js": 2 * 1024,
         "assets/big.js": 100 * 1024}
FACE = 20_000


def build(tmp, name, manifest, sizes):
    dist = Path(tmp) / name
    (dist / ".vite").mkdir(parents=True)
    for file, size in sizes.items():
        (dist / file).parent.mkdir(parents=True, exist_ok=True)
        (dist / file).write_bytes(b"x" * size)
    path = dist / ".vite" / "manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    return path


with tempfile.TemporaryDirectory() as tmp:
    # One face in the entry's stylesheet: every route pays exactly its bytes.
    one = copy.deepcopy(MANIFEST)
    one["index.html"]["assets"] = ["assets/face-regular.woff2"]
    path = build(tmp, "one", one, {**SIZES, "assets/face-regular.woff2": FACE})
    shared, routes = measure(path)
    check(shared - 35 * 1024 == FACE and uncounted_fonts(one, path.parent.parent) == [],
          f"one 20,000 B face in the entry's assets must add 20,000 B to the shared closure, "
          f"read from those assets: {shared - 35 * 1024:+,}, and charged as uncounted: "
          f"{uncounted_fonts(one, path.parent.parent)}")
    check(routes["Light"] - 36 * 1024 == FACE and routes["Heavy"] - 137 * 1024 == FACE,
          f"every route pays the entry's face: Light {routes['Light'] - 36 * 1024:+,}, "
          f"Heavy {routes['Heavy'] - 137 * 1024:+,}")

    # The probe's shape: the entry and a route both name the face, the route adds a
    # `.ttf` and an image, an image under src/workspaces/ gets its own manifest
    # entry, and a legacy face's suffix is upper-case.
    probe = copy.deepcopy(MANIFEST)
    probe["index.html"]["assets"] = ["assets/face-regular.woff2", "assets/marker.png"]
    probe["src/workspaces/Heavy.tsx"]["assets"] = [
        "assets/route-only.ttf", "assets/face-regular.woff2", "assets/marker.png"]
    probe["src/workspaces/Light.tsx"]["assets"] = ["assets/Legacy.WOFF"]
    probe["src/fonts/face-regular.woff2"] = {"file": "assets/face-regular.woff2",
                                             "src": "src/fonts/face-regular.woff2"}
    probe["src/workspaces/map/pin.png"] = {"file": "assets/pin.png",
                                           "src": "src/workspaces/map/pin.png"}
    path = build(tmp, "probe", probe, {
        **SIZES, "assets/face-regular.woff2": FACE, "assets/route-only.ttf": 9_000,
        "assets/marker.png": 6_000, "assets/Legacy.WOFF": 3_000, "assets/pin.png": 4_000})
    check(uncounted_fonts(probe, path.parent.parent) == [],
          f"a face a measured closure names is counted there, not charged again as "
          f"uncounted: {uncounted_fonts(probe, path.parent.parent)}")
    shared, routes = measure(path)
    check(shared - 35 * 1024 == FACE,
          f"an image in assets is not a font and must not count: {shared - 35 * 1024:+,}")
    check(routes["Heavy"] - 137 * 1024 == FACE + 9_000,
          f"a face the entry and a route both name is one download, and the route's own "
          f".ttf counts: {routes['Heavy'] - 137 * 1024:+,}")
    check(set(routes) == {"Light", "Heavy"},
          f"an asset's own manifest entry under src/workspaces/ is not a route: {sorted(routes)}")
    check(routes["Light"] - 36 * 1024 == FACE + 3_000,
          f"a font suffix counts in any case: {routes['Light'] - 36 * 1024:+,}")
    check(is_font("assets/a.otf") and is_font("assets/a.eot") and not is_font("assets/a.woff2.map")
          and not is_font("assets/a.svg"), "only .woff2, .woff, .ttf, .otf and .eot are fonts")

    # Two routes' shared component: Vite lists its face under the imported chunk.
    imported = copy.deepcopy(MANIFEST)
    imported["_big.js"]["assets"] = ["assets/widget-icons.ttf"]
    shared, routes = measure(build(tmp, "imported", imported,
                                   {**SIZES, "assets/widget-icons.ttf": 5_000}))
    check((shared, routes["Light"], routes["Heavy"] - 137 * 1024) == (35 * 1024, 36 * 1024, 5_000),
          f"a face on a chunk a route imports is paid by that route alone: "
          f"shared {shared - 35 * 1024:+,}, Light {routes['Light'] - 36 * 1024:+,}, "
          f"Heavy {routes['Heavy'] - 137 * 1024:+,}")

    # Faces copied from public/ are in dist/ and in no manifest entry, at any depth,
    # in any case and any format.
    path = build(tmp, "public", MANIFEST, {**SIZES, "fonts/public-face.woff2": 12_000,
                                           "fonts/source-sans-3/deep.ttf": 11_000,
                                           "fonts/Upper.WOFF2": 2_000})
    found = uncounted_fonts(MANIFEST, path.parent.parent)
    check("fonts/public-face.woff2" in found,
          f"a font no chunk names must be found by name: {found}")
    check("fonts/source-sans-3/deep.ttf" in found,
          f"a font no chunk names must be found at any depth under dist/: {found}")
    check("fonts/Upper.WOFF2" in found,
          f"a font no chunk names must be found whatever the case of its suffix: {found}")
    shared, routes = measure(path)
    check(shared - 35 * 1024 == 25_000,
          f"a font from public/ that no chunk names must be charged to the shared closure, "
          f"not missed: {shared - 35 * 1024:+,}")
    check(routes["Light"] - 36 * 1024 == 25_000 and routes["Heavy"] - 137 * 1024 == 25_000,
          "and so to every route")

    # A route's lazily loaded panel: its chunk is in no closure, since closures
    # follow static imports, so its face would ship uncounted.
    lazy = copy.deepcopy(MANIFEST)
    lazy["src/workspaces/Heavy.tsx"]["dynamicImports"] = ["src/components/Chart.tsx"]
    lazy["src/components/Chart.tsx"] = {
        "file": "assets/chart.js", "src": "src/components/Chart.tsx", "isDynamicEntry": True,
        "assets": ["assets/nested.woff2"]}
    shared, routes = measure(build(tmp, "lazy", lazy, {**SIZES, "assets/chart.js": 1024,
                                                       "assets/nested.woff2": 11_000}))
    check(shared - 35 * 1024 == 11_000,
          f"a face only a lazily loaded chunk names is in no measured closure and must be "
          f"charged to the shared closure, not missed: {shared - 35 * 1024:+,}")

    # An emitted face that only its own asset entry names is not a reference either.
    orphan = copy.deepcopy(MANIFEST)
    orphan["src/fonts/orphan.woff2"] = {"file": "assets/orphan.woff2",
                                        "src": "src/fonts/orphan.woff2"}
    shared, _routes = measure(build(tmp, "orphan", orphan, {**SIZES, "assets/orphan.woff2": 7_000}))
    check(shared - 35 * 1024 == 7_000,
          f"a font named only by its own manifest entry is fetched by no closure: "
          f"{shared - 35 * 1024:+,}")

    # Vite's manifest plugin calls `.mjs` and `.cjs` files chunks too.
    modern = copy.deepcopy(MANIFEST)
    modern["src/workspaces/Light.tsx"]["file"] = "assets/light.mjs"
    _shared, routes = measure(build(tmp, "modern", modern, {**SIZES, "assets/light.mjs": 1024}))
    check(routes.get("Light") == 36 * 1024,
          f"a route whose chunk is .mjs is still a script chunk: {sorted(routes)}")

    # The report says who pays for each font, so a re-baseline can name its faces.
    report = copy.deepcopy(MANIFEST)
    report["index.html"]["assets"] = ["assets/face-regular.woff2"]
    report["src/workspaces/Heavy.tsx"]["assets"] = ["assets/route-only.ttf"]
    path = build(tmp, "report", report, {**SIZES, "assets/face-regular.woff2": FACE,
                                         "assets/route-only.ttf": 9_000,
                                         "fonts/public-face.woff2": 12_000})
    shared, routes = measure(path)
    baseline = Path(tmp) / "report-baseline.json"
    baseline.write_text(json.dumps({"tolerance_kb": 8, "shared_closure_bytes": shared,
                                    "routes": routes}), encoding="utf-8")
    saved = payload.MANIFEST, payload.BASELINE, sys.argv
    payload.MANIFEST, payload.BASELINE, sys.argv = path, baseline, ["audit_route_payload.py"]
    printed = io.StringIO()
    try:
        with contextlib.redirect_stdout(printed):
            code = payload.main()
    finally:
        payload.MANIFEST, payload.BASELINE, sys.argv = saved
    out = printed.getvalue()
    check(code == 0 and "assets/face-regular.woff2  (shared)" in out,
          f"the report must mark a face the shared closure pays for:\n{out}")
    check("assets/route-only.ttf  (Heavy)" in out,
          f"the report must name the routes that pay for a route's face:\n{out}")
    check("fonts/public-face.woff2  (fetched by no measured closure: charged to the "
          "shared closure)" in out,
          f"the report must say a face no closure fetches is charged to the shared "
          f"closure:\n{out}")

BASE = {"tolerance_kb": 8, "shared_closure_bytes": 35 * 1024,
        "routes": {"Light": 36 * 1024, "Heavy": 137 * 1024}}

ok, failures, _notes = compare(35 * 1024, {"Light": 36 * 1024, "Heavy": 137 * 1024}, BASE)
check(ok and not failures, failures)

# --- gate: a route grows past its ceiling ------------------------------------
grew = compare(35 * 1024, {"Light": 60 * 1024, "Heavy": 137 * 1024}, BASE)
check(not grew[0], "a route 24 KB over its ceiling must fail")
check(any("Light" in f for f in grew[1]), grew[1])

# Inside the tolerance is ordinary work and passes.
nudged = compare(35 * 1024, {"Light": 40 * 1024, "Heavy": 137 * 1024}, BASE)
check(nudged[0], nudged[1])

# --- gate: the shared closure grows ------------------------------------------
hoisted = compare(200 * 1024, {"Light": 36 * 1024, "Heavy": 137 * 1024}, BASE)
check(not hoisted[0], "a vendor library entering the entry graph must fail")
check(any("shared closure" in f and "manualChunks" in f for f in hoisted[1]), hoisted[1])
check(not any("font" in f for f in hoisted[1]),
      f"with no font in the build, the failure must not point at fonts: {hoisted[1]}")
faced = compare(200 * 1024, {"Light": 36 * 1024, "Heavy": 137 * 1024}, BASE,
                ["assets/face-regular.woff2"])
check(any("1 font file(s): assets/face-regular.woff2" in f for f in faced[1]),
      f"the shared-closure failure must name the faces it pays for: {faced[1]}")

# --- gate: a new route with no ceiling ---------------------------------------
fresh = compare(35 * 1024, {"Light": 36 * 1024, "Heavy": 137 * 1024, "Brand": 90 * 1024}, BASE)
check(not fresh[0], "a route with no recorded ceiling must fail")
check(any("Brand" in f and "no recorded ceiling" in f for f in fresh[1]), fresh[1])

# --- note: an improvement asks for the baseline to move ----------------------
better = compare(20 * 1024, {"Light": 30 * 1024, "Heavy": 137 * 1024}, BASE)
check(better[0], better[1])
check(any("set-baseline" in n for n in better[2]), better[2])

# --- the live build -----------------------------------------------------------
check(BASELINE.exists(), f"no baseline at {BASELINE}")
recorded = json.loads(BASELINE.read_text(encoding="utf-8"))
check(recorded["provenance"]["stale_after"] == "recomputed each run", recorded)
check(len(recorded["routes"]) >= 15, len(recorded["routes"]))

# The point of the split: the graph library rides with the graph screens, not
# with everyone. If the shared closure ever exceeds the heaviest non-graph route
# again, something has been hoisted back into the entry.
shared = recorded["shared_closure_bytes"]
check(shared < 500 * 1024, f"shared closure is {shared / 1024:.0f} KB")
graph_screens = [recorded["routes"].get(n, 0)
                 for n in ("OntologyManager", "VisualBuilder", "PlatformGraph")]
check(all(size > shared for size in graph_screens), graph_screens)

print(f"Route payload gate verified: {checks} assertions passed "
      f"({len(recorded['routes'])} routes, shared closure {shared / 1024:.0f} KB).")

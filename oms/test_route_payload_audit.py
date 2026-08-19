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
"""
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from audit_route_payload import BASELINE, closure, compare, measure, weigh  # noqa: E402

checks = 0


def check(condition, message):
    global checks
    assert condition, message
    checks += 1


# --- a closure is transitive, and a shared chunk is counted once -------------
MANIFEST = {
    "index.html": {"file": "assets/index.js", "isEntry": True, "imports": ["_shared.js"]},
    "_shared.js": {"file": "assets/shared.js", "imports": ["_deep.js"]},
    "_deep.js": {"file": "assets/deep.js"},
    "src/workspaces/Light.tsx": {"file": "assets/light.js"},
    "src/workspaces/Heavy.tsx": {"file": "assets/heavy.js", "imports": ["_big.js"]},
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

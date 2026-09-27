"""Every resource kind's URL, one table on both sides (GOAL_FOUNDATIONS A6).

`frontend/src/routes.json` lists what each workspace view reads from its query and which view
opens each kind of resource. The server's copy is a constant in `app/workspace_routes.py`
(production ships `frontend/dist`, not the table's source), and this holds the two equal. Every
workspace link written with a query is built from the table, on either side: a hand-built one
is counted here and the count may only fall, since before A6 the server spelled one id three
ways and no screen read any of them.
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "oms"))
from app.workspace_routes import KINDS, VIEWS, app_url, workspace_href  # noqa: E402

checks = 0


def check(condition, message):
    global checks
    assert condition, message
    checks += 1


table = json.loads((ROOT / "frontend" / "src" / "routes.json").read_text(encoding="utf-8"))
apps = {app["id"] for app in json.loads((ROOT / "frontend" / "src" / "apps.json").read_text(encoding="utf-8"))["apps"]}

check(VIEWS == table["views"] and KINDS == table["kinds"],
      f"the server's route table is not routes.json: views {VIEWS} vs {table['views']}, kinds {KINDS} vs {table['kinds']}")

for view, route in table["views"].items():
    params = route["params"]
    check(view in apps, f"routes.json names {view}, which apps.json does not list")
    check(len(params) == len(set(params)), f"{view} lists a param twice: {params}")
    check("legacy" not in params, f"{view}: ?legacy=1 is the server's switch to the legacy UI, never a screen's param")
    check(set(route.get("defaults", {})) <= set(params), f"{view} has a default for a param it does not read")
    check(set(route.get("filters", [])) <= set(params), f"{view} has a filter it does not read")

for kind, entry in table["kinds"].items():
    view = table["views"].get(entry["view"])
    check(view is not None, f"kind {kind} opens {entry['view']}, which has no row")
    check(entry["param"] in view["params"], f"kind {kind}: {entry['view']} does not read {entry['param']}")
    check(set(entry.get("requires", [])) <= set(view["params"]) - {entry["param"]},
          f"kind {kind} requires a param {entry['view']} does not read")

# Workspace hrefs written by hand, by file. A link built from the table never appears here.
# Each reader's commit takes its links off this list.
HAND_BUILT: dict = {}
SERVER_HREF = re.compile(r"/workspace/[a-z-]+\?")
CLIENT_HREF = re.compile(r"/workspace/[a-z-]+\?(?!legacy=1)")
found = {}
for path in sorted((ROOT / "oms" / "app").rglob("*.py")):
    if path.name == "workspace_routes.py":
        continue
    count = len(SERVER_HREF.findall(path.read_text(encoding="utf-8")))
    if count:
        found[path.relative_to(ROOT).as_posix()] = count
for path in sorted((ROOT / "frontend" / "src").rglob("*.ts*")):
    count = len(CLIENT_HREF.findall(path.read_text(encoding="utf-8")))
    if count:
        found[path.relative_to(ROOT).as_posix()] = count
check(found == HAND_BUILT,
      f"hand-built workspace hrefs {found}; build them with workspace_routes.app_url / workspace_href or "
      f"hrefForResource. Expected {HAND_BUILT}")

# Every kind, and every view no kind opens, has a case in the browser spec.
spec = (ROOT / "frontend" / "tests" / "routes.spec.ts").read_text(encoding="utf-8")
opened = {entry["view"] for entry in table["kinds"].values()}
for name in list(table["kinds"]) + [view for view in table["views"] if view not in opened]:
    check(re.search(rf"[\"'`]{re.escape(name)}[\"'`:]", spec), f"routes.spec.ts has no case for {name}")

check(workspace_href("ops") == "/workspace/ops", workspace_href("ops"))
check(workspace_href("ops", tab="command") == "/workspace/ops", "a param at its default is left out of the URL")
check(workspace_href("ops", tab="incidents") == "/workspace/ops?tab=incidents", workspace_href("ops", tab="incidents"))
try:
    workspace_href("ops", legacy="1")
    check(False, "a param the view does not read was written into its URL")
except ValueError:
    checks += 1
check(app_url("dataset", "d 1") == "/workspace/data-media?dataset=d+1", app_url("dataset", "d 1"))
check(app_url("pipeline_graph", "g1") == "/workspace/pipeline?graph=g1", app_url("pipeline_graph", "g1"))
check(app_url("aip_logic", "a") == "/workspace/aip?artifact=a", app_url("aip_logic", "a"))
check(app_url("object", "o", type="t") == "/workspace/object-explorer?type=t&object=o", app_url("object", "o", type="t"))
check(app_url("object_type", "t") == "/workspace/ontology?type=t", app_url("object_type", "t"))
check(workspace_href("ontology", type="t", section="overview") == "/workspace/ontology?type=t", "the overview section is the default and is left out")
check(workspace_href("ontology", type="t", page="releases") == "/workspace/ontology?type=t&page=releases", workspace_href("ontology", type="t", page="releases"))
try:
    app_url("object", "o")
    check(False, "an object's URL was built without its type")
except ValueError:
    checks += 1
try:
    app_url("no_such_kind", "x")
    check(False, "a kind with no row got a URL")
except KeyError:
    checks += 1

print(f"Workspace routes verified: {checks} assertions passed ({len(VIEWS)} views, {len(KINDS)} kinds).")

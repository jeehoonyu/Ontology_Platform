"""One app registry (GOAL_FOUNDATIONS A9).

`frontend/src/apps.json` lists the workspace apps. The sidebar, the command palette
and the client's view check read it, and nothing else in the client lists the apps.
The server's view list is a constant (the production image ships `frontend/dist`,
not the registry's source), and this holds it to the registry's ids plus the legacy
UI's own views. App.tsx's screen switch must cover the same ids: a registry entry
with no screen would fall through to a blank workspace.

Before A9 there were three hand-written lists that disagreed: `CORE_VIEWS` and
`NAV_ITEMS` in App.tsx, and the server's inline set of 27.
"""
import json
import os
import re
import tempfile
from pathlib import Path

tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tmpdir.name, 'registry.db')}"
os.environ["AUTH_MODE"] = "local"
os.environ["APP_ENV"] = "test"

from app.main import WORKSPACE_VIEWS  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "frontend" / "src"
checks = 0


def check(condition, message):
    global checks
    assert condition, message
    checks += 1


registry = json.loads((SRC / "apps.json").read_text(encoding="utf-8"))
ids = [app["id"] for app in registry["apps"]]
legacy = registry["legacy_only"]
check(len(ids) == len(set(ids)), f"an app is listed twice: {sorted(i for i in ids if ids.count(i) > 1)}")
check(not set(ids) & set(legacy), f"a view is both an app and legacy-only: {sorted(set(ids) & set(legacy))}")
for app in registry["apps"]:
    check(all(isinstance(app.get(key), str) and app[key] for key in ("id", "label", "description")),
          f"an app needs an id, a label and a description: {app}")

served = set(ids) | set(legacy)
check(WORKSPACE_VIEWS == served,
      f"the server's view list is not the registry's: serves {sorted(WORKSPACE_VIEWS - served)} it does not list, "
      f"and lacks {sorted(served - WORKSPACE_VIEWS)}")

app_tsx = (SRC / "App.tsx").read_text(encoding="utf-8")
check('from "./apps.json"' in app_tsx, "App.tsx reads the registry")
screens = set(re.findall(r'\{view === "([a-z-]+)" &&', app_tsx))
check(screens == set(ids),
      f"App.tsx's screen switch is not the registry: screens {sorted(screens - set(ids))} it does not list, "
      f"and no screen for {sorted(set(ids) - screens)}")

# Nothing else in the client lists the apps: no second literal of ten or more view ids.
for path in sorted(SRC.rglob("*.ts*")):
    text = path.read_text(encoding="utf-8", errors="replace")
    for literal in re.findall(r"\[([^\[\]]{200,})\]", text):
        named = {name for name in re.findall(r'"([a-z-]+)"', literal) if name in set(ids)}
        check(len(named) < 10, f"{path.relative_to(ROOT)} lists {len(named)} apps by hand: {sorted(named)[:6]}")

print(f"Workspace registry verified: {checks} assertions passed ({len(ids)} apps, {len(legacy)} legacy-only views).")

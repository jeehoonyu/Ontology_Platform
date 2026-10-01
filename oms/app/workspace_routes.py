"""Every resource kind's URL, the server's copy (GOAL_FOUNDATIONS A6).

`frontend/src/routes.json` is the source. The production image ships `frontend/dist`, not
`frontend/src` (oms/Dockerfile), so this is a constant, and `oms/test_workspace_routes.py`
holds it equal to the JSON, as `test_workspace_registry.py` does for `WORKSPACE_VIEWS`. Every
workspace link the server writes with a query is built here, so a link and the screen that
reads it cannot spell a param two ways. Before A6 the server spelled one id as `object_type`,
`object_type_id` and `objectType`, and no screen read any of them. Search's `app_url` (H2) and
the resource index (Q4) use it when they land.
"""
from __future__ import annotations

from typing import Any, Dict
from urllib.parse import urlencode

# Grows with routes.json, a row with each reader.
VIEWS: Dict[str, Dict[str, Any]] = {
    "ops": {"params": ["tab"], "defaults": {"tab": "command"}},
    "data-media": {"params": ["dataset"]},
}
KINDS: Dict[str, Dict[str, Any]] = {
    "dataset": {"view": "data-media", "param": "dataset"},
}


def workspace_href(view: str, **params: object) -> str:
    """A view's one spelling: declared params only, in the table's order, defaults left out."""
    route = VIEWS.get(view, {"params": []})
    undeclared = sorted(set(params) - set(route["params"]))
    if undeclared:
        raise ValueError(f"/workspace/{view} reads no {undeclared}")
    defaults = route.get("defaults", {})
    pairs = [(name, str(params[name])) for name in route["params"]
             if params.get(name) not in (None, "") and str(params[name]) != defaults.get(name)]
    return f"/workspace/{view}" + (f"?{urlencode(pairs)}" if pairs else "")


def app_url(kind: str, resource_id: str, **context: object) -> str:
    """The URL that opens one resource: a kind needs a row, and a screen reading it, first."""
    entry = KINDS[kind]
    missing = [name for name in entry.get("requires", []) if not context.get(name)]
    if missing:
        raise ValueError(f"a {kind} URL needs {missing}")
    return workspace_href(entry["view"], **context, **{entry["param"]: resource_id})

"""Count the handlers nothing authorizes, and ratchet it down.

R6 of GOAL_REPAIR_2026-08-23. Authorization here is two layers and only one of
them is per-route. A handler can declare
`Depends(production_auth.require_permission("edit"))`, and 572 of them do. The
rest fall through to `ProductionAuthorizationMiddleware`, which begins:

    if auth_mode() != "oidc":
        return await call_next(request)

`AUTH_MODE` defaults to `local`, where every caller resolves to a principal with
`permissions=["*"]` and `project_ids=["*"]`. So for the handlers with no
dependency of their own, the only gate is a middleware that disables itself
outside one deployment mode -- and `validate_auth_configuration()` refuses to
boot production without OIDC, which makes this a development-default problem
rather than a shipped open door, but not a measured one.

Nothing counted it. `audit_route_coverage` counts typed twins, `audit_request_cost`
counts statements, and neither asks whether a route checks anything. This does,
and the count is a ratchet: it may fall and must never rise, so a new handler
without a permission is loud on the commit that adds it.

**What is gated and what is reported.** The gate is *mutating* handlers with no
authorization -- POST, PUT, PATCH and DELETE, where an unauthorized caller
changes state. Unauthorized reads are reported and not gated, because several are
deliberately public and the ones that are not are a larger argument than a
ratchet should try to win in one commit.

Public paths come from `production_auth.PUBLIC_PREFIXES`, the tuple the
middleware itself uses, so this cannot judge a route the gate exempts.

  python oms/audit_auth_coverage.py
  python oms/audit_auth_coverage.py --verbose
  python oms/audit_auth_coverage.py --set-baseline
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, List

REPO_ROOT = Path(__file__).resolve().parent.parent
BASELINE = REPO_ROOT / "docs" / "auth-coverage-baseline.json"

MUTATING = {"POST", "PUT", "PATCH", "DELETE"}

# The closures require_permission and require_detached_permission return are both
# named `dependency`, so their qualified names carry the factory that built them.
# Matching on that rather than on the name alone keeps an unrelated inner
# function called `dependency` from reading as authorization.
AUTHORIZING = ("require_permission.", "require_detached_permission.")
PRINCIPAL_DEPENDENCIES = {"current_principal", "resolve_principal"}


def _authorizes(dependant: Any, seen: set) -> bool:
    """Does this route ask for a principal or a permission, anywhere in its tree?"""
    call = getattr(dependant, "call", None)
    if call is not None:
        identity = id(call)
        if identity in seen:
            return False
        seen.add(identity)
        qualname = getattr(call, "__qualname__", "")
        if any(marker in qualname for marker in AUTHORIZING):
            return True
        if getattr(call, "__name__", "") in PRINCIPAL_DEPENDENCIES:
            return True
    for sub in getattr(dependant, "dependencies", []) or []:
        if _authorizes(sub, seen):
            return True
    return False


def read() -> Dict[str, Any]:
    scratch = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
    os.environ["DATABASE_URL"] = f"sqlite:///{Path(scratch.name, 'auth-coverage.db').as_posix()}"
    os.environ["AUTH_MODE"] = "local"
    os.environ["APP_ENV"] = "test"
    os.environ["SKIP_CREATE_ALL"] = "1"
    sys.path.insert(0, str(REPO_ROOT / "oms"))

    from fastapi.routing import APIRoute

    from app.main import app
    from app.production_auth import PUBLIC_PREFIXES

    handlers: Dict[Any, Dict[str, Any]] = {}
    for route in app.routes:
        if not isinstance(route, APIRoute):
            continue
        path = route.path
        if path == "/" or path.startswith(PUBLIC_PREFIXES):
            continue
        # The generated /api/v1 aliases reuse the legacy endpoint object, so
        # counting routes would count each handler twice and report a surface
        # twice its real size. api_v1_compat asserts that identity in its own
        # test; this relies on it.
        endpoint = route.endpoint
        entry = handlers.setdefault(endpoint, {
            "module": getattr(endpoint, "__module__", "?").rsplit(".", 1)[-1],
            "name": getattr(endpoint, "__name__", "?"),
            "paths": [],
            "methods": set(),
            "authorized": True,
        })
        entry["paths"].append(path)
        entry["methods"].update(route.methods or set())
        # Every route reaching this handler must authorize, not merely one of
        # them. A handler gated on its legacy path and open on its generated
        # /api/v1 twin is an open handler, and taking the optimistic reading
        # would have reported it as covered.
        if not _authorizes(route.dependant, set()):
            entry["authorized"] = False

    rows = sorted(handlers.values(), key=lambda item: (item["module"], item["name"]))
    unauthorized = [row for row in rows if not row["authorized"]]
    mutating = [row for row in unauthorized if row["methods"] & MUTATING]
    modules: Dict[str, int] = {}
    for row in mutating:
        modules[row["module"]] = modules.get(row["module"], 0) + 1

    scratch.cleanup()
    return {
        "handlers": len(rows),
        "authorized": len(rows) - len(unauthorized),
        "unauthorized": len(unauthorized),
        "unauthorized_mutating": len(mutating),
        "modules": dict(sorted(modules.items(), key=lambda item: -item[1])),
        "sites": [{"module": row["module"], "name": row["name"],
                   "methods": sorted(row["methods"] & MUTATING),
                   "path": sorted(row["paths"])[0]} for row in mutating],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--set-baseline", action="store_true")
    args = parser.parse_args()

    reading = read()
    print(f"{reading['handlers']} non-public handlers: "
          f"{reading['authorized']} authorized, {reading['unauthorized']} not")
    print(f"  of those, {reading['unauthorized_mutating']} mutate state with no "
          f"permission of their own")
    for module, count in list(reading["modules"].items())[:12]:
        print(f"    {count:>4}  {module}")
    if args.verbose:
        for site in reading["sites"]:
            print(f"      {','.join(site['methods']):<18} {site['path']}  ({site['name']})")

    if args.set_baseline:
        BASELINE.write_text(json.dumps({
            "provenance": {
                "recorded_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "stale_after": "recomputed each run",
            },
            "note": ("Ratchet. Mutating handlers with no permission dependency of their "
                     "own, falling back to a middleware that disables itself outside "
                     "AUTH_MODE=oidc. This count may fall and must never rise. "
                     "Unauthorized reads are reported, not gated."),
            "unauthorized_mutating_ceiling": reading["unauthorized_mutating"],
            "unauthorized_read_reference": reading["unauthorized"] - reading["unauthorized_mutating"],
        }, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(f"\nBaseline set: ceiling {reading['unauthorized_mutating']}.")
        return 0

    if not BASELINE.exists():
        print("\nNo baseline recorded. Run with --set-baseline to start the ratchet.")
        return 0

    ceiling = json.loads(BASELINE.read_text(encoding="utf-8"))["unauthorized_mutating_ceiling"]
    if reading["unauthorized_mutating"] > ceiling:
        print(f"\nRATCHET BROKEN: {reading['unauthorized_mutating']} mutating handlers "
              f"authorize nothing, above the ceiling of {ceiling}.")
        return 1
    if reading["unauthorized_mutating"] < ceiling:
        print(f"\nRatchet held, and improved: {ceiling} -> "
              f"{reading['unauthorized_mutating']}. Re-run with --set-baseline.")
        return 0
    print(f"\nRatchet held: {reading['unauthorized_mutating']} <= {ceiling}.")
    return 0


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from enforcement_runs import recording  # noqa: E402

    sys.exit(recording("audit_auth_coverage", main))

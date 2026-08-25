"""The authorization census is executed here, not only declared.

R6 of GOAL_REPAIR_2026-08-23, and the suite home `audit_check_coverage` requires:
a check that needs no infrastructure and has no suite home is, in the registry's
own words, a defect rather than a configuration.

The census is the part worth asserting. It counts *handlers*, not routes, because
`api_v1_compat` clones every legacy route into `/api/v1` reusing the same endpoint
object -- counting routes would report a surface twice its real size and halve the
apparent severity of every gap. And it takes its public paths from
`production_auth.PUBLIC_PREFIXES`, the tuple the middleware itself branches on, so
the audit cannot judge a route the gate exempts.

  python oms/test_auth_coverage.py
"""
import io
import sys
from contextlib import redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import audit_auth_coverage  # noqa: E402

passed = 0


def check(condition, label, payload=None):
    global passed
    assert condition, f"{label}: {payload}"
    passed += 1


reading = audit_auth_coverage.read()

check(reading["handlers"] > 500,
      "the census sees the whole non-public surface", reading["handlers"])
check(reading["authorized"] > 0 and reading["unauthorized"] >= 0,
      "and splits it both ways", reading)
check(reading["authorized"] + reading["unauthorized"] == reading["handlers"],
      "every handler lands on exactly one side", reading)
check(reading["unauthorized_mutating"] <= reading["unauthorized"],
      "the gated subset is inside the reported one", reading)

from app.production_auth import PUBLIC_PREFIXES  # noqa: E402

check(PUBLIC_PREFIXES and all(prefix.startswith("/") for prefix in PUBLIC_PREFIXES),
      "public paths come from the middleware's own tuple", PUBLIC_PREFIXES)
for site in reading["sites"]:
    check(not site["path"].startswith(PUBLIC_PREFIXES),
          "so nothing the gate exempts is counted against it", site["path"])
    check(site["methods"], "and every gated site actually mutates", site)

# Counting routes rather than handlers would roughly double the surface: every
# eligible legacy route has an /api/v1 twin reusing the same endpoint object. Two
# different handlers may still share a path -- PATCH and DELETE on one resource
# are two functions -- so the invariant is the dedup, not path uniqueness.
from fastapi.routing import APIRoute  # noqa: E402

from app.main import app  # noqa: E402

routes = [route for route in app.routes
          if isinstance(route, APIRoute)
          and route.path != "/"
          and not route.path.startswith(PUBLIC_PREFIXES)]
check(reading["handlers"] < len(routes) * 0.75,
      "handlers are deduplicated across the generated /api/v1 aliases, so the "
      "count is the real surface rather than twice it",
      {"handlers": reading["handlers"], "routes": len(routes)})

# A local closure named `dependency` is not authorization; the qualified name of
# the factory that built it is what makes the match trustworthy.
class _Fake:
    dependencies = ()

    def __init__(self, call):
        self.call = call


def _unrelated():
    def dependency():
        return None
    return dependency


from app.production_auth import require_permission  # noqa: E402

check(audit_auth_coverage._authorizes(_Fake(require_permission("edit")), set()),
      "a require_permission dependency reads as authorization")
check(not audit_auth_coverage._authorizes(_Fake(_unrelated()), set()),
      "and an unrelated inner function called `dependency` does not")
check(not audit_auth_coverage._authorizes(_Fake(lambda: None), set()),
      "nor a bare callable with no dependencies of its own")

argv = sys.argv[:]
sys.argv = ["audit_auth_coverage"]
try:
    with redirect_stdout(io.StringIO()) as captured:
        code = audit_auth_coverage.main()
finally:
    sys.argv = argv
check(code == 0, "and the ratchet holds against its recorded ceiling",
      captured.getvalue()[-200:])

print(f"Authorization coverage verified: {passed} assertions passed "
      f"({reading['unauthorized_mutating']} mutating handlers still unauthorized).")

"""The orphan census is executed here, not merely declared.

Suite home for `audit_tenant_orphans`, which `audit_check_coverage` requires.

The census rests on two claims, and these assertions hold it to both. The first is
structural: a table inherits a tenant through its foreign keys, so a child of a
project-carrying parent is tenanted even though it carries no column of its own. If that
walk stopped at depth one the count would balloon with rows that are perfectly well
scoped. The second is that the substrate list is an exemption, and an exemption nobody
rechecks is how a real gap gets filed as fine -- so a listed table that has since gained
a tenant, or vanished, must fail rather than sit unread.

  python oms/test_tenant_orphans.py
"""
import io
import json
import sys
from contextlib import redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import audit_tenant_orphans  # noqa: E402

passed = 0


def check(condition, label, payload=None):
    global passed
    assert condition, f"{label}: {payload}"
    passed += 1


reading = audit_tenant_orphans.read()

check(reading["tables"] > 250, "the census sees the whole schema", reading["tables"])
check(reading["tenanted"] + reading["untenanted"] == reading["tables"],
      "every table lands in exactly one column", reading)
check(reading["substrate"] + len(reading["orphans"]) == reading["untenanted"],
      "and the untenanted split accounts for all of them", reading)
check(reading["tenanted"] > len(reading["orphans"]),
      "most tables do name a tenant -- if that inverted, the walk is broken rather "
      "than the schema", reading)
check(not reading["stale_substrate"],
      "no exemption outlives its subject", reading["stale_substrate"])

# The foreign-key walk is the whole basis for calling a child tenanted. A table with no
# project_id of its own that reaches one through a parent must not be counted as debt.
orphans = set(reading["orphans"])
check("ArtifactRevision" not in orphans,
      "a revision inherits its artifact's project through a foreign key", "ArtifactRevision")
check("ObjectInstance" not in orphans,
      "a table carrying project_id outright is never untenanted", "ObjectInstance")

# The findings that opened this census. Each is a table a route serves and no read of it
# can be scoped, because there is nothing to scope it to.
for named in ("NotepadDocument", "SlateApp", "AtmAutomation"):
    check(named in orphans, f"{named} is counted -- it is why this audit exists", named)

substrate = json.loads(audit_tenant_orphans.SUBSTRATE.read_text(encoding="utf-8"))["substrate"]
check(all(isinstance(reason, str) and len(reason) > 20 for reason in substrate.values()),
      "every exemption records why, in a sentence rather than a word", substrate)
check("AdminUser" in substrate and "AdminProject" in substrate,
      "projects and their users are what a tenant is made of, not work inside one", None)

first = audit_tenant_orphans.read()
check(first["orphans"] == reading["orphans"],
      "the census is reproducible, or a ratchet on it means nothing", None)

argv = sys.argv[:]
sys.argv = ["audit_tenant_orphans"]
try:
    with redirect_stdout(io.StringIO()) as captured:
        code = audit_tenant_orphans.main()
finally:
    sys.argv = argv
check(code == 0, "and the ratchet holds against its recorded ceiling",
      captured.getvalue()[-200:])

print(f"Tenant-orphan census verified: {passed} assertions passed "
      f"({len(reading['orphans'])} orphan tables, {reading['substrate']} exempt).")

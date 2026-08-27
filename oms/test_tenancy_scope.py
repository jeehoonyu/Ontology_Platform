"""The tenancy census is executed here, not merely declared.

Suite home for `audit_tenancy_scope`, which `audit_check_coverage` requires: a
check that needs no infrastructure and has no suite home is, in the registry's own
words, a defect rather than a configuration.

What is worth asserting about this census is mostly what it does NOT claim. Six
lines of proximity is a coarse proxy for "this read is scoped" and is wrong in
both directions; the file says so, and these assertions hold it to the two things
it can actually support — that it distinguishes project-scoped models from the
tenancy substrate, and that its count is reproducible so a ratchet on it means
something.

  python oms/test_tenancy_scope.py
"""
import io
import sys
from contextlib import redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import audit_tenancy_scope  # noqa: E402

passed = 0


def check(condition, label, payload=None):
    global passed
    assert condition, f"{label}: {payload}"
    passed += 1


reading = audit_tenancy_scope.read()

check(reading["scoped_models"] > 50,
      "the census finds the project-scoped models", reading["scoped_models"])
check(reading["scoped_reads"] > reading["unscoped_reads"],
      "and most reads of them do name a project -- if that inverted, the proxy is "
      "measuring something else", reading)
check(reading["unscoped_reads"] == len(reading["sites"]),
      "the count is the sites, not a separate tally", reading["unscoped_reads"])
check(sum(reading["modules"].values()) == reading["unscoped_reads"],
      "and the per-module breakdown adds up", reading["modules"])

# Reproducible, or a ratchet on it is noise.
again = audit_tenancy_scope.read()
check(again["unscoped_reads"] == reading["unscoped_reads"],
      "the census is deterministic", (reading["unscoped_reads"], again["unscoped_reads"]))

# The substrate is not counted. admin_users has no project and never should: it is
# the table that defines what a project's members are.
scoped = audit_tenancy_scope.scoped_classes()
for substrate in ("AdminUser", "AdminOrganization", "AdminProject"):
    check(substrate not in scoped,
          f"{substrate} is tenancy substrate, not a tenant-scoped row", sorted(scoped)[:6])
for tenant_row in ("ObjectInstance", "LinkInstance", "DataAsset"):
    check(tenant_row in scoped,
          f"{tenant_row} is a tenant-scoped row and is counted", tenant_row)

# The detector must recognise both query shapes, or a module could evade it by
# switching from db.query to db.get.
import ast  # noqa: E402

for shape in ("db.query(models.ObjectInstance)", "db.get(models.ObjectInstance, oid)",
              "db.query(ObjectInstance)"):
    node = ast.parse(shape, mode="eval").body
    check(audit_tenancy_scope._queried_class(node, scoped) == "ObjectInstance",
          f"the census recognises `{shape}`")
for benign in ("db.query(AdminUser)", "isinstance(row, ObjectInstance)", "db.commit()"):
    node = ast.parse(benign, mode="eval").body
    check(audit_tenancy_scope._queried_class(node, scoped) is None,
          f"and does not count `{benign}`")

argv = sys.argv[:]
sys.argv = ["audit_tenancy_scope"]
try:
    with redirect_stdout(io.StringIO()) as captured:
        code = audit_tenancy_scope.main()
finally:
    sys.argv = argv
check(code == 0, "and the ratchet holds against its recorded ceiling",
      captured.getvalue()[-200:])

print(f"Tenancy scope census verified: {passed} assertions passed "
      f"({reading['unscoped_reads']} unscoped reads of {reading['scoped_reads']}).")

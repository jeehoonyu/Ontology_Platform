"""No test or operator script pins the migration head as a literal.

R14 of GOAL_REPAIR_2026-08-23. Twenty-seven of the suite's scripts asserted
`version == "0042_stream_outer_joins"` immediately after `alembic upgrade head`,
and `scripts/rehearse-recovery.ps1` seeded a synthetic `alembic_version` row with
the same string. Fifty-five files repository-wide carried the literal.

The effect was that **the schema could not move.** Any new revision reddened
twenty-seven scripts at once, none of them for a reason connected to what the
revision did. That is not a safety net; it is a lock, and it was quietly blocking
three of the five items under R8 -- two of which need a table dropped.

The distinction this file draws is between the two things a head literal can mean.
Asserting *"the database reached the head this repository declares"* is a real
check and must read the head. Recording *"this evidence was taken at head X"* is a
fact about a past measurement, and those literals belong in `docs/*evidence*.json`
where `audit_evidence_corpus.py` reads them and reports CURRENT or STALE. So this
gate covers the suite and the operator scripts, and deliberately does not cover
the evidence corpus or the migration files themselves.

  python oms/test_migration_head_not_pinned.py
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from tier_b_evidence import current_head  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[1]

# Only the *head* is forbidden, and the distinction is the whole rule. A migration
# test seeds a database at an older revision on purpose -- `0003_platform_job_leases`
# is the starting point of the upgrade being tested, a historical fact that will
# never move. The head is the one id that changes every time anyone adds a revision,
# so it is the only one a literal can go stale against. A first draft of this file
# forbade every revision id and reported 60 offenders, all of them correct.
def head_literal(head: str) -> "re.Pattern[str]":
    return re.compile(r"""["']""" + re.escape(head) + r"""["']""")

# Where a literal is a legitimate record rather than a pin.
EXEMPT = (
    REPO_ROOT / "oms" / "alembic",          # the chain declares its own ids
    REPO_ROOT / "docs",                     # evidence records the head it was taken at
)

passed = 0


def check(condition, label, payload=None):
    global passed
    assert condition, f"{label}: {payload}"
    passed += 1


head = current_head()
HEAD_LITERAL = head_literal(head)
check(re.fullmatch(r"\d{4}_[a-z0-9_]+", head), "the head is readable from the chain", head)
check(HEAD_LITERAL.fullmatch(f'"{head}"'), "and the pattern catches it as a literal", head)

scanned, offenders = 0, []
# The workflows are in scope, and were not on the first pass. CI pinned the head
# in an inline assertion inside the PostgreSQL job, and the very first run this
# repository ever completed failed on it -- a gate written to stop head pins,
# missing the pin in the file that runs the gates.
targets = sorted(REPO_ROOT.glob("oms/test_*.py")) + \
    sorted(REPO_ROOT.glob("scripts/*.ps1")) + sorted(REPO_ROOT.glob("scripts/*.sh")) + \
    sorted(REPO_ROOT.glob(".github/workflows/*.yml"))
for path in targets:
    if any(str(path).startswith(str(exempt)) for exempt in EXEMPT):
        continue
    if path.name == Path(__file__).name:
        continue
    scanned += 1
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if line.lstrip().startswith("#"):
            continue
        for found in HEAD_LITERAL.findall(line):
            offenders.append(f"{path.relative_to(REPO_ROOT)}:{number} {found}")

check(scanned > 200, "the scan covers the suite and the operator scripts", scanned)
check(not offenders,
      "no test or operator script pins a migration head; read it with "
      "tier_b_evidence.current_head() instead",
      offenders[:8])

# The gate has to be able to fail, or it is decoration.
check(HEAD_LITERAL.search(f'assert version == "{head}"'),
      "a pinned head is detected")
check(not HEAD_LITERAL.search("assert version == current_head()"),
      "and the correct form is not")
check(not HEAD_LITERAL.search('seed = "0003_platform_job_leases"'),
      "an older revision is left alone -- it is a starting point, not a moving target")
check(not head_literal("0043_a_future_revision").search(f'assert version == "{head}"'),
      "and the gate tracks the head rather than any fixed string")

print(f"Migration head pinning verified: {passed} assertions passed "
      f"({scanned} files scanned, 0 pinned literals, head reads as {head}).")

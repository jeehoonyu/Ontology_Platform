"""Migration head must identify the schema it names.

`0001_runtime_baseline` calls Base.metadata.create_all(checkfirst=True), so the
baseline is not immutable: it materializes whatever the ORM defines at the moment
it runs. A database created today gets every current table. A database that ran
0001 a year ago got the tables that existed then, and no later migration adds the
rest.

Both report the same head. That makes migration head an unreliable identity for
the schema, which matters beyond upgrades: `migration_head` is the staleness key
in every Tier B evidence file, so two files can both read CURRENT at the same
head while describing different schemas.

This test ratchets the gap. It may shrink and must not grow: a new table needs an
explicit migration, or it will never reach a deployment that already passed the
baseline.
"""
import os
import pathlib
import re
import sys

os.environ.setdefault("SKIP_CREATE_ALL", "1")
os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("AUTH_MODE", "local")
os.environ.setdefault(
    "DATABASE_URL",
    "sqlite:///" + str(pathlib.Path(__file__).parent / "schema_identity_probe.db"),
)

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from app.database import Base  # noqa: E402
from app import main  # noqa: E402,F401 - registers every model on Base.metadata

# Recorded 2026-08-03. This is a ceiling, not a target. Lower it whenever an
# explicit migration is added for one of these tables; never raise it.
BASELINE_ONLY_CEILING = 215

passed = 0


def check(condition, label, payload=None):
    global passed
    assert condition, f"{label}: {payload}"
    passed += 1


versions = pathlib.Path(__file__).resolve().parent / "alembic" / "versions"
check(versions.is_dir(), "the migration directory is present", str(versions))

baseline = (versions / "0001_runtime_baseline.py").read_text(encoding="utf-8")
check("create_all" in baseline,
      "the baseline still materializes from ORM metadata; if this changed, "
      "this test's premise needs revisiting")

explicitly_created = set()
for path in versions.glob("*.py"):
    if path.name.startswith("0001_"):
        continue
    text = path.read_text(encoding="utf-8")
    explicitly_created |= set(re.findall(r'create_table\(\s*["\']([a-z0-9_]+)["\']', text))

orm_tables = set(Base.metadata.tables)
baseline_only = sorted(orm_tables - explicitly_created)

check(len(orm_tables) > 200, "the ORM defines the full schema", len(orm_tables))
check(explicitly_created, "some tables have explicit migrations", len(explicitly_created))
check(
    len(baseline_only) <= BASELINE_ONLY_CEILING,
    "tables reachable only through the baseline did not increase. A new table "
    "without an explicit migration never reaches a database that already passed "
    "0001, while still reporting the same head",
    {"now": len(baseline_only), "ceiling": BASELINE_ONLY_CEILING,
     "sample": baseline_only[:10]},
)

# The interface tables are a concrete instance worth naming: they are real,
# tested, and routed, yet reach an existing deployment only if it was created
# after the models were added.
for table in ("ontology_interfaces", "shared_property_types"):
    check(table in orm_tables, f"{table} is defined by the ORM", sorted(orm_tables)[:5])

print(f"\nSchema identity verified: {passed} assertions passed. "
      f"{len(baseline_only)} of {len(orm_tables)} tables reach a database only "
      f"through the baseline (ceiling {BASELINE_ONLY_CEILING}).")

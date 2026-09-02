"""The reconciliation rule for an object type's project is asserted, not assumed.

This schema records that project twice -- the `ObjectType.project_id` column and
`properties["__manager"]["project_id"]` -- and nothing keeps them in agreement. Seven
modules each carried their own copy of the same expression for reading the second one, so
"which project owns this type" had seven answers that happened to coincide. It now has
one, and these assertions pin the rule that one implements, because a silent change to it
moves rows between tenants.

T11 of GOAL_TENANCY_2026-08-27 is the recording; this is the reading.

  python oms/test_semantic_scope.py
"""
import os
import sys
import tempfile
from pathlib import Path

_scratch = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
os.environ["DATABASE_URL"] = f"sqlite:///{Path(_scratch.name, 'scope.db').as_posix()}"
sys.path.insert(0, str(Path(__file__).resolve().parent))

from app import models, semantic_scope  # noqa: E402

passed = 0


def check(condition, label, payload=None):
    global passed
    assert condition, f"{label}: {payload}"
    passed += 1


def object_type(column, manager):
    properties = {"__manager": {"project_id": manager}} if manager is not None else {}
    return models.ObjectType(id="t", display_name="T", description=None,
                             project_id=column, properties=properties,
                             created_at=1, updated_at=1)


read = semantic_scope.object_type_project

# The column wins wherever it says anything, because authorization already uses it:
# `owned_row` checks it, and POST /objects refuses a 409 when it disagrees.
check(read(object_type("alpha", "beta")) == "alpha",
      "a set column outranks the manager blob", read(object_type("alpha", "beta")))
check(read(object_type("alpha", None)) == "alpha",
      "a set column stands alone", None)

# "default" is what the column says when nobody set it, so it is not an answer. Dropping
# the blob there would silently move those types into the default project -- which is the
# failure that reverted the runtime change this rule came out of.
check(read(object_type("default", "alpha-workshop")) == "alpha-workshop",
      "an unset column yields to a manager naming a real project", None)
check(read(object_type("default", None)) == "default",
      "and falls back to default when neither names anything", None)
check(read(object_type("", "alpha")) == "alpha",
      "an empty column is not an answer either", None)

# Shapes that reach this from stored JSON, where a blob is whatever was written.
check(read(object_type("default", "")) == "default", "an empty manager project is ignored", None)
malformed = models.ObjectType(id="t", display_name="T", description=None, project_id="default",
                              properties={"__manager": "not-a-dict"}, created_at=1, updated_at=1)
check(read(malformed) == "default", "a manager that is not a mapping does not raise", None)
bare = models.ObjectType(id="t", display_name="T", description=None, project_id="alpha",
                         properties=None, created_at=1, updated_at=1)
check(read(bare) == "alpha", "properties may be null", None)

# The point of the accessor is that there is exactly one of it.
app_dir = Path(__file__).resolve().parent / "app"
inline = [path.name for path in sorted(app_dir.glob("*.py"))
          if path.name != "semantic_scope.py"
          and '.get("__manager") or {}).get("project_id")' in path.read_text(encoding="utf-8")]
check(not inline, "no module reads the manager project except semantic_scope", inline)

print(f"Semantic scope reconciliation verified: {passed} assertions passed.")

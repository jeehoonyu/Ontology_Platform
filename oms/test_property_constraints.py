"""Declared property constraints are enforced on write.

R4 of GOAL_REPAIR_2026-08-23. `ontology_core.ObjectTypePropertyCreate` has
accepted `minimum`, `maximum`, `min_length`, `max_length`, `pattern` and `enum`
for as long as the field has existed. `_validate_property_constraints` checked
that they were mutually consistent -- that a minimum did not exceed its maximum --
and then nothing ever compared a value against any of them. An enum-constrained
property accepted any string.

Two quieter halves of the same finding are asserted here too, because fixing only
the loud one would have left the fix inert:

  *The type key is spelled twice.* `ObjectType.properties` carries `type`;
  `ObjectTypeProfile.properties` carries `base_type` and deliberately omits
  `type`. `_schema_type` read `type` alone, and `_matches_type(value, None)` is
  True -- so pointing validation at the live schema, which R3 did, would have
  validated nothing at all for precisely the types that had been edited. The
  cure looked like the disease: more validation, less checking.

  *Archived properties were still enforced.* A property retired with
  `status: "archived"` kept its `required` flag, so retiring a property made
  every subsequent write fail until the data caught up with a schema nobody
  intended to apply.

  python oms/test_property_constraints.py
"""
import os
import tempfile

tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
if not os.environ.get("DATABASE_URL"):
    os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tmpdir.name, 'constraints.db')}"

import sys  # noqa: E402
from pathlib import Path  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))

from app import models  # noqa: E402
from app.runtime import _schema_type, validate_object_properties  # noqa: E402

passed = 0


def check(condition, label, payload=None):
    global passed
    assert condition, f"{label}: {payload}"
    passed += 1


TYPE = models.ObjectType(id="t", display_name="T", description="", properties={},
                         project_id="p", created_at=0, updated_at=0)


def errors_for(schema, properties):
    return validate_object_properties(TYPE, properties, schema=schema)


def rejects(schema, properties, label, fragment=None):
    found = errors_for(schema, properties)
    check(found, label, "accepted")
    if fragment:
        check(any(fragment in error for error in found),
              f"{label} -- and says why", found)


def accepts(schema, properties, label):
    check(errors_for(schema, properties) == [], label, errors_for(schema, properties))


# --- the six constraint kinds -------------------------------------------------

enum_spec = {"grade": {"type": "string", "enum": ["A", "B"]}}
rejects(enum_spec, {"grade": "C"}, "enum rejects a value outside the set", "must be one of")
accepts(enum_spec, {"grade": "A"}, "and accepts one inside it")

pattern_spec = {"sku": {"type": "string", "pattern": "^SKU-"}}
rejects(pattern_spec, {"sku": "X-1"}, "pattern rejects a non-match", "does not match pattern")
accepts(pattern_spec, {"sku": "SKU-1"}, "and accepts a match")

range_spec = {"n": {"type": "integer", "minimum": 1, "maximum": 5}}
rejects(range_spec, {"n": 0}, "minimum rejects a value below it", "below the minimum")
rejects(range_spec, {"n": 9}, "maximum rejects a value above it", "above the maximum")
accepts(range_spec, {"n": 3}, "and a value inside the range passes")

length_spec = {"name": {"type": "string", "min_length": 3, "max_length": 5}}
rejects(length_spec, {"name": "ab"}, "min_length rejects a short string", "shorter than")
rejects(length_spec, {"name": "abcdef"}, "max_length rejects a long one", "longer than")
accepts(length_spec, {"name": "abcd"}, "and one in range passes")

list_spec = {"tags": {"type": "array", "max_length": 2}}
rejects(list_spec, {"tags": [1, 2, 3]}, "length applies to lists as well as strings")
accepts(list_spec, {"tags": [1, 2]}, "and a short enough list passes")

# --- the constraints must not fire where they were never declared -------------

accepts({"free": {"type": "string"}}, {"free": "anything at all"},
        "a property with no constraints is unconstrained")
accepts({"other": {"type": "string", "enum": ["A"]}}, {"unrelated": "x"},
        "and a constraint on one property does not judge another")

# `bool` is an `int` in Python, so an unguarded numeric bound would silently
# compare True against a minimum nobody declared it for.
rejects({"flag": {"type": "integer", "minimum": 5}}, {"flag": True},
        "a boolean is caught as a type error rather than range-checked",
        "expected integer")

# A wrong type makes range and length meaningless; reporting both buries the
# cause under its consequence.
found = errors_for({"n": {"type": "integer", "minimum": 5}}, {"n": "x"})
check(len(found) == 1, "one error, not two, when the type is already wrong", found)

# An unusable pattern is a defect in the schema, not in the row.
accepts({"s": {"type": "string", "pattern": "([unclosed"}}, {"s": "anything"},
        "a malformed pattern does not fail the write that happens to hit it")

# --- base_type is the profile's spelling of type ------------------------------

check(_schema_type({"type": "string"}) == "string", "the column's spelling is read")
check(_schema_type({"base_type": "double"}) == "number",
      "the profile's spelling is read, and mapped to its runtime type",
      _schema_type({"base_type": "double"}))
check(_schema_type({"type": "string", "base_type": "double"}) == "string",
      "an explicit type wins over base_type")
check(_schema_type({}) is None, "and a spec declaring neither still declares nothing")

rejects({"amt": {"base_type": "double"}}, {"amt": "x"},
        "so a profile-backed property is type-checked at all", "expected number")
accepts({"amt": {"base_type": "double"}}, {"amt": 1.5},
        "and accepts the type it declares")
rejects({"grade": {"base_type": "string", "enum": ["A"]}}, {"grade": "Z"},
        "and its constraints are enforced too", "must be one of")

# --- archived properties are being retired, not enforced ----------------------

archived = {"old": {"base_type": "string", "required": True, "status": "archived"}}
accepts(archived, {}, "an archived property is not required")
accepts(archived, {"old": "x"}, "nor constrained on the way out")
accepts({"old": {"base_type": "string", "enum": ["A"], "status": "archived"}},
        {"old": "not-in-the-enum"}, "including its enum")

active = {"live": {"base_type": "string", "required": True, "status": "active"}}
rejects(active, {}, "while an active one is still required", "Missing required property")
accepts({"implicit": {"base_type": "string", "required": True}}, {"implicit": "x"},
        "and a spec with no status is treated as active")
rejects({"implicit": {"base_type": "string", "required": True}}, {},
        "in both directions", "Missing required property")

print(f"Property constraints verified: {passed} assertions passed "
      f"(6 constraint kinds, both type spellings, archived skipped).")

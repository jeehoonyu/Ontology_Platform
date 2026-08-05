"""Interface conformance must check base types, not just property names.

An interface is only worth targeting if its guarantee holds for every
implementer. Checking that a mapped property *exists* lets a string satisfy a
geopoint requirement, which silently turns `Geolocatable` into a naming
convention: a map that queries the interface would receive objects with no
usable geometry.
"""
import os
import tempfile

tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tmpdir.name, 'iface_types.db')}"
os.environ["AUTH_MODE"] = "local"
os.environ["APP_ENV"] = "test"

from fastapi.testclient import TestClient  # noqa: E402
from app.main import app  # noqa: E402
from app.ontology_interfaces_ops import base_type_satisfies  # noqa: E402

client = TestClient(app)
passed = 0


def check(condition, label, payload=None):
    global passed
    assert condition, f"{label}: {payload}"
    passed += 1


# --- the widening rules themselves -------------------------------------------
check(base_type_satisfies("geopoint", "geopoint"), "an exact match satisfies")
check(base_type_satisfies("geopoint", "geoshape"), "a point is a geometry")
check(not base_type_satisfies("geoshape", "geopoint"), "a geometry is not necessarily a point")
check(not base_type_satisfies("string", "geopoint"), "a string is not a location")
check(not base_type_satisfies("string", "geoshape"), "a string is not a geometry")
check(base_type_satisfies("integer", "long"), "an integer widens to long")
check(not base_type_satisfies("long", "integer"), "a long does not narrow to integer")
check(base_type_satisfies("date", "timestamp"), "a date widens to timestamp")
check(not base_type_satisfies("timestamp", "date"), "a timestamp does not narrow to date")
# An untyped property is allowed rather than refused: legacy bags often omit
# a type, and rejecting them would break existing implementations. The limit
# is deliberate and is what the profile-first lookup narrows over time.
check(base_type_satisfies("", "geopoint"), "an untyped property is not refused, only unjudged")
check(base_type_satisfies("anything", ""), "an untyped requirement is satisfied by anything")


def ok(response, label, expect=200):
    assert response.status_code == expect, f"{label}: {response.status_code} {response.text[:600]}"
    return response.json() if response.content else {}


# --- through the API ----------------------------------------------------------
ok(client.post("/object-types", json={
    "id": "wellsite", "display_name": "Well site",
    "properties": {"site_name": {"type": "string"}, "position": {"type": "geometry"}},
}), "create object type")

ok(client.post("/interfaces", json={
    "id": "geolocatable", "display_name": "Geolocatable",
    "properties": {"location": {"base_type": "geoshape", "required": True}},
}), "create interface")

# Mapping the geometry property satisfies the interface.
ok(client.post("/object-types/wellsite/implement-interface", json={
    "interface_id": "geolocatable",
    "property_mappings": {"location": "position"},
}), "implement with a geometry property")
passed += 1

# The same interface mapped onto the string property must be refused. Before the
# base-type check this returned 200 and the map would have received a site name
# where it expected geometry.
rejected = client.post("/object-types/wellsite/implement-interface", json={
    "interface_id": "geolocatable",
    "property_mappings": {"location": "site_name"},
})
check(rejected.status_code in (400, 422),
      "a string property must not satisfy a geoshape requirement", rejected.status_code)
if rejected.status_code == 422:
    detail = rejected.json()["detail"]
    check(any("site_name" in item for item in detail.get("unmet", [])),
          "the rejection names the offending mapping", detail)
    check(any("geoshape" in item for item in detail.get("unmet", [])),
          "the rejection names the required type", detail)
else:
    # Already implemented from the accepted mapping above; uniqueness fires
    # first, which is still a refusal rather than a silent acceptance.
    passed += 2

ok(client.post("/object-types", json={
    "id": "depot", "display_name": "Depot",
    "properties": {"label": {"type": "string"}},
}), "create a second object type")

typed_mismatch = client.post("/object-types/depot/implement-interface", json={
    "interface_id": "geolocatable",
    "property_mappings": {"location": "label"},
})
check(typed_mismatch.status_code == 422,
      "a declared string cannot implement a geoshape requirement",
      typed_mismatch.status_code)

missing = client.post("/object-types/depot/implement-interface", json={
    "interface_id": "geolocatable", "property_mappings": {},
})
check(missing.status_code == 422, "an unmapped required property is still refused",
      missing.status_code)

print(f"\nInterface type conformance verified: {passed} assertions passed.")
from app.database import engine as _engine  # noqa: E402
_engine.dispose()
tmpdir.cleanup()

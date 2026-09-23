"""Extensibility measurement and its ratchets."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import audit_extensibility as audit  # noqa: E402

passed = 0


def check(condition, label, payload=None):
    global passed
    assert condition, f"{label}: {payload}"
    passed += 1


declared = audit.declared_base_types()
check(len(declared) >= 20, "the base-type vocabulary is parsed", len(declared))
for expected in ("geopoint", "geoshape", "timeSeries", "marking", "vector", "struct"):
    check(expected in declared, f"{expected} is a declared base type", declared)

# The spatial types must be declared before GIS work extends them. If these ever
# vanish from the vocabulary, map rendering loses its type basis silently.
check("geopoint" in declared and "geoshape" in declared, "spatial types are declared")

reading = audit.measure()
for key in ("declared_base_types", "renderable_base_types", "ontology_type_coupling",
            "interfaces_configured", "unrendered_semantic_types"):
    check(key in reading, f"measurement reports {key}", sorted(reading))

check(reading["renderable_base_types"] + len(reading["unrendered_semantic_types"])
      == reading["semantic_base_types"],
      "every semantic type is either rendered or listed as unrendered", reading)

# Authoring surfaces must not count as rendering. The ontology editor has a
# dropdown containing every base type; counting it would report full coverage
# while the product still shows a geoshape as raw text.
sources = audit.ui_sources()
editors = [p for p in sources if "OntologyManager" in p.name]
check(editors, "the ontology editor is among the scanned sources", len(sources))
check("geoshape" not in audit.renderable_base_types(editors),
      "a base type named only in the authoring editor is not counted as renderable")

baseline_path = audit.BASELINE
check(baseline_path.exists(), "a baseline is recorded", str(baseline_path))
baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
check("renderable_base_types_floor" in baseline, "the floor is recorded", baseline)
check("ontology_type_coupling_ceiling" in baseline, "the ceiling is recorded", baseline)

check(reading["renderable_base_types"] >= baseline["renderable_base_types_floor"],
      "renderable base types hold their floor",
      {"now": reading["renderable_base_types"], "floor": baseline["renderable_base_types_floor"]})
check(reading["ontology_type_coupling"] <= baseline["ontology_type_coupling_ceiling"],
      "object-type coupling holds its ceiling",
      {"now": reading["ontology_type_coupling"], "ceiling": baseline["ontology_type_coupling_ceiling"]})

# A JavaScript type guard names a JavaScript type, not an object type. The
# ontology manager's `typeof objectType === "object"` was the one coupling this
# audit reported from its first baseline until 2026-09-23.
check(audit.coupling_matches('const ok = typeof objectType === "object";') == [],
      "a typeof guard is not an object-type coupling")
check(audit.coupling_matches('if (objectType === "pump_station") {}') == ["pump_station"],
      "a comparison with an object-type id is a coupling")
check(audit.coupling_matches('open({ objectTypeId: "work_order" })') == ["work_order"],
      "an object-type id passed as a literal is a coupling")
check(audit.coupling_matches('typeof x; objectType === "pump_station"') == ["pump_station"],
      "a typeof elsewhere on the line does not hide a real coupling")

# The writer leaves `provenance` to enforcement_runs.recording(), which dates
# every baseline a command-line run rewrites; the committed file must carry it.
check(baseline.get("provenance", {}).get("recorded_at"),
      "the committed baseline is dated", baseline)

# interfaces_configured is the flag Stage 1 flips. It is asserted as a boolean
# rather than as False so this test does not have to be edited to land the
# feature it is watching for.
check(isinstance(reading["interfaces_configured"], bool),
      "interface configuration is reported as a boolean", reading["interfaces_configured"])

print(f"\nExtensibility audit verified: {passed} assertions passed.")

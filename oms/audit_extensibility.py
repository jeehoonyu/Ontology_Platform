"""Measure what the next object type, view, and program will cost.

The standing goal's first invariant guards against evidence decay. This measures
the other decay: an ontology can stay perfectly proven while the platform around
it becomes impossible to extend, because every new object type needs new UI code
and every new view needs new backend code.

Three readings, each a ratchet:

  renderable_base_types    How many declared property base types the UI can
                           render from ontology metadata alone. A geoshape or a
                           timeSeries that falls through to generic text is a
                           type the ontology understands and the product does
                           not.
  ontology_type_coupling   Occurrences of a concrete object-type identifier in
                           UI source. Each one is a place a new object type will
                           not reach without an edit.
  interfaces_configured    Whether the ontology supports polymorphism at all.
                           Without it every cross-type view is written per type.

  python oms/audit_extensibility.py
  python oms/audit_extensibility.py --set-baseline
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List

REPO_ROOT = Path(__file__).resolve().parent.parent
FRONTEND_SRC = REPO_ROOT / "frontend" / "src"
ONTOLOGY_CORE = REPO_ROOT / "oms" / "app" / "ontology_core.py"
BASELINE = REPO_ROOT / "docs" / "extensibility-baseline.json"

# Property base types whose meaning is lost when rendered as generic text.
# A string rendered as text is correct; a geoshape rendered as raw GeoJSON, or a
# marking rendered as its raw identifier, is a semantic the product discards.
SEMANTIC_BASE_TYPES = (
    "geopoint", "geoshape", "timestamp", "date", "timeSeries", "attachment",
    "mediaReference", "marking", "vector", "cipherText", "struct", "array", "decimal",
)


def declared_base_types() -> List[str]:
    source = ONTOLOGY_CORE.read_text(encoding="utf-8")
    block = source.split("FOUNDRY_BASE_TYPES", 1)[1].split("}\n\n", 1)[0]
    return sorted(set(re.findall(r'^\s*"([A-Za-z]+)":\s*\{', block, re.MULTILINE)))


def ui_sources() -> List[Path]:
    if not FRONTEND_SRC.exists():
        return []
    return sorted(p for p in FRONTEND_SRC.rglob("*.tsx")) + \
        sorted(p for p in FRONTEND_SRC.rglob("*.ts") if "types.ts" not in p.name)


def renderable_base_types(sources: List[Path]) -> List[str]:
    """Base types the UI dispatches on explicitly rather than stringifying.

    Looks for the base type name appearing in a rendering decision -- a
    comparison, a lookup key, or a switch arm -- not merely as a form option in
    the ontology editor, which is authoring rather than rendering.
    """
    renderable = set()
    for path in sources:
        if "OntologyManager" in path.name or "OntologyRelease" in path.name:
            continue  # authoring surfaces, not data rendering
        text = path.read_text(encoding="utf-8", errors="ignore")
        for base_type in SEMANTIC_BASE_TYPES:
            patterns = (
                f'=== "{base_type}"', f'== "{base_type}"',
                f'case "{base_type}"', f'["{base_type}"]', f'"{base_type}":',
            )
            if any(pattern in text for pattern in patterns):
                renderable.add(base_type)
    return sorted(renderable)


def ontology_type_coupling(sources: List[Path]) -> Dict[str, int]:
    """Concrete object-type identifiers appearing in UI source.

    Each occurrence is a place where a new object type is invisible until
    someone edits the front end.
    """
    # snake_case identifiers used where an object type id is expected.
    patterns = (
        re.compile(r'objectTypeId\s*[=:]\s*"([a-z][a-z0-9_]{2,})"'),
        re.compile(r'object_type_id"\s*:\s*"([a-z][a-z0-9_]{2,})"'),
        re.compile(r'objectType\s*===\s*"([a-z][a-z0-9_]{2,})"'),
    )
    hits: Dict[str, int] = {}
    for path in sources:
        text = path.read_text(encoding="utf-8", errors="ignore")
        for pattern in patterns:
            for match in pattern.findall(text):
                key = f"{path.relative_to(REPO_ROOT).as_posix()}:{match}"
                hits[key] = hits.get(key, 0) + 1
    return hits


def interfaces_configured() -> bool:
    source = ONTOLOGY_CORE.read_text(encoding="utf-8")
    return '"interfaces": {"summary": {"configured": False}' not in source


def measure() -> Dict[str, Any]:
    sources = ui_sources()
    declared = declared_base_types()
    renderable = renderable_base_types(sources)
    coupling = ontology_type_coupling(sources)
    return {
        "declared_base_types": len(declared),
        "semantic_base_types": len(SEMANTIC_BASE_TYPES),
        "renderable_base_types": len(renderable),
        "renderable_base_type_names": renderable,
        "unrendered_semantic_types": sorted(set(SEMANTIC_BASE_TYPES) - set(renderable)),
        "ontology_type_coupling": sum(coupling.values()),
        "ontology_type_coupling_sites": sorted(coupling),
        "interfaces_configured": interfaces_configured(),
        "ui_source_files": len(sources),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--set-baseline", action="store_true")
    args = parser.parse_args()

    reading = measure()
    print("Extensibility audit\n")
    print(f"  declared property base types      {reading['declared_base_types']}")
    print(f"  semantic types the UI can render  {reading['renderable_base_types']}"
          f" of {reading['semantic_base_types']}")
    print(f"  interfaces configured             {reading['interfaces_configured']}")
    print(f"  concrete object-type couplings    {reading['ontology_type_coupling']}")
    print(f"  UI source files scanned           {reading['ui_source_files']}")
    if reading["unrendered_semantic_types"]:
        print("\n  Types the ontology declares and the UI renders as plain text:")
        for name in reading["unrendered_semantic_types"]:
            print(f"    - {name}")
    for site in reading["ontology_type_coupling_sites"]:
        print(f"  coupled: {site}")

    if args.set_baseline:
        BASELINE.write_text(json.dumps({
            "renderable_base_types_floor": reading["renderable_base_types"],
            "ontology_type_coupling_ceiling": reading["ontology_type_coupling"],
            "note": "Ratchets. Renderable types may rise; coupling may fall. Never the reverse.",
        }, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(f"\nBaseline set: renderable floor {reading['renderable_base_types']}, "
              f"coupling ceiling {reading['ontology_type_coupling']}.")
        return 0

    if not BASELINE.exists():
        print("\nNo baseline recorded. Run with --set-baseline to start the ratchets.")
        return 0
    baseline = json.loads(BASELINE.read_text(encoding="utf-8"))
    floor = baseline["renderable_base_types_floor"]
    ceiling = baseline["ontology_type_coupling_ceiling"]
    broken = []
    if reading["renderable_base_types"] < floor:
        broken.append(f"renderable base types fell to {reading['renderable_base_types']} "
                      f"below floor {floor}")
    if reading["ontology_type_coupling"] > ceiling:
        broken.append(f"object-type coupling rose to {reading['ontology_type_coupling']} "
                      f"above ceiling {ceiling}")
    if broken:
        print("\nRATCHET BROKEN:")
        for message in broken:
            print(f"  {message}")
        print("A new object type now costs more UI work than it did before.")
        return 1
    print(f"\nRatchets held: renderable >= {floor}, coupling <= {ceiling}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

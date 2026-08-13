"""Static release-contract checks for the PostgreSQL ontology benchmark."""

from pathlib import Path


root = Path(__file__).resolve().parent
source = (root / "benchmark_ontology_scale_postgres.py").read_text(encoding="utf-8")
workflow = (root.parent / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")

for required in (
    "REFERENCE_OBJECTS = 10_000_000",
    "REFERENCE_LINKS = 50_000_000",
    'ONTOLOGY_SCALE_PROFILE", "smoke"',
    "OBJECT_P95_LIMIT_MS",
    "GRAPH_P95_LIMIT_MS",
    "EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)",
    "reference_scale_achieved",
    "ONTOLOGY_SCALE_REUSE_EXISTING",
    "Reuse fixture count mismatch",
    "object_index_names",
    "graph_index_names",
):
    assert required in source, required

assert "benchmark_ontology_scale_postgres.py" in workflow

# Gate evidence must exist and must be reference-only. CI runs the smoke profile
# at a hundredth of the scale on every push; if that emitted, it would overwrite
# a genuine reference PASS with a FAIL and the gate could never hold.
assert 'if PROFILE == "reference":' in source, "gate evidence is not guarded by profile"
gate_block = source.split('if PROFILE == "reference":', 1)[1]
assert "write_evidence(" in gate_block, "write_evidence is outside the reference guard"
assert '"ontology_scale"' in gate_block, "gate id is not recorded"
for threshold in ("objects_min", "links_min", "object_lookup_p95_ms_max",
                  "graph_two_hop_p95_ms_max"):
    assert threshold in gate_block, threshold

print("Ontology scale benchmark contract verified: smoke CI and strict reference profiles "
      "are wired, and gate evidence is reference-only.")

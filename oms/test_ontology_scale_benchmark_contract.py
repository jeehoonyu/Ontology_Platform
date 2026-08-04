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
print("Ontology scale benchmark contract verified: smoke CI and strict reference profiles are wired.")

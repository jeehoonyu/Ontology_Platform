"""Static release-contract checks for the ontology mixed workload benchmark."""

from pathlib import Path


root = Path(__file__).resolve().parent
source = (root / "benchmark_ontology_mixed_workload_postgres.py").read_text(encoding="utf-8")
workflow = (root.parent / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")

for required in (
    "REFERENCE_OBJECTS = 10_000_000",
    "REFERENCE_LINKS = 50_000_000",
    'ONTOLOGY_MIXED_PROFILE", "smoke"',
    "READ_P95_LIMIT_MS",
    "WRITE_P95_LIMIT_MS",
    "MIN_WRITE_THROUGHPUT",
    '"status": "FAIL" if gate_failures else "PASS"',
    '"gate_failures": gate_failures',
    '"run_id": RUN_ID',
    "FOR UPDATE",
    "object_change_events",
    "intentional rollback probe",
    "engine.dispose()",
    "indexed_plan_after_mutation",
    "reference_scale_achieved",
):
    assert required in source, required

assert "benchmark_ontology_mixed_workload_postgres.py" in workflow
print("Ontology mixed workload benchmark contract verified: CI smoke and strict reference gates are wired.")
